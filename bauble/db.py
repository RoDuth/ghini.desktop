# Copyright 2005-2010 Brett Adams <brett@belizebotanic.org>
# Copyright 2015-2017 Mario Frasca <mario@anche.no>.
# Copyright 2017 Jardín Botánico de Quito
# Copyright 2018 Ilja Everilä
# Copyright 2021-2025 Ross Demuth <rossdemuth123@gmail.com>
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
"""
Database connection and associated.
"""

import datetime
import json
import logging
import os
import re
from collections.abc import Callable
from collections.abc import Sequence
from dataclasses import dataclass
from typing import cast

logger = logging.getLogger(__name__)

import sqlalchemy as sa
from gi.repository import Gtk
from sqlalchemy import event
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session as SASession
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import object_session
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm import synonym as sa_synonym
from sqlalchemy.orm.attributes import get_history
from sqlalchemy.orm.exc import MultipleResultsFound

from bauble import btypes as types
from bauble import error
from bauble import utils
from bauble.i18n import _


def sqlalchemy_debug(verbose):
    if verbose:
        logging.getLogger("sqlalchemy.engine").setLevel(logging.INFO)
        logging.getLogger("sqlalchemy.orm.unitofwork").setLevel(logging.DEBUG)
    else:
        logging.getLogger("sqlalchemy.engine").setLevel(logging.WARN)
        logging.getLogger("sqlalchemy.orm.unitofwork").setLevel(logging.WARN)


SQLALCHEMY_DEBUG = False
if os.environ.get("BAUBLE_SQLA_DEBUG") == "True":
    SQLALCHEMY_DEBUG = True

sqlalchemy_debug(SQLALCHEMY_DEBUG)


def natsort(attr, obj):
    """Return the naturally sorted list of the object attribute

    meant to be curried.  the main role of this function is to invert
    the order in which the function getattr receives its arguments.

    attr is in the form <attribute> but can also specify a path from the
    object to the attribute, like <a1>.<a2>.<a3>, in which case each
    step should return a single database object until the last step
    where the result should be a list of objects.

    e.g.:
    from functools import partial
    partial(natsort, 'accessions')(species)
    partial(natsort, 'species.accessions')(vern_name)
    """
    jumps = attr.split(".")
    for atr in jumps:
        obj = getattr(obj, atr)
    return sorted(obj, key=utils.natsort_key)


def get_active_children(
    children: Callable[["Domain"], Sequence["Domain"]] | str,
    obj: "Domain",
) -> Sequence["Domain"]:
    """Return only active children of obj if the 'exclude_inactive' pref is
    set True else return all children.
    """
    kids = children(obj) if callable(children) else getattr(obj, children)
    # avoid circular refs
    from bauble import prefs

    if prefs.prefs.get(prefs.exclude_inactive_pref):
        return [i for i in kids if getattr(i, "active", True)]
    return kids


engine: sa.engine.Engine | None = None
"""A :class:`sqlalchemy.engine.base.Engine` used as the default
connection to the database.
"""


_Session: type[SASession] | None = None
"""``bauble.db._Session`` is created after the database has been opened with
:func:``bauble.db.open_conn()``.

It is preferable to use ``bauble.db.Session``.
"""

DBase = declarative_base()


def Session() -> SASession:  # pylint: disable=invalid-name
    """For use when you need to do ORM based activities on a bauble database.
    To create a new Session use::

        session = Session()

    When you are finished with the session be sure to close the session
    with ``session.close()``. Failure to close sessions can lead to database
    deadlocks.

    Or, use it as a context manager to ensure it is closed after use, i.e.::

        with Session() as session:
            ...

    :raises DatabaseError: if no database is connected.
    """
    if _Session:
        return _Session()  # pylint: disable=not-callable
    raise error.DatabaseError(
        "No session available, not currently connected to a database"
    )


