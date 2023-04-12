# Copyright 2008-2010 Brett Adams
# Copyright 2015 Mario Frasca <mario@anche.no>.
# Copyright 2017 Jardín Botánico de Quito
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
#
# Description: test for the Plant plugin
#
import logging
logging.basicConfig()
# logging.getLogger('sqlalchemy.engine').setLevel(logging.INFO)

import os
from datetime import datetime
from unittest import TestCase, skip, mock
from functools import partial

from sqlalchemy.orm.exc import NoResultFound
from sqlalchemy.exc import IntegrityError

from bauble import utils, search, db
from bauble import prefs
from bauble.test import (BaubleTestCase,
                         check_dupids,
                         mockfunc,
                         update_gui,
                         wait_on_threads)
from . import SplashInfoBox
from .species import (Species,
                      VernacularName,
                      SpeciesSynonym,
                      SpeciesEditor,
                      DefaultVernacularName,
                      SpeciesDistribution,
                      SpeciesNote)
from .species_editor import (species_to_string_matcher,
                             species_match_func,
                             generic_sp_get_completions,
                             species_cell_data_func,
                             SpeciesEntry,
                             DistributionPresenter,
                             VernacularNamePresenter,
                             SynonymsPresenter,
                             InfraspPresenter,
                             InfraspRow,
                             SpeciesEditorPresenter,
                             SpeciesEditorView)
from .species_model import _remove_zws as remove_zws
from .species_model import (update_all_full_names_task,
                            update_all_full_names_handler,
                            infrasp_rank_values)
from .family import Family, FamilySynonym, FamilyEditor, FamilyNote
from .genus import Genus, GenusSynonym, GenusEditor, GenusNote
from .geography import Geography, get_species_in_geography, geography_importer

#
# TODO: things to create tests for
#
# - test schema cascading works for all tables in the plants module
# - test unicode is working properly in the relevant fields, especially
# in the Species.str function
# - test the setting the default vernacular name on a species is working
# and that delete vernacular names and default vernacular names does
# proper  cascading
# make sure that deleting either of the species referred to in a synonym
# deletes the synonym

# TODO: create some scenarios that should fail


family_test_data = (
    {'id': 1, 'family': 'Orchidaceae'},
    {'id': 2, 'family': 'Leguminosae', 'qualifier': 's. str.'},
    {'id': 3, 'family': 'Polypodiaceae'},
    {'id': 4, 'family': 'Solanaceae'},
    {'id': 5, 'family': 'Rosaceae'},
    {'id': 6, 'family': 'Arecaceae'},
    {'id': 7, 'family': 'Poaceae'},
)

family_note_test_data = (
    {'id': 1, 'family_id': 1, 'category': 'CITES', 'note': 'II'},
)

genus_test_data = (
    {'id': 1, 'genus': 'Maxillaria', 'family_id': 1},
    {'id': 2, 'genus': 'Encyclia', 'family_id': 1},
    {'id': 3, 'genus': 'Abrus', 'family_id': 2},
    {'id': 4, 'genus': 'Campyloneurum', 'family_id': 3},
    {'id': 5, 'genus': 'Paphiopedilum', 'family_id': 1},
    {'id': 6, 'genus': 'Laelia', 'family_id': 1},
    {'id': 7, 'genus': 'Brugmansia', 'family_id': 4},
    {'id': 8, 'hybrid': '+', 'genus': 'Crataegomespilus', 'family_id': 5},
    {'id': 9, 'hybrid': '×', 'genus': 'Butyagrus', 'family_id': 6},
    {'id': 10, 'genus': 'Cynodon', 'family_id': 7},
)

genus_note_test_data = (
    {'id': 1, 'genus_id': 5, 'category': 'CITES', 'note': 'I'},
    {'id': 2, 'genus_id': 1, 'category': 'URL', 'note':
     'https://en.wikipedia.org/wiki/Maxillaria'},
)

species_test_data = (
    {'id': 1, 'sp': 'variabilis', 'genus_id': 1,
     'sp_author': 'Bateman ex Lindl.'},
    {'id': 2, 'sp': 'cochleata', 'genus_id': 2,
     'sp_author': '(L.) Lem\xe9e'},
    {'id': 3, 'sp': 'precatorius', 'genus_id': 3,
     'sp_author': 'L.'},
    {'id': 4, 'sp': 'alapense', 'genus_id': 4,
     'hybrid': '×', 'sp_author': 'F\xe9e'},
    {'id': 5, 'sp': 'cochleata', 'genus_id': 2,
     'sp_author': '(L.) Lem\xe9e',
     'infrasp1_rank': 'var.', 'infrasp1': 'cochleata'},
    {'id': 6, 'sp': 'cochleata', 'genus_id': 2,
     'sp_author': '(L.) Lem\xe9e',
     'cultivar_epithet': 'Black Night'},
    {'id': 7, 'sp': 'precatorius', 'genus_id': 3,
     'sp_author': 'L.', 'cv_group': 'SomethingRidiculous'},
    {'id': 8, 'sp': 'precatorius', 'genus_id': 3,
     'sp_author': 'L.',
     'cultivar_epithet': 'Hot Rio Nights',
     'cv_group': 'SomethingRidiculous'},
    {'id': 9, 'sp': 'generalis', 'genus_id': 1,
     'hybrid': '×',
     'cultivar_epithet': 'Red'},
    {'id': 10, 'sp': 'generalis', 'genus_id': 1,
     'hybrid': '×', 'sp_author': 'L.',
     'cultivar_epithet': 'Red',
     'cv_group': 'SomeGroup'},
    {'id': 11, 'sp': 'generalis', 'genus_id': 1,
     'sp_qual': 'agg.'},
    {'id': 12, 'genus_id': 1, 'cv_group': 'SomeGroup'},
    {'id': 13, 'genus_id': 1,
     'cultivar_epithet': 'Red'},
    {'id': 14, 'genus_id': 1,
     'cultivar_epithet': 'Red & Blue'},
    {'id': 15, 'sp': 'cochleata', 'genus_id': 2,
     'sp_author': 'L.',
     'infrasp1_rank': 'subsp.', 'infrasp1': 'cochleata',
     'infrasp1_author': 'L.',
     'infrasp2_rank': 'var.', 'infrasp2': 'cochleata',
     'infrasp2_author': 'L.',
     'cultivar_epithet': 'Black'},
    {'id': 16, 'genus_id': 1, 'sp': 'test',
     'infrasp1_rank': 'subsp.', 'infrasp1': 'test',
     'cv_group': 'SomeGroup'},
    {'id': 17, 'genus_id': 5, 'sp': 'adductum', 'author': 'Asher'},
    {'id': 18, 'genus_id': 6, 'sp': 'lobata', 'author': 'H.J. Veitch'},
    {'id': 19, 'genus_id': 6, 'sp': 'grandiflora', 'author': 'Lindl.'},
    {'id': 20, 'genus_id': 2, 'sp': 'fragrans', 'author': 'Dressler'},
    {'id': 21, 'genus_id': 7, 'sp': 'arborea', 'author': 'Lagerh.'},
    {'id': 22, 'sp': '', 'genus_id': 1, 'sp_author': '',
     'cultivar_epithet': 'Layla Saida'},
    {'id': 23, 'sp': '', 'genus_id': 1, 'sp_author': '',
     'cultivar_epithet': 'Buonanotte'},
    {'id': 24, 'sp': '', 'genus_id': 1, 'sp_author': '',
     'infrasp1_rank': None, 'infrasp1': 'sp'},
    {'id': 25, 'sp': 'dardarii', 'genus_id': 8},
    {'id': 26, 'sp': 'nabonnandii', 'genus_id': 9},
    {'id': 27, 'sp': 'dactylon × transvaalensis', 'genus_id': 10,
     'cultivar_epithet': 'DT-1', 'pbr_protected': True, 'trade_name': 'TifTuf',
     'trademark_symbol': '™'},
    {'id': 28, 'sp': 'precatorius', 'genus_id': 3,
     'infrasp1_rank': 'subsp.', 'infrasp1': 'africanus',
     'infrasp1_author': 'Verdc.'},
    {'id': 29, 'genus_id': 5, 'cultivar_epithet': 'Springwater',
     'grex': 'Jim Kie'}
)

species_note_test_data = (
    {'id': 1, 'species_id': 18, 'category': 'CITES', 'note': 'I'},
    {'id': 2, 'species_id': 20, 'category': 'IUCN', 'note': 'LC'},
    {'id': 3, 'species_id': 18, 'category': '<price>', 'note': '19.50'},
    {'id': 4, 'species_id': 18, 'category': '[list_var]', 'note': 'abc'},
    {'id': 5, 'species_id': 18, 'category': '[list_var]', 'note': 'def'},
    {'id': 6, 'species_id': 18, 'category': '<price_tag>', 'note': '$19.50'},
    {'id': 7, 'species_id': 18, 'category': '{dict_var:k}', 'note': 'abc'},
    {'id': 8, 'species_id': 18, 'category': '{dict_var:l}', 'note': 'def'},
    {'id': 9, 'species_id': 18, 'category': '{dict_var:m}', 'note': 'xyz'},
)

species_str_map = {
    1: 'Maxillaria variabilis',
    2: 'Encyclia cochleata',
    3: 'Abrus precatorius',
    4: 'Campyloneurum × alapense',
    5: 'Encyclia cochleata var. cochleata',
    6: "Encyclia cochleata 'Black Night'",
    7: 'Abrus precatorius SomethingRidiculous Group',
    8: "Abrus precatorius (SomethingRidiculous Group) 'Hot Rio Nights'",
    9: "Maxillaria × generalis 'Red'",
    10: "Maxillaria × generalis (SomeGroup Group) 'Red'",
    11: "Maxillaria generalis agg.",
    12: "Maxillaria SomeGroup Group",
    13: "Maxillaria 'Red'",
    14: "Maxillaria 'Red & Blue'",
    15: "Encyclia cochleata subsp. cochleata var. cochleata 'Black'",
    16: "Maxillaria test subsp. test SomeGroup Group",
    25: "+ Crataegomespilus dardarii",
    26: "× Butyagrus nabonnandii",
    27: "Cynodon dactylon × transvaalensis 'DT-1' (PBR) TIFTUF™",
    28: "Abrus precatorius subsp. africanus",
    29: "Paphiopedilum Jim Kie 'Springwater'",
}

species_markup_map = {
    1: '<i>Maxillaria</i> <i>variabilis</i>',
    2: '<i>Encyclia</i> <i>cochleata</i>',
    3: '<i>Abrus</i> <i>precatorius</i>',
    4: '<i>Campyloneurum</i> × <i>alapense</i>',
    5: '<i>Encyclia</i> <i>cochleata</i> var. <i>cochleata</i>',
    6: '<i>Encyclia</i> <i>cochleata</i> \'Black Night\'',
    12: "<i>Maxillaria</i> SomeGroup Group",
    14: "<i>Maxillaria</i> 'Red &amp; Blue'",
    15: ("<i>Encyclia</i> <i>cochleata</i> subsp. <i>"
         "cochleata</i> var. <i>cochleata</i> 'Black'"),
    25: "+ <i>Crataegomespilus</i> <i>dardarii</i>",
    26: "× <i>Butyagrus</i> <i>nabonnandii</i>",
    27: ("<i>Cynodon</i> <i>dactylon</i> × <i>transvaalensis</i> 'DT-1' "
         "<span size=\"xx-small\">(PBR)</span> "
         "T<small>IF</small>T<small>UF</small>™"),
    29: "<i>Paphiopedilum</i> Jim Kie 'Springwater'",
}

species_str_authors_map = {
    1: 'Maxillaria variabilis Bateman ex Lindl.',
    2: 'Encyclia cochleata (L.) Lem\xe9e',
    3: 'Abrus precatorius L.',
    4: 'Campyloneurum × alapense F\xe9e',
    5: 'Encyclia cochleata (L.) Lem\xe9e var. cochleata',
    6: 'Encyclia cochleata (L.) Lem\xe9e \'Black Night\'',
    7: 'Abrus precatorius L. SomethingRidiculous Group',
    8: "Abrus precatorius L. (SomethingRidiculous Group) 'Hot Rio Nights'",
    15: ("Encyclia cochleata L. subsp. "
         "cochleata L. var. cochleata L. 'Black'"),
    28: "Abrus precatorius subsp. africanus Verdc.",
}

species_markup_authors_map = {
    1: '<i>Maxillaria</i> <i>variabilis</i> Bateman ex Lindl.',
    2: '<i>Encyclia</i> <i>cochleata</i> (L.) Lem\xe9e',
    3: '<i>Abrus</i> <i>precatorius</i> L.',
    4: '<i>Campyloneurum</i> × <i>alapense</i> F\xe9e',
    5: '<i>Encyclia</i> <i>cochleata</i> (L.) Lem\xe9e var. <i>cochleata</i>',
    6: '<i>Encyclia</i> <i>cochleata</i> (L.) Lem\xe9e \'Black Night\''}

species_searchview_markup_map = {
    1: ('<i>Maxillaria</i> <i>variabilis</i> <span weight="light">Bateman ex '
        'Lindl.</span>'),
    28: ('<i>Abrus</i> <i>precatorius</i> subsp. <i>africanus</i> '
         '<span weight="light">Verdc.</span>'),
}

sp_synonym_test_data = ({'id': 1, 'synonym_id': 1, 'species_id': 2},
                        )

vn_test_data = (
    {'id': 1, 'name': 'SomeName', 'language': 'English', 'species_id': 1},
    {'id': 2, 'name': 'SomeName 2', 'language': 'English', 'species_id': 1},
    {'id': 3, 'name': 'Floripondio', 'language': 'es', 'species_id': 21},
    {'id': 4, 'name': 'Toé', 'language': 'agr', 'species_id': 21},
    {'id': 5, 'name': 'Clamshell orchid', 'language': 'English',
     'species_id': 15},
    {'id': 6, 'name': 'Clamshell orchid', 'language': 'English',
     'species_id': 6},
    {'id': 7, 'name': 'Clamshell orchid', 'language': 'English',
     'species_id': 5},
    {'id': 8, 'name': 'Clamshell orchid', 'language': 'English',
     'species_id': 2},
)

test_data_table_control = (
    (Family, family_test_data),
    (Genus, genus_test_data),
    (Species, species_test_data),
    (VernacularName, vn_test_data),
    (SpeciesSynonym, sp_synonym_test_data),
    (FamilyNote, family_note_test_data),
    (GenusNote, genus_note_test_data),
    (SpeciesNote, species_note_test_data),
)


def setUp_data():
    """
    bauble.plugins.plants.test.setUp_test_data()

    if this method is called again before tearDown_test_data is called you
    will get an error about the test data rows already existing in the database
    """

    for mapper, data in test_data_table_control:
        table = mapper.__table__
        # insert row by row instead of doing an insert many since each
        # row will have different columns
        for row in data:
            table.insert().execute(row).close()
        for col in table.c:
            utils.reset_sequence(col)


setUp_data.order = 0


class DuplicateIdsGlade(TestCase):
    def test_duplicate_ids(self):
        """
        Test for duplicate ids for all .glade files in the plants plugin.
        """
        import bauble.plugins.garden as mod
        import glob
        head, tail = os.path.split(mod.__file__)
        files = glob.glob(os.path.join(head, '*.glade'))
        for f in files:
            self.assertTrue(not check_dupids(f), f)


class PlantTestCase(BaubleTestCase):

    def setUp(self):
        super().setUp()
        setUp_data()


class PrefsUpdatedTest(BaubleTestCase):

    def test_prefs_update(self):
        # NOTE plugin.init() is called in BaubleTestCase.setUp if this plugin
        # exists the prefs in default/config.cfg should have been copied in.
        # tests pluginmgr.update_prefs
        self.assertTrue(
            prefs.prefs.get('web_button_defs.species.googlebutton')
        )
        self.assertTrue(
            prefs.prefs.get('web_button_defs.genus.googlebutton')
        )
        self.assertTrue(
            prefs.prefs.get('web_button_defs.family.googlebutton')
        )


