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
import traceback
from collections.abc import Sequence
from pathlib import Path
from typing import cast

from gi.repository import Gtk  # noqa
from sqlalchemy import distinct
from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.session import object_session

from bauble import db
from bauble import prefs
from bauble import utils
from bauble.i18n import _
from bauble.ui import dialogs
from bauble.ui.views import Action
from bauble.ui.views import InfoBox
from bauble.ui.views import InfoExpander
from bauble.ui.views import LinksExpander
from bauble.ui.views import PropertiesExpander
from bauble.ui.views import on_clicked_search

from ..genus import Genus
from ..species import Species
from .genus_editor import GENUS_WEB_BUTTON_DEFS_PREFS
from .genus_editor import add_species_callback
from .genus_editor import edit_callback
from .misc import on_taxa_clicked
from .widgets import SynonymsExpander


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
class GeneralGenusExpander(InfoExpander[Genus], Gtk.Expander):

    __gtype_name__ = "GeneralGenusExpander"

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

    def update(self, row: Genus) -> None:
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


def remove_callback(
    objs: Sequence["Genus"],
    **_kwargs,
) -> bool:
    genera = objs
    genus = genera[0]
    gen_lst = []
    session = object_session(genus)
    if not isinstance(session, Session):
        return False

    for genus in genera:
        num_sp = len(genus.species)
        safe_str = utils.xml_safe(str(genus))
        gen_lst.append(safe_str)
        if num_sp > 0:
            msg = _(
                "The genus <i>%(gen)s</i> has %(num_sp)s species.\n\n"
                "You cannot remove a genus with species."
            ) % {"gen": safe_str, "num_sp": num_sp}
            dialogs.message_dialog(msg, typ=Gtk.MessageType.WARNING)

            return False

        msg = _(
            "Are you sure you want to remove the following genera "
            "<i>%s</i>?"
        ) % ", ".join(gen_lst)
    if not dialogs.yes_no_dialog(msg):

        return False

    for genus in genera:
        session.delete(genus)
    try:
        session.commit()
    except Exception as e:  # pylint: disable=broad-except
        msg = _("Could not delete.\n\n%s") % utils.xml_safe(e)
        dialogs.message_details_dialog(
            msg, traceback.format_exc(), Gtk.MessageType.ERROR
        )
        session.rollback()

        return False

    return True


edit_action = Action(
    "genus_edit",
    _("_Edit"),
    callback=edit_callback,
    accelerator="<ctrl>e",
)
add_species_action = Action(
    "genus_sp_add",
    _("_Add species"),
    callback=add_species_callback,
    accelerator="<ctrl>k",
)
remove_action = Action(
    "genus_remove",
    _("_Delete"),
    callback=remove_callback,
    accelerator="<ctrl>Delete",
    multiselect=True,
)

genus_context_menu = [edit_action, add_species_action, remove_action]
