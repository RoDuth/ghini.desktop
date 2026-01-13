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
from sqlalchemy.orm import object_mapper

from bauble import db
from bauble import utils

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

        self.class_name = class_.__name__

        self.problem_name_template = (
            f"{{}}::{self.name}::{self.class_name}::{id(instance)}"
        )

        def bound_method(widget: T, **kwargs) -> None:
            """Handler method called when the widget signal is emitted.

            :param problem_widget: if supplied the problem is attached to this
                widget instead of the one that emitted the signal.
            """
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

        for validator in self.validators:
            problem = self.problem_name_template.format(validator.problem_name)

            try:
                validator(value, field_name, instance.model)
            except ValidatorError as e:
                logger.debug("%s(%s)", type(e).__name__, str(e) or problem)
                instance.add_problem(problem, problem_widget)

                if hasattr(instance, "update"):
                    instance.update()

                return

            instance.remove_problem(problem, problem_widget)

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
            utils.message_details_dialog(
                msg,
                str(e),
                type_=Gtk.MessageType.ERROR,
            )

        if hasattr(instance, "update"):
            instance.update()


class EntryHandler(HandlerMethodDescriptor[Gtk.Entry]):
    """HandlerMethodDescriptor for Gtk.Entry widgets.

    If validation/conversion is needed provide a ValidatorConverter instance
    and a problem string as parameters.
    """

    def get_value(self, widget: Gtk.Entry) -> str:
        return widget.get_text()


class EntryWCompletionHandler(EntryHandler):
    """HandlerMethodDescriptor for Gtk.Entry widgets with completions.

    The entry must have a ``Gtk.EntryCompletion`` with model attached.

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

        super().__init__(validators, converter)

    def handler(
        self,
        instance: GenericPresenter,
        widget: Gtk.Entry,
        **kwargs: Any,
    ) -> None:
        get_values: Callable[[str], Any] = kwargs.pop("get_values")

        text = widget.get_text()
        completion = widget.get_completion()
        min_key_length = completion.get_minimum_key_length()
        completion_model = cast(Gtk.ListStore, completion.get_model())
        completion_model.clear()
        match_problem = self.problem_name_template.format("not_matched")

        if not self.must_match:
            super().handler(instance, widget, **kwargs)
        else:
            instance.add_problem(match_problem, widget)

        if len(text) > min_key_length:
            values = get_values(text)
            for value in values:
                completion_model.append([value])

            # if an exact match select it
            if len(values) == 1 and str(values[0]).lower() == text.lower():
                completion.emit(
                    "match-selected",
                    completion_model,
                    completion_model.get_iter_first(),
                )
                if self.must_match:
                    instance.remove_problem(match_problem, widget)
                    super().handler(instance, widget, **kwargs)


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


class ComboBoxHandler(HandlerMethodDescriptor[Gtk.ComboBox]):
    """HandlerMethodDescriptor for Gtk.ComboBox widgets.

    If validation or conversion is needed provide a list of ``Validator``s and
    a ``Converter`` callback as required.

    To specify which column holds the value instatiate with ``column=<int>``
    else column 0 is used.
    """

    def __init__(
        self,
        validators: Sequence[Validator] | None = None,
        converter: Converter = lambda value, *args: value,
        column: int = 0,
    ) -> None:
        self.column = column

        super().__init__(validators, converter)

    def get_value(self, widget: Gtk.ComboBox) -> Any:
        if widget.get_has_entry():
            return cast(Gtk.Entry, widget.get_child()).get_text()

        model = widget.get_model()
        iter_ = widget.get_active_iter()

        if model is None or iter_ is None:
            return None

        value = model[iter_][self.column]

        return value


def populate_enum_combo(
    combo: Gtk.ComboBox,
    model: db.Base,
    field: str,
) -> None:
    """Populate a ComboBox from a Enum Column's values.

    :param combo: a ``Gtk.ComboBox``
    :param model: an instance of ``db.Base``.
    :param field: the column name of the enum to use to populate the ComboBox.
    """
    mapper = object_mapper(model)
    values = sorted(mapper.c[field].type.values, key=lambda v: str(v or ""))
    combo_model = cast(Gtk.ListStore, combo.get_model())
    for value in values:
        combo_model.append([value])


def default_completion_cell_data_func(
    _column: Gtk.TreeViewColumn,
    renderer: Gtk.CellRenderer,
    model: Gtk.ListStore,
    treeiter: Gtk.TreeIter,
) -> None:
    """The default completion cell data function for Gtk.EntryCompletion."""
    v = model[treeiter][0]
    renderer.set_property("markup", utils.xml_safe(v))


def default_completion_match_func(
    completion: Gtk.EntryCompletion,
    key_string: str,
    treeiter: Gtk.TreeIter,
):
    """The default completion match function for Gtk.EntryCompletion.

    A case-insensitive string comparison of the the completions object in
    column 0.
    """
    value = cast(Gtk.ListStore, completion.get_model())[treeiter][0]
    return str(value).lower().startswith(key_string.lower())
