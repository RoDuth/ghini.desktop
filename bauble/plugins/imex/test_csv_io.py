# Copyright (c) 2021-2022 Ross Demuth <rossdemuth123@gmail.com>
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
Test csv import/export
"""
import logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

import csv
from tempfile import TemporaryDirectory
from pathlib import Path
from csv import DictWriter
from unittest import mock
from datetime import datetime

from gi.repository import Gtk

from bauble import prefs
from bauble.editor import MockView
from bauble.plugins.plants import Species
from bauble.plugins.garden import Accession, Location, Plant, PlantNote
import bauble.plugins.garden.test_garden as garden_test
import bauble.plugins.plants.test_plants as plants_test
from bauble.test import BaubleTestCase
from .csv_io import (CSVImporter,
                     CSVExporter,
                     CSVExportTool,
                     CSV_IO_PREFS,
                     CSV_EXPORT_DIR_PREF,
                     CSV_IMPORT_DIR_PREF)

plant_full_csv_data = [
    {'qty': 'quantity', 'code': 'code', 'acc': 'accession.code',
     'loc': 'location.code', 'fam': 'accession.species.genus.family.epithet',
     'gen': 'accession.species.genus.epithet', 'hybrid':
     'accession.species.hybrid', 'sp': 'accession.species.epithet', 'infrasp':
     'accession.species.infraspecific_parts', 'cv':
     'accession.species.cultivar_epithet'},
    {'qty': '1', 'code': '1', 'acc': '2021.0001', 'loc': 'bed2', 'fam':
     'Bromeliaceae', 'gen': 'Dyckia', 'hybrid': '', 'sp': 'sp. (red/brown)',
     'infrasp': '', 'cv': ''},
    {'qty': '2', 'code': '1', 'acc': '2021.0002', 'loc': 'bed2', 'fam':
     'Myrtaceae', 'gen': 'Syzygium', 'hybrid': '', 'sp': 'australe',
     'infrasp': '', 'cv': 'Bush Christmas'},
]

update_plants_csv_data = [
    {'qty': 'quantity', 'code': 'code', 'acc': 'accession.code',
     'loc': 'location.code', 'gen': 'accession.species.genus.epithet',
     'hybrid': 'accession.species.hybrid', 'sp': 'accession.species.epithet',
     'infrasp': 'accession.species.infraspecific_parts', 'cv':
     'accession.species.cultivar_epithet'},
    {'qty': '3', 'code': '1', 'acc': '2001.1', 'loc': 'SE',
     'gen': 'Maxillaria', 'hybrid': '', 'sp': 'variabilis',
     'infrasp': 'var. unipunctata', 'cv': ''},
]


plant_csv_search_by = ['code', 'acc']


def create_csv(records: list[dict],
               out_dir: str,
               name: str = 'test.csv') -> str:
    """Create a temporary csv file.

    :param records: a list of dicts of lines as they should be written.
        NOTE:
        To include a mapping row it must be the first dict in the list.
        To include a domain column it should be the first item in the dicts.
    :param out_dir: directory to write `test.csv` file to.
    :param name: optional, the filename as a string, default: `test.csv`
    :return: fully qualified filename as a string.
    """
    name = 'test.csv'
    path = Path(out_dir) / name
    with path.open('w') as f:
        writer = DictWriter(f, records[0].keys())
        writer.writeheader()
        writer.writerows(records)

    return str(path)


class CSVTestCase(BaubleTestCase):

    def setUp(self):
        super().setUp()
        plants_test.setUp_data()
        garden_test.setUp_data()
        self.temp_dir = TemporaryDirectory()

    def tearDown(self):
        self.temp_dir.cleanup()
        super().tearDown()


class CSVExporterTests(CSVTestCase):

    def test_export_plants(self):
        mock_view = MockView()
        mock_view.selection = self.session.query(Plant).all()
        exporter = CSVExporter(mock_view, open_=False)
        fields = {
            'domain': 'plant', 'id': 'id', 'plant': 'code',
            'acc': 'accession.code', 'species': 'accession.species'
        }
        field_list = fields.copy()
        del field_list['domain']
        exporter.presenter.fields = list(field_list.items())
        out = [
            {'domain': 'plant', 'id': '1', 'plant': '1', 'acc': '2001.1',
             'species': 'Maxillaria variabilis'},
            {'domain': 'plant', 'id': '2', 'plant': '1', 'acc': '2001.2',
             'species': 'Encyclia cochleata'},
        ]
        out_file = Path(self.temp_dir.name) / 'test.csv'
        exporter.filename = str(out_file)
        exporter.run()
        with out_file.open() as f:
            reader = csv.DictReader(f)
            field_map = next(reader)
            self.assertEqual(field_map, fields)
            rec = next(reader)
            self.assertEqual(rec, out[0])
            rec = next(reader)
            self.assertEqual(rec, out[1])
        self.assertEqual(prefs.prefs.get(f'{CSV_IO_PREFS}.plant'), field_list)

    def test_export_plants_w_notes(self):
        plt = self.session.query(Plant).get(1)
        plt.notes.append(PlantNote(category='test1', note='test note'))
        plt.notes.append(PlantNote(category='[test2]', note='test1'))
        plt.notes.append(PlantNote(category='[test2]', note='test2'))
        plt.notes.append(PlantNote(category='{test3:1}', note='test1'))
        plt.notes.append(PlantNote(category='{test3:2}', note='test2'))
        plt.notes.append(PlantNote(category='<test4>',
                                   note='{"key": "value"}'))
        self.session.add(plt)
        self.session.commit()
        mock_view = MockView()
        mock_view.selection = self.session.query(Plant).all()
        exporter = CSVExporter(mock_view, open_=False)
        fields = {
            'domain': 'plant', 'id': 'id', 'test1': 'Note', 'test2': 'Note',
            'test3': 'Note', 'test4': 'Note', '{test3:1}': 'Note'
        }
        field_list = fields.copy()
        del field_list['domain']
        exporter.presenter.fields = list(field_list.items())
        out = [
            {'domain': 'plant', 'id': '1',
             'test1': 'test note',
             'test2': "['test1', 'test2']",
             'test3': "{'1': 'test1', '2': 'test2'}",
             'test4': "{'key': 'value'}",
             '{test3:1}': 'test1'}
        ]
        out_file = Path(self.temp_dir.name) / 'test.csv'
        exporter.filename = str(out_file)
        exporter.run()
        with out_file.open() as f:
            reader = csv.DictReader(f)
            field_map = next(reader)
            self.assertEqual(field_map, fields)
            rec = next(reader)
            self.assertEqual(rec, out[0])

    def test_export_species(self):
        mock_view = MockView()
        mock_view.selection = (self.session.query(Species)
                               .filter(Species.id.in_([1, 15])).all())
        exporter = CSVExporter(mock_view, open_=False)
        fields = {
            'domain': 'species', 'id': 'id', 'gen': 'genus.epithet',
            'sp': 'epithet', 'infrasp': 'infraspecific_parts',
            'cv': 'cultivar_epithet'
        }
        field_list = fields.copy()
        del field_list['domain']
        exporter.presenter.fields = list(field_list.items())
        out = [
            {'domain': 'species', 'id': '1', 'gen': 'Maxillaria',
             'sp': 'variabilis', 'infrasp': '', 'cv': ''},
            {'domain': 'species', 'id': '15', 'gen': 'Encyclia',
             'sp': 'cochleata', 'infrasp': 'subsp. cochleata var. cochleata',
             'cv': 'Black'},
        ]
        out_file = Path(self.temp_dir.name) / 'test.csv'
        exporter.filename = str(out_file)
        exporter.run()
        with out_file.open() as f:
            reader = csv.DictReader(f)
            field_map = next(reader)
            self.assertEqual(field_map, fields)
            rec = next(reader)
            self.assertEqual(rec, out[0])
            rec = next(reader)
            logger.debug(rec)
            self.assertEqual(rec, out[1])

    @mock.patch('bauble.plugins.imex.csv_io.CSVExportDialogPresenter.start',
                return_value=Gtk.ResponseType.OK)
    def test_export_species_w_note_empty_via_start(self, _mock_start):
        mock_view = MockView()
        mock_view.selection = (self.session.query(Species)
                               .filter(Species.id == 18).all())
        exporter = CSVExporter(mock_view, open_=False)
        fields = {
            'domain': 'species', 'sp': 'species', 'field_note': 'Empty',
            'fam': 'genus.family.epithet', 'CITES': 'Note'
        }
        field_list = fields.copy()
        del field_list['domain']
        exporter.presenter.fields = list(field_list.items())
        out = [
            {'domain': 'species', 'sp': 'Laelia lobata', 'field_note': '',
             'fam': 'Orchidaceae', 'CITES': 'I'},
        ]
        out_file = Path(self.temp_dir.name) / 'test.csv'
        exporter.filename = str(out_file)
        exporter.start()
        with out_file.open() as f:
            reader = csv.DictReader(f)
            field_map = next(reader)
            self.assertEqual(field_map, fields)
            rec = next(reader)
            self.assertEqual(rec, out[0])

    def test_mixed_types_raises(self):
        mock_view = MockView()
        plant = self.session.query(Plant).get(1)
        loc = self.session.query(Location).get(1)
        mock_view.selection = [loc, plant]
        from bauble.error import BaubleError
        with self.assertRaises(
            BaubleError, msg='Can only export search items of the same type.'
        ):
            exporter = CSVExporter(mock_view, open_=False)
            self.assertFalse(hasattr(exporter, 'presenter'))
            self.assertFalse(hasattr(exporter, 'filename'))
            self.assertIsNone(exporter.items)

    def test_no_items_bails_early(self):
        mock_view = MockView()
        mock_view.selection = []
        exporter = CSVExporter(mock_view, open_=False)
        self.assertIsNone(exporter.presenter)
        self.assertIsNone(exporter.filename)
        self.assertIsNone(exporter.items)

    def test_on_btnbrowse_clicked(self):
        mock_view = MockView()
        mock_view.selection = (self.session.query(Species)
                               .filter(Species.id == 18).all())
        exporter = CSVExporter(mock_view, open_=False)
        out_file = Path(self.temp_dir.name) / 'test.csv'
        exporter.presenter.view.reply_file_chooser_dialog = [str(out_file)]
        exporter.presenter.on_btnbrowse_clicked('button')
        self.assertEqual(
            exporter.presenter.view.values.get('out_filename_entry'),
            str(out_file)
        )

    def test_on_filename_entry_changed(self):
        mock_view = MockView()
        mock_view.selection = (self.session.query(Species)
                               .filter(Species.id == 18).all())
        exporter = CSVExporter(mock_view, open_=False)
        out_file = Path(self.temp_dir.name) / 'test.csv'
        mock_view.reply_file_chooser_dialog = [str(out_file)]
        exporter.presenter.on_btnbrowse_clicked('button')
        self.assertEqual(
            exporter.presenter.view.values.get('out_filename_entry'),
            str(out_file)
        )
        exporter.presenter.on_filename_entry_changed('out_filename_entry')
        self.assertEqual(exporter.filename, str(out_file))
        self.assertEqual(prefs.prefs.get(CSV_EXPORT_DIR_PREF),
                         self.temp_dir.name)

    def test_on_name_entry_changed(self):
        mock_widget = mock.Mock()
        mock_widget.get_text.return_value = 'Test'
        mock_view = MockView()
        mock_view.selection = (self.session.query(Species)
                               .filter(Species.id == 18).all())
        exporter = CSVExporter(mock_view, open_=False)
        exporter.presenter.fields = [(None, None), (None, None)]
        with mock.patch.object(exporter.presenter, 'grid') as mock_grid:
            mock_grid.child_get_property.return_value = 1
            exporter.presenter.on_name_entry_changed(mock_widget)
            self.assertEqual(exporter.presenter.fields,
                             [('Test', None), (None, None)])

    def test_on_add_button_clicked(self):
        mock_view = MockView()
        mock_view.selection = (self.session.query(Species)
                               .filter(Species.id == 18).all())
        exporter = CSVExporter(mock_view, open_=False)
        exporter.presenter.fields = [(None, None)]
        exporter.presenter.on_add_button_clicked('button')
        self.assertEqual(exporter.presenter.fields,
                         [(None, None), (None, None)])

    def test_on_remove_button_clicked(self):
        mock_view = MockView()
        mock_view.selection = (self.session.query(Species)
                               .filter(Species.id == 18).all())
        exporter = CSVExporter(mock_view, open_=False)
        exporter.presenter.fields = [(None, None), (None, None)]
        with mock.patch.object(exporter.presenter, 'grid') as mock_grid:
            mock_grid.child_get_property.return_value = 1
            exporter.presenter.on_remove_button_clicked('button')
            self.assertEqual(exporter.presenter.fields,
                             [(None, None)])


class CSVExportToolTests(BaubleTestCase):

    @mock.patch('bauble.plugins.imex.csv_io.message_dialog')
    @mock.patch('bauble.gui', **{'get_view.return_value': None})
    def test_no_search_view_asks_to_search_first(self,
                                                 _mock_get_view,
                                                 mock_dialog):
        tool = CSVExportTool()
        result = tool.start()
        self.assertIsNone(result)
        mock_dialog.assert_called_with('Search for something first.')

    @mock.patch('bauble.plugins.imex.csv_io.message_dialog')
    @mock.patch('bauble.gui')
    def test_no_model_asks_to_search_first(self, mock_gui, mock_dialog):
        mock_searchview = mock.Mock()
        from bauble.view import SearchView
        mock_searchview.__class__ = SearchView
        mock_results_view = mock.Mock()
        mock_results_view.get_model.return_value = None
        mock_searchview.results_view = mock_results_view
        mock_gui.get_view.return_value = mock_searchview
        tool = CSVExportTool()
        result = tool.start()
        self.assertIsNone(result)
        mock_dialog.assert_called_with(
            'Search for something first. (No model)'
        )

    @mock.patch('bauble.gui')
    @mock.patch('bauble.plugins.imex.csv_io.CSVExporter')
    def test_exporter_start_return_none(self, mock_exporter, mock_gui):
        mock_instance = mock.Mock()
        mock_instance.start.return_value = None
        mock_exporter.return_value = mock_instance
        logger.debug('start %s', mock_exporter.start() is None)
        mock_searchview = mock.Mock()
        from bauble.view import SearchView
        mock_searchview.__class__ = SearchView
        mock_results_view = mock.Mock()
        mock_results_view.get_model.return_value = 'something'
        mock_searchview.results_view = mock_results_view
        mock_gui.get_view.return_value = mock_searchview
        tool = CSVExportTool()
        result = tool.start()
        self.assertIsNone(result)


class CSVImporterEmptyDBTests(BaubleTestCase):

    def setUp(self):
        super().setUp()
        self.temp_dir = TemporaryDirectory()
        self.importer = CSVImporter(MockView())

    def tearDown(self):
        self.temp_dir.cleanup()
        super().tearDown()

    def test_add_plants(self):
        importer = self.importer
        importer.filename = create_csv(plant_full_csv_data, self.temp_dir.name)
        importer.search_by = plant_csv_search_by
        importer.fields = plant_full_csv_data[0]
        importer.domain = Plant
        importer.option = '1'
        importer.run()
        result = self.session.query(Plant).all()
        self.assertEqual(len(result), len(plant_full_csv_data) - 1)

    def test_add_update_plants_just_adds(self):

        start_plants = self.session.query(Plant).count()
        self.assertEqual(start_plants, 0)
        importer = self.importer
        importer.filename = create_csv(plant_full_csv_data, self.temp_dir.name)
        importer.search_by = plant_csv_search_by
        importer.fields = plant_full_csv_data[0]
        importer.domain = Plant
        importer.option = '2'
        importer.run()
        result = self.session.query(Plant).all()
        self.assertEqual(len(result), len(plant_full_csv_data) - 1)

    def test_update_plants_doesnt_add(self):
        start_plants = self.session.query(Plant).count()
        start_sp = self.session.query(Species).count()
        importer = self.importer
        importer.filename = create_csv(plant_full_csv_data,
                                       self.temp_dir.name)
        importer.search_by = plant_csv_search_by
        importer.fields = plant_full_csv_data[0]
        importer.domain = Plant
        importer.option = '0'
        importer.run()
        end_plants = self.session.query(Plant).count()
        end_sp = self.session.query(Species).count()
        # no plants added
        self.assertEqual(end_plants, start_plants)
        self.assertEqual(end_plants, 0)
        # no new species
        self.assertEqual(end_sp, start_sp)
        self.assertEqual(end_sp, 0)

    def test_add_location_w_id_use_id(self):
        # needs locations dict
        start = self.session.query(Location).count()
        self.assertEqual(start, 0)
        importer = self.importer
        locs = [
            {'id': 'id', 'code': 'code', 'name': 'name',
             'soil': 'Note[category="soil_type"]',
             'irrigation': 'Note[category="irrig_type"]'},
            {'id': '10', 'code': 'BED1', 'name': 'Entrance', 'soil': 'clay',
             'irrigation': 'drip'}
        ]
        importer.filename = create_csv(locs, self.temp_dir.name)
        importer.search_by = ['id']
        importer.use_id = True
        importer.fields = locs[0]
        importer.domain = Location
        importer.option = '1'
        importer.run()
        result = self.session.query(Location).all()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].code, 'BED1')
        self.assertEqual(result[0].id, 10)

    def test_add_plant_w_planted_date(self):
        plant = [
            {'qty': 'quantity',
             'code': 'code',
             'planted': 'planted.date',
             'acc': 'accession.code',
             'loc': 'location.code',
             'fam': 'accession.species.genus.family.epithet',
             'gen': 'accession.species.genus.epithet',
             'hybrid': 'accession.species.hybrid',
             'sp': 'accession.species.epithet',
             'infrasp': 'accession.species.infraspecific_parts',
             'cv': 'accession.species.cultivar_epithet'},
            {'qty': '2',
             'code': '1',
             'planted': '29/09/2020 10:00:00 pm',
             'acc': '2021.0002',
             'loc': 'bed2',
             'fam': 'Myrtaceae',
             'gen': 'Syzygium',
             'hybrid': '',
             'sp': 'australe',
             'infrasp': '',
             'cv': 'Bush Christmas'},
        ]
        start_plants = self.session.query(Plant).count()
        importer = self.importer
        importer.filename = create_csv(plant, self.temp_dir.name)
        importer.search_by = plant_csv_search_by
        importer.fields = plant[0]
        importer.domain = Plant
        importer.option = '1'
        importer.run()
        added_plant = self.session.query(Plant).get(1)
        logger.debug('added_plant: %s', added_plant)
        end_plants = self.session.query(Plant).count()
        # planted added
        self.assertEqual(len(added_plant.changes), 1)
        self.assertEqual(added_plant.planted.date,
                         datetime(2020, 9, 29, 22, 0, 0).astimezone(None))
        self.assertEqual(added_plant.planted.quantity, 2)
        # 1 plant are added
        self.assertEqual(end_plants, start_plants + 1)
        # quantity changed and a change was added.
        self.assertEqual(added_plant.quantity, 2)


class CSVImporterTests(CSVTestCase):

    def setUp(self):
        super().setUp()
        self.importer = CSVImporter(view=MockView())

    def test_add_plants(self):
        start_plants = self.session.query(Plant).count()
        importer = self.importer
        importer.filename = create_csv(plant_full_csv_data, self.temp_dir.name)
        importer.search_by = plant_csv_search_by
        importer.fields = plant_full_csv_data[0]
        importer.domain = Plant
        importer.option = '1'
        importer.run()
        result = self.session.query(Plant).count()
        # test correct amount added
        end_plants = start_plants + len(plant_full_csv_data) - 1
        self.assertEqual(result, end_plants)
        # check some data
        new_plt1 = self.session.query(Plant).get(4)
        new_plt2 = self.session.query(Plant).get(4)
        accs = [i.get('acc') for i in plant_full_csv_data[1:]]
        spp = ['Dyckia sp. (red/brown)', "Syzygium australe 'Bush Christmas'"]
        self.assertIn(new_plt1.accession.code, accs)
        self.assertIn(str(new_plt1.accession.species), spp)
        self.assertIn(new_plt2.accession.code, accs)
        self.assertIn(str(new_plt2.accession.species), spp)

    def test_update_accession_w_str_dates(self):
        acc = [
            {'id': 'id', 'recvd': 'date_recvd', 'created': '_created'},
            {'id': '1', 'recvd': '29/09/2020',
             'created': '29/09/2020 10:00:00 pm'}
        ]
        start_accs = self.session.query(Accession).count()
        importer = self.importer
        importer.filename = create_csv(acc, self.temp_dir.name)
        importer.search_by = ['id']
        importer.fields = acc[0]
        importer.domain = Accession
        importer.option = '0'
        importer.run()
        end_accs = self.session.query(Accession).count()
        # test no additions
        updated_acc = self.session.query(Accession).get(1)
        self.assertEqual(end_accs, start_accs)
        # test the date.
        self.assertEqual(updated_acc.date_recvd,
                         datetime(2020, 9, 29).date())
        self.assertEqual(updated_acc._created,
                         datetime(2020, 9, 29, 22, 0, 0).astimezone(None))

    @mock.patch('bauble.plugins.imex.csv_io.CSVImportDialogPresenter.start',
                return_value=Gtk.ResponseType.OK)
    def test_add_plants_w_start(self, _mock_start):
        start_plants = self.session.query(Plant).count()
        importer = self.importer
        importer.filename = create_csv(plant_full_csv_data, self.temp_dir.name)
        importer.search_by = plant_csv_search_by
        importer.fields = plant_full_csv_data[0]
        importer.domain = Plant
        importer.option = '1'
        importer.start()
        result = self.session.query(Plant).all()
        end_plants = start_plants + len(plant_full_csv_data) - 1
        self.assertEqual(len(result), end_plants)

    def test_add_update_plants(self):
        start_plants = self.session.query(Plant).count()
        start_sp = self.session.query(Species).count()
        importer = self.importer
        update_plant = update_plants_csv_data[1].copy()
        # add family
        update_plant['fam'] = 'Orchidaceae'
        plants = plant_full_csv_data + [update_plant]
        logger.debug('plants: %s', plants)
        importer.filename = create_csv(plants, self.temp_dir.name)
        importer.search_by = plant_csv_search_by
        importer.fields = plant_full_csv_data[0]
        importer.domain = Plant
        importer.option = '2'
        importer.run()
        end_plants = self.session.query(Plant).count()
        end_sp = self.session.query(Species).count()
        # check the plant was updated
        updated_plant = self.session.query(Plant).get(1)
        # quantity changed
        self.assertEqual(updated_plant.quantity, 3)
        # species changed
        self.assertEqual(str(updated_plant.accession.species),
                         'Maxillaria variabilis var. unipunctata')
        # location changed
        self.assertEqual(updated_plant.location.code, 'SE')
        # 2 plants added
        self.assertEqual(end_plants, start_plants + 2)
        # 3 new species
        self.assertEqual(end_sp, start_sp + 3)

    def test_update_plants_geojson(self):
        start_plants = self.session.query(Plant).count()
        importer = self.importer
        plants_csv_data = [
            {'id': 'id', 'geojson': 'geojson'},
            {'id': 1,
             'geojson': "{'type': 'Point', 'coordinates': [0.0, 0.0]}"},
        ]
        importer.filename = create_csv(plants_csv_data,
                                       self.temp_dir.name)
        importer.search_by = ['id']
        importer.fields = plants_csv_data[0]
        importer.domain = Plant
        importer.option = '0'
        importer.run()
        updated_plant = self.session.query(Plant).get(1)
        end_plants = self.session.query(Plant).count()
        # check the plant was updated
        self.assertEqual(updated_plant.geojson.get('type'), 'Point')
        self.assertEqual(len(updated_plant.geojson.get('coordinates')), 2)
        self.assertEqual(updated_plant.geojson.get('coordinates')[0], 0.0)
        # nothing added
        self.assertEqual(end_plants, start_plants)

        # test setting to None
        plants_csv_data = [
            {'id': 'id', 'geojson': 'geojson'},
            {'id': 1,
             'geojson': ""},
        ]
        importer.filename = create_csv(plants_csv_data,
                                       self.temp_dir.name)
        importer.search_by = ['id']
        importer.fields = plants_csv_data[0]
        importer.domain = Plant
        importer.option = '0'
        importer.run()
        self.session.expire_all()
        self.assertIsNone(updated_plant.geojson)

    def test_update_plants(self):
        start_plants = self.session.query(Plant).count()
        start_sp = self.session.query(Species).count()
        importer = self.importer
        importer.filename = create_csv(update_plants_csv_data,
                                       self.temp_dir.name)
        importer.search_by = plant_csv_search_by
        importer.fields = plant_full_csv_data[0]
        importer.domain = Plant
        importer.option = '0'
        importer.run()
        updated_plant = self.session.query(Plant).get(1)
        end_plants = self.session.query(Plant).count()
        end_sp = self.session.query(Species).count()
        # check the plant was updated
        # quantity changed
        self.assertEqual(updated_plant.quantity, 3)
        # location changed
        self.assertEqual(updated_plant.location.code, 'SE')
        # species changed
        self.assertEqual(str(updated_plant.accession.species),
                         'Maxillaria variabilis var. unipunctata')
        # no plants added
        self.assertEqual(end_plants, start_plants)
        # one new species
        self.assertEqual(end_sp, start_sp + 1)

    def test_update_plant_quantity_planted_date(self):
        # add the plant here so a planted entry is created by the event
        # listener
        acc = self.session.query(Accession).get(1)
        acc_code = acc.code
        loc = self.session.query(Location).get(1)
        plt = Plant(accession=acc, code='3', quantity=1, location=loc)
        self.session.add(plt)
        self.session.commit()
        self.assertEqual(plt.quantity, 1)
        plt_id = int(plt.id)
        # need to expire plt so we reload later
        self.session.expire(plt)
        start_plants = self.session.query(Plant).count()
        importer = self.importer
        plant = [
            {'code': 'code', 'acc': 'accession.code', 'qty': 'quantity',
             'planted': 'planted.date'},
            {'code': '3', 'acc': acc_code, 'qty': '4',
             'planted': '29/09/2020 10:00:00 pm'},
        ]
        importer.filename = create_csv(plant, self.temp_dir.name)
        importer.search_by = plant_csv_search_by
        importer.fields = plant[0]
        importer.domain = Plant
        importer.option = '0'
        importer.run()
        updated_plant = self.session.query(Plant).get(plt_id)
        logger.debug('updated_plant: %s', updated_plant)
        end_plants = self.session.query(Plant).count()
        # date changed
        self.assertEqual(updated_plant.planted.date,
                         datetime(2020, 9, 29, 22, 0, 0).astimezone(None))
        # no plants are added
        self.assertEqual(end_plants, start_plants)
        # quantity changed and a change was added.
        self.assertTrue(updated_plant.changes[1].quantity == 3)
        self.assertEqual(updated_plant.quantity, 4)

    def test_update_plant_quantity_death_date(self):
        # add the plant here so a planted entry is created by the event
        # listener
        acc = self.session.query(Accession).get(1)
        acc_code = acc.code
        loc = self.session.query(Location).get(1)
        plt = Plant(accession=acc, code='3', quantity=1, location=loc)
        self.session.add(plt)
        self.session.commit()
        # add a planted entry
        plt.planted.date = '29/09/2010 10:00:00 pm'
        self.session.add(plt)
        self.session.commit()
        self.assertEqual(plt.quantity, 1)
        plt_id = int(plt.id)
        # need to expire plt so we reload later
        self.session.expire(plt)
        start_plants = self.session.query(Plant).count()
        importer = self.importer
        plant = [
            {'code': 'code', 'acc': 'accession.code', 'qty': 'quantity',
             'death': 'death.date'},
            {'code': '3', 'acc': acc_code, 'qty': '0',
             'death': '29/09/2020 10:00:00 pm'},
        ]
        importer.filename = create_csv(plant, self.temp_dir.name)
        importer.search_by = plant_csv_search_by
        importer.fields = plant[0]
        importer.domain = Plant
        importer.option = '0'
        importer.run()
        updated_plant = self.session.query(Plant).get(plt_id)
        logger.debug('updated_plant: %s', updated_plant)
        end_plants = self.session.query(Plant).count()
        # quantity changed
        self.assertEqual(updated_plant.quantity, 0)
        # death date added
        self.assertEqual(updated_plant.death.date,
                         datetime(2020, 9, 29, 22, 0, 0).astimezone(None))
        # no plants are added
        self.assertEqual(end_plants, start_plants)
        # expire
        self.session.expire(plt)
        # rerun with updated date.
        # test can update the death date.
        plant = [
            {'code': 'code', 'acc': 'accession.code', 'qty': 'quantity',
             'death': 'death.date'},
            {'code': '3', 'acc': acc_code, 'qty': '0',
             'death': '29/09/2021 10:00:00 pm'},
        ]
        importer.filename = create_csv(plant, self.temp_dir.name)
        importer.search_by = plant_csv_search_by
        importer.fields = plant[0]
        importer.domain = Plant
        importer.option = '0'
        importer.run()
        updated_plant = self.session.query(Plant).get(plt_id)
        # death date updated
        self.assertEqual(updated_plant.death.date,
                         datetime(2021, 9, 29, 22, 0, 0).astimezone(None))

    def test_update_accession_w_notes(self):
        acc = [
            {'code': 'code', 'test': 'Note'},
            {'code': '2020.1', 'test': 'test note'}
        ]
        start_accs = self.session.query(Accession).count()
        importer = self.importer
        importer.filename = create_csv(acc, self.temp_dir.name)
        importer.search_by = ['code']
        importer.fields = acc[0]
        importer.domain = Accession
        importer.option = '0'
        importer.run()
        updated_acc = self.session.query(Accession).get(3)
        end_accs = self.session.query(Accession).count()
        # no acessions added
        self.assertEqual(end_accs, start_accs)
        notes = updated_acc.notes
        self.assertEqual([i for i in notes if i.category == 'test'][0].note,
                         'test note')
        # replace notes
        acc = [
            {'code': 'code', 'test': 'Note'},
            {'code': '2020.1', 'test': 'test 2'}
        ]
        importer.replace_notes.add('test')
        importer.filename = create_csv(acc, self.temp_dir.name, 'test2.csv')
        importer.run()
        self.session.expire_all()
        end_accs = self.session.query(Accession).count()
        # no acessions added
        self.assertEqual(end_accs, start_accs)
        # still only one note
        self.assertEqual(len(updated_acc.notes), 1)
        self.assertEqual([i for i in notes if i.category == 'test'][0].note,
                         'test 2')

    def test_add_location_w_notes_w_categories(self):
        start_locs = self.session.query(Location).count()
        locs = [
            {'code': 'code', 'name': 'name',
             'soil': 'Note[category="soil_type"]',
             'irrigation': 'Note[category="irrig_type"]'},
            {'code': 'BED1', 'name': 'Entrance', 'soil': 'clay',
             'irrigation': 'drip'}
        ]
        importer = self.importer
        importer.filename = create_csv(locs, self.temp_dir.name)
        importer.search_by = ['code']
        importer.fields = locs[0]
        importer.domain = Location
        importer.option = '1'
        importer.run()
        end_locs = self.session.query(Location).count()
        end_num = start_locs + len(locs) - 1
        self.assertEqual(end_locs, end_num)
        new_loc = (self.session.query(Location)
                   .filter(Location.code == 'BED1').one())
        self.assertEqual(new_loc.name, 'Entrance')
        notes = new_loc.notes
        self.assertTrue(
            [i for i in notes if i.category == 'soil_type'][0].note == 'clay'
        )
        self.assertTrue(
            [i for i in notes if i.category == 'irrig_type'][0].note == 'drip'
        )

    def test_on_btnbrowse_clicked(self):
        importer = self.importer
        in_file = Path(self.temp_dir.name) / 'test.csv'
        importer.presenter.view.reply_file_chooser_dialog = [str(in_file)]
        importer.presenter.on_btnbrowse_clicked('button')
        self.assertEqual(
            importer.presenter.view.values.get('in_filename_entry'),
            str(in_file)
        )

    def test_construct_grid(self):
        importer = self.importer
        importer.fields = {'domain': 'location', 'id': 'id', 'code': 'code',
                           'name': 'name', 'test': 'Note'}
        importer.presenter.domain = Location
        importer.presenter._construct_grid()
        # check some components
        grid = importer.presenter.grid
        domain_lbl = grid.get_child_at(0, 0)
        self.assertEqual(domain_lbl.get_label(), 'Domain:  <b>location</b>')
        from .csv_io import NAME, PATH, MATCH, OPTION
        id_chk_btn = grid.get_child_at(MATCH, 3)
        self.assertEqual(id_chk_btn.get_label(), 'match')
        id_import_chk_btn = grid.get_child_at(OPTION, 3)
        self.assertEqual(id_import_chk_btn.get_label(), 'import')
        name_label = grid.get_child_at(NAME, 5)
        self.assertEqual(name_label.get_label(), 'name')
        path_label = grid.get_child_at(PATH, 5)
        self.assertEqual(path_label.get_label(), 'name')
        self.assertIsNone(grid.get_child_at(MATCH, 5))
        self.assertIsNone(grid.get_child_at(OPTION, 5))
        note_replace_chk_btn = grid.get_child_at(OPTION, 6)
        self.assertEqual(note_replace_chk_btn.get_label(), 'replace')

    def test_on_filename_entry_changed(self):
        importer = self.importer
        locs = [
            {'domain': 'location', 'code': 'code', 'name': 'name'},
            {'domain': 'location', 'code': 'BED1', 'name': 'Entrance'}
        ]
        in_file = create_csv(locs, self.temp_dir.name)
        importer.presenter.view.reply_file_chooser_dialog = [in_file]
        importer.presenter.on_btnbrowse_clicked('button')
        self.assertEqual(
            importer.presenter.view.values.get('in_filename_entry'), in_file
        )
        importer.presenter.on_filename_entry_changed('in_filename_entry')
        self.assertEqual(importer.filename, in_file)
        self.assertEqual(prefs.prefs.get(CSV_IMPORT_DIR_PREF),
                         self.temp_dir.name)

    def test_on_filename_entry_changed_bad_name(self):
        importer = self.importer
        in_file = Path('bad_directory') / 'test.csv'
        importer.presenter.view.reply_file_chooser_dialog = [str(in_file)]
        importer.presenter.on_btnbrowse_clicked('button')
        self.assertEqual(
            importer.presenter.view.values.get('in_filename_entry'),
            str(in_file)
        )
        importer.presenter.on_filename_entry_changed('in_filename_entry')
        self.assertEqual(importer.fields, None)
        self.assertEqual(importer.presenter.filename, None)
        self.assertNotEqual(prefs.prefs.get(CSV_IMPORT_DIR_PREF),
                            self.temp_dir.name)

    def test_on_filename_entry_changed_bad_file(self):
        locs = [
            {'code': 'code', 'name': 'name'},
            {'code': 'BED1', 'name': 'Entrance'}
        ]
        importer = self.importer
        in_file = create_csv(locs, self.temp_dir.name)
        importer.presenter.view.reply_file_chooser_dialog = [in_file]
        importer.presenter.on_btnbrowse_clicked('button')
        self.assertEqual(
            importer.presenter.view.values.get('in_filename_entry'), in_file
        )
        importer.presenter.on_filename_entry_changed('in_filename_entry')
        self.assertIn((importer.presenter.PROBLEM_INVALID_FILENAME),
                      [i[0] for i in importer.presenter.problems])
        self.assertEqual(importer.fields, None)
        self.assertEqual(prefs.prefs.get(CSV_IMPORT_DIR_PREF),
                         self.temp_dir.name)

    def test_on_match_chk_button_change(self):
        importer = self.importer
        mock_button = mock.Mock()
        # set
        mock_button.get_active.return_value = True
        importer.presenter.on_match_chk_button_change(mock_button, 'test')
        self.assertEqual(importer.search_by, {'test'})
        # unset
        mock_button.get_active.return_value = False
        importer.presenter.on_match_chk_button_change(mock_button, 'test')
        self.assertEqual(importer.search_by, set())

    def test_on_import_id_chk_button_change(self):
        importer = self.importer
        mock_button = mock.Mock()
        # set
        mock_button.get_active.return_value = True
        importer.presenter.on_import_id_chk_button_change(mock_button)
        self.assertEqual(importer.use_id, True)
        # unset
        mock_button.get_active.return_value = False
        importer.presenter.on_import_id_chk_button_change(mock_button)
        self.assertEqual(importer.use_id, False)

    def test_on_replace_chk_button_change(self):
        importer = self.importer
        mock_button = mock.Mock()
        # set
        mock_button.get_active.return_value = True
        importer.presenter.on_replace_chk_button_change(mock_button, 'test')
        self.assertEqual(importer.replace_notes, {'test'})
        # unset
        mock_button.get_active.return_value = False
        importer.presenter.on_replace_chk_button_change(mock_button, 'test')
        self.assertEqual(importer.replace_notes, set())

    def test_get_importable_fields(self):
        importer = self.importer
        presenter = importer.presenter
        field_map = {'domain': 'location', 'code': 'code', 'name': 'name'}
        presenter.get_importable_fields(field_map)
        self.assertEqual(presenter.domain, Location)
        del field_map['domain']
        self.assertEqual(importer.fields, field_map)

    def test_get_importable_fields_w_tablename(self):
        importer = self.importer
        presenter = importer.presenter
        field_map = {'domain': 'location', 'loc': 'location', 'name': 'name'}
        presenter.get_importable_fields(field_map)
        self.assertEqual(presenter.domain, Location)
        del field_map['domain']
        field_map['loc'] = None
        self.assertEqual(importer.fields, field_map)

    def test_get_importable_fields_w_related_class(self):
        importer = self.importer
        presenter = importer.presenter
        field_map = {'domain': 'accession', 'code': 'code', 'sp': 'species'}
        presenter.get_importable_fields(field_map)
        self.assertEqual(presenter.domain, Accession)
        del field_map['domain']
        field_map['sp'] = None
        self.assertEqual(importer.fields, field_map)

    def test_get_importable_fields_bad_domain(self):
        # good domain, bad domain, with tablename, with related related class
        importer = self.importer
        presenter = importer.presenter
        field_map = {'domain': 'none_domain', 'code': 'code', 'name': 'name'}
        presenter.get_importable_fields(field_map)
        self.assertEqual(presenter.domain, None)
        del field_map['domain']
        self.assertEqual(importer.fields, None)
