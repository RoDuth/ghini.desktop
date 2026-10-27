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
Genus widgets and helper functions.
"""
from gi.repository import Gtk
from sqlalchemy import inspect
from sqlalchemy import select
from sqlalchemy.sql import Select

from bauble import utils

from ...genus import Genus


def genus_completions(text: str) -> Select:
    """Given text to search for return an appropriate statement to retrieve
    matching genera.
    """
    query = select(Genus)
    hybrid = ""
    genus = text.removeprefix("×").removeprefix("+").strip()
    try:
        if text[0] in ["×", "+"]:
            hybrid = text[0]
    except (AttributeError, IndexError):
        pass
    query = query.where(utils.ilike(Genus.genus, f"{genus}%"))
    if hybrid:
        query = query.where(Genus.hybrid == hybrid)
    return query.order_by(Genus.epithet)


def genus_to_string_matcher(
    genus: Genus,
    key: str,
) -> bool:
    """Helper function to match string or partial string.

    :param genus: a Genus table entry
    :param key: the string to search with
    :param gen_path: optional path for model obects to get to the genus

    :return: bool, True if the genus matches the key
    """
    key = key.removeprefix("× ").removeprefix("+ ").lower()
    return genus.genus.lower().startswith(key)


def genus_match_func(
    completion: Gtk.EntryCompletion,
    key: str,
    treeiter: Gtk.TreeIter,
) -> bool:
    """match_func that allows partial matches.

    :param completion: the completion to match
    :param key: lowercase string of the entry text
    :param treeiter: the row number for the item to match
    :param gen_path: optional path for model obects to get to the genus

    :return: bool, True if the item at the treeiter matches the key
    """
    tree_model = completion.get_model()
    if not tree_model:
        raise AttributeError(f"can't get TreeModel from {completion}")
    genus = tree_model[treeiter][0]
    if not inspect(genus).persistent:
        return False
    return genus_to_string_matcher(genus, key)


def genus_cell_data_func(
    column: Gtk.TreeViewColumn,
    renderer: Gtk.CellRendererText,
    model: Gtk.ListStore,
    treeiter: Gtk.TreeIter,
) -> None:
    # pylint: disable=unused-argument
    value = model[treeiter][0]
    # occassionally the session gets lost and can result in
    # DetachedInstanceErrors. So check first
    if inspect(value).persistent:
        renderer.set_property(
            "markup",
            f"{value.markup(authors=True)}  <small>({value.family})</small>",
        )
