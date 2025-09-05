# Copyright 2025 Ross Demuth <rossdemuth123@gmail.com>
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
#
"""
Provides a database model and GUI to manage stored queries.

Stored queries are saved in the database and can be quickly accessed
from the home view by all users.
"""
from pathlib import Path
from typing import Self
from typing import cast

from gi.repository import Gtk
from sqlalchemy import Column
from sqlalchemy import String
from sqlalchemy import Text
from sqlalchemy import func

import bauble
from bauble import db
from bauble import editor


class StoredQuery(db.Base):  # pylint: disable=too-few-public-methods

    __tablename__ = "stored_query"

    name: str = Column(String(64), nullable=False)
    description: str = Column(String(256))
    query: str = Column(Text, nullable=False)


@Gtk.Template(
    filename=str(Path(__file__).resolve().parent / "stored_query_editor.ui")
)
class StoredQueryEditorDialog(
    editor.GenericPresenter[StoredQuery],
    Gtk.Dialog,
):
    """Dialog to create or edit a stored query."""

    __gtype_name__ = "StoredQueryEditorDialog"

    __gsignals__ = editor.GenericPresenter.gsignals

    name_entry = cast(Gtk.Entry, Gtk.Template.Child())
    description_textbuffer = cast(Gtk.TextBuffer, Gtk.Template.Child())
    query_textbuffer = cast(Gtk.TextBuffer, Gtk.Template.Child())
    query_textview = cast(Gtk.TextView, Gtk.Template.Child())
    ok_button = cast(Gtk.Button, Gtk.Template.Child())

    def __init__(
        self,
        model: StoredQuery,
        transient_for: Gtk.Window | None = None,
    ) -> None:
        super().__init__(model, self)
        self.widgets_to_model_map = {
            self.name_entry: "name",
            self.description_textbuffer: "description",
            self.query_textbuffer: "query",
        }
        self.set_transient_for(transient_for)
        self.set_destroy_with_parent(True)
        self.connect("problems-changed", self.on_problems_changed)

        self.name_entry.grab_focus()
        self.refresh_all_widgets_from_model()
        # trigger problems
        self.on_query_text_buffer_changed(self.query_textbuffer)
        self.name_entry.emit("changed")

    @Gtk.Template.Callback()
    def on_text_buffer_changed(self, buffer: Gtk.TextBuffer) -> None:
        super().on_text_buffer_changed(buffer)

    @Gtk.Template.Callback()
    def on_query_text_buffer_changed(self, buffer: Gtk.TextBuffer) -> None:
        super().on_non_empty_text_buffer_changed(buffer, self.query_textview)

    @Gtk.Template.Callback()
    def on_name_entry_changed(self, entry: Gtk.Entry) -> None:
        super().on_unique_text_entry_changed(entry)

    def on_problems_changed(self, _foo: Self, has_problems: bool) -> None:
        self.ok_button.set_sensitive(not has_problems)


