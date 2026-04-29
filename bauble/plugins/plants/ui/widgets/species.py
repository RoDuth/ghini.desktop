# Copyright 2020-2026 Ross Demuth <rossdemuth123@gmail.com>
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
Species widgets and helper functions.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

import traceback
from pathlib import Path
from typing import cast

from gi.repository import GObject
from gi.repository import Gtk
from sqlalchemy import inspect
from sqlalchemy import select
from sqlalchemy.sql import Select

from bauble import db
from bauble import meta
from bauble import utils
from bauble.i18n import _
from bauble.task import queue
from bauble.ui import dialogs
from bauble.ui.presenter import GenericPresenter
from bauble.ui.utils import get_widget_value
from bauble.ui.utils import set_widget_value

from ...genus import Genus
from ...species_model import Species
from ...species_model import infrasp_rank_values
from ...species_model import register_custom_column
from ...species_model import update_all_full_names_task

parent = Path(__file__).resolve().parent


def setup_conservation_fields(*_args) -> None:
    msg = _(
        "Setup custom conservation fields.\n\nYou have 2 fields "
        "available.  To set them up you need to provide a "
        "dictionary that defines the `field_name` as used in "
        "searches, reports, etc., the `display_name` as used in "
        "the editor and the `values` as a tuple or list of the "
        "values it can accept.\n\n Examples are provided, replace "
        "these as needed set them empty to disable."
    )

    custom1_default = (
        "{'field_name': 'nca_status', "
        "'display_name': 'NCA Status', "
        "'short_hand': 'NCA', "
        "'values': ("
        "'Extinct in the wild', "
        "'Critically endangered', "
        "'Endangered', "
        "'Vulnerable', "
        "'Near threatened', "
        "'Special least concern', "
        "'Least concern', "
        "None"
        ")}"
    )
    custom2_default = (
        "{'field_name': 'epbc_status', "
        "'display_name': 'EPBC Status',  "
        "'short_hand': 'EPBC', "
        "'values': ("
        "'Extinct', "
        "'Critically endangered', "
        "'Endangered', "
        "'Vulnerable', "
        "'Conservation dependent', "
        "'Not listed', "
        "None"
        ")}"
    )
    meta.set_value(
        ("_sp_custom1", "_sp_custom2"),
        (custom1_default, custom2_default),
        msg,
    )
    register_custom_column("_sp_custom1")
    register_custom_column("_sp_custom2")
    db.open_conn(db.engine.url)


def update_all_full_names_handler(*_args):
    """Handler to update all the species full names."""

    try:
        queue(update_all_full_names_task())
    except Exception as e:  # pylint: disable=broad-except
        dialogs.message_details_dialog(
            utils.xml_safe(str(e)),
            traceback.format_exc(),
            Gtk.MessageType.ERROR,
        )
        logger.debug(traceback.format_exc())


def species_completions(text: str) -> Select:
    """Given text to search for return an appropriate statement to retrieve
    matching genera.
    """
    query = select(Species).join(Genus)
    hybrid = ""
    epithet = ""
    genus = text.removeprefix("×").removeprefix("+").strip()

    try:
        if text[0] in ["×", "+"]:
            hybrid = text[0]
    except (AttributeError, IndexError):
        pass

    try:
        genus, epithet = genus.split(" ", 1)
        epithet = epithet.strip(" +×'")
    except (AttributeError, ValueError):
        pass

    query = query.where(utils.ilike(Genus.genus, f"{genus}%"))
    if hybrid:
        query = query.where(Genus.hybrid == hybrid)
    if epithet:
        query = query.where(
            utils.ilike(Species.full_name, f"%{genus}%{epithet}%")
        )
    return query.order_by(Species.full_name)


def species_to_string_matcher(
    species: Species,
    key: str,
) -> bool:
    """Helper function to match string or partial string of the pattern
    'Genus species' with a Species

    Allows partial matches (e.g. 'Den d' and 'Dendr' will match
    'Dendrobium discolor').  Searches are case insensitive.

    :param species: a Species table entry
    :param key: the string to search with
    :param sp_path: optional path for model obects to get to the species

    :return: bool, True if the Species matches the key
    """

    if species.full_name and species.full_name.lower().startswith(key.lower()):
        return True

    key = key.lower().removeprefix("×").removeprefix("+").strip()
    key = key.replace(" s. str ", " ", 1).replace(" s. lat. ", " ", 1)
    key_gen, key_sp = (key + " ").split(" ", 1)
    key_sp = key_sp.removeprefix("×").removeprefix("+").strip()

    comp_gen = str(species.genus.epithet).lower()
    comp_sp = species.string(genus=False).lower().strip(" ×+")
    comp_cv = "'" + (species.cultivar_epithet or "").lower()
    comp_trade = "'" + (species.trade_name or "").lower()

    if comp_gen.startswith(key_gen):
        if comp_sp.startswith(key_sp.strip()):
            return True
        if comp_cv.startswith(key_sp.strip()):
            return True
        if comp_trade.startswith(key_sp.strip()):
            return True
    return False


