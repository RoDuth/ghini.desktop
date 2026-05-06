# Copyright 2008-2010 Brett Adams
# Copyright 2015 Mario Frasca <mario@anche.no>.
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
Location GUI search view components.
"""
from pathlib import Path
from typing import cast

from gi.repository import Gtk
from sqlalchemy import select

from bauble import db
from bauble import prefs
from bauble import utils
from bauble.i18n import _
from bauble.ui.views import Action
from bauble.ui.views import InfoBox
from bauble.ui.views import InfoExpander
from bauble.ui.views import LinksExpander
from bauble.ui.views import PropertiesExpander
from bauble.ui.views import on_clicked_search
from bauble.utils.geo import KMLMapCallbackFunctor
from bauble.utils.geo import get_approx_area_from_geojson_sqm

from ..location import LOC_KML_MAP_PREFS
from ..location import Location
from ..location import add_plants_callback
from ..location import edit_callback
from ..location import remove_callback

parent = Path(__file__).resolve().parent


@Gtk.Template(filename=str(parent / "location_expander.ui"))
class GeneralLocationExpander(
    InfoExpander[Location],
    Gtk.Expander,
):
    """General expander for the PlantInfoBox"""

    __gtype_name__ = "GeneralLocationExpander"

    name_label = cast(Gtk.Label, Gtk.Template.Child())
    num_plants_label = cast(Gtk.Label, Gtk.Template.Child())
    geojson_type_label = cast(Gtk.Label, Gtk.Template.Child())
    approx_area_label = cast(Gtk.Label, Gtk.Template.Child())

    def __init__(self) -> None:
        super().__init__(label=_("General"))
        self.connect("notify::expanded", self.on_expanded)

    def update(self, row: Location) -> None:
        utils.make_label_clickable(
            self.num_plants_label,
            on_clicked_search,
            f"plant where location.code = {row.code}",
        )

        self.num_plants_label.set_label(str(len(row.plants)))
        self.name_label.set_markup(f"<big>{utils.xml_safe(str(row))}</big>")

        # NOTE don't load geojson from the row or history will always record
        # an unpdate and _last_updated will always change when a note is edited
        # (e.g. `shape = row.geojson...`) instead use a temp session
        with db.engine.begin() as connection:
            table = Location.__table__
            stmt = select([table.c.geojson]).where(table.c.id == row.id)
            geojson = connection.execute(stmt).scalar()

        shape = ""
        approx_area = ""

        if geojson:
            shape = geojson.get("type", "")
            if shape == "Polygon":
                area = get_approx_area_from_geojson_sqm(geojson)
                approx_area = f"{area:.2f} m²"

        self.geojson_type_label.set_label(shape)
        self.approx_area_label.set_label(approx_area)


class DescriptionExpander(
    InfoExpander[Location],
    Gtk.Expander,
):
    """The location description"""

    def __init__(self) -> None:
        super().__init__(label=_("Description"))
        scrolled_window = Gtk.ScrolledWindow()
        self.description_text_view = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD)
        scrolled_window.add(self.description_text_view)
        self.add(scrolled_window)

    def update(self, row: Location) -> None:
        if row.description is None:
            self.set_expanded(False)
            self.set_sensitive(False)
        else:
            self.set_expanded(True)
            self.set_sensitive(True)
            buffer = self.description_text_view.get_buffer()
            buffer.set_text(str(row.description))


class LocationInfoBox(InfoBox[Location]):
    """an InfoBox for a Location table row"""

    def __init__(self) -> None:
        super().__init__()
        self.add_expander(GeneralLocationExpander())
        self.add_expander(DescriptionExpander())
        self.add_expander(LinksExpander("notes"))
        self.add_expander(PropertiesExpander())


map_kml_callback = KMLMapCallbackFunctor(
    prefs.prefs.get(LOC_KML_MAP_PREFS, str(parent / "loc.kml"))
)


edit_action = Action(
    "loc_edit", _("_Edit"), callback=edit_callback, accelerator="<ctrl>e"
)

add_plant_action = Action(
    "loc_add_plant",
    _("_Add plants"),
    callback=add_plants_callback,
    accelerator="<ctrl>k",
)

remove_action = Action(
    "loc_remove",
    _("_Delete"),
    callback=remove_callback,
    accelerator="<ctrl>Delete",
    multiselect=True,
)

map_action = Action(
    "loc_map",
    _("Show in _map"),
    callback=map_kml_callback,
    accelerator="<ctrl>m",
    multiselect=True,
)

loc_context_menu = [edit_action, add_plant_action, remove_action, map_action]
