# Copyright 2023-2024 Ross Demuth <rossdemuth123@gmail.com>
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
# pylint: disable=too-few-public-methods
"""
Sync changes from a previously cloned database.
"""
import importlib
import json
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from typing import Literal
from typing import cast

logger = logging.getLogger(__name__)

from gi.repository import Gio
from gi.repository import Gtk
from sqlalchemy import Column
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy import Table
from sqlalchemy import create_engine
from sqlalchemy import select
from sqlalchemy import update
from sqlalchemy.engine import URL
from sqlalchemy.engine import Connection
from sqlalchemy.engine import Engine
from sqlalchemy.engine import Row
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.sql import Executable
from sqlalchemy.sql import func
from sqlalchemy.sql.expression import Delete
from sqlalchemy.sql.expression import Insert
from sqlalchemy.sql.expression import Update

import bauble
from bauble import btypes as types
from bauble import command_handler
from bauble import db
from bauble import error
from bauble import meta
from bauble import pluginmgr
from bauble import prefs
from bauble import task
from bauble import utils
from bauble.connmgr import start_connection_manager
from bauble.i18n import _

from ..tag import tags_menu_manager
from .clone import DBCloner

RESPONSE_QUIT = 1
RESPONSE_SKIP = 2
RESPONSE_SKIP_RELATED = 3
RESPONSE_RESOLVE = 4


class ToSync(db.HistoryBase):
    """The to_sync table is used during synchronisation between a previously
    cloned database and the current one.  It is essentially a store for copies
    of the History entries from the cloned database since it was cloned.
    """

    __tablename__ = "to_sync"
    id = Column(Integer, primary_key=True, autoincrement=True)
    batch_number = Column(Integer, nullable=False, autoincrement=False)
    table_name = Column(String(32), nullable=False)
    table_id = Column(Integer, nullable=False, autoincrement=False)
    values = Column(types.JSON(), nullable=False)
    operation = Column(String(8), nullable=False)
    user = Column(types.TruncatedString(64))
    timestamp = Column(types.DateTime, nullable=False)

    @classmethod
    def add_batch_from_uri(cls, uri: str | URL) -> str:
        """Grabs the history entries since cloned from the cloned database."""
        if not db.engine:
            raise error.DatabaseError("Not connected to a database")

        logger.debug("adding batch form uri: %s", uri)
        clone_engine: Engine = create_engine(uri)
        batch_num_meta = meta.get_default("sync_batch_num", "1")

        if not batch_num_meta:
            raise error.DatabaseError("Not connected to a database")

        batch_num = batch_num_meta.value or ""

        history: Table = db.History.__table__
        meta_table: Table = meta.BaubleMeta.__table__
        with clone_engine.begin() as connection:
            start = connection.execute(
                select(meta_table.c.value).where(
                    meta_table.c.name == "clone_history_id"
                )
            ).scalar()
            logger.debug("start = %s", start)
            if not start:
                raise error.BaubleError(_("Does not seem to be a clone."))
            select_stmt = select(history.c).where(history.c.id > start)
            rows = connection.execute(select_stmt).all()
        clone_engine.dispose()
        logger.debug("got %s rows", len(rows))

        with db.engine.begin() as connection:
            for row in rows:
                stmt = cls.__table__.insert(
                    {
                        "batch_number": batch_num,
                        "table_name": row.table_name,
                        "table_id": row.table_id,
                        "values": row["values"],
                        "operation": row.operation,
                        "user": row.user,
                        "timestamp": func.now(),
                    }
                )
                connection.execute(stmt)
            # update the batch number
            connection.execute(
                meta_table.update()
                .where(meta_table.c.name == "sync_batch_num")
                .values({"value": str(int(batch_num) + 1)})
            )
        return batch_num

    @classmethod
    def remove_row(cls, row: Row, connection: Connection) -> None:
        logger.debug("removing row with id = %s", row.id)
        table: Table = cls.__table__
        stmt = table.delete().where(table.c.id == row.id)
        connection.execute(stmt)


