# Copyright (c) 2005,2006,2007,2008,2009 Brett Adams <brett@belizebotanic.org>
# Copyright (c) 2012-2015 Mario Frasca <mario@anche.no>
# Copyright (c) 2022-2025 Ross Demuth <rossdemuth123@gmail.com>
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
#
# test_bauble.py
#

import json
import os
import tempfile
from pathlib import Path
from shutil import copy2
from unittest import TestCase
from unittest import mock

from gi.repository import Gtk

from bauble import db
from bauble import paths
from bauble import prefs
from bauble import utils
from bauble.editor import DocumentBox
from bauble.editor import GenericEditorView
from bauble.editor import GenericPresenter
from bauble.editor import NoteBox
from bauble.editor import NotesPresenter
from bauble.editor import PictureBox
from bauble.editor import PicturesPresenter
from bauble.editor import PresenterLinksMixin
from bauble.editor import PresenterMapMixin
from bauble.editor import Problem
from bauble.meta import BaubleMeta
from bauble.search.strategies import MapperSearch
from bauble.test import BaubleTestCase
from bauble.test import get_setUp_data_funcs


class BaubleTests(BaubleTestCase):
    def test_create_generic_view(self):
        filename = os.path.join(paths.lib_dir(), "bauble.glade")
        view = GenericEditorView(filename)
        self.assertTrue(type(view.widgets) is utils.BuilderWidgets)

    def test_set_title_ok(self):
        filename = os.path.join(paths.lib_dir(), "bauble.glade")
        view = GenericEditorView(filename, root_widget_name="main_window")
        title = "testing"
        view.set_title(title)
        self.assertEqual(view.get_window().get_title(), title)

    def test_set_title_no_root(self):
        filename = os.path.join(paths.lib_dir(), "bauble.glade")
        view = GenericEditorView(filename)
        title = "testing"
        self.assertRaises(NotImplementedError, view.set_title, title)
        self.assertRaises(NotImplementedError, view.get_window)

    def test_set_icon_no_root(self):
        filename = os.path.join(paths.lib_dir(), "bauble.glade")
        view = GenericEditorView(filename)
        title = "testing"
        self.assertRaises(NotImplementedError, view.set_icon, title)

    def test_add_widget(self):
        filename = os.path.join(paths.lib_dir(), "bauble.glade")
        view = GenericEditorView(filename)
        label = Gtk.Label(label="testing")
        view.widget_add("statusbar", label)

    def test_set_accept_buttons_sensitive_not_set(self):
        "it is a task of the presenter to indicate the accept buttons"
        filename = os.path.join(paths.lib_dir(), "connmgr.glade")
        view = GenericEditorView(filename, root_widget_name="main_dialog")
        self.assertIsNone(view.set_accept_buttons_sensitive(False))
        view.get_window().destroy()

    def test_set_sensitive(self):
        filename = os.path.join(paths.lib_dir(), "connmgr.glade")
        view = GenericEditorView(filename, root_widget_name="main_dialog")
        view.widget_set_sensitive("cancel_button", True)
        self.assertTrue(view.widgets.cancel_button.get_sensitive())
        view.widget_set_sensitive("cancel_button", False)
        self.assertFalse(view.widgets.cancel_button.get_sensitive())
        view.get_window().destroy()

    def test_set_visible_get_visible(self):
        filename = os.path.join(paths.lib_dir(), "connmgr.glade")
        view = GenericEditorView(filename, root_widget_name="main_dialog")
        view.widget_set_visible("noconnectionlabel", True)
        self.assertTrue(view.widget_get_visible("noconnectionlabel"))
        self.assertTrue(view.widgets.noconnectionlabel.get_visible())
        view.widget_set_visible("noconnectionlabel", False)
        self.assertFalse(view.widget_get_visible("noconnectionlabel"))
        self.assertFalse(view.widgets.noconnectionlabel.get_visible())
        view.get_window().destroy()


import datetime

from dateutil.parser import parse as parse_date


class TimeStampParserTests(TestCase):
    def test_date_parser_generic(self):
        import dateutil

        target = parse_date("2019-01-18 18:20 +0500")
        result = parse_date("18 January 2019 18:20 +0500")
        self.assertEqual(result, target)
        result = parse_date("18:20, 18 January 2019 +0500")
        self.assertEqual(result, target)
        result = parse_date("18:20+0500, 18 January 2019")
        self.assertEqual(result, target)
        result = parse_date("18:20+0500, 18 Jan 2019")
        self.assertEqual(result, target)
        result = parse_date("18:20+0500, 2019-01-18")
        self.assertEqual(result, target)
        result = parse_date("18:20+0500, 1/18 2019")
        self.assertEqual(result, target)
        result = parse_date("18:20+0500, 18/1 2019")
        self.assertEqual(result, target)

    def test_date_parser_ambiguous(self):
        ## defaults to European: day, month, year - FAILS
        # result = parse_date('5 1 4')
        # self.assertEquals(result, datetime.datetime(2004, 1, 5, 0, 0))
        # explicit, American: month, day, year
        result = parse_date("5 1 4", dayfirst=False, yearfirst=False)
        self.assertEqual(result, datetime.datetime(2004, 5, 1, 0, 0))
        # explicit, European: day, month, year
        result = parse_date("5 1 4", dayfirst=True, yearfirst=False)
        self.assertEqual(result, datetime.datetime(2004, 1, 5, 0, 0))
        # explicit, Japanese: year, month, day (month, day, year)
        result = parse_date("5 1 4", dayfirst=False, yearfirst=True)
        self.assertEqual(result, datetime.datetime(2005, 1, 4, 0, 0))
        ## explicit, illogical: year, day, month - FAILS
        # result = parse_date('5 1 4', dayfirst=True, yearfirst=True)
        # self.assertEquals(result, datetime.datetime(2005, 4, 1, 0, 0))

    def test_date_parser_365(self):
        target = datetime.datetime(2014, 1, 1, 20)
        result = parse_date("2014-01-01 20")
        self.assertEqual(result, target)
        target = parse_date("2014-01-01 20:00 +0000")
        result = parse_date("2014-01-01 20+0")
        self.assertEqual(result, target)


