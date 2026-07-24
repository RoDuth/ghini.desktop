# Copyright 2026 Ross Demuth <rossdemuth123@gmail.com>
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
Generic widget signal handlers.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

from abc import ABC
from abc import abstractmethod
from collections.abc import Sequence
from typing import TYPE_CHECKING
from typing import Any
from typing import Callable
from typing import Protocol
from typing import Self
from typing import cast
from typing import overload

from gi.repository import GObject
from gi.repository import Gtk

from . import dialogs
from .utils import combo_get_value_iter
from .validators import Validator
from .validators import ValidatorError

if TYPE_CHECKING:
    from .presenter import GenericPresenter


class Converter(Protocol):
    # pylint: disable=too-few-public-methods
    def __call__(self, value: Any, *args: Any) -> Any: ...


class BoundMethod[T](Protocol):
    # pylint: disable=too-few-public-methods
    def __call__(self, widget: T, **kwargs: Any) -> None: ...


class HandlerMethodDescriptor[T: GObject.Object](ABC):
    """Descriptor for handler methods that get and validate data from widgets.

    When the handler method is called it gets the value from the widget,
    validates it and optionally adjusts it.  If validation fails the problem is
    registered with the presenter.  If not, the value is set on the model, any
    existing problem is removed and, if the presenter has an ``update()``,
    method it is called.

    Intended to be used as class attributes in ``GenericPresenter`` subclasses
    to allow constructing the user interface signal handlers declaratively.

    :param validators: an sequence of ``Validator``s or None. If None no
        validation occurs.
    :param converter: a ``Converter`` callback or None. If None no conversion
        is performed.
    """

    def __init__(
        self,
        validators: Sequence[Validator] | None = None,
        converter: Converter | None = None,
    ) -> None:
        validators = validators or []
        self.validators = validators
        self.converter = converter
        self.problem_name_template: str
        # generic problem used internally by classes that implement must_match
        self.match_problem: str
        self.name = ""
        self.class_name = ""

    def __set_name__(self, _owner, name: str) -> None:
        self.name = name

    @overload
    def __get__(
        self,
        instance: GenericPresenter,
        class_: type[GenericPresenter],
    ) -> BoundMethod[T]: ...

    @overload
    def __get__(
        self,
        instance: None,
        class_: type[GenericPresenter],
    ) -> Self: ...

    def __get__(
        self,
        instance: GenericPresenter | None,
        class_: type[GenericPresenter],
    ) -> BoundMethod[T] | Self:

        if instance is None:
            # allow access to the descriptor itself via the class
            return self

        def bound_method(widget: T, **kwargs) -> None:
            """Handler method called when the widget signal is emitted.

            :param problem_widget: if supplied the problem is attached to this
                widget instead of the one that emitted the signal.
            """

            self.class_name = class_.__name__

            self.problem_name_template = (
                f"{{}}::{self.name}::{self.class_name}::{id(instance)}"
            )

            self.match_problem = self.problem_name_template.format(
                "not_matched"
            )

            return self.handler(instance, widget, **kwargs)

        return bound_method

    @abstractmethod
    def get_value(self, widget: T) -> Any: ...

    def handler(
        self,
        instance: GenericPresenter,
        widget: T,
        **kwargs: Any,
    ) -> None:
        value = self.get_value(widget)
        field_name = instance.widgets_to_model_map[widget]

        current = getattr(instance.model, field_name)

        logger.debug(
            "%s.%s(%s) called for field %s - values: %s -> %s",
            self.class_name,
            self.name,
            widget,
            field_name,
            current,
            value,
        )

        problem_widget = kwargs.get("problem_widget", widget)

        if not self.validate(instance, problem_widget, field_name, value):
            return

        self.set_model_value(instance, problem_widget, field_name, value)

        if hasattr(instance, "update"):
            instance.update()

    def match_handler(
        self,
        instance: GenericPresenter,
        widget: T,
        **kwargs: Any,
    ) -> None:
        """Only adds ``match_problem`` to the widget and logs.

        Subclasses that implement ``must_match=True`` can override ``handler``
        to run this instead where required (i.e. where setting the problem and
        logging is all thats needed).  These subclasses should remove
        ``match_problem`` later where appropriate.
        """
        # logger here as self.handler() is not called
        field_name = instance.widgets_to_model_map[widget]
        current = getattr(instance.model, field_name)
        logger.debug(
            "%s.%s(%s) called for field %s - values: %s >> %s",
            self.class_name,
            self.name,
            widget,
            field_name,
            current,
            self.get_value(widget),
        )

        problem_widget = kwargs.get("problem_widget", widget)
        instance.add_problem(self.match_problem, problem_widget)

        if hasattr(instance, "update"):
            instance.update()

    def validate(
        self,
        instance: GenericPresenter,
        problem_widget: Gtk.Widget,
        field_name: str,
        value: Any,
    ) -> bool:

        for validator in self.validators:
            problem = self.problem_name_template.format(validator.problem_name)

            try:
                validator(value, field_name, instance.model)
            except ValidatorError as e:
                logger.debug("%s(%s)", type(e).__name__, str(e) or problem)
                instance.add_problem(problem, problem_widget)

                if hasattr(instance, "update"):
                    instance.update()

                return False

            instance.remove_problem(problem, problem_widget)

        return True

    def set_model_value(
        self,
        instance: GenericPresenter,
        problem_widget: Gtk.Widget,
        field_name: str,
        value: Any,
    ) -> None:
        # setting
        setting_problem = self.problem_name_template.format("setting_error")
        instance.remove_problem(setting_problem, problem_widget)

        try:
            if instance.model and field_name:
                if self.converter:
                    value = self.converter(value, field_name, instance.model)

                setattr(instance.model, field_name, value)
        except Exception as e:  # pylint: disable=broad-except
            logger.warning(
                "Error setting %s.%s to %s: %s",
                instance.model.__class__.__name__,
                field_name,
                value,
                e,
            )

            instance.add_problem(setting_problem, problem_widget)

            model_name = instance.model.__class__.__name__
            msg = (
                f"<b>{type(e).__name__} setting '{field_name}' to "
                f"'{value}' on model '{model_name}'</b>\n\n"
            )
            dialogs.message_details_dialog(
                msg,
                str(e),
                type_=Gtk.MessageType.ERROR,
            )


