# Copyright 2007 Brett Adams
# Copyright 2015 Mario Frasca <mario@anche.no>.
# Copyright 2021-2024 Ross Demuth <rossdemuth123@gmail.com>
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
"""
imex plugin

Description: plugin to provide importing and exporting
"""

import csv
import datetime
import logging
from abc import ABC
from abc import abstractmethod
from operator import attrgetter

from sqlalchemy.ext.hybrid import hybrid_property

logger = logging.getLogger(__name__)

from bauble import btypes
from bauble import db
from bauble import error
from bauble import pluginmgr
from bauble import prefs
from bauble import task
from bauble import utils
from bauble.i18n import _

# TODO: it might be best to do something like the reporter plugin so
# that this plugin provides a generic interface for importing and exporting
# and let the different tools provide the settings which are then passed to
# their start() methods

# see http://www.postgresql.org/docs/current/static/sql-copy.html

# NOTE: always beware when writing an imex plugin not to use the
# table.insert().execute(*list) statement or it will fill in values for
# missing columns so that all columns will have some value


def is_importable_attr(domain: db.Base, path: str) -> bool:
    """Check if a path points to an importable attribute (i.e. can be set).

    For hybrid_property returns False if has no setter.

    :param item: a sqlalchemy orm model class
    :param path: path as a string from the item to the attribute
    """

    if "." in path:
        table = db.get_related_class(domain, path.rsplit(".", 1)[0])
    else:
        table = domain
    column = getattr(table, path.split(".")[-1])
    if (
        hasattr(column, "descriptor")
        and isinstance(column.descriptor, hybrid_property)
        and not column.fset
    ):
        return False
    return True


