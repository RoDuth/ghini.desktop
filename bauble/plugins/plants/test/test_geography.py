# pylint: disable=too-many-locals
# Copyright 2008-2010 Brett Adams
# Copyright 2015 Mario Frasca <mario@anche.no>.
# Copyright 2017 Jardín Botánico de Quito
# Copyright 2021-2026 Ross Demuth <rossdemuth123@gmail.com>
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
Geography tests.
"""
import os
from unittest import TestCase

from bauble import db
from bauble.test import BaubleClassTestCase
from bauble.test import BaubleTestCase

from ..family import Family
from ..genus import Genus
from ..geography import Geography
from ..geography import _coord_string
from ..geography import _path_string
from ..geography import consolidate_geographies
from ..geography import consolidate_geographies_by_percent_area
from ..geography import get_species_in_geography
from ..species import Species
from ..species import SpeciesDistribution
from .test_plants import setUp_data as setup_plants_data


def setup_geographies() -> None:
    """For convenience for test that need geography data run this."""

    from bauble.paths import lib_dir
    from bauble.plugins.imex.csv_ import CSVRestore

    csv = CSVRestore()
    geo_csv = os.path.join(
        lib_dir(), "plugins", "plants", "default", "geography.csv"
    )
    csv.start(
        [geo_csv],
        metadata=db.metadata,
        force=True,
    )


class GeographyTests(BaubleClassTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        setup_plants_data()
        cls.family = Family(family="family")
        cls.genus = Genus(genus="genus", family=cls.family)
        cls.session.add_all([cls.family, cls.genus])
        cls.session.flush()
        setup_geographies()
        cls.session.commit()

    def test_get_species(self):
        mexico_id = 53
        mexico_central_id = 267
        puebla_id = 642
        oaxaca_id = 665
        northern_america_id = 7
        western_canada_id = 45
        british_columbia_id = 102

        # create a some species
        sp1 = Species(genus=self.genus, sp="sp1")
        dist = SpeciesDistribution(geography_id=mexico_central_id)
        sp1.distribution.append(dist)
        self.session.add_all([sp1, dist])
        # commit each time seems to avoid: KeyError: "Deferred loader for
        # attribute '_created' failed to populate correctly"
        self.session.commit()

        sp2 = Species(genus=self.genus, sp="sp2")
        dist = SpeciesDistribution(geography_id=oaxaca_id)
        sp2.distribution.append(dist)
        self.session.add_all([sp2, dist])
        self.session.commit()

        sp3 = Species(genus=self.genus, sp="sp3")
        dist = SpeciesDistribution(geography_id=western_canada_id)
        sp3.distribution.append(dist)
        self.session.add_all([sp3, dist])
        self.session.commit()

        oaxaca = self.session.get(Geography, oaxaca_id)
        species = get_species_in_geography(oaxaca)
        self.assertTrue([s.id for s in species] == [sp2.id])

        mexico = self.session.get(Geography, mexico_id)
        species = get_species_in_geography(mexico)
        self.assertTrue([s.id for s in species] == [sp1.id, sp2.id])

        north_america = self.session.get(Geography, northern_america_id)
        species = get_species_in_geography(north_america)
        self.assertTrue([s.id for s in species] == [sp1.id, sp2.id, sp3.id])

        # recorded in parent should show in children
        british_columbia = self.session.get(Geography, british_columbia_id)
        species = get_species_in_geography(british_columbia)
        self.assertTrue([s.id for s in species] == [sp3.id])

        puebla = self.session.get(Geography, puebla_id)
        species = get_species_in_geography(puebla)
        self.assertTrue([s.id for s in species] == [sp1.id])

        # un mapped raises
        geo = Geography()
        self.assertRaises(ValueError, get_species_in_geography, geo)

    def test_species_distribution_str(self):
        # create a some species
        sp1 = Species(genus=self.genus, sp="sp1000")
        dist = SpeciesDistribution(geography_id=267)
        sp1.distribution.append(dist)
        self.session.flush()
        self.assertEqual(sp1.distribution_str(), "Mexico Central")
        dist = SpeciesDistribution(geography_id=45)
        sp1.distribution.append(dist)
        self.session.flush()
        self.assertEqual(
            sp1.distribution_str(), "Mexico Central, Western Canada"
        )

    def test_get_children_id_get_parent_id(self):
        australia = self.session.get(Geography, 38)
        self.assertCountEqual(
            australia.get_children_ids(),
            [
                414,
                359,
                296,
                297,
                330,
                682,
                683,
                695,
                727,
                688,
                689,
                694,
                407,
                726,
                378,
                286,
            ],
        )
        lord_howe = self.session.get(Geography, 682)
        self.assertCountEqual(lord_howe.get_parent_ids(), [286, 38, 5])

    def test_consolidate_geographies(self):
        # all level 2 geographies
        lv2 = self.session.query(Geography).filter(Geography.level == 2)
        result = (
            self.session.query(Geography).filter(Geography.level == 1).all()
        )
        self.assertCountEqual(result, consolidate_geographies(lv2))
        # all level 3 geographies from EUROPE and AUSTRALASIA
        lv2s = (
            self.session.query(Geography.id)
            .filter(Geography.level == 2)
            .filter(Geography.parent_id.in_([1, 5]))
        )
        lv3 = (
            self.session.query(Geography)
            .filter(Geography.level == 3)
            .filter(Geography.parent_id.in_(lv2s))
        )
        result = (
            self.session.query(Geography)
            .filter(Geography.id.in_([1, 5]))
            .all()
        )
        self.assertCountEqual(result, consolidate_geographies(lv3))
        # all level 4 geographies from Brazil
        lv3s = (
            self.session.query(Geography.id)
            .filter(Geography.level == 3)
            .filter(Geography.parent_id == 58)
        )
        lv4 = (
            self.session.query(Geography)
            .filter(Geography.parent_id.in_(lv3s))
            .filter(Geography.level == 4)
        )
        result = [self.session.get(Geography, 58)]
        self.assertCountEqual(result, consolidate_geographies(lv4))
        # a combination that ends up in AUSTALIASIA + Paupua New Guinea
        ids = (39, 688, 689, 286, 297, 330, 359, 378, 407, 414, 691)
        geos = self.session.query(Geography).filter(Geography.id.in_(ids))
        result = (
            self.session.query(Geography)
            .filter(Geography.id.in_((691, 5)))
            .all()
        )
        self.assertCountEqual(result, consolidate_geographies(geos))
        # AUSTRALASIA and Lord Howe I. should remove Lord Howe
        ids = (5, 682)
        geos = self.session.query(Geography).filter(Geography.id.in_(ids))
        result = [self.session.get(Geography, 5)]
        self.assertCountEqual(result, consolidate_geographies(geos))

    def test_approx_area(self):
        geos = self.session.query(Geography).filter(Geography.level < 3).all()
        for geo in geos:
            self.assertGreater(geo.approx_area, 0.0)
            if geo.children:
                children_area = sum(i.approx_area for i in geo.children)
                difference = abs(children_area - geo.approx_area)
                # NOTE have to accept 8% error due to current inaccuracy of
                # WGSRPD data
                error_margin = geo.approx_area * 8 / 100
                # error_margin = 5000
                self.assertLess(difference, error_margin, str(geo))

    def test_consolidate_geographies_by_percent_area(self):
        # all level 2 geographies
        lv2 = self.session.query(Geography).filter(Geography.level == 2)
        result = (
            self.session.query(Geography).filter(Geography.level == 1).all()
        )
        self.assertCountEqual(
            result, consolidate_geographies_by_percent_area(lv2, 34)
        )
        # all level 3 geographies from EUROPE and AUSTRALASIA
        lv2s = (
            self.session.query(Geography.id)
            .filter(Geography.level == 2)
            .filter(Geography.parent_id.in_([1, 5]))
        )
        lv3 = (
            self.session.query(Geography)
            .filter(Geography.level == 3)
            .filter(Geography.parent_id.in_(lv2s))
        )
        result = (
            self.session.query(Geography)
            .filter(Geography.id.in_([1, 5]))
            .all()
        )
        self.assertCountEqual(
            result, consolidate_geographies_by_percent_area(lv3, 33)
        )
        # all level 4 geographies from Brazil
        lv3s = (
            self.session.query(Geography.id)
            .filter(Geography.level == 3)
            .filter(Geography.parent_id == 58)
        )
        lv4 = (
            self.session.query(Geography)
            .filter(Geography.parent_id.in_(lv3s))
            .filter(Geography.level == 4)
        )
        # with allowable_children = 2 gets brazil
        result = [self.session.get(Geography, 58)]
        self.assertCountEqual(
            result, consolidate_geographies_by_percent_area(lv4, 33, 2)
        )
        # with allowable_children not set (i.e. 1) gets Southern America
        result = [result[0].parent]
        self.assertCountEqual(
            result, consolidate_geographies_by_percent_area(lv4, 33)
        )
        # a combination that ends up in AUSTALIASIA + Paupua New Guinea
        ids = (39, 688, 689, 286, 297, 330, 359, 378, 407, 414, 691)
        geos = self.session.query(Geography).filter(Geography.id.in_(ids))
        result = (
            self.session.query(Geography)
            .filter(Geography.id.in_((691, 5)))
            .all()
        )
        self.assertCountEqual(
            result, consolidate_geographies_by_percent_area(geos, 33, 2)
        )
        # AUSTRALASIA and Lord Howe I. should remove Lord Howe
        ids = (5, 682)
        geos = self.session.query(Geography).filter(Geography.id.in_(ids))
        result = [self.session.get(Geography, 5)]
        self.assertCountEqual(
            result, consolidate_geographies_by_percent_area(geos, 33)
        )
        # Australia and Lord Howe I. should remove Lord Howe
        ids = (38, 682)
        geos = self.session.query(Geography).filter(Geography.id.in_(ids))
        result = [self.session.get(Geography, 38)]
        self.assertCountEqual(
            result, consolidate_geographies_by_percent_area(geos, 33)
        )
        # shouldn't make a difference if allowable_children is set higher
        self.assertCountEqual(
            result, consolidate_geographies_by_percent_area(geos, 33, 4)
        )
        # all Australian islands should not return Australia but consolidate
        # Norfolk Is.
        ids = (726, 694, 682, 683, 378)
        geos = self.session.query(Geography).filter(Geography.id.in_(ids))
        res_ids = (726, 694, 286, 378)
        result = self.session.query(Geography).filter(
            Geography.id.in_(res_ids)
        )
        self.assertCountEqual(
            result, consolidate_geographies_by_percent_area(geos, 33)
        )

    def test_distribution_map(self):
        geo = (
            self.session.query(Geography)
            .filter(Geography.code == "NFK-LH")
            .one()
        )
        self.assertEqual(geo.get_geography_ids(), [geo.id])

    def test_top_level_count(self):
        # check we get the plural name
        self.assertEqual(Geography.top_level_count([1, 2]), "Geographies: 2")


class GeographyTests2(TestCase):
    """Tests not requiring setup_geographies()"""

    def test_as_svg_paths_polygon(self):
        geojson = {
            "type": "Polygon",
            "coordinates": [
                [
                    [159.07080078125, -31.599998474121094],
                    [159.08578491210938, -31.561111450195312],
                    [159.04913330078125, -31.52166748046875],
                    [159.10189819335938, -31.57111358642578],
                    [159.07080078125, -31.599998474121094],
                ]
            ],
        }
        geo = Geography(
            name="Lord Howe I.",
            code="NFK-LH",
            level=4,
            geojson=geojson,
        )
        self.assertEqual(
            geo.as_svg_paths(),
            '<path stroke="green" stroke-width="0.2" fill="green" d='
            '"M 159.071 -31.6 L 159.086 -31.561 L 159.049 -31.522 L '
            '159.102 -31.571 Z"'
            "/>",
        )

    def test_as_svg_paths_pacific_centric(self):
        geojson = {
            "type": "Polygon",
            "coordinates": [
                [
                    [-115.7504425, 24.9516697],
                    [-115.7500534, 24.9512501],
                    [-115.7487793, 24.9524994],
                    [-115.7500305, 24.9537201],
                    [-115.7504196, 24.9533291],
                    [-115.7504501, 24.9516697],
                    [-115.7504425, 24.9516697],
                ]
            ],
        }
        geo = Geography(
            name="Rocas Alijos",
            code="MXI-RA",
            level=4,
            geojson=geojson,
        )

        # not pacific centric
        self.assertEqual(
            geo.as_svg_paths(),
            '<path stroke="green" stroke-width="0.2" fill="green" d='
            '"M -115.75 24.952 L -115.75 24.951 L -115.749 24.952 L '
            '-115.75 24.954 L -115.75 24.953 L -115.75 24.952 Z"/>',
        )
        # pacific centric (returns both)
        self.assertEqual(
            geo.as_svg_paths(pacific_centric=True),
            '<path stroke="green" stroke-width="0.2" fill="green" d='
            '"M -115.75 24.952 L -115.75 24.951 L -115.749 24.952 L '
            '-115.75 24.954 L -115.75 24.953 L -115.75 24.952 Z"/>'
            '<path stroke="green" stroke-width="0.2" fill="green" d='
            '"M 244.25 24.952 L 244.25 24.951 L 244.251 24.952 L '
            '244.25 24.954 L 244.25 24.953 L 244.25 24.952 Z"/>',
        )

    def test_as_svg_paths_multi_polygon(self):
        geojson = {
            "type": "MultiPolygon",
            "coordinates": [
                [
                    [
                        [159.07080078125, -31.599998474121094],
                        [159.08578491210938, -31.561111450195312],
                        [159.04913330078125, -31.52166748046875],
                        [159.10189819335938, -31.57111358642578],
                        [159.07080078125, -31.599998474121094],
                    ],
                    [
                        [139.07080078125, -21.599998474121094],
                        [139.08578491210938, -21.561111450195312],
                        [139.04913330078125, -21.52166748046875],
                        [139.10189819335938, -21.57111358642578],
                        [139.07080078125, -21.599998474121094],
                    ],
                ]
            ],
        }
        geo = Geography(
            name="Lord Howe I.",
            code="NFK-LH",
            level=4,
            geojson=geojson,
        )
        self.assertEqual(
            geo.as_svg_paths(),
            '<path stroke="green" stroke-width="0.2" fill="green" d="M '
            "159.071 -31.6 L 159.086 -31.561 L 159.049 -31.522 L 159.102 "
            '-31.571 Z"/><path stroke="green" stroke-width="0.2" fill="green" '
            'd="M 139.071 -21.6 L 139.086 -21.561 L 139.049 -21.522 L 139.102 '
            '-21.571 Z"/>',
        )

    def test_coord_string(self):
        self.assertEqual(
            _coord_string(10.0011, 20.0011111, False), "10.001 20.001"
        )
        self.assertEqual(
            _coord_string(-10.0011, 20.0011111, True), "349.999 20.001"
        )

    def test_path_string(self):
        path = [[10.01, 20.01], [12.01, 21.01], [13.10, 22.10], [10.01, 20.01]]
        res = (
            '<path stroke="blue" stroke-width="0.2" fill="blue" '
            'd="M 10.01 20.01 L 12.01 21.01 L 13.1 22.1 Z"/>'
        )
        self.assertEqual(
            _path_string(path, fill="blue", pacific_centric=False), res
        )


class GeographyApproxAreaTests(BaubleTestCase):
    def test_approx_area_is_set_at_insert(self):
        # test listens_for insert
        geojson = {
            "type": "Polygon",
            "coordinates": [
                [
                    [159.07080078125, -31.599998474121094],
                    [159.08578491210938, -31.561111450195312],
                    [159.04913330078125, -31.52166748046875],
                    [159.10189819335938, -31.57111358642578],
                    [159.07080078125, -31.599998474121094],
                ]
            ],
        }
        geo = Geography(
            name="Lord Howe I.",
            code="NFK-LH",
            level=4,
            geojson=geojson,
        )
        self.session.add(geo)
        self.session.commit()
        self.assertGreater(geo.approx_area, 5)
        self.assertEqual(geo.approx_area, geo.get_approx_area())
        hist_query = (
            self.session.query(db.History.values)
            .filter(db.History.table_name == "geography")
            .filter(db.History.table_id == geo.id)
            .all()
        )
        self.assertEqual(len(hist_query), 1)

    def test_approx_area_is_set_at_update(self):
        # test listens_for update
        geojson = {
            "type": "Polygon",
            "coordinates": [
                [
                    [159.07080078125, -31.599998474121094],
                    [159.08578491210938, -31.561111450195312],
                    [159.04913330078125, -31.52166748046875],
                    [159.10189819335938, -31.57111358642578],
                    [159.07080078125, -31.599998474121094],
                ]
            ],
        }
        geo = Geography(
            name="Lord Howe I.",
            code="NFK-LH",
            level=4,
            geojson=None,
        )
        self.session.add(geo)
        self.session.commit()
        self.assertEqual(geo.approx_area, 0.0)
        geo.geojson = geojson
        self.session.commit()
        self.assertGreater(geo.approx_area, 5)
        self.assertEqual(geo.approx_area, geo.get_approx_area())
        hist_query = (
            self.session.query(db.History.values)
            .filter(db.History.table_name == "geography")
            .filter(db.History.table_id == geo.id)
        )
        self.assertEqual(len(hist_query.all()), 2)
        geo.geojson = None
        self.session.commit()
        self.assertEqual(geo.approx_area, 0.0)
        self.assertEqual(len(hist_query.all()), 3)

    def test_get_approx_area_handles_holes(self):
        geojson = {
            "type": "Polygon",
            "coordinates": [
                [
                    [10.0, 10.0],
                    [0.0, 10.0],
                    [0.0, 0.0],
                    [10.0, 0.0],
                    [10.0, 10.0],
                ],
            ],
        }
        geo = Geography(
            name="Lord Howe I.",
            code="NFK-LH",
            level=4,
            geojson=geojson,
        )
        self.assertAlmostEqual(geo.get_approx_area(), 1227877.0, delta=1)
        # single hole
        geojson = {
            "type": "Polygon",
            "coordinates": [
                [
                    [10.0, 10.0],
                    [0.0, 10.0],
                    [0.0, 0.0],
                    [10.0, 0.0],
                    [10.0, 10.0],
                ],
                [  # hole 1
                    [5.0, 5.0],
                    [5.0, 1.0],
                    [1.0, 1.0],
                    [1.0, 5.0],
                    [5.0, 5.0],
                ],
            ],
        }
        geo = Geography(
            name="Lord Howe I.",
            code="NFK-LH",
            level=4,
            geojson=geojson,
        )
        self.assertAlmostEqual(geo.get_approx_area(), 1031153.0, delta=1)
        # multiple holes
        geojson = {
            "type": "Polygon",
            "coordinates": [
                [
                    [10.0, 10.0],
                    [0.0, 10.0],
                    [0.0, 0.0],
                    [10.0, 0.0],
                    [10.0, 10.0],
                ],
                [  # hole 1
                    [5.0, 5.0],
                    [5.0, 1.0],
                    [1.0, 1.0],
                    [1.0, 5.0],
                    [5.0, 5.0],
                ],
                [  # hole 2
                    [9.0, 9.0],
                    [9.0, 6.0],
                    [6.0, 6.0],
                    [6.0, 9.0],
                    [9.0, 9.0],
                ],
            ],
        }
        geo = Geography(
            name="Lord Howe I.",
            code="NFK-LH",
            level=4,
            geojson=geojson,
        )
        self.assertAlmostEqual(geo.get_approx_area(), 921283.0, delta=1)


class RetrieveTests(BaubleTestCase):
    def test_geography_retreives(self):
        setup_geographies()
        keys = {
            "code": "50",
        }
        geo = Geography.retrieve(self.session, keys)
        self.assertEqual(geo.name, "Australia")

        # test id only
        keys = {"id": 4}
        geo = Geography.retrieve(self.session, keys)
        self.assertEqual(geo.id, 4)

        # test non-existent
        keys = {"epithet": "Nonexistent"}
        geo = Geography.retrieve(self.session, keys)
        self.assertIsNone(geo)

        # test wrong keys
        keys = {
            "accession.code": "2001.1",
        }
        geo = Geography.retrieve(self.session, keys)
        self.assertIsNone(geo)
