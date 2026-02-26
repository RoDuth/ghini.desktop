# pylint: disable=no-self-use
# Copyright (c) 2018-2021 Ross Demuth <rossdemuth123@gmail.com>
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
Dialog tests
"""
import time
from unittest import TestCase
from unittest import mock

from gi.repository import GLib
from gi.repository import Gtk

from bauble.test import update_gui
from bauble.ui.dialogs import create_message_details_dialog
from bauble.ui.dialogs import create_message_dialog
from bauble.ui.dialogs import entry_dialog
from bauble.ui.dialogs import file_chooser_dialog
from bauble.ui.dialogs import message_details_dialog
from bauble.ui.dialogs import message_dialog
from bauble.ui.dialogs import truncate_message
from bauble.ui.dialogs import yes_no_dialog


class DialogTest(TestCase):

    def test_create_message_details_dialog(self):
        details = "these are the lines that I want to test\n2nd line\n3rd Line"
        msg = "test message"

        dlog = create_message_details_dialog(msg, details)
        self.assertTrue(isinstance(dlog, Gtk.MessageDialog))
        msg_label = dlog.get_message_area().get_children()[0]

        self.assertEqual(msg_label.get_text(), msg)
        expander = dlog.get_content_area().get_children()[1]
        buffer = expander.get_children()[0].get_children()[0].get_buffer()

        self.assertEqual(buffer.get_line_count(), 3)
        self.assertEqual(buffer.get_text(*buffer.get_bounds(), False), details)
        dlog.destroy()

    @mock.patch("bauble.ui.dialogs.GdkPixbuf.Pixbuf.new_from_file")
    def test_create_message_details_dialog_glib_error(self, mock_pixbuf):
        mock_pixbuf.side_effect = GLib.Error("BOOM")
        details = "these are the lines that I want to test\n2nd line\n3rd Line"
        msg = "test message"

        dlog = create_message_details_dialog(msg, details)

        self.assertTrue(isinstance(dlog, Gtk.MessageDialog))

        msg_label = dlog.get_message_area().get_children()[0]

        self.assertEqual(msg_label.get_text(), msg)

        contents = dlog.get_content_area().get_children()
        expander = contents[1]
        buffer = expander.get_children()[0].get_children()[0].get_buffer()

        # should have content area
        self.assertEqual(len(contents), 3)
        self.assertEqual(buffer.get_line_count(), 3)
        self.assertEqual(buffer.get_text(*buffer.get_bounds(), False), details)
        dlog.destroy()

    def test_create_message_dialog(self):
        msg = "test message"

        dlog = create_message_dialog(msg)
        self.assertTrue(isinstance(dlog, Gtk.MessageDialog))
        msg_label = dlog.get_message_area().get_children()[0]

        self.assertEqual(msg_label.get_text(), msg)
        contents = dlog.get_content_area().get_children()
        # should just be message_area and button_box  (no details area)
        self.assertEqual(len(contents), 2)
        self.assertIsNotNone(dlog.get_icon())
        dlog.destroy()

    @mock.patch("bauble.ui.dialogs.GdkPixbuf.Pixbuf.new_from_file")
    def test_create_message_dialog_glib_error(self, mock_pixbuf):
        mock_pixbuf.side_effect = GLib.Error("BOOM")
        msg = "test message"

        dlog = create_message_dialog(msg)
        self.assertTrue(isinstance(dlog, Gtk.MessageDialog))
        msg_label = dlog.get_message_area().get_children()[0]

        self.assertEqual(msg_label.get_text(), msg)
        contents = dlog.get_content_area().get_children()
        # should just be message_area and button_box  (no details area)
        self.assertEqual(len(contents), 2)
        self.assertIsNone(dlog.get_icon())
        dlog.destroy()

    @mock.patch("bauble.ui.dialogs.Gtk.MessageDialog")
    def test_message_dialog_creates_runs_destroys(self, mock_dialog):
        msg = "test message"
        mock_dialog().run.return_value = Gtk.ResponseType.OK
        metrics = mock_dialog().get_pango_context().get_metrics()
        metrics.get_approximate_char_width.return_value = 10

        message_dialog(msg)

        mock_dialog.assert_called_with(
            modal=True,
            destroy_with_parent=True,
            transient_for=None,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
        )
        mock_dialog().run.assert_called_once()
        mock_dialog().destroy.assert_called_once()

    @mock.patch("bauble.ui.dialogs.Gtk.MessageDialog")
    def test_yes_no_dialog_creates_delays_runs_destroys(self, mock_dialog):
        msg = "test message"
        mock_dialog().run.return_value = Gtk.ResponseType.YES
        metrics = mock_dialog().get_pango_context().get_metrics()
        metrics.get_approximate_char_width.return_value = 10
        mock_dialog.reset_mock()

        result = yes_no_dialog(msg, yes_delay=0.5)

        mock_dialog.assert_called_with(
            modal=True,
            destroy_with_parent=True,
            transient_for=None,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO,
        )
        # test YES is not responsive until delay is up
        mock_dialog().set_response_sensitive.assert_called_once()
        mock_dialog().set_response_sensitive.assert_called_with(
            Gtk.ResponseType.YES, False
        )
        self.assertTrue(result)
        update_gui()
        time.sleep(0.8)
        update_gui()
        mock_dialog().set_response_sensitive.assert_called_with(
            Gtk.ResponseType.YES, True
        )
        mock_dialog().run.assert_called_once()
        mock_dialog().destroy.assert_called_once()

    def test_truncate_message(self):
        line = "#" * 500
        lines_in = "\n".join(line for _ in range(200))
        expected = "\n".join(line[:100] + "  ..." for _ in range(50))
        expected += "\n... message truncated ..."

        self.assertEqual(truncate_message(lines_in, 50, 100), expected)

    def test_message_details_dialog_truncates(self):
        line = "#" * 500
        lines_in = "\n".join(line for _ in range(200))
        expected_message = "\n".join(line[:400] + "  ..." for _ in range(100))
        expected_message += "\n... message truncated ..."

        detail = "*" * 500
        details_in = "\n".join(detail for _ in range(500))
        expected_details = "\n".join(
            detail[:400] + "  ..." for _ in range(300)
        )
        expected_details += "\n... message truncated ..."

        with mock.patch(
            "bauble.ui.dialogs.create_message_details_dialog"
        ) as mockdd:
            message_details_dialog(lines_in, details_in)
            mockdd.assert_called_with(
                expected_message,
                expected_details,
                Gtk.MessageType.INFO,
                Gtk.ButtonsType.OK,
                None,
            )

    @mock.patch("bauble.ui.dialogs.Gtk.FileChooserNative.new")
    def test_file_chooser_dialog_sets_suffix(self, mock_chooser):
        temp = "/some/file/path.xsl"
        mock_chooser().run.return_value = Gtk.ResponseType.ACCEPT
        mock_chooser().get_filename.return_value = temp
        target = Gtk.Entry()
        file_chooser_dialog(
            "Select a file",
            None,
            Gtk.FileChooserAction.OPEN,
            None,
            target,
            ".csv",
        )

        self.assertEqual(target.get_text(), temp[:-3] + "csv")

    @mock.patch("bauble.ui.dialogs.Gtk.FileChooserNative.new")
    def test_file_chooser_dialog_error(self, mock_chooser):
        mock_chooser().run.return_value = Gtk.ResponseType.ACCEPT
        mock_chooser().get_filename.side_effect = Exception("BOOM")
        target = Gtk.Entry()
        with self.assertLogs("bauble.ui.dialogs", level="WARNING") as log:
            file_chooser_dialog(
                "Select a file",
                None,
                Gtk.FileChooserAction.OPEN,
                None,
                target,
                ".csv",
            )
            self.assertIn("unhandled Exception exception: BOOM", log.output[0])

    @mock.patch("bauble.ui.connmgr.Gtk.Dialog.run")
    def test_run_entry_dialog(self, mock_run):
        mock_run.return_value = Gtk.ResponseType.ACCEPT
        result = entry_dialog(
            "What ya got then?",
            visible=False,
            start_val="spam, spam, spam, egg and spam",
        )

        self.assertEqual(result, "spam, spam, spam, egg and spam")

        mock_run.return_value = Gtk.ResponseType.CANCEL
        result = entry_dialog("Have you got anything without spam in it?")

        self.assertIsNone(result)
