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
from unittest import mock, TestCase

from bauble.test import BaubleTestCase
from bauble.utils.geo import transform, ProjDB, prj_crs, KMLMapCallbackFunctor
from bauble import db

# test data - avoiding tuples as they end up lists in the database anyway
epsg3857_point = {'type': 'Point',
                  'coordinates': [17029543.308700003, -3183278.8702000007]}
epsg3857_line = {'type': 'LineString',
                 'coordinates': [[17029384.466049697, -3183246.159990889],
                                 [17029411.0810928, -3183232.853872207]]}
epsg3857_poly = {
    'type': 'Polygon',
    'coordinates': [[[17029038.7838, -3183264.1862999983],
                     [17029058.1867, -3183303.8123999983],
                     [17029035.357, -3183287.9422000013],
                     [17029038.7838, -3183264.1862999983]]]
}

epsg4326_point = {'type': 'Point',
                  'coordinates': [-27.477676044133204, 152.97899035780537]}
epsg4326_point_xy = {'type': 'Point',
                     'coordinates': [152.97899035780537, -27.477676044133204]}
epsg4326_line = {'type': 'LineString',
                 'coordinates': [[-27.477415350999937, 152.97756344999996],
                                 [-27.477309303999977, 152.97780253700006]]}
epsg4326_line_xy = {'type': 'LineString',
                    'coordinates': [[152.97756344999996, -27.477415350999937],
                                    [152.97780253700006, -27.477309303999977]]}
epsg4326_poly = {
    'type': 'Polygon',
    'coordinates': [[[-27.477559016773604, 152.97445813351644],
                     [-27.477874827537065, 152.97463243273273],
                     [-27.477748345857805, 152.9744273500483],
                     [-27.477559016773604, 152.97445813351644]]]
}
epsg4326_poly_xy = {
    'type': 'Polygon',
    'coordinates': [[[152.97445813351644, -27.477559016773604],
                     [152.97463243273273, -27.477874827537065],
                     [152.9744273500483, -27.477748345857805],
                     [152.97445813351644, -27.477559016773604]]]
}
epsg4326_multipoly = {
    'type': 'MultiPolygon',
    'coordinates': [
        [[
            [17028908.311800003, -3183185.5018000007],
            [17028908.303000003, -3183185.569699999],
            [17028907.5362, -3183185.664900001],
            [17028908.311800003, -3183185.5018000007]
        ]],
        [[
            [17028982.7514, -3183316.0643000007],
            [17028919.9353, -3183259.421599999],
            [17028908.1211, -3183209.726500001],
            [17028982.7514, -3183316.0643000007]]]
    ]}

proj_db_data = [('PROJCS["test1"]', 'test:1', True),
                ('PROJCS["test2"]', 'test:2', False),
                ('PROJCS["test3"]', 'test:3', False)]


class TestProjDBDefaults(BaubleTestCase):
    def test_defualts_added_on_db_creation(self):
        proj_db = ProjDB()
        from pathlib import Path
        from bauble.paths import lib_dir
        from ast import literal_eval
        prj_crs_csv = Path(lib_dir(), 'utils', 'prj_crs.csv')
        with prj_crs_csv.open(encoding='utf-8') as f:
            import csv
            reader = csv.DictReader(f)
            for line in reader:
                self.assertEqual(line.get('proj_crs'),
                                 proj_db.get_crs(line.get('prj_text')))
                self.assertEqual(literal_eval(line.get('always_xy')),
                                 proj_db.get_always_xy(line.get('prj_text')))


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
        self.proj_db.add(prj='PROJCS["test4"]', crs='test:4')
        with self.assertRaises(Exception):
            self.proj_db.add(prj='PROJCS["test4"]', crs='test:5')

    def test_cant_add_null_crs_or_prj(self):
        with self.assertRaises(Exception):
            self.proj_db.add(prj='PROJCS["test6"]', crs=None)
        with self.assertRaises(Exception):
            self.proj_db.add(prj=None, crs='test:6')

    def test_cant_add_too_short_crs_or_prj(self):
        with self.assertRaises(Exception):
            self.proj_db.add(prj='PROJCS["test6"]', crs='tst')
        with self.assertRaises(Exception):
            self.proj_db.add(prj='PROJCS[]', crs='test:6')

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
        self.assertIsNone(self.proj_db.get_prj('test:XYZ'))

    def test_set_crs(self):
        # set it and check it's set then set it back
        new_crs = 'test:XYZ'
        self.proj_db.set_crs(prj=proj_db_data[0][0], crs=new_crs)
        self.assertEqual(self.proj_db.get_crs(proj_db_data[0][0]), new_crs)
        self.proj_db.set_crs(prj=proj_db_data[0][0], crs=proj_db_data[0][1])
        self.assertEqual(
            self.proj_db.get_crs(proj_db_data[0][0]), proj_db_data[0][1])

    def test_set_always_xy(self):
        # set it and check it's set then set it back
        new_axy = False
        self.proj_db.set_always_xy(prj=proj_db_data[0][0], axy=new_axy)
        self.assertEqual(
            self.proj_db.get_always_xy(proj_db_data[0][0]), new_axy)
        self.proj_db.set_always_xy(
            prj=proj_db_data[0][0], axy=proj_db_data[0][2])
        self.assertEqual(
            self.proj_db.get_always_xy(proj_db_data[0][0]), proj_db_data[0][2])

    def test_get_valid_prj_when_multiple_crs(self):
        data = [('PROJCS["test5"]', 'test:5', None),
                ('PROJCS["test6"]', 'test:5', None)]
        for i in data:
            self.proj_db.add(prj=i[0], crs=i[1])
        self.assertIn(self.proj_db.get_prj(data[0][1]), [i[0] for i in data])