class GenericImporter(ABC):  # pylint: disable=too-many-instance-attributes
    """Generic importer base class.

    Impliment `_import_task`
    """

    OPTIONS_MAP = []

    def __init__(self):
        self.option = "0"
        self.filename = None
        self.use_id = False
        self.search_by = set()
        self.replace_notes = set()
        self.fields = None
        self.domain = None
        self.completed = []
        # keepng track
        self._committed = 0
        self._total_records = 0
        self._errors = 0
        self._err_recs = []
        self._is_new = False
        # view and presenter
        self.presenter = None
        self.obj_cache = {}

    def start(self):
        """Start the importer UI.  On response run the import task.

        :return: Gtk.ResponseType"""
        response = self.presenter.start()
        self.presenter.cleanup()
        if response == -5:  # Gtk.ResponseType.OK - avoid importing Gtk here
            self.run()
            # just in case for postgres reset all sequences
            for table in db.metadata.sorted_tables:
                for col in table.c:
                    utils.reset_sequence(col)
        logger.debug("responded %s", response)
        return response

    def run(self):
        """Queues the import task"""
        self.completed = []
        task.clear_messages()
        task.queue(self._import_task(self.OPTIONS_MAP[int(self.option)]))
        msg = (
            f"import {self.filename} complete: "
            f"of {self._total_records} records "
            f"{self._committed} committed, "
            f"{self._errors} errors encounted"
        )
        task.set_message(msg)
        if self._err_recs:
            msg = (
                _(
                    "%s errors encountered, would you like to open a CSV of "
                    "the these records?"
                )
                % self._errors
            )
            if utils.yes_no_dialog(msg):
                filepath = utils.get_temp_path().with_suffix(".csv")
                with filepath.open("w", encoding="utf-8-sig", newline="") as f:
                    writer = csv.DictWriter(f, self._err_recs[0].keys())
                    writer.writeheader()
                    writer.writerows(self._err_recs)
                utils.desktop.open(str(filepath))

    @abstractmethod
    def _import_task(self, options):
        """Import task, to be implemented in subclasses"""

    def get_db_item(self, session, record, add):
        """Get an appropriate database instance to add the record to.

        This is the root (i.e. of the domain) item for the record.

        :param session: instance of db.Session()
        :param record: dict of paths to their values
        :param add: bool, whether or not to add new records to the database
        """
        in_dict_mapped = {}
        for field in self.search_by:
            record_field = self.get_value_as_python_type(
                self.domain, self.fields.get(field), record.get(field)
            )
            logger.debug("searching by %s = %s", field, record_field)
            in_dict_mapped[self.fields.get(field)] = record_field

        if in_dict_mapped in self.completed:
            match_str = ", ".join(
                f"{k} = {v}" for k, v in in_dict_mapped.items()
            )
            logger.debug("duplicate %s", match_str)
            msg = _(
                "Appears to be a duplicate record with matching values "
                "of: <b>%s</b> \nWould you like to skip this entry?\nOr "
                "select Cancel to stop importing any further?"
            ) % utils.xml_safe(match_str)
            dialog = utils.create_yes_no_dialog(msg)
            dialog.add_button("Cancel", -6)
            response = dialog.run()
            dialog.destroy()
            if response == -6:
                logger.debug("cancel")
                raise error.BaubleError(
                    msg="You have requested to cancelled further imports..."
                )
            if response == -8:
                logger.debug("skip")
                return None

        item = None
        if in_dict_mapped:
            item = self.domain.retrieve(session, in_dict_mapped)
            logger.debug("existing item: %s", item)

        if not item and add and self.domain:
            logger.debug("new item")
            self._is_new = True
            item = self.domain()  # pylint: disable=not-callable

        if item:
            self.completed.append(in_dict_mapped)

        return item

    def add_db_data(self, session, item, record):
        """Add column data from the record to the database item.

        Uses `self.fields` to map to the correct database field.  Where a path
        is provided attempt to create a corresponding entry for it.

        :param session: instance of db.Session()
        :param item: database table instance
        :param record: record as a dict of column names to values
        """
        self.obj_cache.clear()
        out_dict = {}
        logger.debug("fields = %s", self.fields)
        for col, value in record.items():
            if self.fields.get(col) is None:
                continue
            if self.fields.get(col).startswith("Note"):
                note_field = self.fields.get(col)
                # If the note has supplied a category use it.
                if note_field.endswith("]") and "[category=" in note_field:
                    note_category = note_field.split("[category=")[1]
                    note_category = note_category[:-1].strip('"').strip("'")
                else:
                    note_category = col
                note_text = str(record.get(col))
                if not note_text:
                    continue
                if note_category in self.replace_notes:
                    for note in item.notes:
                        logger.debug(
                            "deleting note of category: %s", note_category
                        )
                        if note.category == note_category:
                            session.delete(note)
                            # safest to commit each delete, should only occur
                            # on existing records, not new ones.
                            session.commit()
                note_model = self.domain.__mapper__.relationships.get(
                    "notes"
                ).mapper.class_
                note_dict = {
                    self.domain.__name__.lower(): item,
                    "category": note_category,
                    "note": note_text,
                }
                new_note = note_model(**note_dict)
                logger.debug("adding_note: %s", note_dict)
                session.add(new_note)
            elif self.fields.get(col) == "id" and not self.use_id:
                # for new entries skip the id when id has no value or we have
                # not selected to use it
                continue
            else:
                out_dict[self.fields.get(col)] = value

        item = self.add_rec_to_db(
            session, item, self.organise_record(out_dict)
        )
        logger.debug("adding to the session item : %s", item)
        session.add(item)
        self.obj_cache.clear()

    def commit_db(self, session):
        """If session is dirty try committing the changes.

        Also increment `_total_records`, `_committed`, `_errors` accordingly.

        :param session: an sqlalchemy Session instance
        :raises: if any errors encountered
        """
        from sqlalchemy.exc import SQLAlchemyError

        self._total_records += 1
        if session.dirty or session.new:
            try:
                session.commit()
                self._committed += 1
                logger.debug("committing")
            except (SQLAlchemyError, ValueError) as e:
                self._errors += 1
                logger.debug("Commit failed with %s", e)
                session.rollback()
                raise

    @staticmethod
    def organise_record(rec: dict) -> dict:
        """Organize record appropriate for use in `add_rec_to_db`.

        :param rec: dict of paths to values.
        :return: dict organised appropriately for `add_rec_to_db`.
        e.g.:
            {'accession.code': '1999025004',
            'code': '1',
            'quantity': '10',
            'location.code': 'Ad02a',
            'accession.species.genus.family.epithet': 'Asparagaceae',
            'accession.species.genus.epithet': 'Agave',
            'accession.species.epithet': 'ocahui',
            'accession.species.infraspecific_parts': 'var. longifolia'}
        becomes:
            {'accession.species.genus.family': {'epithet': 'Asparagaceae'},
            'accession.species.genus': {'epithet': 'Agave'},
            'accession.species': {'epithet': 'ocahui',
                                  'infraspecific_parts': 'var. longifolia'},
            'accession': {'code': '1999025004'},
            'location': {'code': 'Ad02a'},
            'code': '1',
            'quantity': '10'}
        """
        record = {}
        for k in sorted(rec, key=lambda i: i.count("."), reverse=True):
            # get rid of empty strings
            record[k] = None if rec[k] == "" else rec[k]
        organised = {}
        for k, v in record.items():
            if "." in k:
                path, atr = k.rsplit(".", 1)
                organised[path] = organised.get(path, {})
                organised[path][atr] = v
            else:
                organised[k] = v
        return organised

    @staticmethod
    def get_value_as_python_type(model, attr, value):
        """Given a model and attribute convert the value to an appropriate
        python type.

        Requires the supplied value to be resonable. i.e. int('Ten') will fail.
        """
        try:
            path_type = getattr(model, attr).type
            if path_type.__class__.__name__ == "JSON":
                from ast import literal_eval

                value = literal_eval(value)
            else:
                value = path_type.python_type(value)
        except Exception as e:  # pylint: disable=broad-except
            logger.debug(
                "convert models: %s type k: %s, v: %s raised %s (%s)",
                model,
                attr,
                value,
                type(e).__name__,
                e,
            )
            # for anything that doesn't have an obvious python_type a string
            # should work, this includes DateTime, Date and Boolean
            value = str(value)
        return value

    @staticmethod
    def handle_plant_changes(key, value, item):
        """Handle plant changes, especially `planted` and `death`"""
        from bauble.plugins.garden.plant import PlantChange

        if key == "planted":
            if hasattr(item, "planted") and item.planted:
                value["id"] = item.planted.id
            else:
                # should be a new entry. (i.e. item.id is None)
                # create the change and let the event.listen_for deal
                # with correcting the values later.
                # provides a way to add a planted change to data that
                # has no changes and is not being changed.
                if not item.changes and not value.get("quantity"):
                    value["quantity"] = item.quantity
                new_change = PlantChange(**value)
                item.changes.append(new_change)
                value = None
        elif key == "death":
            if hasattr(item, "death") and item.death:
                value["id"] = item.death.id
            else:
                # should be a new death entry.
                # NOTE No guarantee this will become a death change or
                # just a regular change.
                new_change = PlantChange(**value)
                item.changes.append(new_change)
                value = None
        elif key == "changes":
            # should be a new change relating to another field change
            new_change = PlantChange(**value)
            item.changes.append(new_change)
            value = None
        return value

    def memoized_get_create_or_update(
        self, session, model, create_one_to_one=False, **kwargs
    ):
        """Memoizing the result of get_create_or_update allows the same
        instance to be used multiple time without the need to query repeatedly.

        Most usefull when new instances are returned, avoids needing to flush
        the session to add in the id etc. or the risk of returning identical
        new instances when the query fails.

        Make sure to clear or destroy self.obj_cache after all records are
        committed so they do not stay in memory.
        """
        key = (model, tuple(sorted(kwargs.items())))
        if value := self.obj_cache.get(key):
            logger.debug("memoized_get_create_or_update returning memoized")
            return value
        value = db.get_create_or_update(
            session, model, create_one_to_one, **kwargs
        )
        self.obj_cache[key] = value
        return value

    def add_rec_to_db(
        self, session, item, rec
    ):  # pylint: disable=too-many-locals
        """Add or update the item record in the database including any related
        records.

        :param session: instance of db.Session()
        :param item: an instance of a sqlalchemy table
        :param rec: dict of the records to add, ordered so that related records
            are first so that they are found, created, or updated first.  Keys
            are paths from the item class to either fields of that class or to
            related tables.  Values are item columns values or the related
            table columns and values as a nested dict.
            e.g.:
            {'accession.species.genus.family': {'epithet': 'Alliaceae'},
             'accession.species.genus': {'epithet': 'Agapanthus'}, ...}
        """
        # peel off the first record to work on
        first, *remainder = rec.items()
        remainder = dict(remainder)
        key, value = first
        logger.debug(
            "adding key: %s with value: %s type: %s", key, value, type(value)
        )
        # related records
        if isinstance(value, dict):
            # after this "value" will be in the session
            # Try convert values to the correct type
            model = db.get_related_class(type(item), key)
            for k, v in value.items():
                if v is not None and not hasattr(v, "__table__"):
                    v = self.get_value_as_python_type(model, k, v)
                    value[k] = v

            logger.debug("values: %s", value)
            logger.debug("model tablename: %s", model.__tablename__)

            if model.__tablename__ == "plant_change":
                value = self.handle_plant_changes(key, value, item)

            if value:
                db_item = None
                # try get_create_or_update
                db_item = self.memoized_get_create_or_update(
                    session, model, create_one_to_one=self._is_new, **value
                )
                logger.debug("item is now: %s", db_item)
                # try existing
                if db_item is None:
                    try:
                        logger.debug("try get existing with attrgetter")
                        db_item = attrgetter(key)(item)  # existing entries
                        logger.debug("item is now: %s", db_item)
                        for k, v in value.items():
                            setattr(db_item, k, v)
                    except AttributeError as e:
                        logger.debug("%s(%s)", type(e).__name__, e)
                # error if not found
                if db_item is None:
                    logger.debug("item still None, raising")
                    raise error.DatabaseError(
                        "No item could be found or created for record with "
                        f"value:\n\n{value}\n\nYour import data may have "
                        "insufficient identifying fields, consider including "
                        "'id' fields."
                    )
                value = db_item
            root, atr = key.rsplit(".", 1) if "." in key else (None, key)
            logger.debug(
                "root = %s, atr = %s, remainder = %s", root, atr, remainder
            )
            # should block _default_vernacular_name in relation_filter
            # NOTE default vernacular names need to be added directly as they
            # use their own methods,
            # Below accepts
            # 'accession.species._default_vernacular_name.vernacular_name.name'
            # which at this point would be:
            # root = 'accession.species._default_vernacular_name'
            # atr = 'vernacular_name'
            #  - depending on what we get back from
            #  get_create_or_update(session, VernacularName, name=... )
            # value = VernacularName(...)
            # and changes it to
            # root = 'accession.species'
            # atr = 'default_vernacular_name'
            # value = VernacularName(...)
            # This will generally work but is not fool proof.  It is preferable
            # to use the hybrid_property default_vernacular_name
            if (
                root
                and root.endswith("._default_vernacular_name")
                and atr == "vernacular_name"
            ):
                root = root.removesuffix("._default_vernacular_name")
                atr = "default_vernacular_name"

            if root in remainder:
                remainder[root][atr] = value
            elif root and "." in root and root.rsplit(".", 1)[0] in remainder:
                # linking 1-1 table steps away from item
                link, atr2 = root.rsplit(".", 1)
                try:
                    link_item = attrgetter(root)(item)  # existing entries
                except AttributeError:
                    link_item = db.get_related_class(type(item), root)()
                    session.add(link_item)
                setattr(link_item, atr, value)
                logger.debug("adding: %s to %s", atr2, link)
                remainder[link][atr2] = link_item
            elif root and "." not in root and root not in remainder:
                # linking 1-1 table of item
                link_item = getattr(item, root)  # existing entries
                if not link_item:
                    link_item = db.get_related_class(type(item), root)()
                logger.debug(
                    "adding: %s to %s",
                    type(link_item).__name__,
                    type(item).__name__,
                )
                setattr(link_item, atr, value)
                setattr(item, root, link_item)
        elif value is not None and not hasattr(value, "__table__"):
            model = type(item)
            value = self.get_value_as_python_type(model, key, value)

        # if there are more records continue to add them
        if len(remainder) > 0:
            self.add_rec_to_db(session, item, remainder)

        # once all records are accounted for add them to item in reverse
        if "." not in key and key != "changes":
            logger.debug(
                "setattr on object: %s with name: %s and value: %s (type %s)",
                item,
                key,
                value,
                type(value),
            )
            # make sure geojson history items work... (NOTE does not account
            # for other deferred columns but currently there are none)
            if key == "geojson":
                hasattr(item, key)
            setattr(item, key, value)
        return item