class SyncRow:  # pylint: disable=too-many-instance-attributes
    """An addapter between the database changes contained in a ToSync row and
    the database itself.
    """

    def __init__(self, id_map: dict, row: Row, connection: Connection) -> None:
        self.id_map = id_map
        self.row = row
        self.connection = connection
        self.table: Table = db.metadata.tables[row.table_name]
        self.table_id: int = self.id_map.get(row.table_name, {}).get(
            row.table_id, row.table_id
        )
        self._instance: Row | None = None
        self._values: dict[str, Any] | None = None
        self.statement: Executable | Literal[""] | None = None

    @property
    def values(self) -> dict:
        """Row values as required for generating a statement for the sync and
        for adding to history.

        Note: removes `id`, `_created` and `_last_updated` so that they get
            default values.
        """
        if self._values is None:
            values: dict = self.row["values"].copy()
            del values["id"]
            del values["_created"]
            del values["_last_updated"]

            for k, v in values.items():
                if k.endswith("_id") and v:
                    foreign_key = None
                    # get first set item
                    for foreign_key in self.table.c[k].foreign_keys:
                        break

                    if foreign_key:
                        tablename = foreign_key.column.table.name
                    elif k == "obj_id" and (
                        obj_class := values.get("obj_class")
                    ):
                        # TaggedObj
                        module_str, class_str = obj_class.rsplit(".", 1)
                        module = importlib.import_module(module_str)
                        tablename = getattr(module, class_str).__tablename__
                    else:
                        continue

                    table_id_map: dict = self.id_map.get(tablename, {})

                    if isinstance(v, list):
                        new_id = [table_id_map.get(i, i) for i in v]
                    else:
                        new_id = table_id_map.get(v, v)

                    if new_id is None:
                        return None

                    values[k] = new_id
            self._values = values
        return self._values

    def _set_instance(self) -> None:
        """Set the instance as required to add history.

        For a delete or update call this before the sync, for an insert call
        this after.
        """
        self._instance = self.connection.execute(
            select(self.table.c).where(self.table.c.id == self.table_id)
        ).first()

    @property
    def instance(self) -> Row:
        if not self._instance:
            self._set_instance()

        if not self._instance:
            raise error.DatabaseError("Could not set instance")

        return self._instance

    def _get_statement(self) -> Executable | Literal[""] | None:
        """Returns an appropriate sqlalchemy Executable statement for
        synchronising this row, or an empty str if the record is to be skipped.
        """
        table_id = self.id_map.get(self.row.table_name, {}).get(
            self.row.table_id, self.row.table_id
        )
        logger.debug("table_id = %s", table_id)
        logger.debug("values = %s", self.values)

        if table_id is None or self.values is None:
            # user has selected to skip all related, this should cascade.
            id_map = self.id_map.setdefault(self.row.table_name, {})
            id_map[self.row.table_id] = None
            return ""

        stmt: Insert | Update | Delete | None
        if self.row.operation == "insert":
            logger.debug("inserting")
            stmt = self.table.insert().values(**self.values)
        elif self.row.operation == "delete":
            logger.debug("deleting")
            self._set_instance()
            stmt = self.table.delete().where(self.table.c.id == table_id)
        elif self.row.operation == "update":
            logger.debug("updating")
            self._set_instance()
            update_vals = {}
            for k, v in self.values.items():
                if isinstance(v, list):
                    update_vals[k] = v[0]

            stmt = None  # skip this record as no changes
            if update_vals:
                stmt = (
                    self.table.update()
                    .where(self.table.c.id == table_id)
                    .values(**update_vals)
                )
            self._values = update_vals

        return stmt

    def sync(self) -> None:
        """Synchronise this row.

        Raises SkipRecord when skipping,
        captures `id` value on inserts and adds them to the id_map for future
        use of related records.
        """
        logger.debug("syncing row")
        statement = self._get_statement()
        if statement == "":
            # items we are skipping because user has chosen to skip or they
            # contain no changes
            logger.debug("skipping row with id %s", self.row.id)
            raise error.SkipRecord(f"skipping record {self.row.id}")

        result = None
        if statement is not None:
            result = self.connection.execute(statement)

        if result is None or result.rowcount == 0:
            # Don't add to the history if nothing occured
            return

        if result.is_insert:
            id_ = result.inserted_primary_key[0]
            id_map = self.id_map.setdefault(self.row.table_name, {})
            id_map[self.row.table_id] = id_
            self.table_id = id_
        elif self.row.operation == "update":
            # grab the actual value of _last_updated and replace it in values
            # to pass to history
            last_update = self.connection.execute(
                select(self.table.c._last_updated).where(
                    self.table.c.id == self.table_id
                )
            ).scalar()
            if last_update != self.instance._last_updated:
                self.values["_last_updated"] = last_update

        self.add_to_history()

    def add_to_history(self) -> None:
        logger.debug("values = %s", self.values)
        db.History.event_add(
            self.row.operation,
            self.table,
            self.connection,
            self.instance,
            commit_user=self.row.user,
            **self.values,
        )