class FamilyTests(PlantTestCase):
    """
    Test for Family and FamilySynonym
    """
    def test_cascades(self):
        """
        Test that cascading is set up properly
        """
        family = Family(family='family')
        genus = Genus(family=family, genus='genus')
        self.session.add_all([family, genus])
        self.session.commit()

        # test that deleting a family deletes an orphaned genus
        self.session.delete(family)
        self.session.commit()
        query = self.session.query(Genus).filter_by(family_id=family.id)
        self.assertRaises(NoResultFound, query.one)

    def test_synonyms(self):
        """
        Test that Family.synonyms works correctly
        """
        family = Family(family='family')
        family2 = Family(family='family2')
        family.synonyms.append(family2)
        self.session.add_all([family, family2])
        self.session.commit()

        # test that family2 was added as a synonym to family
        family = self.session.query(Family).filter_by(family='family').one()
        self.assertTrue(family2 in family.synonyms)

        # test that the synonyms relation and family backref works
        self.assertTrue(family._synonyms[0].family == family)
        self.assertTrue(family._synonyms[0].synonym == family2)

        # test that the synonyms are removed properly
        family.synonyms.remove(family2)
        self.session.commit()
        self.assertTrue(family2 not in family.synonyms)

        # test synonyms contraints, e.g that a family cannot have the
        # same synonym twice
        family.synonyms.append(family2)
        self.session.commit()
        family.synonyms.append(family2)
        self.assertRaises(IntegrityError, self.session.commit)
        self.session.rollback()

        # test that clearing all the synonyms works
        family.synonyms.clear()
        self.session.commit()
        self.assertTrue(len(family.synonyms) == 0)
        self.assertTrue(self.session.query(FamilySynonym).count() == 0)

        # test that deleting a family that is a synonym of another family
        # deletes all the dangling object s
        family.synonyms.append(family2)
        self.session.commit()
        self.session.delete(family2)
        self.session.commit()
        self.assertTrue(self.session.query(FamilySynonym).count() == 0)

        # test that deleting the previous synonyms didn't delete the
        # family that it refered to
        self.assertTrue(self.session.query(Family).get(family.id))

        # test that deleting a family that has synonyms deletes all
        # the synonyms that refer to that family deletes all the
        family2 = Family(family='family2')
        self.session.add(family2)
        family.synonyms.append(family2)
        self.session.commit()
        self.session.delete(family)
        self.session.commit()
        self.assertTrue(self.session.query(FamilySynonym).count() == 0)

    def test_constraints(self):
        """
        Test that the family constraints were created correctly
        """
        values = [dict(family='family'),
                  dict(family='family', qualifier='s. lat.')]
        for v in values:
            self.session.add(Family(**v))
            self.session.add(Family(**v))
            self.assertRaises(IntegrityError, self.session.commit)
            self.session.rollback()

        # test that family cannot be null
        self.session.add(Family(family=None))
        self.assertRaises(IntegrityError, self.session.commit)
        self.session.rollback()

    def test_str(self):
        """
        Test that the family str function works as expected
        """
        f = Family()
        self.assertTrue(str(f) == repr(f))
        f = Family(family='fam')
        self.assertTrue(str(f) == 'fam')
        f.qualifier = 's. lat.'
        self.assertTrue(str(f) == 'fam s. lat.')

    @mock.patch('bauble.editor.GenericEditorView.start')
    def test_editor_doesnt_leak(self, mock_start):
        from gi.repository import Gtk
        mock_start.return_value = Gtk.ResponseType.OK
        fam = Family(family='some family')
        editor = FamilyEditor(model=fam)
        editor.start()
        del editor
        self.assertEqual(utils.gc_objects_by_type('FamilyEditor'),
                         [], 'FamilyEditor not deleted')
        self.assertEqual(utils.gc_objects_by_type('FamilyEditorPresenter'),
                         [], 'FamilyEditorPresenter not deleted')
        self.assertEqual(utils.gc_objects_by_type('FamilyEditorView'),
                         [], 'FamilyEditorView not deleted')

    def test_remove_callback_no_genera_no_confirm(self):
        # T_0
        f5 = Family(family='Araucariaceae')
        self.session.add(f5)
        self.session.flush()
        self.invoked = []

        # action
        orig_yes_no_dialog = utils.yes_no_dialog
        orig_message_details_dialog = utils.message_details_dialog
        utils.yes_no_dialog = partial(
            mockfunc, name='yes_no_dialog', caller=self, result=False)
        utils.message_details_dialog = partial(
            mockfunc, name='message_details_dialog', caller=self)
        from bauble.plugins.plants.family import remove_callback
        result = remove_callback([f5])
        self.session.flush()

        # effect
        self.assertFalse('message_details_dialog' in
                         [f for (f, m) in self.invoked])
        self.assertTrue(('yes_no_dialog', 'Are you sure you want to '
                         'remove the following families <i>Araucariaceae</i>?')
                        in self.invoked)
        self.assertEqual(result, None)
        q = self.session.query(Family).filter_by(family="Araucariaceae")
        matching = q.all()
        self.assertEqual(matching, [f5])
        utils.yes_no_dialog = orig_yes_no_dialog
        utils.message_details_dialog = orig_message_details_dialog

    def test_remove_callback_no_genera_confirm(self):
        # T_0
        f5 = Family(family='Araucariaceae')
        self.session.add(f5)
        self.session.flush()
        self.invoked = []

        # action
        orig_yes_no_dialog = utils.yes_no_dialog
        orig_message_details_dialog = utils.message_details_dialog
        utils.yes_no_dialog = partial(
            mockfunc, name='yes_no_dialog', caller=self, result=True)
        utils.message_details_dialog = partial(
            mockfunc, name='message_details_dialog', caller=self)
        from bauble.plugins.plants.family import remove_callback
        result = remove_callback([f5])
        self.session.flush()

        # effect
        print(self.invoked)
        self.assertFalse('message_details_dialog' in
                         [f for (f, m) in self.invoked])
        self.assertTrue(('yes_no_dialog', 'Are you sure you want to '
                         'remove the following families <i>Araucariaceae</i>?')
                        in self.invoked)

        self.assertEqual(result, True)
        q = self.session.query(Family).filter_by(family="Araucariaceae")
        matching = q.all()
        self.assertEqual(matching, [])
        utils.yes_no_dialog = orig_yes_no_dialog
        utils.message_details_dialog = orig_message_details_dialog

    def test_remove_callback_with_genera_cant_cascade(self):
        # T_0
        f5 = Family(family='Araucariaceae')
        gf5 = Genus(family=f5, genus='Araucaria')
        self.session.add_all([f5, gf5])
        self.session.flush()
        self.invoked = []

        # action
        orig_yes_no_dialog = utils.yes_no_dialog
        orig_message_dialog = utils.message_dialog
        orig_message_details_dialog = utils.message_details_dialog
        utils.yes_no_dialog = partial(
            mockfunc, name='yes_no_dialog', caller=self, result=True)
        utils.message_dialog = partial(
            mockfunc, name='message_dialog', caller=self, result=True)
        utils.message_details_dialog = partial(
            mockfunc, name='message_details_dialog', caller=self)
        from bauble.plugins.plants.family import remove_callback
        result = remove_callback([f5])
        self.session.flush()

        # effect
        print(self.invoked)
        self.assertFalse('message_details_dialog' in
                         [f for (f, m) in self.invoked])
        self.assertTrue(('message_dialog',
                         'The family <i>Araucariaceae</i> has 1 genera.\n\nYou '
                         'cannot remove a family with genera.')
                        in self.invoked)
        q = self.session.query(Family).filter_by(family="Araucariaceae")
        matching = q.all()
        self.assertEqual(matching, [f5])
        q = self.session.query(Genus).filter_by(genus="Araucaria")
        matching = q.all()
        self.assertEqual(matching, [gf5])
        utils.yes_no_dialog = orig_yes_no_dialog
        utils.message_dialog = orig_message_dialog
        utils.message_details_dialog = orig_message_details_dialog

    def test_no_synonyms_means_itself_accepted(self):
        def create_tmp_fam(id):
            fam = Family(id=id, epithet="fam%02d" % id)
            self.session.add(fam)
            return fam

        fam1 = create_tmp_fam(51)
        self.session.commit()
        self.assertEqual(fam1.accepted, None)

    def test_synonyms_and_accepted_properties(self):
        def create_tmp_fam(id):
            fam = Family(id=id, epithet="fam%02d" % id)
            self.session.add(fam)
            return fam

        # equivalence classes after changes
        fam1 = create_tmp_fam(41)
        fam2 = create_tmp_fam(42)
        fam3 = create_tmp_fam(43)
        fam4 = create_tmp_fam(44)  # (1), (2), (3), (4)
        fam3.accepted = fam1  # (1 3), (2), (4)
        self.assertEqual([i.epithet for i in fam1.synonyms], [fam3.epithet])
        fam1.synonyms.append(fam2)  # (1 3 2), (4)
        self.session.flush()
        self.assertEqual(fam2.accepted.epithet, fam1.epithet)  # just added
        self.assertEqual(fam3.accepted.epithet, fam1.epithet)  # no change
        fam2.accepted = fam4  # (1 3), (4 2)
        self.session.commit()
        self.assertEqual([i.epithet for i in fam4.synonyms], [fam2.epithet])
        self.assertEqual([i.epithet for i in fam1.synonyms], [fam3.epithet])
        self.assertEqual(fam1.accepted, None)
        self.assertEqual(fam2.accepted, fam4)
        self.assertEqual(fam3.accepted, fam1)
        self.assertEqual(fam4.accepted, None)
        fam2.accepted = fam4  # does not change anything
        self.session.commit()
        self.assertEqual(fam1.accepted, None)
        self.assertEqual(fam2.accepted, fam4)
        self.assertEqual(fam3.accepted, fam1)
        self.assertEqual(fam4.accepted, None)
        fam2.accepted = fam2  # cannot be a synonym of itself
        self.assertRaises(IntegrityError, self.session.commit)

    def test_top_level_count_w_plant_qty(self):
        from ..garden import Accession, Plant, Location
        fam = Family(family='Myrtaceae')
        gen = Genus(epithet='Syzygium', family=fam)
        sp = Species(epithet='australe', genus=gen)
        acc = Accession(species=sp, code='1')
        plant = Plant(accession=acc,
                      quantity=1,
                      location=Location(name='site', code='STE'),
                      code='1')
        self.session.add_all([fam, gen, sp, acc, plant])
        self.session.commit()
        self.assertEqual(len(fam.top_level_count()[(1, 'Families')]), 1)
        self.assertEqual(len(fam.top_level_count()[(2, 'Genera')]), 1)
        self.assertEqual(len(fam.top_level_count()[(3, 'Species')]), 1)
        self.assertEqual(fam.top_level_count()[(4, 'Accessions')], 1)
        self.assertEqual(fam.top_level_count()[(5, 'Plantings')], 1)
        self.assertEqual(fam.top_level_count()[(6, 'Living plants')], 1)
        self.assertEqual(len(fam.top_level_count()[(7, 'Locations')]), 1)
        self.assertEqual(len(fam.top_level_count()[(8, 'Sources')]), 0)

    def test_top_level_count_wo_plant_qty(self):
        from ..garden import Accession, Plant, Location
        fam = Family(family='Myrtaceae')
        gen = Genus(epithet='Syzygium', family=fam)
        sp = Species(epithet='australe', genus=gen)
        acc = Accession(species=sp, code='1')
        plant = Plant(accession=acc,
                      quantity=0,
                      location=Location(name='site', code='STE'),
                      code='1')
        self.session.add_all([fam, gen, sp, acc, plant])
        self.session.commit()
        self.assertEqual(len(fam.top_level_count()[(1, 'Families')]), 1)
        self.assertEqual(len(fam.top_level_count()[(2, 'Genera')]), 1)
        self.assertEqual(len(fam.top_level_count()[(3, 'Species')]), 1)
        self.assertEqual(fam.top_level_count()[(4, 'Accessions')], 1)
        self.assertEqual(fam.top_level_count()[(5, 'Plantings')], 1)
        self.assertEqual(fam.top_level_count()[(6, 'Living plants')], 0)
        self.assertEqual(len(fam.top_level_count()[(7, 'Locations')]), 1)
        self.assertEqual(len(fam.top_level_count()[(8, 'Sources')]), 0)

    def test_top_level_count_wo_plant_qty_exclude_inactive_set(self):
        from ..garden import Accession, Plant, Location
        fam = Family(family='Myrtaceae')
        gen = Genus(epithet='Syzygium', family=fam)
        sp = Species(epithet='australe', genus=gen)
        acc = Accession(species=sp, code='1')
        plant = Plant(accession=acc,
                      quantity=0,
                      location=Location(name='site', code='STE'),
                      code='1')
        self.session.add_all([fam, gen, sp, acc, plant])
        self.session.commit()
        prefs.prefs[prefs.exclude_inactive_pref] = True
        self.assertEqual(len(fam.top_level_count()[(1, 'Families')]), 1)
        self.assertEqual(len(fam.top_level_count()[(2, 'Genera')]), 1)
        self.assertEqual(len(fam.top_level_count()[(3, 'Species')]), 0)
        self.assertEqual(fam.top_level_count()[(4, 'Accessions')], 0)
        self.assertEqual(fam.top_level_count()[(5, 'Plantings')], 0)
        self.assertEqual(fam.top_level_count()[(6, 'Living plants')], 0)
        self.assertEqual(len(fam.top_level_count()[(7, 'Locations')]), 0)
        self.assertEqual(len(fam.top_level_count()[(8, 'Sources')]), 0)


class GenusTests(PlantTestCase):

    def test_synonyms(self):
        family = Family(family='family')
        genus = Genus(family=family, genus='genus')
        genus2 = Genus(family=family, genus='genus2')
        genus.synonyms.append(genus2)
        self.session.add_all([genus, genus2])
        self.session.commit()

        # test that genus2 was added as a synonym to genus
        genus = self.session.query(Genus).filter_by(genus='genus').one()
        self.assertTrue(genus2 in genus.synonyms)

        # test that the synonyms relation and genus backref works
        self.assertTrue(genus._synonyms[0].genus == genus)
        self.assertTrue(genus._synonyms[0].synonym == genus2)

        # test that the synonyms are removed properly
        genus.synonyms.remove(genus2)
        self.session.commit()
        self.assertTrue(genus2 not in genus.synonyms)

        # test synonyms contraints, e.g that a genus cannot have the
        # same synonym twice
        genus.synonyms.append(genus2)
        self.session.commit()
        genus.synonyms.append(genus2)
        self.assertRaises(IntegrityError, self.session.commit)
        self.session.rollback()

        # test that clearing all the synonyms works
        genus.synonyms.clear()
        self.session.commit()
        self.assertTrue(len(genus.synonyms) == 0)
        self.assertTrue(self.session.query(GenusSynonym).count() == 0)

        # test that deleting a genus that is a synonym of another genus
        # deletes all the dangling objects
        genus.synonyms.append(genus2)
        self.session.commit()
        self.session.delete(genus2)
        self.session.commit()
        self.assertTrue(self.session.query(GenusSynonym).count() == 0)

        # test that deleting the previous synonyms didn't delete the
        # genus that it refered to
        self.assertTrue(self.session.query(Genus).get(genus.id))

        # test that deleting a genus that has synonyms deletes all
        # the synonyms that refer to that genus
        genus2 = Genus(family=family, genus='genus2')
        self.session.add(genus2)
        genus.synonyms.append(genus2)
        self.session.commit()
        self.session.delete(genus)
        self.session.commit()
        self.assertTrue(self.session.query(GenusSynonym).count() == 0)

    def test_contraints(self):
        """
        Test that the genus constraints were created correctly
        """
        family = Family(family='family')
        self.session.add(family)

        # if any of these values are inserted twice they should raise
        # an IntegrityError because the UniqueConstraint on Genus
        values = [dict(family=family, genus='genus'),
                  dict(family=family, genus='genus', author='author'),
                  dict(family=family, genus='genus', qualifier='s. lat.'),
                  dict(family=family, genus='genus', qualifier='s. lat.',
                       author='author')
                  ]
        for v in values:
            self.session.add(Genus(**v))
            self.session.add(Genus(**v))
            self.assertRaises(IntegrityError, self.session.commit)
            self.session.rollback()

    def test_str(self):
        """
        Test that the Genus string functions works as expected
        """
        pass

    @mock.patch('bauble.editor.GenericEditorView.start')
    def test_editor_doesnt_leak(self, mock_start):
        from gi.repository import Gtk
        mock_start.return_value = Gtk.ResponseType.OK
        # loc = self.create(Genus, name=u'some site')
        fam = Family(family='family')
        fam2 = Family(family='family2')
        fam2.synonyms.append(fam)
        self.session.add_all([fam, fam2])
        self.session.commit()
        gen = Genus(genus='some genus')
        editor = GenusEditor(model=gen)
        editor.start()
        del editor
        self.assertEqual(utils.gc_objects_by_type('GenusEditor'),
                         [], 'GenusEditor not deleted')
        self.assertEqual(utils.gc_objects_by_type('GenusEditorPresenter'),
                         [], 'GenusEditorPresenter not deleted')
        self.assertEqual(utils.gc_objects_by_type('GenusEditorView'),
                         [], 'GenusEditorView not deleted')

    def test_can_use_epithet_field(self):
        family = Family(epithet='family')
        genus = Genus(family=family, genus='genus')
        self.session.add_all([family, genus])
        self.session.commit()
        g1 = self.session.query(Genus).filter(Genus.epithet=='genus').one()
        g2 = self.session.query(Genus).filter(Genus.genus=='genus').one()
        self.assertEqual(g1, g2)
        self.assertEqual(g1.genus, 'genus')
        self.assertEqual(g2.epithet, 'genus')

    def test_remove_callback_no_species_no_confirm(self):
        # T_0
        caricaceae = Family(family='Caricaceae')
        f5 = Genus(epithet='Carica', family=caricaceae)
        self.session.add(caricaceae)
        self.session.add(f5)
        self.session.flush()
        self.invoked = []

        # action
        orig_yes_no_dialog = utils.yes_no_dialog
        orig_message_details_dialog = utils.message_details_dialog
        utils.yes_no_dialog = partial(
            mockfunc, name='yes_no_dialog', caller=self, result=False)
        utils.message_details_dialog = partial(
            mockfunc, name='message_details_dialog', caller=self)
        from bauble.plugins.plants.genus import remove_callback
        result = remove_callback([f5])
        self.session.flush()

        # effect
        self.assertFalse('message_details_dialog' in
                         [f for (f, m) in self.invoked])
        self.assertTrue(('yes_no_dialog', 'Are you sure you want to '
                         'remove the following genera <i>Carica</i>?')
                        in self.invoked)
        self.assertEqual(result, False)
        q = self.session.query(Genus).filter_by(genus="Carica")
        matching = q.all()
        self.assertEqual(matching, [f5])
        utils.yes_no_dialog = orig_yes_no_dialog
        utils.message_details_dialog = orig_message_details_dialog

    def test_remove_callback_no_species_confirm(self):
        # T_0
        caricaceae = Family(family='Caricaceae')
        f5 = Genus(epithet='Carica', family=caricaceae)
        self.session.add_all([caricaceae, f5])
        self.session.flush()
        self.invoked = []

        # action
        orig_yes_no_dialog = utils.yes_no_dialog
        orig_message_details_dialog = utils.message_details_dialog
        utils.yes_no_dialog = partial(
            mockfunc, name='yes_no_dialog', caller=self, result=True)
        utils.message_details_dialog = partial(
            mockfunc, name='message_details_dialog', caller=self)
        from bauble.plugins.plants.genus import remove_callback
        result = remove_callback([f5])
        self.session.flush()

        # effect
        print(self.invoked)
        self.assertFalse('message_details_dialog' in
                         [f for (f, m) in self.invoked])
        self.assertTrue(('yes_no_dialog', 'Are you sure you want to '
                         'remove the following genera <i>Carica</i>?')
                        in self.invoked)

        self.assertEqual(result, True)
        q = self.session.query(Genus).filter_by(genus="Carica")
        matching = q.all()
        self.assertEqual(matching, [])
        utils.yes_no_dialog = orig_yes_no_dialog
        utils.message_details_dialog = orig_message_details_dialog

    def test_remove_callback_with_species_cant_cascade(self):
        # T_0
        caricaceae = Family(family='Caricaceae')
        f5 = Genus(epithet='Carica', family=caricaceae)
        gf5 = Species(genus=f5, sp='papaya')
        self.session.add_all([caricaceae, f5, gf5])
        self.session.flush()
        self.invoked = []

        # action
        orig_yes_no_dialog = utils.yes_no_dialog
        orig_message_dialog = utils.message_dialog
        orig_message_details_dialog = utils.message_details_dialog
        utils.yes_no_dialog = partial(
            mockfunc, name='yes_no_dialog', caller=self, result=True)
        utils.message_dialog = partial(
            mockfunc, name='message_dialog', caller=self, result=True)
        utils.message_details_dialog = partial(
            mockfunc, name='message_details_dialog', caller=self)
        from bauble.plugins.plants.genus import remove_callback
        result = remove_callback([f5])
        self.session.flush()

        # effect
        print(self.invoked)
        self.assertFalse('message_details_dialog' in
                         [f for (f, m) in self.invoked])
        self.assertTrue(('message_dialog',
                         'The genus <i>Carica</i> has 1 species.\n\nYou '
                         'cannot remove a genus with species.')
                        in self.invoked)
        q = self.session.query(Genus).filter_by(genus="Carica")
        matching = q.all()
        self.assertEqual(matching, [f5])
        q = self.session.query(Species).filter_by(sp="papaya")
        matching = q.all()
        self.assertEqual(matching, [gf5])
        utils.yes_no_dialog = orig_yes_no_dialog
        utils.message_dialog = orig_message_dialog
        utils.message_details_dialog = orig_message_details_dialog

    def test_count_children_wo_plants(self):
        from ..garden import Accession
        fam = Family(family='Myrtaceae')
        gen = Genus(epithet='Syzygium', family=fam)
        sp = Species(epithet='australe', genus=gen)
        acc = Accession(species=sp, code='1')
        self.session.add_all([fam, gen, sp, acc])
        self.session.commit()

        self.assertEqual(gen.count_children(), 1)

    def test_count_children_w_plant_w_qty(self):
        from ..garden import Accession, Plant, Location
        fam = Family(family='Myrtaceae')
        gen = Genus(epithet='Syzygium', family=fam)
        sp = Species(epithet='australe', genus=gen)
        acc = Accession(species=sp, code='1')
        plant = Plant(accession=acc,
                      quantity=1,
                      location=Location(name='site', code='STE'),
                      code='1')
        self.session.add_all([fam, gen, sp, acc, plant])
        self.session.commit()

        self.assertEqual(gen.count_children(), 1)

    def test_count_children_w_plant_w_qty_exclude_inactive_set(self):
        # should be the same as if exclude inactive not set.
        from ..garden import Accession, Plant, Location
        fam = Family(family='Myrtaceae')
        gen = Genus(epithet='Syzygium', family=fam)
        sp = Species(epithet='australe', genus=gen)
        acc = Accession(species=sp, code='1')
        plant = Plant(accession=acc,
                      quantity=1,
                      location=Location(name='site', code='STE'),
                      code='1')
        self.session.add_all([fam, gen, sp, acc, plant])
        self.session.commit()

        prefs.prefs[prefs.exclude_inactive_pref] = True

        self.assertEqual(gen.count_children(), 1)

    def test_count_children_w_plant_wo_qty(self):
        from ..garden import Accession, Plant, Location
        fam = Family(family='Myrtaceae')
        gen = Genus(epithet='Syzygium', family=fam)
        sp = Species(epithet='australe', genus=gen)
        acc = Accession(species=sp, code='1')
        plant = Plant(accession=acc,
                      quantity=0,
                      location=Location(name='site', code='STE'),
                      code='1')
        self.session.add_all([fam, gen, sp, acc, plant])
        self.session.commit()

        self.assertEqual(gen.count_children(), 1)

    def test_count_children_w_plant_wo_qty_exclude_inactive_set(self):
        from ..garden import Accession, Plant, Location
        fam = Family(family='Myrtaceae')
        gen = Genus(epithet='Syzygium', family=fam)
        sp = Species(epithet='australe', genus=gen)
        acc = Accession(species=sp, code='1')
        plant = Plant(accession=acc,
                      quantity=0,
                      location=Location(name='site', code='STE'),
                      code='1')
        self.session.add_all([fam, gen, sp, acc, plant])
        self.session.commit()

        prefs.prefs[prefs.exclude_inactive_pref] = True

        self.assertEqual(gen.count_children(), 0)

    def test_top_level_count_w_plant_qty(self):
        from ..garden import Accession, Plant, Location
        fam = Family(family='Myrtaceae')
        gen = Genus(epithet='Syzygium', family=fam)
        sp = Species(epithet='australe', genus=gen)
        acc = Accession(species=sp, code='1')
        plant = Plant(accession=acc,
                      quantity=1,
                      location=Location(name='site', code='STE'),
                      code='1')
        self.session.add_all([fam, gen, sp, acc, plant])
        self.session.commit()
        self.assertEqual(len(gen.top_level_count()[(1, 'Genera')]), 1)
        self.assertEqual(len(gen.top_level_count()[(2, 'Families')]), 1)
        self.assertEqual(gen.top_level_count()[(3, 'Species')], 1)
        self.assertEqual(gen.top_level_count()[(4, 'Accessions')], 1)
        self.assertEqual(gen.top_level_count()[(5, 'Plantings')], 1)
        self.assertEqual(gen.top_level_count()[(6, 'Living plants')], 1)
        self.assertEqual(len(gen.top_level_count()[(7, 'Locations')]), 1)
        self.assertEqual(len(gen.top_level_count()[(8, 'Sources')]), 0)

    def test_top_level_count_wo_plant_qty(self):
        from ..garden import Accession, Plant, Location
        fam = Family(family='Myrtaceae')
        gen = Genus(epithet='Syzygium', family=fam)
        sp = Species(epithet='australe', genus=gen)
        acc = Accession(species=sp, code='1')
        plant = Plant(accession=acc,
                      quantity=0,
                      location=Location(name='site', code='STE'),
                      code='1')
        self.session.add_all([fam, gen, sp, acc, plant])
        self.session.commit()
        self.assertEqual(len(gen.top_level_count()[(1, 'Genera')]), 1)
        self.assertEqual(len(gen.top_level_count()[(2, 'Families')]), 1)
        self.assertEqual(gen.top_level_count()[(3, 'Species')], 1)
        self.assertEqual(gen.top_level_count()[(4, 'Accessions')], 1)
        self.assertEqual(gen.top_level_count()[(5, 'Plantings')], 1)
        self.assertEqual(gen.top_level_count()[(6, 'Living plants')], 0)
        self.assertEqual(len(gen.top_level_count()[(7, 'Locations')]), 1)
        self.assertEqual(len(gen.top_level_count()[(8, 'Sources')]), 0)

    def test_top_level_count_wo_plant_qty_exclude_inactive_set(self):
        from ..garden import Accession, Plant, Location
        fam = Family(family='Myrtaceae')
        gen = Genus(epithet='Syzygium', family=fam)
        sp = Species(epithet='australe', genus=gen)
        acc = Accession(species=sp, code='1')
        plant = Plant(accession=acc,
                      quantity=0,
                      location=Location(name='site', code='STE'),
                      code='1')
        self.session.add_all([fam, gen, sp, acc, plant])
        self.session.commit()
        prefs.prefs[prefs.exclude_inactive_pref] = True
        self.assertEqual(len(gen.top_level_count()[(1, 'Genera')]), 1)
        self.assertEqual(len(gen.top_level_count()[(2, 'Families')]), 1)
        self.assertEqual(gen.top_level_count()[(3, 'Species')], 0)
        self.assertEqual(gen.top_level_count()[(4, 'Accessions')], 0)
        self.assertEqual(gen.top_level_count()[(5, 'Plantings')], 0)
        self.assertEqual(gen.top_level_count()[(6, 'Living plants')], 0)
        self.assertEqual(len(gen.top_level_count()[(7, 'Locations')]), 0)
        self.assertEqual(len(gen.top_level_count()[(8, 'Sources')]), 0)



