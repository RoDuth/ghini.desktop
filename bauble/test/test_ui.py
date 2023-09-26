# pylint: disable=too-many-public-methods
# Copyright (c) 2023 Ross Demuth <rossdemuth123@gmail.com>
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
UI tests
"""
from unittest import mock

from gi.repository import Gio
from gi.repository import Gtk

from bauble import prefs
from bauble import search
from bauble import task
from bauble import utils
from bauble import view
from bauble.test import BaubleTestCase
from bauble.test import get_setUp_data_funcs
from bauble.test import update_gui
from bauble.test import wait_on_threads
from bauble.ui import GUI
from bauble.ui import DefaultView
from bauble.ui import SimpleSearchBox
from bauble.ui import SplashCommandHandler


class SimpleSearchBoxTest(BaubleTestCase):
    def setUp(self):
        super().setUp()
        self.simplesearch = SimpleSearchBox()

    def test_on_domain_combo_changed(self):
        mapper_search = search.get_strategy("MapperSearch")
        mock_combo = mock.Mock()
        mock_combo.get_active_text.return_value = "species_full_name"
        self.simplesearch.on_domain_combo_changed(mock_combo)
        self.assertEqual(
            self.simplesearch.domain, mapper_search.domains["species"][0]
        )
        self.assertEqual(self.simplesearch.columns, ["full_name"])
        self.assertEqual(self.simplesearch.short_domain, "taxon")
        self.assertEqual(self.simplesearch.completion_getter, None)

    def test_on_entry_changed(self):
        for func in get_setUp_data_funcs():
            func()
        mapper_search = search.get_strategy("MapperSearch")
        Species = mapper_search.domains["species"][
            0
        ]  # pylint: disable=invalid-name
        sp = Species(genus_id=1, sp="grandiosa")
        self.session.add(sp)
        self.session.commit()
        self.simplesearch.domain = Species
        self.simplesearch.columns = ["sp"]
        self.simplesearch.short_domain = "sp"
        mock_entry = mock.Mock()
        mock_entry.get_text.return_value = str(sp.sp)[:4]
        completion = Gtk.EntryCompletion()
        mock_entry.get_completion.return_value = completion
        self.simplesearch.on_entry_changed(mock_entry)
        update_gui()
        self.assertTrue(utils.tree_model_has(completion.get_model(), sp.sp))

    def test_update(self):
        self.assertFalse(list(self.simplesearch.domain_combo.get_model()))
        self.simplesearch.update()
        self.assertTrue(list(self.simplesearch.domain_combo.get_model()))
        self.assertFalse(self.simplesearch.entry.get_text())
        self.assertFalse(self.simplesearch.domain_combo.get_active())
        self.assertFalse(self.simplesearch.cond_combo.get_active())

    @mock.patch("bauble.gui")
    def test_on_entry_activated(self, mock_gui):
        mock_send = mock.Mock()
        mock_gui.send_command = mock_send
        self.simplesearch.update()
        mock_entry = mock.Mock()
        mock_entry.get_text.return_value = "test"
        self.simplesearch.on_entry_activated(mock_entry)
        mock_send.assert_called()
        mock_send.assert_called_with("acc = 'test'")


class DefaultViewTests(BaubleTestCase):
    @mock.patch("bauble.gui")
    def test_update(self, mock_gui):
        mock_send = mock.Mock()
        mock_gui.send_command = mock_send
        def_view = DefaultView()
        self.assertFalse(list(def_view.search_box.domain_combo.get_model()))
        self.assertFalse(def_view.infobox)
        def_view.update()
        # SplashInfoBox threads
        wait_on_threads()
        self.assertTrue(list(def_view.search_box.domain_combo.get_model()))
        # set in PlantsPlugin.init
        self.assertTrue(def_view.infoboxclass)
        self.assertTrue(def_view.infobox)

    @mock.patch("bauble.ui.DefaultView", spec=DefaultView)
    def test_splashcommandhandler(self, mock_default):
        splash = SplashCommandHandler()
        self.assertIsNone(splash.view)
        self.assertIsInstance(splash.get_view(), DefaultView)
        self.assertIsInstance(splash.view, DefaultView)
        splash(None, None)
        mock_default.assert_called_once()


class GUITests(BaubleTestCase):
    def test_actions(self):
        gui = GUI()
        mock_handler = mock.Mock()
        self.assertIsNone(gui.lookup_action("test"))
        gui.add_action("test", mock_handler)
        self.assertIsNotNone(gui.lookup_action("test"))
        gui.remove_action("test")
        self.assertIsNone(gui.lookup_action("test"))

    def test_message_box(self):
        gui = GUI()
        self.assertFalse(gui.widgets.msg_box_parent.get_children())

        gui.show_yesno_box("test")
        self.assertTrue(gui.widgets.msg_box_parent.get_children())

        gui.close_message_box()
        self.assertFalse(gui.widgets.msg_box_parent.get_children())

        gui.show_error_box("test")
        self.assertTrue(gui.widgets.msg_box_parent.get_children())

        gui.close_message_box()
        self.assertFalse(gui.widgets.msg_box_parent.get_children())

        gui.show_message_box("test")
        self.assertTrue(gui.widgets.msg_box_parent.get_children())

        gui.close_message_box()
        self.assertFalse(gui.widgets.msg_box_parent.get_children())

    def test_history_sizes(self):
        gui = GUI()
        # pylint: disable=protected-access
        self.assertEqual(gui.history_size, gui._default_history_size)
        self.assertEqual(gui.history_pins_size, gui._default_history_pin_size)
        prefs.prefs[gui.history_size_pref] = 2
        prefs.prefs[gui.history_pins_size_pref] = 1
        self.assertEqual(gui.history_size, 2)
        self.assertEqual(gui.history_pins_size, 1)

    def test_send_command(self):
        gui = GUI()
        mock_combo = mock.Mock()
        mock_entry = mock.Mock()
        mock_btn = mock.Mock()
        mock_combo.get_child.return_value = mock_entry

        gui.widgets.main_comboentry = mock_combo
        gui.widgets.go_button = mock_btn
        gui.send_command("test command")
        mock_entry.set_text.assert_called_once()
        mock_entry.set_text.assert_called_with("test command")

    def test_om_main_combo_changed(self):
        # with text not in history_pins
        gui = GUI()
        mock_combo = mock.Mock()
        mock_entry = mock.Mock()
        mock_entry = mock.Mock()
        mock_entry.get_text.return_value = "test1"
        mock_combo.get_child.return_value = mock_entry

        gui.on_main_combo_changed(mock_combo)
        mock_entry.set_icon_from_icon_name.assert_called_with(
            Gtk.EntryIconPosition.SECONDARY, "non-starred-symbolic"
        )
        # with text in history_pins
        prefs.prefs[gui.entry_history_pins_pref] = ["test1"]
        gui.on_main_combo_changed(mock_combo)
        mock_entry.set_icon_from_icon_name.assert_called_with(
            Gtk.EntryIconPosition.SECONDARY, "starred-symbolic"
        )
        # without text
        mock_entry.get_text.return_value = ""
        gui.on_main_combo_changed(mock_combo)
        mock_entry.set_icon_from_icon_name.assert_called_with(
            Gtk.EntryIconPosition.SECONDARY, None
        )

    def test_on_main_entry_activated(self):
        gui = GUI()
        mock_btn = mock.Mock()
        gui.widgets.go_button = mock_btn
        gui.on_main_entry_activate(None)
        mock_btn.emit.assert_called_with("clicked")

    @mock.patch("bauble.ui.bauble.command_handler")
    def test_on_home_clicked(self, mock_handler):
        gui = GUI()
        gui.on_home_clicked()
        mock_handler.assert_called_with("home", None)

    def test_on_prev_view_clicked(self):
        gui = GUI()
        mock_combo = mock.Mock()
        mock_entry = mock.Mock()
        mock_combo.get_child.return_value = mock_entry
        gui.widgets.main_comboentry = mock_combo
        gui.set_view = mock.Mock()

        gui.on_prev_view_clicked()
        mock_entry.set_text.assert_called_with("")
        gui.set_view.assert_called_with("previous")

    @mock.patch("bauble.ui.bauble.command_handler")
    def test_on_go_button_clicked(self, mock_handler):
        gui = GUI()
        mock_combo = mock.Mock()
        mock_entry = mock.Mock()
        mock_combo.get_child.return_value = mock_entry
        gui.widgets.main_comboentry = mock_combo
        gui.set_view = mock.Mock()

        gui.on_prev_view_clicked()
        mock_entry.set_text.assert_called_with("")
        gui.set_view.assert_called_with("previous")

        # with blank text
        mock_entry.get_text.return_value = ""
        gui.on_go_button_clicked(None)
        mock_handler.assert_not_called()

        history = prefs.prefs.get(gui.entry_history_pref, [])
        self.assertEqual(history, [])
        # with a command
        mock_entry.get_text.return_value = ":cmd"
        gui.on_go_button_clicked(None)
        mock_handler.assert_called_with("cmd", None)

        history = prefs.prefs.get(gui.entry_history_pref)
        self.assertEqual(history, [":cmd"])
        # with a command and arg
        mock_entry.get_text.return_value = ":cmd=args"
        gui.on_go_button_clicked(None)
        mock_handler.assert_called_with("cmd", "args")

        history = prefs.prefs.get(gui.entry_history_pref)
        self.assertEqual(history, [":cmd=args", ":cmd"])
        # with arg
        mock_entry.get_text.return_value = "domain where expression"
        gui.on_go_button_clicked(None)
        mock_handler.assert_called_with(None, "domain where expression")

        history = prefs.prefs.get(gui.entry_history_pref)
        self.assertEqual(
            history, ["domain where expression", ":cmd=args", ":cmd"]
        )

    @mock.patch("bauble.ui.QueryBuilder")
    def test_on_query_button_clicked(self, mock_builder_class):
        mock_builder = mock_builder_class.return_value
        gui = GUI()
        mock_combo = mock.Mock()
        mock_entry = mock.Mock()
        mock_combo.get_child.return_value = mock_entry
        mock_btn = mock.Mock()
        gui.widgets.go_button = mock_btn

        gui.widgets.main_comboentry = mock_combo
        gui.widgets.go_button = mock_btn
        mock_builder.start.return_value = Gtk.ResponseType.OK
        mock_builder.get_query.return_value = "sp = sp."

        gui.on_query_button_clicked(None)

        mock_entry.set_text.assert_called_with("sp = sp.")
        mock_btn.emit.assert_called_with("clicked")
        mock_builder.cleanup.assert_called_once()

    def test_on_history_pinned_clicked(self):
        gui = GUI()
        mock_entry = mock.Mock()

        # no text, no history, no pins - does nothing
        mock_entry.get_text.return_value = ""

        gui.on_history_pinned_clicked(mock_entry, None, None)

        history = prefs.prefs.get(gui.entry_history_pref, [])
        pins = prefs.prefs.get(gui.entry_history_pins_pref, [])
        self.assertEqual(history, [])
        self.assertEqual(pins, [])

        # with text, no history, no pins - adds to pins
        mock_entry.get_text.return_value = ":cmd"

        gui.on_history_pinned_clicked(mock_entry, None, None)

        history = prefs.prefs.get(gui.entry_history_pref, [])
        pins = prefs.prefs.get(gui.entry_history_pins_pref, [])
        self.assertEqual(history, [])
        self.assertEqual(pins, [":cmd"])

        # with text, no history, in pins - moves from pins to history
        mock_entry.get_text.return_value = ":cmd"

        gui.on_history_pinned_clicked(mock_entry, None, None)

        history = prefs.prefs.get(gui.entry_history_pref, [])
        pins = prefs.prefs.get(gui.entry_history_pins_pref, [])
        self.assertEqual(history, [":cmd"])
        self.assertEqual(pins, [])

        # with text, in history, no pins - moves from history to pins
        mock_entry.get_text.return_value = ":cmd"

        gui.on_history_pinned_clicked(mock_entry, None, None)

        history = prefs.prefs.get(gui.entry_history_pref, [])
        pins = prefs.prefs.get(gui.entry_history_pins_pref, [])
        self.assertEqual(history, [])
        self.assertEqual(pins, [":cmd"])

    def test_add_to_history(self):
        gui = GUI()

        # with no history, adds
        gui.add_to_history("test1")

        history = prefs.prefs.get(gui.entry_history_pref, [])
        pins = prefs.prefs.get(gui.entry_history_pins_pref, [])
        self.assertEqual(history, ["test1"])
        self.assertEqual(pins, [])

        # with same in history, adding again doesn't add a double up
        gui.add_to_history("test1")

        history = prefs.prefs.get(gui.entry_history_pref, [])
        pins = prefs.prefs.get(gui.entry_history_pins_pref, [])
        self.assertEqual(history, ["test1"])
        self.assertEqual(pins, [])

        # with different in history, prepends
        gui.add_to_history("test2")

        history = prefs.prefs.get(gui.entry_history_pref, [])
        pins = prefs.prefs.get(gui.entry_history_pins_pref, [])
        self.assertEqual(history, ["test2", "test1"])
        self.assertEqual(pins, [])

        # with same in pins, doesn't add
        prefs.prefs[gui.entry_history_pref] = []
        prefs.prefs[gui.entry_history_pins_pref] = ["test1"]
        gui.add_to_history("test1")

        history = prefs.prefs.get(gui.entry_history_pref, [])
        pins = prefs.prefs.get(gui.entry_history_pins_pref, [])
        self.assertEqual(history, [])
        self.assertEqual(pins, ["test1"])

    def test_populate_main_entry(self):
        gui = GUI()
        prefs.prefs[gui.entry_history_pref] = ["test1"]
        prefs.prefs[gui.entry_history_pins_pref] = ["test2"]
        entry = gui.widgets.main_comboentry.get_child()
        completion = entry.get_completion()
        comp_model = completion.get_model()
        self.assertCountEqual(list(comp_model), [])
        combo = gui.widgets.main_comboentry
        model = combo.get_model()

        gui.populate_main_entry()

        self.assertEqual([v[0] for v in comp_model], ["test2", "test1"])
        self.assertEqual(
            [v[0] for v in model], ["test2", "--separator--", "test1"]
        )

    def test_title(self):
        import bauble

        orig_conn = bauble.conn_name
        orig_version = bauble.version

        bauble.conn_name = None
        bauble.version = "1"
        gui = GUI()
        self.assertEqual(gui.title, "Ghini 1")
        bauble.conn_name = "test"
        self.assertEqual(gui.title, "Ghini 1 - test")

        bauble.conn_name = orig_conn
        bauble.version = orig_version

    def test_set_busy(self):
        gui = GUI()
        gui.set_busy(False)
        self.assertTrue(gui.widgets.main_box.get_sensitive())
        gui.set_busy(True)
        self.assertFalse(gui.widgets.main_box.get_sensitive())

    def test_set_get_view(self):
        gui = GUI()
        self.assertIsNone(gui.previous_view)
        self.assertIsInstance(gui.get_view(), DefaultView)

        # None doesn't set
        gui.set_view(None)
        self.assertIsInstance(gui.get_view(), DefaultView)
        first_view = gui.get_view()

        # set to SearchView
        gui.set_view(view.SearchView())
        self.assertIsInstance(gui.get_view(), view.SearchView)
        second_view = gui.get_view()
        self.assertIsNotNone(gui.previous_view)
        self.assertIs(gui.previous_view, first_view)

        # switch back to previous
        gui.set_view("previous")
        self.assertIsNotNone(gui.previous_view)
        self.assertIs(gui.get_view(), first_view)
        self.assertIs(gui.previous_view, second_view)

    def test_add_remove_menu(self):
        gui = GUI()
        self.assertIsNotNone(gui.insert_menu)
        self.assertIsNotNone(gui.edit_context_menu)
        self.assertIsNotNone(gui.tools_menu)
        self.assertIsNotNone(gui.options_menu)
        start = gui.menubar.get_n_items()
        gui.remove_menu(0)
        self.assertEqual(gui.menubar.get_n_items(), start - 1)
        gui.add_menu("test", Gio.Menu())
        self.assertEqual(gui.menubar.get_n_items(), start)

    def test_add_to_insert_menu(self):
        gui = GUI()
        self.assertEqual(gui.insert_menu.get_n_items(), 0)
        mock_editor = mock.Mock()
        gui.add_to_insert_menu(mock_editor, "test")
        self.assertEqual(gui.insert_menu.get_n_items(), 1)

    def test_build_tools_menu(self):
        gui = GUI()
        self.assertEqual(gui.tools_menu.get_n_items(), 0)
        from bauble import pluginmgr

        pluginmgr.init()
        gui.build_tools_menu()
        self.assertNotEqual(gui.tools_menu.get_n_items(), 0)

        # -1 to account for __root
        tool_count = -1
        for plugin in list(pluginmgr.plugins.values()):
            tool_count += len({t.category for t in plugin.tools})
        self.assertEqual(gui.tools_menu.get_n_items(), tool_count)

    def test_on_tools_menu_item_activate(self):
        gui = GUI()
        mock_tool = mock.Mock()
        gui.on_tools_menu_item_activate(None, None, mock_tool)
        mock_tool.start.assert_called_once()

    @mock.patch("bauble.ui.utils.gc_objects_by_type")
    def test_on_insert_menu_item_activate(self, mock_gc_objects):
        gui = GUI()

        # function no SearchView (minimal)
        mock_editor = mock.Mock(spec=type(lambda x: x))
        mock_editor.__name__ = "test"
        gui.on_insert_menu_item_activate(None, None, mock_editor)
        mock_editor.assert_called_once()

        # function with SeachView
        search_view = view.SearchView()
        search_view.expand_to_all_rows = mock.Mock()
        gui.set_view(search_view)
        mock_editor = mock.Mock(spec=type(lambda x: x))
        mock_editor.__name__ = "test"
        gui.on_insert_menu_item_activate(None, None, mock_editor)
        mock_editor.assert_called_once()
        search_view.expand_to_all_rows.assert_called_once()

        # class with SeachView
        search_view = view.SearchView()
        search_view.expand_to_all_rows = mock.Mock()
        gui.set_view(search_view)
        mock_editor = mock.Mock()
        mock_editor.__name__ = "test"
        # we know that mock_editor will not be garbage collected (mocking here
        # avoids ReferenceError: weakly-referenced object no longer exists)
        mock_gc_objects.assert_not_called()
        mock_gc_objects.return_value = []
        gui.on_insert_menu_item_activate(None, None, mock_editor)
        mock_gc_objects.assert_called()
        mock_editor.assert_called_once()
        search_view.expand_to_all_rows.assert_called_once()

    def test_cut_copy_paste(self):
        gui = GUI()
        mock_combo = mock.Mock()
        mock_entry = mock.Mock()
        mock_combo.get_child.return_value = mock_entry

        gui.widgets.main_comboentry = mock_combo
        # cut
        gui.on_edit_menu_cut(None, None)
        mock_entry.cut_clipboard.assert_called_once()
        # copy
        gui.on_edit_menu_copy(None, None)
        mock_entry.copy_clipboard.assert_called_once()
        # paste
        gui.on_edit_menu_paste(None, None)
        mock_entry.paste_clipboard.assert_called_once()

    @mock.patch("bauble.ui.bauble.command_handler")
    def test_edit_menu_prefs_hist(self, mock_handler):
        gui = GUI()

        gui.on_edit_menu_history(None, None)
        mock_handler.assert_called_with("history", None)

        gui.on_edit_menu_preferences(None, None)
        mock_handler.assert_called_with("prefs", None)

    @mock.patch("bauble.ui.db.create")
    @mock.patch("bauble.ui.utils.yes_no_dialog")
    @mock.patch("bauble.ui.bauble.command_handler")
    def test_on_file_menu_new(self, mock_handler, mock_dialog, mock_create):
        gui = GUI()
        # user backs out
        mock_dialog.return_value = False
        gui.on_file_menu_new(None, None)
        mock_dialog.assert_called()
        mock_handler.assert_not_called()
        mock_create.assert_not_called()
        # user backs out
        mock_dialog.return_value = True
        gui.on_file_menu_new(None, None)
        mock_handler.assert_called()
        mock_create.assert_called()

    @mock.patch("bauble.connmgr.start_connection_manager")
    @mock.patch("bauble.ui.db.open_conn")
    @mock.patch("bauble.ui.bauble.command_handler")
    def test_on_file_menu_open(self, mock_handler, mock_open, mock_start):
        gui = GUI()
        # back out
        mock_start.return_value = (None, None)
        gui.on_file_menu_open(None, None)
        mock_handler.assert_not_called()
        mock_open.assert_not_called()
        import bauble

        self.assertIsNone(bauble.conn_name)
        # connection selected
        mock_start.return_value = ("test", "test_conn")
        gui.on_file_menu_open(None, None)
        mock_handler.assert_called()
        mock_open.assert_called()

    @mock.patch("bauble.ui.Gtk.AboutDialog")
    @mock.patch("bauble.ui.desktop.open")
    def test_help_menu(self, mock_open, mock_about):
        gui = GUI()

        gui.on_help_menu_contents(None, None)
        mock_open.assert_called_once()
        mock_open.reset_mock()

        gui.on_help_menu_bug(None, None)
        mock_open.assert_called_once()
        mock_open.reset_mock()

        gui.on_help_menu_logfile(None, None)
        mock_open.assert_called_once()
        mock_open.reset_mock()

        gui.on_help_menu_web_devel(None, None)
        mock_open.assert_called_once()
        mock_open.reset_mock()

        gui.on_help_menu_about(None, None)
        mock_about.assert_called()
        mock_about().set_program_name.assert_called_once()
        mock_about().run.assert_called_once()
        mock_about().destroy.assert_called_once()
        self.assertTrue(gui.lic_path.exists())

    @mock.patch("bauble.ui.bauble.utils.yes_no_dialog")
    @mock.patch("bauble.ui.bauble.task.running")
    def test_on_delete_event(self, mock_running, mock_dialog):
        gui = GUI()
        # no tasks running
        mock_running.return_value = False
        self.assertFalse(gui.on_delete_event(None, None))

        # user backs out - tasks running
        mock_running.return_value = True
        mock_dialog.return_value = False
        self.assertTrue(gui.on_delete_event(None, None))
        mock_dialog.assert_called_once()
        mock_dialog.reset_mock()

        # cancel tasks and close
        mock_dialog.return_value = True
        self.assertFalse(gui.on_delete_event(None, None))
        mock_dialog.assert_called()
        # have to use getattr to avoid name mangling
        self.assertTrue(getattr(task, "__kill"))

    def test_on_destroy(self):
        gui = GUI()
        mock_view = mock.Mock()
        gui.get_view = mock.Mock(return_value=mock_view)
        gui.on_destroy(None)
        mock_view.cancel_threads.assert_called_once()
        self.assertTrue(mock_view.prevent_threads)
        self.assertTrue(getattr(task, "__kill"))

    def test_on_resize(self):
        gui = GUI()
        prefs.prefs[gui.window_geometry_pref] = 25, 15
        gui.window = mock.Mock()
        mock_rect = mock.Mock(width=20, height=10)
        gui.window.get_size.return_value = mock_rect
        gui.on_resize(None, None)
        self.assertEqual(prefs.prefs.get(gui.window_geometry_pref), (20, 10))

    def test_on_quit(self):
        gui = GUI()
        gui.window = mock.Mock()
        gui.on_quit(None, None)
        gui.window.destroy.assert_called_once()
