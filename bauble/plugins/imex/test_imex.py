# Copyright 2004-2010 Brett Adams
# Copyright 2015 Mario Frasca <mario@anche.no>.
# Copyright 2021-2023 Ross Demuth <rossdemuth123@gmail.com>
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

import csv
import logging
from unittest import mock

logger = logging.getLogger(__name__)

import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

from dateutil.parser import parse as date_parse
from sqlalchemy.exc import IntegrityError

import bauble
import bauble.plugins.garden.test_garden as garden_test
import bauble.plugins.plants.test_plants as plants_test
from bauble import db
from bauble import prefs
from bauble.plugins.garden import Accession
from bauble.plugins.garden import Collection
from bauble.plugins.garden import Location
from bauble.plugins.garden import Plant
from bauble.plugins.garden.accession import Voucher
from bauble.plugins.plants import Family
from bauble.plugins.plants import Genus
from bauble.plugins.plants import Species
from bauble.test import BaubleTestCase
from bauble.test import get_setUp_data_funcs

from . import GenericExporter
from . import GenericImporter
from . import is_importable_attr
from .csv_ import QUOTE_CHAR
from .csv_ import QUOTE_STYLE
from .csv_ import CSVBackup
from .csv_ import CSVRestore
from .xml import XMLExporter

family_data = [
    {"id": 1, "family": "Orchidaceae", "qualifier": None},
    {"id": 2, "family": "Myrtaceae"},
]
genus_data = [
    {"id": 1, "genus": "Calopogon", "family_id": 1, "author": "R. Br."},
    {"id": 2, "genus": "Panisea", "family_id": 1},
]
species_data = [
    {
        "id": 1,
        "sp": "tuberosus",
        "genus_id": 1,
        "sp_author": None,
        "full_sci_name": "Calopogon tuberosus",
    },
    {
        "id": 2,
        "sp": "albiflora",
        "genus_id": 2,
        "sp_author": "(Ridl.) Seidenf.",
        "full_sci_name": "Panisea albiflora (Ridl.) Seidenf.",
    },
    {
        "id": 3,
        "sp": "distelidia",
        "genus_id": 2,
        "sp_author": "I.D.Lund",
        "full_sci_name": "Panisea distelidia I.D.Lund",
    },
    {
        "id": 4,
        "sp": "zeylanica",
        "genus_id": 2,
        "sp_author": "(Hook.f.) Aver.",
        "full_sci_name": "Panisea zeylanica (Hook.f.) Aver.",
    },
]
accession_data = [
    {"id": 1, "species_id": 1, "code": "2015.0001"},
    {"id": 2, "species_id": 1, "code": "2015.0002"},
    {"id": 3, "species_id": 1, "code": "2015.0003", "private": True},
]
location_data = [
    {"id": 1, "code": "1"},
]
plant_data = [
    {"id": 1, "accession_id": 1, "location_id": 1, "code": "1", "quantity": 1},
    {"id": 2, "accession_id": 3, "location_id": 1, "code": "1", "quantity": 1},
]


class ImexTestCase(BaubleTestCase):
    def setUp(self):
        super().setUp()
        plants_test.setUp_data()
        garden_test.setUp_data()


class CSVTestImporter(CSVRestore):
    def on_error(self, exc):
        logger.debug(exc)


class PrefsUpdatedTest(BaubleTestCase):
    def test_prefs_update(self):
        # NOTE plugin.init() is called in BaubleTestCase.setUp if this plugin
        # exists the prefs in default/config.cfg should have been copied in.
        # tests pluginmgr.update_prefs
        self.assertTrue(prefs.prefs.get("shapefile.location.fields"))
        self.assertTrue(prefs.prefs.get("shapefile.plant.search_by"))


