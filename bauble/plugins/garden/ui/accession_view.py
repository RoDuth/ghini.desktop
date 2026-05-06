# Copyright 2008-2010 Brett Adams
# Copyright 2015-2016 Mario Frasca <mario@anche.no>.
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
Accession GUI search view components.
"""
from pathlib import Path
from typing import cast

from gi.repository import Gtk

from bauble import prefs
from bauble import utils
from bauble.i18n import _
from bauble.plugins.plants.ui.misc import on_taxa_clicked
from bauble.ui.views import Action
from bauble.ui.views import InfoBox
from bauble.ui.views import InfoExpander
from bauble.ui.views import LinksExpander
from bauble.ui.views import PropertiesExpander
from bauble.ui.views import on_clicked_search
from bauble.ui.views import on_clicked_select
from bauble.utils.geo import KMLMapCallbackFunctor

from ..accession import Accession
from ..accession import add_plants_callback
from ..accession import edit_callback
from ..accession import latitude_to_dms
from ..accession import longitude_to_dms
from ..accession import prov_type_values
from ..accession import recvd_type_values
from ..accession import remove_callback
from ..accession import wild_prov_status_values
from ..source import COLLECTION_KML_MAP_PREF
from ..source import Collection

parent = Path(__file__).resolve().parent


@Gtk.Template(filename=str(parent / "accession_expander.ui"))
class GeneralAccessionExpander(
    InfoExpander[Accession],
    Gtk.Expander,
):
    """Generic information about an accession like number of clones, provenance
    type, wild provenance type, speciess
    """

    __gtype_name__ = "GeneralAccessionExpander"

    code_label = cast(Gtk.Label, Gtk.Template.Child())
    name_label = cast(Gtk.Label, Gtk.Template.Child())
    supplied_name_label = cast(Gtk.Label, Gtk.Template.Child())
    num_plants_label = cast(Gtk.Label, Gtk.Template.Child())
    provenance_label = cast(Gtk.Label, Gtk.Template.Child())
    date_accd_label = cast(Gtk.Label, Gtk.Template.Child())
    date_received_label = cast(Gtk.Label, Gtk.Template.Child())
    quantity_recvd_label = cast(Gtk.Label, Gtk.Template.Child())
    received_type_label = cast(Gtk.Label, Gtk.Template.Child())
    purchase_price_label = cast(Gtk.Label, Gtk.Template.Child())
    private_image = cast(Gtk.Image, Gtk.Template.Child())
    intended_locations_label = cast(Gtk.Label, Gtk.Template.Child())
    living_plants_label = cast(Gtk.Label, Gtk.Template.Child())

    def __init__(self) -> None:
        super().__init__(label=_("General"))
        self.connect("notify::expanded", self.on_expanded)

    def update(self, row: Accession) -> None:
        self.code_label.set_markup(
            f"<big>{utils.xml_safe(str(row.code))}</big>"
        )

        self.name_label.set_markup(row.species_str(markup=True))

        utils.make_label_clickable(
            self.name_label,
            on_taxa_clicked,
            row.species,
        )

        self.supplied_name_label.set_label(row.supplied_name or "")
        self.num_plants_label.set_label(str(len(row.plants)))

        utils.make_label_clickable(
            self.num_plants_label,
            on_clicked_search,
            f'plant where accession.code = "{row.code}"',
        )

        self.update_provenance(row)
        self.update_dates(row)

        self.quantity_recvd_label.set_label(str(row.quantity_recvd or ""))
        self.received_type_label.set_label(recvd_type_values[row.recvd_type])

        price_str = ""
        if row.purchase_price:
            price_str = f"{row.purchase_price / 100:.2f} {row.price_unit}"
        self.purchase_price_label.set_label(price_str)

        icon = None
        if row.private:
            icon = "dialog-password-symbolic"
        self.private_image.set_from_icon_name(icon, Gtk.IconSize.MENU)

        self.update_locations(row)

    def update_locations(self, row: Accession) -> None:
        plant_locations: dict[str, int] = {}
        for plant in row.plants:
            if plant.quantity == 0:
                continue
            qty = plant_locations.setdefault(plant.location, 0)
            plant_locations[plant.location] = qty + plant.quantity

        string = "0"
        if plant_locations:
            strs = []
            for location, quantity in plant_locations.items():
                strs.append(
                    _("%(quantity)s in %(location)s")
                    % {"quantity": quantity, "location": str(location)}
                )
            string = "\n".join(strs)

        self.living_plants_label.set_label(string)

        locations_str = "\n".join(
            f"{i.location} : {i.quantity}" for i in row.intended_locations
        )
        self.intended_locations_label.set_label(locations_str)

    def update_provenance(self, row: Accession) -> None:
        prov_str = dict(prov_type_values)[row.prov_type]
        if row.prov_type == "Wild" and row.wild_prov_status:
            prov_status = dict(wild_prov_status_values)[row.wild_prov_status]
            prov_str += f" ({prov_status})"

        self.provenance_label.set_label(prov_str)

    def update_dates(self, row: Accession) -> None:
        self.date_accd_label.set_label(utils.date_string(row.date_accd))

        if row.date_accd:
            date_str = utils.date_string(row.date_accd)
            utils.make_label_clickable(
                self.date_accd_label,
                on_clicked_search,
                f"accession where date_accd on {date_str}",
            )

        self.date_received_label.set_label(utils.date_string(row.date_recvd))

        if row.date_recvd:
            date_str = utils.date_string(row.date_accd)
            utils.make_label_clickable(
                self.date_received_label,
                on_clicked_search,
                f"accession where date_recvd on {date_str}",
            )


@Gtk.Template(filename=str(parent / "source_expander.ui"))
class SourceExpander(
    InfoExpander[Accession],
    Gtk.Expander,
):

    __gtype_name__ = "SourceExpander"

    source_name_label = cast(Gtk.Label, Gtk.Template.Child())
    source_name_data_label = cast(Gtk.Label, Gtk.Template.Child())
    sources_code_label = cast(Gtk.Label, Gtk.Template.Child())
    sources_code_data_label = cast(Gtk.Label, Gtk.Template.Child())
    source_notes_label = cast(Gtk.Label, Gtk.Template.Child())
    source_notes_data_label = cast(Gtk.Label, Gtk.Template.Child())
    parent_plant_label = cast(Gtk.Label, Gtk.Template.Child())
    parent_plant_eventbox = cast(Gtk.EventBox, Gtk.Template.Child())
    parent_plant_data_label = cast(Gtk.Label, Gtk.Template.Child())
    propagation_label = cast(Gtk.Label, Gtk.Template.Child())
    propagation_data_label = cast(Gtk.Label, Gtk.Template.Child())
    collection_seperator = cast(Gtk.Separator, Gtk.Template.Child())
    collection_expander = cast(Gtk.Expander, Gtk.Template.Child())
    latitude_label = cast(Gtk.Label, Gtk.Template.Child())
    longitude_label = cast(Gtk.Label, Gtk.Template.Child())
    datum_label = cast(Gtk.Label, Gtk.Template.Child())
    elevavation_label = cast(Gtk.Label, Gtk.Template.Child())
    collection_region_label = cast(Gtk.Label, Gtk.Template.Child())
    collector_label = cast(Gtk.Label, Gtk.Template.Child())
    collection_date_label = cast(Gtk.Label, Gtk.Template.Child())
    collectors_code_label = cast(Gtk.Label, Gtk.Template.Child())
    locale_label = cast(Gtk.Label, Gtk.Template.Child())
    habitat_textview = cast(Gtk.TextView, Gtk.Template.Child())
    collection_notes_textview = cast(Gtk.TextView, Gtk.Template.Child())

    def __init__(self) -> None:
        super().__init__(label=_("Source"))
        self.connect("notify::expanded", self.on_expanded)

        self.source_detail_widgets = [
            self.source_name_label,
            self.source_name_data_label,
        ]
        self.source_code_widgets = [
            self.sources_code_label,
            self.sources_code_data_label,
        ]
        self.source_notes_widgets = [
            self.source_notes_label,
            self.source_notes_data_label,
        ]
        self.plt_prop_widgets = [
            self.parent_plant_label,
            self.parent_plant_eventbox,
        ]
        self.prop_widgets = [
            self.propagation_label,
            self.propagation_data_label,
        ]
        self.collection_widgets = [
            self.collection_expander,
            self.collection_seperator,
        ]

        self.display_widgets = [
            *self.source_detail_widgets,
            *self.source_code_widgets,
            *self.source_notes_widgets,
            *self.plt_prop_widgets,
            *self.prop_widgets,
            *self.collection_widgets,
        ]

    def update(self, row: Accession) -> None:
        utils.hide_widgets(self.display_widgets)

        if row.source:
            self.set_sensitive(True)
        else:
            self.set_sensitive(False)
            return

        self.update_source(row)
        self.update_propagation(row)

        if row.source.collection:
            utils.unhide_widgets(self.collection_widgets)
            self.collection_expander.set_expanded(True)
            self.update_collection(row.source.collection)

    def update_source(self, row: Accession) -> None:
        if row.source.source_detail:
            utils.unhide_widgets(self.source_detail_widgets)
            self.source_name_data_label.set_label(
                str(row.source.source_detail)
            )

            utils.make_label_clickable(
                self.source_name_data_label,
                on_clicked_select,
                row.source.source_detail,
            )

        if row.source.sources_code:
            utils.unhide_widgets(self.source_code_widgets)
            self.sources_code_data_label.set_label(
                str(row.source.sources_code)
            )

        if row.source.notes:
            utils.unhide_widgets(self.source_notes_widgets)
            self.source_notes_data_label.set_label(str(row.source.notes))

    def update_propagation(self, row: Accession) -> None:
        prop_str = ""
        if row.source.plant_propagation:
            utils.unhide_widgets(self.plt_prop_widgets)
            self.parent_plant_data_label.set_label(
                str(row.source.plant_propagation.plant),
            )
            prop_str = row.source.plant_propagation.get_summary(partial=2)
            utils.make_label_clickable(
                self.parent_plant_data_label,
                on_clicked_select,
                row.source.plant_propagation.plant,
            )

        if row.source.propagation:
            prop_str = row.source.propagation.get_summary()

        self.propagation_data_label.set_label(prop_str)

        if prop_str:
            utils.unhide_widgets(self.prop_widgets)

    def update_collection(self, collection: Collection) -> None:
        self.locale_label.set_label(collection.locale or "")
        self.datum_label.set_label(collection.gps_datum or "")

        geo_accy = ""
        if collection.geo_accy:
            geo_accy = f"(+/- {collection.geo_accy}m)"

        lat_str = ""
        if collection.latitude is not None:
            direct, degs, mins, secs = latitude_to_dms(collection.latitude)
            lat_str = (
                f"{collection.latitude} "
                f"({direct} {degs}°{mins}'{secs}\") {geo_accy}"
            )
        self.latitude_label.set_label(lat_str)

        long_str = ""
        if collection.longitude is not None:
            direct, degs, mins, secs = longitude_to_dms(collection.longitude)
            long_str = (
                f"{collection.longitude} "
                f"({direct} {degs}°{mins}'{secs}\") {geo_accy}"
            )
        self.longitude_label.set_label(long_str)

        elevation = ""
        if collection.elevation:
            elevation = f"{collection.elevation}m"
            if collection.elevation_accy:
                elevation += f" (+/- {collection.elevation_accy}m)"
        self.elevavation_label.set_label(elevation)

        region = ""
        if collection.region:
            region = f"{collection.region.name} ({collection.region.code})"
            utils.make_label_clickable(
                self.collection_region_label,
                on_clicked_search,
                "accession where source.collection.region.code = "
                f"{collection.region.code}",
            )
        self.collection_region_label.set_label(region)

        self.collector_label.set_label(collection.collector or "")
        if collection.collector:
            utils.make_label_clickable(
                self.collector_label,
                on_clicked_search,
                "accession where source.collection.collector = "
                f"'{collection.collector}'",
            )

        date_str = utils.date_string(collection.date)
        self.collection_date_label.set_label(date_str)
        if collection.date:
            utils.make_label_clickable(
                self.collection_date_label,
                on_clicked_search,
                f"accession where source.collection.date on {date_str}",
            )

        self.collectors_code_label.set_label(collection.collectors_code or "")
        buffer = self.habitat_textview.get_buffer()
        buffer.set_text(collection.habitat or "")
        buffer = self.collection_notes_textview.get_buffer()
        buffer.set_text(collection.notes or "")


class VouchersExpander(
    InfoExpander[Accession],
    Gtk.Expander,
):
    """The accession's vouchers"""

    def __init__(self) -> None:
        super().__init__(label=_("Vouchers"))
        self.connect("notify::expanded", self.on_expanded)
        self.vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.vbox.set_border_width(5)
        self.add(self.vbox)

    def update(self, row: Accession) -> None:

        for kid in self.vbox.get_children():
            self.vbox.remove(kid)

        if row.vouchers:
            self.set_sensitive(True)
        else:
            self.set_sensitive(False)
            return

        parents = [v for v in row.vouchers if v.parent_material]
        for voucher in parents:
            string = f"{voucher.herbarium} {voucher.code} (parent)"
            label = Gtk.Label(label=string)
            label.set_xalign(0)
            label.set_yalign(0.5)
            self.vbox.pack_start(label, True, True, 0)
            label.show()

        not_parents = [v for v in row.vouchers if not v.parent_material]
        for voucher in not_parents:
            string = f"{voucher.herbarium} {voucher.code}"
            label = Gtk.Label(label=string)
            label.set_xalign(0)
            label.set_yalign(0.5)
            self.vbox.pack_start(label, True, True, 0)
            label.show()


