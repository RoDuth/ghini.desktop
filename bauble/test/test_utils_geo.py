# pylint: disable=missing-module-docstring
# Copyright (c) 2021-2023 Ross Demuth <rossdemuth123@gmail.com>
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
from unittest import TestCase
from unittest import mock

from bauble import db
from bauble.test import BaubleTestCase
from bauble.utils.geo import KMLMapCallbackFunctor
from bauble.utils.geo import ProjDB
from bauble.utils.geo import is_point_within_poly
from bauble.utils.geo import kml_string_to_geojson
from bauble.utils.geo import polylabel
from bauble.utils.geo import prj_crs
from bauble.utils.geo import transform
from bauble.utils.geo import web_mercator_point_coords_to_geojson

# test data - avoiding tuples as they end up lists in the database anyway
epsg3857_point = {
    "type": "Point",
    "coordinates": [17029543.308700003, -3183278.8702000007],
}
epsg3857_line = {
    "type": "LineString",
    "coordinates": [
        [17029384.466049697, -3183246.159990889],
        [17029411.0810928, -3183232.853872207],
    ],
}
epsg3857_poly = {
    "type": "Polygon",
    "coordinates": [
        [
            [17029038.7838, -3183264.1862999983],
            [17029058.1867, -3183303.8123999983],
            [17029035.357, -3183287.9422000013],
            [17029038.7838, -3183264.1862999983],
        ]
    ],
}

