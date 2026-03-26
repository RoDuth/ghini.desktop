# Copyright 2008-2010 Brett Adams
# Copyright 2012-2015 Mario Frasca <mario@anche.no>.
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
Species GUI search view components.
"""
import traceback
from collections.abc import Sequence

from gi.repository import Gtk
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.orm.session import object_session

from bauble import utils
from bauble.i18n import _
from bauble.ui import dialogs
from bauble.ui.views import Action

from ..geography import map_kml_callback
from ..species_model import Species
from ..species_model import VernacularName
from .species_editor import add_accession_callback
from .species_editor import edit_callback


def remove_callback(
    objs: Sequence[Species | VernacularName],
    **_kwargs,
) -> bool:

    species = objs[0]
    sp_lst: list[str] = []
    session = object_session(species)
    if not isinstance(session, Session):
        return False

    for species in objs:
        if isinstance(species, VernacularName):
            species = species.species

        num_acc = len(species.accessions)
        safe_str = utils.xml_safe(str(species))
        sp_lst.append(safe_str)
        if num_acc > 0:

            msg = _(
                "The species <i>%(sp)s</i> has %(num_acc)s accessions.\n\n"
                "You cannot remove a species with accessions."
            ) % {"sp": safe_str, "num_acc": num_acc}

            dialogs.message_dialog(msg, typ=Gtk.MessageType.WARNING)

            return False

    msg = _(
        "Are you sure you want to remove the following species <i>%s</i>?"
    ) % ", ".join(sp_lst)
    if not dialogs.yes_no_dialog(msg):
        return False

    for species in objs:
        session.delete(species)
    try:
        session.commit()
    except SQLAlchemyError as e:
        msg = _("Could not delete.\n\n%s") % utils.xml_safe(e)
        dialogs.message_details_dialog(
            msg, traceback.format_exc(), Gtk.MessageType.ERROR
        )
        session.rollback()
        return False

    return True


edit_action = Action(
    "species_edit", _("_Edit"), callback=edit_callback, accelerator="<ctrl>e"
)

add_accession_action = Action(
    "species_acc_add",
    _("_Add accession"),
    callback=add_accession_callback,
    accelerator="<ctrl>k",
)

remove_action = Action(
    "species_remove",
    _("_Delete"),
    callback=remove_callback,
    accelerator="<ctrl>Delete",
    multiselect=True,
)

distribution_map_action = Action(
    "acc_dist_map",
    _("Show distribution in _map"),
    callback=map_kml_callback,
    accelerator="<ctrl>m",
    multiselect=True,
)

species_context_menu = [edit_action, remove_action, distribution_map_action]

vernname_context_menu = [edit_action]
