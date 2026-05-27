# pylint: disable=no-self-use,protected-access
# Copyright (c) 2005,2006,2007,2008,2009 Brett Adams <brett@belizebotanic.org>
# Copyright (c) 2012-2015 Mario Frasca <mario@anche.no>
# Copyright (c) 2021-2026 Ross Demuth <rossdemuth123@gmail.com>
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
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

import bauble
from bauble import db
from bauble import utils
from bauble.error import BaubleError
from bauble.plugins.plants import Family
from bauble.test import BaubleTestCase
from bauble.test import update_gui
from bauble.ui.gui import GUI
from bauble.ui.presenter import Response
from bauble.ui.utils import set_widget_value

from ..model import Tag
from ..ui.editor import TagEditorDialog
from ..ui.editor import TagItemsDialog
from ..ui.editor import edit_callback


class TagEditorDialogTests(BaubleTestCase):
    def setUp(self):
        super().setUp()
        bauble.gui = GUI()

    def tearDown(self):
        super().tearDown()
        bauble.gui.destroy()
        bauble.gui = None

    def test_can_create_dialog(self):
        model = Tag()
        self.session.add(model)
        dialog = TagEditorDialog(model, self.session)
        self.assertEqual(dialog.model, model)
        self.assertTrue(dialog.name_entry.is_focus())
        dialog.destroy()

    def test_populates(self):
        model = Tag(tag="Foo", description="Bar")
        dialog = TagEditorDialog(model, self.session)

        self.assertEqual(dialog.name_entry.get_text(), "Foo")
        buffer = dialog.description_textbuffer
        self.assertEqual(buffer.get_text(*buffer.get_bounds(), False), "Bar")
        dialog.destroy()

    def test_empty_name_is_a_problem(self):
        model = Tag()
        dialog = TagEditorDialog(model, self.session)

        self.assertEqual(
            dialog.problems,
            {
                (
                    "empty::on_unique_text_entry_changed::"
                    f"TagEditorDialog::{id(dialog)}",
                    dialog.name_entry,
                )
            },
        )
        dialog.destroy()

    def test_not_unique_name_is_a_problem(self):
        tag = Tag(tag="Foo")
        self.session.add(tag)
        self.session.commit()

        model = Tag(tag="Foo")
        self.session.add(model)

        dialog = TagEditorDialog(model, self.session)

        self.assertEqual(
            dialog.problems,
            {
                (
                    "not_unique::on_unique_text_entry_changed::"
                    f"TagEditorDialog::{id(dialog)}",
                    dialog.name_entry,
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

        dialog = TagEditorDialog(model, self.session)

        self.assertEqual(dialog.problems, set())
        dialog.destroy()

    def test_on_text_buffer_changed(self):
        model = Tag()
        self.session.add(model)
        dialog = TagEditorDialog(model, self.session)
        text_buffer = dialog.description_textbuffer

        text_buffer.set_text("test")
        dialog.on_text_buffer_changed(text_buffer)
        self.assertEqual(model.description, "test")
        dialog.destroy()

    def test_on_tag_entry_changed(self):
        model = Tag()
        self.session.add(model)
        dialog = TagEditorDialog(model, self.session)
        entry = dialog.name_entry

        entry.set_text("test")
        dialog.on_tag_entry_changed(entry)
        self.assertEqual(model.tag, "test")
        dialog.destroy()

    def test_on_tag_entry_changed_empty_is_a_problem(self):
        model = Tag()
        self.session.add(model)
        dialog = TagEditorDialog(model, self.session)
        entry = dialog.name_entry

        entry.set_text("")
        dialog.on_tag_entry_changed(entry)
        self.assertIsNone(model.tag)
        self.assertEqual(
            dialog.problems,
            {
                (
                    "empty::on_unique_text_entry_changed::"
                    f"TagEditorDialog::{id(dialog)}",
                    dialog.name_entry,
                )
            },
        )
        dialog.destroy()

    def test_editor_doesnt_leak(self):
        editor = TagEditorDialog(
            model=Tag(tag="Spam"),
            session=db.Session(),
        )
        editor.show()
        editor.emit("response", -6)

        del editor
        update_gui()

        self.assertEqual(
            utils.gc_objects_by_type("TagEditorDialog"),
            [],
            "TagEditorDialog not deleted",
        )

    def test_can_commit(self):
        # new
        editor = TagEditorDialog(
            model=Tag(),
            session=db.Session(),
        )

        self.assertFalse(editor.can_commit)
        self.assertFalse(
            editor.get_widget_for_response(Response.OK).get_sensitive()
        )
        self.assertTrue(
            editor.get_widget_for_response(Response.CANCEL).get_sensitive()
        )

        editor.name_entry.set_text("Spam and Eggs")

        self.assertTrue(editor.can_commit)
        self.assertTrue(
            editor.get_widget_for_response(Response.OK).get_sensitive()
        )
        self.assertTrue(
            editor.get_widget_for_response(Response.CANCEL).get_sensitive()
        )

        editor.destroy()

        # existing
        tag = Tag(tag="Spam spam spam")
        self.session.add(tag)
        self.session.commit()

        editor = TagEditorDialog(
            model=tag,
            session=db.Session(),
        )

        self.assertFalse(editor.can_commit)
        self.assertFalse(
            editor.get_widget_for_response(Response.OK).get_sensitive()
        )
        self.assertTrue(
            editor.get_widget_for_response(Response.CANCEL).get_sensitive()
        )

        set_widget_value(editor.description_textbuffer, "and eggs")

        self.assertTrue(editor.can_commit)
        self.assertTrue(
            editor.get_widget_for_response(Response.OK).get_sensitive()
        )
        self.assertTrue(
            editor.get_widget_for_response(Response.CANCEL).get_sensitive()
        )

        editor.destroy()

    @mock.patch("bauble.ui.dialogs.message_details_dialog")
    def test_on_response_ok(self, mock_dlog):
        editor = TagEditorDialog(
            model=Tag(),
            session=db.Session(),
        )
        # force an error, NOTE that the editor should never allow this.
        editor.model.tag = None
        # use emit here to avoid warning due to:
        # `dialog.stop_emission_by_name("response")`
        editor.emit("response", Response.OK)

        update_gui()
        mock_dlog.assert_called_once()
        mock_dlog.reset_mock()

        editor.name_entry.set_text("Eggs")
        self.assertFalse(editor.on_response(editor, Response.OK))

        update_gui()
        mock_dlog.assert_not_called()

        editor.destroy()

    def test_on_response_cancel(self):
        editor = TagEditorDialog(
            model=Tag(),
            session=db.Session(),
        )

        self.assertFalse(editor.on_response(editor, Response.CANCEL))

        editor.destroy()


class TagItemsDialogTests(BaubleTestCase):
    def setUp(self):
        super().setUp()
        bauble.gui = GUI()

    def tearDown(self):
        super().tearDown()
        bauble.gui.destroy()
        bauble.gui = None

    def test_can_create_dialog(self):
        fam = Family(epithet="Myrtaceae")
        dialog = TagItemsDialog([fam], self.session)
        dialog.destroy()

    def test_create_dialog_no_selection_raises_and_logs(self):
        with self.assertLogs(level="WARNING") as logs:
            self.assertRaises(BaubleError, TagItemsDialog, [], self.session)
        string = "No selection provided."
        self.assertTrue(any(string in i for i in logs.output))

    def test_create_dialog_with_selected_set_label(self):
        fam = Family(epithet="Myrtaceae")
        fam2 = Family(epithet="Asteraceae")
        self.session.add_all([fam, fam2])
        self.session.commit()

        dialog = TagItemsDialog([fam, fam2], self.session)

        self.assertEqual(
            dialog.items_data_label.get_text(), "Myrtaceae,  Asteraceae"
        )
        self.assertCountEqual(dialog.selected, [fam, fam2])
        dialog.destroy()

    def test_can_start_dialog(self):
        fam = Family(epithet="Myrtaceae")
        tag = Tag(tag="foo")
        self.session.add_all([fam, tag])
        self.session.commit()
        dialog = TagItemsDialog([fam], self.session)

        with mock.patch.object(dialog, "show") as mock_show:
            dialog.start()

            mock_show.assert_called_once()
        self.assertEqual(len(dialog.tag_tree.get_model()), 1)

        dialog.destroy()

    @mock.patch("bauble.plugins.tag.ui.editor.TagEditorDialog")
    def test_on_new_button_clicked_cancel_doesnt_append(self, mock_editor):
        fam = Family(epithet="Myrtaceae")
        dialog = TagItemsDialog([fam], self.session)
        mock_editor().run.return_value = Response.CANCEL

        dialog.on_new_button_clicked(None)

        self.assertEqual(len(dialog.tag_tree.get_model()), 0)

        dialog.destroy()

    @mock.patch("bauble.plugins.tag.ui.editor.TagEditorDialog.run")
    def test_on_new_button_clicked_ok_appends(self, mock_run):
        fam = Family(epithet="Myrtaceae")
        dialog = TagItemsDialog([fam], self.session)
        mock_run.return_value = Response.OK

        dialog.on_new_button_clicked(None)

        self.assertEqual(len(dialog.tag_tree.get_model()), 1)

        dialog.destroy()

    def test_on_tag_toggled_toggles(self):
        tag = Tag(tag="foo")
        fam = Family(epithet="Myrtaceae")
        self.session.add_all([fam, tag])
        self.session.commit()
        dialog = TagItemsDialog([fam], self.session)
        dialog.start()
        self.assertFalse(tag.is_tagging(fam))
        mock_renderer = mock.Mock()
        # tag
        mock_renderer.get_active.return_value = False

        dialog.on_tag_toggled(mock_renderer, "0")

        self.assertIn(
            ("family", fam.id), [(i.obj_class, i.obj_id) for i in tag.objects_]
        )

        # untag
        mock_renderer.get_active.return_value = True

        dialog.on_tag_toggled(mock_renderer, "0")

        self.assertNotIn(
            ("family", fam.id), [(i.obj_class, i.obj_id) for i in tag.objects_]
        )

        dialog.destroy()

    def test_on_tag_toggled_bails_no_model(self):
        fam = Family(epithet="Myrtaceae")
        dialog = TagItemsDialog([fam], self.session)
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
        dialog = TagItemsDialog([fam], self.session)
        dialog.start()
        self.assertFalse(dialog.delete_button.get_sensitive())
        self.assertIsNone(dialog.selected_model_row)

        dialog.tag_tree.get_selection().select_path(Gtk.TreePath().new_first())

        self.assertIsNotNone(dialog.selected_model_row)
        self.assertTrue(dialog.delete_button.get_sensitive())

        dialog.destroy()

    @mock.patch("bauble.plugins.tag.ui.editor.dialogs.yes_no_dialog")
    def test_on_delete_button_clicked_deletes_selected_if_yes(
        self,
        mock_yn_dialog,
    ):
        tag = Tag(tag="foo")
        fam = Family(epithet="Myrtaceae")
        self.session.add_all([fam, tag])
        self.session.commit()
        dialog = TagItemsDialog([fam], self.session)
        dialog.start()
        self.assertFalse(dialog.delete_button.get_sensitive())
        self.assertIsNone(dialog.selected_model_row)
        dialog.tag_tree.get_selection().select_path(Gtk.TreePath().new_first())
        self.assertEqual(len(self.session.query(Tag).all()), 1)
        mock_yn_dialog.return_value = True

        dialog.on_delete_button_clicked(None)
        self.session.commit()

        mock_yn_dialog.assert_called()
        self.assertEqual(len(self.session.query(Tag).all()), 0)

        dialog.destroy()

    @mock.patch("bauble.plugins.tag.ui.editor.dialogs.yes_no_dialog")
    def test_on_delete_button_clicked_doesnt_delete_selected_if_no(
        self,
        mock_yn_dialog,
    ):
        tag = Tag(tag="foo")
        fam = Family(epithet="Myrtaceae")
        self.session.add_all([fam, tag])
        self.session.commit()
        dialog = TagItemsDialog([fam], self.session)
        dialog.start()
        self.assertFalse(dialog.delete_button.get_sensitive())
        self.assertIsNone(dialog.selected_model_row)
        dialog.tag_tree.get_selection().select_path(Gtk.TreePath().new_first())
        self.assertEqual(len(self.session.query(Tag).all()), 1)
        mock_yn_dialog.return_value = False

        dialog.on_delete_button_clicked(None)
        self.session.commit()

        mock_yn_dialog.assert_called()
        self.assertEqual(len(self.session.query(Tag).all()), 1)

        dialog.destroy()

    @mock.patch("bauble.plugins.tag.ui.editor.dialogs.yes_no_dialog")
    def test_on_delete_button_clicked_bails_no_selected(
        self,
        mock_yn_dialog,
    ):
        tag = Tag(tag="foo")
        fam = Family(epithet="Myrtaceae")
        self.session.add_all([fam, tag])
        self.session.commit()
        dialog = TagItemsDialog([fam], self.session)
        dialog.start()
        self.assertFalse(dialog.delete_button.get_sensitive())
        self.assertIsNone(dialog.selected_model_row)

        dialog.on_delete_button_clicked(None)

        mock_yn_dialog.assert_not_called()
        self.assertEqual(len(self.session.query(Tag).all()), 1)

        dialog.destroy()

    def test_editor_doesnt_leak(self):
        tag = Tag(tag="foo")
        fam = Family(epithet="Myrtaceae")
        self.session.add_all([fam, tag])
        self.session.commit()
        dialog = TagItemsDialog([fam], self.session)
        dialog.start()
        dialog.emit("response", -6)

        del dialog
        update_gui()

        self.assertEqual(
            utils.gc_objects_by_type("TagItemsDialog"),
            [],
            "TagItemsDialog not deleted",
        )

    @mock.patch("bauble.ui.dialogs.message_dialog")
    def test_on_response_ok(self, mock_dlog):
        tag = Tag(tag="foo")
        fam = Family(epithet="Myrtaceae")
        self.session.add_all([fam, tag])
        self.session.commit()
        tag.tag_objects([fam])
        dialog = TagItemsDialog([fam], db.Session())
        with mock.patch.object(dialog.session, "commit") as mock_commit:
            dialog.start()
            mock_commit.side_effect = SQLAlchemyError("BOOM")
            # use emit here to avoid warning due to:
            # `dialog.stop_emission_by_name("response")`
            dialog.emit("response", Response.OK)

        update_gui()
        mock_dlog.assert_called_once()

        dialog.destroy()

        mock_dlog.reset_mock()
        dialog = TagItemsDialog([fam], self.session)
        tag.tag_objects([fam])
        self.assertFalse(dialog.on_response(dialog, Response.OK))

        update_gui()
        tag = self.session.merge(tag)
        fam = self.session.merge(fam)

        mock_dlog.assert_not_called()
        self.assertTrue(tag.is_tagging(fam))

        dialog.destroy()

    def test_on_response_cancel(self):
        tag = Tag(tag="foo")
        fam = Family(epithet="Myrtaceae")
        self.session.add_all([fam, tag])
        self.session.commit()
        tag.tag_objects([fam])
        mock_sess = mock.Mock()
        dialog = TagItemsDialog([fam], mock_sess)

        self.assertFalse(dialog.on_response(dialog, Response.CANCEL))

        update_gui()
        self.session.refresh(tag)

        self.assertFalse(tag.is_tagging(fam))

        dialog.destroy()


class GlobalFunctionsTests(BaubleTestCase):

    def test_edit_callback(self):
        tag = Tag(tag="Foo")
        self.session.add(tag)
        self.session.commit()

        with mock.patch.object(edit_callback, "dialog_class") as mock_editor:

            self.assertFalse(edit_callback([tag]))
            mock_editor.assert_called_once()
            self.assertEqual(mock_editor.call_args.kwargs["model"], tag)
            mock_editor().show.assert_called_once()
