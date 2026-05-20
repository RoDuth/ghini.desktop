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
#
"""
Plant GUI search view components.
"""

import logging
from collections.abc import Sequence

logger = logging.getLogger(__name__)

import traceback
from pathlib import Path
from typing import cast

from gi.repository import Gtk
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm import object_session

from bauble import db
from bauble import utils
from bauble.i18n import _
from bauble.plugins.plants.ui.misc import on_taxa_clicked
from bauble.ui import dialogs
from bauble.ui.views import Action
from bauble.ui.views import InfoBox
from bauble.ui.views import InfoExpander
from bauble.ui.views import LinksExpander
from bauble.ui.views import PropertiesExpander
from bauble.ui.views import on_clicked_select

# from ..plant import branch_callback
from ..plant import Plant
from ..plant import PlantChange
from ..plant import acc_type_values
from ..plant import change_reasons
from ..propagation import Propagation
from .plant_editor import edit_callback
from .plant_editor import map_kml_callback

parent = Path(__file__).resolve().parent


@Gtk.Template(filename=str(parent / "plant_expander.ui"))
class GeneralPlantExpander(
    InfoExpander[Plant],
    Gtk.Expander,
):
    """general expander for the PlantInfoBox"""

    __gtype_name__ = "GeneralPlantExpander"

    acc_code_label = cast(Gtk.Label, Gtk.Template.Child())
    plant_code_label = cast(Gtk.Label, Gtk.Template.Child())
    name_label = cast(Gtk.Label, Gtk.Template.Child())
    location_label = cast(Gtk.Label, Gtk.Template.Child())
    quantity_label = cast(Gtk.Label, Gtk.Template.Child())
    status_label = cast(Gtk.Label, Gtk.Template.Child())
    type_label = cast(Gtk.Label, Gtk.Template.Child())
    geojson_type_label = cast(Gtk.Label, Gtk.Template.Child())
    memorial_image = cast(Gtk.Image, Gtk.Template.Child())

    def __init__(self) -> None:
        super().__init__(label=_("General"))
        self.connect("notify::expanded", self.on_expanded)

    def update(self, row: Plant) -> None:
        acc_code = str(row.accession)
        plant_code = str(row)
        head, tail = plant_code[: len(acc_code)], plant_code[len(acc_code) :]

        self.acc_code_label.set_markup(f"<big>{utils.xml_safe(head)}</big>")
        self.plant_code_label.set_markup(f"<big>{utils.xml_safe(tail)}</big>")
        self.name_label.set_markup(row.accession.species_str(markup=True))
        self.location_label.set_label(utils.xml_safe(row.location))
        self.quantity_label.set_label(str(row.quantity))

        # NOTE don't load geojson from the row or history will always record
        # an update and _last_updated will always change when a relationship
        # (note, propagation, etc.) is edited. (e.g. `shape = row.geojson...`
        # instead use a temp session)
        with db.engine.connect() as connection:
            table = Plant.__table__
            stmt = select(table.c.geojson).where(table.c.id == row.id)
            geojson = connection.scalar(stmt)

        shape = geojson.get("type", "") if geojson else ""
        self.geojson_type_label.set_label(shape)

        status_str = _("Alive")
        if row.quantity <= 0:
            status_str = _("Dead")

        self.status_label.set_label(status_str)
        self.type_label.set_label(acc_type_values[row.acc_type])

        icon = None
        if row.memorial:
            icon = "object-select-symbolic"

        self.memorial_image.set_from_icon_name(icon, Gtk.IconSize.MENU)

        utils.make_label_clickable(
            self.acc_code_label,
            on_clicked_select,
            row.accession,
        )

        utils.make_label_clickable(
            self.name_label,
            on_taxa_clicked,
            row.accession.species,
        )
        utils.make_label_clickable(
            self.location_label,
            on_clicked_select,
            row.location,
        )


