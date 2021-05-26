# Copyright (c) 2021 Ross Demuth <rossdemuth123@gmail.com>
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

from zipfile import ZipFile
from pathlib import Path
from random import random

import logging
logger = logging.getLogger(__name__)

from shapefile import Reader
from sqlalchemy.orm import class_mapper

from gi.repository import Gtk

from bauble.utils.geo import ProjDB, transform
# NOTE importing shapefile Reader Writer above wipes out gettext _
from bauble.i18n import _
from bauble.prefs import (prefs,
                          debug_logging_prefs,
                          testing,
                          location_shapefile_prefs,
                          plant_shapefile_prefs)

if not testing and __name__ in prefs.get(debug_logging_prefs, []):
    logger.setLevel(logging.DEBUG)
logger.setLevel(logging.DEBUG)

import bauble
from bauble import db, task, pb_set_fraction
# NOTE: need to import the Note classes as we may need them.
from bauble.plugins.garden.plant import Plant, PlantNote  \
    # noqa pylint: disable=unused-import
from bauble.plugins.garden.location import Location, LocationNote  \
    # noqa pylint: disable=unused-import
from bauble.editor import GenericEditorView, GenericEditorPresenter

from bauble.utils.geo import DEFAULT_IN_PROJ


class ShapefileReader():
    """
    A wrapper for reading zipped shapefile data and the settings used.  By
    making changes here we can change how the shapefile data is read and hence
    imported into the database e.g. mapping fields to database fields.
    Primarily changes are made in the SettingsBox.
    """
    from contextlib import contextmanager

    def __init__(self, filename):
        """
        :param filename: string absolute path to zip file containing all
            shapefile component files (.shp, .prj, .dbf, .shx)
        """
        self._filename = None
        self.filename = filename
        self._type = None
        self._search_by = set()
        self._field_map = dict()

    def __guess_type(self):
        """
        try guess what type (Plant or Location) the record is by checking the
        for fields that match the default field maps.
        """
        plt = len([i for i in self.get_fields() if
                   prefs.get(f'{plant_shapefile_prefs}.fields',
                             {}).get(i[0])])
        loc = len([i for i in self.get_fields() if
                   prefs.get(f'{location_shapefile_prefs}.fields',
                             {}).get(i[0])])
        if plt > loc:
            logger.debug('type guess plt - plant:%s location:%s', plt, loc)
            return 'plant'
        if loc > plt:
            logger.debug('type guess loc - plant:%s location:%s', plt, loc)
            return 'location'
        logger.debug('could not guess type - plant:%s location:%s', plt, loc)
        return None

    @property
    def type(self):
        """the type of record as a string ('plant' or 'location') if this is
        not set manually an attempt to guess it will be made
        """
        if self._type is None:
            self._type = self.__guess_type()
        return self._type

    @type.setter
    def type(self, typ):
        self._search_by = set()
        self._field_map = {}
        self._type = typ

    @property
    def filename(self):
        """Absolute path to a zip file containting shapefile components,
        changing the value resets all other values."""
        return self._filename

    @filename.setter
    def filename(self, filename):
        # reset whenever the filename is reset.
        self._type = None
        self._search_by = set()
        self._field_map = {}
        self._filename = filename

    @property
    def search_by(self):
        """When trying to match a record from the shapefile which fields are
        used to match the database entry.  Unless manually set this will match
        the defaults for the type."""
        if not self._search_by:
            if self.type == 'plant':
                default_search_by = prefs.get(
                    f'{plant_shapefile_prefs}.search_by', {})
            elif self.type == 'location':
                default_search_by = prefs.get(
                    f'{location_shapefile_prefs}.search_by', {})
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
        """A dict for mapping shapefile fields to database fields.
        """
        if not self._field_map:
            if self.type == 'plant':
                default_map = prefs.get(f'{plant_shapefile_prefs}.fields',
                                        {})
            elif self.type == 'location':
                default_map = prefs.get(f'{location_shapefile_prefs}.fields',
                                        {})
            else:
                default_map = {}
            # rebuild the field map
            for field in self.get_fields():
                if field[0] in default_map.keys() and not isinstance(
                        default_map.get(field[0]), list):
                    self._field_map[field[0]] = default_map.get(field[0])
        return self._field_map

    @field_map.setter
    def field_map(self, fim):
        self._field_map = fim

    @contextmanager
    def _reader(self):
        """A contextmanager for the shapefile Reader.  Extracts the zip first.
        """
        z = ZipFile(self.filename, 'r')
        namelist = z.namelist()
        shp = z.open([i for i in namelist if i.endswith('.shp')][0])
        dbf = z.open([i for i in namelist if i.endswith('.dbf')][0])
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
            with ZipFile(self.filename, 'r') as z:
                namelist = z.namelist()
                with z.open(
                     [i for i in namelist if i.endswith('.prj')][0]) as prj:
                    prj_str = prj.read().decode('utf-8')
                prj_str = prj_str.strip()
            return prj_str if prj_str else None
        except Exception as e:   # pylint: disable=broad-except
            logger.debug("can't get .prj file string %s(%s)", type(e).__name__,
                         e)
            return None

    def get_fields(self):
        """
        :return: list of fields in the shapefile or None.
        """
        try:
            with self._reader() as reader:
                fields = list(reader.fields)
                logger.debug('fields = %s', fields)
            return fields if fields else []
        except Exception as e:   # pylint: disable=broad-except
            logger.debug("%s(%s)", type(e).__name__, e)
            return []

    def get_records_count(self):
        """
        :return: int count of records in the shapefile or None.
        """
        try:
            with self._reader() as reader:
                return len(reader)
        except Exception as e:   # pylint: disable=broad-except
            logger.debug("%s(%s)", type(e).__name__, e)
            return 0

    @contextmanager
    def get_records(self):
        """
        a contextmanager for shapeRecords (records and shapes) for the
        shapefile.
        """
        with self._reader() as reader:
            shape_records = reader.shapeRecords()
        try:
            yield shape_records
        finally:
            reader.close()


