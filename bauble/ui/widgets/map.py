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
Mapping related widgets.
"""
import logging

logger = logging.getLogger(__name__)

import json
import re
from collections.abc import Callable
from typing import Protocol

from gi.repository import Gio
from gi.repository import GObject
from gi.repository import Gtk

from bauble.i18n import _
from bauble.ui.utils import get_clipboard
from bauble.ui.utils import get_window_from_widget
from bauble.utils import geo as geo_utils

from .. import dialogs


class ModelWGeojson(Protocol):  # pylint: disable=too-few-public-methods
    __tablename__: str
    geojson: str | None


class MapMenuButton(Gtk.MenuButton):
    """MenuButton widget for use in editors of models with geojson.

    To use, include the widget, either in the ``.ui`` file or directly.  Call
    ``init`` on instantiation supplying the database model and appropriate
    ``KMLMapCallbackFunctor``. Connect to the ``changed`` signal to handle
    updates to the model's geojson. e.g.::

        @Gtk.Template(filename="/path/to/file.ui"))
        class Foo(Gtk.Dialog):

            __gtype_name__ = "Foo"

            map_menu_btn = cast(MapMenuButton, Gtk.Template.Child())

            def __init__(self, model: FooModel) -> None:
                super().__init__()

                self.map_menu_btn.init(model)
                self.map_menu_btn.connect('changed', self.on_changed)

            def on_changed(self, map_menu_btn: MapMenuButton) -> None:
                self.update()
                ...

    """

    __gtype_name__ = "MapMenuButton"

    __gsignals__: dict = {"changed": (GObject.SignalFlags.RUN_FIRST, None, ())}

    def __init__(self) -> None:
        super().__init__()
        self.model: ModelWGeojson
        self.kml_callback: geo_utils.KMLMapCallbackFunctor

    def init(
        self,
        model: ModelWGeojson,
        kml_callback: geo_utils.KMLMapCallbackFunctor,
    ) -> None:
        """Initialise the menu button."""
        self.model = model
        self.kml_callback = kml_callback

        self.setup_menu()
        self.set_tooltip()
        # ensure destroys with parent
        parent = self.get_parent()
        if parent:
            parent.connect("destroy", self.on_destroy)

    def setup_menu(self) -> None:
        menu = Gio.Menu()
        action_name = self.model.__tablename__.lower() + "_map"
        action_group = Gio.SimpleActionGroup()

        menu_items: tuple[tuple[str, str, Callable[..., None]], ...] = (
            (_("Copy"), "copy", self.on_map_copy),
            (_("Paste"), "paste", self.on_map_paste),
            (_("Delete"), "delete", self.on_map_delete),
            (_("Show"), "show", self.on_map_kml_show),
        )

        image = Gtk.Image.new_from_icon_name(
            "location-services-active-symbolic",
            Gtk.IconSize.BUTTON,
        )

        if not self.model.geojson:
            menu_items = (menu_items[1],)
            image = Gtk.Image.new_from_icon_name(
                "location-services-disabled-symbolic",
                Gtk.IconSize.BUTTON,
            )

        self.set_image(image)

        for label, name, handler in menu_items:
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", handler)
            action_group.add_action(action)
            menu_item = Gio.MenuItem.new(label, f"{action_name}.{name}")
            menu.append_item(menu_item)

        self.set_menu_model(menu)
        self.insert_action_group(action_name, action_group)

    def set_tooltip(self) -> None:
        tooltip = _(
            "Links Menu - the items here are a selection of the Links "
            "available in the search results view info box (right hand pane) "
            "for the same type.  You can include others by adding:\n"
            "\t'editor_button': True\n"
            "to their definitions in the preferences."
        )
        self.set_tooltip_text(tooltip)

    def on_destroy(self, _parent: Gtk.Widget) -> None:
        self.destroy()

    def on_map_copy(self, *_args) -> None:
        # convert to JSON string and copy to clipboard
        geojson = json.dumps(self.model.geojson)
        clipboard = get_clipboard()

        if clipboard:
            clipboard.set_text(geojson, -1)

    def on_map_paste(self, *_args) -> None:
        clipboard = get_clipboard()

        if not clipboard:
            return

        text = clipboard.wait_for_text()

        if not text:
            return

        if re.match(r"-?\d{1,2}\.\d*, -?\d{1,3}\.\d*", text):
            text = geo_utils.web_mercator_point_coords_to_geojson(text)
        elif text.startswith("<?xml"):
            text = geo_utils.kml_string_to_geojson(text)

        try:
            geojson = json.loads(text)
            # basic validation...
            if not set(geojson.keys()) == {"type", "coordinates"}:
                raise AttributeError(
                    "wrong keys, need 'type' and 'coordinates'"
                )
            if self.model.geojson != geojson:
                self.model.geojson = geojson
                self.emit("changed")
                self.setup_menu()

        except (AttributeError, json.JSONDecodeError) as e:
            logger.debug("geojson paste %s(%s)", type(e).__name__, e)
            logger.debug("geojson paste %s", text)

            dialogs.message_dialog(
                _("Paste failed, invalid geojson?"),
                parent=get_window_from_widget(self),
            )

    def on_map_delete(self, *_args) -> None:
        msg = _("Are you sure you want to delete spatial data?")
        if dialogs.yes_no_dialog(
            msg,
            parent=get_window_from_widget(self),
            yes_delay=1,
        ):
            if self.model.geojson:
                self.model.geojson = None
                self.emit("changed")
                self.setup_menu()

    def on_map_kml_show(self, *_args) -> None:
        self.kml_callback([self.model])
