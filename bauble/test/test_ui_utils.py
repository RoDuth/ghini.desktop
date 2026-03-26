# pylint: disable=too-many-public-methods,no-self-use
# Copyright (c) 2005,2006,2007,2008,2009 Brett Adams <brett@belizebotanic.org>
# Copyright (c) 2012-2016 Mario Frasca <mario@anche.no>
# Copyright (c) 2018-2026 Ross Demuth <rossdemuth123@gmail.com>
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
Tests for bauble.ui.utils
"""
import os
from functools import partial
from unittest import mock

from gi.repository import Gtk
from sqlalchemy import Column
from sqlalchemy.orm.exc import DetachedInstanceError

from bauble import btypes
from bauble import db
from bauble import paths
from bauble.test import BaubleTestCase
from bauble.test import update_gui
from bauble.test import wait_on_threads
from bauble.ui import utils


class UIUtilsTests(BaubleTestCase):

    def test_search_tree_model(self):
        """
        Test bauble.utils.search_tree_model
        """
        model = Gtk.TreeStore(str)

        # the rows that should be found
        to_find = []

        row = model.append(None, ["1"])
        model.append(row, ["1.1"])
        to_find.append(model.append(row, ["something"]))
        model.append(row, ["1.3"])

        row = model.append(None, ["2"])
        to_find.append(model.append(row, ["something"]))
        model.append(row, ["2.1"])

        to_find.append(model.append(None, ["something"]))

        root = model.get_iter_first()
        results = utils.search_tree_model(model[root], "something")
        self.assertTrue(
            sorted([model.get_path(r) for r in results]), sorted(to_find)
        )

    def test_set_combo_from_value(self):
        combo = Gtk.ComboBox()
        model = Gtk.ListStore(object)
        mock1 = mock.Mock(val="1")
        mock2 = mock.Mock(val="2")
        mock3 = mock.Mock(val="3")
        model.append((mock1,))
        model.append((mock2,))
        model.append((mock3,))
        combo.set_model(model)
        utils.set_combo_from_value(combo, mock2)
        itr = combo.get_active_iter()

        self.assertIs(model[itr][0], mock2)

        utils.set_combo_from_value(combo, "3", lambda r, d: r[0].val == d)
        itr = combo.get_active_iter()

        self.assertIs(model[itr][0], mock3)

        self.assertRaises(
            ValueError,
            utils.set_combo_from_value,
            combo,
            "5",
            lambda r, d: r[0].val == d,
        )

    def test_get_widget_value_label(self):
        label = Gtk.Label(label="Foo")
        self.assertEqual(utils.get_widget_value(label), "Foo")

    def test_get_widget_value_entry(self):
        entry = Gtk.Entry()
        entry.set_text("Bar")
        self.assertEqual(utils.get_widget_value(entry), "Bar")

    def test_get_widget_value_textview(self):
        entry = Gtk.TextView()
        entry.get_buffer().set_text("Baz")
        self.assertEqual(utils.get_widget_value(entry), "Baz")

    def test_get_widget_value_comboboxtext_w_entry(self):
        combo = Gtk.ComboBoxText().new_with_entry()
        combo.append_text("foo")
        combo.append_text("baz")
        combo.get_child().set_text("bar")
        self.assertEqual(utils.get_widget_value(combo), "bar")

    def test_get_widget_value_comboboxtext_wo_entry(self):
        combo = Gtk.ComboBoxText()
        combo.append_text("foo")
        combo.append_text("bar")
        combo.append_text("baz")
        combo.set_active(1)
        self.assertEqual(utils.get_widget_value(combo), "bar")

    def test_get_widget_value_combobox_w_entry(self):
        combo = Gtk.ComboBox().new_with_entry()
        model = Gtk.ListStore(str)
        model.append(("foo",))
        model.append(("baz",))
        combo.set_model(model)
        combo.get_child().set_text("bar")
        self.assertEqual(utils.get_widget_value(combo), "bar")

    def test_get_widget_value_combobox_wo_entry(self):
        combo = Gtk.ComboBox()
        model = Gtk.ListStore(str)
        model.append(("foo",))
        model.append(("bar",))
        model.append(("baz",))
        combo.set_model(model)
        combo.set_active(1)
        self.assertEqual(utils.get_widget_value(combo), "bar")

    def test_get_widget_value_togglebutton(self):
        button = Gtk.ToggleButton().new_with_label(label="FOO")
        self.assertFalse(utils.get_widget_value(button))
        button.set_active(True)
        self.assertTrue(utils.get_widget_value(button))

    def test_get_widget_value_checkbutton(self):
        button = Gtk.CheckButton().new_with_label(label="FOO")
        self.assertFalse(utils.get_widget_value(button))
        button.set_active(True)
        self.assertTrue(utils.get_widget_value(button))

    def test_get_widget_value_radiobutton(self):
        button1 = Gtk.RadioButton.new_with_label(None, "FOO")
        button2 = Gtk.RadioButton.new_with_label_from_widget(button1, "BAR")
        self.assertFalse(utils.get_widget_value(button2))
        button2.set_active(True)
        self.assertTrue(utils.get_widget_value(button2))
        self.assertFalse(utils.get_widget_value(button1))

    def test_get_widget_value_button(self):
        button = Gtk.Button(label="BAZ")
        self.assertEqual(utils.get_widget_value(button), "BAZ")

    def test_get_widget_value_unknown_raises(self):
        self.assertRaises(TypeError, utils.get_widget_value, mock.Mock())

    def test_set_widget_value_label(self):
        label = Gtk.Label(label="Foo")
        utils.set_widget_value(label, "Bar")
        self.assertEqual(label.get_text(), "Bar")

    def test_set_widget_value_label_w_markup(self):
        label = Gtk.Label(label="Foo")
        utils.set_widget_value(label, "<b>Bar</b>", markup=True)
        self.assertEqual(label.get_text(), "Bar")
        self.assertTrue(label.get_use_markup())

    def test_set_widget_value_textview(self):
        entry = Gtk.TextView()
        buffer = entry.get_buffer()
        buffer.set_text("Baz")
        utils.set_widget_value(entry, "Bar")
        self.assertEqual(
            entry.get_buffer().get_text(*buffer.get_bounds(), False), "Bar"
        )

    def test_set_widget_value_textbuffer(self):
        buffer = Gtk.TextBuffer()
        buffer.set_text("Baz")
        utils.set_widget_value(buffer, "Bar")
        self.assertEqual(buffer.get_text(*buffer.get_bounds(), False), "Bar")

    def test_set_widget_value_spinbutton(self):
        adj = Gtk.Adjustment(
            lower=-10, upper=10, step_increment=0.1, page_increment=1
        )
        spin = Gtk.SpinButton(adjustment=adj, numeric=True)
        spin.set_value(-5)
        utils.set_widget_value(spin, 5)
        self.assertEqual(spin.get_value(), 5)

    def test_set_widget_value_entry(self):
        entry = Gtk.Entry()
        utils.set_widget_value(entry, "Bar")
        self.assertEqual(entry.get_text(), "Bar")

    def test_set_widget_value_comboboxtext_w_entry(self):
        combo = Gtk.ComboBoxText().new_with_entry()
        combo.append_text("foo")
        combo.append_text("baz")
        utils.set_widget_value(combo, "bar")
        self.assertEqual(combo.get_child().get_text(), "bar")

    def test_set_widget_value_comboboxtext_wo_entry(self):
        combo = Gtk.ComboBoxText()
        combo.append_text("foo")
        combo.append_text("bar")
        combo.append_text("baz")
        utils.set_widget_value(combo, "bar")
        self.assertEqual(combo.get_active(), 1)

    def test_set_widget_value_combobox_w_entry(self):
        combo = Gtk.ComboBox().new_with_entry()
        model = Gtk.ListStore(str)
        model.append(("foo",))
        model.append(("baz",))
        combo.set_model(model)
        utils.set_widget_value(combo, "bar")
        self.assertEqual(combo.get_child().get_text(), "bar")

    def test_set_widget_value_combobox_wo_entry(self):
        combo = Gtk.ComboBox()
        model = Gtk.ListStore(str)
        model.append(("foo",))
        model.append(("bar",))
        model.append(("baz",))
        combo.set_model(model)
        utils.set_widget_value(combo, "bar")
        self.assertEqual(combo.get_active(), 1)

    def test_set_widget_value_combobox_wo_model_logs(self):
        combo = Gtk.ComboBox()
        with self.assertLogs("bauble.ui.utils", "WARNING") as logs:
            utils.set_widget_value(combo, "bar")
        self.assertIn(
            "ui.utils.set_widget_value(): combo doesn't have a model",
            logs.output[0],
        )

    def test_set_widget_value_togglebutton(self):
        button = Gtk.ToggleButton().new_with_label(label="FOO")
        self.assertFalse(button.get_active())
        utils.set_widget_value(button, True)
        self.assertTrue(button.get_active())

    def test_set_widget_value_checkbutton(self):
        button = Gtk.CheckButton().new_with_label(label="FOO")
        self.assertFalse(button.get_active())
        utils.set_widget_value(button, True)
        self.assertTrue(button.get_active())

    def test_set_widget_value_radiobutton(self):
        button1 = Gtk.RadioButton.new_with_label(None, "FOO")
        button2 = Gtk.RadioButton.new_with_label_from_widget(button1, "BAR")
        self.assertFalse(button2.get_active())
        utils.set_widget_value(button2, True)
        self.assertTrue(button2.get_active())
        self.assertFalse(button1.get_active())

    def test_set_widget_value_button(self):
        button = Gtk.Button(label="BAZ")
        utils.set_widget_value(button, "FOO")
        self.assertEqual(button.get_label(), "FOO")

    def test_set_widget_value_unknown_raises(self):
        self.assertRaises(TypeError, utils.set_widget_value, mock.Mock())

    def test_populate_enum_combo(self):
        class Model(db.Base):
            # pylint: disable=too-few-public-methods
            __tablename__ = "test"
            value = Column(
                btypes.Enum(
                    values=["eggs", "ham", "spam", None],
                    empty_to_none=True,
                ),
                default=None,
            )

        combo = Gtk.ComboBox()
        list_store = Gtk.ListStore(str)
        combo.set_model(list_store)
        utils.populate_enum_combo(combo, Model(), "value")
        values = [i[0] for i in list_store]

        self.assertCountEqual(values, ["eggs", "ham", "spam", None])

    def test_default_completion_cell_data_func_strings(self):
        list_store = Gtk.ListStore(str)
        list_store.append(["<Test>"])
        mock_renderer = mock.MagicMock()

        utils.default_completion_cell_data_func(
            None, mock_renderer, list_store, 0
        )
        mock_renderer.set_property.assert_called_once_with("text", "<Test>")

    def test_default_completion_cell_data_func_objects(self):
        mock_obj = mock.MagicMock()
        mock_obj.__str__.return_value = "<Test>"
        list_store = Gtk.ListStore(object)
        list_store.append([mock_obj])
        mock_renderer = mock.MagicMock()

        utils.default_completion_cell_data_func(
            None, mock_renderer, list_store, 0
        )
        mock_renderer.set_property.assert_called_once_with("text", "<Test>")

    def test_default_completion_cell_data_func_detached_instance(self):
        mock_obj = mock.MagicMock()
        mock_obj.__str__.side_effect = DetachedInstanceError
        list_store = Gtk.ListStore(object)
        list_store.append([mock_obj])
        mock_renderer = mock.MagicMock()

        with self.assertLogs("bauble.ui.utils", level="DEBUG") as logs:
            utils.default_completion_cell_data_func(
                None,
                mock_renderer,
                list_store,
                0,
            )
        self.assertIn("DetachedInstanceError", logs.output[0])
        mock_renderer.set_property.assert_called_once_with("text", "")

    def test_default_completion_match_func(self):
        mock_obj = mock.MagicMock()
        mock_obj.__str__.return_value = "Testing"
        list_store = Gtk.ListStore(object)
        list_store.append([mock_obj])
        completion = Gtk.EntryCompletion(model=list_store)

        self.assertTrue(
            utils.default_completion_match_func(completion, "Tes", 0)
        )
        self.assertFalse(
            utils.default_completion_match_func(completion, "Foo", 0)
        )

    def test_format_combo_entry_text(self):
        mock_obj = mock.MagicMock()
        mock_obj.__str__.return_value = "Test"
        liststore = Gtk.ListStore(object)
        liststore.append([None])
        liststore.append([mock_obj])
        combo = Gtk.ComboBox.new_with_model(liststore)
        self.assertEqual(utils.format_combo_entry_text(combo, 0), "")
        self.assertEqual(utils.format_combo_entry_text(combo, 1), "Test")


class ImageLoaderTests(BaubleTestCase):
    def setUp(self):
        super().setUp()
        utils.ImageLoader.cache.storage.clear()

    def test_image_loader_local_url(self):
        path = os.path.join(paths.lib_dir(), "images", "bauble_logo.png")
        img = Gtk.Image()
        self.assertIsNone(img.get_pixbuf())
        pic_box = Gtk.Box()
        pic_box.add(img)
        # needs a window for size-allocate signal
        win = Gtk.Window(title="test_window")
        win.add(pic_box)
        win.show_all()
        mock_size_alloc = mock.Mock()
        mock_size_alloc.return_value = False
        utils.ImageLoader(
            pic_box,
            path,
            on_size_allocated=mock_size_alloc,
        ).start()
        mock_size_alloc.assert_not_called()
        wait_on_threads()
        update_gui()
        image = pic_box.get_children()[0]

        self.assertIsInstance(image, Gtk.Image)
        self.assertIsNotNone(image.get_pixbuf())
        # does reuse existing
        self.assertIs(image, img)

        while not mock_size_alloc.called:
            # WARNING this could deadlock if the signal hanlder doesn't call
            # but is required for the nested idle_add
            update_gui()
        # kind of redundant
        mock_size_alloc.assert_called()

        self.assertIsInstance(mock_size_alloc.call_args.args[0], Gtk.Image)
        # does reuse existing
        self.assertIs(mock_size_alloc.call_args.args[0], img)

        win.destroy()

    @mock.patch("bauble.ui.utils.get_net_sess")
    def test_image_loader_global_url(self, mock_get_sess):
        mock_resp = mock.Mock()
        from pathlib import Path

        path = Path(paths.lib_dir(), "images", "bauble_logo.png")
        with path.open("rb") as f:
            img = f.read()
        # path = os.path.join(paths.lib_dir(), "images", "bauble_logo.png")
        # with open(path, "rb") as f:
        #     img = f.read()
        mock_resp.content = img
        mock_get_sess().get.return_value = mock_resp
        pic_box = Gtk.Box()
        # needs a window for size-allocate signal
        win = Gtk.Window(title="test_window")
        win.add(pic_box)
        win.show_all()
        mock_size_alloc = mock.Mock()
        mock_size_alloc.return_value = False
        utils.ImageLoader(
            pic_box,
            "https://test.org",
            on_size_allocated=mock_size_alloc,
        ).start()
        mock_size_alloc.assert_not_called()
        wait_on_threads()
        update_gui()
        self.assertIsInstance(pic_box.get_children()[0], Gtk.Image)
        while not mock_size_alloc.called:
            # WARNING this could deadlock if the signal hanlder doesn't call
            # but is required for the nested idle_add
            update_gui()
        # kind of redundant
        mock_size_alloc.assert_called()
        self.assertIsInstance(mock_size_alloc.call_args.args[0], Gtk.Image)
        win.destroy()

    @mock.patch("bauble.ui.utils.get_net_sess")
    def test_image_loader_global_url_fails_to_retrieve(self, mock_get_sess):
        # failure to retrieve
        mock_get_sess().get.side_effect = Exception
        pic_box = Gtk.Box()
        # needs a window for size-allocate signal
        win = Gtk.Window(title="test_window")
        win.add(pic_box)
        win.show_all()
        mock_size_alloc = mock.Mock()
        mock_size_alloc.return_value = False
        utils.ImageLoader(
            pic_box,
            "https://test.org",
            on_size_allocated=mock_size_alloc,
        ).start()
        mock_size_alloc.assert_not_called()
        wait_on_threads()
        update_gui()
        self.assertIsInstance(pic_box.get_children()[0], Gtk.Label)
        while not mock_size_alloc.called:
            # WARNING this could deadlock if the signal hanlder doesn't call
            # but is required for the nested idle_add
            update_gui()
        # kind of redundant
        mock_size_alloc.assert_called()
        self.assertIsInstance(mock_size_alloc.call_args.args[0], Gtk.Label)
        win.destroy()

    def test_image_loader_base64_url(self):
        path = (
            "|data:image/jpeg;base64,R0lGODlhAQABAIAAAP///"
            "wAAACH5BAEAAAAALAAAAAABAAEAAAICRAEAOw=="
        )
        pic_box = Gtk.Box()
        # needs a window for size-allocate signal
        win = Gtk.Window(title="test_window")
        win.add(pic_box)
        win.show_all()
        mock_size_alloc = mock.Mock()
        mock_size_alloc.return_value = False
        utils.ImageLoader(
            pic_box,
            path,
            on_size_allocated=mock_size_alloc,
        ).start()
        mock_size_alloc.assert_not_called()
        wait_on_threads()
        update_gui()
        image = pic_box.get_children()[0]
        self.assertIsInstance(image, Gtk.Image)
        while not mock_size_alloc.called:
            # WARNING this could deadlock if the signal hanlder doesn't call
            # but is required for the nested idle_add
            update_gui()
        # kind of redundant
        mock_size_alloc.assert_called()
        self.assertIsInstance(mock_size_alloc.call_args.args[0], Gtk.Image)
        win.destroy()

    def test_image_loader_glib_error(self):
        pic_box = Gtk.Box()
        # needs a window for size-allocate signal
        win = Gtk.Window(title="test_window")
        win.add(pic_box)
        win.show_all()
        mock_size_alloc = mock.Mock()
        mock_size_alloc.return_value = False
        utils.ImageLoader(
            pic_box,
            "junk_data",
            on_size_allocated=mock_size_alloc,
        ).start()
        mock_size_alloc.assert_not_called()
        wait_on_threads()
        while not mock_size_alloc.called:
            # WARNING this could deadlock if the signal hanlder doesn't call
            # but is required for the nested idle_add
            update_gui()
        self.assertIsInstance(pic_box.get_children()[0], Gtk.Label)
        mock_size_alloc.assert_called()
        self.assertIsInstance(mock_size_alloc.call_args.args[0], Gtk.Label)
        win.destroy()

    def test_image_loader_exception(self):
        # exactly the same test as test_image_loader_local_url except for
        # raising an Exception
        path = os.path.join(paths.lib_dir(), "images", "bauble_logo.png")
        pic_box = Gtk.Box()
        # needs a window for size-allocate signal
        win = Gtk.Window(title="test_window")
        win.add(pic_box)
        win.show_all()
        mock_size_alloc = mock.Mock()
        mock_size_alloc.return_value = False
        mock_loader = mock.Mock()
        img_loader = utils.ImageLoader(
            pic_box,
            path,
            on_size_allocated=mock_size_alloc,
            loader=mock_loader,
        )
        mock_loader.close.side_effect = Exception
        img_loader.loader = mock_loader
        img_loader.start()
        mock_size_alloc.assert_not_called()
        wait_on_threads()
        while not mock_size_alloc.called:
            # WARNING this could deadlock if the signal hanlder doesn't call
            # but is required for the nested idle_add
            update_gui()
        self.assertIsInstance(pic_box.get_children()[0], Gtk.Label)
        mock_size_alloc.assert_called()
        self.assertIsInstance(mock_size_alloc.call_args.args[0], Gtk.Label)
        win.destroy()

    def test_image_cache_create_store_retrieve(self):
        invoked = []

        def getter(x):
            invoked.append(x)
            return x

        cache = utils.ImageCache(2)
        v = cache.get(1, partial(getter, 1))
        self.assertEqual(v, 1)
        self.assertEqual(invoked, [1])
        v = cache.get(1, partial(getter, 1))
        self.assertEqual(v, 1)
        self.assertEqual(invoked, [1])

    def test_image_cache_respects_size(self):
        invoked = []

        def getter(x):
            invoked.append(x)
            return x

        cache = utils.ImageCache(2)
        cache.get(1, partial(getter, 1))
        cache.get(2, partial(getter, 2))
        cache.get(3, partial(getter, 3))
        cache.get(4, partial(getter, 4))
        self.assertEqual(invoked, [1, 2, 3, 4])
        self.assertEqual(sorted(cache.storage.keys()), [3, 4])

    def test_image_cache_respects_timing(self):
        invoked = []

        def getter(x):
            invoked.append(x)
            return x

        cache = utils.ImageCache(2)
        from time import sleep

        cache.get(1, partial(getter, 1))
        sleep(0.01)
        cache.get(2, partial(getter, 2))
        sleep(0.01)
        cache.get(1, partial(getter, 1))
        sleep(0.01)
        cache.get(3, partial(getter, 3))
        sleep(0.01)
        cache.get(1, partial(getter, 1))
        sleep(0.01)
        cache.get(4, partial(getter, 4))
        self.assertEqual(invoked, [1, 2, 3, 4])
        self.assertEqual(sorted(cache.storage.keys()), [1, 4])