class GenusSynonymyTests(PlantTestCase):

    def setUp(self):
        super().setUp()
        f = self.session.query(Family).filter(Family.family == 'Orchidaceae'
                                              ).one()
        bu = Genus(family=f, genus='Bulbophyllum')  # accepted
        zy = Genus(family=f, genus='Zygoglossum')  # synonym
        bu.synonyms.append(zy)
        self.session.add_all([f, bu, zy])
        self.session.commit()

    def test_forward_synonyms(self):
        "a taxon has a list of synonyms"
        bu = self.session.query(
            Genus).filter(
            Genus.genus == 'Bulbophyllum').one()
        zy = self.session.query(
            Genus).filter(
            Genus.genus == 'Zygoglossum').one()
        self.assertEqual(bu.synonyms, [zy])
        self.assertEqual(zy.synonyms, [])

    def test_backward_synonyms(self):
        "synonymy is used to get the accepted taxon"
        bu = self.session.query(
            Genus).filter(
            Genus.genus == 'Bulbophyllum').one()
        zy = self.session.query(
            Genus).filter(
            Genus.genus == 'Zygoglossum').one()
        self.assertEqual(zy.accepted, bu)
        self.assertEqual(bu.accepted, None)

    def test_synonymy_included_in_as_dict(self):
        bu = self.session.query(
            Genus).filter(
            Genus.genus == 'Bulbophyllum').one()
        zy = self.session.query(
            Genus).filter(
            Genus.genus == 'Zygoglossum').one()
        self.assertTrue('accepted' not in bu.as_dict())
        self.assertTrue('accepted' in zy.as_dict())
        self.assertEqual(zy.as_dict()['accepted'],
                          bu.as_dict(recurse=False))

    def test_define_accepted(self):
        # notice that same test should be also in Species and Family
        bu = self.session.query(
            Genus).filter(
            Genus.genus == 'Bulbophyllum').one()
        f = self.session.query(
            Family).filter(
            Family.family == 'Orchidaceae').one()
        he = Genus(family=f, genus='Henosis')  # one more synonym
        self.session.add(he)
        self.session.commit()
        self.assertEqual(len(bu.synonyms), 1)
        self.assertFalse(he in bu.synonyms)
        he.accepted = bu
        self.assertEqual(len(bu.synonyms), 2)
        self.assertTrue(he in bu.synonyms)

    def test_can_redefine_accepted(self):
        # Altamiranoa Rose used to refer to Villadia Rose for its accepted
        # name, it is now updated to Sedum L.

        # T_0
        claceae = Family(family='Crassulaceae')  # J. St.-Hil.
        villa = Genus(family=claceae, genus='Villadia', author='Rose')
        alta = Genus(family=claceae, genus='Altamiranoa', author='Rose')
        alta.accepted = villa
        self.session.add_all([claceae, alta, villa])
        self.session.commit()

        sedum = Genus(family=claceae, genus='Sedum', author='L.')
        alta.accepted = sedum
        self.session.commit()

    def test_no_synonyms_means_itself_accepted(self):
        def create_tmp_gen(id):
            gen = Genus(id=id, epithet="gen%02d" % id, family_id=1)
            self.session.add(gen)
            return gen

        gen1 = create_tmp_gen(51)
        self.session.commit()
        self.assertEqual(gen1.accepted, None)

    def test_synonyms_and_accepted_properties(self):
        def create_tmp_gen(id):
            gen = Genus(id=id, epithet="gen%02d" % id, family_id=1)
            self.session.add(gen)
            return gen

        # equivalence classes after changes
        gen1 = create_tmp_gen(41)
        gen2 = create_tmp_gen(42)
        gen3 = create_tmp_gen(43)
        gen4 = create_tmp_gen(44)  # (1), (2), (3), (4)
        gen3.accepted = gen1  # (1 3), (2), (4)
        self.assertEqual([i.epithet for i in gen1.synonyms], [gen3.epithet])
        gen1.synonyms.append(gen2)  # (1 3 2), (4)
        self.session.flush()
        self.assertEqual(gen2.accepted.epithet, gen1.epithet)  # just added
        self.assertEqual(gen3.accepted.epithet, gen1.epithet)  # no change
        gen2.accepted = gen4  # (1 3), (4 2)
        self.session.flush()
        self.assertEqual([i.epithet for i in gen4.synonyms], [gen2.epithet])
        self.assertEqual([i.epithet for i in gen1.synonyms], [gen3.epithet])
        self.assertEqual(gen1.accepted, None)
        self.assertEqual(gen2.accepted, gen4)
        self.assertEqual(gen3.accepted, gen1)
        self.assertEqual(gen4.accepted, None)
        gen2.accepted = gen4  # does not change anything
        self.assertEqual(gen1.accepted, None)
        self.assertEqual(gen2.accepted, gen4)
        self.assertEqual(gen3.accepted, gen1)
        self.assertEqual(gen4.accepted, None)
        gen2.accepted = gen2  # cannot be a synonym of itself
        self.assertRaises(IntegrityError, self.session.commit)


