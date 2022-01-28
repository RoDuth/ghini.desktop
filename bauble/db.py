# Copyright 2005-2010 Brett Adams <brett@belizebotanic.org>
# Copyright 2015-2017 Mario Frasca <mario@anche.no>.
# Copyright 2017 Jardín Botánico de Quito
# Copyright 2018 Ilja Everilä
# Copyright 2021-2022 Ross Demuth <rossdemuth123@gmail.com>
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

import datetime
import os
import re
import json

import logging
logger = logging.getLogger(__name__)

from gi.repository import Gtk  # noqa

try:
    import sqlalchemy as sa
    from bauble import error
    parts = tuple(int(i) for i in sa.__version__.split('.')[:2])
    if parts < (0, 6):
        msg = _('This version of Ghini requires SQLAlchemy 0.6 or greater. '
                'You are using version %s. '
                'Please download and install a newer version of SQLAlchemy '
                'from http://www.sqlalchemy.org or contact your system '
                'administrator.') % '.'.join(parts)
        raise error.SQLAlchemyVersionError(msg)
except ImportError:
    msg = _('SQLAlchemy not installed. Please install SQLAlchemy from '
            'http://www.sqlalchemy.org')
    raise

from sqlalchemy import event
from sqlalchemy.orm import class_mapper
from sqlalchemy.ext.declarative import declarative_base, DeclarativeMeta
# sqla >1.4 i think will be:
# from sqlalchemy.orm import class_mapper, declarative_base
# from sqlalchemy.ext.decl_api import DeclarativeMeta

# pylint: disable=ungrouped-imports
from bauble import utils
from bauble import btypes as types
# pylint: enable=ungrouped-imports


def sqlalchemy_debug(verbose):
    if verbose:
        logging.getLogger('sqlalchemy.engine').setLevel(logging.INFO)
        logging.getLogger('sqlalchemy.orm.unitofwork').setLevel(logging.DEBUG)
    else:
        logging.getLogger('sqlalchemy.engine').setLevel(logging.WARN)
        logging.getLogger('sqlalchemy.orm.unitofwork').setLevel(logging.WARN)


SQLALCHEMY_DEBUG = False
if os.environ.get('BAUBLE_SQLA_DEBUG') == 'True':
    SQLALCHEMY_DEBUG = True
sqlalchemy_debug(SQLALCHEMY_DEBUG)


def natsort(attr, obj):
    """return the naturally sorted list of the object attribute

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
    from bauble import utils
    jumps = attr.split('.')
    for attr in jumps:
        obj = getattr(obj, attr)
    return sorted(obj, key=utils.natsort_key)


class MapperBase(DeclarativeMeta):
    """
    MapperBase adds the id, _created and _last_updated columns to all
    tables.

    In general there is no reason to use this class directly other
    than to extend it to add more default columns to all the bauble
    tables.
    """
    def __init__(cls, classname, bases, dict_):
        if '__tablename__' in dict_:
            cls.id = sa.Column('id', sa.Integer, primary_key=True,
                               autoincrement=True)
            cls._created = sa.Column('_created', types.DateTime(timezone=True),
                                     default=sa.func.now())
            cls._last_updated = sa.Column('_last_updated',
                                          types.DateTime(timezone=True),
                                          default=sa.func.now(),
                                          onupdate=sa.func.now())
        if 'top_level_count' not in dict_:
            cls.top_level_count = lambda x: {classname: 1}
        if 'search_view_markup_pair' not in dict_:
            cls.search_view_markup_pair = lambda x: (
                utils.xml_safe(str(x)),
                '(%s)' % type(x).__name__)

        super().__init__(classname, bases, dict_)


engine = None
"""A :class:`sqlalchemy.engine.base.Engine` used as the default
connection to the database.
"""


Session = None
"""
bauble.db.Session is created after the database has been opened with
:func:`bauble.db.open()`. bauble.db.Session should be used when you need
to do ORM based activities on a bauble database.  To create a new
Session use::Uncategorized

    session = bauble.db.Session()

