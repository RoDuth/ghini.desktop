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

from functools import partial
from pathlib import Path
from typing import cast

from gi.repository import Gtk

from bauble import utils
from bauble.i18n import _
from bauble.ui.views import InfoBox
from bauble.ui.views import InfoExpander
from bauble.ui.views import LinksExpander
from bauble.ui.views import PropertiesExpander
from bauble.ui.views import on_clicked_select
from bauble.ui.views import select_in_search_results

from ...plants.ui.misc import on_taxa_clicked
from ..propagation import SOURCE_MATERIALS
from ..propagation import SOURCE_TYPES
from ..propagation import Propagation

parent = Path(__file__).resolve().parent


on_clicked_traverse_select = utils.generate_on_clicked(
    partial(select_in_search_results, expand_current_first=True)
)


@Gtk.Template(filename=str(parent / "propagation_expander.ui"))
class GeneralPropagationExpander(
    InfoExpander[Propagation],
    Gtk.Expander,
):
    """General expander for the PropagationInfoBox"""

    __gtype_name__ = "GeneralPropagationExpander"

    code_label = cast(Gtk.Label, Gtk.Template.Child())
    name_label = cast(Gtk.Label, Gtk.Template.Child())
    source_plants_box = cast(Gtk.Box, Gtk.Template.Child())
    type_label = cast(Gtk.Label, Gtk.Template.Child())
    propagator_label = cast(Gtk.Label, Gtk.Template.Child())
    date_label = cast(Gtk.Label, Gtk.Template.Child())
    media_label = cast(Gtk.Label, Gtk.Template.Child())
    container_label = cast(Gtk.Label, Gtk.Template.Child())
    location_label = cast(Gtk.Label, Gtk.Template.Child())
    notes_label = cast(Gtk.Label, Gtk.Template.Child())
    quantity_label = cast(Gtk.Label, Gtk.Template.Child())
    success_label = cast(Gtk.Label, Gtk.Template.Child())
    available_label = cast(Gtk.Label, Gtk.Template.Child())
    source_for_box = cast(Gtk.Box, Gtk.Template.Child())

    def __init__(self) -> None:
        super().__init__(label=_("General"))
        self.connect("notify::expanded", self.on_expanded)

    def update(self, row: Propagation) -> None:
        self.code_label.set_markup(
            f"<big>{utils.xml_safe(str(row.code))}</big>"
        )
        self.name_label.set_markup(
            row.species.string(markup=True, authors=True)
        )

        utils.make_label_clickable(
            self.name_label,
            on_taxa_clicked,
            row.species,
        )

        self.update_source_plants(row)

        self.type_label.set_text(row.prop_type.name)
        self.propagator_label.set_text(row.propagator or "")
        self.date_label.set_text(utils.date_string(row.date) or "")
        self.media_label.set_text(row.media or "")
        self.container_label.set_text(row.container or "")
        self.location_label.set_text(row.location or "")
        self.notes_label.set_text(row.prop_notes or "")
        self.quantity_label.set_text(str(row.quantity))
        self.success_label.set_text(f"{row.percent_success:.2f}%")
        self.available_label.set_text(str(row.unused))

        self.update_source_for(row)

    def update_source_plants(self, row: Propagation) -> None:

        for label in self.source_plants_box.get_children():
            label.destroy()

        for plant_source in row.plant_sources:
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
            event_box = Gtk.EventBox()
            plant = plant_source.plant
            label = Gtk.Label(label=str(plant))
            event_box.add(label)
            utils.make_label_clickable(
                label,
                on_clicked_select,
                plant_source.plant,
            )
            label.set_tooltip_markup(
                plant.accession.species_str(markup=True, authors=True)
            )
            box.add(event_box)

            type_ = SOURCE_TYPES.get(plant_source.source_type)
            material = SOURCE_MATERIALS.get(plant_source.source_material)
            box.add(Gtk.Label(label=f" ({material} - {type_})"))
            self.source_plants_box.add(box)

        self.source_plants_box.show_all()

    def update_source_for(self, row: Propagation) -> None:

        for label in self.source_for_box.get_children():
            label.destroy()

        for accession in row.accessions:
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
            event_box = Gtk.EventBox()
            label = Gtk.Label(label=str(accession))
            event_box.add(label)
            utils.make_label_clickable(
                label,
                on_clicked_traverse_select,
                accession,
            )
            label.set_tooltip_markup(
                accession.species_str(markup=True, authors=True)
            )
            box.add(event_box)
            self.source_for_box.add(box)

        self.source_for_box.show_all()


class PropagationInfoBox(InfoBox[Propagation]):
    """an InfoBox for a Propagation table row"""

    def __init__(self) -> None:
        super().__init__()
        self.add_expander(GeneralPropagationExpander())
        self.add_expander(LinksExpander("notes"))
        self.add_expander(PropertiesExpander())