class Base(DBase):
    """All tables/mappers which use the SQLAlchemy declarative plugin for
    declaring tables and mappers should derive from this class.
    """

    __abstract__ = True

    __tablename__: str

    id: int = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
    # mypy when run on whole code base does not like datetime.datetime here
    # unless cast
    _created: datetime.datetime = cast(
        datetime.datetime,
        sa.Column(
            types.DateTime(timezone=True),
            default=sa.func.now(),
        ),
    )
    _last_updated: datetime.datetime = cast(
        datetime.datetime,
        sa.Column(
            types.DateTime(timezone=True),
            default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )


@dataclass
class TopLevelCount:
    families: int
    genera: int
    species: int
    accessions: int
    plants: int
    living: int
    locations: int
    sources: int

    def __str__(self) -> str:
        return ", ".join(
            f"{k}: {v}"
            for k, v in {
                _("Families"): self.families,
                _("Genera"): self.genera,
                _("Species"): self.species,
                _("Accessions"): self.accessions,
                _("Plantings"): self.plants,
                _("Living plants"): self.living or 0,
                _("Locations"): self.locations,
                _("Sources"): self.sources,
            }.items()
        )


class Domain(Base):
    """Domains are a subset of tables that contain extra functionality as
    expected for SearchView etc..

    Any tables that are expected to be displayed in SearchView (and hence
    available in searches, etc.) should derive from this class.
    """

    __abstract__ = True

    @classmethod
    def top_level_count(
        cls,
        ids: list[int],
        exclude_inactive: bool = False,  # pylint: disable=unused-argument
    ) -> TopLevelCount | str:
        return f"{cls.__name__.replace('y', 'ie')}s: {len(ids)}"

    def search_view_markup_pair(self) -> tuple[str, str]:
        return utils.xml_safe(str(self)), type(self).__name__

    def has_children(self) -> bool:
        raise NotImplementedError

    def count_children(self) -> int:
        raise NotImplementedError


@event.listens_for(Base, "before_update", propagate=True)
def before_update(_mapper, _connection, instance):
    if object_session(instance).is_modified(
        instance, include_collections=False
    ):
        # capture previous value
        # pylint: disable=protected-access
        instance._previously_updated_ = instance._last_updated


@event.listens_for(Base, "after_update", propagate=True)
def after_update(mapper, connection, instance):
    if object_session(instance).is_modified(
        instance, include_collections=False
    ):
        History.add("update", mapper, connection, instance)


@event.listens_for(Base, "after_insert", propagate=True)
def after_insert(mapper, connection, instance):
    History.add("insert", mapper, connection, instance)


@event.listens_for(Base, "before_delete", propagate=True)
def before_delete(_mapper, _connection, instance):
    # load the deferred column before deleting so it is available after.
    # hasattr is enough to trigger load.
    hasattr(instance, "geojson")


@event.listens_for(Base, "after_delete", propagate=True)
def after_delete(mapper, connection, instance):
    # NOTE these delete events do NOT WORK for session.query(...).delete()
    # better to use session.delete(qry_obj)
    History.add("delete", mapper, connection, instance)


metadata = Base.metadata
"""The default metadata for all tables.

An instance of :class:`sqlalchemy.schema.Metadata`
"""

HistoryBase = declarative_base(metadata=metadata)


class History(HistoryBase):
    """
    The history table records every change made to every table that inherits
    from :ref:`Base`

    :Table name: history

    :Columns:
      id: :class:`sqlalchemy.types.Integer`
        A unique identifier.
      table_name: :class:`sqlalchemy.types.String`
        The name of the table the change was made on.
      table_id: :class:`sqlalchemy.types.Integer`
        The id in the table of the row that was changed.
      values: :class:`sqlalchemy.types.Text`
        The changed values.
      operation: :class:`sqlalchemy.types.String`
        The type of change.  This is usually one of insert, update or delete.
      user: :class:`btypes.TruncatedString`
        The name of the user who made the change.
      timestamp: :class:`sqlalchemy.types.DateTime`
        When the change was made.
    """

    __tablename__ = "history"
    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
    table_name = sa.Column(sa.String(32), nullable=False)
    table_id = sa.Column(sa.Integer, nullable=False, autoincrement=False)
    values = sa.Column(types.JSON(), nullable=False)
    operation = sa.Column(sa.String(8), nullable=False)
    user = sa.Column(types.TruncatedString(64))
    timestamp = sa.Column(types.DateTime, nullable=False)

    history_revert_callbacks: list[Callable[[sa.Table], None]] = []

    @staticmethod
    def _val(val, type_):
        # need to convert string date values to there datetime value first to
        # ensure the same string format in output (i.e. the string can take
        # many formats)
        if isinstance(val, str) and str(type_) in ["DATE", "DATETIME"]:
            val = type_.process_bind_param(val, None)
        if isinstance(val, datetime.datetime):
            # ensure local time for comparison
            return str(val.astimezone())
        if isinstance(val, datetime.date):
            return str(val)
        return val

    @classmethod
    def add(cls, operation, mapper, connection, instance):
        """Add a new entry to the history table.

        NOTE: if you wish connection.execute changes to be recorded in the
        History table (i.e. within event.listens_for) you will need to add them
        yourself via the `event_add` method.
        """
        # XXX logging here can cause test_get_create_or_update to fail when run
        # seperately to the whole test suite (??)
        # logger.debug('adding history, operation: %s instance: %s', operation,
        #              instance)

        row = {}
        has_updates = False
        for column in mapper.local_table.c:
            if operation == "update":
                if column.name == "_last_updated" and hasattr(
                    instance, "_previously_updated_"
                ):
                    # pylint: disable=protected-access
                    values = [
                        cls._val(instance._last_updated, column.type),
                        cls._val(instance._previously_updated_, column.type),
                    ]
                    if len(values) == 1 or len({str(i) for i in values}) > 1:
                        # don't set has_updates to avoid pointless entries
                        # where no other field has changed.
                        row[column.name] = values
                        continue

                history = get_history(instance, column.name)
                if history.has_changes():
                    values = [cls._val(i, column.type) for i in history.sum()]
                    # string values on datetimes can return has_changes() when
                    # they are actually equal
                    # NOTE just incase let through unrefreshed updates (i.e.
                    # len(values) == 1) or we get no record at all, this should
                    # never happen (only happens when committing multiple
                    # changes in the one session without refreshing)
                    if len(values) == 1 or len({str(i) for i in values}) > 1:
                        has_updates = True
                        row[column.name] = values
                        continue

            val = cls._val(getattr(instance, column.name), column.type)
            row[column.name] = val

        if operation == "update" and not has_updates:
            # don't commit if no changes
            # NOTE adding a species.synonym can cause a pointless species entry
            logger.debug("%s update appears to contain no changes", instance)
            return

        table = cls.__table__
        user = current_user()
        stmt = table.insert(
            {
                "table_name": mapper.local_table.name,
                "table_id": instance.id,
                "values": row,
                "operation": operation,
                "user": user,
                "timestamp": utils.utcnow_naive(),
            }
        )
        connection.execute(stmt)

    @classmethod
    def event_add(
        cls, operation, table, connection, instance, commit_user=None, **kwargs
    ):
        """Add an extra entry to the history table.

        This version accepts the instance in its state before changes with any
        changes provided as kwargs.  Intended for use in `event.listens_for`
        where a change has been made via `connection.execute` and hence not
        triggered the usual history event handlers.

        NOTE: for updates kwarg values are assumed to be actual changes, make
            sure before using event_add (e.g. datetime entries as strings)
        """
        if operation == "update" and not kwargs:
            # don't commit if no changes
            # NOTE can result from sync
            logger.debug("%s update appears to contain no changes", instance)
            return

        user = commit_user or current_user()

        values = {}
        for column in table.c:
            if operation == "update" and column.name in kwargs:
                values[column.name] = [
                    cls._val(kwargs[column.name], column.type),
                    cls._val(getattr(instance, column.name), column.type),
                ]
                continue

            values[column.name] = cls._val(
                getattr(instance, column.name), column.type
            )
        history = cls.__table__
        stmt = history.insert(
            {
                "table_name": table.name,
                "table_id": instance.id,
                "values": values,
                "operation": operation,
                "user": user,
                "timestamp": utils.utcnow_naive(),
            }
        )
        connection.execute(stmt)

    @classmethod
    def revert_to(cls, id_):
        """Revert history to the history line with id."""
        logger.debug("reverting to id: %s", id_)
        session = Session()
        rows = session.query(cls).filter(cls.id >= id_).order_by(cls.id.desc())
        session.close()
        with engine.begin() as connection:
            for row in rows:
                table = metadata.tables[row.table_name]
                if row.operation == "insert":
                    stmt = table.delete().where(table.c.id == row.table_id)
                elif row.operation == "delete":
                    stmt = table.insert().values(**row.values)
                elif row.operation == "update":
                    # an insert and update in the one flush/commit can create a
                    # scenario where history.sum() stores a single item list
                    # (where the second entry would normally be None.)  Best to
                    # avoid this situation altogether but have including the
                    # len check here as a boots and braces approach
                    values = {
                        k: v[1] if len(v) == 2 else None
                        for k, v in row.values.items()
                        if isinstance(v, list)
                    }
                    stmt = (
                        table.update()
                        .where(table.c.id == row.table_id)
                        .values(**values)
                    )
                logger.debug("history revert values: %s", row.values)
                logger.debug("%s history revert stmt: %s", row.operation, stmt)
                connection.execute(stmt)
                for callback in cls.history_revert_callbacks:
                    callback(table)
                table = cls.__table__
                stmt = table.delete().where(table.c.id == row.id)
                connection.execute(stmt)


@event.listens_for(sa.engine.Engine, "connect")
def _sqlite_fk_pragma(dbapi_connection, _connection_record):
    """Enable foregin_key constraints on sqlite connections."""
    from sqlite3 import Connection

    if isinstance(dbapi_connection, Connection):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON;")
        cursor.close()


def open_conn(uri, verify=True, show_error_dialogs=False, poolclass=None):
    """Open a database connection.  This function sets bauble.db.engine to
    the opened engined.

    Return bauble.db.engine if successful else returns None and
    bauble.db.engine remains unchanged.

    :param uri: The URI of the database to open.
    :type uri: str

    :param verify: Where the database we connect to should be verified
        as one created by Ghini.  This flag is used mostly for
        testing.
    :type verify: bool

    :param show_error_dialogs: A flag to indicate whether the error
        dialogs should be displayed.  This is used mostly for testing.
    :type show_error_dialogs: bool
    :param poolclass: the poolclass to use, if left as None sqlalchemy default
        is used. Used in testing.
    """

    # ** WARNING: this can print your passwd
    # logger.debug('db.open(%s)', uri)
    new_engine = None

    connect_args = {}
    if uri.startswith("sqlite"):
        logger.debug("sqlite, setting check_same_thread to False")
        # avoid sqlite thread errors
        connect_args = {"check_same_thread": False}

    new_engine = sa.create_engine(
        uri,
        echo=SQLALCHEMY_DEBUG,
        connect_args=connect_args,
        poolclass=poolclass,
        implicit_returning=False,
    )

    new_engine.connect().close()  # make sure we can connect

    def _bind():
        """bind metadata to engine and create sessionmaker"""
        global _Session, engine
        engine = new_engine
        metadata.bind = engine  # make engine implicit for metadata

        # autoflush=False required or can not put an empty object into the
        # session (as is done in the editors), will get NOT NULL, etc. errors
        _Session = sessionmaker(bind=engine, autoflush=False)

    if new_engine is not None and not verify:
        _bind()
        return engine

    if new_engine is None:
        return None

    verify_connection(new_engine, show_error_dialogs)
    _bind()
    return engine


def create(import_defaults=True):
    """Create new database at the current connection

    :param import_defaults: A flag that is passed to each plugins
        install() method to indicate where it should import its
        default data.  This is mainly used for testing.  The default
        value is True
    :type import_defaults: bool

    """

    logger.debug("entered db.create()")
    if not engine:
        raise ValueError("engine is None, not connected to a database")
    import bauble
    from bauble import meta
    from bauble import pluginmgr

    connection = engine.connect()
    transaction = connection.begin()
    try:
        metadata.drop_all(bind=connection, checkfirst=True)
        metadata.create_all(bind=connection)

        # fill in the bauble meta table and install all the plugins
        meta_table = meta.BaubleMeta.__table__
        (
            meta_table.insert(bind=connection)
            .execute(name=meta.VERSION_KEY, value=str(bauble.version))
            .close()
        )
        from dateutil.tz import tzlocal

        (
            meta_table.insert(bind=connection)
            .execute(
                name=meta.CREATED_KEY,
                value=str(datetime.datetime.now(tz=tzlocal())),
            )
            .close()
        )
    except (GeneratorExit, Exception) as e:
        # this is here in case the main windows is closed in the middle
        # of a task
        # UPDATE 2009.06.18: i'm not sure if this is still relevant since we
        # switched the task system to use fibra...but it doesn't hurt
        # having it here until we can make sure
        logger.warning("bauble.db.create(): %s(%s)", type(e).__name__, e)
        transaction.rollback()
        raise
    else:
        transaction.commit()
    finally:
        connection.close()

    connection = engine.connect()
    transaction = connection.begin()
    try:
        pluginmgr.install("all", import_defaults, force=True)
    except (GeneratorExit, Exception) as e:
        logger.warning("bauble.db.create(): %s(%s)", type(e).__name__, e)
        transaction.rollback()
        raise
    else:
        transaction.commit()
    finally:
        connection.close()

    connection = engine.connect()
    transaction = connection.begin()
    try:
        utils.geo.install_default_prjs()
    except (GeneratorExit, Exception) as e:
        logger.warning("bauble.db.create(): %s(%s)", type(e).__name__, e)
        transaction.rollback()
        raise
    else:
        transaction.commit()
    finally:
        connection.close()


def verify_connection(new_engine, show_error_dialogs=False):
    """Test whether a connection to an engine is a valid database.

    This method will raise an error for the first problem it finds with the
    database.

    :param new_engine: the engine to test
    :type new_engine: :class:`sqlalchemy.engine.Engine`
    :param show_error_dialogs: flag for whether or not to show message
        dialogs detailing the error, default=False
    :type show_error_dialogs: bool
    """
    logger.debug("entered verify_connection(%s)", show_error_dialogs)
    import bauble

    if show_error_dialogs:
        try:
            return verify_connection(new_engine, False)
        except error.EmptyDatabaseError as e:
            logger.info("%s(%s)", type(e).__name__, e)
            msg = _("The database you have connected to is empty.")
            utils.message_dialog(msg, Gtk.MessageType.ERROR)
            raise
        except error.MetaTableError as e:
            logger.info("%s(%s)", type(e).__name__, e)
            msg = _(
                "The database you have connected to does not have the "
                "bauble meta table.  This usually means that the database "
                "is either corrupt or it was created with an old version "
                "of Ghini"
            )
            utils.message_dialog(msg, Gtk.MessageType.ERROR)
            raise
        except error.TimestampError as e:
            logger.info("%s(%s)", type(e).__name__, e)
            msg = _(
                "The database you have connected to does not have a "
                "timestamp for when it was created. This usually means "
                "that there was a problem when you created the "
                "database or the database you connected to wasn't "
                "created with Ghini."
            )
            utils.message_dialog(msg, Gtk.MessageType.ERROR)
            raise
        except error.VersionError as e:
            logger.info("%s(%s)", type(e).__name__, e)
            msg = _(
                "You are using Ghini version %(version)s while the "
                "database you have connected to was created with "
                "version %(db_version)s\n\nSome things might not work as "
                "or some of your data may become unexpectedly "
                "corrupted."
            ) % {"version": bauble.version, "db_version": str(e.version)}
            utils.message_dialog(msg, Gtk.MessageType.ERROR)
            raise

    # check if the database has any tables
    if len(sa.inspect(new_engine).get_table_names()) == 0:
        raise error.EmptyDatabaseError()

    from bauble import meta

    # check that the database we connected to has the bauble meta table
    if not sa.inspect(new_engine).has_table(meta.BaubleMeta.__tablename__):
        raise error.MetaTableError()

    from sqlalchemy.orm import sessionmaker

    # if we don't close this session before raising an exception then we
    # will probably get deadlocks....i'm not really sure why
    session = sessionmaker(bind=new_engine)()
    query = session.query  # (meta.BaubleMeta)

    # check that the database we connected to has a "created" timestamp
    # in the bauble meta table.  we're not using the value though.
    result = query(meta.BaubleMeta).filter_by(name=meta.CREATED_KEY).first()
    if not result:
        session.close()
        raise error.TimestampError()

    # check that the database we connected to has a "version" in the bauble
    # meta table and the the major and minor version are the same
    result = query(meta.BaubleMeta).filter_by(name=meta.VERSION_KEY).first()
    if not result:
        session.close()
        raise error.VersionError(None)
    try:
        major, minor, _revision = result.value.split(".")
    except Exception as e:
        session.close()
        raise error.VersionError(result.value) from e

    if major != bauble.version_tuple[0] or minor != bauble.version_tuple[1]:
        session.close()
        raise error.VersionError(result.value)

    session.close()
    return True


def make_note_class(name, cls_type="note", extra_columns=None):
    """Dynamically create a related table class of the notes type.

    Current use is for notes, documents and pictures tables."""

    cls_type_name = cls_type.strip("_")
    class_name = name + cls_type_name.capitalize()
    table_name = name.lower() + "_" + cls_type_name

    obj_dict = {
        "__tablename__": table_name,
        "date": sa.Column(types.Date, default=sa.func.now(), nullable=False),
        "user": sa.Column(
            sa.Unicode(64), default=utils.get_user_display_name()
        ),
        "category": sa.Column(sa.Unicode(32)),
        cls_type_name: sa.Column(sa.UnicodeText, nullable=False),
        name.lower()
        + "_id": sa.Column(
            sa.Integer, sa.ForeignKey(name.lower() + ".id"), nullable=False
        ),
        name.lower(): sa.orm.relationship(
            name,
            uselist=False,
            backref=sa.orm.backref(
                cls_type + "s", cascade="all, delete-orphan"
            ),
        ),
        "owner": sa_synonym(name.lower()),
    }

    if extra_columns:
        obj_dict.update(extra_columns)

    result = type(class_name, (Base,), obj_dict)
    return result


class WithNotes:
    key_pattern = re.compile(r"{[^:]+:(.*)}")

    def __getattr__(self, name):
        """retrieve value from corresponding note(s)

        the result can be an atomic value, a list, or a dictionary.
        """

        if name.startswith("_sa"):  # _sa are internal sqlalchemy fields
            raise AttributeError(name)

        result = []
        is_dict = False
        for note in self.notes:
            if note.category is None:
                pass
            elif note.category == f"[{name}]":
                result.append(note.note)
            elif note.category.startswith(
                f"{{{name}:"
            ) and note.category.endswith("}"):
                is_dict = True
                match = self.key_pattern.match(note.category)
                key = match.group(1)
                result.append((key, note.note))
            elif note.category == f"<{name}>":
                try:
                    return json.loads(
                        re.sub(
                            r"(\w+)[ ]*(?=:)",
                            r'"\g<1>"',
                            "{" + note.note.replace(";", ",") + "}",
                        )
                    )
                except json.JSONDecodeError:
                    pass
                try:
                    return json.loads(
                        re.sub(r"(\w+)[ ]*(?=:)", r'"\g<1>"', note.note)
                    )
                except json.JSONDecodeError as e:
                    logger.debug(
                        "not parsed %s(%s), returning literal text »%s«",
                        type(e).__name__,
                        e,
                        note.note,
                    )
                    return note.note
        if result == []:
            # if nothing was found, do not break the proxy.
            raise AttributeError(name)
        if is_dict:
            return dict(result)
        return result


def class_of_object(obj):
    """Which class implements obj."""

    name = "".join(p.capitalize() for p in obj.split("_"))
    cls = globals().get(name)
    if cls is None:
        from bauble import pluginmgr

        cls = pluginmgr.provided.get(name)
    return cls


def get_related_class(model, path):
    """Follow the path from the model class provided to get the related table's
    class.

    :param model: sqlalchemy table class
    :param path: string dot seperated path to a related table

    :return: sqlalchemy table class
    """
    logger.debug("get_related_class model: %s, path: %s", model, path)
    if not path:
        return model
    relation, path = path.split(".", 1) if "." in path else (path, None)
    # synonyms
    if syn := model.__mapper__.synonyms.get(relation):
        relation = syn.name
    # association_proxy
    if local_atr := getattr(getattr(model, relation), "local_attr", None):
        relation = getattr(getattr(model, relation), "value_attr")
        local_rel = local_atr.key
        logger.debug("local_rel: %s, relation now: %s", local_rel, relation)
        model = model.__mapper__.relationships.get(local_rel).mapper.class_
    model = model.__mapper__.relationships.get(relation).mapper.class_
    return get_related_class(model, path)


def get_or_create(session, model, **kwargs):
    instance = session.query(model).filter_by(**kwargs).first()
    if instance:
        return instance
    instance = model(**kwargs)
    session.add(instance)
    return instance


def get_unique_columns(model):
    """Given a model get the unique columns.

    Agregates any `UniqueConstraint` columns set in `__table_args__`, columns
    with `unique` value set and `epithet` columns in taxanomic tables.

    Used by `get_create_or_update`.
    """
    uniq_cols = []
    if hasattr(model, "__table_args__"):
        from sqlalchemy import UniqueConstraint

        uniq_const = [
            i for i in model.__table_args__ if isinstance(i, UniqueConstraint)
        ][0]
        uniq_cols = uniq_const.columns.keys()
    # - add any joining columns (i.e. in plant we have accession_id as part
    # of the UniqueConstraint so "accession_id" would also include
    # "accession")
    uniq_joins = [i[:-3] for i in uniq_cols if i.endswith("_id")]
    uniq_cols.extend(uniq_joins)
    # - add columns with the unique attribute set
    uniq_table_cols = [
        i.key
        for i in model.__table__.columns
        if i.unique and i.key not in uniq_cols
    ]
    uniq_cols.extend(uniq_table_cols)
    # include epithet for genus and family only (will not work on species as if
    # it ends up as the only fields searched it could return a bad match)
    if model.__tablename__ in ["family", "genus"]:
        uniq_cols.append("epithet")
    logger.debug("unique columns: %s", uniq_cols)
    return uniq_cols


def get_existing(session, model, **kwargs):
    """Get an appropriate database entry given its model and some data or None.

    Does not search for an exact match, you may wish to do so first, i.e.:
    session.query(model).filter_by(**kwargs).one()

    :param session: instance of db.Session()
    :param model: sqlalchemy table class
    :param kwargs: database values
    """
    logger.debug("looking for record matching: %s", kwargs)
    # try using a primary key if one is provided
    inst = None
    for col in model.__table__.columns:
        if col.primary_key and (pkey := kwargs.get(col.key)):
            logger.debug("trying using primary key: %s", col.key)
            inst = session.query(model).get(pkey)

    # try using unique fields
    if not inst:
        unique = {}
        uniq_cols = get_unique_columns(model)
        # get the kwargs that have keys in uniq_cols and try finding a match
        for col in uniq_cols:
            if uniq_val := kwargs.get(col):
                unique[col] = uniq_val
        if unique:
            try:
                logger.debug("trying using unique columns: %s", unique)
                inst = session.query(model).filter_by(**unique).one()
            except MultipleResultsFound:
                return None
            except SQLAlchemyError as e:
                logger.debug("%s(%s)", type(e).__name__, e)
                inst = False
        else:
            logger.debug("couldn't find unique columns to use.")

    # last try, when available use uniq_props
    if not inst and hasattr(model, "uniq_props"):
        unique = {}
        for k in kwargs:
            if k in model.uniq_props:
                unique[k] = kwargs.get(k)
        if unique:
            try:
                logger.debug("trying using uniq_props columns: %s", unique)
                inst = session.query(model).filter_by(**unique).one()
            except MultipleResultsFound:
                return None
            except SQLAlchemyError as e:
                logger.debug("%s(%s)", type(e).__name__, e)
                inst = False
        else:
            logger.debug("couldn't find uniq_props columns to use.")

    return inst


def get_create_or_update(session, model, create_one_to_one=False, **kwargs):
    """get, create or update and add to the session an appropriate database
    entry given its model and some data.

    Intended for use when possibly looking to update values but unsure
    what those updates are.  It is best to provide something clearly
    identifying (i.e. a primary key or all unique fields) when updating.
    Note: when using unique fields and not a primary key it is generally not
    possible to update any unique fields, a new entry will be created instead.
    Note: will add related items to the session but not flush or commit
    anything.

    :param session: instance of db.Session()
    :param model: sqlalchemy table class
    :param create_one_to_one: bool, allow creating when MultipleResultsFound is
        likely but not likely to be an issue
    :param kwargs: database values
    """
    # first try to get an exact match and return it immediately if found
    try:
        inst = session.query(model).filter_by(**kwargs).one()
        return inst
    except MultipleResultsFound:
        # no unique entry found, abort or we risk overwriting the wrong one.
        if not create_one_to_one:
            logger.debug("Multiples found using kwargs, aborting")
            return None
    except SQLAlchemyError:
        # any other error (i.e. no result, error in the statement - can occur
        # with new data not flushed yet.)
        logger.debug("couldn't find matching object just using kwargs")

    inst = get_existing(session, model, **kwargs)
    logger.debug("get_existing returned: %s", inst)

    if (
        inst is None
        and create_one_to_one
        and getattr(model, "is_one_to_one", False)
    ):
        logger.debug("is_one_to_one = True creating")
        inst = False

    if inst is None:
        return None
    # if the above got a false result it should be safe to create a new entry
    if inst is False:
        logger.debug("creating new %s with %s", model, kwargs)
        inst = model(**kwargs)
        session.add(inst)
        return inst

    # update the columns values.
    for k, v in kwargs.items():
        val = getattr(inst, k)
        if val != v:
            logger.debug("updating %s.%s from %s to %s", inst, k, val, v)
            setattr(inst, k, v)

    return inst


class CurrentUserFunctor:
    """implement the current_user function, and allow overriding.

    invoke the current_user object as a function.
    invoke current_user.override(user_name) to set user name.
    invoke current_user.override() to reset.
    """

    def __init__(self):
        self.override_value = None

    def override(self, value=None):
        self.override_value = value

    @property
    def is_admin(self):
        """Does the current user have CREATE privilege.

        Only relevent to postgres databases, will return True for others.
        """
        # on cancel connmgr main still runs _build_menubar
        if not engine:
            return None
        if not engine.name.startswith("postgresql"):
            return True
        from psycopg2.sql import SQL
        from psycopg2.sql import Literal

        conn = engine.raw_connection()
        with conn.cursor() as cur:
            stmt = "SELECT has_database_privilege({role}, {db}, 'CREATE')"
            stmt = SQL(stmt).format(
                role=Literal(self()), db=Literal(engine.url.database)
            )
            cur.execute(stmt)
            return cur.fetchone()[0]

    def __call__(self):
        """return current user name: from database, or system"""
        if self.override_value:
            return self.override_value
        user = None
        if engine.name.startswith("postgresql"):
            with engine.connect() as conn:
                result = conn.execute("select current_user;")
                user = result.fetchone()[0]
        elif engine.name.startswith("mysql"):
            with engine.connect() as conn:
                result = conn.execute("select current_user();")
                user = result.fetchone()[0]
        elif engine.name.startswith("sqlite"):
            user = utils.get_user_display_name()
        if not user:
            logger.debug("retrieving user name from system")
            user = (
                os.getenv("USER")
                or os.getenv("USERNAME")
                or os.getenv("LOGNAME")
                or os.getenv("LNAME")
            )

        return user


current_user = CurrentUserFunctor()


def get_model_by_name(name: str) -> type[Base] | None:
    # try domains first
    for domain in Domain.__subclasses__():
        if domain.__tablename__ == name:
            return domain

    for model in Base.__subclasses__():
        # ignore Domain
        if getattr(model, "__tablename__", None) == name:
            return model

    return None