class NoteBoxTests(BaubleTestCase):
    def setUp(self):
        super().setUp()
        # get the first note class
        for klass in MapperSearch.get_domain_classes().values():
            if hasattr(klass, "notes") and hasattr(klass.notes, "mapper"):
                self.parent_model = klass()
                note_cls = klass.notes.mapper.class_
                self.model = note_cls()
                self.session.add(self.model)
                break

    def test_note_box_set_contents_sets_widget(self):
        presenter = mock.Mock(model=self.model)
        box = NoteBox(presenter, self.model)
        self.assertTrue(box)
        # test set_contents set widget value.
        test_str = "test string"
        box.set_content(test_str)
        self.assertEqual(utils.get_widget_value(box.note_textview), test_str)

    def test_note_box_set_widget_set_model(self):
        presenter = mock.Mock(model=self.model)
        box = NoteBox(presenter, self.model)
        self.assertTrue(box)
        # test set widget sets model value
        test_str = "test string"
        utils.set_widget_value(box.note_textview, test_str)
        self.assertEqual(self.model.note, test_str)

    def test_note_box_on_notes_remove_button_removes_note(self):
        presenter = mock.Mock(model=self.model, notes=[self.model])
        box = NoteBox(presenter, self.model)
        self.assertIn(self.model, presenter.notes)
        box.on_notes_remove_button(None)
        self.assertNotIn(self.model, presenter.notes)

    def test_note_box_on_date_entry_changed_sets_attr(self):
        presenter = mock.Mock(model=self.model, notes=[self.model])
        box = NoteBox(presenter, self.model)
        self.assertIsNone(self.model.date)
        date = "25/10/2022"
        box.date_entry.set_text(date)
        self.assertEqual(self.model.date, date)

    def test_note_box_on_user_entry_changed_sets_attr(self):
        presenter = mock.Mock(model=self.model, notes=[self.model])
        box = NoteBox(presenter, self.model)
        self.assertIsNone(self.model.date)
        user = "Test User"
        box.user_entry.set_text(user)
        self.assertEqual(self.model.user, user)

    def test_note_box_on_category_combo_changed_sets_attr(self):
        presenter = mock.Mock(model=self.model, notes=[self.model])
        box = NoteBox(presenter, self.model)
        self.assertIsNone(self.model.date)
        cat = "Test Category"
        utils.set_widget_value(box.category_comboentry, cat)
        self.assertEqual(self.model.category, cat)

    def test_presenter_on_add_button_adds_context_box(self):
        presenter = mock.Mock(model=self.parent_model)
        parent = Gtk.Box()
        notes_presenter = NotesPresenter(presenter, "notes", parent)
        start = len(notes_presenter.box.get_children())
        notes_presenter.on_add_button_clicked(None)
        self.assertEqual(len(notes_presenter.box.get_children()) - start, 1)

    def test_note_box_on_notes_remove_button_after_failed_commit(self):
        self.session.close()
        self.session = db.Session()
        self.session.add(self.parent_model)
        self.parent_model.epithet = "Test"
        self.session.commit()
        presenter = mock.Mock(model=self.parent_model)
        parent = Gtk.Box()
        notes_presenter = NotesPresenter(presenter, "notes", parent)
        start = len(notes_presenter.box.get_children())
        self.assertEqual(len(presenter.model.notes), 0)
        notes_presenter.on_add_button_clicked(None)
        self.assertEqual(len(notes_presenter.box.get_children()) - start, 1)
        self.assertEqual(len(presenter.model.notes), 1)
        try:
            self.session.commit()  # fails with NOT NULL on note.note
        except Exception:
            self.session.rollback()

        notes_presenter.box.get_children()[0].on_notes_remove_button(None)
        self.assertEqual(len(presenter.model.notes), 0)
        self.session.commit()  # doesn't fail


