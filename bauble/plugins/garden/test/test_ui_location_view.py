# Copyright 2025-2025 Ross Demuth <rossdemuth123@gmail.com>
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
Location search view tests
"""

from ..location import Location
from ..test_garden import GardenTestCase
from ..ui.location_view import DescriptionExpander
from ..ui.location_view import GeneralLocationExpander


class InfoBoxTests(GardenTestCase):

    def test_general_location_expander_update_w_geojson(self):
        expander = GeneralLocationExpander()
        loc = self.session.query(Location).first()
        loc.geojson = {
            "type": "Polygon",
            "coordinates": [
                [
                    [0.001, 0.001],
                    [0.0, 0.001],
                    [0.0, 0.0],
                    [0.001, 0.0],
                    [0.001, 0.001],
                ],
            ],
        }
        self.session.commit()

        expander.update(loc)

        self.assertEqual(expander.geojson_type_label.get_text(), "Polygon")
        self.assertEqual(expander.approx_area_label.get_text(), "12309.07 m²")

    def test_desription_expander_expands(self):
        expander = DescriptionExpander()
        # with description
        loc = self.session.query(Location).first()
        expander.update(loc)

        self.assertTrue(expander.get_expanded())

        # without description
        loc = self.session.get(Location, 2)
        expander.update(loc)

        self.assertFalse(expander.get_expanded())