class SpeciesTests(PlantTestCase):

    def test_str(self):
        """
        Test the Species.str() method
        """
        def get_sp_str(id, **kwargs):
            return self.session.query(Species).get(id).str(**kwargs)

        for sid, expect in species_str_map.items():
            sp = self.session.query(Species).get(sid)
            printable_name = remove_zws("%s" % sp)
            self.assertEqual(species_str_map[sid], printable_name)
            spstr = get_sp_str(sid)
            self.assertEqual(remove_zws(spstr), expect)

        for sid, expect in species_str_authors_map.items():
            spstr = get_sp_str(sid, authors=True)
            self.assertEqual(remove_zws(spstr), expect)

        for sid, expect in species_markup_map.items():
            spstr = get_sp_str(sid, markup=True)
            self.assertEqual(remove_zws(spstr), expect)

        for sid, expect in species_markup_authors_map.items():
            spstr = get_sp_str(sid, markup=True, authors=True)
            self.assertEqual(remove_zws(spstr), expect)

        for sid, expect in species_searchview_markup_map.items():
            spstr = get_sp_str(sid,
                               markup=True,
                               authors=True,
                               for_search_view=True)
            self.assertEqual(remove_zws(spstr), expect)

    def test_lexicographic_order__unspecified_precedes_specified(self):
        def get_sp_str(id, **kwargs):
            return self.session.query(Species).get(id).str(**kwargs)

        self.assertTrue(get_sp_str(1) > get_sp_str(22))
        self.assertTrue(get_sp_str(1) > get_sp_str(23))
        self.assertTrue(get_sp_str(1) > get_sp_str(24))
        self.assertTrue(get_sp_str(16) > get_sp_str(22))
        self.assertTrue(get_sp_str(16) > get_sp_str(23))
        self.assertTrue(get_sp_str(16) > get_sp_str(24))

    # def test_dirty_string(self):
    #     """
    #     That that the cache on a string is invalidated if the species
    #     is changed or expired.
    #     """
    #     family = Family(family=u'family')
    #     genus = Genus(family=family, genus=u'genus')
    #     sp = Species(genus=genus, sp=u'sp')
    #     self.session.add_all([family, genus, sp])
    #     self.session.commit()

    #     str1 = Species.str(sp)
    #     sp.sp = u'sp2'
    #     self.session.commit()
    #     self.session.refresh(sp)
    #     sp = self.session.query(Species).get(sp.id)
    #     self.assert_(Species.str(sp) != str1)

    def test_vernacular_name(self):
        """
        Test the Species.vernacular_name property
        """
        family = Family(family='family')
        genus = Genus(family=family, genus='genus')
        sp = Species(genus=genus, sp='sp')
        self.session.add_all([family, genus, sp])
        self.session.commit()

        # add a name
        vn = VernacularName(name='name')
        sp.vernacular_names.append(vn)
        self.session.commit()
        self.assertTrue(vn in sp.vernacular_names)

        # test that removing a name removes deleted orphaned objects
        sp.vernacular_names.remove(vn)
        self.session.commit()
        q = self.session.query(VernacularName).filter_by(species_id=sp.id)
        self.assertRaises(NoResultFound, q.one)

    def test_default_vernacular_name(self):
        """
        Test the Species.default_vernacular_name property
        """
        family = Family(family='family')
        genus = Genus(family=family, genus='genus')
        sp = Species(genus=genus, sp='sp')
        vn = VernacularName(name='name')
        sp.vernacular_names.append(vn)
        self.session.add_all([family, genus, sp, vn])
        self.session.commit()

        # test that setting the default vernacular names
        default = VernacularName(name='default')
        sp.default_vernacular_name = default
        self.session.commit()
        self.assertTrue(vn in sp.vernacular_names)
        self.assertTrue(sp.default_vernacular_name == default)

        # test that set_attr work on default vernacular name
        default = VernacularName(name='default2')
        setattr(sp, 'default_vernacular_name', default)
        self.session.commit()
        self.assertTrue(vn in sp.vernacular_names)
        self.assertTrue(default in sp.vernacular_names)
        self.assertTrue(sp.default_vernacular_name == default)

        # test that if you set the default_vernacular_name on a
        # species then it automatically adds it to vernacular_names
        default = VernacularName(name='default3')
        sp.default_vernacular_name = default
        self.session.commit()
        self.assertTrue(vn in sp.vernacular_names)
        self.assertTrue(default in sp.vernacular_names)
        self.assertTrue(sp.default_vernacular_name == default)

        # test that removing a vernacular name removes it from
        # default_vernacular_name, this test also effectively tests VNList
        dvid = int(sp._default_vernacular_name.id)
        sp.vernacular_names.remove(default)
        self.session.commit()
        self.assertEqual(sp.default_vernacular_name, None)
        q = self.session.query(DefaultVernacularName)
        self.assertRaises(NoResultFound, q.filter_by(species_id=sp.id).one)
        self.assertRaises(NoResultFound, q.filter_by(id=dvid).one)

        # test that setting default_vernacular_name to None
        # removes the name properly and deletes any orphaned objects
        sp.vernacular_names.append(vn)
        sp.default_vernacular_name = vn
        self.session.commit()
        dvid = sp._default_vernacular_name.id
        sp.default_vernacular_name = None
        self.session.commit()
        q = self.session.query(DefaultVernacularName)
        self.assertRaises(NoResultFound, q.filter_by(species_id=sp.id).one)
        self.assertRaises(NoResultFound, q.filter_by(id=dvid).one)

        # test that calling __del__ on a default vernacular name removes it
        sp.default_vernacular_name = vn
        self.session.commit()
        dvid = sp._default_vernacular_name.id
        del sp.default_vernacular_name
        self.session.commit()
        self.assertEqual(sp.default_vernacular_name, None)
        q = self.session.query(DefaultVernacularName)
        self.assertRaises(NoResultFound, q.filter_by(species_id=sp.id).one)
        self.assertRaises(NoResultFound, q.filter_by(id=dvid).one)

        # test for regression in bug Launchpad #123286
        vn1 = VernacularName(name='vn1')
        vn2 = VernacularName(name='vn2')
        sp.default_vernacular_name = vn1
        sp.default_vernacular_name = vn2
        self.session.commit()

        # test hybrid property setter and expression
        q = self.session.query(Species).filter(
            Species.default_vernacular_name == 'vn2').one()
        self.assertEqual(q, sp)
        sp.default_vernacular_name = 'hybrid set'
        self.session.commit()
        self.assertEqual(sp.default_vernacular_name.name, 'hybrid set')
        self.assertIsNone(sp.default_vernacular_name.language)
        # Test the language is added
        sp.default_vernacular_name = 'set hybrid:Lang'
        self.session.commit()
        self.assertEqual(sp.default_vernacular_name.name, 'set hybrid')
        self.assertEqual(sp.default_vernacular_name.language, 'Lang')

    def test_accepted_low_level(self):
        sp1 = self.session.query(Species).get(2)
        sp2 = self.session.query(Species).get(3)
        sp3 = self.session.query(Species).get(4)
        sp1.accepted = sp2
        self.session.commit()
        self.assertEqual(sp1.accepted, sp2)
        self.assertIn(sp1, sp2.synonyms)
        sp1.accepted = sp3
        self.session.commit()
        self.assertEqual(sp1.accepted, sp3)
        self.assertIn(sp1, sp3.synonyms)
        self.assertNotIn(sp1, sp2.synonyms)
        sp1.accepted = sp1
        self.assertRaises(IntegrityError, self.session.commit)
        self.session.rollback()
        self.assertNotIn(sp1, sp1.synonyms)
        self.assertEqual(sp1.accepted, sp3)
        sp1.accepted = None
        self.session.commit()
        self.assertIsNone(sp1.accepted)
        self.assertNotIn(sp1, sp3.synonyms)

    def test_synonyms_low_level(self):
        """
        Test the Species.synonyms property
        """
        load_sp = lambda id: self.session.query(Species).get(id)

        def syn_str(id1, id2, isit='not'):
            sp1 = load_sp(id1)
            sp2 = load_sp(id2)
            return '%s(%s).synonyms: %s' % \
                   (sp1, sp1.id,
                    str(['%s(%s)' %
                            (s, s.id) for s in sp1.synonyms]))

        def synonym_of(id1, id2):
            sp1 = load_sp(id1)
            sp2 = load_sp(id2)
            return sp2 in sp1.synonyms

        # test that appending a synonym works using species.synonyms
        sp1 = load_sp(1)
        sp2 = load_sp(2)
        sp1.synonyms.append(sp2)
        self.session.flush()
        self.assertTrue(synonym_of(1, 2), syn_str(1, 2))

        # test that removing a synonyms works using species.synonyms
        sp1.synonyms.remove(sp2)
        self.session.flush()
        self.assertFalse(synonym_of(1, 2), syn_str(1, 2))

        self.session.expunge_all()

        # test that appending a synonym works using species._synonyms
        sp1 = load_sp(1)
        sp2 = load_sp(2)
        syn = SpeciesSynonym(synonym=sp2)
        sp1._synonyms.append(syn)
        self.session.flush()
        self.assertTrue(synonym_of(1, 2), syn_str(1, 2))

        # test that removing a synonyms works using species._synonyms
        sp1._synonyms.remove(syn)
        self.session.flush()
        self.assertFalse(synonym_of(1, 2), syn_str(1, 2))

        # test adding a species and then immediately remove it
        self.session.expunge_all()
        sp1 = load_sp(1)
        sp2 = load_sp(2)
        sp1.synonyms.append(sp2)
        sp1.synonyms.remove(sp2)
        import warnings
        # SAWarning: Object of type <SpeciesSynonym> not in session, add
        # operation along 'Species._accepted' will not proceed
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            self.session.commit()
        assert sp2 not in sp1.synonyms

        # add a species and immediately add the same species
        sp2 = load_sp(2)
        sp1.synonyms.append(sp2)
        sp1.synonyms.remove(sp2)
        sp1.synonyms.append(sp2)
        #self.session.flush() # shouldn't raise an error
        self.session.commit()
        assert sp2 in sp1.synonyms

        # test that deleting a species removes it from the synonyms list
        assert sp2 in sp1.synonyms
        self.session.delete(sp2)
        self.session.commit()
        assert sp2 not in sp1.synonyms
        # but doesn't delete the species it referes to.
        self.assertTrue(self.session.query(Species).get(sp1.id))

        # test that deleting a species that has synonyms deletes all
        # the synonyms that refer to that species
        sp3 = Species(genus=self.session.query(Genus).get(1), epithet='three')
        self.session.add(sp3)
        sp1.synonyms.append(sp3)
        self.session.commit()
        self.session.delete(sp1)
        self.session.commit()
        self.assertTrue(self.session.query(SpeciesSynonym).count() == 0)

    def test_no_synonyms_means_itself_accepted(self):
        def create_tmp_sp(id):
            sp = Species(id=id, epithet="sp%02d"%id, genus_id=1)
            self.session.add(sp)
            return sp

        sp1 = create_tmp_sp(51)
        sp2 = create_tmp_sp(52)
        sp3 = create_tmp_sp(53)
        sp4 = create_tmp_sp(54)
        self.session.commit()
        self.assertEqual(sp1.accepted, None)
        self.assertEqual(sp2.accepted, None)
        self.assertEqual(sp3.accepted, None)
        self.assertEqual(sp4.accepted, None)

    def test_synonyms_and_accepted_properties(self):
        def create_tmp_sp(id):
            sp = Species(id=id, epithet="sp%02d"%id, genus_id=1)
            self.session.add(sp)
            return sp

        # equivalence classes after changes
        sp1 = create_tmp_sp(41)
        sp2 = create_tmp_sp(42)
        sp3 = create_tmp_sp(43)
        sp4 = create_tmp_sp(44)  # (1), (2), (3), (4)
        sp3.accepted = sp1  # (1 3), (2), (4)
        self.assertEqual([i.epithet for i in sp1.synonyms], [sp3.epithet])
        sp1.synonyms.append(sp2)  # (1 3 2), (4)
        self.session.flush()
        print('synonyms of 1', [i.epithet[-1] for i in sp1.synonyms])
        print('synonyms of 4', [i.epithet[-1] for i in sp4.synonyms])
        self.assertEqual(sp2.accepted.epithet, sp1.epithet)  # just added
        self.assertEqual(sp3.accepted.epithet, sp1.epithet)  # no change
        sp2.accepted = sp4  # (1 3), (4 2)
        self.session.flush()
        print('synonyms of 1', [i.epithet[-1] for i in sp1.synonyms])
        print('synonyms of 4', [i.epithet[-1] for i in sp4.synonyms])
        self.assertEqual([i.epithet for i in sp4.synonyms], [sp2.epithet])
        self.assertEqual([i.epithet for i in sp1.synonyms], [sp3.epithet])
        self.assertEqual(sp1.accepted, None)
        self.assertEqual(sp2.accepted, sp4)
        self.assertEqual(sp3.accepted, sp1)
        self.assertEqual(sp4.accepted, None)
        sp2.accepted = sp4  # does not change anything
        self.assertEqual(sp1.accepted, None)
        self.assertEqual(sp2.accepted, sp4)
        self.assertEqual(sp3.accepted, sp1)
        self.assertEqual(sp4.accepted, None)

    def test_remove_callback_no_accessions_no_confirm(self):
        # T_0
        caricaceae = Family(family='Caricaceae')
        f5 = Genus(epithet='Carica', family=caricaceae)
        sp = Species(epithet='papaya', genus=f5)
        self.session.add_all([caricaceae, f5, sp])
        self.session.flush()
        self.invoked = []

        # action
        orig_yes_no_dialog = utils.yes_no_dialog
        orig_message_details_dialog = utils.message_details_dialog
        utils.yes_no_dialog = partial(
            mockfunc, name='yes_no_dialog', caller=self, result=False)
        utils.message_details_dialog = partial(
            mockfunc, name='message_details_dialog', caller=self)
        from bauble.plugins.plants.species import remove_callback
        result = remove_callback([sp])
        self.session.flush()

        # effect
        self.assertFalse('message_details_dialog' in
                         [f for (f, m) in self.invoked])
        print(self.invoked)
        self.assertTrue(('yes_no_dialog', 'Are you sure you want to remove '
                         'the following species <i>Carica papaya</i>?')
                        in self.invoked)
        self.assertEqual(result, False)
        q = self.session.query(Species).filter_by(genus=f5, sp="papaya")
        matching = q.all()
        self.assertEqual(matching, [sp])
        utils.yes_no_dialog = orig_yes_no_dialog
        utils.message_details_dialog = orig_message_details_dialog

    def test_remove_callback_no_accessions_confirm(self):
        # T_0
        caricaceae = Family(family='Caricaceae')
        f5 = Genus(epithet='Carica', family=caricaceae)
        sp = Species(epithet='papaya', genus=f5)
        self.session.add_all([caricaceae, f5, sp])
        self.session.flush()
        self.invoked = []

        # action
        orig_yes_no_dialog = utils.yes_no_dialog
        orig_message_details_dialog = utils.message_details_dialog
        utils.yes_no_dialog = partial(
            mockfunc, name='yes_no_dialog', caller=self, result=True)
        utils.message_details_dialog = partial(
            mockfunc, name='message_details_dialog', caller=self)
        from bauble.plugins.plants.species import remove_callback
        result = remove_callback([sp])
        self.session.flush()

        # effect
        print(self.invoked)
        self.assertFalse('message_details_dialog' in
                         [f for (f, m) in self.invoked])
        self.assertTrue(('yes_no_dialog', 'Are you sure you want to remove '
                         'the following species <i>Carica papaya</i>?')
                        in self.invoked)

        self.assertEqual(result, True)
        q = self.session.query(Species).filter_by(sp="Carica")
        matching = q.all()
        self.assertEqual(matching, [])
        utils.yes_no_dialog = orig_yes_no_dialog
        utils.message_details_dialog = orig_message_details_dialog

    def test_remove_callback_with_accessions_cant_cascade(self):
        # T_0
        caricaceae = Family(family='Caricaceae')
        f5 = Genus(epithet='Carica', family=caricaceae)
        sp = Species(epithet='papaya', genus=f5)
        from bauble.plugins.garden import (Accession)
        acc = Accession(code='0123456', species=sp)
        self.session.add_all([caricaceae, f5, sp, acc])
        self.session.flush()
        self.invoked = []

        # action
        orig_yes_no_dialog = utils.yes_no_dialog
        orig_message_dialog = utils.message_dialog
        orig_message_details_dialog = utils.message_details_dialog
        utils.yes_no_dialog = partial(
            mockfunc, name='yes_no_dialog', caller=self, result=True)
        utils.message_dialog = partial(
            mockfunc, name='message_dialog', caller=self, result=True)
        utils.message_details_dialog = partial(
            mockfunc, name='message_details_dialog', caller=self)
        from bauble.plugins.plants.species import remove_callback
        result = remove_callback([sp])
        self.session.flush()

        # effect
        print(self.invoked)
        self.assertFalse('message_details_dialog' in
                         [f for (f, m) in self.invoked])
        self.assertTrue(('message_dialog',
                         'The species <i>Carica papaya</i> has 1 accessions.'
                         '\n\nYou cannot remove a species with accessions.')
                        in self.invoked)
        q = self.session.query(Species).filter_by(genus=f5, sp="papaya")
        matching = q.all()
        self.assertEqual(matching, [sp])
        q = self.session.query(Accession).filter_by(species=sp)
        matching = q.all()
        self.assertEqual(matching, [acc])
        utils.yes_no_dialog = orig_yes_no_dialog
        utils.message_dialog = orig_message_dialog
        utils.message_details_dialog = orig_message_details_dialog

    def test_active_no_accessions(self):
        from ..garden.accession import Accession
        fam = Family(family='Myrtaceae')
        gen = Genus(epithet='Syzygium', family=fam)
        sp = Species(epithet='australe', genus=gen)
        self.session.add_all([fam, gen, sp])
        self.session.commit()
        self.assertTrue(sp.active)
        # test the hybrid_property expression
        # pylint: disable=no-member
        sp_active_in_db = (self.session.query(Species)
                           .filter(Species.active.is_(True)))
        self.assertIn(sp, sp_active_in_db)

    def test_active_no_plants(self):
        from ..garden.accession import Accession
        fam = Family(family='Myrtaceae')
        gen = Genus(epithet='Syzygium', family=fam)
        sp = Species(epithet='australe', genus=gen)
        acc = Accession(species=sp, code='1')
        self.session.add_all([fam, gen, sp, acc])
        self.session.commit()
        self.assertTrue(sp.active)
        # test the hybrid_property expression
        # pylint: disable=no-member
        sp_active_in_db = (self.session.query(Species)
                           .filter(Species.active.is_(True)))
        self.assertIn(sp, sp_active_in_db)

    def test_active_plants_w_qty(self):
        from ..garden import Accession, Plant, Location
        fam = Family(family='Myrtaceae')
        gen = Genus(epithet='Syzygium', family=fam)
        sp = Species(epithet='australe', genus=gen)
        acc = Accession(species=sp, code='1')
        plant = Plant(accession=acc,
                      quantity=1,
                      location=Location(name='site', code='STE'),
                      code='1')
        self.session.add_all([fam, gen, sp, acc, plant])
        self.session.commit()
        self.assertTrue(sp.active)
        # test the hybrid_property expression
        # pylint: disable=no-member
        sp_active_in_db = (self.session.query(Species)
                           .filter(Species.active.is_(True)))
        self.assertIn(sp, sp_active_in_db)

    def test_active_plants_wo_qty(self):
        from ..garden import Accession, Plant, Location
        fam = Family(family='Myrtaceae')
        gen = Genus(epithet='Syzygium', family=fam)
        sp = Species(epithet='australe', genus=gen)
        acc = Accession(species=sp, code='1')
        plant = Plant(accession=acc,
                      quantity=0,
                      location=Location(name='site', code='STE'),
                      code='1')
        self.session.add_all([fam, gen, sp, acc, plant])
        self.session.commit()
        self.assertFalse(sp.active)
        self.assertFalse(plant.active)
        # test the hybrid_property expression
        # pylint: disable=no-member
        sp_active_in_db = (self.session.query(Species)
                           .filter(Species.active.is_(True)))
        self.assertNotIn(sp, sp_active_in_db)

    def test_count_children_wo_plants(self):
        from ..garden import Accession
        fam = Family(family='Myrtaceae')
        gen = Genus(epithet='Syzygium', family=fam)
        sp = Species(epithet='australe', genus=gen)
        acc = Accession(species=sp, code='1')
        self.session.add_all([fam, gen, sp, acc])
        self.session.commit()

        self.assertEqual(sp.count_children(), 1)

    def test_count_children_w_plant_w_qty(self):
        from ..garden import Accession, Plant, Location
        fam = Family(family='Myrtaceae')
        gen = Genus(epithet='Syzygium', family=fam)
        sp = Species(epithet='australe', genus=gen)
        acc = Accession(species=sp, code='1')
        plant = Plant(accession=acc,
                      quantity=1,
                      location=Location(name='site', code='STE'),
                      code='1')
        self.session.add_all([fam, gen, sp, acc, plant])
        self.session.commit()

        self.assertEqual(sp.count_children(), 1)

    def test_count_children_w_plant_w_qty_exclude_inactive_set(self):
        # should be the same as if exclude inactive not set.
        from ..garden import Accession, Plant, Location
        fam = Family(family='Myrtaceae')
        gen = Genus(epithet='Syzygium', family=fam)
        sp = Species(epithet='australe', genus=gen)
        acc = Accession(species=sp, code='1')
        plant = Plant(accession=acc,
                      quantity=1,
                      location=Location(name='site', code='STE'),
                      code='1')
        self.session.add_all([fam, gen, sp, acc, plant])
        self.session.commit()

        prefs.prefs[prefs.exclude_inactive_pref] = True

        self.assertEqual(sp.count_children(), 1)

    def test_count_children_w_plant_wo_qty(self):
        from ..garden import Accession, Plant, Location
        fam = Family(family='Myrtaceae')
        gen = Genus(epithet='Syzygium', family=fam)
        sp = Species(epithet='australe', genus=gen)
        acc = Accession(species=sp, code='1')
        plant = Plant(accession=acc,
                      quantity=0,
                      location=Location(name='site', code='STE'),
                      code='1')
        self.session.add_all([fam, gen, sp, acc, plant])
        self.session.commit()

        self.assertEqual(sp.count_children(), 1)

    def test_count_children_w_plant_wo_qty_exclude_inactive_set(self):
        from ..garden import Accession, Plant, Location
        fam = Family(family='Myrtaceae')
        gen = Genus(epithet='Syzygium', family=fam)
        sp = Species(epithet='australe', genus=gen)
        acc = Accession(species=sp, code='1')
        plant = Plant(accession=acc,
                      quantity=0,
                      location=Location(name='site', code='STE'),
                      code='1')
        self.session.add_all([fam, gen, sp, acc, plant])
        self.session.commit()

        prefs.prefs[prefs.exclude_inactive_pref] = True

        self.assertEqual(sp.count_children(), 0)

    def test_top_level_count_w_plant_qty(self):
        from ..garden import Accession, Plant, Location
        fam = Family(family='Myrtaceae')
        gen = Genus(epithet='Syzygium', family=fam)
        sp = Species(epithet='australe', genus=gen)
        acc = Accession(species=sp, code='1')
        plant = Plant(accession=acc,
                      quantity=1,
                      location=Location(name='site', code='STE'),
                      code='1')
        self.session.add_all([fam, gen, sp, acc, plant])
        self.session.commit()
        self.assertEqual(sp.top_level_count()[(1, 'Species')], 1)
        self.assertEqual(len(sp.top_level_count()[(2, 'Genera')]), 1)
        self.assertEqual(len(sp.top_level_count()[(3, 'Families')]), 1)
        self.assertEqual(sp.top_level_count()[(4, 'Accessions')], 1)
        self.assertEqual(sp.top_level_count()[(5, 'Plantings')], 1)
        self.assertEqual(sp.top_level_count()[(6, 'Living plants')], 1)
        self.assertEqual(len(sp.top_level_count()[(7, 'Locations')]), 1)
        self.assertEqual(len(sp.top_level_count()[(8, 'Sources')]), 0)

    def test_top_level_count_wo_plant_qty(self):
        from ..garden import Accession, Plant, Location
        fam = Family(family='Myrtaceae')
        gen = Genus(epithet='Syzygium', family=fam)
        sp = Species(epithet='australe', genus=gen)
        acc = Accession(species=sp, code='1')
        plant = Plant(accession=acc,
                      quantity=0,
                      location=Location(name='site', code='STE'),
                      code='1')
        self.session.add_all([fam, gen, sp, acc, plant])
        self.session.commit()
        self.assertEqual(sp.top_level_count()[(1, 'Species')], 1)
        self.assertEqual(len(sp.top_level_count()[(2, 'Genera')]), 1)
        self.assertEqual(len(sp.top_level_count()[(3, 'Families')]), 1)
        self.assertEqual(sp.top_level_count()[(4, 'Accessions')], 1)
        self.assertEqual(sp.top_level_count()[(5, 'Plantings')], 1)
        self.assertEqual(sp.top_level_count()[(6, 'Living plants')], 0)
        self.assertEqual(len(sp.top_level_count()[(7, 'Locations')]), 1)
        self.assertEqual(len(sp.top_level_count()[(8, 'Sources')]), 0)

    def test_top_level_count_wo_plant_qty_exclude_inactive_set(self):
        from ..garden import Accession, Plant, Location
        fam = Family(family='Myrtaceae')
        gen = Genus(epithet='Syzygium', family=fam)
        sp = Species(epithet='australe', genus=gen)
        acc = Accession(species=sp, code='1')
        plant = Plant(accession=acc,
                      quantity=0,
                      location=Location(name='site', code='STE'),
                      code='1')
        self.session.add_all([fam, gen, sp, acc, plant])
        self.session.commit()
        prefs.prefs[prefs.exclude_inactive_pref] = True
        self.assertEqual(sp.top_level_count()[(1, 'Species')], 1)
        self.assertEqual(len(sp.top_level_count()[(2, 'Genera')]), 1)
        self.assertEqual(len(sp.top_level_count()[(3, 'Families')]), 1)
        self.assertEqual(sp.top_level_count()[(4, 'Accessions')], 0)
        self.assertEqual(sp.top_level_count()[(5, 'Plantings')], 0)
        self.assertEqual(sp.top_level_count()[(6, 'Living plants')], 0)
        self.assertEqual(len(sp.top_level_count()[(7, 'Locations')]), 0)
        self.assertEqual(len(sp.top_level_count()[(8, 'Sources')]), 0)


class GeographyTests(PlantTestCase):

    def __init__(self, *args):
        super().__init__(*args)

    def setUp(self):
        super().setUp()
        self.family = Family(family='family')
        self.genus = Genus(genus='genus', family=self.family)
        self.session.add_all([self.family, self.genus])
        self.session.flush()
        from bauble.task import queue
        queue(geography_importer())
        self.session.commit()

    def tearDown(self):
        super().tearDown()

    def test_get_species(self):
        mexico_id = 53
        mexico_central_id = 267
        oaxaca_id = 665
        northern_america_id = 7
        western_canada_id = 45

        # create a some species
        sp1 = Species(genus=self.genus, sp='sp1')
        dist = SpeciesDistribution(geography_id=mexico_central_id)
        sp1.distribution.append(dist)

        sp2 = Species(genus=self.genus, sp='sp2')
        dist = SpeciesDistribution(geography_id=oaxaca_id)
        sp2.distribution.append(dist)

        sp3 = Species(genus=self.genus, sp='sp3')
        dist = SpeciesDistribution(geography_id=western_canada_id)
        sp3.distribution.append(dist)

        self.session.commit()

        oaxaca = self.session.query(Geography).get(oaxaca_id)
        species = get_species_in_geography(oaxaca)
        self.assertTrue([s.id for s in species] == [sp2.id])

        mexico = self.session.query(Geography).get(mexico_id)
        species = get_species_in_geography(mexico)
        self.assertTrue([s.id for s in species] == [sp1.id, sp2.id])

        north_america = self.session.query(Geography).get(northern_america_id)
        species = get_species_in_geography(north_america)
        self.assertTrue([s.id for s in species] == [sp1.id, sp2.id, sp3.id])

    def test_species_distribution_str(self):
        # create a some species
        sp1 = Species(genus=self.genus, sp='sp1')
        dist = SpeciesDistribution(geography_id=267)
        sp1.distribution.append(dist)
        self.session.flush()
        self.assertEqual(sp1.distribution_str(), 'Mexico Central')
        dist = SpeciesDistribution(geography_id=45)
        sp1.distribution.append(dist)
        self.session.flush()
        self.assertEqual(sp1.distribution_str(), ('Mexico Central, '
                                                  'Western Canada'))


class FromAndToDictTest(PlantTestCase):
    """tests the retrieve_or_create and the as_dict methods
    """

    def test_can_grab_existing_families(self):
        all_families = self.session.query(Family).all()
        orc = Family.retrieve_or_create(
            self.session, {'rank': 'family',
                           'epithet': 'Orchidaceae'})
        leg = Family.retrieve_or_create(
            self.session, {'rank': 'family',
                           'epithet': 'Leguminosae'})
        pol = Family.retrieve_or_create(
            self.session, {'rank': 'family',
                           'epithet': 'Polypodiaceae'})
        sol = Family.retrieve_or_create(
            self.session, {'rank': 'family',
                           'epithet': 'Solanaceae'})
        ros = Family.retrieve_or_create(
            self.session, {'rank': 'family',
                           'epithet': 'Rosaceae'})
        are = Family.retrieve_or_create(
            self.session, {'rank': 'family',
                           'epithet': 'Arecaceae'})
        poa = Family.retrieve_or_create(
            self.session, {'rank': 'family',
                           'epithet': 'Poaceae'})
        self.assertEqual(set(all_families),
                         {orc, pol, leg, sol, ros, are, poa})

    def test_grabbing_same_params_same_output_existing(self):
        orc1 = Family.retrieve_or_create(
            self.session, {'rank': 'family',
                           'epithet': 'Orchidaceae'})
        orc2 = Family.retrieve_or_create(
            self.session, {'rank': 'family',
                           'epithet': 'Orchidaceae'})
        self.assertTrue(orc1 is orc2)

    def test_can_create_family(self):
        all_families = self.session.query(Family).all()
        fab = Family.retrieve_or_create(
            self.session, {'rank': 'family',
                           'epithet': 'Fabaceae'})
        # it's in the session, it wasn't there before.
        self.assertTrue(fab in self.session)
        self.assertFalse(fab in all_families)
        # according to the session, it is in the database
        ses_families = self.session.query(Family).all()
        self.assertTrue(fab in ses_families)

    @skip('not implimented')
    def test_where_can_object_be_found_before_commit(self):  # disabled
        fab = Family.retrieve_or_create(
            self.session, {'rank': 'family',
                           'epithet': 'Fabaceae'})
        # created in a session, it's not in other sessions
        other_session = db.Session()
        db_families = other_session.query(Family).all()
        fab = Family.retrieve_or_create(
            other_session, {'rank': 'family',
                            'epithet': 'Fabaceae'})
        self.assertFalse(fab in db_families)  # fails, why?

    def test_where_can_object_be_found_after_commit(self):
        fab = Family.retrieve_or_create(
            self.session, {'rank': 'family',
                           'epithet': 'Fabaceae'})
        # after commit it's in database.
        self.session.commit()
        other_session = db.Session()
        all_families = other_session.query(Family).all()
        fab = Family.retrieve_or_create(
            other_session, {'rank': 'family',
                            'epithet': 'Fabaceae'})
        self.assertTrue(fab in all_families)

    def test_grabbing_same_params_same_output_new(self):
        fab1 = Family.retrieve_or_create(
            self.session, {'rank': 'family',
                           'epithet': 'Fabaceae'})
        fab2 = Family.retrieve_or_create(
            self.session, {'rank': 'family',
                           'epithet': 'Fabaceae'})
        self.assertTrue(fab1 is fab2)

    def test_can_grab_existing_genera(self):
        orc = Family.retrieve_or_create(
            self.session, {'rank': 'family',
                           'epithet': 'Orchidaceae'})
        all_genera_orc = self.session.query(Genus).filter(
            Genus.family == orc).all()
        mxl = Genus.retrieve_or_create(
            self.session, {'ht-rank': 'family',
                           'ht-epithet': 'Orchidaceae',
                           'rank': 'genus',
                           'epithet': 'Maxillaria'})
        enc = Genus.retrieve_or_create(
            self.session, {'ht-rank': 'family',
                           'ht-epithet': 'Orchidaceae',
                           'rank': 'genus',
                           'epithet': 'Encyclia'})
        self.assertTrue(mxl in set(all_genera_orc))
        self.assertTrue(enc in set(all_genera_orc))


