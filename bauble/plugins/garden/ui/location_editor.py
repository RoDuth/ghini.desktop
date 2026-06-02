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
Location GUI editor parts.
"""

import logging

logger = logging.getLogger(__name__)

from pathlib import Path
from typing import Self
from typing import cast

from gi.repository import GLib
from gi.repository import Gspell
from gi.repository import Gtk
from sqlalchemy import select
from sqlalchemy.orm import Session

from bauble import prefs
from bauble import utils
from bauble.i18n import _
from bauble.ui.presenter import AddCallback
from bauble.ui.presenter import DomainEditorDialog
from bauble.ui.presenter import EditCreateCallback
from bauble.ui.presenter import Response
from bauble.ui.widgets import DocumentBox
from bauble.ui.widgets import MapMenuButton
from bauble.ui.widgets import NoteBox
from bauble.ui.widgets import NotesPresenter
from bauble.ui.widgets import PictureBox
from bauble.ui.widgets.message import YesNoMessageBox
from bauble.utils.geo import KMLMapCallbackFunctor

from ..location import Location
from ..plant import Plant
from .plant_editor import PlantEditorDialog

LOC_KML_MAP_PREFS = "kml_templates.location"
"""pref for path to a custom mako kml template."""

parent = Path(__file__).resolve().parent


@Gtk.Template(filename=str(parent / "location_editor.ui"))
class LocationEditorDialog(
    DomainEditorDialog[Location],
    Gtk.Dialog,
):  # pylint: disable=not-callable,too-many-public-methods

    __gtype_name__ = "LocationEditorDialog"

    revealer = cast(Gtk.Revealer, Gtk.Template.Child())
    code_entry = cast(Gtk.Entry, Gtk.Template.Child())
    name_entry = cast(Gtk.Entry, Gtk.Template.Child())
    description_textview = cast(Gtk.TextView, Gtk.Template.Child())
    description_textbuffer = cast(Gtk.TextBuffer, Gtk.Template.Child())

    map_menu_btn = cast(MapMenuButton, Gtk.Template.Child())
    notes_presenter = cast(NotesPresenter[NoteBox], Gtk.Template.Child())
    pictures_presenter = cast(NotesPresenter[PictureBox], Gtk.Template.Child())
    documents_presenter = cast(
        NotesPresenter[DocumentBox],
        Gtk.Template.Child(),
    )

    def __init__(
        self,
        model: Location,
        session: Session,
        transient_for: Gtk.Window | None = None,
    ) -> None:

        super().__init__(model, session, transient_for=transient_for)

        self.widgets_to_model_map = {
            self.code_entry: "code",
            self.name_entry: "name",
            self.description_textbuffer: "description",
        }

        self.refresh_all_widgets_from_model()

        self.map_menu_btn.init(self.model, map_kml_callback)
        self.notes_presenter.init(self.model)
        self.pictures_presenter.init(self.model, "_pictures", PictureBox)
        self.documents_presenter.init(self.model, "documents", DocumentBox)

        spell_view = Gspell.TextView.get_from_gtk_text_view(
            self.description_textview
        )
        spell_view.basic_setup()

        self.code_entry.emit("changed")

        if self.model.code:
            current = self.get_title()
            self.set_title(f"{current} - {self.model.code}")

    @property
    def can_commit(self) -> bool:
        modified = self.session.is_modified(self.model)
        if not modified:
            modified = any(
                self.session.is_modified(i) for i in self.session.dirty
            )

        no_problems = not self.problems

        return all((modified, no_problems))

    @Gtk.Template.Callback()
    def on_changed(self, _presenter: Gtk.Widget) -> None:
        self.update()

    @Gtk.Template.Callback()
    def on_code_entry_changed(self, entry: Gtk.Entry) -> None:
        code = entry.get_text()
        existing = (
            self.session.execute(select(Location).where(Location.code == code))
            .scalars()
            .first()
        )
        if existing and existing is not self.model:
            logger.debug("found existing location with code %s", code)
            GLib.idle_add(self.notify_existing_location, existing)

        super().on_unique_text_entry_changed(entry)

    def notify_existing_location(self, existing: Location) -> None:
        modal = self.get_modal()

        def on_yes_clicked(_button: Gtk.Button) -> None:
            self.revealer.set_reveal_child(False)

            if modal:
                # just return with model in place
                self.session.expunge(self.model)
                self.model = existing
                self.emit("response", Response.RETURN)
                return

            self.emit("response", Response.CANCEL)
            edit_callback([existing])

        def on_no_clicked(_button: Gtk.Button) -> None:
            self.revealer.set_reveal_child(False)

        location = utils.xml_safe(existing)

        if modal:
            msg = _(
                "<b>%(location)s</b> already exists.\n\n"
                "Would you like to use this location instead?"
            ) % {"location": location}
        else:
            msg = _(
                "<b>%(location)s</b> already exists.\n\n"
                "Would you like to edit the existing location instead?"
            ) % {"location": location}

        message_box = YesNoMessageBox(msg, on_yes_clicked, on_no_clicked)

        self.revealer.foreach(self.revealer.remove)
        message_box.show_all()
        self.revealer.add(message_box)
        self.revealer.set_reveal_child(True)

    @Gtk.Template.Callback()
    def on_name_entry_changed(self, entry: Gtk.Entry) -> None:
        super().on_text_entry_changed(entry)

    @Gtk.Template.Callback()
    def on_text_buffer_changed(self, buffer: Gtk.TextBuffer) -> None:
        super().on_text_buffer_changed(buffer)

    @Gtk.Template.Callback()
    def on_response(
        self,
        dialog: Self,
        response: Response,
    ) -> bool:
        name = str(response)
        if response in Response:
            name = Response(response).name

        logger.debug("Response: %s", name)

        if response == Response.RETURN:
            logger.debug("plain return, no commit")
            return False

        if response in [Response.NEXT, Response.ADD, Response.OK]:
            logger.debug("committing")
            if self.do_commit() is False:
                logger.debug("commit failed")
                dialog.stop_emission_by_name("response")
                return True

        if response == Response.NEXT:
            create_location()

        elif response == Response.ADD:
            add_plants_callback([self.model])

        elif response == Response.CANCEL:
            # most likely not needed
            self.session.rollback()
            self.session.close()

        if not self.get_modal():
            # allow chaining response signal
            GLib.idle_add(self.destroy)

        return False


map_kml_callback = KMLMapCallbackFunctor(
    prefs.prefs.get(LOC_KML_MAP_PREFS, str(parent / "loc.kml"))
)

edit_callback = EditCreateCallback(
    LocationEditorDialog,
    Location,
)

create_location = edit_callback

add_plants_callback = AddCallback(PlantEditorDialog, Plant, "location")