epsg4326_point = {
    "type": "Point",
    "coordinates": [-27.477676044133204, 152.97899035780537],
}
epsg4326_point_xy = {
    "type": "Point",
    "coordinates": [152.97899035780537, -27.477676044133204],
}
epsg4326_line = {
    "type": "LineString",
    "coordinates": [
        [-27.477415350999937, 152.97756344999996],
        [-27.477309303999977, 152.97780253700006],
    ],
}
epsg4326_line_xy = {
    "type": "LineString",
    "coordinates": [
        [152.97756344999996, -27.477415350999937],
        [152.97780253700006, -27.477309303999977],
    ],
}
epsg4326_poly = {
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
epsg4326_poly_xy = {
    "type": "Polygon",
    "coordinates": [
        [
            [152.97445813351644, -27.477559016773604],
            [152.97463243273273, -27.477874827537065],
            [152.9744273500483, -27.477748345857805],
            [152.97445813351644, -27.477559016773604],
        ]
    ],
}
epsg4326_multipoly = {
    "type": "MultiPolygon",
    "coordinates": [
        [
            [
                [17028908.311800003, -3183185.5018000007],
                [17028908.303000003, -3183185.569699999],
                [17028907.5362, -3183185.664900001],
                [17028908.311800003, -3183185.5018000007],
            ]
        ],
        [
            [
                [17028982.7514, -3183316.0643000007],
                [17028919.9353, -3183259.421599999],
                [17028908.1211, -3183209.726500001],
                [17028982.7514, -3183316.0643000007],
            ]
        ],
    ],
}

proj_db_data = [
    ('PROJCS["test1"]', "test:1", True),
    ('PROJCS["test2"]', "test:2", False),
    ('PROJCS["test3"]', "test:3", False),
]


kml_point = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"
 xmlns:gx="http://www.google.com/kml/ext/2.2"
 xmlns:kml="http://www.opengis.net/kml/2.2"
 xmlns:atom="http://www.w3.org/2005/Atom">
<Document>
  <name>KmlFile</name>
  <StyleMap id="m_ylw-pushpin">
    <Pair>
      <key>normal</key>
      <styleUrl>#s_ylw-pushpin</styleUrl>
    </Pair>
    <Pair>
      <key>highlight</key>
      <styleUrl>#s_ylw-pushpin_hl</styleUrl>
    </Pair>
  </StyleMap>
  <Style id="s_ylw-pushpin">
    <IconStyle>
      <scale>1.1</scale>
      <Icon>
        <href>http://maps.google.com/mapfiles/kml/pushpin/ylw-pushpin.png</href>
      </Icon>
      <hotSpot x="20" y="2" xunits="pixels" yunits="pixels"/>
    </IconStyle>
  </Style>
  <Style id="s_ylw-pushpin_hl">
    <IconStyle>
      <scale>1.3</scale>
      <Icon>
        <href>http://maps.google.com/mapfiles/kml/pushpin/ylw-pushpin.png</href>
      </Icon>
      <hotSpot x="20" y="2" xunits="pixels" yunits="pixels"/>
    </IconStyle>
  </Style>
  <Placemark>
    <name>Untitled Placemark</name>
    <LookAt>
      <longitude>152.9742036592858</longitude>
      <latitude>-27.47773096030531</latitude>
      <altitude>0</altitude>
      <heading>-0.0003665758068030529</heading>
      <tilt>0</tilt>
      <range>1335.809291980569</range>
      <gx:altitudeMode>relativeToSeaFloor</gx:altitudeMode>
    </LookAt>
    <styleUrl>#m_ylw-pushpin</styleUrl>
    <Point>
      <gx:drawOrder>1</gx:drawOrder>
      <coordinates>152.9742036592858,-27.47773096030531,0</coordinates>
    </Point>
  </Placemark>
</Document>
</kml>
"""

kml_line = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"
 xmlns:gx="http://www.google.com/kml/ext/2.2"
 xmlns:kml="http://www.opengis.net/kml/2.2"
 xmlns:atom="http://www.w3.org/2005/Atom">
<Document>
  <name>KmlFile</name>
  <StyleMap id="m_ylw-pushpin">
    <Pair>
      <key>normal</key>
      <styleUrl>#s_ylw-pushpin</styleUrl>
    </Pair>
    <Pair>
      <key>highlight</key>
      <styleUrl>#s_ylw-pushpin_hl</styleUrl>
    </Pair>
  </StyleMap>
  <Style id="s_ylw-pushpin">
    <IconStyle>
      <scale>1.1</scale>
      <Icon>
        <href>http://maps.google.com/mapfiles/kml/pushpin/ylw-pushpin.png</href>
      </Icon>
      <hotSpot x="20" y="2" xunits="pixels" yunits="pixels"/>
    </IconStyle>
  </Style>
  <Style id="s_ylw-pushpin_hl">
    <IconStyle>
      <scale>1.3</scale>
      <Icon>
        <href>http://maps.google.com/mapfiles/kml/pushpin/ylw-pushpin.png</href>
      </Icon>
      <hotSpot x="20" y="2" xunits="pixels" yunits="pixels"/>
    </IconStyle>
  </Style>
  <Placemark>
    <name>Untitled Path</name>
    <styleUrl>#m_ylw-pushpin</styleUrl>
    <LineString>
      <tessellate>1</tessellate>
      <coordinates>
152.97410632,-27.4777376524,0 152.974131,-27.477702,0 152.97415,-27.477706,0
      </coordinates>
    </LineString>
  </Placemark>
</Document>
</kml>
"""

kml_poly = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"
 xmlns:gx="http://www.google.com/kml/ext/2.2"
 xmlns:kml="http://www.opengis.net/kml/2.2"
 xmlns:atom="http://www.w3.org/2005/Atom">
<Document>
  <name>KmlFile</name>
  <StyleMap id="m_ylw-pushpin">
    <Pair>
      <key>normal</key>
      <styleUrl>#s_ylw-pushpin</styleUrl>
    </Pair>
    <Pair>
      <key>highlight</key>
      <styleUrl>#s_ylw-pushpin_hl</styleUrl>
    </Pair>
  </StyleMap>
  <Style id="s_ylw-pushpin">
    <IconStyle>
      <scale>1.1</scale>
      <Icon>
        <href>http://maps.google.com/mapfiles/kml/pushpin/ylw-pushpin.png</href>
      </Icon>
      <hotSpot x="20" y="2" xunits="pixels" yunits="pixels"/>
    </IconStyle>
  </Style>
  <Style id="s_ylw-pushpin_hl">
    <IconStyle>
      <scale>1.3</scale>
      <Icon>
        <href>http://maps.google.com/mapfiles/kml/pushpin/ylw-pushpin.png</href>
      </Icon>
      <hotSpot x="20" y="2" xunits="pixels" yunits="pixels"/>
    </IconStyle>
  </Style>
  <Placemark>
    <name>Untitled Polygon</name>
    <styleUrl>#m_ylw-pushpin</styleUrl>
    <Polygon>
      <tessellate>1</tessellate>
      <outerBoundaryIs>
        <LinearRing>
          <coordinates>
152.9739,-27.4776,0 152.9739,-27.4777,0 152.9740,-27.4776,0 152.9739,-27.4776,0 
          </coordinates>
        </LinearRing>
      </outerBoundaryIs>
    </Polygon>
  </Placemark>
</Document>
</kml>

"""


class TestProjDBDefaults(BaubleTestCase):
    def test_defualts_added_on_db_creation(self):
        proj_db = ProjDB()
        from ast import literal_eval
        from pathlib import Path

        from bauble.paths import lib_dir

        prj_crs_csv = Path(lib_dir(), "utils", "prj_crs.csv")
        with prj_crs_csv.open(encoding="utf-8") as f:
            import csv

            reader = csv.DictReader(f)
            for line in reader:
                self.assertEqual(
                    line.get("proj_crs"), proj_db.get_crs(line.get("prj_text"))
                )
                self.assertEqual(
                    literal_eval(line.get("always_xy")),
                    proj_db.get_always_xy(line.get("prj_text")),
                )


class TestProjDB(BaubleTestCase):
    def setUp(self):
        super().setUp()
        # start with blank data (i.e. remove default data added by db.create)
        prj_crs.drop(bind=db.engine)
        prj_crs.create(bind=db.engine)
        self.proj_db = ProjDB()
        for i in proj_db_data:
            self.proj_db.add(prj=i[0], crs=i[1], axy=i[2])

    def test_add_data(self):
        # test data added in setup has been added
        stmt = prj_crs.select()
        with db.engine.begin() as conn:
            result = conn.execute(stmt).all()
        self.assertEqual(list(result), proj_db_data)

    def test_cant_add_prj_entry_twice(self):
        self.proj_db.add(prj='PROJCS["test4"]', crs="test:4")
        with self.assertRaises(Exception):
            self.proj_db.add(prj='PROJCS["test4"]', crs="test:5")

    def test_cant_add_null_crs_or_prj(self):
        with self.assertRaises(Exception):
            self.proj_db.add(prj='PROJCS["test6"]', crs=None)
        with self.assertRaises(Exception):
            self.proj_db.add(prj=None, crs="test:6")

    def test_cant_add_too_short_crs_or_prj(self):
        with self.assertRaises(Exception):
            self.proj_db.add(prj='PROJCS["test6"]', crs="tst")
        with self.assertRaises(Exception):
            self.proj_db.add(prj="PROJCS[]", crs="test:6")

    def test_get_crs(self):
        result = self.proj_db.get_crs(proj_db_data[0][0])
        self.assertEqual(result, proj_db_data[0][1])
        result = self.proj_db.get_crs(proj_db_data[1][0])
        self.assertEqual(result, proj_db_data[1][1])
        result = self.proj_db.get_crs(None)
        self.assertEqual(result, None)

    def test_get_always_xy(self):
        result = self.proj_db.get_always_xy(proj_db_data[0][0])
        self.assertEqual(result, proj_db_data[0][2])
        result = self.proj_db.get_always_xy(proj_db_data[1][0])
        self.assertEqual(result, proj_db_data[1][2])
        result = self.proj_db.get_always_xy(None)
        self.assertEqual(result, proj_db_data[0][2])

    def test_get_unknown_crs_returns_none(self):
        self.assertIsNone(self.proj_db.get_crs('PROJCS["testXYZ"]'))

    def test_get_prj(self):
        result = self.proj_db.get_prj(proj_db_data[0][1])
        self.assertEqual(result, proj_db_data[0][0])
        result = self.proj_db.get_prj(proj_db_data[1][1])
        self.assertEqual(result, proj_db_data[1][0])

    def test_get_unknown_prj_returns_none(self):
        self.assertIsNone(self.proj_db.get_prj("test:XYZ"))

    def test_set_crs(self):
        # set it and check it's set then set it back
        new_crs = "test:XYZ"
        self.proj_db.set_crs(prj=proj_db_data[0][0], crs=new_crs)
        self.assertEqual(self.proj_db.get_crs(proj_db_data[0][0]), new_crs)
        self.proj_db.set_crs(prj=proj_db_data[0][0], crs=proj_db_data[0][1])
        self.assertEqual(
            self.proj_db.get_crs(proj_db_data[0][0]), proj_db_data[0][1]
        )

    def test_set_always_xy(self):
        # set it and check it's set then set it back
        new_axy = False
        self.proj_db.set_always_xy(prj=proj_db_data[0][0], axy=new_axy)
        self.assertEqual(
            self.proj_db.get_always_xy(proj_db_data[0][0]), new_axy
        )
        self.proj_db.set_always_xy(
            prj=proj_db_data[0][0], axy=proj_db_data[0][2]
        )
        self.assertEqual(
            self.proj_db.get_always_xy(proj_db_data[0][0]), proj_db_data[0][2]
        )

    def test_get_valid_prj_when_multiple_crs(self):
        data = [
            ('PROJCS["test5"]', "test:5", None),
            ('PROJCS["test6"]', "test:5", None),
        ]
        for i in data:
            self.proj_db.add(prj=i[0], crs=i[1])
        self.assertIn(self.proj_db.get_prj(data[0][1]), [i[0] for i in data])


class GlobalFunctionsTests(BaubleTestCase):
    @mock.patch("bauble.utils.geo.confirm_default")
    def test_transform_raises_error_if_no_sys_crs(self, mock_conf_def):
        from bauble.error import MetaTableError
        from bauble.meta import get_default

        mock_conf_def.return_value = None

        self.assertIsNone(get_default("system_proj_string"))
        data = epsg3857_point
        self.assertRaises(MetaTableError, transform, data)

    def test_transform(self):
        def coord_diff(a, b):
            return [abs(i[0] - i[1]) for i in zip(a, b)]

        def max_diff_point(a, b):
            diff = max(coord_diff(a.get("coordinates"), b.get("coordinates")))
            return diff

        def max_diff_line(a, b):
            diff = max(
                max(coord_diff(i[0], i[1]))
                for i in zip(a.get("coordinates"), b.get("coordinates"))
            )
            return diff

        def max_diff_poly(a, b):
            diff = max(
                max(coord_diff(i[0], i[1]))
                for i in zip(a.get("coordinates")[0], b.get("coordinates")[0])
            )
            return diff

        # epsg:3857 point
        data = epsg3857_point
        # same projection
        out = transform(data, in_crs="epsg:3857", out_crs="epsg:3857")
        self.assertEqual(out, data)
        # same projection without supplying in param
        out = transform(data, out_crs="epsg:3857")
        self.assertEqual(out, data)
        # same projection always_xy - makes no difference
        out = transform(
            data, in_crs="epsg:3857", out_crs="epsg:3857", always_xy=True
        )
        self.assertEqual(out, data)
        # projected
        out = transform(data, in_crs="epsg:3857", out_crs="epsg:4326")
        self.assertLess(max_diff_point(out, epsg4326_point), 0.00000001)
        # projected with always_xy
        out = transform(
            data, in_crs="epsg:3857", out_crs="epsg:4326", always_xy=True
        )
        self.assertLess(max_diff_point(out, epsg4326_point_xy), 0.00000001)

        # epsg:3857 line
        data = epsg3857_line
        # same projection
        out = transform(data, in_crs="epsg:3857", out_crs="epsg:3857")
        self.assertEqual(out, data)
        # project
        out = transform(data, in_crs="epsg:3857", out_crs="epsg:4326")
        self.assertLess(max_diff_line(out, epsg4326_line), 0.00000001)
        # assert we haven't mutated the original
        self.assertNotEqual(data, out)
        for i, j in zip(data.get("coordinates"), out.get("coordinates")):
            self.assertGreater(abs(i[0] - j[0]), 10)
            self.assertGreater(abs(i[1] - j[1]), 10)
        # projected with always_xy
        out = transform(
            data, in_crs="epsg:3857", out_crs="epsg:4326", always_xy=True
        )
        self.assertLess(max_diff_line(out, epsg4326_line_xy), 0.00000001)

        # epsg:3857 polygon
        data = epsg3857_poly
        # same projection
        out = transform(data, in_crs="epsg:3857", out_crs="epsg:3857")
        self.assertEqual(out, data)
        # projected
        out = transform(data, in_crs="epsg:3857", out_crs="epsg:4326")
        self.assertLess(max_diff_poly(out, epsg4326_poly), 0.00000001)
        # projected with always_xy
        out = transform(
            data, in_crs="epsg:3857", out_crs="epsg:4326", always_xy=True
        )
        self.assertLess(max_diff_poly(out, epsg4326_poly_xy), 0.00000001)

        # epsg:4326 point
        data = epsg4326_point
        # same projection
        out = transform(data, in_crs="epsg:4326", out_crs="epsg:4326")
        self.assertEqual(out, data)
        # same projectio always_xy - makes no difference
        out = transform(data, in_crs="epsg:4326", out_crs="epsg:4326")
        self.assertEqual(out, data)
        # projected
        out = transform(data, in_crs="epsg:4326", out_crs="epsg:3857")
        self.assertLess(max_diff_point(out, epsg3857_point), 0.00000001)
        # projected with always_xy - should be out of bounds and return None
        out = transform(
            data, in_crs="epsg:4326", out_crs="epsg:3857", always_xy=True
        )
        self.assertIsNone(out)

        # epsg:4326 point xy
        data = epsg4326_point_xy
        # projected with always_xy - should work
        out = transform(
            data, in_crs="epsg:4326", out_crs="epsg:3857", always_xy=True
        )
        self.assertLess(max_diff_point(out, epsg3857_point), 0.00000001)

        # epsg:4326 line
        data = epsg4326_line
        # projected
        out = transform(data, in_crs="epsg:4326", out_crs="epsg:3857")
        self.assertLess(max_diff_line(out, epsg3857_line), 0.00000001)

        # epsg:4326 unsupported type returns none
        data = epsg4326_multipoly
        out = transform(data, in_crs="epsg:4326", out_crs="epsg:3857")
        self.assertIsNone(out)

        # need to have default out_crs for this to not hang waiting for the
        # dialog to respond
        from bauble.meta import get_default
        from bauble.utils.geo import DEFAULT_SYS_PROJ

        get_default("system_proj_string", DEFAULT_SYS_PROJ)
        # junk data returns none
        self.assertIsNone(transform("hjkl"))

    def test_kml_string_to_geojson_point(self):
        self.assertEqual(
            kml_string_to_geojson(kml_point),
            '{"type": "Point", "coordinates": [152.9742036592858, '
            "-27.47773096030531]}",
        )

    def test_kml_string_to_geojson_line(self):
        self.assertEqual(
            kml_string_to_geojson(kml_line),
            '{"type": "LineString", "coordinates": [[152.97410632, '
            "-27.4777376524], [152.974131, -27.477702], "
            "[152.97415, -27.477706]]}",
        )

    def test_kml_string_to_geojson_poly(self):
        self.assertEqual(
            kml_string_to_geojson(kml_poly),
            '{"type": "Polygon", "coordinates": [[[152.9739, -27.4776], '
            "[152.9739, -27.4777], [152.9740, -27.4776], "
            "[152.9739, -27.4776]]]}",
        )

    def test_kml_string_to_geojson_junk_returns_string(self):
        junk_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<kml xmlns="http://www.opengis.net/kml/2.2" '
            ' xmlns:gx="http://www.google.com/kml/ext/2.2" '
            ' xmlns:kml="http://www.opengis.net/kml/2.2" '
            ' xmlns:atom="http://www.w3.org/2005/Atom"> '
            "<junk>data</junk>"
            "</kml>"
        )
        self.assertEqual(kml_string_to_geojson(junk_xml), junk_xml)

        self.assertEqual(kml_string_to_geojson("JUNK"), "JUNK")

    def test_web_mercator_point_coords_to_geojson(self):
        self.assertEqual(
            web_mercator_point_coords_to_geojson(
                "-27.47677001137734, 152.97467501385253"
            ),
            '{"type": "Point", "coordinates": [152.97467501385253, '
            "-27.47677001137734]}",
        )

    def test_is_point_within_poly_sqr(self):
        long = -27.0
        lat = 152.0
        poly = [
            [-26.0, 151.0],
            [-28.0, 151.0],
            [-28.0, 153.0],
            [-26.0, 153.0],
            [-26.0, 151.0],
        ]
        self.assertTrue(is_point_within_poly(long, lat, poly))
        # outside 2 intersects - False
        long = -29.0
        lat = 152.0
        poly = [
            [-26.0, 151.0],
            [-28.0, 151.0],
            [-28.0, 153.0],
            [-26.0, 153.0],
            [-26.0, 151.0],
        ]
        self.assertFalse(is_point_within_poly(long, lat, poly))
        # outside, no intersects
        long = -25.0
        lat = 152.0
        poly = [
            [-26.0, 151.0],
            [-28.0, 151.0],
            [-28.0, 153.0],
            [-26.0, 153.0],
            [-26.0, 151.0],
        ]
        self.assertFalse(is_point_within_poly(long, lat, poly))

    def test_is_point_within_poly_concave_polygon(self):
        # 1 intersects
        long = -27.5
        lat = 151.49
        poly = [
            [-26.0, 151.0],
            [-28.0, 151.0],
            [-27.0, 152.0],
            [-28.0, 153.0],
            [-26.0, 153.0],
            [-26.0, 151.0],
        ]
        self.assertTrue(is_point_within_poly(long, lat, poly))
        # 3 intersects
        long = -27.5
        lat = 151.51
        poly = [
            [-26.0, 151.0],
            [-27.0, 152.0],
            [-28.0, 151.0],
            [-28.0, 153.0],
            [-26.0, 153.0],
            [-26.0, 151.0],
        ]
        self.assertTrue(is_point_within_poly(long, lat, poly))
        # 2 intersects False
        long = -27.5
        lat = 151.49
        poly = [
            [-26.0, 151.0],
            [-27.0, 152.0],
            [-28.0, 151.0],
            [-28.0, 153.0],
            [-26.0, 153.0],
            [-26.0, 151.0],
        ]
        self.assertFalse(is_point_within_poly(long, lat, poly))

    def test_is_point_within_poly_northern_lat(self):
        # 1 intersects
        long = 27.5
        lat = 151.49
        poly = [
            [26.0, 151.0],
            [28.0, 151.0],
            [27.0, 152.0],
            [28.0, 153.0],
            [26.0, 153.0],
            [26.0, 151.0],
        ]
        self.assertTrue(is_point_within_poly(long, lat, poly))
        # 3 intersects
        long = 27.5
        lat = 151.51
        poly = [
            [26.0, 151.0],
            [27.0, 152.0],
            [28.0, 151.0],
            [28.0, 153.0],
            [26.0, 153.0],
            [26.0, 151.0],
        ]
        self.assertTrue(is_point_within_poly(long, lat, poly))
        # 2 intersects False
        long = 27.5
        lat = 151.49
        poly = [
            [26.0, 151.0],
            [27.0, 152.0],
            [28.0, 151.0],
            [28.0, 153.0],
            [26.0, 153.0],
            [26.0, 151.0],
        ]
        self.assertFalse(is_point_within_poly(long, lat, poly))

    def test_is_point_within_poly_stradling_lat(self):
        # should all reach angle calc
        # 1 intersects
        long = 0.5
        lat = 151.49
        poly = [
            [-1.0, 151.0],
            [1.0, 151.0],
            [0.0, 152.0],
            [1.0, 153.0],
            [-1.0, 153.0],
            [-1.0, 151.0],
        ]
        self.assertTrue(is_point_within_poly(long, lat, poly))
        # 3 intersects
        long = 0.5
        lat = 151.51
        poly = [
            [-1.0, 151.0],
            [0.0, 152.0],
            [1.0, 151.0],
            [1.0, 153.0],
            [-1.0, 153.0],
            [-1.0, 151.0],
        ]
        self.assertTrue(is_point_within_poly(long, lat, poly))
        # 2 intersects False
        long = 0.5
        lat = 151.49
        poly = [
            [-1.0, 151.0],
            [0.0, 152.0],
            [1.0, 151.0],
            [1.0, 153.0],
            [-1.0, 153.0],
            [-1.0, 151.0],
        ]
        self.assertFalse(is_point_within_poly(long, lat, poly))

    def test_is_point_within_poly_western_long(self):
        # 1 intersects
        long = 27.5
        lat = -151.49
        poly = [
            [26.0, -151.0],
            [28.0, -151.0],
            [27.0, -152.0],
            [28.0, -153.0],
            [26.0, -153.0],
            [26.0, -151.0],
        ]
        self.assertTrue(is_point_within_poly(long, lat, poly))
        # 3 intersects
        long = 27.5
        lat = -151.51
        poly = [
            [26.0, -151.0],
            [27.0, -152.0],
            [28.0, -151.0],
            [28.0, -153.0],
            [26.0, -153.0],
            [26.0, -151.0],
        ]
        self.assertTrue(is_point_within_poly(long, lat, poly))
        # 2 intersects False
        long = 27.5
        lat = -151.49
        poly = [
            [26.0, -151.0],
            [27.0, -152.0],
            [28.0, -151.0],
            [28.0, -153.0],
            [26.0, -153.0],
            [26.0, -151.0],
        ]
        self.assertFalse(is_point_within_poly(long, lat, poly))

    def test_is_point_within_poly_stradling_0_long(self):
        # 1 intersects
        long = 0.5
        lat = -151.49
        poly = [
            [-1.0, -151.0],
            [1.0, -151.0],
            [0.0, -152.0],
            [1.0, -153.0],
            [-1.0, -153.0],
            [-1.0, -151.0],
        ]
        self.assertTrue(is_point_within_poly(long, lat, poly))
        # 3 intersects
        long = 0.5
        lat = -151.51
        poly = [
            [-1.0, -151.0],
            [0.0, -152.0],
            [1.0, -151.0],
            [1.0, -153.0],
            [-1.0, -153.0],
            [-1.0, -151.0],
        ]
        self.assertTrue(is_point_within_poly(long, lat, poly))
        # 2 intersects False
        long = 0.5
        lat = -151.49
        poly = [
            [-1.0, -151.0],
            [0.0, -152.0],
            [1.0, -151.0],
            [1.0, -153.0],
            [-1.0, -153.0],
            [-1.0, -151.0],
        ]
        self.assertFalse(is_point_within_poly(long, lat, poly))

    def test_is_point_within_poly_stradling_0_long_stradling_lat(self):
        # 1 intersects
        long = 0.5
        lat = -0.51
        poly = [
            [-1.0, -1.0],
            [1.0, -1.0],
            [0.0, 0.0],
            [1.0, 1.0],
            [-1.0, 1.0],
            [-1.0, -1.0],
        ]
        self.assertTrue(is_point_within_poly(long, lat, poly))
        # 3 intersects
        long = 0.5
        lat = -0.49
        poly = [
            [-1.0, -1.0],
            [0.0, 0.0],
            [1.0, -1.0],
            [1.0, 1.0],
            [-1.0, 1.0],
            [-1.0, -1.0],
        ]
        self.assertTrue(is_point_within_poly(long, lat, poly))
        # 2 intersects False
        long = 0.5
        lat = -0.51
        poly = [
            [-1.0, -1.0],
            [0.0, 0.0],
            [1.0, -1.0],
            [1.0, 1.0],
            [-1.0, 1.0],
            [-1.0, -1.0],
        ]
        self.assertFalse(is_point_within_poly(long, lat, poly))

    def test_is_point_within_poly_multipolygon(self):
        # 1 intersects
        long = 0.5
        lat = 0.5
        poly = [
            [
                [0.0, 0.0],
                [0.0, 1.0],
                [1.0, 1.0],
                [1.0, 0.0],
                [0.0, 0.0],
            ],
            [
                [2.0, 2.0],
                [2.0, 3.0],
                [3.0, 3.0],
                [3.0, 2.0],
                [2.0, 2.0],
            ],
        ]
        self.assertTrue(is_point_within_poly(long, lat, poly))
        # 3 intersects
        long = 0.5
        lat = 0.5
        poly = [
            [
                [0.0, 0.0],
                [0.0, 1.0],
                [1.0, 1.0],
                [1.0, 0.0],
                [0.0, 0.0],
            ],
            [
                [2.0, 0.0],
                [2.0, 1.0],
                [3.0, 1.0],
                [3.0, 0.0],
                [2.0, 0.0],
            ],
        ]
        self.assertTrue(is_point_within_poly(long, lat, poly))
        # 2 intersects False
        long = 2.05
        lat = 0.05
        poly = [
            [
                [0.0, 0.0],
                [0.0, 1.0],
                [1.0, 1.0],
                [1.0, 0.0],
                [0.0, 0.0],
            ],
            [
                [0.0, 2.0],
                [0.0, 3.0],
                [1.0, 3.0],
                [1.0, 2.0],
                [0.0, 2.0],
            ],
        ]
        self.assertFalse(is_point_within_poly(long, lat, poly))

    def test_is_point_within_poly_multipolygon_with_hole(self):
        # 1 intersects
        long = 0.75
        lat = 0.75
        poly = [
            [
                [0.0, 0.0],
                [0.0, 1.0],
                [1.0, 1.0],
                [1.0, 0.0],
                [0.0, 0.0],
            ],
            [
                [0.2, 0.2],
                [0.2, 0.7],
                [0.7, 0.7],
                [0.7, 0.2],
                [0.2, 0.2],
            ],
        ]
        self.assertTrue(is_point_within_poly(long, lat, poly))
        # 3 intersects
        long = 0.05
        lat = 0.5
        poly = [
            [
                [0.0, 0.0],
                [0.0, 1.0],
                [1.0, 1.0],
                [1.0, 0.0],
                [0.0, 0.0],
            ],
            [
                [0.2, 0.2],
                [0.2, 0.7],
                [0.7, 0.7],
                [0.7, 0.2],
                [0.2, 0.2],
            ],
        ]
        self.assertTrue(is_point_within_poly(long, lat, poly))
        # 2 intersects False
        long = 0.5
        lat = 0.5
        poly = [
            [
                [0.0, 0.0],
                [0.0, 1.0],
                [1.0, 1.0],
                [1.0, 0.0],
                [0.0, 0.0],
            ],
            [
                [0.2, 0.2],
                [0.2, 0.7],
                [0.7, 0.7],
                [0.7, 0.2],
                [0.2, 0.2],
            ],
        ]
        self.assertFalse(is_point_within_poly(long, lat, poly))


class TestPolyLabel(TestCase):
    def test_polylabel(self):
        self.assertEqual(
            polylabel([[[100, 0], [105, 0], [110, 10], [100, 1], [100, 0]]]),
            [103.125, 1.875],
        )

    def test_polylabel_degenerate_polygons(self):
        self.assertEqual(polylabel([[[0, 0], [1, 0], [2, 0], [0, 0]]]), [0, 0])
        self.assertEqual(
            polylabel([[[0, 0], [1, 0], [1, 1], [1, 0], [0, 0]]]), [0, 0]
        )

    def test_polylabel_concave_polygon_w_precision(self):
        polygon = [
            [
                [152.9715799870417, -27.479999843402393],
                [152.97165778114527, -27.479980796053578],
                [152.9715987618311, -27.480164017067317],
                [152.97150488788395, -27.480302050270026],
                [152.97133052488726, -27.480428128944915],
                [152.97119371146954, -27.480509020054125],
                [152.97096041899024, -27.48060186544124],
                [152.9709281694715, -27.480611349214584],
                [152.97078336104772, -27.480620912682664],
                [152.97057953330977, -27.480587520236345],
                [152.97041056020484, -27.48051380179273],
                [152.97037561574027, -27.480506628387815],
                [152.97016909305646, -27.480475707269548],
                [152.97004036447623, -27.48038764272321],
                [152.96997865021626, -27.480221079312965],
                [152.96995188042075, -27.480064078370347],
                [152.96989016616075, -27.479954576057583],
                [152.9697882972075, -27.47971190133029],
                [152.96980168210524, -27.479699946896407],
                [152.9698311468466, -27.479745214345854],
                [152.96990094594412, -27.479792792965444],
                [152.970115463634, -27.480033156330883],
                [152.97017448294815, -27.48025439217455],
                [152.97022541742479, -27.480390034392105],
                [152.97029521652232, -27.48043761273319],
                [152.97036762073424, -27.4804542691325],
                [152.9705097342122, -27.480478098139596],
                [152.97073503168542, -27.480520894704554],
                [152.97096302410458, -27.480570863857185],
                [152.97114008204707, -27.48050423831532],
                [152.9713787644181, -27.480366285061724],
                [152.97148611309447, -27.48026634575129],
                [152.9715799870417, -27.479999843402393],
            ]
        ]
        self.assertTrue(
            is_point_within_poly(
                *polylabel(polygon, precision=0.0001), polygon
            )
        )
        self.assertEqual(
            polylabel(polygon, precision=0.0001),
            [152.97007609901567, -27.48021799015118],
        )

    def test_polylabel_holed_polygon(self):
        polygon = [
            [[0, 0], [100, 0], [100, 100], [0, 100], [0, 0]],
            [[10, 10], [10, 90], [80, 90], [60, 10], [10, 10]],
        ]
        self.assertTrue(is_point_within_poly(*polylabel(polygon), polygon))
        self.assertEqual(polylabel(polygon), [81.25, 18.75])


class TestKMLMapCallbackFunctor(TestCase):
    @mock.patch("bauble.gui")
    @mock.patch("bauble.utils.message_dialog")
    @mock.patch("bauble.utils.geo.Template")
    def test_fails_single(self, mock_template, mock_dialog, mock_gui):
        call_back = KMLMapCallbackFunctor(None)
        mock_template_instance = mock_template.return_value
        mock_template_instance.render.side_effect = ValueError("test")
        with self.assertLogs(level="DEBUG") as logs:
            call_back([None])
        self.assertIn("None: test", logs.output[0])
        mock_gui.widgets.statusbar.push.assert_called()
        mock_dialog.assert_called()

    @mock.patch("bauble.utils.message_dialog")
    @mock.patch("bauble.utils.geo.Template")
    def test_fails_multiple(self, mock_template, mock_dialog):
        call_back = KMLMapCallbackFunctor(None)
        mock_template_instance = mock_template.return_value
        mock_template_instance.render.side_effect = ValueError("test")
        with self.assertLogs(level="DEBUG") as logs:
            call_back([None, None, None])
        self.assertTrue(all("None: test" in i for i in logs.output))
        mock_dialog.assert_called()

    @mock.patch("bauble.utils.message_dialog")
    @mock.patch("bauble.utils.desktop.open")
    @mock.patch("bauble.utils.geo.Template")
    def test_open_fails_oserror(self, mock_template, mock_open, mock_dialog):
        call_back = KMLMapCallbackFunctor(None)
        mock_open.side_effect = OSError("test")
        mock_template_instance = mock_template.return_value
        mock_template_instance.render.return_value = b"test"
        with self.assertNoLogs(level="DEBUG"):
            call_back([None])
        mock_open.assert_called()
        mock_dialog.assert_called()
        self.assertTrue(
            mock_dialog.call_args.args[0].startswith(
                "Could not open the kml file"
            )
        )

    @mock.patch("bauble.utils.desktop.open")
    @mock.patch("bauble.utils.geo.Template")
    def test_succeeds_single(self, mock_template, mock_open):
        call_back = KMLMapCallbackFunctor(None)
        mock_template_instance = mock_template.return_value
        mock_template_instance.render.return_value = b"test"
        with self.assertNoLogs(level="DEBUG"):
            call_back([None])
        mock_open.assert_called()

    @mock.patch("bauble.utils.desktop.open")
    @mock.patch("bauble.utils.geo.Template")
    def test_suceeds_multiple(self, mock_template, mock_open):
        call_back = KMLMapCallbackFunctor(None)
        mock_template_instance = mock_template.return_value
        mock_template_instance.render.return_value = b"test"
        with self.assertNoLogs(level="DEBUG"):
            call_back([None, None, None])
        mock_open.assert_called()
