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
Geography GUI search view components.
"""
from pathlib import Path
from typing import cast

from gi.repository import Gtk

from bauble import prefs
from bauble import utils
from bauble.i18n import _
from bauble.ui.views import Action
from bauble.ui.views import InfoBox
from bauble.ui.views import InfoExpander
from bauble.ui.views import PropertiesExpander
from bauble.ui.views import on_clicked_select
from bauble.utils.geo import KMLMapCallbackFunctor

from ..geography import Geography
from .widgets import DistributionMapEventBox

GEO_KML_MAP_PREFS = "kml_templates.geography"
"""pref for path to a custom mako kml template."""

parent = Path(__file__).resolve().parent


@Gtk.Template(filename=str(parent / "geography_expander.ui"))
class GeneralGeographyExpander(
    InfoExpander[Geography],
    Gtk.Expander,
):

    __gtype_name__ = "GeneralGeographyExpander"

    GEO_AREAS_EXPANDED_PREF = "infobox.species_geo_areas_expanded"

    general_box = cast(Gtk.Box, Gtk.Template.Child())
    name_label = cast(Gtk.Label, Gtk.Template.Child())
    map_event_box = cast(DistributionMapEventBox, Gtk.Template.Child())
    level_label = cast(Gtk.Label, Gtk.Template.Child())
    code_label = cast(Gtk.Label, Gtk.Template.Child())
    iso_code_label = cast(Gtk.Label, Gtk.Template.Child())
    parent_label = cast(Gtk.Label, Gtk.Template.Child())
    children_box = cast(Gtk.Box, Gtk.Template.Child())
    geojson_type_label = cast(Gtk.Label, Gtk.Template.Child())
    approx_area_label = cast(Gtk.Label, Gtk.Template.Child())
    label_name_label = cast(Gtk.Label, Gtk.Template.Child())

    def __init__(self) -> None:
        super().__init__(label=_("General"))
        self.connect("notify::expanded", self.on_expanded)

    def update(self, row: Geography) -> None:
        self.map_event_box.update(row)

        self.name_label.set_label(row.name)
        level = ["Continent", "Region", "Bot. Country", "Unit"][row.level - 1]
        self.level_label.set_label(f"{level} ({row.level})")
        self.code_label.set_label(row.code)
        self.iso_code_label.set_label(row.iso_code or "")
        self.parent_label.set_label(str(row.parent or ""))

        if row.parent:
            utils.make_label_clickable(
                self.parent_label, on_clicked_select, row.parent
            )

        self.update_children(row)

        shape = row.geojson.get("type", "") if row.geojson else ""
        self.geojson_type_label.set_label(shape)
        self.approx_area_label.set_label(f"{row.approx_area:,.2f} km²")
        self.label_name_label.set_label(row.label_name or "")

    def update_children(self, row: Geography) -> None:
        self.children_box.foreach(self.children_box.remove)

        for geo in row.children:
            child_lbl = Gtk.Label()
            child_lbl.set_xalign(0)
            child_lbl.set_text(str(geo))
            eventbox = Gtk.EventBox()
            eventbox.add(child_lbl)
            self.children_box.pack_start(eventbox, True, True, 0)
            utils.make_label_clickable(child_lbl, on_clicked_select, geo)
        self.children_box.show_all()


class GeographyInfoBox(InfoBox):
    """General info."""

    def __init__(self):
        super().__init__()
        self.add_expander(GeneralGeographyExpander())
        self.add_expander(PropertiesExpander())


map_kml_callback = KMLMapCallbackFunctor(
    prefs.prefs.get(GEO_KML_MAP_PREFS, str(parent / "geo.kml"))
)

map_action = Action(
    "geo_map",
    _("Show in _Map"),
    callback=map_kml_callback,
    accelerator="<ctrl>m",
    multiselect=True,
)

geography_context_menu = [map_action]