class GenericExporter(ABC):
    """Generic exporter base class.

    Impliment _export_task
    """

    def __init__(self, open_=True):
        self.items = None
        self.open = open_
        self.domain = None
        self.filename = None
        self.error = 0
        self.presenter = None

    def start(self):
        """Start the CSV exporter UI.  On response run the export task.

        :return: Gtk.ResponseType"""
        response = self.presenter.start()
        self.presenter.cleanup()
        if response == -5:  # Gtk.ResponseType.OK - avoid importing Gtk here
            self.run()
        logger.debug("responded %s", response)
        return response

    def run(self):
        """Queues the export task(s)"""
        task.clear_messages()
        task.set_message(f"exporting {self.domain.__tablename__} records")
        task.queue(self._export_task())
        task.set_message("export completed")

    @abstractmethod
    def _export_task(self):
        """Export task, to be implemented in subclasses"""

    @staticmethod
    def get_item_value(path, item):
        """Get the items value as a string.

        Intended mostly for use with `get_item_record`

        :param path: path as a string from the item to the attribute
        :param item: an instance of a sqlalchemy table
        :return: string value of the attribute
        """
        datetime_fmat = prefs.prefs.get(prefs.datetime_format_pref)
        date_fmat = prefs.prefs.get(prefs.date_format_pref)
        try:
            value = attrgetter(path)(item)
            try:
                if "." in path:
                    table = db.get_related_class(
                        item.__table__, path.rsplit(".", 1)[0]
                    ).__table__
                else:
                    table = item.__table__
                column_type = getattr(table.c, path.split(".")[-1]).type
            except AttributeError:
                # path is to a table and not a column
                column_type = None
            if value and isinstance(column_type, btypes.Date):
                return value.strftime(date_fmat)
            if value and isinstance(column_type, btypes.DateTime):
                return value.strftime(datetime_fmat)
            # planted.date death.date etc.
            if value and isinstance(value, datetime.datetime):
                return value.strftime(datetime_fmat)
            return str(value if value is not None else "")
        except AttributeError:
            return ""

    @staticmethod
    def get_attr_notes(item):
        """Get a list of names of any attribute notes for an item."""
        attr_notes = []
        for note in item.notes:
            category = getattr(note, "category", None)
            if not category:
                continue
            import re

            if match := re.match(r"\{([^\{:]+):(.*)}", category):
                attr_notes.append(match.group(1))
            elif category.startswith("[") and category.endswith("]"):
                attr_notes.append(category[1:-1])
            elif category.startswith("<") and category.endswith(">"):
                attr_notes.append(category[1:-1])
        return attr_notes

    @classmethod
    def get_item_record(cls, item, fields):
        """Given a database entry and a dict of names to the paths to
        attributes return a dict of names to their values.

        :param item: an instance of a sqlalchemy table
        :param fields: dict of names to paths as strings.
            NOTE: if `domain` key is included, return it as it was recieved.
            Intended as a method to state which type is being exported.
        :return: dict of names to values
        """
        record = {}
        # handle generated attribute notes
        has_notes = hasattr(item, "notes") and isinstance(item.notes, list)
        attr_notes = cls.get_attr_notes(item) if has_notes else []
        for name, path in fields.items():
            if name == "domain":
                record[name] = path
            elif path == "Note":
                value = ""
                # handle generated attribute notes
                if hasattr(item, name) and name in attr_notes:
                    value = getattr(item, name)
                else:
                    value = [n.note for n in item.notes if n.category == name]
                    value = str(value[-1]) if value else ""
                record[name] = str(value)
            elif path == "Empty":
                record[name] = ""
            elif path == item.__table__.key:
                record[name] = str(item)
            else:
                record[name] = cls.get_item_value(path, item)
        return record


class ImexPlugin(pluginmgr.Plugin):
    # avoid cicular imports
    from .csv_ import CSVBackupCommandHandler
    from .csv_ import CSVBackupTool
    from .csv_ import CSVRestoreCommandHandler
    from .csv_ import CSVRestoreTool
    from .csv_io import CSVExportTool
    from .csv_io import CSVImportTool
    from .shapefile import ShapefileExportTool
    from .shapefile import ShapefileImportTool
    from .xml import XMLExportCommandHandler
    from .xml import XMLExportTool

    tools = [
        CSVRestoreTool,
        CSVBackupTool,
        CSVExportTool,
        CSVImportTool,
        XMLExportTool,
        ShapefileImportTool,
        ShapefileExportTool,
    ]
    commands = [
        CSVBackupCommandHandler,
        CSVRestoreCommandHandler,
        XMLExportCommandHandler,
    ]


plugin = ImexPlugin
