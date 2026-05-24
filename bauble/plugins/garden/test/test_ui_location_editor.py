# Copyright (c) 2026 Ross Demuth <rossdemuth123@gmail.com>
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
Location editor tests
"""
from unittest import mock

from gi.repository import Gtk

from bauble import db
from bauble import utils
from bauble.test import BaubleTestCase
from bauble.test import update_gui
from bauble.ui.presenter import Response
from bauble.ui.widgets.message import YesNoMessageBox

from ..location import Location
from ..plant import Plant
from ..ui.location_editor import LocationEditorDialog
from ..ui.location_editor import add_plants_callback
from ..ui.location_editor import edit_callback


class LocationEditorDialogTests(BaubleTestCase):
    @mock.patch("bauble.gui")
    def test_init_existing(self, mock_gui):
        mock_gui.window = Gtk.Window()
        location = Location(
            code="LOC1",
            name="Location One",
            description="First location.",
        )
        self.session.add(location)
        self.session.commit()
        editor = LocationEditorDialog(location, self.session)

        self.assertEqual(editor.get_transient_for(), mock_gui.window)
        self.assertEqual(editor.map_menu_btn.model, location)
        self.assertEqual(editor.notes_presenter.model, location)
        self.assertEqual(editor.pictures_presenter.model, location)
        self.assertEqual(editor.pictures_presenter.prop, "_pictures")
        self.assertEqual(editor.documents_presenter.model, location)
        self.assertEqual(editor.documents_presenter.prop, "documents")
        self.assertEqual(editor.code_entry.get_text(), "LOC1")
        self.assertEqual(editor.name_entry.get_text(), "Location One")
        buffer = editor.description_textbuffer
        self.assertEqual(
            buffer.get_text(*buffer.get_bounds(), False),
            "First location.",
        )
        self.assertEqual(len(editor.problems), 0)

        editor.destroy()

    def test_init_new(self):
        location = Location()
        editor = LocationEditorDialog(location, self.session)

        self.assertTrue(editor.map_menu_btn.model)
        self.assertTrue(editor.notes_presenter.model)
        self.assertTrue(editor.pictures_presenter.model)
        self.assertEqual(editor.pictures_presenter.prop, "_pictures")
        self.assertTrue(editor.documents_presenter.model)
        self.assertEqual(editor.documents_presenter.prop, "documents")
        self.assertEqual(editor.code_entry.get_text(), "")
        self.assertEqual(editor.name_entry.get_text(), "")
        buffer = editor.description_textbuffer
        self.assertEqual(
            buffer.get_text(*buffer.get_bounds(), False),
            "",
        )
        self.assertEqual(len(editor.problems), 1)
        for problem, widget in editor.problems:
            self.assertEqual(widget, editor.code_entry)
            self.assertTrue(
                problem.startswith(
                    "empty::on_unique_text_entry_changed::LocationEditorDialog"
                )
            )

        editor.destroy()

    def test_editor_doesnt_leak(self):
        editor = LocationEditorDialog(
            model=Location(),
            session=db.Session(),
        )
        editor.show()
        editor.emit("response", Response.CANCEL)

        del editor
        update_gui()

        self.assertEqual(
            utils.gc_objects_by_type("LocationEditorDialog"),
            [],
            "LocationEditorDialog not deleted",
        )

    def test_can_commit_new(self):
        editor = LocationEditorDialog(Location(), self.session)

        self.assertFalse(editor.can_commit)

        editor.code_entry.set_text("LOC1")

        self.assertTrue(editor.can_commit)

        editor.destroy()

    def test_can_commit_existing(self):
        location = Location(
            code="LOC1",
            name="Location One",
            description="First location.",
        )
        self.session.add(location)
        location2 = Location(
            code="LOC2",
            name="Location Two",
            description="Second location.",
        )
        self.session.add(location2)
        self.session.commit()
        editor = LocationEditorDialog(location, self.session)

        self.assertFalse(editor.can_commit)

        editor.code_entry.set_text("LOC2")

        self.assertFalse(editor.can_commit)

        editor.code_entry.set_text("LOC3")

        self.assertTrue(editor.can_commit)
        # clear revealer
        update_gui()

        editor.destroy()

    def test_ok_sensitive(self):
        location = Location()
        self.session.add(location)
        editor = LocationEditorDialog(location, self.session)
        ok_button = editor.get_widget_for_response(-5)

        self.assertFalse(ok_button.get_sensitive())

        editor.destroy()

        location.code = "LOC1"
        editor = LocationEditorDialog(location, db.Session())

        ok_button = editor.get_widget_for_response(-5)

        self.assertTrue(ok_button.get_sensitive())

        editor.destroy()

    def test_on_changed_calls_update(self):
        editor = LocationEditorDialog(Location(), self.session)
        with mock.patch.object(editor, "update") as mock_update:
            editor.map_menu_btn.emit("changed")
            mock_update.assert_called_once()

        editor.destroy()

    def test_update(self):
        editor = LocationEditorDialog(Location(), self.session)

        for response in Response:
            widget = editor.get_widget_for_response(response.value)
            if response == Response.CANCEL:
                self.assertTrue(widget.get_sensitive())
            elif widget:
                self.assertFalse(widget.get_sensitive())

        editor.code_entry.set_text("LOC1")

        for response in Response:
            widget = editor.get_widget_for_response(response.value)
            if widget:
                self.assertTrue(widget.get_sensitive())

        editor.destroy()

    @mock.patch("bauble.plugins.garden.ui.location_editor.edit_callback")
    def test_on_code_entry_changed_location_exists(self, mock_callback):
        location = Location(
            code="LOC1",
            name="Location One",
            description="First location.",
        )
        self.session.add(location)
        self.session.commit()
        editor = LocationEditorDialog(Location(), self.session)
        editor.code_entry.set_text("LOC1")

        # self.assertEqual(editor.model.code, "LOC1")
        self.assertEqual(len(editor.problems), 1)
        update_gui()

        child = editor.revealer.get_child()

        self.assertIsInstance(child, YesNoMessageBox)

        # no
        mock_callback.reset_mock()
        child.get_children()[1].get_children()[1].emit("clicked")

        mock_callback.assert_not_called()

        # yes
        editor.code_entry.set_text("")
        editor.code_entry.set_text("LOC1")
        update_gui()
        child.get_children()[1].get_children()[0].emit("clicked")

        mock_callback.assert_called_once()

        editor.destroy()

    @mock.patch("bauble.ui.dialogs.message_details_dialog")
    def test_on_response_ok(self, mock_dlog):
        editor = LocationEditorDialog(Location(), self.session)
        # change code to None to force an error,
        # NOTE that the editor should never allow this.
        editor.model.code = None
        # fails no code, use emit here to avoid warning due to:
        # `dialog.stop_emission_by_name("response")`
        editor.emit("response", Response.OK)

        update_gui()
        mock_dlog.assert_called_once()
        mock_dlog.reset_mock()

        editor.code_entry.set_text("LOC1")
        self.assertFalse(editor.on_response(editor, Response.OK))

        update_gui()
        mock_dlog.assert_not_called()

        editor.destroy()

    def test_on_response_cancel(self):
        editor = LocationEditorDialog(Location(), self.session)

        self.assertFalse(editor.on_response(editor, Response.CANCEL))

        editor.destroy()

    @mock.patch("bauble.plugins.garden.ui.location_editor.create_location")
    def test_on_response_next(self, mock_callback):
        mock_callback.return_value = False
        editor = LocationEditorDialog(Location(code="LOC1"), self.session)

        self.assertFalse(editor.on_response(editor, Response.NEXT))

        update_gui()

        mock_callback.assert_called_once()

        editor.destroy()

    @mock.patch("bauble.plugins.garden.ui.location_editor.add_plants_callback")
    def test_on_reponse_add(self, mock_callback):
        mock_callback.return_value = False
        editor = LocationEditorDialog(Location(code="LOC1"), self.session)

        self.assertFalse(editor.on_response(editor, Response.ADD))

        update_gui()

        mock_callback.assert_called_once_with([editor.model])

        editor.destroy()


class FunctionTests(BaubleTestCase):

    def test_edit_callback(self):
        location = Location(
            code="LOC1",
            name="Location One",
            description="First location.",
        )
        self.session.add(location)
        self.session.commit()

        with mock.patch.object(edit_callback, "dialog_class") as mock_editor:

            self.assertFalse(edit_callback([location]))
            mock_editor.assert_called_once()
            self.assertEqual(mock_editor.call_args.kwargs["model"], location)
            mock_editor().show.assert_called_once()

    def test_add_plants_callback(self):
        location = Location(
            code="LOC1",
            name="Location One",
            description="First location.",
        )
        self.session.add(location)
        self.session.flush()

        with mock.patch.object(
            add_plants_callback,
            "dialog_class",
        ) as mock_editor:

            self.assertFalse(add_plants_callback([location]))
            mock_editor.assert_called_once()
            plt = mock_editor.call_args.kwargs["model"]
            plt = self.session.merge(plt)
            self.assertIsInstance(plt, Plant)
            self.assertEqual(plt.location, location)