def species_match_func(
    completion: Gtk.EntryCompletion,
    key: str,
    treeiter: Gtk.TreeIter,
) -> bool:
    """match_func that allows partial matches on both Genus and species.

    :param completion: the completion to match
    :param key: lowercase string of the entry text
    :param treeiter: the row number for the item to match
    :param path: optional path for model obects to get to the species

    :return: bool, True if the item at the treeiter matches the key
    """
    tree_model = completion.get_model()

    if not tree_model:
        raise AttributeError(f"can't get TreeModel from {completion}")

    species = tree_model[treeiter][0]

    if not inspect(species).persistent:
        return False

    return species_to_string_matcher(species, key)


def species_cell_data_func(
    column: Gtk.TreeViewColumn,
    renderer: Gtk.CellRendererText,
    model: Gtk.ListStore,
    treeiter: Gtk.TreeIter,
) -> None:
    # pylint: disable=unused-argument
    sp = model[treeiter][0]
    # occassionally the session gets lost and can result in
    # DetachedInstanceErrors. So check first
    if inspect(sp).persistent:
        renderer.set_property(
            "markup",
            f"{sp.markup(authors=True)}  "
            f"(<small>{sp.genus.family}</small>)",
        )


class SpeciesEntry(Gtk.Entry, Gtk.Editable):
    """Custom entry widget for species epithet.

    Allows spaces under a limited set of conditions, converts "*" to the cross
    character ("×") with spaces either side where appropriate.
    """

    __gtype_name__ = "SpeciesEntry"

    def __init__(self) -> None:
        super().__init__()
        self.species_space = False  # do not accept spaces in epithet

    def do_insert_text(self, text: str, _length, position: int) -> int:
        # immediately allow spaces when opening a species for editing or
        # pasting text.
        if any(("×" in text, " (" in text, text[:4] == "sp. ")):
            self.species_space = True

        # discourage capitalising species names
        if position == 0 and text and "×" not in text:
            text = "".join([text[0].lower(), *text[1:]])

        if "*" in text:
            self.species_space = True
            text = text.replace("*", " × ")

            if position == 0:
                text = text.lstrip()
        # provisional names (e.g. 'sp. nov.', 'sp. (OrmeauL.H.Bird AQ435851)')
        full_text = self.get_chars(0, -1)
        if full_text[:3] == "sp.":
            self.species_space = True

        # informal descriptive names (e.g. 'caerulea (Finch Hatton)')
        if text == ("(") and self.species_space is False:
            self.species_space = True
            text = text.replace("(", " (")

        if self.species_space is False:
            text = text.replace(" ", "")

        if text != "":
            # best way to get correct length (accounts for ×)
            length = self.get_buffer().insert_text(position, text, -1)
            new_pos = position + length
            return new_pos
        return position


