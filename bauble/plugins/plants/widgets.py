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
"""Generic widgets"""

from gi.repository import Gtk

from bauble import utils
from bauble.i18n import _
from bauble.view import InfoExpanderMixin
from bauble.view import on_clicked_select

from .model import Taxon


class SynonymsExpander[T: Taxon](InfoExpanderMixin[T], Gtk.Expander):

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
