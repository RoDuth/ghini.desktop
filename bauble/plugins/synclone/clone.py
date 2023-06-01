# Copyright 2023 Ross Demuth <rossdemuth123@gmail.com>
#
# This file is part of ghini.desktop.
#
# ghini.desktop is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# ghini.desktop is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with ghini.desktop. If not, see <http://www.gnu.org/licenses/>.
#
# csv import/export
#
# Description: have to name this module csv_ in order to avoid conflict
# with the system csv module
#
"""
Clone the current database to another connection.
"""

from typing import Generator
import logging
logger = logging.getLogger(__name__)

from gi.repository import Gtk

from sqlalchemy import func, select, create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

import bauble
from bauble import db
from bauble import utils
from bauble import pluginmgr
from bauble import task
from bauble import pb_set_fraction


class DBCloner:
    """Make a clone of the current database."""

    def __init__(self):
        self.__cancel: bool = False
        self.uri: str | None = None
        self._clone_engine: Engine | None = None

    def start(self, uri: str | None = None):
        """start the clone process as a task.

        :param uri: address to the database to clone to.
        """
        if uri:
            self.uri = uri
        else:
            self.uri = self._get_uri()

        if self.uri:
            task.clear_messages()
            task.queue(self.run())

    @staticmethod
    def _get_uri() -> None | str:
        """Ask the user for a database connection to clone into."""
        msg = _('<b>Select a database connection to clone the contents of\n'
                'the current database to.</b>')
        uri = None
        _name, uri = bauble.connmgr.start_connection_manager(msg)
        logger.debug('selected uri = %s', uri)

        if str(db.engine.url) == uri:
            msg = _('Can not clone to the same database.')
            utils.message_dialog(msg, Gtk.MessageType.ERROR)
            logger.debug('can not clone, uri is same as current')
            return None

        return uri

    @property
    def clone_engine(self) -> Engine:
        """Provides an SQLAlchemy database engine."""
        if not self._clone_engine:
            if self.uri.startswith('mssql'):
                # mssql fails on large inserts and is slow without
                # fast_executemany
                self._clone_engine = create_engine(self.uri,
                                                   fast_executemany=True)
            else:
                self._clone_engine = create_engine(self.uri)
        return self._clone_engine

    def __del__(self) -> None:
        """Dispose of the clone_engine."""
        if self._clone_engine:
            self._clone_engine.dispose()

    def drop_create_tables(self) -> None:
        """Drop all tables on the clone then recreate them."""
        with self.clone_engine.begin() as clone_conn:
            db.metadata.drop_all(bind=clone_conn,
                                 tables=db.metadata.tables.values())
            # recreate
            for table in db.metadata.sorted_tables:
                table.create(bind=clone_conn)

    @staticmethod
    def get_line_count() -> int:
        """Return the total number of rows in all tables for the current
        database
        """
        total_lines: int = 0
        for table in db.metadata.tables.values():
            stmt = select(func.count()).select_from(table)
            with db.engine.begin() as main_conn:
                total_lines += main_conn.execute(stmt).scalar()
        return total_lines

    def run(self) -> Generator:
        """A generator method for cloning the database."""
        self.drop_create_tables()
        total_lines = self.get_line_count()

        five_percent = int(total_lines / 20) or 1
        steps_so_far = 0
        # how many rows to insert at a time
        update_every = 127

        with (db.engine.begin() as main_conn,
              self.clone_engine.begin() as clone_conn):

            for table in db.metadata.sorted_tables:
                if table.name == 'to_sync':
                    continue
                if self.__cancel:
                    logger.debug('cancelling...')
                    return

                msg = _('Cloning %(table)s table') % {'table': table.name}
                logger.info(msg)
                task.set_message(msg)
                yield
                values = []
                logger.debug('start transaction')
                try:
                    for row in main_conn.execute(table.select()):
                        values.append(dict(row))

                        steps_so_far += 1
                        if steps_so_far % update_every == 0:
                            # NOTE used in test...
                            logger.info('adding %s rows to clone',
                                        update_every)
                            clone_conn.execute(table.insert(), values)
                            values.clear()

                        if steps_so_far % five_percent == 0:
                            fraction = steps_so_far / total_lines
                            pb_set_fraction(fraction)
                            yield

                    if values:
                        # mop up any leftovers
                        logger.info('adding last %s rows', len(values))
                        clone_conn.execute(table.insert(), values)
                        values.clear()
                except SQLAlchemyError as e:
                    self.__cancel = True
                    logger.debug('%s(%s)', type(e).__name__, e)
                    msg = (_('Error cloning.\n\n%s') %
                           utils.xml_safe(e))
                    utils.message_details_dialog(msg, str(e),
                                                 Gtk.MessageType.ERROR)
        self._record_clone_point()

    def _record_clone_point(self) -> None:
        """Record the last history id at the point of the clone in the cloned
        database.
        """
        # using core sqlalchemy for 2 reasons: its easier & wont record history
        with self.clone_engine.begin() as clone_conn:
            # record the point this clone was created
            history_table = db.History.__table__
            last_hist_id = clone_conn.execute(
                select(func.max(history_table.c.id))
            ).scalar()
            logger.debug('last history id = %s', last_hist_id)

            if not last_hist_id:
                return

            meta_table = bauble.meta.BaubleMeta.__table__
            stmt = (select(meta_table.c.value)
                    .where(meta_table.c.name == 'clone_history_id'))

            if clone_conn.execute(stmt).scalar():
                stmt = (meta_table.update()
                        .where(meta_table.c.name == 'clone_history_id'))
            else:
                stmt = meta_table.insert()

            stmt = stmt.values({'name': 'clone_history_id',
                                'value': last_hist_id})
            logger.debug(stmt)
            clone_conn.execute(stmt)


# pylint: disable=too-few-public-methods
class DBCloneTool(pluginmgr.Tool):
    category = _('Sync or clone')
    label = _('Clone')

    @classmethod
    def start(cls) -> None:
        msg = _('Cloning will destroy any existing data in the clone '
                'database.\n\n<b>CAUTION! only proceed if you know what you '
                'are doing</b>.\n\n<i>Would you like to continue?</i>')
        if utils.yes_no_dialog(msg, yes_delay=2):
            cloner = DBCloner()
            cloner.start()
            bauble.command_handler('home', None)