@Gtk.Template(
    filename=str(Path(__file__).resolve().parent / "stored_queries_dialog.ui")
)
class StoredQueriesDialog(Gtk.Dialog):
    """Dialog to manage stored queries.

    Allows creating, editing, and deleting stored queries.
    """

    __gtype_name__ = "StoredQueriesDialog"

    # new_button = cast(Gtk.Button, Gtk.Template.Child())
    delete_button = cast(Gtk.Button, Gtk.Template.Child())
    edit_button = cast(Gtk.Button, Gtk.Template.Child())
    list_store = cast(Gtk.ListStore, Gtk.Template.Child())
    selection = cast(Gtk.TreeSelection, Gtk.Template.Child())
    name_column = cast(Gtk.TreeViewColumn, Gtk.Template.Child())
    name_cell = cast(Gtk.CellRendererText, Gtk.Template.Child())
    description_column = cast(Gtk.TreeViewColumn, Gtk.Template.Child())
    description_cell = cast(Gtk.CellRendererText, Gtk.Template.Child())
    query_column = cast(Gtk.TreeViewColumn, Gtk.Template.Child())
    query_cell = cast(Gtk.CellRendererText, Gtk.Template.Child())
    ok_button = cast(Gtk.Button, Gtk.Template.Child())

    def __init__(self) -> None:
        transient_for = bauble.gui.window if bauble.gui else None
        super().__init__(
            transient_for=transient_for,
            destroy_with_parent=True,
        )
        self.session = db.Session()

        self.name_column.set_cell_data_func(
            self.name_cell,
            self.cell_data_func,
            "name",
        )
        self.description_column.set_cell_data_func(
            self.description_cell,
            self.cell_data_func,
            "description",
        )
        self.query_column.set_cell_data_func(
            self.query_cell,
            self.cell_data_func,
            "query",
        )

        for stored_query in self.session.query(StoredQuery):
            self.list_store.append([stored_query])

    @Gtk.Template.Callback()
    def on_new_button_clicked(self, _button) -> None:
        new_query = StoredQuery(name="", query="")
        dialog = StoredQueryEditorDialog(new_query, self)

        if dialog.run() == Gtk.ResponseType.OK:
            self.session.add(new_query)
            self.list_store.append([new_query])

        dialog.destroy()
        self.refresh()

    @Gtk.Template.Callback()
    def on_edit_button_clicked(self, _button) -> None:
        model, treeiter = self.selection.get_selected()

        if treeiter is None:
            return

        stored_query = model[treeiter][0]
        dialog = StoredQueryEditorDialog(stored_query, self)

        if dialog.run() != Gtk.ResponseType.OK:
            self.session.refresh(stored_query)

        dialog.destroy()
        self.refresh()

    @Gtk.Template.Callback()
    def on_delete_button_clicked(self, _button) -> None:
        model, treeiter = self.selection.get_selected()

        if treeiter is None:
            return

        stored_query = model[treeiter][0]
        self.session.delete(stored_query)
        self.refresh()

    @Gtk.Template.Callback()
    def on_selection_changed(self, selection: Gtk.TreeSelection) -> None:
        _model, treeiter = selection.get_selected()
        self.delete_button.set_sensitive(treeiter is not None)
        self.edit_button.set_sensitive(treeiter is not None)

    def refresh(self) -> None:
        if self.session.dirty or self.session.new or self.session.deleted:
            self.ok_button.set_sensitive(True)
        else:
            self.ok_button.set_sensitive(False)
        self.selection.unselect_all()

    def cell_data_func(
        self,
        _column: Gtk.TreeViewColumn,
        cell: Gtk.CellRendererText,
        model: Gtk.TreeModel,
        treeiter: Gtk.TreeIter,
        prop: str,
    ) -> None:
        stored_query = model[treeiter][0]
        value = getattr(stored_query, prop) or ""
        cell.set_property("text", value)
        cell.set_property("foreground", None)

        if self.session.is_modified(stored_query):
            cell.set_property("foreground", "blue")

        if stored_query in self.session.deleted:
            cell.set_property("foreground", "red")


@Gtk.Template(
    filename=str(
        Path(__file__).resolve().parent / "stored_queries_button_box.ui"
    )
)
class StoredQueriesButtonBox(Gtk.Box):
    """Home view button box widget for stored queries.

    Displays buttons for each stored query in the database. Clicking a button
    populates the main query entry with the stored query and triggers a search.
    """

    __gtype_name__ = "StoredQueriesButtonBox"

    query_button_box = cast(Gtk.Box, Gtk.Template.Child())

    def __init__(self) -> None:
        super().__init__()
        self.refresh()

    @Gtk.Template.Callback()
    def on_edit_button_clicked(self, _button: Gtk.Button) -> None:
        dialog = StoredQueriesDialog()

        if dialog.run() == Gtk.ResponseType.OK:
            dialog.session.commit()

        dialog.session.close()
        dialog.destroy()
        self.refresh()

    def refresh(self) -> None:
        self.query_button_box.foreach(self.query_button_box.remove)
        with db.Session() as session:
            for stored_query in session.query(StoredQuery).order_by(
                func.lower(StoredQuery.name)
            ):
                button = Gtk.Button(label=stored_query.name)

                if stored_query.description:
                    button.set_tooltip_text(stored_query.description)

                button.connect(
                    "clicked",
                    self.on_stored_query_button_clicked,
                    stored_query.query or "",
                )

                self.query_button_box.add(button)
        self.query_button_box.show_all()

    @staticmethod
    def on_stored_query_button_clicked(
        _button: Gtk.Button,
        query: str,
    ) -> None:
        if query:
            bauble.gui.send_command(query)