When you are finished with the session be sure to close the session
with :func:`session.close()`. Failure to close sessions can lead to
database deadlocks, particularly when using PostgreSQL based
databases.
"""

Base = declarative_base(metaclass=MapperBase)
"""
All tables/mappers in Ghini which use the SQLAlchemy declarative
plugin for declaring tables and mappers should derive from this class.

An instance of :class:`sqlalchemy.ext.declarative.Base`
"""


def _add_to_history(operation, mapper, connection, instance):
    """
    Add a new entry to the history table.
    """
    user = current_user()

    row = {}
    for column in mapper.local_table.c:
        # skip defered geojson columns
        if column.name == 'geojson':
            continue
        row[column.name] = str(getattr(instance, column.name))
    table = History.__table__   # pylint: disable=no-member
    stmt = table.insert(dict(table_name=mapper.local_table.name,
                             table_id=instance.id, values=str(row),
                             operation=operation, user=user,
                             timestamp=datetime.datetime.utcnow()))
    connection.execute(stmt)


@event.listens_for(Base, 'after_update', propagate=True)
def after_update(mapper, connection, instance):
    _add_to_history('update', mapper, connection, instance)


@event.listens_for(Base, 'after_insert', propagate=True)
def after_insert(mapper, connection, instance):
    _add_to_history('insert', mapper, connection, instance)


@event.listens_for(Base, 'after_delete', propagate=True)
def after_delete(mapper, connection, instance):
    _add_to_history('delete', mapper, connection, instance)


metadata = Base.metadata
"""The default metadata for all Ghini tables.

An instance of :class:`sqlalchemy.schema.Metadata`
"""

HistoryBase = declarative_base(metadata=metadata)


class History(HistoryBase):
    """
    The history table records ever changed made to every table that
    inherits from :ref:`Base`

    :Table name: history

    :Columns:
      id: :class:`sqlalchemy.types.Integer`
        A unique identifier.
      table_name: :class:`sqlalchemy.types.String`
        The name of the table the change was made on.
      table_id: :class:`sqlalchemy.types.Integer`
        The id in the table of the row that was changed.
      values: :class:`sqlalchemy.types.String`
        The changed values.
      operation: :class:`sqlalchemy.types.String`
        The type of change.  This is usually one of insert, update or delete.
      user: :class:`sqlalchemy.types.String`
        The name of the user who made the change.
      timestamp: :class:`sqlalchemy.types.DateTime`
        When the change was made.
    """
    __tablename__ = 'history'
    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
    table_name = sa.Column(sa.Text, nullable=False)
    table_id = sa.Column(sa.Integer, nullable=False, autoincrement=False)
    values = sa.Column(sa.Text, nullable=False)
    operation = sa.Column(sa.Text, nullable=False)
    user = sa.Column(sa.Text)
    timestamp = sa.Column(types.DateTime, nullable=False)


def open(uri, verify=True, show_error_dialogs=False):
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
    """

    # ** WARNING: this can print your passwd
    logger.debug('db.open(%s)', uri)
    from sqlalchemy.orm import sessionmaker, scoped_session
    global engine
    new_engine = None

    # avoid sqlite thread errors
    connect_args = {}
    if uri.find('sqlite') != -1:
        # NOTE If this is causing errors consider removing it
        connect_args = {"check_same_thread": False}

    # NOTE sqla, by default, for sqlite uses SingletonThreadPool for
    # :memory: databases and NullPool for files.  For other DBs QueuePool
    # is used
    # docs states: re: SingletonThreadPool is only intended for sqlite memory
    # data, generally testing, and 'not recommended for production use'.
    new_engine = sa.create_engine(uri, echo=SQLALCHEMY_DEBUG,
                                  connect_args=connect_args,
                                  implicit_returning=False)

    # TODO: there is a problem here: the code may cause an exception, but we
    # immediately loose the 'new_engine', which should know about the
    # encoding used in the exception string.
    try:
        new_engine.connect().close()  # make sure we can connect
    except Exception:
        logger.info('about to forget about encoding of exception text.')
        raise

    def _bind():
        """bind metadata to engine and create sessionmaker """
        global Session, engine
        engine = new_engine
        metadata.bind = engine  # make engine implicit for metadata

        def temp():
            import inspect
            logger.debug('creating session %s' % str(inspect.stack()[1]))
            return scoped_session(sessionmaker(bind=engine, autoflush=False))()

        # Session = scoped_session(sessionmaker(bind=engine, autoflush=False))
        Session = temp

    if new_engine is not None and not verify:
        _bind()
        return engine

    if new_engine is None:
        return None

    verify_connection(new_engine, show_error_dialogs)
    _bind()
    return engine