class CSVTests(ImexTestCase):
    def setUp(self):
        self.path = tempfile.mkdtemp()
        super().setUp()

        data = (
            ("family", family_data),
            ("genus", genus_data),
            ("species", species_data),
        )
        for table_name, data in data:
            filename = os.path.join(self.path, "%s.csv" % table_name)
            f = open(filename, "w", encoding="utf-8", newline="")
            format = {
                "delimiter": ",",
                "quoting": QUOTE_STYLE,
                "quotechar": QUOTE_CHAR,
            }

            fields = list(data[0].keys())
            f.write("%s\n" % ",".join(fields))
            writer = csv.DictWriter(f, fields, **format)
            writer.writerows(data)
            f.flush()
            f.close()
            importer = CSVTestImporter()
            importer.start([filename], force=True)

    def tearDown(self):
        shutil.rmtree(self.path)
        super().tearDown()

    def test_import_self_referential_table(self):
        """
        Test tables that are self-referenial are import in order.
        """
        geo_data = [
            {"id": 3, "code": "AR3", "name": "3", "level": 3, "parent_id": 1},
            {
                "id": 1,
                "code": "AR1",
                "name": "1",
                "level": 1,
                "parent_id": None,
            },
            {"id": 2, "code": "AR2", "name": "2", "level": 2, "parent_id": 1},
        ]
        filename = os.path.join(self.path, "geography.csv")
        f = open(filename, "w", encoding="utf-8", newline="")
        format = {
            "delimiter": ",",
            "quoting": QUOTE_STYLE,
            "quotechar": QUOTE_CHAR,
        }
        fields = list(geo_data[0].keys())
        f.write("%s\n" % ",".join(fields))
        f.flush()
        writer = csv.DictWriter(f, fields, **format)
        writer.writerows(geo_data)
        f.flush()
        f.close()
        importer = CSVTestImporter()
        importer.start([filename], force=True)

    def test_import_bool_column(self):
        sp = self.session.query(Species).get(1)
        self.session.add(Accession(species=sp, code="2023.0001"))
        self.session.commit()
        data = [
            {
                "herbarium": "BRI",
                "code": "1234",
                "accession_id": 1,
                "parent_material": "True",
            },
            {
                "herbarium": "SYD",
                "code": "4321",
                "accession_id": 1,
                "parent_material": "False",
            },
        ]
        filename = os.path.join(self.path, "voucher.csv")
        f = open(filename, "w", encoding="utf-8", newline="")
        format = {
            "delimiter": ",",
            "quoting": QUOTE_STYLE,
            "quotechar": QUOTE_CHAR,
        }
        fields = list(data[0].keys())
        writer = csv.DictWriter(f, fields, **format)
        writer.writeheader()
        writer.writerows(data)
        f.flush()
        f.close()
        importer = CSVTestImporter()
        importer.start([filename], force=True)

        voucher = self.session.query(Voucher).get(1)
        self.assertTrue(voucher.parent_material)

        voucher = self.session.query(Voucher).get(2)
        self.assertFalse(voucher.parent_material)

    def test_with_open_connection(self):
        """
        Test that the import doesn't stall if we have a connection
        open to Family while importing to the family table
        """
        # TODO this will not work on postgresql, open connections will stall.
        # Is this test therefore obsolete?
        # list(self.session.query(Family))
        filename = os.path.join(self.path, "family.csv")
        f = open(filename, "w", encoding="utf-8", newline="")
        format = {
            "delimiter": ",",
            "quoting": QUOTE_STYLE,
            "quotechar": QUOTE_CHAR,
        }
        fields = list(family_data[0].keys())
        f.write("%s\n" % ",".join(fields))
        writer = csv.DictWriter(f, fields, **format)
        writer.writerows(family_data)
        f.flush()
        f.close()
        importer = CSVTestImporter()
        importer.start([filename], force=True)
        # list(self.session.query(Family))

    def test_import_use_defaultxxx(self):
        """
        Test that if we import from a csv file that doesn't include a
        column and that column has a default value then that default
        value is executed.
        """
        self.session = db.Session()
        family = self.session.query(Family).filter_by(id=1).one()
        self.assertTrue(family.qualifier == "")

    def test_import_use_default(self):
        """
        Test that if we import from a csv file that doesn't include a
        column and that column has a default value then that default
        value is executed.
        """
        q = self.session.query(Family)
        ids = [r.id for r in q]
        self.assertEqual(ids, [1, 2])
        del q
        self.session.expunge_all()
        self.session = db.Session()
        family = self.session.query(Family).filter_by(id=1).one()
        self.assertTrue(family.qualifier == "")

    def test_import_no_default(self):
        """
        Test that if we import from a csv file that doesn't include a
        column and that column does not have a default value then that
        value is set to None
        """
        species = self.session.query(Species).filter_by(id=1).one()
        self.assertTrue(species.cv_group is None)

    def test_import_empty_is_none(self):
        """
        Test that if we import from a csv file that includes a column
        but that column is empty and doesn't have a default values
        then the column is set to None
        """
        species = self.session.query(Species).filter_by(id=1).one()
        self.assertTrue(species.cv_group is None)

    def test_import_empty_uses_default(self):
        """
        Test that if we import from a csv file that includes a column
        but that column is empty and has a default then the default is
        executed.
        """
        family = self.session.query(Family).filter_by(id=2).one()
        self.assertTrue(family.qualifier == "")

    def test_sequences(self):
        """
        Test that the sequences are set correctly after an import,
        bauble.util.test already has a method to test
        utils.reset_sequence but this test makes sure that it works
        correctly after an import
        """
        # turn off logger
        logging.getLogger("bauble.info").setLevel(logging.ERROR)
        highest_id = len(family_data)
        conn = db.engine.connect()
        conn = db.engine.connect()
        if db.engine.name == "postgresql":
            stmt = "SELECT nextval('family_id_seq')"
            nextval = conn.execute(stmt).fetchone()[0]
        elif db.engine.name in ("sqlite", "mssql"):
            # max(id) isn't really safe in production use but is ok for a test
            stmt = "SELECT max(id) from family;"
            nextval = conn.execute(stmt).fetchone()[0] + 1
        else:
            raise Exception("no test for engine type: %s" % db.engine.name)

        self.assertTrue(nextval > highest_id)

    def test_import_unicode(self):
        """
        Test importing a unicode string.
        """
        genus = self.session.query(Genus).filter_by(id=1).one()
        self.assertTrue(genus.author == genus_data[0]["author"])

    def test_import_no_inherit(self):
        """
        Test importing a row with None doesn't inherit from previous row.
        """
        query = self.session.query(Genus).all()
        self.assertNotEqual(query[1].author, query[0].author)

    def test_export_none_is_empty(self):
        """
        Test exporting a None column exports a ''
        """
        species = Species(genus_id=1, sp="sp")
        self.assertTrue(species is not None)
        temp_path = tempfile.mkdtemp()
        exporter = CSVBackup()
        exporter.start(temp_path)
        f = open(
            os.path.join(temp_path, "species.csv"),
            encoding="utf-8",
            newline="",
        )
        reader = csv.DictReader(f, dialect=csv.excel)
        row = next(reader)
        self.assertTrue(row["cv_group"] == "")


