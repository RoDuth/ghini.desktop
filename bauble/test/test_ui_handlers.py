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
Presenter handler tests
"""

import os
from unittest import TestCase
from unittest import mock

from gi.repository import Gtk

from bauble.ui.handlers import ComboBoxHandler
from bauble.ui.handlers import EntryHandler
from bauble.ui.handlers import EntryWCompletionHandler
from bauble.ui.handlers import TextBufferHandler
from bauble.ui.presenter import GenericPresenter
from bauble.ui.utils import format_combo_entry_text
from bauble.ui.validators import Validator
from bauble.ui.validators import validate_non_empty


class Presenter(GenericPresenter, Gtk.Box):
    entry_handler_basic = EntryHandler()
    entry_handler_single = EntryHandler(
        [Validator(validate_non_empty, "empty")]
    )
    entry_handler_multiple = EntryHandler(
        [
            Validator(validate_non_empty, "empty"),
            Validator(
                lambda value, *args: os.path.exists(value), "invalid_path"
            ),
        ],
        lambda value, *args: os.path.abspath(value),
    )
    entry_w_completion_handler = EntryWCompletionHandler()
    combobox_handler = ComboBoxHandler()
    combobox_handler_match = ComboBoxHandler(must_match=True)
    text_buffer_handler = TextBufferHandler(
        [Validator(validate_non_empty, "empty")],
        lambda value, *_args: value.strip(),
    )

    def __init__(self):
        self.model = mock.Mock()
        super().__init__(self.model, self)
        self.entry = Gtk.Entry()
        self.combo = Gtk.ComboBox()
        self.combo_w_entry = Gtk.ComboBox().new_with_entry()
        self.combo_w_entry.connect(
            "format-entry-text",
            format_combo_entry_text,
        )
        self.text_view = Gtk.TextView()
        self.buffer = Gtk.TextBuffer()
        self.text_view.set_buffer(self.buffer)

        self.widgets_to_model_map = {
            self.entry: "value",
            self.combo: "value",
            self.combo_w_entry: "value",
            self.buffer: "value",
        }
        self.update = mock.Mock()


class HandlerTests(TestCase):

    def test_basic_entry_handler(self):
        presenter = Presenter()
        presenter.entry.set_text("foo bar baz")
        presenter.entry_handler_basic(presenter.entry)

        self.assertEqual(presenter.model.value, "foo bar baz")
        presenter.update.assert_called()

        presenter.update.reset_mock()
        presenter.entry.set_text("")
        presenter.entry_handler_basic(presenter.entry)

        self.assertEqual(presenter.model.value, "")
        presenter.update.assert_called()

        presenter.destroy()

    def test_single_entry_handler(self):
        presenter = Presenter()
        presenter.entry.set_text("foo bar baz")
        presenter.entry_handler_single(presenter.entry)

        self.assertEqual(presenter.model.value, "foo bar baz")
        presenter.update.assert_called()

        presenter.update.reset_mock()
        presenter.entry.set_text("")
        presenter.entry_handler_single(presenter.entry)

        self.assertNotEqual(presenter.model.value, "")
        self.assertEqual(len(presenter.problems), 1)
        presenter.update.assert_called()

        presenter.destroy()

    def test_multiple_entry_handler(self):
        presenter = Presenter()
        presenter.entry.set_text(".")
        presenter.entry_handler_multiple(presenter.entry)

        self.assertEqual(presenter.model.value, os.path.abspath("."))
        presenter.update.assert_called()

        presenter.update.reset_mock()
        presenter.entry.set_text("")
        presenter.entry_handler_multiple(presenter.entry)

        self.assertNotEqual(presenter.model.value, "")
        self.assertEqual(len(presenter.problems), 1)
        self.assertTrue(list(presenter.problems)[0][0].startswith("empty"))
        presenter.update.assert_called()

        presenter.update.reset_mock()
        presenter.entry.set_text("//boom\\")
        presenter.entry_handler_multiple(presenter.entry)

        self.assertNotEqual(presenter.model.value, "//boom\\")
        self.assertEqual(len(presenter.problems), 1)
        self.assertTrue(
            list(presenter.problems)[0][0].startswith("invalid_path")
        )
        presenter.update.assert_called()

        presenter.destroy()

    def test_entry_w_completion_handler(self):
        presenter = Presenter()
        list_store = Gtk.ListStore(str)
        completion = Gtk.EntryCompletion()
        completion.set_model(list_store)
        completion.set_text_column(0)
        presenter.entry.set_completion(completion)
        presenter.entry.set_text("Foo")
        values = ["Foo bar", "Foo baz", "Baz foo bar"]

        def values_getter(text):
            return [(i,) for i in values if i.startswith(text)]

        presenter.entry_w_completion_handler(
            presenter.entry,
            get_values=values_getter,
        )

        self.assertEqual(len(list_store), 2)
        self.assertCountEqual(
            [i[0] for i in list_store],
            [i[0] for i in values_getter("Foo")],
        )
        self.assertEqual(len(presenter.problems), 0)
        self.assertEqual(presenter.model.value, "Foo")

        # no match, must_match=True
        type(presenter).entry_w_completion_handler.must_match = True
        presenter.model.value = ""
        presenter.entry_w_completion_handler(
            presenter.entry,
            get_values=values_getter,
        )

        self.assertEqual(len(list_store), 2)
        self.assertCountEqual(
            [i[0] for i in list_store],
            [i[0] for i in values_getter("Foo")],
        )
        self.assertEqual(len(presenter.problems), 1)
        self.assertTrue(
            list(presenter.problems)[0][0].startswith("not_matched")
        )
        self.assertEqual(presenter.model.value, "")

        # exact match
        presenter.entry.set_text("Foo bar")
        presenter.entry_w_completion_handler(
            presenter.entry,
            get_values=values_getter,
        )

        # cleared to close the popup
        self.assertEqual(len(list_store), 0)
        self.assertEqual(len(presenter.problems), 0)
        self.assertEqual(presenter.entry.get_text(), "Foo bar")
        self.assertEqual(presenter.model.value, "Foo bar")
        presenter.update.assert_called()

        # exact match doesn't validate
        presenter.entry.set_text("Foo baz")
        with mock.patch(
            "bauble.ui.handlers.EntryWCompletionHandler.validate",
            return_value=False,
        ):
            presenter.entry_w_completion_handler(
                presenter.entry,
                get_values=values_getter,
            )
        self.assertEqual(presenter.entry.get_text(), "Foo baz")
        # doesn't set
        self.assertEqual(presenter.model.value, "Foo bar")
        presenter.update.assert_called()

        presenter.destroy()

    def test_combobox_handler(self):
        presenter = Presenter()
        model = Gtk.ListStore(str)
        model.append(["Foo"])
        model.append(["Bar"])
        model.append(["Baz"])
        presenter.combo.set_model(model)
        presenter.combo.set_active(0)
        presenter.combobox_handler(presenter.combo)

        self.assertEqual(len(presenter.problems), 0)
        self.assertEqual(presenter.model.value, "Foo")

        presenter.combo.set_active(1)
        presenter.combobox_handler(presenter.combo)

        self.assertEqual(len(presenter.problems), 0)
        self.assertEqual(presenter.model.value, "Bar")
        presenter.update.assert_called()

        presenter.destroy()

    def test_combobox_handler_matching(self):
        presenter = Presenter()
        model = Gtk.ListStore(str)
        model.append(["Foo"])
        model.append(["Bar"])
        model.append(["Baz"])
        presenter.combo_w_entry.set_model(model)
        presenter.combo_w_entry.set_active(0)
        presenter.combobox_handler_match(presenter.combo_w_entry)

        self.assertEqual(len(presenter.problems), 0)
        self.assertEqual(presenter.model.value, "Foo")

        presenter.combo_w_entry.set_active(1)
        presenter.combobox_handler_match(presenter.combo_w_entry)

        self.assertEqual(len(presenter.problems), 0)
        self.assertEqual(presenter.model.value, "Bar")
        presenter.update.assert_called()

        presenter.combo_w_entry.get_child().set_text("ham")
        presenter.combobox_handler_match(presenter.combo_w_entry)
        self.assertEqual(len(presenter.problems), 1)
        self.assertTrue(
            list(presenter.problems)[0][0].startswith("not_matched")
        )
        self.assertEqual(presenter.model.value, "Bar")

        presenter.combo_w_entry.get_child().set_text("Foo")
        presenter.combobox_handler_match(presenter.combo_w_entry)
        self.assertEqual(len(presenter.problems), 0)
        self.assertEqual(presenter.model.value, "Foo")

        presenter.destroy()

    def test_text_buffer_handler(self):
        presenter = Presenter()
        presenter.buffer.set_text(" foo bar baz ")
        presenter.text_buffer_handler(
            presenter.buffer, problem_widget=presenter.text_view
        )

        self.assertEqual(presenter.model.value, "foo bar baz")

        presenter.buffer.set_text(" ")
        presenter.text_buffer_handler(
            presenter.buffer, problem_widget=presenter.text_view
        )

        self.assertEqual(len(presenter.problems), 1)
        self.assertTrue(list(presenter.problems)[0][0].startswith("empty"))

        presenter.update.assert_called()

        presenter.destroy()
