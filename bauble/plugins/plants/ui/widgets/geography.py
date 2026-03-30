# Copyright 2008-2010 Brett Adams
# Copyright 2012-2015 Mario Frasca <mario@anche.no>.
# Copyright 2021-2024 Ross Demuth <rossdemuth123@gmail.com>
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
Generic Geography widgets.
"""
import logging

logger = logging.getLogger(__name__)

import threading
from collections.abc import Callable
from operator import itemgetter

from gi.repository import Gio
from gi.repository import GLib
from gi.repository import Gtk
from sqlalchemy import event
from sqlalchemy import select

from bauble import db

from ...geography import Geography


class GeographyMenu(Gio.Menu):
    """Menu that attaches to a button for geography selection.

    NOTE: the menu is populated in a thread.  The button supplied to
    ``attach_new`` should be set insensitive and will be set sensitive when the
    menu is ready and attached.

    Usage example::

        def __init__(self):
            GeographyMenu.attach_new(self.on_activate_menu_item, geo_button)

        # signal handler for the menu item activation
        def on_activate_menu_item(self, action, geo_id): ...

    """

    ACTION_NAME = "geography_activated"

    _geos_ordered: dict[int | None, list[tuple[int, str]]] = {}

    def __init__(self) -> None:
        super().__init__()
        self._populate()

    @classmethod
    def attach_new(
        cls,
        handler: Callable[[Gio.SimpleAction, GLib.Variant], None],
        button: Gtk.Button,
    ) -> None:

        threading.Thread(
            target=cls._create,
            args=(handler, button),
            daemon=True,
        ).start()

    @classmethod
    def _create(
        cls,
        handler: Callable[[Gio.SimpleAction, GLib.Variant], None],
        button: Gtk.Button,
    ) -> None:

        logger.debug("new geography menu %s", button)
        menu_model = cls()
        GLib.idle_add(menu_model._attach, handler, button)

    def _attach(
        self,
        handler: Callable[[Gio.SimpleAction, GLib.Variant], None],
        button: Gtk.Button,
    ) -> None:
        self._attach_action_group(handler, button)
        menu = Gtk.Menu.new_from_model(self)
        menu.attach_to_widget(button)

        button.connect(
            "button-press-event",
            lambda w, e: menu.popup_at_pointer(e),
        )

        button.set_sensitive(True)

    @property
    def geos_ordered(self) -> dict[int | None, list[tuple[int, str]]]:
        if not self._geos_ordered:
            geography_table = Geography.__table__
            stmt = select(
                [
                    geography_table.c.id,
                    geography_table.c.name,
                    geography_table.c.parent_id,
                ]
            )
            with db.engine.begin() as connection:
                geos = connection.execute(stmt).all()

            geos_ordered: dict[int | None, list[tuple[int, str]]] = {}
            for id_, name, parent_id in geos:
                geos_ordered.setdefault(parent_id, []).append((id_, name))

            for kids in geos_ordered.values():
                kids.sort(key=itemgetter(1))  # sort by name

            type(self)._geos_ordered = geos_ordered
        return self._geos_ordered

    def _attach_action_group(
        self,
        handler: Callable[[Gio.SimpleAction, GLib.Variant], None],
        button: Gtk.Button,
    ) -> None:
        action = Gio.SimpleAction.new(self.ACTION_NAME, GLib.VariantType("s"))
        action.connect("activate", handler)
        action_group = Gio.SimpleActionGroup()
        action_group.add_action(action)
        button.insert_action_group("geo", action_group)

    def _build_menu(self, geo_id: int, name: str) -> Gio.MenuItem | Gio.Menu:
        next_level = self.geos_ordered.get(geo_id)

        if next_level:
            submenu = Gio.Menu()
            item = Gio.MenuItem.new(name, f"geo.{self.ACTION_NAME}::{geo_id}")
            submenu.append_item(item)
            section = Gio.Menu()
            submenu.append_section(None, section)
            for id_, name_ in next_level:
                next_item = self._build_menu(id_, name_)
                if isinstance(next_item, Gio.MenuItem):
                    section.append_item(next_item)
                else:
                    section.append_submenu(name_, next_item)
            # result
            return submenu

        # base case
        return Gio.MenuItem.new(name, f"geo.{self.ACTION_NAME}::{geo_id}")

    def _populate(self) -> None:
        """add geography value to the menu, any top level items that don't
        have any kids are appended to the bottom of the menu
        """

        if not self.geos_ordered:
            # we would get here if the geos_ordered isn't populated, usually
            # during a unit test
            return

        no_kids = []

        for geo_id, geo_name in self.geos_ordered[None]:
            menu = self._build_menu(geo_id, geo_name)

            if isinstance(menu, Gio.Menu):
                self.append_submenu(geo_name, menu)
            else:
                no_kids.append(menu)

        for item in no_kids:
            # append to the end of the menu
            self.append_item(item)

    @classmethod
    def reset(cls) -> None:
        cls._geos_ordered = {}


# update the menu in the event of any changes (should be rare)
@event.listens_for(Geography, "after_update")
def geography_after_update(_mapper, _connection, _target) -> None:
    GeographyMenu.reset()


@event.listens_for(Geography, "after_insert")
def geography_after_insert(_mapper, _connection, _target) -> None:
    GeographyMenu.reset()


@event.listens_for(Geography, "after_delete")
def geography_after_delete(_mapper, _connection, _target) -> None:
    GeographyMenu.reset()