class SettingsBox(Gtk.ScrolledWindow):
    """
    Advanced settings used to change the behaviour of the ShapefileReader.
    """
    def __init__(self, shape_reader=None, grid=None):
        super().__init__(propagate_natural_height=True)
        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.shape_reader = shape_reader
        type_frame = Gtk.Frame(shadow_type=Gtk.ShadowType.NONE)
        type_label = Gtk.Label(justify=Gtk.Justification.LEFT)
        type_label.set_markup("<b>records type:</b>")
        type_frame.set_label_widget(type_label)
        type_combo = Gtk.ComboBoxText()
        type_combo.connect("changed", self.on_type_changed)
        type_combo.append_text('plant')
        type_combo.append_text('location')

        if shape_reader.type == 'plant':
            type_combo.set_active(0)
        elif shape_reader.type == 'location':
            type_combo.set_active(1)
        else:
            type_combo.set_active(-1)

        height = min(24 + (len(shape_reader.get_fields()) * 42), 550)
        self.set_min_content_height(height)
        type_frame.add(type_combo)
        self.box.add(type_frame)
        # for tests and avoids gtk errors
        if grid is None:
            grid = Gtk.Grid(column_spacing=6, row_spacing=6)

        self.grid = grid
        self.box.add(self.grid)
        self.add(self.box)
        self._construct_grid()

    def _construct_grid(self):
        """Create the field grid layout.
        """
        labels = ['name', 'type', 'length', 'dec places', 'database field',
                  'match database']
        for column, txt in enumerate(labels):
            label = Gtk.Label()
            label.set_markup(f'<b>{txt}</b>')
            self.grid.attach(label, column, 0, 1, 1)

        # NOTE can not use enumerate for row here
        row = 0
        for field in self.shape_reader.get_fields():
            # only list fields are needed
            if isinstance(field, list):
                row += 1
                for column, value in enumerate(field):
                    label = Gtk.Label()
                    label.set_text(str(value))
                    self.grid.attach(label, column, row, 1, 1)

                chk_button = Gtk.CheckButton.new_with_label('match')
                prop_button, schema_menu = self._get_prop_button(field,
                                                                 chk_button)
                prop_button.connect('button-press-event',
                                    self.on_prop_button_press_event,
                                    schema_menu)
                self.grid.attach(prop_button, column + 1, row, 1, 1)

                chk_button.connect('toggled', self.on_chk_button_change,
                                   (field[0], prop_button))
                tooltip = (
                    "Select to ensure this field matches the current data. If "
                    "a match can not be found the record will be skipped.\n\n"
                    "There must be at least one match field and a match must "
                    "return a single database entry.  (Best to use unique "
                    "or ID fields, if using ID fields it is almost always "
                    "best to also set Use ID to True)"
                )
                chk_button.set_tooltip_text(tooltip)
                if field[0] in self.shape_reader.search_by:
                    chk_button.set_active(True)
                self.grid.attach(chk_button, column + 2, row, 1, 1)

    @staticmethod
    def relation_filter(prop):
        # Avoid offering many relationships
        try:
            if prop.prop.uselist:
                return False
        except AttributeError:
            pass
        # force users to use the hybrid property
        if prop.key == '_default_vernacular_name':
            return False
        return True

    @staticmethod
    def on_prop_button_press_event(widget, event, menu):  \
            # pylint: disable=unused-argument
        menu.popup(None, None, None, None, event.button, event.time)

    def _get_prop_button(self, field, chk_button):
        if self.shape_reader.type == 'plant':
            model = Plant
        elif self.shape_reader.type == 'location':
            model = Location
        db_field = self.shape_reader.field_map.get(field[0], '')
        prop_button = Gtk.Button()
        prop_button.props.use_underline = False

        # pylint: disable=unused-argument
        def menu_activated(widget, path, prop):
            """
            Closure used to set the field_map and button label.
            """
            prop_button.get_style_context().remove_class('err-btn')
            if path:
                prop_button.set_label(path)
                self.shape_reader.field_map[field[0]] = path
            else:
                if self.shape_reader.field_map.get(field[0]):
                    del self.shape_reader.field_map[field[0]]
                    chk_button.set_active(False)
                prop_button.set_label(_('Choose a property…'))

        from bauble.search import SchemaMenu
        schema_menu = SchemaMenu(
            class_mapper(model),
            menu_activated,
            relation_filter=self.relation_filter,
            private=True,
            selectable_relations=False
        )

        schema_menu.append(Gtk.SeparatorMenuItem())
        for item in ['Note', '']:
            xtra = Gtk.MenuItem(item, use_underline=False)
            xtra.connect('activate', menu_activated, item, None)
            schema_menu.append(xtra)

        schema_menu.show_all()

        menu_activated(None, db_field, None)
        tooltip = (
            'NOTE: Not all fields can be imported and some may '
            'cause unexpected results.  Take caution and consider '
            'BACKING UP your data first.\n\nSettings here '
            'override settings above.  Fields left blank will not '
            'be imported.  "Note" designates the field is to be '
            'added as a note of the item.  The current "name" '
            'will be used as the category for the note.'
        )
        prop_button.set_tooltip_text(tooltip)
        return prop_button, schema_menu

    def on_type_changed(self, widget):
        if self.shape_reader.type != widget.get_active_text():
            self.shape_reader.type = widget.get_active_text()
            while self.grid.get_child_at(0, 0) is not None:
                self.grid.remove_row(0)
            self._construct_grid()
            self.grid.show_all()

    def on_chk_button_change(self, widget, data):
        field, prop_button = data
        prop_button.get_style_context().remove_class('err-btn')
        if widget.get_active() is True:
            self.shape_reader.search_by.add(field)
            if prop_button.get_label() not in [
                    v for k, v in self.shape_reader.field_map.items() if k in
                    self.shape_reader.search_by]:
                prop_button.get_style_context().add_class('err-btn')
        else:
            logging.debug('deleting %s from search_by', field)
            self.shape_reader.search_by.remove(field)


