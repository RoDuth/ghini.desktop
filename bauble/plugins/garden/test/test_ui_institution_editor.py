# pylint: disable=no-self-use,protected-access
# Copyright 2008-2010 Brett Adams
# Copyright 2015,2017 Mario Frasca <mario@anche.no>.
# Copyright 2017 Jardín Botánico de Quito
# Copyright 2021-2026 Ross Demuth <rossdemuth123@gmail.com>
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
Institution editor tests
"""

import time
from unittest import mock

from gi.repository import Gtk

from bauble.test import BaubleTestCase
from bauble.test import update_gui
from bauble.ui.gui import GUI

from ..institution import Institution
from ..ui.institution_editor import InstitutionCommand
from ..ui.institution_editor import InstitutionDialog
from ..ui.institution_editor import InstitutionTool
from ..ui.institution_editor import start_institution_editor


class InstitutionDialogTests(BaubleTestCase):
    def test_can_create_dialog(self):
        model = Institution()
        dialog = InstitutionDialog(model)
        self.assertEqual(dialog.model, model)

        dialog.destroy()

    @mock.patch("bauble.gui")
    def test_sets_transient_for_gui(self, mock_gui):
        mock_gui.window = Gtk.Window()
        model = Institution()
        dialog = InstitutionDialog(model)

        self.assertEqual(dialog.model, model)
        self.assertEqual(dialog.get_transient_for(), mock_gui.window)

        # should also destroy the dialog
        mock_gui.window.destroy()

    def test_empty_name_is_a_problem(self):
        model = Institution()
        dialog = InstitutionDialog(model)
        update_gui()
        message_box = dialog.revealer.get_child()
        label = message_box.get_children()[1]

        self.assertTrue(dialog.revealer.get_reveal_child())
        self.assertEqual(
            label.get_text(),
            "Please specify an institution name for this database.",
        )

        dialog.destroy()

    def test_initially_empty_name_then_specified_is_ok(self):
        model = Institution()
        model.name = ""
        dialog = InstitutionDialog(model)
        update_gui()

        self.assertTrue(dialog.revealer.get_reveal_child())

        dialog.name_entry.set_text("testBG")
        update_gui()

        self.assertEqual(model.name, "testBG")
        self.assertFalse(dialog.revealer.get_reveal_child())

        dialog.destroy()

    def test_on_text_buffer_changed(self):
        model = Institution()

        dialog = InstitutionDialog(model)

        dialog.address_buffer.set_text("test")
        self.assertEqual(model.address, "test")

        dialog.destroy()

    def test_on_text_entry_changed(self):
        model = Institution()

        dialog = InstitutionDialog(model)

        dialog.code_entry.set_text("BotG")

        self.assertEqual(model.code, "BotG")

        dialog.destroy()

    def test_on_non_empty_text_entry_changed(self):
        model = Institution()

        dialog = InstitutionDialog(model)

        dialog.name_entry.set_text("BG")

        self.assertEqual(model.name, "BG")

        dialog.destroy()

    def test_on_combobox_changed(self):
        model = Institution()

        dialog = InstitutionDialog(model)
        combo = Gtk.ComboBoxText()
        combo.append_text("1")
        combo.append_text("2")
        combo.append_text("3")

        dialog.widgets_to_model_map = {combo: "geo_zoom"}

        combo.set_active(1)
        dialog.on_combobox_changed(combo)
        self.assertEqual(model.geo_zoom, "2")

        dialog.destroy()

    def test_on_response(self):
        model = Institution()
        dialog = InstitutionDialog(model)
        with mock.patch.object(model, "write") as mock_write:
            dialog.on_response(dialog, Gtk.ResponseType.CANCEL)

            mock_write.assert_not_called()

            dialog.on_response(dialog, Gtk.ResponseType.OK)

            mock_write.assert_called_once()

        dialog.destroy()

    def test_on_delete_event_cancel(self):
        gui = GUI()
        dialog = InstitutionDialog(Institution())
        update_gui()
        id_ = id(dialog)

        self.assertTrue(gui.on_delete_event(None, None))
        self.assertEqual([id_], gui._pending_delete_dialogs)

        time.sleep(0.05)
        update_gui()

        message_box = dialog.revealer.get_child()
        button_box = message_box.get_children()[1]
        cancel_button = button_box.get_children()[1]
        del message_box
        del button_box
        cancel_button.clicked()
        del cancel_button
        update_gui()

        self.assertEqual([id_], gui._pending_delete_dialogs)
        self.assertTrue(gui.on_delete_event(None, None))
        update_gui()
        dialog.destroy()
        del dialog
        gui.destroy()

    def test_on_delete_event_ok(self):
        gui = GUI()
        dialog = InstitutionDialog(Institution())
        # no problems with changes
        dialog.name_entry.set_text("BG")
        update_gui()
        id_ = id(dialog)

        self.assertTrue(gui.on_delete_event(None, None))
        self.assertEqual([id_], gui._pending_delete_dialogs)

        time.sleep(0.1)
        update_gui()

        message_box = dialog.revealer.get_child()
        button_box = message_box.get_children()[1]
        ok_button = button_box.get_children()[0]
        del message_box
        del button_box
        del dialog
        ok_button.clicked()
        del ok_button
        update_gui()

        self.assertEqual([], gui._pending_delete_dialogs)
        self.assertFalse(gui.on_delete_event(None, None))
        del gui

    @mock.patch(
        "bauble.plugins.garden.ui.institution_editor.InstitutionDialog"
    )
    def test_start_institution_editor(self, mock_dialog):
        start_institution_editor()
        mock_dialog.assert_called_once()
        self.assertIsInstance(mock_dialog.call_args[0][0], Institution)
        mock_dialog().show.assert_called_once()

    @mock.patch(
        "bauble.plugins.garden.ui.institution_editor.start_institution_editor"
    )
    def test_institution_command(self, mock_start):
        InstitutionCommand()(None, None)
        mock_start.assert_called()

    @mock.patch(
        "bauble.plugins.garden.ui.institution_editor.start_institution_editor"
    )
    def test_institution_tool(self, mock_start):
        InstitutionTool.start()
        mock_start.assert_called()