class CSVTests2(ImexTestCase):
    def test_sequences(self):
        """
        Test that the sequences are set correctly after an import,
        bauble.util.test already has a method to test
        utils.reset_sequence but this test makes sure that it works
        correctly after an import

        This test requires the PlantPlugin
        """
        # turn off logger
        logging.getLogger("bauble.info").setLevel(logging.ERROR)
        # import the family data
        filename = os.path.join(
            "bauble", "plugins", "plants", "default", "family.csv"
        )
        importer = CSVRestore()
        importer.start([filename], force=True)
        # the highest id number in the family file is assumed to be
        # num(lines)-1 since the id numbers are sequential and
        # subtract for the file header
        highest_id = len(open(filename).readlines()) - 1
        conn = db.engine.connect()
        if db.engine.name == "postgresql":
            stmt = "SELECT nextval('family_id_seq')"
            nextval = conn.execute(stmt).fetchone()[0]
        elif db.engine.name in ("sqlite", "mssql"):
            # max(id) isn't really safe in production use but is ok for a test
            stmt = "SELECT max(id) from family;"
            nextval = conn.execute(stmt).fetchone()[0] + 1
        else:
            raise Exception("no test for engine type: %s" % db.engine.name)

        self.assertTrue(nextval > highest_id)

    def test_import(self):
        # TODO: create a test to check that we aren't using an insert
        # statement for import that assumes a column value from the previous
        # insert values, could probably create an insert statement from a
        # row in the test data and then create an insert statement from some
        # other dummy data that has different columns from the test data and
        # see if any of the columns from the second insert statement has values
        # from the first statement

        # TODO: this test doesn't really test yet that any of the data was
        # correctly imported or exported, only that export and importing
        # run successfuly

        # 1. write the test data to a temporary file or files
        # 2. import the data and make sure the objects match field for field

        # the exporters and importers show logging information, turn it off
        logging.getLogger("bauble.info").setLevel(logging.ERROR)
        tempdir = tempfile.mkdtemp()

        # export all the testdata
        exporter = CSVBackup()
        exporter.start(tempdir)

        # import all the files in the temp directory
        filenames = os.listdir(tempdir)
        importer = CSVRestore()
        # import twice to check for regression Launchpad #???
        importer.start(
            [os.path.join(tempdir, name) for name in filenames], force=True
        )
        importer.start(
            [os.path.join(tempdir, name) for name in filenames], force=True
        )

    #        utils.log.echo(False)

    def test_unicode(self):
        from bauble.plugins.plants.geography import Geography

        geography_table = Geography.__table__
        # u'Gal\xe1pagos' is the unencoded unicode object,
        # calling u.encode('utf-8') will convert the \xe1 to the a
        # with an accent
        data = {"code": "GAL", "name": "Gal\xe1pagos", "level": 3}
        geography_table.insert().execute(data)
        query = self.session.query(Geography)
        row_name = [r.name for r in query.all() if r.name.startswith("Gal")][0]
        self.assertEqual(row_name, data["name"])

    def test_export(self):
        # 1. export the test data
        # 2. read the exported data into memory and make sure it matches
        # the test export string
        pass


class XMLExporterTests(BaubleTestCase):
    def test_export_one_file_exports_all_tables_empty_db(self):
        bauble.conn_name = "test_xml"
        exporter = XMLExporter()
        exporter.one_file = True
        with tempfile.TemporaryDirectory() as temp_dir:
            exporter.start(path=temp_dir)
            out = Path(temp_dir, "test_xml.xml")
            self.assertTrue(out.exists())
            with out.open("r", encoding="utf8") as file:
                data = file.readline()
                self.assertEqual(
                    data, "<?xml version='1.0' encoding='UTF8'?>\n"
                )
                data = file.readline()
                self.assertGreater(len(data), 100, data)
                for table in db.metadata.tables:
                    self.assertIn(f'<table name="{table}"', data)

    def test_export_one_file_exports_all_tables_non_empty_db(self):
        for func in get_setUp_data_funcs():
            func()
        bauble.conn_name = "test_xml"
        exporter = XMLExporter()
        exporter.one_file = True
        with tempfile.TemporaryDirectory() as temp_dir:
            exporter.start(path=temp_dir)
            out = Path(temp_dir, "test_xml.xml")
            self.assertTrue(out.exists())
            with out.open("r", encoding="utf8") as file:
                data = file.readline()
                self.assertEqual(
                    data, "<?xml version='1.0' encoding='UTF8'?>\n"
                )
                data = file.readline()
                self.assertGreater(len(data), 100, data)
                for table in db.metadata.tables:
                    self.assertIn(f'<table name="{table}"', data)

    def test_export_one_file_per_table(self):
        exporter = XMLExporter()
        exporter.one_file = False
        with tempfile.TemporaryDirectory() as temp_dir:
            exporter.start(path=temp_dir)
            out_dir = Path(temp_dir)
            files = [i.stem for i in out_dir.glob("*.xml")]
            for table in db.metadata.tables:
                self.assertIn(table, files)
            for out in out_dir.glob("*.xml"):
                with out.open("r", encoding="utf8") as file:
                    data = file.readline()
                    self.assertEqual(
                        data, "<?xml version='1.0' encoding='UTF8'?>\n"
                    )
                    data = file.readline()
                    self.assertGreater(len(data), 10, data)

    def test_raises_bad_path(self):
        exporter = XMLExporter()
        self.assertRaises(
            ValueError, exporter.start, path="/some/NoExistent/PATH/name"
        )

    def test_presenter_adds_problem_invalid_paths(self):
        exporter = XMLExporter()
        entry = exporter.presenter.view.widgets.filename_entry
        self.assertFalse(exporter.presenter.has_problems(entry))
        entry.set_text("/some/NoExistent/PATH/name")
        self.assertTrue(exporter.presenter.has_problems(entry))