def create(import_defaults=True):
    """
    Create new Ghini database at the current connection

    :param import_defaults: A flag that is passed to each plugins
        install() method to indicate where it should import its
        default data.  This is mainly used for testing.  The default
        value is True
    :type import_defaults: bool

    """

    logger.debug('entered db.create()')
    if not engine:
        raise ValueError('engine is None, not connected to a database')
    import bauble
    from bauble import meta
    from bauble import pluginmgr
    import datetime

    connection = engine.connect()
    transaction = connection.begin()
    try:
        # TODO: here we are dropping/creating all the tables in the
        # metadata whether they are in the registry or not, we should
        # really only be creating those tables from registered
        # plugins, maybe with an uninstall() method on Plugin
        metadata.drop_all(bind=connection, checkfirst=True)
        metadata.create_all(bind=connection)

        # fill in the bauble meta table and install all the plugins
        meta_table = meta.BaubleMeta.__table__
        meta_table.insert(bind=connection).\
            execute(name=meta.VERSION_KEY,
                    value=str(bauble.version)).close()
        from dateutil.tz import tzlocal
        meta_table.insert(bind=connection).\
            execute(name=meta.CREATED_KEY,
                    value=str(datetime.datetime.now(tz=tzlocal()))).close()
    except GeneratorExit as e:
        # this is here in case the main windows is closed in the middle
        # of a task
        # UPDATE 2009.06.18: i'm not sure if this is still relevant since we
        # switched the task system to use fibra...but it doesn't hurt
        # having it here until we can make sure
        logger.warning('bauble.db.create(): %s', e)
        transaction.rollback()
        raise
    except Exception as e:
        logger.warning('bauble.db.create(): %s', e)
        transaction.rollback()
        raise
    else:
        transaction.commit()
    finally:
        connection.close()

    connection = engine.connect()
    transaction = connection.begin()
    try:
        pluginmgr.install('all', import_defaults, force=True)
    except GeneratorExit as e:
        # this is here in case the main windows is closed in the middle
        # of a task
        # UPDATE 2009.06.18: i'm not sure if this is still relevant since we
        # switched the task system to use fibra...but it doesn't hurt
        # having it here until we can make sure
        logger.warning('bauble.db.create(): %s', e)
        transaction.rollback()
        raise
    except Exception as e:
        logger.warning('bauble.db.create(): %s', e)
        transaction.rollback()
        raise
    else:
        transaction.commit()
    finally:
        connection.close()


