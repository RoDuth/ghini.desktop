# Copyright (c) 2005,2006,2007,2008,2009 Brett Adams <brett@belizebotanic.org>
# Copyright (c) 2012-2015 Mario Frasca <mario@anche.no>
# Copyright (c) 2020-2023 Ross Demuth <rossdemuth123@gmail.com>
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
import logging

from sqlalchemy import Column
from sqlalchemy import Unicode
from sqlalchemy import UnicodeText
from sqlalchemy import event
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

from bauble import db
from bauble import utils

VERSION_KEY = "version"
CREATED_KEY = "created"
REGISTRY_KEY = "registry"

DATE_FORMAT_KEY = "date_format"


@utils.timed_cache(secs=None)
def get_cached_value(name):
    session = db.Session()
    query = session.query(BaubleMeta)
    meta = query.filter_by(name=name).first()
    value = meta.value if meta else None
    logger.debug("get_cached_value from database: %s=%s", name, value)
    session.close()
    return value


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
        dialog = utils.create_message_dialog(
            msg=msg, parent=parent, resizable=False
        )
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


def set_value(names, defaults, msg, parent=None):
    """Allow the user to change the value of a BaubleMeta object at any time.

    :param names: a string or iterable of strings, an iterable of names
        allows setting multiple values.
    :param defaults: a string or iterable of strings, if names is an interable
        of names this should be a corresponding iterable in the same length and
        order as names.
    :param msg: the message to display in the dialog.
    :param parent: the parent window
    """
    logger.debug("set_value for %s", names)
    meta = None
    from gi.repository import Gtk  # noqa

    import bauble

    if bauble.gui:
        parent = bauble.gui.window
    dialog = utils.create_message_dialog(
        msg=msg, parent=parent, resizable=False
    )
    box = dialog.get_message_area()
    if isinstance(names, str):
        names = [names]
        defaults = [defaults]
    entry_map = {}
    for name, default in zip(names, defaults):
        frame = Gtk.Frame(shadow_type=Gtk.ShadowType.NONE)
        label = Gtk.Label(justify=Gtk.Justification.LEFT)
        label.set_markup(f"<b>{name}:</b>")
        frame.set_label_widget(label)
        entry = Gtk.Entry()
        entry_map[name] = entry
        entry.set_text(default)
        frame.add(entry)
        box.add(frame)
    dialog.resize(1, 1)
    dialog.show_all()
    response = dialog.run()
    metas = []
    if response == Gtk.ResponseType.OK:
        session = db.Session()
        for name, entry in entry_map.items():
            value = entry.get_text()
            if not value:
                logger.debug("no value for %s", name)
                continue
            meta = session.query(BaubleMeta).filter_by(name=name).first()
            meta = meta or BaubleMeta(name=name)
            meta.value = value
            session.add(meta)
            logger.debug("committing %s: %s", name, value)
            session.commit()
            metas.append(meta)
        for meta in metas:
            # load the properties to avoid DetachedInstanceError
            # pylint: disable=pointless-statement
            meta.name
            meta.value

        session.close()

    dialog.destroy()
    return metas


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

    __tablename__ = "bauble"
    name = Column(Unicode(64), unique=True)
    value = Column(UnicodeText)


def get_default(
    name: str, default: str | None = None, session: Session | None = None
) -> BaubleMeta | None:
    """Get a BaubleMeta object with name.

    If the default value is not None then a BaubleMeta object is returned with
    name and the default value given.

    If a session instance is passed (session != None) then we
    don't commit the session.
    """
    commit = False
    if not session and db.Session:
        session = db.Session()
        commit = True

    if not session:
        return None

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
            # pylint: disable=pointless-statement
            meta.value
            meta.name

    if commit:
        # close the session whether we added anything or not
        session.close()
    return meta


@event.listens_for(BaubleMeta, "after_insert")
@event.listens_for(BaubleMeta, "after_delete")
@event.listens_for(BaubleMeta, "after_update")
def meta_after_execute(*_args):
    """Clear cache on any commits to BaubleMeta."""
    logger.debug("clearing meta.get_cache_value cache")
    get_cached_value.clear_cache()
