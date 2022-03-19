# Copyright 2004-2010 Brett Adams
# Copyright 2015 Mario Frasca <mario@anche.no>.
# Copyright 2021-2022 Ross Demuth <rossdemuth123@gmail.com>
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
logger = logging.getLogger(__name__)

import os
import shutil
import tempfile
import json
from datetime import datetime

from sqlalchemy import Column, Integer

from bauble.btypes import Boolean

from bauble import db
from bauble import prefs
from bauble.plugins.plants import (Familia,
                                   Family,
                                   Genus,
                                   Species,
                                   VernacularName,
                                   SpeciesNote)
from bauble.plugins.garden import Accession, Location, Plant, SourceDetail, Source
import bauble.plugins.garden.test_garden as garden_test
import bauble.plugins.plants.test_plants as plants_test
from bauble.test import BaubleTestCase
from bauble.editor import MockView
from bauble.utils import get_user_display_name
from .csv_ import (CSVRestore,
                   CSVBackup,
                   QUOTE_CHAR,
                   QUOTE_STYLE)
from .iojson import JSONImporter, JSONExporter
from . import GenericExporter, GenericImporter


family_data = [{'id': 1, 'family': 'Orchidaceae', 'qualifier': None},
               {'id': 2, 'family': 'Myrtaceae'}]
genus_data = [
    {'id': 1, 'genus': 'Calopogon', 'family_id': 1, 'author': 'R. Br.'},
    {'id': 2, 'genus': 'Panisea', 'family_id': 1}, ]
species_data = [
    {'id': 1, 'sp': 'tuberosus', 'genus_id': 1, 'sp_author': None},
    {'id': 2, 'sp': 'albiflora', 'genus_id': 2,
     'sp_author': '(Ridl.) Seidenf.'},
    {'id': 3, 'sp': 'distelidia', 'genus_id': 2, 'sp_author': 'I.D.Lund'},
    {'id': 4, 'sp': 'zeylanica', 'genus_id': 2, 'sp_author': '(Hook.f.) Aver.'}
]
species_note_test_data = [
    {'id': 1, 'species_id': 18, 'category': 'CITES', 'note': 'I'},
    {'id': 2, 'species_id': 20, 'category': 'IUCN', 'note': 'LC'},
    {'id': 3, 'species_id': 18, 'category': '<price>', 'note': '19.50'}, ]
accession_data = [
    {'id': 1, 'species_id': 1, 'code': '2015.0001'},
    {'id': 2, 'species_id': 1, 'code': '2015.0002'},
    {'id': 3, 'species_id': 1, 'code': '2015.0003', 'private': True}, ]
location_data = [
    {'id': 1, 'code': '1'}, ]
plant_data = [
    {'id': 1, 'accession_id': 1, 'location_id': 1, 'code': '1',
     'quantity': 1},
    {'id': 2, 'accession_id': 3, 'location_id': 1, 'code': '1',
     'quantity': 1}, ]


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
        self.assertTrue(
            prefs.prefs.get('shapefile.location.fields')
        )
        self.assertTrue(
            prefs.prefs.get('shapefile.plant.search_by')
        )


