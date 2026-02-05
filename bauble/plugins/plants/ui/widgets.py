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
Generic widgets.
"""

import logging

logger = logging.getLogger(__name__)

from collections.abc import Callable
from pathlib import Path
from typing import cast

from gi.repository import GLib
from gi.repository import GObject
from gi.repository import Gtk
from sqlalchemy.orm import Query
from sqlalchemy.orm import Session
from sqlalchemy.orm import object_session

from bauble import utils
from bauble.i18n import _
from bauble.ui.handlers import default_completion_cell_data_func
from bauble.ui.handlers import default_completion_match_func
from bauble.view import InfoExpanderMixin
from bauble.view import on_clicked_select

from ..model import Synonym
from ..model import Taxon


class SynonymsExpander[T: Taxon](InfoExpanderMixin[T], Gtk.Expander):
    """Provides a generic InfoExpander that can be used with any Taxon's search
    view InfoBox.
    """

    def __init__(self) -> None:
        super().__init__()
        self.connect("notify::expanded", self.on_expanded)
        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.box.set_border_width(5)
        self.add(self.box)

    def update(self, row: T) -> None:
        self.set_label(_("Synonyms"))
        self.set_sensitive(False)
        self.box.foreach(self.box.remove)

        if row.accepted is not None:
            self.set_label(_("Accepted name"))
            # create clickable label that will select the synonym
            # in the search results
            ebox = Gtk.EventBox()
            label = Gtk.Label(
                label=row.accepted.string(markup=True, authors=True),
                use_markup=True,
                xalign=0.0,
                yalign=0.5,
            )
            ebox.add(label)
            utils.make_label_clickable(label, on_clicked_select, row.accepted)
            self.box.pack_start(ebox, False, False, 0)
            self.set_sensitive(True)
        elif row.synonyms:
            for syn in sorted(row.synonyms, key=str):
                # create clickable label that will select the synonym
                # in the search results
                ebox = Gtk.EventBox()
                label = Gtk.Label(
                    label=syn.string(markup=True, authors=True),
                    use_markup=True,
                    xalign=0.0,
                    yalign=0.5,
                )
                ebox.add(label)
                utils.make_label_clickable(label, on_clicked_select, syn)
                self.box.pack_start(ebox, False, False, 0)

            self.set_sensitive(True)

        self.show_all()


def _syn_data_func(_column, cell, model, treeiter, _data):
    # avoid using self.session - must be static or wont garbage collect
    val = model[treeiter][0]
    cell.set_property("text", str(val))
    # background color to indicate it's new
    session = object_session(val)
    if session.is_modified(val):
        cell.set_property("foreground", "blue")
    else:
        cell.set_property("foreground", "black")


@Gtk.Template(
    filename=str(Path(__file__).resolve().parent / "synonyms_presenter.ui")
)
class SynonymsPresenter(Gtk.Frame):
    """Provides a generic presenter for adding and removing synonyms that can
    be used with any Taxon editor.

    To use, include in your ``.ui`` file definition or instantiate otherwise
    then call ``init`` on it.  To react to changes connect to the ``changed``
    signal.
    """

    __gtype_name__ = "SynonymsPresenter"
    __gsignals__ = dict = {
        "changed": (GObject.SignalFlags.RUN_FIRST, None, ())
    }

    entry = cast(Gtk.Entry, Gtk.Template.Child())
    scrolled_window = cast(Gtk.ScrolledWindow, Gtk.Template.Child())
    treeview = cast(Gtk.TreeView, Gtk.Template.Child())
    column = cast(Gtk.TreeViewColumn, Gtk.Template.Child())
    cell_renderer = cast(Gtk.CellRendererText, Gtk.Template.Child())
    remove_button = cast(Gtk.Button, Gtk.Template.Child())
    add_button = cast(Gtk.Button, Gtk.Template.Child())
    completion = cast(Gtk.EntryCompletion, Gtk.Template.Child())
    cell = cast(Gtk.CellRendererText, Gtk.Template.Child())

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.model: Taxon
        self.synonym_table: type[Synonym]
        self.session: Session
        self.completions_seed: Callable[[Session, str], Query]
        self._selected: Taxon | None = None
        self.additional: list[Synonym] = []

    def init(
        self,
        model: Taxon,
        synonym_table: type[Synonym],
        session: Session,
        completions_seed: Callable[[Session, str], Query],
    ) -> None:
        """Setup the widget.

        :param model: an instance of the Taxon.
        :param synonym_table: the sqlalchemy ORM table class for synonyms.
        :param session: an sqlalchemy session, should be the same as the editor
            this widget is used in.
        :param completion_seed: a callable that returns an ORM query for use in
            entry completions given the current text.  This will be further
            filtered to exclude the current model and any of its current
            synonyms.  Results will be limited to 20.
        """
        self.model = model
        self.synonym_table = synonym_table
        self.session = session
        self.completions_seed = completions_seed
        self.completion.set_cell_data_func(
            self.cell,
            default_completion_cell_data_func,
        )
        self.completion.set_match_func(default_completion_match_func)

        self.completion.connect("match-selected", self.on_match_selected)
        # self.completion.set_property("text-column", -1)
        self.init_treeview()

        # prevent adding synonyms to synonyms
        if self.model.accepted:
            self.entry.set_placeholder_text(
                _("Already a synonym of %s") % self.model.accepted
            )
            self.set_sensitive(False)

    @Gtk.Template.Callback()
    def on_entry_changed(self, entry) -> None:
        self.add_button.set_sensitive(False)
        self._selected = None
        text = entry.get_text()
        completion = entry.get_completion()
        min_key_length = completion.get_minimum_key_length()
        completion_model = cast(Gtk.ListStore, completion.get_model())
        completion_model.clear()

        if len(text) < min_key_length:
            return

        values = self.syn_get_completions(text)
        for value in values:
            completion_model.append([value])

        # if an exact match select it
        if len(values) == 1 and str(values[0]).lower() == text.lower():
            completion.emit(
                "match-selected",
                completion_model,
                completion_model.get_iter_first(),
            )

    def syn_get_completions(self, text: str) -> list:
        # Skip current synonyms, self and already added synonyms
        if not self.model:
            return []

        result = self.completions_seed(self.session, text)
        ids = [i[0] for i in self.session.query(self.synonym_table.synonym_id)]

        for syn in self.model._synonyms:
            if syn.synonym and syn.synonym.id not in ids:
                ids.append(syn.synonym.id)

        if self.model.id:
            ids.append(self.model.id)

        return result.filter(type(self.model).id.notin_(ids)).limit(20).all()

    def on_match_selected(
        self,
        _completion: Gtk.EntryCompletion,
        liststore: Gtk.ListStore,
        tree_iter: Gtk.TreeIter,
    ) -> bool:
        value = liststore[tree_iter][0]
        self.entry.set_text(str(value))

        sensitive = True
        if value is None:
            sensitive = False

        self.add_button.set_sensitive(sensitive)
        self._selected = value
        return True

    def init_treeview(self) -> None:
        """initialize the Gtk.TreeView"""

        self.column.set_cell_data_func(self.cell_renderer, _syn_data_func)

        utils.clear_model(self.treeview)
        tree_model = Gtk.ListStore(object)

        for synonym in sorted(self.model._synonyms, key=str):
            tree_model.append([synonym])

        self.treeview.set_model(tree_model)

    @Gtk.Template.Callback()
    def on_tree_cursor_changed(self, treeview: Gtk.TreeView) -> None:
        selection = treeview.get_selection()
        _model, treeiter = selection.get_selected()
        self.remove_button.set_sensitive(treeiter is not None)

    @Gtk.Template.Callback()
    def on_add_button_clicked(self, _button: Gtk.Button) -> None:
        """Adds the synonym from the synonym entry to the list of synonyms.

        If the synonym is already considered a synonym, move all its synonyms
        across.
        """
        if not self._selected:
            return

        synonyms = []
        syn = self.synonym_table()
        syn.synonym = self._selected
        synonyms.append(syn)

        for syn in self._selected._synonyms:
            synonyms.append(syn)
            self.additional.append(syn)

        tree_model = cast(Gtk.ListStore, self.treeview.get_model())

        for syn in synonyms:
            setattr(syn, self.model.__tablename__, self.model)
            tree_model.prepend([syn])

        self._selected = None
        self.entry.set_text("")
        self.entry.set_position(-1)
        self.add_button.set_sensitive(False)
        vadjustment = self.scrolled_window.get_vadjustment()
        GLib.idle_add(vadjustment.set_value, vadjustment.get_lower())
        self.emit("changed")

    @Gtk.Template.Callback()
    def on_remove_button_clicked(self, _button):
        """Removes the currently selected synonym from the list of synonyms."""
        path, _col = self.treeview.get_cursor()

        if path is None:
            return

        tree_model = self.treeview.get_model()
        value = tree_model[tree_model.get_iter(path)][0]
        syn_str = str(value.synonym)

        msg = _(
            "Are you sure you want to remove %s as a synonym? \n\n"
            "<i>Note: This will not remove %s from the database.</i>"
        ) % (syn_str, syn_str)
        # for sake of tests
        toplevel = self.get_toplevel()
        parent = None if toplevel is self else toplevel

        if not utils.yes_no_dialog(msg, parent=parent):
            return

        tree_model.remove(tree_model.get_iter(path))
        self.model.synonyms.remove(value.synonym)
        self.session.refresh(value.synonym)

        if value in self.additional:
            self.session.expunge(value)
            self.additional.remove(value)
        elif value in self.session:
            self.session.delete(value)

        self.emit("changed")
