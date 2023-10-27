# pylint: disable=protected-access
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
from dataclasses import astuple
from time import sleep
from unittest import mock

import gi

gi.require_version("OsmGpsMap", "1.0")

from gi.repository import GLib
from gi.repository.OsmGpsMap import Map  # type: ignore
from gi.repository.OsmGpsMap import MapImage
from gi.repository.OsmGpsMap import MapPolygon
from gi.repository.OsmGpsMap import MapTrack

from bauble import db
from bauble import prefs
from bauble.test import BaubleTestCase
from bauble.test import get_setUp_data_funcs
from bauble.test import update_gui
from bauble.view import SearchView

from . import Location
from . import Plant
from . import garden_map
from .garden_map import MAP_LOCATION_COLOUR_PREF_KEY
from .garden_map import MAP_TILES_PREF_KEY
from .garden_map import BoundingBox
from .garden_map import GardenMap
from .garden_map import MapLine
from .garden_map import MapPoint
from .garden_map import MapPoly
from .garden_map import SearchViewMapPresenter
from .garden_map import colours
from .garden_map import expunge_garden_map
from .garden_map import get_locations_polys
from .garden_map import glib_events
from .garden_map import map_item_factory
from .garden_map import setup_garden_map

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


class TestGardenMap(BaubleTestCase):
    def test_empty_garden_map(self):
        map_ = GardenMap(Map())
        self.assertEqual(map_.map.get_property("map-source"), 1)

    def test_map_item_fatory_plant_point(self):
        plant = Plant(geojson=point)
        colour = colours.get("red")
        item = map_item_factory(plant, colour)
        self.assertIsInstance(item, MapPoint)
        self.assertEqual(item.image, colour.image)

    def test_map_item_fatory_plant_line(self):
        plant = Plant(geojson=line)
        colour = colours.get("blue")
        item = map_item_factory(plant, colour)
        self.assertIsInstance(item, MapLine)
        self.assertEqual(item.rgba, colour.rgba)

    def test_map_item_fatory_plant_poly(self):
        plant = Plant(geojson=poly)
        colour = colours.get("black")
        item = map_item_factory(plant, colour)
        self.assertIsInstance(item, MapPoly)
        self.assertEqual(item.rgba, colour.rgba)

    def test_map_item_fatory_location_poly(self):
        loc = Location(geojson=poly)
        colour = colours.get("grey")
        item = map_item_factory(loc, colour)
        self.assertIsInstance(item, MapPoly)
        self.assertEqual(item.rgba, colour.rgba)

    def test_map_item_fatory_location_no_geojson(self):
        loc = Location()
        colour = colours.get("black")
        item = map_item_factory(loc, colour)
        self.assertIsNone(item)

    def test_map_item_fatory_location_corrupt_geojson(self):
        loc = Location(geojson={"test": "this fails"})
        colour = colours.get("white")
        item = map_item_factory(loc, colour)
        self.assertIsNone(item)

    def test_map_point_add_to_map(self):
        map_ = GardenMap(Map())
        glib_events[1] = True
        colour = colours.get("white")
        map_item = MapPoint(1, point, colour)
        map_item.add_to_map(map_.map)
        self.assertIsInstance(map_item.point, MapImage)
        self.assertEqual(glib_events, {})

    def test_map_point_remove_from_map(self):
        map_ = GardenMap(Map())
        colour = colours.get("white")
        map_item = MapPoint(1, point, colour)
        map_item.add_to_map(map_.map)
        mock_map = mock.Mock()
        map_item.remove_from_map(mock_map)
        mock_map.image_remove.assert_called_with(map_item.point)

    def test_map_point_add_to_map_no_glib_events(self):
        map_ = GardenMap(Map())
        colour = colours.get("white")
        map_item = MapPoint(1, point, colour)
        map_item.add_to_map(map_.map)
        self.assertIsNone(map_item.point)
        self.assertEqual(glib_events, {})

    def test_map_point_wrong_type(self):
        self.assertRaises(TypeError, MapPoint, 1, poly, colours.get("white"))

    def test_map_line_add_to_map(self):
        map_ = GardenMap(Map())
        glib_events[1] = True
        colour = colours.get("yellow")
        map_item = MapLine(1, line, colour)
        map_item.add_to_map(map_.map)
        self.assertIsInstance(map_item._line, MapTrack)
        self.assertEqual(glib_events, {})

    def test_map_line_remove_from_map(self):
        colour = colours.get("white")
        map_item = MapLine(1, line, colour)
        map_item.create_item()
        mock_map = mock.Mock()
        map_item.remove_from_map(mock_map)
        mock_map.track_remove.assert_called_with(map_item._line)

    def test_map_line_add_to_map_no_glib_events(self):
        map_ = GardenMap(Map())
        colour = colours.get("green")
        map_item = MapLine(1, line, colour)
        map_item.add_to_map(map_.map)
        self.assertIsNone(map_item._line)
        self.assertEqual(glib_events, {})

    def test_map_line_wrong_type(self):
        self.assertRaises(TypeError, MapLine, 1, point, colours.get("white"))

    def test_map_poly_add_to_map(self):
        map_ = GardenMap(Map())
        glib_events[1] = True
        colour = colours.get("yellow")
        map_item = MapPoly(1, poly, colour)
        map_item.add_to_map(map_.map)
        self.assertIsInstance(map_item._poly, MapPolygon)
        self.assertEqual(glib_events, {})

    def test_map_poly_remove_from_map(self):
        colour = colours.get("white")
        map_item = MapPoly(1, poly, colour)
        map_item.create_item()
        mock_map = mock.Mock()
        map_item.remove_from_map(mock_map)
        mock_map.polygon_remove.assert_called_with(map_item._poly)

    def test_map_poly_add_to_map_no_glib_events(self):
        map_ = GardenMap(Map())
        colour = colours.get("green")
        map_item = MapPoly(1, poly, colour)
        map_item.add_to_map(map_.map)
        self.assertIsNone(map_item._poly)
        self.assertEqual(glib_events, {})

    def test_map_poly_set_props(self):
        colour = colours.get("red")
        map_item = MapPoly(1, poly, colour)
        map_item.set_props(alpha=0.7, line_width=2)
        self.assertIsInstance(map_item._poly, MapPolygon)
        self.assertAlmostEqual(
            map_item._poly.get_track().props.alpha, 0.7, delta=7
        )
        self.assertEqual(map_item._poly.get_track().props.line_width, 2)

    def test_map_poly_update(self):
        colour = colours.get("grey")
        map_item = MapPoly(1, poly, colour)
        # does nothing
        map_item.update(poly)
        self.assertEqual(map_item.coordinates, poly["coordinates"])
        for i, pnt in enumerate(map_item.poly.get_track().get_points()):
            degs = pnt.get_degrees()
            self.assertAlmostEqual(
                poly["coordinates"][0][i][0], degs[1], delta=6
            )
            self.assertAlmostEqual(
                poly["coordinates"][0][i][1], degs[0], delta=6
            )
        # changes
        poly2 = {
            "type": "Polygon",
            "coordinates": [
                [
                    [27.477559016773604, -152.97445813351644],
                    [27.477874827537065, -152.97463243273273],
                    [27.477748345857805, -152.9744273500483],
                    [27.477559016773604, -152.97445813351644],
                ]
            ],
        }
        map_item.update(poly2)
        for i, pnt in enumerate(map_item.poly.get_track().get_points()):
            degs = pnt.get_degrees()
            self.assertAlmostEqual(
                poly2["coordinates"][0][i][0], degs[1], delta=6
            )
            self.assertAlmostEqual(
                poly2["coordinates"][0][i][1], degs[0], delta=6
            )

        self.assertEqual(map_item._poly.get_track().props.line_width, 2)

    def test_map_poly_wrong_type(self):
        self.assertRaises(TypeError, MapPoly, 1, line, colours.get("white"))

    def test_on_tiles_combo_changed(self):
        map_ = GardenMap(Map())
        # pylint: disable=no-member
        self.assertEqual(map_.map.props.map_source, 1)
        mock_combo = mock.Mock()
        mock_combo.get_active_text.return_value = "Google Maps"
        map_.on_tiles_combo_changed(mock_combo)
        self.assertEqual(prefs.prefs.get(MAP_TILES_PREF_KEY), 7)
        self.assertEqual(map_.map.props.map_source, 7)

    def test_set_colour_prefs_from_combo(self):
        map_ = GardenMap(Map())
        map_.reset_item_colour = mock.Mock(return_value=False)
        combo = mock.Mock()
        combo.get_active_iter.return_value = 1
        colour = colours["green"]
        combo.get_model.return_value = {1: [colour]}
        map_._set_colour_prefs_from_combo(combo, MAP_LOCATION_COLOUR_PREF_KEY)
        update_gui()
        self.assertEqual(
            prefs.prefs.get(MAP_LOCATION_COLOUR_PREF_KEY), colour.name
        )
        map_.reset_item_colour.assert_called()