def verify_connection(engine, show_error_dialogs=False):
    """
    Test whether a connection to an engine is a valid Ghini database. This
    method will raise an error for the first problem it finds with the
    database.

    :param engine: the engine to test
    :type engine: :class:`sqlalchemy.engine.Engine`
    :param show_error_dialogs: flag for whether or not to show message
        dialogs detailing the error, default=False
    :type show_error_dialogs: bool
    """
    logger.debug('entered verify_connection(%s)' % show_error_dialogs)
    import bauble
    if show_error_dialogs:
        try:
            return verify_connection(engine, False)
        except error.EmptyDatabaseError:
            msg = _('The database you have connected to is empty.')
            utils.message_dialog(msg, Gtk.MessageType.ERROR)
            raise
        except error.MetaTableError:
            msg = _('The database you have connected to does not have the '
                    'bauble meta table.  This usually means that the database '
                    'is either corrupt or it was created with an old version '
                    'of Ghini')
            utils.message_dialog(msg, Gtk.MessageType.ERROR)
            raise
        except error.TimestampError:
            msg = _('The database you have connected to does not have a '
                    'timestamp for when it was created. This usually means '
                    'that there was a problem when you created the '
                    'database or the database you connected to wasn\'t '
                    'created with Ghini.')
            utils.message_dialog(msg, Gtk.MessageType.ERROR)
            raise
        except error.VersionError as e:
            msg = (_('You are using Ghini version %(version)s while the '
                     'database you have connected to was created with '
                     'version %(db_version)s\n\nSome things might not work as '
                     'or some of your data may become unexpectedly '
                     'corrupted.') %
                   {'version': bauble.version,
                    'db_version': '%s' % e.version})
            utils.message_dialog(msg, Gtk.MessageType.ERROR)
            raise

    # check if the database has any tables
    if len(engine.table_names()) == 0:
        raise error.EmptyDatabaseError()

    from bauble import meta
    # check that the database we connected to has the bauble meta table
    if not engine.has_table(meta.BaubleMeta.__tablename__):
        raise error.MetaTableError()

    from sqlalchemy.orm import sessionmaker
    # if we don't close this session before raising an exception then we
    # will probably get deadlocks....i'm not really sure why
    session = sessionmaker(bind=engine)()
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
        major, minor, revision = result.value.split('.')
    except Exception:
        session.close()
        raise error.VersionError(result.value)

    if major != bauble.version_tuple[0] or minor != bauble.version_tuple[1]:
        session.close()
        raise error.VersionError(result.value)

    session.close()
    return True


def make_note_class(name, compute_serializable_fields, as_dict=None,
                    retrieve=None):
    class_name = name + 'Note'
    table_name = name.lower() + '_note'

    def is_defined(self):
        return bool(self.user and self.category and self.note)

    def is_empty(self):
        return not self.user and not self.category and not self.note

    def retrieve_or_create(cls, session, keys, create=True, update=True):
        """return database object corresponding to keys
        """
        category = keys.get('category', '')

        # normally, it's one note per category, but for list values, and for
        # pictures, we can have more than one.
        if (create and (category.startswith('[') and category.endswith(']') or
                        category == '<picture>')):
            # dirty trick: making sure it's not going to be found!
            import uuid
            keys['category'] = str(uuid.uuid4())
        result = super(globals()[class_name], cls
                       ).retrieve_or_create(session, keys, create, update)
        keys['category'] = category
        if result:
            result.category = category
        return result

    def retrieve_default(cls, session, keys):
        qry = session.query(cls)
        if name.lower() in keys:
            qry = qry.join(globals()[name]).filter(
                globals()[name].code == keys[name.lower()])
        if 'date' in keys:
            qry = qry.filter(cls.date == keys['date'])
        if 'category' in keys:
            qry = qry.filter(cls.category == keys['category'])
        try:
            return qry.one()
        except:
            return None

    def as_dict_default(self):
        result = db.Serializable.as_dict(self)
        result[name.lower()] = getattr(self, name.lower()).code
        return result

    as_dict = as_dict or as_dict_default
    retrieve = retrieve or retrieve_default

    result = type(class_name, (Base, Serializable),
                  {'__tablename__': table_name,

                   'date': sa.Column(types.Date, default=sa.func.now(),
                                     nullable=False),
                   'user': sa.Column(sa.Unicode(64),
                                     default=utils.get_user_display_name()),
                   'category': sa.Column(sa.Unicode(32)),
                   'note': sa.Column(sa.UnicodeText, nullable=False),
                   name.lower() + '_id': sa.Column(
                       sa.Integer,
                       sa.ForeignKey(name.lower() + '.id'),
                       nullable=False),
                   name.lower(): sa.orm.relation(
                       name,
                       uselist=False,
                       backref=sa.orm.backref('notes',
                                              cascade='all, delete-orphan')),
                   'retrieve': classmethod(retrieve),
                   'retrieve_or_create': classmethod(retrieve_or_create),
                   'compute_serializable_fields':
                   classmethod(compute_serializable_fields),
                   'is_defined': is_defined,
                   'as_dict': as_dict,
                   }
                  )
    return result


