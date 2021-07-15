# pylint: disable=missing-module-docstring,invalid-name,too-many-lines
# pylint: disable=too-many-public-methods,too-many-statements,protected-access
# pylint: disable=unused-argument,no-self-use,protected-access
# Copyright (c) 2021 Ross Demuth <rossdemuth123@gmail.com>
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

from pathlib import Path
from zipfile import ZipFile
from tempfile import TemporaryDirectory
from shapefile import Writer, Reader
from gi.repository import Gtk

from bauble.test import BaubleTestCase
from bauble.meta import get_default
from bauble.utils.geo import DEFAULT_SYS_PROJ
from bauble.plugins.garden import (Plant,
                                   PlantNote,
                                   Location,
                                   LocationNote,
                                   Accession)
from bauble.plugins.plants import Family, Genus
from bauble.plugins.plants.species import (Species, VernacularName,
                                           DefaultVernacularName)
from bauble.utils.geo import transform
from bauble.plugins.imex.shapefile import (ShapefileImportTool,
                                           ShapefileExportTool)
from bauble.plugins.imex.shapefile.import_tool import (ShapefileImporter,
                                                       ShapefileReader,
                                                       add_rec_to_db)
from bauble.plugins.imex.shapefile.export_tool import (ShapefileExporter,
                                                       get_field_properties)

from .import_tool import ShapefileImportSettingsBox as ImpSetBox
from .export_tool import ShapefileExportSettingsBox as ExpSetBox
# test data - avoiding tuples as they end up lists in the database anyway
epsg3857_point = {'type': 'Point',
                  'coordinates': [17029543.308700003, -3183278.8702000007]}
epsg3857_point2 = {'type': 'Point',
                   'coordinates': [17029543.308700999, -3183278.8702000099]}
epsg3857_line = {'type': 'LineString',
                 'coordinates': [[17029384.466049697, -3183246.159990889],
                                 [17029411.0810928, -3183232.853872207]]}
epsg3857_line2 = {'type': 'LineString',
                  'coordinates': [[17029478.511093233, -3183065.1561169717],
                                  [17029474.927718833, -3183065.9045586935],
                                  [17029471.934003755, -3183064.58910809],
                                  [17029470.82270129, -3183062.32119827]]}
epsg3857_poly = {
    'type': 'Polygon',
    'coordinates': [[[17029038.7838, -3183264.1862999983],
                     [17029058.1867, -3183303.8123999983],
                     [17029035.357, -3183287.9422000013],
                     [17029038.7838, -3183264.1862999983]]]
}
epsg3857_poly2 = {
    'type': 'Polygon',
    'coordinates': [[[17028982.7514, -3183316.0643000007],
                     [17028913.3605, -3183241.0999],
                     [17028906.9547, -3183196.0471],
                     [17028908.303000003, -3183185.569699999],
                     [17028961.4045, -3183259.5353000015],
                     [17028982.7514, -3183316.0643000007]]]
}

epsg4326_point_xy = {'type': 'Point',
                     'coordinates': [152.97899035780537, -27.477676044133204]}
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
epsg4326_poly_xy2 = {
    'type': 'Polygon',
    'coordinates': [[[152.9739547859032, -27.47797247213578],
                     [152.97333143684273, -27.477375023139412],
                     [152.97327389256225, -27.47701596114478],
                     [152.97328600454725, -27.476932458150536],
                     [152.9737630234378, -27.477521949330367],
                     [152.9739547859032, -27.47797247213578]]]
}


# database data:
family_data = [{'id': 1, 'family': 'Proteaceae'},
               {'id': 2, 'family': 'Myrtaceae'}]
genus_data = [
    {'id': 1, 'genus': 'Grevillea', 'family_id': 1},
    {'id': 2, 'genus': 'Eucalyptus', 'family_id': 2},
]
species_data = [
    {'id': 1, 'sp': 'robusta', 'genus_id': 1},
    {'id': 2, 'sp': 'major', 'genus_id': 2},
]
vernacular_data = [
    {'id': 1, 'name': 'Mountain Grey Gum', 'species_id': 2}
]
default_vernacular_data = [
    {'id': 1, 'vernacular_name_id': 1, 'species_id': 2}
]
accession_data = [
    {'id': 1, 'code': '2021001', 'species_id': 1},
    {'id': 2, 'code': '2021002', 'species_id': 2, 'private': True},
]
location_data = [
    {'id': 1, 'code': 'QCC01', 'name': 'SE Qld Rainforest'},
    {'id': 2, 'code': 'APC01', 'name': 'Brigalow Belt'},
]
loc_note_data = [
    {'id': 1, 'location_id': 2, 'category': 'field_note', 'note': 'test 1'},
    {'id': 2, 'location_id': 1, 'category': 'field_note', 'note': 'test 2'}
]
plant_data = [
    {'id': 1, 'code': '1', 'accession_id': 1, 'location_id': 1, 'quantity': 2},
    {'id': 2, 'code': '2', 'accession_id': 2, 'location_id': 2, 'quantity': 2}
]
plt_note_data = [
    {'id': 1, 'plant_id': 1, 'category': '<field_note>', 'note': 'test 1'},
    {'id': 2, 'plant_id': 2, 'category': 'field_note', 'note': 'test 2'}
]

# seems to work with epsg:4326 always_xy data
prj_str_4326 = (
    'GEOGCS["GCS_WGS_1984",DATUM["D_WGS_1984",SPHEROID["WGS_1984",6378137,298'
    '.257223563]],PRIMEM["Greenwich",0],UNIT["Degree",0.017453292519943295]]'
)

prj_str_3857 = (
    'PROJCS["WGS_1984_Web_Mercator_Auxiliary_Sphere",GEOGCS["GCS_WGS_1984",'
    'DATUM["D_WGS_1984",SPHEROID["WGS_1984",6378137.0,298.257223563]],PRIMEM'
    '["Greenwich",0.0],UNIT["Degree",0.0174532925199433]],PROJECTION["Mercator'
    '_Auxiliary_Sphere"],PARAMETER["False_Easting",0.0],PARAMETER["False_'
    'Northing",0.0],PARAMETER["Central_Meridian",0.0],PARAMETER["Standard_'
    'Parallel_1",0.0],PARAMETER["Auxiliary_Sphere_Type",0.0],UNIT["Meter",'
    '1.0]]'
)

# shapefile data
location_fields = [('loc_id', 'N'), ('loc_code', 'C', 24), ('name', 'C', 126),
                   ('descript', 'C'), ('field_note', 'C', 255)]

plant_fields = [('plt_id', 'N'), ('accession', 'C', 16), ('plt_code', 'C', 16),
                ('quantity', 'N'), ('bed', 'C', 24), ('field_note', 'C', 255),
                ('family', 'C', 126), ('genus', 'C', 124),
                ('species', 'C', 126), ('infrasp', 'C', 126),
                ('cultivar', 'C', 126), ('vernacular', 'C', 64)]

plant_fields_wrong_types = [
    ('plt_id', 'F', 6), ('accession', 'N'), ('plt_code', 'F', 6),
    ('quantity', 'F', 6), ('bed', 'N', 24), ('field_note', 'C', 255),
    ('family', 'C', 126), ('genus', 'C', 124), ('species', 'C', 126),
    ('infrasp', 'C', 126), ('cultivar', 'C', 126), ('vernacular', 'C', 64)
]

loc_recs_4326 = [
    {'record':
     {'loc_id': 1, 'loc_code': 'QCC01', 'name': 'SE Qld Rainforest',
      'descript': 'Rainforest garden', 'field_note': 'storm damaged area'},
     **epsg4326_poly_xy},
    {'record':
     {'loc_id': 2, 'loc_code': 'APC01', 'name': 'Brigalow Belt',
      'descript': 'Inland plant communities', 'field_note': ''},
     **epsg4326_poly_xy2},
]
loc_recs_4326_bulk = [
    {'record':
     {'loc_id': i, 'loc_code': f'bed{i}', 'name': f'garden bed {i}',
      'descript': '', 'field_note': f'note {i}'}, **epsg4326_poly_xy}
    for i in range(30)
]
loc_recs_4326_2 = [
    {'record':
     {'loc_id': 1, 'loc_code': 'QCC01', 'name': 'SE Qld Rainforest',
      'descript': 'Rainforest garden', 'field_note': 'storm damaged area'},
     **epsg4326_poly_xy2},
    {'record':
     {'loc_id': 2, 'loc_code': 'APC01', 'name': 'Brigalow Belt',
      'descript': 'Inland plant communities', 'field_note': ''},
     **epsg4326_poly_xy},
]
loc_recs_4326_diff_name_descript = [
    {'record':
     {'loc_id': 1, 'loc_code': 'QCC01', 'name': 'Western Drylands',
      'descript': 'Desert species', 'field_note': 'storm damaged area'},
     **epsg4326_poly_xy},
    {'record':
     {'loc_id': 2, 'loc_code': 'APC01', 'name': 'Eucalyts',
      'descript': 'Eucalyptus, Corymbia, etc.', 'field_note': 'seeding'},
     **epsg4326_poly_xy2},
]
loc_recs_4326_new_data = [
    {'record':
     {'loc_id': 3, 'loc_code': 'QCC02', 'name': 'SEQ Threatened',
      'descript': 'local species', 'field_note': ''}, **epsg4326_poly_xy},
    {'record':
     {'loc_id': 4, 'loc_code': 'APC02', 'name': 'Xanthorrhoea',
      'descript': 'Grass Trees', 'field_note': 'flowering'},
     **epsg4326_poly_xy2},
]
loc_recs_3857 = [
    {'record':
     {'loc_id': 1, 'loc_code': 'QCC01', 'name': 'SE Qld Rainforest',
      'descript': 'Rainforest garden', 'field_note': 'storm damaged area'},
     **epsg3857_poly},
    {'record':
     {'loc_id': 2, 'loc_code': 'APC01', 'name': 'Brigalow Belt',
      'descript': 'Inland plant communities', 'field_note': ''},
     **epsg3857_poly2},
]
plt_rec_3857_points = [
    {'record':
     {'plt_id': 1, 'accession': '2021001', 'plt_code': '1', 'quantity': 2,
      'bed': 'QCC01', 'field_note': 'in decline', 'family': 'Proteaceae',
      'genus': 'Grevillea', 'species': 'robusta', 'infrasp': ''},
     **epsg3857_point},
    {'record':
     {'plt_id': 2, 'accession': '2021002', 'plt_code': '2', 'quantity': 3,
      'bed': 'APC01', 'field_note': '', 'family': 'Myrtaceae',
      'genus': 'Eucalyptus', 'species': 'major', 'infrasp': ''},
     **epsg3857_point2},
]
plt_rec_3857_points_wrong_types = [
    {'record':
     {'plt_id': 1.00, 'accession': 2021001, 'plt_code': 1.00, 'quantity': 2.00,
      'bed': 1, 'field_note': 'in decline', 'family': 'Proteaceae',
      'genus': 'Grevillea', 'species': 'robusta', 'infrasp': ''},
     **epsg3857_point},
    {'record':
     {'plt_id': 2.00, 'accession': 2021002, 'plt_code': 2.00, 'quantity': 3.00,
      'bed': 2, 'field_note': '', 'family': 'Myrtaceae',
      'genus': 'Eucalyptus', 'species': 'major', 'infrasp': ''},
     **epsg3857_point2},
]
# first record has bad accession number, 3rd record has bad location, 2nd
# record should be fine 4th record should create a new entry if add_all as
# should the 5th as well as having a complex infraspecific_parts and a
# cultivar_epithet
plt_rec_3857_points_new_some_bad = [
    {'record':
     {'plt_id': 3, 'accession': '', 'plt_code': '1', 'quantity': 4,
      'bed': 'QCC01', 'field_note': 'in decline', 'family': 'Proteaceae',
      'genus': 'Grevillea', 'species': 'robusta', 'infrasp': ''},
     **epsg3857_point},
    {'record':
     {'plt_id': 4, 'accession': '2021001', 'plt_code': '2', 'quantity': 5,
      'bed': 'QCC01', 'field_note': '', 'family': 'Proteaceae',
      'genus': 'Grevillea', 'species': 'robusta', 'infrasp': ''},
     **epsg3857_point},
    {'record':
     {'plt_id': 5, 'accession': '2021002', 'plt_code': '2', 'quantity': 6,
      'bed': '', 'field_note': '', 'family': 'Myrtaceae',
      'genus': 'Eucalyptus', 'species': 'major', 'infrasp': ''},
     **epsg3857_point2},
    {'record':
     {'plt_id': 6, 'accession': '2020002', 'plt_code': '1', 'quantity': 1,
      'bed': 'XYZ01', 'field_note': 'new data', 'family': 'Moraceae',
      'genus': 'Ficus', 'species': 'virens', 'infrasp': 'var. virens'},
     **epsg3857_point2},
]
# some examples of uglier taxonomic names
plt_rec_3857_points_new_complex_sp = [
    {'record':
     {'plt_id': 3, 'accession': '2020001', 'plt_code': '1', 'quantity': 9,
      'bed': 'XYZ01', 'field_note': 'new complex species, cultivar name',
      'family': 'Bromeliaceae', 'genus': 'Tillandsia', 'species': 'ionantha',
      'infrasp': 'var. stricta f. fastigiata', 'cultivar': 'Peanut'},
     **epsg3857_point},
    {'record':
     {'plt_id': 4, 'accession': '2021007', 'plt_code': '3', 'quantity': 2,
      'bed': 'ABC01', 'field_note': 'new provisory name species',
      'family': 'Malvaceae', 'genus': 'Argyrodendron',
      'species': 'sp. (Kin Kin W.D.Francis AQ81198  )'},
     **epsg3857_point2},
    {'record':
     {'plt_id': 5, 'accession': '2021008', 'plt_code': '1', 'quantity': 1,
      'bed': 'ABC02', 'field_note': 'new sub-species name',
      'family': 'Malvaceae', 'genus': 'Abelmoschus', 'species': 'moscatus',
      'infrasp': 'subsp. tuberosus', 'vernacular': 'Native Rosella'},
     **epsg3857_point2},
]
# no full species.genus.family data, new data should not import but already
# existing should change quantity
plt_rec_3857_points2 = [
    {'record':
     {'plt_id': 1, 'accession': '2021001', 'plt_code': '1', 'quantity': 5,
      'bed': 'QCC01', 'field_note': 'in decline', 'family': 'Proteaceae',
      'species_str': 'Grevillea robusta'}, **epsg3857_point},
    {'record':
     {'plt_id': 2, 'accession': '2021002', 'plt_code': '2', 'quantity': 5,
      'bed': 'APC01', 'field_note': '', 'family': 'Myrtaceae',
      'species_str': 'Eucalyptus major'}, **epsg3857_point2},
    {'record':
     {'plt_id': 3, 'accession': '2021002', 'plt_code': '3', 'quantity': 5,
      'bed': 'APC01', 'field_note': '', 'family': 'Myrtaceae',
      'species_str': 'Eucalyptus major'}, **epsg3857_point2},
]
plt_rec_3857_new_only_lines = [
    {'record':
     {'plt_id': 3, 'accession': '2021001', 'plt_code': '2', 'quantity': 5,
      'bed': 'APC01', 'field_note': '', 'family': 'Proteaceae',
      'genus': 'Grevillea', 'species': 'robusta'}, **epsg3857_line},
    {'record':
     {'plt_id': 7, 'accession': '2021002', 'plt_code': '1', 'quantity': 1,
      'bed': 'QCC01', 'field_note': 'replaced?', 'family': 'Myrtaceae',
      'genus': 'Eucalyptus', 'species': 'major'}, **epsg3857_line2},
]
plt_rec_3857_new_data_lines = [
    {'record':
     {'plt_id': 1, 'accession': '2021001', 'plt_code': '1', 'quantity': 1,
      'bed': 'QCC01', 'field_note': 'in decline', 'family': 'Proteaceae',
      'genus': 'Grevillea', 'species': 'robusta'}, **epsg3857_line2},
    {'record':
     {'plt_id': 2, 'accession': '2021002', 'plt_code': '2', 'quantity': 1,
      'bed': 'APC01', 'field_note': '', 'family': 'Myrtaceae',
      'genus': 'Eucalyptus', 'species': 'major'}, **epsg3857_line},
    {'record':
     {'plt_id': 3, 'accession': '2021001', 'plt_code': '2', 'quantity': 5,
      'bed': 'APC01', 'field_note': '', 'family': 'Proteaceae',
      'genus': 'Grevillea', 'species': 'robusta'}, **epsg3857_line},
    {'record':
     {'plt_id': 7, 'accession': '2021002', 'plt_code': '1', 'quantity': 1,
      'bed': 'QCC01', 'field_note': 'replaced?', 'family': 'Myrtaceae',
      'genus': 'Eucalyptus', 'species': 'major'}, **epsg3857_line2},
]


def create_shapefile(name, prj_string, fields, records, out_dir):  \
        # pylint: disable=too-many-locals
    """
    Create a zipped shapefile

    :param name: name to use for the shapefile as a string
    :param prj_string: the string for the .prj file
    :param fields: the fields to use in the shape file as a list of tuples
    :param records: the records for the shape file as a list of dicts where
        'record' = data,
        'type' = shape type,
        'coordinates' = coordinates
    :param out_dir: the absolute path to save the zipped shapefile as a string
    """
    blank = {f[0]: '' for f in fields}
    out_path = Path(out_dir) / name
    out_path = out_path.with_suffix('.zip')
    with TemporaryDirectory() as _temp_dir:
        path = Path(_temp_dir) / name
        prj_path = path.with_suffix('.prj')
        with open(prj_path, "w") as prj:
            prj.write(prj_string)
            prj.close()
        with Writer(path) as shpf:
            for field in fields:
                shpf.field(*field)
            for rec in records:
                record = rec.get('record')
                geo_type = rec.get('type')
                # ensure all the fields are included even if they are blank
                record = {**blank, **record}
                shpf.record(**record)
                coords = rec.get('coordinates')
                if geo_type == 'Point':
                    shpf.point(*coords)
                elif geo_type == 'LineString':
                    shpf.line([coords])
                elif geo_type == 'Polygon':
                    shpf.poly(coords)
                else:
                    # have not implemented type, not sure I ever will
                    pass
        with ZipFile(out_path.with_suffix('.zip'), 'w') as zf:
            in_files = Path(_temp_dir).glob(f'{name}.*')
            for f in in_files:
                zf.write(f, arcname=f.name)
    return out_path