class ChangeBox(Gtk.Box):
    def __init__(self, change: PlantChange) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.change = change
        self.add_date_label()
        self.add_summary_label()

        if self.change.reason:
            self.add_reason_label()

        if change.parent_plant:
            self.add_parent_label()

        if change.child_plant:
            self.add_child_label()

    def add_date_label(self) -> None:
        date = utils.date_string(self.change.date)
        date_lbl = Gtk.Label()
        date_lbl.set_markup(f"<b>{date}</b>")
        date_lbl.set_xalign(0.0)
        date_lbl.set_yalign(0.0)

        self.add(date_lbl)

    def add_summary_label(self) -> None:
        change = self.change

        if change.to_location and change.from_location:
            summary = _(
                "%(quantity)s Transferred from %(from_loc)s to %(to_loc)s"
            ) % {
                "quantity": change.quantity,
                "from_loc": change.from_location,
                "to_loc": change.to_location,
            }
        elif change.quantity < 0:
            summary = _("%(quantity)s Removed from %(location)s") % {
                "quantity": -change.quantity,
                "location": change.from_location,
            }
        elif change.quantity > 0:
            txt = _("Added to")
            if change.reason == "PLTD":
                txt = _("Planted in")
            if change.reason == "ESTM":
                txt = _("Planted (estm.) in")
            if change.reason in ["NTRL", "PRIR"]:
                txt = _("Captured in")
            summary = f"{change.quantity} {txt} {change.to_location}"
        else:
            summary = (
                f"{change.quantity}: {change.from_location} -> "
                f"{change.to_location}"
            )

        summary_lbl = Gtk.Label()
        summary_lbl.set_text(summary)
        summary_lbl.set_xalign(0.0)
        summary_lbl.set_yalign(0.0)
        summary_lbl.set_line_wrap(True)

        self.add(summary_lbl)

    def add_reason_label(self) -> None:
        reason_lbl = Gtk.Label()
        reason_lbl.set_text(change_reasons.get(self.change.reason, ""))
        reason_lbl.set_xalign(0.0)
        reason_lbl.set_yalign(0.0)

        self.add(reason_lbl)

    def add_parent_label(self) -> None:
        parent_lbl = Gtk.Label()
        text = _("Split from %s") % utils.xml_safe(self.change.parent_plant)
        parent_lbl.set_markup(f"<i>{text}</i>")
        eventbox = Gtk.EventBox()
        eventbox.add(parent_lbl)

        utils.make_label_clickable(
            parent_lbl,
            on_clicked_select,
            self.change.parent_plant,
        )

        self.add(eventbox)

    def add_child_label(self) -> None:
        child_label = Gtk.Label()
        text = _("Split as %s") % utils.xml_safe(self.change.child_plant)
        child_label.set_markup(f"<i>{text}</i>")
        eventbox = Gtk.EventBox()
        eventbox.add(child_label)

        utils.make_label_clickable(
            child_label,
            on_clicked_select,
            self.change.child_plant,
        )

        self.add(eventbox)


class ChangesExpander(
    InfoExpander[Plant],
    Gtk.Expander,
):
    def __init__(self) -> None:
        super().__init__(label=_("Changes"))
        self.vbox = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=6,
            border_width=5,
        )
        self.add(self.vbox)

    def update(self, row: Plant) -> None:
        self.vbox.foreach(self.vbox.remove)

        if not row.changes:
            self.set_sensitive(False)
            return

        self.set_sensitive(True)

        for change in sorted(
            row.changes,
            key=lambda x: (x.date, x.id),
            reverse=True,
        ):
            self.vbox.add(ChangeBox(change))

        self.show_all()
        # trigger resize
        self.get_preferred_size()


class PropagationBox(Gtk.Box):
    def __init__(self, prop: Propagation) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.prop = prop
        self.add_date_label()
        self.add_summary_label()

        if prop.accessions:
            self.add_accessions_labels()

    def add_date_label(self) -> None:
        date = utils.date_string(self.prop.date)
        date_lbl = Gtk.Label()
        date_lbl.set_markup(f"<b>{date}</b>")
        date_lbl.set_xalign(0.0)
        date_lbl.set_yalign(0.0)

        self.add(date_lbl)

    def add_summary_label(self) -> None:
        summary_label = Gtk.Label()
        summary_label.set_text(self.prop.get_summary(partial=2))
        summary_label.set_line_wrap(True)
        summary_label.set_xalign(0.0)
        summary_label.set_yalign(0.0)
        summary_label.set_size_request(-1, -1)

        self.add(summary_label)

    def add_accessions_labels(self) -> None:
        box = Gtk.Box(spacing=8, margin_start=12)
        used_lbl = Gtk.Label()
        used_lbl.set_text(_("Parent of:"))

        box.add(used_lbl)

        for acc in self.prop.accessions:
            accession_lbl = Gtk.Label()
            accession_lbl.set_text(acc.code)
            accession_lbl.set_xalign(0.0)
            accession_lbl.set_yalign(0.0)

            eventbox = Gtk.EventBox()
            eventbox.add(accession_lbl)

            utils.make_label_clickable(
                accession_lbl,
                on_clicked_select,
                acc,
            )
            box.add(eventbox)

        self.add(box)