class TestSearchViewMapPresenter(BaubleTestCase):
    def setUp(self):
        super().setUp()
        SearchViewMapPresenter.thread_event.clear()
        get_locations_polys.clear_cache()

    def test_on_destroy(self):
        map_ = GardenMap(Map())
        presenter = SearchViewMapPresenter(map_)
        thread_event = presenter.thread_event
        self.assertFalse(thread_event.is_set())
        presenter.on_destroy()
        self.assertTrue(thread_event.is_set())

    def test_populate_map_empty_results(self):
        map_ = GardenMap(Map())
        presenter = SearchViewMapPresenter(map_)
        results = []
        presenter.populate_map(results)
        update_gui()
        self.assertEqual(presenter.plt_items, {})
        self.assertEqual(presenter.selected, set())
        self.assertIsNone(presenter.populate_thread)

    def test_populate_map_not_visible(self):
        for func in get_setUp_data_funcs():
            func()
        results = self.session.query(Location).all()
        for i in results:
            i.geojson = poly
        map_ = GardenMap(Map())
        presenter = SearchViewMapPresenter(map_)
        presenter.is_visible = lambda: False
        presenter.populate_map(results)
        update_gui()
        self.assertEqual(presenter.loc_items, {})
        self.assertEqual(presenter.selected, set())
        self.assertIsNone(presenter.populate_thread)

    def test_populate_map_no_geojson(self):
        for func in get_setUp_data_funcs():
            func()
        results = self.session.query(Location).all()
        map_ = GardenMap(Map())
        presenter = SearchViewMapPresenter(map_)
        presenter.is_visible = lambda: True
        presenter.populate_map(results)
        self.assertIsNotNone(presenter.populate_thread)
        presenter.populate_thread.join()
        update_gui()
        self.assertEqual(presenter.plt_items, {})
        self.assertEqual(presenter.selected, set())
        map_.destroy()

    def test_populate_map_stops_threads(self):
        for func in get_setUp_data_funcs():
            func()
        map_ = GardenMap(Map())
        presenter = SearchViewMapPresenter(map_)
        presenter.is_visible = lambda: True
        stopped = []

        def dont_stop():
            while True:
                if presenter.thread_event.is_set():
                    stopped.append(None)
                    break
                sleep(0.2)

        presenter.populate_thread = threading.Thread(target=dont_stop)
        presenter.populate_thread.start()
        presenter.update_thread = threading.Thread(target=dont_stop)
        presenter.update_thread.start()
        results = self.session.query(Location).all()
        with self.assertLogs(level="DEBUG") as logs:
            presenter.populate_map(results)
            # run twice checks first cancels the other
            presenter.populate_map(results)
            presenter.populate_thread.join()
            update_gui()
        self.assertTrue(any("clearing GLib events" in i for i in logs.output))
        self.assertEqual(len(stopped), 2)
        map_.destroy()

    def test_populate_map_stops_glib_events(self):
        for func in get_setUp_data_funcs():
            func()
        map_ = GardenMap(Map())
        presenter = SearchViewMapPresenter(map_)
        presenter.is_visible = lambda: True

        results = self.session.query(Location).all()
        mock_source = mock.Mock()
        glib_events[1] = mock_source
        presenter.populate_map(results)
        presenter.populate_thread.join()
        mock_source.destroy.assert_called()
        self.assertEqual(glib_events, {})
        map_.destroy()

    def test_populate_map_failed_search(self):
        map_ = GardenMap(Map())
        presenter = SearchViewMapPresenter(map_)
        presenter.is_visible = lambda: True
        results = ["failed search"]
        presenter.populate_map(results)
        update_gui()
        self.assertEqual(presenter.plt_items, {})
        self.assertEqual(presenter.selected, set())
        self.assertIsNotNone(presenter.populate_thread)
        self.assertEqual(glib_events, {})

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
        map_ = GardenMap(Map())
        presenter = SearchViewMapPresenter(map_)
        presenter.is_visible = lambda: True
        presenter.populate_map(results)
        self.assertIsNotNone(presenter.populate_thread)
        presenter.populate_thread.join()
        update_gui()
        self.assertEqual(len(presenter.plt_items), 3)
        self.assertIsInstance(presenter.plt_items[1], MapPoint)
        self.assertIsInstance(presenter.plt_items[2], MapLine)
        self.assertIsInstance(presenter.plt_items[3], MapPoly)
        self.assertEqual(presenter.selected, set())
        self.assertEqual(glib_events, {})
        map_.destroy()

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
        map_ = GardenMap(Map())
        presenter = SearchViewMapPresenter(map_)
        presenter.is_visible = lambda: True
        presenter.populate_map(results)
        presenter.populate_thread.join()
        update_gui()
        presenter.update_map([plt1, plt3])
        presenter.update_thread.join()
        update_gui()
        self.assertEqual(presenter.selected, {("plt", 1), ("plt", 3)})
        # check color changed
        self.assertEqual(
            presenter.plt_items[3].rgba,
            map_.map_plant_selected_colour.rgba,
        )
        # change selection and check it updates (tests clear_selected also)
        presenter.update_map([plt2])
        presenter.update_thread.join()
        update_gui()
        self.assertEqual(presenter.selected, {("plt", 2)})
        self.assertEqual(
            presenter.plt_items[3].rgba,
            map_.map_plant_colour.rgba,
        )

    def test_update_map_updates_bbox(self):
        for func in get_setUp_data_funcs():
            func()
        plt1 = self.session.query(Plant).get(1)
        plt2 = self.session.query(Plant).get(2)
        plt3 = self.session.query(Plant).get(3)
        plt1.geojson = point
        plt3.geojson = poly
        self.session.commit()
        results = self.session.query(Plant).all()

        map_ = GardenMap(Map())
        presenter = SearchViewMapPresenter(map_)
        presenter.selected_bbox.clear()
        presenter.is_visible = lambda: True

        presenter.populate_map(results)
        presenter.populate_thread.join()
        update_gui()
        presenter.update_map([plt1, plt3])
        presenter.update_thread.join()
        update_gui()
        expected = (
            -27.477558135986328,
            -27.477874755859375,
            152.97898864746094,
            152.97442626953125,
        )
        self.assertEqual(astuple(presenter.selected_bbox), expected)
        # change selection to no geojson should clear
        presenter.update_map([plt2])
        presenter.update_thread.join()
        update_gui()
        self.assertEqual(
            astuple(presenter.selected_bbox), (None, None, None, None)
        )

    def test_update_map_threads(self):
        for func in get_setUp_data_funcs():
            func()
        plt1 = self.session.query(Plant).get(1)
        plt3 = self.session.query(Plant).get(3)
        plt1.geojson = point
        plt3.geojson = poly
        self.session.commit()
        results = self.session.query(Plant).all()

        map_ = GardenMap(Map())
        presenter = SearchViewMapPresenter(map_)
        presenter.is_visible = lambda: True

        presenter.populate_map(results)
        presenter.populate_thread.join()
        update_gui()
        stopped = []

        def dont_stop():
            while True:
                if presenter.update_thread_event.is_set():
                    stopped.append(None)
                    break
                sleep(0.2)

        presenter.update_thread = threading.Thread(target=dont_stop)
        presenter.update_thread.start()

        presenter.update_map([plt1])
        presenter.update_thread.join()
        update_gui()

        self.assertEqual(len(stopped), 1)

    def test_update_map_redraw(self):
        for func in get_setUp_data_funcs():
            func()
        plt1 = self.session.query(Plant).get(1)
        plt3 = self.session.query(Plant).get(3)
        plt1.geojson = point
        plt3.geojson = poly
        self.session.commit()
        results = self.session.query(Plant).all()

        map_ = GardenMap(Map())
        presenter = SearchViewMapPresenter(map_)
        presenter.is_visible = lambda: True
        presenter.redraw_on_update = True
        presenter._populate_map_from_search_view = mock.Mock()
        presenter.clear_selected = mock.Mock()
        presenter.populate_map(results)
        presenter.populate_thread.join()

        presenter.update_map([plt1])
        self.assertFalse(presenter.redraw_on_update)
        self.assertIsNone(presenter.update_thread)
        presenter._populate_map_from_search_view.assert_called()
        presenter.clear_selected.assert_not_called()

    @mock.patch("bauble.plugins.garden.garden_map.GLib")
    def test_update_worker_bails_early_on_thread_event(self, mock_glib):
        map_ = GardenMap(Map())
        presenter = SearchViewMapPresenter(map_)
        presenter._highlight_plant = mock.Mock()
        presenter._highlight_location = mock.Mock()
        presenter.update_thread_event.set()
        presenter._update_worker([Plant()])
        mock_glib.idle_add.assert_not_called()
        presenter._highlight_plant.assert_not_called()
        presenter._highlight_location.assert_not_called()

    def test_clear_selected(self):
        for func in get_setUp_data_funcs():
            func()
        map_ = GardenMap(Map())
        presenter = SearchViewMapPresenter(map_)
        presenter.is_visible = lambda: True
        # preload the cache
        get_locations_polys()
        plt1 = self.session.query(Plant).get(1)
        plt2 = self.session.query(Plant).get(2)
        plt3 = self.session.query(Plant).get(3)
        plt1.geojson = point
        plt2.geojson = line
        plt3.geojson = poly
        loc1 = self.session.query(Location).get(1)
        loc1.geojson = poly
        self.session.commit()
        get_locations_polys.clear_cache()
        results = self.session.query(Plant).all()
        presenter.populate_map(results)
        presenter.populate_thread.join()
        update_gui()
        presenter.update_map([plt1, plt3])
        presenter.update_thread.join()
        update_gui()
        self.assertEqual(presenter.selected, {("plt", 1), ("plt", 3)})
        presenter.clear_selected()
        self.assertEqual(presenter.selected, set())
        self.assertEqual(
            presenter.plt_items[3].rgba,
            map_.map_plant_colour.rgba,
        )
        presenter.update_map([loc1])
        presenter.update_thread.join()
        update_gui()
        self.assertEqual(presenter.selected, {("loc", 1)})
        presenter.clear_selected()
        self.assertEqual(presenter.selected, set())
        self.assertEqual(
            get_locations_polys()[1].rgba,
            map_.map_location_colour.rgba,
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
        map_ = GardenMap(Map())
        presenter = SearchViewMapPresenter(map_)
        presenter.is_visible = lambda: True
        search_view = SearchView()
        search_view.search("plant=*")
        presenter.populate_map_from_search_view(view=search_view)
        # update for _populate_map_from_search_view
        update_gui()
        presenter.populate_thread.join()
        update_gui()
        self.assertEqual(len(presenter.plt_items), 3)
        self.assertIsInstance(presenter.plt_items[1], MapPoint)
        self.assertIsInstance(presenter.plt_items[2], MapLine)
        self.assertIsInstance(presenter.plt_items[3], MapPoly)
        map_.destroy()
        presenter.update_thread.join()

    def test_get_location_polys(self):
        for func in get_setUp_data_funcs():
            func()
        setup_garden_map()
        presenter = garden_map.map_presenter
        presenter.is_visible = lambda: True
        # preload the cache
        get_locations_polys()
        loc = self.session.query(Location).get(1)
        loc.geojson = poly
        self.session.commit()
        presenter.add_locations()
        polys = get_locations_polys()
        self.assertEqual(len(polys), 1)
        self.assertEqual(polys[1].id_, 1)
        # test values are cached
        with self.assertNoLogs(level="DEBUG"):
            presenter.add_locations()
            polys2 = get_locations_polys()
        self.assertEqual(polys, polys2)
        # test values are updated next call if if any locs are updated
        loc = self.session.query(Location).get(2)
        loc.geojson = poly
        self.session.commit()
        with self.assertLogs(level="DEBUG") as logs:
            presenter.add_locations()
            polys3 = get_locations_polys()
        self.assertTrue(any("get_locations_polys" in i for i in logs.output))
        self.assertNotEqual(polys, polys3)
        self.assertEqual(len(polys3), 2)
        # test doesn't fail if pref set incorrect
        get_locations_polys.clear_cache()
        prefs.prefs[MAP_LOCATION_COLOUR_PREF_KEY] = "rainbow"
        polys4 = get_locations_polys()
        self.assertEqual(len(polys4), len(polys3))
        # test doesn't fail if db.Session is None (instead returns {})
        get_locations_polys.clear_cache()
        db.Session = None
        self.assertEqual(get_locations_polys(), {})
        expunge_garden_map()

    def test_add_locations(self):
        map_ = GardenMap(Map())
        presenter = SearchViewMapPresenter(map_)
        presenter.is_visible = lambda: True
        with mock.patch(
            "bauble.plugins.garden.garden_map.get_locations_polys"
        ) as mock_get_polys:
            mock_poly = mock.Mock()
            mock_get_polys.return_value = {1: mock_poly}
            presenter.add_locations()
            mock_poly.add_to_map.assert_called_with(map_.map, glib=False)

    def test_reset_selected_colour(self):
        map_ = GardenMap(Map())
        presenter = SearchViewMapPresenter(map_)
        presenter.is_visible = lambda: True
        mock_loc_item = mock.Mock()
        presenter.loc_items = {1: mock_loc_item}
        presenter.selected = [("plt", 1), ("loc", 1)]
        mock_plant_item = mock.Mock()
        presenter.plt_items = {1: mock_plant_item}
        presenter.reset_selected_colour()
        mock_plant_item.set_colour.assert_called_with(
            map_.map_plant_selected_colour
        )
        mock_loc_item.set_colour.assert_called_with(
            map_.map_location_selected_colour
        )

    def test_reset_item_colour(self):
        map_ = GardenMap(Map())
        presenter = SearchViewMapPresenter(map_)
        presenter.is_visible = lambda: True
        mock_loc_item = mock.Mock()
        presenter.loc_items = {1: mock_loc_item}
        mock_plant_item = mock.Mock()
        presenter.plt_items = {1: mock_plant_item}
        stopped = []

        def dont_stop():
            for _ in range(4):
                sleep(0.2)
            stopped.append(None)

        # check it waits on populate thread
        presenter.populate_thread = threading.Thread(target=dont_stop)
        presenter.populate_thread.start()
        with self.assertLogs(level="DEBUG") as logs:
            presenter.reset_item_colour()
        self.assertTrue(
            any("waiting on populate thread" in i for i in logs.output)
        )
        mock_plant_item.set_colour.assert_called_with(map_.map_plant_colour)
        mock_loc_item.set_colour.assert_called_with(map_.map_location_colour)
        self.assertEqual(len(stopped), 1)

    def test_on_button_press(self):
        map_ = GardenMap(Map())
        presenter = SearchViewMapPresenter(map_)
        presenter.is_visible = lambda: True
        presenter.context_menu = mock.Mock()
        mock_event = mock.Mock(button=3)
        presenter.on_button_press(None, mock_event)
        presenter.context_menu.popup_at_pointer.assert_called_with(mock_event)
        presenter.context_menu.reset_mock()
        mock_event.button = 1
        presenter.on_button_press(None, mock_event)
        presenter.context_menu.popup_at_pointer.assert_not_called()

    def test_on_zoom_to_selected(self):
        map_ = GardenMap(Map())
        presenter = SearchViewMapPresenter(map_)
        presenter.is_visible = lambda: True
        presenter.selected_bbox = BoundingBox(1.0, 0.1, 1.0, 0.1)
        map_.map = mock.Mock()
        presenter.selected = [("plt", 1)]
        presenter.on_zoom_to_selected()
        map_.map.zoom_fit_bbox.assert_called_with(1.0, 0.1, 1.0, 0.1)
        map_.map.reset_mock()
        presenter.selected = []
        presenter.on_zoom_to_selected()
        map_.map.zoom_fit_bbox.assert_not_called()

    def test_highlight_location(self):
        for func in get_setUp_data_funcs():
            func()
        loc1 = self.session.query(Location).get(1)
        loc1.geojson = poly
        self.session.commit()
        map_ = GardenMap(Map())
        presenter = SearchViewMapPresenter(map_)
        presenter.is_visible = lambda: True
        presenter.add_locations()
        presenter._highlight_location(1)
        update_gui()
        self.assertEqual(
            get_locations_polys()[1].rgba,
            map_.map_location_selected_colour.rgba,
        )
        self.assertEqual(presenter.selected, {("loc", 1)})

    def test_highlight_plant(self):
        for func in get_setUp_data_funcs():
            func()
        plt1 = self.session.query(Plant).get(1)
        plt1.geojson = point
        self.session.commit()
        map_ = GardenMap(Map())
        presenter = SearchViewMapPresenter(map_)
        presenter.is_visible = lambda: True
        map_item = map_item_factory(plt1, colours["red"])
        # for point the only way to create the item is to add it to the map
        glib_events[1] = True
        map_item.add_to_map(map_.map)
        presenter.plt_items[1] = map_item
        presenter._highlight_plant(1)
        update_gui()
        self.assertEqual(
            presenter.plt_items[1].image,
            map_.map_plant_selected_colour.image,
        )
        self.assertEqual(presenter.selected, {("plt", 1)})

    def test_update_after_db_connection_change(self):
        get_locations_polys.clear_cache()
        setup_garden_map()
        for func in get_setUp_data_funcs():
            func()
        results = self.session.query(Location).all()
        for loc in results:
            loc.geojson = poly
        self.session.commit()
        self.assertTrue(results)
        presenter = garden_map.map_presenter
        presenter.is_visible = lambda: True
        self.assertEqual(len(presenter.loc_items), 0)
        presenter.populate_map(results)
        update_gui()
        presenter.populate_thread.join()
        # check we did populate
        self.assertEqual(len(results), len(presenter.loc_items))
        garden_map.glib_events[1] = GLib.idle_source_new()
        # test stops threads and clears glib events
        stopped = []

        def dont_stop():
            while True:
                if presenter.thread_event.is_set():
                    stopped.append(None)
                    break
                sleep(0.2)

        presenter.populate_thread = threading.Thread(target=dont_stop)
        presenter.populate_thread.start()
        presenter.update_thread = threading.Thread(target=dont_stop)
        presenter.update_thread.start()
        self.assertTrue(presenter.populate_thread.is_alive())
        self.assertTrue(presenter.update_thread.is_alive())

        db.open_conn(
            "sqlite:///:memory:",
            verify=False,
            show_error_dialogs=False,
        )
        self.assertFalse(presenter.populate_thread.is_alive())
        self.assertFalse(presenter.update_thread.is_alive())
        self.assertEqual(len(stopped), 2)
        self.assertFalse(garden_map.glib_events)
        expunge_garden_map()

    def test_update_after_location_change_edit_geojson(self):
        get_locations_polys.clear_cache()
        for func in get_setUp_data_funcs():
            func()
        results = self.session.query(Location).all()
        for loc in results:
            loc.geojson = poly
        self.session.commit()
        setup_garden_map()
        self.assertTrue(results)
        presenter = garden_map.map_presenter
        presenter.is_visible = lambda: True
        self.assertEqual(len(presenter.loc_items), 0)
        presenter.populate_map(results)
        update_gui()
        presenter.populate_thread.join()
        # check we did populate and flags are not set
        self.assertEqual(len(results), len(presenter.loc_items))
        self.assertFalse(presenter.redraw_on_update)
        self.assertFalse(presenter.clear_locations_cache)
        loc1 = self.session.query(Location).get(1)
        self.assertIn(loc1.id, presenter.loc_items)

        poly2 = {
            "type": "Polygon",
            "coordinates": [
                [
                    [27.477559016773604, -152.97445813351644],
                    [27.477874827537065, -152.97463243273273],
                    [27.477748345857805, -152.9744273500483],
                    [27.477559016773604, -152.97445813351644],
                ]
            ],
        }
        loc1.geojson = poly2
        self.session.commit()
        self.assertTrue(presenter.redraw_on_update)
        self.assertTrue(presenter.clear_locations_cache)
        self.assertIn(loc1.id, presenter.loc_items)
        expunge_garden_map()

    def test_update_after_location_change_delete_geojson(self):
        get_locations_polys.clear_cache()
        for func in get_setUp_data_funcs():
            func()
        results = self.session.query(Location).all()
        for loc in results:
            loc.geojson = poly
        self.session.commit()
        setup_garden_map()
        self.assertTrue(results)
        presenter = garden_map.map_presenter
        presenter.is_visible = lambda: True
        self.assertEqual(len(presenter.loc_items), 0)
        presenter.populate_map(results)
        update_gui()
        presenter.populate_thread.join()
        # check we did populate and flags are not set
        self.assertEqual(len(results), len(presenter.loc_items))
        self.assertFalse(presenter.redraw_on_update)
        self.assertFalse(presenter.clear_locations_cache)
        loc1 = self.session.query(Location).get(1)
        self.assertIn(loc1.id, presenter.loc_items)

        loc1.geojson = None
        self.session.commit()
        self.assertTrue(presenter.clear_locations_cache)
        self.assertNotIn(loc1.id, presenter.loc_items)
        expunge_garden_map()

    def test_update_after_location_delete(self):
        get_locations_polys.clear_cache()
        loc1 = Location(code="xyz", geojson=poly)
        self.session.add(loc1)
        self.session.commit()
        setup_garden_map()
        presenter = garden_map.map_presenter
        presenter.is_visible = lambda: True
        self.assertEqual(len(presenter.loc_items), 0)
        presenter.populate_map([loc1])
        presenter.populate_thread.join()
        update_gui()
        # check we did populate and flags are not set
        for i in presenter.loc_items.values():
            print(i)
        self.assertEqual(len(presenter.loc_items), 1)
        self.assertFalse(presenter.redraw_on_update)
        self.assertFalse(presenter.clear_locations_cache)
        self.assertIn(loc1.id, presenter.loc_items)

        self.session.delete(loc1)
        self.session.commit()

        self.assertTrue(presenter.clear_locations_cache)
        self.assertNotIn(loc1.id, presenter.loc_items)

        expunge_garden_map()

    def test_update_after_plant_change_edit_geojson(self):
        get_locations_polys.clear_cache()
        for func in get_setUp_data_funcs():
            func()
        results = self.session.query(Plant).all()
        for plt in results:
            plt.geojson = point
        self.session.commit()
        setup_garden_map()
        self.assertTrue(results)
        presenter = garden_map.map_presenter
        presenter.is_visible = lambda: True
        self.assertEqual(len(presenter.loc_items), 0)
        presenter.populate_map(results)
        presenter.populate_thread.join()
        update_gui()
        # check we did populate and flags are not set
        self.assertEqual(len(results), len(presenter.plt_items))
        plt1 = self.session.query(Plant).get(1)
        self.assertIn(plt1.id, presenter.plt_items)
        self.assertIsInstance(presenter.plt_items[plt1.id], MapPoint)

        plt1.geojson = line
        self.session.commit()
        self.assertIn(plt1.id, presenter.plt_items)
        self.assertIsInstance(presenter.plt_items[plt1.id], MapLine)
        expunge_garden_map()

    def test_update_after_plant_change_delete_geojson(self):
        get_locations_polys.clear_cache()
        for func in get_setUp_data_funcs():
            func()
        results = self.session.query(Plant).all()
        for plt in results:
            plt.geojson = point
        self.session.commit()
        setup_garden_map()
        self.assertTrue(results)
        presenter = garden_map.map_presenter
        presenter.is_visible = lambda: True
        self.assertEqual(len(presenter.loc_items), 0)
        presenter.populate_map(results)
        presenter.populate_thread.join()
        update_gui()
        # check we did populate and flags are not set
        self.assertEqual(len(results), len(presenter.plt_items))
        plt1 = self.session.query(Plant).get(1)
        self.assertIn(plt1.id, presenter.plt_items)
        self.assertIsInstance(presenter.plt_items[plt1.id], MapPoint)

        plt1.geojson = None
        self.session.commit()
        self.assertNotIn(plt1.id, presenter.plt_items)
        expunge_garden_map()

    def test_update_after_plant_delete(self):
        get_locations_polys.clear_cache()
        for func in get_setUp_data_funcs():
            func()
        results = self.session.query(Plant).all()
        for plt in results:
            plt.geojson = point
        self.session.commit()
        setup_garden_map()
        self.assertTrue(results)
        presenter = garden_map.map_presenter
        presenter.is_visible = lambda: True
        self.assertEqual(len(presenter.loc_items), 0)
        presenter.populate_map(results)
        presenter.populate_thread.join()
        update_gui()
        # check we did populate and flags are not set
        self.assertEqual(len(results), len(presenter.plt_items))
        plt1 = self.session.query(Plant).get(1)
        self.assertIn(plt1.id, presenter.plt_items)
        self.assertIsInstance(presenter.plt_items[plt1.id], MapPoint)

        self.session.delete(plt1)
        self.session.commit()
        self.assertNotIn(plt1.id, presenter.plt_items)
        expunge_garden_map()


class GlobalFunctionsTest(BaubleTestCase):
    def test_search_view_sets_up(self):
        # test setup_garden_map
        SearchView.pic_pane_notebook_pages.clear()
        garden_map.map_presenter = None
        search_view = SearchView()
        self.assertEqual(search_view.pic_pane_notebook.get_n_pages(), 1)

        self.assertFalse(SearchViewMapPresenter.is_visible())

        setup_garden_map()
        search_view = SearchView()
        search_view.pic_pane = mock.Mock()
        search_view.pic_pane.get_allocation().width = 1000
        search_view.pic_pane.get_child1().get_allocation().width = 500
        search_view.pic_pane_notebook.set_current_page(0)

        self.assertEqual(search_view.pic_pane_notebook.get_n_pages(), 2)
        self.assertIsInstance(
            search_view.pic_pane_notebook.get_nth_page(0), GardenMap
        )
        with mock.patch("bauble.gui") as mock_gui:
            mock_gui.get_view.return_value = search_view
            self.assertTrue(SearchViewMapPresenter.is_visible())
        # test if we run it again it aborts
        map_presenter = garden_map.map_presenter
        with self.assertLogs(level="DEBUG") as logs:
            setup_garden_map()
        self.assertTrue(any("setup - aborting" in i for i in logs.output))
        self.assertEqual(map_presenter, garden_map.map_presenter)
        self.assertEqual(search_view.pic_pane_notebook.get_n_pages(), 2)
        self.assertEqual(
            search_view.pic_pane_notebook.get_nth_page(0),
            map_presenter.garden_map,
        )
        expunge_garden_map()
        # test calling twice doesn't fail
        expunge_garden_map()

    def test_boundingbox(self):
        bbox = BoundingBox()
        bbox.update([3.0, 15.0], [1.0, 12.0])
        self.assertEqual(astuple(bbox), (15.0, 3.0, 12.0, 1.0))
        bbox.update([2.0, 16.0], [2.0, 14.0])
        self.assertEqual(astuple(bbox), (16.0, 2.0, 14.0, 1.0))
        bbox.update([-2.0, -16.0], [-2.0, -14.0])
        self.assertEqual(astuple(bbox), (16.0, -16.0, 14.0, -14.0))
        bbox.clear()
        self.assertEqual(astuple(bbox), (None, None, None, None))
        bbox.update([-2.0, -16.0, -1.0, -5.0], [-2.0, -14.0, -9.1, -1.123])
        self.assertEqual(astuple(bbox), (-1.0, -16.0, -1.123, -14.0))
