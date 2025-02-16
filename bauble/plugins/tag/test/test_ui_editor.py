# pylint: disable=no-self-use,protected-access
# Copyright (c) 2005,2006,2007,2008,2009 Brett Adams <brett@belizebotanic.org>
# Copyright (c) 2012-2015 Mario Frasca <mario@anche.no>
# Copyright (c) 2021-2025 Ross Demuth <rossdemuth123@gmail.com>
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
Tag editor tests
"""

from unittest import mock

from gi.repository import Gtk
from sqlalchemy.exc import SQLAlchemyError

import bauble
from bauble.error import BaubleError
from bauble.error import DatabaseError
from bauble.plugins.plants import Family
from bauble.test import BaubleTestCase
from bauble.ui import GUI

from .. import Tag
from ..ui.editor import TagEditorDialog
from ..ui.editor import TagItemsDialog
from ..ui.editor import edit_callback
from ..ui.editor import remove_callback


class TagEditorDialogTests(BaubleTestCase):
    def setUp(self):
        super().setUp()
        bauble.gui = GUI()

    def tearDown(self):
        super().tearDown()
        bauble.gui = None

    def test_can_create_dialog(self):
        model = Tag()
        dialog = TagEditorDialog(model)
        self.assertEqual(dialog.model, model)
        self.assertTrue(dialog.tag_name_entry.is_focus())
        dialog.destroy()

    def test_populates(self):
        model = Tag(tag="Foo", description="Bar")
        dialog = TagEditorDialog(model)

        self.assertEqual(dialog.tag_name_entry.get_text(), "Foo")
        buffer = dialog.tag_desc_textbuffer
        self.assertEqual(buffer.get_text(*buffer.get_bounds(), False), "Bar")
        dialog.destroy()

    def test_empty_name_is_a_problem(self):
        model = Tag()
        dialog = TagEditorDialog(model)

        self.assertEqual(
            dialog.problems,
            {(f"empty::TagEditorDialog::{id(dialog)}", dialog.tag_name_entry)},
        )
        dialog.destroy()

    def test_not_unique_name_is_a_problem(self):
        tag = Tag(tag="Foo")
        self.session.add(tag)
        self.session.commit()

        model = Tag(tag="Foo")
        self.session.add(model)

        dialog = TagEditorDialog(model)

        self.assertEqual(
            dialog.problems,
            {
                (
                    f"not_unique::TagEditorDialog::{id(dialog)}",
                    dialog.tag_name_entry,
                )
            },
        )
        dialog.destroy()

    def test_unique_name_is_not_a_problem(self):
        tag = Tag(tag="Foo")
        self.session.add(tag)
        self.session.commit()

        model = Tag(tag="Bar")
        self.session.add(model)

        dialog = TagEditorDialog(model)

        self.assertEqual(dialog.problems, set())
        dialog.destroy()

    def test_on_text_buffer_changed(self):
        model = Tag()
        dialog = TagEditorDialog(model)
        text_buffer = dialog.tag_desc_textbuffer

        text_buffer.set_text("test")
        dialog.on_text_buffer_changed(text_buffer)
        self.assertEqual(model.description, "test")
        dialog.destroy()

    def test_on_tag_entry_changed(self):
        model = Tag()
        dialog = TagEditorDialog(model)
        entry = dialog.tag_name_entry

        entry.set_text("test")
        dialog.on_tag_entry_changed(entry)
        self.assertEqual(model.tag, "test")
        dialog.destroy()

    def test_on_tag_entry_changed_empty_is_a_problem(self):
        model = Tag()
        dialog = TagEditorDialog(model)
        entry = dialog.tag_name_entry

        entry.set_text("")
        dialog.on_tag_entry_changed(entry)
        self.assertEqual(model.tag, "")
        self.assertEqual(
            dialog.problems,
            {(f"empty::TagEditorDialog::{id(dialog)}", dialog.tag_name_entry)},
        )
        dialog.destroy()


class TagItemsDialogTests(BaubleTestCase):
    def setUp(self):
        super().setUp()
        bauble.gui = GUI()

    def tearDown(self):
        super().tearDown()
        bauble.gui = None

    def test_can_create_dialog(self):
        fam = Family(epithet="Myrtaceae")
        dialog = TagItemsDialog([fam])
        dialog.destroy()

    def test_create_dialog_no_selection_raises_and_logs(self):
        with self.assertLogs(level="WARNING") as logs:
            self.assertRaises(BaubleError, TagItemsDialog, [])
        string = "No selection provided."
        self.assertTrue(any(string in i for i in logs.output))

    def test_create_dialog_with_selected_set_label(self):
        fam = Family(epithet="Myrtaceae")
        fam2 = Family(epithet="Asteraceae")

        dialog = TagItemsDialog([fam, fam2])

        self.assertEqual(
            dialog.items_data_label.get_text(), "Myrtaceae,  Asteraceae"
        )
        self.assertEqual(dialog.selected, [fam, fam2])
        dialog.destroy()

    def test_can_start_dialog(self):
        fam = Family(epithet="Myrtaceae")
        self.session.add(fam)
        dialog = TagItemsDialog([fam])
        dialog.run = mock.Mock()

        dialog.start()

        dialog.run.assert_called()

        dialog.destroy()

    def test_start_dialog_no_session_bails(self):
        fam = Family(epithet="Myrtaceae")
        self.session.add(fam)
        dialog = TagItemsDialog([fam])
        dialog.run = mock.Mock()

        with mock.patch("bauble.db.Session", None):
            dialog.start()

        dialog.run.assert_not_called()

        dialog.destroy()

    def test_start_dialog_no_tree_model_bails(self):
        fam = Family(epithet="Myrtaceae")
        self.session.add(fam)
        dialog = TagItemsDialog([fam])
        dialog.run = mock.Mock()
        dialog.tag_tree = mock.Mock()
        dialog.tag_tree.get_model.return_value = None

        dialog.start()

        dialog.run.assert_not_called()

        dialog.destroy()

    def test_start_dialog_no_object_session_raises_and_logs(self):
        fam = Family(epithet="Myrtaceae")
        dialog = TagItemsDialog([fam])

        with self.assertLogs(level="WARNING") as logs:
            self.assertRaises(DatabaseError, dialog.start)

        string = "no object session bailing."
        self.assertTrue(any(string in i for i in logs.output))
        dialog.destroy()

    def test_on_new_button_clicked_cancel_doesnt_append(self):
        fam = Family(epithet="Myrtaceae")
        dialog = TagItemsDialog([fam])
        mock_editor = mock.Mock(return_value=Gtk.ResponseType.CANCEL)

        dialog.on_new_button_clicked(edit_func=mock_editor)

        self.assertEqual(len(dialog.tag_tree.get_model()), 0)

        dialog.destroy()

    def test_on_new_button_clicked_ok_appends(self):
        fam = Family(epithet="Myrtaceae")
        dialog = TagItemsDialog([fam])
        mock_editor = mock.Mock(return_value=Gtk.ResponseType.OK)

        dialog.on_new_button_clicked(edit_func=mock_editor)

        self.assertEqual(len(dialog.tag_tree.get_model()), 1)

        dialog.destroy()

    def test_on_new_button_no_session_bails(self):
        fam = Family(epithet="Myrtaceae")
        dialog = TagItemsDialog([fam])
        mock_editor = mock.Mock(return_value=Gtk.ResponseType.OK)

        with mock.patch("bauble.db.Session", None):
            dialog.on_new_button_clicked(edit_func=mock_editor)

        mock_editor.assert_not_called()
        self.assertEqual(len(dialog.tag_tree.get_model()), 0)

        dialog.destroy()

    def test_on_tag_toggled_toggles(self):
        tag = Tag(tag="foo")
        fam = Family(epithet="Myrtaceae")
        self.session.add_all([fam, tag])
        self.session.commit()
        dialog = TagItemsDialog([fam])
        dialog.run = mock.Mock()
        dialog.start()
        self.assertFalse(tag.is_tagging(fam))
        mock_renderer = mock.Mock()
        # tag
        mock_renderer.get_active.return_value = False

        dialog.on_tag_toggled(mock_renderer, "0")

        self.assertTrue(tag.is_tagging(fam))

        # untag
        mock_renderer.get_active.return_value = True

        dialog.on_tag_toggled(mock_renderer, "0")

        self.assertFalse(tag.is_tagging(fam))

        dialog.destroy()

    def test_on_tag_toggled_bails_no_model(self):
        fam = Family(epithet="Myrtaceae")
        dialog = TagItemsDialog([fam])
        dialog.tag_tree = mock.Mock()
        dialog.tag_tree.get_model.return_value = None
        mock_renderer = mock.Mock()

        # cover to type guard, raises if fails
        dialog.on_tag_toggled(mock_renderer, "0")

        dialog.destroy()

    def test_on_selection_changed_sets_delete_button_sesitive(self):
        tag = Tag(tag="foo")
        fam = Family(epithet="Myrtaceae")
        self.session.add_all([fam, tag])
        self.session.commit()
        dialog = TagItemsDialog([fam])
        dialog.run = mock.Mock()
        dialog.start()
        self.assertFalse(dialog.delete_button.get_sensitive())
        self.assertIsNone(dialog.selected_model_row)

        dialog.tag_tree.get_selection().select_path(Gtk.TreePath.new_first())

        self.assertIsNotNone(dialog.selected_model_row)
        self.assertTrue(dialog.delete_button.get_sensitive())

        dialog.destroy()

    def test_on_delete_button_clicked_deletes_selected_if_yes(self):
        tag = Tag(tag="foo")
        fam = Family(epithet="Myrtaceae")
        self.session.add_all([fam, tag])
        self.session.commit()
        dialog = TagItemsDialog([fam])
        dialog.run = mock.Mock()
        dialog.start()
        self.assertFalse(dialog.delete_button.get_sensitive())
        self.assertIsNone(dialog.selected_model_row)
        dialog.tag_tree.get_selection().select_path(Gtk.TreePath.new_first())
        self.assertEqual(len(self.session.query(Tag).all()), 1)
        mock_yn_dialog = mock.Mock()
        mock_yn_dialog.return_value = True

        with mock.patch("bauble.gui") as mock_gui:
            dialog.on_delete_button_clicked(None, yn_dialog=mock_yn_dialog)
            mock_gui.get_view().update.assert_called()

        mock_yn_dialog.assert_called()
        self.assertEqual(len(self.session.query(Tag).all()), 0)

        dialog.destroy()

    def test_on_delete_button_clicked_doesnt_delete_selected_if_no(self):
        tag = Tag(tag="foo")
        fam = Family(epithet="Myrtaceae")
        self.session.add_all([fam, tag])
        self.session.commit()
        dialog = TagItemsDialog([fam])
        dialog.run = mock.Mock()
        dialog.start()
        self.assertFalse(dialog.delete_button.get_sensitive())
        self.assertIsNone(dialog.selected_model_row)
        dialog.tag_tree.get_selection().select_path(Gtk.TreePath.new_first())
        self.assertEqual(len(self.session.query(Tag).all()), 1)
        mock_yn_dialog = mock.Mock()
        mock_yn_dialog.return_value = False

        dialog.on_delete_button_clicked(None, yn_dialog=mock_yn_dialog)

        mock_yn_dialog.assert_called()
        self.assertEqual(len(self.session.query(Tag).all()), 1)

        dialog.destroy()

    def test_on_delete_button_clicked_bails_no_session(self):
        tag = Tag(tag="foo")
        fam = Family(epithet="Myrtaceae")
        self.session.add_all([fam, tag])
        self.session.commit()
        dialog = TagItemsDialog([fam])
        dialog.run = mock.Mock()
        dialog.start()
        self.assertFalse(dialog.delete_button.get_sensitive())
        self.assertIsNone(dialog.selected_model_row)
        dialog.tag_tree.get_selection().select_path(Gtk.TreePath.new_first())
        self.assertEqual(len(self.session.query(Tag).all()), 1)
        mock_yn_dialog = mock.Mock()

        with mock.patch("bauble.db.Session", None):
            dialog.on_delete_button_clicked(None, yn_dialog=mock_yn_dialog)

        mock_yn_dialog.assert_not_called()
        self.assertEqual(len(self.session.query(Tag).all()), 1)

        dialog.destroy()

    def test_on_delete_button_clicked_bails_no_selected(self):
        tag = Tag(tag="foo")
        fam = Family(epithet="Myrtaceae")
        self.session.add_all([fam, tag])
        self.session.commit()
        dialog = TagItemsDialog([fam])
        dialog.run = mock.Mock()
        dialog.start()
        self.assertFalse(dialog.delete_button.get_sensitive())
        self.assertIsNone(dialog.selected_model_row)
        mock_yn_dialog = mock.Mock()

        dialog.on_delete_button_clicked(None, yn_dialog=mock_yn_dialog)

        mock_yn_dialog.assert_not_called()
        self.assertEqual(len(self.session.query(Tag).all()), 1)

        dialog.destroy()


class GlobalFunctionsTests(BaubleTestCase):

    def test_remove_callback_no_confirm(self):
        mock_ynd = mock.Mock(return_value=False)
        mock_mdd = mock.Mock()
        mock_reset = mock.Mock()

        tag = Tag(tag="Foo")
        self.session.add(tag)
        self.session.flush()

        result = remove_callback(
            [tag],
            yes_no_dialog=mock_ynd,
            message_details_dialog=mock_mdd,
            menu_reset=mock_reset,
        )
        self.session.flush()

        mock_mdd.assert_not_called()
        # effect
        mock_ynd.assert_called_with(
            "Are you sure you want to remove Tag: Foo?"
        )
        mock_reset.assert_not_called()

        self.assertFalse(result)
        matching = self.session.query(Tag).filter_by(tag="Foo").all()
        self.assertEqual(matching, [tag])

    def test_remove_callback_confirm(self):
        mock_ynd = mock.Mock(return_value=True)
        mock_mdd = mock.Mock()
        mock_reset = mock.Mock()

        tag = Tag(tag="Foo")
        self.session.add(tag)
        self.session.flush()

        result = remove_callback(
            [tag],
            yes_no_dialog=mock_ynd,
            message_details_dialog=mock_mdd,
            menu_reset=mock_reset,
        )
        self.session.flush()

        mock_reset.assert_called()
        mock_mdd.assert_not_called()
        mock_ynd.assert_called_with(
            "Are you sure you want to remove Tag: Foo?"
        )
        self.assertEqual(result, True)
        matching = self.session.query(Tag).filter_by(tag="Foo").all()
        self.assertEqual(matching, [])

    def test_remove_callback_no_object_session_bails(self):
        mock_ynd = mock.Mock(return_value=True)
        mock_mdd = mock.Mock()
        mock_reset = mock.Mock()
        tag = Tag(tag="Foo")

        with self.assertLogs(level="WARNING") as logs:
            result = remove_callback(
                [tag],
                yes_no_dialog=mock_ynd,
                message_details_dialog=mock_mdd,
                menu_reset=mock_reset,
            )

        string = "no object session bailing."
        self.assertTrue(any(string in i for i in logs.output))
        mock_reset.assert_not_called()
        mock_mdd.assert_not_called()
        mock_ynd.assert_not_called()
        self.assertEqual(result, False)

    def test_remove_callback_warns_if_exception(self):
        mock_ynd = mock.Mock(return_value=True)
        mock_mdd = mock.Mock()
        mock_reset = mock.Mock()
        tag = Tag()
        self.session.add(tag)

        result = remove_callback(
            [tag],
            yes_no_dialog=mock_ynd,
            message_details_dialog=mock_mdd,
            menu_reset=mock_reset,
        )

        mock_reset.assert_called()
        mock_ynd.assert_called()
        mock_mdd.assert_called()
        self.assertEqual(result, True)

    def test_edit_callback_ok(self):
        mock_dialog = mock.Mock()
        mock_dialog.run.return_value = Gtk.ResponseType.OK

        def side_effect(tag):
            tag.tag = "Bar"
            return mock_dialog

        mock_dialog.side_effect = side_effect

        tag = Tag(tag="Foo")
        self.session.add(tag)
        self.session.commit()

        self.assertEqual(
            edit_callback([tag], dialog_cls=mock_dialog),
            Gtk.ResponseType.OK,
        )
        self.assertEqual(tag.tag, "Bar")

    def test_edit_callback_cancel(self):
        mock_dialog = mock.Mock()
        mock_dialog.run.return_value = Gtk.ResponseType.CANCEL

        def side_effect(tag):
            tag.tag = "Bar"
            return mock_dialog

        mock_dialog.side_effect = side_effect

        tag = Tag(tag="Foo")
        self.session.add(tag)
        self.session.commit()

        self.assertEqual(
            edit_callback([tag], dialog_cls=mock_dialog),
            Gtk.ResponseType.CANCEL,
        )
        self.assertEqual(tag.tag, "Foo")

    def test_edit_callback_no_session_raises(self):
        tag = Tag(tag="Foo")

        self.assertRaises(DatabaseError, edit_callback, [tag])
