# Copyright (c) 2021-2022 Ross Demuth <rossdemuth123@gmail.com>
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
Export data to shapefiles (zip file with all component files).
"""

from zipfile import ZipFile
from pathlib import Path
from tempfile import TemporaryDirectory
from random import random

import logging
logger = logging.getLogger(__name__)

from shapefile import Writer

from gi.repository import Gtk, Gdk
from gi.repository import GLib

from sqlalchemy.orm import class_mapper

from bauble.utils.geo import ProjDB
from bauble.meta import get_default
# NOTE importing shapefile Writer above wipes out gettext _
from bauble.i18n import _
from bauble import prefs

import bauble
from bauble import db, task, pb_set_fraction
# NOTE: need to import the Note classes as we may need them.
from bauble.plugins.garden.plant import Plant, PlantNote  \
    # noqa pylint: disable=unused-import
from bauble.plugins.garden.location import Location, LocationNote  \
    # noqa pylint: disable=unused-import
from bauble.editor import GenericEditorView, GenericEditorPresenter

from . import LOCATION_SHAPEFILE_PREFS, PLANT_SHAPEFILE_PREFS
from .. import GenericExporter

NAME = 0
TYPE = 1
SIZE = 2
PATH = 3

TYPE_MAP = {
    'Enum': 'C',
    'str': 'C',
    'int': 'N',
    'float': 'F',
    'bool': 'L',
    'DateTime': 'D',
    'Date': 'D'
}

MAX_LENGTH = 255
MAX_PRECIS = 20


def get_field_properties(model, path):
    """Get the appropriate shapefile type and size proporties for a database
    field.
    """
    if path in ['Note', 'Empty']:
        return 'C', MAX_LENGTH

    if '.' in path:
        mapper = model.__mapper__
        model, path = path.rsplit('.', 1)
        for step in model.split('.'):
            mapper = mapper.relationships.get(step).mapper
        model = mapper.class_

    field_type = 'str'
    size = None

    try:
        path_type = getattr(model, path).type
    except AttributeError:
        # relationships
        if (path == model.__table__.key or
                hasattr(getattr(getattr(model, path), 'property'),
                        'back_populates')):
            return 'C', MAX_LENGTH
    try:
        field_type = path_type.python_type.__name__
    except NotImplementedError:
        field_type = path_type.__class__.__name__
    field_type = TYPE_MAP.get(field_type)
    if field_type == 'F':
        if hasattr(path_type, 'precision'):
            size = path_type.precision or 10
    if hasattr(path_type, 'length'):
        size = path_type.length or MAX_LENGTH
    return field_type, size


class ShapefileExportSettingsBox(Gtk.ScrolledWindow):
    """Advanced settings used to set the database fields to export.

    :param model: Plant or Location, the class of exports that the settings are
        intended for.
    :param fields: dictionary of fields settings used for the export.
    :param gen_settings: dictionary of auto-generated points settings (Plants).
    :param resize_func: function that can resize the presenter window.
    :param grid: a grid to use for widgets (for testing).
    """
    def __init__(self, model,   # pylint: disable=too-many-arguments
                 fields=None,
                 gen_settings=None,
                 resize_func=None,
                 grid=None):
        super().__init__(propagate_natural_height=True)
        self.fields = fields
        self.model = model
        self.resize_func = resize_func
        self.gen_settings = gen_settings
        # for testing
        if grid is None:
            grid = Gtk.Grid(column_spacing=6, row_spacing=6)

        self.grid = grid
        self.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.add(self.grid)
        self.type_vals = {k: v for v, k in enumerate(set(TYPE_MAP.values()))}
        self._construct_grid()
        self.grid.show_all()
        GLib.idle_add(self.resize_func)

    def _construct_grid(self): \
            # pylint: disable=too-many-locals,too-many-statements
        """Create the field grid layout."""
        labels = ['name', 'type', 'length/places', 'database field']
        for column, txt in enumerate(labels):
            label = Gtk.Label()
            label.set_markup(f'<b>{txt}</b>')
            self.grid.attach(label, column, 0, 1, 1)

        logger.debug('export settings box shapefile fields: %s', self.fields)
        # make attach_row available outside for loop scope.
        attach_row = 0
        for row, (name, typ, size, path) in enumerate(self.fields):
            attach_row = row + 1
            name_entry = Gtk.Entry(max_length=10)
            name_entry.set_text(name or '')
            name_entry.set_width_chars(11)
            name_entry.connect('changed', self.on_name_entry_changed)
            self.grid.attach(name_entry, NAME, attach_row, 1, 1)
            # type
            type_combo = Gtk.ComboBoxText()
            for k in self.type_vals:
                type_combo.append_text(k)
            if typ:
                type_combo.set_active(self.type_vals.get(typ))
            # type_combo.set_width_chars(1)
            type_combo.set_popup_fixed_width(True)
            type_combo.connect('changed', self.on_type_combo_changed)
            self.grid.attach(type_combo, TYPE, attach_row, 1, 1)
            # length or decimal places
            length_adj = Gtk.Adjustment(upper=MAX_LENGTH, step_increment=1,
                                        page_increment=10)
            length_entry = Gtk.SpinButton(adjustment=length_adj,
                                          numeric=True)
            if typ in ['F', 'N']:
                length_adj.set_upper(MAX_PRECIS)
            if size:
                length_entry.set_value(int(size))
            length_entry.set_sensitive(typ in ('C', 'F', 'N'))
            # length_entry.set_width_chars(4)
            length_entry.connect('value-changed', self.on_length_entry_changed)
            self.grid.attach(length_entry, SIZE, attach_row, 1, 1)

            self._add_prop_button(path, attach_row)
            remove_button = Gtk.Button.new_from_icon_name(
                'list-remove-symbolic', Gtk.IconSize.BUTTON
            )
            remove_button.connect('clicked', self.on_remove_button_clicked)
            remove_button.set_tooltip_text(
                _("click to remove a row, drag and drop to move."))
            remove_button.connect(
                'drag-begin', lambda w, c:
                w.drag_source_set_icon_name('list-remove-symbolic')
            )
            remove_button.connect('drag-data-get',
                                  self.on_remove_button_dragged)
            remove_button.connect('drag-data-received',
                                  self.on_remove_button_dropped)
            remove_button.drag_dest_set(Gtk.DestDefaults.ALL, [],
                                        Gdk.DragAction.COPY)
            remove_button.drag_source_set(Gdk.ModifierType.BUTTON1_MASK, [],
                                          Gdk.DragAction.COPY)
            remove_button.drag_source_add_text_targets()
            remove_button.drag_dest_add_text_targets()
            self.grid.attach(remove_button, 4, attach_row, 1, 1)
        add_button = Gtk.Button.new_from_icon_name('list-add-symbolic',
                                                   Gtk.IconSize.BUTTON)
        add_button.set_halign(Gtk.Align.START)
        add_button.connect('clicked', self.on_add_button_clicked)
        self.grid.attach(add_button, 0, attach_row + 1, 1, 1)
        if self.gen_settings:
            gen_hbox = Gtk.Box()
            gen_chkbtn = Gtk.CheckButton(label="Auto-generate points")
            gen_chkbtn.connect('toggled', self.on_gen_chkbtn_toggled)
            gen_hbox.pack_start(gen_chkbtn, False, False, 3)
            self.gen_button = Gtk.Button(label="generate points settings")
            self.gen_button.set_sensitive(False)
            self.gen_button.connect('clicked', self.on_gen_button_clicked)
            gen_hbox.pack_start(self.gen_button, False, False, 3)
            self.grid.attach(gen_hbox, 0, attach_row + 2, 5, 1)

    def generated_points_settings_dialog(self):
        """Settings for generated points."""
        from bauble.utils import create_message_dialog
        msg = _("Auto generated points for plants that don't currently "
                "have geojson entries. (only avialable when using search "
                "items and limited to 100 points - will fail otherwise)"
                "\n\nA default starting point can be set by setting the "
                "instituion's latitude and longitude in the Institution "
                "Editor in the tools menu.")
        dialog = create_message_dialog(msg=msg)
        dialog.set_keep_above(True)
        box = dialog.get_message_area()
        grid = Gtk.Grid(column_spacing=6, row_spacing=6)
        box.add(grid)
        x_adj = Gtk.Adjustment(upper=1000, lower=-1000, step_increment=0.0001,
                               page_increment=10)
        gen_x_entry = Gtk.SpinButton(adjustment=x_adj, digits=10)
        gen_x_entry.set_tooltip_text("set the X coordinate for the starting "
                                     "point. Default is the institution's "
                                     "longitude.")
        gen_x_entry.connect('value-changed', self.on_coord_changed, 1)
        gen_x_entry.set_value(self.gen_settings.get('start')[1])
        y_adj = Gtk.Adjustment(upper=1000, lower=-1000, step_increment=0.0001,
                               page_increment=10)
        gen_y_entry = Gtk.SpinButton(adjustment=y_adj, digits=10)
        gen_y_entry.set_tooltip_text("set the Y coordinate for the starting "
                                     "point. Default is the institution's "
                                     "latitude.")
        gen_y_entry.connect('value-changed', self.on_coord_changed, 0)
        gen_y_entry.set_value(self.gen_settings.get('start')[0])
        gen_combo = Gtk.ComboBoxText()
        gen_combo.set_tooltip_text('Set the axis for the line of '
                                   'auto-generated plant points.')
        for i in ['', 'NS', 'EW']:
            gen_combo.append_text(i)
        gen_combo.connect('changed', self.on_gen_combo_changed)
        increment_adj = Gtk.Adjustment(upper=1000, lower=-1000,
                                       step_increment=0.0001,
                                       page_increment=10)
        gen_increment_entry = Gtk.SpinButton(adjustment=increment_adj,
                                             digits=10)
        gen_increment_entry.connect('value-changed', self.on_increment_changed)
        gen_increment_entry.set_value(self.gen_settings.get('increment'))
        gen_increment_entry.set_tooltip_text(
            'set the spacing and direction (+/-) of the line of plants.')
        grid.attach(Gtk.Label(label='X:'), 0, 0, 1, 1)
        grid.attach(gen_x_entry, 1, 0, 1, 1)
        grid.attach(Gtk.Label(label='Y:'), 0, 1, 1, 1)
        grid.attach(gen_y_entry, 1, 1, 1, 1)
        grid.attach(Gtk.Label(label='axis:'), 0, 2, 1, 1)
        grid.attach(gen_combo, 1, 2, 1, 1)
        grid.attach(Gtk.Label(label='increment:'), 0, 3, 1, 1)
        grid.attach(gen_increment_entry, 1, 3, 1, 1)
        dialog.resize(1, 1)
        dialog.show_all()
        return dialog

    def on_gen_button_clicked(self, _widget):
        dialog = self.generated_points_settings_dialog()
        response = dialog.run()
        dialog.destroy()
        if response == Gtk.ResponseType.OK:
            self.gen_button.get_style_context().remove_class('err-btn')
        else:
            self.reset_gen_settings()
            self.gen_button.get_style_context().add_class('err-btn')

    def reset_gen_settings(self):
        session = db.Session()
        # These should always have some value, even if it is Null as its
        # set when a new database is started
        start_lat = get_default('inst_geo_latitude',
                                session=session).value
        start_lng = get_default('inst_geo_longitude',
                                session=session).value
        # mutate the original dict - don't overwrite it with a new one.
        self.gen_settings['start'][0] = float(start_lng or 0.0)
        self.gen_settings['start'][1] = float(start_lat or 0.0)
        self.gen_settings['increment'] = 0.00001
        self.gen_settings['axis'] = ''

    def on_gen_chkbtn_toggled(self, widget):
        if widget.get_active() is True:
            self.reset_gen_settings()
            self.gen_button.get_style_context().add_class('err-btn')
            self.gen_button.set_sensitive(True)
        else:
            self.gen_button.get_style_context().remove_class('err-btn')
            self.gen_button.set_sensitive(False)

    def on_increment_changed(self, widget):
        self.gen_settings['increment'] = widget.get_value()

    def on_coord_changed(self, widget, axis):
        self.gen_settings['start'][axis] = widget.get_value()

    def on_gen_combo_changed(self, widget):
        self.gen_settings['axis'] = widget.get_active_text()

    # pylint: disable=too-many-arguments
    def on_remove_button_dragged(self, widget, drag_context, data, info,
                                 time):
        logger.debug('drag event = context: %s data: %s info: %s time: %s',
                     drag_context, data, info, time)
        row = self.grid.child_get_property(widget, 'top_attach')
        data.set_text(str(row), len(str(row)))

    def on_remove_button_dropped(self, widget, drag_context, x, y, data, info,
                                 time):
        logger.debug('drop event = context: %s x: %s y: %s data: %s info: %s '
                     'time: %s', drag_context, x, y, data, info, time)
        source_row = int(data.get_text()) - 1
        row_dest = self.grid.child_get_property(widget, 'top_attach') - 1
        self.fields.insert(row_dest, self.fields.pop(source_row))
        self._rebuild_grid()
    # pylint: enable=too-many-arguments

    def _rebuild_grid(self):
        while self.grid.get_child_at(0, 0) is not None:
            self.grid.remove_row(0)
        self._construct_grid()
        self.grid.show_all()

    def on_name_entry_changed(self, widget):
        attached_row = self.grid.child_get_property(widget, 'top_attach')
        row = attached_row - 1
        logger.debug('name_entry changed %s', self.fields[row])
        self.fields[row][NAME] = widget.get_text()

    def on_type_combo_changed(self, widget):
        attached_row = self.grid.child_get_property(widget, 'top_attach')
        row = attached_row - 1
        typ = widget.get_active_text()
        size_widget = self.grid.get_child_at(2, attached_row)
        size_widget.set_sensitive(typ in ('C', 'F', 'N'))
        if typ == 'C':
            size_widget.get_adjustment().set_upper(MAX_LENGTH)
        elif typ in ['N', 'F']:
            size_widget.get_adjustment().set_upper(20)
        self.fields[row][TYPE] = typ

    def on_length_entry_changed(self, widget):
        attached_row = self.grid.child_get_property(widget, 'top_attach')
        row = attached_row - 1
        lgth = widget.get_value_as_int()
        if lgth:
            self.fields[row][SIZE] = lgth
        else:
            self.fields[row][SIZE] = None

    def on_remove_button_clicked(self, widget):
        attached_row = self.grid.child_get_property(widget, 'top_attach')
        row = attached_row - 1
        self.grid.remove_row(self.grid.child_get_property(widget,
                                                          'top_attach'))
        del self.fields[row]
        self.resize_func()

    def on_add_button_clicked(self, _widget):
        # add extra field
        self.fields.append([None, None, None, None])
        # should reorder rather than rebuild
        self._rebuild_grid()
        self.resize_func()

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
    def on_prop_button_press_event(_widget, event, menu):
        menu.popup_at_pointer(event)

    def _add_prop_button(self, db_field, row):
        prop_button = Gtk.Button(hexpand=True, use_underline=False)

        def menu_activated(_widget, path, _prop):
            """Closure of sorts, used to set the field_map and button label.
            """
            attached_row = self.grid.child_get_property(prop_button,
                                                        'top_attach')
            row = attached_row - 1
            prop_button.get_style_context().remove_class('err-btn')
            if path:
                prop_button.set_label(path)
            else:
                prop_button.set_label(_('Choose a property…'))
                prop_button.get_style_context().add_class('err-btn')
                return

            if self.fields[row][PATH] != path:
                self.fields[row][PATH] = path
                typ, size = get_field_properties(self.model, path)
                self.fields[row][TYPE] = typ
                self.fields[row][SIZE] = size
                self.grid.get_child_at(TYPE, attached_row).set_active(
                    self.type_vals.get(typ))
                self.grid.get_child_at(SIZE, attached_row).set_text(
                    str(size or ''))

        from bauble.query_builder import SchemaMenu
        schema_menu = SchemaMenu(
            class_mapper(self.model),
            menu_activated,
            relation_filter=self.relation_filter,
            private=True,
            selectable_relations=True
        )

        schema_menu.append(Gtk.SeparatorMenuItem())
        for item in ['Note', 'Empty']:
            xtra = Gtk.MenuItem(label=item, use_underline=False)
            xtra.connect('activate', menu_activated, item, None)
            schema_menu.append(xtra)

        schema_menu.show_all()

        tooltip = (
            'use "Note" for a note of the item.  The current "name" will be '
            'used as the category for the note.  If you wish to include an '
            'empty field use "Empty"'
        )
        prop_button.set_tooltip_text(tooltip)

        prop_button.connect('button-press-event',
                            self.on_prop_button_press_event,
                            schema_menu)
        self.grid.attach(prop_button, 3, row, 1, 1)
        # this wont work if the prop_button hasn't been attached yet
        menu_activated(None, db_field, None)
        # return prop_button, schema_menu

    def cleanup(self):
        # garbage collection
        self.grid.destroy()


class ShapefileExportDialogPresenter(GenericEditorPresenter):
    """The presenter for the Dialog.

    Manages the tasks between the model(interface) and view
    """

    widget_to_field_map = {
        'cb_locations': 'export_locations',
        'cb_plants': 'export_plants',
        'cb_include_private': 'private',
        'rb_search_results': 'search_or_all',
        'rb_all_records': 'search_or_all',
        'input_dirname': 'dirname',
    }

    view_accept_buttons = ['exp_button_ok']

    PROBLEM_NO_DIR = f'no_dir:{random()}'

    last_folder = str(Path.home())

    def __init__(self, model, view):
        super().__init__(model=model, view=view, session=False)
        from bauble.view import SearchView
        # bauble.gui is None when testing
        main_view = None if bauble.gui is None else bauble.gui.get_view()
        if (not isinstance(main_view, SearchView) or
                main_view.results_view.get_model() is None):
            self.view.widget_set_sensitive('rb_search_results', False)
            self.view.widget_set_active('rb_all_records', True)
        else:
            self.view.widget_set_sensitive('rb_search_results', True)
            self.view.widget_set_active('rb_all_records', True)

        self.add_problem(self.PROBLEM_EMPTY,
                         self.view.widgets.input_dirname)
        self.settings_boxes = []
        self.refresh_view()
        self.refresh_sensitivity()

    def on_btnbrowse_clicked(self, _widget):
        self.view.run_file_chooser_dialog(
            _("Select a shapefile"),
            None,
            Gtk.FileChooserAction.CREATE_FOLDER,
            self.last_folder,
            'input_dirname'
        )

        self.refresh_sensitivity()

    def on_dirname_entry_changed(self, widget):
        # this will set the model value also, could just use the model's value
        self.remove_problem(self.PROBLEM_NO_DIR)
        path = Path(self.on_non_empty_text_entry_changed(widget))
        logger.debug('dirname changed to %s', str(path))

        if path.exists() and path.is_dir():
            self.__class__.last_folder = str(path)
        else:
            self.add_problem(self.PROBLEM_NO_DIR, widget)

        self.refresh_sensitivity()

    def _settings_expander(self):
        """Start the settings box."""
        expander = self.view.widgets.exp_settings_expander
        child = expander.get_child()
        if child:
            expander.remove(child)
        notebook = Gtk.Notebook()
        if self.model.export_plants:
            gen_settings = None
            if self.model.search_or_all == 'rb_search_results':
                gen_settings = self.model.gen_settings
            plt_settings_box = ShapefileExportSettingsBox(
                Plant,
                fields=self.model.plant_fields,
                gen_settings=gen_settings,
                resize_func=self.reset_win_size
            )
            notebook.append_page(plt_settings_box,
                                 Gtk.Label(label="Plants"))
            self.settings_boxes.append(plt_settings_box)
        if self.model.export_locations:
            loc_settings_box = ShapefileExportSettingsBox(
                Location,
                fields=self.model.location_fields,
                resize_func=self.reset_win_size
            )
            notebook.append_page(loc_settings_box,
                                 Gtk.Label(label="Locations"))
            self.settings_boxes.append(loc_settings_box)
        expander.add(notebook)
        notebook.connect('switch_page', self.on_notebook_switch)
        notebook.show_all()
        return False

    def on_notebook_switch(self, _widget, _page, _page_num):
        self.view.get_window().resize(1, 1)

    def reset_win_size(self):
        heights = []
        if self.model.export_plants:
            heights.append(60 + (len(self.model.plant_fields) * 40))
        if self.model.export_locations:
            heights.append(60 + (len(self.model.location_fields) * 40))
        height = min(max(heights), 650)
        for settings_box in self.settings_boxes:
            settings_box.set_min_content_height(height)
        self.view.get_window().resize(1, 1)
        return False

    def on_settings_activate(self, _widget):
        logger.debug('settings expander toggled')
        self._settings_expander()
        self.view.get_window().resize(1, 1)

    def refresh_sensitivity(self):
        sensitive = False
        if self.is_dirty() and not self.has_problems():
            sensitive = True
        self.view.widget_set_sensitive('exp_settings_expander', sensitive)
        self.view.set_accept_buttons_sensitive(sensitive)

    def cleanup(self):
        for settings_box in self.settings_boxes:
            settings_box.cleanup()
        super().cleanup()


class ShapefileExporter(GenericExporter):
    """The interface for exporting data in a shapefile.

    The intent for one of these exports is to provide a way to gather
    information for importing, i.e.  we don't export field_notes but we do
    provide a column for them.
    """
    # pylint: disable=too-many-instance-attributes

    SHAPE_MAP = {'Polygon': 'poly',
                 'LineString': 'line',
                 'Point': 'point'}

    _tooltips = {
        'plants_locations': _("What is it that you want to export.  Plants "
                              "may produce multiple files."),
        'search_or_all': _("Base the export of the results on a search or all "
                           "records.  NOTE: all records will use all records "
                           "WITH spatial data.  Only when using search "
                           "results can the user select to auto generate "
                           "spatial data in advanced settings (and therefore "
                           "enable the user to edit and reimport corrected "
                           "spatial data where there currently is none)."),
        'input_dirname': _("The full path to a folder to export files to.")
    }

    def __init__(self, view=None, proj_db=None, open_=True):
        super().__init__(open_=open_)
        # widget fields
        if view is None:
            view = GenericEditorView(
                str(Path(__file__).resolve().parent / 'shapefile.glade'),
                root_widget_name='shapefile_export_dialog',
                tooltips=self._tooltips
            )
        if proj_db is None:
            proj_db = ProjDB()
        self.search_or_all = 'rb_search_results'
        self.export_locations = True
        self.export_plants = False
        self.private = True
        self.dirname = None
        self.plant_fields = prefs.prefs.get(
            f'{PLANT_SHAPEFILE_PREFS}.fields', {}
        )
        self.location_fields = prefs.prefs.get(
            f'{LOCATION_SHAPEFILE_PREFS}.fields', {}
        )
        # transform prefs into something to work with
        self.plant_fields = [[k, *get_field_properties(Plant, v), v] for
                             k, v in self.plant_fields.items()]
        self.location_fields = [[k, *get_field_properties(Location, v), v] for
                                k, v in self.location_fields.items()]
        self.gen_settings = {'start': [0, 0], 'increment': 0, 'axis': ''}
        self.proj_db = proj_db

        self.presenter = ShapefileExportDialogPresenter(self, view)
        self.generated_items = []
        self._generate_points = 0

    def run(self):
        """Queues the export task(s)

        If both plants and locations are selected in the UI then this will
        queue 2 tasks, one for each.
        The directory will be open on completion.
        """
        # generating points for plants
        if all((bool(v[0]) and bool(v[1]) if isinstance(v, list) else
                bool(v) for k, v in self.gen_settings.items())):
            self._generate_points = 2
        if self.export_plants:
            self.domain = Plant
            super().run()
        self.generated_items = []
        self._generate_points = 0
        if self.export_locations:
            self.domain = Location
            super().run()

    def _export_task(self):  # pylint: disable=too-many-locals
        """The export task.

        Yields occasionally to allow the UI to update.

        :param fields: a list of list of field name, type and size to add
            to the shapefile
        :param allowable_shapetypes: list of shapefile shapetypes to produce
            shapefiles for.
        """
        session = db.Session()

        allowable_shapetypes = {'poly'}
        fields = self.location_fields
        if self.domain is Plant:
            allowable_shapetypes = {'poly', 'line', 'point'}
            fields = self.plant_fields

        shapetypes, export_items = self.get_shapes_and_items(
            session, self.domain, allowable_shapetypes
        )

        num_items = len(list(export_items))
        five_percent = int(num_items / 20) or 1

        if self._generate_points:
            if 'point' not in shapetypes:
                self._generate_points = 1
                shapetypes.add('point')
        # quit if no shapetypes
        if not shapetypes:
            return

        logger.debug('creating shapefiles for %s types', shapetypes)
        from contextlib import ExitStack
        with TemporaryDirectory() as _temp_dir:
            logger.debug('build directory (_temp_dir) = %s', _temp_dir)
            to_zip = []
            shapefiles = {}
            with ExitStack() as stack:
                for shape in shapetypes:
                    shapefilename = (
                        f'{_temp_dir}/{self.domain.__tablename__.lower()}s'
                        f'_{shape}'
                    )
                    self.create_prj_file(shapefilename)
                    to_zip.append(shapefilename)
                    shapefiles[shape] = stack.enter_context(
                        Writer(shapefilename)
                    )
                    # create the columns and their types and size.
                    self.add_fields(shape, shapefiles, fields)

                # add records
                for records_done, item in enumerate(export_items):
                    self.add_shapefile_record(item, fields, shapefiles)
                    if records_done % five_percent == 0:
                        pb_set_fraction(records_done / num_items)
                        yield

                if self._generate_points == -1:
                    self._generate_points = 0
                    # don't zip - files removed on completion of _temp_dir
                    to_zip = [i for i in to_zip if not i.endswith('point')]

                if self.generated_items:
                    task.set_message('shapefile adding generated points')
                    self.generated_items = sorted(
                        self.generated_items,
                        key=lambda i: i.accession.species_str()
                    )
                    five_percent = int(len(self.generated_items) / 20) or 1
                    for records_done, item in enumerate(self.generated_items):
                        if records_done % five_percent == 0:
                            pb_set_fraction(records_done /
                                            len(self.generated_items))
                            yield
                        self.add_generated_points(item, records_done, fields,
                                                  shapefiles)

            task.clear_messages()
            if to_zip:
                self.zip_shapefiles(to_zip)

        session.rollback()  # best to roll back before closing esp. generated
        session.close()

    def add_generated_points(self, item, records_done, fields, shapefiles):
        increment_x = 0
        increment_y = 0
        if self.gen_settings.get('axis') == 'NS':
            increment_y = float(self.gen_settings.get('increment'))
        else:
            increment_x = float(self.gen_settings.get('increment'))
        xxx = float(self.gen_settings.get(
            'start')[0]) + (increment_x * records_done)
        yyy = float(self.gen_settings.get(
            'start')[1]) + (increment_y * records_done)
        item.geojson = {
            'type': 'Point',
            'coordinates': [xxx, yyy]}
        logger.debug('adding generated point %s', item.geojson)
        self.add_shapefile_record(item, fields, shapefiles)

    def get_shapes_and_items(self, session, model, allowable_shapetypes):

        if self.search_or_all == 'rb_search_results':
            selection = self.presenter.view.get_selection()
            if model is Plant:
                from bauble.plugins.report import get_plants_pertinent_to
                export_items = get_plants_pertinent_to(selection, session)
            elif model is Location:
                from bauble.plugins.report import get_locations_pertinent_to
                export_items = get_locations_pertinent_to(selection, session)
        else:
            export_items = session.query(model).filter(
                model.geojson.isnot(None)).all()

        # collate the shapefile types to create. Drop any private entries if
        # private is not selected.
        shapetypes = set()
        final = []
        logger.debug('iterate export_items')
        for item in export_items:
            if model is Plant and not self.private:
                if item.accession.private:
                    logger.debug('skipping private entry')
                    # don't consider this entry for shapetypes
                    continue
                final.append(item)
            if item.geojson:
                logger.debug('json is not none for item: %s', item)
                shapetype = self.SHAPE_MAP.get(item.geojson.get('type'))
                if shapetype in allowable_shapetypes:
                    shapetypes.add(shapetype)

        if final:
            export_items = final

        return (shapetypes, export_items)

    def create_prj_file(self, shapefilename):
        # TODO a way to save the settings for reuse in importing etc.
        sys_proj_str = get_default('system_proj_string')
        if not sys_proj_str:
            from bauble.error import MetaTableError
            msg = _('Cannot proceed without a system CRS. To set a system '
                    'CRS you should first import shapefile data.')
            raise MetaTableError(msg=msg)
        sys_proj_str = sys_proj_str.value
        if not self.proj_db.get_prj(sys_proj_str):
            from bauble.error import BaubleError
            msg = _('Cannot proceed without a .prj file string for the system '
                    'CRS. To set one you should first import shapefile data '
                    'in the desired format.')
            raise BaubleError(msg=msg)
        with open(f'{shapefilename}.prj', 'w') as prj:
            # NOTE: this will fail if there isn't an approriate
            # entry in the ProjDB.
            prj.write(self.proj_db.get_prj(sys_proj_str))
            prj.close()

    @staticmethod
    def add_field(shapefile, field_name, field_type, field_size=None):
        if field_size and field_type in ['N', 'F']:
            shapefile.field(field_name, field_type,
                            decimal=field_size)
        elif field_size and field_type == 'C':
            shapefile.field(field_name, field_type,
                            size=field_size)
        else:
            shapefile.field(field_name, field_type)

    def add_fields(self, shape, shapefiles, fields):
        """Adds the field definitions to the shapefile."""
        for name, typ, size, __ in fields:
            self.add_field(shapefiles.get(shape), name, typ, size)

    def add_shapefile_record(self, item, fields, shapefiles):
        try:
            shape_type = item.geojson.get('type')
        except AttributeError as e:
            logger.debug('shape_type wasn\'t found: %s', e)
            self.error += 1
            if self._generate_points > 0:
                if self.error > 400:
                    logger.debug('too many generated_items')
                    msg = ('<b>Over 400 records have no geojson.\n\n This is '
                           'too many points to generate, please select a '
                           'smaller search.</b>')
                    from bauble.utils import message_dialog
                    message_dialog(msg)
                    self.generated_items = []
                    self._generate_points -= 2
                    return
                logger.debug('appending to generated_items')
                self.generated_items.append(item)
            return
        shape = self.SHAPE_MAP.get(shape_type)
        record = {}

        record = self.get_item_record(item, {k: v for k, __, __, v in fields})

        shapefiles.get(shape).record(**record)
        shapefiles.get(shape).shape(item.geojson)

    def zip_shapefiles(self, to_zip):
        for shapefilename in to_zip:
            in_path = Path(shapefilename)
            in_paths = Path(in_path.parent).glob(f'{in_path.name}.*')
            basename = in_path.name
            logger.debug('zipping shapefile with basename: %s', basename)
            with ZipFile(f'{self.dirname}/{basename}.zip', 'w') as z:
                for path in in_paths:
                    z.write(path, arcname=path.name)

        if self.open:
            from bauble.utils import desktop
            desktop.open(self.dirname)