class ShapefileImporter():
    """
    Import shapefile data into the database.
    """
    # pylint: disable=too-many-instance-attributes

    OPTIONS_MAP = [
        {'add_geo': True, 'update': False, 'add_new': False, 'all_data': False
         },
        {'add_geo': True, 'update': True, 'add_new': False, 'all_data': False},
        {'add_geo': True, 'update': True, 'add_new': False, 'all_data': True},
        {'add_geo': False, 'update': False, 'add_new': True, 'all_data': True},
        {'add_geo': True, 'update': True, 'add_new': True, 'all_data': True},
    ]

    def __init__(self):
        # widget fields
        # NOTE use string NOT int for option
        self.option = '0'
        self.filename = None
        self.projection = DEFAULT_IN_PROJ
        self.always_xy = True
        self.use_id = False
        # view and presenter
        if testing:
            from bauble.editor import MockView
            self.view = MockView()
        else:
            self.view = ShapefileImportDialogView()
        self.presenter = ShapefileImportDialogPresenter(self, self.view)
        # reader
        self.shape_reader = ShapefileReader(None)
        # record class
        self.model = None
        # keepng track
        self._committed = 0
        self._errors = 0
        self._is_new = False

    def start(self):
        """Start the shapefile importer UI.  On response run the import task.
        :return: Gtk.ResponseType"""
        response = self.presenter.start()
        if response == Gtk.ResponseType.OK:
            if bauble.gui is not None:
                bauble.gui.set_busy(True)
            self.run()
            if bauble.gui is not None:
                bauble.gui.set_busy(False)
            self.presenter.cleanup()
        logger.debug('responded %s', response)
        return response

    def run(self):
        """Queues the import task"""
        task.clear_messages()
        task.queue(self._import_task(self.OPTIONS_MAP[int(self.option)]))
        msg = (f'import {self.shape_reader.type}s complete: '
               f'{self._committed} records committed, '
               f'{self._errors} errors encounted')
        task.set_message(msg)

    def _import_task(self, options):
        """The import task.

        Yields occasionally to allow the UI to update.

        :param options: dict of settings used to decide when/what to add.
        """
        session = db.Session()
        logger.debug('importing %s with option %s', self.filename, self.option)
        record_count = self.shape_reader.get_records_count()
        records_added = records_done = 0
        if self.shape_reader.type == 'plant':
            self.model = Plant
        elif self.shape_reader.type == 'location':
            self.model = Location

        with self.shape_reader.get_records() as records:
            for record in records:
                self._is_new = False
                item = self.get_db_item(session, record,
                                        options.get('add_new'))

                pb_set_fraction(records_done / record_count)
                msg = (f'{self._committed} committed, '
                       f'{self._errors} errors')
                task.set_message(msg)
                yield
                records_done += 1
                if item is None:
                    continue
                if item.geojson:
                    if options.get('update'):
                        if not self.add_db_geo(session, item, record):
                            logger.debug('add_db_geo failed')
                            continue
                        records_added += 1
                        if options.get('all_data'):
                            logger.debug('adding all data')
                            self.add_db_data(session, item, record)
                else:
                    if self._is_new or options.get('add_geo'):
                        if not self.add_db_geo(session, item, record):
                            logger.debug('add_db_geo failed')
                            continue
                        records_added += 1
                        if options.get('all_data'):
                            logger.debug('adding all data')
                            self.add_db_data(session, item, record)

                # commit every record catches errors and avoids losing records.
                self.commit_db(session)

        session.close()
        try:
            bauble.gui.get_view().update()
        except Exception:   # pylint: disable=broad-except
            pass

    def get_db_item(self, session, record, add):
        """Get an appropriate database instance to add the record to.

        :param session: instance of db.Session()
        :param record: a shapefile.Record().shapefileRecord() value
        :param add: bool(), whether or not to add new records to the database
        """
        if any(self.shape_reader.field_map.get(i) == 'id' for i in
               self.shape_reader.search_by):
            # id search by
            id_field = [i for i in self.shape_reader.search_by if
                        self.shape_reader.field_map.get(i) == 'id'][0]
            id_val = record.record.as_dict().get(id_field)
            logger.debug('searching id')
            return session.query(self.model).get(id_val)

        # more complex
        in_dict_mapped = dict()
        for field in self.shape_reader.search_by:
            logger.debug('searching by %s = %s', field,
                         self.shape_reader.field_map.get(field))
            in_dict_mapped[self.shape_reader.field_map.get(field).split('.')[0]
                           ] = record.record.as_dict().get(field)

        if in_dict_mapped:
            item = self.model.retrieve(session, in_dict_mapped)

            if item:
                return item

        if add and self.model:
            logger.debug('new item')
            self._is_new = True
            return self.model()

        return None

    def add_db_geo(self, session, item, record):
        """Add the __geo_interface__ data from the shapefile record to the
        database item's geojson field

        Coordinates are projected to the system CRS as needed.

        :param session: instance of db.Session()
        :param item: database instance
        :param record: a shapefile.Record().shapefileRecord() value
        """
        logger.debug('adding geojson data')
        geojson = transform(record.shape.__geo_interface__,
                            in_crs=self.projection,
                            always_xy=self.always_xy)
        if not geojson:
            logger.debug('error transforming %s', record)
            return False
        item.geojson = geojson

        session.add(item)
        return True

    def add_db_data(self, session, item, record):
        """Add the column data from the shapefile record to the database item.

        Uses the field_map to map the shapefile columns to the correct
        database column.  Where a path is provided attempt to create a
        corresponding entry for it.

        :param session: instance of db.Session()
        :param item: database instance
        :param record: a shapefile.Record().shapefileRecord() value
        """
        out_dict = dict()
        in_dict = record.record.as_dict()
        logger.debug('field_map = %s', self.shape_reader.field_map)
        for sf_col, db_path in self.shape_reader.field_map.items():
            if db_path.startswith('Note'):
                # If the note has supplied a category use it.
                if db_path.endswith(']') and db_path.find('[category='):
                    note_category = db_path.split('[category=')[1]
                    note_category = note_category[:-1].strip('"').strip("'")
                else:
                    # use the field name
                    note_category = sf_col
                note_text = in_dict.get(sf_col)
                if not note_text:
                    continue
                note_model = self.model.__mapper__.relationships.get(
                    'notes').mapper.class_
                note_dict = {
                    self.model.__name__.lower(): item,
                    'category': note_category,
                    'note': note_text
                }
                new_note = note_model(**note_dict)
                logger.debug('adding_note: %s', note_dict)
                session.add(new_note)
            elif (db_path == 'id' and
                  (not in_dict.get(sf_col) or not self.use_id)):
                # for new entries skip the id when id has no value or we have
                # not selected to use it
                continue
            else:
                out_dict[db_path] = in_dict.get(sf_col)

        organised = self.organise_record(out_dict)
        item = add_rec_to_db(session, item, organised)
        logger.debug('adding item : %s', item)
        session.add(item)

    def commit_db(self, session):
        from sqlalchemy.exc import IntegrityError
        try:
            session.commit()
            self._committed += 1
            logger.debug('committing')
        except IntegrityError as e:
            self._errors += 1
            logger.debug('Commit failed with %s', e)
            session.rollback()

    @staticmethod
    def organise_record(rec):
        record = {}
        for k in sorted(rec, key=lambda i: i.count('.'), reverse=True):
            # get rid of empty strings
            record[k] = None if rec[k] == '' else rec[k]
        compressed = dict()
        for k, v in record.items():
            if '.' in k:
                path, atr = k.rsplit('.', 1)
                compressed[path] = compressed.get(path, {})
                compressed[path][atr] = v
            else:
                compressed[k] = v
        return compressed