class CSVTests(ImexTestCase):

    def setUp(self):
        self.path = tempfile.mkdtemp()
        super().setUp()

        data = (('family', family_data), ('genus', genus_data),
                ('species', species_data))
        for table_name, data in data:
            filename = os.path.join(self.path, '%s.csv' % table_name)
            f = open(filename, 'w', encoding='utf-8', newline='')
            format = {'delimiter': ',', 'quoting': QUOTE_STYLE,
                      'quotechar': QUOTE_CHAR}

            fields = list(data[0].keys())
            f.write('%s\n' % ','.join(fields))
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
        geo_data = [{'id': 3, 'name': '3', 'parent_id': 1},
                    {'id': 1, 'name': '1', 'parent_id': None},
                    {'id': 2, 'name': '2', 'parent_id': 1},
                    ]
        filename = os.path.join(self.path, 'geography.csv')
        f = open(filename, 'w', encoding='utf-8', newline='')
        format = {'delimiter': ',', 'quoting': QUOTE_STYLE,
                  'quotechar': QUOTE_CHAR}
        fields = list(geo_data[0].keys())
        f.write('%s\n' % ','.join(fields))
        f.flush()
        writer = csv.DictWriter(f, fields, **format)
        writer.writerows(geo_data)
        f.flush()
        f.close()
        importer = CSVTestImporter()
        importer.start([filename], force=True)

    def test_import_bool_column(self):
        class BoolTest(db.Base):
            __tablename__ = 'bool_test'
            id = Column(Integer, primary_key=True)
            col1 = Column(Boolean, default=False)
        table = BoolTest.__table__
        table.create(bind=db.engine)
        data = [{'id': 1, 'col1': 'True'},
                {'id': 2, 'col1': 'False'},
                {'id': 3, 'col1': ''},
                ]
        filename = os.path.join(self.path, 'bool_test.csv')
        f = open(filename, 'w', encoding='utf-8', newline='')
        format = {'delimiter': ',', 'quoting': QUOTE_STYLE,
                  'quotechar': QUOTE_CHAR}
        fields = list(data[0].keys())
        f.write('%s\n' % ','.join(fields))
        f.flush()
        writer = csv.DictWriter(f, fields, **format)
        writer.writerows(data)
        f.flush()
        f.close()
        importer = CSVTestImporter()
        importer.start([filename], force=True)

        t = self.session.query(BoolTest).get(1)
        self.assertTrue(t.col1 is True)

        t = self.session.query(BoolTest).get(2)
        self.assertTrue(t.col1 is False)

        t = self.session.query(BoolTest).get(3)
        self.assertTrue(t.col1 is False)
        table.drop(bind=db.engine)

    def test_with_open_connection(self):
        """
        Test that the import doesn't stall if we have a connection
        open to Family while importing to the family table
        """
        list(self.session.query(Family))
        filename = os.path.join(self.path, 'family.csv')
        f = open(filename, 'w', encoding='utf-8', newline='')
        format = {'delimiter': ',', 'quoting': QUOTE_STYLE,
                  'quotechar': QUOTE_CHAR}
        fields = list(family_data[0].keys())
        f.write('%s\n' % ','.join(fields))
        writer = csv.DictWriter(f, fields, **format)
        writer.writerows(family_data)
        f.flush()
        f.close()
        importer = CSVTestImporter()
        importer.start([filename], force=True)
        list(self.session.query(Family))

    def test_import_use_defaultxxx(self):
        """
        Test that if we import from a csv file that doesn't include a
        column and that column has a default value then that default
        value is executed.
        """
        self.session = db.Session()
        family = self.session.query(Family).filter_by(id=1).one()
        self.assertTrue(family.qualifier == '')

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
        self.assertTrue(family.qualifier == '')

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
        self.assertTrue(family.qualifier == '')

    def test_sequences(self):
        """
        Test that the sequences are set correctly after an import,
        bauble.util.test already has a method to test
        utils.reset_sequence but this test makes sure that it works
        correctly after an import
        """
        # turn off logger
        logging.getLogger('bauble.info').setLevel(logging.ERROR)
        highest_id = len(family_data)
        conn = db.engine.connect()
        if db.engine.name == 'postgresql':
            stmt = "SELECT currval('family_id_seq');"
            nextval = conn.execute(stmt).fetchone()[0]
        elif db.engine.name == 'sqlite':
            # max(id) isn't really safe in production use but is ok for a test
            stmt = "SELECT max(id) from family;"
            nextval = conn.execute(stmt).fetchone()[0] + 1
        else:
            raise Exception("no test for engine type: %s" % db.engine.name)

        #debug(list(conn.execute("SELECT * FROM family").fetchall()))
        maxid = conn.execute("SELECT max(id) FROM family").fetchone()[0]
        assert nextval > highest_id, \
            "bad sequence: highest_id(%s) > nexval(%s) -- %s" % \
            (highest_id, nextval, maxid)

    def test_import_unicode(self):
        """
        Test importing a unicode string.
        """
        genus = self.session.query(Genus).filter_by(id=1).one()
        self.assertTrue(genus.author == genus_data[0]['author'])

    def test_import_no_inherit(self):
        """
        Test importing a row with None doesn't inherit from previous row.
        """
        query = self.session.query(Genus)
        self.assertTrue(query[1].author != query[0].author,
                     (query[1].author, query[0].author))

    def test_export_none_is_empty(self):
        """
        Test exporting a None column exports a ''
        """
        species = Species(genus_id=1, sp='sp')
        self.assertTrue(species is not None)
        from tempfile import mkdtemp
        temp_path = mkdtemp()
        exporter = CSVBackup()
        exporter.start(temp_path)
        f = open(os.path.join(temp_path, 'species.csv'), encoding='utf-8',
                 newline='')
        reader = csv.DictReader(f, dialect=csv.excel)
        row = next(reader)
        self.assertTrue(row['cv_group'] == '')


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
        logging.getLogger('bauble.info').setLevel(logging.ERROR)
        # import the family data
        filename = os.path.join('bauble', 'plugins', 'plants', 'default',
                                'family.csv')
        importer = CSVRestore()
        importer.start([filename], force=True)
        # the highest id number in the family file is assumed to be
        # num(lines)-1 since the id numbers are sequential and
        # subtract for the file header
        highest_id = len(open(filename).readlines())-1
        currval = None
        conn = db.engine.connect()
        if db.engine.name == 'postgres':
            stmt = "SELECT currval('family_id_seq');"
            currval = conn.execute(stmt).fetchone()[0]
            self.assertEqual(currval, 0)
        elif db.engine.name == 'sqlite':
            # max(id) isn't really safe in production use but is ok for a test
            stmt = "SELECT max(id) from family;"
            nextval = conn.execute(stmt).fetchone()[0] + 1
        else:
            raise "no test for engine type: %s" % db.engine.name

        #debug(list(conn.execute("SELECT * FROM family").fetchall()))
        maxid = conn.execute("SELECT max(id) FROM family").fetchone()[0]
        assert nextval > highest_id, \
            "bad sequence: highest_id(%s) > nexval(%s) -- %s" % \
            (highest_id, nextval, maxid)

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
        logging.getLogger('bauble.info').setLevel(logging.ERROR)
        import tempfile
        tempdir = tempfile.mkdtemp()

        # export all the testdata
        exporter = CSVBackup()
        exporter.start(tempdir)

        # import all the files in the temp directory
        filenames = os.listdir(tempdir)
        importer = CSVRestore()
        # import twice to check for regression Launchpad #???
        importer.start([os.path.join(tempdir, name) for name in filenames],
                       force=True)
        importer.start([os.path.join(tempdir, name) for name in filenames],
                       force=True)
#        utils.log.echo(False)

    def test_unicode(self):
        from bauble.plugins.plants.geography import Geography
        geography_table = Geography.__table__
        # u'Gal\xe1pagos' is the unencoded unicode object,
        # calling u.encode('utf-8') will convert the \xe1 to the a
        # with an accent
        data = {'name': 'Gal\xe1pagos'}
        geography_table.insert().execute(data)
        query = self.session.query(Geography)
        row_name = [r.name for r in query.all()
                    if r.name.startswith("Gal")][0]
        self.assertEqual(row_name, data['name'])

    def test_export(self):
        # 1. export the test data
        # 2. read the exported data into memory and make sure it matches
        # the test export string
        pass


class MockExportView:
    def widget_set_value(self, *args):
        pass

    def widget_get_value(self, *args):
        pass

    def connect_signals(self, *args):
        pass

    def connect(self, *args):
        pass

    def set_selection(self, a):
        self.__selection = a

    def get_selection(self):
        return self.__selection


