# Copyright 2008-2010 Brett Adams
# Copyright 2015,2018 Mario Frasca <mario@anche.no>.
# Copyright 2017 Jardín Botánico de Quito
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
# Description: edit and store information about the institution in the bauble
# meta
#

import logging
import os
import re

logger = logging.getLogger(__name__)

from gi.repository import Gtk

from bauble import editor
from bauble import meta
from bauble import paths
from bauble import pluginmgr
from bauble import utils
from bauble.editor import GenericEditorView
from bauble.i18n import _


class Institution:
    """Institution is a "live" object, you only need to set a value on it and
    then call `write` to persist them to the database.

    Institution values are stored in the Ghini meta database and not in its own
    table
    """

    name: str
    abbreviation: str
    code: str
    contact: str
    technical_contact: str
    email: str
    tel: str
    fax: str
    address: str
    geo_latitude: str
    geo_longitude: str
    geo_zoom: str
    uuid: str

    __properties = (
        "name",
        "abbreviation",
        "code",
        "contact",
        "technical_contact",
        "email",
        "tel",
        "fax",
        "address",
        "geo_latitude",
        "geo_longitude",
        "geo_zoom",
        "uuid",
    )

    table = meta.BaubleMeta.__table__

    def __init__(self):
        for prop in self.__properties:
            # initialize properties to None
            setattr(self, prop, None)
            db_prop = str("inst_" + prop)
            result = self.table.select(self.table.c.name == db_prop).execute()
            row = result.fetchone()
            if row:
                setattr(self, prop, row["value"])
            result.close()

    def write(self):
        for prop in self.__properties:
            value = getattr(self, prop)
            db_prop = utils.nstr("inst_" + prop)
            if value is not None:
                value = utils.nstr(value)
            result = self.table.select(self.table.c.name == db_prop).execute()
            row = result.fetchone()
            result.close()
            # have to check if the property exists first because sqlite doesn't
            # raise an error if you try to update a value that doesn't exist
            # and do an insert and then catching the exception if it exists
            # and then updating the value is too slow
            if not row:
                logger.debug("insert: %s = %s", prop, value)
                self.table.insert().execute(name=db_prop, value=value)
            else:
                logger.debug("update: %s = %s", prop, value)
                self.table.update(self.table.c.name == db_prop).execute(
                    value=value
                )


class InstitutionEditorView(GenericEditorView):
    _tooltips = {
        "inst_name": _("The full name of the institution."),
        "inst_abbr": _("The standard abbreviation of the institution."),
        "inst_code": _(
            "The intitution code should be unique among all institions."
        ),
        "inst_contact": _(
            "The name of the person to contact for "
            "information related to the institution."
        ),
        "inst_tech": _(
            "The email address or phone number of the "
            "person to contact for technical "
            "information related to the institution."
        ),
        "inst_email": _("The email address of the institution."),
        "inst_tel": _("The telephone number of the institution."),
        "inst_fax": _("The fax number of the institution."),
        "inst_addr": _("The mailing address of the institition."),
        "inst_geo_latitude": _(
            "The latitude of the geographic centre of the garden."
        ),
        "inst_geo_longitude": _(
            "The longitude of the geographic centre of the garden."
        ),
        "inst_geo_zoom": _(
            "The start zoom level for maps that best displays the garden."
        ),
    }

    def __init__(self):
        filename = os.path.join(
            paths.lib_dir(), "plugins", "garden", "institution.glade"
        )
        parent = None
        root_widget_name = "inst_dialog"
        super().__init__(filename, parent, root_widget_name)


class InstitutionPresenter(editor.GenericEditorPresenter):
    widget_to_field_map = {
        "inst_name": "name",
        "inst_abbr": "abbreviation",
        "inst_code": "code",
        "inst_contact": "contact",
        "inst_tech": "technical_contact",
        "inst_email": "email",
        "inst_tel": "tel",
        "inst_fax": "fax",
        "inst_addr_tb": "address",
        "inst_geo_latitude": "geo_latitude",
        "inst_geo_longitude": "geo_longitude",
        "inst_geo_zoom": "geo_zoom",
    }

    def __init__(self, model, view):
        self.message_box = None
        self.email_regexp = re.compile(r".+@.+\..+")
        super().__init__(model, view, refresh_view=True)
        self.view.widget_grab_focus("inst_name")
        self.on_non_empty_text_entry_changed("inst_name")
        self.on_email_text_entry_changed("inst_email")
        if not model.uuid:
            import uuid

            model.uuid = str(uuid.uuid4())

    def cleanup(self):
        super().cleanup()
        if self.message_box:
            self.view.remove_box(self.message_box)
            self.message_box = None

    def on_non_empty_text_entry_changed(self, widget, value=None):
        value = super().on_non_empty_text_entry_changed(widget, value)
        box = self.message_box
        if value:
            if box:
                self.view.remove_box(box)
                self.message_box = None
        elif not box:
            box = self.view.add_message_box(utils.MESSAGE_BOX_INFO)
            box.message = _(
                "Please specify an institution name for this database."
            )
            box.show()
            self.view.add_box(box)
            self.message_box = box

    def on_email_text_entry_changed(self, widget, value=None):
        value = super().on_text_entry_changed(widget, value)

    def on_inst_addr_tb_changed(self, widget, value=None, attr=None):
        return self.on_textbuffer_changed(widget, value, attr="address")


def start_institution_editor():
    from bauble import prefs

    if prefs.testing:
        from bauble.editor import MockView

        view = MockView()
    else:
        view = InstitutionEditorView()
    model = Institution()
    inst_pres = InstitutionPresenter(model, view)
    response = inst_pres.start()
    if response == Gtk.ResponseType.OK:
        model.write()
        inst_pres.commit_changes()
    else:
        inst_pres.session.rollback()
    inst_pres.session.close()


class InstitutionCommand(pluginmgr.CommandHandler):
    command = ("inst", "institution")
    view = None

    def __call__(self, cmd, arg):
        InstitutionTool.start()


class InstitutionTool(pluginmgr.Tool):
    label = _("Institution")

    @classmethod
    def start(cls):
        start_institution_editor()
