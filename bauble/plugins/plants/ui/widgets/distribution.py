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
SpeciesDistribution widgets.
"""

import logging

logger = logging.getLogger(__name__)

import re
import textwrap
from pathlib import Path
from typing import cast

from gi.repository import Gdk
from gi.repository import Gio
from gi.repository import GLib
from gi.repository import GObject
from gi.repository import Gtk
from sqlalchemy import select
from sqlalchemy.orm import Session

from bauble import utils
from bauble.i18n import _
from bauble.ui import dialogs
from bauble.ui.utils import get_clipboard

from ...geography import Geography
from ...geography import consolidate_geographies
from ...species_model import Species
from ...species_model import SpeciesDistribution
from .geography import GeographyMenu

parent = Path(__file__).resolve().parent


@Gtk.Template(filename=str(parent / "dist_presenter.ui"))
class DistributionPresenter(Gtk.Frame):
    MENU_ACTIONGRP_NAME = "distribution_menu_btn"

    __gtype_name__ = "DistributionPresenter"

    __gsignals__ = {
        "changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    label = cast(Gtk.Label, Gtk.Template.Child())
    add_button = cast(Gtk.Button, Gtk.Template.Child())
    remove_button = cast(Gtk.Button, Gtk.Template.Child())
    menu_button = cast(Gtk.MenuButton, Gtk.Template.Child())

    def __init__(self) -> None:
        super().__init__()
        self.model: Species
        self.session: Session
        self.remove_menu_model: Gio.Menu
        self.remove_menu: Gtk.Menu

    def init(self, model: Species, session: Session) -> None:
        self.model = model
        self.session = session

        GeographyMenu.attach_new(
            self.on_activate_add_menu_item, self.add_button
        )

        self.remove_menu_model = Gio.Menu()
        action = Gio.SimpleAction.new(
            "geography_remove", GLib.VariantType("s")
        )
        action.connect("activate", self.on_activate_remove_menu_item)

        action_group = Gio.SimpleActionGroup()
        action_group.add_action(action)

        self.remove_button.insert_action_group("geo", action_group)

        self.remove_menu = Gtk.Menu.new_from_model(self.remove_menu_model)
        self.remove_menu.attach_to_widget(self.remove_button, None)

        self.add_button.set_sensitive(False)

        menu = Gio.Menu()
        action_group = Gio.SimpleActionGroup()
        menu_items = (
            (_("Clear All"), "clear", self.on_clear_all),
            (_("Consolidate"), "consolidate", self.on_consolidate),
            (_("Paste - append"), "append", self.on_paste_append),
            (_("Paste - replace all"), "replace", self.on_paste_replace),
            (_("Copy Codes"), "copy_codes", self.on_copy_codes),
            (_("Copy Names"), "copy_names", self.on_copy_names),
        )
        for label, name, handler in menu_items:
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", handler)
            action_group.add_action(action)
            menu_item = Gio.MenuItem.new(
                label, f"{self.MENU_ACTIONGRP_NAME}.{name}"
            )
            menu.append_item(menu_item)

        self.menu_button.set_menu_model(menu)

        self.menu_button.insert_action_group(
            self.MENU_ACTIONGRP_NAME,
            action_group,
        )
        self.refresh_label()

    def update(self) -> None:
        self.refresh_label()
        self.emit("changed")

    def on_clear_all(self, *_args) -> None:
        """Clear all distributions."""
        self.model.distribution = []
        self.update()

    def append_dists_from_text(self, text: str) -> None:
        """Given a string of comma seperated names or codes, attempt to match
        them to WGSRPD units and append them to the current distributions.

        If any errors resolving names let the user know and return.
        """

        geo_names = [i.strip() for i in text.strip().split(",")]

        levels_counter: dict[int, int] = {}
        name_map: dict[str, list[Geography]] = {}
        unresolved = set()

        code_re = re.compile(r"^[0-9A-Z-]{1,6}$")
        # if text contains only codes
        if all(code_re.match(i) for i in geo_names):
            geos = self.session.execute(
                select(Geography).where(Geography.code.in_(geo_names))
            ).scalars()

            for geo in geos:
                name_map.setdefault(geo.code, []).append(geo)
                val = levels_counter.get(geo.level, 0) + 1
                levels_counter[geo.level] = val

            for code in geo_names:
                if code not in name_map:
                    unresolved.add(code)
        else:
            # get the full names first - low hanging fruit
            geos = self.session.execute(
                select(Geography).where(Geography.name.in_(geo_names))
            ).scalars()

            for geo in geos:
                name_map.setdefault(geo.name, []).append(geo)
                val = levels_counter.get(geo.level, 0) + 1
                levels_counter[geo.level] = val

            # then the abbreviated
            for name in geo_names:
                if not name:
                    unresolved.add(name)
                elif name not in name_map:
                    geos_list = (
                        self.session.execute(
                            select(Geography).where(
                                utils.ilike(Geography.name, f"{name}%")
                            )
                        )
                        .scalars()
                        .all()
                    )
                    if not geos_list:
                        unresolved.add(name)
                    for geo in geos_list:
                        name_map.setdefault(geo.name, []).append(geo)
                        val = levels_counter.get(geo.level, 0) + 1
                        levels_counter[geo.level] = val

        if unresolved:
            msg = _('Could not resolve "%s"') % ", ".join(unresolved)
            # for sake of tests
            toplevel = self.get_toplevel()
            if toplevel is self:
                parent_window = None
            else:
                parent_window = cast(Gtk.Window, toplevel)

            dialogs.message_dialog(
                msg,
                Gtk.MessageType.ERROR,
                parent=parent_window,
            )
            logger.debug(msg)
            return

        geos_final: set[Geography] = set()
        for geo_list in name_map.values():
            # heuristic choice: highest level or most common level
            if len(geo_list) > 1:
                if len(set(levels_counter.values())) == 1:
                    geo_list = [
                        sorted(geo_list, key=lambda i: i.level, reverse=True)[
                            0
                        ]
                    ]
                else:
                    geo_list = [
                        sorted(
                            geo_list,
                            key=lambda i: levels_counter[i.level],
                            reverse=True,
                        )[0]
                    ]
            geos_final.add(geo_list[0])

        existing_geos = [dist.geography for dist in self.model.distribution]

        for geo in sorted(geos_final, key=lambda i: i.name):
            if geo not in existing_geos:
                dist = SpeciesDistribution(geography=geo)
                self.model.distribution.append(dist)

        self.update()

    def on_consolidate(self, *_args) -> None:
        geos = [i.geography for i in self.model.distribution]
        dists = []

        for geo in sorted(consolidate_geographies(geos), key=lambda i: i.name):
            dist = SpeciesDistribution(geography=geo)
            dists.append(dist)

        self.model.distribution = dists

        self.update()

    def on_paste_append(self, *_args) -> None:
        clipboard = get_clipboard()
        if not clipboard:
            return

        text = clipboard.wait_for_text()
        self.append_dists_from_text(text or "")

    def on_paste_replace(self, *_args) -> None:
        clipboard = get_clipboard()
        if not clipboard:
            return

        self.model.distribution = []
        text = clipboard.wait_for_text()
        self.append_dists_from_text(text or "")

    def on_copy_codes(self, *_args) -> None:
        clipboard = get_clipboard()
        if not clipboard:
            return

        txt = ", ".join([d.geography.code for d in self.model.distribution])
        clipboard.set_text(txt, -1)

    def on_copy_names(self, *_args) -> None:
        clipboard = get_clipboard()
        if not clipboard:
            return

        txt = ", ".join([d.geography.name for d in self.model.distribution])
        clipboard.set_text(txt, -1)

    def refresh_label(self) -> None:
        txt = ", ".join(str(d) for d in self.model.distribution)
        self.label.set_text(
            textwrap.shorten(txt, width=500, placeholder=" ...")
        )

    @Gtk.Template.Callback()
    def on_remove_button_pressed(
        self,
        _button: Gtk.Button,
        event: Gdk.EventButton,
    ) -> None:
        # clear the menu first
        self.remove_menu_model.remove_all()
        # populate the menu
        for dist in self.model.distribution:
            # NOTE can't use dist.id as dist may not have been committed yet.
            item = Gio.MenuItem.new(
                str(dist), f"geo.geography_remove::{dist.geography.id}"
            )
            self.remove_menu_model.append_item(item)

        self.remove_menu.popup_at_pointer(event)

    def on_activate_add_menu_item(
        self,
        _action: Gio.SimpleAction,
        geo_id: GLib.Variant,
    ) -> None:
        _id = int(geo_id.unpack())

        geo = self.session.get(Geography, _id)
        if not geo:
            logger.debug("Can't find Geography with ID: %s", _id)
            return
        # check that this geography isn't already in the distributions
        if geo in [d.geography for d in self.model.distribution]:
            logger.debug("%s already in %s", geo, self.model)
            return
        dist = SpeciesDistribution(geography=geo)
        self.model.distribution.append(dist)

        self.update()

    def on_activate_remove_menu_item(
        self,
        _action: Gio.SimpleAction,
        geo_id: GLib.Variant,
    ) -> None:
        _id = int(geo_id.unpack())
        dist = [i for i in self.model.distribution if i.geography.id == _id][0]
        self.model.distribution.remove(dist)
        utils.delete_or_expunge(dist)

        self.update()
