# Copyright 2008-2010 Brett Adams
# Copyright 2015,2018 Mario Frasca <mario@anche.no>.
# Copyright 2017 Jardín Botánico de Quito
# Copyright 2024-2025 Ross Demuth <rossdemuth123@gmail.com>
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
Edit and store information about the institution in the bauble meta table
"""

import logging

logger = logging.getLogger(__name__)

from collections.abc import Callable
from copy import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Self
from typing import cast

from gi.repository import GLib
from gi.repository import Gtk
from sqlalchemy import Table
from sqlalchemy import bindparam
from sqlalchemy import select

import bauble
from bauble import db
from bauble import meta
from bauble import pluginmgr
from bauble import utils
from bauble.i18n import _
from bauble.ui import GenericPresenter
from bauble.ui.presenter import generic_notify_delete_event
from bauble.ui.widgets import MessageBox


@dataclass
class Institution:  # pylint: disable=too-many-instance-attributes
    """Institution is a "live" object, you only need to set a value on it and
    then call `write` to persist them to the database.

    Institution values are stored in the Ghini meta database and not in its own
    table
    """

    name: str | None = None
    abbreviation: str | None = None
    code: str | None = None
    contact: str | None = None
    technical_contact: str | None = None
    email: str | None = None
    tel: str | None = None
    fax: str | None = None
    address: str | None = None
    geo_latitude: str | None = None
    geo_longitude: str | None = None
    geo_zoom: str | None = None
    uuid: str | None = None

    def __post_init__(self) -> None:
        table: Table = meta.BaubleMeta.__table__

        if not db.engine:
            return

        with db.engine.begin() as conn:
            for key in self.__dict__:
                db_prop = str("inst_" + key)
                stmt = select(table.c.value).where(table.c.name == db_prop)
                value = conn.execute(stmt).scalar()
                setattr(self, key, value)

    def write(self) -> None:
        table: Table = meta.BaubleMeta.__table__

        if not db.engine:
            return

        inserts: list[dict[str, str]] = []
        updates: list[dict[str, str]] = []
        with db.engine.begin() as conn:
            for key, value in self.__dict__.items():
                db_prop = str("inst_" + key)
                stmt = select(table.c.id).where(table.c.name == db_prop)
                row = conn.execute(stmt).scalar()
                if row:
                    updates.append({"_name": db_prop, "value": value})
                else:
                    inserts.append({"name": db_prop, "value": value})

            if inserts:
                insert = table.insert()
                conn.execute(insert, inserts)

            if updates:
                update = (
                    table.update()
                    .where(table.c.name == bindparam("_name"))
                    .values(value=bindparam("value"))
                )
                conn.execute(update, updates)


@Gtk.Template(filename=str(Path(__file__).resolve().parent / "institution.ui"))
class InstitutionDialog(
    GenericPresenter[Institution],
    Gtk.Dialog,
):  # pylint: disable=not-callable

    __gtype_name__ = "InstitutionDialog"

    __gsignals__ = GenericPresenter.gsignals

    name_entry = cast(Gtk.Entry, Gtk.Template.Child())
    abbreviation_entry = cast(Gtk.Entry, Gtk.Template.Child())
    code_entry = cast(Gtk.Entry, Gtk.Template.Child())
    contact_entry = cast(Gtk.Entry, Gtk.Template.Child())
    tech_contact_entry = cast(Gtk.Entry, Gtk.Template.Child())
    email_entry = cast(Gtk.Entry, Gtk.Template.Child())
    phone_entry = cast(Gtk.Entry, Gtk.Template.Child())
    fax_entry = cast(Gtk.Entry, Gtk.Template.Child())
    address_buffer = cast(Gtk.TextBuffer, Gtk.Template.Child())
    geo_latitude_entry = cast(Gtk.Entry, Gtk.Template.Child())
    geo_longitude_entry = cast(Gtk.Entry, Gtk.Template.Child())
    geo_zoom_combo = cast(Gtk.ComboBoxText, Gtk.Template.Child())
    revealer = cast(Gtk.Revealer, Gtk.Template.Child())
    ok_button = cast(Gtk.Button, Gtk.Template.Child())

    message_box: utils.GenericMessageBox | None = None

    def __init__(self, model: Institution) -> None:
        super().__init__(model, self)
        self.widgets_to_model_map = {
            self.name_entry: "name",
            self.abbreviation_entry: "abbreviation",
            self.code_entry: "code",
            self.contact_entry: "contact",
            self.tech_contact_entry: "technical_contact",
            self.email_entry: "email",
            self.phone_entry: "tel",
            self.fax_entry: "fax",
            self.address_buffer: "address",
            self.geo_latitude_entry: "geo_latitude",
            self.geo_longitude_entry: "geo_longitude",
            self.geo_zoom_combo: "geo_zoom",
        }

        if bauble.gui:
            self.set_transient_for(bauble.gui.window)

        self.name_entry.grab_focus()
        self.refresh_all_widgets_from_model()

        self.start = copy(self.model)

        if not self.model.name:
            GLib.idle_add(self.notify_no_institution)

        self.name_entry.emit("changed")

    def notify_no_institution(self) -> None:

        self.revealer.foreach(self.revealer.remove)

        msg = _("Please specify an institution name for this database.")

        message_box = MessageBox(msg)
        message_box.show_all()
        self.revealer.add(message_box)
        self.revealer.set_reveal_child(True)

    @Gtk.Template.Callback()
    def on_non_empty_text_entry_changed(self, entry: Gtk.Entry) -> None:
        super().on_non_empty_text_entry_changed(entry)
        if self.model.name:
            self.revealer.set_reveal_child(False)
            self.revealer.foreach(self.revealer.remove)

    @Gtk.Template.Callback()
    def on_text_buffer_changed(self, buffer: Gtk.TextBuffer) -> None:
        super().on_text_buffer_changed(buffer)

    @Gtk.Template.Callback()
    def on_text_entry_changed(self, entry: Gtk.Entry) -> None:
        super().on_text_entry_changed(entry)

    @Gtk.Template.Callback()
    def on_combobox_changed(self, combobox: Gtk.ComboBoxText) -> None:
        super().on_combobox_changed(combobox)

    @Gtk.Template.Callback()
    def on_problems_changed(self, _widget: Self, has_problems: bool) -> None:
        self.ok_button.set_sensitive(not has_problems)

    @Gtk.Template.Callback()
    def on_response(self, dialog: Self, response: Gtk.ResponseType) -> None:
        if response == Gtk.ResponseType.OK:
            self.model.write()
        dialog.destroy()

    def has_pending_changes(self) -> bool:
        if self.problems:
            return True
        return self.model != self.start

    def notify_delete_event(self, remove: Callable[[int], None]) -> None:
        generic_notify_delete_event(self, remove)


def start_institution_editor() -> None:
    model = Institution()
    dialog = InstitutionDialog(model)
    dialog.show()


class InstitutionCommand(pluginmgr.CommandHandler):
    command = ("inst", "institution")
    view = None

    def __call__(self, cmd, arg):
        InstitutionTool.start()


# pylint: disable=too-few-public-methods
class InstitutionTool(pluginmgr.Tool):
    label = _("Institution")

    @classmethod
    def start(cls):
        start_institution_editor()