class BasicImporter(GenericImporter):
    """Dummy GenericImporter, does nothing"""

    def _import_task(self, options):
        pass


class GenericImporterTests(BaubleTestCase):
    def test_add_rec_to_db_plants(self):
        data1 = {
            "accession.species._default_vernacular_name.vernacular_name": {
                "name": "Air Plant"
            },
            "accession.species.genus.family": {"family": "Bromeliaceae"},
            "accession.species.genus": {"genus": "Tillandsia", "author": "L."},
            "accession.source.source_detail": {
                "name": "Tropical Garden Foliage"
            },
            "accession.species": {
                "infrasp1_rank": "f.",
                "infrasp1": "fastigiate",
                "infrasp1_author": "Koide",
                "sp": "ionantha",
                "sp_author": "Planchon",
            },
            "location": {"name": "Epiphites of the Americas", "code": "10.10"},
            "accession": {"code": "XXXX000001"},
            "code": "1",
            "quantity": 1,
        }

        obj = Plant()
        self.session.add(obj)
        out = BasicImporter().add_rec_to_db(self.session, obj, data1)
        self.assertEqual(obj, out)
        # Committing will reveal issues that only show up at commit
        self.session.commit()
        result = self.session.query(Plant).all()
        self.assertEqual(result[0].quantity, data1.get("quantity"))
        self.assertEqual(result[0].code, data1.get("code"))
        self.assertEqual(
            result[0].accession.code, data1.get("accession").get("code")
        )
        self.assertEqual(
            result[0].location.name, data1.get("location").get("name")
        )
        self.assertEqual(
            result[0].accession.species.default_vernacular_name.name,
            data1.get(
                "accession.species._default_vernacular_name.vernacular_name"
            ).get("name"),
        )
        self.assertEqual(
            result[0].accession.species.sp_author,
            data1.get("accession.species").get("sp_author"),
        )
        self.assertEqual(
            result[0].accession.species.infrasp1,
            data1.get("accession.species").get("infrasp1"),
        )
        self.assertEqual(
            result[0].accession.source.source_detail.name,
            data1.get("accession.source.source_detail").get("name"),
        )

        data2 = {
            "accession.species.genus.family": {"epithet": "Taccaceae"},
            "accession.species.genus": {"epithet": "Tacca"},
            "accession.source.source_detail": {
                "name": "MRBG Friends of the Gardens"
            },
            "accession.species": {
                "epithet": "leontopetaloides",
                "default_vernacular_name": "Arrowroot",
            },
            "location": {"name": "Whitsunday Islands", "code": "12.01"},
            "accession": {"code": "1999000003"},
            "code": "1",
            "quantity": 10,
        }
        obj = Plant()
        self.session.add(obj)
        out = BasicImporter().add_rec_to_db(self.session, obj, data2)
        self.assertEqual(obj, out)
        self.session.commit()
        result = self.session.query(Plant).all()
        self.assertEqual(result[1].quantity, data2.get("quantity"))
        self.assertEqual(result[1].code, data2.get("code"))
        self.assertEqual(
            result[1].accession.code, data2.get("accession").get("code")
        )
        self.assertEqual(
            result[1].location.name, data2.get("location").get("name")
        )
        self.assertEqual(
            result[1].accession.species.default_vernacular_name.name,
            data2.get("accession.species").get("default_vernacular_name"),
        )
        self.assertEqual(
            result[1].accession.species.sp,
            data2.get("accession.species").get("epithet"),
        )

        # change the location and quantity of a previous record (data2)
        data3 = {
            "location": {"code": "10.10"},
            "accession": {"code": "1999000003"},
            "code": "1",
            "quantity": 5,
        }
        # the previous record (from the last data set)
        obj = result[1]
        self.session.add(obj)
        out = BasicImporter().add_rec_to_db(self.session, obj, data3)
        self.assertEqual(obj, out)
        self.session.commit()
        result = self.session.query(Plant).all()
        # quantity is has changed
        self.assertEqual(result[1].quantity, data3.get("quantity"))
        # location has changed (same as first data set)
        self.assertEqual(
            result[1].location.name, data1.get("location").get("name")
        )
        # and last data set
        self.assertEqual(
            result[1].location.code, data3.get("location").get("code")
        )
        # the rest is the same as the last data set
        self.assertEqual(result[1].code, data2.get("code"))
        self.assertEqual(
            result[1].accession.code, data2.get("accession").get("code")
        )
        self.assertEqual(
            result[1].accession.species.default_vernacular_name.name,
            data2.get("accession.species").get("default_vernacular_name"),
        )
        self.assertEqual(
            result[1].accession.species.sp,
            data2.get("accession.species").get("epithet"),
        )

        data4 = {
            "accession.species.genus.family": {"epithet": "Moraceae"},
            "accession.species.genus": {"epithet": "Ficus"},
            "accession.source.source_detail": {
                "name": "MRBG Friends of the Gradens"
            },
            "accession.species": {
                "epithet": "virens",
                "infraspecific_parts": "var. virens",
            },
            "location": {"name": "Whitsunday Islands", "code": "12.01"},
            "accession": {"code": "2020.0002"},
            "code": "1",
            "quantity": 1,
        }
        obj = Plant()
        self.session.add(obj)
        out = BasicImporter().add_rec_to_db(self.session, obj, data4)
        self.assertEqual(obj, out)
        # Committing will reveal issues that only show up at commit
        self.session.commit()
        result = self.session.query(Plant).all()
        self.assertEqual(result[2].quantity, data4.get("quantity"))
        self.assertEqual(result[2].code, data4.get("code"))
        self.assertEqual(
            result[2].accession.code, data4.get("accession").get("code")
        )
        self.assertEqual(
            result[2].location.name, data4.get("location").get("name")
        )
        # epithet is a synonym of sp
        self.assertEqual(
            result[2].accession.species.sp,
            data4.get("accession.species").get("epithet"),
        )
        self.assertEqual(
            result[2].accession.species.infraspecific_parts,
            data4.get("accession.species").get("infraspecific_parts"),
        )

    def test_add_rec_to_db_plants_w_change_reason(self):
        data1 = {
            "accession.species.genus.family": {"family": "Bromeliaceae"},
            "accession.species.genus": {"genus": "Tillandsia", "author": "L."},
            "accession.source.source_detail": {
                "name": "Tropical Garden Foliage"
            },
            "accession.species": {
                "infrasp1_rank": "f.",
                "infrasp1": "fastigiate",
                "infrasp1_author": "Koide",
                "sp": "ionantha",
                "sp_author": "Planchon",
            },
            "location": {"name": "Epiphites of the Americas", "code": "10.10"},
            "accession": {"code": "XXXX000001"},
            "planted": {"date": "01/01/2001 12:00:00 pm"},
            "code": "1",
            "quantity": 1,
        }

        obj = Plant()
        self.session.add(obj)
        out = BasicImporter().add_rec_to_db(self.session, obj, data1)
        self.assertEqual(obj, out)
        # Committing will reveal issues that only show up at commit
        self.session.commit()
        # then change its quantity
        data2 = {
            "accession": {"code": "XXXX000001"},
            "changes": {"date": "11/11/2011 12:00:00 pm", "reason": "ERRO"},
            "code": "1",
            "quantity": 11,
        }
        out = BasicImporter().add_rec_to_db(self.session, obj, data2)
        self.assertEqual(obj, out)
        self.session.commit()
        result = self.session.query(Plant).get(1)
        self.assertEqual(len(result.changes), 2)
        self.assertEqual(result.changes[1].quantity, 10)
        self.assertEqual(result.quantity, data2["quantity"])
        self.assertEqual(
            result.changes[1].date.strftime("%d/%m/%Y %I:%M:%S %p").lower(),
            data2["changes"]["date"],
        )
        self.assertEqual(result.changes[1].reason, data2["changes"]["reason"])
        # if nothing actually changes errors and no change is added or changed
        data3 = {
            "accession": {"code": "XXXX000001"},
            "changes": {"date": "12/12/2012 11:00:00 pm", "reason": "DELE"},
            "code": "1",
            "quantity": 11,
        }
        out = BasicImporter().add_rec_to_db(self.session, obj, data3)
        self.assertEqual(obj, out)
        # self.session.commit()
        self.assertRaises(IntegrityError, self.session.commit)
        self.session.rollback()
        session2 = db.Session()
        result = session2.query(Plant).get(1)
        self.assertEqual(len(result.changes), 2)
        self.assertEqual(result.quantity, data2["quantity"])
        self.assertEqual(result.changes[1].quantity, 10)
        self.assertEqual(
            result.changes[1].date.strftime("%d/%m/%Y %I:%M:%S %p").lower(),
            data2["changes"]["date"],
        )
        self.assertEqual(result.changes[1].reason, data2["changes"]["reason"])

    def test_add_rec_to_db_plants_w_planted(self):
        data1 = {
            "accession.species.genus.family": {"family": "Bromeliaceae"},
            "accession.species.genus": {"genus": "Tillandsia", "author": "L."},
            "accession.source.source_detail": {
                "name": "Tropical Garden Foliage"
            },
            "accession.species": {
                "infrasp1_rank": "f.",
                "infrasp1": "fastigiate",
                "infrasp1_author": "Koide",
                "sp": "ionantha",
                "sp_author": "Planchon",
            },
            "location": {"name": "Epiphites of the Americas", "code": "10.10"},
            "accession": {"code": "XXXX000001"},
            "planted": {"date": "01/01/2001 12:00:00 pm"},
            "code": "1",
            "quantity": 1,
        }

        obj = Plant()
        self.session.add(obj)
        out = BasicImporter().add_rec_to_db(self.session, obj, data1)
        self.assertEqual(obj, out)
        # Committing will reveal issues that only show up at commit
        self.session.commit()
        result = self.session.query(Plant).get(1)
        self.assertEqual(result.quantity, data1.get("quantity"))
        self.assertEqual(result.code, data1.get("code"))
        self.assertEqual(
            result.accession.code, data1.get("accession").get("code")
        )
        self.assertEqual(
            result.location.name, data1.get("location").get("name")
        )
        self.assertEqual(
            result.accession.species.sp_author,
            data1.get("accession.species").get("sp_author"),
        )
        self.assertEqual(
            result.accession.species.infrasp1,
            data1.get("accession.species").get("infrasp1"),
        )
        self.assertEqual(
            result.planted.date.strftime("%d/%m/%Y %I:%M:%S %p").lower(),
            data1.get("planted").get("date").lower(),
        )
        # change date on existing planted
        data2 = {
            "accession": {"code": "XXXX000001"},
            "planted": {"date": "02/01/2001 12:00:00 pm"},
            "code": "1",
            "quantity": 1,
        }
        out = BasicImporter().add_rec_to_db(self.session, obj, data2)
        self.assertEqual(obj, out)
        self.session.commit()
        result = self.session.query(Plant).get(1)
        self.assertEqual(
            result.planted.date.strftime("%d/%m/%Y %I:%M:%S %p").lower(),
            data2.get("planted").get("date").lower(),
        )
        self.assertEqual(len(result.changes), 1)

    def test_add_rec_to_db_plants_w_death(self):
        # first add a plant to work with
        data1 = {
            "accession.species.genus.family": {"family": "Bromeliaceae"},
            "accession.species.genus": {"genus": "Tillandsia", "author": "L."},
            "accession.source.source_detail": {
                "name": "Tropical Garden Foliage"
            },
            "accession.species": {
                "infrasp1_rank": "f.",
                "infrasp1": "fastigiate",
                "infrasp1_author": "Koide",
                "sp": "ionantha",
                "sp_author": "Planchon",
            },
            "location": {"name": "Epiphites of the Americas", "code": "10.10"},
            "accession": {"code": "XXXX000001"},
            "planted": {"date": "01/01/2001 12:00:00 pm"},
            "code": "1",
            "quantity": 1,
        }

        obj = Plant()
        self.session.add(obj)
        out = BasicImporter().add_rec_to_db(self.session, obj, data1)
        self.assertEqual(obj, out)
        # Committing will reveal issues that only show up at commit
        self.session.commit()
        result = self.session.query(Plant).get(1)
        # then kill it
        data2 = {
            "accession": {"code": "XXXX000001"},
            "death": {"date": "02/01/2011 12:00:00 pm"},
            "code": "1",
            "quantity": 0,
        }
        out = BasicImporter().add_rec_to_db(self.session, obj, data2)
        self.assertEqual(obj, out)
        self.session.commit()
        result = self.session.query(Plant).get(1)
        self.assertEqual(
            result.death.date.strftime("%d/%m/%Y %I:%M:%S %p").lower(),
            data2.get("death").get("date").lower(),
        )
        self.assertEqual(len(result.changes), 2)
        # change the date of the existing death.
        data3 = {
            "accession": {"code": "XXXX000001"},
            "death": {"date": "02/01/2012 12:00:00 pm"},
            "code": "1",
            "quantity": 0,
        }
        out = BasicImporter().add_rec_to_db(self.session, obj, data3)
        self.assertEqual(obj, out)
        self.session.commit()
        result = self.session.query(Plant).get(1)
        self.assertEqual(
            result.death.date.strftime("%d/%m/%Y %I:%M:%S %p").lower(),
            data3.get("death").get("date").lower(),
        )
        self.assertEqual(len(result.changes), 2)

    def test_add_rec_to_db_plants_w_geojson(self):
        data1 = {
            "accession.species.genus.family": {"family": "Bromeliaceae"},
            "accession.species.genus": {"genus": "Tillandsia", "author": "L."},
            "accession.source.source_detail": {
                "name": "Tropical Garden Foliage"
            },
            "accession.species": {
                "infrasp1_rank": "f.",
                "infrasp1": "fastigiate",
                "infrasp1_author": "Koide",
                "sp": "ionantha",
                "sp_author": "Planchon",
            },
            "location": {"name": "Epiphites of the Americas", "code": "10.10"},
            "accession": {"code": "XXXX000001"},
            "planted": {"date": "01/01/2001 12:00:00 pm"},
            "code": "1",
            "quantity": 1,
            "geojson": ("{'type': 'Point', 'coordinates': [0.0, 0.0]}"),
        }

        obj = Plant()
        self.session.add(obj)
        out = BasicImporter().add_rec_to_db(self.session, obj, data1)
        self.assertEqual(obj, out)
        # Committing will reveal issues that only show up at commit
        self.session.commit()
        result = self.session.query(Plant).get(1)
        self.assertEqual(result.geojson.get("type"), "Point")
        self.assertEqual(len(result.geojson.get("coordinates")), 2)
        self.assertEqual(len(result.changes), 1)

    def test_add_rec_to_db_location(self):
        data1 = {
            "code": "10.10",
            "name": "Whitsunday Islands",
            "description": "Selection of species of horticultural value "
            "commonly found on the Whitsunday Islands.",
        }

        obj = Location()
        self.session.add(obj)
        out = BasicImporter().add_rec_to_db(self.session, obj, data1)
        self.assertEqual(obj, out)
        # Committing will reveal issues that only show up at commit
        self.session.commit()
        result = self.session.query(Location).all()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].code, data1.get("code"))
        self.assertEqual(result[0].name, data1.get("name"))
        self.assertEqual(result[0].description, data1.get("description"))

        # make a change to the entry.
        data2 = {
            "code": "10.10",
            "name": "Whitsunday Islands",
            "description": "Rare, threatend and vulnerable species endemic to "
            "the Whitsunday Islands off the Central Queensland Coast.",
        }
        out = BasicImporter().add_rec_to_db(self.session, obj, data2)
        self.assertEqual(obj, out)
        # Committing will reveal issues that only show up at commit
        self.session.commit()
        result = self.session.query(Location).all()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].code, data1.get("code"))
        self.assertEqual(result[0].name, data1.get("name"))
        self.assertEqual(result[0].description, data2.get("description"))

    def test_get_db_item_id_only(self):
        for func in get_setUp_data_funcs():
            func()
        loc1 = self.session.query(Location).get(1)
        self.assertIsNotNone(loc1)
        # Note float id will fail in postgres if get_value_as_python_type
        # doesn't convert to int correctly
        record = {"loc_id": 1.00}

        importer = BasicImporter()
        importer.domain = Location
        importer.search_by.add("loc_id")
        importer.fields = {"loc_id": "id"}
        item = importer.get_db_item(self.session, record, add=True)
        self.assertTrue(item in self.session)
        self.assertEqual(item, loc1)

    def test_get_db_item_id_only_w_add_creates_new(self):
        record = {"loc_id": 1}

        importer = BasicImporter()
        importer.domain = Location
        importer.search_by.add("loc_id")
        importer.fields = {"loc_id": "id"}
        item = importer.get_db_item(self.session, record, add=True)
        self.assertFalse(item in self.session)

    def test_get_db_item_id_only_wo_add_returns_none(self):
        record = {"loc_id": 1}

        importer = BasicImporter()
        importer.domain = Location
        importer.search_by.add("loc_id")
        importer.fields = {"loc_id": "id"}
        item = importer.get_db_item(self.session, record, add=False)
        self.assertIsNone(item)

    def test_get_db_item_plant_acc_code(self):
        for func in get_setUp_data_funcs():
            func()
        plt1 = self.session.query(Plant).get(2)
        self.assertIsNotNone(plt1)

        record = {
            "accession": str(plt1.accession.code),
            "plt_code": str(plt1.code),
        }

        importer = BasicImporter()
        importer.domain = Plant
        importer.search_by.add("accession")
        importer.search_by.add("plt_code")
        importer.fields = {"accession": "accession.code", "plt_code": "code"}
        item = importer.get_db_item(self.session, record, add=False)
        self.assertTrue(item in self.session)
        self.assertEqual(item, plt1)

    def test_get_db_item_plant_acc_code_new(self):
        record = {"accession": "1234567", "plt_code": "10"}

        importer = BasicImporter()
        importer.domain = Plant
        importer.search_by.add("accession")
        importer.search_by.add("plt_code")
        importer.fields = {"accession": "accession.code", "plt_code": "code"}
        item = importer.get_db_item(self.session, record, add=True)
        self.assertFalse(item in self.session)

    @mock.patch("bauble.utils.create_yes_no_dialog")
    def test_get_db_item_duplicate_yes(self, mock_dialog):
        mock_dialog().run.return_value = -8
        for func in get_setUp_data_funcs():
            func()
        plt1 = self.session.query(Plant).get(2)
        self.assertIsNotNone(plt1)

        record = {
            "accession": str(plt1.accession.code),
            "plt_code": str(plt1.code),
        }

        importer = BasicImporter()
        importer.domain = Plant
        importer.search_by.add("accession")
        importer.search_by.add("plt_code")
        importer.fields = {"accession": "accession.code", "plt_code": "code"}
        item = importer.get_db_item(self.session, record, add=True)
        self.assertTrue(item in self.session)
        # skip
        item = importer.get_db_item(self.session, record, add=True)
        self.assertIsNone(item)
        mock_dialog.assert_called()

    @mock.patch("bauble.utils.create_yes_no_dialog")
    def test_get_db_item_duplicate_skip_cancel(self, mock_dialog):
        mock_dialog().run.return_value = -6
        for func in get_setUp_data_funcs():
            func()
        plt1 = self.session.query(Plant).get(2)
        self.assertIsNotNone(plt1)

        record = {
            "accession": str(plt1.accession.code),
            "plt_code": str(plt1.code),
        }

        importer = BasicImporter()
        importer.domain = Plant
        importer.search_by.add("accession")
        importer.search_by.add("plt_code")
        importer.fields = {"accession": "accession.code", "plt_code": "code"}
        item = importer.get_db_item(self.session, record, add=True)
        self.assertTrue(item in self.session)
        # cancel
        self.assertRaises(
            bauble.error.BaubleError,
            importer.get_db_item,
            self.session,
            record,
            add=True,
        )
        mock_dialog.assert_called()

    @mock.patch("bauble.utils.create_yes_no_dialog")
    def test_get_db_item_duplicate_skip_no(self, mock_dialog):
        mock_dialog().run.return_value = -9
        for func in get_setUp_data_funcs():
            func()
        plt1 = self.session.query(Plant).get(2)
        self.assertIsNotNone(plt1)

        record = {
            "accession": str(plt1.accession.code),
            "plt_code": str(plt1.code),
        }

        importer = BasicImporter()
        importer.domain = Plant
        importer.search_by.add("accession")
        importer.search_by.add("plt_code")
        importer.fields = {"accession": "accession.code", "plt_code": "code"}
        item = importer.get_db_item(self.session, record, add=True)
        self.assertTrue(item in self.session)
        # overwrite
        item = importer.get_db_item(self.session, record, add=True)
        self.assertTrue(item in self.session)
        mock_dialog.assert_called()

    def test_add_rec_to_db_raises_if_rec_cant_be_found_or_created(self):
        # I'm not sure this test is still relevant?
        data1 = {
            "accession.species._default_vernacular_name.vernacular_name": {
                "name": "Air Plant"
            },
            "accession.species.genus.family": {"family": "Bromeliaceae"},
            "accession.species.genus": {"genus": "Tillandsia", "author": "L."},
            "accession.source.source_detail": {
                "name": "Tropical Garden Foliage"
            },
            "accession.species": {
                "infrasp1_rank": "f.",
                "infrasp1": "fastigiate",
                "infrasp1_author": "Koide",
                "sp": "ionantha",
                "sp_author": "Planchon",
            },
            "location": {"name": "loc1"},
            "accession": {"code": "XXXX000001"},
            "code": "1",
            "quantity": 1,
        }

        start_plants = self.session.query(Plant).count()
        obj = Plant()
        self.session.add(obj)

        with mock.patch("bauble.plugins.imex.attrgetter") as mock_attrgetter:
            with mock.patch.object(
                BasicImporter, "memoized_get_create_or_update"
            ) as mock_get:
                mock_get.return_value = None
                # first look for an existing should fail
                mock_attrgetter().return_value = None
                self.assertRaises(
                    bauble.error.DatabaseError,
                    BasicImporter().add_rec_to_db,
                    self.session,
                    obj,
                    data1,
                )
        # Committing will reveal issues that only show up at commit
        self.assertRaises(Exception, self.session.commit)
        self.session.rollback()
        end_plants = self.session.query(Plant).count()
        self.assertEqual(start_plants, end_plants)

    def test_add_rec_to_db_one_to_one_no_value_doesnt_add(self):
        data1 = {
            "accession.species._default_vernacular_name.vernacular_name": {
                "name": "Air Plant"
            },
            "accession.species.genus.family": {"family": "Bromeliaceae"},
            "accession.species.genus": {"genus": "Tillandsia", "author": "L."},
            "accession.source.source_detail": {"name": ""},
            "accession.species": {
                "infrasp1_rank": "f.",
                "infrasp1": "fastigiate",
                "infrasp1_author": "Koide",
                "sp": "ionantha",
                "sp_author": "Planchon",
            },
            "location": {"code": "loc1"},
            "accession": {"code": "XXXX000001"},
            "code": "1",
            "quantity": 1,
        }

        start_plants = self.session.query(Plant).count()
        obj = Plant()
        self.session.add(obj)
        BasicImporter().add_rec_to_db(self.session, obj, data1)
        # Committing will reveal issues that only show up at commit
        self.session.commit()
        end_plants = self.session.query(Plant).count()
        self.assertEqual(start_plants + 1, end_plants)
        self.assertIsNone(obj.accession.source)