class PictureBoxTests(BaubleTestCase):
    def setUp(self):
        super().setUp()
        # get the first picture class
        for klass in MapperSearch.get_domain_classes().values():
            if hasattr(klass, "pictures") and hasattr(
                klass.pictures, "mapper"
            ):
                self.parent_model = klass()
                note_cls = klass.pictures.mapper.class_
                self.model = note_cls()
                self.parent_model.pictures.append(self.model)
                self.session.add(self.model)
                break

    @mock.patch("bauble.utils.ImageLoader")
    def test_picture_box_set_contents_calls_imageloader_for_url(
        self, mockloader
    ):
        presenter = mock.Mock(model=self.model)
        box = PictureBox(presenter, self.model)
        self.assertTrue(box)
        # sets widgets
        test_str = "http://test.org"
        box.set_content(test_str)
        self.assertEqual(utils.get_widget_value(box.file_entry), test_str)
        self.assertIsInstance(box.picture_box.get_children()[0], Gtk.Box)
        mockloader.assert_called()

    def test_picture_box_set_contents_adds_label_for_none_existing(self):
        presenter = mock.Mock(model=self.model)
        box = PictureBox(presenter, self.model)
        self.assertTrue(box)
        # sets widgets none existing image
        test_str = "test.jpg"
        box.set_content(test_str)
        self.assertEqual(utils.get_widget_value(box.file_entry), test_str)
        self.assertIsInstance(box.picture_box.get_children()[0], Gtk.Label)
        self.assertIn(test_str, box.picture_box.get_children()[0].get_text())

    def test_picture_box_set_contents_adds_pixbuff_for_existing(self):
        prefs.prefs[prefs.root_directory_pref] = os.path.join(paths.lib_dir())
        prefs.prefs[prefs.picture_path_pref] = "images"
        presenter = mock.Mock(model=self.model)
        box = PictureBox(presenter, self.model)
        self.assertTrue(box)
        # sets widgets none existing image
        test_str = "dmg_background.png"
        box.set_content(test_str)
        self.assertEqual(utils.get_widget_value(box.file_entry), test_str)
        self.assertIsInstance(box.picture_box.get_children()[0], Gtk.Image)

    def test_picture_box_set_contents_adds_label_for_none(self):
        presenter = mock.Mock(model=self.model)
        box = PictureBox(presenter, self.model)
        self.assertTrue(box)
        # sets widgets none existing image
        box.set_content(None)
        self.assertEqual(utils.get_widget_value(box.file_entry), "")
        self.assertIsInstance(box.picture_box.get_children()[0], Gtk.Label)
        self.assertIn(
            "Choose a file", box.picture_box.get_children()[0].get_text()
        )

    @mock.patch(
        "bauble.utils.yes_no_dialog", return_value=Gtk.ResponseType.YES
    )
    @mock.patch("bauble.editor.DefaultCommandHandler")
    def test_picture_box_on_notes_remove_button_empty_entry(
        self, mock_handler, mock_dlog
    ):
        temp = tempfile.mkdtemp()
        prefs.prefs[prefs.root_directory_pref] = temp

        self.model.picture = None

        mock_parent = mock.Mock(view=None)
        presenter = mock.Mock(
            model=self.model,
            notes=[self.model],
            **{"parent_ref.return_value": mock_parent},
        )
        box = PictureBox(presenter, self.model)
        self.assertIn(self.model, presenter.notes)
        box.on_notes_remove_button(None)
        mock_dlog.assert_not_called()
        self.assertNotIn(self.model, presenter.notes)
        self.assertEqual(
            mock_handler().get_view().pictures_scroller.selection, []
        )

    @mock.patch(
        "bauble.utils.yes_no_dialog", return_value=Gtk.ResponseType.YES
    )
    @mock.patch("bauble.editor.DefaultCommandHandler")
    def test_picture_box_on_notes_remove_button_removes_image(
        self, mock_handler, mock_dlog
    ):
        temp = tempfile.mkdtemp()
        prefs.prefs[prefs.root_directory_pref] = temp
        os.mkdir(os.path.join(temp, "pictures"))
        os.mkdir(os.path.join(temp, "pictures", "thumbs"))
        img_name = "dmg_background.png"
        img_full_path = os.path.join(paths.lib_dir(), "images", img_name)
        copy2(img_full_path, os.path.join(temp, "pictures"))
        copy2(img_full_path, os.path.join(temp, "pictures", "thumbs"))

        self.model.picture = img_name

        mock_parent = mock.Mock(view=None)
        presenter = mock.Mock(
            model=self.model,
            notes=[self.model],
            **{"parent_ref.return_value": mock_parent},
        )
        box = PictureBox(presenter, self.model)
        self.assertTrue(
            os.path.isfile(os.path.join(temp, "pictures", img_name))
        )
        self.assertTrue(
            os.path.isfile(os.path.join(temp, "pictures", "thumbs", img_name))
        )
        box.on_notes_remove_button(None)
        self.assertFalse(
            os.path.isfile(os.path.join(temp, "pictures", img_name))
        )
        self.assertFalse(
            os.path.isfile(os.path.join(temp, "pictures", "thumbs", img_name))
        )
        msg = mock_dlog.call_args.args[0]
        self.assertNotIn("the same file", msg)
        self.assertEqual(
            mock_handler().get_view().pictures_scroller.selection, []
        )

    @mock.patch(
        "bauble.utils.yes_no_dialog", return_value=Gtk.ResponseType.YES
    )
    @mock.patch("bauble.editor.DefaultCommandHandler")
    def test_picture_box_remove_others_same_type_warns(
        self, _mock_handler, mock_dlog
    ):
        for func in get_setUp_data_funcs():
            func()
        temp = tempfile.mkdtemp()
        prefs.prefs[prefs.root_directory_pref] = temp
        os.mkdir(os.path.join(temp, "pictures"))
        img_name = "dmg_background.png"
        img_full_path = os.path.join(paths.lib_dir(), "images", img_name)
        copy2(img_full_path, os.path.join(temp, "pictures"))

        from sqlalchemy import Unicode

        # create fake data and add a second model of different type with same
        # img.  Commit the lot.
        self.model.picture = img_name
        for col in self.parent_model.__table__.columns:
            if not col.nullable and col.name != "id":
                if col.name.endswith("_id"):
                    setattr(self.parent_model, col.name, 1)
                if not getattr(self.parent_model, col.name):
                    setattr(self.parent_model, col.name, "123")
            elif isinstance(col.type, Unicode):
                setattr(self.parent_model, col.name, "987")

        note_cls = type(self.model)
        parent_model = type(self.parent_model)()
        model2 = note_cls(picture=img_name)
        parent_model.pictures.append(model2)
        self.session.add(model2)

        for col in parent_model.__table__.columns:
            if not col.nullable and col.name != "id":
                if col.name.endswith("_id"):
                    setattr(parent_model, col.name, 1)
                if not getattr(parent_model, col.name):
                    setattr(parent_model, col.name, "345")
            elif isinstance(col.type, Unicode):
                setattr(parent_model, col.name, "567")

        self.session.commit()

        self.assertIs(type(self.model), type(model2))

        mock_parent = mock.Mock(view=None)
        presenter = mock.Mock(
            model=self.model,
            notes=[self.model, model2],
            **{"parent_ref.return_value": mock_parent},
        )
        box = PictureBox(presenter, self.model)
        self.assertTrue(
            os.path.isfile(os.path.join(temp, "pictures", img_name))
        )
        box.on_notes_remove_button(None)
        self.assertFalse(
            os.path.isfile(os.path.join(temp, "pictures", img_name))
        )
        msg = mock_dlog.call_args.args[0]
        self.assertIn("1 other", msg)
        self.assertIn(f"of type {note_cls.__tablename__}", msg)

    @mock.patch(
        "bauble.utils.yes_no_dialog", return_value=Gtk.ResponseType.YES
    )
    @mock.patch("bauble.editor.DefaultCommandHandler")
    def test_picture_box_remove_others_dif_types_warns(
        self, _mock_handler, mock_dlog
    ):
        for func in get_setUp_data_funcs():
            func()
        temp = tempfile.mkdtemp()
        prefs.prefs[prefs.root_directory_pref] = temp
        img_name = "dmg_background.png"
        img_full_path = os.path.join(paths.lib_dir(), "images", img_name)
        os.mkdir(os.path.join(temp, "pictures"))
        copy2(img_full_path, os.path.join(temp, "pictures"))

        # create fake data and add a second model of different type with same
        # img.  Commit the lot.
        self.model.picture = img_name
        for col in self.parent_model.__table__.columns:
            if not col.nullable:
                if col.name.endswith("_id"):
                    setattr(self.parent_model, col.name, 1)
                if not getattr(self.parent_model, col.name):
                    setattr(self.parent_model, col.name, "456")

        # get a different note class
        for klass in MapperSearch.get_domain_classes().values():
            if hasattr(klass, "_pictures") and hasattr(
                klass._pictures, "mapper"
            ):
                note_cls = klass._pictures.mapper.class_
                if type(self.model) is not note_cls:
                    parent_model = klass()
                    model2 = note_cls(picture=img_name)
                    parent_model._pictures.append(model2)
                    self.session.add(model2)
                    break

        for col in parent_model.__table__.columns:
            if not col.nullable:
                if col.name.endswith("_id"):
                    setattr(parent_model, col.name, 1)
                if not getattr(parent_model, col.name):
                    setattr(parent_model, col.name, "567")

        self.session.commit()

        self.assertIsNot(type(self.model), type(model2))

        mock_parent = mock.Mock(view=None)
        presenter = mock.Mock(
            model=self.model,
            notes=[self.model, model2],
            **{"parent_ref.return_value": mock_parent},
        )
        box = PictureBox(presenter, self.model)
        self.assertTrue(
            os.path.isfile(os.path.join(temp, "pictures", img_name))
        )
        box.on_notes_remove_button(None)
        self.assertFalse(
            os.path.isfile(os.path.join(temp, "pictures", img_name))
        )
        msg = mock_dlog.call_args.args[0]
        self.assertIn("1 other", msg)
        self.assertIn(f"of type {note_cls.__tablename__}", msg)

    @mock.patch("bauble.utils.Gtk.FileChooserNative.new")
    def test_picture_box_on_file_btnbrowse_clicked_copies_file(self, mock_fc):
        temp = tempfile.mkdtemp()
        prefs.prefs[prefs.root_directory_pref] = temp
        os.makedirs(os.path.join(temp, "pictures", "thumbs"))
        img_name = "dmg_background.png"
        img_full_path = os.path.join(paths.lib_dir(), "images", img_name)
        mock_fc().get_filenames.return_value = [img_full_path]
        presenter = mock.Mock(model=self.model, notes=[self.model])
        box = PictureBox(presenter, self.model)
        box.on_file_btnbrowse_clicked(None)
        self.assertTrue(
            os.path.isfile(os.path.join(temp, "pictures", img_name))
        )
        self.assertTrue(
            os.path.isfile(os.path.join(temp, "pictures", "thumbs", img_name))
        )

    @mock.patch("bauble.utils.Gtk.FileChooserNative.new")
    def test_picture_box_on_file_btnbrowse_clicked_multi_files(self, mock_fc):
        temp = tempfile.mkdtemp()
        prefs.prefs[prefs.root_directory_pref] = temp
        os.makedirs(os.path.join(temp, "pictures", "thumbs"))
        img_name = "bauble_logo.png"
        img_full_path = os.path.join(paths.lib_dir(), "images", img_name)
        img_name2 = "dmg_background.png"
        img_full_path2 = os.path.join(paths.lib_dir(), "images", img_name2)
        mock_fc().get_filenames.return_value = [img_full_path, img_full_path2]
        presenter = mock.Mock(model=self.parent_model, notes=[self.model])
        parent = Gtk.Box()
        pic_presenter = PicturesPresenter(presenter, "pictures", parent)
        box = PictureBox(pic_presenter, self.model)
        utils.set_widget_value(box.category_comboentry, "test")
        self.assertEqual(self.model.category, "test")
        box.on_file_btnbrowse_clicked(None)
        self.assertEqual(len(self.parent_model.pictures), 2)
        for i in self.parent_model.pictures:
            self.assertEqual(i.category, "test")
        self.assertTrue(
            os.path.isfile(os.path.join(temp, "pictures", img_name))
        )
        self.assertTrue(
            os.path.isfile(os.path.join(temp, "pictures", "thumbs", img_name))
        )
        self.assertTrue(
            os.path.isfile(os.path.join(temp, "pictures", img_name2))
        )
        self.assertTrue(
            os.path.isfile(os.path.join(temp, "pictures", "thumbs", img_name2))
        )

    @mock.patch("bauble.utils.Gtk.FileChooserNative.new")
    def test_on_file_btnbrowse_clicked_rename_if_file_exists(self, mock_fc):
        temp = tempfile.mkdtemp()
        prefs.prefs[prefs.root_directory_pref] = temp
        os.makedirs(os.path.join(temp, "pictures", "thumbs"))
        img_name = "dmg_background.png"
        img_full_path = os.path.join(paths.lib_dir(), "images", img_name)
        mock_fc().get_filenames.return_value = [img_full_path]
        mock_parent = mock.Mock(view=None)
        presenter = mock.Mock(
            model=self.model,
            documents=[self.model],
            **{"parent_ref.return_value": mock_parent},
        )
        box = PictureBox(presenter, self.model)
        pic_root = prefs.prefs[prefs.picture_root_pref]
        Path(pic_root, img_name).touch()
        with mock.patch(
            "bauble.editor.utils.yes_no_dialog",
            return_value=Gtk.ResponseType.YES,
        ) as mock_dialog:
            box.on_file_btnbrowse_clicked(None)
            mock_dialog.assert_called_once()
        files = []
        for file in os.listdir(prefs.prefs[prefs.picture_root_pref]):
            if os.path.isfile(os.path.join(pic_root, file)):
                files.append(file)
                self.assertTrue(file.startswith("dmg_background"))
        self.assertEqual(len(files), 2)

    @mock.patch("bauble.utils.Gtk.FileChooserNative.new")
    def test_on_file_btnbrowse_clicked_file_exists_user_bails(self, mock_fc):
        temp = tempfile.mkdtemp()
        prefs.prefs[prefs.root_directory_pref] = temp
        os.makedirs(os.path.join(temp, "pictures", "thumbs"))
        img_name = "bauble_logo.png"
        img_full_path = os.path.join(paths.lib_dir(), "images", img_name)
        img_name2 = "dmg_background.png"
        img_full_path2 = os.path.join(paths.lib_dir(), "images", img_name2)
        mock_fc().get_filenames.return_value = [img_full_path, img_full_path2]
        self.parent_model.pictures = []
        self.assertEqual(len(self.parent_model.pictures), 0)
        presenter = mock.Mock(model=self.parent_model, notes=[self.model])
        parent = Gtk.Box()
        pic_presenter = PicturesPresenter(presenter, "pictures", parent)
        box = PictureBox(pic_presenter, self.model)
        pic_root = prefs.prefs[prefs.picture_root_pref]
        Path(pic_root, img_name).touch()
        Path(pic_root, img_name2).touch()
        with mock.patch(
            "bauble.editor.utils.yes_no_dialog", return_value=False
        ) as mock_dialog:
            box.on_file_btnbrowse_clicked(None)
            self.assertEqual(mock_dialog.call_count, 2)
        self.assertCountEqual(
            os.listdir(prefs.prefs[prefs.picture_root_pref]),
            [img_name, img_name2, "thumbs"],
        )
        self.assertEqual(len(self.parent_model.pictures), 0)
        self.assertEqual(len(pic_presenter.box.get_children()), 0)


