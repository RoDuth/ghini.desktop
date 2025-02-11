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
Tag tests
"""

import os
from time import sleep
from unittest import mock

from gi.repository import Gio
from gi.repository import GLib
from gi.repository import Gtk

import bauble
import bauble.plugins.tag as tag_plugin
from bauble import utils
from bauble.editor import GenericEditorView
from bauble.test import BaubleTestCase
from bauble.test import check_dupids
from bauble.ui import GUI
from bauble.view import SearchView

from ..garden import Accession
from ..plants import Family
from . import Tag
from . import TagEditorPresenter
from . import TagInfoBox
from . import TagsMenuManager
from . import remove_callback
from . import tag_objects
from . import untag_objects
from .model import TaggedObj

tag_test_data = (
    {"id": 1, "tag": "test1", "description": "empty test tag"},
    {"id": 2, "tag": "test2", "description": "not empty test tag"},
)

tag_object_test_data = (
    {
        "id": 1,
        "obj_id": 1,
        "obj_class": f"{Tag.__module__}.{Tag.__name__}",
        "tag_id": 2,
    },
    {
        "id": 2,
        "obj_id": 5,
        "obj_class": f"{Accession.__module__}.{Accession.__name__}",
        "tag_id": 2,
    },
)

test_data_table_control = (
    (Tag, tag_test_data),
    (TaggedObj, tag_object_test_data),
)


def setUp_data():
    """Load test data.

    if this method is called again before tearDown_test_data is called you
    will get an error about the test data rows already existing in the database
    """

    for mapper, data in test_data_table_control:
        table = mapper.__table__
        # insert row by row instead of doing an insert many since each
        # row will have different columns
        for row in data:
            table.insert().execute(row).close()
        for col in table.c:
            utils.reset_sequence(col)


setUp_data.order = 2  # type: ignore [attr-defined]


def test_duplicate_ids():
    """
    Test for duplicate ids for all .glade files in the tag plugin.
    """
    import glob

    import bauble.plugins.tag as mod

    head, tail = os.path.split(mod.__file__)
    files = glob.glob(os.path.join(head, "*.glade"))
    for f in files:
        assert not check_dupids(f)


class TagMenuTests(BaubleTestCase):
    def setUp(self):
        super().setUp()
        bauble.gui = GUI()

    def tearDown(self):
        super().tearDown()
        bauble.gui = None

    def test_build_menu_no_tags(self):
        menu_model = tag_plugin.tags_menu_manager.build_menu()
        self.assertTrue(isinstance(menu_model, Gio.Menu))
        m = Gtk.Menu.new_from_model(menu_model)
        self.assertEqual(len(m.get_children()), 1)
        self.assertEqual(menu_model.get_n_items(), 1)
        self.assertEqual(m.get_children()[0].get_label(), "Tag Selection")

    def test_build_menu_one_tag(self):
        tagname = "some-tag"
        t = Tag(tag=tagname, description="description")
        self.session.add(t)
        self.session.commit()
        menu_model = tag_plugin.tags_menu_manager.build_menu()
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
        menu_model = tag_plugin.tags_menu_manager.build_menu()
        self.assertTrue(isinstance(menu_model, Gio.Menu))
        m = Gtk.Menu.new_from_model(menu_model)
        self.assertEqual(menu_model.get_n_items(), 3)
        self.assertEqual(len(m.get_children()), 10)
        for i in range(5):
            self.assertEqual(m.get_children()[i + 2].get_label(), tagname % i)

    @mock.patch("bauble.gui")
    def test_reset_adds_and_removes_menu(self, mock_gui):
        tags_mm = TagsMenuManager()
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

    def test_reset_active_tag_name_session_is_none_bails(self):
        tags_mm = TagsMenuManager()
        self.assertIsNone(tags_mm.active_tag_name)
        with mock.patch("bauble.plugins.tag.db.Session", None):
            with self.assertLogs(level="WARNING") as logs:
                tags_mm.reset_active_tag_name()
            self.assertIsNone(tags_mm.active_tag_name)
            string = "no session bailing."
            self.assertTrue(any(string in i for i in logs.output))

    def test_reset_active_tag_name_resets_if_none_or_invalid(self):
        t1 = Tag(tag="tag-1")
        t2 = Tag(tag="tag-2")
        self.session.add_all([t1, t2])
        self.session.commit()
        tags_mm = TagsMenuManager()
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
        tags_mm = TagsMenuManager()
        tags_mm.refresh = mock.Mock()
        variant = GLib.Variant.new_string("test1")
        action = Gio.SimpleAction.new_stateful(
            tags_mm.ACTIVATED_ACTION_NAME, variant.get_type(), variant
        )

        with mock.patch("bauble.plugins.tag.GLib.idle_add") as mock_iadd:
            tags_mm.on_tag_change_state(action, variant)

            mock_iadd.assert_called()
        mock_gui.send_command.assert_called_with("tag='test1'")
        tags_mm.refresh.assert_called()
        self.assertEqual(tags_mm.active_tag_name, "test1")

    @mock.patch("bauble.gui")
    def test_on_context_menu_apply_activated_bails(self, mock_gui):
        # no SearchView
        mock_sv = mock.Mock()
        mock_gui.get_view.return_value = mock_sv
        mock_sv.get_selected_values.return_value = []
        tags_mm = TagsMenuManager()
        variant = GLib.Variant.new_string("test2")

        tags_mm.on_context_menu_apply_activated(None, variant)

        mock_sv.get_selected_values.assert_not_called()
        mock_sv.update_bottom_notebook.assert_not_called()

    @mock.patch("bauble.gui")
    def test_on_context_menu_apply_activated_w_values(self, mock_gui):
        # with SearchView with Values
        mock_sv = mock.Mock(spec=SearchView)
        mock_gui.get_view.return_value = mock_sv
        fam = Family(epithet="Myrtaceae")
        mock_sv.get_selected_values.return_value = [fam]
        tags_mm = TagsMenuManager()
        variant = GLib.Variant.new_string("test2")

        with mock.patch("bauble.plugins.tag.tag_objects") as mock_to:
            tags_mm.on_context_menu_apply_activated(None, variant)
            mock_to.assert_called()

        mock_sv.update_bottom_notebook.assert_called_with([fam])

    @mock.patch("bauble.gui")
    def test_on_context_menu_remove_activated_bails(self, mock_gui):
        # no SearchView
        mock_sv = mock.Mock()
        mock_gui.get_view.return_value = mock_sv
        mock_sv.get_selected_values.return_value = []
        tags_mm = TagsMenuManager()
        variant = GLib.Variant.new_string("test2")

        tags_mm.on_context_menu_remove_activated(None, variant)

        mock_sv.get_selected_values.assert_not_called()
        mock_sv.update_bottom_notebook.assert_not_called()

    @mock.patch("bauble.gui")
    def test_on_context_menu_remove_activated_w_values(self, mock_gui):
        # with SearchView with Values
        mock_sv = mock.Mock(spec=SearchView)
        mock_gui.get_view.return_value = mock_sv
        fam = Family(epithet="Myrtaceae")
        mock_sv.get_selected_values.return_value = [fam]
        tags_mm = TagsMenuManager()
        variant = GLib.Variant.new_string("test2")

        with mock.patch("bauble.plugins.tag.untag_objects") as mock_uto:
            tags_mm.on_context_menu_remove_activated(None, variant)
            mock_uto.assert_called()

        mock_sv.update_bottom_notebook.assert_called_with([fam])

    def test_context_menu_callback_bails_nothing_selected(self):
        tags_mm = TagsMenuManager()

        with self.assertLogs(level="WARNING") as logs:
            self.assertIsNone(tags_mm.context_menu_callback([]))

        string = "nothing selected bailing."
        self.assertTrue(any(string in i for i in logs.output))

    def test_context_menu_callback_bails_no_session(self):
        tags_mm = TagsMenuManager()

        with self.assertLogs(level="WARNING") as logs:
            self.assertIsNone(
                tags_mm.context_menu_callback([Family(epithet="Myrtaceae")])
            )

        string = "no object session bailing."
        self.assertTrue(any(string in i for i in logs.output))

    def test_context_menu_callback_bails_no_tags(self):
        tags_mm = TagsMenuManager()
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
        tags_mm = TagsMenuManager()
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
        apply, remove = TagsMenuManager._apply_remove_tags([fam, fam2], query)
        self.assertCountEqual(remove, [tag1])
        self.assertCountEqual(apply, [tag1, tag2, tag3])

        tag1.tag_objects([fam2])
        self.session.commit()
        apply, remove = TagsMenuManager._apply_remove_tags([fam, fam2], query)
        self.assertCountEqual(remove, [tag1])
        self.assertCountEqual(apply, [tag2, tag3])

    def test_toggle_tag_warns_not_search_view(self):
        tags_mm = TagsMenuManager()
        with mock.patch("bauble.gui") as mock_gui:
            mock_sv = mock.Mock()
            mock_gui.get_view.return_value = mock_sv
            tags_mm.toggle_tag(None)
            mock_gui.show_message_box.assert_called_with(
                "In order to tag or untag an item you must first search "
                "for something."
            )

    def test_toggle_tag_warns_nothing_selected(self):
        tags_mm = TagsMenuManager()
        with mock.patch("bauble.gui") as mock_gui:
            mock_sv = mock.Mock(spec=SearchView)
            mock_sv.get_selected_values.return_value = None
            mock_gui.get_view.return_value = mock_sv
            tags_mm.toggle_tag(None)
            mock_gui.show_message_box.assert_called_with(
                "In order to tag or untag an item you must first search "
                "for something."
            )

    @mock.patch("bauble.plugins.tag.utils.message_dialog")
    def test_toggle_tag_no_active_tag_messages(self, mock_dialog):
        tags_mm = TagsMenuManager()
        with mock.patch("bauble.gui") as mock_gui:
            mock_sv = mock.Mock(spec=SearchView)
            mock_sv.get_selected_values.return_value = [None, None]
            mock_gui.get_view.return_value = mock_sv
            self.assertIsNone(tags_mm.active_tag_name)
            tags_mm.toggle_tag(None)
            mock_dialog.assert_called_with("Please make sure a tag is active.")

    def test_toggle_tag_applies(self):
        # setup some test data
        tags_mm = TagsMenuManager()
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
        tags_mm = TagsMenuManager()
        tags_mm.toggle_tag = mock.Mock()
        tags_mm.on_apply_active_tag_activated(None, None)
        tags_mm.toggle_tag.assert_called_with(tag_objects)

    def test_on_remove_active_tag_activated(self):
        tags_mm = TagsMenuManager()
        tags_mm.toggle_tag = mock.Mock()
        tags_mm.on_remove_active_tag_activated(None, None)
        tags_mm.toggle_tag.assert_called_with(untag_objects)


from types import SimpleNamespace

import bauble.db as db


class MockTagView(GenericEditorView):
    def __init__(self):
        self._dirty = False
        self.sensitive = False
        self.dict = {}
        self.widgets = SimpleNamespace(tag_name_entry=Gtk.Entry())
        self.window = Gtk.Dialog()

    def get_window(self):
        return self.window

    def is_dirty(self):
        return self._dirty

    def connect_signals(self, *args):
        pass

    def set_accept_buttons_sensitive(self, value):
        self.sensitive = value

    def widget_set_value(
        self, widget, value, markup=False, default=None, index=0
    ):
        self.dict[widget] = value

    def widget_get_value(self, widget):
        return self.dict.get(widget)


class TagPresenterTests(BaubleTestCase):
    "Presenter manages view and model, implements view callbacks."

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        import bauble.prefs

        bauble.prefs.testing = True

    def test_when_user_edits_name_name_is_memorized(self):
        model = Tag()
        view = MockTagView()
        presenter = TagEditorPresenter(model, view)
        view.widget_set_value("tag_name_entry", "1234")
        presenter.on_text_entry_changed("tag_name_entry")
        self.assertEqual(presenter.model.tag, "1234")

    def test_when_user_inserts_existing_name_warning_ok_deactivated(self):
        session = db.Session()

        # prepare data in database
        obj = Tag(tag="1234")
        session.add(obj)
        session.commit()
        session.close()
        ## ok. thing is already there now.

        session = db.Session()
        view = MockTagView()
        obj = Tag()  # new scratch object
        session.add(obj)  # is in session
        presenter = TagEditorPresenter(obj, view)
        self.assertTrue(not view.sensitive)  # not changed
        presenter.on_unique_text_entry_changed("tag_name_entry", "1234")
        self.assertEqual(obj.tag, "1234")
        self.assertTrue(view.is_dirty())
        self.assertTrue(not view.sensitive)  # unacceptable change
        self.assertTrue(presenter.has_problems())

    def test_widget_names_and_field_names(self):
        model = Tag()
        view = MockTagView()
        presenter = TagEditorPresenter(model, view)
        for widget, field in list(presenter.widget_to_field_map.items()):
            self.assertTrue(hasattr(model, field), field)
            presenter.view.widget_get_value(widget)

    def test_when_user_edits_fields_ok_active(self):
        model = Tag()
        view = MockTagView()
        presenter = TagEditorPresenter(model, view)
        self.assertTrue(not view.sensitive)  # not changed
        view.widget_set_value("tag_name_entry", "1234")
        presenter.on_text_entry_changed("tag_name_entry")
        self.assertEqual(presenter.model.tag, "1234")
        self.assertTrue(view.sensitive)  # changed

    def test_when_user_edits_description_description_is_memorized(self):
        pass

    def test_presenter_does_not_initialize_view(self):
        session = db.Session()

        # prepare data in database
        obj = Tag(tag="1234")
        session.add(obj)
        view = MockTagView()
        presenter = TagEditorPresenter(obj, view)
        self.assertFalse(view.widget_get_value("tag_name_entry"))
        presenter.refresh_view()
        self.assertEqual(view.widget_get_value("tag_name_entry"), "1234")

    def test_if_asked_presenter_initializes_view(self):
        session = db.Session()

        # prepare data in database
        obj = Tag(tag="1234")
        session.add(obj)
        view = MockTagView()
        TagEditorPresenter(obj, view, refresh_view=True)
        self.assertEqual(view.widget_get_value("tag_name_entry"), "1234")


class TagInfoBoxTest(BaubleTestCase):
    def setUp(self):
        self.ib = TagInfoBox()
        super().setUp()

    def tearDown(self):
        # due to way BuilderLoader caches Gtk.Bulder need to reattach
        # general_box each time or will get these annoying errors each run:
        # Gtk-CRITICAL: gtk_bin_remove: assertion 'priv->child == child' failed
        # Gtk-CRITICAL: gtk_box_pack: assertion '_gtk_widget_get_parent (child)
        # == NULL' failed
        # Doesn't occur in usage
        gbox = self.ib.widgets.general_box
        gbox.get_parent().remove(gbox)
        # self.ib.destroy()
        self.ib.widgets.general_window.add(gbox)
        super().tearDown()

    def test_update_infobox_from_empty_tag(self):
        t = Tag(tag="name", description="description")
        # ib = TagInfoBox()
        self.ib.update(t)
        self.assertEqual(
            self.ib.widgets.ib_description_label.get_text(), t.description
        )
        self.assertEqual(self.ib.widgets.ib_name_label.get_text(), t.tag)
        self.assertEqual(self.ib.general.table_cells, [])

    def test_update_infobox_from_tagging_tag(self):
        t = Tag(tag="name", description="description")
        x = Tag(tag="objectx", description="none")
        y = Tag(tag="objecty", description="none")
        z = Tag(tag="objectz", description="none")
        self.session.add_all([t, x, y, z])
        self.session.commit()
        t.tag_objects([x, y, z])
        # ib = TagInfoBox()
        self.assertEqual(self.ib.general.table_cells, [])
        self.ib.update(t)
        self.assertEqual(
            self.ib.widgets.ib_description_label.get_text(), t.description
        )
        self.assertEqual(self.ib.widgets.ib_name_label.get_text(), t.tag)
        self.assertEqual(len(self.ib.general.table_cells), 2)
        self.assertEqual(self.ib.general.table_cells[0].get_text(), "Tag")
        self.assertEqual(type(self.ib.general.table_cells[1]), Gtk.EventBox)
        label = self.ib.general.table_cells[1].get_children()[0]
        self.assertEqual(label.get_text(), " 3 ")


class TagCallbackTest(BaubleTestCase):
    @mock.patch("bauble.gui")
    def test_on_add_tag_activated_wrong_view(self, mock_gui):
        mock_gui.get_view.return_value = mock.Mock()

        tag_plugin._on_add_tag_activated(None, None)

        msg = (
            "In order to tag or untag an item you must first search for "
            "something."
        )
        mock_gui.show_message_box.assert_called_with(msg)

    @mock.patch("bauble.gui")
    def test_on_add_tag_activated_search_view_empty_selection(self, mock_gui):
        mock_sv = mock.Mock(spec=SearchView)
        mock_gui.get_view.return_value = mock_sv
        mock_sv.get_selected_values.return_value = []

        tag_plugin._on_add_tag_activated(None, None)

        mock_sv.get_selected_values.assert_called()

        msg = (
            "In order to tag or untag an item you must first search for "
            "something."
        )
        mock_gui.show_message_box.assert_called_with(msg)


class GlobalFunctionsTests(BaubleTestCase):

    def test_tag_untag_objects(self):
        family1 = Family(epithet="family1")
        family2 = Family(epithet="family2")
        self.session.add_all([family1, family2])
        self.session.commit()
        family1_id = family1.id
        family2_id = family2.id
        tag_objects("test", [family1, family2])

        tag = self.session.query(Tag).filter_by(tag="test").one()
        sorted_pairs = sorted([(type(o), o.id) for o in tag.objects])
        self.assertEqual(
            sorted([(Family, family1_id), (Family, family2_id)]), sorted_pairs
        )

        # required for windows tests to succeed due to 16ms resolution
        sleep(0.02)
        tag_objects("test", [family1, family2])
        self.assertEqual(tag.objects, [family1, family2])

        # first untag one
        sleep(0.02)
        untag_objects("test", [family1])

        # get object by tag
        tag = self.session.query(Tag).filter_by(tag="test").one()
        self.assertEqual(tag.objects, [family2])

        # then both
        sleep(0.02)
        untag_objects("test", [family1, family2])

        # get object by tag
        tag = self.session.query(Tag).filter_by(tag="test").one()
        self.assertEqual(tag.objects, [])

    @mock.patch("bauble.plugins.tag.utils.yes_no_dialog")
    @mock.patch("bauble.plugins.tag.utils.message_details_dialog")
    def test_remove_callback_no_confirm(self, mock_mdd, mock_ynd):
        mock_ynd.return_value = False
        tag = Tag(tag="Foo")
        self.session.add(tag)
        self.session.flush()

        result = remove_callback([tag])
        self.session.flush()

        mock_mdd.assert_not_called()
        # effect
        mock_ynd.assert_called_with(
            "Are you sure you want to remove Tag: Foo?"
        )

        self.assertFalse(result)
        matching = self.session.query(Tag).filter_by(tag="Foo").all()
        self.assertEqual(matching, [tag])

    @mock.patch("bauble.plugins.tag.utils.yes_no_dialog")
    @mock.patch("bauble.plugins.tag.utils.message_details_dialog")
    def test_remove_callback_confirm(self, mock_mdd, mock_ynd):
        mock_ynd.return_value = True
        tag = Tag(tag="Foo")
        self.session.add(tag)
        self.session.flush()
        with mock.patch("bauble.plugins.tag.TagsMenuManager.reset") as m_reset:

            result = remove_callback([tag])
            self.session.flush()

            m_reset.assert_called()
            mock_mdd.assert_not_called()
            mock_ynd.assert_called_with(
                "Are you sure you want to remove Tag: Foo?"
            )
            self.assertEqual(result, True)
        matching = self.session.query(Tag).filter_by(tag="Arecaceae").all()
        self.assertEqual(matching, [])
