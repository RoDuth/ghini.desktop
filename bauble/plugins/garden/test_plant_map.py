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
Test plant map
"""

import threading
from time import sleep
from unittest import mock

from gi.repository.OsmGpsMap import MapImage  # type: ignore
from gi.repository.OsmGpsMap import MapPolygon
from gi.repository.OsmGpsMap import MapTrack

from bauble import prefs
from bauble.test import BaubleTestCase
from bauble.test import get_setUp_data_funcs
from bauble.test import update_gui
from bauble.view import SearchView

from . import Location
from . import Plant
from .plant_map import MAP_TILES_PREF_KEY
from .plant_map import PlantMap

point = {
    "type": "Point",
    "coordinates": [-27.477676044133204, 152.97899035780537],
}

line = {
    "type": "LineString",
    "coordinates": [
        [-27.477415350999937, 152.97756344999996],
        [-27.477309303999977, 152.97780253700006],
    ],
}

poly = {
    "type": "Polygon",
    "coordinates": [
        [
            [-27.477559016773604, 152.97445813351644],
            [-27.477874827537065, 152.97463243273273],
            [-27.477748345857805, 152.9744273500483],
            [-27.477559016773604, 152.97445813351644],
        ]
    ],
}


class TestPlantMap(BaubleTestCase):
    def test_empty_plant_map(self):
        plant_map = PlantMap(is_visible=lambda *_: True)
        self.assertEqual(plant_map.map.get_property("map-source"), 1)

    def test_map_adders_populate(self):
        plant_map = PlantMap(is_visible=lambda *_: True)
        self.assertIn(plant_map.map_add_line, plant_map.map_adders.values())
        self.assertIn(plant_map.map_add_point, plant_map.map_adders.values())
        self.assertIn(plant_map.map_add_poly, plant_map.map_adders.values())

    def test_map_add_point_adds(self):
        plant_map = PlantMap(is_visible=lambda *_: True)
        plant_map.glib_events[1] = True
        plant_map.map_add_point(point.get("coordinates"), 1)
        self.assertIsInstance(plant_map.map_items[1], MapImage)
        self.assertEqual(plant_map.glib_events, {})

    def test_map_add_line_adds(self):
        plant_map = PlantMap(is_visible=lambda *_: True)
        plant_map.glib_events[1] = True
        plant_map.map_add_line(line.get("coordinates"), 1)
        self.assertIsInstance(plant_map.map_items[1], MapTrack)
        self.assertEqual(plant_map.glib_events, {})

    def test_map_add_poly_adds(self):
        plant_map = PlantMap(is_visible=lambda *_: True)
        plant_map.glib_events[1] = True
        plant_map.map_add_poly(poly.get("coordinates"), 1)
        self.assertIsInstance(plant_map.map_items[1], MapPolygon)
        self.assertEqual(plant_map.glib_events, {})

    def test_map_add_point_doesnt_adds_if_glib_events_cleared(self):
        plant_map = PlantMap(is_visible=lambda *_: True)
        plant_map.map_add_point(point.get("coordinates"), 1)
        self.assertEqual(plant_map.map_items, {})
        self.assertEqual(plant_map.glib_events, {})

    def test_map_add_line_doesnt_adds_if_glib_events_cleared(self):
        plant_map = PlantMap(is_visible=lambda *_: True)
        plant_map.map_add_line(line.get("coordinates"), 1)
        self.assertEqual(plant_map.map_items, {})
        self.assertEqual(plant_map.glib_events, {})

    def test_map_add_poly_doesnt_adds_if_glib_events_cleared(self):
        plant_map = PlantMap(is_visible=lambda *_: True)
        plant_map.map_add_poly(poly.get("coordinates"), 1)
        self.assertEqual(plant_map.map_items, {})
        self.assertEqual(plant_map.glib_events, {})

    def test_on_destroy(self):
        plant_map = PlantMap(is_visible=lambda *_: True)
        thread_event = plant_map.thread_event
        self.assertFalse(thread_event.is_set())
        plant_map.destroy()
        self.assertTrue(thread_event.is_set())

    def test_populate_map_empty_results(self):
        plant_map = PlantMap(is_visible=lambda *_: True)
        results = []
        plant_map.populate_map(results)
        update_gui()
        self.assertEqual(plant_map.map_items, {})
        self.assertEqual(plant_map.selected, set())
        self.assertIsNone(plant_map.populate_thread)

    def test_populate_map_not_visible(self):
        for func in get_setUp_data_funcs():
            func()
        results = self.session.query(Location).all()
        plant_map = PlantMap(is_visible=lambda *_: False)
        plant_map.populate_map(results)
        update_gui()
        self.assertEqual(plant_map.map_items, {})
        self.assertEqual(plant_map.selected, set())
        self.assertIsNone(plant_map.populate_thread)

    def test_populate_map_no_geojson(self):
        for func in get_setUp_data_funcs():
            func()
        results = self.session.query(Location).all()
        plant_map = PlantMap(is_visible=lambda *_: True)
        plant_map.populate_map(results)
        self.assertIsNotNone(plant_map.populate_thread)
        plant_map.populate_thread.join()
        update_gui()
        self.assertEqual(plant_map.map_items, {})
        self.assertEqual(plant_map.selected, set())
        plant_map.destroy()

    def test_populate_map_stops_threads(self):
        for func in get_setUp_data_funcs():
            func()
        plant_map = PlantMap(is_visible=lambda *_: True)

        def dont_stop():
            while True:
                if plant_map.thread_event.is_set():
                    break
                sleep(0.2)

        plant_map.populate_thread = threading.Thread(target=dont_stop)
        plant_map.populate_thread.start()
        results = self.session.query(Location).all()
        with self.assertLogs(level="DEBUG") as logs:
            plant_map.populate_map(results)
            plant_map.populate_thread.join()
            update_gui()
        self.assertTrue(any("clearing GLib events" in i for i in logs.output))
        plant_map.destroy()

    def test_populate_map_w_geojson(self):
        # Also tests adders
        for func in get_setUp_data_funcs():
            func()
        plt1 = self.session.query(Plant).get(1)
        plt2 = self.session.query(Plant).get(2)
        plt3 = self.session.query(Plant).get(3)
        plt1.geojson = point
        plt2.geojson = line
        plt3.geojson = poly
        self.session.commit()
        results = self.session.query(Plant).all()
        plant_map = PlantMap(is_visible=lambda *_: True)
        plant_map.populate_map(results)
        self.assertIsNotNone(plant_map.populate_thread)
        plant_map.populate_thread.join()
        update_gui()
        self.assertEqual(len(plant_map.map_items), 3)
        self.assertIsInstance(plant_map.map_items[1], MapImage)
        self.assertIsInstance(plant_map.map_items[2], MapTrack)
        self.assertIsInstance(plant_map.map_items[3], MapPolygon)
        self.assertEqual(plant_map.selected, set())
        self.assertEqual(plant_map.glib_events, {})
        plant_map.destroy()

    def test_update_map_selects(self):
        for func in get_setUp_data_funcs():
            func()
        plt1 = self.session.query(Plant).get(1)
        plt2 = self.session.query(Plant).get(2)
        plt3 = self.session.query(Plant).get(3)
        plt1.geojson = point
        plt2.geojson = line
        plt3.geojson = poly
        self.session.commit()
        results = self.session.query(Plant).all()
        plant_map = PlantMap(is_visible=lambda *_: True)
        plant_map.populate_map(results)
        plant_map.populate_thread.join()
        update_gui()
        plant_map.update_map([plt1, plt3])
        plant_map.update_thread.join()
        update_gui()
        self.assertEqual(
            plant_map.selected, {("plt", 1, "Point"), ("plt", 3, "Polygon")}
        )
        # check color changed
        self.assertEqual(
            plant_map.map_items[3].get_track().get_color(),
            plant_map.map_plant_selected_colour.rbga,
        )
        # change selection and check it updates (tests clear_selected also)
        plant_map.update_map([plt2])
        plant_map.update_thread.join()
        update_gui()
        self.assertEqual(plant_map.selected, {("plt", 2, "LineString")})
        self.assertEqual(
            plant_map.map_items[3].get_track().get_color(),
            plant_map.map_plant_colour.rbga,
        )

    def test_clear_selected(self):
        for func in get_setUp_data_funcs():
            func()
        plt1 = self.session.query(Plant).get(1)
        plt2 = self.session.query(Plant).get(2)
        plt3 = self.session.query(Plant).get(3)
        plt1.geojson = point
        plt2.geojson = line
        plt3.geojson = poly
        self.session.commit()
        results = self.session.query(Plant).all()
        plant_map = PlantMap(is_visible=lambda *_: True)
        plant_map.populate_map(results)
        plant_map.populate_thread.join()
        update_gui()
        plant_map.update_map([plt1, plt3])
        plant_map.update_thread.join()
        update_gui()
        self.assertEqual(
            plant_map.selected, {("plt", 1, "Point"), ("plt", 3, "Polygon")}
        )
        plant_map.clear_selected()
        self.assertEqual(plant_map.selected, set())
        self.assertEqual(
            plant_map.map_items[3].get_track().get_color(),
            plant_map.map_plant_colour.rbga,
        )

    def test_populate_map_from_search_view(self):
        for func in get_setUp_data_funcs():
            func()
        plt1 = self.session.query(Plant).get(1)
        plt2 = self.session.query(Plant).get(2)
        plt3 = self.session.query(Plant).get(3)
        plt1.geojson = point
        plt2.geojson = line
        plt3.geojson = poly
        self.session.commit()
        plant_map = PlantMap(is_visible=lambda *_: True)
        search_view = SearchView()
        search_view.search("plant=*")
        plant_map.populate_map_from_search_view(view=search_view)
        # update for _populate_map_from_search_view
        update_gui()
        plant_map.populate_thread.join()
        update_gui()
        self.assertEqual(len(plant_map.map_items), 3)
        self.assertIsInstance(plant_map.map_items[1], MapImage)
        self.assertIsInstance(plant_map.map_items[2], MapTrack)
        self.assertIsInstance(plant_map.map_items[3], MapPolygon)
        plant_map.destroy()

    def test_search_view_sets_up(self):
        # test the GardenPlugin.setup_plant_map
        search_view = SearchView()
        self.assertEqual(search_view.pic_pane_notebook.get_n_pages(), 1)

        from . import GardenPlugin
        from . import map_is_visible

        self.assertFalse(map_is_visible())

        GardenPlugin.setup_plant_map()
        search_view = SearchView()
        search_view.pic_pane = mock.Mock()
        search_view.pic_pane.get_allocation().width = 1000
        search_view.pic_pane.get_child1().get_allocation().width = 500
        search_view.pic_pane_notebook.set_current_page(0)

        self.assertEqual(search_view.pic_pane_notebook.get_n_pages(), 2)
        self.assertIsInstance(
            search_view.pic_pane_notebook.get_nth_page(0), PlantMap
        )
        with mock.patch("bauble.gui") as mock_gui:
            mock_gui.get_view.return_value = search_view
            self.assertTrue(map_is_visible())

    def test_on_tiles_combo_changed(self):
        plant_map = PlantMap(is_visible=lambda *_: True)
        # pylint: disable=no-member
        self.assertEqual(plant_map.map.props.map_source, 1)
        mock_combo = mock.Mock()
        mock_combo.get_active_text.return_value = "Google Maps"
        plant_map.on_tiles_combo_changed(mock_combo)
        self.assertEqual(prefs.prefs.get(MAP_TILES_PREF_KEY), 7)
        self.assertEqual(plant_map.map.props.map_source, 7)
