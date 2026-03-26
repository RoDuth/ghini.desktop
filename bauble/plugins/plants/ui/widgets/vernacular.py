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
Vernacular names widgets.
"""
import logging

logger = logging.getLogger(__name__)

from collections.abc import Callable
from pathlib import Path
from string import capwords
from typing import Any
from typing import cast

from gi.repository import GLib
from gi.repository import GObject
from gi.repository import Gtk
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import DetachedInstanceError

from bauble import prefs
from bauble import utils
from bauble.i18n import _
from bauble.ui import dialogs
from bauble.ui.presenter import Problem
from bauble.ui.widgets import MessageBox

from ...species_model import Species
from ...species_model import VernacularName

parent = Path(__file__).resolve().parent

CAPITALISE_VNAMES_ON_PASTE_PREF_KEY = "species_editor.cap_vnames_on_paste"
"""Preference key for capitalising vernacular names on paste.

Values: 'title', 'capword'
(Defaults to 'title', any other value, e.g. 'off', disables capitalisation)
"""


@Gtk.Template(filename=str(parent / "vernacular_presenter.ui"))
class VernacularNamePresenter(Gtk.Frame):

    __gtype_name__ = "VernacularNamePresenter"

    __gsignals__ = {
        "changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    # convince pylint liststore is subscriptable
    list_store = Gtk.ListStore(object)
    list_store = cast(Gtk.ListStore, Gtk.Template.Child())
    treeview = cast(Gtk.TreeView, Gtk.Template.Child())
    name_column = cast(Gtk.TreeViewColumn, Gtk.Template.Child())
    name_cell = cast(Gtk.CellRendererText, Gtk.Template.Child())
    lang_column = cast(Gtk.TreeViewColumn, Gtk.Template.Child())
    lang_cell = cast(Gtk.CellRendererText, Gtk.Template.Child())
    default_column = cast(Gtk.TreeViewColumn, Gtk.Template.Child())
    default_cell = cast(Gtk.CellRendererToggle, Gtk.Template.Child())
    add_button = cast(Gtk.Button, Gtk.Template.Child())
    remove_button = cast(Gtk.Button, Gtk.Template.Child())

    PROBLEM_EMPTY = Problem("empty")

    def __init__(self) -> None:
        super().__init__()
        self.model: Species
        self.session: Session
        self.revealer: Gtk.Revealer
        self.problems: set[tuple[str, Gtk.Widget]] = set()
        self.handlers: list[tuple[GObject.Object, int]] = []

    def init(
        self,
        model: Species,
        session: Session,
        revealer: Gtk.Revealer,
    ) -> None:
        self.connect("destroy", self.on_destroy)
        self.model = model
        self.session = session
        self.revealer = revealer

        self.init_treeview()

        vernacular_names = self.model.vernacular_names
        default_vernacular_name = self.model.default_vernacular_name

        if vernacular_names and default_vernacular_name is None:
            # pylint: disable=line-too-long
            self.model.default_vernacular_name = vernacular_names[0]  # type: ignore [method-assign]  # noqa
            GLib.idle_add(self.notify_user_default_set)

    def notify_user_default_set(self) -> None:

        msg = _(
            "This species has vernacular names but none have been "
            "selected as the default.\n\nThe first vernacular name in "
            "the list has been automatically selected."
        )
        message_box = MessageBox(msg)
        self.revealer.foreach(self.revealer.remove)
        message_box.show_all()
        self.revealer.add(message_box)
        self.revealer.set_reveal_child(True)

    def init_treeview(self) -> None:

        self.name_column.set_cell_data_func(
            self.name_cell,
            self.generic_data_func,
            "name",
        )

        def _name_edit_start(_renderer, entry, _path):
            logger.debug("vernacular name editing-started")
            self.connect_w_ref(
                entry,
                "paste-clipboard",
                self.on_vernacular_name_paste,
            )

        self.connect_w_ref(self.name_cell, "editing-started", _name_edit_start)
        self.connect_w_ref(
            self.name_cell,
            "edited",
            self.on_cell_edited,
            "name",
        )

        self.lang_column.set_cell_data_func(
            self.lang_cell,
            self.generic_data_func,
            "language",
        )

        lang_store = Gtk.ListStore(str)
        languages = self.session.execute(
            select(VernacularName.language).distinct()
        ).scalars()
        for lang in languages:
            if lang:
                lang_store.append([lang])

        lang_completion = Gtk.EntryCompletion(model=lang_store)
        lang_completion.set_text_column(0)

        def _lang_edit_start(_renderer, entry, _path):
            entry.set_completion(lang_completion)

        self.connect_w_ref(self.lang_cell, "editing-started", _lang_edit_start)
        self.connect_w_ref(
            self.lang_cell,
            "edited",
            self.on_cell_edited,
            "language",
        )

        self.default_column.set_cell_data_func(
            self.default_cell,
            self.default_data_func,
        )
        self.connect_w_ref(
            self.default_cell,
            "toggled",
            self.on_default_toggled,
        )

        for vernacular in self.model.vernacular_names:
            self.list_store.append([vernacular])

        self.treeview.connect("cursor-changed", self.on_cursor_changed)

    def on_cursor_changed(self, _tree: Gtk.TreeView) -> None:
        self.remove_button.set_sensitive(len(self.list_store) > 0)

    def connect_w_ref(
        self,
        widget: GObject.Object,
        signal: str,
        handler: Callable,
        *args: Any,
    ) -> None:
        """Connects a widget to a handler and keeps a copy of the handler ID.

        Use when the handler maintains a reference to the widget that needs
        to be disconnected before garbage collection.  Handlers are
        disconnected in ``on_destroy``.
        """
        self.handlers.append((widget, widget.connect(signal, handler, *args)))

    def on_destroy(self, *_args):
        while self.handlers:
            widget, handler = self.handlers.pop()
            widget.disconnect(handler)

    @property
    def can_commit(self) -> bool:
        return not self.problems

    @staticmethod
    def generic_data_func(
        _column: Gtk.TreeViewColumn,
        cell: Gtk.CellRendererText,
        model: Gtk.TreeModel,
        treeiter: Gtk.TreeIter,
        attr: str,
    ) -> None:
        val = model[treeiter][0]

        try:
            cell.set_property("text", getattr(val, attr))
            cell.set_property("background", None)
            # change the foreground color to indicate it's new and hasn't been
            # committed
            if val.id is None:  # hasn't been committed
                cell.set_property("foreground", "blue")
            else:
                cell.set_property("foreground", None)

            if attr == "name" and not val.name:
                # highlight the problem row
                cell.set_property("background", "pink")
        except DetachedInstanceError as e:
            logger.debug("%s(%s)", type(e).__name__, e)

    @staticmethod
    def default_data_func(
        _column: Gtk.TreeViewColumn,
        cell: Gtk.CellRendererToggle,
        model: Gtk.TreeModel,
        treeiter: Gtk.TreeIter,
        _attr,
    ) -> None:
        val = model[treeiter][0]
        try:
            cell.set_property(
                "active", val == val.species.default_vernacular_name
            )
            return
        except (AttributeError, DetachedInstanceError) as e:
            logger.debug("%s(%s)", type(e).__name__, e)

    def on_cell_edited(
        self,
        _cell: Gtk.CellRendererText,
        path: str,
        new_text: str,
        prop: str,
    ) -> None:
        vernacular = self.list_store[path][0]

        if getattr(vernacular, prop) == new_text:
            return  # no change

        if new_text:
            new_text = new_text.strip()

        setattr(vernacular, prop, new_text)
        self.check_problems()
        self.emit("changed")

    @staticmethod
    def on_vernacular_name_paste(entry: Gtk.Entry) -> None:
        """Handler for pasting into the vernacular name entry.

        Capitalises the pasted text according to user preferences.
        If user has disabled capitilisation the text is left exactly as is
        otherwise removes erroneous whitespace and capitalise the text.
        """

        capitalise = prefs.prefs.get(
            CAPITALISE_VNAMES_ON_PASTE_PREF_KEY,
            "title",
        )

        if capitalise not in ("title", "capwords"):
            return

        def _cap(entry):
            string = entry.get_text()
            if capitalise == "title":
                cap_string = utils.title_case(string)
            else:
                cap_string = capwords(string)

            if string != cap_string:
                entry.set_text(cap_string)

        GLib.idle_add(_cap, entry)

    def on_default_toggled(self, cell, path):
        active = cell.get_active()

        if not active:
            vernacular = self.treeview.get_model()[path][0]
            self.model.default_vernacular_name = vernacular

        self.emit("changed")

    def check_problems(self) -> None:
        self.remove_problem(self.PROBLEM_EMPTY, self)
        for name in self.model.vernacular_names:
            if not name.name:
                self.add_problem(self.PROBLEM_EMPTY, self)
                self.treeview.get_selection().unselect_all()

    def add_problem(
        self,
        problem_id: str,
        widget: Gtk.Widget,
    ) -> None:

        self.problems.add((problem_id, widget))
        widget.get_style_context().add_class("problem")

        logger.debug("problems now: %s", self.problems)

    def remove_problem(
        self,
        problem_id: str,
        widget: Gtk.Widget,
    ) -> None:

        if (problem_id, widget) in self.problems:
            self.problems.remove((problem_id, widget))
            widget.get_style_context().remove_class("problem")

        logger.debug("problems now: %s", self.problems)

    @Gtk.Template.Callback()
    def on_add_clicked(self, _button: Gtk.Button) -> None:
        column = self.treeview.get_column(0)
        vernacular = VernacularName()
        self.model.vernacular_names.append(vernacular)
        treeiter = self.list_store.append([vernacular])
        path = self.list_store.get_path(treeiter)
        self.treeview.set_cursor(path, column, start_editing=True)

        if len(self.list_store) == 1:
            self.model.default_vernacular_name = vernacular  # type: ignore [method-assign]  # noqa

    @Gtk.Template.Callback()
    def on_remove_clicked(self, _button: Gtk.Button) -> None:
        path, _col = self.treeview.get_cursor()
        vernacular = self.list_store[path][0]

        parent_window = None
        toplevel = self.get_toplevel()
        if isinstance(toplevel, Gtk.Window):
            parent_window = toplevel

        msg = _(
            "Are you sure you want to remove the vernacular name <b>%s</b>?"
        ) % utils.xml_safe(vernacular.name)
        if (
            vernacular.name
            and vernacular not in self.session.new
            and not dialogs.yes_no_dialog(msg, parent=parent_window)
        ):
            return

        self.list_store.remove(self.list_store.get_iter(path))

        if self.model.default_vernacular_name == vernacular:
            first = self.list_store.get_iter_first()
            if first:
                vern = self.list_store[first][0]
                self.model.default_vernacular_name = vern  # type: ignore [method-assign]  # noqa

        self.model.vernacular_names.remove(vernacular)
        self.check_problems()

        self.emit("changed")
