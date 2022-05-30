# Copyright (c) 2005,2006,2007,2008,2009 Brett Adams <brett@belizebotanic.org>
# Copyright (c) 2012-2015 Mario Frasca <mario@anche.no>
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
# meta.py
#
from sqlalchemy import Unicode, UnicodeText, Column

from bauble import db
from bauble import utils

VERSION_KEY = 'version'
CREATED_KEY = 'created'
REGISTRY_KEY = 'registry'

DATE_FORMAT_KEY = 'date_format'


def get_default(name, default=None, session=None):
    """Get a BaubleMeta object with name.

    If the default value is not None then a BaubleMeta object is returned with
    name and the default value given.

    If a session instance is passed (session != None) then we
    don't commit the session.
    """
    commit = False
    if not session:
        session = db.Session()
        commit = True
    query = session.query(BaubleMeta)
    meta = query.filter_by(name=name).first()
    if not meta and default is not None:
        meta = BaubleMeta(name=utils.nstr(name), value=default)
        session.add(meta)
        if commit:
            session.commit()
            # load the properties so that we can close the session and
            # avoid getting errors when accessing the properties on the
            # returned meta
            meta.value
            meta.name

    if commit:
        # close the session whether we added anything or not
        session.close()
    return meta


def confirm_default(name, default, msg, parent=None):
    """Allow the user to confirm the value of a BaubleMeta object the first
    time it is needed.
    """
    current_default = get_default(name)
    if not current_default:
        from gi.repository import Gtk  # noqa
        import bauble
        if bauble.gui:
            parent = bauble.gui.window
        dialog = utils.create_message_dialog(msg=msg,
                                             parent=parent,
                                             resizable=False)
        box = dialog.get_message_area()
        frame = Gtk.Frame(shadow_type=Gtk.ShadowType.NONE)
        label = Gtk.Label(justify=Gtk.Justification.LEFT)
        label.set_markup(f"<b>{name}:</b>")
        frame.set_label_widget(label)
        entry = Gtk.Entry()
        entry.set_text(default)
        frame.add(entry)
        box.add(frame)
        dialog.resize(1, 1)
        dialog.show_all()
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            current_default = get_default(name, entry.get_text())

        dialog.destroy()
    return current_default


class BaubleMeta(db.Base):
    """The BaubleMeta class is used to set and retrieve meta information
    based on key/name values from the bauble meta table.

    :Table name: bauble

    :Columns:
      *name*:
        The name of the data.

      *value*:
        The value.
    """
    __tablename__ = 'bauble'
    name = Column(Unicode(64), unique=True)
    value = Column(UnicodeText)
