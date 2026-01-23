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
Genus GUI search view components.
"""
from pathlib import Path
from typing import cast

from gi.repository import Gtk  # noqa
from sqlalchemy import distinct
from sqlalchemy import func
from sqlalchemy import select

from bauble import db
from bauble import prefs
from bauble import utils
from bauble.i18n import _
from bauble.view import InfoBox
from bauble.view import InfoExpanderMixin
from bauble.view import LinksExpander
from bauble.view import PropertiesExpander
from bauble.view import on_clicked_search

from ..genus import Genus
from ..species import on_taxa_clicked
from ..species_model import Species
from .widgets import SynonymsExpander

GENUS_WEB_BUTTON_DEFS_PREFS = "web_button_defs.genus"


def infobox_counts(id_: int) -> dict[str, int]:
    from ...garden import Accession
    from ...garden import Plant

    stmt = (
        select(
            func.count(distinct(Species.id)),
            func.count(distinct(Accession.species_id)),
            func.count(distinct(Accession.id)),
            func.count(distinct(Plant.accession_id)),
            func.count(Plant.id),
            func.sum(Plant.quantity),
        )
        .select_from(Genus)
        .outerjoin(Species)
        .outerjoin(Accession)
        .outerjoin(Plant)
        .where(Genus.id == id_)
    )
    with db.engine.begin() as connection:
        counts = connection.execute(stmt).one()

    keys = (
        "species",
        "sp_w_acc",
        "accessions",
        "acc_w_plants",
        "plants",
        "living_plants",
    )

    return dict(zip(keys, counts, strict=True))


@Gtk.Template(
    filename=str(Path(__file__).resolve().parent / "genus_expander.ui")
)
class GeneralGenusExpander(InfoExpanderMixin[Genus], Gtk.Expander):

    __gtype_name__ = "GeneralGenusExpander"

    general_box = cast(Gtk.Box, Gtk.Template.Child())
    name_label = cast(Gtk.Label, Gtk.Template.Child())
    fam_label = cast(Gtk.Label, Gtk.Template.Child())
    subfam_label = cast(Gtk.Label, Gtk.Template.Child())
    tribe_label = cast(Gtk.Label, Gtk.Template.Child())
    subtribe_label = cast(Gtk.Label, Gtk.Template.Child())
    num_taxa_label = cast(Gtk.Label, Gtk.Template.Child())
    num_acc_label = cast(Gtk.Label, Gtk.Template.Child())
    num_plants_label = cast(Gtk.Label, Gtk.Template.Child())
    living_plants_label = cast(Gtk.Label, Gtk.Template.Child())
    cites_label = cast(Gtk.Label, Gtk.Template.Child())

    def __init__(self) -> None:
        super().__init__(label=_("General"))
        self.connect("notify::expanded", self.on_expanded)
        self.has_details = False

    def update(self, row: Genus) -> None:
        self.has_details = any((row.subfamily, row.tribe, row.subtribe))
        self.update_details(row)
        self.name_label.set_markup(
            f"<big>{row.markup()}</big> {utils.xml_safe(str(row.author))}",
        )
        self.update_family(row)
        self.update_counts(row)
        self.update_clickable_labels(row)

    def update_family(self, row: Genus) -> None:

        self.fam_label.set_markup(utils.xml_safe(str(row.family)))

        utils.make_label_clickable(
            self.fam_label,
            on_taxa_clicked,
            row.family,
        )

    def update_details(self, row: Genus) -> None:
        """Provides higher parts, if they exist, above the genus name."""

        self.subfam_label.set_markup(
            f"> {utils.xml_safe(row.subfamily)}" if row.subfamily else "",
        )

        if row.subfamily:
            utils.make_label_clickable(
                self.subfam_label,
                on_clicked_search,
                f"genus where subfamily = {row.subfamily}",
            )

        self.tribe_label.set_markup(
            f"> {utils.xml_safe(row.tribe)}" if row.tribe else "",
        )

        if row.tribe:
            utils.make_label_clickable(
                self.tribe_label,
                on_clicked_search,
                f"genus where tribe = {row.tribe}",
            )

        self.subtribe_label.set_markup(
            f"> {utils.xml_safe(row.subtribe)}" if row.subtribe else "",
        )

        if row.subtribe:
            utils.make_label_clickable(
                self.subtribe_label,
                on_clicked_search,
                f"genus where subtribe = {row.subtribe}",
            )

    def update_counts(self, row: Genus) -> None:
        counts = infobox_counts(row.id)

        self.num_taxa_label.set_label("0")
        self.num_acc_label.set_label("0")
        self.num_plants_label.set_label("0")

        if counts["species"]:
            self.num_taxa_label.set_label(str(counts["species"]))

        if counts["accessions"]:
            self.num_acc_label.set_label(
                f"{counts['accessions']} in {counts['sp_w_acc']} species"
            )

        if counts["plants"]:
            self.num_plants_label.set_label(
                f"{counts['plants']} in {counts['acc_w_plants']} accessions"
            )

        self.living_plants_label.set_label(str(counts["living_plants"] or 0))
        self.cites_label.set_label(row.cites or "")

    def update_clickable_labels(self, row: Genus) -> None:
        labels_to_searches = (
            (
                self.num_taxa_label,
                f"species where genus.id = {row.id}",
            ),
            (
                self.num_acc_label,
                f"accession where species.genus.id = {row.id}",
            ),
            (
                self.num_plants_label,
                f"plant where accession.species.genus.id = {row.id}",
            ),
            (
                self.cites_label,
                f"family where cites = {row.cites}",
            ),
            (
                self.living_plants_label,
                f"plant where accession.species.genus.id = {row.id} "
                "and quantity > 0",
            ),
        )

        for label, search in labels_to_searches:
            utils.make_label_clickable(
                label,
                on_clicked_search,
                search,
            )


class GenusInfoBox(InfoBox):

    def __init__(self):
        super().__init__()
        self.add_expander(GeneralGenusExpander())
        self.add_expander(SynonymsExpander[Genus]())

        button_defs = []
        buttons = prefs.prefs.itersection(GENUS_WEB_BUTTON_DEFS_PREFS)
        for name, button in buttons:
            button["name"] = name
            button_defs.append(button)

        self.add_expander(LinksExpander("notes", links=button_defs))
        self.add_expander(PropertiesExpander())