def add_rec_to_db(session, item, rec):
    """Add or update the item record in the database including any related
    records.

    :param session: instance of db.Session()
    :param item: an instance of a sqlalchemy table
    :param rec: dict of the records to add, ordered so that related records
             are first so that they are found, created, or updated first.
             Keys are paths from the item class to either fields of that class
             or to related tables.  Values are item columns values or the
             related table columns and values as a nested dict.
    """
    # peel of the first record to work on
    first, *remainder = rec.items()
    remainder = dict(remainder)
    key, value = first
    logger.debug('adding key: %s with value: %s', key, value)
    # related records
    if isinstance(value, dict):
        # after this "value" will be in the session
        value = db.get_create_or_update(
            session, db.get_related_class(type(item), key), **value)
        root, atr = key.rsplit('.', 1) if '.' in key else (None, key)
        # NOTE default vernacular names need to be added directly as they use
        # their own methods,
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
        # This will generally work but is not full proof.  It is preferable to
        # use the hybrid_property default_vernacular_name
        # Could probably remove this now that _default_vernacular_name is
        # blocked in relation_filter
        if (root and root.endswith('._default_vernacular_name') and
                atr == 'vernacular_name'):
            root = root[:-len('._default_vernacular_name')]
            atr = 'default_vernacular_name'
        if remainder.get(root):
            remainder[root][atr] = value
        # source, contact etc. with a linking 1-1 table
        elif root and '.' in root and remainder.get(root.rsplit('.', 1)[0]):
            link, atr2 = root.rsplit('.', 1)
            from operator import attrgetter
            try:
                link_item = attrgetter(root)(item)    # existing entries
            except AttributeError:
                link_item = db.get_related_class(type(item), root)()
                session.add(link_item)
            if link_item:
                setattr(link_item, atr, value)
                logger.debug('adding: %s to %s', atr2, link)
                remainder[link][atr2] = link_item

    # if there are more records continue to add them
    if len(remainder) > 0:
        add_rec_to_db(session, item, remainder)

    # once all records are accounted for add them to item in reverse
    logger.debug('setattr on object: %s with name: %s and value: %s',
                 item, key, value)
    setattr(item, key, value)
    return item