class WithNotes:

    key_pattern = re.compile(r'{[^:]+:(.*)}')

    def __getattr__(self, name):
        """retrieve value from corresponding note(s)

        the result can be an atomic value, a list, or a dictionary.
        """

        if name.startswith('_sa'):  # _sa are internal sqlalchemy fields
            raise AttributeError(name)

        result = []
        is_dict = False
        for note in self.notes:
            if note.category is None:
                pass
            elif note.category == ('[%s]' % name):
                result.append(note.note)
            elif (note.category.startswith('{%s:' % name) and
                  note.category.endswith('}')):
                is_dict = True
                match = self.key_pattern.match(note.category)
                key = match.group(1)
                result.append((key, note.note))
            elif note.category == ('<%s>' % name):
                try:
                    return json.loads(
                        re.sub(r'(\w+)[ ]*(?=:)', r'"\g<1>"',
                               '{' + note.note.replace(';', ',') + '}')
                    )
                except Exception as e:
                    pass
                try:
                    return json.loads(
                        re.sub(r'(\w+)[ ]*(?=:)', r'"\g<1>"', note.note))
                except Exception as e:
                    logger.debug(
                        'not parsed %s(%s), returning literal text »%s«',
                        type(e), e, note.note)
                    return note.note
        if result == []:
            # if nothing was found, do not break the proxy.
            raise AttributeError(name)
        if is_dict:
            return dict(result)
        return result


class DefiningPictures:

    @property
    def pictures(self):
        """a list of Gtk.Image objects."""

        result = []
        for note in self.notes:
            if note.category != '<picture>':
                continue
            # contains the image or the error message
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            # Avoid pixbuf errors during test_import_pocket_log
            from bauble.prefs import testing
            if not testing:
                utils.ImageLoader(box, note.note).start()
            result.append(box)
        return result