class GenericExporterTests(BaubleTestCase):
    def setUp(self):
        super().setUp()
        plants_test.setUp_data()
        garden_test.setUp_data()
        dayfirst = prefs.prefs[prefs.parse_dayfirst_pref]
        yearfirst = prefs.prefs[prefs.parse_yearfirst_pref]
        from functools import partial

        self.date_parse = partial(
            date_parse, dayfirst=dayfirst, yearfirst=yearfirst
        )

    def test_get_item_value_gets_datetime_datetime_type(self):
        item = Plant(code="3", accession_id=1, location_id=1, quantity=10)
        self.session.add(item)
        self.session.commit()
        now = datetime.now().timestamp()
        val = GenericExporter.get_item_value("planted.date", item)
        # accuracy is seconds
        val = self.date_parse(val).timestamp()
        self.assertAlmostEqual(val, now, delta=2)

    def test_get_item_value_gets_date_type(self):
        item = Accession(code="2020.4", species_id=1, date_accd=datetime.now())
        self.session.add(item)
        self.session.commit()
        now = (
            datetime.now()
            .replace(hour=0, minute=0, second=0, microsecond=0)
            .timestamp()
        )
        val = GenericExporter.get_item_value("date_accd", item)
        # accuracy is a day - i.e. very rarely this could spill over from one
        # day to the next
        val = self.date_parse(val).timestamp()
        secs_in_day = 86400
        self.assertAlmostEqual(val, now, delta=secs_in_day)

    def test_get_item_value_gets_datetime_type(self):
        item = Plant(code="3", accession_id=1, location_id=1, quantity=10)
        self.session.add(item)
        self.session.commit()
        now = datetime.now().timestamp()
        val = GenericExporter.get_item_value("_created", item)
        # accuracy is seconds
        val = self.date_parse(val).timestamp()
        self.assertAlmostEqual(val, now, delta=2)

    def test_get_item_value_gets_path(self):
        item = self.session.query(Plant).get(1)
        val = GenericExporter.get_item_value(
            "accession.species.genus.family.epithet", item
        )
        self.assertEqual(val, "Orchidaceae")

    def test_get_item_value_gets_boolean(self):
        item = self.session.query(Accession).get(1)
        val = GenericExporter.get_item_value("private", item)
        self.assertEqual(val, "True")

    def test_get_item_record_w_notes(self):
        item = self.session.query(Species).get(1)
        val = GenericExporter.get_item_record(
            item, {"sp": "species", "gen": "genus.epithet"}
        )
        self.assertEqual(
            val, {"sp": "Maxillaria s. str variabilis", "gen": "Maxillaria"}
        )

    def test_get_item_record_wo_notes(self):
        from bauble.plugins.plants.geography import Geography
        from bauble.plugins.plants.test_plants import setup_geographies

        setup_geographies()

        item = (
            self.session.query(Geography).filter(Geography.code == "50").one()
        )
        val = GenericExporter.get_item_record(item, {"name": "name"})
        self.assertEqual(val, {"name": "Australia"})

    def test_get_item_record_wo_notes_text_field_does_not_error(self):
        item = self.session.query(Collection).get(1)
        val = GenericExporter.get_item_record(
            item, {"locale": "locale", "collector": "collector"}
        )
        self.assertEqual(val, {"locale": "Somewhere", "collector": "Someone"})


class GlobalFunctionsTests(BaubleTestCase):
    def test_is_importable_attr(self):
        self.assertTrue(is_importable_attr(Species, "epithet"))
        self.assertTrue(is_importable_attr(Species, "sp"))
        self.assertTrue(is_importable_attr(Species, "epithet"))
        self.assertTrue(
            is_importable_attr(Plant, "accession.species.genus.cites")
        )

        self.assertFalse(is_importable_attr(Plant, "accession.qualified_name"))
        self.assertFalse(is_importable_attr(Accession, "active"))
        self.assertFalse(
            is_importable_attr(
                Plant, "accession.species.infraspecific_epithet"
            )
        )