class DocumentBoxTests(BaubleTestCase):
    def setUp(self):
        super().setUp()
        # get the first note class
        self.doc_name = "test.txt"
        temp = tempfile.mkdtemp()
        self.test_doc = os.path.join(temp, self.doc_name)
        with open(self.test_doc, "w", encoding="utf-8") as f:
            f.write("a line of test text")
        for klass in MapperSearch.get_domain_classes().values():
            if hasattr(klass, "documents") and hasattr(
                klass.documents, "mapper"
            ):
                self.parent_model = klass()
                note_cls = klass.documents.mapper.class_
                self.model = note_cls()
                self.parent_model.documents.append(self.model)
                self.session.add(self.model)
                break

    def tearDown(self):
        super().tearDown()
        os.remove(self.test_doc)

    def test_set_contents_sets_widget(self):
        presenter = mock.Mock(model=self.model)
        box = DocumentBox(presenter, self.model)
        self.assertTrue(box)
        # test set_contents set widget value.
        test_str = "test string"
        box.set_content(test_str)
        self.assertEqual(utils.get_widget_value(box.file_entry), test_str)

    def test_set_note_contents_sets_widget(self):
        presenter = mock.Mock(model=self.model)
        box = DocumentBox(presenter, self.model)
        self.assertTrue(box)
        # test set_contents set widget value.
        test_str = "test string"
        box.set_note_content(test_str)
        self.assertEqual(utils.get_widget_value(box.note_textview), test_str)

    def test_set_widget_set_model(self):
        presenter = mock.Mock(model=self.model)
        box = DocumentBox(presenter, self.model)
        self.assertTrue(box)
        # test set widget sets model value
        test_str = "test string"
        utils.set_widget_value(box.note_textview, test_str)
        self.assertEqual(self.model.note, test_str)

    def test_on_notes_remove_button_removes_note(self):
        presenter = mock.Mock(model=self.model, notes=[self.model])
        box = DocumentBox(presenter, self.model)
        self.assertIn(self.model, presenter.notes)
        box.on_notes_remove_button(None)
        self.assertNotIn(self.model, presenter.notes)

    def test_on_date_entry_changed_sets_attr(self):
        presenter = mock.Mock(model=self.model, notes=[self.model])
        box = DocumentBox(presenter, self.model)
        self.assertIsNone(self.model.date)
        date = "25/10/2022"
        box.date_entry.set_text(date)
        self.assertEqual(self.model.date, date)

    def test_on_user_entry_changed_sets_attr(self):
        presenter = mock.Mock(model=self.model, notes=[self.model])
        box = DocumentBox(presenter, self.model)
        self.assertIsNone(self.model.date)
        user = "Test User"
        box.user_entry.set_text(user)
        self.assertEqual(self.model.user, user)

    def test_on_category_combo_changed_sets_attr(self):
        presenter = mock.Mock(model=self.model, notes=[self.model])
        box = DocumentBox(presenter, self.model)
        self.assertIsNone(self.model.date)
        cat = "Test Category"
        utils.set_widget_value(box.category_comboentry, cat)
        self.assertEqual(self.model.category, cat)

    @mock.patch(
        "bauble.utils.yes_no_dialog", return_value=Gtk.ResponseType.YES
    )
    def test_on_notes_remove_button_empty_entry(self, mock_dlog):
        temp = tempfile.mkdtemp()
        prefs.prefs[prefs.root_directory_pref] = temp

        self.model.document = None

        mock_parent = mock.Mock(view=None)
        presenter = mock.Mock(
            model=self.model,
            notes=[self.model],
            **{"parent_ref.return_value": mock_parent},
        )
        box = DocumentBox(presenter, self.model)
        self.assertIn(self.model, presenter.notes)
        box.on_notes_remove_button(None)
        mock_dlog.assert_not_called()
        self.assertNotIn(self.model, presenter.notes)

    @mock.patch(
        "bauble.utils.yes_no_dialog", return_value=Gtk.ResponseType.YES
    )
    def test_on_notes_remove_button_removes_document(self, mock_dlog):
        temp = tempfile.mkdtemp()
        prefs.prefs[prefs.root_directory_pref] = temp
        os.mkdir(os.path.join(temp, "documents"))
        copy2(self.test_doc, os.path.join(temp, "documents"))

        self.model.document = self.doc_name

        mock_parent = mock.Mock(view=None)
        presenter = mock.Mock(
            model=self.model,
            notes=[self.model],
            **{"parent_ref.return_value": mock_parent},
        )
        box = DocumentBox(presenter, self.model)
        self.assertTrue(
            os.path.isfile(os.path.join(temp, "documents", self.doc_name))
        )
        box.on_notes_remove_button(None)
        self.assertFalse(
            os.path.isfile(os.path.join(temp, "documents", self.doc_name))
        )
        msg = mock_dlog.call_args.args[0]
        self.assertNotIn("the same file", msg)

    @mock.patch(
        "bauble.utils.yes_no_dialog", return_value=Gtk.ResponseType.YES
    )
    def test_remove_others_same_type_warns(self, mock_dlog):
        for func in get_setUp_data_funcs():
            func()
        temp = tempfile.mkdtemp()
        prefs.prefs[prefs.root_directory_pref] = temp
        os.mkdir(os.path.join(temp, "documents"))
        copy2(self.test_doc, os.path.join(temp, "documents"))

        # create fake data and add a second model of different type with same
        # img.  Commit the lot.
        self.model.document = self.doc_name
        for col in self.parent_model.__table__.columns:
            if not col.nullable:
                if col.name.endswith("_id"):
                    setattr(self.parent_model, col.name, 1)
                if not getattr(self.parent_model, col.name):
                    setattr(self.parent_model, col.name, "123")

        note_cls = type(self.model)
        parent_model = type(self.parent_model)()
        model2 = note_cls(document=self.doc_name)
        parent_model.documents.append(model2)
        self.session.add(model2)

        for col in parent_model.__table__.columns:
            if not col.nullable:
                if col.name.endswith("_id"):
                    setattr(parent_model, col.name, 1)
                if not getattr(parent_model, col.name):
                    setattr(parent_model, col.name, "345")

        self.session.commit()

        self.assertIs(type(self.model), type(model2))

        mock_parent = mock.Mock(view=None)
        presenter = mock.Mock(
            model=self.model,
            notes=[self.model, model2],
            **{"parent_ref.return_value": mock_parent},
        )
        box = DocumentBox(presenter, self.model)
        self.assertTrue(
            os.path.isfile(os.path.join(temp, "documents", self.doc_name))
        )
        box.on_notes_remove_button(None)
        self.assertFalse(
            os.path.isfile(os.path.join(temp, "documents", self.doc_name))
        )
        msg = mock_dlog.call_args.args[0]
        self.assertIn("1 other", msg)
        self.assertIn(f"of type {note_cls.__tablename__}", msg)

    # # NOTE Impliment if other type are added
    # def test_remove_others_dif_types_warns(self, mock_dlog):
    #     pass

    @mock.patch("bauble.utils.Gtk.FileChooserNative")
    def test_on_file_btnbrowse_clicked_copies_file(self, mock_fc):
        self.assertTrue(os.path.isfile(self.test_doc))
        temp = tempfile.mkdtemp()
        prefs.prefs[prefs.root_directory_pref] = temp
        os.mkdir(os.path.join(temp, "documents"))
        mock_fc().get_filename.return_value = self.test_doc
        presenter = mock.Mock(model=self.model, documents=[self.model])
        box = DocumentBox(presenter, self.model)
        box.on_file_btnbrowse_clicked(None)
        self.assertTrue(
            os.path.isfile(os.path.join(temp, "documents", self.doc_name))
        )

    @mock.patch("bauble.utils.Gtk.FileChooserNative")
    def test_on_file_btnbrowse_clicked_rename_if_file_exists(self, mock_fc):
        self.assertTrue(os.path.isfile(self.test_doc))
        temp = tempfile.mkdtemp()
        prefs.prefs[prefs.root_directory_pref] = temp
        os.mkdir(os.path.join(temp, "documents"))
        mock_fc().get_filename.return_value = self.test_doc
        mock_parent = mock.Mock(view=None)
        presenter = mock.Mock(
            model=self.model,
            documents=[self.model],
            **{"parent_ref.return_value": mock_parent},
        )
        box = DocumentBox(presenter, self.model)
        Path(temp, "documents", self.doc_name).touch()
        with mock.patch(
            "bauble.editor.utils.yes_no_dialog",
            return_value=Gtk.ResponseType.YES,
        ) as mock_dialog:
            box.on_file_btnbrowse_clicked(None)
            mock_dialog.assert_called_once()
        files = []
        for file in os.listdir(prefs.prefs[prefs.document_root_pref]):
            if os.path.isfile(
                os.path.join(prefs.prefs[prefs.document_root_pref], file)
            ):
                files.append(file)
                self.assertTrue(file.startswith("test"))
        self.assertEqual(len(files), 2)

    # Test the menu button mixin
    @mock.patch("bauble.utils.desktop.open")
    def test_on_file_open_clicked(self, mock_open):
        presenter = mock.Mock(model=self.model)
        box = DocumentBox(presenter, self.model)
        # test set widget sets model value
        test_str = "test.txt"
        utils.set_widget_value(box.file_entry, test_str)
        box.on_file_open_clicked(None)
        self.assertEqual(
            mock_open.call_args.args[0], os.path.join("documents", test_str)
        )

    # Test the menu button mixin
    @mock.patch("bauble.gui")
    def test_on_copy_filename(self, mock_gui):
        mock_clipboard = mock.Mock()
        mock_gui.get_display_clipboard.return_value = mock_clipboard
        presenter = mock.Mock(model=self.model)
        box = DocumentBox(presenter, self.model)
        # test set widget sets model value
        test_str = "test.txt"
        utils.set_widget_value(box.file_entry, test_str)
        box.on_copy_filename(None)
        mock_clipboard.set_text.assert_called_with(test_str, -1)


