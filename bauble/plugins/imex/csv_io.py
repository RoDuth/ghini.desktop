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
Import/Export data in csv format as specified by user using search results
only.
"""

import csv
import logging
from pathlib import Path
from random import random

logger = logging.getLogger(__name__)

from gi.repository import Gdk
from gi.repository import Gtk
from sqlalchemy.ext.associationproxy import AssociationProxy
from sqlalchemy.orm import class_mapper

import bauble
from bauble import db
from bauble import pb_set_fraction
from bauble import pluginmgr
from bauble import prefs
from bauble import task
from bauble.editor import GenericEditorPresenter
from bauble.editor import GenericEditorView
from bauble.search.strategies import MapperSearch
from bauble.utils import desktop
from bauble.utils import message_dialog

from . import GenericExporter
from . import GenericImporter

NAME = 0
"""Column position for the name entry widget and attribte"""
PATH = 1
"""Column position for the path widget and attribte"""
MATCH = 2
"""Column position for the match widget."""
OPTION = 3
"""Column position for the option widget."""

CSV_IO_PREFS = "csv_io"
"""csv_io default prefs key."""

CSV_EXPORT_DIR_PREF = f"{CSV_IO_PREFS}.ex_last_folder"
"""csv_io default prefs key for storing last folder used for exports."""

CSV_IMPORT_DIR_PREF = f"{CSV_IO_PREFS}.im_last_folder"
"""csv_io default prefs key for storing last folder used for imports."""


class CSVExportDialogPresenter(GenericEditorPresenter):
    """The presenter for the Dialog.

    Manages the tasks between the model(interface) and view
    """

    widget_to_field_map = {
        "out_filename_entry": "filename",
    }

    view_accept_buttons = ["exp_button_ok"]

    PROBLEM_NO_FILENAME = f"no_filename:{random()}"

    last_file = None

    def __init__(self, model, view):
        super().__init__(model=model, view=view, session=False)
        self.box = self.view.widgets.export_box
        self.grid = Gtk.Grid()
        self.box.pack_start(self.grid, True, True, 0)
        self.table_name = self.model.domain.__tablename__
        fields = prefs.prefs.get(f"{CSV_IO_PREFS}.{self.table_name}", {})
        self.fields = list(fields.items())
        self.last_folder = prefs.prefs.get(
            CSV_EXPORT_DIR_PREF, str(Path.home())
        )
        self.filename = None
        self.schema_menus = []
        self._construct_grid()
        self.box.show_all()
        self.add_problem(self.PROBLEM_NO_FILENAME, "out_filename_entry")
        self.refresh_sensitivity()
        if self.last_file:
            self.view.widgets.out_filename_entry.set_text(self.last_file)

    def on_btnbrowse_clicked(self, _button):
        self.view.run_file_chooser_dialog(
            _("Select CSV file"),
            None,
            Gtk.FileChooserAction.SAVE,
            self.last_folder,
            "out_filename_entry",
            ".csv",
        )
        self.refresh_sensitivity()

    def on_filename_entry_changed(self, entry):
        self.remove_problem(self.PROBLEM_NO_FILENAME)
        val = self.on_non_empty_text_entry_changed(entry)
        path = Path(val)
        logger.debug("filename changed to %s", str(path))

        if path.parent.exists() and path.parent.is_dir():
            prefs.prefs[CSV_EXPORT_DIR_PREF] = str(path.parent)
        else:
            self.add_problem(self.PROBLEM_NO_FILENAME, entry)

        self.filename = path
        self.refresh_sensitivity()

    def _construct_grid(self):  # pylint: disable=too-many-locals
        """Create the field grid layout."""
        labels = ["column title", "database field"]
        for column, txt in enumerate(labels):
            label = Gtk.Label()
            label.set_markup(f"<b>{txt}</b>")
            self.grid.attach(label, column, 0, 1, 1)

        logger.debug("export fields: %s", self.fields)
        # make attach_row available outside for loop scope.
        attach_row = 0
        for row, (name, path) in enumerate(self.fields):
            attach_row = row + 1
            name_entry = Gtk.Entry(max_length=24)
            name_entry.set_text(name or "")
            name_entry.set_width_chars(11)
            name_entry.connect("changed", self.on_name_entry_changed)
            self.grid.attach(name_entry, NAME, attach_row, 1, 1)

            self._add_prop_button(path, attach_row)
            remove_button = Gtk.Button.new_from_icon_name(
                "list-remove-symbolic", Gtk.IconSize.BUTTON
            )
            remove_button.connect("clicked", self.on_remove_button_clicked)
            remove_button.set_tooltip_text(
                _("click to remove a row, drag and drop to move.")
            )
            remove_button.connect(
                "drag-begin",
                lambda w, c: w.drag_source_set_icon_name(
                    "list-remove-symbolic"
                ),
            )
            remove_button.connect(
                "drag-data-get", self.on_remove_button_dragged
            )
            remove_button.connect(
                "drag-data-received", self.on_remove_button_dropped
            )
            remove_button.drag_dest_set(
                Gtk.DestDefaults.ALL, [], Gdk.DragAction.COPY
            )
            remove_button.drag_source_set(
                Gdk.ModifierType.BUTTON1_MASK, [], Gdk.DragAction.COPY
            )
            remove_button.drag_source_add_text_targets()
            remove_button.drag_dest_add_text_targets()
            self.grid.attach(remove_button, 4, attach_row, 1, 1)
        add_button = Gtk.Button.new_from_icon_name(
            "list-add-symbolic", Gtk.IconSize.BUTTON
        )
        add_button.set_halign(Gtk.Align.START)
        add_button.connect("clicked", self.on_add_button_clicked)
        self.grid.attach(add_button, 0, attach_row + 1, 1, 1)

    def on_name_entry_changed(self, entry):
        attached_row = self.grid.child_get_property(entry, "top_attach")
        row = attached_row - 1
        logger.debug("name_entry changed %s", self.fields[row])
        self.fields[row] = entry.get_text(), self.fields[row][PATH]
        self.refresh_sensitivity()

    @staticmethod
    def relation_filter(key, prop):
        # dont offer many relationships
        try:
            if isinstance(prop, AssociationProxy):
                prop = getattr(prop._class, prop.target_collection)
            if prop.prop.uselist:
                return False
        except AttributeError:
            pass
        # force users to use the hybrid property
        if key == "_default_vernacular_name":
            return False
        return True

    @staticmethod
    def on_prop_button_press_event(_button, event, menu):
        menu.popup_at_pointer(event)

    def _add_prop_button(self, db_field, row):
        prop_button = Gtk.Button(hexpand=True, use_underline=False)

        def menu_activated(_widget, path, _prop):
            """Closure of sorts, used to set the field_map and button label."""
            attached_row = self.grid.child_get_property(
                prop_button, "top_attach"
            )
            row = attached_row - 1
            prop_button.get_style_context().remove_class("err-btn")
            if path:
                prop_button.set_label(path)
            else:
                prop_button.set_label(_("Choose a property…"))
                prop_button.get_style_context().add_class("err-btn")
                return

            if self.fields[row][PATH] != path:
                self.fields[row] = self.fields[row][NAME], path
            self.refresh_sensitivity()

        from bauble.query_builder import SchemaMenu

        schema_menu = SchemaMenu(
            class_mapper(self.model.domain),
            menu_activated,
            relation_filter=self.relation_filter,
            private=True,
            selectable_relations=True,
        )

        extras = ["Empty"]
        if self.model.domain.__mapper__.relationships.get("notes"):
            extras.append("Note")

        schema_menu.append(Gtk.SeparatorMenuItem())
        for item in extras:
            xtra = Gtk.MenuItem(label=item, use_underline=False)
            xtra.connect("activate", menu_activated, item, None)
            schema_menu.append(xtra)

        schema_menu.show_all()
        self.schema_menus.append(schema_menu)

        tooltip = (
            'use "Note" for a note of the item.  The current "name" will be '
            "used as the category for the note.  If you wish to include an "
            'empty field use "Empty"'
        )
        prop_button.set_tooltip_text(tooltip)

        prop_button.connect(
            "button-press-event", self.on_prop_button_press_event, schema_menu
        )
        self.grid.attach(prop_button, PATH, row, 1, 1)
        # this wont work if the prop_button hasn't been attached yet
        menu_activated(None, db_field, None)

    def on_remove_button_clicked(self, button):
        attached_row = self.grid.child_get_property(button, "top_attach")
        row = attached_row - 1
        self.grid.remove_row(
            self.grid.child_get_property(button, "top_attach")
        )
        del self.fields[row]
        # self.resize_func()
        self.view.get_window().resize(1, 1)
        self.refresh_sensitivity()

    # pylint: disable=too-many-arguments
    def on_remove_button_dragged(self, button, _context, data, _info, _time):
        logger.debug("drag event = %s", button)
        row = self.grid.child_get_property(button, "top_attach")
        data.set_text(str(row), len(str(row)))

    def on_remove_button_dropped(
        self, button, _context, _x, _y, data, _info, _time
    ):
        logger.debug("drop event = %s", button)
        source_row = int(data.get_text()) - 1
        row_dest = self.grid.child_get_property(button, "top_attach") - 1
        self.fields.insert(row_dest, self.fields.pop(source_row))
        self._rebuild_grid()

    # pylint: enable=too-many-arguments

    def on_add_button_clicked(self, _button):
        # add extra field
        self.fields.append((None, None))
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

    def cleanup(self):
        # garbage collection
        self.grid.destroy()
        for schema_menu in self.schema_menus:
            schema_menu.destroy()
        super().cleanup()


class CSVExporter(GenericExporter):
    """The interface for exporting user selected CSV data.

    The intent for one of these exports is to provide a way to gather
    information for importing, i.e.  we don't export field_notes but we do
    provide a column for them.
    """

    _tooltips = {
        "out_filename_entry": _("The full path to a file to export to."),
        "out_btnbrowse": _("click to choose a file."),
    }

    def __init__(self, view=None, open_=True):
        super().__init__(open_)
        if view is None:
            view = GenericEditorView(
                str(Path(__file__).resolve().parent / "csv_io.glade"),
                root_widget_name="csv_export_dialog",
                tooltips=self._tooltips,
            )
        self.items = self.get_items(view)
        if not self.items:
            logger.debug("no items bailing")
            return
        self.presenter = CSVExportDialogPresenter(self, view)

    def get_items(self, view):
        """Get items in the search view.

        If they are not of the one type we can't work with them.
        """
        items = view.get_selection()
        if not items:
            return None
        self.domain = type(items[0])
        if any(not isinstance(i, self.domain) for i in items):
            # used in test
            raise bauble.error.BaubleError(
                "Can only export search items of the same type."
            )
        return items

    def _export_task(self):
        """The export task.

        Yields occasionally to allow the UI to update.
        """
        # add in the first column 'domain' to make it possible to determine how
        # to import it.
        table_name = self.domain.__tablename__
        obj_type = ["domain", table_name]
        fields = [obj_type] + self.presenter.fields
        fields = dict(fields)
        len_of_items = len(self.items)
        five_percent = int(len_of_items / 20) or 1
        # save to prefs...
        prefs.prefs[f"{CSV_IO_PREFS}.{table_name}"] = dict(
            self.presenter.fields
        )
        with open(self.filename, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(
                f,
                fields.keys(),
                extrasaction="ignore",
                quotechar='"',
                quoting=csv.QUOTE_MINIMAL,
            )
            writer.writeheader()
            # first row is the paths used, in case of reimporting
            writer.writerow(fields)
            for records_done, item in enumerate(self.items):
                row = self.get_item_record(item, fields)
                writer.writerow(row)
                if records_done % five_percent == 0:
                    pb_set_fraction(records_done / len_of_items)
                    yield
            self.presenter.__class__.last_file = self.filename
        if self.open:
            desktop.open(self.filename)


class CSVImportDialogPresenter(GenericEditorPresenter):
    """The presenter for the Dialog.

    Manages the tasks between the model(interface) and view
    """

    widget_to_field_map = {
        "option_combo": "option",
        "in_filename_entry": "filename",
    }

    view_accept_buttons = ["imp_button_ok"]

    PROBLEM_INVALID_FILENAME = f"invalid_filename:{random()}"

    last_file = None

    def __init__(self, model, view):
        super().__init__(model=model, view=view, session=False)
        self.box = self.view.widgets.import_box
        self.grid = Gtk.Grid(column_spacing=6, row_spacing=6)
        self.box.pack_start(self.grid, True, True, 0)
        self.filename = None
        self.box.show_all()
        self.domain = None
        self.last_folder = prefs.prefs.get(
            CSV_IMPORT_DIR_PREF, str(Path.home())
        )
        self.add_problem(self.PROBLEM_EMPTY, "in_filename_entry")
        self.refresh_sensitivity()
        if self.last_file:
            self.view.widgets.in_filename_entry.set_text(self.last_file)
        self.refresh_view()

    def refresh_sensitivity(self):
        sensitive = False
        if self.is_dirty() and not self.has_problems():
            sensitive = True
        # accept buttons
        self.view.set_accept_buttons_sensitive(sensitive)

    def on_btnbrowse_clicked(self, _button):
        self.view.run_file_chooser_dialog(
            _("Select CSV file"),
            None,
            Gtk.FileChooserAction.OPEN,
            self.last_folder,
            "in_filename_entry",
            ".csv",
        )
        self.refresh_sensitivity()

    def on_filename_entry_changed(self, entry):
        self.remove_problem(self.PROBLEM_EMPTY, entry)
        self.remove_problem(self.PROBLEM_INVALID_FILENAME, entry)
        val = self.on_non_empty_text_entry_changed(entry)
        path = Path(val)
        logger.debug("filename changed to %s", str(path))

        if path.exists() and path.parent.is_dir():
            prefs.prefs[CSV_IMPORT_DIR_PREF] = str(path.parent)
            self.filename = path

            with self.filename.open("r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                field_map = next(reader)
                logger.debug("field_map: %s", field_map)
                self.get_importable_fields(field_map)

        else:
            self.add_problem(self.PROBLEM_INVALID_FILENAME, entry)
            self.filename = None
            logger.debug("setting model fields None")
            self.model.fields = None

        self._rebuild_grid()
        self.refresh_sensitivity()

    def get_importable_fields(self, field_map):
        domains = MapperSearch.get_domain_classes()
        dom_name = field_map.get("domain")
        fields = None
        if dom_name in domains:
            self.domain = domains.get(dom_name)
            logger.debug("domain: %s", self.domain)
            fields = {}
            for name, path in field_map.items():
                if name == "domain":
                    continue
                try:
                    # If a path is a table then don't try importing it (is
                    # is used for display only)
                    if path == self.domain.__tablename__:
                        path = None
                    elif db.get_related_class(self.domain, path):
                        path = None
                except AttributeError:
                    pass
                fields[name] = path
            if not fields:
                fields = None
        else:
            self.add_problem(
                self.PROBLEM_INVALID_FILENAME, "in_filename_entry"
            )
            self.domain = None
        self.model.domain = self.domain
        self.model.fields = fields

    def _rebuild_grid(self):
        while self.grid.get_child_at(0, 0) is not None:
            self.grid.remove_row(0)
        if self.model.fields:
            self._construct_grid()
        self.grid.show_all()
        self.view.get_window().resize(1, 1)
        self.refresh_sensitivity()

    def _construct_grid(self):  # pylint: disable=too-many-locals
        """Create the field grid layout."""
        domain_label = Gtk.Label()
        domain_label.set_markup(f"Domain:  <b>{self.domain.__tablename__}</b>")
        self.grid.attach(domain_label, 0, 0, 3, 1)
        labels = ["column title", "database field", "match database", "option"]
        for column, txt in enumerate(labels):
            label = Gtk.Label()
            label.set_markup(f"<b>{txt}</b>")
            self.grid.attach(label, column, 1, 1, 1)

        logger.debug("import csv fields: %s", self.model.fields)
        for row, (name, path) in enumerate(self.model.fields.items()):
            attach_row = row + 2
            name_label = Gtk.Label()
            name_label.set_xalign(0)
            name_label.set_margin_top(4)
            name_label.set_margin_bottom(4)
            name_label.set_text(name or "")
            self.grid.attach(name_label, NAME, attach_row, 1, 1)

            path_label = Gtk.Label()
            path_label.set_xalign(0)
            path_label.set_margin_top(4)
            path_label.set_margin_bottom(4)
            path_label.set_text(path or "--")
            self.grid.attach(path_label, PATH, attach_row, 1, 1)

            if path and path in self.domain.retrieve_cols:
                chk_button = Gtk.CheckButton.new_with_label("match")
                tooltip = (
                    "Select to ensure this field matches the current data. If "
                    "a match can not be found the record will be skipped.\n\n"
                    "There must be at least one match field and a match must "
                    "return a single database entry accurately."
                )
                chk_button.set_tooltip_text(tooltip)
                chk_button.connect(
                    "toggled", self.on_match_chk_button_change, name
                )
                self.grid.attach(chk_button, MATCH, attach_row, 1, 1)

            if path == "id":
                chk_button = Gtk.CheckButton.new_with_label("import")
                tooltip = (
                    "Select to import this field into the database.  You "
                    "generally won't want to do this as any conflicts with "
                    "existing records could fail anyway."
                )
                chk_button.set_tooltip_text(tooltip)
                chk_button.connect(
                    "toggled", self.on_import_id_chk_button_change
                )
                self.grid.attach(chk_button, OPTION, attach_row, 1, 1)
            elif path and path.startswith("Note"):
                chk_button = Gtk.CheckButton.new_with_label("replace")
                tooltip = (
                    "Select to replace all existing notes of this category. "
                    "If not selected or no notes of this category exist a new "
                    "note will be added.\n\nCAUTION! will delete all notes of "
                    "category."
                )
                chk_button.set_tooltip_text(tooltip)
                chk_button.connect(
                    "toggled", self.on_replace_chk_button_change, name
                )
                self.grid.attach(chk_button, OPTION, attach_row, 1, 1)

    def on_match_chk_button_change(self, chk_btn, name):
        if chk_btn.get_active() is True:
            self.model.search_by.add(name)
        else:
            logging.debug("deleting %s from search_by", name)
            self.model.search_by.remove(name)

    def on_import_id_chk_button_change(self, chk_btn):
        if chk_btn.get_active() is True:
            self.model.use_id = True
        else:
            self.model.use_id = False

    def on_replace_chk_button_change(self, chk_btn, name):
        if chk_btn.get_active() is True:
            self.model.replace_notes.add(name)
        else:
            self.model.replace_notes.remove(name)


class CSVImporter(GenericImporter):
    """Import CSV data."""

    OPTIONS_MAP = [
        {"update": True, "add_new": False},
        {"update": False, "add_new": True},
        {"update": True, "add_new": True},
    ]

    _tooltips = {
        "option_combo": _(
            "Ordered roughly least destructive to most destructive."
        ),
        "in_filename_entry": _("The full path to a file to import."),
        "in_btnbrowse": _("click to choose a file."),
    }

    def __init__(self, view=None):
        super().__init__()
        # view and presenter
        if view is None:
            view = GenericEditorView(
                str(Path(__file__).resolve().parent / "csv_io.glade"),
                root_widget_name="csv_import_dialog",
                tooltips=self._tooltips,
            )
            view.init_translatable_combo(
                view.widgets.option_combo,
                [
                    ("0", "update existing records"),
                    ("1", "add new records only"),
                    ("2", "add or update all records"),
                ],
            )
        self.presenter = CSVImportDialogPresenter(self, view)

    def _import_task(self, options):
        """The import task.

        Yields occasionally to allow the UI to update.

        :param options: dict of settings used to decide when/what to add.
        """
        file = Path(self.filename)
        session = db.Session()
        logger.debug("importing %s with options %s", self.filename, options)

        record_count = 0
        with file.open("r", encoding="utf-8-sig") as f:
            record_count = len(f.readlines())
        five_percent = int(record_count / 20) or 1

        records_added = records_done = 0

        with file.open("r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            next(reader, None)  # skip field_map row
            for rec in reader:
                record = {k: v for k, v in rec.items() if self.fields.get(k)}
                self._is_new = False
                item = self.get_db_item(
                    session, record, options.get("add_new")
                )

                if records_done % five_percent == 0:
                    pb_set_fraction(records_done / record_count)
                    msg = (
                        f"{self._total_records} records, "
                        f"{self._committed} committed, "
                        f"{self._errors} errors"
                    )
                    task.set_message(msg)
                    yield

                records_done += 1

                if item is None:
                    continue

                if self._is_new or options.get("update"):
                    logger.debug("adding all data")
                    try:
                        self.add_db_data(session, item, record)
                    except Exception as e:
                        rec["__line_#"] = self._total_records
                        rec["__err"] = e
                        self._err_recs.append(rec)
                        self._total_records += 1
                        self._errors += 1
                        session.rollback()
                        continue
                    records_added += 1

                # commit every record catches errors and avoids losing records.
                logger.debug("committing")
                try:
                    self.commit_db(session)
                except Exception as e:
                    # record errored
                    rec["__line_#"] = self._total_records
                    rec["__err"] = e
                    self._err_recs.append(rec)
            self.presenter.__class__.last_file = self.filename

        session.close()

        if bauble.gui and (view := bauble.gui.get_view()):
            view.update()


class CSVImportTool(pluginmgr.Tool):  # pylint: disable=too-few-public-methods
    category = _("Import")
    label = _("CSV")

    @classmethod
    def start(cls):
        """Start the CSV importer."""
        importer = CSVImporter()
        importer.start()
        logger.debug("import finished")
        return importer


class CSVExportTool(pluginmgr.Tool):  # pylint: disable=too-few-public-methods
    category = _("Export")
    label = _("CSV")

    @classmethod
    def start(cls):
        """Start the CSV exporter."""

        from bauble.view import SearchView

        view = bauble.gui.get_view()
        if not isinstance(view, SearchView):
            # used in tests
            logger.debug("view is not SearchView")
            message_dialog(_("Search for something first."))
            return None

        model = view.results_view.get_model()
        if model is None:
            # used in tests
            logger.debug("model is None")
            message_dialog(_("Search for something first. (No model)"))
            return None

        exporter = CSVExporter()
        if exporter.start() is None:
            return None

        logger.debug("CSVExportTool finished")
        return exporter
