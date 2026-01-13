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
from unittest import mock

from gi.repository import Gtk

from bauble.plugins.garden.location import Location
from bauble.plugins.plants.family import Family
from bauble.plugins.plants.ui.family_editor import FAMILY_WEB_BUTTON_DEFS_PREFS
from bauble.test import BaubleClassTestCase
from bauble.ui.widgets.links_menu_button import LinksMenuButton


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