class Serializable:
    import re
    single_cap_re = re.compile('([A-Z])')
    link_keys = []

    def as_dict(self):
        result = dict((col, getattr(self, col)) for col in
                      list(self.__table__.columns.keys()) if col not in
                      ['id'] and col[0] != '_' and getattr(self, col) is not
                      None and not col.endswith('_id'))
        result['object'] = self.single_cap_re.sub(
            r'_\1', self.__class__.__name__).lower()[1:]
        return result

    @classmethod
    def correct_field_names(cls, keys):
        """correct keys dictionary according to class attributes

        exchange format may use different keys than class attributes
        """
        pass

    @classmethod
    def compute_serializable_fields(cls, session, keys):
        """create objects corresponding to keys (class dependent)
        """
        return {}

    @classmethod
    def retrieve_or_create(cls, session, keys, create=True, update=True):
        """return database object corresponding to keys"""

        logger.debug('initial value of keys: %s', keys)
        # first try retrieving
        is_in_session = cls.retrieve(session, keys)\
            # pylint: disable=no-member
        logger.debug('2 value of keys: %s', keys)

        if not create and not is_in_session:
            logger.debug('not creating from %s; returning None (1)', str(keys))
            return None

        if is_in_session and not update:
            logger.debug("returning not updated existing %s", is_in_session)
            return is_in_session

        try:
            # some fields are given as text but actually correspond to
            # different fields and should be associated to objects
            extradict = cls.compute_serializable_fields(
                session, keys)

            # what fields must be corrected
            cls.correct_field_names(keys)
        except error.NoResultException:
            if not is_in_session:
                logger.debug("returning None (2)")
                return None
            extradict = {}
        except Exception as e:  # pylint: disable=broad-except
            logger.debug("this was unexpected %s", e)
            raise

        logger.debug('3 value of keys: %s', keys)

        # at this point, resulting object is either in database or not. in
        # either case, the database is going to be updated.

        # link_keys are python-side properties, not database associations
        # and have as value objects that are possibly in the database, or
        # not, but they cannot be used to construct the `self` object.
        link_values = {}
        for k in cls.link_keys:
            if keys.get(k):
                link_values[k] = keys[k]

        logger.debug("link_values : %s", str(link_values))

        for k in list(keys.keys()):
            if k not in class_mapper(cls).persist_selectable.c:
                del keys[k]
        if 'id' in keys:
            del keys['id']
        logger.debug('4 value of keys: %s', keys)

        keys.update(extradict)
        logger.debug('5 value of keys: %s', keys)

        # early construct object before building links
        if not is_in_session and create:
            # completing the task of building the links
            logger.debug("links? %s, %s", cls.link_keys, list(keys.keys()))
            for key in cls.link_keys:
                d = link_values.get(key)
                if d is None:
                    continue
                logger.debug('recursive call to construct_from_dict %s', d)
                obj = construct_from_dict(session, d)
                keys[key] = obj
            logger.debug("going to create new %s with %s", cls, keys)
            result = cls(**keys)
            session.add(result)

        # or possibly reuse existing object
        if is_in_session and update:
            result = is_in_session

            # completing the task of building the links
            logger.debug("links? %s, %s", cls.link_keys, list(keys.keys()))
            for key in cls.link_keys:
                d = link_values.get(key)
                if d is None:
                    continue
                logger.debug('recursive call to construct_from_dict %s', d)
                obj = construct_from_dict(session, d)
                keys[key] = obj

        logger.debug("going to update %s with %s", result, keys)
        if 'id' in keys:
            del keys['id']
        for k, v in list(keys.items()):
            if isinstance(v, dict):
                if v.get('__class__') == 'datetime':
                    m = v.get('millis', 0)
                    v = datetime.datetime(1970, 1, 12)
                    v = v + datetime.timedelta(0, m)
                else:
                    v = None
            if v is not None:
                setattr(result, k, v)
        logger.debug('returning updated existing %s', result)

        session.flush()

        logger.debug('returning new %s', result)
        return result


def construct_from_dict(session, obj, create=True, update=True):
    # get class and remove reference
    logger.debug("construct_from_dict %s", obj)
    klass = None
    if 'object' in obj:
        klass = class_of_object(obj['object'])
    if klass is None and 'rank' in obj:
        klass = globals().get(obj['rank'].capitalize())
        del obj['rank']
    return klass.retrieve_or_create(session, obj, create=create, update=update)


def class_of_object(obj):
    """Which class implements obj."""

    name = ''.join(p.capitalize() for p in obj.split('_'))
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
    if not path:
        return model
    relation, path = path.split('.', 1) if '.' in path else (path, None)
    # we have one relationship with a synonym - default_vernacular_name
    if syn := model.__mapper__.synonyms.get(relation):
        relation = syn.name
    model = model.__mapper__.relationships.get(
        relation).mapper.class_
    return get_related_class(model, path)


def get_or_create(session, model, **kwargs):
    instance = session.query(model).filter_by(**kwargs).first()
    if instance:
        return instance
    instance = model(**kwargs)
    session.add(instance)
    session.flush()
    return instance