class EntryHandler(HandlerMethodDescriptor[Gtk.Entry]):
    """HandlerMethodDescriptor for Gtk.Entry widgets.

    If validation or conversion is needed provide a list of ``Validator``s and
    a ``Converter`` callback as required.
    """

    def get_value(self, widget: Gtk.Entry) -> str:
        return widget.get_text()


class EntryWCompletionHandler(EntryHandler):
    """HandlerMethodDescriptor for Gtk.Entry widgets with completions.

    The entry must have a ``Gtk.EntryCompletion`` with model attached.

    If the completion model handles non-string values set ``must_match=True``.

    To work for both string or object values the default "match-selected"
    behaviour is overriden to update the entry widget with the string of the
    object and set the model's value to the object.

    If validation or conversion is needed provide a list of ``Validator``s and
    a ``Converter`` callback as required.

    ``get_values`` kwarg must be supplied, along with the Entry widget, to the
    handler as a callable that returns completions given a string to match.

    If the entry must match one of the completions instanciate with
    ``must_match=True``
    """

    def __init__(
        self,
        validators: Sequence[Validator] | None = None,
        converter: Converter = lambda value, *args: value,
        must_match: bool = False,
    ) -> None:

        self.must_match = must_match
        self.connected: list[int] = []

        super().__init__(validators, converter)

    def handler(
        self,
        instance: GenericPresenter,
        widget: Gtk.Entry,
        **kwargs: Any,
    ) -> None:
        get_values: Callable[[str], Any] = kwargs.pop("get_values")
        problem_widget = kwargs.get("problem_widget", widget)

        text = widget.get_text()

        completion = widget.get_completion()
        min_key_length = completion.get_minimum_key_length()
        completion_model = cast(Gtk.ListStore, completion.get_model())
        completion_model.clear()

        completion_id = id(completion)

        def on_match_selected(
            _completion: Gtk.EntryCompletion,
            liststore: Gtk.ListStore,
            tree_iter: Gtk.TreeIter,
        ) -> bool:
            """Overrides default behaviour as can not set_text to an object.

            This handler runs last.
            """
            field_name = instance.widgets_to_model_map[widget]
            obj = liststore[tree_iter][0]
            widget.set_text(str(obj))
            instance.remove_problem(self.match_problem, problem_widget)

            if not self.validate(instance, problem_widget, field_name, obj):
                return True

            self.set_model_value(instance, problem_widget, field_name, obj)

            if hasattr(instance, "update"):
                instance.update()

            return True

        if completion_id not in self.connected:
            # connect once, on first run
            # (several widgets can use the same handler)
            completion.connect(
                "match-selected",
                on_match_selected,
            )
            self.connected.append(completion_id)

        if self.must_match:
            # just log and mark the problem
            super().match_handler(instance, widget, **kwargs)
        else:
            super().handler(instance, widget, **kwargs)

        if len(text) < min_key_length:
            return

        values = get_values(text)
        for value in values:
            completion_model.append(value)

        # if an exact match select it
        if len(values) == 1 and str(values[0][0]).lower() == text.lower():
            completion.emit(
                "match-selected",
                completion_model,
                completion_model.get_iter_first(),
            )
            # force the popup to close
            completion_model.clear()