class GlobalFunctionsTests(BaubleTestCase):

    @mock.patch('bauble.utils.geo.confirm_default')
    def test_transform_raises_error_if_no_sys_crs(self, mock_conf_def):
        from bauble.meta import get_default
        from bauble.error import MetaTableError

        mock_conf_def.return_value = None

        self.assertIsNone(get_default('system_proj_string'))
        data = epsg3857_point
        self.assertRaises(MetaTableError, transform, data)

    def test_transform(self):

        def coord_diff(a, b):
            return [abs(i[0] - i[1]) for i in zip(a, b)]

        def max_diff_point(a, b):
            diff = max(coord_diff(a.get('coordinates'), b.get('coordinates')))
            return diff

        def max_diff_line(a, b):
            diff = max(max(coord_diff(i[0], i[1])) for i in zip(
                a.get('coordinates'), b.get('coordinates')))
            return diff

        def max_diff_poly(a, b):
            diff = max(max(coord_diff(i[0], i[1])) for i in zip(
                a.get('coordinates')[0], b.get('coordinates')[0]))
            return diff

        # epsg:3857 point
        data = epsg3857_point
        # same projection
        out = transform(data, in_crs='epsg:3857', out_crs='epsg:3857')
        self.assertEqual(out, data)
        # same projection without supplying in param
        out = transform(data, out_crs='epsg:3857')
        self.assertEqual(out, data)
        # same projection always_xy - makes no difference
        out = transform(data, in_crs='epsg:3857', out_crs='epsg:3857',
                        always_xy=True)
        self.assertEqual(out, data)
        # projected
        out = transform(data, in_crs='epsg:3857', out_crs='epsg:4326')
        self.assertLess(max_diff_point(out, epsg4326_point), 0.00000001)
        # projected with always_xy
        out = transform(data, in_crs='epsg:3857', out_crs='epsg:4326',
                        always_xy=True)
        self.assertLess(max_diff_point(out, epsg4326_point_xy), 0.00000001)

        # epsg:3857 line
        data = epsg3857_line
        # same projection
        out = transform(data, in_crs='epsg:3857', out_crs='epsg:3857')
        self.assertEqual(out, data)
        # project
        out = transform(data, in_crs='epsg:3857', out_crs='epsg:4326')
        self.assertLess(max_diff_line(out, epsg4326_line), 0.00000001)
        # assert we haven't mutated the original
        self.assertNotEqual(data, out)
        for i, j in zip(data.get('coordinates'), out.get('coordinates')):
            self.assertGreater(abs(i[0] - j[0]), 10)
            self.assertGreater(abs(i[1] - j[1]), 10)
        # projected with always_xy
        out = transform(data, in_crs='epsg:3857', out_crs='epsg:4326',
                        always_xy=True)
        self.assertLess(max_diff_line(out, epsg4326_line_xy), 0.00000001)

        # epsg:3857 polygon
        data = epsg3857_poly
        # same projection
        out = transform(data, in_crs='epsg:3857', out_crs='epsg:3857')
        self.assertEqual(out, data)
        # projected
        out = transform(data, in_crs='epsg:3857', out_crs='epsg:4326')
        self.assertLess(max_diff_poly(out, epsg4326_poly), 0.00000001)
        # projected with always_xy
        out = transform(data, in_crs='epsg:3857', out_crs='epsg:4326',
                        always_xy=True)
        self.assertLess(max_diff_poly(out, epsg4326_poly_xy), 0.00000001)

        # epsg:4326 point
        data = epsg4326_point
        # same projection
        out = transform(data, in_crs='epsg:4326', out_crs='epsg:4326')
        self.assertEqual(out, data)
        # same projectio always_xy - makes no difference
        out = transform(data, in_crs='epsg:4326', out_crs='epsg:4326')
        self.assertEqual(out, data)
        # projected
        out = transform(data, in_crs='epsg:4326', out_crs='epsg:3857')
        self.assertLess(max_diff_point(out, epsg3857_point), 0.00000001)
        # projected with always_xy - should be out of bounds and return None
        out = transform(data, in_crs='epsg:4326', out_crs='epsg:3857',
                        always_xy=True)
        self.assertIsNone(out)

        # epsg:4326 point xy
        data = epsg4326_point_xy
        # projected with always_xy - should work
        out = transform(data, in_crs='epsg:4326', out_crs='epsg:3857',
                        always_xy=True)
        self.assertLess(max_diff_point(out, epsg3857_point), 0.00000001)

        # epsg:4326 line
        data = epsg4326_line
        # projected
        out = transform(data, in_crs='epsg:4326', out_crs='epsg:3857')
        self.assertLess(max_diff_line(out, epsg3857_line), 0.00000001)

        # epsg:4326 unsupported type returns none
        data = epsg4326_multipoly
        out = transform(data, in_crs='epsg:4326', out_crs='epsg:3857')
        self.assertIsNone(out)

        # need to have default out_crs for this to not hang waiting for the
        # dialog to respond
        from bauble.meta import get_default
        from bauble.utils.geo import DEFAULT_SYS_PROJ
        get_default('system_proj_string', DEFAULT_SYS_PROJ)
        # junk data returns none
        self.assertIsNone(transform('hjkl'))