@Gtk.Template(
    filename=str(Path(__file__).resolve().parent / "resolver_window.ui")
)
class ResolverDialog(Gtk.Dialog):
    """Dialog to allow the user to try to resolve conflicts."""

    __gtype_name__ = "ResolverDialog"

    cancel_btn = cast(Gtk.Button, Gtk.Template.Child())
    quit_btn = cast(Gtk.Button, Gtk.Template.Child())
    skip_entry_btn = cast(Gtk.Button, Gtk.Template.Child())
    skip_related_btn = cast(Gtk.Button, Gtk.Template.Child())
    resolve_btn = cast(Gtk.Button, Gtk.Template.Child())
    msg_label = cast(Gtk.Label, Gtk.Template.Child())
    liststore = cast(Gtk.ListStore, Gtk.Template.Child())

    def __init__(
        self, msg: None | str = None, row: Row | None = None, **kwargs
    ) -> None:
        super().__init__(**kwargs)
        if msg is None:
            self.msg_label.set_visible(False)
        else:
            self.msg_label.set_markup(msg)

        if row:
            self.table: Table = db.metadata.tables[row.table_name]
            self.row: Row = row
        self._refresh_liststore()

    def _refresh_liststore(self) -> None:
        self.liststore.clear()
        for k, v in self.row["values"].items():
            self.liststore.append([k, str(v or "")])

    @Gtk.Template.Callback()
    def on_value_cell_edited(self, _cell, path, new_text) -> None:
        # pylint: disable=unsubscriptable-object
        logger.debug("value editied path:%s, new_text%s", path, new_text)
        column = self.table.c[self.liststore[path][0]]
        try:
            typ = column.type.python_type
        except NotImplementedError:
            typ = str
        try:
            self.row["values"][self.liststore[path][0]] = typ(new_text)
        except ValueError as e:
            logger.debug("%s(%s)", type(e).__name__, e)
            return
        self._refresh_liststore()


class DBSyncroniser:
    """Synchronise the provided rows' changes to the database capturing the id
    of any failed rows."""

    def __init__(self, rows: list[Row]):
        self.id_map: dict = {}
        self.rows = rows
        self.failed: list[int] = []

    def _open_resolver(self, row: Row, msg: None | str):
        """Offer the user an opportunity to resolve any conflicts on the fly"""
        parent = bauble.gui.window if bauble.gui else None
        start_values = row["values"].copy()
        resolver = ResolverDialog(msg=msg, row=row, transient_for=parent)
        resolver.cancel_btn.set_visible(False)

        response = resolver.run()
        resolver.destroy()
        if response == Gtk.ResponseType.DELETE_EVENT:
            # row being a tuple and not mutable can not assign, need to update
            # the dictionary in place
            row["values"].update(start_values)
        elif response == RESPONSE_QUIT:
            row["values"].update(start_values)
            self.failed.append(row.id)
        elif response == RESPONSE_SKIP_RELATED:
            row["values"].update(start_values)
            self.failed.append(row.id)
            id_map = self.id_map.setdefault(row.table_name, {})
            id_map[row.table_id] = None
        elif response == RESPONSE_SKIP:
            row["values"].update(start_values)
            self.failed.append(row.id)
        return response

    def _sync_row(self, row: Row) -> None:
        """Attempt to sync a row, if user decides to quite raises DatabaseError
        to trigger a rollback"""
        if not db.engine:
            raise error.DatabaseError("Not connected to a database")

        while True:
            with db.engine.begin() as connection:
                sync_row = SyncRow(self.id_map, row, connection)
                try:
                    sync_row.sync()
                    # remove if successfull
                    ToSync.remove_row(row, connection)
                    break
                except error.SkipRecord:
                    self.failed.append(row.id)
                    break
                except SQLAlchemyError as e:
                    logger.debug("%s(%s)", type(e).__name__, e)
                    msg = utils.xml_safe(str(e).split("\n", maxsplit=1)[0])
                    response = self._open_resolver(row, msg)
                    if response == RESPONSE_QUIT:
                        # raise exception to trigger a rollback
                        raise error.DatabaseError("Sync aborted.")
                    if response in (RESPONSE_SKIP, RESPONSE_SKIP_RELATED):
                        break
                    if response == Gtk.ResponseType.DELETE_EVENT:
                        msg = _("Would you like to abort the sync?")
                        parent = bauble.gui.window if bauble.gui else None
                        # if user selects no the record is skipped only
                        if utils.yes_no_dialog(msg=msg, parent=parent):
                            # raise exception to trigger a rollback
                            raise error.DatabaseError("Sync aborted.")

    def _sync_task(self) -> Iterator[None]:
        num_items = len(self.rows)
        five_percent = int(num_items / 20) or 1

        for done, row in enumerate(reversed(self.rows)):
            self._sync_row(row)
            if done % five_percent == 0:
                bauble.pb_set_fraction(done / num_items)
                yield

    def sync(self) -> list[int]:
        task.clear_messages()
        task.set_message(_("syncing"))
        try:
            task.queue(self._sync_task())
        except error.DatabaseError:
            pass
        task.set_message(_("sync complete"))
        if bauble.gui:
            tags_menu_manager.reset()
        return self.failed