class MockGrid(Gtk.Widget):     # pylint: disable=too-many-instance-attributes
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.items = [[None for i in range(10)] for j in range(20)]
        self.item_count = 0
        self.labels = {}
        self.props = {}
        self.check_buttons = []
        self.max_x = 0
        self.max_y = 0
        self.max_size = 0

    def add(self, item):
        if isinstance(item, Gtk.Label):
            label = item.get_label()
            if label:
                self.labels[label] = item
        if isinstance(item, Gtk.Entry):
            text = item.get_text()
            if text:
                self.props[text] = item
        self.items.append(item)

    def attach(self, item, y, x, width, height):  \
            # pylint: disable=too-many-arguments
        if isinstance(item, Gtk.Label):
            label = item.get_label()
            if label:
                self.labels[label] = item
        if isinstance(item, Gtk.Button):
            text = item.get_label()
            if text:
                self.props[text] = item
        if isinstance(item, Gtk.Entry):
            text = item.get_text()
            if text:
                self.props[text] = item
        if isinstance(item, Gtk.CheckButton):
            self.check_buttons.append(item)

        self.items[x][y] = item
        self.item_count += 1
        self.max_x = max(self.max_x, x)
        self.max_y = max(self.max_y, y)
        self.max_size = max(self.max_size, width + height)

    def show_all(self):     # pylint: disable=arguments-differ
        return

    def get_child_at(self, y, x):
        if self.max_x > x:
            return self.items[x][y]
        return None

    def child_get_property(self, widget, prop):
        if prop == 'top_attach':
            for i, items in enumerate(self.items):
                if widget in items:
                    return i
            return self.max_y
        return None

    def remove_row(self, x):   # pylint: disable=unused-argument
        self.max_x -= 1


class MochSchemaMenu:
    full_path = None

    def __init__(self, *args, **kwargs):
        self.activate_cb = args[1]

    def popup(self, *args):
        self.activate_cb(None, self.full_path, None)

    def append(self, *args):
        return

    def show_all(self):
        return


class ExportSettingsBoxTests(BaubleTestCase):

    def setUp(self):
        super().setUp()
        get_default('system_proj_string', DEFAULT_SYS_PROJ)
        self.temp_dir = TemporaryDirectory()
        from bauble.prefs import (prefs, plant_shapefile_prefs,
                                  location_shapefile_prefs)
        self.plant_fields = prefs.get(f'{plant_shapefile_prefs}.fields', {})
        self.location_fields = prefs.get(f'{location_shapefile_prefs}.fields',
                                         {})
        # transform prefs into something to work with
        self.plant_fields = [[k, *get_field_properties(Plant, v), v] for
                             k, v in self.plant_fields.items()]
        self.location_fields = [[k, *get_field_properties(Location, v), v] for
                                k, v in self.location_fields.items()]

    def tearDown(self):
        self.temp_dir.cleanup()
        super().tearDown()

    def test_settings_box_grid_populates1(self):
        settings_box = ExpSetBox(Location,
                                 fields=self.location_fields,
                                 resize_func=lambda: False,
                                 grid=MockGrid())
        # a item for each value plus a remove button for each row plus a label
        # for item row and an add row button
        total_grid_items = (
            (len(self.location_fields) + 1) *
            (len(self.location_fields[0]) + 1)
        )
        self.assertEqual(settings_box.grid.item_count, total_grid_items)
        self.assertEqual(settings_box.grid.max_size, 2)
        self.assertEqual(settings_box.grid.max_y, 4)
        self.assertEqual(settings_box.grid.max_x, 6)
        from bauble.prefs import LOC_DEFAULTS
        for i in LOC_DEFAULTS.get('fields').keys():
            self.assertIn(i, settings_box.grid.props.keys())

    def test_settings_box_grid_populates2(self):
        settings_box = ExpSetBox(Plant,
                                 fields=self.plant_fields,
                                 resize_func=lambda: False,
                                 grid=MockGrid())
        # a item for each value plus a remove button for each row plus a label
        # for item row, an add row button and nothing for the generate plants
        # fields as we haven't provided the option here (i.e. not search) (65)
        generate_plants = 0
        total_grid_items = (
            (len(self.plant_fields) + 1) *
            (len(self.plant_fields[0]) + 1)
        ) + generate_plants
        self.assertEqual(settings_box.grid.item_count, total_grid_items)

    def test_settings_box_grid_populates3(self):
        fields = {
            'plant': 'plant',
            'quantity': 'quantity',
            'bed': 'location',
            'family': 'accession.species.genus.family',
            'species': 'accession.species',
            'vernacular': 'accession.species.default_vernacular_name'
        }
        fields = [[k, *get_field_properties(Plant, v), v] for
                  k, v in fields.items()]
        settings_box = ExpSetBox(Plant,
                                 fields=fields,
                                 resize_func=lambda: False,
                                 gen_settings={'start': [0.0, 0.0]},
                                 grid=MockGrid())
        # a item for each value plus a remove button for each row plus a label
        # for item row, an add row button and the 1 box of the generate
        # plants fields
        generate_plants = 1
        total_grid_items = (
            (len(fields) + 1) *
            (len(fields[0]) + 1)
        ) + generate_plants
        self.assertEqual(settings_box.grid.item_count, total_grid_items)

    def test_on_add_button_clicked(self):
        start_len = len(self.plant_fields)
        settings_box = ExpSetBox(Plant,
                                 fields=self.plant_fields,
                                 resize_func=lambda: False,
                                 grid=MockGrid())
        settings_box.on_add_button_clicked(None)
        self.assertEqual(start_len + 1, len(self.plant_fields))
        self.assertTrue(all(i is None for i in self.plant_fields[-1]))

    def test_on_remove_button_clicked(self):
        start_len = len(self.plant_fields)
        settings_box = ExpSetBox(Plant,
                                 fields=self.plant_fields,
                                 resize_func=lambda: False,
                                 grid=MockGrid())
        settings_box.on_remove_button_clicked(settings_box.grid.items[2][-1])

        self.assertEqual(start_len - 1, len(self.plant_fields))

    def test_on_gen_combo_changed(self):
        from bauble.meta import BaubleMeta
        self.session.add(BaubleMeta(name='inst_geo_latitude',
                                    value='10.001'))
        self.session.add(BaubleMeta(name='inst_geo_longitude',
                                    value='10.001'))
        self.session.commit()
        settings_box = ExpSetBox(Plant,
                                 fields=self.plant_fields,
                                 resize_func=lambda: False,
                                 gen_settings={'start': [0, 0],
                                               'increment': 0,
                                               'axis': ''},
                                 grid=MockGrid())
        start = settings_box.gen_settings.copy()
        gen_chkbtn = type('MockCheckButton', (object, ), {
            'get_active': lambda: True
        })
        settings_box.on_gen_chkbtn_toggled(gen_chkbtn)
        gen_combo = type('MockComboBox', (object, ), {
            'get_active_text': lambda: 'NS'
        })
        settings_box.on_gen_combo_changed(gen_combo)
        # gen_combo_widget = settings_box.grid.items[14][2]
        # gen_combo_widget.set_active(1)
        result = settings_box.gen_settings
        self.assertNotEqual(start, result)
        self.assertEqual(result.get('axis'), 'NS')
        self.assertEqual(result.get('start'), [10.001, 10.001])
        self.assertEqual(result.get('increment'), 0.00001)

    def test_on_name_entry_changed_field_changes(self):
        settings_box = ExpSetBox(Plant,
                                 fields=self.plant_fields,
                                 resize_func=lambda: False,
                                 grid=MockGrid())
        name_widget = settings_box.grid.items[2][0]
        start = name_widget.get_text()
        name = self.plant_fields[1][0]
        self.assertEqual(start, name)
        name_widget.set_text('test')
        result = self.plant_fields[1][0]
        self.assertEqual('test', result)

    def test_on_field_type_changed_field_changes(self):
        settings_box = ExpSetBox(Plant,
                                 fields=self.plant_fields,
                                 resize_func=lambda: False,
                                 grid=MockGrid())
        type_widget = settings_box.grid.items[2][1]
        start = type_widget.get_active_text()
        typ = self.plant_fields[1][1]
        self.assertEqual(start, typ)
        type_widget.set_active(settings_box.type_vals.get('F'))
        result = self.plant_fields[1][1]
        self.assertEqual('F', result)
        type_widget.set_active(settings_box.type_vals.get('C'))
        result = self.plant_fields[1][1]
        self.assertEqual('C', result)

    def test_on_gen_chkbtn_toggled(self):
        from bauble.meta import BaubleMeta
        self.session.add(BaubleMeta(name='inst_geo_latitude',
                                    value='10.001'))
        self.session.add(BaubleMeta(name='inst_geo_longitude',
                                    value='10.001'))
        self.session.commit()
        settings_box = ExpSetBox(Plant,
                                 fields=self.plant_fields,
                                 resize_func=lambda: False,
                                 gen_settings={'start': [0, 0],
                                               'increment': 0,
                                               'axis': ''},
                                 grid=MockGrid())
        start = settings_box.gen_settings.copy()
        # check when set true it grabs the system defaults
        gen_chkbtn = type('MockCheckButton', (object, ), {
            'get_active': lambda: True
        })
        settings_box.on_gen_chkbtn_toggled(gen_chkbtn)
        result = settings_box.gen_settings
        self.assertNotEqual(start, result)
        self.assertEqual(result.get('axis'), '')
        self.assertEqual(result.get('start'), [10.001, 10.001])
        self.assertEqual(result.get('increment'), 0.00001)

        # check if set false the gen_button is not sensitive
        gen_chkbtn = type('MockCheckButton', (object, ), {
            'get_active': lambda: False
        })
        settings_box.on_gen_chkbtn_toggled(gen_chkbtn)
        self.assertFalse(settings_box.gen_button.get_sensitive())
        # TODO check the button is not active.

    def test_on_length_entry_changed_field_changes(self):
        settings_box = ExpSetBox(Plant,
                                 fields=self.location_fields,
                                 resize_func=lambda: False,
                                 grid=MockGrid())
        length_widget = settings_box.grid.items[2][2]
        start = int(length_widget.get_text())
        length = self.location_fields[1][2]
        self.assertEqual(start, length)
        length_widget.set_value(30)
        result = self.location_fields[1][2]
        self.assertEqual(30, result)
        length_widget.set_value(0)
        result = self.location_fields[1][2]
        self.assertIsNone(result)

    def test_add_prop_button_adds_field(self):
        settings_box = ExpSetBox(Plant,
                                 fields=self.plant_fields,
                                 resize_func=lambda: False,
                                 grid=MockGrid())
        test_path = 'accession.source.collection.geo_accy'
        typ, length = get_field_properties(Plant, test_path)
        start = len(self.plant_fields)
        row = start + 1
        # add blank record first
        settings_box.on_add_button_clicked(None)
        settings_box._add_prop_button(test_path, row)
        self.assertEqual(start + 1, len(self.plant_fields))
        self.assertIsNone(self.plant_fields[-1][0])
        self.assertEqual(self.plant_fields[-1][1], typ)
        self.assertEqual(self.plant_fields[-1][2], length)

    def test_on_remove_button_drag_and_drop(self):
        settings_box = ExpSetBox(Plant,
                                 fields=self.plant_fields,
                                 resize_func=lambda: False,
                                 grid=MockGrid())

        class MockSelection:
            def __init__(self):
                self.text = None

            def set_text(self, text, length):
                self.text = text

            def get_text(self):
                return self.text

        selection_data = MockSelection()
        start = list(self.plant_fields)
        start_widget = settings_box.grid.items[4][4]
        end_widget = settings_box.grid.items[2][4]
        settings_box.on_remove_button_dragged(start_widget, None,
                                              selection_data, None, None)
        settings_box.on_remove_button_dropped(end_widget, None, None,
                                              None, selection_data, None, None)
        self.assertNotEqual(start, self.plant_fields)
        self.assertEqual(start[3], self.plant_fields[1])
        self.assertEqual(start[4:], self.plant_fields[4:])

    def test_static_funcs(self):
        settings_box = ExpSetBox(Plant,
                                 fields=self.plant_fields,
                                 resize_func=lambda: False,
                                 grid=MockGrid())

        mockprop = type('Prop', (object, ), {
            'key': '_default_vernacular_name'
        })()
        self.assertFalse(settings_box.relation_filter(mockprop))

    def test_generated_points_settings_dialog(self):
        from bauble.meta import BaubleMeta
        self.session.add(BaubleMeta(name='inst_geo_latitude',
                                    value='10.001'))
        self.session.add(BaubleMeta(name='inst_geo_longitude',
                                    value='10.001'))
        gen_settings = {'start': [0, 0], 'increment': 0, 'axis': ''}
        start_settings = gen_settings.copy()
        self.session.commit()
        settings_box = ExpSetBox(Plant,
                                 fields=self.plant_fields,
                                 resize_func=lambda: False,
                                 gen_settings=gen_settings,
                                 grid=MockGrid())
        # pick up the system default
        settings_box.reset_gen_settings()

        from bauble import utils
        _orig_create_message_dialog = utils.create_message_dialog

        class MockDialog:
            def __init__(self):
                self.msg = None
                self.box = set()
                self.size = dict()

            def get_message_area(self):
                return self.box

            def resize(self, x, y):
                return

            def show_all(self):
                return

            def set_keep_above(self, val):
                return

            def run(self):
                return Gtk.ResponseType.OK

            def destroy(self):
                return

        mock_dialog = MockDialog()

        def mock_create_message_dialog(msg):
            mock_dialog.msg = msg
            return mock_dialog

        utils.create_message_dialog = mock_create_message_dialog

        # trigger the dialog box
        dialog = settings_box.generated_points_settings_dialog()
        dialog.run()

        # test values
        self.assertNotEqual(gen_settings, start_settings)
        self.assertEqual(gen_settings.get('start'), [10.001, 10.001])
        self.assertEqual(gen_settings.get('increment'), 0.00001)
        self.assertEqual(gen_settings.get('axis'), '')

        grid = mock_dialog.box.pop()
        self.assertEqual(len(grid.get_children()), 8)

        gen_combo = grid.get_child_at(1, 2)
        gen_combo.set_active(1)
        self.assertEqual(gen_settings.get('axis'), 'NS')

        gen_inc_entry = grid.get_child_at(1, 3)
        gen_inc_entry.set_value(0.1)
        self.assertEqual(gen_settings.get('increment'), 0.1)

        utils.create_message_dialog = _orig_create_message_dialog

    def test_on_gen_button_clicked(self):
        from bauble.meta import BaubleMeta
        self.session.add(BaubleMeta(name='inst_geo_latitude',
                                    value='10.001'))
        self.session.add(BaubleMeta(name='inst_geo_longitude',
                                    value='10.001'))
        gen_settings = {'start': [0, 0], 'increment': 0, 'axis': ''}
        self.session.commit()
        settings_box = ExpSetBox(Plant,
                                 fields=self.plant_fields,
                                 resize_func=lambda: False,
                                 gen_settings=gen_settings,
                                 grid=MockGrid())
        # pick up the system default
        settings_box.reset_gen_settings()

        from bauble import utils
        _orig_create_message_dialog = utils.create_message_dialog

        class MockDialog:
            def __init__(self):
                self.msg = None
                self.box = set()
                self.size = dict()

            def get_message_area(self):
                return self.box

            def resize(self, x, y):
                return

            def show_all(self):
                return

            def set_keep_above(self, val):
                return

            def run(self):
                return Gtk.ResponseType.OK

            def destroy(self):
                return

        mock_dialog = MockDialog()

        def mock_create_message_dialog(msg):
            mock_dialog.msg = msg
            return mock_dialog

        utils.create_message_dialog = mock_create_message_dialog

        settings_box.on_gen_button_clicked(None)
        grid = mock_dialog.box.pop()
        self.assertEqual(len(grid.get_children()), 8)

        self.assertFalse('err-btn' in
                         (settings_box.gen_button
                          .get_style_context()
                          .list_classes()))

        class MockDialog2(MockDialog):
            def run(self):
                return Gtk.ResponseType.CANCEL

        mock_dialog = MockDialog2()

        settings_box.on_gen_button_clicked(None)
        grid = mock_dialog.box.pop()
        self.assertEqual(len(grid.get_children()), 8)

        self.assertTrue('err-btn' in
                        (settings_box.gen_button
                         .get_style_context()
                         .list_classes()))

        utils.create_message_dialog = _orig_create_message_dialog


class ShapefileExportTestsEmptyDB(BaubleTestCase):

    def setUp(self):  # pylint: disable=too-many-locals
        super().setUp()
        get_default('system_proj_string', DEFAULT_SYS_PROJ)
        # temp_dir
        self.temp_dir = TemporaryDirectory()
        self.exporter = ShapefileExporter()
        self.exporter.proj_db.add(prj=prj_str_4326, crs='epsg:4326')
        self.exporter.view.widgets.imp_settings_expander = type(
            'MockExpander', (object, ), {
                'get_child': lambda s: None,
                'add': lambda s, w: None,
                'remove': lambda s, w: None,
            }
        )()

    def tearDown(self):
        self.temp_dir.cleanup()
        super().tearDown()

    def test_export_all_fails(self):
        exporter = self.exporter
        exporter.search_or_all = 'rb_all_records'
        exporter.export_locations = True
        exporter.export_plants = True
        exporter.dirname = self.temp_dir.name
        # test start
        exporter.presenter.start = lambda: -5
        response = exporter.start()
        self.assertEqual(response, -5)
        out = [str(i) for i in Path(self.temp_dir.name).glob('*.zip')]
        self.assertEqual(len(out), 0)