class FromAndToDict_create_update_test(PlantTestCase):
    "test the create and update fields in retrieve_or_create"

    def test_family_nocreate_noupdate_noexisting(self):
        # do not create if not existing
        obj = Family.retrieve_or_create(
            self.session, {'object': 'taxon',
                           'rank': 'familia',
                           'epithet': 'Araucariaceae'},
            create=False)
        self.assertEqual(obj, None)

    def test_family_nocreate_noupdateeq_existing(self):
        # retrieve same object, we only give the keys
        obj = Family.retrieve_or_create(
            self.session, {'object': 'taxon',
                           'rank': 'familia',
                           'epithet': 'Leguminosae'},
            create=False, update=False)
        self.assertTrue(obj is not None)
        self.assertEqual(obj.qualifier, 's. str.')

    def test_family_nocreate_noupdatediff_existing(self):
        # do not update object with new data
        obj = Family.retrieve_or_create(
            self.session, {'object': 'taxon',
                           'rank': 'familia',
                           'epithet': 'Leguminosae',
                           'qualifier': 's. lat.'},
            create=False, update=False)
        self.assertEqual(obj.qualifier, 's. str.')

    def test_family_nocreate_updatediff_existing(self):
        # update object in self.session
        obj = Family.retrieve_or_create(
            self.session, {'object': 'taxon',
                           'rank': 'familia',
                           'epithet': 'Leguminosae',
                           'qualifier': 's. lat.'},
            create=False, update=True)
        self.assertEqual(obj.qualifier, 's. lat.')

    def test_genus_nocreate_noupdate_noexisting_impossible(self):
        # do not create if not existing
        obj = Genus.retrieve_or_create(
            self.session, {'object': 'taxon',
                           'rank': 'genus',
                           'epithet': 'Masdevallia'},
            create=False)
        self.assertEqual(obj, None)

    def test_genus_create_noupdate_noexisting_impossible(self):
        # do not create if not existing
        obj = Genus.retrieve_or_create(
            self.session, {'object': 'taxon',
                           'rank': 'genus',
                           'epithet': 'Masdevallia'},
            create=True)
        self.assertEqual(obj, None)

    def test_genus_nocreate_noupdate_noexisting_possible(self):
        # do not create if not existing
        obj = Genus.retrieve_or_create(
            self.session, {'object': 'taxon',
                           'rank': 'genus',
                           'epithet': 'Masdevallia',
                           'ht-rank': 'familia',
                           'ht-epithet': 'Orchidaceae'},
            create=False)
        self.assertEqual(obj, None)

    def test_genus_nocreate_noupdateeq_existing(self):
        # retrieve same object, we only give the keys
        obj = Genus.retrieve_or_create(
            self.session, {'object': 'taxon',
                           'rank': 'genus',
                           'epithet': 'Maxillaria'},
            create=False, update=False)
        self.assertTrue(obj is not None)
        self.assertEqual(obj.author, '')

    def test_genus_nocreate_noupdatediff_existing(self):
        # do not update object with new data
        obj = Genus.retrieve_or_create(
            self.session, {'object': 'taxon',
                           'rank': 'genus',
                           'epithet': 'Maxillaria',
                           'author': 'Schltr.'},
            create=False, update=False)
        self.assertTrue(obj is not None)
        self.assertEqual(obj.author, '')

    def test_genus_nocreate_updatediff_existing(self):
        # update object in self.session
        obj = Genus.retrieve_or_create(
            self.session, {'object': 'taxon',
                           'rank': 'genus',
                           'epithet': 'Maxillaria',
                           'author': 'Schltr.'},
            create=False, update=True)
        self.assertTrue(obj is not None)
        self.assertEqual(obj.author, 'Schltr.')

    def test_vernacular_name_as_dict(self):
        bra = self.session.query(Species).filter(Species.id == 21).first()
        vn_bra = self.session.query(VernacularName).filter(
            VernacularName.language == 'agr',
            VernacularName.species == bra).all()
        self.assertEqual(vn_bra[0].as_dict(),
                          {'object': 'vernacular_name',
                           'name': 'Toé',
                           'language': 'agr',
                           'species': 'Brugmansia arborea'})
        vn_bra = self.session.query(VernacularName).filter(
            VernacularName.language == 'es',
            VernacularName.species == bra).all()
        self.assertEqual(vn_bra[0].as_dict(),
                          {'object': 'vernacular_name',
                           'name': 'Floripondio',
                           'language': 'es',
                           'species': 'Brugmansia arborea'})

    def test_vernacular_name_nocreate_noupdate_noexisting(self):
        # do not create if not existing
        obj = VernacularName.retrieve_or_create(
            self.session, {'object': 'vernacular_name',
                           'language': 'nap',
                           'species': 'Brugmansia arborea'},
            create=False)
        self.assertEqual(obj, None)

    def test_vernacular_name_nocreate_noupdateeq_existing(self):
        # retrieve same object, we only give the keys
        obj = VernacularName.retrieve_or_create(
            self.session, {'object': 'vernacular_name',
                           'language': 'agr',
                           'species': 'Brugmansia arborea'},
            create=False, update=False)
        self.assertTrue(obj is not None)
        self.assertEqual(obj.name, 'Toé')

    def test_vernacular_name_nocreate_noupdatediff_existing(self):
        # do not update object with new data
        obj = VernacularName.retrieve_or_create(
            self.session, {'object': 'vernacular_name',
                           'language': 'agr',
                           'name': 'wronge',
                           'species': 'Brugmansia arborea'},
            create=False, update=False)
        self.assertEqual(obj.name, 'Toé')

    def test_vernacular_name_nocreate_updatediff_existing(self):
        # update object in self.session
        obj = VernacularName.retrieve_or_create(
            self.session, {'object': 'vernacular_name',
                           'language': 'agr',
                           'name': 'wronge',
                           'species': 'Brugmansia arborea'},
            create=False, update=True)
        self.assertEqual(obj.name, 'wronge')


class CitesStatus_test(PlantTestCase):
    "we can retrieve the cites status as defined in family-genus-species"

    def test(self):
        obj = Genus.retrieve_or_create(
            self.session, {'object': 'taxon',
                           'rank': 'genus',
                           'epithet': 'Maxillaria'},
            create=False, update=False)
        self.assertEqual(obj.cites, 'II')
        obj = Genus.retrieve_or_create(
            self.session, {'object': 'taxon',
                           'rank': 'genus',
                           'epithet': 'Laelia'},
            create=False, update=False)
        self.assertEqual(obj.cites, 'II')
        obj = Species.retrieve_or_create(
            self.session, {'object': 'taxon',
                           'ht-rank': 'genus',
                           'ht-epithet': 'Paphiopedilum',
                           'rank': 'species',
                           'epithet': 'adductum'},
            create=False, update=False)
        self.assertEqual(obj.cites, 'I')
        obj = Species.retrieve_or_create(
            self.session, {'object': 'taxon',
                           'ht-rank': 'genus',
                           'ht-epithet': 'Laelia',
                           'rank': 'species',
                           'epithet': 'lobata'},
            create=False, update=False)
        self.assertEqual(obj.cites, 'I')
        obj = Species.retrieve_or_create(
            self.session, {'object': 'taxon',
                           'ht-rank': 'genus',
                           'ht-epithet': 'Laelia',
                           'rank': 'species',
                           'epithet': 'grandiflora'},
            create=False, update=False)
        self.assertEqual(obj.cites, 'II')


class SpeciesInfraspecificProp(PlantTestCase):

    def include_cinnamomum_camphora(self):
        '''\
Lauraceae,,Cinnamomum,,"camphora",,"","(L.) J.Presl"
Lauraceae,,Cinnamomum,,"camphora",f.,"linaloolifera","(Y.Fujita) Sugim."
Lauraceae,,Cinnamomum,,"camphora",var.,"nominale","Hats. & Hayata"
'''
        self.cinnamomum = Genus(family=Family(epithet='Lauraceae'),
                                epithet='Cinnamomum')
        self.cinnamomum_camphora = Species(genus=self.cinnamomum,
                                           epithet='camphora')
        self.session.add(self.cinnamomum_camphora)
        self.session.commit()

    def test_infraspecific_1(self):
        self.include_cinnamomum_camphora()
        obj = Species(genus=self.cinnamomum,
                      sp='camphora',
                      infrasp1_rank='f.',
                      infrasp1='linaloolifera',
                      infrasp1_author='(Y.Fujita) Sugim.')
        self.assertEqual(obj.infraspecific_rank, 'f.')
        self.assertEqual(obj.infraspecific_epithet, 'linaloolifera')
        self.assertEqual(obj.infraspecific_author, '(Y.Fujita) Sugim.')

    def test_infraspecific_2(self):
        self.include_cinnamomum_camphora()
        obj = Species(genus=self.cinnamomum,
                      sp='camphora',
                      infrasp2_rank='f.',
                      infrasp2='linaloolifera',
                      infrasp2_author='(Y.Fujita) Sugim.')
        self.assertEqual(obj.infraspecific_rank, 'f.')
        self.assertEqual(obj.infraspecific_epithet, 'linaloolifera')
        self.assertEqual(obj.infraspecific_author, '(Y.Fujita) Sugim.')

    def include_gleditsia_triacanthos(self):
        "Gleditsia triacanthos var. inermis 'Sunburst'."
        self.gleditsia = Genus(family=Family(epithet='Fabaceae'),
                               epithet='Gleditsia')
        self.gleditsia_triacanthos = Species(genus=self.gleditsia,
                                             epithet='triacanthos')
        self.session.add(self.gleditsia_triacanthos)
        self.session.commit()

    def test_variety_and_cultivar_1(self):
        self.include_gleditsia_triacanthos()
        obj = Species(genus=self.gleditsia,
                      sp='triacanthos',
                      infrasp1_rank='var.',
                      infrasp1='inermis',
                      cultivar_epithet='Sunburst')
        self.assertEqual(obj.infraspecific_rank, 'var.')
        self.assertEqual(obj.infraspecific_epithet, 'inermis')
        self.assertEqual(obj.infraspecific_author, '')
        self.assertEqual(obj.cultivar_epithet, 'Sunburst')

    def test_variety_and_cultivar_2(self):
        self.include_gleditsia_triacanthos()
        obj = Species(genus=self.gleditsia,
                      sp='triacanthos',
                      infrasp2_rank='var.',
                      infrasp2='inermis',
                      cultivar_epithet='Sunburst')
        self.assertEqual(obj.infraspecific_rank, 'var.')
        self.assertEqual(obj.infraspecific_epithet, 'inermis')
        self.assertEqual(obj.infraspecific_author, '')
        self.assertEqual(obj.cultivar_epithet, 'Sunburst')

    def test_infraspecific_props_is_lowest_ranked(self):
        """Saxifraga aizoon var. aizoon subvar. brevifolia f. multicaulis
        subf. surculosa"""
        genus = Genus(family=Family(epithet='Saxifragaceae'),
                      epithet='Saxifraga')
        subvar = Species(genus=genus,
                         sp='aizoon',
                         infrasp1_rank='var.',
                         infrasp1='aizoon',
                         infrasp2_rank='subvar.',
                         infrasp2='brevifolia',
                         )
        subf = Species(genus=genus,
                       sp='aizoon',
                       infrasp2_rank='var.',
                       infrasp2='aizoon',
                       infrasp1_rank='subvar.',
                       infrasp1='brevifolia',
                       infrasp3_rank='f.',
                       infrasp3='multicaulis',
                       infrasp4_rank='subf.',
                       infrasp4='surculosa',
                       )
        self.assertEqual(subvar.infraspecific_rank, 'subvar.')
        self.assertEqual(subvar.infraspecific_epithet, 'brevifolia')
        self.assertEqual(subvar.infraspecific_author, '')
        self.assertIsNone(subf.cultivar_epithet)
        self.assertEqual(subf.infraspecific_rank, 'subf.')
        self.assertEqual(subf.infraspecific_epithet, 'surculosa')
        self.assertEqual(subf.infraspecific_author, '')
        self.assertIsNone(subf.cultivar_epithet)
        # Saxifraga aizoon var. aizoon subvar. brevifolia f. multicaulis
        # cv. 'Bellissima'
        cv = Species(genus=genus,
                     sp='aizoon',
                     infrasp4_rank='var.',
                     infrasp4='aizoon',
                     infrasp1_rank='subvar.',
                     infrasp1='brevifolia',
                     infrasp3_rank='f.',
                     infrasp3='multicaulis',
                     cultivar_epithet='Bellissima',
                     )
        self.assertEqual(cv.infraspecific_rank, 'f.')
        self.assertEqual(cv.infraspecific_epithet, 'multicaulis')
        self.assertEqual(cv.infraspecific_author, '')
        self.assertEqual(cv.cultivar_epithet, 'Bellissima')

    def test_infraspecific_hybrid_properties(self):
        # NOTE some of this and similar test are no longer relevant
        family = Family(family='family')
        genus = Genus(family=family, genus='genus')
        sp = Species(genus=genus, sp='sp')
        # Check all parts end up where they should
        parts = "var. variety f. form"
        sp.infraspecific_parts = parts
        cul = "Cultivar In Parts"
        sp.cultivar_epithet = cul
        self.session.add_all([family, genus, sp])
        self.session.commit()
        # Make sure we cover the expression for each
        q = self.session.query(Species).filter_by(
            infraspecific_rank=parts.split()[-2]).one()
        self.assertEqual(sp, q)
        q = self.session.query(Species).filter_by(
            infraspecific_epithet=parts.split()[-1]).one()
        self.assertEqual(sp, q)
        q = self.session.query(Species).filter_by(
            cultivar_epithet=cul).one()
        self.assertEqual(sp, q)
        self.assertEqual(sp.infraspecific_parts, parts)
        self.assertEqual(sp.infrasp1_rank, parts.split()[0])
        self.assertEqual(sp.infrasp1, parts.split()[1])
        self.assertEqual(sp.infrasp2_rank, parts.split()[2])
        self.assertEqual(sp.infrasp2, parts.split()[3])
        self.assertEqual(sp.cultivar_epithet, cul)
        # test if we remove the infraspecific parts removes all parts
        sp.infraspecific_parts = None
        self.session.commit()
        self.assertIsNone(sp.infrasp1_rank)
        self.assertIsNone(sp.infrasp1)
        self.assertIsNone(sp.infrasp2_rank)
        self.assertIsNone(sp.infrasp2)
        self.assertIsNone(sp.infrasp3_rank)
        self.assertIsNone(sp.infrasp3)
        self.assertIsNone(sp.infrasp4_rank)
        self.assertIsNone(sp.infrasp4)

    def test_infraspecific_hybrid_properties_w_cv_rank_only(self):
        family = Family(family='family')
        genus = Genus(family=family, genus='genus')
        sp = Species(genus=genus, sp='sp')
        parts = "var. variety f. form"
        sp.infraspecific_parts = parts
        self.session.add_all([family, genus, sp])
        self.session.commit()
        # test 'cv.'
        cul = 'cv.'
        sp.cultivar_epithet = cul
        self.session.commit()
        self.assertEqual(sp.infraspecific_parts, parts)
        self.assertEqual(sp.infrasp1_rank, parts.split()[0])
        self.assertEqual(sp.infrasp1, parts.split()[1])
        self.assertEqual(sp.infrasp2_rank, parts.split()[2])
        self.assertEqual(sp.infrasp2, parts.split()[3])
        self.assertEqual(sp.cultivar_epithet, cul)
        self.assertIsNone(sp.infrasp3)
        # test removing parts leaves cv in correct place
        sp.infraspecific_parts = None
        self.session.commit()
        self.assertEqual(sp.cultivar_epithet, cul)

    def test_infraspecific_hybrid_properties_wo_cv(self):
        family = Family(family='family')
        genus = Genus(family=family, genus='genus')
        sp = Species(genus=genus, sp='sp')
        parts = "var. variety f. form"
        sp.infraspecific_parts = parts
        self.session.add_all([family, genus, sp])
        self.session.commit()
        self.assertEqual(sp.infraspecific_parts, parts)
        self.assertEqual(sp.infrasp1_rank, parts.split()[0])
        self.assertEqual(sp.infrasp1, parts.split()[1])
        self.assertEqual(sp.infrasp2_rank, parts.split()[2])
        self.assertEqual(sp.infrasp2, parts.split()[3])
        self.assertIsNone(sp.infrasp3_rank)
        # test if we remove the infraspecific parts everything is removed
        sp.infraspecific_parts = None
        self.session.commit()
        self.assertIsNone(sp.infrasp1_rank)
        self.assertIsNone(sp.infrasp1)
        self.assertIsNone(sp.infrasp2_rank)
        self.assertIsNone(sp.infrasp2)
        self.assertIsNone(sp.infrasp3_rank)
        self.assertIsNone(sp.infrasp3)
        self.assertIsNone(sp.infrasp4_rank)
        self.assertIsNone(sp.infrasp4)


class SpeciesProperties_test(PlantTestCase):
    "we can retrieve species_note objects given species and category"

    def test_species_note_nocreate_noupdate_noexisting(self):
        # do not create if not existing
        obj = SpeciesNote.retrieve_or_create(
            self.session, {'object': 'species_note',
                           'category': 'IUCN',
                           'species': 'Laelia grandiflora'},
            create=False)
        self.assertEqual(obj, None)

    def test_species_note_nocreate_noupdateeq_existing(self):
        # retrieve same object, we only give the keys
        obj = SpeciesNote.retrieve_or_create(
            self.session, {'object': 'species_note',
                           'category': 'IUCN',
                           'species': 'Encyclia fragrans'},
            create=False, update=False)
        self.assertTrue(obj is not None)
        self.assertEqual(obj.note, 'LC')

    def test_species_note_nocreate_noupdatediff_existing(self):
        # do not update object with new data
        obj = SpeciesNote.retrieve_or_create(
            self.session, {'object': 'species_note',
                           'category': 'IUCN',
                           'species': 'Encyclia fragrans',
                           'note': 'EX'},
            create=False, update=False)
        self.assertEqual(obj.note, 'LC')

    def test_species_note_nocreate_updatediff_existing(self):
        # update object in self.session
        obj = SpeciesNote.retrieve_or_create(
            self.session, {'object': 'species_note',
                           'category': 'IUCN',
                           'species': 'Encyclia fragrans',
                           'note': 'EX'},
            create=False, update=True)
        self.assertEqual(obj.note, 'EX')


class AttributesStoredInNotesTests(PlantTestCase):

    def setUp(self):
        super().setUp()
        self.obj = (self.session.query(Species)
                    .join(Genus)
                    .filter(Genus.epithet == 'Laelia')
                    .filter(Species.epithet == 'lobata')
                    .one())

    def test_proper_yaml_dictionary(self):
        note = SpeciesNote(category='<coords>', note='{1: 1, 2: 2}')
        note.species = self.obj
        self.session.commit()
        self.assertEqual(self.obj.coords, {'1': 1, '2': 2})

    def test_very_sloppy_json_dictionary(self):
        note = SpeciesNote(category='<coords>', note='lat:8.3,lon:-80.1')
        note.species = self.obj
        self.session.commit()
        self.assertEqual(self.obj.coords, {'lat': 8.3, 'lon': -80.1})

    def test_very_very_sloppy_json_dictionary(self):
        note = SpeciesNote(category='<coords>',
                           note='lat:8.3;lon:-80.1;alt:1400.0')
        note.species = self.obj
        self.session.commit()
        self.assertEqual(self.obj.coords,
                         {'lat': 8.3, 'lon': -80.1, 'alt': 1400.0})

    def test_atomic_value_interpreted(self):
        self.assertEqual(self.obj.price, 19.50)

    def test_atomic_value_verbatim(self):
        self.assertEqual(self.obj.price_tag, '$19.50')

    def test_list_value(self):
        self.assertEqual(self.obj.list_var, ['abc', 'def'])

    def test_dict_value(self):
        self.assertEqual(self.obj.dict_var,
                         {'k': 'abc', 'l': 'def', 'm': 'xyz'})


class ConservationStatus_test(PlantTestCase):
    "can retrieve the IUCN conservation status as defined in species"

    def test(self):
        obj = (self.session.query(Species)
               .join(Genus)
               .filter(Genus.epithet == 'Encyclia')
               .filter(Species.epithet == 'fragrans')
               .one())
        self.assertEqual(obj.conservation, 'LC')


class SpeciesEntryTests(TestCase):
    def test_spaces_not_allowed_on_init(self):
        entry = SpeciesEntry()
        self.assertFalse(entry.species_space)
        # like pasting
        string = 'test1 test2'
        entry.set_text(string)
        self.assertEqual(entry.get_text(), string.replace(' ', ''))

        # like typing
        self.assertEqual(entry.insert_text('s', 0), 1)
        self.assertEqual(entry.insert_text(' ', 1), 1)

    def test_dont_allow_capitalised(self):
        entry = SpeciesEntry()
        # like pasting
        entry.set_text('Test')
        self.assertEqual(entry.get_text(), 'test')

        # like typing at the start
        self.assertEqual(entry.insert_text('T', 0), 1)
        self.assertEqual(entry.get_text(), 'ttest')

    def test_allow_spaces_for_hybrids(self):
        entry = SpeciesEntry()
        # like pasting
        hybrid = 'test1 × test2'
        entry.set_text(hybrid)
        self.assertEqual(entry.get_text(), hybrid)

        # like typing
        self.assertEqual(entry.insert_text('*', len(hybrid)), len(hybrid) + 3)
        self.assertEqual(entry.get_text(), hybrid + ' × ')

    def test_allow_spaces_for_sp_nov(self):
        entry = SpeciesEntry()
        # like pasting
        nov = 'sp. nov.'
        entry.set_text(nov)
        self.assertEqual(entry.get_text(), nov)

        # like typing
        entry = SpeciesEntry()
        self.assertEqual(entry.insert_text('s', 0), 1)
        self.assertEqual(entry.insert_text('p', 1), 2)
        self.assertEqual(entry.insert_text('.', 2), 3)
        self.assertEqual(entry.insert_text(' ', 3), 4)
        self.assertEqual(entry.insert_text('n', 4), 5)
        self.assertEqual(entry.insert_text('o', 5), 6)
        self.assertEqual(entry.insert_text('v', 6), 7)
        self.assertEqual(entry.insert_text('.', 7), 8)
        self.assertEqual(entry.get_text(), nov)

    def test_allow_spaces_for_provisional(self):
        # very similar to above but tests that capitals remain
        entry = SpeciesEntry()
        # like pasting
        prov = 'sp. (Ormeau L.H.Bird AQ435851)'
        entry.set_text(prov)
        self.assertEqual(entry.get_text(), prov)

    def test_allow_spaces_for_descriptive(self):
        entry = SpeciesEntry()
        # like pasting
        prov = 'banksii (White Form)'
        entry.set_text(prov)
        self.assertEqual(entry.get_text(), prov)

        # like typing
        entry = SpeciesEntry()
        self.assertEqual(entry.insert_text('t', 0), 1)
        self.assertEqual(entry.insert_text('(', 1), 3)   # inserts space
        self.assertEqual(entry.insert_text('T', 3), 4)
        self.assertEqual(entry.get_text(), 't (T')


