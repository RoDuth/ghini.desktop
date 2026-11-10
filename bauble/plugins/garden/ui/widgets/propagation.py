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
Propagation widgets and helper functions.
"""

import logging

logger = logging.getLogger(__name__)

from gi.repository import Gtk

from ...propagation import Propagation
from .accession import accession_to_string_matcher


def propagation_to_string_matcher(propagation: Propagation, key: str) -> bool:
    """Helper function to match string or partial string of the pattern
    'PROPAGATIONCODE ACCESSIONCODE Genus species' with a `Propagation`.

    Allows partial matches (e.g. 'Den d', 'Dendr', 'XX D d', '2026 D d',
    `2026S XXX` will all match '2026S/1 XXX.0001 (Dendrobium discolor)').
    Searches are case insensitive.

    :param accession: an Propagation table entry
    :param key: the string to search with

    :return: bool, True if the Species matches the key
    """

    if propagation.code.startswith(key):
        return True

    accession = propagation.get_accession()
    if accession and accession_to_string_matcher(accession, key):
        return True

    parts = key.split()
    if len(parts) > 1 and accession:
        propagation_match = propagation.code.lower().startswith(parts[0])
        accession_match = accession_to_string_matcher(accession, parts[1])
        return propagation_match and accession_match

    return False


def propagation_match_func(
    completion: Gtk.EntryCompletion,
    key: str,
    treeiter: int,
) -> bool:
    """match_func that allows partial matches on propagation code, accession
    code, Genus and species.

    :param completion: the completion to match
    :param key: lowercase string of the entry text
    :param treeiter: the row number for the item to match

    :return: bool, True if the item at the treeiter matches the key
    """
    tree_model = completion.get_model()

    if not tree_model:
        raise AttributeError(f"can't get TreeModel from {completion}")

    propagation = tree_model[treeiter][0]

    if propagation is None:
        return True

    return propagation_to_string_matcher(propagation, key)
