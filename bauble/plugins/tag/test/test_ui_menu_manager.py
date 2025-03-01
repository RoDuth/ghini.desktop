# pylint: disable=no-self-use,protected-access,too-many-public-methods
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
Tag menu manager tests
"""

from unittest import TestCase
from unittest import mock

from gi.repository import Gio
from gi.repository import GLib
from gi.repository import Gtk

import bauble
from bauble.plugins.plants import Family
from bauble.test import BaubleTestCase
from bauble.ui import GUI
from bauble.view import SearchView

from .. import Tag
from ..model import tag_objects
from ..model import untag_objects
from ..ui.menu_manager import _on_add_tag_activated
from ..ui.menu_manager import _tags_menu_manager
from ..ui.menu_manager import _TagsMenuManager


class TagMenuTests(BaubleTestCase):
    def setUp(self):
        super().setUp()
        bauble.gui = GUI()

    def tearDown(self):
        super().tearDown()
        bauble.gui = None

    def test_build_menu_no_tags(self):
        menu_model = _tags_menu_manager.build_menu()
        self.assertTrue(isinstance(menu_model, Gio.Menu))
        m = Gtk.Menu.new_from_model(menu_model)
        self.assertEqual(len(m.get_children()), 1)
        self.assertEqual(menu_model.get_n_items(), 1)
        self.assertEqual(m.get_children()[0].get_label(), "Tag Selection")

    def test_build_menu_one_tag(self):
        tagname = "some-tag"
        tag = Tag(tag=tagname, description="description")
        self.session.add(tag)
        self.session.commit()
        menu_model = _tags_menu_manager.build_menu()
        self.assertTrue(isinstance(menu_model, Gio.Menu))
        m = Gtk.Menu.new_from_model(menu_model)
        self.assertEqual(menu_model.get_n_items(), 3)
        self.assertEqual(m.get_children()[2].get_label(), tagname)

    @mock.patch("bauble.gui", new=mock.Mock())
    def test_build_menu_more_tags(self):
        tagname = "%s-some-tag"
        t1 = Tag(tag=tagname % 1, description="description")
        t2 = Tag(tag=tagname % 3, description="description")
        t3 = Tag(tag=tagname % 2, description="description")
        t4 = Tag(tag=tagname % 0, description="description")
        t5 = Tag(tag=tagname % 4, description="description")
        self.session.add_all([t1, t2, t3, t4, t5])
        self.session.commit()
        menu_model = _tags_menu_manager.build_menu()
        self.assertTrue(isinstance(menu_model, Gio.Menu))
        m = Gtk.Menu.new_from_model(menu_model)
        self.assertEqual(menu_model.get_n_items(), 3)
        self.assertEqual(len(m.get_children()), 10)
        for i in range(5):
            self.assertEqual(m.get_children()[i + 2].get_label(), tagname % i)

    @mock.patch("bauble.gui")
    def test_reset_adds_and_removes_menu(self, mock_gui):
        tags_mm = _TagsMenuManager()
        self.assertIsNone(tags_mm.menu_pos)

        # first run
        mock_gui.add_menu.return_value = 5
        tags_mm.reset()
        self.assertEqual(tags_mm.menu_pos, 5)
        mock_gui.remove_menu.assert_not_called()

        # subsequent tuns
        mock_gui.add_menu.return_value = 6
        tags_mm.reset()
        self.assertEqual(tags_mm.menu_pos, 6)
        mock_gui.remove_menu.assert_called()

    def test_reset_active_tag_name_resets_if_none_or_invalid(self):
        t1 = Tag(tag="tag-1")
        t2 = Tag(tag="tag-2")
        self.session.add_all([t1, t2])
        self.session.commit()
        tags_mm = _TagsMenuManager()
        self.assertIsNone(tags_mm.active_tag_name)
        tags_mm.reset_active_tag_name()
        self.assertEqual(tags_mm.active_tag_name, "tag-2")
        self.session.delete(t2)
        self.session.commit()
        tags_mm.reset_active_tag_name()
        self.assertEqual(tags_mm.active_tag_name, "tag-1")

    @mock.patch("bauble.gui")
    def test_on_tag_change_state_searches_sets_active(self, mock_gui):
        mock_sv = mock.Mock(spec=SearchView)
        mock_gui.get_view.return_value = mock_sv
        tags_mm = _TagsMenuManager()
        tags_mm.refresh = mock.Mock()
        variant = GLib.Variant.new_string("test1")
        action = Gio.SimpleAction.new_stateful(
            tags_mm.ACTIVATED_ACTION_NAME, variant.get_type(), variant
        )
        mock_sv.results_view.expand_to_path.return_value = False

        tags_mm.on_tag_change_state(action, variant)

        mock_gui.send_command.assert_called_with("tag='test1'")
        tags_mm.refresh.assert_called()
        self.assertEqual(tags_mm.active_tag_name, "test1")

    @mock.patch("bauble.gui")
    def test_on_context_menu_apply_activated_bails(self, mock_gui):
        # no SearchView
        mock_sv = mock.Mock()
        mock_gui.get_view.return_value = mock_sv
        mock_sv.get_selected_values.return_value = []
        tags_mm = _TagsMenuManager()
        variant = GLib.Variant.new_string("test2")

        tags_mm.on_context_menu_apply_activated(None, variant)

        mock_sv.get_selected_values.assert_not_called()
        mock_sv.update_bottom_notebook.assert_not_called()

    @mock.patch("bauble.gui")
    def test_on_context_menu_apply_activated_w_values_tags(self, mock_gui):
        # with SearchView with Values
        mock_sv = mock.Mock(spec=SearchView)
        mock_gui.get_view.return_value = mock_sv
        fam = Family(epithet="Myrtaceae")
        tag = Tag(tag="bar")
        self.session.add_all([fam, tag])
        self.session.commit()
        self.assertFalse(tag.is_tagging(fam))
        mock_sv.get_selected_values.return_value = [fam]
        tags_mm = _TagsMenuManager()
        variant = GLib.Variant.new_string("bar")

        tags_mm.on_context_menu_apply_activated(None, variant)

        mock_sv.update_bottom_notebook.assert_called_with([fam])
        self.assertTrue(tag.is_tagging(fam))

    @mock.patch("bauble.gui")
    def test_on_context_menu_remove_activated_bails(self, mock_gui):
        # no SearchView
        mock_sv = mock.Mock()
        mock_gui.get_view.return_value = mock_sv
        mock_sv.get_selected_values.return_value = []
        tags_mm = _TagsMenuManager()
        variant = GLib.Variant.new_string("test2")

        tags_mm.on_context_menu_remove_activated(None, variant)

        mock_sv.get_selected_values.assert_not_called()
        mock_sv.update_bottom_notebook.assert_not_called()

    @mock.patch("bauble.gui")
    def test_on_context_menu_remove_activated_w_values_untags(self, mock_gui):
        # with SearchView with Values
        mock_sv = mock.Mock(spec=SearchView)
        mock_gui.get_view.return_value = mock_sv
        fam = Family(epithet="Myrtaceae")
        tag = Tag(tag="bar")
        self.session.add_all([fam, tag])
        self.session.commit()
        tag_objects("bar", [fam])
        self.assertTrue(tag.is_tagging(fam))
        mock_sv.get_selected_values.return_value = [fam]
        tags_mm = _TagsMenuManager()
        variant = GLib.Variant.new_string("bar")

        tags_mm.on_context_menu_remove_activated(None, variant)

        mock_sv.update_bottom_notebook.assert_called_with([fam])
        self.assertFalse(tag.is_tagging(fam))

    def test_context_menu_callback_bails_nothing_selected(self):
        tags_mm = _TagsMenuManager()

        with self.assertLogs(level="WARNING") as logs:
            self.assertIsNone(tags_mm.context_menu_callback([]))

        string = "nothing selected bailing."
        self.assertTrue(any(string in i for i in logs.output))

    def test_context_menu_callback_bails_no_session(self):
        tags_mm = _TagsMenuManager()

        with self.assertLogs(level="WARNING") as logs:
            self.assertIsNone(
                tags_mm.context_menu_callback([Family(epithet="Myrtaceae")])
            )

        string = "no object session bailing."
        self.assertTrue(any(string in i for i in logs.output))

    def test_context_menu_callback_bails_no_tags(self):
        tags_mm = _TagsMenuManager()
        fam = Family(epithet="Myrtaceae")
        self.session.add(fam)

        with self.assertLogs(level="DEBUG") as logs:
            section = tags_mm.context_menu_callback([fam])

        self.assertIsNotNone(section)
        self.assertEqual(section.get_n_items(), 1)
        string = "no tags, not creating submenus."
        self.assertTrue(any(string in i for i in logs.output))

        menu = Gtk.Menu.new_from_model(section)
        self.assertEqual(menu.get_children()[0].get_label(), "Tag Selection")

    def test_context_menu_callback_builds_menu(self):
        tags_mm = _TagsMenuManager()
        fam = Family(epithet="Myrtaceae")
        tag1 = Tag(tag="Foo")
        tag2 = Tag(tag="Bar")
        self.session.add_all([fam, tag1, tag2])
        self.session.commit()
        tag1.tag_objects([fam])
        self.session.commit()

        section = tags_mm.context_menu_callback([fam])

        self.assertIsNotNone(section)
        self.assertEqual(section.get_n_items(), 3)

        menu = Gtk.Menu.new_from_model(section)
        self.assertEqual(menu.get_children()[0].get_label(), "Tag Selection")
        self.assertEqual(menu.get_children()[1].get_label(), "Apply Tag")
        self.assertEqual(menu.get_children()[2].get_label(), "Remove Tag")

    def test_apply_remove_tags(self):
        fam = Family(epithet="Myrtaceae")
        fam2 = Family(epithet="Fabaceae")
        fam3 = Family(epithet="Malvaceae")
        tag1 = Tag(tag="Foo")
        tag2 = Tag(tag="Bar")
        tag3 = Tag(tag="Baz")
        self.session.add_all([fam, fam2, fam3, tag1, tag2, tag3])
        self.session.commit()
        tag1.tag_objects([fam])
        self.session.commit()

        query = self.session.query(Tag)
        apply, remove = _TagsMenuManager._apply_remove_tags([fam, fam2], query)
        self.assertCountEqual(remove, [tag1])
        self.assertCountEqual(apply, [tag1, tag2, tag3])

        tag1.tag_objects([fam2])
        self.session.commit()
        apply, remove = _TagsMenuManager._apply_remove_tags([fam, fam2], query)
        self.assertCountEqual(remove, [tag1])
        self.assertCountEqual(apply, [tag2, tag3])

    @mock.patch("bauble.gui")
    def test_toggle_tag_not_search_view_bails(self, mock_gui):
        tags_mm = _TagsMenuManager()
        mock_sv = mock.Mock()
        mock_gui.get_view.return_value = mock_sv

        tags_mm.toggle_tag(None)

        mock_sv.update_bottom_notebook.assert_not_called()

    @mock.patch("bauble.gui")
    def test_toggle_tag_wo_selected_bails(self, mock_gui):
        tags_mm = _TagsMenuManager()
        mock_sv = mock.Mock(spec=SearchView)
        mock_sv.get_selected_values.return_value = None
        mock_gui.get_view.return_value = mock_sv

        tags_mm.toggle_tag(None)

        mock_sv.update_bottom_notebook.assert_not_called()

    @mock.patch("bauble.gui")
    def test_toggle_tag_no_active_tag_messages(self, mock_gui):
        tags_mm = _TagsMenuManager()
        mock_sv = mock.Mock(spec=SearchView)
        mock_sv.get_selected_values.return_value = [None, None]
        mock_gui.get_view.return_value = mock_sv
        self.assertIsNone(tags_mm.active_tag_name)
        mock_dialog = mock.Mock()

        tags_mm.toggle_tag(None, message_dialog=mock_dialog)

        mock_dialog.assert_called_with("Please make sure a tag is active.")

    def test_toggle_tag_applies(self):
        # setup some test data
        tags_mm = _TagsMenuManager()
        tags_mm.active_tag_name = "test"
        with mock.patch("bauble.gui") as mock_gui:
            mock_sv = mock.Mock(spec=SearchView)
            mock_sv.get_selected_values.return_value = [None, None]
            mock_gui.get_view.return_value = mock_sv
            mock_applying = mock.Mock()

            tags_mm.toggle_tag(mock_applying)

            mock_applying.assert_called_with("test", [None, None])
            mock_sv.update_bottom_notebook.assert_called()

    def test_on_apply_active_tag_activated(self):
        tags_mm = _TagsMenuManager()
        tags_mm.toggle_tag = mock.Mock()
        tags_mm.on_apply_active_tag_activated(None, None)
        tags_mm.toggle_tag.assert_called_with(tag_objects)

    def test_on_remove_active_tag_activated(self):
        tags_mm = _TagsMenuManager()
        tags_mm.toggle_tag = mock.Mock()
        tags_mm.on_remove_active_tag_activated(None, None)
        tags_mm.toggle_tag.assert_called_with(untag_objects)


class TagCallbackTest(TestCase):
    @mock.patch("bauble.gui")
    def test_on_add_tag_activated_w_selected_starts_editor(self, mock_gui):
        tagname = "some-tag"
        tag = Tag(tag=tagname, description="description")
        mock_sv = mock.Mock(spec=SearchView)
        mock_selected = [tag]
        mock_sv.get_selected_values.return_value = mock_selected
        mock_gui.get_view.return_value = mock_sv
        mock_dialog = mock.Mock()

        _on_add_tag_activated(None, None, dialog_cls=mock_dialog)

        mock_dialog.assert_called_with([tag])
        mock_dialog().start.assert_called()

    @mock.patch("bauble.gui")
    def test_on_add_tag_activated_wo_selected_returns(self, mock_gui):

        mock_sv = mock.Mock(spec=SearchView)
        mock_selected = []
        mock_sv.get_selected_values.return_value = mock_selected
        mock_gui.get_view.return_value = mock_sv
        mock_dialog = mock.Mock()

        _on_add_tag_activated(None, None, dialog_cls=mock_dialog)

        mock_sv.get_selected_values.assert_called()
        mock_sv.update_bottom_notebook.assert_not_called()
        mock_dialog.assert_not_called()

    @mock.patch("bauble.gui")
    def test_on_add_tag_activated_not_searchview_bails_early(self, mock_gui):
        mock_sv = mock.Mock()
        mock_gui.get_view.return_value = mock_sv
        mock_dialog = mock.Mock()

        _on_add_tag_activated(None, None, dialog_cls=mock_dialog)

        mock_sv.get_selected_values.assert_not_called()
        mock_dialog.assert_not_called()