@Gtk.Template(
    filename=str(Path(__file__).resolve().parent / "resolution_centre_view.ui")
)
class ResolutionCentreView(pluginmgr.View, Gtk.Box):
    """Show all the ToSync table rows for the user to attempt to sync them."""

    __gtype_name__ = "ResolutionView"

    liststore = cast(Gtk.ListStore, Gtk.Template.Child())
    sync_tv = cast(Gtk.TreeView, Gtk.Template.Child())
    resolve_btn = cast(Gtk.Button, Gtk.Template.Child())
    remove_selected_btn = cast(Gtk.Button, Gtk.Template.Child())
    sync_selected_btn = cast(Gtk.Button, Gtk.Template.Child())

    TVC_OBJ = 0
    TVC_BATCH = 1
    TVC_TIMESTAMP = 2
    TVC_OPERATION = 3
    TVC_USER = 4
    TVC_TABLE = 5
    TVC_USER_FRIENDLY = 6

    def __init__(self, uri: str | URL | None = None) -> None:
        logger.debug("Starting ResolutionCentreView")
        super().__init__()
        self._uri = None
        self.uri = uri  # type: ignore [assignment]
        self.last_pos: (
            tuple[Gtk.TreePath | None, Gtk.TreeViewColumn | None, int, int]
            | None
        ) = None
        self.setup_context_menu()

    @property
    def uri(self) -> URL | None:
        return self._uri

    @uri.setter
    def uri(self, uri: str | URL | None) -> None:
        if uri and isinstance(uri, URL):
            self._uri = uri
        elif uri and isinstance(uri, str):
            self._uri = make_url(uri)
        else:
            self._uri = None
        logger.debug("uri = %s", repr(self._uri))

    def setup_context_menu(self) -> None:
        menu_model = Gio.Menu()
        batch_action_name = "select_batch"
        related_action_name = "select_related"
        all_action_name = "select_all"

        if bauble.gui:
            bauble.gui.add_action(batch_action_name, self.on_select_batch)
            bauble.gui.add_action(related_action_name, self.on_select_related)
            bauble.gui.add_action(all_action_name, self.on_select_all)

        select_batch = Gio.MenuItem.new(
            _("Select batch"), f"win.{batch_action_name}"
        )
        select_related = Gio.MenuItem.new(
            _("Select related"), f"win.{related_action_name}"
        )
        select_all = Gio.MenuItem.new(
            _("Select all"), f"win.{all_action_name}"
        )
        menu_model.append_item(select_batch)
        menu_model.append_item(select_related)
        menu_model.append_item(select_all)

        self.context_menu = Gtk.Menu.new_from_model(menu_model)
        self.context_menu.attach_to_widget(self.sync_tv)

    def get_selected_rows(self) -> list[Row]:
        """Get the selected rows objects from column 0."""
        model, rows = self.sync_tv.get_selection().get_selected_rows()
        if model is None or rows is None:
            return None
        return [model[row][0] for row in rows]

    @Gtk.Template.Callback()
    def on_button_press(self, view, event) -> bool:
        """Allow multiple selection with right mouse button."""
        if event.button == 3:
            self.last_pos = view.get_path_at_pos(int(event.x), int(event.y))
            # occasionally pos will return None and can't be unpacked
            if not self.last_pos:
                return False
            path, _c, _i, _i = self.last_pos
            if not view.get_selection().path_is_selected(path):
                return False
            return True
        return False

    @Gtk.Template.Callback()
    def on_button_release(self, _view, event) -> bool:
        """Open context menu on right click"""
        if event.button != 3:
            return False
        self.context_menu.popup_at_pointer(event)
        return True

    def on_select_batch(self, *_args) -> None:
        """Context menu action to select all rows with the same batch number as
        the selected.
        """
        if self.last_pos and self.last_pos[0] is not None:
            batch_num = self.liststore.get_value(
                self.liststore.get_iter(self.last_pos[0]), self.TVC_BATCH
            )
            selection = self.sync_tv.get_selection()
            # pylint: disable=not-an-iterable
            for row in self.liststore:
                if row[self.TVC_BATCH] == batch_num:
                    selection.select_iter(row.iter)

    def on_select_related(self, *_args) -> None:
        """Context menu action to select all rows that are directly related to
        the selected.

        Uses the selected rows id value to search for foreign keys
        realtionships in other rows.
        """
        if self.last_pos and self.last_pos[0] is not None:
            obj = self.liststore.get_value(
                self.liststore.get_iter(self.last_pos[0]), self.TVC_OBJ
            )
            selection = self.sync_tv.get_selection()
            # pylint: disable=not-an-iterable
            for row in self.liststore:
                row_obj = row[self.TVC_OBJ]
                if (
                    row_obj.table_name == obj.table_name
                    and row_obj.table_id == obj.table_id
                ):
                    selection.select_iter(row.iter)
                    continue

                for k, v in row_obj["values"].items():
                    if k.endswith("_id") and v == obj.table_id:
                        table = db.metadata.tables[row_obj.table_name]
                        foreign_key = None
                        # get first set item
                        for foreign_key in table.c[k].foreign_keys:
                            break
                        if (
                            foreign_key
                            and foreign_key.column.table.name == obj.table_name
                        ):
                            selection.select_iter(row.iter)

    def on_select_all(self, *_args) -> None:
        """Context menu action to select all."""
        self.sync_tv.get_selection().select_all()

    @Gtk.Template.Callback()
    def on_resolve_btn_clicked(self, *_args) -> None:
        """Edit the a row's `values` entry."""
        if not db.engine:
            raise error.DatabaseError("Not connected to a database")

        parent = bauble.gui.window if bauble.gui else None
        row = self.get_selected_rows()[0]
        resolver = ResolverDialog(row=row, transient_for=parent)

        resolver.quit_btn.set_visible(False)
        resolver.skip_entry_btn.set_visible(False)
        resolver.skip_related_btn.set_visible(False)

        response = resolver.run()
        resolver.destroy()
        if response == RESPONSE_RESOLVE:
            logger.debug("resolving row %s", row)
            table = ToSync.__table__
            vals = {"values": row["values"]}
            stmt = update(table).where(table.c.id == row.id).values(vals)
            with db.engine.begin() as connection:
                connection.execute(stmt)
        self.update()

    @Gtk.Template.Callback()
    def on_remove_selected_btn_clicked(self, *_args) -> None:
        if not db.engine:
            raise error.DatabaseError("Not connected to a database")

        table = ToSync.__table__
        for row in self.get_selected_rows():
            with db.engine.begin() as connection:
                stmt = table.delete().where(table.c.id == row.id)
                connection.execute(stmt)
        self.update()

    @Gtk.Template.Callback()
    def on_sync_selected_btn_clicked(self, *_args) -> None:
        synchroniser = DBSyncroniser(self.get_selected_rows())
        failed = synchroniser.sync()
        logger.debug("failed: %s", failed)
        self.update()
        if failed:
            selection = self.sync_tv.get_selection()
            selection.unselect_all()
            # pylint: disable=not-an-iterable
            for row in self.liststore:
                if row[self.TVC_OBJ].id in failed:
                    selection.select_iter(row.iter)
        elif self.uri:
            msg = _(
                "Would you like to clone to the syncing database to keep "
                "them in sync?"
            )
            parent = bauble.gui.window if bauble.gui else None
            if utils.yes_no_dialog(msg=msg, parent=parent):
                logger.debug("cloning back to %s", repr(self.uri))
                cloner = DBCloner()
                cloner.start(self.uri)
                command_handler("home", None)

    @Gtk.Template.Callback()
    def on_sync_selection_changed(self, selection: Gtk.TreeSelection) -> None:
        """Update button sensitivity"""
        multi = (self.remove_selected_btn, self.sync_selected_btn)
        selected_count = selection.count_selected_rows()
        if selected_count > 1:
            for i in multi:
                i.set_sensitive(True)
            self.resolve_btn.set_sensitive(False)
        elif selected_count == 1:
            for i in multi:
                i.set_sensitive(True)
            self.resolve_btn.set_sensitive(True)
        else:
            for i in multi:
                i.set_sensitive(False)
            self.resolve_btn.set_sensitive(False)

    @staticmethod
    def _cmp_items_key(val: tuple[str, Any]) -> tuple[int, str]:
        """Sort by the key after putting id first, changes second and None
        values last.
        """
        k, v = val
        if k == "id":
            return (0, k)
        if isinstance(v, list):
            return (1, k)
        if v is None:
            return (3, k)
        return (2, k)

    def add_row(self, row: Row) -> None:
        dct = dict(row["values"])
        del dct["_created"]
        del dct["_last_updated"]

        geojson = None
        if dct.get("geojson"):
            geojson = json.dumps(row["values"].get("geojson"))
        try:
            del dct["geojson"]
        except KeyError:
            pass

        friendly = ", ".join(
            f"{k}: {repr('') if v is None else v}"
            for k, v in sorted(list(dct.items()), key=self._cmp_items_key)
        )
        frmt = prefs.prefs.get(prefs.datetime_format_pref)
        self.liststore.append(
            [
                row,
                str(row.batch_number),
                row.timestamp.strftime(frmt),
                row.operation,
                row.user,
                row.table_name,
                friendly,
                geojson,
            ]
        )

    def update(self, *args) -> None:
        if not db.engine:
            raise error.DatabaseError("Not connected to a database")

        batch_num = None
        if args and isinstance(args[0], list):
            logger.debug("args = %s", args)
            batch_num = args[0][0]
            self.uri = args[0][1]

        self.liststore.clear()

        with db.engine.begin() as connection:
            table = ToSync.__table__
            stmt = select(table).order_by(table.c.id.desc())
            rows = connection.execute(stmt).all()

        for row in rows:
            self.add_row(row)

        if batch_num:
            logger.debug("selecting batch num: %s", batch_num)
            selection = self.sync_tv.get_selection()
            # pylint: disable=not-an-iterable
            for tree_row in self.liststore:
                if tree_row[self.TVC_BATCH] == batch_num:
                    selection.select_iter(tree_row.iter)


