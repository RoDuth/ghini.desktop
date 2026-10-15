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
Propagation GUI search view components.
"""
import logging

logger = logging.getLogger(__name__)
from pathlib import Path
from typing import cast

from gi.repository import Gtk

from bauble.i18n import _
from bauble.ui.views import InfoBox
from bauble.ui.views import InfoExpander
from bauble.ui.views import LinksExpander
from bauble.ui.views import PropertiesExpander

from ..propagation import Propagation

parent = Path(__file__).resolve().parent


@Gtk.Template(filename=str(parent / "propagation_expander.ui"))
class GeneralPropagationExpander(
    InfoExpander[Propagation],
    Gtk.Expander,
):
    """General expander for the PropagationInfoBox"""

    __gtype_name__ = "GeneralPropagationExpander"

    label = cast(Gtk.Label, Gtk.Template.Child())

    def __init__(self) -> None:
        super().__init__(label=_("General"))
        self.connect("notify::expanded", self.on_expanded)

    def update(self, row: Propagation) -> None:
        self.label.set_label(str(row))


class PropagationInfoBox(InfoBox[Propagation]):
    """an InfoBox for a Propagation table row"""

    def __init__(self) -> None:
        super().__init__()
        self.add_expander(GeneralPropagationExpander())
        self.add_expander(LinksExpander("notes"))
        self.add_expander(PropertiesExpander())
