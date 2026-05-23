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
Location widgets and helper functions.
"""

from gi.repository import Gtk


def location_match_func(
    completion: Gtk.EntryCompletion,
    key: str,
    treeiter: int,
) -> bool:
    """match_func that allows partial matches string, code or name.

    :param completion: the completion to match
    :param key: lowercase string of the entry text
    :param treeiter: the row number for the item to match

    :return: bool, True if the item at the treeiter matches the key
    """
    tree_model = completion.get_model()

    if not tree_model:
        raise AttributeError(f"can't get TreeModel from {completion}")

    loc = tree_model[treeiter][0]
    if str(loc).lower().startswith(key.lower()):
        return True

    if loc.code.lower().startswith(key.lower()):
        return True

    if loc.name and loc.name.lower().startswith(key.lower()):
        return True

    return False
