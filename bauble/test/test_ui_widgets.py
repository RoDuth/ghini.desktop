# pylint: disable=no-self-use
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
from unittest import TestCase
from unittest import mock

from gi.repository import Gtk

from bauble.error import BaubleError
from bauble.plugins.garden.location import Location
from bauble.plugins.garden.location import LocationNote
from bauble.plugins.plants.family import Family
from bauble.plugins.plants.geography import Geography
from bauble.plugins.plants.ui.family_editor import FAMILY_WEB_BUTTON_DEFS_PREFS
from bauble.test import BaubleClassTestCase
from bauble.ui.widgets.date_picker import DatePickerBox
from bauble.ui.widgets.links_menu_button import LinksMenuButton
from bauble.ui.widgets.notes_presenter import NotesPresenter


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
        with mock.patch(
            "bauble.ui.widgets.links_menu_button.prefs.prefs"
        ) as mock_prefs:
            mock_prefs.itersection.return_value = ((1, 2), (1, 2))
            links_menu_button.init(fam, FAMILY_WEB_BUTTON_DEFS_PREFS)

        self.assertFalse(links_menu_button.get_visible())
        self.assertIsNone(links_menu_button.get_menu_model())
        box.destroy()

    @mock.patch("bauble.ui.widgets.links_menu_button.desktop.open")
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

    @mock.patch("bauble.ui.widgets.links_menu_button.desktop.open")
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
        loc.notes.append(LocationNote(note="Test"))
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