class LinksMixinTests(BaubleTestCase):
    def setUp(self):
        super().setUp()
        mock_model = mock.Mock(
            __tablename__="test",
            __str__=lambda s: "Test test",
            genus=mock.Mock(genus="Test"),
            sp="test",
        )
        self.link_button = Gtk.MenuButton()
        mock_view = mock.Mock(**{"widgets.link_menu_btn": self.link_button})
        PresenterLinksMixin.model = mock_model
        PresenterLinksMixin.view = mock_view
        PresenterLinksMixin.LINK_BUTTONS_PREF_KEY = "web_button_defs.fam"
        prefs.prefs["web_button_defs.fam.googlebutton"] = {
            "_base_uri": "http://www.google.com/search?q=%s",
            "_space": "+",
            "title": "Search Google",
            "tooltip": None,
        }
        self.mixin = PresenterLinksMixin()

    def tearDown(self):
        super().tearDown()
        del PresenterLinksMixin.model
        del PresenterLinksMixin.view
        del PresenterLinksMixin.LINK_BUTTONS_PREF_KEY

    def test_init_menu(self):
        self.mixin.init_links_menu()
        self.assertIsNone(self.link_button.get_menu_model())
        self.assertFalse(self.link_button.get_visible())

        prefs.prefs["web_button_defs.fam.googlebutton"] = {
            "_base_uri": "http://www.google.com/search?q=%s",
            "_space": "+",
            "title": "Search Google",
            "tooltip": None,
            "editor_button": True,
        }
        self.mixin.init_links_menu()
        self.assertEqual(self.link_button.get_menu_model().get_n_items(), 1)

    @mock.patch("bauble.utils.desktop.open")
    def test_on_item_selected(self, mock_open):
        google = {
            "_base_uri": "http://www.google.com/search?q=%s",
            "_space": "+",
            "title": "Search Google",
            "tooltip": None,
            "editor_button": True,
        }
        self.mixin.on_item_selected(None, None, google)
        mock_open.assert_called_with(
            "http://www.google.com/search?q=Test+test"
        )

    def test_get_url(self):
        # no fields
        google = {
            "_base_uri": "http://www.google.com/search?q=%s",
            "_space": "+",
            "title": "Search Google",
            "tooltip": None,
            "editor_button": True,
        }
        self.assertEqual(
            self.mixin.get_url(google),
            "http://www.google.com/search?q=Test+test",
        )
        # with fields
        ipni = {
            "_base_uri": (
                "http://www.ipni.org/ipni/advPlantNameSearch.do?"
                "find_genus=%(genus.genus)s&find_species=%(sp)s&"
                "find_isAPNIRecord=on"
            ),
            "_space": " ",
            "title": "Search IPNI",
            "tooltip": "Search the International Plant Names Index",
        }
        self.assertEqual(
            self.mixin.get_url(ipni),
            (
                "http://www.ipni.org/ipni/advPlantNameSearch.do?"
                "find_genus=Test&find_species=test&find_isAPNIRecord=on"
            ),
        )


