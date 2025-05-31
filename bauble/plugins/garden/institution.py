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
from dataclasses import dataclass
from pathlib import Path
from typing import cast

logger = logging.getLogger(__name__)

from gi.repository import Gtk
from sqlalchemy import Table
from sqlalchemy import bindparam
from sqlalchemy import select

import bauble
from bauble import db
from bauble import editor
from bauble import meta
from bauble import pluginmgr
from bauble import utils
from bauble.i18n import _


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
class InstitutionDialog(editor.GenericPresenter, Gtk.Dialog):

    __gtype_name__ = "InstitutionDialog"

    inst_name = cast(Gtk.Entry, Gtk.Template.Child())
    inst_abbr = cast(Gtk.Entry, Gtk.Template.Child())
    inst_code = cast(Gtk.Entry, Gtk.Template.Child())
    inst_contact = cast(Gtk.Entry, Gtk.Template.Child())
    inst_tech = cast(Gtk.Entry, Gtk.Template.Child())
    inst_email = cast(Gtk.Entry, Gtk.Template.Child())
    inst_tel = cast(Gtk.Entry, Gtk.Template.Child())
    inst_fax = cast(Gtk.Entry, Gtk.Template.Child())
    inst_addr_tb = cast(Gtk.TextBuffer, Gtk.Template.Child())
    inst_geo_latitude = cast(Gtk.Entry, Gtk.Template.Child())
    inst_geo_longitude = cast(Gtk.Entry, Gtk.Template.Child())
    inst_geo_zoom = cast(Gtk.ComboBoxText, Gtk.Template.Child())
    notify_revealer = cast(Gtk.Revealer, Gtk.Template.Child())
    notify_message_label = cast(Gtk.Label, Gtk.Template.Child())
    inst_ok = cast(Gtk.Button, Gtk.Template.Child())

    message_box: utils.GenericMessageBox | None = None

    def __init__(self, model: Institution) -> None:
        super().__init__(model, self)
        self.widgets_to_model_map = {
            self.inst_name: "name",
            self.inst_abbr: "abbreviation",
            self.inst_code: "code",
            self.inst_contact: "contact",
            self.inst_tech: "technical_contact",
            self.inst_email: "email",
            self.inst_tel: "tel",
            self.inst_fax: "fax",
            self.inst_addr_tb: "address",
            self.inst_geo_latitude: "geo_latitude",
            self.inst_geo_longitude: "geo_longitude",
            self.inst_geo_zoom: "geo_zoom",
        }

        if bauble.gui:
            self.set_transient_for(bauble.gui.window)
            self.set_destroy_with_parent(True)

        self.inst_name.grab_focus()
        self.refresh_all_widgets_from_model()
        self.inst_name.emit("changed")

    @Gtk.Template.Callback()
    def on_non_empty_text_entry_changed(self, entry: Gtk.Entry) -> None:
        value = super()._on_non_empty_text_entry_changed(entry)

        if not value:
            msg = _("Please specify an institution name for this database.")
            self.notify_message_label.set_label(msg)
            self.notify_revealer.set_reveal_child(True)

    @Gtk.Template.Callback()
    def on_notify_close_button_clicked(self, _button) -> None:
        """Close the notification revealer."""
        self.notify_revealer.set_reveal_child(False)

    @Gtk.Template.Callback()
    def on_text_buffer_changed(self, buffer: Gtk.TextBuffer) -> None:
        super().on_text_buffer_changed(buffer)

    @Gtk.Template.Callback()
    def on_text_entry_changed(self, entry: Gtk.Entry) -> None:
        super().on_text_entry_changed(entry)

    @Gtk.Template.Callback()
    def on_combobox_changed(self, combobox: Gtk.ComboBoxText) -> None:
        super().on_combobox_changed(combobox)

    def add_problem(self, problem_id: str, widget: Gtk.Widget) -> None:
        super().add_problem(problem_id, widget)
        self.inst_ok.set_sensitive(False)

    def remove_problem(
        self, problem_id: str | None = None, widget: Gtk.Widget | None = None
    ) -> None:
        super().remove_problem(problem_id, widget)
        self.inst_ok.set_sensitive(bool(self.problems))


def start_institution_editor() -> None:
    model = Institution()
    dialog = InstitutionDialog(model)
    if dialog.run() == Gtk.ResponseType.OK:
        model.write()
    dialog.destroy()


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
