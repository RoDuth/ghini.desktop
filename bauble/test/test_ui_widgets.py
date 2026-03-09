# pylint: disable=no-self-use,protected-access
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
Generic widgets tests
"""
from datetime import datetime
from pathlib import Path
from tempfile import mkdtemp
from unittest import TestCase
from unittest import mock

from gi.repository import Gtk
from PIL import Image

from bauble import prefs
from bauble.error import BaubleError
from bauble.plugins.plants.family import Family
from bauble.plugins.plants.geography import Geography
from bauble.plugins.plants.ui.family_editor import FAMILY_WEB_BUTTON_DEFS_PREFS
from bauble.test import BaubleClassTestCase
from bauble.ui.widgets.date import DatePickerBox
from bauble.ui.widgets.notes import NotesPresenter
from bauble.ui.widgets.notes import PictureBox
from bauble.ui.widgets.web import LinksMenuButton


class LinksMenuButtonTests(BaubleClassTestCase):
    def test_init_no_links(self):
        links_menu_button = LinksMenuButton()
        links_menu_button.set_visible(True)
        box = Gtk.Box()
        box.add(links_menu_button)
        loc = Location()
        links_menu_button.init(loc, "")

        self.assertFalse(links_menu_button.get_visible())
        self.assertIsNone(links_menu_button.get_menu_model())
        box.destroy()

    def test_init_w_links(self):
        links_menu_button = LinksMenuButton()
        links_menu_button.set_visible(True)
        box = Gtk.Box()
        box.add(links_menu_button)
        fam = Family()
        links_menu_button.init(fam, FAMILY_WEB_BUTTON_DEFS_PREFS)

        self.assertTrue(links_menu_button.get_visible())
        self.assertIsNotNone(links_menu_button.get_menu_model())
        box.destroy()

    def test_init_w_links_malformed(self):
        links_menu_button = LinksMenuButton()
        links_menu_button.set_visible(True)
        box = Gtk.Box()
        box.add(links_menu_button)
        fam = Family()
        with mock.patch("bauble.ui.widgets.web.prefs.prefs") as mock_prefs:
            mock_prefs.itersection.return_value = ((1, 2), (1, 2))
            links_menu_button.init(fam, FAMILY_WEB_BUTTON_DEFS_PREFS)

        self.assertFalse(links_menu_button.get_visible())
        self.assertIsNone(links_menu_button.get_menu_model())
        box.destroy()

    @mock.patch("bauble.ui.widgets.web.desktop.open")
    def test_on_item_selected_no_url(self, mock_open):
        links_menu_button = LinksMenuButton()
        links_menu_button.set_visible(True)
        box = Gtk.Box()
        box.add(links_menu_button)
        fam = Family()
        links_menu_button.init(fam, FAMILY_WEB_BUTTON_DEFS_PREFS)
        self.assertIsNotNone(links_menu_button.get_menu_model())

        links_menu_button.on_item_selected(None, None, {})

        mock_open.assert_not_called()

        box.destroy()

    @mock.patch("bauble.ui.widgets.web.desktop.open")
    def test_on_item_selected_w_url(self, mock_open):
        links_menu_button = LinksMenuButton()
        links_menu_button.set_visible(True)
        box = Gtk.Box()
        box.add(links_menu_button)
        fam = Family(epithet="Fooaceae")
        links_menu_button.init(fam, FAMILY_WEB_BUTTON_DEFS_PREFS)
        self.assertIsNotNone(links_menu_button.get_menu_model())
        link_btn = {
            "_base_uri": "http://www.google.com/search?q={}",
            "title": "Search Google",
            "tooltip": "",
            "editor_button": True,
        }

        links_menu_button.on_item_selected(None, None, link_btn)

        mock_open.assert_called_with("http://www.google.com/search?q=Fooaceae")

        box.destroy()


class DatePickerBoxTests(TestCase):
    def test_sets_calendar_from_entry(self):
        box = DatePickerBox()
        box.init()

        box.entry.set_text("4th of April 2004")

        year, month, day = box.button.calendar.get_date()

        self.assertEqual(year, 2004)
        self.assertEqual(month + 1, 4)
        self.assertEqual(day, 4)

        # resets to today
        with mock.patch.object(box, "emit") as mock_emit:
            box.entry.set_text("")

        year, month, day = box.button.calendar.get_date()

        today = datetime.today().date()
        self.assertEqual(year, today.year)
        self.assertEqual(month + 1, today.month)
        self.assertEqual(day, today.day)
        mock_emit.assert_called_once_with("changed")

        box.destroy()

    def test_on_selected(self):
        box = DatePickerBox()
        box.init()
        box.button.calendar.select_month(1, 2002)
        box.button.calendar.select_day(2)
        with mock.patch.object(box, "emit") as mock_emit:
            box.button.calendar.emit("day-selected-double-click")

        self.assertEqual(box.entry.get_text(), "02-02-2002")
        mock_emit.assert_called_once_with("changed")

        box.destroy()


class NotesPresenterTests(BaubleClassTestCase):
    def test_init(self):
        # without notes
        presenter = NotesPresenter()

        presenter.init(Location())

        self.assertIs(presenter.note_cls, LocationNote)
        self.assertEqual(len(presenter.expander_box.get_children()), 0)

        presenter.destroy()

        # with note
        loc = Location(code="Loc1")
        note = LocationNote(category="Test", note="Test")
        loc.notes.append(note)
        self.session.add(note)
        self.session.commit()
        presenter = NotesPresenter()

        presenter.init(loc)

        self.assertIs(presenter.note_cls, LocationNote)
        self.assertEqual(len(presenter.expander_box.get_children()), 1)

        presenter.destroy()

        # not notes errors
        presenter = NotesPresenter()
        self.assertRaises(BaubleError, presenter.init, Geography())

        presenter.destroy()

    def test_add_note_button_clicked(self):
        presenter = NotesPresenter()
        loc = Location()
        presenter.init(loc)

        presenter.on_add_button_clicked(None)

        self.assertEqual(len(loc.notes), 1)
        self.assertEqual(len(presenter.expander_box.get_children()), 1)

        presenter.destroy()

    def test_on_changed_emits(self):
        # test it cascades
        loc = Location(code="Loc1")
        # catch some edge cases on the label
        loc.notes.append(LocationNote(user="Me", note="Test " * 6))
        presenter = NotesPresenter()
        presenter.init(loc)
        note_boxes = presenter.expander_box.get_children()

        with mock.patch.object(presenter, "emit") as mock_emit:
            note_boxes[0].emit("changed")
            mock_emit.assert_called_once_with("changed")

        presenter.destroy()

    def test_can_commit(self):
        loc = Location(code="Loc1")
        loc.notes.append(LocationNote(note="Test1"))
        loc.notes.append(LocationNote(note="Test2"))
        presenter = NotesPresenter()
        presenter.init(loc)

        self.assertTrue(presenter.can_commit)

        note_boxes = presenter.expander_box.get_children()
        note_boxes[1].date_entry.set_text("BOOM")

        self.assertFalse(presenter.can_commit)

        presenter.destroy()

    def test_on_remove_button_clicked(self):
        loc = Location(code="Loc1")
        loc.notes.append(LocationNote(note="Test1"))
        loc.notes.append(LocationNote(note="Test2"))
        presenter = NotesPresenter()
        presenter.init(loc)
        note_boxes = presenter.expander_box.get_children()
        note_boxes[0].on_remove_button_clicked(None)

        self.assertEqual(len(loc.notes), 1)
        self.assertEqual(len(presenter.expander_box.get_children()), 1)

        presenter.destroy()


TEMP_ROOT = mkdtemp()


class PicturesPresenterTests(BaubleClassTestCase):
    def setUp(self):

        prefs.prefs[prefs.root_directory_pref] = TEMP_ROOT

        pics = Path(TEMP_ROOT, "pictures")
        if not pics.is_dir():
            pics.mkdir()

        thumbs = Path(TEMP_ROOT, "pictures", "thumbs")
        if not thumbs.is_dir():
            thumbs.mkdir()

        test1_pic = pics / "Test1.jpg"
        if not test1_pic.is_file():
            img = Image.new("RGB", (800, 800), "blue")
            img.save(test1_pic)

        test1_thumb = thumbs / "Test1.jpg"
        if not test1_thumb.is_file():
            img = Image.new("RGB", (400, 400), "blue")
            img.save(test1_thumb)

        empty_pic = pics / "Bad.jpg"
        if not empty_pic.is_file():
            empty_pic.touch()

        empty_thumb = pics / "Bad.jpg"
        if not empty_thumb.is_file():
            empty_thumb.touch()

    def test_init(self):
        # without pictures
        presenter = NotesPresenter()

        presenter.init(Location(), "_pictures", PictureBox)

        self.assertIs(presenter.note_cls, LocationPicture)
        self.assertEqual(len(presenter.expander_box.get_children()), 0)

        presenter.destroy()

        # with pictures
        loc = Location(code="Loc2")
        pic = LocationPicture(category="Test", picture="Test1.jpg")
        loc._pictures.append(pic)
        presenter = NotesPresenter()

        presenter.init(loc, "_pictures", PictureBox)

        self.assertIs(presenter.note_cls, LocationPicture)
        self.assertEqual(len(presenter.expander_box.get_children()), 1)

        presenter.destroy()

        # not pictures errors
        presenter = NotesPresenter()
        self.assertRaises(BaubleError, presenter.init, Geography())

        presenter.destroy()

    def test_add_button_clicked(self):
        presenter = NotesPresenter()
        loc = Location()
        presenter.init(loc, "_pictures", PictureBox)

        presenter.on_add_button_clicked(None)

        pic_boxes = presenter.expander_box.get_children()

        self.assertEqual(len(loc._pictures), 1)
        self.assertEqual(len(presenter.expander_box.get_children()), 1)
        self.assertEqual(
            pic_boxes[0].picture_box.get_children()[0].get_text(),
            "Choose a file or enter a URL…",
        )

        presenter.destroy()

    def test_on_changed_emits(self):
        # test it cascades
        loc = Location(code="Loc1")
        # catch some edge cases on the label
        loc._pictures.append(LocationPicture(user="Me", picture="Test1.jpg"))
        presenter = NotesPresenter()
        presenter.init(loc, "_pictures", PictureBox)
        pic_boxes = presenter.expander_box.get_children()

        with mock.patch.object(presenter, "emit") as mock_emit:
            pic_boxes[0].emit("changed")
            mock_emit.assert_called_once_with("changed")

        presenter.destroy()

    def test_can_commit(self):
        loc = Location(code="Loc1")
        loc._pictures.append(LocationPicture(picture="Test1.jpg"))
        loc._pictures.append(LocationPicture(picture="Test2.jpg"))
        presenter = NotesPresenter()
        presenter.init(loc, "_pictures", PictureBox)

        self.assertTrue(presenter.can_commit)

        pic_boxes = presenter.expander_box.get_children()
        pic_boxes[1].date_entry.set_text("BOOM")

        self.assertFalse(presenter.can_commit)

        presenter.destroy()

    def test_on_remove_button_clicked_not_existing(self):

        loc = Location(code="Loc1")
        loc._pictures.append(LocationPicture(picture="Test1.jpg"))
        loc._pictures.append(LocationPicture(picture="Test2.jpg"))
        presenter = NotesPresenter()
        presenter.init(loc, "_pictures", PictureBox)
        pic_boxes = presenter.expander_box.get_children()

        self.assertEqual(pic_boxes[0].file_entry.get_text(), "Test2.jpg")
        self.assertEqual(pic_boxes[1].file_entry.get_text(), "Test1.jpg")

        # Test1.jpg does not exist, no dialog to confirm
        pic_boxes[0].on_remove_button_clicked(None)

        self.assertEqual(len(loc._pictures), 1)
        self.assertEqual(len(presenter.expander_box.get_children()), 1)

        presenter.destroy()

    @mock.patch("bauble.ui.dialogs.yes_no_dialog")
    def test_on_remove_button_clicked_existing_accept(self, mock_dialog):

        pics = Path(TEMP_ROOT, "pictures")
        thumbs = pics / "thumbs"
        loc = Location(code="Loc1")
        loc._pictures.append(LocationPicture(picture="Test1.jpg"))
        loc._pictures.append(LocationPicture(picture="Test2.jpg"))
        presenter = NotesPresenter()
        presenter.init(loc, "_pictures", PictureBox)
        pic_boxes = presenter.expander_box.get_children()

        self.assertEqual(pic_boxes[0].file_entry.get_text(), "Test2.jpg")
        self.assertEqual(pic_boxes[1].file_entry.get_text(), "Test1.jpg")

        # Accept
        mock_dialog.return_value = True
        pic_boxes[1].on_remove_button_clicked(None)

        mock_dialog.assert_called_once_with(
            "File Test1.jpg exist, would you like to delete?",
            parent=None,
            yes_delay=0.5,
        )

        self.assertEqual(len(loc._pictures), 1)
        self.assertEqual(len(presenter.expander_box.get_children()), 1)
        # files deleted
        self.assertEqual(len(list(pics.glob("Test1.jpg"))), 0)
        self.assertEqual(len(list(thumbs.glob("Test1.jpg"))), 0)

        presenter.destroy()

    @mock.patch("bauble.ui.dialogs.yes_no_dialog")
    def test_on_remove_button_clicked_existing_reject(self, mock_dialog):

        pics = Path(TEMP_ROOT, "pictures")
        thumbs = pics / "thumbs"
        loc = Location(code="Loc1")
        loc._pictures.append(LocationPicture(picture="Test1.jpg"))
        loc._pictures.append(LocationPicture(picture="Test2.jpg"))
        presenter = NotesPresenter()
        presenter.init(loc, "_pictures", PictureBox)
        pic_boxes = presenter.expander_box.get_children()

        self.assertEqual(pic_boxes[0].file_entry.get_text(), "Test2.jpg")
        self.assertEqual(pic_boxes[1].file_entry.get_text(), "Test1.jpg")

        # reject
        mock_dialog.return_value = False
        pic_boxes[1].on_remove_button_clicked(None)

        mock_dialog.assert_called_once_with(
            "File Test1.jpg exist, would you like to delete?",
            parent=None,
            yes_delay=0.5,
        )

        self.assertEqual(len(loc._pictures), 1)
        self.assertEqual(len(presenter.expander_box.get_children()), 1)
        # files left in place
        self.assertEqual(len(list(pics.glob("Test1.jpg"))), 1)
        self.assertEqual(len(list(thumbs.glob("Test1.jpg"))), 1)

        presenter.destroy()

    @mock.patch("bauble.ui.dialogs.yes_no_dialog")
    def test_on_remove_button_clicked_existing_other(self, mock_dialog):

        loc = Location(code="Loc1")
        loc._pictures.append(LocationPicture(picture="Test1.jpg"))
        loc._pictures.append(LocationPicture(picture="Test2.jpg"))
        presenter = NotesPresenter()
        presenter.init(loc, "_pictures", PictureBox)
        pic_boxes = presenter.expander_box.get_children()

        self.assertEqual(pic_boxes[0].file_entry.get_text(), "Test2.jpg")
        self.assertEqual(pic_boxes[1].file_entry.get_text(), "Test1.jpg")

        # exists elewhere
        loc2 = Location(code="Loc2")
        loc2._pictures.append(LocationPicture(picture="Test1.jpg"))
        self.session.add(loc2)
        self.session.commit()

        # Accept
        mock_dialog.return_value = True
        pic_boxes[1].on_remove_button_clicked(None)

        mock_dialog.assert_called_once_with(
            "File Test1.jpg exist, would you like to delete? 1 other "
            "picture(s) of type location_picture exist using the same "
            "file.",
            parent=None,
            yes_delay=0.5,
        )

        self.assertEqual(len(loc._pictures), 1)
        self.assertEqual(len(presenter.expander_box.get_children()), 1)

        self.session.delete(loc2)
        self.session.commit()
        presenter.destroy()

    @mock.patch("bauble.ui.dialogs.yes_no_dialog")
    @mock.patch("bauble.ui.dialogs.message_details_dialog")
    def test_on_remove_button_clicked_exception(
        self,
        mock_details_dialog,
        mock_yn_dialog,
    ):

        loc = Location(code="Loc1")
        loc._pictures.append(LocationPicture(picture="Test1.jpg"))
        presenter = NotesPresenter()
        presenter.init(loc, "_pictures", PictureBox)
        pic_boxes = presenter.expander_box.get_children()

        self.assertEqual(pic_boxes[0].file_entry.get_text(), "Test1.jpg")

        # Accept
        mock_yn_dialog.return_value = True
        with mock.patch("bauble.ui.widgets.notes.Path.unlink") as mock_unlink:
            mock_unlink.side_effect = Exception("BOOM")
            pic_boxes[0].on_remove_button_clicked(None)
            mock_details_dialog.assert_called_once_with(
                "Error removing file...  File in use?",
                details="BOOM",
                parent=None,
            )

        self.assertEqual(len(loc._pictures), 1)
        self.assertEqual(len(presenter.expander_box.get_children()), 1)

        presenter.destroy()

    @mock.patch("bauble.ui.widgets.notes.ImageLoader")
    def test_uses_imageloader_for_url(self, mock_loader):

        loc = Location(code="Loc1")
        loc._pictures.append(LocationPicture(picture="http://test.org"))
        presenter = NotesPresenter()
        presenter.init(loc, "_pictures", PictureBox)
        pic_boxes = presenter.expander_box.get_children()

        self.assertEqual(
            pic_boxes[0].file_entry.get_text(),
            "http://test.org",
        )
        mock_loader.assert_called_once()
        mock_loader().start.assert_called_once()

        presenter.destroy()

    def test_sets_label_non_existing(self):

        loc = Location(code="Loc1")
        loc._pictures.append(LocationPicture(picture="non_exsisting.jpg"))
        presenter = NotesPresenter()
        presenter.init(loc, "_pictures", PictureBox)
        pic_boxes = presenter.expander_box.get_children()

        self.assertEqual(
            pic_boxes[0].file_entry.get_text(),
            "non_exsisting.jpg",
        )
        self.assertEqual(
            pic_boxes[0].picture_box.get_children()[0].get_text(),
            "picture file non_exsisting.jpg not found.",
        )

        presenter.destroy()

    def test_sets_label_error_loading(self):

        loc = Location(code="Loc1")
        loc._pictures.append(LocationPicture(picture="Bad.jpg"))
        presenter = NotesPresenter()
        presenter.init(loc, "_pictures", PictureBox)
        pic_boxes = presenter.expander_box.get_children()

        self.assertEqual(pic_boxes[0].file_entry.get_text(), "Bad.jpg")
        self.assertEqual(
            pic_boxes[0].picture_box.get_children()[0].get_text(),
            "Error loading Bad.jpg.",
        )

        presenter.destroy()

    @mock.patch("bauble.ui.widgets.notes.Path.is_file")
    def test_sets_label_exception(self, mock_is_file):
        mock_is_file.side_effect = Exception("BOOM")

        loc = Location(code="Loc1")
        loc._pictures.append(LocationPicture(picture="Bad.jpg"))
        presenter = NotesPresenter()
        presenter.init(loc, "_pictures", PictureBox)
        pic_boxes = presenter.expander_box.get_children()

        self.assertEqual(pic_boxes[0].file_entry.get_text(), "Bad.jpg")
        self.assertEqual(
            pic_boxes[0].picture_box.get_children()[0].get_text(),
            "Exception: BOOM",
        )

        presenter.destroy()

    @mock.patch("gi.repository.Gtk.FileChooserNative.new")
    def test_on_file_btnbrowse_clicked(self, mock_file_chooser):
        temp = Path(mkdtemp())
        test3_pic = temp / "Test3.jpg"
        img = Image.new("RGB", (800, 800), "blue")
        img.save(test3_pic)
        test4_pic = temp / "Test4.jpg"
        img = Image.new("RGB", (800, 800), "red")
        img.save(test4_pic)

        mock_file_chooser().get_filenames.return_value = [
            str(test3_pic),
            str(test4_pic),
        ]

        loc = Location(code="Loc1")
        presenter = NotesPresenter()
        presenter.init(loc, "_pictures", PictureBox)
        presenter.on_add_button_clicked(None)
        pic_boxes = presenter.expander_box.get_children()
        pic_boxes[0].on_file_btnbrowse_clicked(None)
        pic_boxes = presenter.expander_box.get_children()

        self.assertEqual(len(loc._pictures), 2)
        self.assertEqual(len(presenter.expander_box.get_children()), 2)
        self.assertEqual(pic_boxes[0].file_entry.get_text(), "Test4.jpg")
        self.assertEqual(pic_boxes[1].file_entry.get_text(), "Test3.jpg")

        # exception
        with mock.patch.object(pic_boxes[0], "add_from_files") as mock_add:
            mock_add.side_effect = Exception("BOOM")
            with mock.patch("bauble.ui.dialogs.message_details_dialog") as md:
                pic_boxes[0].on_file_btnbrowse_clicked(None)
                md.assert_called_once_with(
                    "Exception trying to add the selected files.",
                    "BOOM",
                    Gtk.MessageType.WARNING,
                    parent=None,
                )

        presenter.destroy()

    @mock.patch("bauble.ui.dialogs.yes_no_dialog")
    def test_add_from_files(self, mock_dialog):
        pics = Path(TEMP_ROOT, "pictures")
        self.assertEqual(len(list(pics.glob("Test1*.jpg"))), 1)
        thumbs = Path(TEMP_ROOT, "pictures", "thumbs")
        temp = Path(mkdtemp())
        # existing
        test1_pic = temp / "Test1.jpg"
        img = Image.new("RGB", (800, 800), "blue")
        img.save(test1_pic)
        # new
        test5_pic = temp / "Test5.jpg"
        img = Image.new("RGB", (800, 800), "red")
        img.save(test5_pic)
        loc = Location(code="Loc1")
        presenter = NotesPresenter()
        presenter.init(loc, "_pictures", PictureBox)
        presenter.on_add_button_clicked(None)
        pic_boxes = presenter.expander_box.get_children()

        self.assertEqual(len(pic_boxes), 1)

        # don't rename
        mock_dialog.return_value = False
        pic_boxes[0].add_from_files([str(test1_pic), str(test5_pic)])
        pic_boxes = presenter.expander_box.get_children()

        self.assertEqual(len(pic_boxes), 1)
        self.assertEqual(len(list(pics.glob("Test5.jpg"))), 1)
        self.assertEqual(len(list(pics.glob("Test5_*.jpg"))), 0)
        self.assertEqual(len(list(pics.glob("Test1.jpg"))), 1)
        self.assertEqual(len(list(pics.glob("Test1_*.jpg"))), 0)
        self.assertEqual(len(list(thumbs.glob("Test5.jpg"))), 1)
        self.assertEqual(len(list(thumbs.glob("Test5_*.jpg"))), 0)
        self.assertEqual(len(list(thumbs.glob("Test1.jpg"))), 1)
        self.assertEqual(len(list(thumbs.glob("Test1_*.jpg"))), 0)

        # do rename
        mock_dialog.return_value = True
        presenter.on_add_button_clicked(None)
        pic_boxes = presenter.expander_box.get_children()
        pic_boxes[1].add_from_files([str(test1_pic), str(test5_pic)])
        pic_boxes = presenter.expander_box.get_children()

        self.assertEqual(len(pic_boxes), 3)
        self.assertEqual(len(list(pics.glob("Test5.jpg"))), 1)
        self.assertEqual(len(list(pics.glob("Test5_*.jpg"))), 1)
        self.assertEqual(len(list(pics.glob("Test1.jpg"))), 1)
        self.assertEqual(len(list(pics.glob("Test1_*.jpg"))), 1)
        self.assertEqual(len(list(thumbs.glob("Test5.jpg"))), 1)
        self.assertEqual(len(list(thumbs.glob("Test5_*.jpg"))), 1)
        self.assertEqual(len(list(thumbs.glob("Test1.jpg"))), 1)
        self.assertEqual(len(list(thumbs.glob("Test1_*.jpg"))), 1)

        presenter.destroy()

    def test_get_dialog_window(self):
        loc = Location(code="Loc1")
        presenter = NotesPresenter()
        presenter.init(loc, "_pictures", PictureBox)
        presenter.on_add_button_clicked(None)
        pic_boxes = presenter.expander_box.get_children()
        win = Gtk.Window()
        win.add(presenter)

        self.assertIs(pic_boxes[0].get_dialog_window(), win)

        presenter.destroy()

    def test_set_content_no_thumbnail(self):
        pics = Path(TEMP_ROOT, "pictures")
        no_thumb = pics / "no_thumb.jpg"
        img = Image.new("RGB", (800, 800), "blue")
        img.save(no_thumb)
        loc = Location(code="Loc1")
        loc._pictures.append(LocationPicture(picture="no_thumb.jpg"))
        presenter = NotesPresenter()
        presenter.init(loc, "_pictures", PictureBox)
        pic_boxes = presenter.expander_box.get_children()

        self.assertEqual(len(pic_boxes), 1)
        self.assertIsInstance(
            pic_boxes[0].picture_box.get_children()[0],
            Gtk.Image,
        )

        presenter.destroy()

    def test_update_label_truncates_long(self):
        pic_box = PictureBox(
            LocationPicture(
                picture="a very only string requiring truncation.jpg"
            )
        )
        self.assertEqual(
            pic_box.expander.get_label(),
            " : a very only string re …",
        )
        pic_box.destroy()


# avoid circular imports
from bauble.plugins.garden.location import Location
from bauble.plugins.garden.location import LocationNote
from bauble.plugins.garden.location import LocationPicture
