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
Notes and Documents display widgets, as used in SearchView.
"""

import logging

logger = logging.getLogger(__name__)

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Protocol
from typing import cast

from gi.repository import Gtk

import bauble
from bauble import db
from bauble import prefs
from bauble.i18n import _

parent = Path(__file__).resolve().parent


class Note(Protocol):  # pylint: disable=too-few-public-methods
    date: datetime
    user: str
    category: str
    note: str


@Gtk.Template(filename=str(parent / "notes_scroller.ui"))
class NotesScroller(Gtk.ScrolledWindow):
    """Display Notes corresponding to the supplied domain object.

    Can be used as a page to append to ``SearchView.bottom_notebook``.
    """

    __gtype_name__ = "NotesScroller"

    treeview = cast(Gtk.TreeView, Gtk.Template.Child())
    liststore = cast(Gtk.ListStore, Gtk.Template.Child())

    LABEL_STR = _("Notes")
    label = Gtk.Label(label=LABEL_STR)

    def __init__(self) -> None:
        super().__init__()
        self.domain: str = ""

    def update(self, row: db.Domain) -> None:
        logger.debug("update notes bottom page")

        self.domain = row.__class__.__name__.lower() if row else ""

        self.liststore.clear()

        notes: list[Note] = []
        if hasattr(row, "notes") and isinstance(row.notes, list):
            notes = row.notes or notes

        for note in sorted(notes, key=lambda note: note.date, reverse=True):
            date = note.date.strftime(prefs.prefs.get(prefs.date_format_pref))
            self.liststore.append((note.category, note.note, note.user, date))

        if notes:
            self.label.set_use_markup(True)
            self.label.set_label(f"<b>{self.LABEL_STR}</b>")
        else:
            self.label.set_use_markup(False)
            self.label.set_label(self.LABEL_STR)

    @Gtk.Template.Callback()
    def on_row_activated(
        self,
        _tree,
        path: Gtk.TreePath,
        _column,
        *,
        send_command: Callable[[str], None] | None = None,
    ) -> None:
        """When a row is double clicked run a search to find other items of the
        same type with the same note.
        """
        send_command = send_command or bauble.gui.send_command

        row = self.liststore[path]  # pylint: disable=unsubscriptable-object
        cat = None if row[0] == "" else repr(row[0])
        note = repr(row[1])
        logger.debug(
            "notes bottom page row_activated: domain=%s, cat=%s, note=%s",
            self.domain,
            cat,
            note,
        )

        send_command(f"{self.domain} where notes[category={cat}].note={note}")


class Document(Note):  # pylint: disable=too-few-public-methods
    document: str


@Gtk.Template(filename=str(parent / "docs_scroller.ui"))
class DocumentsScroller(Gtk.ScrolledWindow):
    """Display Documents corresponding to the supplied domain object.

    Can be used as a page to append to ``SearchView.bottom_notebook``.
    """

    __gtype_name__ = "DocumentsScroller"

    treeview = cast(Gtk.TreeView, Gtk.Template.Child())
    liststore = cast(Gtk.ListStore, Gtk.Template.Child())

    LABEL_STR = _("Docs")
    label = Gtk.Label(label=LABEL_STR)

    def __init__(self) -> None:
        super().__init__()
        self.domain: str = ""

    def update(self, row: db.Domain) -> None:
        logger.debug("update docs bottom page")

        self.domain = row.__class__.__name__.lower() if row else ""

        self.liststore.clear()

        docs: list[Document] = []
        if hasattr(row, "documents") and isinstance(row.documents, list):
            docs = row.documents or docs

        for doc in sorted(docs, key=lambda doc: doc.date, reverse=True):
            date = doc.date.strftime(prefs.prefs.get(prefs.date_format_pref))
            self.liststore.append(
                (
                    doc.category,
                    doc.document,
                    doc.note,
                    doc.user,
                    date,
                )
            )

        if docs:
            self.label.set_use_markup(True)
            self.label.set_label(f"<b>{self.LABEL_STR}</b>")
        else:
            self.label.set_use_markup(False)
            self.label.set_label(self.LABEL_STR)

    @Gtk.Template.Callback()
    def on_row_activated(
        self,
        _tree,
        path: Gtk.TreePath,
        _column,
        *,
        send_command: Callable[[str], None] | None = None,
    ) -> None:
        """When a row is double clicked run a search to find other items of the
        same type with the same document.
        """
        send_command = send_command or bauble.gui.send_command

        row = self.liststore[path]  # pylint: disable=unsubscriptable-object
        cat = None if row[0] == "" else repr(row[0])
        doc = repr(row[1])
        logger.debug(
            "docs bottom page row_activated: domain=%s, cat=%s, document=%s",
            self.domain,
            cat,
            doc,
        )

        send_command(f"{self.domain} where documents.document={doc}")