class VerificationsExpander(
    InfoExpander[Accession],
    Gtk.Expander,
):
    """The accession's verifications"""

    def __init__(self) -> None:
        super().__init__(label=_("Verifications"))
        self.connect("notify::expanded", self.on_expanded)
        self.vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.vbox.set_border_width(5)
        self.add(self.vbox)

    def update(self, row: Accession) -> None:

        for kid in self.vbox.get_children():
            self.vbox.remove(kid)

        if row.verifications:
            self.set_sensitive(True)
        else:
            self.set_sensitive(False)
            return

        for verification in sorted(
            row.verifications, key=lambda v: v.date or 0, reverse=True
        ):
            date = utils.date_string(verification.date)
            date_lbl = Gtk.Label()
            date_lbl.set_markup(f"<b>{date}</b>")
            date_lbl.set_xalign(0.0)
            date_lbl.set_yalign(0.5)
            self.vbox.pack_start(date_lbl, True, True, 0)
            label = Gtk.Label()
            sp = verification.species.markup()
            string = f"verified as {sp} by {verification.verifier}"
            label.set_markup(string)
            label.set_xalign(0.0)
            label.set_yalign(0.5)
            self.vbox.pack_start(label, True, True, 0)
            label.show()


class AccessionInfoBox(InfoBox[Collection | Accession]):
    """Accession InfoBox"""

    def __init__(self) -> None:
        super().__init__()
        self.add_expander(GeneralAccessionExpander())
        self.add_expander(SourceExpander())
        self.add_expander(VouchersExpander())
        self.add_expander(VerificationsExpander())
        self.add_expander(LinksExpander("notes"))
        self.add_expander(PropertiesExpander())

    def update(self, row: Accession | Collection) -> None:
        if isinstance(row, Collection):
            row = row.source.accession

        super().update(row)


map_kml_callback = KMLMapCallbackFunctor(
    prefs.prefs.get(COLLECTION_KML_MAP_PREF, str(parent / "collection.kml"))
)


edit_action = Action(
    "acc_edit",
    _("_Edit"),
    callback=edit_callback,
    accelerator="<ctrl>e",
)

add_plant_action = Action(
    "acc_add",
    _("_Add Plants"),
    callback=add_plants_callback,
    accelerator="<ctrl>k",
)

remove_action = Action(
    "acc_remove",
    _("_Delete"),
    callback=remove_callback,
    accelerator="<ctrl>Delete",
    multiselect=True,
)

collection_map_action = Action(
    "collection_map",
    _("Show collection site in _map"),
    callback=map_kml_callback,
    accelerator="<ctrl>m",
    multiselect=True,
)


acc_context_menu = [
    edit_action,
    add_plant_action,
    remove_action,
    collection_map_action,
]