class ShapefileImportDialogView(GenericEditorView):
    """
    This view is mostly just inherited from GenericEditorView and kept as
    simple as possible.
    """

    OPTIONS = [
        ('0', 'add missing spatial data for existing records'),
        ('1', 'add or update spatial data for existing records'),
        ('2', 'add or update all data for existing records'),
        ('3', 'add new records only'),
        ('4', 'add or update all records'),
    ]

    # tooltips are the reason to subclass GenericEditorView
    _tooltips = {
        'option_combo': _("Ordered roughly least destructive to most "
                          "destructive. The primary purpose of this plugin is "
                          "to add spatial data to existing records and hence "
                          "adding new records is limited to plants, locations "
                          "and associated notes. When adding plants the "
                          "accession and location must already exist. Some "
                          "fields are read only, e.g. species and family "
                          "epithets are ignored during imports."),
        'input_filename': _("The full path to the zip file containing "
                            "the shapefile."),
        'btn_file_chooser': _("Browse to the zipfile that contains "
                              "the shapefile and other required files."),
        'input_projection': _("The shapefile's projection control parameter, "
                              "can contain any string parameters accepted by "
                              "pyproj.crs.CRS().  An EPSG code is most likely "
                              "the simplest to use.   see: https://pyproj4."
                              "github.io/pyproj/stable/api/crs/crs.html"),
        'projection_button': _("If no projection control parameters for the "
                               ".prj file included with the selected "
                               "shapefile, adding it to the list.  If you "
                               "believe it is currently wrong changing it."),
        'cb_always_xy': _("Use the traditional GIS order long, lat.  Some GIS "
                          "systems do this some don't.  You may need to use "
                          "trial and error to decide if you need to use this "
                          "for each data source. (if all items turn up in the "
                          "wrong place this could be the cause.) The state is "
                          "saved on clicking OK."),
        'cb_use_id': _("CAUTION: use this only if you are sure the shapefile "
                       "data will match the database, e.g. was exported from "
                       "it with the ID value.  Consider backing up your data "
                       "first. Collisions could corrupt records.  This option "
                       "is only intended for situation where there has been a "
                       "change in one of the other identifying fields of the "
                       "records. (e.g. code)")
    }

    def __init__(self):
        filename = str(Path(__file__).resolve().parent / 'shapefile.glade')
        parent = bauble.gui.window
        root_widget_name = 'shapefile_import_dialog'
        super().__init__(filename, parent, root_widget_name)
        self.init_translatable_combo(self.widgets.option_combo, self.OPTIONS)


