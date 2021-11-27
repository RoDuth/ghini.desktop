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
Export data to csv in format as specified by user (NOT a full backup) using
search results only.
"""

import time
import csv
from pathlib import Path
from random import random
from operator import attrgetter

import logging
logger = logging.getLogger(__name__)

from gi.repository import Gtk, Gdk

from sqlalchemy.orm import class_mapper

import bauble
from bauble.utils import desktop
from bauble import pluginmgr
from bauble import db
from bauble import prefs
from bauble import btypes
from bauble import task, pb_set_fraction
from bauble.editor import GenericEditorView, GenericEditorPresenter

NAME = 0
PATH = 1


class CSVExportDialogView(GenericEditorView):
    """This view is mostly just inherited from GenericEditorView and kept as
    simple as possible.
    """

    _tooltips = {
        'out_filename_entry': _("The full path to a file to export to."),
        'out_btnbrowse': _("click to choose a file.")
    }

    def __init__(self):
        filename = str(Path(__file__).resolve().parent / 'csv_io.glade')
        parent = None
        if bauble.gui:
            parent = bauble.gui.window
        root_widget_name = 'csv_export_dialog'
        super().__init__(filename, parent, root_widget_name)


class CSVExportDialogPresenter(GenericEditorPresenter):
    """The presenter for the Dialog.

    Manages the tasks between the model(interface) and view
    """
    widget_to_field_map = {
        'out_filename_entry': 'filename',
    }

    view_accept_buttons = ['exp_button_cancel', 'exp_button_ok']

    PROBLEM_NO_FILENAME = random()

    last_folder = str(Path.home())
    last_file = None

    last_fields = {}

    def __init__(self, model, view):
        super().__init__(model=model, view=view)
        self.box = self.view.widgets.export_box
        self.grid = Gtk.Grid()
        self.box.pack_start(self.grid, True, True, 0)
        self.fields = self.last_fields.get(self.model.model.__tablename__, [])
        self.filename = None
        self._construct_grid()
        self.box.show_all()
        self.add_problem(self.PROBLEM_NO_FILENAME, 'out_filename_entry')
        self.refresh_sensitivity()
        if self.last_file:
            self.view.widgets.out_filename_entry.set_text(self.last_file)

    def on_btnbrowse_clicked(self, _widget):
        self.view.run_file_chooser_dialog(
            _("Select CSV file"),
            None,
            Gtk.FileChooserAction.SAVE,
            self.last_folder,
            'out_filename_entry'
        )
        self.refresh_sensitivity()

    def on_filename_entry_changed(self, widget):
        self.remove_problem(self.PROBLEM_NO_FILENAME)
        val = self.on_non_empty_text_entry_changed(widget)
        path = Path(val)
        logger.debug('filename changed to %s', str(path))

        if path.parent.exists() and path.parent.is_dir():
            self.__class__.last_folder = str(path.parent)
        else:
            self.add_problem(self.PROBLEM_NO_FILENAME, widget)

        self.filename = path
        self.refresh_sensitivity()

    def _construct_grid(self):   # pylint: disable=too-many-locals
        """Create the field grid layout."""
        labels = ['column title', 'database field']
        for column, txt in enumerate(labels):
            label = Gtk.Label()
            label.set_markup(f'<b>{txt}</b>')
            self.grid.attach(label, column, 0, 1, 1)

        logger.debug('export settings box shapefile fields: %s', self.fields)
        attach_row = 0
        for row, (name, path) in enumerate(self.fields):
            attach_row = row + 1
            name_entry = Gtk.Entry(max_length=24)
            name_entry.set_text(name or '')
            name_entry.set_width_chars(11)
            name_entry.connect('changed', self.on_name_entry_changed)
            self.grid.attach(name_entry, NAME, attach_row, 1, 1)

            self._add_prop_button(path, attach_row)
            remove_button = Gtk.Button.new_from_icon_name('list-remove',
                                                          Gtk.IconSize.BUTTON)
            remove_button.connect('clicked', self.on_remove_button_clicked)
            remove_button.set_tooltip_text(
                _("click to remove a row, drag and drop to move."))
            remove_button.connect('drag-begin', lambda w, c:
                                  w.drag_source_set_icon_name('list-remove'))
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
        add_button = Gtk.Button.new_from_icon_name('list-add',
                                                   Gtk.IconSize.BUTTON)
        add_button.set_halign(Gtk.Align.START)
        add_button.connect('clicked', self.on_add_button_clicked)
        self.grid.attach(add_button, 0, attach_row + 1, 1, 1)

    def on_name_entry_changed(self, widget):
        attached_row = self.grid.child_get_property(widget, 'top_attach')
        row = attached_row - 1
        logger.debug('name_entry changed %s', self.fields[row])
        self.fields[row][NAME] = widget.get_text()
        self.refresh_sensitivity()

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
        menu.popup(None, None, None, None, event.button, event.time)

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
            self.refresh_sensitivity()

        from bauble.query_builder import SchemaMenu
        schema_menu = SchemaMenu(
            class_mapper(self.model.model),
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
        self.grid.attach(prop_button, PATH, row, 1, 1)
        # this wont work if the prop_button hasn't been attached yet
        menu_activated(None, db_field, None)
        # return prop_button, schema_menu

    def on_remove_button_clicked(self, widget):
        attached_row = self.grid.child_get_property(widget, 'top_attach')
        row = attached_row - 1
        self.grid.remove_row(self.grid.child_get_property(widget,
                                                          'top_attach'))
        del self.fields[row]
        # self.resize_func()
        self.view.get_window().resize(1, 1)
        self.refresh_sensitivity()

    # pylint: disable=too-many-arguments
    def on_remove_button_dragged(self, widget, _context, data, _info, _time):
        logger.debug('drag event = %s', widget)
        row = self.grid.child_get_property(widget, 'top_attach')
        data.set_text(str(row), len(str(row)))

    def on_remove_button_dropped(self, widget, _context, _x, _y, data, _info,
                                 _time):
        logger.debug('drop event = %s', widget)
        source_row = int(data.get_text()) - 1
        row_dest = self.grid.child_get_property(widget, 'top_attach') - 1
        self.fields.insert(row_dest, self.fields.pop(source_row))
        self._rebuild_grid()
    # pylint: enable=too-many-arguments

    def on_add_button_clicked(self, _widget):
        # add extra field
        self.fields.append([None, None])
        # should reorder rather than rebuild
        self._rebuild_grid()
        self.view.get_window().resize(1, 1)

    def _rebuild_grid(self):
        while self.grid.get_child_at(0, 0) is not None:
            self.grid.remove_row(0)
        self._construct_grid()
        self.grid.show_all()
        self.refresh_sensitivity()

    def refresh_sensitivity(self):
        sensitive = False
        has_fields = any(i for i in self.fields if i[0] and i[1])
        if has_fields and self.is_dirty() and not self.has_problems():
            sensitive = True
        self.view.set_accept_buttons_sensitive(sensitive)


class CSVExporter:
    """The interface for exporting user selected CSV data.

    The intent for one of these exports is to provide a way to gather
    information for importing, i.e.  we don't export field_notes but we do
    provide a column for them.
    """
    def __init__(self, view=None, open_=True):
        # widget fields
        if view is None:
            view = CSVExportDialogView()
        self.open = open_
        self.dirname = None
        self.view = view

        self.model = None
        self.items = self.get_items()
        if not self.items:
            return
        self.filename = None
        self.presenter = CSVExportDialogPresenter(self, self.view)

        self.error = 0

    def get_items(self):
        """Get items in the search view.

        If they are not of the one type we can't work with them.
        """
        items = self.view.get_selection()
        if not items:
            return None
        self.model = type(items[0])
        if any(not isinstance(i, self.model) for i in items):
            raise bauble.error.BaubleError(
                'Can only export search items of the same type.'
            )
        return items

    def start(self):
        """Start the CSV exporter UI.  On response run the export task.
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
        """Queues the export task(s)"""
        task.clear_messages()
        task.set_message(
            f'exporting CSV of {self.model.__tablename__} records'
        )
        task.queue(self._export_task())
        task.set_message('CSV export completed')

    def _export_task(self):
        """The export task.

        Yields occasionally to allow the UI to update.
        """
        start = time.time()
        column_names = [i[0] for i in self.presenter.fields]
        len_of_items = len(self.items)
        five_percent = int(len_of_items / 20) or 1
        self.presenter.__class__.last_fields[
            self.model.__tablename__
        ] = self.presenter.fields
        with open(self.filename, 'w', encoding='utf-8', newline='') as fname:
            writer = csv.DictWriter(fname,
                                    column_names,
                                    extrasaction='ignore',
                                    quotechar='"',
                                    quoting=csv.QUOTE_MINIMAL)
            writer.writeheader()
            fields = dict(self.presenter.fields)
            writer.writerow(fields)
            for records_done, item in enumerate(self.items):
                row = self.get_item_record(item, fields)
                writer.writerow(row)
                if records_done % five_percent == 0:
                    pb_set_fraction(records_done / len_of_items)
                    yield
            self.presenter.__class__.last_file = self.filename
        print(time.time() - start)
        desktop.open(self.filename)

    @staticmethod
    def get_item_record(item, fields):
        record = {}
        datetime_fmat = prefs.prefs.get(prefs.datetime_format_pref)
        date_fmat = prefs.prefs.get(prefs.date_format_pref)

        for name, path in fields.items():
            if path == 'Note':
                value = ''
                if hasattr(item, name) and name in [n.category[1:-1] for n in
                                                    item.notes]:
                    value = getattr(item, name)
                else:
                    value = [n.note for n in item.notes if n.category == name]
                    value = str(value[-1]) if value else ''
                record[name] = str(value)
            elif path == 'Empty':
                record[name] = ''
            elif path == item.__table__.key:
                record[name] = str(item)
            else:
                try:
                    value = attrgetter(path)(item)
                    try:
                        if '.' in path:
                            table = db.get_related_class(
                                item.__table__, path.rsplit('.', 1)[0]
                            ).__table__
                        else:
                            table = item.__table__
                        column_type = getattr(table.c,
                                              path.split('.')[-1]).type
                    except AttributeError:
                        # path is to a table and not a column
                        column_type = None
                    if value and isinstance(column_type, btypes.Date):
                        record[name] = value.strftime(date_fmat)
                    elif value and isinstance(column_type, btypes.DateTime):
                        record[name] = value.strftime(datetime_fmat)
                    else:
                        record[name] = str(value or '')
                except AttributeError:
                    record[name] = ''
        return record


class CSVExportTool(pluginmgr.Tool):  # pylint: disable=too-few-public-methods

    category = _('Export')
    label = _('CSV')

    @classmethod
    def start(cls):
        """Start the CSV exporter."""

        exporter = CSVExporter()
        if not exporter.items:
            return None
        exporter.start()
        logger.debug('CSVExportTool finished')
        return exporter