class SpeciesEditorTests(BaubleTestCase):

    @mock.patch('bauble.editor.GenericEditorView.start')
    def test_editor_doesnt_leak(self, mock_start):
        from gi.repository import Gtk
        mock_start.return_value = Gtk.ResponseType.OK
        from bauble import paths
        default_path = os.path.join(paths.lib_dir(), "plugins", "plants",
                                    "default")
        from bauble.plugins.imex.csv_ import CSVRestore
        importer = CSVRestore()
        importer.start([os.path.join(default_path, 'habit.csv')], force=True)
        from bauble.task import queue
        queue(geography_importer())

        fam = Family(family='family')
        gen2 = Genus(genus='genus2', family=fam)
        gen = Genus(genus='genus', family=fam)
        gen2.synonyms.append(gen)
        self.session.add(fam)
        self.session.commit()
        sp = Species(genus=gen, sp='sp')
        editor = SpeciesEditor(model=sp)
        # edit_species(model=Species(genus=gen, sp='sp'))
        update_gui()
        editor.start()
        del editor
        update_gui()
        self.assertEqual(utils.gc_objects_by_type('SpeciesEditor'), [])
        self.assertEqual(utils.gc_objects_by_type('SpeciesEditorPresenter'),
                         [])
        self.assertEqual(utils.gc_objects_by_type('SpeciesEditorView'), [])

    @mock.patch('bauble.utils.message_dialog')
    def test_start_bails_if_no_genera(self, mock_dialog):
        editor = SpeciesEditor(model=Species())
        update_gui()
        self.assertIsNone(editor.start())
        del editor
        update_gui()
        mock_dialog.assert_called()

    def test_commit_changes_removes_incomplete_vernacular_names(self):
        fam = Family(family='family')
        gen = Genus(genus='genus', family=fam)
        sp = Species(genus=gen, sp='sp')
        self.assertEqual(len(sp.vernacular_names), 0)
        vern = VernacularName(name='')
        sp.default_vernacular_name = vern
        self.session.add_all([gen, fam, sp, vern])
        self.session.commit()
        self.assertEqual(len(sp.vernacular_names), 1)

        editor = SpeciesEditor(model=sp)
        update_gui()
        editor.commit_changes()
        self.session.refresh(sp)
        self.assertEqual(len(sp.vernacular_names), 0)
        editor.presenter.cleanup()
        editor.session.close()
        del editor
        update_gui()

    def test_commit_changes_add_syn_chkbox_adds_previous_as_syn(self):
        fam = Family(family='family')
        gen = Genus(genus='genus', family=fam)
        sp = Species(genus=gen, sp='sp')
        self.session.add_all([gen, fam, sp])
        self.session.commit()

        editor = SpeciesEditor(model=sp)
        editor.presenter.view.widgets.sp_species_entry.set_text('species2')
        editor.presenter.view.widgets.add_syn_chkbox.set_active(True)
        update_gui()
        editor.commit_changes()
        self.session.refresh(sp)
        self.assertEqual(sp._synonyms[0].synonym.sp, 'sp')
        self.assertEqual(sp._synonyms[0].synonym.genus, gen)
        editor.presenter.cleanup()
        editor.session.close()
        del editor
        update_gui()

    @mock.patch('bauble.utils.yes_no_dialog')
    @mock.patch('bauble.editor.GenericEditorView.start')
    def test_handle_response_rolls_back_on_cancel(self, mock_start, mock_dlog):
        mock_dlog.return_value = True
        from gi.repository import Gtk
        mock_start.return_value = Gtk.ResponseType.CANCEL
        fam = Family(family='family')
        gen = Genus(genus='genus', family=fam)
        sp = Species(genus=gen, sp='sp')
        self.session.add(fam, sp)
        self.session.commit()
        editor = SpeciesEditor(model=sp)
        editor.presenter.view.widgets.sp_species_entry.set_text('species2')
        update_gui()
        committed = editor.start()
        self.assertEqual(len(committed), 0)
        self.session.expire_all()
        self.assertEqual(sp.sp, 'sp')

        del editor
        update_gui()
        self.assertEqual(utils.gc_objects_by_type('SpeciesEditor'), [])
        self.assertEqual(utils.gc_objects_by_type('SpeciesEditorPresenter'),
                         [])
        self.assertEqual(utils.gc_objects_by_type('SpeciesEditorView'), [])

    @mock.patch('bauble.editor.GenericEditorView.start')
    def test_handle_response_adds_to_committed(self, mock_start):
        # set the editor dirty then send the response and check it commits and
        # stores returns the model in _committed
        from gi.repository import Gtk
        mock_start.return_value = Gtk.ResponseType.OK
        fam = Family(family='family')
        gen = Genus(genus='genus', family=fam)
        sp = Species(genus=gen, sp='sp')
        self.session.add(fam, sp)
        self.session.commit()
        editor = SpeciesEditor(model=sp)
        editor.presenter.view.widgets.sp_species_entry.set_text('species2')
        update_gui()
        committed = editor.start()
        committed1 = self.session.merge(committed[0])
        self.assertEqual(len(committed), 1)
        self.session.expire_all()
        self.assertEqual(committed1.id, sp.id)

        del editor
        update_gui()
        self.assertEqual(utils.gc_objects_by_type('SpeciesEditor'), [])
        self.assertEqual(utils.gc_objects_by_type('SpeciesEditorPresenter'),
                         [])
        self.assertEqual(utils.gc_objects_by_type('SpeciesEditorView'), [])

    def test_genus_match_func(self):
        mock_completion = mock.Mock()
        mock_completion.get_model.return_value = [[Genus(epithet='Test')]]
        result = SpeciesEditorView.genus_match_func(mock_completion, 'Tes', 0)
        self.assertTrue(result)

        mock_completion.get_model.return_value = [[Genus(epithet='Test',
                                                         hybrid='+')]]
        result = SpeciesEditorView.genus_match_func(mock_completion, 'Tes', 0)
        self.assertTrue(result)

        result = SpeciesEditorView.genus_match_func(mock_completion, '+', 0)
        self.assertTrue(result)

        result = SpeciesEditorView.genus_match_func(mock_completion, 'tes', 0)
        self.assertTrue(result)

        result = SpeciesEditorView.genus_match_func(mock_completion, 'abc', 0)
        self.assertFalse(result)

    def test_genus_completion_cell_data_func(self):
        mock_renderer = mock.Mock()
        mock_model = [[
            Genus(epithet='Test', family=Family(epithet='Testaceae'))
        ]]

        SpeciesEditorView.genus_completion_cell_data_func(None,
                                                          mock_renderer,
                                                          mock_model,
                                                          0)
        mock_renderer.set_property.assert_called_with('text',
                                                      'Test (Testaceae)')


class SpeciesEditorPresenterTests(PlantTestCase):

    def test_gen_get_completions(self):
        sp = Species()
        self.session.add(sp)
        presenter = SpeciesEditorPresenter(sp, SpeciesEditorView())
        result = presenter.gen_get_completions('Cy')
        self.assertEqual([str(i) for i in result], ['Cynodon', 'Encyclia'])
        del presenter

    def test_sp_species_tpl_callback(self):
        fam = Family(family='Family')
        gen = Genus(genus='Genus', family=fam)
        sp = Species(genus=gen, sp='sp')
        self.session.add(sp)
        view = SpeciesEditorView()
        presenter = SpeciesEditorPresenter(sp, view)

        presenter.sp_species_tpl_callback(None, None)
        self.assertEqual([i.message for i in presenter.species_check_messages],
                         ['No match found on ThePlantList.org'])
        presenter.species_check_messages = []

        presenter.sp_species_tpl_callback({'Species': 'sp',
                                           'Authorship': None,
                                           'Species hybrid marker': None},
                                          None)
        self.assertEqual([i.message for i in presenter.species_check_messages],
                         ['your data finely matches ThePlantList.org'])
        presenter.species_check_messages = []

        presenter.sp_species_tpl_callback({'Family': 'Family',
                                           'Genus': 'Genus',
                                           'Species': 'better_name',
                                           'Authorship': None,
                                           'Species hybrid marker': None},
                                          None)
        self.assertEqual(len(presenter.species_check_messages), 1)
        self.assertIn('is the closest match for your data',
                      presenter.species_check_messages[0].message)
        self.assertIn('better_name',
                      presenter.species_check_messages[0].message)
        presenter.species_check_messages = []

        presenter.sp_species_tpl_callback({'Family': 'Family',
                                           'Genus': 'Genus',
                                           'Species': 'better_name',
                                           'Authorship': None,
                                           'Species hybrid marker': None},
                                          None)
        self.assertEqual(len(presenter.species_check_messages), 1)
        self.assertIn('is the closest match for your data',
                      presenter.species_check_messages[0].message)
        self.assertIn('better_name',
                      presenter.species_check_messages[0].message)
        presenter.species_check_messages = []

        presenter.sp_species_tpl_callback({'Family': 'Family',
                                           'Genus': 'Genus',
                                           'Species': 'better_name',
                                           'Authorship': None,
                                           'Species hybrid marker': None},
                                          {'Family': 'Family',
                                           'Genus': 'Genus',
                                           'Species': 'even_better_name',
                                           'Authorship': 'Somone',
                                           'Species hybrid marker': None})
        self.assertEqual(len(presenter.species_check_messages), 2)
        self.assertIn('is the closest match for your data',
                      presenter.species_check_messages[0].message)
        self.assertIn('better_name',
                      presenter.species_check_messages[0].message)
        self.assertIn('is the accepted taxon for your data',
                      presenter.species_check_messages[1].message)
        self.assertIn('even_better_name',
                      presenter.species_check_messages[1].message)
        presenter.species_check_messages = []

        del presenter

    @mock.patch('bauble.plugins.plants.ask_tpl.AskTPL')
    def test_on_species_button_clicked(self, mock_tpl):
        sp = Species()
        self.session.add(sp)
        view = SpeciesEditorView()
        presenter = SpeciesEditorPresenter(sp, view)
        presenter.on_sp_species_button_clicked(None)
        self.assertEqual(len(presenter.species_check_messages), 0)
        self.assertEqual(len(view.boxes), 1)
        self.assertIn('querying the plant list', list(view.boxes)[0].message)
        del presenter

    def test_on_expand_cv_button_clicked(self):
        sp = Species()
        self.session.add(sp)
        view = SpeciesEditorView()
        presenter = SpeciesEditorPresenter(sp, view)

        presenter.on_expand_cv_button_clicked()
        icon = view.widgets.expand_btn_icon.get_icon_name()[0]
        self.assertEqual('pan-start-symbolic', icon)
        self.assertTrue(view.widgets.cv_extras_grid.get_visible())

        presenter.on_expand_cv_button_clicked()
        icon = view.widgets.expand_btn_icon.get_icon_name()[0]
        self.assertEqual('pan-end-symbolic', icon)
        self.assertFalse(view.widgets.cv_extras_grid.get_visible())

        del presenter

    def test_on_entry_changed_clear_boxes(self):
        sp = Species()
        self.session.add(sp)
        view = SpeciesEditorView()
        presenter = SpeciesEditorPresenter(sp, view)
        box = view.add_message_box(utils.MESSAGE_BOX_INFO)
        presenter.species_check_messages.append(box)

        presenter.on_entry_changed_clear_boxes(None)
        self.assertEqual(len(presenter.species_check_messages), 0)

        del presenter

    def test_on_habit_entry_changed(self):
        # Also on_habit_comboentry_changed
        from bauble.plugins.imex.csv_ import CSVRestore
        importer = CSVRestore()
        from bauble import paths
        default_path = os.path.join(paths.lib_dir(), "plugins", "plants",
                                    "default")
        importer.start([os.path.join(default_path, 'habit.csv')], force=True)

        sp = Species()
        self.session.add(sp)
        view = SpeciesEditorView()
        presenter = SpeciesEditorPresenter(sp, view)

        combo = view.widgets.sp_habit_comboentry
        self.assertEqual(combo.get_active(), -1)

        from gi.repository import Gtk
        entry = Gtk.Entry()

        entry.set_text('Tre')
        presenter.on_habit_entry_changed(entry, combo)
        self.assertEqual(combo.get_active(), -1)

        entry.set_text('Tree (TRE)')
        presenter.on_habit_entry_changed(entry, combo)
        self.assertEqual(combo.get_active(), 34)

        del presenter

    def test_refresh_fullname_label(self):
        # toggles prev_sp_box visibility
        # sets sp_fullname_label to markup
        sp = (self.session.query(Species)
              .filter(Species.grex == 'Jim Kie',
                      Species.cultivar_epithet == 'Springwater')
              .first())
        view = SpeciesEditorView()
        presenter = SpeciesEditorPresenter(sp, view)

        sp.grex = 'Test Grex'  # should not trigger change on the label yet
        self.assertEqual(view.widgets.sp_fullname_label.get_label(),
                         "<i>Paphiopedilum</i> Jim Kie 'Springwater'")
        self.assertFalse(view.widgets.prev_sp_box.get_visible())

        presenter.refresh_fullname_label()
        self.assertEqual(view.widgets.sp_fullname_label.get_label(),
                         "<i>Paphiopedilum</i> Test Grex 'Springwater'")
        self.assertTrue(view.widgets.prev_sp_box.get_visible())

        del presenter

    def test_warn_double_ups(self):
        fam = Family(family='Family')
        gen = Genus(genus='Genus', family=fam)
        self.session.add_all([fam, gen])
        self.session.commit()
        sp = Species(genus=gen, sp='sp')
        self.session.add(sp)

        view = SpeciesEditorView()
        presenter = SpeciesEditorPresenter(sp, view)

        presenter._warn_double_ups()
        self.assertIsNone(presenter.omonym_box)

        maxillaria = (self.session.query(Genus)
                      .filter(Genus.genus == 'Maxillaria')
                      .first())
        sp.genus = maxillaria
        view.widget_set_value('sp_species_entry', 'variabilis')

        presenter._warn_double_ups()
        self.assertIsNotNone(presenter.omonym_box)

        del presenter


class InfraspPresenterTests(TestCase):
    def test_init_with_model_no_infras_doesnt_populate(self):
        mock_model = mock.Mock()
        mock_model.get_infrasp.return_value = (None, None, None)
        mock_parent = mock.Mock()
        mock_parent.view = mock.Mock()
        mock_parent.view.widgets.infrasp_grid.get_children.return_value = []
        mock_parent.model = mock_model
        presenter = InfraspPresenter(mock_parent)
        self.assertEqual(presenter.table_rows, [])
        del presenter

    def test_init_with_model_w_infras_does_populate(self):
        mock_model = mock.Mock()
        mock_model.get_infrasp = lambda x: (
            list(infrasp_rank_values.keys())[x],
            f'test{x}',
            None
        )
        mock_parent = mock.Mock()
        mock_parent.view = mock.Mock()
        mock_parent.view.widgets.infrasp_grid.get_children.return_value = [
            'fake_widget1', 'fake_widget2', 'fake_widget3'
        ]
        mock_parent.model = mock_model
        presenter = InfraspPresenter(mock_parent)
        mock_parent.view.widgets.remove_parent.assert_called()
        self.assertEqual(len(presenter.table_rows), 4)
        del presenter

    def test_clear_rows(self):
        mock_model = mock.Mock()
        mock_model.get_infrasp = lambda x: (
            list(infrasp_rank_values.keys())[x],
            f'test{x}',
            None
        ) if x < 5 else (None, None, None)
        mock_parent = mock.Mock()
        mock_parent.view = mock.Mock()
        mock_parent.view.widgets.infrasp_grid.get_children.return_value = []
        mock_parent.model = mock_model
        presenter = InfraspPresenter(mock_parent)
        self.assertEqual(len(presenter.table_rows), 4)
        presenter.clear_rows()
        self.assertEqual(len(presenter.table_rows), 0, presenter.table_rows)
        del presenter

    def test_infrarow_set_model_attr(self):
        mock_presenter = mock.Mock()
        mock_presenter.model = sp = Species()
        row = InfraspRow(mock_presenter, 1)
        row.set_model_attr('epithet', 'test')
        self.assertEqual(sp.infrasp1, 'test')
        self.assertTrue(mock_presenter._dirty)
        del row

    def test_infrarow_on_epithet_entry_changed(self):
        mock_presenter = mock.Mock()
        mock_presenter.model = sp = Species()
        row = InfraspRow(mock_presenter, 1)
        self.assertEqual(sp.infrasp1, None)
        mock_entry = mock.Mock()
        mock_entry.get_text.return_value = 'testname'
        row.on_epithet_entry_changed(mock_entry)
        self.assertEqual(sp.infrasp1, 'testname')
        self.assertTrue(mock_presenter._dirty)
        del row

    def test_infrarow_on_author_entry_changed(self):
        mock_presenter = mock.Mock()
        mock_presenter.model = sp = Species()
        row = InfraspRow(mock_presenter, 1)
        self.assertEqual(sp.infrasp1_author, None)
        mock_entry = mock.Mock()
        mock_entry.get_text.return_value = 'testname'
        row.on_author_entry_changed(mock_entry)
        self.assertEqual(sp.infrasp1_author, 'testname')
        self.assertTrue(mock_presenter._dirty)
        del row

    def test_infrarow_on_rank_combo_changed(self):
        mock_presenter = mock.Mock()
        mock_presenter.model = sp = Species()
        mock_presenter.table_rows = []
        row = InfraspRow(mock_presenter, 1)
        self.assertEqual(sp.infrasp1_rank, None)
        mock_combo = mock.Mock()
        mock_combo.get_model.return_value = [['var.']]
        mock_combo.get_active_iter.return_value = 0
        row.on_rank_combo_changed(mock_combo)
        self.assertEqual(sp.infrasp1_rank, 'var.')
        self.assertTrue(mock_presenter._dirty)
        del row

    def test_infrarow_on_remove_button_clicked(self):
        mock_model = mock.Mock()
        mock_model.get_infrasp = lambda x: (
            list(infrasp_rank_values.keys())[x],
            f'test{x}',
            None
        ) if x < 5 else (None, None, None)
        mock_parent = mock.Mock()
        mock_parent.view = mock.Mock()
        mock_parent.view.widgets.infrasp_grid.get_children.return_value = []
        mock_parent.model = mock_model
        presenter = InfraspPresenter(mock_parent)
        self.assertEqual(len(presenter.table_rows), 4)
        presenter.table_rows[0].on_remove_button_clicked(None)
        self.assertEqual(len(presenter.table_rows), 3)
        presenter.table_rows[0].on_remove_button_clicked(None)
        self.assertEqual(len(presenter.table_rows), 2)
        for i, row in enumerate(presenter.table_rows):
            self.assertEqual(row.level, i + 1)
        del presenter

    def test_refresh_rank_combo(self):
        mock_presenter = mock.Mock()
        mock_presenter.model = sp = Species(infrasp1_rank='var.')
        mock_presenter.table_rows = []
        row = InfraspRow(mock_presenter, 2)
        self.assertEqual(sp.infrasp1_rank, 'var.')
        sp.infrasp1_rank = 'f.'
        row.refresh_rank_combo()
        self.assertEqual(sp.infrasp1_rank, 'f.')
        mock_presenter.view.init_translatable_combo.assert_called()
        args = mock_presenter.view.init_translatable_combo.call_args.args
        self.assertEqual(args[1], {'subf.': 'subf.', None: ''}, args)
        self.assertTrue(mock_presenter._dirty)
        del row


