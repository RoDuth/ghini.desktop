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
import os
import threading
import time
from typing import Any
from typing import Callable
from typing import Sequence

logger = logging.getLogger(__name__)

import gi

gi.require_version("OsmGpsMap", "1.0")
gi.require_version("GdkPixbuf", "2.0")

from gi.repository import Gdk
from gi.repository import GdkPixbuf
from gi.repository import GLib
from gi.repository import Gtk
from gi.repository import OsmGpsMap  # type: ignore

import bauble
from bauble import paths
from bauble import prefs
from bauble.view import SearchView

from .plant import Plant

MAP_TILES_PREF_KEY = "garden.plant_map.base_tiles"
"""
The preferences key for the URI to the source for tiles.
"""


class PlantMap(Gtk.Paned):  # pylint: disable=too-many-instance-attributes
    """Widget to display plants in an OsmGpsMap map"""

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

        from .institution import Institution

        institution = Institution()
        self.map.set_center_and_zoom(
            float(institution.geo_latitude or 0),
            float(institution.geo_longitude or 0),
            int(institution.geo_zoom or 16),
        )
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        vbox.pack_start(self.map, True, True, 0)
        self.add(vbox)
        self.map_adders = {
            "Point": self.map_add_point,
            "LineString": self.map_add_line,
            "Polygon": self.map_add_poly,
        }
        self.map_items: dict[int, Any] = {}
        self.prior_selection: set[tuple[int, str]] = set()
        self.populate_thread: None | threading.Thread = None
        self.update_thread: None | threading.Thread = None
        self.thread_event = threading.Event()
        self.glib_events: dict[int, int] = {}
        # see:https://github.com/python/mypy/issues/708
        self.is_visible = is_visible  # type: ignore
        self.populated: bool = False
        self.connect("destroy", self.on_destroy)

        self.map_point_image = os.path.join(
            paths.lib_dir(), "images", "green_point.png"
        )
        self.map_point_selected_image = os.path.join(
            paths.lib_dir(), "images", "yellow_point.png"
        )
        self.map_item_colour = Gdk.RGBA(0.0, 0.56, 0.0, 0.0)
        self.map_item_selected_colour = Gdk.RGBA(1.0, 1.0, 0.0, 0.0)
        self.tile_options = self._get_tiles_option_map()

        settings = self._get_settings_widgets()
        vbox.pack_start(settings, False, True, 0)

    def _get_settings_widgets(self) -> Gtk.Widget:
        box = Gtk.Box()
        expander = Gtk.Expander(label="<b>Map Settings</b>", use_markup=True)
        expander.add(box)
        tiles_combo = Gtk.ComboBoxText()
        for k in self.tile_options:
            tiles_combo.append_text(k)
        base_tiles = prefs.prefs.get(MAP_TILES_PREF_KEY, 1)
        tiles_combo.set_active(
            list(self.tile_options.values()).index(base_tiles)
        )
        tiles_combo.connect("changed", self.on_tiles_combo_changed)
        box.pack_start(tiles_combo, False, True, 5)
        return expander

    def on_tiles_combo_changed(self, combo) -> None:
        text = combo.get_active_text()
        prefs.prefs[MAP_TILES_PREF_KEY] = self.tile_options[text]
        logger.debug("setting base tiles to %s", text)
        self.set_tiles_from_prefs()

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
            icon = GdkPixbuf.Pixbuf.new_from_file_at_size(
                self.map_point_image, 6, 6
            )
            self.map_items[id_] = self.map.image_add(lat, long, icon)
            del self.glib_events[id_]

    def map_add_line(self, coordinates: list[list[float]], id_: int) -> None:
        if self.glib_events.get(id_):
            track = OsmGpsMap.MapTrack()
            track.set_color(self.map_item_colour)
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
            track.set_color(self.map_item_colour)
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
        self.map_items = {}
        self.prior_selection.clear()
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

    def clear_prior_selection(self) -> None:
        """Set all items back to default colours"""
        logger.debug("clearing prior map selection")
        for id_, type_ in self.prior_selection:
            map_item = self.map_items[id_]
            if type_ == "Point":
                icon = GdkPixbuf.Pixbuf.new_from_file_at_size(
                    self.map_point_image, 6, 6
                )
                map_item.props.pixbuf = icon
            if type_ == "LineString":
                map_item.set_color(self.map_item_colour)
            if type_ == "Polygon":
                map_item.get_track().set_color(self.map_item_colour)

        self.prior_selection.clear()

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

        for value in selected_values:
            if self.thread_event.is_set():
                return

            if not isinstance(value, Plant):
                continue

            geojson = getattr(value, "geojson", None)

            if not geojson:
                continue

            map_item = self.map_items.get(value.id)
            if map_item:
                if geojson["type"] == "Point":
                    icon = GdkPixbuf.Pixbuf.new_from_file_at_size(
                        self.map_point_selected_image, 8, 8
                    )
                    map_item.props.pixbuf = icon
                elif geojson["type"] == "LineString":
                    map_item.set_color(self.map_item_selected_colour)
                if geojson["type"] == "Polygon":
                    map_item.get_track().set_color(
                        self.map_item_selected_colour
                    )

                self.prior_selection.add((value.id, geojson["type"]))

        GLib.idle_add(self.map.map_redraw)

    def update_map(self, selected_values: Sequence) -> None:
        self.clear_prior_selection()
        if selected_values and self.is_visible():
            self.update_thread = threading.Thread(
                target=self._update_worker,
                args=(selected_values,),
            )
            self.update_thread.start()