class InfraspRow(GenericPresenter[Species], Gtk.Widget):

    __gsignals__ = {
        "changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "row-removed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "rank-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(
        self,
        model: Species,
        grid: Gtk.Grid,
        level: int,
    ) -> None:
        super().__init__(model, self)
        self.grid = grid

        self.block_change = True
        self.rank_combo = Gtk.ComboBoxText()
        self.rank_combo.show()
        grid.attach(self.rank_combo, 0, level, 1, 1)
        self.rank_sid = self.rank_combo.connect(
            "changed", self.on_rank_combo_changed
        )
        self.refresh_rank_combo()

        self.epithet_entry = Gtk.Entry(hexpand=True)
        self.epithet_entry.show()
        grid.attach(self.epithet_entry, 1, level, 1, 1)
        self.epithet_entry.connect(
            "changed",
            self.on_non_empty_text_entry_changed,
        )

        self.author_entry = Gtk.Entry(hexpand=True)
        self.author_entry.show()
        grid.attach(self.author_entry, 2, level, 1, 1)
        self.author_entry.connect("changed", self.on_text_entry_changed)

        self.remove_button = Gtk.Button()
        image = Gtk.Image.new_from_icon_name(
            "list-remove-symbolic",
            Gtk.IconSize.BUTTON,
        )
        self.remove_button.set_image(image)
        self.remove_button.show()
        self.remove_button.connect("clicked", self.on_remove_clicked)
        grid.attach(self.remove_button, 3, level, 1, 1)

        self.widgets_to_model_map = {
            self.rank_combo: self.infrasp_rank_attr,
            self.epithet_entry: self.infrasp_epithet_attr,
            self.author_entry: self.infrasp_author_attr,
        }

        self.refresh_all_widgets_from_model()
        self.block_change = False
        self.epithet_entry.emit("changed")

    @property
    def infrasp_rank_attr(self) -> str:
        return f"infrasp{self.row}_rank"

    @property
    def infrasp_epithet_attr(self) -> str:
        return f"infrasp{self.row}"

    @property
    def infrasp_author_attr(self) -> str:
        return f"infrasp{self.row}_author"

    @property
    def row(self) -> int:
        return self.grid.child_get_property(
            self.rank_combo,
            "top-attach",
        )

    def update(self) -> None:
        if not self.block_change:
            self.emit("changed")

    def set_problem(self, problem: str) -> None:
        if getattr(self.model, self.infrasp_rank_attr):
            self.add_problem(problem, self.rank_combo)

        if getattr(self.model, self.infrasp_epithet_attr):
            self.add_problem(problem, self.epithet_entry)

        if getattr(self.model, self.infrasp_author_attr):
            self.add_problem(problem, self.author_entry)

    def on_rank_combo_changed(self, combo: Gtk.ComboBoxText) -> None:
        self.on_combobox_changed(combo)
        self.emit("rank-changed")

    def refresh_rank_combo(self) -> None:
        start = get_widget_value(self.rank_combo)

        self.rank_combo.handler_block(self.rank_sid)
        self.rank_combo.remove_all()

        if self.row > 1:
            highest_rank = self.model.get_infrasp(self.row - 1)[0]
            list_ranks = list(infrasp_rank_values.items())
            index = list_ranks.index(
                (highest_rank or None, highest_rank or "")
            )
            for key, value in list_ranks[index + 1 :]:
                self.rank_combo.append(key, value)
        else:
            for key, value in infrasp_rank_values.items():
                self.rank_combo.append(key, value)

        if start:
            set_widget_value(self.rank_combo, start)

        self.rank_combo.handler_unblock(self.rank_sid)

        if start:
            self.rank_combo.emit("changed")

    def on_remove_clicked(self, _button: Gtk.Button) -> None:
        self.emit("row-removed")
        self.destroy()

    def refresh(self) -> None:
        self.widgets_to_model_map = {
            self.rank_combo: self.infrasp_rank_attr,
            self.epithet_entry: self.infrasp_epithet_attr,
            self.author_entry: self.infrasp_author_attr,
        }
        self.block_change = True
        self.refresh_rank_combo()
        self.epithet_entry.emit("changed")
        self.block_change = False
        # allow last to emit
        self.author_entry.emit("changed")


@Gtk.Template(filename=str(parent / "infrasp_presenter.ui"))
class InfraspecificPresenter(Gtk.Frame):

    __gtype_name__ = "InfraspecificPresenter"

    __gsignals__ = {
        "changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    grid = cast(Gtk.Grid, Gtk.Template.Child())
    add_button = cast(Gtk.Button, Gtk.Template.Child())

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[InfraspRow] = []
        self.model: Species
        self.block_change = False

    def init(self, model: Species) -> None:
        self.model = model
        for i in range(1, 5):
            if any(model.get_infrasp(i)):
                self.add_row()
            else:
                break

    @property
    def can_commit(self) -> bool:
        for row in self.rows:
            if row.problems:
                return False
        return True

    def set_problem(self, problem: str) -> None:
        """Set a global problem - all rows, all widgets"""
        for row in self.rows:
            row.set_problem(problem)

    def unset_problem(self, problem: str) -> None:
        """Unsets a global problem - all rows, all widgets"""
        for row in self.rows:
            row.remove_problem(problem, None)

    def clear(self) -> None:
        for row in reversed(self.rows):
            self.on_row_removed(row)

    @Gtk.Template.Callback()
    def on_add_clicked(self, _button: Gtk.Button) -> None:
        self.add_row()

    def add_row(self) -> InfraspRow:
        row = InfraspRow(self.model, self.grid, len(self.rows) + 1)
        row.connect("row-removed", self.on_row_removed)
        row.connect("changed", self.on_row_changed)
        row.connect("rank-changed", self.on_rank_changed)
        self.rows.append(row)

        if len(self.rows) == 4:
            self.add_button.set_sensitive(False)

        return row

    def on_row_removed(self, row: InfraspRow) -> None:
        self.add_button.set_sensitive(True)
        level = row.row
        self.rows.remove(row)
        self.grid.remove_row(level)

        self.block_change = True
        for i in self.rows[level - 1 :]:
            i.refresh()
        self.block_change = False

        self.model.set_infrasp(len(self.rows) + 1, None, None, None)

        self.emit("changed")

    def on_row_changed(self, _row: InfraspRow) -> None:
        if self.block_change:
            return
        # bubble up
        self.emit("changed")

    def on_rank_changed(self, row: InfraspRow) -> None:
        if len(self.rows) > row.row:
            self.rows[row.row].refresh_rank_combo()