class TextBufferHandler(HandlerMethodDescriptor[Gtk.TextBuffer]):
    """HandlerMethodDescriptor for Gtk.TextBuffer widgets.

    If validation or conversion is needed provide a list of ``Validator``s and
    a ``Converter`` callback as required.

    ``problem_widget`` kwarg, set to the associated TextView, should be
    supplied to the handler, along with the TextBuffer widget, to display
    problems correctly.
    """

    def get_value(self, widget: Gtk.TextBuffer) -> str:
        return widget.get_text(*widget.get_bounds(), False)


class NOTFOUND:  # pylint: disable=all
    # sentinal value for logging etc. purely for a better repr, use the class,
    # don't instanciate
    # in python 3.15 we will have: `NOTFOUND = sentinal("NOTFOUND")`
    pass


class ComboBoxHandler(HandlerMethodDescriptor[Gtk.ComboBox]):
    """HandlerMethodDescriptor for Gtk.ComboBox widgets.

    If the model handles non-string values set ``must_match=True``.

    If the combobox also has an entry with a ``Gtk.EntryCompletion`` then, to
    make it work for both string or object values the default "match-selected"
    behaviour is overriden to update the entry widget with the string of the
    object and set the model's value to the object.

    If validation or conversion is needed provide a list of ``Validator``s and
    a ``Converter`` callback as required.

    To specify which column holds the value instatiate with ``column=<int>``
    else column 0 is used.

    If the combo has an entry that must match one of the model values
    instanciate with ``must_match=True``
    """

    def __init__(
        self,
        validators: Sequence[Validator] | None = None,
        converter: Converter = lambda value, *args: value,
        column: int = 0,
        must_match: bool = False,
    ) -> None:
        self.column = column
        self.must_match = must_match
        self.connected: list[int] = []

        super().__init__(validators, converter)

    def get_value(self, widget: Gtk.ComboBox) -> Any:
        model = widget.get_model()
        iter_ = widget.get_active_iter()

        if not iter_ and widget.get_has_entry():
            text = cast(Gtk.Entry, widget.get_child()).get_text()
            iter_ = combo_get_value_iter(
                widget,
                text,
                cmp=lambda row, val: str(row[0]) == val,
            )

            if not iter_:
                return NOTFOUND if self.must_match else text

        if model is None or iter_ is None:
            return None

        value = model[iter_][self.column]

        return value

    def handler(
        self,
        instance: GenericPresenter,
        widget: Gtk.ComboBox,
        **kwargs: Any,
    ) -> None:
        problem_widget: Gtk.Widget = widget
        completion_id = 0
        entry: Gtk.Entry | None = None

        if widget.get_has_entry():
            entry = cast(Gtk.Entry, widget.get_child())
            problem_widget = entry

            completion = problem_widget.get_completion()
            if completion:
                completion_id = id(completion)

        def on_match_selected(
            _completion: Gtk.EntryCompletion,
            liststore: Gtk.ListStore,
            tree_iter: Gtk.TreeIter,
        ) -> bool:
            """Overrides default behaviour as can not set_text to an object.

            This handler runs last.
            """
            field_name = instance.widgets_to_model_map[widget]
            obj = liststore[tree_iter][self.column]

            if entry:
                entry.set_text(str(obj))

            instance.remove_problem(self.match_problem, problem_widget)

            if not self.validate(instance, problem_widget, field_name, obj):
                return True

            self.set_model_value(instance, problem_widget, field_name, obj)

            if hasattr(instance, "update"):
                instance.update()

            return True

        if completion_id and completion_id not in self.connected:
            # connect once, on first run
            # (several widgets can use the same handler)
            self.connected.append(completion_id)
            completion.connect(
                "match-selected",
                on_match_selected,
            )

        if self.must_match and self.get_value(widget) is NOTFOUND:
            # just log and mark the problem
            super().match_handler(
                instance,
                widget,
                problem_widget=problem_widget,
                **kwargs,
            )
        else:
            instance.remove_problem(self.match_problem, problem_widget)
            super().handler(instance, widget, **kwargs)


class ToggleButtonHandler(HandlerMethodDescriptor[Gtk.ToggleButton]):
    """HandlerMethodDescriptor for Gtk.ToggleButton and related widgets.

    If validation or conversion is needed provide a list of ``Validator``s and
    a ``Converter`` callback as required.
    """

    def get_value(self, widget: Gtk.ToggleButton) -> bool:
        return widget.get_active()