class JSONExportTests(BaubleTestCase):

    def setUp(self):
        super().setUp()
        from tempfile import mkstemp
        handle, self.temp_path = mkstemp()
        os.close(handle)

        data = ((Family, family_data),
                (Genus, genus_data),
                (Species, species_data),
                (Accession, accession_data),
                (Location, location_data),
                (Plant, plant_data))

        self.objects = []
        for klass, dics in data:
            for dic in dics:
                obj = klass(**dic)
                self.session.add(obj)
                self.objects.append(obj)

        self.session.commit()

    def tearDown(self):
        super().tearDown()
        os.remove(self.temp_path)

    def test_writes_complete_database(self):
        "exporting without specifying what: export complete database"

        exporter = JSONExporter(MockView())
        exporter.view.selection = None
        exporter.selection_based_on == 'sbo_selection'
        exporter.include_private = False
        exporter.filename = self.temp_path
        exporter.run()
        ## must still check content of generated file!
        with open(self.temp_path) as f:
            result = json.load(f)
        self.assertEqual(len(result), 14)
        families = [i for i in result
                    if i['object'] == 'taxon' and i['rank'] == 'familia']
        self.assertEqual(len(families), 2)
        genera = [i for i in result
                  if i['object'] == 'taxon' and i['rank'] == 'genus']
        self.assertEqual(len(genera), 2)
        species = [i for i in result
                   if i['object'] == 'taxon' and i['rank'] == 'species']
        self.assertEqual(len(species), 4)
        target = [
            {"epithet": "Orchidaceae", "object": "taxon", "rank": "familia"},
            {"epithet": "Myrtaceae", "object": "taxon", "rank": "familia"},
            {"author": "R. Br.", "epithet": "Calopogon",
             "ht-epithet": "Orchidaceae", "ht-rank": "familia",
             "object": "taxon", "rank": "genus"},
            {"author": "", "epithet": "Panisea", "ht-epithet": "Orchidaceae",
             "ht-rank": "familia", "object": "taxon", "rank": "genus"},
            {'ht-epithet': 'Calopogon', 'hybrid': False, 'object': 'taxon',
             'ht-rank': 'genus', 'rank': 'species', 'epithet': 'tuberosus'},
            {'ht-epithet': 'Panisea', 'hybrid': False, 'object': 'taxon',
             'ht-rank': 'genus', 'rank': 'species', 'epithet': 'albiflora',
             'sp_author': '(Ridl.) Seidenf.'},
            {'ht-epithet': 'Panisea', 'hybrid': False, 'object': 'taxon',
             'ht-rank': 'genus', 'rank': 'species', 'epithet': 'distelidia',
             'sp_author': 'I.D.Lund'},
            {'ht-epithet': 'Panisea', 'hybrid': False, 'object': 'taxon',
             'ht-rank': 'genus', 'rank': 'species', 'epithet': 'zeylanica',
             'sp_author': '(Hook.f.) Aver.'},
            {"code": "2015.0001", "object": "accession", "private": False,
             "species": "Calopogon tuberosus"},
            {"code": "2015.0002", "object": "accession", "private": False,
             "species": "Calopogon tuberosus"},
            {"code": "2015.0003", "object": "accession", "private": True,
             "species": "Calopogon tuberosus"},
            {"code": "1", "object": "location"},
            {"accession": "2015.0001", "code": "1", "location": "1",
             "memorial": False, "object": "plant", "quantity": 1},
            {"accession": "2015.0003", "code": "1", "location": "1",
             "memorial": False, "object": "plant", "quantity": 1}]
        for o1 in result:
            self.assertTrue(o1 in target, o1)
        for o2 in target:
            self.assertTrue(o1 in result, o2)

    def test_when_selection_huge_ask(self):
        view = MockView()
        exporter = JSONExporter(view)
        exporter.selection_based_on == 'sbo_selection'
        view.selection = list(range(5000))
        view.reply_yes_no_dialog = [False]
        exporter.run()
        self.assertTrue('run_yes_no_dialog' in view.invoked)
        self.assertEqual(view.reply_yes_no_dialog, [])

    def test_writes_full_taxonomic_info(self):
        "exporting one family: export full taxonomic information below family"

        selection = self.session.query(Family).filter(
            Family.family == 'Orchidaceae').all()
        exporter = JSONExporter(MockView())
        exporter.selection_based_on == 'sbo_selection'
        exporter.include_private = False
        exporter.view.selection = selection
        exporter.filename = self.temp_path
        exporter.run()
        with open(self.temp_path) as f:
            result = json.load(f)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['rank'], 'familia')
        self.assertEqual(result[0]['epithet'], 'Orchidaceae')

    def test_writes_partial_taxonomic_info(self):
        "exporting one genus: all species below genus"

        selection = self.session.query(Genus).filter(
            Genus.genus == 'Calopogon').all()
        exporter = JSONExporter(MockView())
        exporter.view.selection = selection
        exporter.selection_based_on == 'sbo_selection'
        exporter.include_private = False
        exporter.filename = self.temp_path
        exporter.run()
        with open(self.temp_path) as f:
            result = json.load(f)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['rank'], 'genus')
        self.assertEqual(result[0]['epithet'], 'Calopogon')
        self.assertEqual(result[0]['ht-rank'], 'familia')
        self.assertEqual(result[0]['ht-epithet'], 'Orchidaceae')
        self.assertEqual(result[0]['author'], 'R. Br.')

    def test_writes_partial_taxonomic_info_species(self):
        "exporting one species: all species below species"

        selection = self.session.query(
            Species).filter(Species.sp == 'tuberosus').join(
            Genus).filter(Genus.genus == "Calopogon").all()
        exporter = JSONExporter(MockView())
        exporter.view.selection = selection
        exporter.selection_based_on == 'sbo_selection'
        exporter.include_private = False
        exporter.filename = self.temp_path
        exporter.run()
        with open(self.temp_path) as f:
            result = json.load(f)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['rank'], 'species')
        self.assertEqual(result[0]['epithet'], 'tuberosus')
        self.assertEqual(result[0]['ht-rank'], 'genus')
        self.assertEqual(result[0]['ht-epithet'], 'Calopogon')
        self.assertEqual(result[0]['hybrid'], False)

    def test_export_single_species_with_notes(self):
        selection = self.session.query(
            Species).filter(Species.sp == 'tuberosus').join(
            Genus).filter(Genus.genus == "Calopogon").all()
        note = SpeciesNote(category='<coords>', note='{1: 1, 2: 2}')
        note.species = selection[0]
        self.session.add(note)
        self.session.commit()
        exporter = JSONExporter(MockView())
        exporter.view.selection = selection
        exporter.selection_based_on == 'sbo_selection'
        exporter.include_private = False
        exporter.filename = self.temp_path
        exporter.run()
        with open(self.temp_path) as f:
            result = json.load(f)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0],
                         {'ht-epithet': 'Calopogon', 'hybrid': False,
                          'object': 'taxon', 'ht-rank': 'genus',
                          'rank': 'species', 'epithet': 'tuberosus'})
        date_dict = result[1]['date']
        del result[1]['date']
        self.assertEqual(result[1], {
            'category': '<coords>', 'note': '{1: 1, 2: 2}',
            'species': 'Calopogon tuberosus',
            'object': 'species_note', 'user':
            get_user_display_name()})
        self.assertEqual(set(date_dict.keys()), set(['millis', '__class__']))

    def test_export_single_species_with_vernacular_name(self):
        selection = self.session.query(
            Species).filter(Species.sp == 'tuberosus').join(
            Genus).filter(Genus.genus == "Calopogon").all()
        vn = VernacularName(language="it", name='orchidea')
        selection[0].vernacular_names.append(vn)
        self.session.add(vn)
        self.session.commit()
        exporter = JSONExporter(MockView())
        exporter.view.selection = selection
        exporter.selection_based_on == 'sbo_selection'
        exporter.include_private = False
        exporter.filename = self.temp_path
        exporter.run()
        with open(self.temp_path) as f:
            result = json.load(f)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0],
                         {'ht-epithet': 'Calopogon', 'hybrid': False,
                          'object': 'taxon', 'ht-rank': 'genus',
                          'rank': 'species', 'epithet': 'tuberosus'})
        self.assertEqual(result[1],
                         {'language': 'it', 'name': 'orchidea',
                          'object': 'vernacular_name',
                          'species': 'Calopogon tuberosus'})

    def test_partial_taxonomic_with_synonymy(self):
        "exporting one genus which is not an accepted name."

        f = self.session.query(
            Family).filter(
            Family.family == 'Orchidaceae').one()
        bu = Genus(family=f, genus='Bulbophyllum')  # accepted
        zy = Genus(family=f, genus='Zygoglossum')  # synonym
        bu.synonyms.append(zy)
        self.session.add_all([f, bu, zy])
        self.session.commit()

        selection = self.session.query(Genus).filter(
            Genus.genus == 'Zygoglossum').all()
        exporter = JSONExporter(MockView())
        exporter.view.selection = selection
        exporter.selection_based_on == 'sbo_selection'
        exporter.include_private = True
        exporter.filename = self.temp_path
        exporter.run()
        with open(self.temp_path) as f:
            result = json.load(f)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['rank'], 'genus')
        self.assertEqual(result[0]['epithet'], 'Zygoglossum')
        self.assertEqual(result[0]['ht-rank'], 'familia')
        self.assertEqual(result[0]['ht-epithet'], 'Orchidaceae')
        accepted = result[0].get('accepted')
        self.assertTrue(isinstance(accepted, dict))
        self.assertEqual(accepted['rank'], 'genus')
        self.assertEqual(accepted['epithet'], 'Bulbophyllum')
        self.assertEqual(accepted['ht-rank'], 'familia')
        self.assertEqual(accepted['ht-epithet'], 'Orchidaceae')

    def test_export_ignores_private_if_sbo_selection(self):
        exporter = JSONExporter(MockView())
        selection = [o for o in self.objects if isinstance(o, Accession)]
        non_private = [a for a in selection if a.private is False]
        self.assertEqual(len(selection), 3)
        self.assertEqual(len(non_private), 2)
        exporter.view.selection = selection
        exporter.selection_based_on == 'sbo_selection'
        exporter.include_private = False
        exporter.filename = self.temp_path
        exporter.run()
        with open(self.temp_path) as f:
            result = json.load(f)
        self.assertEqual(len(result), 3)

    def test_export_non_private_if_sbo_accessions(self):
        exporter = JSONExporter(MockView())
        exporter.view.selection = None
        exporter.selection_based_on = 'sbo_accessions'
        exporter.include_private = False
        exporter.filename = self.temp_path
        exporter.run()
        with open(self.temp_path) as f:
            result = json.load(f)
        self.assertEqual(len(result), 5)

    def test_export_private_if_sbo_accessions(self):
        exporter = JSONExporter(MockView())
        exporter.view.selection = None
        exporter.selection_based_on = 'sbo_accessions'
        exporter.include_private = True
        exporter.filename = self.temp_path
        exporter.run()
        with open(self.temp_path) as f:
            result = json.load(f)
        self.assertEqual(len(result), 6)

    def test_export_non_private_if_sbo_plants(self):
        exporter = JSONExporter(MockView())
        exporter.view.selection = None
        exporter.selection_based_on = 'sbo_plants'
        exporter.include_private = False
        exporter.filename = self.temp_path
        exporter.run()
        with open(self.temp_path) as f:
            result = json.load(f)
        self.assertEqual(len(result), 6)

    def test_export_private_if_sbo_plants(self):
        exporter = JSONExporter(MockView())
        exporter.view.selection = None
        exporter.selection_based_on = 'sbo_plants'
        exporter.include_private = True
        exporter.filename = self.temp_path
        exporter.run()
        with open(self.temp_path) as f:
            result = json.load(f)
        self.assertEqual(len(result), 8)

    def test_export_with_vernacular(self):
        "exporting one genus which is not an accepted name."

        ## precondition
        sola = Family(family='Solanaceae')
        brug = Genus(family=sola, genus='Brugmansia')
        arbo = Species(genus=brug, sp='arborea')
        vern = VernacularName(species=arbo,
                              language="es", name="Floripondio")
        self.session.add_all([sola, brug, arbo, vern])
        self.session.commit()

        ## action
        exporter = JSONExporter(MockView())
        exporter.view.selection = None
        exporter.selection_based_on = 'sbo_taxa'
        exporter.include_private = False
        exporter.filename = self.temp_path
        exporter.run()

        ## check
        with open(self.temp_path) as f:
            result = json.load(f)
        vern_from_json = [i for i in result
                          if i['object'] == 'vernacular_name']
        self.assertEqual(len(vern_from_json), 1)
        self.assertEqual(vern_from_json[0]['language'], 'es')

    def test_on_btnbrowse_clicked(self):
        view = MockView()
        exporter = JSONExporter(view)
        view.reply_file_chooser_dialog = ['/tmp/test.json']
        exporter.on_btnbrowse_clicked('button')
        exporter.on_text_entry_changed('output_filename')
        self.assertEqual(exporter.filename, '/tmp/test.json')
        self.assertEqual(JSONExporter.last_folder, '/tmp')

    def test_includes_sources(self):

        ## precondition
        # Create an Accession a, then create a Source s, then assign
        # a.source = s
        a = self.session.query(Accession).first()
        a.source = s = Source()
        s.source_detail = c = SourceDetail(name='Summit')
        self.session.add_all([s, c])
        self.session.commit()

        ## action
        exporter = JSONExporter(MockView())
        exporter.view.selection = None
        exporter.selection_based_on = 'sbo_accessions'
        exporter.include_private = True
        exporter.filename = self.temp_path
        exporter.run()

        ## check
        with open(self.temp_path) as f:
            result = json.load(f)
        contacts_from_json = [i for i in result
                              if i['object'] == 'source_detail']
        self.assertEqual(len(contacts_from_json), 1)
        self.assertEqual(contacts_from_json[0]['name'], 'Summit')
        accessions_from_json = [i for i in result
                                if i['object'] == 'accession']
        self.assertEqual(len(accessions_from_json), 3)
        accessions_with_contact = [i for i in result if
                                   i['object'] == 'accession' and
                                   i.get('contact') is not None]
        self.assertEqual(len(accessions_with_contact), 1)
        self.assertEqual(accessions_with_contact[0]['contact'], 'Summit')