class MapMixinTests(BaubleTestCase):
    def setUp(self):
        super().setUp()
        with mock.patch("bauble.editor.PresenterMapMixin.init_map_menu"):
            self.mixin = PresenterMapMixin()
            self.mixin.refresh_sensitivity = mock.Mock()
            self.geojson = {"test": "value"}
            self.mixin.model = mock.Mock(
                __tablename__="test", geojson=self.geojson
            )
            self.mixin.view = mock.Mock()

    def test_on_map_delete(self):
        self.assertEqual(self.mixin.model.geojson, self.geojson)
        self.mixin.on_map_delete()
        self.assertIsNone(self.mixin.model.geojson)
        self.mixin.refresh_sensitivity.assert_called()

    @mock.patch("bauble.gui")
    def test_on_map_copy(self, mock_gui):
        mock_clipboard = mock.Mock()
        mock_gui.get_display_clipboard.return_value = mock_clipboard
        self.mixin.on_map_copy()
        self.assertEqual(self.mixin.model.geojson, self.geojson)
        mock_clipboard.set_text.assert_called_with(
            json.dumps(self.geojson), -1
        )

    @mock.patch("bauble.gui")
    def test_on_map_paste(self, mock_gui):
        mock_clipboard = mock.Mock()
        geojson = {"type": "TEST", "coordinates": "test"}
        mock_clipboard.wait_for_text.return_value = json.dumps(geojson)
        mock_gui.get_display_clipboard.return_value = mock_clipboard
        self.mixin.on_map_paste()
        self.assertEqual(self.mixin.model.geojson, geojson)

    @mock.patch("bauble.gui")
    def test_on_map_paste_invalid(self, mock_gui):
        mock_clipboard = mock.Mock()
        mock_clipboard.wait_for_text.return_value = "INVALID VALUE"
        mock_gui.get_display_clipboard.return_value = mock_clipboard
        self.mixin.on_map_paste()
        self.assertEqual(self.mixin.model.geojson, self.geojson)
        self.mixin.view.run_message_dialog.assert_called()

    @mock.patch("bauble.gui")
    def test_on_map_paste_kml(self, mock_gui):
        from bauble.test.test_utils_geo import kml_point

        mock_clipboard = mock.Mock()
        mock_clipboard.wait_for_text.return_value = kml_point
        mock_gui.get_display_clipboard.return_value = mock_clipboard
        self.mixin.on_map_paste()
        self.assertEqual(
            self.mixin.model.geojson,
            {
                "type": "Point",
                "coordinates": [152.9742036592858, -27.47773096030531],
            },
        )

    @mock.patch("bauble.gui")
    def test_on_map_paste_web_coords(self, mock_gui):
        mock_clipboard = mock.Mock()
        mock_clipboard.wait_for_text.return_value = (
            "-27.47677001137734, 152.97467501385253"
        )
        mock_gui.get_display_clipboard.return_value = mock_clipboard
        self.mixin.on_map_paste()
        self.assertEqual(
            self.mixin.model.geojson,
            {
                "type": "Point",
                "coordinates": [152.97467501385253, -27.47677001137734],
            },
        )

    @mock.patch("bauble.utils.desktop.open")
    def test_on_map_kml_show_produces_file(self, mock_open):
        template_str = "${value}"
        template = utils.get_temp_path()
        with template.open("w", encoding="utf-8") as f:
            f.write(template_str)
        self.mixin.kml_template = str(template)
        self.mixin.on_map_kml_show()
        with open(mock_open.call_args.args[0], encoding="utf-8") as f:
            self.assertEqual(str(self.mixin.model), f.read())


template_xml = """\
<interface>
  <template class="{gtype}" parent="GtkBox">
    <child>
      <object class="GtkEntry" id="bar_entry">
        <signal name="changed" handler="on_bar_changed" swapped="no" />
      </object>
    </child>
  </template>
</interface>
"""


