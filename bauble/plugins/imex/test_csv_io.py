# Copyright (c) 2021-2024 Ross Demuth <rossdemuth123@gmail.com>
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
from csv import DictWriter
from datetime import datetime
from operator import attrgetter
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from gi.repository import Gtk

import bauble.plugins.garden.test_garden as garden_test
import bauble.plugins.plants.test_plants as plants_test
from bauble import db
from bauble import prefs
from bauble import utils
from bauble.editor import MockView
from bauble.plugins.garden import Accession
from bauble.plugins.garden import Collection
from bauble.plugins.garden import Location
from bauble.plugins.garden import Plant
from bauble.plugins.garden import Source
from bauble.plugins.garden import SourceDetail
from bauble.plugins.garden.plant import PlantNote
from bauble.plugins.plants import Genus
from bauble.plugins.plants import Species
from bauble.test import BaubleTestCase

from .csv_io import CSV_EXPORT_DIR_PREF
from .csv_io import CSV_IMPORT_DIR_PREF
from .csv_io import CSV_IO_PREFS
from .csv_io import CSVExportDialogPresenter
from .csv_io import CSVExporter
from .csv_io import CSVExportTool
from .csv_io import CSVImporter

plant_full_csv_data = [
    {
        "qty": "quantity",
        "code": "code",
        "acc": "accession.code",
        "loc": "location.code",
        "fam": "accession.species.genus.family.epithet",
        "gen": "accession.species.genus.epithet",
        "hybrid": "accession.species.hybrid",
        "sp": "accession.species.epithet",
        "infrasp": "accession.species.infraspecific_parts",
        "cv": "accession.species.cultivar_epithet",
    },
    {
        "qty": "1",
        "code": "1",
        "acc": "2021.0001",
        "loc": "bed2",
        "fam": "Bromeliaceae",
        "gen": "Dyckia",
        "hybrid": "",
        "sp": "sp. (red/brown)",
        "infrasp": "",
        "cv": "",
    },
    {
        "qty": "2",
        "code": "1",
        "acc": "2021.0002",
        "loc": "bed2",
        "fam": "Myrtaceae",
        "gen": "Syzygium",
        "hybrid": "",
        "sp": "australe",
        "infrasp": "",
        "cv": "Bush Christmas",
    },
]

update_plants_csv_data = [
    {
        "qty": "quantity",
        "code": "code",
        "acc": "accession.code",
        "loc": "location.code",
        "gen": "accession.species.genus.epithet",
        "hybrid": "accession.species.hybrid",
        "sp": "accession.species.epithet",
        "infrasp": "accession.species.infraspecific_parts",
        "cv": "accession.species.cultivar_epithet",
    },
    {
        "qty": "3",
        "code": "1",
        "acc": "2001.1",
        "loc": "SE",
        "gen": "Maxillaria",
        "hybrid": "",
        "sp": "variabilis",
        "infrasp": "var. unipunctata",
        "cv": "",
    },
]


plant_csv_search_by = ["code", "acc"]