class DistributionPresenterTests(PlantTestCase):

    def setUp(self):
        super().setUp()
        from bauble.task import queue
        queue(geography_importer())
        self.session.commit()

    def test_on_remove_button_pressed(self):
        qld = (self.session.query(Geography)
               .filter(Geography.tdwg_code == 'QLD')
               .one())
        nsw = (self.session.query(Geography)
               .filter(Geography.tdwg_code == 'NSW')
               .one())

        qld_dist = SpeciesDistribution(geography=qld)
        nsw_dist = SpeciesDistribution(geography=nsw)
        fam = Family(family='family')
        gen = Genus(genus='genus', family=fam)
        sp = Species(genus=gen, sp='sp')
        sp.distribution.append(qld_dist)
        sp.distribution.append(nsw_dist)
        self.session.add(sp)
        self.session.commit()

        mock_parent = mock.Mock()
        mock_parent.view = SpeciesEditorView()
        mock_parent.model = sp
        mock_parent.session = self.session

        presenter = DistributionPresenter(mock_parent)
        presenter.remove_menu_model = mock.Mock()
        presenter.remove_menu = mock.Mock()

        mock_event = mock.Mock(button=1, time=datetime.now().timestamp())
        presenter.on_remove_button_pressed(None, mock_event)

        self.assertEqual(presenter.remove_menu_model.append_item.call_count, 2)
        self.assertEqual(presenter.remove_menu.popup_at_pointer.call_count, 1)

        del presenter

    def test_on_activate_add_menu_item(self):
        qld = (self.session.query(Geography)
               .filter(Geography.tdwg_code == 'QLD')
               .one())

        fam = Family(family='family')
        gen = Genus(genus='genus', family=fam)
        sp = Species(genus=gen, sp='sp')
        self.session.add(sp)
        self.session.commit()

        mock_parent = mock.Mock()
        mock_parent.view = SpeciesEditorView()
        mock_parent.model = sp
        mock_parent.session = self.session

        presenter = DistributionPresenter(mock_parent)
        mock_geo = mock.Mock()
        mock_geo.unpack.return_value = qld.id
        presenter.on_activate_add_menu_item(None, mock_geo)
        self.assertEqual([dist.geography for dist in sp.distribution], [qld])

        del presenter

    def test_on_activate_remove_menu_item(self):
        qld = (self.session.query(Geography)
               .filter(Geography.tdwg_code == 'QLD')
               .one())
        nsw = (self.session.query(Geography)
               .filter(Geography.tdwg_code == 'NSW')
               .one())

        qld_dist = SpeciesDistribution(geography=qld)
        nsw_dist = SpeciesDistribution(geography=nsw)
        fam = Family(family='family')
        gen = Genus(genus='genus', family=fam)
        sp = Species(genus=gen, sp='sp')
        sp.distribution.append(qld_dist)
        sp.distribution.append(nsw_dist)
        self.session.add(sp)
        self.session.commit()

        mock_parent = mock.Mock()
        mock_parent.view = SpeciesEditorView()
        mock_parent.model = sp
        mock_parent.session = self.session

        presenter = DistributionPresenter(mock_parent)
        mock_geo = mock.Mock()
        mock_geo.unpack.return_value = qld.id
        presenter.on_activate_remove_menu_item(None, mock_geo)
        self.assertEqual([dist.geography for dist in sp.distribution], [nsw])

        del presenter


class VernacularNamePresenterTests(PlantTestCase):
    def test_on_add_button_clicked(self):
        mock_parent = mock.Mock()
        mock_parent.view = SpeciesEditorView()
        fam = Family(family='family')
        gen = Genus(genus='genus', family=fam)
        sp = Species(genus=gen, sp='sp')
        mock_parent.model = sp
        mock_parent.session = self.session

        presenter = VernacularNamePresenter(mock_parent)
        self.assertEqual(sp.vernacular_names, [])
        self.assertIsNone(sp.default_vernacular_name)

        presenter.on_add_button_clicked(None)

        self.assertEqual(len(sp.vernacular_names), 1)
        self.assertIsNotNone(sp.default_vernacular_name)

        del presenter

    def test_on_remove_button_clicked_new(self):
        mock_parent = mock.Mock()
        mock_parent.view = SpeciesEditorView()
        fam = Family(family='family')
        gen = Genus(genus='genus', family=fam)
        sp = Species(genus=gen, sp='sp')
        self.session.add(sp)
        self.session.commit()
        mock_parent.model = sp
        mock_parent.session = self.session

        presenter = VernacularNamePresenter(mock_parent)
        self.assertEqual(sp.vernacular_names, [])
        self.assertIsNone(sp.default_vernacular_name)

        # new VernacularName (not committed)
        presenter.on_add_button_clicked(None)

        self.assertEqual(len(sp.vernacular_names), 1)
        self.assertIsNotNone(sp.default_vernacular_name)

        presenter.on_remove_button_clicked(None)

        self.session.commit()

        self.assertEqual(sp.vernacular_names, [])
        self.assertIsNone(sp.default_vernacular_name)

        del presenter

    @mock.patch('bauble.utils.yes_no_dialog')
    def test_on_remove_button_clicked_existing(self, mock_dlog):
        mock_dlog.return_value = True
        mock_parent = mock.Mock()
        mock_parent.view = SpeciesEditorView()
        fam = Family(family='family')
        gen = Genus(genus='genus', family=fam)
        sp = Species(genus=gen, sp='sp')
        self.session.add(sp)
        name = VernacularName(name='Test Name', language='EN')
        sp.vernacular_names.append(name)
        sp.default_vernacular_name = name
        self.session.commit()
        mock_parent.model = sp
        mock_parent.session = self.session

        presenter = VernacularNamePresenter(mock_parent)
        presenter.treeview.set_cursor(0)

        # existing VernacularName
        self.assertEqual(len(sp.vernacular_names), 1)
        self.assertIsNotNone(sp.default_vernacular_name)

        presenter.on_remove_button_clicked(None)

        self.session.commit()

        self.assertEqual(sp.vernacular_names, [])
        self.assertIsNone(sp.default_vernacular_name)
        self.assertTrue(presenter.is_dirty())

        del presenter

    def test_on_default_toggled(self):
        mock_parent = mock.Mock()
        mock_parent.view = SpeciesEditorView()
        fam = Family(family='family')
        gen = Genus(genus='genus', family=fam)
        sp = Species(genus=gen, sp='sp')
        self.session.add(sp)
        name = VernacularName(name='Test Name', language='EN')
        sp.vernacular_names.append(name)
        sp.default_vernacular_name = name
        name2 = VernacularName(name='Another Name', language='XY')
        sp.vernacular_names.append(name2)
        self.session.commit()
        mock_parent.model = sp
        mock_parent.session = self.session

        presenter = VernacularNamePresenter(mock_parent)
        presenter.treeview.set_cursor(0)

        self.assertEqual(len(sp.vernacular_names), 2)
        self.assertEqual(sp.default_vernacular_name, name)

        mock_cell = mock.Mock()
        mock_cell.get_active.return_value = False
        mock_path = 1
        presenter.on_default_toggled(mock_cell, mock_path)

        self.assertEqual(sp.default_vernacular_name, name2)

        # switch back
        mock_path = 0
        presenter.on_default_toggled(mock_cell, mock_path)

        self.assertEqual(sp.default_vernacular_name, name)

        self.assertEqual(len(sp.vernacular_names), 2)
        self.assertTrue(presenter.is_dirty())

        del presenter

    def test_on_cell_edited(self):
        mock_parent = mock.Mock()
        mock_parent.view = SpeciesEditorView()
        fam = Family(family='family')
        gen = Genus(genus='genus', family=fam)
        sp = Species(genus=gen, sp='sp')
        self.session.add(sp)
        name = VernacularName(name='Test Name', language='EN')
        sp.vernacular_names.append(name)
        sp.default_vernacular_name = name
        self.session.commit()
        mock_parent.model = sp
        mock_parent.session = self.session

        presenter = VernacularNamePresenter(mock_parent)
        presenter.treeview.set_cursor(0)

        self.assertEqual(len(sp.vernacular_names), 1)
        self.assertEqual(sp.default_vernacular_name, name)

        presenter.on_cell_edited(None, 0, 'New name', 'name')
        presenter.on_cell_edited(None, 0, 'XYZ', 'language')

        self.assertEqual(sp.default_vernacular_name.name, 'New name')
        self.assertEqual(sp.default_vernacular_name.language, 'XYZ')
        self.assertTrue(presenter.is_dirty())

        del presenter

    def test_generic_data_func(self):
        mock_parent = mock.Mock()
        mock_parent.view = SpeciesEditorView()
        fam = Family(family='family')
        gen = Genus(genus='genus', family=fam)
        sp = Species(genus=gen, sp='sp')
        self.session.add(sp)
        name = VernacularName(name='Test Name', language='EN')
        sp.vernacular_names.append(name)
        sp.default_vernacular_name = name
        self.session.commit()
        name2 = VernacularName(name='Another Name', language='XY')
        sp.vernacular_names.append(name2)
        mock_parent.model = sp
        mock_parent.session = self.session

        presenter = VernacularNamePresenter(mock_parent)

        mock_cell = mock.Mock()
        mock_model = [[name]]

        # with existing vernacular
        presenter.generic_data_func(None, mock_cell, mock_model, 0, 'name')
        self.assertIn(('text', name.name),
                      [i.args for i in mock_cell.set_property.call_args_list])
        self.assertIn(('foreground', None),
                      [i.args for i in mock_cell.set_property.call_args_list])

        mock_cell.reset_mock()
        presenter.generic_data_func(None, mock_cell, mock_model, 0, 'language')
        self.assertIn(('text', name.language),
                      [i.args for i in mock_cell.set_property.call_args_list])
        self.assertIn(('foreground', None),
                      [i.args for i in mock_cell.set_property.call_args_list])

        # with new vernacular
        mock_cell.reset_mock()
        mock_model = [[name2]]
        print(name2.id)
        presenter.generic_data_func(None, mock_cell, mock_model, 0, 'name')
        self.assertIn(('text', name2.name),
                      [i.args for i in mock_cell.set_property.call_args_list])
        self.assertIn(('foreground', 'blue'),
                      [i.args for i in mock_cell.set_property.call_args_list])

        del presenter

    def test_default_data_func(self):
        mock_parent = mock.Mock()
        mock_parent.view = SpeciesEditorView()
        fam = Family(family='family')
        gen = Genus(genus='genus', family=fam)
        sp = Species(genus=gen, sp='sp')
        self.session.add(sp)
        name = VernacularName(name='Test Name', language='EN')
        sp.vernacular_names.append(name)
        sp.default_vernacular_name = name
        self.session.commit()
        name2 = VernacularName(name='Another Name', language='XY')
        sp.vernacular_names.append(name2)
        mock_parent.model = sp
        mock_parent.session = self.session

        presenter = VernacularNamePresenter(mock_parent)

        mock_cell = mock.Mock()
        mock_model = [[name]]

        presenter.default_data_func(None, mock_cell, mock_model, 0, None)

        self.assertIn(('active', True),
                      [i.args for i in mock_cell.set_property.call_args_list])

        mock_model = [[name2]]

        presenter.default_data_func(None, mock_cell, mock_model, 0, None)

        self.assertIn(('active', False),
                      [i.args for i in mock_cell.set_property.call_args_list])

        del presenter

    @mock.patch('bauble.utils.message_dialog')
    def test_refresh_view_set_default_when_none(self, mock_dialog):
        mock_parent = mock.Mock()
        mock_parent.view = SpeciesEditorView()
        fam = Family(family='family')
        gen = Genus(genus='genus', family=fam)
        sp = Species(genus=gen, sp='sp')
        self.session.add(sp)
        name = VernacularName(name='Test Name', language='EN')
        sp.vernacular_names.append(name)
        self.session.commit()
        mock_parent.model = sp
        mock_parent.session = self.session

        presenter = VernacularNamePresenter(mock_parent)

        self.assertIsNone(sp.default_vernacular_name)

        presenter.refresh_view()

        self.assertEqual(sp.default_vernacular_name, name)
        self.assertTrue(presenter.is_dirty())

        del presenter


class SynonymsPresenterTests(PlantTestCase):
    def test_on_select(self):
        mock_parent = mock.Mock()
        view = SpeciesEditorView()
        mock_parent.view = view
        sp = self.session.query(Species).get(2)
        mock_parent.model = sp
        mock_parent.session = self.session
        presenter = SynonymsPresenter(mock_parent)

        self.assertIsNone(presenter._selected)
        self.assertFalse(view.widgets.sp_syn_add_button.get_sensitive())

        syn = self.session.query(Species).get(4)
        presenter.on_select(syn)

        self.assertTrue(view.widgets.sp_syn_add_button.get_sensitive())
        self.assertEqual(presenter._selected, syn)

        presenter.on_select(None)
        self.assertIsNone(presenter._selected)
        self.assertFalse(view.widgets.sp_syn_add_button.get_sensitive())

        del presenter

    def test_get_completions(self):
        mock_parent = mock.Mock()
        view = SpeciesEditorView()
        mock_parent.view = view
        sp = self.session.query(Species).get(2)
        start_syns = sp.synonyms
        mock_parent.model = sp
        mock_parent.session = self.session
        presenter = SynonymsPresenter(mock_parent)
        self.assertEqual([i.id for i in start_syns], [1])

        # skips self
        result = presenter.get_completions(str(sp)[:3])
        self.assertNotIn(sp, result)

        # skips current
        result = presenter.get_completions(str(start_syns[0])[:3])
        self.assertNotIn(start_syns[0], result)

        del presenter

    def test_on_add_button_clicked(self):
        # adds _selected to synonyms, adds all _selected's synonyms, empties
        # the entry, resets _selected to None, add button to insensitive and
        # sets presenter dirty
        mock_parent = mock.Mock()
        view = SpeciesEditorView()
        mock_parent.view = view
        sp = self.session.query(Species).get(4)
        start_syns = sp.synonyms
        mock_parent.model = sp
        mock_parent.session = self.session
        presenter = SynonymsPresenter(mock_parent)
        self.assertEqual(start_syns, [])
        sp_w_syns = self.session.query(Species).get(2)
        existing_syn = sp_w_syns.synonyms[0]
        # just checking it is only the one
        self.assertEqual(sp_w_syns.synonyms, [existing_syn])

        view.widgets.sp_syn_entry.set_text(str(sp_w_syns))
        presenter.on_select(sp_w_syns)
        self.assertEqual(sp_w_syns, presenter._selected)

        presenter.on_add_button_clicked(None)

        self.assertEqual(sp.synonyms, [sp_w_syns, existing_syn])
        self.assertFalse(sp_w_syns.synonyms)
        self.assertFalse(view.widgets.sp_syn_entry.get_text())
        self.assertIsNone(presenter._selected)
        self.assertTrue(presenter.is_dirty())
        self.assertFalse(view.widgets.sp_syn_add_button.get_sensitive())

        del presenter

    @mock.patch('bauble.utils.yes_no_dialog')
    def test_on_remove_button_clicker(self, mock_dialog):
        mock_dialog.return_value = True
        mock_parent = mock.Mock()
        view = SpeciesEditorView()
        mock_parent.view = view
        sp = self.session.query(Species).get(2)
        mock_parent.model = sp
        mock_parent.session = self.session
        presenter = SynonymsPresenter(mock_parent)
        view.widgets.sp_syn_treeview.set_cursor(0)

        presenter.on_remove_button_clicked(None)

        self.assertFalse(sp.synonyms)
        self.assertTrue(presenter.is_dirty())

        del presenter


class GlobalFunctionsTest(PlantTestCase):
    def test_species_markup_func(self):
        sp1 = (self.session.query(Species)
               .join(Genus)
               .filter(Genus.epithet == 'Maxillaria')
               .filter(Species.epithet == 'variabilis')
               .one())
        sp2 = (self.session.query(Species)
               .join(Genus)
               .filter(Genus.epithet == 'Laelia')
               .filter(Species.epithet == 'lobata')
               .one())
        first, second = sp1.search_view_markup_pair()
        self.assertTrue(remove_zws(first).startswith(
            '<i>Maxillaria</i> <i>variabilis</i>'))
        expect = '<i>Maxillaria</i> <i>variabilis</i> <span weight="light">'\
            'Bateman ex Lindl.</span><span foreground="#555555" size="small" '\
            'weight="light"> - synonym of <i>Encyclia</i> <i>cochleata</i> '\
            '(L.) Lemée</span>'
        self.assertEqual(remove_zws(first), expect)
        self.assertEqual(second, 'Orchidaceae -- SomeName, SomeName 2')
        first, second = sp2.search_view_markup_pair()
        self.assertEqual(remove_zws(first), '<i>Laelia</i> <i>lobata</i>')
        self.assertEqual(second, 'Orchidaceae')

    def test_vername_markup_func(self):
        vName = self.session.query(VernacularName).filter_by(id=1).one()
        first, second = vName.search_view_markup_pair()
        self.assertEqual(remove_zws(second),
                         '<i>Maxillaria</i> <i>variabilis</i>')
        self.assertEqual(first, 'SomeName')

    def test_species_get_kids(self):
        mVa = self.session.query(Species).filter_by(id=1).one()
        self.assertEqual(partial(db.natsort, 'accessions')(mVa), [])

    def test_vernname_get_kids(self):
        vName = self.session.query(VernacularName).filter_by(id=1).one()
        self.assertEqual(partial(db.natsort, 'species.accessions')(vName), [])

    def test_species_to_string_matcher(self):
        family = Family(family='Myrtaceae')
        gen1 = Genus(family=family, genus='Syzygium')
        gen2 = Genus(family=family, genus='Melaleuca')
        sp1 = Species(genus=gen1, sp='australe')
        sp2 = Species(genus=gen2, sp='viminalis')
        sp3 = Species(genus=gen2, sp='viminalis',
                      cultivar_epithet='Captain Cook')
        sp4 = Species(genus=gen2, sp='viminalis',
                      cultivar_epithet='cv.')
        sp5 = Species(genus=gen2, sp='sp. Carnarvon NP (M.B.Thomas 115)')
        sp6 = Species(genus=gen1, sp='wilsonii',
                      infraspecific_parts='subsp. cryptophlebium')
        self.assertTrue(species_to_string_matcher(sp1, 'S a'))
        self.assertTrue(species_to_string_matcher(sp1, 'Syzyg'))
        self.assertTrue(species_to_string_matcher(sp1, 'Syzygium australe'))
        self.assertFalse(species_to_string_matcher(sp1, 'unknown'))
        self.assertFalse(species_to_string_matcher(sp1, 'Mel vim'))
        self.assertTrue(species_to_string_matcher(sp2, 'Mel vim'))
        self.assertTrue(species_to_string_matcher(sp2, 'M'))
        self.assertTrue(species_to_string_matcher(sp2, ''))
        self.assertFalse(species_to_string_matcher(sp2, 'unknown'))
        self.assertFalse(species_to_string_matcher(
            sp2, 'a long string with little meaning'))
        self.assertTrue(species_to_string_matcher(sp3, 'M'))
        self.assertTrue(species_to_string_matcher(sp3, 'M v'))
        self.assertTrue(species_to_string_matcher(
            sp3, "M viminalis 'Captain Cook'"))
        self.assertTrue(species_to_string_matcher(sp4, 'Mel viminalis cv.'))
        self.assertTrue(species_to_string_matcher(sp4, 'Mel'))
        self.assertFalse(species_to_string_matcher(sp4, 'Cal vim'))
        self.assertTrue(species_to_string_matcher(sp5, 'Mel sp.'))
        self.assertTrue(species_to_string_matcher(sp5, 'Mel sp. Carn'))
        self.assertTrue(species_to_string_matcher(sp5, 'Mel'))
        self.assertTrue(species_to_string_matcher(sp6, 'Syz wil'))
        self.assertTrue(species_to_string_matcher(
            sp6, 'Syz wilsonii subsp. cry'))
        self.assertFalse(species_to_string_matcher(
            sp6, 'Syz wilsonii subsp. wil'))

    def test_species_cell_data_func(self):
        family = Family(family='Myrtaceae')
        gen = Genus(family=family, genus='Syzygium')
        sp = Species(genus=gen, sp='australe')
        self.session.add(sp)
        self.session.commit()
        mock_renderer = mock.Mock()
        mock_model = [[sp]]

        species_cell_data_func(None, mock_renderer, mock_model, 0)

        mock_renderer.set_property.assert_called_with(
            'text', 'Syzygium australe (Myrtaceae)'
        )