class JSONImportTests(BaubleTestCase):

    def setUp(self):
        super().setUp()
        from tempfile import mkstemp
        handle, self.temp_path = mkstemp()
        os.close(handle)

        data = ((Familia, family_data),
                (Genus, genus_data),
                (Species, species_data))

        for klass, dics in data:
            for dic in dics:
                obj = klass(**dic)
                self.session.add(obj)
        self.session.commit()

    def tearDown(self):
        super().tearDown()
        os.remove(self.temp_path)

    def test_import_new_inserts(self):
        "importing new taxon adds it to database."
        json_string = '[{"rank": "Genus", "epithet": "Neogyna", '\
            '"ht-rank": "Familia", "ht-epithet": "Orchidaceae", '\
            '"author": "Rchb. f."}]'
        with open(self.temp_path, "w") as f:
            f.write(json_string)
        self.assertEqual(len(self.session.query(Genus).filter(
            Genus.genus == "Neogyna").all()), 0)
        importer = JSONImporter(MockView())
        importer.filename = self.temp_path
        importer.on_btnok_clicked(None)
        self.assertEqual(len(self.session.query(Genus).filter(
            Genus.genus == "Neogyna").all()), 1)

    def test_import_new_inserts_lowercase(self):
        "importing new taxon adds it to database, rank name can be\
        all lower case."
        json_string = '[{"rank": "genus", "epithet": "Neogyna", "ht-rank"'\
            ': "familia", "ht-epithet": "Orchidaceae", "author": "Rchb. f."}]'
        with open(self.temp_path, "w") as f:
            f.write(json_string)
        self.assertEqual(len(self.session.query(Genus).filter(
            Genus.genus == "Neogyna").all()), 0)
        importer = JSONImporter(MockView())
        importer.filename = self.temp_path
        importer.on_btnok_clicked(None)
        self.assertEqual(len(self.session.query(Genus).filter(
            Genus.genus == "Neogyna").all()), 1)

    def test_import_new_with_non_timestamped_note(self):
        json_string = (
            '[{"ht-epithet": "Calopogon", "epithet": "pallidus", "author": '
            '"Chapm.", "rank": "Species", "ht-rank": "Genus", "hybrid": '
            'false},  {"object": "species_note", "species": "Calopogon '
            'pallidus", "category": "<coords>", "note": "{lat: 8.5, lon: -80}"'
            '}]'
        )
        with open(self.temp_path, "w") as f:
            f.write(json_string)
        importer = JSONImporter(MockView())
        importer.filename = self.temp_path
        importer.on_btnok_clicked(None)
        self.session.commit()
        afterwards = Species.retrieve_or_create(
            self.session, {'ht-epithet': "Calopogon",
                           'epithet': "pallidus"})
        self.assertEqual(afterwards.sp_author, 'Chapm.')
        self.assertEqual(len(afterwards.notes), 1)

    def test_import_new_with_three_array_notes(self):
        json_string = (
            '[{"ht-epithet": "Calopogon", "epithet": "pallidus", "author": '
            '"Chapm.", "rank": "Species", "ht-rank": "Genus", "hybrid": '
            'false}, {"object": "species_note", "species": "Calopogon '
            'pallidus", "category": "[x]", "note": "1"}, {"object": '
            '"species_note", "species": "Calopogon pallidus", "category": '
            '"[x]", "note": "1"}, {"object": "species_note", "species": '
            '"Calopogon pallidus", "category": "[x]", "note": "1"}]'
        )
        with open(self.temp_path, "w") as f:
            f.write(json_string)
        importer = JSONImporter(MockView())
        importer.filename = self.temp_path
        importer.on_btnok_clicked(None)
        self.session.commit()
        afterwards = Species.retrieve_or_create(
            self.session, {'ht-epithet': "Calopogon",
                           'epithet': "pallidus"})
        self.assertEqual(afterwards.sp_author, 'Chapm.')
        self.assertEqual(len(afterwards.notes), 3)

    def test_import_new_same_picture_notes(self):
        before = Species.retrieve_or_create(
            self.session, {'ht-epithet': "Calopogon",
                           'epithet': "pallidus"})
        note = SpeciesNote(category='<picture>', note='a')
        self.session.commit()

        json_string = (
            '[{"ht-epithet": "Calopogon", "epithet": "pallidus", "author": '
            '"Chapm.", "rank": "Species", "ht-rank": "Genus", "hybrid": '
            'false}, {"object": "species_note", "species": "Calopogon '
            'pallidus", "category": "<picture>", "note": "a"}, {"object": '
            '"species_note", "species": "Calopogon pallidus", "category": '
            '"<picture>", "note": "b"}]'
        )
        with open(self.temp_path, "w") as f:
            f.write(json_string)
        importer = JSONImporter(MockView())
        importer.filename = self.temp_path
        importer.on_btnok_clicked(None)
        self.session.commit()
        afterwards = Species.retrieve_or_create(
            self.session, {'ht-epithet': "Calopogon",
                           'epithet': "pallidus"})
        self.assertEqual(afterwards.sp_author, 'Chapm.')
        self.assertEqual(len(afterwards.notes), 2)

    def test_import_new_with_repeated_note(self):
        json_string = (
            '[{"ht-epithet": "Calopogon", "epithet": "pallidus", "author": '
            '"Chapm.", "rank": "Species", "ht-rank": "Genus", "hybrid": '
            'false}, {"object": "species_note", "species": "Calopogon '
            'pallidus", "category": "<price>", "note": "8"}, {"object": '
            '"species_note", "species": "Calopogon pallidus", "category": '
            '"<price>", "note": "10"}]')
        with open(self.temp_path, "w") as f:
            f.write(json_string)
        importer = JSONImporter(MockView())
        importer.filename = self.temp_path
        importer.on_btnok_clicked(None)
        self.session.commit()
        afterwards = Species.retrieve_or_create(
            self.session, {'ht-epithet': "Calopogon",
                           'epithet': "pallidus"})
        self.assertEqual(afterwards.sp_author, 'Chapm.')
        self.assertEqual(len(afterwards.notes), 1)
        self.assertEqual(afterwards.notes[0].note, '10')

    def test_import_new_with_timestamped_note(self):
        json_string = (
            '[{"ht-epithet": "Calopogon", "epithet": "pallidus", "author": '
            '"Chapm.", "rank": "Species", "ht-rank": "Genus", "hybrid": '
            'false}, {"object": "species_note", "species": "Calopogon '
            'pallidus", "category": "<coords>", "note": "{lat: 8.5, lon: '
            '-80}", "date": {"__class__": "datetime", "millis": 1234567890}}]'
        )
        with open(self.temp_path, "w") as f:
            f.write(json_string)
        importer = JSONImporter(MockView())
        importer.filename = self.temp_path
        importer.on_btnok_clicked(None)
        self.session.commit()
        afterwards = Species.retrieve_or_create(
            self.session, {'ht-epithet': "Calopogon",
                           'epithet': "pallidus"})
        self.assertEqual(afterwards.sp_author, 'Chapm.')
        self.assertEqual(len(afterwards.notes), 1)
        import datetime
        self.assertEqual(afterwards.notes[0].date, datetime.date(2009, 2, 24))

    def test_import_existing_updates(self):
        "importing existing taxon updates it"
        json_string = (
            '[{"rank": "Species", "epithet": "tuberosus", "ht-rank"'
            ': "Genus", "ht-epithet": "Calopogon", "hybrid": false, "author"'
            ': "Britton et al."}]'
        )
        with open(self.temp_path, "w") as f:
            f.write(json_string)
        previously = Species.retrieve_or_create(
            self.session, {'ht-epithet': "Calopogon",
                           'epithet': "tuberosus"})
        self.assertEqual(previously.sp_author, None)
        importer = JSONImporter(MockView())
        importer.filename = self.temp_path
        importer.on_btnok_clicked(None)
        self.session.commit()
        afterwards = Species.retrieve_or_create(
            self.session, {'ht-epithet': "Calopogon",
                           'epithet': "tuberosus"})
        self.assertEqual(afterwards.sp_author, "Britton et al.")

    def test_import_ignores_id_new(self):
        "importing taxon disregards id value if present (new taxon)."
        previously = Genus.retrieve_or_create(
            self.session, {'epithet': "Neogyna"})
        self.assertEqual(previously, None)
        json_string = '[{"rank": "Genus", "epithet": "Neogyna", '\
            '"ht-rank": "Familia", "ht-epithet": "Orchidaceae", '\
            '"author": "Rchb. f.", "id": 1}]'
        with open(self.temp_path, "w") as f:
            f.write(json_string)
        importer = JSONImporter(MockView())
        importer.filename = self.temp_path
        importer.on_btnok_clicked(None)

        self.session.commit()
        real_id = Genus.retrieve_or_create(self.session,
                                           {'epithet': "Neogyna"}).id
        self.assertTrue(real_id != 1)

    def test_import_ignores_id_updating(self):
        "importing taxon disregards id value if present (updating taxon)."
        previously = Species.retrieve_or_create(self.session,
                                                {'ht-epithet': "Calopogon",
                                                 'epithet': "tuberosus"}).id
        json_string = '[{"rank": "Species", "epithet": "tuberosus", '\
            '"ht-rank": "Genus", "ht-epithet": "Calopogon", "hybrid": false, '\
            '"id": 8}]'
        with open(self.temp_path, "w") as f:
            f.write(json_string)
        importer = JSONImporter(MockView())
        importer.filename = self.temp_path
        importer.on_btnok_clicked(None)

        self.session.commit()
        afterwards = Species.retrieve_or_create(self.session,
                                                {'ht-epithet': "Calopogon",
                                                 'epithet': "tuberosus"}).id
        self.assertEqual(previously, afterwards)

    def test_import_species_to_new_genus_fails(self):
        "importing new species referring to non existing genus logs a warning."
        json_string = '[{"rank": "Species", "epithet": "lawrenceae", '\
            '"ht-rank": "Genus", "ht-epithet": "Aerides", "author": '\
            '"Rchb. f."}]'
        with open(self.temp_path, "w") as f:
            f.write(json_string)
        importer = JSONImporter(MockView())
        importer.filename = self.temp_path
        importer.on_btnok_clicked(None)

        ## should check the logs
        ## check the species is still not there
        sp = self.session.query(Species).filter(
            Species.sp == 'lawrenceae').join(Genus).filter(
            Genus.genus == 'Aerides').all()
        self.assertEqual(sp, [])

    def test_import_species_to_new_genus_and_family(self):
        "species referring to non existing genus (family is specified)"

        ## precondition: the species is not there
        sp = self.session.query(Species).filter(
            Species.sp == 'lawrenceae').join(Genus).filter(
            Genus.genus == 'Aerides').all()
        self.assertEqual(sp, [])

        json_string = '[{"rank": "Species", "epithet": "lawrenceae", '\
            '"ht-rank": "Genus", "ht-epithet": "Aerides", '\
            '"familia": "Orchidaceae", "author" : "Rchb. f."}]'
        with open(self.temp_path, "w") as f:
            f.write(json_string)
        importer = JSONImporter(MockView())
        importer.filename = self.temp_path
        importer.on_btnok_clicked(None)

        self.session.commit()
        ## postcondition: the species is there
        sp = self.session.query(Species).filter(
            Species.sp == 'lawrenceae').join(Genus).filter(
            Genus.genus == 'Aerides').all()
        self.assertEqual(len(sp), 1)
        sp = sp[0]
        genus = self.session.query(Genus).filter(
            Genus.genus == 'Aerides').first()
        family = self.session.query(Family).filter(
            Family.family == 'Orchidaceae').first()
        self.assertEqual(sp.genus, genus)
        self.assertEqual(genus.family, family)

    def test_import_with_synonym(self):
        "importing taxon with `accepted` field imports both taxa"
        json_string = '[{"rank": "Genus", "epithet": "Zygoglossum", '\
            '"ht-rank": "Familia", "ht-epithet": "Orchidaceae", '\
            '"author": "Reinw.", "accepted": {"rank": "Genus", '\
            '"epithet": "Bulbophyllum", "ht-rank": "Familia", '\
            '"ht-epithet": "Orchidaceae", "author": "Thouars"}}]'
        with open(self.temp_path, "w") as f:
            f.write(json_string)
        importer = JSONImporter(MockView())
        importer.filename = self.temp_path
        importer.on_btnok_clicked(None)

        self.session.commit()
        synonym = Genus.retrieve_or_create(
            self.session, {'epithet': "Zygoglossum"})
        self.assertEqual(synonym.accepted.__class__, Genus)
        accepted = Genus.retrieve_or_create(
            self.session, {'epithet': "Bulbophyllum"})
        self.assertEqual(synonym.accepted, accepted)

    def test_use_author_to_break_ties(self):
        "importing homonym taxon is possible if authorship breaks ties"
        # Anacampseros was used twice, by Linnaeus, and by Miller
        ataceae = Family(family='Anacampserotaceae')  # Eggli & Nyffeler
        linnaeus = Genus(family=ataceae, genus='Anacampseros', author='L.')
        claceae = Family(family='Crassulaceae')  # J. St.-Hil.
        miller = Genus(family=claceae, genus='Anacampseros', author='Mill.')
        self.session.add_all([claceae, ataceae, linnaeus, miller])
        self.session.commit()

        ## T_0
        accepted = Genus.retrieve_or_create(
            self.session, {'epithet': "Sedum"}, create=False)
        self.assertEqual(accepted, None)
        self.assertEqual(miller.accepted, None)

        ## what if we update Anacampseros Mill., with `accepted` information?
        json_string = ' {"author": "Mill.", "epithet": "Anacampseros", '\
            '"ht-epithet": "Crassulaceae", "ht-rank": "familia", '\
            '"object": "taxon", "rank": "genus", "accepted": {'\
            '"author": "L.", "epithet": "Sedum", "ht-epithet": '\
            '"Crassulaceae", "ht-rank": "familia", "object": "taxon", '\
            '"rank": "genus"}}'
        with open(self.temp_path, "w") as f:
            f.write(json_string)
        importer = JSONImporter(MockView())
        importer.filename = self.temp_path
        importer.on_btnok_clicked(None)
        self.session.commit()

        ## T_1
        accepted = Genus.retrieve_or_create(
            self.session, {'epithet': "Sedum"}, create=False)
        self.assertEqual(accepted.__class__, Genus)
        self.assertEqual(miller.accepted, accepted)

    def test_import_create_update(self):
        'existing gets updated, not existing is created'

        ## T_0
        ataceae = Family(family='Anacampserotaceae')  # Eggli & Nyffeler
        linnaeus = Genus(family=ataceae, genus='Anacampseros')  # L.
        self.session.add_all([ataceae, linnaeus])
        self.session.commit()

        ## offer two objects for import
        importer = JSONImporter(MockView())
        json_string = '[{"author": "L.", "epithet": "Anacampseros", '\
            '"ht-epithet": "Anacampserotaceae", "ht-rank": "familia", '\
            '"object": "taxon", "rank": "genus"}, {"author": "L.", '\
            '"epithet": "Sedum", "ht-epithet": "Crassulaceae", '\
            '"ht-rank": "familia", "object": "taxon", '\
            '"rank": "genus"}]'
        with open(self.temp_path, "w") as f:
            f.write(json_string)
        importer.filename = self.temp_path
        importer.create = True
        importer.update = True
        importer.on_btnok_clicked(None)
        self.session.commit()

        ## T_1
        sedum = Genus.retrieve_or_create(
            self.session, {'epithet': "Sedum"}, create=False)
        self.assertEqual(sedum.__class__, Genus)
        self.assertEqual(sedum.author, 'L.')
        anacampseros = Genus.retrieve_or_create(
            self.session, {'epithet': "Anacampseros"}, create=False)
        self.assertEqual(anacampseros.__class__, Genus)
        self.assertEqual(anacampseros.author, 'L.')

    def test_import_no_create_update(self):
        'existing gets updated, not existing is not created'

        ## T_0
        ataceae = Family(family='Anacampserotaceae')  # Eggli & Nyffeler
        linnaeus = Genus(family=ataceae, genus='Anacampseros')  # L.
        self.session.add_all([ataceae, linnaeus])
        self.session.commit()

        ## offer two objects for import
        importer = JSONImporter(MockView())
        json_string = '[{"author": "L.", "epithet": "Anacampseros", '\
            '"ht-epithet": "Anacampserotaceae", "ht-rank": "familia", '\
            '"object": "taxon", "rank": "genus"}, {"author": "L.", '\
            '"epithet": "Sedum", "ht-epithet": "Crassulaceae", '\
            '"ht-rank": "familia", "object": "taxon", '\
            '"rank": "genus"}]'
        with open(self.temp_path, "w") as f:
            f.write(json_string)
        importer.filename = self.temp_path
        importer.create = False
        importer.update = True
        importer.on_btnok_clicked(None)
        self.session.commit()

        ## T_1
        sedum = Genus.retrieve_or_create(
            self.session, {'epithet': "Sedum"}, create=False)
        self.assertEqual(sedum, None)
        anacampseros = Genus.retrieve_or_create(
            self.session, {'epithet': "Anacampseros"}, create=False)
        self.assertEqual(anacampseros.__class__, Genus)
        self.assertEqual(anacampseros.author, 'L.')

    def test_import_create_no_update(self):
        'existing remains untouched, not existing is created'

        ## T_0
        ataceae = Family(family='Anacampserotaceae')  # Eggli & Nyffeler
        linnaeus = Genus(family=ataceae, genus='Anacampseros')  # L.
        self.session.add_all([ataceae, linnaeus])
        self.session.commit()

        ## offer two objects for import
        importer = JSONImporter(MockView())
        json_string = '[{"author": "L.", "epithet": "Anacampseros", '\
            '"ht-epithet": "Anacampserotaceae", "ht-rank": "familia", '\
            '"object": "taxon", "rank": "genus"}, {"author": "L.", '\
            '"epithet": "Sedum", "ht-epithet": "Crassulaceae", '\
            '"ht-rank": "familia", "object": "taxon", '\
            '"rank": "genus"}]'
        with open(self.temp_path, "w") as f:
            f.write(json_string)
        importer.filename = self.temp_path
        importer.create = True
        importer.update = False
        importer.on_btnok_clicked(None)
        self.session.commit()

        ## T_1
        sedum = Genus.retrieve_or_create(
            self.session, {'epithet': "Sedum"}, create=False)
        self.assertEqual(sedum.__class__, Genus)
        self.assertEqual(sedum.author, 'L.')
        anacampseros = Genus.retrieve_or_create(
            self.session, {'epithet': "Anacampseros"}, create=False)
        self.assertEqual(anacampseros.__class__, Genus)
        self.assertEqual(anacampseros.author, '')

    def test_on_btnbrowse_clicked(self):
        view = MockView()
        exporter = JSONImporter(view)
        view.reply_file_chooser_dialog = ['/tmp/test.json']
        exporter.on_btnbrowse_clicked('button')
        exporter.on_text_entry_changed('input_filename')
        self.assertEqual(exporter.filename, '/tmp/test.json')
        self.assertEqual(JSONImporter.last_folder, '/tmp')

    def test_import_contact(self):
        ## T_0
        # empty database

        ## offer two objects for import
        importer = JSONImporter(MockView())
        json_string = '[{"name": "Summit", "object": "source_detail"}]'
        with open(self.temp_path, "w") as f:
            f.write(json_string)
        importer.filename = self.temp_path
        importer.create = True
        importer.update = True
        importer.on_btnok_clicked(None)
        self.session.commit()

        ## T_1
        summit = self.session.query(SourceDetail).first()
        self.assertNotEqual(summit, None)