class GenericPresenterTests(TestCase):
    def test_can_use_as_template_mixin(self):
        gtype = "Foo1"

        @Gtk.Template(string=template_xml.format(gtype=gtype))
        class Foo(GenericPresenter, Gtk.Box):

            __gtype_name__ = gtype

            bar_entry = Gtk.Template.Child()

            def __init__(self, model):
                super().__init__(model, self)
                self.widgets_to_model_map = {self.bar_entry: "bar"}
                self.refresh_all_widgets_from_model()

            # signal handlers defined in the .ui file
            @Gtk.Template.Callback()
            def on_bar_changed(self, entry: Gtk.Entry) -> None:
                super().on_text_entry_changed(entry)

        val1 = "BLAH"
        mock_model = mock.Mock(bar=val1)
        presenter = Foo(mock_model)

        self.assertEqual(presenter.bar_entry.get_text(), val1)

        val2 = "TEST"
        presenter.bar_entry.set_text("TEST")
        self.assertEqual(presenter.bar_entry.get_text(), val2)

    def test_can_use_as_presenter_class(self):
        gtype = "Foo2"

        @Gtk.Template(string=template_xml.format(gtype=gtype))
        class Foo(Gtk.Box):

            __gtype_name__ = gtype

            bar_entry = Gtk.Template.Child()

        class FooPresenter(GenericPresenter):

            def __init__(self, model, view):
                super().__init__(model, view)
                self.widgets_to_model_map = {view.bar_entry: "bar"}
                self.refresh_all_widgets_from_model()

                view.bar_entry.connect("changed", self.on_text_entry_changed)

        val1 = "BLAH"
        mock_model = mock.Mock(bar=val1)
        view = Foo()
        FooPresenter(mock_model, view)

        self.assertEqual(view.bar_entry.get_text(), val1)

        val2 = "TEST"
        view.bar_entry.set_text("TEST")
        self.assertEqual(view.bar_entry.get_text(), val2)

    def test_refresh_all_widgets_from_model(self):
        mock_model = mock.Mock(foo="blah", bar="test", baz="2")

        baz_combobox = Gtk.ComboBoxText()
        baz_combobox.append_text("1")
        baz_combobox.append_text("2")
        baz_combobox.append_text("3")
        mock_view = mock.Mock(
            foo_entry=Gtk.Entry(),
            bar_text_buf=Gtk.TextBuffer(),
            baz_combobox=baz_combobox,
        )

        presenter = GenericPresenter(mock_model, mock_view)

        presenter.widgets_to_model_map = {
            mock_view.foo_entry: "foo",
            mock_view.bar_text_buf: "bar",
            mock_view.baz_combobox: "baz",
        }
        presenter.refresh_all_widgets_from_model()
        self.assertEqual(mock_model.foo, mock_view.foo_entry.get_text())
        self.assertEqual(
            mock_model.bar,
            mock_view.bar_text_buf.get_text(
                *mock_view.bar_text_buf.get_bounds(), False
            ),
        )
        self.assertEqual(
            mock_model.baz, mock_view.baz_combobox.get_active_text()
        )

    def test_problem_desciptor(self):

        class T:  # pylint: disable=too-few-public-methods
            problem = Problem("test")

        t = T()

        t_id = id(t)
        self.assertEqual(t.problem, f"test::T::{t_id}")

    def test_add_problem(self):
        mock_widget = mock.Mock()
        mock_model = mock.Mock()
        mock_view = mock.Mock(widget=mock_widget)

        # not a widget
        presenter = GenericPresenter(mock_model, mock_view)
        presenter.add_problem("TEST", mock_widget)
        self.assertEqual(presenter.problems, {("TEST", mock_widget)})
        mock_widget.get_style_context().add_class.assert_not_called()

        # reset problems
        presenter.problems = set()

        # a widget
        mock_widget = mock.Mock(spec=Gtk.Widget)
        presenter.add_problem("TEST", mock_widget)
        self.assertEqual(presenter.problems, {("TEST", mock_widget)})
        mock_widget.get_style_context().add_class.assert_called_with("problem")

    def test_remove_problem_widget_and_problem_id(self):
        mock_model = mock.Mock()
        mock_view = mock.Mock()

        presenter = GenericPresenter(mock_model, mock_view)
        mock_widget1 = mock.Mock()
        mock_widget2 = mock.Mock()
        mock_widget3 = mock.Mock()
        mock_widget4 = mock.Mock()
        presenter.problems = {
            ("TEST1", mock_widget1),
            ("TEST2", mock_widget1),
            ("TEST3", mock_widget1),
            ("TEST1", mock_widget2),
            ("TEST3", mock_widget3),
            ("TEST1", mock_widget4),
            ("TEST3", mock_widget4),
        }

        presenter.remove_problem("TEST3", mock_widget4)
        self.assertEqual(
            presenter.problems,
            {
                ("TEST1", mock_widget1),
                ("TEST2", mock_widget1),
                ("TEST3", mock_widget1),
                ("TEST1", mock_widget2),
                ("TEST3", mock_widget3),
                ("TEST1", mock_widget4),
            },
        )

    def test_remove_problem_problem_id_only(self):
        mock_model = mock.Mock()
        mock_view = mock.Mock()

        presenter = GenericPresenter(mock_model, mock_view)
        mock_widget1 = mock.Mock()
        mock_widget2 = mock.Mock()
        mock_widget3 = mock.Mock(spec=Gtk.Widget)
        mock_widget4 = mock.Mock()
        presenter.problems = {
            ("TEST1", mock_widget1),
            ("TEST2", mock_widget1),
            ("TEST3", mock_widget1),
            ("TEST1", mock_widget2),
            ("TEST2", mock_widget3),
            ("TEST1", mock_widget4),
            ("TEST3", mock_widget4),
        }

        presenter.remove_problem("TEST2")
        self.assertEqual(
            presenter.problems,
            {
                ("TEST1", mock_widget1),
                ("TEST3", mock_widget1),
                ("TEST1", mock_widget2),
                ("TEST1", mock_widget4),
                ("TEST3", mock_widget4),
            },
        )
        mock_widget1.get_style_context().remove_class.assert_not_called()
        mock_widget2.get_style_context().remove_class.assert_not_called()
        mock_widget3.get_style_context().remove_class.assert_called_with(
            "problem"
        )
        mock_widget4.get_style_context().remove_class.assert_not_called()

    def test_remove_problem_widget_only(self):
        mock_model = mock.Mock()
        mock_view = mock.Mock()

        presenter = GenericPresenter(mock_model, mock_view)
        mock_widget1 = mock.Mock(spec=Gtk.Widget)
        mock_widget2 = mock.Mock(spec=Gtk.Widget)
        mock_widget3 = mock.Mock(spec=Gtk.Widget)
        mock_widget4 = mock.Mock(spec=Gtk.Widget)
        presenter.problems = {
            ("TEST1", mock_widget1),
            ("TEST2", mock_widget1),
            ("TEST3", mock_widget1),
            ("TEST1", mock_widget2),
            ("TEST2", mock_widget3),
            ("TEST1", mock_widget4),
            ("TEST3", mock_widget4),
        }

        presenter.remove_problem(widget=mock_widget4)
        self.assertEqual(
            presenter.problems,
            {
                ("TEST1", mock_widget1),
                ("TEST2", mock_widget1),
                ("TEST3", mock_widget1),
                ("TEST1", mock_widget2),
                ("TEST2", mock_widget3),
            },
        )
        mock_widget1.get_style_context().remove_class.assert_not_called()
        mock_widget2.get_style_context().remove_class.assert_not_called()
        mock_widget3.get_style_context().remove_class.assert_not_called()
        mock_widget4.get_style_context().remove_class.assert_called_with(
            "problem"
        )

    def test_on_text_entry_changed(self):
        mock_model = mock.Mock()
        mock_view = mock.Mock()

        presenter = GenericPresenter(mock_model, mock_view)
        entry = Gtk.Entry()
        presenter.widgets_to_model_map = {entry: "foo"}

        entry.set_text("test")
        presenter.on_text_entry_changed(entry)
        self.assertEqual(mock_model.foo, "test")

    def test_on_non_empty_text_entry_changed(self):
        mock_model = mock.Mock()
        mock_view = mock.Mock()

        presenter = GenericPresenter(mock_model, mock_view)
        entry = Gtk.Entry()
        presenter.widgets_to_model_map = {entry: "foo"}

        # empty
        entry.set_text("")
        presenter.on_non_empty_text_entry_changed(entry)
        self.assertEqual(mock_model.foo, "")
        self.assertEqual(
            presenter.problems,
            {(f"empty::GenericPresenter::{id(presenter)}", entry)},
        )
        self.assertTrue(entry.get_style_context().has_class("problem"))

        entry.set_text("test")
        presenter.on_non_empty_text_entry_changed(entry)
        self.assertEqual(mock_model.foo, "test")
        self.assertEqual(presenter.problems, set())
        self.assertFalse(entry.get_style_context().has_class("problem"))

    def test_on_text_buffer_changed(self):
        mock_model = mock.Mock()
        mock_view = mock.Mock()

        presenter = GenericPresenter(mock_model, mock_view)
        buffer = Gtk.TextBuffer()
        presenter.widgets_to_model_map = {buffer: "foo"}

        buffer.set_text("test")
        presenter.on_text_buffer_changed(buffer)
        self.assertEqual(mock_model.foo, "test")

    def test_on_combobox_changed_comboboxtext(self):
        mock_model = mock.Mock()
        mock_view = mock.Mock()

        presenter = GenericPresenter(mock_model, mock_view)
        combo = Gtk.ComboBoxText()
        combo.append_text("1")
        combo.append_text("2")
        combo.append_text("3")

        presenter.widgets_to_model_map = {combo: "foo"}

        combo.set_active(1)
        presenter.on_combobox_changed(combo)
        self.assertEqual(mock_model.foo, "2")

    def test_on_combobox_changed_comboboxtext_w_entry(self):
        mock_model = mock.Mock()
        mock_view = mock.Mock()

        presenter = GenericPresenter(mock_model, mock_view)
        combo = Gtk.ComboBoxText.new_with_entry()
        combo.append_text("1")
        combo.append_text("2")
        combo.append_text("3")

        presenter.widgets_to_model_map = {combo: "foo"}

        combo.set_active(1)
        presenter.on_combobox_changed(combo)
        self.assertEqual(mock_model.foo, "2")

    def test_on_combobox_changed_combobox_wo_model(self):
        mock_model = mock.Mock()
        mock_view = mock.Mock()

        presenter = GenericPresenter(mock_model, mock_view)
        combo = Gtk.ComboBox()
        cell = Gtk.CellRendererText()
        combo.pack_start(cell, True)
        combo.add_attribute(cell, "text", 1)
        presenter.widgets_to_model_map = {combo: "foo"}

        combo.set_active(1)
        presenter.on_combobox_changed(combo)
        self.assertEqual(mock_model.foo, None)

    def test_on_combobox_changed_combobox(self):
        mock_model = mock.Mock()
        mock_view = mock.Mock()

        presenter = GenericPresenter(mock_model, mock_view)
        combo = Gtk.ComboBox()
        cell = Gtk.CellRendererText()
        combo.pack_start(cell, True)
        combo.add_attribute(cell, "text", 1)
        model = Gtk.ListStore(str, str)
        model.append(["1", "one"])
        model.append(["2", "two"])
        model.append(["3", "three"])
        combo.set_model(model)
        presenter.widgets_to_model_map = {combo: "foo"}

        combo.set_active(1)
        presenter.on_combobox_changed(combo)
        self.assertEqual(mock_model.foo, "2")

    def test_on_combobox_changed_combobox_w_entry(self):
        mock_model = mock.Mock()
        mock_view = mock.Mock()

        presenter = GenericPresenter(mock_model, mock_view)
        model = Gtk.ListStore(str, str)
        model.append(["1", "one"])
        model.append(["2", "two"])
        model.append(["3", "three"])
        combo = Gtk.ComboBox.new_with_model_and_entry(model)
        cell = Gtk.CellRendererText()
        combo.pack_start(cell, True)
        combo.add_attribute(cell, "text", 1)
        combo.connect("format-entry-text", utils.format_combo_entry_text)
        combo.set_model(model)
        presenter.widgets_to_model_map = {combo: "foo"}

        combo.set_active(1)
        presenter.on_combobox_changed(combo)
        self.assertEqual(mock_model.foo, "2")


