# Copyright 2021-2026 Ross Demuth <rossdemuth123@gmail.com>
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
Accession widgets and helper functions.
"""

import logging

logger = logging.getLogger(__name__)

import re

from gi.repository import Gtk
from sqlalchemy.orm.exc import DetachedInstanceError

from ...accession import Accession


def accession_completion_cell_data_func(
    column: Gtk.TreeViewColumn,
    renderer: Gtk.CellRenderer,
    model: Gtk.ListStore,
    treeiter: Gtk.TreeIter,
) -> None:
    # pylint: disable=unused-argument
    value = model[treeiter][0]

    try:
        string = f"{value} ({value.species})"
    except DetachedInstanceError as e:
        # object may be detached from the session when editor is destroyed
        logger.debug("%s(%s)", type(e).__name__, str(e))
        string = ""

    renderer.set_property("text", string)


def accession_to_string_matcher(accession: Accession, key: str) -> bool:
    """Helper function to match string or partial string of the pattern
    'ACCESSIONCODE Genus species' with an Accession.

    Allows partial matches (e.g. 'Den d', 'Dendr', 'XX D d' will all match
    'XXX.0001 (Dendrobium discolor)').  Searches are case insensitive.

    :param accession: an Accession table entry
    :param key: the string to search with

    :return: bool, True if the Species matches the key
    """
    if accession.code.lower().startswith(key):
        return True

    full_name = (accession.species.full_name or "").lower()

    if full_name.startswith(key.lower()):
        return True

    pattern = f"^{'.* '.join(key.lower().split())}.*$"
    string_w_acc = f"{accession.code.lower()} {full_name}"
    return any((re.match(pattern, string_w_acc), re.match(pattern, full_name)))


def accession_match_func(
    completion: Gtk.EntryCompletion,
    key: str,
    treeiter: int,
) -> bool:
    """match_func that allows partial matches on both accession code,
    Genus and species.

    :param completion: the completion to match
    :param key: lowercase string of the entry text
    :param treeiter: the row number for the item to match

    :return: bool, True if the item at the treeiter matches the key
    """
    tree_model = completion.get_model()

    if not tree_model:
        raise AttributeError(f"can't get TreeModel from {completion}")

    accession = tree_model[treeiter][0]
    return accession_to_string_matcher(accession, key)