class GlobalFunctionsTests(BaubleTestCase):
    def test_json_serializer_datetime(self):
        import datetime
        from .iojson import serializedatetime
        stamp = datetime.datetime(2011, 11, 11, 12, 13)
        self.assertEqual(serializedatetime(stamp),
                         {'millis': 1321013580000, '__class__': 'datetime'})


class GenericImporterTests(BaubleTestCase):
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
        out = GenericImporter.add_rec_to_db(self.session, obj, data1)
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
                                               'MRBG Friends of the Gardens'},
            'accession.species': {'epithet': 'leontopetaloides',
                                  'default_vernacular_name': 'Arrowroot'},
            'location': {'name': 'Whitsunday Islands', 'code': '12.01'},
            'accession': {'code': '1999000003'},
            'code': '1',
            'quantity': 10
        }
        obj = Plant()
        self.session.add(obj)
        out = GenericImporter.add_rec_to_db(self.session, obj, data2)
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
        out = GenericImporter.add_rec_to_db(self.session, obj, data3)
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
        out = GenericImporter.add_rec_to_db(self.session, obj, data4)
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

    def test_add_rec_to_db_plants_w_planted(self):
        data1 = {
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
            'planted': {'date': '01/01/2001 12:00:00 pm'},
            'code': '1',
            'quantity': 1
        }

        obj = Plant()
        self.session.add(obj)
        out = GenericImporter.add_rec_to_db(self.session, obj, data1)
        self.assertEqual(obj, out)
        # Committing will reveal issues that only show up at commit
        self.session.commit()
        result = self.session.query(Plant).get(1)
        self.assertEqual(result.quantity, data1.get('quantity'))
        self.assertEqual(result.code, data1.get('code'))
        self.assertEqual(result.accession.code,
                         data1.get('accession').get('code'))
        self.assertEqual(result.location.name,
                         data1.get('location').get('name'))
        self.assertEqual(
            result.accession.species.sp_author,
            data1.get('accession.species').get('sp_author'))
        self.assertEqual(
            result.accession.species.infrasp1,
            data1.get('accession.species').get('infrasp1'))
        self.assertEqual(
            result.planted.date.strftime('%d/%m/%Y %I:%M:%S %p').lower(),
            data1.get('planted').get('date').lower())
        # change date on existing planted
        data2 = {
            'accession': {'code': 'XXXX000001'},
            'planted': {'date': '02/01/2001 12:00:00 pm'},
            'code': '1',
            'quantity': 1
        }
        out = GenericImporter.add_rec_to_db(self.session, obj, data2)
        self.assertEqual(obj, out)
        self.session.commit()
        result = self.session.query(Plant).get(1)
        self.assertEqual(
            result.planted.date.strftime('%d/%m/%Y %I:%M:%S %p').lower(),
            data2.get('planted').get('date').lower())
        self.assertEqual(len(result.changes), 1)

    def test_add_rec_to_db_plants_w_death(self):
        # first add a plant to work with
        data1 = {
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
            'planted': {'date': '01/01/2001 12:00:00 pm'},
            'code': '1',
            'quantity': 1
        }

        obj = Plant()
        self.session.add(obj)
        out = GenericImporter.add_rec_to_db(self.session, obj, data1)
        self.assertEqual(obj, out)
        # Committing will reveal issues that only show up at commit
        self.session.commit()
        result = self.session.query(Plant).get(1)
        # then kill it
        data2 = {
            'accession': {'code': 'XXXX000001'},
            'death': {'date': '02/01/2011 12:00:00 pm'},
            'code': '1',
            'quantity': 0
        }
        out = GenericImporter.add_rec_to_db(self.session, obj, data2)
        self.assertEqual(obj, out)
        self.session.commit()
        result = self.session.query(Plant).get(1)
        self.assertEqual(
            result.death.date.strftime('%d/%m/%Y %I:%M:%S %p').lower(),
            data2.get('death').get('date').lower())
        self.assertEqual(len(result.changes), 2)
        # change the date of the existing death.
        data3 = {
            'accession': {'code': 'XXXX000001'},
            'death': {'date': '02/01/2012 12:00:00 pm'},
            'code': '1',
            'quantity': 0
        }
        out = GenericImporter.add_rec_to_db(self.session, obj, data3)
        self.assertEqual(obj, out)
        self.session.commit()
        result = self.session.query(Plant).get(1)
        self.assertEqual(
            result.death.date.strftime('%d/%m/%Y %I:%M:%S %p').lower(),
            data3.get('death').get('date').lower())
        self.assertEqual(len(result.changes), 2)

    def test_add_rec_to_db_plants_w_geojson(self):
        data1 = {
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
            'planted': {'date': '01/01/2001 12:00:00 pm'},
            'code': '1',
            'quantity': 1,
            'geojson': ("{'type': 'Point', 'coordinates': [0.0, 0.0]}")
        }

        obj = Plant()
        self.session.add(obj)
        out = GenericImporter.add_rec_to_db(self.session, obj, data1)
        self.assertEqual(obj, out)
        # Committing will reveal issues that only show up at commit
        self.session.commit()
        result = self.session.query(Plant).get(1)
        self.assertEqual(result.geojson.get('type'), 'Point')
        self.assertEqual(len(result.geojson.get('coordinates')), 2)
        self.assertEqual(len(result.changes), 1)

    def test_add_rec_to_db_location(self):
        data1 = {
            'code': '10.10',
            'name': 'Whitsunday Islands',
            'description': 'Selection of species of horticultural value '
            'commonly found on the Whitsunday Islands.'
        }

        obj = Location()
        self.session.add(obj)
        out = GenericImporter.add_rec_to_db(self.session, obj, data1)
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
        out = GenericImporter.add_rec_to_db(self.session, obj, data2)
        self.assertEqual(obj, out)
        # Committing will reveal issues that only show up at commit
        self.session.commit()
        result = self.session.query(Location).all()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].code, data1.get('code'))
        self.assertEqual(result[0].name, data1.get('name'))
        self.assertEqual(result[0].description, data2.get('description'))


