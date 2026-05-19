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
Plant widgets.
"""
import logging

logger = logging.getLogger(__name__)

from collections.abc import Callable
from pathlib import Path
from typing import Any
from typing import cast

from gi.repository import GObject
from gi.repository import Gtk
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import DetachedInstanceError

from bauble import db
from bauble import prefs
from bauble.btypes import parse_str_date

from ...plant import Plant
from ...plant import PlantChange
from ...plant import added_reasons
from ...plant import change_reasons
from ...plant import deleted_reasons
from ...plant import new_plt_reasons
from ...plant import split_reasons
from ...plant import transfer_reasons

parent = Path(__file__).resolve().parent


def _set_cell_from_func(
    cell: Gtk.CellRendererText,
    val: PlantChange,
    func: Callable[[PlantChange], str],
) -> None:
    """Helper function to set a cell's text property from a function.

    Captures DetachedInstanceErrors that can occur when the editor is destroyed
    and logs them.
    """

    try:
        cell.set_property("text", func(val))
    except DetachedInstanceError as e:
        logger.debug("%s(%s)", type(e).__name__, e)


@Gtk.Template(filename=str(parent / "history_presenter.ui"))
class PlantHistoryPresenter(Gtk.ScrolledWindow):

    __gtype_name__ = "PlantHistoryPresenter"

    __gsignals__ = {
        "changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    # convince pylint liststore is subscriptable
    liststore = Gtk.ListStore(object)
    liststore = cast(Gtk.ListStore, Gtk.Template.Child())
    reason_liststore = Gtk.ListStore(str, str)
    reason_liststore = cast(Gtk.ListStore, Gtk.Template.Child())
    selection = cast(Gtk.TreeSelection, Gtk.Template.Child())
    date_column = cast(Gtk.TreeViewColumn, Gtk.Template.Child())
    date_cell = cast(Gtk.CellRendererText, Gtk.Template.Child())
    quantity_column = cast(Gtk.TreeViewColumn, Gtk.Template.Child())
    quantity_cell = cast(Gtk.CellRendererText, Gtk.Template.Child())
    from_column = cast(Gtk.TreeViewColumn, Gtk.Template.Child())
    from_cell = cast(Gtk.CellRendererText, Gtk.Template.Child())
    to_column = cast(Gtk.TreeViewColumn, Gtk.Template.Child())
    to_cell = cast(Gtk.CellRendererText, Gtk.Template.Child())
    parent_column = cast(Gtk.TreeViewColumn, Gtk.Template.Child())
    parent_cell = cast(Gtk.CellRendererText, Gtk.Template.Child())
    child_column = cast(Gtk.TreeViewColumn, Gtk.Template.Child())
    child_cell = cast(Gtk.CellRendererText, Gtk.Template.Child())
    reason_column = cast(Gtk.TreeViewColumn, Gtk.Template.Child())
    reason_cell = cast(Gtk.CellRendererCombo, Gtk.Template.Child())
    user_column = cast(Gtk.TreeViewColumn, Gtk.Template.Child())
    user_cell = cast(Gtk.CellRendererText, Gtk.Template.Child())

    def __init__(self) -> None:
        super().__init__()
        self.model: Plant
        self.session: Session
        self.revealer: Gtk.Revealer
        self.handlers: list[tuple[GObject.Object, int]] = []

    def init(
        self,
        model: Plant,
    ) -> None:
        self.model = model

        self.connect("destroy", self.on_destroy)

        self.init_treeview()

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

    def on_destroy(self, *_args) -> None:
        while self.handlers:
            widget, handler = self.handlers.pop()
            widget.disconnect(handler)

    def init_treeview(self) -> None:

        self.date_column.set_cell_data_func(
            self.date_cell,
            self.date_cell_data_func,
        )
        self.connect_w_ref(self.date_cell, "edited", self.on_date_edited)

        self.quantity_column.set_cell_data_func(
            self.quantity_cell,
            self.quantity_cell_data_func,
        )

        self.from_column.set_cell_data_func(
            self.from_cell,
            self.from_cell_data_func,
        )

        self.to_column.set_cell_data_func(
            self.to_cell,
            self.to_cell_data_func,
        )

        self.parent_column.set_cell_data_func(
            self.parent_cell,
            self.parent_cell_data_func,
        )

        self.child_column.set_cell_data_func(
            self.child_cell,
            self.child_cell_data_func,
        )

        for key, val in change_reasons.items():
            self.reason_liststore.append((key, val))

        self.reason_column.set_cell_data_func(
            self.reason_cell,
            self.reason_cell_data_func,
        )
        self.connect_w_ref(self.reason_cell, "changed", self.on_reason_changed)

        self.user_column.set_cell_data_func(
            self.user_cell,
            self.user_cell_data_func,
        )
        self.connect_w_ref(self.user_cell, "edited", self.on_user_edited)

        self.user_cell.connect("editing-started", self._user_edit_start)

        for change in self.model.changes:
            self.liststore.append((change,))

    @staticmethod
    def date_cell_data_func(
        _column: Gtk.TreeViewColumn,
        cell: Gtk.CellRendererText,
        model: Gtk.TreeModel,
        treeiter: Gtk.TreeIter,
        _data: Any = None,
    ) -> None:
        frmt = prefs.prefs[prefs.date_format_pref]

        _set_cell_from_func(
            cell,
            model[treeiter][0],
            lambda obj: obj.date.strftime(frmt) if obj.date else "",
        )

    @staticmethod
    def quantity_cell_data_func(
        _column: Gtk.TreeViewColumn,
        cell: Gtk.CellRendererText,
        model: Gtk.TreeModel,
        treeiter: Gtk.TreeIter,
        _data: Any = None,
    ) -> None:
        _set_cell_from_func(
            cell,
            model[treeiter][0],
            lambda obj: str(obj.quantity),
        )

    @staticmethod
    def from_cell_data_func(
        _column: Gtk.TreeViewColumn,
        cell: Gtk.CellRendererText,
        model: Gtk.TreeModel,
        treeiter: Gtk.TreeIter,
        _data: Any = None,
    ) -> None:
        def _func(obj: PlantChange) -> str:
            if obj.from_location and obj.from_location.code:
                return obj.from_location.code
            return ""

        _set_cell_from_func(
            cell,
            model[treeiter][0],
            _func,
        )

    @staticmethod
    def to_cell_data_func(
        _column: Gtk.TreeViewColumn,
        cell: Gtk.CellRendererText,
        model: Gtk.TreeModel,
        treeiter: Gtk.TreeIter,
        _data: Any = None,
    ) -> None:
        def _func(obj: PlantChange) -> str:
            if obj.to_location and obj.to_location.code:
                return obj.to_location.code
            return ""

        _set_cell_from_func(
            cell,
            model[treeiter][0],
            _func,
        )

    @staticmethod
    def parent_cell_data_func(
        _column: Gtk.TreeViewColumn,
        cell: Gtk.CellRendererText,
        model: Gtk.TreeModel,
        treeiter: Gtk.TreeIter,
        _data: Any = None,
    ) -> None:
        _set_cell_from_func(
            cell,
            model[treeiter][0],
            lambda obj: str(obj.parent_plant or ""),
        )

    @staticmethod
    def child_cell_data_func(
        _column: Gtk.TreeViewColumn,
        cell: Gtk.CellRendererText,
        model: Gtk.TreeModel,
        treeiter: Gtk.TreeIter,
        _data: Any = None,
    ) -> None:
        _set_cell_from_func(
            cell,
            model[treeiter][0],
            lambda obj: str(obj.child_plant or ""),
        )

    @staticmethod
    def reason_cell_data_func(
        _column: Gtk.TreeViewColumn,
        cell: Gtk.CellRendererCombo,
        model: Gtk.TreeModel,
        treeiter: Gtk.TreeIter,
        _data: Any = None,
    ) -> None:
        _set_cell_from_func(
            cell,
            model[treeiter][0],
            lambda obj: str(change_reasons.get(obj.reason) or ""),
        )

    @staticmethod
    def user_cell_data_func(
        _column: Gtk.TreeViewColumn,
        cell: Gtk.CellRendererText,
        model: Gtk.TreeModel,
        treeiter: Gtk.TreeIter,
        _data: Any = None,
    ) -> None:
        _set_cell_from_func(
            cell,
            model[treeiter][0],
            lambda obj: obj.person or "",
        )

    @staticmethod
    def _user_edit_start(
        _renderer: Gtk.CellRendererText,
        entry: Gtk.Entry,
        _path: str,
    ) -> None:
        # setup completion for user names
        name_store = Gtk.ListStore(str)
        with db.engine.connect() as conn:
            names = conn.execute(
                select(PlantChange.person).distinct()
            ).scalars()
            for name in names:
                if name:
                    name_store.append([name])

        lang_completion = Gtk.EntryCompletion(model=name_store)
        lang_completion.set_text_column(0)

        entry.set_completion(lang_completion)

    @Gtk.Template.Callback()
    def on_selection_changed(self, selection: Gtk.TreeSelection) -> None:
        model, treeiter = selection.get_selected()
        if not treeiter:
            return

        path = model.get_path(treeiter)

        change = self.liststore[path][0]
        reasons = change_reasons

        if change.parent_plant or change.child_plant:
            reasons = split_reasons
        elif path == Gtk.TreePath().new_first():
            reasons = new_plt_reasons
        elif change.from_location and change.to_location:
            reasons = transfer_reasons
        elif change.from_location and change.quantity < 0:
            reasons = deleted_reasons
        elif change.to_location and change.quantity > 0:
            reasons = added_reasons

        self.reason_liststore.clear()
        for key, val in reasons.items():
            self.reason_liststore.append((key, val))

    def on_date_edited(
        self,
        _cell: Gtk.CellRendererText,
        path: str,
        new_text: str,
    ) -> None:
        change = self.liststore[path][0]

        val = parse_str_date(new_text)

        # only set the date if its a valid and different date
        if not val or val == change.date:
            return

        change.date = val

        self.emit("changed")

    def on_reason_changed(
        self,
        _cell: Gtk.CellRendererText,
        path: str,
        new_iter: str,
    ) -> None:
        change = self.liststore[path][0]

        val = self.reason_liststore[new_iter][0]

        change.reason = val

        self.emit("changed")

    def on_user_edited(
        self,
        _cell: Gtk.CellRendererText,
        path: str,
        new_text: str,
    ) -> None:
        change = self.liststore[path][0]

        change.person = new_text

        self.emit("changed")