def create_csv(
    records: list[dict], out_dir: str, name: str = "test.csv"
) -> str:
    """Create a temporary csv file.

    :param records: a list of dicts of lines as they should be written.
        NOTE:
        To include a mapping row it must be the first dict in the list.
        To include a domain column it should be the first item in the dicts.
    :param out_dir: directory to write `test.csv` file to.
    :param name: optional, the filename as a string, default: `test.csv`
    :return: fully qualified filename as a string.
    """
    name = "test.csv"
    path = Path(out_dir) / name
    with path.open("w") as f:
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
            "domain": "plant",
            "id": "id",
            "plant": "code",
            "acc": "accession.code",
            "species": "accession.species",
        }
        field_list = fields.copy()
        del field_list["domain"]
        exporter.presenter.fields = list(field_list.items())
        out = [
            {
                "domain": "plant",
                "id": "1",
                "plant": "1",
                "acc": "2001.1",
                "species": "Maxillaria s. str variabilis",
            },
            {
                "domain": "plant",
                "id": "2",
                "plant": "1",
                "acc": "2001.2",
                "species": "Encyclia cochleata",
            },
        ]
        out_file = Path(self.temp_dir.name) / "test.csv"
        exporter.filename = str(out_file)
        exporter.run()
        with out_file.open("r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            field_map = next(reader)
            self.assertEqual(field_map, fields)
            rec = next(reader)
            self.assertEqual(rec, out[0])
            rec = next(reader)
            self.assertEqual(rec, out[1])
        self.assertEqual(prefs.prefs.get(f"{CSV_IO_PREFS}.plant"), field_list)
        exporter.presenter.cleanup()

    def test_export_plants_w_notes(self):
        plt = self.session.query(Plant).get(1)
        plt.notes.append(PlantNote(category="test1", note="test note"))
        plt.notes.append(PlantNote(category="[test2]", note="test1"))
        plt.notes.append(PlantNote(category="[test2]", note="test2"))
        plt.notes.append(PlantNote(category="{test3:1}", note="test1"))
        plt.notes.append(PlantNote(category="{test3:2}", note="test2"))
        plt.notes.append(
            PlantNote(category="<test4>", note='{"key": "value"}')
        )
        self.session.add(plt)
        self.session.commit()
        mock_view = MockView()
        mock_view.selection = self.session.query(Plant).all()
        exporter = CSVExporter(mock_view, open_=False)
        fields = {
            "domain": "plant",
            "id": "id",
            "test1": "Note",
            "test2": "Note",
            "test3": "Note",
            "test4": "Note",
            "{test3:1}": "Note",
        }
        field_list = fields.copy()
        del field_list["domain"]
        exporter.presenter.fields = list(field_list.items())
        out = [
            {
                "domain": "plant",
                "id": "1",
                "test1": "test note",
                "test2": "['test1', 'test2']",
                "test3": "{'1': 'test1', '2': 'test2'}",
                "test4": "{'key': 'value'}",
                "{test3:1}": "test1",
            }
        ]
        out_file = Path(self.temp_dir.name) / "test.csv"
        exporter.filename = str(out_file)
        exporter.run()
        with out_file.open("r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            field_map = next(reader)
            self.assertEqual(field_map, fields)
            rec = next(reader)
            self.assertEqual(rec, out[0])
        exporter.presenter.cleanup()

    def test_export_species(self):
        mock_view = MockView()
        mock_view.selection = (
            self.session.query(Species).filter(Species.id.in_([1, 15])).all()
        )
        exporter = CSVExporter(mock_view, open_=False)
        fields = {
            "domain": "species",
            "id": "id",
            "gen": "genus.epithet",
            "sp": "epithet",
            "infrasp": "infraspecific_parts",
            "cv": "cultivar_epithet",
        }
        field_list = fields.copy()
        del field_list["domain"]
        exporter.presenter.fields = list(field_list.items())
        out = [
            {
                "domain": "species",
                "id": "1",
                "gen": "Maxillaria",
                "sp": "variabilis",
                "infrasp": "",
                "cv": "",
            },
            {
                "domain": "species",
                "id": "15",
                "gen": "Encyclia",
                "sp": "cochleata",
                "infrasp": "subsp. cochleata var. cochleata",
                "cv": "Black",
            },
        ]
        out_file = Path(self.temp_dir.name) / "test.csv"
        exporter.filename = str(out_file)
        exporter.run()
        with out_file.open("r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            field_map = next(reader)
            self.assertEqual(field_map, fields)
            rec = next(reader)
            self.assertEqual(rec, out[0])
            rec = next(reader)
            logger.debug(rec)
            self.assertEqual(rec, out[1])
        exporter.presenter.cleanup()

    @mock.patch(
        "bauble.plugins.imex.csv_io.CSVExportDialogPresenter.start",
        return_value=Gtk.ResponseType.OK,
    )
    def test_export_species_w_note_empty_via_start(self, _mock_start):
        mock_view = MockView()
        mock_view.selection = (
            self.session.query(Species).filter(Species.id == 18).all()
        )
        exporter = CSVExporter(mock_view, open_=False)
        fields = {
            "domain": "species",
            "sp": "species",
            "field_note": "Empty",
            "fam": "genus.family.epithet",
            "value": "Note",
        }
        field_list = fields.copy()
        del field_list["domain"]
        exporter.presenter.fields = list(field_list.items())
        out = {
            "domain": "species",
            "sp": "Laelia lobata",
            "field_note": "",
            "fam": "Orchidaceae",
            "value": "high",
        }

        out_file = Path(self.temp_dir.name) / "test.csv"
        exporter.filename = str(out_file)
        exporter.start()
        with out_file.open("r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            field_map = next(reader)
            self.assertEqual(field_map, fields)
            rec = next(reader)
            self.assertEqual(rec, out)

    def test_mixed_types_raises(self):
        mock_view = MockView()
        plant = self.session.query(Plant).get(1)
        loc = self.session.query(Location).get(1)
        mock_view.selection = [loc, plant]
        from bauble.error import BaubleError

        with self.assertRaises(
            BaubleError, msg="Can only export search items of the same type."
        ):
            exporter = CSVExporter(mock_view, open_=False)
            self.assertFalse(hasattr(exporter, "presenter"))
            self.assertFalse(hasattr(exporter, "filename"))
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
        mock_view.selection = (
            self.session.query(Species).filter(Species.id == 18).all()
        )
        exporter = CSVExporter(mock_view, open_=False)
        out_file = Path(self.temp_dir.name) / "test.csv"
        exporter.presenter.view.reply_file_chooser_dialog = [str(out_file)]
        exporter.presenter.on_btnbrowse_clicked("button")
        self.assertEqual(
            exporter.presenter.view.values.get("out_filename_entry"),
            str(out_file),
        )
        exporter.presenter.cleanup()

    def test_on_filename_entry_changed(self):
        mock_view = MockView()
        mock_view.selection = (
            self.session.query(Species).filter(Species.id == 18).all()
        )
        exporter = CSVExporter(mock_view, open_=False)
        out_file = Path(self.temp_dir.name) / "test.csv"
        mock_view.reply_file_chooser_dialog = [str(out_file)]
        exporter.presenter.on_btnbrowse_clicked("button")
        self.assertEqual(
            exporter.presenter.view.values.get("out_filename_entry"),
            str(out_file),
        )
        exporter.presenter.on_filename_entry_changed("out_filename_entry")
        self.assertEqual(exporter.filename, str(out_file))
        self.assertEqual(
            prefs.prefs.get(CSV_EXPORT_DIR_PREF), self.temp_dir.name
        )
        exporter.presenter.cleanup()

    def test_on_name_entry_changed(self):
        mock_widget = mock.Mock()
        mock_widget.get_text.return_value = "Test"
        mock_view = MockView()
        mock_view.selection = (
            self.session.query(Species).filter(Species.id == 18).all()
        )
        exporter = CSVExporter(mock_view, open_=False)
        exporter.presenter.fields = [(None, None), (None, None)]
        with mock.patch.object(exporter.presenter, "grid") as mock_grid:
            mock_grid.child_get_property.return_value = 1
            exporter.presenter.on_name_entry_changed(mock_widget)
            self.assertEqual(
                exporter.presenter.fields, [("Test", None), (None, None)]
            )
        exporter.presenter.cleanup()

    def test_on_add_button_clicked(self):
        mock_view = MockView()
        mock_view.selection = (
            self.session.query(Species).filter(Species.id == 18).all()
        )
        exporter = CSVExporter(mock_view, open_=False)
        exporter.presenter.fields = [(None, None)]
        exporter.presenter.on_add_button_clicked("button")
        self.assertEqual(
            exporter.presenter.fields, [(None, None), (None, None)]
        )
        exporter.presenter.cleanup()

    def test_on_remove_button_clicked(self):
        mock_view = MockView()
        mock_view.selection = (
            self.session.query(Species).filter(Species.id == 18).all()
        )
        exporter = CSVExporter(mock_view, open_=False)
        exporter.presenter.fields = [(None, None), (None, None)]
        with mock.patch.object(exporter.presenter, "grid") as mock_grid:
            mock_grid.child_get_property.return_value = 1
            exporter.presenter.on_remove_button_clicked("button")
            self.assertEqual(exporter.presenter.fields, [(None, None)])
        exporter.presenter.cleanup()


class CSVExporterEditorTests(BaubleTestCase):
    @mock.patch("bauble.editor.GenericEditorView.start")
    def test_presenter_doesnt_leak(self, mock_start):
        import gc

        gc.collect()
        from gi.repository import Gtk

        mock_start.return_value = Gtk.ResponseType.OK
        from bauble.editor import GenericEditorView

        view = GenericEditorView(
            str(Path(__file__).resolve().parent / "csv_io.glade"),
            root_widget_name="csv_export_dialog",
        )
        mock_model = mock.MagicMock()
        mock_model.domain.__tablename__ = "tablename"
        presenter = CSVExportDialogPresenter(model=mock_model, view=view)
        presenter.start()
        presenter.cleanup()
        del presenter
        self.assertEqual(
            utils.gc_objects_by_type("CSVExportDialogPresenter"),
            [],
            "CSVExportDialogPresenter not deleted",
        )

    def test_relation_filter(self):
        Species.synonyms.parent._class = Species
        Species.accepted.parent._class = Species
        result = CSVExportDialogPresenter.relation_filter(
            "test", Species.synonyms.parent
        )
        self.assertFalse(result)
        result = CSVExportDialogPresenter.relation_filter(
            "test", Species.accepted.parent
        )
        self.assertTrue(result)
        # active should raise AttributeError
        result = CSVExportDialogPresenter.relation_filter(
            "test", Species.active
        )
        self.assertTrue(result)
        result = CSVExportDialogPresenter.relation_filter(
            "_default_vernacular_name", None
        )
        self.assertFalse(result)


class CSVExportToolTests(BaubleTestCase):
    @mock.patch("bauble.plugins.imex.csv_io.message_dialog")
    @mock.patch("bauble.gui")
    def test_no_search_view_asks_to_search_first(self, mock_gui, mock_dialog):
        mock_gui.get_view.return_value = None
        tool = CSVExportTool()
        result = tool.start()
        self.assertIsNone(result)
        mock_dialog.assert_called_with("Search for something first.")

    @mock.patch("bauble.plugins.imex.csv_io.message_dialog")
    @mock.patch("bauble.gui")
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
            "Search for something first. (No model)"
        )

    @mock.patch("bauble.gui")
    @mock.patch("bauble.plugins.imex.csv_io.CSVExporter")
    def test_exporter_start_return_none(self, mock_exporter, mock_gui):
        mock_instance = mock.Mock()
        mock_instance.start.return_value = None
        mock_exporter.return_value = mock_instance
        logger.debug("start %s", mock_exporter.start() is None)
        mock_searchview = mock.Mock()
        from bauble.view import SearchView

        mock_searchview.__class__ = SearchView
        mock_results_view = mock.Mock()
        mock_results_view.get_model.return_value = "something"
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
        importer.option = "1"
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
        importer.option = "2"
        importer.run()
        result = self.session.query(Plant).all()
        self.assertEqual(len(result), len(plant_full_csv_data) - 1)

    def test_update_plants_doesnt_add(self):
        start_plants = self.session.query(Plant).count()
        start_sp = self.session.query(Species).count()
        importer = self.importer
        importer.filename = create_csv(plant_full_csv_data, self.temp_dir.name)
        importer.search_by = plant_csv_search_by
        importer.fields = plant_full_csv_data[0]
        importer.domain = Plant
        importer.option = "0"
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
            {
                "id": "id",
                "code": "code",
                "name": "name",
                "soil": 'Note[category="soil_type"]',
                "irrigation": 'Note[category="irrig_type"]',
            },
            {
                "id": "10",
                "code": "BED1",
                "name": "Entrance",
                "soil": "clay",
                "irrigation": "drip",
            },
        ]
        importer.filename = create_csv(locs, self.temp_dir.name)
        importer.search_by = ["id"]
        importer.use_id = True
        importer.fields = locs[0]
        importer.domain = Location
        importer.option = "1"
        importer.run()
        result = self.session.query(Location).all()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].code, "BED1")
        self.assertEqual(result[0].id, 10)

    def test_add_plant_w_planted_date(self):
        plant = [
            {
                "qty": "quantity",
                "code": "code",
                "planted": "planted.date",
                "acc": "accession.code",
                "loc": "location.code",
                "fam": "accession.species.genus.family.epithet",
                "gen": "accession.species.genus.epithet",
                "hybrid": "accession.species.hybrid",
                "sp": "accession.species.epithet",
                "infrasp": "accession.species.infraspecific_parts",
                "cv": "accession.species.cultivar_epithet",
            },
            {
                "qty": "2",
                "code": "1",
                "planted": "29/09/2020 10:00:00 pm",
                "acc": "2021.0002",
                "loc": "bed2",
                "fam": "Myrtaceae",
                "gen": "Syzygium",
                "hybrid": "",
                "sp": "australe",
                "infrasp": "",
                "cv": "Bush Christmas",
            },
        ]
        start_plants = self.session.query(Plant).count()
        importer = self.importer
        importer.filename = create_csv(plant, self.temp_dir.name)
        importer.search_by = plant_csv_search_by
        importer.fields = plant[0]
        importer.domain = Plant
        importer.option = "1"
        importer.run()
        added_plant = self.session.query(Plant).get(1)
        logger.debug("added_plant: %s", added_plant)
        end_plants = self.session.query(Plant).count()
        # planted added
        self.assertEqual(len(added_plant.changes), 1)
        self.assertEqual(
            added_plant.planted.date,
            datetime(2020, 9, 29, 22, 0, 0).astimezone(None),
        )
        self.assertEqual(added_plant.planted.quantity, 2)
        # 1 plant are added
        self.assertEqual(end_plants, start_plants + 1)
        # quantity changed and a change was added.
        self.assertEqual(added_plant.quantity, 2)

    def test_add_accession_with_collection_data(self):
        # test allowing creating 1-1 relations
        acc = [
            {
                "acc_code": "code",
                "fam": "species.genus.family.epithet",
                "gen": "species.genus.epithet",
                "sp": "species.epithet",
                "date_accd": "date_accd",
                "recvd": "date_recvd",
                "prov_type": "prov_type",
                "prov_status": "wild_prov_status",
                "qty": "quantity_recvd",
                "recvd_type": "recvd_type",
                "source_name": "source.source_detail.name",
                "source_type": "source.source_detail.source_type",
                "collector": "source.collection.collector",
                "date_collected": "source.collection.date",
                "elevation": "source.collection.elevation",
                "el_accuracy": "source.collection.elevation_accy",
                "geo_acc": "source.collection.geo_accy",
                "habitat": "source.collection.habitat",
                "locale": "source.collection.locale",
                "lat": "source.collection.latitude",
                "long": "source.collection.longitude",
                "datum": "source.collection.gps_datum",
                "col_notes": "source.collection.notes",
            },
            {
                "acc_code": "2024.0002",
                "fam": "Myrtaceae",
                "gen": "Syzygium",
                "sp": "australe",
                "date_accd": "2024-01-31",
                "recvd": "2024-01-24",
                "prov_type": "Wild",
                "prov_status": "WildNative",
                "qty": "7",
                "recvd_type": "PLTS",
                "source_name": "Jade Green",
                "source_type": "Individual",
                "collector": "Peter Plant",
                "date_collected": "2024-01-10",
                "elevation": "5.0",
                "el_accuracy": "3.0",
                "geo_acc": "20.0",
                "habitat": "forest",
                "locale": "Mountain road",
                "lat": "-26.918",
                "long": "152.911",
                "datum": "WGS84",
                "col_notes": "in flower",
            },
        ]
        start_acc = self.session.query(Accession).count()
        start_source = self.session.query(Source).count()
        start_source_detail = self.session.query(SourceDetail).count()
        start_collection = self.session.query(Collection).count()
        importer = self.importer
        importer.filename = create_csv(acc, self.temp_dir.name)
        importer.search_by = ["acc_code"]
        importer.fields = acc[0]
        importer.domain = Accession
        importer.option = "1"
        importer.run()
        end_acc = self.session.query(Accession).count()
        end_source = self.session.query(Source).count()
        end_source_detail = self.session.query(SourceDetail).count()
        end_collection = self.session.query(Collection).count()

        self.assertEqual(end_acc, start_acc + 1)
        self.assertEqual(end_source, start_source + 1)
        self.assertEqual(end_source_detail, start_source_detail + 1)
        self.assertEqual(end_collection, start_collection + 1)

        added_acc = self.session.query(Accession).get(1)
        for k, v in acc[1].items():
            logger.debug("assert equal %s = %s", acc[0][k], v)
            self.assertEqual(str(attrgetter(acc[0][k])(added_acc)), v)

    def test_update_accession_with_collection_data(self):
        # first add working data (if this fails so should previous test)
        acc = [
            {
                "acc_code": "code",
                "fam": "species.genus.family.epithet",
                "gen": "species.genus.epithet",
                "sp": "species.epithet",
                "date_accd": "date_accd",
                "recvd": "date_recvd",
                "prov_type": "prov_type",
                "prov_status": "wild_prov_status",
                "qty": "quantity_recvd",
                "recvd_type": "recvd_type",
                "source_name": "source.source_detail.name",
                "source_type": "source.source_detail.source_type",
                "collector": "source.collection.collector",
                "date_collected": "source.collection.date",
                "elevation": "source.collection.elevation",
                "el_accuracy": "source.collection.elevation_accy",
                "geo_acc": "source.collection.geo_accy",
                "habitat": "source.collection.habitat",
                "locale": "source.collection.locale",
                "lat": "source.collection.latitude",
                "long": "source.collection.longitude",
                "datum": "source.collection.gps_datum",
                "col_notes": "source.collection.notes",
            },
            {
                "acc_code": "2024.0002",
                "fam": "Myrtaceae",
                "gen": "Syzygium",
                "sp": "australe",
                "date_accd": "2024-01-31",
                "recvd": "2024-01-24",
                "prov_type": "Wild",
                "prov_status": "WildNative",
                "qty": "7",
                "recvd_type": "PLTS",
                "source_name": "Jade Green",
                "source_type": "Individual",
                "collector": "Peter Plant",
                "date_collected": "2024-01-10",
                "elevation": "5.0",
                "el_accuracy": "3.0",
                "geo_acc": "20.0",
                "habitat": "forest",
                "locale": "Mountain road",
                "lat": "-26.918",
                "long": "152.911",
                "datum": "WGS84",
                "col_notes": "in flower",
            },
        ]
        start_acc = self.session.query(Accession).count()
        start_source = self.session.query(Source).count()
        start_source_detail = self.session.query(SourceDetail).count()
        start_collection = self.session.query(Collection).count()
        importer = self.importer
        importer.filename = create_csv(acc, self.temp_dir.name)
        importer.search_by = ["acc_code"]
        importer.fields = acc[0]
        importer.domain = Accession
        importer.option = "1"
        importer.run()
        # add update the same data (should only update)
        acc = [
            {
                "acc_code": "code",
                "fam": "species.genus.family.epithet",
                "gen": "species.genus.epithet",
                "sp": "species.epithet",
                "date_accd": "date_accd",
                "recvd": "date_recvd",
                "prov_type": "prov_type",
                "prov_status": "wild_prov_status",
                "qty": "quantity_recvd",
                "recvd_type": "recvd_type",
                "source_name": "source.source_detail.name",
                "source_type": "source.source_detail.source_type",
                "collector": "source.collection.collector",
                "date_collected": "source.collection.date",
                "elevation": "source.collection.elevation",
                "el_accuracy": "source.collection.elevation_accy",
                "geo_acc": "source.collection.geo_accy",
                "habitat": "source.collection.habitat",
                "locale": "source.collection.locale",
                "lat": "source.collection.latitude",
                "long": "source.collection.longitude",
                "datum": "source.collection.gps_datum",
                "col_notes": "source.collection.notes",
            },
            {
                "acc_code": "2024.0002",
                "fam": "Myrtaceae",
                "gen": "Syzygium",
                "sp": "australe",
                "date_accd": "2024-01-31",
                "recvd": "2021-01-24",  # updated
                "prov_type": "Wild",
                "prov_status": "WildNative",
                "qty": "9",  # updated
                "recvd_type": "PLTS",
                "source_name": "Peter Plant",  # update
                "source_type": "Individual",
                "collector": "Jade Green",  # update
                "date_collected": "2024-01-10",
                "elevation": "7.0",  # update
                "el_accuracy": "3.0",
                "geo_acc": "20.0",
                "habitat": "rainforest",  # update
                "locale": "Mountain road",
                "lat": "-26.918",
                "long": "152.911",
                "datum": "WGS84",
                "col_notes": "in flower",
            },
        ]
        importer = self.importer
        importer.filename = create_csv(acc, self.temp_dir.name)
        importer.search_by = ["acc_code"]
        importer.fields = acc[0]
        importer.domain = Accession
        importer.option = "2"  # add/update
        importer.run()

        end_acc = self.session.query(Accession).count()
        end_source = self.session.query(Source).count()
        end_source_detail = self.session.query(SourceDetail).count()
        end_collection = self.session.query(Collection).count()

        self.assertEqual(end_acc, start_acc + 1)
        self.assertEqual(end_source, start_source + 1)
        # do want an extra source_detail added
        self.assertEqual(end_source_detail, start_source_detail + 2)
        self.assertEqual(end_collection, start_collection + 1)

        added_acc = self.session.query(Accession).get(1)
        for k, v in acc[1].items():
            logger.debug("assert equal %s = %s", acc[0][k], v)
            self.assertEqual(str(attrgetter(acc[0][k])(added_acc)), v)

    def test_update_accession_with_no_collection_data_ignores(self):
        # first add working data (if this fails so should previous test)
        acc = [
            {
                "acc_code": "code",
                "fam": "species.genus.family.epithet",
                "gen": "species.genus.epithet",
                "sp": "species.epithet",
                "date_accd": "date_accd",
                "recvd": "date_recvd",
                "prov_type": "prov_type",
                "prov_status": "wild_prov_status",
                "qty": "quantity_recvd",
                "recvd_type": "recvd_type",
                "source_name": "source.source_detail.name",
                "source_type": "source.source_detail.source_type",
            },
            {
                "acc_code": "2024.0002",
                "fam": "Myrtaceae",
                "gen": "Syzygium",
                "sp": "australe",
                "date_accd": "2024-01-31",
                "recvd": "2024-01-24",
                "prov_type": "Wild",
                "prov_status": "WildNative",
                "qty": "7",
                "recvd_type": "PLTS",
                "source_name": "Jade Green",
                "source_type": "Individual",
            },
        ]
        start_acc = self.session.query(Accession).count()
        start_source = self.session.query(Source).count()
        start_source_detail = self.session.query(SourceDetail).count()
        start_collection = self.session.query(Collection).count()
        importer = self.importer
        importer.filename = create_csv(acc, self.temp_dir.name)
        importer.search_by = ["acc_code"]
        importer.fields = acc[0]
        importer.domain = Accession
        importer.option = "1"
        importer.run()

        # add update the same data but with an empty collection entry
        acc = [
            {
                "acc_code": "code",
                "fam": "species.genus.family.epithet",
                "gen": "species.genus.epithet",
                "sp": "species.epithet",
                "date_accd": "date_accd",
                "recvd": "date_recvd",
                "prov_type": "prov_type",
                "prov_status": "wild_prov_status",
                "qty": "quantity_recvd",
                "recvd_type": "recvd_type",
                "source_name": "source.source_detail.name",
                "source_type": "source.source_detail.source_type",
                "collector": "source.collection.collector",
            },
            {
                "acc_code": "2024.0002",
                "fam": "Myrtaceae",
                "gen": "Syzygium",
                "sp": "australe",
                "date_accd": "2024-01-31",
                "recvd": "2021-01-24",
                "prov_type": "Wild",
                "prov_status": "WildNative",
                "qty": "9",
                "recvd_type": "PLTS",
                "source_name": "Peter Plant",
            },
        ]
        importer = self.importer
        importer.filename = create_csv(acc, self.temp_dir.name)
        importer.search_by = ["acc_code"]
        importer.fields = acc[0]
        importer.domain = Accession
        importer.option = "2"  # add/update
        importer.run()

        end_acc = self.session.query(Accession).count()
        end_source = self.session.query(Source).count()
        end_source_detail = self.session.query(SourceDetail).count()
        end_collection = self.session.query(Collection).count()

        self.assertEqual(end_acc, start_acc + 1)
        self.assertEqual(end_source, start_source + 1)
        # do want both extra source_details added
        self.assertEqual(end_source_detail, start_source_detail + 2)
        # no collection should have been added
        self.assertEqual(end_collection, start_collection)

    @mock.patch("bauble.utils.desktop.open")
    @mock.patch(
        "bauble.utils.Gtk.MessageDialog.run", return_value=Gtk.ResponseType.YES
    )
    def test_update_accession_with_unresolved_collection_data(
        self, mock_dialog, mock_open
    ):
        start_acc = self.session.query(Accession).count()
        start_source = self.session.query(Source).count()
        start_source_detail = self.session.query(SourceDetail).count()
        start_collection = self.session.query(Collection).count()
        acc = [
            {
                "acc_code": "code",
                "fam": "species.genus.family.epithet",
                "gen": "species.genus.epithet",
                "sp": "species.epithet",
                "date_accd": "date_accd",
                "recvd": "date_recvd",
                "prov_type": "prov_type",
                "prov_status": "wild_prov_status",
                "qty": "quantity_recvd",
                "recvd_type": "recvd_type",
                "source_name": "source.source_detail.name",
                "source_type": "source.source_detail.source_type",
                "collector": "source.collection.boom",  # bad key
            },
            {
                "acc_code": "2024.0002",
                "fam": "Myrtaceae",
                "gen": "Syzygium",
                "sp": "australe",
                "date_accd": "2024-01-31",
                "recvd": "2021-01-24",
                "prov_type": "Wild",
                "prov_status": "WildNative",
                "qty": "9",
                "recvd_type": "PLTS",
                "source_name": "Peter Plant",
                "source_type": "Individual",
                "collector": "Peter Plant",
            },
        ]
        importer = self.importer
        importer.filename = create_csv(acc, self.temp_dir.name)
        importer.search_by = ["acc_code"]
        importer.fields = acc[0]
        importer.domain = Accession
        importer.option = "2"  # add/update
        importer.run()

        end_acc = self.session.query(Accession).count()
        end_source = self.session.query(Source).count()
        end_source_detail = self.session.query(SourceDetail).count()
        end_collection = self.session.query(Collection).count()

        self.assertEqual(end_acc, start_acc)
        self.assertEqual(end_source, start_source)
        self.assertEqual(end_source_detail, start_source_detail)
        self.assertEqual(end_collection, start_collection)
        mock_dialog.assert_called()
        mock_open.assert_called()
        with open(mock_open.call_args.args[0], "r", encoding="utf-8-sig") as f:
            import csv

            reader = csv.DictReader(f)
            for record in reader:
                self.assertEqual(int(record["__line_#"]), 0)

    def test_add_synonym_species_w_accepted(self):
        # i.e. we want to import a species and all its synonyms
        species = [
            {
                "fam": "genus.family.epithet",
                "gen": "genus.epithet",
                "epithet": "epithet",
                "accepted_fam": "_accepted.species.genus.family.epithet",
                "accepted_gen": "_accepted.species.genus.epithet",
                "accpeted_epithet": "_accepted.species.epithet",
            },
            {
                "fam": "Myrtaceae",
                "gen": "Acmena",
                "epithet": "ingens",
                "accepted_fam": "Myrtaceae",
                "accepted_gen": "Acmena",
                "accpeted_epithet": "brachyandra",
            },
            {
                "fam": "Myrtaceae",
                "gen": "Syzygium",
                "epithet": "ingens",
                "accepted_fam": "Myrtaceae",
                "accepted_gen": "Acmena",
                "accpeted_epithet": "brachyandra",
            },
        ]
        start_sp = self.session.query(Species).count()
        importer = self.importer
        importer.filename = create_csv(species, self.temp_dir.name)
        importer.search_by = ["fam", "gen", "epithet"]
        importer.fields = species[0]
        importer.domain = Species
        importer.option = "2"
        importer.run()
        end_sp = self.session.query(Species).count()

        self.assertEqual(end_sp, start_sp + 3)

        added_sp = (
            self.session.query(Species)
            .join(Genus)
            .filter(Species.epithet == "ingens", Genus.epithet == "Acmena")
            .one()
        )
        for k, v in species[1].items():
            logger.debug("assert equal %s = %s", species[0][k], v)
            self.assertEqual(str(attrgetter(species[0][k])(added_sp)), v)

        added_sp = (
            self.session.query(Species)
            .join(Genus)
            .filter(Species.epithet == "ingens", Genus.epithet == "Syzygium")
            .one()
        )
        added_sp = self.session.query(Species).get(3)
        for k, v in species[2].items():
            logger.debug("assert equal %s = %s", species[0][k], v)
            self.assertEqual(str(attrgetter(species[0][k])(added_sp)), v)

    def test_add_synonym_species_w_accepted_association_proxy(self):
        # i.e. we want to import a species and all its synonyms
        species = [
            {
                "fam": "genus.family.epithet",
                "gen": "genus.epithet",
                "epithet": "epithet",
                "accepted_fam": "accepted.genus.family.epithet",
                "accepted_gen": "accepted.genus.epithet",
                "accpeted_epithet": "accepted.epithet",
            },
            {
                "fam": "Myrtaceae",
                "gen": "Acmena",
                "epithet": "ingens",
                "accepted_fam": "Myrtaceae",
                "accepted_gen": "Acmena",
                "accpeted_epithet": "brachyandra",
            },
            {
                "fam": "Myrtaceae",
                "gen": "Syzygium",
                "epithet": "ingens",
                "accepted_fam": "Myrtaceae",
                "accepted_gen": "Acmena",
                "accpeted_epithet": "brachyandra",
            },
        ]
        start_sp = self.session.query(Species).count()
        importer = self.importer
        importer.filename = create_csv(species, self.temp_dir.name)
        importer.search_by = ["fam", "gen", "epithet"]
        importer.fields = species[0]
        importer.domain = Species
        importer.option = "2"
        importer.run()
        end_sp = self.session.query(Species).count()

        self.assertEqual(end_sp, start_sp + 3)

        added_sp = (
            self.session.query(Species)
            .join(Genus)
            .filter(Species.epithet == "ingens", Genus.epithet == "Acmena")
            .one()
        )
        for k, v in species[1].items():
            logger.debug("assert equal %s = %s", species[0][k], v)
            self.assertEqual(str(attrgetter(species[0][k])(added_sp)), v)

        added_sp = (
            self.session.query(Species)
            .join(Genus)
            .filter(Species.epithet == "ingens", Genus.epithet == "Syzygium")
            .one()
        )
        for k, v in species[2].items():
            logger.debug("assert equal %s = %s", species[0][k], v)
            self.assertEqual(str(attrgetter(species[0][k])(added_sp)), v)

    def test_update_synonym_species_w_accepted_association_proxy(self):
        # first add working data (if this fails so should previous test)
        species = [
            {
                "fam": "genus.family.epithet",
                "gen": "genus.epithet",
                "epithet": "epithet",
                "accepted_fam": "accepted.genus.family.epithet",
                "accepted_gen": "accepted.genus.epithet",
                "accpeted_epithet": "accepted.epithet",
            },
            {
                "fam": "Myrtaceae",
                "gen": "Acmena",
                "epithet": "ingens",
                "accepted_fam": "Myrtaceae",
                "accepted_gen": "Acmena",
                "accpeted_epithet": "brachyandra",
            },
            {
                "fam": "Myrtaceae",
                "gen": "Syzygium",
                "epithet": "ingens",
                "accepted_fam": "Myrtaceae",
                "accepted_gen": "Acmena",
                "accpeted_epithet": "brachyandra",
            },
        ]
        start_sp = self.session.query(Species).count()
        importer = self.importer
        importer.filename = create_csv(species, self.temp_dir.name)
        importer.search_by = ["fam", "gen", "epithet"]
        importer.fields = species[0]
        importer.domain = Species
        importer.option = "2"
        importer.run()
        acmena_ingens = (
            self.session.query(Species)
            .join(Genus)
            .filter(Species.epithet == "ingens", Genus.epithet == "Acmena")
            .one()
        )
        syzygium_ingens = (
            self.session.query(Species)
            .join(Genus)
            .filter(Species.epithet == "ingens", Genus.epithet == "Syzygium")
            .one()
        )
        acmena_brachyandra = (
            self.session.query(Species)
            .join(Genus)
            .filter(
                Species.epithet == "brachyandra", Genus.epithet == "Acmena"
            )
            .one()
        )
        self.assertEqual(syzygium_ingens.accepted, acmena_brachyandra)
        self.assertEqual(acmena_ingens.accepted, acmena_brachyandra)
        # change the accepted to be one of the previously synonym names
        species = [
            {
                "fam": "genus.family.epithet",
                "gen": "genus.epithet",
                "epithet": "epithet",
                "accepted_fam": "accepted.genus.family.epithet",
                "accepted_gen": "accepted.genus.epithet",
                "accpeted_epithet": "accepted.epithet",
            },
            {
                "fam": "Myrtaceae",
                "gen": "Acmena",
                "epithet": "brachyandra",
                "accepted_fam": "Myrtaceae",
                "accepted_gen": "Acmena",
                "accpeted_epithet": "ingens",
            },
            {
                "fam": "Myrtaceae",
                "gen": "Syzygium",
                "epithet": "ingens",
                "accepted_fam": "Myrtaceae",
                "accepted_gen": "Acmena",
                "accpeted_epithet": "ingens",
            },
        ]
        importer.filename = create_csv(species, self.temp_dir.name)
        importer.search_by = ["fam", "gen", "epithet"]
        importer.fields = species[0]
        importer.domain = Species
        importer.option = "2"
        importer.run()
        end_sp = self.session.query(Species).count()

        # should not add any more
        self.assertEqual(end_sp, start_sp + 3)

        self.session.refresh(acmena_ingens)
        self.session.refresh(acmena_brachyandra)
        self.session.refresh(syzygium_ingens)

        added_sp = (
            self.session.query(Species)
            .join(Genus)
            .filter(
                Species.epithet == "brachyandra", Genus.epithet == "Acmena"
            )
            .one()
        )
        for k, v in species[1].items():
            logger.debug("assert equal %s = %s", species[0][k], v)
            self.assertEqual(str(attrgetter(species[0][k])(added_sp)), v)

        added_sp = (
            self.session.query(Species)
            .join(Genus)
            .filter(Species.epithet == "ingens", Genus.epithet == "Syzygium")
            .one()
        )
        for k, v in species[2].items():
            logger.debug("assert equal %s = %s", species[0][k], v)
            self.assertEqual(str(attrgetter(species[0][k])(added_sp)), v)

        # check that epithets haven't changed
        self.assertEqual(acmena_ingens.epithet, "ingens")
        self.assertEqual(acmena_brachyandra.epithet, "brachyandra")
        self.assertEqual(syzygium_ingens.epithet, "ingens")


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
        importer.option = "1"
        importer.run()
        result = self.session.query(Plant).count()
        # test correct amount added
        end_plants = start_plants + len(plant_full_csv_data) - 1
        self.assertEqual(result, end_plants)
        # check some data
        plts = self.session.query(Plant).all()
        accs = [i.get("acc") for i in plant_full_csv_data[1:]]
        spp = ["Dyckia sp. (red/brown)", "Syzygium australe 'Bush Christmas'"]
        self.assertIn(plts[-1].accession.code, accs)
        self.assertIn(str(plts[-1].accession.species), spp)
        self.assertIn(plts[-2].accession.code, accs)
        self.assertIn(str(plts[-2].accession.species), spp)

    def test_update_accession_w_str_dates(self):
        acc = [
            {"id": "id", "recvd": "date_recvd", "created": "_created"},
            {
                "id": "1",
                "recvd": "29/09/2020",
                "created": "29/09/2020 10:00:00 pm",
            },
        ]
        start_accs = self.session.query(Accession).count()
        importer = self.importer
        importer.filename = create_csv(acc, self.temp_dir.name)
        importer.search_by = ["id"]
        importer.fields = acc[0]
        importer.domain = Accession
        importer.option = "0"
        importer.run()
        end_accs = self.session.query(Accession).count()
        # test no additions
        updated_acc = self.session.query(Accession).get(1)
        self.assertEqual(end_accs, start_accs)
        # test the date.
        self.assertEqual(updated_acc.date_recvd, datetime(2020, 9, 29).date())
        self.assertEqual(
            updated_acc._created,
            datetime(2020, 9, 29, 22, 0, 0).astimezone(None),
        )

    @mock.patch(
        "bauble.plugins.imex.csv_io.CSVImportDialogPresenter.start",
        return_value=Gtk.ResponseType.OK,
    )
    def test_add_plants_w_start(self, _mock_start):
        start_plants = self.session.query(Plant).count()
        importer = self.importer
        importer.filename = create_csv(plant_full_csv_data, self.temp_dir.name)
        importer.search_by = plant_csv_search_by
        importer.fields = plant_full_csv_data[0]
        importer.domain = Plant
        importer.option = "1"
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
        update_plant["fam"] = "Orchidaceae"
        plants = plant_full_csv_data + [update_plant]
        logger.debug("plants: %s", plants)
        importer.filename = create_csv(plants, self.temp_dir.name)
        importer.search_by = plant_csv_search_by
        importer.fields = plant_full_csv_data[0]
        importer.domain = Plant
        importer.option = "2"
        importer.run()
        end_plants = self.session.query(Plant).count()
        end_sp = self.session.query(Species).count()
        # check the plant was updated
        updated_plant = self.session.query(Plant).get(1)
        # quantity changed
        self.assertEqual(updated_plant.quantity, 3)
        # species changed
        self.assertEqual(
            str(updated_plant.accession.species),
            "Maxillaria s. str variabilis var. unipunctata",
        )
        # location changed
        self.assertEqual(updated_plant.location.code, "SE")
        # 2 plants added
        self.assertEqual(end_plants, start_plants + 2)
        # 3 new species
        self.assertEqual(end_sp, start_sp + 3)

    def test_update_plants_geojson(self):
        start_plants = self.session.query(Plant).count()
        importer = self.importer
        plants_csv_data = [
            {"id": "id", "geojson": "geojson"},
            {
                "id": 1,
                "geojson": "{'type': 'Point', 'coordinates': [0.0, 0.0]}",
            },
        ]
        importer.filename = create_csv(plants_csv_data, self.temp_dir.name)
        importer.search_by = ["id"]
        importer.fields = plants_csv_data[0]
        importer.domain = Plant
        importer.option = "0"
        importer.run()
        updated_plant = self.session.query(Plant).get(1)
        end_plants = self.session.query(Plant).count()
        # check the plant was updated
        self.assertEqual(updated_plant.geojson.get("type"), "Point")
        self.assertEqual(len(updated_plant.geojson.get("coordinates")), 2)
        self.assertEqual(updated_plant.geojson.get("coordinates")[0], 0.0)
        # nothing added
        self.assertEqual(end_plants, start_plants)
        # correct history
        hist = (
            self.session.query(db.History.values)
            .order_by(db.History.id.desc())
            .first()
        )
        self.assertEqual(hist.values.get("id"), 1)
        self.assertEqual(
            hist.values.get("geojson"),
            [{"type": "Point", "coordinates": [0.0, 0.0]}, None],
        )

        # test setting to None
        plants_csv_data = [
            {"id": "id", "geojson": "geojson"},
            {"id": 1, "geojson": ""},
        ]
        importer.filename = create_csv(plants_csv_data, self.temp_dir.name)
        importer.search_by = ["id"]
        importer.fields = plants_csv_data[0]
        importer.domain = Plant
        importer.option = "0"
        importer.run()
        self.session.expire_all()
        self.assertIsNone(updated_plant.geojson)
        # correct history
        hist = (
            self.session.query(db.History.values)
            .order_by(db.History.id.desc())
            .first()
        )
        self.assertEqual(hist.values.get("id"), 1)
        self.assertEqual(
            hist.values.get("geojson"),
            [None, {"type": "Point", "coordinates": [0.0, 0.0]}],
        )

    def test_update_plants(self):
        start_plants = self.session.query(Plant).count()
        start_sp = self.session.query(Species).count()
        importer = self.importer
        importer.filename = create_csv(
            update_plants_csv_data, self.temp_dir.name
        )
        importer.search_by = plant_csv_search_by
        importer.fields = plant_full_csv_data[0]
        importer.domain = Plant
        importer.option = "0"
        importer.run()
        updated_plant = self.session.query(Plant).get(1)
        end_plants = self.session.query(Plant).count()
        end_sp = self.session.query(Species).count()
        # check the plant was updated
        # quantity changed
        self.assertEqual(updated_plant.quantity, 3)
        # location changed
        self.assertEqual(updated_plant.location.code, "SE")
        # species changed
        self.assertEqual(
            str(updated_plant.accession.species),
            "Maxillaria s. str variabilis var. unipunctata",
        )
        # no plants added
        self.assertEqual(end_plants, start_plants)
        # one new species
        self.assertEqual(end_sp, start_sp + 1)

    @mock.patch("bauble.utils.desktop.open")
    @mock.patch(
        "bauble.utils.Gtk.MessageDialog.run", return_value=Gtk.ResponseType.YES
    )
    def test_update_plants_bad_data(self, mock_dialog, mock_open):
        start_plants = self.session.query(Plant).count()
        start_sp = self.session.query(Species).count()
        importer = self.importer
        bad_data = [i.copy() for i in update_plants_csv_data]
        bad_data[1]["qty"] = "BAD_DATA"
        importer.filename = create_csv(bad_data, self.temp_dir.name)
        importer.search_by = plant_csv_search_by
        importer.fields = plant_full_csv_data[0]
        importer.domain = Plant
        importer.option = "0"
        importer.run()
        mock_dialog.assert_called()
        mock_open.assert_called()
        with open(mock_open.call_args.args[0], "r", encoding="utf-8-sig") as f:
            import csv

            reader = csv.DictReader(f)
            for record in reader:
                self.assertEqual(int(record["__line_#"]), 1)
        updated_plant = self.session.query(Plant).get(1)
        end_plants = self.session.query(Plant).count()
        end_sp = self.session.query(Species).count()
        # check the plant was not changed
        self.assertEqual(updated_plant.quantity, 1)
        self.assertEqual(updated_plant.location.code, "RBW")
        self.assertEqual(
            str(updated_plant.accession.species),
            "Maxillaria s. str variabilis",
        )
        # no plants added
        self.assertEqual(end_plants, start_plants)
        # no new species
        self.assertEqual(end_sp, start_sp)

    def test_update_plant_quantity_planted_date(self):
        # add the plant here so a planted entry is created by the event
        # listener
        acc = self.session.query(Accession).get(1)
        acc_code = acc.code
        loc = self.session.query(Location).get(1)
        plt = Plant(accession=acc, code="3", quantity=1, location=loc)
        self.session.add(plt)
        self.session.commit()
        self.assertEqual(plt.quantity, 1)
        plt_id = int(plt.id)
        # need to expire plt so we reload later
        self.session.expire(plt)
        start_plants = self.session.query(Plant).count()
        importer = self.importer
        plant = [
            {
                "code": "code",
                "acc": "accession.code",
                "qty": "quantity",
                "planted": "planted.date",
            },
            {
                "code": "3",
                "acc": acc_code,
                "qty": "4",
                "planted": "29/09/2020 10:00:00 pm",
            },
        ]
        importer.filename = create_csv(plant, self.temp_dir.name)
        importer.search_by = plant_csv_search_by
        importer.fields = plant[0]
        importer.domain = Plant
        importer.option = "0"
        importer.run()
        updated_plant = self.session.query(Plant).get(plt_id)
        logger.debug("updated_plant: %s", updated_plant)
        end_plants = self.session.query(Plant).count()
        # date changed, quantity the same
        date = datetime(2020, 9, 29, 22, 0, 0).astimezone(None)
        self.assertEqual(updated_plant.planted.date, date)
        self.assertEqual(updated_plant.planted.quantity, 1)
        # no plants are added
        self.assertEqual(end_plants, start_plants)
        # quantity changed and a change was added.
        self.assertEqual(len(updated_plant.changes), 2)
        # change that isn't planted
        chg = [i for i in updated_plant.changes if i.date != date][0]
        self.assertEqual(chg.quantity, 3)
        self.assertEqual(updated_plant.quantity, 4)

    def test_update_plant_quantity_death_date(self):
        # add the plant here so a planted entry is created by the event
        # listener
        acc = self.session.query(Accession).get(1)
        acc_code = acc.code
        loc = self.session.query(Location).get(1)
        plt = Plant(accession=acc, code="3", quantity=1, location=loc)
        self.session.add(plt)
        self.session.commit()
        # add a planted entry
        plt.planted.date = "29/09/2010 10:00:00 pm"
        self.session.add(plt)
        self.session.commit()
        self.assertEqual(plt.quantity, 1)
        plt_id = int(plt.id)
        # need to expire plt so we reload later
        self.session.expire(plt)
        start_plants = self.session.query(Plant).count()
        importer = self.importer
        plant = [
            {
                "code": "code",
                "acc": "accession.code",
                "qty": "quantity",
                "death": "death.date",
            },
            {
                "code": "3",
                "acc": acc_code,
                "qty": "0",
                "death": "29/09/2020 10:00:00 pm",
            },
        ]
        importer.filename = create_csv(plant, self.temp_dir.name)
        importer.search_by = plant_csv_search_by
        importer.fields = plant[0]
        importer.domain = Plant
        importer.option = "0"
        importer.run()
        updated_plant = self.session.query(Plant).get(plt_id)
        logger.debug("updated_plant: %s", updated_plant)
        end_plants = self.session.query(Plant).count()
        # quantity changed
        self.assertEqual(updated_plant.quantity, 0)
        # death date added
        self.assertEqual(
            updated_plant.death.date,
            datetime(2020, 9, 29, 22, 0, 0).astimezone(None),
        )
        # no plants are added
        self.assertEqual(end_plants, start_plants)
        # expire
        self.session.expire(plt)
        # rerun with updated date.
        # test can update the death date.
        plant = [
            {
                "code": "code",
                "acc": "accession.code",
                "qty": "quantity",
                "death": "death.date",
            },
            {
                "code": "3",
                "acc": acc_code,
                "qty": "0",
                "death": "29/09/2021 10:00:00 pm",
            },
        ]
        importer.filename = create_csv(plant, self.temp_dir.name)
        importer.search_by = plant_csv_search_by
        importer.fields = plant[0]
        importer.domain = Plant
        importer.option = "0"
        importer.run()
        updated_plant = self.session.query(Plant).get(plt_id)
        # death date updated
        self.assertEqual(
            updated_plant.death.date,
            datetime(2021, 9, 29, 22, 0, 0).astimezone(None),
        )

    def test_update_accession_w_notes(self):
        acc = [
            {"code": "code", "test": "Note"},
            {"code": "2020.1", "test": "test note"},
        ]
        start_accs = self.session.query(Accession).count()
        importer = self.importer
        importer.filename = create_csv(acc, self.temp_dir.name)
        importer.search_by = ["code"]
        importer.fields = acc[0]
        importer.domain = Accession
        importer.option = "0"
        importer.run()
        updated_acc = self.session.query(Accession).get(3)
        end_accs = self.session.query(Accession).count()
        # no acessions added
        self.assertEqual(end_accs, start_accs)
        notes = updated_acc.notes
        self.assertEqual(
            [i for i in notes if i.category == "test"][0].note, "test note"
        )
        # replace notes
        acc = [
            {"code": "code", "test": "Note"},
            {"code": "2020.1", "test": "test 2"},
        ]
        importer.replace_notes.add("test")
        importer.filename = create_csv(acc, self.temp_dir.name, "test2.csv")
        importer.run()
        self.session.expire_all()
        end_accs = self.session.query(Accession).count()
        # no acessions added
        self.assertEqual(end_accs, start_accs)
        # still only one note
        self.assertEqual(len(updated_acc.notes), 1)
        self.assertEqual(
            [i for i in updated_acc.notes if i.category == "test"][0].note,
            "test 2",
        )

    def test_add_location_w_notes_w_categories(self):
        start_locs = self.session.query(Location).count()
        locs = [
            {
                "code": "code",
                "name": "name",
                "soil": 'Note[category="soil_type"]',
                "irrigation": 'Note[category="irrig_type"]',
            },
            {
                "code": "BED1",
                "name": "Entrance",
                "soil": "clay",
                "irrigation": "drip",
            },
        ]
        importer = self.importer
        importer.filename = create_csv(locs, self.temp_dir.name)
        importer.search_by = ["code"]
        importer.fields = locs[0]
        importer.domain = Location
        importer.option = "1"
        importer.run()
        end_locs = self.session.query(Location).count()
        end_num = start_locs + len(locs) - 1
        self.assertEqual(end_locs, end_num)
        new_loc = (
            self.session.query(Location).filter(Location.code == "BED1").one()
        )
        self.assertEqual(new_loc.name, "Entrance")
        notes = new_loc.notes
        self.assertTrue(
            [i for i in notes if i.category == "soil_type"][0].note == "clay"
        )
        self.assertTrue(
            [i for i in notes if i.category == "irrig_type"][0].note == "drip"
        )

    def test_on_btnbrowse_clicked(self):
        importer = self.importer
        in_file = Path(self.temp_dir.name) / "test.csv"
        importer.presenter.view.reply_file_chooser_dialog = [str(in_file)]
        importer.presenter.on_btnbrowse_clicked("button")
        self.assertEqual(
            importer.presenter.view.values.get("in_filename_entry"),
            str(in_file),
        )

    def test_construct_grid(self):
        importer = self.importer
        importer.fields = {
            "domain": "location",
            "id": "id",
            "code": "code",
            "name": "name",
            "test": "Note",
        }
        importer.presenter.domain = Location
        importer.presenter._construct_grid()
        # check some components
        grid = importer.presenter.grid
        domain_lbl = grid.get_child_at(0, 0)
        self.assertEqual(domain_lbl.get_label(), "Domain:  <b>location</b>")
        from .csv_io import MATCH
        from .csv_io import NAME
        from .csv_io import OPTION
        from .csv_io import PATH

        id_chk_btn = grid.get_child_at(MATCH, 3)
        self.assertEqual(id_chk_btn.get_label(), "match")
        id_import_chk_btn = grid.get_child_at(OPTION, 3)
        self.assertEqual(id_import_chk_btn.get_label(), "import")
        name_label = grid.get_child_at(NAME, 5)
        self.assertEqual(name_label.get_label(), "name")
        path_label = grid.get_child_at(PATH, 5)
        self.assertEqual(path_label.get_label(), "name")
        self.assertIsNone(grid.get_child_at(MATCH, 5))
        self.assertIsNone(grid.get_child_at(OPTION, 5))
        note_replace_chk_btn = grid.get_child_at(OPTION, 6)
        self.assertEqual(note_replace_chk_btn.get_label(), "replace")

    def test_on_filename_entry_changed(self):
        importer = self.importer
        locs = [
            {"domain": "location", "code": "code", "name": "name"},
            {"domain": "location", "code": "BED1", "name": "Entrance"},
        ]
        in_file = create_csv(locs, self.temp_dir.name)
        importer.presenter.view.reply_file_chooser_dialog = [in_file]
        importer.presenter.on_btnbrowse_clicked("button")
        self.assertEqual(
            importer.presenter.view.values.get("in_filename_entry"), in_file
        )
        importer.presenter.on_filename_entry_changed("in_filename_entry")
        self.assertEqual(importer.filename, in_file)
        self.assertEqual(
            prefs.prefs.get(CSV_IMPORT_DIR_PREF), self.temp_dir.name
        )

    def test_on_filename_entry_changed_bad_name(self):
        importer = self.importer
        in_file = Path("bad_directory") / "test.csv"
        importer.presenter.view.reply_file_chooser_dialog = [str(in_file)]
        importer.presenter.on_btnbrowse_clicked("button")
        self.assertEqual(
            importer.presenter.view.values.get("in_filename_entry"),
            str(in_file),
        )
        importer.presenter.on_filename_entry_changed("in_filename_entry")
        self.assertEqual(importer.fields, None)
        self.assertEqual(importer.presenter.filename, None)
        self.assertNotEqual(
            prefs.prefs.get(CSV_IMPORT_DIR_PREF), self.temp_dir.name
        )

    def test_on_filename_entry_changed_bad_file(self):
        locs = [
            {"code": "code", "name": "name"},
            {"code": "BED1", "name": "Entrance"},
        ]
        importer = self.importer
        in_file = create_csv(locs, self.temp_dir.name)
        importer.presenter.view.reply_file_chooser_dialog = [in_file]
        importer.presenter.on_btnbrowse_clicked("button")
        self.assertEqual(
            importer.presenter.view.values.get("in_filename_entry"), in_file
        )
        importer.presenter.on_filename_entry_changed("in_filename_entry")
        self.assertIn(
            (importer.presenter.PROBLEM_INVALID_FILENAME),
            [i[0] for i in importer.presenter.problems],
        )
        self.assertEqual(importer.fields, None)
        self.assertEqual(
            prefs.prefs.get(CSV_IMPORT_DIR_PREF), self.temp_dir.name
        )

    def test_on_match_chk_button_change(self):
        importer = self.importer
        mock_button = mock.Mock()
        # set
        mock_button.get_active.return_value = True
        importer.presenter.on_match_chk_button_change(mock_button, "test")
        self.assertEqual(importer.search_by, {"test"})
        # unset
        mock_button.get_active.return_value = False
        importer.presenter.on_match_chk_button_change(mock_button, "test")
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
        importer.presenter.on_replace_chk_button_change(mock_button, "test")
        self.assertEqual(importer.replace_notes, {"test"})
        # unset
        mock_button.get_active.return_value = False
        importer.presenter.on_replace_chk_button_change(mock_button, "test")
        self.assertEqual(importer.replace_notes, set())

    def test_get_importable_fields(self):
        importer = self.importer
        presenter = importer.presenter
        field_map = {"domain": "location", "code": "code", "name": "name"}
        presenter.get_importable_fields(field_map)
        self.assertEqual(presenter.domain, Location)
        del field_map["domain"]
        self.assertEqual(importer.fields, field_map)

    def test_get_importable_fields_no_domain(self):
        importer = self.importer
        presenter = importer.presenter
        field_map = {"code": "code", "name": "name"}
        presenter.get_importable_fields(field_map)
        self.assertIsNone(importer.fields)
        self.assertIsNone(importer.domain)

    def test_get_importable_fields_w_tablename(self):
        importer = self.importer
        presenter = importer.presenter
        field_map = {"domain": "location", "loc": "location", "name": "name"}
        presenter.get_importable_fields(field_map)
        self.assertEqual(presenter.domain, Location)
        del field_map["domain"]
        field_map["loc"] = None
        self.assertEqual(importer.fields, field_map)

    def test_get_importable_fields_w_related_class(self):
        importer = self.importer
        presenter = importer.presenter
        field_map = {"domain": "accession", "code": "code", "sp": "species"}
        presenter.get_importable_fields(field_map)
        self.assertEqual(presenter.domain, Accession)
        del field_map["domain"]
        field_map["sp"] = None
        self.assertEqual(importer.fields, field_map)

    def test_get_importable_fields_bad_domain(self):
        # good domain, bad domain, with tablename, with related related class
        importer = self.importer
        presenter = importer.presenter
        field_map = {"domain": "none_domain", "code": "code", "name": "name"}
        presenter.get_importable_fields(field_map)
        self.assertEqual(presenter.domain, None)
        del field_map["domain"]
        self.assertEqual(importer.fields, None)

    def test_get_importable_fields_hybrid_property(self):
        importer = self.importer
        presenter = importer.presenter
        # can't import
        field_map = {
            "domain": "plant",
            "code": "code",
            "qual_name": "accession.qualified_name",
        }
        presenter.get_importable_fields(field_map)
        self.assertEqual(importer.fields, {"code": "code"})

        # can import
        field_map = {
            "domain": "plant",
            "code": "code",
            "cites": "accession.species.cites",
        }
        presenter.get_importable_fields(field_map)
        self.assertEqual(
            importer.fields,
            {"code": "code", "cites": "accession.species.cites"},
        )

    def test_get_importable_fields_no_importabke_fields(self):
        importer = self.importer
        presenter = importer.presenter
        field_map = {
            "domain": "plant",
            "qual_name": "accession.qualified_name",
        }
        presenter.get_importable_fields(field_map)
        self.assertIsNone(importer.fields)
        self.assertEqual(importer.domain, Plant)