def get_unique_columns(model):
    """Given a model get the unique columns.

    Agregates any `UniqueConstraint` columns set in `__table_args__`, columns
    with `unique` value set and `epithet` columns in taxanomic tables.

    Used by `get_create_or_update`.
    """
    uniq_cols = []
    if hasattr(model, '__table_args__'):
        from sqlalchemy import UniqueConstraint
        uniq_const = [i for i in model.__table_args__ if
                      isinstance(i, UniqueConstraint)][0]
        uniq_cols = uniq_const.columns.keys()
    # - add any joining columns (i.e. in plant we have accession_id as part
    # of the UniqueConstraint so "accession_id" would also include
    # "accession")
    uniq_joins = [i[:-3] for i in uniq_cols if i.endswith('_id')]
    uniq_cols.extend(uniq_joins)
    # - add columns with the unique attribute set
    uniq_table_cols = [i.key for i in model.__table__.columns if
                       i.unique and i.key not in uniq_cols]
    uniq_cols.extend(uniq_table_cols)
    # include epithet - synonym for family and genus
    if model.__tablename__ in ['family', 'genus']:
        uniq_cols.append('epithet')
    logger.debug('unique columns: %s', uniq_cols)
    return uniq_cols


def get_create_or_update(session, model, **kwargs):
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
    :param kwargs: database values
    """
    from sqlalchemy.orm.exc import MultipleResultsFound
    from sqlalchemy.exc import SQLAlchemyError
    logger.debug('looking for record matching: %s', kwargs)
    # first try using just one
    try:
        inst = session.query(model).filter_by(**kwargs).one()
        return inst
    except MultipleResultsFound:
        # no unique entry found, abort or we risk overwriting the wrong one.
        return None
    except SQLAlchemyError:
        # any other error (i.e. no result, error in the statement - can occur
        # with new data not flushed yet.)
        inst = None

    logger.debug("couldn't find matching object just using kwargs")
    # second try using a primary key if one is provided
    if not inst:
        for col in model.__table__.columns:
            if col.primary_key and (pkey := kwargs.get(col.key)):
                logger.debug('trying using primary key: %s', col.key)
                inst = session.query(model).get(pkey)

    # third try using unique fields
    if not inst:
        unique = {}
        uniq_cols = get_unique_columns(model)
        # get the kwargs that have keys in uniq_cols and try finding a match
        for col in uniq_cols:
            if (uniq_val := kwargs.get(col)):
                unique[col] = uniq_val
        if unique:
            try:
                logger.debug('trying using unique columns: %s', unique)
                inst = session.query(model).filter_by(**unique).one()
            except MultipleResultsFound:
                return None
            except SQLAlchemyError:
                inst = None
        else:
            logger.debug("couldn't find unique columns to use.")

    # last try, when available use uniq_props
    if not inst and hasattr(model, 'uniq_props'):
        unique = {}
        for k in kwargs:
            if k in model.uniq_props:
                unique[k] = kwargs.get(k)
        if unique:
            try:
                logger.debug('trying using uniq_props columns: %s', unique)
                inst = session.query(model).filter_by(**unique).one()
            except MultipleResultsFound:
                return None
            except SQLAlchemyError:
                inst = None
        else:
            logger.debug("couldn't find uniq_props columns to use.")

    # if none of the above got a result it should be safe to create a new entry
    if not inst:
        logger.debug('creating new %s with %s', model, kwargs)
        inst = model(**kwargs)
        session.add(inst)
        return inst

    # update the columns values.
    for k, v in kwargs.items():
        if getattr(inst, k) != v:
            setattr(inst, k, v)

    return inst


class current_user_functor:
    """implement the current_user function, and allow overriding.

    invoke the current_user object as a function.
    invoke current_user.override(user_name) to set user name.
    invoke current_user.override() to reset.
    """
    def __init__(self):
        self.override_value = None

    def override(self, value=None):
        self.override_value = value

    def __call__(self):
        """return current user name: from database, or system """
        if self.override_value:
            return self.override_value
        try:
            if engine.name.startswith('postgresql'):
                r = engine.execute('select current_user;')
                user = r.fetchone()[0]
                r.close()
            elif engine.name.startswith('mysql'):
                r = engine.execute('select current_user();')
                user = r.fetchone()[0]
                r.close()
            else:
                raise TypeError()
        except:
            logger.debug("retrieving user name from system")
            user = (os.getenv('USER') or os.getenv('USERNAME') or
                    os.getenv('LOGNAME') or os.getenv('LNAME'))

        return user


current_user = current_user_functor()