class GenericPresenterWithDBTests(BaubleTestCase):

    def test_on_unique_text_entry_changed_empty(self):
        # need a real object for this:
        model1 = BaubleMeta(name="test_unique_entry", value="some_value")
        model2 = BaubleMeta(name="test_unique_entry2", value="unique_value")
        self.session.add(model1)
        self.session.add(model2)
        mock_view = mock.Mock()

        presenter = GenericPresenter(model1, mock_view)
        entry = Gtk.Entry()
        presenter.widgets_to_model_map = {entry: "value"}

        # empty
        entry.set_text("")
        presenter.on_unique_text_entry_changed(entry)
        self.assertEqual(model1.value, "")
        self.assertEqual(
            presenter.problems,
            {(f"empty::GenericPresenter::{id(presenter)}", entry)},
        )
        self.assertTrue(entry.get_style_context().has_class("problem"))

        # not empty but unique
        entry.set_text("test")
        presenter.on_non_empty_text_entry_changed(entry)
        self.assertEqual(model1.value, "test")
        self.assertEqual(presenter.problems, set())
        self.assertFalse(entry.get_style_context().has_class("problem"))

    def test_on_unique_text_entry_changed_empty_non_empty_false(self):
        # need a real object for this:
        model1 = BaubleMeta(name="test_unique_entry", value="some_value")
        model2 = BaubleMeta(name="test_unique_entry2", value="unique_value")
        self.session.add(model1)
        self.session.add(model2)
        mock_view = mock.Mock()

        presenter = GenericPresenter(model1, mock_view)
        entry = Gtk.Entry()
        presenter.widgets_to_model_map = {entry: "value"}

        # empty
        entry.set_text("")
        presenter.on_unique_text_entry_changed(entry, non_empty=False)
        self.assertEqual(model1.value, "")
        self.assertEqual(presenter.problems, set())
        self.assertFalse(entry.get_style_context().has_class("problem"))

    def test_on_unique_text_entry_changed_empty_not_unique(self):
        # need a real object for this:
        model1 = BaubleMeta(name="test_unique_entry", value="some_value")
        model2 = BaubleMeta(name="test_unique_entry2", value="unique_value")
        self.session.add(model1)
        self.session.add(model2)
        self.session.commit()
        mock_view = mock.Mock()

        presenter = GenericPresenter(model1, mock_view)
        entry = Gtk.Entry()
        presenter.widgets_to_model_map = {entry: "value"}

        # not unique
        entry.set_text("unique_value")
        presenter.on_unique_text_entry_changed(entry)
        self.assertEqual(model1.value, "unique_value")
        self.assertEqual(
            presenter.problems,
            {(f"not_unique::GenericPresenter::{id(presenter)}", entry)},
        )
        self.assertTrue(entry.get_style_context().has_class("problem"))

    def test_on_unique_text_entry_changed_empty_is_unique(self):
        # need a real object for this:
        model1 = BaubleMeta(name="test_unique_entry", value="some_value")
        model2 = BaubleMeta(name="test_unique_entry2", value="unique_value")
        self.session.add(model1)
        self.session.add(model2)
        mock_view = mock.Mock()

        presenter = GenericPresenter(model1, mock_view)
        entry = Gtk.Entry()
        presenter.widgets_to_model_map = {entry: "value"}

        # not empty and unique
        entry.set_text("test")
        presenter.on_non_empty_text_entry_changed(entry)
        self.assertEqual(model1.value, "test")
        self.assertEqual(presenter.problems, set())
        self.assertFalse(entry.get_style_context().has_class("problem"))
