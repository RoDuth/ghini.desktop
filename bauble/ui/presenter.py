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
Generic presenter, callbacks, etc..
"""
import logging
import traceback

logger = logging.getLogger(__name__)

import gc
from collections.abc import Callable
from collections.abc import Sequence
from enum import IntEnum
from typing import TYPE_CHECKING
from typing import Protocol
from typing import Self

from gi.repository import GLib
from gi.repository import GObject
from gi.repository import Gtk
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

import bauble
from bauble import db
from bauble.i18n import _
from bauble.utils import xml_safe

from . import dialogs
from . import utils
from .handlers import ComboBoxHandler
from .handlers import EntryHandler
from .handlers import TextBufferHandler
from .validators import Validator
from .validators import validate_non_empty
from .validators import validate_unique


class Problem:  # pylint: disable=too-few-public-methods
    """Problem descriptor.

    Intended to be used as a class attribute in ``GenericPresenter`` subclasses
    when creating custom handlers.  The same functionaility is provided in
    ``HandlerMethodDescriptor`` so this is not required in that case.

    Provides a string that states the problem_type, class and the instance
    identifier. Makes logs entries easier to follow.
    """

    __slots__: tuple[str, ...] = ("problem_type",)

    def __init__(self, problem_type: str) -> None:
        self.problem_type = problem_type

    def __get__[T](self, instance: T, class_: type[T]) -> str:
        return f"{self.problem_type}::{class_.__name__}::{id(instance)}"


class GenericPresenter[T]:
    """A presenter with a model that can be used with a Gtk.Template decorated
    class as the view.

    Can be used either as a mixin on the ``Gtk.Template`` class itself or
    inherited from to create a more conventional MVP style (composition).

    NOTE: The handlers provided here are the common ones, more can be defined
    as needed.  Either by using the ``HandlerMethodDescriptor`` base class or
    by defining custom handler methods directly (and possibly providing
    ``Problem`` descriptors when needed).

    Example as a Mixin::

        @Gtk.Template(filename="/path/to/file.ui"))
        class Foo(GenericPresenter[FooModel], Gtk.Dialog):

            __gtype_name__ = "Foo"
            # include if wanting to connect to the 'problems-changed' signal
            __gsignals__ = GenericPresenter.gsignals

            bar = cast(Gtk.Entry, Gtk.Template.Child())
            baz = cast(Gtk.Entry, Gtk.Template.Child())
            qux = cast(Gtk.Entry, Gtk.Template.Child())

            PROBLEM_NOT_BAZ = Problem("not_baz")

            # custom HandlerMethodDescriptor example
            on_valid_path_entry_changed = EntryHandler(
                [
                    Validator(validate_non_empty, "empty"),
                    Validator(
                        lambda value, *args: os.path.exists(value),
                        "invalid_path",
                    )
                ],
                lambda value, *args: os.path.abspath(value),
            )

            def __init__(self, model: FooModel) -> None:
                super().__init__(model, self)
                # connect can go here or in .ui file with handler methods
                self.qux.connect('changed', self.on_valid_path_entry_changed)
                # connect to problems-changed signal
                self.connect('problems-changed', self.on_problems_changed)

            # signal handlers defined in the .ui file
            @Gtk.Template.Callback()
            def on_text_entry_changed(self, entry: Gtk.Entry) -> None:
                super().on_text_entry_changed(entry)

            @Gtk.Template.Callback()
            def on_baz_entry_changed(self, entry: Gtk.Entry) -> None:
                # custom handler example
                value = entry.get_text()
                field_name = self.widgets_to_model_map[entry]

                if value != "baz":
                    self.add_problem(self.PROBLEM_NOT_BAZ, entry)
                else:
                    self.remove_problem(self.PROBLEM_NOT_BAZ, entry,)

                setattr(self.model, field_name, value)
                # Optionally call update if needed
                # self.update()

            def on_problems_changed(
                self, _foo: Self,  has_problems: bool
            ) -> None:
                self.ok_button.set_sensitive(not has_problems)

        model = FooModel()
        presenter = Foo(model)

    Example as a separate presenter classes::

        @Gtk.Template(filename="/path/to/file.ui"))
        class FooView(Gtk.Dialog):

            __gtype_name__ = "Foo"

            bar = cast(Gtk.Entry, Gtk.Template.Child())


        class FooPresenter(GenericPresenter[FooModel]):
            def __init__(
                    self, model: FooModel, view: FooView
            ) -> None:
                self.view: FooView
                super().__init__(model, view)

                view.bar.connect("changed", self.on_text_entry_changed)

            def on_text_entry_changed(self, entry: Gtk.Entry) -> None:
                super().on_text_entry_changed(entry)

        model = FooModel()
        view = FooView()
        presenter = FooPresenter(model, view)
    """

    # to use explictily include this: e.g.:
    # __gsignals__ = GenericPresenter.gsignals
    gsignals: dict = {
        "problems-changed": (GObject.SignalFlags.RUN_FIRST, None, (bool,))
    }

    # *** handler method descriptors ***
    #
    # PROVIDED ARE COMMON HANDLERS FOR USE IN SUBCLASSES,
    # more can be defined as needed
    #

    on_text_entry_changed = EntryHandler(
        converter=lambda value, *_args: value.strip() or None
    )

    on_non_empty_text_entry_changed = EntryHandler(
        [Validator(validate_non_empty, "empty")],
        lambda value, *_args: value.strip(),
    )

    on_unique_text_entry_changed = EntryHandler(
        [
            Validator(validate_non_empty, "empty"),
            Validator(validate_unique, "not_unique"),
        ],
        lambda value, *_args: value.strip() or None,
    )

    on_text_buffer_changed = TextBufferHandler(
        converter=lambda value, *_args: value.strip() or None,
    )

    on_non_empty_text_buffer_changed = TextBufferHandler(
        [Validator(validate_non_empty, "empty")],
        lambda value, *_args: value.strip(),
    )

    on_combobox_changed = ComboBoxHandler()

    def __init__(
        self,
        model: T,
        view: Self | Gtk.Widget,
        *args,
        **kwargs,
    ) -> None:

        logger.debug("%s.__init__", type(self).__name__)
        self.widgets_to_model_map: dict[GObject.Object, str]
        self.problems: set[tuple[str, Gtk.Widget]] = set()

        self.model = model
        self.view = view
        # check this class has implimented gsignals
        signal_list = []
        try:
            signal_list = GObject.signal_list_names(type(view))
        except AttributeError as e:
            logger.debug("%s(%s)", type(e).__name__, e)

        self.emits_problems_changed = "problems-changed" in signal_list
        # Incase of use as a Gtk.Template mixin call the widgets init
        super().__init__(*args, **kwargs)

        if hasattr(view, "connect"):
            view.connect("destroy", idle_garbage_collect)

    def refresh_all_widgets_from_model(self) -> None:
        for widget, field in self.widgets_to_model_map.items():
            value = getattr(self.model, field)
            utils.set_widget_value(widget, value)

    def add_problem(
        self,
        problem_id: str,
        widget: Gtk.Widget,
    ) -> None:
        """Add problem_id to self.problems and change widgets background.

        :param problem_id: A unique identifier for the problem.
        :param widget: the widget whose background color should change to
            indicate a problem
        """
        start = bool(self.problems)

        self.problems.add((problem_id, widget))

        if isinstance(widget, Gtk.ComboBox):
            widget.get_style_context().add_class("problem-bg")
        elif isinstance(widget, Gtk.Widget):
            widget.get_style_context().add_class("problem")

        logger.debug("problems now: %s", self.problems)

        if not self.emits_problems_changed:
            return

        if hasattr(self.view, "emit") and start != bool(self.problems):
            self.view.emit("problems-changed", True)

    def remove_problem(
        self,
        problem_id: str | None = None,
        widget: Gtk.Widget | None = None,
    ) -> None:
        """Remove problem from self.problems and reset the widgets background.

        If widget is None remove problem_id for all widgets.
        If problem_id is None remove all problem ids for widget.
        If not matching problem exists nothing happens.

        :param problem_id: A unique id for the problem.
        :param widget: the problem widget
        """
        start = bool(self.problems)

        for prob, widg in self.problems.copy():
            # pylint: disable=too-many-boolean-expressions
            if (
                (widg == widget and prob == problem_id)
                or (widget is None and prob == problem_id)
                or (widg == widget and problem_id is None)
            ):
                self.problems.remove((prob, widg))
                if isinstance(widg, Gtk.Widget) and not self.has_problem(widg):
                    widg.get_style_context().remove_class("problem")
                    widg.get_style_context().remove_class("problem-bg")

        logger.debug("problems now: %s", self.problems)

        if not self.emits_problems_changed:
            return

        if hasattr(self.view, "emit") and start != bool(self.problems):
            self.view.emit("problems-changed", False)

    def has_problem(self, widget: Gtk.Widget) -> bool:
        """Is the widget in problems."""
        for __, w in self.problems:
            if w is widget:
                return True
        return False


def idle_garbage_collect(*_args, **_kwargs) -> None:
    """Convenience function to call ``GLib.idle_add(gc.collect)`` when required
    to ensure dialogs, etc. are collected after destroy.
    """

    GLib.idle_add(gc.collect)


def default_dialog_update(dialog: Gtk.Dialog, state: bool) -> None:
    """Default update action for dialogs that have Add, Next, OK, Cancel,
    buttons.

    Sets the sensitivity of the committing buttons to the provided state.  If
    the editor has Problems or the Model is otherwise in a state not ready for
    committing :param state: should be False.
    """
    for response in Response:
        if response == Response.CANCEL:
            continue

        widget = dialog.get_widget_for_response(response.value)
        if widget:
            widget.set_sensitive(state)


class Response(IntEnum):
    ADD = 11
    NEXT = 22
    OK = -5
    CANCEL = -6
    SAVE = 33
    RETURN = 44


if TYPE_CHECKING:

    class _Dialog[T](GenericPresenter[T], Gtk.Dialog):
        pass

else:
    _Dialog = GenericPresenter


class DomainEditorDialog[T: db.Domain](_Dialog[T]):
    """Editor dialogs base class for dialogs used in the insert menu, etc..

    i.e. As required by ``AddCallback`` and ``EditCreateCallback``.
    Use as a mixin for a ``Gtk.Template`` decorated ``Gtk.Dialog`` class.

    A subclass of GenericPresenter that expects a ``db.Domain`` model and must
    be used as a mixin on a ``Gtk.Dialog`` subclass.
    """

    revealer: Gtk.Revealer

    def __init__(
        self,
        model: T,
        session: Session,
        transient_for: Gtk.Window | None = None,
    ) -> None:
        self.session = session

        if model not in self.session:
            model = self.session.merge(model)

        if bauble.gui and not transient_for:
            transient_for = bauble.gui.window

        super().__init__(model, self, transient_for=transient_for)

    @property
    def can_commit(self) -> bool:
        raise NotImplementedError

    def run(self) -> Response:
        # pylint: disable=no-member
        for response in Response:
            if response in [Response.OK, Response.CANCEL]:
                continue

            widget = self.get_widget_for_response(response.value)
            if widget:
                widget.hide()

        return super().run()

    def update(self) -> None:
        for response in Response:
            if response == Response.CANCEL:
                continue

            widget = self.get_widget_for_response(response.value)
            if widget:
                widget.set_sensitive(self.can_commit)

    def do_commit(self) -> bool:
        try:
            self.session.commit()
            self.session.close()
            return True
        except SQLAlchemyError as e:
            msg = _("Error committing changes.\n\n%s") % xml_safe(e)
            dialogs.message_details_dialog(
                msg,
                traceback.format_exc(),
                Gtk.MessageType.ERROR,
                parent=self,
            )
            self.session.rollback()
            self.model = self.session.merge(self.model)
        return False

    def has_pending_changes(self) -> bool:
        """Check if the model has pending changes.

        Used by GUI on delete-event to determine if the dialog has pending
        changes.
        """
        if self.problems:
            return True

        return db.is_modified(self.session)

    def notify_delete_event(self, remove: Callable[[int], None]) -> None:
        """Respond to the GUI delete-event signal handler.

        On GUI delete, if this dialog has pending changes the gui will call
        this method supplying the ``remove`` callback which can be called to
        remove close this dialog and remove it from the list of pending
        responses (and hence accept the delete-event).

        If all open dialogs accept the delete-event the app will close.
        """
        generic_notify_delete_event(self, remove)


class RevealerDialog(Protocol):  # pylint: disable=too-few-public-methods
    revealer: Gtk.Revealer

    def emit(self, signal_name: str, *args) -> None: ...


def generic_notify_delete_event(
    dialog: RevealerDialog,
    remove: Callable[[int], None],
) -> None:
    """Respond to the GUI delete-event signal handler.

    Any ``Gtk.Dialog`` can use this if it has a revealer to display the
    message and a ``notify_delete_event`` method.

    On delete the GUI will look for open dialogs and if they have a truthy
    ``problems`` property and/or a modified database ``session`` property, and
    a ``notify_delete_event`` method is available, it will call it supplying
    the ``remove`` callback.  Calling this callback will remove the dialog from
    the list of pending responses (and hence accept the delete-event).

    Usage example::

        class Foo(Gtk.Dialog):
            def __init__(self):
                revealer = Gtk.Revealer()
                ...

            def notify_delete_event(self, remove):
                generic_notify_delete_event(self, remove)

    """
    dialog.revealer.set_reveal_child(False)

    def on_yes_clicked(_button: Gtk.Button) -> None:
        dialog.revealer.set_reveal_child(False)
        # pylint: disable=no-member
        dialog.emit(
            "response",
            Gtk.ResponseType.DELETE_EVENT,
        )
        remove(id(dialog))

    def on_no_clicked(_button: Gtk.Button) -> None:
        dialog.revealer.set_reveal_child(False)

    msg = _(
        "You have UNFINISHED WORK HERE, are you sure you want to exit?\n\n"
        "Only after all windows are closed can you exit."
        "\n\n    <b>CLOSE and DON'T SAVE CHANGES?</b>\n"
    )

    message_box = OkCancelMessageBox(msg, on_yes_clicked, on_no_clicked)

    dialog.revealer.foreach(dialog.revealer.remove)

    def _reveal():
        message_box.show_all()
        dialog.revealer.add(message_box)
        dialog.revealer.set_reveal_child(True)

    # if replaceing existing in-app notifications allow them time to clear
    # first so this one reveals again, makes this notification a little more
    # prominent
    GLib.timeout_add(50, _reveal)


class AddCallback:
    # pylint: disable=too-few-public-methods

    def __init__(
        self,
        dialog_class: type[DomainEditorDialog],
        obj_class: type[db.Domain],
        parent_attr: str,
    ) -> None:
        self.dialog_class = dialog_class
        self.obj_class = obj_class
        self.parent_attr = parent_attr

    def __call__(self, objs: Sequence[db.Domain], **_kwargs) -> bool:
        obj = objs[0]

        # take the object out of searchview's etc. session or could leave a
        # hanging new item in session.
        with db.Session() as session:
            parent = session.merge(obj)
            model = self.obj_class()
            setattr(model, self.parent_attr, parent)

        dialog = self.dialog_class(
            model=model,
            session=db.Session(),
        )

        # update searchview
        dialog.connect_after("response", _on_domain_editor_response)
        dialog.show()

        if hasattr(dialog, f"lock_{self.parent_attr}"):
            getattr(dialog, f"lock_{self.parent_attr}")()

        return False


class EditCreateCallback:
    # pylint: disable=too-few-public-methods
    """Functor to create generic edit/create_callback functions.

    NOTE: these callbacks will not block the UI as they don't use
    ``dialog.run()``, instead using ``dialog.show()``.  This requires the
    DomainEditorDialog's themselves to handle responses, including calling
    ``self.destroy()`` when complete.
    """

    def __init__(
        self,
        dialog_class: type[DomainEditorDialog],
        obj_class: type[db.Domain],
    ) -> None:
        self.dialog_class = dialog_class
        self.obj_class = obj_class

    def __call__(
        self,
        objs: Sequence[db.Domain] | None = None,
        **kwargs,
    ) -> bool:
        """Create or edit an object using the provided dialog class.

        The dialog will be created with a new session, and not destroyed.

        :param objs: If provided the first object in the sequence will be
            edited, otherwise a new object will be created.
        :param kwargs: Additional keyword arguments to pass to the object
            constructor when creating a new object.
        """
        if objs:
            # edit
            for obj in objs:
                self.start_dialog(obj)
        else:
            # create
            obj = self.obj_class(**kwargs)
            self.start_dialog(obj)

        return False

    def start_dialog(self, obj: db.Domain) -> None:

        dialog = self.dialog_class(
            model=obj,
            session=db.Session(),
        )

        # update searchview
        dialog.connect_after("response", _on_domain_editor_response)
        dialog.show()


def _on_domain_editor_response(
    _dialog: DomainEditorDialog,
    response: Response,
) -> None:
    if response in [
        Response.NEXT,
        Response.ADD,
        Response.OK,
        Response.SAVE,
    ]:
        for view in bauble.gui.views:
            view.update(None)


# avoid circular
from .widgets import OkCancelMessageBox