class GenericExporterTests(BaubleTestCase):
    def test_get_item_value_gets_datetime_datetime_type(self):
        datetime_fmat = prefs.prefs.get(prefs.datetime_format_pref)
        item = Plant(code='3', accession_id=1, location_id=1, quantity=10)
        self.session.add(item)
        self.session.commit()
        now = datetime.now().strftime(datetime_fmat)
        val = GenericExporter.get_item_value('planted.date', item)
        # accuracy is seconds, chance of a mismatch should be uncommon
        self.assertEqual(val, now)

    def test_get_item_value_gets_date_type(self):
        date_fmat = prefs.prefs.get(prefs.date_format_pref)
        item = Accession(code='2020.4',
                         species_id=1,
                         date_accd=datetime.now())
        self.session.add(item)
        self.session.commit()
        now = datetime.now().strftime(date_fmat)
        val = GenericExporter.get_item_value('date_accd', item)
        # accuracy is seconds, chance of a mismatch should be very uncommon
        self.assertEqual(val, now)

    def test_get_item_value_gets_datetime_type(self):
        datetime_fmat = prefs.prefs.get(prefs.datetime_format_pref)
        item = Plant(code='3', accession_id=1, location_id=1, quantity=10)
        self.session.add(item)
        self.session.commit()
        now = datetime.now().strftime(datetime_fmat)
        val = GenericExporter.get_item_value('_created', item)
        # accuracy is seconds, chance of a mismatch should be uncommon
        self.assertEqual(val, now)

    def test_get_item_value_gets_path(self):
        plants_test.setUp_data()
        garden_test.setUp_data()
        item = self.session.query(Plant).get(1)
        val = GenericExporter.get_item_value(
            'accession.species.genus.family.epithet', item
        )
        self.assertEqual(val, 'Orchidaceae')

    def test_get_item_value_gets_boolean(self):
        plants_test.setUp_data()
        garden_test.setUp_data()
        item = self.session.query(Species).get(1)
        val = GenericExporter.get_item_value('hybrid', item)
        self.assertEqual(val, 'False')