class ShapefileExportTests(BaubleTestCase):

    def setUp(self):  # pylint: disable=too-many-locals
        from copy import deepcopy
        super().setUp()
        get_default('system_proj_string', DEFAULT_SYS_PROJ)
        loc_data = deepcopy(location_data)
        loc_data[0]['geojson'] = epsg4326_poly_xy
        loc_data[1]['geojson'] = epsg4326_poly_xy2
        plt_data = deepcopy(plant_data)
        self.full_plant_data = plt_data
        # add an extra plant with points and an extra without for these tests
        plt_data.append({'id': 3, 'code': '1', 'accession_id': 2,
                         'location_id': 1, 'quantity': 2})
        plt_data.append({'id': 4, 'code': '3', 'accession_id': 2,
                         'location_id': 1, 'quantity': 10})
        plt_data[0]['geojson'] = epsg4326_point_xy
        plt_data[1]['geojson'] = epsg4326_line_xy
        plt_data[2]['geojson'] = epsg4326_poly_xy
        data = ((Family, family_data),
                (Genus, genus_data),
                (Species, species_data),
                (Accession, accession_data),
                (Location, loc_data),
                (LocationNote, loc_note_data),
                (Plant, plt_data),
                (PlantNote, plt_note_data))

        for klass, dics in data:
            for dic in dics:
                obj = klass(**dic)
                self.session.add(obj)
        self.session.commit()
        # create temp_dir
        self.temp_dir = TemporaryDirectory()
        # something to compare for plants
        self.taxa_to_acc = {}
        for acc in accession_data:   # pylint: disable=too-many-nested-blocks
            family = genus = species = None
            for sp in species_data:
                if sp.get('id') == acc.get('species_id'):
                    species = sp.get('sp')
                    for gen in genus_data:
                        if gen.get('id') == sp.get('genus_id'):
                            genus = gen.get('genus')
                            for fam in family_data:
                                if fam.get('id') == gen.get('family_id'):
                                    family = fam.get('family')
            self.taxa_to_acc[acc.get('id')] = (family, genus, species)
        self.exporter = ShapefileExporter()
        # TODO here couldn't we just use settatr(self, 'trap', 1) etc.
        self.trap = type('Trap', (object, ), {'vals': 0})()
        self.exporter.view.widgets.exp_settings_expander = type(
            'MockExpander', (object, ), {
                'get_child': lambda s: True,
                'add': lambda s, w: None,
                'remove': lambda s, i: setattr(self.trap, 'vals', 1),
            }
        )()
        self.win = type('MockWin', (object, ), {'vals': ()})()
        self.exporter.view.get_window = lambda: type(
            'MockWindow', (object, ), {
                'resize': lambda x, y: setattr(self.win, 'vals', (x, y))
            }
        )

    def tearDown(self):
        self.temp_dir.cleanup()
        super().tearDown()

    def test_exports_all_locations(self):
        exporter = self.exporter
        exporter.proj_db.add(prj=prj_str_4326, crs='epsg:4326')
        exporter.search_or_all = 'rb_all_records'
        exporter.export_locations = True
        exporter.export_plants = False
        exporter.dirname = self.temp_dir.name
        exporter.run()
        out = [str(i) for i in Path(self.temp_dir.name).glob('*.zip')]
        self.assertEqual(len(out), 1)
        with ZipFile(out[0], 'r') as z:
            namelist = z.namelist()
            self.assertEqual(len(namelist), 4)
            with z.open([i for i in namelist if i.endswith('.prj')][0]) as prj:
                self.assertEqual(prj.read().decode('utf-8'), prj_str_4326)
            with z.open([i for i in namelist if i.endswith('.shp')][0]) as shp:
                with z.open([i for i in namelist if i.endswith('.dbf')][0]) as dbf:
                    with Reader(shp=shp, dbf=dbf) as shpf:
                        # field_names = [i[0] for i in shpf.fields]
                        self.assertEqual(len(shpf.shapes()), 2)
                        self.assertEqual(shpf.record(0)['loc_id'],
                                         location_data[0].get('id'))
                        self.assertEqual(shpf.record(0)['loc_code'],
                                         location_data[0].get('code'))
                        self.assertEqual(shpf.record(0)['descript'],
                                         location_data[0].get('description', ''))
                        self.assertEqual(shpf.record(0)['field_note'],
                                         loc_note_data[1].get('note', ''))
                        self.assertEqual(shpf.record(1)['loc_id'],
                                         location_data[1].get('id'))
                        self.assertEqual(shpf.record(1)['loc_code'],
                                         location_data[1].get('code'))
                        self.assertEqual(shpf.record(1)['descript'],
                                         location_data[1].get('description', ''))
                        self.assertEqual(shpf.record(1)['field_note'],
                                         loc_note_data[0].get('note', ''))

                        # use transform to make sure the format is the same
                        # (lists vs tuples for coordinates)
                        self.assertEqual(
                            transform(shpf.shapes()[0].__geo_interface__,
                                      in_crs='epsg:4326',
                                      out_crs='epsg:4326'),
                            epsg4326_poly_xy)
                        self.assertEqual(
                            transform(shpf.shapes()[1].__geo_interface__,
                                      in_crs='epsg:4326',
                                      out_crs='epsg:4326'),
                            epsg4326_poly_xy2)

    def test_exports_all_plants(self):
        exporter = self.exporter
        exporter.proj_db.add(prj=prj_str_4326, crs='epsg:4326')
        exporter.search_or_all = 'rb_all_records'
        exporter.export_locations = False
        exporter.export_plants = True
        exporter.dirname = self.temp_dir.name
        exporter.run()
        out = Path(self.temp_dir.name).glob('*.zip')
        out = [str(i) for i in Path(self.temp_dir.name).glob('*.zip')]
        self.assertEqual(len(out), 3)
        with ZipFile([i for i in out if 'point.zip' in i][0], 'r') as z:
            namelist = z.namelist()
            self.assertEqual(len(namelist), 4)
            with z.open([i for i in namelist if i.endswith('.prj')][0]) as prj:
                self.assertEqual(prj.read().decode('utf-8'), prj_str_4326)
            with z.open([i for i in namelist if i.endswith('.shp')][0]) as shp:
                with z.open([i for i in namelist if i.endswith('.dbf')][0]) as dbf:
                    with Reader(shp=shp, dbf=dbf) as shpf:
                        # field_names = [i[0] for i in shpf.fields]
                        self.assertEqual(len(shpf.shapes()), 1)
                        self.assertEqual(shpf.record(0)['plt_id'],
                                         plant_data[0].get('id'))
                        self.assertEqual(shpf.record(0)['plt_code'],
                                         plant_data[0].get('code'))
                        self.assertEqual(shpf.record(0)['quantity'],
                                         plant_data[0].get('quantity'))
                        acc = [i.get('code') for i in accession_data if
                               i.get('id') == plant_data[0].get('accession_id')][0]
                        self.assertEqual(shpf.record(0)['accession'], acc)
                        loc = [i.get('code') for i in location_data if
                               i.get('id') == plant_data[0].get('location_id')][0]
                        self.assertEqual(shpf.record(0)['bed'], loc)
                        self.assertEqual(shpf.record(0)['family'],
                                         self.taxa_to_acc.get(
                                             plant_data[0].get('accession_id'))[0]
                                         )
                        self.assertEqual(
                            shpf.record(0)['genus'],
                            self.taxa_to_acc.get(
                                plant_data[0].get('accession_id'))[1]
                        )
                        self.assertEqual(
                            shpf.record(0)['species'],
                            self.taxa_to_acc.get(
                                plant_data[0].get('accession_id'))[2]
                        )
                        self.assertEqual(
                            transform(shpf.shapes()[0].__geo_interface__,
                                      in_crs='epsg:4326',
                                      out_crs='epsg:4326'),
                            epsg4326_point_xy)
        with ZipFile([i for i in out if 'line.zip' in i][0], 'r') as z:
            namelist = z.namelist()
            self.assertEqual(len(namelist), 4)
            with z.open([i for i in namelist if i.endswith('.prj')][0]) as prj:
                self.assertEqual(prj.read().decode('utf-8'), prj_str_4326)
            with z.open([i for i in namelist if i.endswith('.shp')][0]) as shp:
                with z.open([i for i in namelist if i.endswith('.dbf')][0]) as dbf:
                    with Reader(shp=shp, dbf=dbf) as shpf:
                        # field_names = [i[0] for i in shpf.fields]
                        self.assertEqual(len(shpf.shapes()), 1)
                        self.assertEqual(shpf.record(0)['plt_id'],
                                         plant_data[1].get('id'))
                        self.assertEqual(shpf.record(0)['plt_code'],
                                         plant_data[1].get('code'))
                        self.assertEqual(shpf.record(0)['quantity'],
                                         plant_data[1].get('quantity'))
                        acc = [i.get('code') for i in accession_data if
                               i.get('id') == plant_data[1].get('accession_id')][0]
                        self.assertEqual(shpf.record(0)['accession'], acc)
                        loc = [i.get('code') for i in location_data if
                               i.get('id') == plant_data[1].get('location_id')][0]
                        self.assertEqual(shpf.record(0)['bed'], loc)
                        self.assertEqual(shpf.record(0)['family'],
                                         self.taxa_to_acc.get(
                                             plant_data[1].get('accession_id'))[0]
                                         )
                        self.assertEqual(
                            shpf.record(0)['genus'],
                            self.taxa_to_acc.get(
                                plant_data[1].get('accession_id'))[1]
                        )
                        self.assertEqual(
                            shpf.record(0)['species'],
                            self.taxa_to_acc.get(
                                plant_data[1].get('accession_id'))[2]
                        )
                        self.assertEqual(
                            transform(shpf.shapes()[0].__geo_interface__,
                                      in_crs='epsg:4326',
                                      out_crs='epsg:4326'),
                            epsg4326_line_xy)
        with ZipFile([i for i in out if 'poly.zip' in i][0], 'r') as z:
            namelist = z.namelist()
            self.assertEqual(len(namelist), 4)
            with z.open([i for i in namelist if i.endswith('.prj')][0]) as prj:
                self.assertEqual(prj.read().decode('utf-8'), prj_str_4326)
            with z.open([i for i in namelist if i.endswith('.shp')][0]) as shp:
                with z.open([i for i in namelist if i.endswith('.dbf')][0]) as dbf:
                    with Reader(shp=shp, dbf=dbf) as shpf:
                        # field_names = [i[0] for i in shpf.fields]
                        self.assertEqual(len(shpf.shapes()), 1)
                        self.assertEqual(
                            transform(shpf.shapes()[0].__geo_interface__,
                                      in_crs='epsg:4326',
                                      out_crs='epsg:4326'),
                            epsg4326_poly_xy)

    def test_exports_all_plants_with_advanced_settings(self):
        fields = {
            'plant': 'plant',
            'quantity': 'quantity',
            'bed': 'location',
            'family': 'accession.species.genus.family',
            'species': 'accession.species',
            'vernacular': 'accession.species.default_vernacular_name',
            'source': 'accession.source.source_detail.name',
            'coll_accy': 'accession.source.collection.geo_accy',
            'plc_holder': 'Empty'
        }
        fields = [[k, *get_field_properties(Plant, v), v] for
                  k, v in fields.items()]
        exporter = self.exporter
        exporter.proj_db.add(prj=prj_str_4326, crs='epsg:4326')
        exporter.search_or_all = 'rb_all_records'
        exporter.export_locations = False
        exporter.export_plants = True
        exporter.plant_fields = fields
        exporter.dirname = self.temp_dir.name
        exporter.run()
        out = Path(self.temp_dir.name).glob('*.zip')
        out = [str(i) for i in Path(self.temp_dir.name).glob('*.zip')]
        self.assertEqual(len(out), 3)
        # Just test some of the easier data to test.
        with ZipFile([i for i in out if 'point.zip' in i][0], 'r') as z:
            namelist = z.namelist()
            self.assertEqual(len(namelist), 4)
            with z.open([i for i in namelist if i.endswith('.prj')][0]) as prj:
                self.assertEqual(prj.read().decode('utf-8'), prj_str_4326)
            with z.open([i for i in namelist if i.endswith('.shp')][0]) as shp:
                with z.open([i for i in namelist if i.endswith('.dbf')][0]) as dbf:
                    with Reader(shp=shp, dbf=dbf) as shpf:
                        # field_names = [i[0] for i in shpf.fields]
                        self.assertEqual(len(shpf.shapes()), 1)
                        acc = [i.get('code') for i in accession_data if
                               i.get('id') == plant_data[0].get('accession_id')][0]
                        self.assertEqual(shpf.record(0)['plant'],
                                         acc + '.' + plant_data[0].get('code'))
                        self.assertEqual(shpf.record(0)['quantity'],
                                         plant_data[0].get('quantity'))
                        loc_code = [i.get('code') for i in location_data if
                                    i.get('id') ==
                                    plant_data[0].get('location_id')][0]
                        loc_name = [i.get('name') for i in location_data if
                                    i.get('id') ==
                                    plant_data[0].get('location_id')][0]
                        self.assertEqual(shpf.record(0)['bed'],
                                         f'({loc_code}) {loc_name}')
                        self.assertEqual(shpf.record(0)['family'],
                                         self.taxa_to_acc.get(
                                             plant_data[0].get('accession_id'))[0]
                                         )
                        self.assertEqual(shpf.record(0)['source'], '')
                        self.assertEqual(shpf.record(0)['plc_holder'], '')
                        self.assertIsNone(shpf.record(0)['coll_accy'], '')
                        self.assertEqual([i for i in shpf.fields if i[0] ==
                                          'coll_accy'][0][3], 10)
                        self.assertEqual(
                            transform(shpf.shapes()[0].__geo_interface__,
                                      in_crs='epsg:4326',
                                      out_crs='epsg:4326'),
                            epsg4326_point_xy)

    def test_exports_all_plants_not_private(self):
        exporter = self.exporter
        exporter.proj_db.add(prj=prj_str_4326, crs='epsg:4326')
        exporter.search_or_all = 'rb_all_records'
        exporter.private = False
        exporter.export_locations = False
        exporter.export_plants = True
        exporter.dirname = self.temp_dir.name
        exporter.run()
        out = Path(self.temp_dir.name).glob('*.zip')
        out = [str(i) for i in Path(self.temp_dir.name).glob('*.zip')]
        self.assertEqual(len(out), 1)
        # Only one plant should come through as the other 2 are from the
        # private accession
        with ZipFile([i for i in out if 'point.zip' in i][0], 'r') as z:
            namelist = z.namelist()
            self.assertEqual(len(namelist), 4)
            with z.open([i for i in namelist if i.endswith('.prj')][0]) as prj:
                self.assertEqual(prj.read().decode('utf-8'), prj_str_4326)
            with z.open([i for i in namelist if i.endswith('.shp')][0]) as shp:
                with z.open([i for i in namelist if i.endswith('.dbf')][0]) as dbf:
                    with Reader(shp=shp, dbf=dbf) as shpf:
                        # field_names = [i[0] for i in shpf.fields]
                        self.assertEqual(len(shpf.shapes()), 1)
                        self.assertEqual(shpf.record(0)['plt_id'],
                                         plant_data[0].get('id'))
                        self.assertEqual(shpf.record(0)['plt_code'],
                                         plant_data[0].get('code'))
                        self.assertEqual(shpf.record(0)['quantity'],
                                         plant_data[0].get('quantity'))
                        acc = [i.get('code') for i in accession_data if
                               i.get('id') == plant_data[0].get('accession_id')][0]
                        self.assertEqual(shpf.record(0)['accession'], acc)
                        loc = [i.get('code') for i in location_data if
                               i.get('id') == plant_data[0].get('location_id')][0]
                        self.assertEqual(shpf.record(0)['bed'], loc)
                        self.assertEqual(shpf.record(0)['family'],
                                         self.taxa_to_acc.get(
                                             plant_data[0].get('accession_id'))[0]
                                         )
                        self.assertEqual(
                            shpf.record(0)['genus'],
                            self.taxa_to_acc.get(
                                plant_data[0].get('accession_id'))[1]
                        )
                        self.assertEqual(
                            shpf.record(0)['species'],
                            self.taxa_to_acc.get(
                                plant_data[0].get('accession_id'))[2]
                        )
                        self.assertEqual(
                            transform(shpf.shapes()[0].__geo_interface__,
                                      in_crs='epsg:4326',
                                      out_crs='epsg:4326'),
                            epsg4326_point_xy)

    def test_exports_all(self):
        exporter = self.exporter
        exporter.proj_db.add(prj=prj_str_4326, crs='epsg:4326')
        exporter.search_or_all = 'rb_all_records'
        exporter.export_locations = True
        exporter.export_plants = True
        exporter.dirname = self.temp_dir.name
        # test start
        exporter.presenter.start = lambda: -5
        response = exporter.start()
        self.assertEqual(response, -5)
        out = [str(i) for i in Path(self.temp_dir.name).glob('*.zip')]
        self.assertEqual(len(out), 4)

        with ZipFile([i for i in out if 'plants_point.zip' in i][0]) as z:
            namelist = z.namelist()
            self.assertEqual(len(namelist), 4)
            with z.open([i for i in namelist if i.endswith('.prj')][0]) as prj:
                self.assertEqual(prj.read().decode('utf-8'), prj_str_4326)
            with z.open([i for i in namelist if i.endswith('.shp')][0]) as shp:
                with z.open([i for i in namelist if i.endswith('.dbf')][0]) as dbf:
                    with Reader(shp=shp, dbf=dbf) as shpf:
                        # field_names = [i[0] for i in shpf.fields]
                        self.assertEqual(len(shpf.shapes()), 1)
                        self.assertEqual(shpf.record(0)['plt_id'],
                                         plant_data[0].get('id'))

        with ZipFile([i for i in out if 'plants_line.zip' in i][0]) as z:
            namelist = z.namelist()
            self.assertEqual(len(namelist), 4)
            with z.open([i for i in namelist if i.endswith('.prj')][0]) as prj:
                self.assertEqual(prj.read().decode('utf-8'), prj_str_4326)
            with z.open([i for i in namelist if i.endswith('.shp')][0]) as shp:
                with z.open([i for i in namelist if i.endswith('.dbf')][0]) as dbf:
                    with Reader(shp=shp, dbf=dbf) as shpf:
                        # field_names = [i[0] for i in shpf.fields]
                        self.assertEqual(len(shpf.shapes()), 1)
                        self.assertEqual(shpf.record(0)['plt_code'],
                                         plant_data[1].get('code'))

        with ZipFile([i for i in out if 'plants_poly.zip' in i][0]) as z:
            namelist = z.namelist()
            self.assertEqual(len(namelist), 4)
            with z.open([i for i in namelist if i.endswith('.prj')][0]) as prj:
                self.assertEqual(prj.read().decode('utf-8'), prj_str_4326)
            with z.open([i for i in namelist if i.endswith('.shp')][0]) as shp:
                with z.open([i for i in namelist if i.endswith('.dbf')][0]) as dbf:
                    with Reader(shp=shp, dbf=dbf) as shpf:
                        # field_names = [i[0] for i in shpf.fields]
                        self.assertEqual(len(shpf.shapes()), 1)
                        self.assertEqual(
                            transform(shpf.shapes()[0].__geo_interface__,
                                      in_crs='epsg:4326',
                                      out_crs='epsg:4326'),
                            epsg4326_poly_xy)

        with ZipFile([i for i in out if 'locations_poly.zip' in i][0]) as z:
            namelist = z.namelist()
            self.assertEqual(len(namelist), 4)
            with z.open([i for i in namelist if i.endswith('.prj')][0]) as prj:
                self.assertEqual(prj.read().decode('utf-8'), prj_str_4326)
            with z.open([i for i in namelist if i.endswith('.shp')][0]) as shp:
                with z.open([i for i in namelist if i.endswith('.dbf')][0]) as dbf:
                    with Reader(shp=shp, dbf=dbf) as shpf:
                        # field_names = [i[0] for i in shpf.fields]
                        self.assertEqual(len(shpf.shapes()), 2)
                        self.assertEqual(shpf.record(0)['loc_id'],
                                         location_data[0].get('id'))

    def test_exports_all_w_generated_plant_points(self):
        exporter = self.exporter
        exporter.proj_db.add(prj=prj_str_4326, crs='epsg:4326')
        exporter.search_or_all = 'rb_all_records'
        exporter.export_locations = True
        exporter.export_plants = True
        # in this case this should not make a difference
        exporter.gen_settings = {'start': [0.2956, 51.4787],
                                 'increment': 0.0001,
                                 'axis': 'NS'}
        exporter.dirname = self.temp_dir.name
        # test start
        exporter.presenter.start = lambda: -5
        response = exporter.start()
        self.assertEqual(response, -5)
        out = [str(i) for i in Path(self.temp_dir.name).glob('*.zip')]
        self.assertEqual(len(out), 4)

        with ZipFile([i for i in out if 'plants_point.zip' in i][0]) as z:
            namelist = z.namelist()
            self.assertEqual(len(namelist), 4)
            with z.open([i for i in namelist if i.endswith('.prj')][0]) as prj:
                self.assertEqual(prj.read().decode('utf-8'), prj_str_4326)
            with z.open([i for i in namelist if i.endswith('.shp')][0]) as shp:
                with z.open([i for i in namelist if i.endswith('.dbf')][0]) as dbf:
                    with Reader(shp=shp, dbf=dbf) as shpf:
                        # field_names = [i[0] for i in shpf.fields]
                        self.assertEqual(len(shpf.shapes()), 1)
                        self.assertEqual(shpf.record(0)['plt_id'],
                                         plant_data[0].get('id'))

        with ZipFile([i for i in out if 'plants_line.zip' in i][0]) as z:
            namelist = z.namelist()
            self.assertEqual(len(namelist), 4)
            with z.open([i for i in namelist if i.endswith('.prj')][0]) as prj:
                self.assertEqual(prj.read().decode('utf-8'), prj_str_4326)
            with z.open([i for i in namelist if i.endswith('.shp')][0]) as shp:
                with z.open([i for i in namelist if i.endswith('.dbf')][0]) as dbf:
                    with Reader(shp=shp, dbf=dbf) as shpf:
                        # field_names = [i[0] for i in shpf.fields]
                        self.assertEqual(len(shpf.shapes()), 1)
                        self.assertEqual(shpf.record(0)['plt_code'],
                                         plant_data[1].get('code'))

        with ZipFile([i for i in out if 'plants_poly.zip' in i][0]) as z:
            namelist = z.namelist()
            self.assertEqual(len(namelist), 4)
            with z.open([i for i in namelist if i.endswith('.prj')][0]) as prj:
                self.assertEqual(prj.read().decode('utf-8'), prj_str_4326)
            with z.open([i for i in namelist if i.endswith('.shp')][0]) as shp:
                with z.open([i for i in namelist if i.endswith('.dbf')][0]) as dbf:
                    with Reader(shp=shp, dbf=dbf) as shpf:
                        # field_names = [i[0] for i in shpf.fields]
                        self.assertEqual(len(shpf.shapes()), 1)
                        self.assertEqual(
                            transform(shpf.shapes()[0].__geo_interface__,
                                      in_crs='epsg:4326',
                                      out_crs='epsg:4326'),
                            epsg4326_poly_xy)

        with ZipFile([i for i in out if 'locations_poly.zip' in i][0]) as z:
            namelist = z.namelist()
            self.assertEqual(len(namelist), 4)
            with z.open([i for i in namelist if i.endswith('.prj')][0]) as prj:
                self.assertEqual(prj.read().decode('utf-8'), prj_str_4326)
            with z.open([i for i in namelist if i.endswith('.shp')][0]) as shp:
                with z.open([i for i in namelist if i.endswith('.dbf')][0]) as dbf:
                    with Reader(shp=shp, dbf=dbf) as shpf:
                        # field_names = [i[0] for i in shpf.fields]
                        self.assertEqual(len(shpf.shapes()), 2)
                        self.assertEqual(shpf.record(0)['loc_id'],
                                         location_data[0].get('id'))

    def test_exports_search_all_w_generated_plants(self):
        objs = self.session.query(Genus).filter_by(genus='Eucalyptus').all()
        exporter = self.exporter
        exporter.view.selection = objs
        exporter.proj_db.add(prj=prj_str_4326, crs='epsg:4326')
        exporter.search_or_all = 'rb_search_results'
        exporter.export_locations = True
        exporter.export_plants = True
        # here this does make a difference and should add an extra shapefile
        # with a plant in it
        exporter.gen_settings = {'start': [0.2956, 51.4787],
                                 'increment': 0.0001,
                                 'axis': 'NS'}
        exporter.dirname = self.temp_dir.name
        exporter.run()
        out = [str(i) for i in Path(self.temp_dir.name).glob('*.zip')]
        self.assertEqual(len(out), 4)
        with ZipFile([i for i in out if 'plants_point.zip' in i][0]) as z:
            namelist = z.namelist()
            self.assertEqual(len(namelist), 4)
            with z.open([i for i in namelist if i.endswith('.prj')][0]) as prj:
                self.assertEqual(prj.read().decode('utf-8'), prj_str_4326)
            with z.open([i for i in namelist if i.endswith('.shp')][0]) as shp:
                with z.open([i for i in namelist if i.endswith('.dbf')][0]) as dbf:
                    with Reader(shp=shp, dbf=dbf) as shpf:
                        self.assertEqual(len(shpf.shapes()), 1)
                        self.assertEqual(shpf.record(0)['plt_id'],
                                         self.full_plant_data[3].get('id'))
                        self.assertEqual(shpf.record(0)['plt_code'],
                                         self.full_plant_data[3].get('code'))
                        self.assertEqual(shpf.record(0)['quantity'],
                                         self.full_plant_data[3].get('quantity'))
                        acc = [i.get('code') for i in accession_data if
                               i.get('id') ==
                               self.full_plant_data[3].get('accession_id')][0]
                        self.assertEqual(shpf.record(0)['accession'], acc)
                        loc = [i.get('code') for i in location_data if
                               i.get('id') ==
                               self.full_plant_data[3].get('location_id')][0]
                        self.assertEqual(shpf.record(0)['bed'], loc)
                        self.assertEqual(
                            shpf.record(0)['family'],
                            self.taxa_to_acc.get(
                                self.full_plant_data[3].get('accession_id'))[0]
                        )
                        self.assertEqual(
                            shpf.record(0)['genus'],
                            self.taxa_to_acc.get(
                                self.full_plant_data[3].get('accession_id'))[1]
                        )
                        self.assertEqual(
                            shpf.record(0)['species'],
                            self.taxa_to_acc.get(
                                self.full_plant_data[3].get('accession_id'))[2]
                        )
                        self.assertEqual(
                            shpf.shapes()[0].__geo_interface__,
                            {'type': 'Point', 'coordinates': (0.2956, 51.4787)}
                        )
        with ZipFile([i for i in out if 'locations_poly.zip' in i][0]) as z:
            namelist = z.namelist()
            self.assertEqual(len(namelist), 4)
            with z.open([i for i in namelist if i.endswith('.prj')][0]) as prj:
                self.assertEqual(prj.read().decode('utf-8'), prj_str_4326)
            with z.open([i for i in namelist if i.endswith('.shp')][0]) as shp:
                with z.open([i for i in namelist if i.endswith('.dbf')][0]) as dbf:
                    with Reader(shp=shp, dbf=dbf) as shpf:
                        self.assertEqual(len(shpf.shapes()), 2)

    def test_exports_search_all_w_generated_plants_under_100(self):
        accs = self.session.query(Accession).all()
        bulk_plants = [
            Plant(code=str(i // len(accs) + 4),
                  accession=accs[i % len(accs)],
                  location_id=i // 2 + 1,
                  quantity=i)
            for i in range(30)
        ]
        self.session.add_all(bulk_plants)
        self.session.commit()
        objs = self.session.query(Plant).all()
        exporter = self.exporter
        exporter.view.selection = objs
        exporter.proj_db.add(prj=prj_str_4326, crs='epsg:4326')
        exporter.search_or_all = 'rb_search_results'
        exporter.export_locations = False
        exporter.export_plants = True
        # here this does make a difference and should add an extra shapefile
        # and a plant in it
        exporter.gen_settings = {'start': [0.2956, 51.4787],
                                 'increment': 0.0001,
                                 'axis': 'EW'}
        exporter.dirname = self.temp_dir.name
        exporter.run()
        out = [str(i) for i in Path(self.temp_dir.name).glob('*.zip')]
        self.assertEqual(len(out), 3)
        with ZipFile([i for i in out if 'plants_point.zip' in i][0]) as z:
            namelist = z.namelist()
            self.assertEqual(len(namelist), 4)
            with z.open([i for i in namelist if i.endswith('.prj')][0]) as prj:
                self.assertEqual(prj.read().decode('utf-8'), prj_str_4326)
            with z.open([i for i in namelist if i.endswith('.shp')][0]) as shp:
                with z.open([i for i in namelist if i.endswith('.dbf')][0]) as dbf:
                    with Reader(shp=shp, dbf=dbf) as shpf:
                        self.assertEqual(len(shpf.shapes()), 32)
                        self.assertEqual(
                            shpf.shapes()[1].__geo_interface__,
                            {'type': 'Point', 'coordinates': (0.2956, 51.4787)}
                        )
                        self.assertEqual(
                            shpf.shapes()[31].__geo_interface__,
                            {'type': 'Point',
                             'coordinates': (0.2956 + (0.0001 * 30), 51.4787)}
                        )

    def test_exports_search_all_w_generated_plants_over_100(self):
        import bauble
        orig_message_dialog = bauble.utils.message_dialog
        mock_dialog = lambda msg: setattr(self, 'msg', msg)  # noqa
        bauble.utils.message_dialog = mock_dialog
        accs = self.session.query(Accession).all()
        bulk_plants = [
            Plant(code=str(i // len(accs) + 4),
                  accession=accs[i % len(accs)],
                  location_id=i // 2 + 1,
                  quantity=i)
            for i in range(100)
        ]
        self.session.add_all(bulk_plants)
        self.session.commit()
        objs = self.session.query(Plant).all()
        objs = self.session.query(Plant).filter(Plant.geojson == None).all()  # noqa
        exporter = self.exporter
        exporter.view.selection = objs
        exporter.proj_db.add(prj=prj_str_4326, crs='epsg:4326')
        exporter.search_or_all = 'rb_search_results'
        exporter.export_locations = False
        exporter.export_plants = True
        # here this does make a difference but being more than 100 should
        # message user, and produce no output.
        exporter.gen_settings = {'start': [0.2956, 51.4787],
                                 'increment': 0.0001,
                                 'axis': 'EW'}
        exporter.dirname = self.temp_dir.name
        exporter.run()
        out = [str(i) for i in Path(self.temp_dir.name).glob('*.zip')]
        self.assertEqual(len(out), 0)
        self.assertEqual(exporter._generate_points, 0)
        self.assertGreater(len(self.msg), 10)   # pylint: disable=no-member
        bauble.utils.message_dialog = orig_message_dialog

    def test_exports_search_plants(self):
        objs = self.session.query(Genus).filter_by(genus='Grevillea').all()
        exporter = self.exporter
        exporter.view.selection = objs
        exporter.proj_db.add(prj=prj_str_4326, crs='epsg:4326')
        exporter.search_or_all = 'rb_search_results'
        exporter.export_locations = False
        exporter.export_plants = True
        exporter.dirname = self.temp_dir.name
        exporter.run()
        out = [str(i) for i in Path(self.temp_dir.name).glob('*.zip')]
        self.assertEqual(len(out), 1)
        with ZipFile(out[0], 'r') as z:
            namelist = z.namelist()
            self.assertEqual(len(namelist), 4)
            with z.open([i for i in namelist if i.endswith('.prj')][0]) as prj:
                self.assertEqual(prj.read().decode('utf-8'), prj_str_4326)
            with z.open([i for i in namelist if i.endswith('.shp')][0]) as shp:
                with z.open([i for i in namelist if i.endswith('.dbf')][0]) as dbf:
                    with Reader(shp=shp, dbf=dbf) as shpf:
                        self.assertEqual(len(shpf.shapes()), 1)
                        self.assertEqual(shpf.record(0)['plt_id'],
                                         plant_data[0].get('id'))
                        self.assertEqual(shpf.record(0)['plt_code'],
                                         plant_data[0].get('code'))
                        self.assertEqual(shpf.record(0)['quantity'],
                                         plant_data[0].get('quantity'))
                        acc = [i.get('code') for i in accession_data if
                               i.get('id') == plant_data[0].get('accession_id')][0]
                        self.assertEqual(shpf.record(0)['accession'], acc)
                        loc = [i.get('code') for i in location_data if
                               i.get('id') == plant_data[0].get('location_id')][0]
                        self.assertEqual(shpf.record(0)['bed'], loc)
                        self.assertEqual(shpf.record(0)['family'],
                                         self.taxa_to_acc.get(
                                             plant_data[0].get('accession_id'))[0]
                                         )
                        self.assertEqual(
                            shpf.record(0)['genus'],
                            self.taxa_to_acc.get(
                                plant_data[0].get('accession_id'))[1]
                        )
                        self.assertEqual(
                            shpf.record(0)['species'],
                            self.taxa_to_acc.get(
                                plant_data[0].get('accession_id'))[2]
                        )
                        self.assertEqual(
                            transform(shpf.shapes()[0].__geo_interface__,
                                      in_crs='epsg:4326',
                                      out_crs='epsg:4326'),
                            epsg4326_point_xy)

    def test_exports_search_plants_with_no_geojson(self):
        rec1 = self.session.query(Plant).get(1)
        rec1.geojson = None
        self.session.add(rec1)
        self.session.commit()
        objs = self.session.query(Plant).all()
        exporter = self.exporter
        exporter.view.selection = objs
        exporter.proj_db.add(prj=prj_str_4326, crs='epsg:4326')
        exporter.search_or_all = 'rb_search_results'
        exporter.export_locations = False
        exporter.export_plants = True
        exporter.dirname = self.temp_dir.name
        exporter.run()
        out = [str(i) for i in Path(self.temp_dir.name).glob('*.zip')]
        self.assertEqual(len(out), 2)
        self.assertEqual(exporter.error, 2)

    def test_exports_search_locations(self):
        objs = self.session.query(Family).filter_by(family='Myrtaceae').all()
        exporter = self.exporter
        exporter.view.selection = objs
        exporter.proj_db.add(prj=prj_str_4326, crs='epsg:4326')
        exporter.search_or_all = 'rb_search_results'
        exporter.export_locations = True
        exporter.export_plants = False
        exporter.dirname = self.temp_dir.name
        exporter.run()
        out = [str(i) for i in Path(self.temp_dir.name).glob('*.zip')]
        self.assertEqual(len(out), 1)
        with ZipFile(out[0], 'r') as z:
            namelist = z.namelist()
            self.assertEqual(len(namelist), 4)
            with z.open([i for i in namelist if i.endswith('.prj')][0]) as prj:
                self.assertEqual(prj.read().decode('utf-8'), prj_str_4326)
            with z.open([i for i in namelist if i.endswith('.shp')][0]) as shp:
                with z.open([i for i in namelist if i.endswith('.dbf')][0]) as dbf:
                    with Reader(shp=shp, dbf=dbf) as shpf:
                        self.assertEqual(len(shpf.shapes()), 2)

    def test_on_btnbrowse_clicked(self):
        exporter = self.exporter
        exporter.view.widgets.input_dirname = 'input_dirname'
        exporter.view.reply_file_chooser_dialog = [self.temp_dir.name]
        exporter.presenter.on_btnbrowse_clicked('button')
        exporter.presenter.on_dirname_entry_changed('input_dirname')
        self.assertEqual(exporter.dirname, self.temp_dir.name)
        self.assertEqual(exporter.presenter.last_folder, self.temp_dir.name)

    def test_on_btnbrowse_clicked_bad_dir(self):
        exporter = self.exporter
        # run the presenter for plants to check it doesn't cause errors
        exporter.export_plants = True
        exporter.presenter._settings_expander()
        # set last_folder
        exporter.view.widgets.input_dirname = 'input_dirname'
        exporter.view.reply_file_chooser_dialog = [self.temp_dir.name]
        exporter.presenter.on_btnbrowse_clicked('button')
        exporter.presenter.on_dirname_entry_changed('input_dirname')
        # try setting to a bad path
        bad_path = '/bad/path/'
        exporter.view.reply_file_chooser_dialog = [bad_path]
        exporter.presenter.on_btnbrowse_clicked('button')
        exporter.presenter.on_dirname_entry_changed('input_dirname')
        # assert that it did set dirname, was unsucessful at changing
        # last_folder but left dirname at the good path
        self.assertEqual(exporter.dirname, bad_path)
        self.assertNotEqual(exporter.presenter.last_folder, bad_path)
        self.assertEqual(exporter.presenter.last_folder, self.temp_dir.name)

    def test_search_view_option(self):
        import bauble
        _orig_gui = bauble.gui
        MockSearchView = type('SearchView', (object, ), {
            'results_view': type('ResultView', (object, ), {
                'get_model': lambda s: Location
            })()
        })
        _orig_search_view = bauble.view.SearchView
        bauble.view.SearchView = MockSearchView
        search_view = MockSearchView()
        GUI = type('MockView', (object, ), {
            'get_view': lambda s: search_view
        })
        bauble.gui = GUI()
        # need to use a new exporter to test after search
        exporter = ShapefileExporter()
        bauble.gui = _orig_gui
        bauble.view.SearchView = _orig_search_view
        self.assertTrue(
            exporter.view.widget_get_sensitive('rb_search_results'))

    def test_export_tool_locations(self):
        export_tool = ShapefileExportTool()
        exporter = export_tool.start()
        exporter.proj_db.add(prj=prj_str_4326, crs='epsg:4326')
        exporter.search_or_all = 'rb_all_records'
        exporter.export_locations = True
        exporter.export_plants = False
        exporter.dirname = self.temp_dir.name
        exporter.run()
        out = [str(i) for i in Path(self.temp_dir.name).glob('*.zip')]
        self.assertEqual(len(out), 1)
        with ZipFile(out[0], 'r') as z:
            namelist = z.namelist()
            self.assertEqual(len(namelist), 4)
            with z.open([i for i in namelist if i.endswith('.prj')][0]) as prj:
                self.assertEqual(prj.read().decode('utf-8'), prj_str_4326)
            with z.open([i for i in namelist if i.endswith('.shp')][0]) as shp:
                with z.open([i for i in namelist if i.endswith('.dbf')][0]) as dbf:
                    with Reader(shp=shp, dbf=dbf) as shpf:
                        # field_names = [i[0] for i in shpf.fields]
                        self.assertEqual(len(shpf.shapes()), 2)

    def test_export_tool_plants(self):
        export_tool = ShapefileExportTool()
        exporter = export_tool.start()
        exporter.proj_db.add(prj=prj_str_4326, crs='epsg:4326')
        exporter.search_or_all = 'rb_all_records'
        exporter.export_locations = False
        exporter.export_plants = True
        exporter.dirname = self.temp_dir.name
        exporter.run()
        out = [str(i) for i in Path(self.temp_dir.name).glob('*.zip')]
        self.assertEqual(len(out), 3)

    def test_on_settings_activate(self):
        # somewhat superfluous
        exporter = self.exporter
        exporter.presenter.on_settings_activate('exp_settings_expander')
        self.assertEqual(self.win.vals, (1, 1))

    def test_reset_win_size(self):
        exporter = self.exporter
        start = self.win.vals
        exporter.presenter.reset_win_size()
        self.assertNotEqual(start, self.win.vals)
        exporter.presenter._settings_expander()
        self.assertEqual(len(exporter.presenter.settings_boxes), 1)
        locs_only = exporter.presenter.settings_boxes[
            0].get_min_content_height()
        exporter.export_plants = True
        exporter.presenter._settings_expander()
        exporter.presenter.reset_win_size()
        with_plants_set_boxes = exporter.presenter.settings_boxes
        with_plants = max([s.get_min_content_height() for s in
                           with_plants_set_boxes])
        self.assertGreater(with_plants, locs_only)

    def test_create_prj_file_raises_error_wo_sys_proj(self):
        # set the system projection string to something unusable
        from bauble.meta import BaubleMeta
        sys_proj = self.session.query(BaubleMeta).filter_by(
            name='system_proj_string').one()
        sys_proj.value = 'badCRS'
        self.session.commit()
        exporter = self.exporter
        shapefile_name = self.temp_dir.name + '/failed_shapefile'
        from bauble.error import BaubleError, MetaTableError
        with self.assertRaises(BaubleError):
            exporter.create_prj_file(shapefile_name)
        self.session.delete(sys_proj)
        self.session.commit()
        with self.assertRaises(MetaTableError):
            exporter.create_prj_file(shapefile_name)


class ImportSettingsBoxTests(BaubleTestCase):

    def setUp(self):
        super().setUp()
        self.temp_dir = TemporaryDirectory()

    def tearDown(self):
        self.temp_dir.cleanup()
        super().tearDown()

    def test_settings_box_grid_populates1(self):
        shape_reader = ShapefileReader(create_shapefile('test',
                                                        prj_str_4326,
                                                        location_fields,
                                                        loc_recs_4326,
                                                        self.temp_dir.name))
        settings_box = ImpSetBox(shape_reader, grid=MockGrid())
        from bauble.prefs import LOC_DEFAULTS
        self.assertEqual(settings_box.grid.item_count,
                         len(LOC_DEFAULTS.get('fields')) * 6 + 6)
        self.assertEqual(settings_box.grid.max_size, 2)
        self.assertEqual(settings_box.grid.max_y, 5)
        self.assertEqual(settings_box.grid.max_x, 5)
        for i in location_fields:
            for j in i:
                self.assertIn(str(j), settings_box.grid.labels.keys())
        for i in LOC_DEFAULTS.get('fields').values():
            self.assertIn(i, settings_box.grid.props.keys())

    def test_settings_box_grid_populates2(self):
        shape_reader = ShapefileReader(
            create_shapefile('test',
                             prj_str_3857,
                             plant_fields,
                             plt_rec_3857_new_data_lines,
                             self.temp_dir.name))
        settings_box = ImpSetBox(shape_reader, grid=MockGrid())
        from bauble.prefs import PLT_DEFAULTS
        self.assertEqual(settings_box.grid.item_count,
                         len(PLT_DEFAULTS.get('fields')) * 6 + 6)
        self.assertEqual(settings_box.grid.max_size, 2)
        self.assertEqual(settings_box.grid.max_y, 5)
        self.assertEqual(settings_box.grid.max_x,
                         len(PLT_DEFAULTS.get('fields')))
        for i in plant_fields:
            for j in i:
                self.assertIn(str(j), settings_box.grid.labels.keys())
        for i in PLT_DEFAULTS.get('fields').values():
            self.assertIn(i, settings_box.grid.props.keys())

    def test_on_prop_change_field_map_changes(self):
        import bauble
        _orig_schema_menu = bauble.search.SchemaMenu
        bauble.search.SchemaMenu = MochSchemaMenu
        shape_reader = ShapefileReader(
            create_shapefile('test',
                             prj_str_3857,
                             plant_fields,
                             plt_rec_3857_new_data_lines,
                             self.temp_dir.name))
        settings_box = ImpSetBox(shape_reader, grid=MockGrid())
        # prop_button = settings_box.grid.props.get('location.code')
        event = type('', (), {})
        event.button = 1
        event.time = 100
        # prop_button.clicked()
        # prop_button.do_button_press_event(prop_button, event)
        chk_button = type('MockChkButton', (object, ), {
            'set_active': lambda s: None
        })
        prop_button, schema_menu = settings_box._get_prop_button(
            ['bed', 'C', 126, 0], chk_button)
        MochSchemaMenu.full_path = 'bed_name'
        settings_box.on_prop_button_press_event(prop_button, event,
                                                schema_menu)
        self.assertEqual(shape_reader.field_map.get('bed'), 'bed_name')
        # testing can add a new field
        prop_button2, schema_menu = settings_box._get_prop_button(
            ['bed_description', 'C', 126, 0], chk_button)
        MochSchemaMenu.full_path = 'location.desciption'
        settings_box.on_prop_button_press_event(prop_button2, event,
                                                schema_menu)
        self.assertEqual(shape_reader.field_map.get('bed_description'),
                         'location.desciption')
        bauble.search.SchemaMenu = _orig_schema_menu

    def test_on_prop_none_field_map_value_deleted(self):
        import bauble
        _orig_schema_menu = bauble.search.SchemaMenu
        bauble.search.SchemaMenu = MochSchemaMenu
        shape_reader = ShapefileReader(
            create_shapefile('test',
                             prj_str_3857,
                             plant_fields,
                             plt_rec_3857_new_data_lines,
                             self.temp_dir.name))
        settings_box = ImpSetBox(shape_reader, grid=MockGrid())
        event = type('', (), {})
        event.button = 1
        event.time = 100
        chk_button = type('MockChkButton', (object, ), {
            'set_active': lambda s: None
        })
        prop_button, schema_menu = settings_box._get_prop_button(
            ['bed', 'C', 126, 0], chk_button)
        MochSchemaMenu.full_path = None
        settings_box.on_prop_button_press_event(prop_button, event,
                                                schema_menu)
        self.assertIsNone(shape_reader.field_map.get('bed'))
        bauble.search.SchemaMenu = _orig_schema_menu

    def test_on_chk_button_change_search_by_changes(self):
        shape_reader = ShapefileReader(create_shapefile('test',
                                                        prj_str_4326,
                                                        location_fields,
                                                        loc_recs_4326,
                                                        self.temp_dir.name))
        settings_box = ImpSetBox(shape_reader, grid=MockGrid())
        # add loc_id
        chk_btn = settings_box.grid.check_buttons[0]
        chk_btn.set_active(True)
        self.assertIn('loc_id', shape_reader.search_by)
        # remove loc_id
        chk_btn.set_active(False)
        self.assertNotIn('loc_id', shape_reader.search_by)
        # have to add loc_id back in to allow removing loc_code
        chk_btn = settings_box.grid.check_buttons[0]
        chk_btn.set_active(True)
        # remove loc_code
        chk_btn = settings_box.grid.check_buttons[1]
        chk_btn.set_active(False)
        self.assertNotIn('loc_code', shape_reader.search_by)
        # NOTE: can't make search_by empty as it will just self populate with
        # the defaults if any of default fields exist in the dataset.

    def test_on_type_changed(self):
        shape_reader = ShapefileReader(create_shapefile('test',
                                                        prj_str_4326,
                                                        location_fields,
                                                        loc_recs_4326,
                                                        self.temp_dir.name))
        settings_box = ImpSetBox(shape_reader, grid=MockGrid())
        type_combo = type('MockComboBox', (object, ), {
            'get_active_text': lambda: 'plant'
        })
        settings_box.on_type_changed(type_combo)
        # assert the grid rebuilt with the same fields
        self.assertEqual(settings_box.grid.max_y, 5)
        self.assertEqual(settings_box.grid.max_x, 5)
        for i in location_fields:
            for j in i:
                self.assertIn(str(j), settings_box.grid.labels.keys())
        from bauble.prefs import LOC_DEFAULTS
        for i in LOC_DEFAULTS.get('fields').values():
            self.assertIn(i, settings_box.grid.props.keys())
        # assert the shape reader only contains the one matching field
        self.assertEqual('Note', shape_reader.field_map.get('field_note'))
        self.assertEqual(len(shape_reader.field_map), 1)


class ShapefileImportEmptyDBTests(BaubleTestCase):

    def setUp(self):
        super().setUp()
        get_default('system_proj_string', DEFAULT_SYS_PROJ)
        # somewhere to create test shapefiles
        self.temp_dir = TemporaryDirectory()
        self.importer = ShapefileImporter()
        self.importer.view.widgets.input_projection = 'input_projection'
        self.importer.view.widgets.input_filename = 'input_filename'
        self.importer.view.widgets.imp_settings_expander = type(
            'MockExpander', (object, ), {
                'get_child': lambda s: None,
                'add': lambda s, w: None,
                'remove': lambda s, w: None,
            }
        )()
        self.win = type('Win', (object, ), {'vals': ()})()
        self.importer.view.get_window = lambda: type(
            'MockWindow', (object, ), {
                'resize': lambda x, y: setattr(self.win, 'vals', (x, y))
            }
        )

    def tearDown(self):
        self.temp_dir.cleanup()
        super().tearDown()

    def test_add_or_update_all_location_records_succeeds(self):
        importer = self.importer
        importer.filename = create_shapefile('test',
                                             prj_str_4326,
                                             location_fields,
                                             loc_recs_4326,
                                             self.temp_dir.name)
        importer.shape_reader.filename = importer.filename
        importer.option = '4'
        importer.projection = 'epsg:4326'
        importer.run()
        result = self.session.query(Location).all()
        # assert len reflects new records
        self.assertEqual(len(result), 2)
        # assert db geojson added
        self.assertEqual(result[0].geojson, epsg4326_poly_xy)
        self.assertEqual(result[1].geojson, epsg4326_poly_xy2)
        # assert other data has changed.
        record = loc_recs_4326[0].get('record')
        self.assertEqual(result[0].description, record.get('descript'))
        self.assertEqual(result[0].name, record.get('name'))
        record = loc_recs_4326[1].get('record')
        self.assertEqual(result[1].description, record.get('descript'))
        self.assertEqual(result[1].name, record.get('name'))
        # check the note was imported
        self.assertEqual(len(result[0].notes), 1)
        self.assertEqual(len(result[1].notes), 0)

    def test_add_or_update_all_bulk_location_records_succeeds(self):
        importer = self.importer
        importer.filename = create_shapefile('test',
                                             prj_str_4326,
                                             location_fields,
                                             loc_recs_4326_bulk,
                                             self.temp_dir.name)
        importer.shape_reader.filename = importer.filename
        importer.option = '4'
        importer.projection = 'epsg:4326'
        importer.run()
        result = self.session.query(Location).all()
        # assert len reflects new records
        self.assertEqual(len(result), 30)
        # assert db geojson added
        self.assertEqual(result[0].geojson, epsg4326_poly_xy)

    def test_add_or_update_all_plant_records(self):
        # NOTE this produces a SQWaring - Fully NULL primary key.... Not
        # entirely sure why.  Cause is usually using something like
        # Plant.get(None)
        importer = self.importer
        importer.filename = create_shapefile('test',
                                             prj_str_3857,
                                             plant_fields,
                                             plt_rec_3857_points,
                                             self.temp_dir.name)
        importer.shape_reader.filename = importer.filename
        importer.option = '4'
        importer.projection = 'epsg:3857'
        importer.use_id = True
        importer.run()
        result = self.session.query(Plant).all()
        # plants should work on an empty DB if all data is provided
        self.assertEqual(len(result), len(plt_rec_3857_points))
        for record in plt_rec_3857_points:
            rec = record.get('record')
            plt = [p for p in result if p.id == rec.get('plt_id')][0]
            self.assertEqual(plt.accession.code, rec.get('accession'), msg=rec)
            self.assertEqual(plt.accession.species.sp, rec.get('species'))
            self.assertEqual(plt.accession.species.genus.genus,
                             rec.get('genus'))
            self.assertEqual(plt.accession.species.genus.family.family,
                             rec.get('family'))
            self.assertEqual(plt.quantity,
                             rec.get('quantity'))
            # test a planted change was added
            self.assertIsNotNone(plt.planted)
        self.assertEqual(len(result), len(plt_rec_3857_points))

    def test_add_or_update_all_plant_records_w_wrong_types(self):
        importer = self.importer
        importer.filename = create_shapefile('test',
                                             prj_str_3857,
                                             plant_fields_wrong_types,
                                             plt_rec_3857_points_wrong_types,
                                             self.temp_dir.name)
        importer.shape_reader.filename = importer.filename
        importer.option = '4'
        importer.projection = 'epsg:3857'
        importer.use_id = True
        importer.run()
        result = self.session.query(Plant).all()
        # Check we got the right amount of records
        self.assertEqual(len(result), len(plt_rec_3857_points_wrong_types))
        for record in plt_rec_3857_points_wrong_types:
            rec = record.get('record')
            plt = [p for p in result if p.id == int(rec.get('plt_id'))][0]
            self.assertEqual(plt.accession.code, str(rec.get('accession')))
            self.assertEqual(plt.accession.species.sp, rec.get('species'))
            self.assertEqual(plt.accession.species.genus.genus,
                             rec.get('genus'))
            self.assertEqual(plt.accession.species.genus.family.family,
                             rec.get('family'))
            self.assertEqual(plt.quantity,
                             rec.get('quantity'))
        self.assertEqual(len(result), len(plt_rec_3857_points_wrong_types))


class ShapefileImportTests(BaubleTestCase):

    def setUp(self):
        super().setUp()
        get_default('system_proj_string', DEFAULT_SYS_PROJ)
        data = ((Family, family_data),
                (Genus, genus_data),
                (Species, species_data),
                (VernacularName, vernacular_data),
                (DefaultVernacularName, default_vernacular_data),
                (Accession, accession_data),
                (Location, location_data),
                (LocationNote, loc_note_data),
                (Plant, plant_data),
                (PlantNote, plt_note_data))

        for klass, dics in data:
            for dic in dics:
                obj = klass(**dic)
                self.session.add(obj)
        self.session.commit()
        # somewhere to create test shapefiles
        self.temp_dir = TemporaryDirectory()
        # importer
        self.importer = ShapefileImporter()
        self.importer.view.widgets.input_projection = 'input_projection'
        self.importer.view.widgets.input_filename = 'input_filename'
        self.trap = type('Trap', (object, ), {'vals': 0})()
        self.importer.view.widgets.imp_settings_expander = type(
            'MockExpander', (object, ), {
                'get_child': lambda s: True,
                'add': lambda s, w: None,
                'remove': lambda s, i: setattr(self.trap, 'vals', 1),
            }
        )()
        self.win = type('MockWin', (object, ), {'vals': ()})()
        self.importer.view.get_window = lambda: type(
            'MockWindow', (object, ), {
                'resize': lambda x, y: setattr(self.win, 'vals', (x, y))
            }
        )

    def tearDown(self):
        self.temp_dir.cleanup()
        super().tearDown()

    def test_add_missing_geo_data_only(self):
        importer = self.importer
        importer.filename = create_shapefile('test', prj_str_4326,
                                             location_fields, loc_recs_4326,
                                             self.temp_dir.name)
        importer.shape_reader.filename = importer.filename
        importer.option = '0'
        importer.projection = 'epsg:4326'
        # test start
        importer.presenter.start = lambda: -5
        response = importer.start()
        self.assertEqual(response, -5)
        result = self.session.query(Location).all()
        # assert len hasn't changed
        self.assertEqual(len(result), 2)
        # assert db geojson == the shapfiles
        self.assertEqual(result[0].geojson, epsg4326_poly_xy)
        self.assertEqual(result[1].geojson, epsg4326_poly_xy2)
        # assert other data hasn't changed. Could be more thorough here.
        self.assertIsNone(result[0].description)
        self.assertIsNone(result[1].description)
        # added one note when creating the database, check the import didn't
        # bring in the other.
        self.assertEqual(len(result[0].notes), 1)

    def test_add_missing_geo_data_only_plants_always_xy_nonsys_crs(self):
        importer = self.importer
        importer.filename = create_shapefile('test',
                                             prj_str_3857,
                                             plant_fields,
                                             plt_rec_3857_points,
                                             self.temp_dir.name)
        importer.shape_reader.filename = importer.filename
        importer.option = '0'
        importer.always_xy = True
        importer.projection = 'epsg:3857'
        importer.run()
        result = self.session.query(Plant).all()
        # assert len hasn't changed
        self.assertEqual(len(result), 2)
        # assert db geojson == the shapfiles transformed
        data = transform(epsg3857_point, in_crs='epsg:3857',
                         out_crs='epsg:4326', always_xy=True)
        self.assertEqual(result[0].geojson, data)
        data = transform(epsg3857_point2, in_crs='epsg:3857',
                         out_crs='epsg:4326', always_xy=True)
        self.assertEqual(result[1].geojson, data)
        # assert other data hasn't changed. Could be more thorough here.
        self.assertEqual(result[0].quantity, 2)
        self.assertEqual(result[1].quantity, 2)
        # added one note when creating the database, check the import didn't
        # bring in the other.
        self.assertEqual(len(result[0].notes), 1)

    def test_add_missing_geo_data_only_doesnt_overwrite_existing(self):
        importer = self.importer
        # import some geojson
        importer.filename = create_shapefile('test', prj_str_4326,
                                             location_fields, loc_recs_4326,
                                             self.temp_dir.name)
        importer.shape_reader.filename = importer.filename
        importer.option = '0'
        importer.projection = 'epsg:4326'
        importer.run()
        # import different geojson
        importer.filename = create_shapefile('test', prj_str_4326,
                                             location_fields, loc_recs_4326_2,
                                             self.temp_dir.name)
        importer.shape_reader.filename = importer.filename
        importer.run()
        result = self.session.query(Location).all()
        # assert db geojson hasn't changed from first import
        self.assertEqual(result[0].geojson, epsg4326_poly_xy)
        self.assertEqual(result[1].geojson, epsg4326_poly_xy2)

    def test_update_geo_data_only_does_only_overwrite_geojson(self):
        importer = self.importer
        # import some geojson
        importer.filename = create_shapefile('test', prj_str_4326,
                                             location_fields, loc_recs_4326,
                                             self.temp_dir.name)
        importer.shape_reader.filename = importer.filename
        importer.option = '1'
        importer.projection = 'epsg:4326'
        importer.run()
        # import different geojson
        importer.filename = create_shapefile('test', prj_str_4326,
                                             location_fields, loc_recs_4326_2,
                                             self.temp_dir.name)
        importer.shape_reader.filename = importer.filename
        importer.run()
        result = self.session.query(Location).all()
        # assert len hasn't changed
        self.assertEqual(len(result), 2)
        # assert db geojson has changed to second import
        self.assertEqual(result[0].geojson, epsg4326_poly_xy2)
        self.assertEqual(result[1].geojson, epsg4326_poly_xy)
        # assert other data hasn't changed.
        self.assertIsNone(result[0].description)
        self.assertIsNone(result[1].description)
        # added one note when creating the database, check the import didn't
        # bring in the other.
        self.assertEqual(len(result[0].notes), 1)

    def test_add_or_update_all_data_existing_records(self):
        importer = self.importer
        # import existing records with some changes
        importer.filename = create_shapefile('test',
                                             prj_str_4326,
                                             location_fields,
                                             loc_recs_4326_diff_name_descript,
                                             self.temp_dir.name)
        importer.shape_reader.filename = importer.filename
        importer.option = '2'
        importer.projection = 'epsg:4326'
        importer.run()
        result = self.session.query(Location).all()
        # assert no new records added
        self.assertEqual(len(result), 2)
        # assert db geojson added
        self.assertEqual(result[0].geojson, epsg4326_poly_xy)
        self.assertEqual(result[1].geojson, epsg4326_poly_xy2)
        # assert same fields remained the same
        self.assertEqual(result[0].code, location_data[0].get('code'))
        self.assertEqual(result[1].code, location_data[1].get('code'))
        # assert other data has changed.
        record = loc_recs_4326_diff_name_descript[0].get('record')
        self.assertEqual(result[0].description, record.get('descript'))
        self.assertEqual(result[0].name, record.get('name'))
        record = loc_recs_4326_diff_name_descript[1].get('record')
        self.assertEqual(result[1].description, record.get('descript'))
        self.assertEqual(result[1].name, record.get('name'))
        # added one note when creating the database, check the import did
        # bring in the other.
        self.assertEqual(len(result[0].notes), 2)
        self.assertEqual(len(result[1].notes), 2)

    def test_add_note_with_category_specified(self):
        # have to trigger the filename change to be get the shape_reader
        importer = self.importer
        shpf_name = create_shapefile('test',
                                     prj_str_4326,
                                     location_fields,
                                     loc_recs_3857,
                                     self.temp_dir.name)
        importer.view.reply_file_chooser_dialog = [shpf_name]
        importer.presenter.on_btnbrowse_clicked('button')
        importer.presenter.on_filename_entry_changed('input_filename')
        # import existing records with some changes
        importer.option = '4'
        importer.projection = 'epsg:4326'
        importer.shape_reader.field_map[
            'field_note'] = 'Note[category="damage"]'
        importer.run()
        result = self.session.query(Location).all()
        # assert no new records added
        self.assertEqual(len(result), 2)
        # added one note when creating the database, check the import did
        # bring in the other.
        self.assertEqual(len(result[0].notes), 2)
        note_cats = [i.category for i in result[0].notes]
        self.assertIn('damage', note_cats)
        self.assertEqual(len(result[1].notes), 1)

    def test_add_new_records_only(self):
        importer = self.importer
        in_data = loc_recs_4326_diff_name_descript + loc_recs_4326_new_data
        importer.filename = create_shapefile('test',
                                             prj_str_4326,
                                             location_fields,
                                             in_data,
                                             self.temp_dir.name)
        importer.shape_reader.filename = importer.filename
        importer.option = '3'
        importer.projection = 'epsg:4326'
        importer.run()
        result = self.session.query(Location).all()
        # assert len reflects new records
        self.assertEqual(len(result), 4)
        # assert db geojson is not addded for existing records
        self.assertIsNone(result[0].geojson)
        self.assertIsNone(result[1].geojson)
        # assert the geojson did get addded for the new entries
        self.assertIsNotNone(result[2].geojson)
        self.assertIsNotNone(result[3].geojson)
        # assert original entries haven't changed
        self.assertTrue(
            all(getattr(result[0], k) == v for
                k, v in location_data[0].items())
        )
        self.assertTrue(
            all(getattr(result[1], k) == v for
                k, v in location_data[1].items())
        )
        # added one note when creating the database, check the import didn't
        # bring in the other.
        self.assertEqual(len(result[0].notes), 1)
        self.assertEqual(len(result[1].notes), 1)

    def test_skip_unknown_records(self):
        importer = self.importer
        in_data = loc_recs_4326_diff_name_descript + loc_recs_4326_new_data
        importer.filename = create_shapefile('test',
                                             prj_str_4326,
                                             location_fields,
                                             in_data,
                                             self.temp_dir.name)
        importer.shape_reader.filename = importer.filename
        importer.option = '0'
        importer.projection = 'epsg:4326'
        importer.run()
        result = self.session.query(Location).all()
        # assert len reflects no new records
        self.assertEqual(len(result), 2)
        # assert db geojson is addded for existing records
        self.assertIsNotNone(result[0].geojson)
        self.assertIsNotNone(result[1].geojson)
        # assert original entries haven't changed
        self.assertTrue(
            all(getattr(result[0], k) == v for
                k, v in location_data[0].items())
        )
        self.assertTrue(
            all(getattr(result[1], k) == v for
                k, v in location_data[1].items())
        )

    def test_add_or_update_all_records(self):
        importer = self.importer
        in_data = loc_recs_4326_diff_name_descript + loc_recs_4326_new_data
        importer.filename = create_shapefile('test',
                                             prj_str_4326,
                                             location_fields,
                                             in_data,
                                             self.temp_dir.name)
        importer.shape_reader.filename = importer.filename
        importer.option = '4'
        importer.projection = 'epsg:4326'
        importer.run()
        result = self.session.query(Location).all()
        # assert len reflects new records
        self.assertEqual(len(result), 4)
        # assert db geojson added
        self.assertEqual(result[0].geojson, epsg4326_poly_xy)
        self.assertEqual(result[1].geojson, epsg4326_poly_xy2)
        # assert the geojson did get addded for the new entries
        self.assertEqual(result[2].geojson, epsg4326_poly_xy)
        self.assertEqual(result[3].geojson, epsg4326_poly_xy2)
        # assert other data has changed.
        record = loc_recs_4326_diff_name_descript[0].get('record')
        self.assertEqual(result[0].description, record.get('descript'))
        self.assertEqual(result[0].name, record.get('name'))
        record = loc_recs_4326_diff_name_descript[1].get('record')
        self.assertEqual(result[1].description, record.get('descript'))
        self.assertEqual(result[1].name, record.get('name'))
        # added one note when creating the database, check the import did
        # bring in the other.
        self.assertEqual(len(result[0].notes), 2)
        self.assertEqual(len(result[1].notes), 2)
        # and that the new entries notes add up
        self.assertEqual(len(result[2].notes), 0)
        self.assertEqual(len(result[3].notes), 1)

    def test_add_or_update_all_records_commit_every(self):
        importer = self.importer
        in_data = loc_recs_4326_diff_name_descript + loc_recs_4326_new_data
        importer.filename = create_shapefile('test',
                                             prj_str_4326,
                                             location_fields,
                                             in_data,
                                             self.temp_dir.name)
        importer.shape_reader.filename = importer.filename
        importer.option = '4'
        importer.projection = 'epsg:4326'
        # add more coverage
        importer._commit_every = 2   # pylint: disable=protected-access
        importer.run()
        result = self.session.query(Location).all()
        # assert len reflects new records
        self.assertEqual(len(result), 4)
        # assert db geojson added
        self.assertEqual(result[0].geojson, epsg4326_poly_xy)
        self.assertEqual(result[1].geojson, epsg4326_poly_xy2)
        # assert the geojson did get addded for the new entries
        self.assertEqual(result[2].geojson, epsg4326_poly_xy)
        self.assertEqual(result[3].geojson, epsg4326_poly_xy2)
        # assert other data has changed.
        record = loc_recs_4326_diff_name_descript[0].get('record')
        self.assertEqual(result[0].description, record.get('descript'))
        self.assertEqual(result[0].name, record.get('name'))
        record = loc_recs_4326_diff_name_descript[1].get('record')
        self.assertEqual(result[1].description, record.get('descript'))
        self.assertEqual(result[1].name, record.get('name'))
        # added one note when creating the database, check the import did
        # bring in the other.
        self.assertEqual(len(result[0].notes), 2)
        self.assertEqual(len(result[1].notes), 2)
        # and that the new entries notes add up
        self.assertEqual(len(result[2].notes), 0)
        self.assertEqual(len(result[3].notes), 1)

    def test_add_or_update_all_records_plants_nonsys_crs_new_recs(self):
        importer = self.importer
        importer.filename = create_shapefile('test',
                                             prj_str_3857,
                                             plant_fields,
                                             plt_rec_3857_new_only_lines,
                                             self.temp_dir.name)
        importer.shape_reader.filename = importer.filename
        importer.option = '4'
        importer.projection = 'epsg:3857'
        importer.run()
        result = self.session.query(Plant).all()
        # assert len reflects new records
        self.assertEqual(len(result), 4)
        # assert db geojson == the shapfiles transformed
        data = transform(epsg3857_line, in_crs='epsg:3857',
                         out_crs='epsg:4326', always_xy=True)
        self.assertEqual(result[2].geojson, data)
        data = transform(epsg3857_line2, in_crs='epsg:3857',
                         out_crs='epsg:4326', always_xy=True)
        self.assertEqual(result[3].geojson, data)
        # assert other data has changed.
        record = plt_rec_3857_new_only_lines[0].get('record')
        self.assertEqual(result[2].accession.code, record.get('accession'))
        self.assertEqual(result[2].quantity, record.get('quantity'))
        self.assertEqual(result[2].location.code, record.get('bed'))
        record = plt_rec_3857_new_only_lines[1].get('record')
        self.assertEqual(result[3].accession.code, record.get('accession'))
        self.assertEqual(result[3].quantity, record.get('quantity'))
        self.assertEqual(result[3].location.code, record.get('bed'))
        # and that the new entries notes add up
        self.assertEqual(len(result[2].notes), 0)
        self.assertEqual(len(result[3].notes), 1)

    def test_add_or_update_all_records_plants_vernacular_names(self):
        importer = self.importer
        in_data = plt_rec_3857_points
        # try create a possible conflict where just wanting to swap the names,
        # this could potetntially create new species etc. when not needed.
        in_data[0]['record']['vernacular'] = 'Mountain Grey Gum'
        in_data[1]['record']['vernacular'] = 'Silky Oak'
        importer.filename = create_shapefile('test',
                                             prj_str_3857,
                                             plant_fields,
                                             in_data,
                                             self.temp_dir.name)
        importer.shape_reader.filename = importer.filename
        importer.option = '4'
        importer.projection = 'epsg:3857'
        importer.run()
        result = self.session.query(Plant).all()
        # assert len reflects no new plants records
        self.assertEqual(len(result), 2)
        species = self.session.query(Species).all()
        self.assertEqual(len(species), 2)
        self.assertEqual(species[0].str(remove_zws=True), 'Grevillea robusta')
        self.assertEqual(species[1].str(remove_zws=True), 'Eucalyptus major')
        self.assertEqual(species[0].default_vernacular_name.name,
                         'Mountain Grey Gum')
        self.assertEqual(species[1].default_vernacular_name.name,
                         'Silky Oak')
        # check the original name is still associated
        self.assertTrue('Mountain Grey Gum' in [i.name for i in
                                                species[1].vernacular_names])
        record = in_data[0].get('record')
        self.assertEqual(
            result[0].accession.species.default_vernacular_name.name,
            record.get('vernacular'))
        record = in_data[1].get('record')
        self.assertEqual(
            result[1].accession.species.default_vernacular_name.name,
            record.get('vernacular'))
        vernaculars = self.session.query(VernacularName).all()
        # should have created a new entry for each, only one gets a vernacular
        # name in setup data so should end up with 3
        self.assertEqual(len(vernaculars), 3)
        self.assertEqual(vernaculars[0].id, 1)
        self.assertEqual(vernaculars[1].id, 2)
        self.assertEqual(vernaculars[2].id, 3)
        self.assertEqual(vernaculars[0].species_id, 2)    # 2
        self.assertEqual(vernaculars[1].species_id, 1)    # 1
        self.assertEqual(vernaculars[2].species_id, 2)    # 2
        self.assertEqual(vernaculars[0].name, 'Mountain Grey Gum')
        self.assertEqual(vernaculars[1].name, 'Mountain Grey Gum')
        self.assertEqual(vernaculars[2].name, 'Silky Oak')
        # assert there is only the 2 default_vernacular_names
        default_vernaculars = self.session.query(DefaultVernacularName).all()
        self.assertEqual(len(default_vernaculars), 2)

    def test_add_or_update_all_records_plants_vernacular_names_w_lang(self):
        importer = self.importer
        in_data = plt_rec_3857_points
        # try create a possible conflict where just wanting to swap the names,
        # and also add a language
        in_data[0]['record']['vernacular'] = 'Mountain Grey Gum:EN'
        in_data[1]['record']['vernacular'] = 'Silky Oak:EN'
        importer.filename = create_shapefile('test',
                                             prj_str_3857,
                                             plant_fields,
                                             in_data,
                                             self.temp_dir.name)
        importer.shape_reader.filename = importer.filename
        importer.option = '4'
        importer.projection = 'epsg:3857'
        importer.run()
        result = self.session.query(Plant).all()
        # assert len reflects no new plants records
        self.assertEqual(len(result), 2)
        species = self.session.query(Species).all()
        self.assertEqual(len(species), 2)
        self.assertEqual(species[0].str(remove_zws=True), 'Grevillea robusta')
        self.assertEqual(species[1].str(remove_zws=True), 'Eucalyptus major')
        self.assertEqual(species[0].default_vernacular_name.name,
                         'Mountain Grey Gum')
        self.assertEqual(species[0].default_vernacular_name.language, 'EN')
        self.assertEqual(species[1].default_vernacular_name.name,
                         'Silky Oak')
        self.assertEqual(species[0].default_vernacular_name.language, 'EN')
        # check the original name is still associated
        self.assertTrue('Mountain Grey Gum' in [i.name for i in
                                                species[1].vernacular_names])
        record = in_data[0].get('record')
        self.assertEqual(
            result[0].accession.species.default_vernacular_name.name,
            record.get('vernacular').split(':')[0])
        record = in_data[1].get('record')
        self.assertEqual(
            result[1].accession.species.default_vernacular_name.name,
            record.get('vernacular').split(':')[0])
        vernaculars = self.session.query(VernacularName).all()
        # should have created a new entry for each, only one gets a vernacular
        # name in setup data so should end up with 3
        self.assertEqual(len(vernaculars), 3)
        self.assertEqual(vernaculars[0].id, 1)
        self.assertEqual(vernaculars[1].id, 2)
        self.assertEqual(vernaculars[2].id, 3)
        self.assertEqual(vernaculars[0].species_id, 2)
        self.assertEqual(vernaculars[1].species_id, 1)
        self.assertEqual(vernaculars[2].species_id, 2)
        self.assertEqual(vernaculars[0].name, 'Mountain Grey Gum')
        self.assertEqual(vernaculars[1].name, 'Mountain Grey Gum')
        self.assertEqual(vernaculars[1].language, 'EN')
        self.assertEqual(vernaculars[2].name, 'Silky Oak')
        self.assertEqual(vernaculars[2].language, 'EN')
        # assert there is only the 2 default_vernacular_names
        default_vernaculars = self.session.query(DefaultVernacularName).all()
        self.assertEqual(len(default_vernaculars), 2)

    def test_add_or_update_all_records_plants_complex_names(self):
        importer = self.importer
        in_data = plt_rec_3857_points + plt_rec_3857_points_new_complex_sp
        in_data[0]['record']['vernacular'] = 'Test Adding To Existing'
        in_data[1]['record']['vernacular'] = 'Test Changing Existing'
        importer.filename = create_shapefile('test',
                                             prj_str_3857,
                                             plant_fields,
                                             in_data,
                                             self.temp_dir.name)
        importer.shape_reader.filename = importer.filename
        importer.option = '4'
        importer.projection = 'epsg:3857'
        importer.run()
        result = self.session.query(Plant).all()
        # assert len reflects new records (2 originals + 3 new)
        self.assertEqual(len(result), 5)
        species = self.session.query(Species).all()
        self.assertEqual(len(species), 5)
        # assert other data has changed.
        record = in_data[0].get('record')
        self.assertEqual(
            result[0].accession.species.default_vernacular_name.name,
            record.get('vernacular'))
        record = in_data[1].get('record')
        self.assertEqual(
            result[1].accession.species.default_vernacular_name.name,
            record.get('vernacular'))

        record = in_data[2].get('record')
        self.assertEqual(result[2].accession.code, record.get('accession'))
        self.assertEqual(result[2].code, record.get('plt_code'))
        self.assertEqual(result[2].quantity, record.get('quantity'))
        self.assertEqual(result[2].location.code, record.get('bed'))
        self.assertEqual(result[2].accession.species.genus.family.epithet,
                         record.get('family'))
        self.assertEqual(result[2].accession.species.genus.epithet,
                         record.get('genus'))
        self.assertEqual(result[2].accession.species.epithet,
                         record.get('species'))
        # Testing that we can use hybrid_property values here and below
        self.assertEqual(result[2].accession.species.infraspecific_parts,
                         record.get('infrasp'))
        self.assertEqual(result[2].accession.species.cultivar_epithet,
                         record.get('cultivar'))

        record = in_data[3].get('record')
        self.assertEqual(result[3].accession.code, record.get('accession'))
        self.assertEqual(result[3].code, record.get('plt_code'))
        self.assertEqual(result[3].quantity, record.get('quantity'))
        self.assertEqual(result[3].location.code, record.get('bed'))
        self.assertEqual(result[3].accession.species.genus.family.epithet,
                         record.get('family'))
        #
        self.assertEqual(result[3].accession.species.genus.epithet,
                         record.get('genus'))
        self.assertEqual(result[3].accession.species.epithet,
                         record.get('species'))

        record = in_data[4].get('record')
        self.assertEqual(result[4].accession.code, record.get('accession'))
        self.assertEqual(result[4].code, record.get('plt_code'))
        self.assertEqual(result[4].quantity, record.get('quantity'))
        self.assertEqual(result[4].location.code, record.get('bed'))
        self.assertEqual(result[4].accession.species.genus.family.epithet,
                         record.get('family'))
        self.assertEqual(result[4].accession.species.genus.epithet,
                         record.get('genus'))
        self.assertEqual(result[4].accession.species.epithet,
                         record.get('species'))
        self.assertEqual(result[4].accession.species.infraspecific_parts,
                         record.get('infrasp'))
        self.assertEqual(
            result[4].accession.species.default_vernacular_name.name,
            record.get('vernacular'))
        # and that the new entries notes add up
        self.assertEqual(len(result[2].notes), 1)
        self.assertEqual(len(result[3].notes), 1)
        self.assertEqual(len(result[4].notes), 1)

    def test_add_or_update_all_records_plants_some_bad_records(self):
        importer = self.importer
        in_data = plt_rec_3857_points + plt_rec_3857_points_new_some_bad
        importer.filename = create_shapefile('test',
                                             prj_str_3857,
                                             plant_fields,
                                             in_data,
                                             self.temp_dir.name)
        importer.shape_reader.filename = importer.filename
        importer.option = '4'
        importer.projection = 'epsg:3857'
        importer.run()
        result = self.session.query(Plant).all()
        # assert len reflects new records
        self.assertEqual(len(result), 4)
        # assert db geojson == the shapfiles transformed
        data = transform(epsg3857_point, in_crs='epsg:3857',
                         out_crs='epsg:4326', always_xy=True)
        self.assertEqual(result[0].geojson, data)
        data = transform(epsg3857_point2, in_crs='epsg:3857',
                         out_crs='epsg:4326', always_xy=True)
        self.assertEqual(result[1].geojson, data)
        data = transform(epsg3857_point, in_crs='epsg:3857',
                         out_crs='epsg:4326', always_xy=True)
        self.assertEqual(result[2].geojson, data)
        # assert other data has changed.
        record = in_data[0].get('record')
        self.assertEqual(result[0].accession.code, record.get('accession'))
        self.assertEqual(result[0].quantity, record.get('quantity'))
        self.assertEqual(result[0].location.code, record.get('bed'))
        record = in_data[1].get('record')
        self.assertEqual(result[1].accession.code, record.get('accession'))
        self.assertEqual(result[1].quantity, record.get('quantity'))
        self.assertEqual(result[1].location.code, record.get('bed'))
        record = in_data[3].get('record')
        self.assertEqual(result[2].accession.code, record.get('accession'))
        self.assertEqual(result[2].quantity, record.get('quantity'))
        self.assertEqual(result[2].location.code, record.get('bed'))
        # and that the new entries notes add up
        self.assertEqual(len(result[0].notes), 2)
        self.assertEqual(len(result[2].notes), 0)

    def test_add_or_update_all_records_failed_transform(self):
        # make sure test update also - add some base data
        rec1 = self.session.query(Location).get(1)
        rec1.geojson = epsg3857_poly
        self.session.add(rec1)
        self.session.commit()

        importer = self.importer
        in_data = loc_recs_4326_diff_name_descript + loc_recs_4326_new_data
        importer.filename = create_shapefile('test',
                                             prj_str_4326,
                                             location_fields,
                                             in_data,
                                             self.temp_dir.name)
        importer.shape_reader.filename = importer.filename
        importer.option = '4'
        importer.projection = 'epsg:4326'
        # should fail transforming from 4326 to 3857 without always_xy
        importer.always_xy = False
        # set the system projection string
        from bauble.meta import BaubleMeta
        sys_proj = self.session.query(BaubleMeta).filter_by(
            name='system_proj_string').one()
        sys_proj.value = 'epsg:3857'
        self.session.commit()
        importer.run()
        result = self.session.query(Location).all()
        # assert len reflects no additions
        self.assertEqual(len(result), 2)
        # assert db geojson wasn't added
        self.assertEqual(result[0].geojson, epsg3857_poly)  # remained same
        self.assertIsNone(result[1].geojson)
        # assert other data hasn't changed.
        # assert other data hasn't changed.
        self.assertIsNone(result[0].description)
        self.assertIsNone(result[1].description)
        # added one note when creating the database, check the import didn't
        # bring in the other.
        self.assertEqual(len(result[0].notes), 1)
        self.assertEqual(len(result[1].notes), 1)

    def test_add_or_update_all_records_plants_nonsys_crs_by_id(self):
        importer = self.importer
        importer.filename = create_shapefile('test',
                                             prj_str_3857,
                                             plant_fields,
                                             plt_rec_3857_new_data_lines,
                                             self.temp_dir.name)
        importer.shape_reader.filename = importer.filename
        importer.option = '4'
        importer.use_id = True
        importer.projection = 'epsg:3857'
        importer.run()
        result = self.session.query(Plant).all()
        # assert len reflects new records
        self.assertEqual(len(result), 4)
        # assert db geojson == the shapfiles transformed
        data = transform(epsg3857_line2, in_crs='epsg:3857',
                         out_crs='epsg:4326', always_xy=True)
        self.assertEqual(result[0].geojson, data)
        data = transform(epsg3857_line, in_crs='epsg:3857',
                         out_crs='epsg:4326', always_xy=True)
        self.assertEqual(result[1].geojson, data)
        data = transform(epsg3857_line, in_crs='epsg:3857',
                         out_crs='epsg:4326', always_xy=True)
        self.assertEqual(result[2].geojson, data)
        data = transform(epsg3857_line2, in_crs='epsg:3857',
                         out_crs='epsg:4326', always_xy=True)
        self.assertEqual(result[3].geojson, data)
        # assert other data has changed.
        record = plt_rec_3857_new_data_lines[0].get('record')
        self.assertEqual(result[0].id, record.get('plt_id'))
        self.assertEqual(result[0].accession.code, record.get('accession'))
        self.assertEqual(result[0].quantity, record.get('quantity'))
        self.assertEqual(result[0].location.code, record.get('bed'))
        record = plt_rec_3857_new_data_lines[1].get('record')
        self.assertEqual(result[1].id, record.get('plt_id'))
        self.assertEqual(result[1].accession.code, record.get('accession'))
        self.assertEqual(result[1].quantity, record.get('quantity'))
        self.assertEqual(result[1].location.code, record.get('bed'))
        record = plt_rec_3857_new_data_lines[2].get('record')
        self.assertEqual(result[2].id, record.get('plt_id'))
        self.assertEqual(result[2].accession.code, record.get('accession'))
        self.assertEqual(result[2].quantity, record.get('quantity'))
        self.assertEqual(result[2].location.code, record.get('bed'))
        record = plt_rec_3857_new_data_lines[3].get('record')
        self.assertEqual(result[3].id, record.get('plt_id'))
        self.assertEqual(result[3].accession.code, record.get('accession'))
        self.assertEqual(result[3].quantity, record.get('quantity'))
        self.assertEqual(result[3].location.code, record.get('bed'))
        # and that the new entries notes add up
        self.assertEqual(len(result[2].notes), 0)
        self.assertEqual(len(result[3].notes), 1)

    def test_search_by_is_id(self):
        importer = self.importer
        from copy import deepcopy
        loc_altered = deepcopy(loc_recs_4326)
        loc_altered[0]['record']['loc_code'] = 'XYZ10'
        loc_altered[0]['record']['descript'] = 'Test this change'
        shpf_name = create_shapefile('test_altered', prj_str_4326,
                                     location_fields, loc_altered,
                                     self.temp_dir.name)
        importer.view.reply_file_chooser_dialog = [shpf_name]
        importer.presenter.on_btnbrowse_clicked('button')
        importer.option = '4'
        importer.presenter.on_filename_entry_changed('input_filename')
        importer.shape_reader.search_by.add('loc_id')\
            # pylint: disable=no-member
        importer.shape_reader.search_by.remove('loc_code')
        importer.projection = 'epsg:4326'
        importer.run()
        result = self.session.query(Location).all()
        # assert len hasn't changed
        self.assertEqual(len(result), 2)
        # assert db geojson == the shapfiles
        self.assertEqual(result[0].geojson, epsg4326_poly_xy)
        self.assertEqual(result[1].geojson, epsg4326_poly_xy2)
        # assert other data hasn't changed.  Could be more thorough here.
        self.assertEqual(result[0].description, 'Test this change')
        self.assertEqual(result[0].code, 'XYZ10')
        self.assertEqual(result[1].code, 'APC01')

    def test_use_id(self):
        importer = self.importer
        importer.filename = create_shapefile('test', prj_str_4326,
                                             location_fields, loc_recs_4326,
                                             self.temp_dir.name)
        importer.shape_reader.filename = importer.filename
        importer.option = '0'
        importer.use_id = True
        importer.projection = 'epsg:4326'
        # test start
        importer.presenter.start = lambda: -5
        importer.start()
        # importer.run()
        result = self.session.query(Location).all()
        # assert len hasn't changed
        self.assertEqual(len(result), 2)
        # assert db geojson == the shapfiles
        self.assertEqual(result[0].geojson, epsg4326_poly_xy)
        self.assertEqual(result[1].geojson, epsg4326_poly_xy2)
        # assert other data hasn't changed.  Could be more thorough here.
        self.assertIsNone(result[0].description)
        self.assertIsNone(result[1].description)
        # added one note when creating the database, check the import didn't
        # bring in the other.
        self.assertEqual(len(result[0].notes), 1)
        # importer.use_id = False

    def test_on_btnbrowse_clicked(self):
        importer = self.importer
        shpf_name = create_shapefile('test', prj_str_4326, location_fields,
                                     loc_recs_4326, self.temp_dir.name)
        importer.view.reply_file_chooser_dialog = [shpf_name]
        importer.presenter.on_btnbrowse_clicked('button')
        importer.presenter.on_filename_entry_changed('input_filename')
        self.assertEqual(importer.filename, shpf_name)
        self.assertEqual(importer.presenter.last_folder,
                         str(Path(shpf_name).parent))
        self.assertEqual(importer.presenter.proj_db_match,
                         importer.presenter.proj_db.get_crs(prj_str_4326))
        # this just test that remove was called.
        self.assertEqual(self.trap.vals, 1)

    def test_on_btnbrowse_clicked_matched_crs(self):
        importer = self.importer
        importer.presenter.proj_db.add(prj=prj_str_4326, crs='epsg:4326')
        shpf_name = create_shapefile('test', prj_str_4326, location_fields,
                                     loc_recs_4326, self.temp_dir.name)
        importer.view.reply_file_chooser_dialog = [shpf_name]
        importer.presenter.on_btnbrowse_clicked('button')
        importer.presenter.on_filename_entry_changed('input_filename')
        self.assertIn('widget_set_text', importer.view.invoked)
        self.assertIn(('widget_set_text', ('input_projection', 'epsg:4326')),
                      importer.view.invoked_detailed)
        self.assertIn('widget_set_active', importer.view.invoked)
        self.assertIn(('widget_set_active', ('cb_always_xy', True)),
                      importer.view.invoked_detailed)
        self.assertEqual(importer.filename, shpf_name)
        self.assertEqual(importer.presenter.last_folder,
                         str(Path(shpf_name).parent))
        self.assertEqual(importer.presenter.proj_db_match,
                         importer.presenter.proj_db.get_crs(prj_str_4326))

    def test_on_btnbrowse_clicked_bad_file(self):
        importer = self.importer
        importer.presenter.proj_db.add(prj=prj_str_4326, crs='epsg:4326')
        bad_file = Path(f'{self.temp_dir.name}/bad.zip')
        bad_file.touch()
        importer.view.reply_file_chooser_dialog = [bad_file]
        importer.presenter.on_btnbrowse_clicked('button')
        importer.presenter.on_filename_entry_changed('input_filename')

        # Should still store the last folder if it exists and has a zip ext
        self.assertEqual(importer.presenter.last_folder,
                         str(Path(bad_file).parent))
        with TemporaryDirectory() as tmp:
            bad_file = Path(f'{tmp}/bad.txt')
            bad_file.touch()
            importer.view.reply_file_chooser_dialog = [bad_file]
            importer.presenter.on_btnbrowse_clicked('button')
            importer.presenter.on_filename_entry_changed('input_filename')
            # Should not store the last folder as not a zip file
            self.assertNotEqual(importer.presenter.last_folder,
                                str(Path(bad_file).parent))
            self.assertIn((importer.presenter.PROBLEM_NOT_SHAPEFILE,
                          'input_filename'), importer.presenter.problems)

    def test_on_always_xy_toggled(self):
        importer = self.importer
        importer.presenter.proj_db.add(prj=prj_str_4326, crs='epsg:4326')
        shpf_name = create_shapefile('test', prj_str_4326, location_fields,
                                     loc_recs_4326, self.temp_dir.name)
        importer.filename = shpf_name
        importer.projection = 'epsg:4326'
        importer.presenter.proj_text = 'epsg:4326'
        importer.presenter.proj_db_match = 'epsg:4326'
        importer.presenter.prj_string = prj_str_4326
        # start = importer.presenter.proj_db.get_always_xy(prj_str_4326)
        importer.presenter.on_always_xy_toggled('cb_always_xy', value=True)
        self.assertTrue(importer.presenter.proj_db.get_always_xy(prj_str_4326))
        importer.presenter.on_always_xy_toggled('cb_always_xy', value=False)
        self.assertFalse(
            importer.presenter.proj_db.get_always_xy(prj_str_4326))

    def test_on_projection_changed(self):
        importer = self.importer
        importer.presenter.proj_text = 'epsg:4326'
        # doesn't work, other than return it to its default value
        importer.presenter.on_projection_changed('input_projection',
                                                 value='epsg:3857')
        self.assertEqual(importer.presenter.proj_text, 'epsg:3857')
        self.assertIn('set_button_label', importer.view.invoked)
        self.assertIn(('set_button_label', ('projection_button', 'Add?')),
                      importer.view.invoked_detailed)
        importer.presenter.proj_db_match = 'epsg:3857'
        importer.presenter.on_projection_changed('input_projection',
                                                 value='epsg:3857')
        self.assertIn(('set_button_label', ('projection_button', 'CORRECT')),
                      importer.view.invoked_detailed)
        importer.presenter.proj_db_match = 'epsg:4326'
        importer.presenter.on_projection_changed('input_projection',
                                                 value='epsg:3857')
        self.assertIn(('set_button_label', ('projection_button', 'Change?')),
                      importer.view.invoked_detailed)

    def test_on_projection_btn_clicked(self):
        importer = self.importer
        importer.presenter.proj_db.add(prj=prj_str_4326, crs='epsg:4326')
        shpf_name = create_shapefile('test', prj_str_4326, location_fields,
                                     loc_recs_4326, self.temp_dir.name)
        importer.filename = shpf_name
        importer.projection = 'epsg:test'
        importer.presenter.proj_text = 'epsg:test'
        importer.presenter.proj_db_match = 'epsg:4326'
        importer.presenter.prj_string = prj_str_4326
        importer.view.widgets.input_projection = 'input_projection'
        importer.presenter.on_projection_btn_clicked('projection_button')
        self.assertEqual(importer.presenter.proj_db.get_crs(prj_str_4326),
                         'epsg:test')
        self.assertIn(('set_button_label', ('projection_button', 'Change?')),
                      importer.view.invoked_detailed)
        # Test adding a new entry
        prj_str = 'PROJCS["test2"]'
        importer.presenter.prj_string = prj_str
        importer.presenter.proj_text = 'epsg:test2'
        importer.presenter.proj_db_match = None
        importer.presenter.on_projection_changed('input_projection',
                                                 value='epsg:test2')
        importer.projection = 'epsg:test2'
        importer.view.widgets.input_projection = 'input_projection'
        importer.presenter.on_projection_btn_clicked('projection_button')
        self.assertEqual(importer.presenter.proj_db.get_crs(prj_str),
                         'epsg:test2')
        self.assertIn(('set_button_label', ('projection_button', 'Add?')),
                      importer.view.invoked_detailed)

    def test_import_tool(self):
        # somewhat superfluous
        import_tool = ShapefileImportTool()

        importer = import_tool.start()
        importer.filename = create_shapefile('test', prj_str_4326,
                                             location_fields, loc_recs_4326,
                                             self.temp_dir.name)
        importer.shape_reader.filename = importer.filename
        importer.option = '0'
        importer.use_id = True
        importer.projection = 'epsg:4326'
        importer.run()
        result = self.session.query(Location).all()
        # assert len hasn't changed
        self.assertEqual(len(result), 2)
        # assert db geojson == the shapfiles
        self.assertEqual(result[0].geojson, epsg4326_poly_xy)
        self.assertEqual(result[1].geojson, epsg4326_poly_xy2)
        # assert other data hasn't changed.  Could be more thorough here.
        self.assertIsNone(result[0].description)
        self.assertIsNone(result[1].description)
        # added one note when creating the database, check the import didn't
        # bring in the other.
        self.assertEqual(len(result[0].notes), 1)

    def test_on_settings_activate(self):
        # somewhat superfluous
        importer = self.importer
        importer.presenter.on_settings_activate('imp_settings_expander')
        importer.presenter.on_filename_entry_changed('input_filename')
        self.assertEqual(self.win.vals, (1, 1))


class ShapefileReaderTests(BaubleTestCase):
    def setUp(self):
        super().setUp()
        self.temp_dir = TemporaryDirectory()

    def tearDown(self):
        self.temp_dir.cleanup()
        super().tearDown()

    def test_get_prj_string_from_file(self):
        prj_str = 'PROJCS["test1"]'

        # Working example
        base_name = 'test1'
        prj_file = Path(f'{self.temp_dir.name}/{base_name}.prj')
        with open(prj_file, 'w') as prj:
            prj.write(prj_str)
            prj.close()
        zip_path = f'{self.temp_dir.name}/{base_name}.zip'
        with ZipFile(zip_path, 'w') as z:
            z.write(prj_file, arcname=prj_file.name)
        shape_reader = ShapefileReader(zip_path)
        self.assertEqual(shape_reader.get_prj_string(), prj_str)

    def test_prj_string_changes_when_file_changes(self):
        prj_str = 'PROJCS["test1"]'
        prj_str2 = 'PROJCS["test2"]'
        base_name = 'test1'
        base_name2 = 'test2'

        # Working example
        prj_file = Path(f'{self.temp_dir.name}/{base_name}.prj')
        prj_file2 = Path(f'{self.temp_dir.name}/{base_name2}.prj')
        with open(prj_file, 'w') as prj, open(prj_file2, 'w') as prj2:
            prj.write(prj_str)
            prj2.write(prj_str2)
            prj.close()
            prj2.close()
        zip_path = f'{self.temp_dir.name}/{base_name}.zip'
        zip_path2 = f'{self.temp_dir.name}/{base_name2}.zip'
        with ZipFile(zip_path, 'w') as z, ZipFile(zip_path2, 'w') as z2:
            z.write(prj_file, arcname=prj_file.name)
            z2.write(prj_file2, arcname=prj_file2.name)
        shape_reader = ShapefileReader(zip_path)
        self.assertEqual(shape_reader.get_prj_string(), prj_str)
        shape_reader.filename = zip_path2
        self.assertNotEqual(shape_reader.get_prj_string(), prj_str)
        self.assertEqual(shape_reader.get_prj_string(), prj_str2)

    def test_prj_string_is_none_when_file_changes_to_bad_file(self):
        prj_str = 'PROJCS["test1"]'
        base_name = 'test1'

        # Working example
        prj_file = Path(f'{self.temp_dir.name}/{base_name}.prj')
        with open(prj_file, 'w') as prj:
            prj.write(prj_str)
            prj.close()
        zip_path = f'{self.temp_dir.name}/{base_name}.zip'
        zip_path2 = f'{self.temp_dir.name}/NO_FILE.zip'
        with ZipFile(zip_path, 'w') as z:
            z.write(prj_file, arcname=prj_file.name)
        shape_reader = ShapefileReader(zip_path)
        self.assertEqual(shape_reader.get_prj_string(), prj_str)
        shape_reader.filename = zip_path2
        self.assertNotEqual(shape_reader.get_prj_string(), prj_str)
        self.assertIsNone(shape_reader.get_prj_string())

    def test_get_prj_string_with_empty_prj_file(self):
        # empty prj file
        base_name = 'test2'
        prj_file = Path(f'{self.temp_dir.name}/{base_name}.prj')
        prj_file.touch()

        zip_path = f'{self.temp_dir.name}/{base_name}.zip'
        with ZipFile(zip_path, 'w') as z:
            z.write(prj_file, arcname=prj_file.name)
        shape_reader = ShapefileReader(zip_path)
        self.assertIsNone(shape_reader.get_prj_string())

    def test_get_prj_string_with_no_file(self):
        # no file
        zip_path = f'{self.temp_dir.name}/NO_FILE.zip'
        shape_reader = ShapefileReader(zip_path)
        self.assertIsNone(shape_reader.get_prj_string())

    def test_get_prj_string_with_no_prj_file(self):
        prj_str = 'PROJCS["test1"]'
        # not prj file
        base_name = 'test3'
        no_prj = Path(f'{self.temp_dir.name}/{base_name}.shp')
        with open(no_prj, 'w') as f:
            f.write(prj_str)
            f.close()
        zip_path = f'{self.temp_dir.name}/{base_name}.zip'
        with ZipFile(zip_path, 'w') as z:
            z.write(no_prj, arcname=no_prj.name)
        shape_reader = ShapefileReader(zip_path)
        self.assertIsNone(shape_reader.get_prj_string())

    def test_get_prj_string_with_empty_zip_file(self):
        # empty zip file
        base_name = 'test2'
        zip_path = Path(f'{self.temp_dir.name}/{base_name}.zip')
        zip_path.touch()
        shape_reader = ShapefileReader(zip_path)
        self.assertIsNone(shape_reader.get_prj_string())
        self.assertFalse(shape_reader.search_by)
        self.assertFalse(shape_reader.field_map)

    def test_get_fields_from_file(self):
        # Working example
        shape_reader = ShapefileReader(create_shapefile('test',
                                                        prj_str_4326,
                                                        location_fields,
                                                        loc_recs_4326,
                                                        self.temp_dir.name))
        fields = shape_reader.get_fields()

        for i in location_fields:
            self.assertIn(i[0], [j[0] for j in fields])

    def test_get_fields_from_file2(self):
        # Working example 2
        shape_reader = ShapefileReader(
            create_shapefile('test',
                             prj_str_3857,
                             plant_fields,
                             plt_rec_3857_new_data_lines,
                             self.temp_dir.name))
        fields = shape_reader.get_fields()

        for i in plant_fields:
            self.assertIn(i[0], [j[0] for j in fields])

    def test_fields_change_when_file_changes(self):
        shape_reader = ShapefileReader(
            create_shapefile('test',
                             prj_str_4326,
                             location_fields,
                             loc_recs_4326,
                             self.temp_dir.name)
        )
        fields = shape_reader.get_fields()
        for i in location_fields:
            self.assertIn(i[0], [j[0] for j in fields])
        # change file
        shape_reader.filename = create_shapefile('test',
                                                 prj_str_3857,
                                                 plant_fields,
                                                 plt_rec_3857_points,
                                                 self.temp_dir.name)
        fields = shape_reader.get_fields()
        for i in plant_fields:
            self.assertIn(i[0], [j[0] for j in fields])

    def test_fields_empty_when_file_changes_to_bad_file(self):
        shape_reader = ShapefileReader(
            create_shapefile('test',
                             prj_str_4326,
                             location_fields,
                             loc_recs_4326,
                             self.temp_dir.name)
        )
        fields = shape_reader.get_fields()
        for i in location_fields:
            self.assertIn(i[0], [j[0] for j in fields])
        # change file to bad name
        shape_reader.filename = f'{self.temp_dir.name}/NO_FILE.zip'
        self.assertFalse(shape_reader.get_fields())
        self.assertFalse(shape_reader.field_map)
        self.assertFalse(shape_reader.search_by)
        self.assertEqual(shape_reader.get_records_count(), 0)

    def test_get_fields_with_no_file(self):
        shape_reader = ShapefileReader(f'{self.temp_dir.name}/NO_FILE.zip')
        self.assertFalse(shape_reader.get_fields())

    def test_get_field_with_empty_file(self):
        # empty file
        zip_path = Path(f'{self.temp_dir.name}/EMPTY.zip')
        zip_path.touch()
        shape_reader = ShapefileReader(zip_path)
        self.assertFalse(shape_reader.get_fields())

    def test_sets_type_from_file(self):
        shape_reader = ShapefileReader(
            create_shapefile('test',
                             prj_str_4326,
                             location_fields,
                             loc_recs_4326,
                             self.temp_dir.name)
        )
        self.assertEqual(shape_reader.type, 'location')

    def test_type_changes_when_file_changes(self):
        shape_reader = ShapefileReader(
            create_shapefile('test',
                             prj_str_4326,
                             location_fields,
                             loc_recs_4326,
                             self.temp_dir.name)
        )
        self.assertEqual(shape_reader.type, 'location')
        # change file (even though its the same name)
        shape_reader.filename = create_shapefile('test',
                                                 prj_str_3857,
                                                 plant_fields,
                                                 plt_rec_3857_points,
                                                 self.temp_dir.name)
        self.assertEqual(shape_reader.type, 'plant')

    def test_get_search_by_from_file(self):
        shape_reader = ShapefileReader(
            create_shapefile('test',
                             prj_str_4326,
                             location_fields,
                             loc_recs_4326,
                             self.temp_dir.name)
        )
        from bauble.prefs import LOC_DEFAULTS
        self.assertEqual(shape_reader.search_by,
                         set(LOC_DEFAULTS.get('search_by')))

    def test_get_field_map_from_file(self):
        shape_reader = ShapefileReader(
            create_shapefile('test',
                             prj_str_4326,
                             location_fields,
                             loc_recs_4326,
                             self.temp_dir.name)
        )
        from bauble.prefs import LOC_DEFAULTS
        self.assertEqual(shape_reader.field_map, LOC_DEFAULTS.get('fields'))

    def test_change_object_type(self):
        shape_reader = ShapefileReader(
            create_shapefile('test',
                             prj_str_3857,
                             plant_fields,
                             plt_rec_3857_new_data_lines,
                             self.temp_dir.name))
        start_search_by = shape_reader.search_by
        start_field_map = shape_reader.field_map
        start_type = shape_reader.type
        new_search_by = ['loc_id']
        new_field_map = {'loc_id': 'id',
                         'accession': 'accession.code'}
        new_type = 'location'
        shape_reader.type = new_type
        shape_reader.search_by = new_search_by
        shape_reader.field_map = new_field_map

        self.assertNotEqual(start_search_by, shape_reader.search_by)
        self.assertNotEqual(start_field_map, shape_reader.field_map)
        self.assertNotEqual(start_type, shape_reader.type)
        self.assertEqual(new_search_by, shape_reader.search_by)
        self.assertEqual(new_field_map, shape_reader.field_map)
        self.assertEqual(new_type, shape_reader.type)

    def test_changes_not_retained_when_file_changes(self):
        shape_reader = ShapefileReader(
            create_shapefile('test',
                             prj_str_3857,
                             plant_fields,
                             plt_rec_3857_new_data_lines,
                             self.temp_dir.name))
        new_search_by = ['loc_id']
        new_field_map = {'loc_id': 'id',
                         'accession': 'accession.code'}
        new_type = 'location'
        shape_reader.type = new_type
        shape_reader.search_by = new_search_by
        shape_reader.field_map = new_field_map
        self.assertEqual(new_search_by, shape_reader.search_by)
        self.assertEqual(new_field_map, shape_reader.field_map)
        self.assertEqual(new_type, shape_reader.type)
        shape_reader.filename = create_shapefile('test2',
                                                 prj_str_3857,
                                                 plant_fields,
                                                 plt_rec_3857_points,
                                                 self.temp_dir.name)

        self.assertNotEqual(new_search_by, shape_reader.search_by)
        self.assertNotEqual(new_field_map, shape_reader.field_map)
        self.assertNotEqual(new_type, shape_reader.type)
        from bauble.prefs import PLT_DEFAULTS
        self.assertEqual(shape_reader.field_map, PLT_DEFAULTS.get('fields'))

    def test_get_records_count(self):
        # Working example
        shape_reader = ShapefileReader(create_shapefile('test',
                                                        prj_str_4326,
                                                        location_fields,
                                                        loc_recs_4326,
                                                        self.temp_dir.name))
        self.assertEqual(shape_reader.get_records_count(), len(loc_recs_4326))

    def test_get_records(self):
        shape_reader = ShapefileReader(create_shapefile('test',
                                                        prj_str_4326,
                                                        location_fields,
                                                        loc_recs_4326,
                                                        self.temp_dir.name))
        with shape_reader.get_records() as records:
            self.assertTrue(records)
            for rec in records:
                # using transform just to make sure the same format with
                # list/tuples
                self.assertIn(transform(rec.shape.__geo_interface__,
                                        in_crs='epsg:4326',
                                        out_crs='epsg:4326'),
                              [epsg4326_poly_xy, epsg4326_poly_xy2])


class GlobalFunctionsTests(BaubleTestCase):
    def test_add_rec_to_db_plants(self):
        data1 = {
            'accession.species._default_vernacular_name.vernacular_name':
            {'name': 'Air Plant'},
            'accession.species.genus.family': {'family': 'Bromeliaceae'},
            'accession.species.genus': {'genus': 'Tillandsia', 'author': 'L.'},
            'accession.source.source_detail': {'name':
                                               'Tropical Garden Foliage'},
            'accession.species': {'infrasp1_rank': 'f.',
                                  'infrasp1': 'fastigiate',
                                  'infrasp1_author': 'Koide',
                                  'sp': 'ionantha',
                                  'sp_author': 'Planchon'},
            'location': {'name': 'Epiphites of the Americas', 'code': '10.10'},
            'accession': {'code': 'XXXX000001'},
            'code': '1',
            'quantity': 1
        }

        obj = Plant()
        self.session.add(obj)
        out = add_rec_to_db(self.session, obj, data1)
        self.assertEqual(obj, out)
        # Committing will reveal issues that only show up at commit
        self.session.commit()
        result = self.session.query(Plant).all()
        self.assertEqual(result[0].quantity, data1.get('quantity'))
        self.assertEqual(result[0].code, data1.get('code'))
        self.assertEqual(result[0].accession.code,
                         data1.get('accession').get('code'))
        self.assertEqual(result[0].location.name,
                         data1.get('location').get('name'))
        self.assertEqual(
            result[0].accession.species.default_vernacular_name.name,
            data1.get(
                'accession.species._default_vernacular_name.vernacular_name'
            ).get('name'))
        self.assertEqual(
            result[0].accession.species.sp_author,
            data1.get('accession.species').get('sp_author'))
        self.assertEqual(
            result[0].accession.species.infrasp1,
            data1.get('accession.species').get('infrasp1'))

        data2 = {
            'accession.species.genus.family': {'epithet': 'Taccaceae'},
            'accession.species.genus': {'epithet': 'Tacca'},
            'accession.source.source_detail': {'name':
                                               'MRBG Friends of the Gradens'},
            'accession.species': {'epithet': 'leontopetaloides',
                                  'default_vernacular_name': 'Arrowroot'},
            'location': {'name': 'Whitsunday Islands', 'code': '12.01'},
            'accession': {'code': '1999000003'},
            'code': '1',
            'quantity': 10
        }
        obj = Plant()
        self.session.add(obj)
        out = add_rec_to_db(self.session, obj, data2)
        self.assertEqual(obj, out)
        self.session.commit()
        result = self.session.query(Plant).all()
        self.assertEqual(result[1].quantity, data2.get('quantity'))
        self.assertEqual(result[1].code, data2.get('code'))
        self.assertEqual(result[1].accession.code,
                         data2.get('accession').get('code'))
        self.assertEqual(result[1].location.name,
                         data2.get('location').get('name'))
        self.assertEqual(
            result[1].accession.species.default_vernacular_name.name,
            data2.get('accession.species').get('default_vernacular_name'))
        self.assertEqual(
            result[1].accession.species.sp,
            data2.get('accession.species').get('epithet'))

        # change the location and quantity of a previous record (data2)
        data3 = {
            'location': {'code': '10.10'},
            'accession': {'code': '1999000003'},
            'code': '1',
            'quantity': 5
        }
        # the previous record (from the last data set)
        obj = result[1]
        self.session.add(obj)
        out = add_rec_to_db(self.session, obj, data3)
        self.assertEqual(obj, out)
        self.session.commit()
        result = self.session.query(Plant).all()
        # quantity is has changed
        self.assertEqual(result[1].quantity, data3.get('quantity'))
        # location has changed (same as first data set)
        self.assertEqual(result[1].location.name,
                         data1.get('location').get('name'))
        # and last data set
        self.assertEqual(result[1].location.code,
                         data3.get('location').get('code'))
        # the rest is the same as the last data set
        self.assertEqual(result[1].code, data2.get('code'))
        self.assertEqual(result[1].accession.code,
                         data2.get('accession').get('code'))
        self.assertEqual(
            result[1].accession.species.default_vernacular_name.name,
            data2.get('accession.species').get('default_vernacular_name'))
        self.assertEqual(
            result[1].accession.species.sp,
            data2.get('accession.species').get('epithet'))

        data4 = {
            'accession.species.genus.family': {'epithet': 'Moraceae'},
            'accession.species.genus': {'epithet': 'Ficus'},
            'accession.source.source_detail': {'name':
                                               'MRBG Friends of the Gradens'},
            'accession.species': {'epithet': 'virens',
                                  'infraspecific_parts': 'var. virens'},
            'location': {'name': 'Whitsunday Islands', 'code': '12.01'},
            'accession': {'code': '2020.0002'},
            'code': '1',
            'quantity': 1
        }
        obj = Plant()
        self.session.add(obj)
        out = add_rec_to_db(self.session, obj, data4)
        self.assertEqual(obj, out)
        # Committing will reveal issues that only show up at commit
        self.session.commit()
        result = self.session.query(Plant).all()
        self.assertEqual(result[2].quantity, data4.get('quantity'))
        self.assertEqual(result[2].code, data4.get('code'))
        self.assertEqual(result[2].accession.code,
                         data4.get('accession').get('code'))
        self.assertEqual(result[2].location.name,
                         data4.get('location').get('name'))
        # epithet is a synonym of sp
        self.assertEqual(
            result[2].accession.species.sp,
            data4.get('accession.species').get('epithet'))
        self.assertEqual(
            result[2].accession.species.infraspecific_parts,
            data4.get('accession.species').get('infraspecific_parts'))

    def test_add_rec_to_db_location(self):
        data1 = {
            'code': '10.10',
            'name': 'Whitsunday Islands',
            'description': 'Selection of species of horticultural value '
            'commonly found on the Whitsunday Islands.'
        }

        obj = Location()
        self.session.add(obj)
        out = add_rec_to_db(self.session, obj, data1)
        self.assertEqual(obj, out)
        # Committing will reveal issues that only show up at commit
        self.session.commit()
        result = self.session.query(Location).all()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].code, data1.get('code'))
        self.assertEqual(result[0].name, data1.get('name'))
        self.assertEqual(result[0].description, data1.get('description'))

        # make a change to the entry.
        data2 = {
            'code': '10.10',
            'name': 'Whitsunday Islands',
            'description': 'Rare, threatend and vulnerable species endemic to '
            'the Whitsunday Islands off the Central Queensland Coast.'
        }
        out = add_rec_to_db(self.session, obj, data2)
        self.assertEqual(obj, out)
        # Committing will reveal issues that only show up at commit
        self.session.commit()
        result = self.session.query(Location).all()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].code, data1.get('code'))
        self.assertEqual(result[0].name, data1.get('name'))
        self.assertEqual(result[0].description, data2.get('description'))

    def test_get_field_properties(self):
        path = 'accession.species'
        result = ('C', 255)
        self.assertEqual(get_field_properties(Plant, path), result)
        path = 'accession.species.sp'
        result = ('C', 128)
        self.assertEqual(get_field_properties(Plant, path), result)
        path = 'accession.species.epithet'
        result = ('C', 128)
        self.assertEqual(get_field_properties(Plant, path), result)
        path = 'accession.species.infraspecific_parts'
        result = ('C', 255)
        self.assertEqual(get_field_properties(Plant, path), result)
        path = 'accession'
        result = ('C', 255)
        self.assertEqual(get_field_properties(Plant, path), result)
        path = 'Note'
        result = ('C', 255)
        self.assertEqual(get_field_properties(Plant, path), result)
        path = 'accession.code'
        result = ('C', 20)
        self.assertEqual(get_field_properties(Plant, path), result)
        path = 'accession.species.genus.family.epithet'
        result = ('C', 45)
        self.assertEqual(get_field_properties(Plant, path), result)
        path = 'accession.species.genus.epithet'
        result = ('C', 64)
        self.assertEqual(get_field_properties(Plant, path), result)
        path = 'accession.species.genus.genus'
        result = ('C', 64)
        self.assertEqual(get_field_properties(Plant, path), result)
        path = 'id'
        result = ('N', None)
        self.assertEqual(get_field_properties(Plant, path), result)
        path = '_created'
        result = ('D', None)
        self.assertEqual(get_field_properties(Plant, path), result)
        path = 'accession.date_accd'
        result = ('D', None)
        self.assertEqual(get_field_properties(Plant, path), result)
        path = 'accession.source.collection.geo_accy'
        result = ('F', 10)
        self.assertEqual(get_field_properties(Plant, path), result)
        path = 'code'
        result = ('C', 12)
        self.assertEqual(get_field_properties(Location, path), result)
        path = 'location'
        result = ('C', 255)
        self.assertEqual(get_field_properties(Location, path), result)