class TestKMLMapCallbackFunctor(TestCase):
    @mock.patch('bauble.utils.message_dialog')
    @mock.patch('bauble.utils.geo.Template')
    def test_fails_single(self, mock_template, mock_dialog):
        call_back = KMLMapCallbackFunctor(None)
        mock_template_instance = mock_template.return_value
        mock_template_instance.render.side_effect = ValueError('test')
        with self.assertLogs(level='DEBUG') as logs:
            call_back([None])
        self.assertIn('None: test', logs.output[0])
        mock_dialog.assert_called()

    @mock.patch('bauble.utils.message_dialog')
    @mock.patch('bauble.utils.geo.Template')
    def test_fails_multiple(self, mock_template, mock_dialog):
        call_back = KMLMapCallbackFunctor(None)
        mock_template_instance = mock_template.return_value
        mock_template_instance.render.side_effect = ValueError('test')
        with self.assertLogs(level='DEBUG') as logs:
            call_back([None, None, None])
        self.assertTrue(all('None: test' in i for i in logs.output))
        mock_dialog.assert_called()

    @mock.patch('bauble.utils.desktop.open')
    @mock.patch('bauble.utils.geo.Template')
    def test_suceeds_single(self, mock_template, mock_open):
        call_back = KMLMapCallbackFunctor(None)
        mock_template_instance = mock_template.return_value
        mock_template_instance.render.return_value = b"test"
        with self.assertNoLogs(level='DEBUG'):
            call_back([None])
        mock_open.assert_called()

    @mock.patch('bauble.utils.desktop.open')
    @mock.patch('bauble.utils.geo.Template')
    def test_suceeds_multiple(self, mock_template, mock_open):
        call_back = KMLMapCallbackFunctor(None)
        mock_template_instance = mock_template.return_value
        mock_template_instance.render.return_value = b"test"
        with self.assertNoLogs(level='DEBUG'):
            call_back([None, None, None])
        mock_open.assert_called()

