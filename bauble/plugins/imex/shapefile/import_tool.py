# Copyright (c) 2021-2024 Ross Demuth <rossdemuth123@gmail.com>
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
Import data from shapefiles (zip file with all component files).
"""

import logging
import weakref
from contextlib import contextmanager
from pathlib import Path
from random import random
from zipfile import ZipFile

logger = logging.getLogger(__name__)

from gi.repository import Gtk
from shapefile import Reader
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import InspectionAttr
from sqlalchemy.orm import class_mapper

import bauble
from bauble import db
from bauble import pb_set_fraction
from bauble import prefs
from bauble import task
from bauble.editor import GenericEditorPresenter
from bauble.editor import GenericEditorView

# NOTE importing shapefile Reader Writer above wipes out gettext _
from bauble.i18n import _

# NOTE: need to import the Note classes as we may need them.
from bauble.plugins.garden.location import Location
from bauble.plugins.garden.plant import Plant
from bauble.utils.geo import DEFAULT_IN_PROJ
from bauble.utils.geo import ProjDB
from bauble.utils.geo import transform

from .. import GenericImporter
from . import LOCATION_SHAPEFILE_PREFS
from . import PLANT_SHAPEFILE_PREFS
from . import SHAPEFILE_IGNORE_PREF

PATH = 4
"""Column position for the path widget and attribte"""
MATCH = 5
"""Column position for the match widget."""
OPTION = 6
"""Column position for the option widget."""
IGNORED_FIELDS = ("st_length_", "st_area_sh")
"""Sensible defaults for shapefile field names to ignore when importing,
overridden if the SHAPEFILE_IGNORE_PREF pref is set."""


class ShapefileReader:
    """
    A wrapper for reading zipped shapefile data and the settings used.  By
    making changes here we can change how the shapefile data is read and hence
    imported into the database e.g. mapping fields to database fields.
    Primarily changes are made in the ShapefileImportSettingsBox.
    """

    def __init__(self, filename):
        """
        :param filename: string absolute path to zip file containing all
            shapefile component files (.shp, .prj, .dbf, .shx)
        """
        self._filename = None
        self.filename = filename
        self.use_id = False
        self.replace_notes = set()
        self._type = None
        self._search_by = None
        self._field_map = {}

    def __eq__(self, other):
        """Override == to check shapefiles are equal in form.

        i.e. Share the same fields, ignoring fields defined in
        SHAPEFILE_IGNORE_PREF or IGNORED_FIELDS.
        """
        other_fields = other.get_fields()

        remainder = []
        for field in self.get_fields():
            try:
                other_fields.remove(field)
            except ValueError:
                remainder.append(field)
        remainder.extend(other_fields)
        ignored = prefs.prefs.get(SHAPEFILE_IGNORE_PREF, IGNORED_FIELDS)
        remainder = [i for i in remainder if i[0] not in ignored]
        return remainder == []

    def _guess_type(self):
        """try guess what type (Plant or Location) the record is by checking
        the for fields that match the default field maps.
        """
        plt = len(
            [
                i
                for i in self.get_fields()
                if prefs.prefs.get(f"{PLANT_SHAPEFILE_PREFS}.fields", {}).get(
                    i[0]
                )
            ]
        )
        loc = len(
            [
                i
                for i in self.get_fields()
                if prefs.prefs.get(
                    f"{LOCATION_SHAPEFILE_PREFS}.fields", {}
                ).get(i[0])
            ]
        )
        if plt > loc:
            logger.debug("type guess plt - plant:%s location:%s", plt, loc)
            return "plant"
        if loc > plt:
            logger.debug("type guess loc - plant:%s location:%s", plt, loc)
            return "location"
        logger.debug("could not guess type - plant:%s location:%s", plt, loc)
        return None

    @property
    def type(self):
        """The type of record as a string ('plant' or 'location')

        if this is not set manually an attempt to guess it will be made
        """
        if self._type is None:
            self._type = self._guess_type()
        return self._type

    @type.setter
    def type(self, typ):
        # reset whenever the type is reset.
        self._search_by = None
        self._field_map = {}
        self._type = typ

    @property
    def filename(self):
        """Absolute path to a zip file containting shapefile components,

        changing the value resets all other values.
        """
        return self._filename

    @filename.setter
    def filename(self, filename):
        # reset whenever the filename is reset.
        self._type = None
        self._search_by = None
        self._field_map = {}
        self._filename = filename

    @property
    def search_by(self):
        """When trying to match a record from the shapefile which fields are
        used to match the database entry.

        Unless manually set this will match the defaults for the type.
        """
        if self._search_by is None:
            self._search_by = set()
            if self.type == "plant":
                default_search_by = prefs.prefs.get(
                    f"{PLANT_SHAPEFILE_PREFS}.search_by", {}
                )
            elif self.type == "location":
                default_search_by = prefs.prefs.get(
                    f"{LOCATION_SHAPEFILE_PREFS}.search_by", {}
                )
            else:
                default_search_by = []
            for field in self.get_fields():
                if field[0] in default_search_by:
                    self._search_by.add(field[0])
        return self._search_by

    @search_by.setter
    def search_by(self, sby):
        self._search_by = sby

    @property
    def field_map(self):
        """A dict for mapping shapefile fields to database fields."""
        if not self._field_map:
            if self.type == "plant":
                default_map = prefs.prefs.get(
                    f"{PLANT_SHAPEFILE_PREFS}.fields", {}
                )
            elif self.type == "location":
                default_map = prefs.prefs.get(
                    f"{LOCATION_SHAPEFILE_PREFS}.fields", {}
                )
            else:
                default_map = {}
            # rebuild the field map
            for field in self.get_fields():
                if field[0] in default_map.keys() and not isinstance(
                    default_map.get(field[0]), list
                ):
                    self._field_map[field[0]] = default_map.get(field[0])
        return self._field_map

    @field_map.setter
    def field_map(self, fim):
        self._field_map = fim

    @contextmanager
    def _reader(self):
        """A contextmanager for the shapefile Reader. Extracts the zip first"""
        z = ZipFile(self.filename, "r")
        namelist = z.namelist()
        shp = z.open([i for i in namelist if i.endswith(".shp")][0])
        dbf = z.open([i for i in namelist if i.endswith(".dbf")][0])
        reader = Reader(shp=shp, dbf=dbf)
        try:
            yield reader
        finally:
            reader.close()
            shp.close()
            dbf.close()
            z.close()

    def get_prj_string(self):
        """
        :return: string as contained in the .prj file or None.
        """
        try:
            with ZipFile(self.filename, "r") as z:
                namelist = z.namelist()
                with z.open(
                    [i for i in namelist if i.endswith(".prj")][0]
                ) as prj:
                    prj_str = prj.read().decode("utf-8")
                prj_str = prj_str.strip()
            return prj_str if prj_str else None
        except Exception as e:  # pylint: disable=broad-except
            logger.debug(
                "can't get .prj file string %s(%s)", type(e).__name__, e
            )
            return None

    def get_fields(self):
        """
        :return: list of fields in the shapefile
        """
        try:
            with self._reader() as reader:
                fields = list(reader.fields)
                logger.debug("fields = %s", fields)
            return fields if fields else []
        except Exception as e:  # pylint: disable=broad-except
            logger.debug("%s(%s)", type(e).__name__, e)
            return []

    def get_records_count(self):
        """
        :return: int count of records in the shapefile or None.
        """
        try:
            with self._reader() as reader:
                return len(reader)
        except Exception as e:  # pylint: disable=broad-except
            logger.debug("%s(%s)", type(e).__name__, e)
            return 0

    @contextmanager
    def get_records(self):
        """a contextmanager for shapeRecords (records and shapes) for the
        shapefile.
        """
        with self._reader() as reader:
            shape_records = reader.shapeRecords()
        try:
            yield shape_records
        finally:
            reader.close()


class ShapefileImportSettingsBox(Gtk.ScrolledWindow):
    """Advanced settings used to change the behaviour of the ShapefileReader"""

    def __init__(self, shape_reader=None, grid=None):
        super().__init__(propagate_natural_height=True)
        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.shape_reader = weakref.proxy(shape_reader)
        self.schema_menus = []
        type_frame = Gtk.Frame(shadow_type=Gtk.ShadowType.NONE)
        type_label = Gtk.Label(justify=Gtk.Justification.LEFT)
        type_label.set_markup("<b>records type:</b>")
        type_frame.set_label_widget(type_label)
        self.type_combo = Gtk.ComboBoxText()
        self._type_sid = self.type_combo.connect(
            "changed", self.on_type_changed
        )
        self.type_combo.append_text("plant")
        self.type_combo.append_text("location")

        if shape_reader.type == "plant":
            self.type_combo.set_active(0)
        elif shape_reader.type == "location":
            self.type_combo.set_active(1)
        else:
            self.type_combo.set_active(-1)

        height = min(24 + (len(shape_reader.get_fields()) * 42), 550)
        self.set_min_content_height(height)
        type_frame.add(self.type_combo)
        self.box.add(type_frame)
        # for tests and avoids gtk errors
        if grid is None:
            grid = Gtk.Grid(column_spacing=6, row_spacing=6)

        self.grid = grid
        self.box.add(self.grid)
        self.add(self.box)
        self._construct_grid()

    def _construct_grid(self):
        """Create the field grid layout."""
        labels = [
            "name",
            "type",
            "length",
            "dec places",
            "database field",
            "match database",
            "option",
        ]
        for column, txt in enumerate(labels):
            label = Gtk.Label()
            label.set_markup(f"<b>{txt}</b>")
            self.grid.attach(label, column, 0, 1, 1)

        model = Plant
        if self.shape_reader.type == "location":
            model = Location
        # NOTE can not use enumerate for row here
        ignored = prefs.prefs.get(SHAPEFILE_IGNORE_PREF, IGNORED_FIELDS)
        row = 0
        for field in self.shape_reader.get_fields():
            if field[0] in ignored:
                continue
            # only list fields are needed
            if isinstance(field, list):
                row += 1
                for column, value in enumerate(field):
                    label = Gtk.Label()
                    label.set_text(str(value))
                    self.grid.attach(label, column, row, 1, 1)

                name = field[0]

                prop_button, schema_menu = self._get_prop_button(
                    model, name, row
                )
                prop_button.connect(
                    "button-press-event",
                    self.on_prop_button_press_event,
                    schema_menu,
                )
                self.grid.attach(prop_button, PATH, row, 1, 1)

    @staticmethod
    def relation_filter(key, prop):
        # Avoid offering many relationships
        try:
            if prop.prop.uselist:
                return False
        except AttributeError:
            pass
        # force users to use the hybrid property
        if key == "_default_vernacular_name":
            return False
        return True

    @staticmethod
    def column_filter(_key, prop: InspectionAttr) -> bool:
        # Avoid offering unimportable hybrid properties
        if isinstance(prop, hybrid_property) and not prop.fset:
            return False
        return True

    @staticmethod
    def on_prop_button_press_event(_widget, event, menu):
        menu.popup_at_pointer(event)

    def _get_prop_button(
        self, model, name, row
    ):  # pylint: disable=too-many-statements
        # default model is plant
        db_field = self.shape_reader.field_map.get(name, "")
        prop_button = Gtk.Button()
        prop_button.set_use_underline(False)

        # Note need to destroy schemmenu to garbage collect this.
        def menu_activated(_widget, path, _prop):
            """Closure used to set the field_map and button label."""
            prop_button.get_style_context().remove_class("err-btn")
            if chk_btn := self.grid.get_child_at(MATCH, row):
                self.grid.remove(chk_btn)
            if chk_btn := self.grid.get_child_at(OPTION, row):
                self.grid.remove(chk_btn)
            if path:
                prop_button.set_label(path)
                self.shape_reader.field_map[name] = path
                if path in model.retrieve_cols:
                    chk_button = Gtk.CheckButton.new_with_label("match")

                    chk_button.connect(
                        "toggled",
                        self.on_match_chk_button_change,
                        (name, prop_button),
                    )
                    tooltip = (
                        "Select to ensure this field matches the current "
                        "data. If a match can not be found the record will be "
                        "skipped.\n\nThere must be at least one match field "
                        "and a match must return a single database entry."
                    )
                    chk_button.set_tooltip_text(tooltip)
                    if name in self.shape_reader.search_by:
                        chk_button.set_active(True)
                    else:
                        chk_button.set_active(False)
                    self.grid.attach(chk_button, MATCH, row, 1, 1)
                    chk_button.show()
                if path == "id":
                    chk_button = Gtk.CheckButton.new_with_label("import")
                    tooltip = (
                        "Select to import this field into the database.  You "
                        "generally won't want to do this as any conflicts "
                        "with existing records could fail anyway."
                    )
                    chk_button.set_tooltip_text(tooltip)
                    chk_button.connect(
                        "toggled", self.on_import_id_chk_button_change
                    )
                    self.grid.attach(chk_button, OPTION, row, 1, 1)
                    chk_button.show()
                elif path and path.startswith("Note"):
                    chk_button = Gtk.CheckButton.new_with_label("replace")
                    tooltip = (
                        "Select to replace all existing notes of this "
                        "category.  If not selected or no notes of this "
                        "category exist a new note will be added.\n\nCAUTION! "
                        "will delete all notes of category."
                    )
                    chk_button.set_tooltip_text(tooltip)
                    chk_button.connect(
                        "toggled", self.on_replace_chk_button_change, name
                    )
                    self.grid.attach(chk_button, OPTION, row, 1, 1)
                    chk_button.show()
            else:
                if self.shape_reader.field_map.get(name):
                    del self.shape_reader.field_map[name]
                prop_button.set_label(_("Choose a property…"))

        from bauble.query_builder import SchemaMenu

        schema_menu = SchemaMenu(
            class_mapper(model),
            menu_activated,
            relation_filter=self.relation_filter,
            column_filter=self.column_filter,
            private=True,
            selectable_relations=False,
        )

        schema_menu.append(Gtk.SeparatorMenuItem())
        for item in ["Note", ""]:
            xtra = Gtk.MenuItem(label=item, use_underline=False)
            xtra.connect("activate", menu_activated, item, None)
            schema_menu.append(xtra)

        schema_menu.show_all()
        self.schema_menus.append(schema_menu)

        try:
            # If a db_field is a table then don't try importing it (is is used
            # as a label only)
            if db_field == model.__tablename__:
                db_field = ""
            elif db.get_related_class(model, db_field):
                db_field = ""
        except AttributeError:
            pass
        menu_activated(None, db_field, None)
        tooltip = (
            "NOTE: Not all fields can be imported and some may "
            "cause unexpected results.  Take caution and consider "
            "BACKING UP your data first.\n\nSettings here "
            "override settings above.  Fields left blank will not "
            'be imported.  "Note" designates the field is to be '
            'added as a note of the item.  The current "name" '
            "will be used as the category for the note."
        )
        prop_button.set_tooltip_text(tooltip)
        return prop_button, schema_menu

    def on_type_changed(self, combo):
        if self.shape_reader.type != combo.get_active_text():
            self.shape_reader.type = combo.get_active_text()
            while self.grid.get_child_at(0, 0) is not None:
                self.grid.remove_row(0)
            self._construct_grid()
            self.grid.show_all()

    def on_match_chk_button_change(self, chk_btn, data):
        field, prop_button = data
        prop_button.get_style_context().remove_class("err-btn")
        if chk_btn.get_active() is True:
            self.shape_reader.search_by.add(field)
            if prop_button.get_label() not in [
                v
                for k, v in self.shape_reader.field_map.items()
                if k in self.shape_reader.search_by
            ]:
                prop_button.get_style_context().add_class("err-btn")
        else:
            logging.debug("deleting %s from search_by", field)
            self.shape_reader.search_by.remove(field)

    def on_import_id_chk_button_change(self, chk_btn):
        if chk_btn.get_active() is True:
            self.shape_reader.use_id = True
        else:
            self.shape_reader.use_id = False

    def on_replace_chk_button_change(self, chk_btn, name):
        if chk_btn.get_active() is True:
            self.shape_reader.replace_notes.add(name)
        else:
            self.shape_reader.replace_notes.remove(name)

    def cleanup(self):
        # garbage collection
        self.type_combo.disconnect(self._type_sid)
        self.grid.destroy()
        for schema_menu in self.schema_menus:
            schema_menu.destroy()


class ShapefileImporter(GenericImporter):
    """Import shapefile data into the database."""

    # pylint: disable=too-many-instance-attributes

    OPTIONS_MAP = [
        {
            "add_geo": True,
            "update": False,
            "add_new": False,
            "all_data": False,
        },
        {"add_geo": True, "update": True, "add_new": False, "all_data": False},
        {"add_geo": True, "update": True, "add_new": False, "all_data": True},
        {"add_geo": False, "update": False, "add_new": True, "all_data": True},
        {"add_geo": True, "update": True, "add_new": True, "all_data": True},
    ]

    _tooltips = {
        "option_combo": _(
            "Ordered roughly least destructive to most "
            "destructive. The primary purpose of this plugin is "
            "to add spatial data to existing records and hence "
            "adding new records is limited to plants, locations "
            "and associated notes. When adding plants the "
            "accession and location must already exist. Some "
            "fields are read only, e.g. species and family "
            "epithets are ignored during imports."
        ),
        "btn_file_chooser": _(
            "Browse to the zipfile(s) that contains "
            "the shapefile and other associated files. "
            "\nNOTE: If choosing multiple files at once "
            "they must all have the same fields and "
            "projection."
        ),
        "input_projection": _(
            "The shapefile's projection control parameter, "
            "can contain any string parameters accepted by "
            "pyproj.crs.CRS().  An EPSG code is most likely "
            "the simplest to use.   see: https://pyproj4."
            "github.io/pyproj/stable/api/crs/crs.html"
        ),
        "projection_button": _(
            "If no projection control parameters for the "
            ".prj file included with the selected "
            "shapefile, adding it to the list.  If you "
            "believe it is currently wrong changing it."
        ),
        "cb_always_xy": _(
            "Use the traditional GIS order long, lat.  Some GIS "
            "systems do this some don't.  You may need to use "
            "trial and error to decide if you need to use this "
            "for each data source. (if all items turn up in the "
            "wrong place this could be the cause.) The state is "
            "saved on clicking OK."
        ),
    }

    def __init__(self, view=None, proj_db=None):
        super().__init__()
        # widget fields
        # NOTE use string NOT int for option
        self.projection = DEFAULT_IN_PROJ
        self.always_xy = True
        # view and presenter
        if view is None:
            view = GenericEditorView(
                str(Path(__file__).resolve().parent / "shapefile.glade"),
                root_widget_name="shapefile_import_dialog",
                tooltips=self._tooltips,
            )
            view.init_translatable_combo(
                view.widgets.option_combo,
                [
                    ("0", "add missing spatial data for existing records"),
                    ("1", "add or update spatial data for existing records"),
                    ("2", "add or update all data for existing records"),
                    ("3", "add new records only"),
                    ("4", "add or update all records"),
                ],
            )
        if proj_db is None:
            proj_db = ProjDB()
        self.presenter = ShapefileImportDialogPresenter(self, view, proj_db)
        # readers
        self.shape_readers = []

    def _import_task(self, options):
        """The import task.

        Yields occasionally to allow the UI to update.

        :param options: dict of settings used to decide when/what to add.
        """
        self.fields = self.shape_readers[0].field_map
        self.search_by = self.shape_readers[0].search_by
        self.use_id = self.shape_readers[0].use_id
        self.replace_notes = self.shape_readers[0].replace_notes
        session = db.Session()
        logger.debug("importing %s with option %s", self.filename, self.option)
        record_count = sum(
            shrd.get_records_count() for shrd in self.shape_readers
        )
        five_percent = int(record_count / 20) or 1
        records_added = records_done = 0
        if self.shape_readers[0].type == "plant":
            self.domain = Plant
        elif self.shape_readers[0].type == "location":
            self.domain = Location
        else:
            from bauble.error import BaubleError

            logger.debug("error - no type set")
            raise BaubleError('No "type" set for the records.')

        for shape_reader in self.shape_readers:
            msg = (
                f"{shape_reader.filename}: {self._total_records} records, "
                f"{self._committed} committed, {self._errors} errors"
            )
            task.set_message(msg)
            with shape_reader.get_records() as records:
                for line, record in enumerate(records, start=1):
                    rec_dict = record.record.as_dict()
                    record_dict = {
                        k: v for k, v in rec_dict.items() if self.fields.get(k)
                    }
                    self._is_new = False
                    item = self.get_db_item(
                        session, record_dict, options.get("add_new")
                    )

                    if records_done % five_percent == 0:
                        pb_set_fraction(records_done / record_count)
                        msg = (
                            f"{shape_reader.filename}: "
                            f"{self._total_records} records, "
                            f"{self._committed} committed, "
                            f"{self._errors} errors"
                        )
                        task.set_message(msg)
                        yield

                    records_done += 1

                    if item is None:
                        continue

                    if item.geojson:
                        if options.get("update"):
                            if not self.add_db_geo(session, item, record):
                                logger.debug("add_db_geo failed")
                                continue
                            records_added += 1
                            if options.get("all_data"):
                                logger.debug("adding all data")
                                try:
                                    self.add_db_data(
                                        session, item, record_dict
                                    )
                                except Exception as e:
                                    logger.debug("%s(%s)", type(e).__name__, e)
                                    rec_dict["__file"] = shape_reader.filename
                                    rec_dict["__line_#"] = line
                                    rec_dict["__err"] = e
                                    self._err_recs.append(rec_dict)
                                    self._total_records += 1
                                    self._errors += 1
                                    session.rollback()
                                    continue
                    else:
                        if self._is_new or options.get("add_geo"):
                            if not self.add_db_geo(session, item, record):
                                logger.debug("add_db_geo failed")
                                continue
                            records_added += 1
                            if options.get("all_data"):
                                logger.debug("adding all data")
                                try:
                                    self.add_db_data(
                                        session, item, record_dict
                                    )
                                except Exception as e:
                                    logger.debug("%s(%s)", type(e).__name__, e)
                                    rec_dict["__file"] = shape_reader.filename
                                    rec_dict["__line_#"] = line
                                    rec_dict["__err"] = e
                                    self._err_recs.append(rec_dict)
                                    self._total_records += 1
                                    self._errors += 1
                                    session.rollback()
                                    continue

                    # commit every record catches errors and avoids losing
                    # records.
                    logger.debug("committing")
                    try:
                        self.commit_db(session)
                    except Exception as e:
                        # record errored
                        rec_dict["__file"] = shape_reader.filename
                        rec_dict["__line_#"] = line
                        rec_dict["__err"] = e
                        self._err_recs.append(rec_dict)

        session.close()
        if bauble.gui and (view := bauble.gui.get_view()):
            view.update()

    def add_db_geo(self, session, item, record):
        """Add the __geo_interface__ data from the shapefile record to the
        database item's geojson field

        Coordinates are projected to the system CRS as needed.

        :param session: instance of db.Session()
        :param item: database instance
        :param record: a shapefile.Record().shapefileRecord() value
        """
        logger.debug("adding geojson data")
        geojson = transform(
            record.shape.__geo_interface__,
            in_crs=self.projection,
            always_xy=self.always_xy,
        )
        if not geojson:
            logger.debug("error transforming %s", record)
            return False
        item.geojson = geojson

        session.add(item)
        return True


class ShapefileImportDialogPresenter(GenericEditorPresenter):
    """The presenter for the shapefile import dialog."""

    widget_to_field_map = {
        "option_combo": "option",
        "input_projection": "projection",
        "cb_always_xy": "always_xy",
    }
    view_accept_buttons = ["imp_button_ok"]

    PROBLEM_NOT_SHAPEFILE = f"no_shapefile:{random()}"
    PROBLEM_NO_PROJ = f"no_proj:{random()}"
    PROBLEM_PROJ_MISMATCH = f"proj_mismatch:{random()}"
    PROBLEM_MULTI_NOT_EQUAL = f"fields_mismatch:{random()}"

    last_folder = str(Path.home())

    def __init__(self, model, view, proj_db):
        super().__init__(model=model, view=view, session=False)
        self.prj_string = None
        self.proj_db_match = None
        self.proj_text = None
        self.settings_box = None
        self.proj_db = proj_db
        self.add_problem(self.PROBLEM_EMPTY, self.view.widgets.filenames_lbl)
        self.refresh_view()

    def refresh_sensitivity(self):
        prj_btn_sensitive = self.has_problems(
            self.view.widgets.input_projection
        ) and not self.has_problems(self.view.widgets.filenames_lbl)
        self.view.widget_set_sensitive("projection_button", prj_btn_sensitive)
        sensitive = self.is_dirty() and not self.has_problems()
        # settings expander
        self.view.widget_set_sensitive("imp_settings_expander", sensitive)
        # accept buttons
        self.view.set_accept_buttons_sensitive(sensitive)

    def _get_filenames(self):
        """Run a filechooser and return the list of selected files."""
        filechooser = Gtk.FileChooserNative.new(
            _("Select shapefile(s) to import…"),
            None,
            Gtk.FileChooserAction.OPEN,
        )
        filter_ = Gtk.FileFilter.new()
        filter_.add_pattern("*.zip")
        filechooser.add_filter(filter_)
        filechooser.set_select_multiple(True)
        filechooser.set_current_folder(self.last_folder)
        filenames = []
        if filechooser.run() == Gtk.ResponseType.ACCEPT:
            filenames = filechooser.get_filenames()
        filechooser.destroy()
        return filenames

    def on_btnbrowse_clicked(self, _widget):
        self.view.widgets.filenames_lbl.set_text("--")
        widget = self.view.widgets.filenames_lbl
        self.remove_problem(None, widget=widget)
        filenames = self._get_filenames()

        # used only for display
        self.model.filename = ", ".join(Path(i).name for i in filenames)

        self.view.widgets.filenames_lbl.set_text(
            "\n".join(repr(i) for i in filenames)
        )
        if self.populate_shape_readers(filenames):
            self.add_problem(self.PROBLEM_NOT_SHAPEFILE, widget)
            return

        if self._projections_equal():
            self.set_crs_axy()
        else:
            self.add_problem(self.PROBLEM_PROJ_MISMATCH, widget)
            return

        all_equal = True

        if len(self.model.shape_readers) != 1:
            first = self.model.shape_readers[0]
            all_equal = all(i == first for i in self.model.shape_readers[1:])

        if not all_equal:
            self.add_problem(self.PROBLEM_MULTI_NOT_EQUAL, widget)
            return

        self._dirty = True

        self.refresh_sensitivity()

    def populate_shape_readers(self, file_names):
        """Given a list of file names attempt to populate the list of shape
        readers.

        If any of the files names are not .zip files they are returned."""
        # check we have a valid file and attempt to guess its crs etc.
        self.model.shape_readers = []
        self.remove_problem(self.PROBLEM_NOT_SHAPEFILE)
        errors = []
        for file_name in file_names:
            path = Path(file_name)
            logger.debug("filename = %s", str(path))

            if path.exists() and path.suffix == ".zip":
                self.__class__.last_folder = str(path.parent)
                self.model.shape_readers.append(ShapefileReader(str(path)))
            else:
                widget = self.view.widgets.filenames_lbl
                self.add_problem(self.PROBLEM_NOT_SHAPEFILE, widget)
                errors.append(str(path))
        return errors

    def _projections_equal(self):
        prj_strings = set()
        self.prj_string = None
        for shape_reader in self.model.shape_readers:
            prj_strings.add(shape_reader.get_prj_string())

        if not len(prj_strings) == 1:
            return False

        self.prj_string = prj_strings.pop()

        return True

    def set_crs_axy(self):
        crs = None
        axy = None
        widget = self.view.widgets.filenames_lbl
        self.remove_problem(self.PROBLEM_NOT_SHAPEFILE, widget)
        logger.debug("set crs axy")
        if self.prj_string:
            crs = self.proj_db.get_crs(self.prj_string)
            axy = self.proj_db.get_always_xy(self.prj_string)
        else:
            self.add_problem(self.PROBLEM_NOT_SHAPEFILE, widget)
        logger.debug("crs = %s", crs)
        logger.debug("axy = %s", axy)
        if crs:
            self.proj_db_match = crs
            # need to change the text for it to trigger a change
            self.view.widget_set_text("input_projection", "")
            self.view.widget_set_text("input_projection", crs)
            self.view.widget_set_active("cb_always_xy", axy)
        else:
            self.proj_db_match = None
            self.view.widget_set_text("input_projection", "")
            self.view.widget_set_text("input_projection", DEFAULT_IN_PROJ)

    def add_settings_box(self):
        """Start the settings box"""
        expander = self.view.widgets.imp_settings_expander
        child = expander.get_child()
        if child:
            expander.remove(child)
        self.settings_box = ShapefileImportSettingsBox(
            shape_reader=self.model.shape_readers[0]
        )
        expander.add(self.settings_box)
        self.settings_box.show_all()
        return False

    def on_settings_activate(self, _widget):
        logger.debug("settings expander toggled")
        if not self.model.shape_readers:
            return
        if not self.settings_box:
            self.add_settings_box()
        self.view.get_window().resize(1, 1)

    def on_always_xy_toggled(self, widget, value=None):
        logger.debug("always_xy toggled")
        # value is for testing only.
        self.on_check_toggled(widget, value=value)
        # only set the database when we are already matched.  Otherwise the act
        # of adding or changing should store it.
        if self.proj_text == self.proj_db_match:
            logger.debug("saving to db")
            self.proj_db.set_always_xy(self.prj_string, self.model.always_xy)

    def on_projection_changed(self, widget, value=None):
        self.remove_problem(self.PROBLEM_NO_PROJ)
        self.remove_problem(self.PROBLEM_PROJ_MISMATCH)
        self.proj_text = self.on_non_empty_text_entry_changed(
            widget, value=value
        )
        logger.debug(
            "proj changed proj_text = %s, match = %s",
            self.proj_text,
            self.proj_db_match,
        )
        if self.proj_text == self.proj_db_match:
            logger.debug("set projection_button to CORRECT")
            self.view.set_button_label("projection_button", "CORRECT")
        elif self.proj_db_match:
            self.add_problem(self.PROBLEM_PROJ_MISMATCH, widget)
            logger.debug("set projection_button to Change?")
            self.view.set_button_label("projection_button", "Change?")
        else:
            self.add_problem(self.PROBLEM_NO_PROJ, widget)
            logger.debug("set projection_button to Add?")
            self.view.set_button_label("projection_button", "Add?")
        self.refresh_sensitivity()

    def on_projection_btn_clicked(self, _widget):
        if self.model.projection and self.prj_string:
            logger.debug(
                "proj btn clicked proj_text = %s, match = %s",
                self.proj_text,
                self.proj_db_match,
            )
            if self.proj_db_match and self.proj_db_match != self.proj_text:
                self.proj_db.set_crs(
                    prj=self.prj_string, crs=self.model.projection
                )
                self.proj_db.set_always_xy(
                    prj=self.prj_string, axy=self.model.always_xy
                )
            else:
                self.proj_db.add(
                    prj=self.prj_string,
                    crs=self.model.projection,
                    axy=self.model.always_xy,
                )
            self.proj_db_match = self.model.projection
            self.on_projection_changed(self.view.widgets.input_projection)

    def cleanup(self):
        if self.settings_box:
            self.settings_box.cleanup()
        super().cleanup()
