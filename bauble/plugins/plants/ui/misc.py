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
Miscellaneous helpers.
"""
from gi.repository import Gdk
from gi.repository import Gtk

from bauble import prefs
from bauble.ui.views import select_in_search_results

from ..model import Taxon


def on_taxa_clicked(
    _label: Gtk.Label,
    _event: Gdk.Event,
    taxon: Taxon,
) -> None:
    """Function intended for use with :func:`utils.make_label_clickable`

    if the return_accepted_pref is set True then select both the name synonym
    clicked on and its accepted name.
    """
    if prefs.prefs.get(prefs.return_accepted_pref) and taxon.accepted:
        select_in_search_results(taxon.accepted)

    select_in_search_results(taxon)