class ResolveCommandHandler(pluginmgr.CommandHandler):
    command = "resolve"
    view: pluginmgr.View | None = None

    def get_view(self) -> pluginmgr.View:
        if self.__class__.view is None:
            self.__class__.view = ResolutionCentreView()
        return self.__class__.view

    def __call__(self, cmd, arg) -> None:
        if self.view:
            self.view.update(arg)


class DBSyncTool(pluginmgr.Tool):
    category = _("Sync or clone")
    label = _("Sync")

    @classmethod
    def start(cls) -> None:
        msg = _(
            "<b>Select a database connection to sync to the contents of\n"
            "the current database.</b>"
        )
        _name, uri = start_connection_manager(msg)
        if uri:
            # convert to URL to compare
            uri = make_url(uri)
        else:
            return

        current_uri = None
        if db.engine:
            current_uri = db.engine.url
        logger.debug("selected uri = %s", repr(uri))
        logger.debug("current uri = %s", repr(current_uri))

        if current_uri == uri:
            msg = _("Can not sync from the same database.")
            utils.message_dialog(msg, Gtk.MessageType.ERROR)
            logger.debug("can not sync, uri is same as current")
            return

        batch_num = ToSync.add_batch_from_uri(uri)

        command_handler("resolve", [batch_num, uri])


class DBResolveSyncTool(pluginmgr.Tool):
    category = _("Sync or clone")
    label = _("Resolution Centre")

    @classmethod
    def start(cls) -> None:
        command_handler("resolve", None)