class ShapefileImportDialogPresenter(GenericEditorPresenter):
    """ The presenter for the shapefile import dialog.
    """

    widget_to_field_map = {
        'option_combo': 'option',
        'input_filename': 'filename',
        'input_projection': 'projection',
        'cb_always_xy': 'always_xy',
        'cb_use_id': 'use_id',
    }
    view_accept_buttons = ['imp_button_cancel', 'imp_button_ok']

    PROBLEM_NOT_SHAPEFILE = random()
    PROBLEM_NO_PROJ = random()
    PROBLEM_PROJ_MISMATCH = random()

    last_folder = str(Path.home())

    def __init__(self, model, view):
        super().__init__(model=model, view=view)
        self.prj_string = None
        self.proj_db_match = None
        self.proj_text = None

        if testing:
            self.proj_db = ProjDB(db_path=':memory:')
        else:
            self.proj_db = ProjDB()
            self.add_problem(self.PROBLEM_EMPTY,
                             self.view.widgets.input_filename)
        self.refresh_view()

    def refresh_sensitivity(self):
        sensitive = False
        self.view.widget_set_sensitive('projection_button', (
            self.has_problems(self.view.widgets.input_projection) and
            not self.has_problems(self.view.widgets.input_filename)
        ))
        if self.is_dirty() and not self.has_problems():
            sensitive = True
        # settings expander
        self.view.widget_set_sensitive('imp_settings_expander', sensitive)
        # accept buttons
        self.view.set_accept_buttons_sensitive(sensitive)

    def on_btnbrowse_clicked(self, widget):  # pylint: disable=unused-argument
        self.view.run_file_chooser_dialog(
            _("Select a shapefile"),
            None,
            Gtk.FileChooserAction.OPEN, None,
            self.__class__.last_folder,
            'input_filename'
        )
        self.refresh_sensitivity()

    def on_filename_entry_changed(self, widget, value=None):
        # check we have a valid file and attempt to guess its crs etc.
        self.remove_problem(self.PROBLEM_NOT_SHAPEFILE)
        path = Path(self.on_non_empty_text_entry_changed(widget, value))
        logger.debug('filename changed to %s', str(path))

        if path.exists() and path.suffix == '.zip':
            self.__class__.last_folder = str(path.parent)
            self.model.shape_reader.filename = str(path)
            self.prj_string = self.model.shape_reader.get_prj_string()
            crs = None
            if self.prj_string:
                crs = self.proj_db.get_crs(self.prj_string)
                axy = self.proj_db.get_always_xy(self.prj_string)
            else:
                self.add_problem(self.PROBLEM_NOT_SHAPEFILE, widget)
            if crs:
                self.proj_db_match = crs
                # need to change the text for it to trigger a change
                self.view.widget_set_text('input_projection', '')
                self.view.widget_set_text('input_projection', crs)
                self.view.widget_set_active('cb_always_xy', axy)
            else:
                self.proj_db_match = None
                self.view.widget_set_text('input_projection', '')
                self.view.widget_set_text('input_projection', DEFAULT_IN_PROJ)
        else:
            self.add_problem(self.PROBLEM_NOT_SHAPEFILE, widget)

        self.refresh_sensitivity()
        self._settings_expander()

    def _settings_expander(self):
        """
        Start the settings box
        """
        expander = self.view.widgets.imp_settings_expander
        child = expander.get_child()
        if child:
            expander.remove(child)
        settings_box = SettingsBox(shape_reader=self.model.shape_reader)
        expander.add(settings_box)
        settings_box.show_all()
        return False

    def on_settings_activate(self, widget):  # pylint: disable=unused-argument
        logger.debug('settings expander toggled')
        self.view.get_window().resize(1, 1)

    def on_always_xy_toggled(self, widget, value=None):
        logger.debug('always_xy toggled')
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
        self.proj_text = self.on_non_empty_text_entry_changed(widget,
                                                              value=value)
        logger.debug('proj changed proj_text = %s, match = %s', self.proj_text,
                     self.proj_db_match)
        if self.proj_text == self.proj_db_match:
            self.view.set_button_label('projection_button', 'CORRECT')
        elif self.proj_db_match:
            self.add_problem(self.PROBLEM_PROJ_MISMATCH, widget)
            self.view.set_button_label('projection_button', 'Change?')
        else:
            self.add_problem(self.PROBLEM_NO_PROJ, widget)
            self.view.set_button_label('projection_button', 'Add?')
        self.refresh_sensitivity()

    def on_projection_btn_clicked(self, widget): \
            # noqa pylint: disable=unused-argument
        if self.model.projection and self.prj_string:
            logger.debug('proj btn clicked proj_text = %s, match = %s',
                         self.proj_text, self.proj_db_match)
            if self.proj_db_match and self.proj_db_match != self.proj_text:
                self.proj_db.set_crs(prj=self.prj_string,
                                     crs=self.model.projection)
                self.proj_db.set_always_xy(prj=self.prj_string,
                                           axy=self.model.always_xy)
            else:
                self.proj_db.add(prj=self.prj_string,
                                 crs=self.model.projection,
                                 axy=self.model.always_xy)
            self.proj_db_match = self.model.projection
            self.on_projection_changed(self.view.widgets.input_projection)
