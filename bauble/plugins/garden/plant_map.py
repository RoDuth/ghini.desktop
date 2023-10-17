# Copyright (c) 2023 Ross Demuth <rossdemuth123@gmail.com>
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
A map to displays plants.
"""
import logging

logger = logging.getLogger(__name__)

import threading
import time
from dataclasses import astuple
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from typing import Callable
from typing import Sequence
from typing import cast

import gi

gi.require_version("OsmGpsMap", "1.0")
gi.require_version("GdkPixbuf", "2.0")

from gi.repository import Gdk
from gi.repository import GdkPixbuf
from gi.repository import Gio
from gi.repository import GLib
from gi.repository import Gtk
from gi.repository import OsmGpsMap  # type: ignore
from sqlalchemy import event

import bauble
from bauble import db
from bauble import paths
from bauble import prefs
from bauble.utils import timed_cache
from bauble.view import SearchView

from .location import Location
from .plant import Plant

MAP_TILES_PREF_KEY = "garden.plant_map.base_tiles"
"""
The preferences key for the URI to the source for tiles.
"""

MAP_PLANT_COLOUR_PREF_KEY = "garden.plant_map.plant_colour"
"""
The preferences key for the colour of plants on the map that are not selected.
"""

MAP_PLANT_SELECTED_COLOUR_PREF_KEY = "garden.plant_map.selected_plant_colour"
"""
The preferences key for the colour of plants on the map that are selected.
"""

MAP_LOCATION_COLOUR_PREF_KEY = "garden.plant_map.location_colour"
"""
The preferences key for the colour of locations on the map that are not
selected.
"""

MAP_LOCATION_SELECTED_COLOUR_PREF_KEY = (
    "garden.plant_map.selected_location_colour"
)
"""
The preferences key for the colour of locations on the map that are selected.
"""


@dataclass
class Colour:
    name: str
    image: GdkPixbuf.Pixbuf | None
    rgba: Gdk.RGBA


@dataclass
class BoundingBox:
    max_lat: float | None
    min_lat: float | None
    max_long: float | None
    min_long: float | None

    def update(self, lats: list[float], longs: list[float]) -> None:
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
        self.max_lat = None
        self.min_lat = None
        self.max_long = None
        self.min_long = None


colours: dict[str, Colour] = {
    "green": Colour(
        "green",
        GdkPixbuf.Pixbuf.new_from_file_at_size(
            str(Path(paths.lib_dir(), "images", "green_point.png")), 6, 6
        ),
        Gdk.RGBA(0.0, 0.56, 0.0, 0.0),
    ),
    "yellow": Colour(
        "yellow",
        GdkPixbuf.Pixbuf.new_from_file_at_size(
            str(Path(paths.lib_dir(), "images", "yellow_point.png")), 6, 6
        ),
        Gdk.RGBA(1.0, 1.0, 0.0, 0.0),
    ),
    "blue": Colour(
        "blue",
        GdkPixbuf.Pixbuf.new_from_file_at_size(
            str(Path(paths.lib_dir(), "images", "blue_point.png")), 6, 6
        ),
        Gdk.RGBA(0.0, 0.0, 1.0, 0.0),
    ),
    "red": Colour(
        "red",
        GdkPixbuf.Pixbuf.new_from_file_at_size(
            str(Path(paths.lib_dir(), "images", "red_point.png")), 6, 6
        ),
        Gdk.RGBA(1.0, 0.0, 0.0, 0.0),
    ),
    "black": Colour(
        "black",
        GdkPixbuf.Pixbuf.new_from_file_at_size(
            str(Path(paths.lib_dir(), "images", "black_point.png")), 6, 6
        ),
        Gdk.RGBA(0.0, 0.0, 0.0, 0.0),
    ),
    "grey": Colour(
        "grey",
        GdkPixbuf.Pixbuf.new_from_file_at_size(
            str(Path(paths.lib_dir(), "images", "grey_point.png")), 6, 6
        ),
        Gdk.RGBA(0.5, 0.5, 0.5, 0.0),
    ),
    "white": Colour(
        "white",
        GdkPixbuf.Pixbuf.new_from_file_at_size(
            str(Path(paths.lib_dir(), "images", "white_point.png")), 6, 6
        ),
        Gdk.RGBA(1.0, 1.0, 1.0, 0.0),
    ),
}


@Gtk.Template(filename=str(Path(__file__).resolve().parent / "plant_map.ui"))
class PlantMap(Gtk.Paned):  # pylint: disable=too-many-instance-attributes
    """Widget to display plants in an OsmGpsMap map"""

    __gtype_name__ = "PlantMapPane"

    map_box = cast(Gtk.Box, Gtk.Template.Child())
    tiles_combo = cast(Gtk.ComboBoxText, Gtk.Template.Child())
    colour_combo = cast(Gtk.ComboBox, Gtk.Template.Child())
    selected_colour_combo = cast(Gtk.ComboBox, Gtk.Template.Child())
    loc_colour_combo = cast(Gtk.ComboBox, Gtk.Template.Child())
    loc_selected_colour_combo = cast(Gtk.ComboBox, Gtk.Template.Child())
    colour_liststore = cast(Gtk.ListStore, Gtk.Template.Child())

    def __init__(self, is_visible: Callable[[], bool]) -> None:
        super().__init__()
        # NOTE max zoom is hard set to 20 (less for some MapSources)
        self.map: OsmGpsMap.Map = OsmGpsMap.Map()
        self.map.layer_add(
            OsmGpsMap.MapOsd(
                show_dpad=True,
                show_zoom=True,
            )
        )
        self.set_tiles_from_prefs()

        self.zoom_to_home()
        self.map.connect("button_press_event", self.on_button_press)
        self.map_box.pack_start(self.map, True, True, 0)

        self.map_adders = {
            "Point": self.map_add_point,
            "LineString": self.map_add_line,
            "Polygon": self.map_add_poly,
        }

        self.map_items: dict[int, Any] = {}
        self.selected: set[tuple[str, int, str]] = set()
        self.selected_bbox = BoundingBox(None, None, None, None)
        self.populate_thread: None | threading.Thread = None
        self.update_thread: None | threading.Thread = None
        self.thread_event = threading.Event()
        self.glib_events: dict[int, int] = {}
        # see:https://github.com/python/mypy/issues/708
        self.is_visible = is_visible  # type: ignore
        self.populated: bool = False
        self.connect("destroy", self.on_destroy)

        self.map_plant_colour: Colour
        self.map_plant_selected_colour: Colour
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
            self.loc_colour_combo,
            self.loc_selected_colour_combo,
        ):
            combo.pack_start(renderer, False)
            combo.add_attribute(renderer, "pixbuf", 1)

        self.colour_combo.set_active(
            list(colours.keys()).index(self.map_plant_colour.name)
        )
        self.selected_colour_combo.set_active(
            list(colours.keys()).index(self.map_plant_selected_colour.name)
        )
        self.loc_colour_combo.set_active(
            list(colours.keys()).index(self.map_location_colour.name)
        )
        self.loc_selected_colour_combo.set_active(
            list(colours.keys()).index(self.map_location_selected_colour.name)
        )

        self.context_menu: Gtk.Menu
        self.init_context_menu()

    def add_locations(self) -> None:
        polygons = get_locations_polys()
        if polygons:
            for poly in polygons.values():
                poly.get_track().set_color(self.map_location_colour.rgba)
                self.map.polygon_add(poly)

    def on_button_press(self, _map: OsmGpsMap.Map, gevent: Gdk.Event) -> None:
        if gevent.button == 3:
            self.context_menu.popup_at_pointer(gevent)

    def init_context_menu(self):
        menu = Gio.Menu()
        action_name = "plant_map"
        action_group = Gio.SimpleActionGroup()
        menu_items = (
            (_("Zoom to selected"), "zoom_select", self.on_zoom_to_selected),
            (_("Zoom to home"), "zoom_home", self.zoom_to_home),
        )

        for label, name, handler in menu_items:
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", handler)
            action_group.add_action(action)
            menu_item = Gio.MenuItem.new(label, f"{action_name}.{name}")
            menu.append_item(menu_item)

        self.map.insert_action_group(action_name, action_group)
        self.context_menu = Gtk.Menu.new_from_model(menu)
        self.context_menu.attach_to_widget(self.map)

    def on_zoom_to_selected(self, *_args) -> None:
        if self.selected:
            max_lat, min_lat, max_long, min_long = astuple(self.selected_bbox)
            self.map.zoom_fit_bbox(max_lat, min_lat, max_long, min_long)

    def zoom_to_home(self, *_args) -> None:
        from .institution import Institution

        institution = Institution()
        self.map.set_center_and_zoom(
            float(institution.geo_latitude or 0),
            float(institution.geo_longitude or 0),
            int(institution.geo_zoom or 16),
        )

    @Gtk.Template.Callback()
    def on_tiles_combo_changed(self, combo: Gtk.ComboBoxText) -> None:
        text = combo.get_active_text()
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
            if self.map_plant_colour != colour:
                logger.debug("set item colour to %s", colour.name)
                prefs.prefs[pref_key] = colour.name
                self.set_colours_from_prefs()
                self.reset_item_colour()

    @Gtk.Template.Callback()
    def on_colour_combo_changed(self, combo: Gtk.ComboBox) -> None:
        self._set_colour_prefs_from_combo(combo, MAP_PLANT_COLOUR_PREF_KEY)

    @Gtk.Template.Callback()
    def on_selected_colour_combo_changed(self, combo: Gtk.ComboBox) -> None:
        self._set_colour_prefs_from_combo(
            combo, MAP_PLANT_SELECTED_COLOUR_PREF_KEY
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
            colour = "yellow"
        self.map_plant_selected_colour = colours[colour]

        colour = prefs.prefs.get(MAP_LOCATION_COLOUR_PREF_KEY)
        if colour not in colours:
            colour = "grey"
        self.map_location_colour = colours[colour]

        colour = prefs.prefs.get(MAP_LOCATION_SELECTED_COLOUR_PREF_KEY)
        if colour not in colours:
            colour = "white"
        self.map_location_selected_colour = colours[colour]

    def reset_item_colour(self) -> None:
        for item in self.map_items.values():
            if isinstance(item, OsmGpsMap.MapImage):
                item.props.pixbuf = self.map_plant_colour.image
            elif isinstance(item, OsmGpsMap.MapTrack):
                item.set_color(self.map_plant_colour.rgba)
            elif isinstance(item, OsmGpsMap.MapPolygon):
                item.get_track().set_color(self.map_plant_colour.rgba)
        for item in get_locations_polys().values():
            item.get_track().set_color(self.map_location_colour.rgba)
        self.reset_selected_colour()

    def reset_selected_colour(self) -> None:
        for obj_type, id_, map_type in self.selected:
            if obj_type == "plt":
                map_item = self.map_items[id_]
                if map_type == "Point":
                    icon = self.map_plant_selected_colour.image
                    map_item.props.pixbuf = icon
                if map_type == "LineString":
                    map_item.set_color(self.map_plant_selected_colour.rgba)
                if map_type == "Polygon":
                    map_item.get_track().set_color(
                        self.map_plant_selected_colour.rgba
                    )
            elif obj_type == "loc":
                map_item = get_locations_polys()[id_]
                map_item.get_track().set_color(
                    self.map_location_selected_colour.rgba
                )

    def _get_tiles_option_map(self) -> dict[str, int]:
        options = {}
        i = 0
        while True:
            try:
                if self.map.source_get_repo_uri(i):
                    options[self.map.source_get_friendly_name(i)] = i
            except TypeError:
                break
            i += 1
        return options

    def set_tiles_from_prefs(self):
        base_tiles = prefs.prefs.get(MAP_TILES_PREF_KEY, 1)
        self.map.set_property("map-source", OsmGpsMap.MapSource_t(base_tiles))

    def on_destroy(self, *_args) -> None:
        """Cancel running threads on exit"""
        self.thread_event.set()

    def map_add_point(self, coordinates: list[float], id_: int) -> None:
        if self.glib_events.get(id_):
            long, lat = coordinates
            icon = self.map_plant_colour.image
            self.map_items[id_] = self.map.image_add(lat, long, icon)
            del self.glib_events[id_]

    def map_add_line(self, coordinates: list[list[float]], id_: int) -> None:
        if self.glib_events.get(id_):
            track = OsmGpsMap.MapTrack()
            track.set_color(self.map_plant_colour.rgba)
            track.props.alpha = 1.0
            for point in coordinates:
                point.reverse()
                track.add_point(OsmGpsMap.MapPoint.new_degrees(*point))
            self.map_items[id_] = track
            self.map.track_add(track)
            del self.glib_events[id_]

    def map_add_poly(
        self, coordinates: list[list[list[float]]], id_: int
    ) -> None:
        if self.glib_events.get(id_):
            poly = OsmGpsMap.MapPolygon.new()
            track = poly.get_track()

            coords = coordinates[0]
            track.set_color(self.map_plant_colour.rgba)
            track.props.alpha = 1.0
            track.props.line_width = 2
            for point in coords:
                point.reverse()
                track.add_point(OsmGpsMap.MapPoint.new_degrees(*point))
            self.map_items[id_] = poly
            self.map.polygon_add(poly)
            del self.glib_events[id_]

    def _populate_worker(self, results: Sequence) -> None:
        if len(results) == 1 and isinstance(results[0], str):
            return

        from ..report import get_plants_pertinent_to

        for plant in get_plants_pertinent_to(results):
            if self.thread_event.is_set():
                break
            geojson = getattr(plant, "geojson", None)
            if geojson:
                adder = self.map_adders.get(geojson["type"], lambda *_: None)
                # see: https://github.com/python/mypy/issues/10740
                self.glib_events[plant.id] = GLib.idle_add(
                    adder, geojson["coordinates"], plant.id  # type: ignore
                )

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
        ):
            logger.debug("populate_map: stopping threads")
            # stop threads and wait
            self.thread_event.set()
            if self.populate_thread:
                self.populate_thread.join()
            if self.update_thread:
                self.update_thread.join()
            # clear idle_add events  NOTE log used in test
            logger.debug("populate_map: clearing GLib events")
            for id_ in self.glib_events.values():
                GLib.source_remove(id_)

        self.glib_events.clear()
        self.map.image_remove_all()
        self.map.track_remove_all()
        self.map.polygon_remove_all()
        self.add_locations()
        self.map_items = {}
        self.selected.clear()
        self.populated = False
        if results and self.is_visible():
            logger.debug("populating the map")
            self.thread_event.clear()
            self.populate_thread = threading.Thread(
                target=self._populate_worker,
                args=(results,),
            )
            self.populate_thread.start()
            self.populated = True

    def populate_map_from_search_view(
        self, *_args, view: SearchView | None = None
    ) -> None:
        """Populate the map with the current search result.

        Can be used as a signal handler to populate the map when it becomes
        visibile.
        :param view: supply the SearchView instance (for testing)
        """
        # idle_add to ensure is_visible returns correctly
        GLib.idle_add(self._populate_map_from_search_view, view)

    def _populate_map_from_search_view(
        self, view: SearchView | None = None
    ) -> None:
        logger.debug("populating map from search view results")
        if not view and bauble.gui:
            view = bauble.gui.get_view()
        if isinstance(view, SearchView) and (
            self.is_visible() and not self.populated
        ):
            model = view.results_view.get_model()
            objs = []
            if model:
                # see: https://github.com/python/mypy/issues/2220
                objs = [i[0] for i in model]  # type: ignore
            self.populate_map(objs)
            self.update_map(view.get_selected_values())

    def clear_selected(self) -> None:
        """Set all items back to default colours"""
        logger.debug("clearing prior map selection")
        for obj_type, id_, type_ in self.selected:
            if obj_type == "plt":
                map_item = self.map_items[id_]
                if type_ == "Point":
                    icon = self.map_plant_colour.image
                    map_item.props.pixbuf = icon
                if type_ == "LineString":
                    map_item.set_color(self.map_plant_colour.rgba)
                if type_ == "Polygon":
                    map_item.get_track().set_color(self.map_plant_colour.rgba)
            elif obj_type == "loc":
                map_item = get_locations_polys()[id_]
                map_item.get_track().set_color(self.map_location_colour.rgba)

        self.selected.clear()

    def _wait_for_map_to_populate(self) -> None:
        # wait for map to populate
        if self.populate_thread and self.populate_thread.is_alive():
            logger.debug("joining populate_thread")
            self.populate_thread.join()

        while True:
            if self.thread_event.is_set():
                break
            if self.glib_events:
                time.sleep(0.2)
            else:
                break

    def _update_worker(self, selected_values: Sequence) -> None:
        self._wait_for_map_to_populate()
        logger.debug("_update_worker, map populated")
        lats: list[float] = []
        longs: list[float] = []
        self.selected_bbox.clear()

        for value in selected_values:
            if self.thread_event.is_set():
                return

            geojson = getattr(value, "geojson", None)

            if not geojson:
                continue

            if isinstance(value, Plant):
                self._highlight_plant(value.id, geojson, lats, longs)
            elif isinstance(value, Location):
                self._highlight_location(value.id, geojson, lats, longs)

        if lats and longs:
            self.selected_bbox.update(lats, longs)

        GLib.idle_add(self.map.map_redraw)

    def _highlight_plant(self, id_, geojson, lats, longs) -> None:
        map_item = self.map_items.get(id_)
        if map_item:
            if geojson["type"] == "Point":
                icon = self.map_plant_selected_colour.image
                map_item.props.pixbuf = icon
                lat, long = map_item.get_point().get_degrees()
                lats.append(lat)
                longs.append(long)
            elif geojson["type"] == "LineString":
                map_item.set_color(self.map_plant_selected_colour.rgba)
                for point in map_item.get_points():
                    lat, long = point.get_degrees()
                    lats.append(lat)
                    longs.append(long)
            elif geojson["type"] == "Polygon":
                map_item.get_track().set_color(
                    self.map_plant_selected_colour.rgba
                )
                for point in map_item.get_track().get_points():
                    lat, long = point.get_degrees()
                    lats.append(lat)
                    longs.append(long)
            else:
                return

            self.selected.add(("plt", id_, geojson["type"]))

    def _highlight_location(self, id_, geojson, lats, longs) -> None:
        map_item = get_locations_polys()[id_]
        if map_item:
            if geojson["type"] == "Polygon":
                map_item.get_track().set_color(
                    self.map_location_selected_colour.rgba
                )
                for point in map_item.get_track().get_points():
                    lat, long = point.get_degrees()
                    lats.append(lat)
                    longs.append(long)
                self.selected.add(("loc", id_, "Polygon"))

    def update_map(self, selected_values: Sequence) -> None:
        self.clear_selected()
        if selected_values and self.is_visible():
            self.update_thread = threading.Thread(
                target=self._update_worker,
                args=(selected_values,),
            )
            self.update_thread.start()


@timed_cache(size=1000, secs=None)
def get_locations_polys() -> dict[int, OsmGpsMap.MapPolygon]:
    if not db.Session:
        return {}

    colour = prefs.prefs.get(MAP_LOCATION_COLOUR_PREF_KEY)
    if colour not in colours:
        colour = "grey"
    colour = colours[colour]

    session = db.Session()
    polys = {}

    for loc in session.query(Location).filter(Location.geojson.isnot(None)):
        if loc.geojson["type"] == "Polygon":
            poly = OsmGpsMap.MapPolygon.new()
            track = poly.get_track()
            coords = loc.geojson["coordinates"][0]
            track.set_color(colour.rgba)
            track.props.alpha = 0.7
            track.props.line_width = 2
            for point in coords:
                point.reverse()
                track.add_point(OsmGpsMap.MapPoint.new_degrees(*point))
            polys[loc.id] = poly

    session.close()

    if polys:
        return polys
    return {}


@event.listens_for(Location, "after_update")
@event.listens_for(Location, "after_insert")
@event.listens_for(Location, "after_delete")
def loc_after_event(*_args):
    get_locations_polys.clear_cache()
