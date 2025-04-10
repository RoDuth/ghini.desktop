# Copyright (c) 2023-2024 Ross Demuth <rossdemuth123@gmail.com>
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
A map to display locations and plants (from the current search results).
"""
import logging

logger = logging.getLogger(__name__)

import threading
import urllib.parse
from abc import ABC
from abc import abstractmethod
from collections.abc import Callable
from collections.abc import Sequence
from dataclasses import astuple
from dataclasses import dataclass
from itertools import chain
from math import hypot
from pathlib import Path
from typing import TypedDict
from typing import cast

import gi

gi.require_version("OsmGpsMap", "1.0")
gi.require_version("GdkPixbuf", "2.0")

from gi.repository import Gdk
from gi.repository import GdkPixbuf
from gi.repository import Gio
from gi.repository import GLib
from gi.repository import Gtk
from gi.repository import OsmGpsMap  # NOTE mypy [attr-defined] only on file
from sqlalchemy import Table
from sqlalchemy import case
from sqlalchemy import engine
from sqlalchemy import event
from sqlalchemy import select

import bauble
from bauble import db
from bauble import paths
from bauble import prefs
from bauble import utils
from bauble.i18n import _
from bauble.pluginmgr import Viewable
from bauble.utils import timed_cache
from bauble.utils.geo import is_point_within_poly
from bauble.utils.geo import polylabel
from bauble.utils.web import get_net_sess
from bauble.view import SearchView
from bauble.view import get_search_view
from bauble.view import get_search_view_selected
from bauble.view import select_in_search_results

from .institution import Institution
from .location import Location
from .plant import Plant

MAP_TILES_PREF_KEY = "garden.garden_map.base_tiles"
"""
The preferences key for the URI to the source for tiles.
"""

MAP_TILES_PROXY_PREF_KEY = "garden.garden_map.base_tiles_proxy"
"""
The preferences key for the proxy for the tiles URI if required.
"""

MAP_PLANT_COLOUR_PREF_KEY = "garden.garden_map.plant_colour"
"""
The preferences key for the colour of plants on the map that are not selected.
"""

MAP_PLANT_SELECTED_COLOUR_PREF_KEY = "garden.garden_map.selected_plant_colour"
"""
The preferences key for the colour of plants on the map that are selected.
"""

MAP_PLANT_DEAD_COLOUR_PREF_KEY = "garden.garden_map.dead_plant_colour"
"""
The preferences key for the colour of dead plants on the map.
"""

MAP_LOCATION_COLOUR_PREF_KEY = "garden.garden_map.location_colour"
"""
The preferences key for the colour of locations on the map that are not
selected.
"""

MAP_LOCATION_SELECTED_COLOUR_PREF_KEY = (
    "garden.garden_map.selected_location_colour"
)
"""
The preferences key for the colour of locations on the map that are selected.
"""

# Types
GEOJSONPoly = TypedDict(
    "GEOJSONPoly", {"type": str, "coordinates": list[list[list[float]]]}
)
GEOJSONLine = TypedDict(
    "GEOJSONLine", {"type": str, "coordinates": list[list[float]]}
)
GEOJSONPoint = TypedDict(
    "GEOJSONPoint", {"type": str, "coordinates": list[float]}
)


@dataclass
class Colour:
    """A MapItem type agnostic colour.

    :param index: int for convenience represents its Position within the
        colours dict
    :param name: string represnetation of the colour for convenience, used in
        prefs.
    :param image: the appropriate Pixbuf for this colour, used for points.
    :param rgba: the appropriate RGBA for this colour, used for polygons and
        lines.
    """

    index: int
    name: str
    image: GdkPixbuf.Pixbuf | None
    rgba: Gdk.RGBA


@dataclass
class BoundingBox:
    """Represent the extents of a map area."""

    max_lat: float | None = None
    min_lat: float | None = None
    max_long: float | None = None
    min_long: float | None = None

    def update(self, lats: list[float], longs: list[float]) -> None:
        """Update the max and min lat and long from a list of lats and longs

        Adjusts the current values (if they exist).
        """
        if self.max_lat is not None:
            values = lats + [self.max_lat]
        else:
            values = lats
        self.max_lat = max(values)

        if self.min_lat is not None:
            values = lats + [self.min_lat]
        else:
            values = lats
        self.min_lat = min(values)

        if self.max_long is not None:
            values = longs + [self.max_long]
        else:
            values = longs
        self.max_long = max(values)

        if self.min_long is not None:
            values = longs + [self.min_long]
        else:
            values = longs
        self.min_long = min(values)

    def clear(self) -> None:
        """Clear the current values."""
        self.max_lat = None
        self.min_lat = None
        self.max_long = None
        self.min_long = None


colours: dict[str, Colour] = {
    "green": Colour(
        0,
        "green",
        GdkPixbuf.Pixbuf.new_from_file_at_size(
            str(Path(paths.lib_dir(), "images", "green_point.png")), 6, 6
        ),
        Gdk.RGBA(0.0, 0.56, 0.0, 0.0),
    ),
    "yellow": Colour(
        1,
        "yellow",
        GdkPixbuf.Pixbuf.new_from_file_at_size(
            str(Path(paths.lib_dir(), "images", "yellow_point.png")), 6, 6
        ),
        Gdk.RGBA(1.0, 1.0, 0.0, 0.0),
    ),
    "blue": Colour(
        2,
        "blue",
        GdkPixbuf.Pixbuf.new_from_file_at_size(
            str(Path(paths.lib_dir(), "images", "blue_point.png")), 6, 6
        ),
        Gdk.RGBA(0.0, 0.0, 1.0, 0.0),
    ),
    "red": Colour(
        3,
        "red",
        GdkPixbuf.Pixbuf.new_from_file_at_size(
            str(Path(paths.lib_dir(), "images", "red_point.png")), 6, 6
        ),
        Gdk.RGBA(1.0, 0.0, 0.0, 0.0),
    ),
    "black": Colour(
        4,
        "black",
        GdkPixbuf.Pixbuf.new_from_file_at_size(
            str(Path(paths.lib_dir(), "images", "black_point.png")), 6, 6
        ),
        Gdk.RGBA(0.0, 0.0, 0.0, 0.0),
    ),
    "grey": Colour(
        5,
        "grey",
        GdkPixbuf.Pixbuf.new_from_file_at_size(
            str(Path(paths.lib_dir(), "images", "grey_point.png")), 6, 6
        ),
        Gdk.RGBA(0.5, 0.5, 0.5, 0.0),
    ),
    "white": Colour(
        6,
        "white",
        GdkPixbuf.Pixbuf.new_from_file_at_size(
            str(Path(paths.lib_dir(), "images", "white_point.png")), 6, 6
        ),
        Gdk.RGBA(1.0, 1.0, 1.0, 0.0),
    ),
    "violet": Colour(
        7,
        "violet",
        GdkPixbuf.Pixbuf.new_from_file_at_size(
            str(Path(paths.lib_dir(), "images", "violet_point.png")), 6, 6
        ),
        Gdk.RGBA(0.37, 0.0, 0.63, 0.0),
    ),
}


glib_events: dict[int, GLib.Source] = {}


class MapItem(ABC):
    """Base class for the various OsmGpsMap map item adaptors."""

    coordinates: list

    @abstractmethod
    def create_item(self) -> None:
        """Create the OsmGpsMap map item for this item"""

    @abstractmethod
    def add_to_map(self, map_: OsmGpsMap.Map, glib=True) -> None:
        """Add this item to the supplied map"""

    @abstractmethod
    def remove_from_map(self, map_: OsmGpsMap.Map) -> None:
        """Remove this item from the supplied map"""

    @abstractmethod
    def set_colour(self, colour: Colour) -> None:
        """Set the colour for this item"""

    @abstractmethod
    def get_lats_longs(self) -> tuple[list[float], list[float]]:
        """Return the latitudes and longitudes for this item"""


class MapPoly(MapItem):
    LABEL_TEMPLATE = (
        '<svg width="110%" xmlns="http://www.w3.org/2000/svg">'
        "<g><text "
        'style="'
        "font: bold 12px sans-serif; "
        "stroke: white; "
        "stroke-width: 2px; "
        'paint-order: stroke" '
        'y="100%">{label_text}</text></g></svg>'
    )

    def __init__(
        self,
        id_: int,
        geojson: GEOJSONPoly,
        colour: Colour,
        label_txt: str = "",
    ) -> None:
        if not geojson["type"] == "Polygon":
            raise TypeError("the provided geojson is not of type Polygon")
        self.id_ = id_
        self.coordinates = geojson["coordinates"]
        self.rgba = colour.rgba
        self.label_txt = label_txt
        self._poly: OsmGpsMap.MapPolygon | None = None
        self._label: GdkPixbuf.Pixbuf | None = None

    @property
    def poly(self) -> OsmGpsMap.MapPolygon:
        if not self._poly:
            self.create_item()
        return self._poly

    def create_item(self) -> None:
        self._poly = OsmGpsMap.MapPolygon.new()
        track = self._poly.get_track()
        track.set_color(self.rgba)
        track.set_property("alpha", 1.0)
        track.set_property("line_width", 2)
        for point in self.coordinates[0]:
            track.add_point(OsmGpsMap.MapPoint.new_degrees(*point[::-1]))

    @property
    def label(self) -> OsmGpsMap.MapImage:
        if not self._label:
            self.create_label()
        return self._label

    def create_label(self) -> None:
        loader = GdkPixbuf.PixbufLoader()
        lbl_svg = self.LABEL_TEMPLATE.format(label_text=self.label_txt)
        loader.write(lbl_svg.encode())
        loader.close()
        self._label = loader.get_pixbuf()

    def add_to_map(
        self, map_: OsmGpsMap.Map, glib=True, with_label=False
    ) -> None:
        if not glib or glib_events.get(self.id_):
            map_.polygon_add(self.poly)
            if with_label:
                long, lat = polylabel(self.coordinates, precision=0.0001)
                map_.image_add(lat, long, self.label)
            if glib:
                del glib_events[self.id_]

    def remove_from_map(self, map_: OsmGpsMap.Map) -> None:
        map_.polygon_remove(self.poly)

    def set_colour(self, colour: Colour) -> None:
        if self.rgba != colour.rgba:
            self.rgba = colour.rgba
            track = self.poly.get_track()
            track.set_color(self.rgba)

    def set_props(self, **kwargs) -> None:
        track = self.poly.get_track()
        for k, v in kwargs.items():
            track.set_property(k, v)

    def update(self, geojson: GEOJSONPoly) -> None:
        if self.coordinates != geojson["coordinates"]:
            self.coordinates = geojson["coordinates"]
        else:
            return

        track = self.poly.get_track()
        for __ in range(track.n_points()):
            track.remove_point(0)

        for point in self.coordinates[0]:
            track.add_point(OsmGpsMap.MapPoint.new_degrees(*point[::-1]))

    def get_lats_longs(self) -> tuple[list[float], list[float]]:
        lats = []
        longs = []
        for point in self.poly.get_track().get_points():
            lat, long = point.get_degrees()
            lats.append(lat)
            longs.append(long)
        return lats, longs


class MapLine(MapItem):
    def __init__(self, id_: int, geojson: GEOJSONLine, colour: Colour) -> None:
        if not geojson["type"] == "LineString":
            raise TypeError("the provided geojson is not of type LineString")
        self.id_ = id_
        self.coordinates = geojson["coordinates"]
        self.rgba = colour.rgba
        self._line: OsmGpsMap.MapTrack | None = None

    @property
    def line(self) -> OsmGpsMap.MapTrack:
        if not self._line:
            self.create_item()
        return self._line

    def create_item(self) -> None:
        self._line = OsmGpsMap.MapTrack()
        self._line.set_color(self.rgba)
        self._line.set_property("alpha", 1.0)
        for point in self.coordinates:
            self._line.add_point(OsmGpsMap.MapPoint.new_degrees(*point[::-1]))

    def add_to_map(self, map_: OsmGpsMap.Map, glib=True) -> None:
        if not glib or glib_events.get(self.id_):
            map_.track_add(self.line)
            if glib:
                del glib_events[self.id_]

    def remove_from_map(self, map_: OsmGpsMap.Map) -> None:
        map_.track_remove(self.line)

    def set_colour(self, colour: Colour) -> None:
        if self.rgba != colour.rgba:
            self.rgba = colour.rgba
            self.line.set_color(self.rgba)

    def get_lats_longs(self) -> tuple[list[float], list[float]]:
        lats = []
        longs = []
        for point in self.line.get_points():
            lat, long = point.get_degrees()
            lats.append(lat)
            longs.append(long)
        return lats, longs


class MapPoint(MapItem):
    def __init__(
        self, id_: int, geojson: GEOJSONPoint, colour: Colour
    ) -> None:
        if not geojson["type"] == "Point":
            raise TypeError("the provided geojson is not of type Point")
        self.id_ = id_
        self.coordinates = geojson["coordinates"]
        self.image = colour.image
        self.point: OsmGpsMap.MapImage | None = None

    def create_item(self) -> None:
        """No control on the creation of the item for points."""

    def add_to_map(self, map_: OsmGpsMap.Map, glib=True) -> None:
        if not glib or glib_events.get(self.id_):
            long, lat = self.coordinates
            if not self.point:
                self.point = map_.image_add(lat, long, self.image)
            if glib:
                del glib_events[self.id_]

    def remove_from_map(self, map_: OsmGpsMap.Map) -> None:
        map_.image_remove(self.point)

    def set_colour(self, colour: Colour) -> None:
        if self.image != colour.image:
            self.image = colour.image
            if self.point:
                self.point.set_property("pixbuf", self.image)

    def get_lats_longs(self) -> tuple[list[float], list[float]]:
        lat = long = 0.0  # fall back value as we can not create
        if self.point:
            lat, long = self.point.get_point().get_degrees()
        return [lat], [long]


MAP_ADAPTORS = {"Polygon": MapPoly, "LineString": MapLine, "Point": MapPoint}


def map_item_factory(obj: Plant | Location, colour: Colour) -> MapItem | None:
    """Creates an appropriate MapItem for the supplied obj."""
    geojson = getattr(obj, "geojson", None)
    if geojson:
        if map_type := geojson.get("type"):
            if adaptor := MAP_ADAPTORS.get(map_type):
                return adaptor(obj.id, geojson, colour)
    return None


@Gtk.Template(filename=str(Path(__file__).resolve().parent / "garden_map.ui"))
class GardenMap(Gtk.Paned):  # pylint: disable=too-many-instance-attributes
    """Widget to display plants in an OsmGpsMap map"""

    __gtype_name__ = "GardenMapPane"

    map_box = cast(Gtk.Box, Gtk.Template.Child())
    tiles_combo = cast(Gtk.ComboBoxText, Gtk.Template.Child())
    colour_combo = cast(Gtk.ComboBox, Gtk.Template.Child())
    selected_colour_combo = cast(Gtk.ComboBox, Gtk.Template.Child())
    dead_colour_combo = cast(Gtk.ComboBox, Gtk.Template.Child())
    loc_colour_combo = cast(Gtk.ComboBox, Gtk.Template.Child())
    loc_selected_colour_combo = cast(Gtk.ComboBox, Gtk.Template.Child())
    colour_liststore = cast(Gtk.ListStore, Gtk.Template.Child())

    def __init__(self, map_: OsmGpsMap.Map) -> None:
        super().__init__()
        # NOTE max zoom is hard set to 20 (less for some MapSources)
        self.map_ = map_
        self.set_tiles_from_prefs()

        self.map_box.pack_start(self.map_, True, True, 0)

        self.reset_item_colour: Callable[[], None] | None = None

        self.map_plant_colour: Colour
        self.map_plant_selected_colour: Colour
        self.map_plant_dead_colour: Colour
        self.map_location_colour: Colour
        self.map_location_selected_colour: Colour
        self.set_colours_from_prefs()

        self.tile_options = self._get_tiles_option_map()

        for k in self.tile_options:
            self.tiles_combo.append_text(k)

        base_tiles = prefs.prefs.get(MAP_TILES_PREF_KEY, 1)
        self.tiles_combo.set_active(
            list(self.tile_options.values()).index(base_tiles)
        )

        for colour in colours.values():
            self.colour_liststore.append([colour, colour.image])

        renderer = Gtk.CellRendererPixbuf()

        for combo in (
            self.colour_combo,
            self.selected_colour_combo,
            self.dead_colour_combo,
            self.loc_colour_combo,
            self.loc_selected_colour_combo,
        ):
            combo.pack_start(renderer, False)
            combo.add_attribute(renderer, "pixbuf", 1)

        self.colour_combo.set_active(self.map_plant_colour.index)
        self.selected_colour_combo.set_active(
            self.map_plant_selected_colour.index
        )
        self.dead_colour_combo.set_active(self.map_plant_dead_colour.index)
        self.loc_colour_combo.set_active(self.map_location_colour.index)
        self.loc_selected_colour_combo.set_active(
            self.map_location_selected_colour.index
        )

    @Gtk.Template.Callback()
    def on_tiles_combo_changed(self, combo: Gtk.ComboBoxText) -> None:
        text = combo.get_active_text() or ""
        prefs.prefs[MAP_TILES_PREF_KEY] = self.tile_options[text]
        logger.debug("setting base tiles to %s", text)
        self.set_tiles_from_prefs()

    def _set_colour_prefs_from_combo(
        self, combo: Gtk.ComboBox, pref_key: str
    ) -> None:
        tree_iter = combo.get_active_iter()
        if tree_iter is not None:
            model = combo.get_model()
            colour = model[tree_iter][0]
            if prefs.prefs[pref_key] != colour:
                logger.debug("set item colour to %s", colour.name)
                prefs.prefs[pref_key] = colour.name
                self.set_colours_from_prefs()
                if self.reset_item_colour:
                    GLib.idle_add(self.reset_item_colour)

    @Gtk.Template.Callback()
    def on_colour_combo_changed(self, combo: Gtk.ComboBox) -> None:
        self._set_colour_prefs_from_combo(combo, MAP_PLANT_COLOUR_PREF_KEY)

    @Gtk.Template.Callback()
    def on_selected_colour_combo_changed(self, combo: Gtk.ComboBox) -> None:
        self._set_colour_prefs_from_combo(
            combo, MAP_PLANT_SELECTED_COLOUR_PREF_KEY
        )

    @Gtk.Template.Callback()
    def on_dead_colour_combo_changed(self, combo: Gtk.ComboBox) -> None:
        self._set_colour_prefs_from_combo(
            combo, MAP_PLANT_DEAD_COLOUR_PREF_KEY
        )

    @Gtk.Template.Callback()
    def on_loc_colour_combo_changed(self, combo: Gtk.ComboBox) -> None:
        self._set_colour_prefs_from_combo(combo, MAP_LOCATION_COLOUR_PREF_KEY)

    @Gtk.Template.Callback()
    def on_loc_selected_colour_combo_changed(
        self, combo: Gtk.ComboBox
    ) -> None:
        self._set_colour_prefs_from_combo(
            combo, MAP_LOCATION_SELECTED_COLOUR_PREF_KEY
        )

    def set_colours_from_prefs(self) -> None:
        colour = prefs.prefs.get(MAP_PLANT_COLOUR_PREF_KEY)
        if colour not in colours:
            colour = "green"
        self.map_plant_colour = colours[colour]

        colour = prefs.prefs.get(MAP_PLANT_SELECTED_COLOUR_PREF_KEY)
        if colour not in colours:
            colour = "blue"
        self.map_plant_selected_colour = colours[colour]

        colour = prefs.prefs.get(MAP_PLANT_DEAD_COLOUR_PREF_KEY)
        if colour not in colours:
            colour = "violet"
        self.map_plant_dead_colour = colours[colour]

        colour = prefs.prefs.get(MAP_LOCATION_COLOUR_PREF_KEY)
        if colour not in colours:
            colour = "grey"
        self.map_location_colour = colours[colour]

        colour = prefs.prefs.get(MAP_LOCATION_SELECTED_COLOUR_PREF_KEY)
        if colour not in colours:
            colour = "white"
        self.map_location_selected_colour = colours[colour]

    def _get_tiles_option_map(self) -> dict[str, int]:
        options = {}
        i = 0
        while True:
            try:
                if self.map_.source_get_repo_uri(i):
                    options[self.map_.source_get_friendly_name(i)] = i
            except TypeError:
                break
            i += 1
        return options

    def set_tiles_from_prefs(self) -> None:
        base_tiles = prefs.prefs.get(MAP_TILES_PREF_KEY, 1)
        self.map_.set_property("map-source", OsmGpsMap.MapSource_t(base_tiles))


class LocationSearchMap(Gtk.Frame):
    """Simple location search widget.  Used to visually generate a search for
    locations from splash screen
    """

    loc_items: dict[int, MapPoly] = {}

    def __init__(self) -> None:
        super().__init__(label=_("Location Search"))
        proxy = get_map_tile_proxy()
        self.map_ = OsmGpsMap.Map(proxy_uri=proxy)
        self.map_.layer_add(
            OsmGpsMap.MapOsd(
                show_dpad=True,
                show_zoom=True,
            )
        )
        self.map_.connect("button_press_event", self.on_button_press)
        box = Gtk.Box(margin=10)
        self.add(box)
        box.pack_start(self.map_, True, True, 0)
        self.selected: set[tuple[str, int]] = set()

    @classmethod
    def history_callback(cls, table: Table) -> None:
        """Update after history revert_to changes for locations."""
        if table is Location.__table__:
            cls.clear_locations()

    @classmethod
    def clear_locations(cls, *_args) -> None:
        logger.debug("clear_locations")
        cls.loc_items.clear()

    @classmethod
    def update_locations(cls) -> None:
        """Reload loc_items if it is empty.

        NOTE this clears the cache on get_locations_polys before and after to
        ensure seperate objects to GardenMap.
        """
        if cls.loc_items:
            return
        get_locations_polys.clear_cache()
        if location_polys := get_locations_polys():
            map_item: MapPoly
            for map_item in location_polys.values():
                map_item.set_colour(
                    colours[
                        prefs.prefs.get(MAP_LOCATION_COLOUR_PREF_KEY, "grey")
                    ]
                )
                cls.loc_items[map_item.id_] = map_item
        get_locations_polys.clear_cache()

    def update(self) -> None:
        """Clear labels and polygons, repopulate from loc_items and zoom to
        home.
        """
        logger.debug("updating LocationSearchMap")
        self.update_locations()

        base_tiles = prefs.prefs.get(MAP_TILES_PREF_KEY, 1)
        self.map_.set_property("map-source", OsmGpsMap.MapSource_t(base_tiles))
        self.map_.polygon_remove_all()
        self.map_.image_remove_all()

        for map_item in self.loc_items.values():
            map_item.add_to_map(self.map_, glib=False, with_label=True)

        institution = Institution()
        self.map_.set_center_and_zoom(
            float(institution.geo_latitude or 0),
            float(institution.geo_longitude or 0),
            int(institution.geo_zoom or 16),
        )

    def on_button_press(
        self, _map: OsmGpsMap.Map, gevent: Gdk.EventButton
    ) -> None:
        """Allows shift click to select multiples and on final click (no
        modifier key) runs a search for selected.

        If none selected on final click searches for the single location.
        """
        current = _map.convert_screen_to_geographic(
            int(gevent.x), int(gevent.y)
        )
        if (
            gevent.button == 1
            and gevent.get_state() == Gdk.ModifierType.SHIFT_MASK
        ):
            logger.debug(
                "selected now: %s",
                ", ".join(i[0] for i in self.selected),
            )
            if poly := self.get_first_match(*current.get_degrees()):
                self.selected.add((poly.label_txt, poly.id_))
                colour = prefs.prefs.get(MAP_LOCATION_SELECTED_COLOUR_PREF_KEY)
                if colour not in colours:
                    colour = "white"
                poly.set_colour(colours[colour])
        elif gevent.button == 1:
            if poly := self.get_first_match(*current.get_degrees()):
                if self.selected:
                    self.selected.add((poly.label_txt, poly.id_))
                    locs = ", ".join(repr(i[0]) for i in self.selected)
                    search_str = f"loc in {locs}"
                else:
                    self.selected.add((poly.label_txt, poly.id_))
                    search_str = f"loc = {repr(poly.label_txt)}"
                logger.debug("search string: %s", search_str)
                if bauble.gui:
                    bauble.gui.send_command(search_str)
                    if map_presenter:
                        bbox = BoundingBox()
                        for __, id_ in self.selected:
                            bbox.update(*self.loc_items[id_].get_lats_longs())
                        GLib.idle_add(  # type: ignore [call-arg]
                            map_presenter.garden_map.map_.zoom_fit_bbox,
                            *astuple(bbox),
                            priority=GLib.PRIORITY_LOW,
                        )
            self.clear_selected()
        else:
            self.clear_selected()

        self.map_.map_redraw()

    def clear_selected(self) -> None:
        """Set all items back to default colours and remove items from
        self.selected
        """
        colour = prefs.prefs.get(MAP_LOCATION_COLOUR_PREF_KEY)
        if colour not in colours:
            colour = "grey"
        for __, id_ in self.selected:
            self.loc_items[id_].set_colour(colours[colour])
        self.selected.clear()

    def get_first_match(self, lat: float, long: float) -> MapPoly | None:
        """Find the first location which contains the supplied lat, long."""
        for poly in self.loc_items.values():
            if is_point_within_poly(long, lat, poly.coordinates[0]):
                return poly
        return None


event.listen(Location, "after_update", LocationSearchMap.clear_locations)
event.listen(Location, "after_insert", LocationSearchMap.clear_locations)
event.listen(Location, "after_delete", LocationSearchMap.clear_locations)
db.History.history_revert_callbacks.append(LocationSearchMap.history_callback)


class SearchViewMapPresenter:
    # pylint: disable=too-many-instance-attributes
    # pylint: disable=too-many-public-methods
    """Presenter to interface with SearchView"""

    thread_event = threading.Event()
    update_thread_event = threading.Event()

    def __init__(self, garden_map: GardenMap) -> None:
        self.garden_map = garden_map
        self.garden_map.reset_item_colour = self.reset_item_colour
        self.garden_map.connect("destroy", self.on_destroy)
        self.garden_map.map_.connect(
            "button_press_event", self.on_button_press
        )
        self.clear_locations_cache = False
        self.selected: set[tuple[str, int, bool]] = set()
        self.selected_bbox = BoundingBox()
        self.populate_thread: None | threading.Thread = None
        self.update_thread: None | threading.Thread = None
        self.plt_items: dict[int, MapItem] = {}
        self.loc_items: dict[int, MapPoly] = {}
        self.populated: bool = False
        self.redraw_on_update = False
        self.context_menu: Gtk.Menu
        self.search_loc_action: Gio.SimpleAction
        self.search_loc_menu_item: Gio.MenuItem
        self.menu_model = Gio.Menu()
        self.init_context_menu()
        self.zoom_to_home()
        self.search_loc: str = ""
        self.add_to_search = False
        self._resize_timer_id: int | None = None

    @staticmethod
    def is_visible() -> bool:
        """Is the plant map visible.

        May be best used with GLib.idle_add to ensure width and current page
        are accurate.
        """
        if bauble.gui and isinstance(
            view := bauble.gui.get_view(), SearchView
        ):
            child1 = cast(Gtk.Paned, view.pic_pane.get_child1())
            width = (
                view.pic_pane.get_allocation().width
                - child1.get_allocation().width
                - 5
            )
            logger.debug("map is_visble width = %s", width)
            if width > 100:
                return view.pic_pane_notebook.get_current_page() == 0
        return False

    def add_locations(self) -> None:
        if self.clear_locations_cache:
            logger.debug("clearing get_locations_polys cache")
            get_locations_polys.clear_cache()
            self.clear_locations_cache = False
        if location_polys := get_locations_polys():
            for map_item in location_polys.values():
                map_item.set_colour(self.garden_map.map_location_colour)
                map_item.add_to_map(self.garden_map.map_, glib=False)
                self.loc_items[map_item.id_] = map_item

    def on_button_press(
        self, _map: OsmGpsMap.Map, gevent: Gdk.EventButton
    ) -> None:
        if gevent.button == 3:
            self.add_to_search = False
            label = _("Search %s")
            if gevent.get_state() == Gdk.ModifierType.SHIFT_MASK:
                self.add_to_search = True
                label = _("Add %s to search")
            self.search_loc_action.set_enabled(False)
            if self.menu_model.get_n_items() == 4:
                self.menu_model.remove(3)
            current = _map.convert_screen_to_geographic(
                int(gevent.x), int(gevent.y)
            )
            lat, long = current.get_degrees()
            for poly in self.loc_items.values():
                if is_point_within_poly(long, lat, poly.coordinates[0]):
                    self.search_loc_action.set_enabled(True)
                    self.search_loc = poly.label_txt
                    self.search_loc_menu_item.set_label(label % poly.label_txt)
                    self.menu_model.append_item(self.search_loc_menu_item)

            self.context_menu.popup_at_pointer(gevent)
        elif gevent.button == 1:
            current = _map.convert_screen_to_geographic(
                int(gevent.x), int(gevent.y)
            )
            if best := self.get_nearest_plants_id(*current.get_degrees()):
                self.select_plant_by_id(best)

    def get_nearest_plants_id(self, x: float, y: float) -> int | None:
        if self.populate_thread:
            while self.populate_thread.is_alive():
                self.populate_thread.join(0.02)
                Gtk.main_iteration()

        best_id = None
        best_hyp = 0.1
        # narrow the selection
        for id_, plant in self.plt_items.items():
            for lat, long in zip(*plant.get_lats_longs()):
                if (this_hypot := hypot(lat - x, long - y)) < 0.00003:
                    if this_hypot < best_hyp:
                        best_id = id_
                        best_hyp = this_hypot
        return best_id

    @staticmethod
    def select_plant_by_id(id_: int) -> None:
        """Select the plant in the SearchView

        Selects the first instance found, i.e. if there are multiple routes
        (e.g. vernacular name, distribution) to the same plant selects the
        first found.
        """
        logger.debug("looking for plant id_ = %s", id_)
        search_view = get_search_view()

        session = search_view.session
        plant = session.query(Plant).get(id_)
        model = search_view.results_view.get_model()

        if not model or plant is None:
            return

        if utils.tree_model_has(model, plant):
            itr = select_in_search_results(plant)
            path = model.get_path(itr)
            search_view.results_view.scroll_to_cell(path, None, True, 0.5, 0.0)
            logger.debug("plant found early")
            return

        for objs in plant.parent_objects():
            for obj in objs:
                if found := utils.search_tree_model(model, obj):
                    logger.debug("found = %s", obj)
                    itr = found[0]
                    path = model.get_path(itr)
                    # expand
                    search_view.on_test_expand_row(
                        search_view.results_view, itr, path
                    )
                    search_view.results_view.expand_to_path(path)
                    if utils.tree_model_has(model, plant):
                        # select, scroll to centre and return
                        itr = select_in_search_results(plant)
                        path = model.get_path(itr)
                        search_view.results_view.scroll_to_cell(
                            path, None, True, 0.5, 0.0
                        )
                        logger.debug("plant found")
                        return

    def init_context_menu(self) -> None:
        action_name = "garden_map"
        action_group = Gio.SimpleActionGroup()
        # https://github.com/python/mypy/issues/12172
        menu_items = (
            (_("Refresh"), "refresh_map", self.on_refresh),
            (_("Zoom to selected"), "zoom_select", self.on_zoom_to_selected),
            (_("Zoom to home"), "zoom_home", self.zoom_to_home),
        )

        for label, name, handler in menu_items:
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", handler)
            action_group.add_action(action)
            menu_item = Gio.MenuItem.new(label, f"{action_name}.{name}")
            self.menu_model.append_item(menu_item)

        self.search_loc_action = Gio.SimpleAction.new("search_loc", None)
        self.search_loc_action.connect("activate", self.on_search_loc)
        action_group.add_action(self.search_loc_action)
        self.search_loc_menu_item = Gio.MenuItem.new(
            "---", f"{action_name}.search_loc"
        )
        self.menu_model.append_item(self.search_loc_menu_item)
        self.search_loc_action.set_enabled(False)

        self.garden_map.map_.insert_action_group(action_name, action_group)
        self.context_menu = Gtk.Menu.new_from_model(self.menu_model)
        self.context_menu.attach_to_widget(self.garden_map.map_)

    def on_search_loc(self, *_args) -> None:
        if self.add_to_search:
            logger.debug("adding %s to search results", self.search_loc)
            search_view = get_search_view()
            if not search_view or not bauble.gui:
                return

            loc = (
                search_view.session.query(Location)
                .filter(Location.code == self.search_loc)
                .one()
            )
            select_in_search_results(loc)
            self.on_refresh()
            return
        query = f"loc = '{self.search_loc}'"
        logger.debug("query: %s", query)
        if bauble.gui:
            bauble.gui.send_command(query)

    def on_zoom_to_selected(self, *_args) -> None:
        if self.selected:
            max_lat, min_lat, max_long, min_long = astuple(self.selected_bbox)
            self.garden_map.map_.zoom_fit_bbox(
                max_lat, min_lat, max_long, min_long
            )

    def zoom_to_home(self, *_args) -> None:
        institution = Institution()
        self.garden_map.map_.set_center_and_zoom(
            float(institution.geo_latitude or 0),
            float(institution.geo_longitude or 0),
            int(institution.geo_zoom or 16),
        )

    def on_refresh(self, *_args) -> None:
        self.populated = False
        self.populate_map_from_search_view()

    def reset_item_colour(self) -> None:
        if self.populate_thread and self.populate_thread.is_alive():
            # NOTE used in test
            logger.debug("waiting on populate thread")
            self.populate_thread.join()
        for map_item in self.plt_items.values():
            map_item.set_colour(self.garden_map.map_plant_colour)
        for map_item in self.loc_items.values():
            map_item.set_colour(self.garden_map.map_location_colour)
        self.reset_selected_colour()

    def reset_selected_colour(self) -> None:
        for obj_type, id_, _active in self.selected:
            if obj_type == "plt":
                map_item = self.plt_items[id_]
                map_item.set_colour(self.garden_map.map_plant_selected_colour)
            elif obj_type == "loc":
                map_item = self.loc_items[id_]
                map_item.set_colour(
                    self.garden_map.map_location_selected_colour
                )
        self.garden_map.map_.map_redraw()

    def on_destroy(self, *_args) -> None:
        """Cancel running threads on exit"""
        self.thread_event.set()

    def _populate_worker(self, results: Sequence[db.Domain]) -> None:
        if len(results) == 1 and isinstance(results[0], str):
            return

        # avoid cicular import
        from ..report import get_plants_pertinent_to

        # get_plants.. using separate session (none provided) avoids messing up
        # history on deferred geojson column
        # chunk for large searches, MSSQL will fail over ~2600
        for plant in chain.from_iterable(
            get_plants_pertinent_to(chunk)
            for chunk in utils.chunks(results, 1000)
        ):
            if plant.id in self.plt_items:
                # previously added
                continue

            if self.thread_event.is_set():
                glib_events.clear()
                break
            if plant.active:
                colour = self.garden_map.map_plant_colour
            else:
                colour = self.garden_map.map_plant_dead_colour
            map_item = map_item_factory(plant, colour)
            if map_item:
                self.plt_items[plant.id] = map_item
                source = GLib.idle_source_new()
                source.set_callback(map_item.add_to_map, self.garden_map.map_)
                source.attach()
                glib_events[plant.id] = source
        self.populated = True

    def clear_all_threads_and_events(self) -> None:
        logger.debug("populate_map: stopping threads")
        # stop threads and wait
        self.thread_event.set()
        self.update_thread_event.set()
        if self.populate_thread and self.populate_thread.is_alive():
            self.populate_thread.join()
        if self.update_thread and self.update_thread.is_alive():
            self.update_thread.join()
        # clear idle_add events  NOTE log used in test
        logger.debug("populate_map: clearing GLib events")
        for source in glib_events.values():
            source.destroy()
        glib_events.clear()

    def populate_map(self, results: Sequence) -> None:
        """Populate the map with results.

        Stops any map threads running, clears any map GLib events, clears the
        map and if results has contents and the map is visible starts a thread
        to populate it.
        """
        if (
            self.populate_thread
            and self.populate_thread.is_alive()
            or self.update_thread
            and self.update_thread.is_alive()
            or glib_events
        ):
            self.clear_all_threads_and_events()

        self.plt_items.clear()
        self.selected.clear()
        self.garden_map.map_.image_remove_all()
        self.garden_map.map_.track_remove_all()
        self.garden_map.map_.polygon_remove_all()
        self.populated = False
        if results and self.is_visible():
            logger.debug("populating the map")
            self.add_locations()
            self.thread_event.clear()
            self.populate_thread = threading.Thread(
                target=self._populate_worker,
                args=(results,),
            )
            self.populate_thread.start()

    def populate_on_size_allocation(
        self, _pic_pane: Gtk.Paned, _allocation: Gdk.Rectangle
    ) -> None:
        if self._resize_timer_id:
            return
        self._resize_timer_id = GLib.timeout_add(
            300, self._populate_after_timer
        )

    def _populate_after_timer(self) -> None:
        if self.is_visible():
            if self.populated:
                if (
                    not self.populate_thread
                    or not self.populate_thread.is_alive()
                ):
                    logger.debug("populate_after_timer: update selected")
                    selected = get_search_view_selected()
                    if selected:
                        self.update_map(selected)
            else:
                logger.debug("populate_after_timer: populate from search view")
                self.populate_map_from_search_view()
        self._resize_timer_id = None

    def populate_map_from_search_view(
        self, *_args, view: Viewable | None = None
    ) -> None:
        """Populate the map with the current search result.

        Can be used as a signal handler to populate the map when it becomes
        visibile.

        :param view: supply the SearchView instance (for testing)
        """
        logger.debug("populating map from search view results")

        if not view and bauble.gui:
            view = bauble.gui.get_view()

        if isinstance(view, SearchView) and self.is_visible():
            if not self.populated:
                model = view.results_view.get_model()
                objs = []
                if model:
                    objs = [i[0] for i in model]
                self.populate_map(objs)
            selected = view.get_selected_values()
            if selected:
                self.update_map(selected)

    def clear_selected(self) -> None:
        """Set all items back to default colours"""
        logger.debug("clearing prior map selection")
        for obj_type, id_, active in self.selected:
            if obj_type == "plt" and (map_item := self.plt_items.get(id_)):
                if active:
                    colour = self.garden_map.map_plant_colour
                else:
                    colour = self.garden_map.map_plant_dead_colour
                GLib.idle_add(map_item.set_colour, colour)
            elif obj_type == "loc" and (map_item := self.loc_items.get(id_)):
                GLib.idle_add(
                    map_item.set_colour, self.garden_map.map_location_colour
                )

        self.selected.clear()

    def update_selected_bbox(self) -> None:
        lats: list[float] = []
        longs: list[float] = []
        self.selected_bbox.clear()
        for type_, id_, _active in self.selected:
            item_lats = item_longs = None
            if type_ == "plt":
                map_item = self.plt_items.get(id_)
                if map_item:
                    item_lats, item_longs = map_item.get_lats_longs()
            elif type_ == "loc":
                map_item = self.loc_items.get(id_)
                if map_item:
                    item_lats, item_longs = map_item.get_lats_longs()

            if item_lats and item_longs:
                lats.extend(item_lats)
                longs.extend(item_longs)

        logger.debug("updating bbox with lats=%s longs=%s", lats, longs)
        if lats and longs:
            self.selected_bbox.update(lats, longs)

    def _update_worker(self, selected_values: Sequence) -> None:
        if not db.engine:
            return

        if self.populate_thread and self.populate_thread.is_alive():
            logger.debug("joining populate_thread")
            self.populate_thread.join()

        logger.debug("_update_worker, map populated")

        for value in selected_values:
            if self.thread_event.is_set() or self.update_thread_event.is_set():
                return

            # check for geojson directly from the database to avoid messing up
            # history entries on deferred geojson column
            if value.__tablename__ in ("plant", "location"):
                table = value.__table__
                # case required for MSSQL
                stmt = select(
                    case((table.c.geojson.is_(None), 1), else_=0)
                ).where(table.c.id == value.id)
                with db.engine.begin() as connection:
                    if connection.execute(stmt).scalar():
                        continue

            if isinstance(value, Plant):
                self._highlight_plant(value.id, value.active)
            elif isinstance(value, Location):
                self._highlight_location(value.id)

        GLib.idle_add(self.update_selected_bbox)
        GLib.idle_add(self.garden_map.map_.map_redraw)

    def _highlight_plant(self, id_: int, active: bool) -> None:
        map_item = self.plt_items.get(id_)
        if map_item:
            GLib.idle_add(
                map_item.set_colour, self.garden_map.map_plant_selected_colour
            )

            self.selected.add(("plt", id_, active))

    def _highlight_location(self, id_: int) -> None:
        map_item = self.loc_items.get(id_)
        if map_item:
            GLib.idle_add(
                map_item.set_colour,
                self.garden_map.map_location_selected_colour,
            )

            self.selected.add(("loc", id_, True))

    def update_map(self, selected_values: Sequence) -> None:
        if self.redraw_on_update:
            self.redraw_on_update = False
            self.populated = False
            self.populate_map_from_search_view()
            # update is called again from within populate_map_from_search_view
            return
        self.clear_selected()
        if selected_values and self.is_visible():
            if self.update_thread and self.update_thread.is_alive():
                self.update_thread_event.set()
                self.update_thread.join()
            self.update_thread_event.clear()

            self.update_thread = threading.Thread(
                target=self._update_worker,
                args=(selected_values,),
            )
            self.update_thread.start()

    # Listen for changes to the database and react if need be
    def update_after_db_connection_change(self, *_args) -> None:
        """On connection change."""
        get_locations_polys.clear_cache()
        self.clear_all_threads_and_events()

    def update_after_location_change(
        self, _mapper, _connection, target: Location
    ) -> None:
        # clear cache and redraw
        logger.debug("location: %s - has changed", target)
        if target.geojson:
            if item := self.loc_items.get(target.id):
                if target.geojson.get("coordinates") != item.coordinates:
                    logger.debug("setting redraw_on_update True")
                    self.redraw_on_update = True
            else:
                # new location geojson
                logger.debug("setting redraw_on_update True")
                self.redraw_on_update = True
        else:
            if item := self.loc_items.get(target.id):
                item.remove_from_map(self.garden_map.map_)
                del self.loc_items[target.id]
        logger.debug("setting clear_locations_cache True")
        self.clear_locations_cache = True

    def update_after_location_delete(
        self, _mapper, _connection, target: Location
    ) -> None:
        id_ = target.id
        if item := self.loc_items.get(id_):
            item.remove_from_map(self.garden_map.map_)
            del self.loc_items[target.id]
        self.clear_locations_cache = True

    def update_after_plant_change(
        self, _mapper, _connection, target: Plant
    ) -> None:
        id_ = target.id
        # remove if existing
        if item := self.plt_items.get(id_):
            # incase of possible type change we need to replace the map item
            if not target.geojson or item.coordinates != target.geojson.get(
                "coordinates"
            ):
                logger.debug("removing plant map_item %s", id_)
                item.remove_from_map(self.garden_map.map_)
                del self.plt_items[id_]
        # add new to map
        if target.geojson:
            logger.debug("adding plant map_item %s", id_)
            if target.active:
                colour = self.garden_map.map_plant_colour
            else:
                colour = self.garden_map.map_plant_dead_colour
            new = map_item_factory(target, colour)
            if new:
                new.add_to_map(self.garden_map.map_, glib=False)
                self.plt_items[id_] = new

    def update_after_plant_delete(
        self, _mapper, _connection, target: Plant
    ) -> None:
        id_ = target.id
        if item := self.plt_items.get(id_):
            logger.debug("deleting plant map_item %s", id_)
            item.remove_from_map(self.garden_map.map_)
            del self.plt_items[id_]


@timed_cache(size=1000, secs=None)
def get_locations_polys() -> dict[int, MapPoly]:
    """Independently search the database for all locations and generate MapPoly
    objects for any that have geojson polygons.
    """
    # NOTE used in test
    logger.debug("get_locations_polys - generating polygon map items")

    colour = prefs.prefs.get(MAP_LOCATION_COLOUR_PREF_KEY)
    if colour not in colours:
        colour = "grey"
    colour = colours[colour]

    polys = {}
    with db.Session() as session:
        locs = session.query(Location).filter(Location.geojson.isnot(None))
        for loc in locs:
            if loc.geojson["type"] == "Polygon":
                poly = MapPoly(loc.id, loc.geojson, colour, label_txt=loc.code)
                poly.create_item()
                poly.set_props(alpha=0.7, line_width=2)
                polys[loc.id] = poly

    return polys


# global object
map_presenter: SearchViewMapPresenter | None = None


def get_map_tile_proxy() -> str | None:
    """Try find an appropriate proxy for map tiles downloads."""
    proxy = prefs.prefs.get(MAP_TILES_PROXY_PREF_KEY)

    if proxy:
        if not proxy.startswith("http://"):
            proxy = "http://" + proxy
        logger.debug("tile proxy = %s", proxy)
        return proxy

    tiles = prefs.prefs.get(MAP_TILES_PREF_KEY, 1)

    net_sess = get_net_sess()
    if net_sess.pac_file:
        logger.debug("checking pac for proxy")
        url = OsmGpsMap.Map.source_get_repo_uri(int(tiles))
        # make the url something that urllib.parse.urlsplit can deal with
        url = (
            url.replace("#R", "1")
            .replace("#X", "1")
            .replace("#Y", "1")
            .replace("#Q", "1")
            .replace("#Z", "1")
            .replace("#S", "1")
        )
        split = urllib.parse.urlsplit(url)
        logger.debug("Using url: %s, host: %s", url, split.netloc)
        proxy = net_sess.pac_file.find_proxy_for_url(url, split.netloc)
        if proxy == "DIRECT":
            proxy = None
        elif proxy:
            proxy = net_sess.pac_file.parse_proxy(proxy)[0]
    elif val := net_sess.get_proxies():
        proxy = val.get("http")

    if proxy:
        proxy = proxy.strip()
        if not proxy.startswith("http://"):
            proxy = "http://" + proxy

    logger.debug("tile proxy = %s", proxy)

    return proxy


def setup_garden_map() -> None:
    # only set up once...
    logger.debug("setup_garden_map")
    global map_presenter  # pylint: disable=global-statement

    if map_presenter:
        # NOTE used in test
        logger.debug("map_presenter already setup - aborting")
        return

    # NOTE proxy can only be set once per session. If a different proxy is
    # needed after changing the tiles source you will need to possibly reset
    # the proxy in prefs (if not using a pac file to determine) and restart
    proxy = get_map_tile_proxy()

    map_ = OsmGpsMap.Map(proxy_uri=proxy)
    map_.layer_add(
        OsmGpsMap.MapOsd(
            show_dpad=True,
            show_zoom=True,
        )
    )
    logger.debug("map cache dir = %s", map_.get_default_cache_directory())
    garden_map = GardenMap(map_)
    map_presenter = SearchViewMapPresenter(garden_map)
    pic_pane_page = (garden_map, 0, "Map")

    SearchView.pic_pane_notebook_pages.add(pic_pane_page)

    size_allocate_signal = (
        "pic_pane",
        "size-allocate",
        map_presenter.populate_on_size_allocation,
    )
    SearchView.extra_signals.add(size_allocate_signal)

    SearchView.populate_callbacks.add(map_presenter.populate_map)
    SearchView.cursor_changed_callbacks.add(map_presenter.update_map)

    # if already initilised setup now. e.g. connection has changed
    search_view = get_search_view()
    if search_view:
        search_view.add_page_to_pic_pane_notebook(*pic_pane_page)
        search_view.connect_signal(*size_allocate_signal)

    # Listen for changes to the database and react if need be
    event.listen(
        engine.Engine,
        "first_connect",
        map_presenter.update_after_db_connection_change,
    )
    event.listen(
        Location, "after_update", map_presenter.update_after_location_change
    )
    event.listen(
        Location, "after_insert", map_presenter.update_after_location_change
    )
    event.listen(
        Location, "after_delete", map_presenter.update_after_location_delete
    )
    event.listen(
        Plant, "after_update", map_presenter.update_after_plant_change
    )
    event.listen(
        Plant, "after_insert", map_presenter.update_after_plant_change
    )
    event.listen(
        Plant, "after_delete", map_presenter.update_after_plant_delete
    )


def expunge_garden_map() -> None:
    """Mainly for tests and on connection change, remove the map and any
    listeners, etc.
    """
    logger.debug("expunge_garden_map")
    global map_presenter  # pylint: disable=global-statement

    if not map_presenter:
        return

    garden_map = map_presenter.garden_map

    # if already initilised clean up. e.g. connection has changed
    search_view = get_search_view()
    if search_view:
        for page in search_view.pic_pane_notebook_pages:
            if isinstance(page[0], GardenMap):
                search_view.pic_pane_notebook.remove_page(page[1])

    SearchView.pic_pane_notebook_pages.remove((garden_map, 0, "Map"))

    SearchView.extra_signals.remove(
        (
            "pic_pane",
            "size-allocate",
            map_presenter.populate_on_size_allocation,
        )
    )
    SearchView.populate_callbacks.remove(map_presenter.populate_map)
    SearchView.cursor_changed_callbacks.remove(map_presenter.update_map)

    # Listen for changes to the database and react if need be
    event.remove(
        engine.Engine,
        "first_connect",
        map_presenter.update_after_db_connection_change,
    )
    event.remove(
        Location, "after_update", map_presenter.update_after_location_change
    )
    event.remove(
        Location, "after_insert", map_presenter.update_after_location_change
    )
    event.remove(
        Location, "after_delete", map_presenter.update_after_location_delete
    )
    event.remove(
        Plant, "after_update", map_presenter.update_after_plant_change
    )
    event.remove(
        Plant, "after_insert", map_presenter.update_after_plant_change
    )
    event.remove(
        Plant, "after_delete", map_presenter.update_after_plant_delete
    )
    map_presenter = None
