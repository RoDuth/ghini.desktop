# Copyright (c) 2025-2026 Ross Demuth <rossdemuth123@gmail.com>
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
GenericPresenter tests
"""
from types import FunctionType
from unittest import TestCase
from unittest import mock

from gi.repository import Gtk
from sqlalchemy.orm import Session

from bauble.meta import BaubleMeta
from bauble.test import BaubleTestCase
from bauble.ui.handlers import EntryHandler
from bauble.ui.presenter import EditCreateCallback
from bauble.ui.presenter import GenericPresenter
from bauble.ui.presenter import Problem
from bauble.ui.presenter import Response
from bauble.ui.utils import format_combo_entry_text
from bauble.ui.validators import Validator
from bauble.ui.validators import validate_unique

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


class BoxPresenter(GenericPresenter, Gtk.Box):
    update = mock.Mock()
    on_unique_w_empty_text_entry_changed = EntryHandler(
        [
            Validator(validate_unique, "not_unique"),
        ],
        lambda value, *_args: value.strip(),
    )

    def __init__(self, model):
        super().__init__(model, self)
        self.update.reset_mock()


class GenericPresenterTests(TestCase):
    def test_can_use_as_template_mixin(self):
        gtype = "Foo1"

        @Gtk.Template(string=template_xml.format(gtype=gtype))
        class Foo(GenericPresenter, Gtk.Box):
            # pylint: disable=not-callable

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

        presenter = BoxPresenter(mock_model)

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

        # not a widget
        presenter = BoxPresenter(mock_model)
        presenter.add_problem("TEST", mock_widget)

        self.assertEqual(presenter.problems, {("TEST", mock_widget)})
        mock_widget.get_style_context().add_class.assert_not_called()

        # a widget
        presenter.problems = set()
        mock_widget = mock.Mock(spec=Gtk.Widget)
        presenter.add_problem("TEST", mock_widget)

        self.assertEqual(presenter.problems, {("TEST", mock_widget)})
        mock_widget.get_style_context().add_class.assert_called_with("problem")

        # a combobox
        presenter.problems = set()
        mock_widget = mock.Mock(spec=Gtk.ComboBox)
        presenter.add_problem("TEST", mock_widget)
        self.assertEqual(presenter.problems, {("TEST", mock_widget)})
        mock_widget.get_style_context().add_class.assert_called_with(
            "problem-bg"
        )

    def test_remove_problem_widget_and_problem_id(self):
        mock_model = mock.Mock()

        presenter = BoxPresenter(mock_model)
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

        presenter = BoxPresenter(mock_model)
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
        calls = mock_widget3.get_style_context().remove_class.call_args_list
        call_list = [j for i in calls for j in i.args]
        self.assertIn("problem-bg", call_list)
        self.assertIn("problem", call_list)
        self.assertEqual(len(call_list), 2)
        mock_widget4.get_style_context().remove_class.assert_not_called()

    def test_remove_problem_widget_only(self):
        mock_model = mock.Mock()

        presenter = BoxPresenter(mock_model)
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
        calls = mock_widget4.get_style_context().remove_class.call_args_list
        call_list = [j for i in calls for j in i.args]
        self.assertIn("problem-bg", call_list)
        self.assertIn("problem", call_list)
        self.assertEqual(len(call_list), 4)
        self.assertEqual(len(set(call_list)), 2)

    def test_handler_method_descriptor_get(self):
        mock_model = mock.Mock()

        self.assertIsInstance(
            BoxPresenter.on_unique_w_empty_text_entry_changed,
            EntryHandler,
        )

        presenter = BoxPresenter(mock_model)

        self.assertIsInstance(
            presenter.on_unique_w_empty_text_entry_changed,
            FunctionType,
        )

    def test_on_text_entry_changed(self):
        mock_model = mock.Mock()

        presenter = BoxPresenter(mock_model)

        presenter.update.assert_not_called()

        entry = Gtk.Entry()
        presenter.widgets_to_model_map = {entry: "foo"}

        entry.set_text("test")
        presenter.on_text_entry_changed(entry)

        self.assertEqual(mock_model.foo, "test")
        presenter.update.assert_called_once()

    @mock.patch("bauble.editor.dialogs.message_details_dialog")
    def test_on_text_entry_changed_w_error_notifies(self, mock_dlog):
        mock_model = mock.MagicMock()
        type(mock_model).foo = mock.PropertyMock(
            side_effect=AttributeError("Boom")
        )

        presenter = BoxPresenter(mock_model)

        presenter.update.assert_not_called()

        entry = Gtk.Entry()
        presenter.widgets_to_model_map = {entry: "foo"}

        entry.set_text("test")
        presenter.on_text_entry_changed(entry)

        self.assertNotEqual(mock_model.foo, "test")
        msg = (
            f"<b>AttributeError setting 'foo' to 'test' "
            f"on model '{mock_model.__class__.__name__}'</b>\n\n"
        )
        mock_dlog.assert_called_once_with(
            msg, "Boom", type_=Gtk.MessageType.ERROR
        )
        self.assertEqual(
            presenter.problems,
            {
                (
                    "setting_error::on_text_entry_changed::BoxPresenter::"
                    f"{id(presenter)}",
                    entry,
                )
            },
        )

        # now if succeeds it should clear the problem
        mock_dlog.reset_mock()
        type(mock_model).foo = mock.PropertyMock(return_value="test")
        entry.set_text("test")
        presenter.on_text_entry_changed(entry)

        self.assertEqual(mock_model.foo, "test")
        self.assertEqual(presenter.problems, set())
        mock_dlog.assert_not_called()

    def test_on_non_empty_text_entry_changed(self):
        mock_model = mock.Mock()

        presenter = BoxPresenter(mock_model)
        entry = Gtk.Entry()
        presenter.widgets_to_model_map = {entry: "foo"}

        # empty
        entry.set_text("")
        presenter.on_non_empty_text_entry_changed(entry)
        self.assertNotEqual(mock_model.foo, "")
        self.assertEqual(
            presenter.problems,
            {
                (
                    "empty::on_non_empty_text_entry_changed::BoxPresenter::"
                    f"{id(presenter)}",
                    entry,
                )
            },
        )
        self.assertTrue(entry.get_style_context().has_class("problem"))

        entry.set_text("test")
        presenter.on_non_empty_text_entry_changed(entry)
        self.assertEqual(mock_model.foo, "test")
        self.assertEqual(presenter.problems, set())
        self.assertFalse(entry.get_style_context().has_class("problem"))

    def test_on_text_buffer_changed(self):
        mock_model = mock.Mock()

        presenter = BoxPresenter(mock_model)
        buffer = Gtk.TextBuffer()
        presenter.widgets_to_model_map = {buffer: "foo"}

        buffer.set_text("test")
        presenter.on_text_buffer_changed(buffer)
        self.assertEqual(mock_model.foo, "test")

    def test_on_combobox_changed_comboboxtext(self):
        mock_model = mock.Mock()

        presenter = BoxPresenter(mock_model)
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

        presenter = BoxPresenter(mock_model)
        combo = Gtk.ComboBoxText().new_with_entry()
        combo.append_text("1")
        combo.append_text("2")
        combo.append_text("3")

        presenter.widgets_to_model_map = {combo: "foo"}

        combo.set_active(1)
        presenter.on_combobox_changed(combo)
        self.assertEqual(mock_model.foo, "2")
        self.assertEqual(combo.get_child().get_text(), "2")

    def test_on_combobox_changed_combobox_wo_model(self):
        mock_model = mock.Mock()

        presenter = BoxPresenter(mock_model)
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

        presenter = BoxPresenter(mock_model)
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

        presenter = BoxPresenter(mock_model)
        model = Gtk.ListStore(str, str)
        model.append(["1", "one"])
        model.append(["2", "two"])
        model.append(["3", "three"])
        combo = Gtk.ComboBox.new_with_model_and_entry(model)
        cell = Gtk.CellRendererText()
        combo.pack_start(cell, True)
        combo.add_attribute(cell, "text", 1)
        combo.connect("format-entry-text", format_combo_entry_text)
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

        presenter = BoxPresenter(model1)
        entry = Gtk.Entry()
        presenter.widgets_to_model_map = {entry: "value"}

        # empty
        entry.set_text("")
        presenter.on_unique_text_entry_changed(entry)
        self.assertEqual(model1.value, "some_value")
        self.assertEqual(
            presenter.problems,
            {
                (
                    f"empty::on_unique_text_entry_changed::BoxPresenter::"
                    f"{id(presenter)}",
                    entry,
                )
            },
        )
        self.assertTrue(entry.get_style_context().has_class("problem"))

        # not empty but unique
        entry.set_text("test")
        presenter.on_unique_text_entry_changed(entry)
        self.assertEqual(model1.value, "test")
        self.assertEqual(presenter.problems, set())
        self.assertFalse(entry.get_style_context().has_class("problem"))

    def test_on_unique_text_entry_changed_empty_allows_empty(self):
        # need a real object for this:
        model1 = BaubleMeta(name="test_unique_entry", value="some_value")
        model2 = BaubleMeta(name="test_unique_entry2", value="unique_value")
        self.session.add(model1)
        self.session.add(model2)

        presenter = BoxPresenter(model1)
        # cheat, switch out the checker to one that allows empty
        entry = Gtk.Entry()
        presenter.widgets_to_model_map = {entry: "value"}

        # empty
        entry.set_text("")
        presenter.on_unique_w_empty_text_entry_changed(entry)
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

        presenter = BoxPresenter(model1)
        entry = Gtk.Entry()
        presenter.widgets_to_model_map = {entry: "value"}

        # not unique
        entry.set_text("unique_value")
        presenter.on_unique_text_entry_changed(entry)
        self.assertEqual(model1.value, "some_value")
        self.assertEqual(
            presenter.problems,
            {
                (
                    "not_unique::on_unique_text_entry_changed::BoxPresenter::"
                    f"{id(presenter)}",
                    entry,
                )
            },
        )
        self.assertTrue(entry.get_style_context().has_class("problem"))

    def test_on_unique_text_entry_changed_empty_is_unique(self):
        # need a real object for this:
        model1 = BaubleMeta(name="test_unique_entry", value="some_value")
        model2 = BaubleMeta(name="test_unique_entry2", value="unique_value")
        self.session.add(model1)
        self.session.add(model2)

        presenter = BoxPresenter(model1)
        entry = Gtk.Entry()
        presenter.widgets_to_model_map = {entry: "value"}

        # not empty and unique
        entry.set_text("test")
        presenter.on_non_empty_text_entry_changed(entry)
        self.assertEqual(model1.value, "test")
        self.assertEqual(presenter.problems, set())
        self.assertFalse(entry.get_style_context().has_class("problem"))


class FunctionTests(BaubleTestCase):
    def test_edit_create_callback(self):
        mock_dialog = mock.Mock()
        mock_obj_class = mock.Mock()

        callback = EditCreateCallback(mock_dialog, mock_obj_class)

        with mock.patch("bauble.ui.presenter.get_search_view") as mock_view:
            self.assertFalse(callback())
            handler = mock_dialog().connect_after.call_args.args[1]
            handler(mock_dialog, Response.OK)
            mock_view().update.assert_called_once()

        mock_obj_class.assert_called_once()
        mock_dialog.assert_called()
        self.assertEqual(
            mock_dialog.call_args_list[0].kwargs["model"],
            mock_obj_class(),
        )
        self.assertIsInstance(
            mock_dialog.call_args_list[0].kwargs["session"], Session
        )
        mock_dialog().show_all.assert_called_once()