class BaubleSearchSearchTest(BaubleTestCase):
    def test_search_search_uses_synonym_search(self):
        prefs.prefs['bauble.search.return_accepted'] = True
        search.search("genus like %", self.session)
        self.assertTrue('SearchStrategy "genus like %" (SynonymSearch)' in
                        self.handler.messages['bauble.search']['debug'])
        self.handler.reset()
        search.search("12.11.13", self.session)
        self.assertTrue('SearchStrategy "12.11.13" (SynonymSearch)' in
                        self.handler.messages['bauble.search']['debug'])
        self.handler.reset()
        search.search("So ha", self.session)
        self.assertTrue('SearchStrategy "So ha" (SynonymSearch)' in
                        self.handler.messages['bauble.search']['debug'])

    def test_search_search_doesnt_use_synonym_search(self):
        prefs.prefs['bauble.search.return_accepted'] = False
        search.search("genus like %", self.session)
        self.assertFalse('SearchStrategy "genus like %" (SynonymSearch)' in
                         self.handler.messages['bauble.search']['debug'])
        self.handler.reset()
        search.search("12.11.13", self.session)
        self.assertFalse('SearchStrategy "12.11.13" (SynonymSearch)' in
                         self.handler.messages['bauble.search']['debug'])
        self.handler.reset()
        search.search("So ha", self.session)
        self.assertFalse('SearchStrategy "So ha" (SynonymSearch)' in
                         self.handler.messages['bauble.search']['debug'])


class SpeciesCompletionMatchTests(PlantTestCase):

    def setUp(self):
        super().setUp()
        self.family = Family(family='Myrtaceae')
        self.genus = Genus(family=self.family, genus='Syzygium')
        self.sp1 = Species(genus=self.genus, sp='australe')
        self.sp2 = Species(genus=self.genus, sp='luehmannii')
        self.session.add_all([self.family, self.genus, self.sp1, self.sp2])
        self.session.commit()
        self.sp3 = Species(genus=self.genus, sp='aqueum')
        self.session.add_all([self.sp3])
        self.session.commit()

        from gi.repository import Gtk
        self.completion = Gtk.EntryCompletion()
        completion_model = Gtk.ListStore(object)
        for val in [self.sp1, self.sp2, self.sp3]:
            completion_model.append([val])
        self.completion.set_model(completion_model)

        # another approach (keeping for reference but this approach does not
        # take into account some of the internals of how a GtkEntryCompletion
        # works, e.g.: key is normalised and case-folded - hence need to
        # lower() case the keys here)
        #
        # self.mock_completion = SpeciesEditorView.attach_completion(
        #     None, entry, cell_data_func=species_cell_data_func,
        #     match_func=species_match_func)

        # self.mock_completion = mock.Mock(
        #     **{'get_model.return_value':
        #        [[self.sp1], [self.sp2], [self.sp3]]}
        # )

    def test_full_name(self):
        key = 'Syzygium australe'.lower()
        self.assertTrue(species_match_func(self.completion, key, 0))
        self.assertFalse(species_match_func(self.completion, key, 1))
        self.assertFalse(species_match_func(self.completion, key, 2))

    def test_only_full_genus(self):
        key = 'Syzygium'.lower()
        self.assertTrue(species_match_func(self.completion, key, 0))
        self.assertTrue(species_match_func(self.completion, key, 1))
        self.assertTrue(species_match_func(self.completion, key, 2))

    def test_only_partial_genus(self):
        key = 'Syzyg'.lower()
        self.assertTrue(species_match_func(self.completion, key, 0))
        self.assertTrue(species_match_func(self.completion, key, 1))
        self.assertTrue(species_match_func(self.completion, key, 2))

    def test_only_partial_binomial(self):
        key = 'Syz lu'.lower()
        self.assertFalse(species_match_func(self.completion, key, 0))
        self.assertTrue(species_match_func(self.completion, key, 1))
        self.assertFalse(species_match_func(self.completion, key, 2))

    def test_generic_sp_get_completions(self):
        completion = partial(generic_sp_get_completions, self.session)
        key = 'Syz lu'
        self.assertCountEqual(completion(key).all(),
                              [self.sp1, self.sp2, self.sp3])
        key = 'Syzyg'
        # [self.sp1, self.sp2, self.sp3]
        self.assertCountEqual(completion(key).all(),
                              [self.sp1, self.sp2, self.sp3])
        key = 'Syzygium australe'
        self.assertCountEqual(completion(key).all(),
                              [self.sp1, self.sp2, self.sp3])
        key = 'Unknown'
        self.assertEqual(completion(key).all(), [])
        key = ''
        self.assertEqual(len(completion(key).all()),
                         len(self.session.query(Species).all()))


class RetrieveTests(PlantTestCase):
    def test_vernacular_name_retreives_full_sp_data(self):
        keys = {
            'species.sp': 'cochleata',
            'species.genus.genus': 'Encyclia',
            'species.infrasp1_rank': 'subsp.',
            'species.infrasp1': 'cochleata',
            'species.infrasp2_rank': 'var.',
            'species.infrasp2': 'cochleata',
            'species.cultivar_epithet': 'Black',
        }
        vname = VernacularName.retrieve(self.session, keys)
        self.assertEqual(vname.id, 5)
        # using hybrid properties
        keys = {
            'species.epithet': 'cochleata',
            'species.genus.epithet': 'Encyclia',
            'species.infrasp_parts': 'subsp. cochleata var. cochleata',
            'species.cultivar_epithet': 'Black',
        }
        vname = VernacularName.retrieve(self.session, keys)
        self.assertEqual(vname.id, 5)

    def test_vernacular_name_retreives_incomplete_sp_data_one_sp(self):
        keys = {
            'species.epithet': 'cochleata',
            'species.genus.epithet': 'Encyclia',
            'species.cultivar_epithet': 'Black',
        }
        vname = VernacularName.retrieve(self.session, keys)
        self.assertEqual(vname.id, 5)

    def test_vernacular_name_doesnt_retreive_incomplete_sp_data_multiple(self):
        keys = {
            'species.genus.epithet': 'Encyclia',
            'species.epithet': 'cochleata',
        }
        vname = VernacularName.retrieve(self.session, keys)
        self.assertIsNone(vname)

    def test_vernacular_name_doesnt_retreive_sp_data_multiple_vnames(self):
        keys = {
            'species.genus.epithet': 'Maxillaria',
            'species.epithet': 'variabilis',
        }
        vname = VernacularName.retrieve(self.session, keys)
        self.assertIsNone(vname)

    def test_vernacular_name_retreives_vn_parts_only_one_sp(self):
        keys = {
            'name': 'SomeName',
            'language': 'English',
        }
        vname = VernacularName.retrieve(self.session, keys)
        self.assertEqual(vname.id, 1)

    def test_vernacular_name_doesnt_retreive_vn_parts_only_multiple_sp(self):
        keys = {
            'name': 'Clamshell Orchid',
            'language': 'English',
        }
        vname = VernacularName.retrieve(self.session, keys)
        self.assertIsNone(vname)

    def test_vernacular_name_retreives_full_data(self):
        keys = {
            'name': 'SomeName',
            'language': 'English',
            'species.epithet': 'variabilis',
            'species.genus.epithet': 'Maxillaria',
        }
        vname = VernacularName.retrieve(self.session, keys)
        self.assertEqual(vname.id, 1)

    def test_vernacular_name_retreives_id_only(self):
        keys = {
            'id': 5
        }
        vname = VernacularName.retrieve(self.session, keys)
        self.assertEqual(vname.species.id, 15)

    def test_vernacular_name_retreives_sp_id_only(self):
        keys = {
            'species.id': 15
        }
        vname = VernacularName.retrieve(self.session, keys)
        self.assertEqual(vname.id, 5)

    def test_vernacular_name_retreives_name_only_exists_once(self):
        keys = {
            'name': 'Toé'
        }
        vname = VernacularName.retrieve(self.session, keys)
        self.assertEqual(vname.id, 4)

    def test_vernacular_name_doesnt_retreive_non_existent_name(self):
        keys = {
            'name': 'NonExistent'
        }
        vname = VernacularName.retrieve(self.session, keys)
        self.assertIsNone(vname)
        # mismatch
        keys = {
            'name': 'Clamshell orchid',
            'language': 'English',
            'species.epithet': 'variabilis',
            'species.genus.epithet': 'Maxillaria'
        }
        vname = VernacularName.retrieve(self.session, keys)
        self.assertIsNone(vname)

    def test_vernacular_name_doesnt_retreive_wrong_keys(self):
        keys = {
            'name': 'Somewhere Else',
            'code': 'SE'
        }
        vname = VernacularName.retrieve(self.session, keys)
        self.assertIsNone(vname)

    def test_vernacular_name_doesnt_retreive_for_sp_non_existent_vname(self):
        keys = {
            'species.genus': 'Campyloneurum',
            'species.sp': 'alapense',
            'species.hybrid': '×',
        }
        vname = VernacularName.retrieve(self.session, keys)
        logs = self.handler.messages['bauble.plugins.plants.species_model']
        self.assertIn(f'retrieved species {species_str_map[4]}', logs['debug'])
        self.assertIsNone(vname)

    def test_species_retreives_full_sp_data(self):
        keys = {
            'sp': 'cochleata',
            'genus.genus': 'Encyclia',
            'infrasp1_rank': 'subsp.',
            'infrasp1': 'cochleata',
            'infrasp2_rank': 'var.',
            'infrasp2': 'cochleata',
            'cultivar_epithet': 'Black',
        }
        sp = Species.retrieve(self.session, keys)
        self.assertEqual(sp.id, 15)
        # using hybrid property infrasp_parts
        keys = {
            'epithet': 'cochleata',
            'genus.epithet': 'Encyclia',
            'infrasp_parts': 'subsp. cochleata var. cochleata',
            'cultivar_epithet': 'Black',
        }
        sp = Species.retrieve(self.session, keys)
        self.assertEqual(sp.id, 15)

    def test_species_retreives_id_only(self):
        keys = {
            'id': 15
        }
        sp = Species.retrieve(self.session, keys)
        self.assertEqual(str(sp), species_str_map[15])

    def test_species_doesnt_retreive_incomplete_sp_data_multiple(self):
        keys = {
            'genus.epithet': 'Encyclia',
            'epithet': 'cochleata',
        }
        sp = Species.retrieve(self.session, keys)
        self.assertIsNone(sp)

    def test_species_doesnt_retreive_non_existent(self):
        keys = {
            'genus.epithet': 'Encyclia',
            'epithet': 'nonexistennt',
        }
        sp = Species.retrieve(self.session, keys)
        self.assertIsNone(sp)

    def test_species_doesnt_retreive_wrong_keys(self):
        keys = {
            'name': 'Somewhere Else',
            'code': 'SE'
        }
        sp = Species.retrieve(self.session, keys)
        self.assertIsNone(sp)

    def test_genus_retreives_full_data(self):
        keys = {
            'epithet': 'Encyclia',
            'family.epithet': 'Orchidaceae',
        }
        gen = Genus.retrieve(self.session, keys)
        self.assertEqual(gen.id, 2)

        keys = {
            'genus': 'Encyclia',
            'family.family': 'Orchidaceae',
        }
        gen = Genus.retrieve(self.session, keys)
        self.assertEqual(gen.id, 2)

    def test_genus_retreives_genus_only_unique_genus(self):
        keys = {
            'epithet': 'Encyclia',
        }
        gen = Genus.retrieve(self.session, keys)
        self.assertEqual(gen.id, 2)

        keys = {
            'genus': 'Encyclia',
        }
        gen = Genus.retrieve(self.session, keys)
        self.assertEqual(gen.id, 2)

    def test_genus_retreives_id_only(self):
        keys = {
            'id': 5
        }
        genus = Genus.retrieve(self.session, keys)
        self.assertEqual(genus.genus, 'Paphiopedilum')

    def test_genus_doesnt_retreive_family_only(self):
        keys = {
            'family.family': 'Orchidaceae',
        }
        genus = Genus.retrieve(self.session, keys)
        self.assertIsNone(genus)
        # single genus family
        keys = {
            'family.family': 'Solanaceae',
        }
        genus = Genus.retrieve(self.session, keys)
        self.assertIsNone(genus)

    def test_genus_doesnt_retreive_non_existent(self):
        keys = {
            'family.family': 'Orchidaceae',
            'genus': 'Nonexistent'
        }
        genus = Genus.retrieve(self.session, keys)
        self.assertIsNone(genus)

    def test_genus_doesnt_retreive_wrong_keys(self):
        keys = {
            'name': 'Somewhere Else',
            'code': 'SE',
        }
        genus = Genus.retrieve(self.session, keys)
        self.assertIsNone(genus)

    def test_family_retreives(self):
        keys = {
            'epithet': 'Orchidaceae',
        }
        fam = Family.retrieve(self.session, keys)
        self.assertEqual(fam.id, 1)
        keys = {
            'family': 'Orchidaceae',
        }
        fam = Family.retrieve(self.session, keys)
        self.assertEqual(fam.id, 1)

    def test_family_retreives_id_only(self):
        keys = {
            'id': 4
        }
        fam = Family.retrieve(self.session, keys)
        self.assertEqual(fam.family, 'Solanaceae')

    def test_family_doesnt_retreive_non_existent(self):
        keys = {
            'epithet': 'Nonexistent'
        }
        fam = Family.retrieve(self.session, keys)
        self.assertIsNone(fam)

    def test_family_doesnt_retreive_wrong_keys(self):
        keys = {
            'name': 'Somewhere Else',
            'accession': '2001.1'
        }
        fam = Family.retrieve(self.session, keys)
        self.assertIsNone(fam)

    def test_geography_retreives(self):
        # NOTE grouped to avoid unnecessarily reloading geography table
        from bauble.task import queue
        queue(geography_importer())
        keys = {
            'tdwg_code': '50',
        }
        geo = Geography.retrieve(self.session, keys)
        self.assertEqual(geo.name, 'Australia')

        # test id only
        keys = {
            'id': 4
        }
        geo = Geography.retrieve(self.session, keys)
        self.assertEqual(geo.id, 4)

        # test non-existent
        keys = {
            'epithet': 'Nonexistent'
        }
        geo = Geography.retrieve(self.session, keys)
        self.assertIsNone(geo)

        # test wrong keys
        keys = {
            'accession.code': '2001.1',
        }
        geo = Geography.retrieve(self.session, keys)
        self.assertIsNone(geo)


class SplashInfoBoxTests(BaubleTestCase):
    @mock.patch('bauble.gui')
    def test_update_sensitise_exclude_inactive(self, _mock_gui):
        splash = SplashInfoBox()
        splash.update()
        wait_on_threads()
        for widget in [splash.splash_nplttot,
                       splash.splash_npltnot,
                       splash.splash_nacctot,
                       splash.splash_naccnot,
                       splash.splash_nspctot,
                       splash.splash_nspcnot]:
            self.assertTrue(widget.get_parent().get_sensitive())

        prefs.prefs[prefs.exclude_inactive_pref] = True
        splash.update()
        wait_on_threads()
        for widget in [splash.splash_nplttot,
                       splash.splash_npltnot,
                       splash.splash_nacctot,
                       splash.splash_naccnot,
                       splash.splash_nspctot,
                       splash.splash_nspcnot]:
            self.assertFalse(widget.get_parent().get_sensitive())


class SpeciesFullNameTests(PlantTestCase):
    def test_full_name_is_created_on_species_insert(self):
        gen = self.session.query(Genus).first()
        sp = Species(genus=gen, sp='sp. nov.')
        self.assertFalse(sp.full_name)
        self.session.add(sp)
        self.session.commit()
        self.assertEqual(sp.full_name, str(sp))
        hist_query = (self.session.query(db.History.values)
                      .filter(db.History.table_name == 'species')
                      .filter(db.History.table_id == sp.id))
        hist_entry = [entry for entry in hist_query if
                      entry[0]['full_name'] == str(sp)]
        self.assertEqual(len(hist_entry), 1)

    def test_full_name_is_created_on_all_insert(self):
        fam = Family(epithet='Fabaceae')
        gen = Genus(epithet='Acacia', family=fam)
        sp = Species(genus=gen,
                     sp='dealbata',
                     infrasp1_rank='subsp.',
                     infrasp1='dealbata')
        self.assertFalse(sp.full_name)
        self.session.add(sp)
        self.session.commit()
        self.assertEqual(sp.full_name, 'Acacia dealbata subsp. dealbata')
        hist_query = (self.session.query(db.History.values)
                      .filter(db.History.table_name == 'species')
                      .filter(db.History.table_id == sp.id))
        hist_entry = [entry for entry in hist_query if
                      entry[0]['full_name'] == str(sp)]
        self.assertEqual(len(hist_entry), 1)

    def test_full_name_updated_on_species_update(self):
        # check update any epithet, infrasp or ranks, group, cv, etc.
        # Epithet
        sp = self.session.query(Species).get(1)
        sp.epithet = 'sophronitis'
        self.session.add(sp)
        self.session.commit()
        self.assertEqual(sp.full_name, str(sp))
        # infrasp
        sp.infrasp1_rank = 'var.'
        sp.infrasp1 = 'sophronitis'
        self.session.add(sp)
        self.session.commit()
        self.assertEqual(sp.full_name, str(sp))
        # group
        sp.group = 'Test'
        self.session.add(sp)
        self.session.commit()
        self.assertEqual(sp.full_name, str(sp))
        # cv
        start = sp.full_name
        sp.cultivar_epithet = 'Red'
        self.session.add(sp)
        self.session.commit()
        self.assertEqual(sp.full_name, str(sp))
        hist_query = (self.session.query(db.History.values)
                      .filter(db.History.table_name == 'species')
                      .filter(db.History.table_id == 1))
        hist_entry = [entry for entry in hist_query if
                      entry[0]['full_name'] == [str(sp), start]]
        self.assertEqual(len(hist_entry), 1)

    def test_full_name_updated_on_genus_update(self):
        # check epithet, hybrid, etc.
        # new genus
        fam = self.session.query(Family).get(1)
        gen = Genus(epithet='Ornithidium', family=fam)
        sp = self.session.query(Species).get(1)
        sp.genus = gen
        self.session.add(gen)
        self.session.commit()
        self.assertEqual(sp.full_name, str(sp))
        # update genus name
        sp.genus.epithet = 'Anguloa'
        self.session.add(sp)
        self.session.commit()
        self.assertEqual(gen.epithet, 'Anguloa')
        self.assertEqual(sp.full_name, str(sp))
        hist_query = (self.session.query(db.History.values)
                      .filter(db.History.table_name == 'species')
                      .filter(db.History.table_id == 1))
        hist_entry = [entry for entry in hist_query if
                      entry[0]['full_name'] ==
                      ['Anguloa variabilis', 'Ornithidium variabilis']]
        self.assertEqual(len(hist_entry), 1)
        # update genus hybrid
        sp.genus.hybrid = '×'
        self.session.add(sp)
        self.session.commit()
        self.assertEqual(sp.full_name, str(sp))
        hist_query = (self.session.query(db.History.values)
                      .filter(db.History.table_name == 'species')
                      .filter(db.History.table_id == 1))
        hist_entry = [entry for entry in hist_query if
                      entry[0]['full_name'] ==
                      ['× Anguloa variabilis', 'Anguloa variabilis']]
        self.assertEqual(len(hist_entry), 1)

    def test_full_name_updated_on_genus_and_sp_update(self):
        # change to another existing genus
        sp = self.session.query(Species).get(1)
        start = sp.full_name
        gen = self.session.query(Genus).get(sp.genus_id + 1)
        sp.genus = gen
        sp.epither = 'test_new'
        self.session.add(sp)
        self.session.commit()
        self.assertEqual(sp.full_name, str(sp))
        self.assertNotEqual(sp.full_name, start)
        hist_query = (self.session.query(db.History.values)
                      .filter(db.History.table_name == 'species')
                      .filter(db.History.table_id == 1))
        hist_entry = [entry for entry in hist_query if
                      entry[0]['full_name'] == [str(sp), start]]
        self.assertEqual(len(hist_entry), 1)

    def test_full_name_no_change_no_update_no_history(self):
        # set full_names (test data is added not triggering event.listens_for)
        list(update_all_full_names_task())
        hist_query = (self.session.query(db.History.values)
                      .filter(db.History.table_name == 'species')
                      .filter(db.History.table_id == 1))
        start_count = hist_query.count()
        sp = self.session.query(Species).get(1)
        start = sp.full_name
        sp.epithet = 'variabilis'
        self.session.add(sp)
        self.session.commit()
        self.assertEqual(sp.full_name, str(sp))
        self.assertEqual(sp.full_name, start)
        end_count = hist_query.count()
        self.assertEqual(start_count, end_count)

    def test_update_all_full_names_handler(self):
        hist_query = (self.session.query(db.History.values)
                      .filter(db.History.table_name == 'species'))
        start_count = hist_query.count()
        update_all_full_names_handler()
        sp_query = self.session.query(Species)
        for sp in sp_query:
            if sp.id in species_str_map:
                self.assertEqual(sp.full_name, species_str_map.get(sp.id))
        end_count = hist_query.count()
        # one history entry per species
        self.assertEqual(end_count, start_count + sp_query.count())
