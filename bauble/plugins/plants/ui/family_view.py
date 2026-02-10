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
Family GUI search view components.
"""
import logging

logger = logging.getLogger(__name__)

import traceback
from collections.abc import Sequence
from pathlib import Path
from typing import cast

from gi.repository import Gtk
from sqlalchemy import distinct
from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.orm.session import object_session

from bauble import db
from bauble import prefs
from bauble import utils
from bauble.i18n import _
from bauble.view import Action
from bauble.view import InfoBox
from bauble.view import InfoExpander
from bauble.view import LinksExpander
from bauble.view import PropertiesExpander
from bauble.view import on_clicked_search

from ..family import Family
from ..genus import Genus
from ..species_model import Species
from .family_editor import FAMILY_WEB_BUTTON_DEFS_PREFS
from .family_editor import add_genera_callback
from .family_editor import edit_callback
from .widgets import SynonymsExpander


def infobox_counts(id_: int) -> dict[str, int]:
    from ...garden import Accession
    from ...garden import Plant

    stmt = (
        select(
            func.count(distinct(Genus.id)),
            func.count(distinct(Species.genus_id)),
            func.count(distinct(Species.id)),
            func.count(distinct(Accession.species_id)),
            func.count(distinct(Accession.id)),
            func.count(distinct(Plant.accession_id)),
            func.count(Plant.id),
            func.sum(Plant.quantity),
        )
        .select_from(Family)
        .outerjoin(Genus)
        .outerjoin(Species)
        .outerjoin(Accession)
        .outerjoin(Plant)
        .where(Family.id == id_)
    )
    with db.engine.begin() as connection:
        counts = connection.execute(stmt).one()

    keys = (
        "genera",
        "gen_w_sp",
        "species",
        "sp_w_acc",
        "accessions",
        "acc_w_plants",
        "plants",
        "living_plants",
    )

    return dict(zip(keys, counts, strict=True))


@Gtk.Template(
    filename=str(Path(__file__).resolve().parent / "family_expander.ui")
)
class GeneralFamilyExpander(InfoExpander[Family], Gtk.Expander):

    __gtype_name__ = "GeneralFamilyExpander"

    details_box = cast(Gtk.Box, Gtk.Template.Child())
    order_label = cast(Gtk.Label, Gtk.Template.Child())
    suborder_label = cast(Gtk.Label, Gtk.Template.Child())
    name_label = cast(Gtk.Label, Gtk.Template.Child())
    num_genera_label = cast(Gtk.Label, Gtk.Template.Child())
    num_taxa_label = cast(Gtk.Label, Gtk.Template.Child())
    num_acc_label = cast(Gtk.Label, Gtk.Template.Child())
    num_plants_label = cast(Gtk.Label, Gtk.Template.Child())
    living_plants_label = cast(Gtk.Label, Gtk.Template.Child())
    cites_label = cast(Gtk.Label, Gtk.Template.Child())

    def __init__(self) -> None:
        super().__init__(label=_("General"))
        self.connect("notify::expanded", self.on_expanded)
        self.has_details = False

    def update(self, row: Family) -> None:
        self.has_details = any((row.order, row.suborder))
        self.update_details(row)
        self.name_label.set_markup(
            f"<big>{row}</big> {utils.xml_safe(str(row.author))}",
        )
        self.update_counts(row)
        self.update_clickable_labels(row)

    def update_counts(self, row: Family) -> None:
        counts = infobox_counts(row.id)

        self.num_genera_label.set_label(str(counts["genera"]))
        self.num_taxa_label.set_label("0")
        self.num_acc_label.set_label("0")
        self.num_plants_label.set_label("0")

        if counts["species"]:
            self.num_taxa_label.set_label(
                f"{counts['species']} in {counts['gen_w_sp']} genera"
            )

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

    def update_clickable_labels(self, row: Family) -> None:
        labels_to_searches = (
            (
                self.num_genera_label,
                f"genus where family.id = {row.id}",
            ),
            (
                self.num_taxa_label,
                f"species where genus.family.id = {row.id}",
            ),
            (
                self.num_acc_label,
                f"accession where species.genus.family.id = {row.id}",
            ),
            (
                self.num_plants_label,
                f"plant where accession.species.genus.family.id = {row.id}",
            ),
            (
                self.cites_label,
                f"family where cites = {row.cites}",
            ),
            (
                self.living_plants_label,
                f"plant where accession.species.genus.family.id = {row.id} "
                "and quantity > 0",
            ),
        )

        for label, search in labels_to_searches:
            utils.make_label_clickable(
                label,
                on_clicked_search,
                search,
            )

    def update_details(self, row: Family) -> None:
        """Provides higher parts, if they exist, above the family name."""

        if not self.has_details:
            utils.hide_widgets([self.details_box])
            return

        utils.unhide_widgets([self.details_box])
        utils.hide_widgets([self.order_label, self.suborder_label])

        if row.order:
            self.order_label.set_markup(f"{utils.xml_safe(row.order)} >")
            utils.make_label_clickable(
                self.order_label,
                on_clicked_search,
                f"family where order = {row.order}",
            )
            utils.unhide_widgets([self.order_label])

        if row.suborder:
            self.suborder_label.set_markup(f"{utils.xml_safe(row.suborder)} >")
            utils.make_label_clickable(
                self.suborder_label,
                on_clicked_search,
                f"family where suborder = {row.suborder}",
            )
            utils.unhide_widgets([self.suborder_label])


class FamilyInfoBox(InfoBox[Family]):

    def __init__(self) -> None:
        super().__init__()
        self.add_expander(GeneralFamilyExpander())
        self.add_expander(SynonymsExpander[Family]())

        button_defs = []
        buttons = prefs.prefs.itersection(FAMILY_WEB_BUTTON_DEFS_PREFS)
        for name, button in buttons:
            button["name"] = name
            button_defs.append(button)

        self.add_expander(LinksExpander("notes", links=button_defs))
        self.add_expander(PropertiesExpander())


def remove_callback(
    objs: Sequence["Family"],
    **_kwargs,
) -> bool:
    family = objs[0]
    fam_lst: list[str] = []
    session = object_session(family)
    if not isinstance(session, Session):
        logger.warning(
            "Could not get session for family %s. Cannot delete.",
            family,
        )
        return False

    for family in objs:
        num_gen = len(family.genera)
        safe_str = utils.xml_safe(str(family))
        fam_lst.append(safe_str)
        if num_gen > 0:
            msg = _(
                "The family <i>%(fam)s</i> has %(num_gen)s genera.\n\n"
                "You cannot remove a family with genera."
            ) % {"fam": safe_str, "num_gen": num_gen}
            utils.message_dialog(msg, typ=Gtk.MessageType.WARNING)

            return False

    msg = _(
        "Are you sure you want to remove the following families <i>%s</i>?"
    ) % ", ".join(fam_lst)
    if not utils.yes_no_dialog(msg):

        return False

    for family in objs:
        session.delete(family)
    try:
        session.commit()
    except SQLAlchemyError as e:
        msg = _("Could not delete.\n\n%s") % utils.xml_safe(e)
        utils.message_details_dialog(
            msg, traceback.format_exc(), Gtk.MessageType.ERROR
        )
        session.rollback()

        return False

    return True


edit_action = Action(
    "family_edit",
    _("_Edit"),
    callback=edit_callback,
    accelerator="<ctrl>e",
)

add_genus_action = Action(
    "family_genus_add",
    _("_Add genus"),
    callback=add_genera_callback,
    accelerator="<ctrl>k",
)

remove_action = Action(
    "family_remove",
    _("_Delete"),
    callback=remove_callback,
    accelerator="<ctrl>Delete",
    multiselect=True,
)

family_context_menu = [edit_action, add_genus_action, remove_action]