class PropagationExpander(
    InfoExpander[Plant],
    Gtk.Expander,
):
    """Propagation Expander"""

    def __init__(self) -> None:
        super().__init__(label=_("Propagations"))
        self.connect("notify::expanded", self.on_expanded)
        self.vbox = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=6,
            border_width=5,
        )
        self.add(self.vbox)

    def update(self, row: Plant) -> None:
        self.vbox.foreach(self.vbox.remove)

        if not row.propagations:
            self.set_sensitive(False)
            return

        self.set_sensitive(True)

        for prop in row.propagations:

            self.vbox.add(PropagationBox(prop))

        self.show_all()
        # trigger resize
        self.get_preferred_size()


class PlantInfoBox(InfoBox[Plant]):
    """an InfoBox for a Plants table row"""

    def __init__(self):
        super().__init__()
        self.add_expander(GeneralPlantExpander())
        self.add_expander(ChangesExpander())
        self.add_expander(PropagationExpander())
        self.add_expander(LinksExpander("notes"))
        self.add_expander(PropertiesExpander())


def remove_callback(
    objs: Sequence[Plant],
    **_kwargs,
) -> bool:

    plants = list(objs)
    plant = plants[0]
    session = object_session(plant)

    if not isinstance(session, Session):
        logger.warning(
            "Could not get session for location %s. Cannot delete.",
            plant,
        )
        return False

    p_str = ", ".join([str(p) for p in plants])
    msg = _(
        "Are you sure you want to remove the following plants?\n\n%s\n\n"
        "<small>Note that deleting a plant can destroy related data.  If "
        "the plant has died set its quantity to zero rather than delete "
        "it.</small>"
    ) % utils.xml_safe(p_str)
    if not dialogs.yes_no_dialog(msg):
        return False

    for plant in plants:
        if plant.branches:
            msg = _(
                "%s has plant(s) split from it.  Removing this plant "
                "will destroy their link back.  Are you sure you want to "
                "want to delete it?"
            ) % utils.xml_safe(plant)
            if not dialogs.yes_no_dialog(msg):
                plants.remove(plant)
                continue
        if plant.propagations:
            msg = _(
                "%s has propagations.  Removing this plant will destroy "
                "these propagations and possibly the source data for any "
                "accessions created from them.  Are you sure you want to "
                "want to delete it?"
            ) % utils.xml_safe(plant)
            if not dialogs.yes_no_dialog(msg):
                plants.remove(plant)
                continue

        session.delete(plant)

    if not plants:
        return False

    try:
        session.commit()
    except Exception as e:  # pylint: disable=broad-except
        msg = _("Could not delete.\n\n%s") % utils.xml_safe(e)
        logger.debug("remove_callback - (%s(%s)", type(e).__name__, e)
        dialogs.message_details_dialog(
            msg,
            traceback.format_exc(),
            Gtk.MessageType.ERROR,
        )
        session.rollback()
        return False
    return True


edit_action = Action(
    "plant_edit",
    _("_Edit"),
    callback=edit_callback,
    accelerator="<ctrl>e",
)

# branch_action = Action(
#     "plant_branch",
#     _("_Split"),
#     callback=branch_callback,
#     accelerator="<ctrl>b",
# )

remove_action = Action(
    "plant_remove",
    _("_Delete"),
    callback=remove_callback,
    accelerator="<ctrl>Delete",
    multiselect=True,
)

map_action = Action(
    "plant_show_in_map",
    _("Show in _map"),
    callback=map_kml_callback,
    accelerator="<ctrl>m",
    multiselect=True,
)

# plant_context_menu = [edit_action, branch_action, remove_action, map_action]
plant_context_menu = [edit_action, remove_action, map_action]
