# Copyright (c) 2005,2006,2007,2008,2009 Brett Adams <brett@belizebotanic.org>
# Copyright (c) 2012-2017 Mario Frasca <mario@anche.no>
# Copyright 2017 Jardín Botánico de Quito
# Copyright (c) 2017-2023 Ross Demuth <rossdemuth123@gmail.com>
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

import os
from unittest import mock
from pathlib import Path

from gi.repository import Gtk

from bauble import prefs
from bauble.test import BaubleTestCase, check_dupids, update_gui
from bauble.plugins.plants import (Family,
                                   Genus,
                                   Species,
                                   VernacularName,
                                   Geography)
from bauble.plugins.garden import (Accession,
                                   Plant,
                                   Location,
                                   Source,
                                   SourceDetail,
                                   Collection)
from bauble.plugins.tag import tag_objects, Tag
from .template_downloader import (download_templates,
                                  set_templates_root_pref,
                                  update_report_template_prefs,
                                  TEMPLATES_ROOT_PREF)
from . import (get_species_pertinent_to,
               get_accessions_pertinent_to,
               get_plants_pertinent_to,
               get_locations_pertinent_to,
               get_geographies_pertinent_to,
               ReportToolDialogView,
               ReportToolDialogPresenter,
               CONFIG_LIST_PREF,
               DEFAULT_CONFIG_PREF)


def test_duplicate_ids():
    """
    Test for duplicate ids for all .glade files in the gardens plugin.
    """
    import bauble.plugins.report as mod
    import glob
    head, _tail = os.path.split(mod.__file__)
    files = []
    files.extend(glob.glob(os.path.join(head, '*.glade')))
    files = glob.glob(os.path.join(head, 'mako', '*.glade'))
    files = glob.glob(os.path.join(head, 'xsl', '*.glade'))
    for f in files:
        assert(not check_dupids(f))


def get_ids(objs):
    return [obj.id for obj in objs]


class ReportTests(BaubleTestCase):

    def setUp(self):
        super().setUp()
        fctr = gctr = sctr = actr = pctr = 0
        for f in range(2):
            fctr += 1
            family = Family(id=fctr, family='fam%s' % fctr)
            self.session.add(family)
            for g in range(2):
                gctr += 1
                genus = Genus(id=gctr, family=family, genus='gen%s' % gctr)
                self.session.add(genus)
                for s in range(2):
                    sctr += 1
                    sp = Species(id=sctr, genus=genus, sp='sp%s' % sctr)
                    vn = VernacularName(id=sctr, species=sp,
                                        name='name%s' % sctr)
                    self.session.add_all([sp, vn])
                    for a in range(2):
                        actr += 1
                        acc = Accession(id=actr, species=sp, code='%s' % actr)
                        contact = SourceDetail(id=actr, name='contact%s' % actr)
                        source = Source(id=actr, source_detail=contact,
                                accession=acc)
                        self.session.add_all([acc, source, contact])
                        for p in range(2):
                            pctr += 1
                            loc = Location(id=pctr, code='%s' % pctr,
                                           name='site%s' % pctr)
                            plant = Plant(id=pctr, accession=acc, location=loc,
                                          code='%s' % pctr, quantity=1)
                            #debug('fctr: %s, gctr: %s, actr: %s, pctr: %s' \
                            #      % (fctr, gctr, actr, pctr))
                            self.session.add_all([loc, plant])
        self.session.commit()

    def test_no_objects_in_FamilyNote(self):
        family = self.session.query(Family).get(1)
        from bauble.plugins.plants.family import FamilyNote
        fn = FamilyNote(family=family, note='empty')
        self.session.add(fn)
        self.session.flush()

        from bauble.error import BaubleError
        self.assertRaises(BaubleError, get_species_pertinent_to, [fn])
        self.assertRaises(BaubleError, get_species_pertinent_to, fn)
        self.assertRaises(BaubleError, get_accessions_pertinent_to, [fn])
        self.assertRaises(BaubleError, get_accessions_pertinent_to, fn)
        self.assertRaises(BaubleError, get_plants_pertinent_to, [fn])
        self.assertRaises(BaubleError, get_plants_pertinent_to, fn)
        self.assertRaises(BaubleError, get_locations_pertinent_to, [fn])
        self.assertRaises(BaubleError, get_locations_pertinent_to, fn)
        self.assertRaises(BaubleError, get_geographies_pertinent_to, [fn])
        self.assertRaises(BaubleError, get_geographies_pertinent_to, fn)

    def test_get_species_pertinent_to_sessionless(self):

        family = self.session.query(Family).get(1)
        ids = get_ids(get_species_pertinent_to([family]))
        self.assertCountEqual(ids, list(range(1, 5)))

    def test_get_species_pertinent_to_element(self):
        """
        Test getting the species from different types
        """
        family = self.session.query(Family).get(1)
        ids = get_ids(get_species_pertinent_to(family, self.session))
        self.assertCountEqual(ids, list(range(1, 5)))

    def test_get_species_pertinent_to_lists(self):
        """
        Test getting the species from different types
        """
        family = self.session.query(Family).get(1)
        ids = get_ids(get_species_pertinent_to([family], self.session))
        self.assertCountEqual(ids, list(range(1, 5)))

        family = self.session.query(Family).get(1)
        family2 = self.session.query(Family).get(2)
        ids = get_ids(
            get_species_pertinent_to([family, family2], self.session))
        self.assertCountEqual(ids, list(range(1, 9)))

        genus = self.session.query(Genus).get(1)
        ids = get_ids(get_species_pertinent_to([genus], self.session))
        self.assertCountEqual(ids, [1, 2])

        species = self.session.query(Species).get(1)
        ids = get_ids(get_species_pertinent_to([species], self.session))
        self.assertCountEqual(ids, [1])

        accession = self.session.query(Accession).get(1)
        ids = get_ids(get_species_pertinent_to([accession], self.session))
        self.assertCountEqual(ids, [1])

        contact = self.session.query(SourceDetail).get(1)
        ids = get_ids(get_species_pertinent_to(contact, self.session))
        self.assertCountEqual(ids, [1])

        plant = self.session.query(Plant).get(1)
        ids = get_ids(get_species_pertinent_to([plant], self.session))
        self.assertCountEqual(ids, [1])

        location = self.session.query(Location).get(1)
        ids = get_ids(get_species_pertinent_to([location], self.session))
        self.assertCountEqual(ids, [1])

        vn = self.session.query(VernacularName).get(1)
        ids = get_ids(get_species_pertinent_to([vn], self.session))
        self.assertCountEqual(ids, [1])

        tag_objects('test', [family, genus, location, accession])
        tag = self.session.query(Tag).filter_by(tag='test').one()
        ids = get_ids(get_species_pertinent_to([tag], self.session))
        self.assertCountEqual(ids, list(range(1, 5)))

        accession.source.collection = Collection(locale='down the road')
        self.session.add(accession)
        self.session.commit()
        collection = self.session.query(Collection).get(1)
        ids = get_ids(get_species_pertinent_to([collection], self.session))
        self.assertCountEqual(ids, [1])

        # now test all the objects
        ids = get_ids(get_species_pertinent_to(
            [family, genus, species, accession, plant, location, collection],
            self.session))
        self.assertCountEqual(ids, list(range(1, 5)))

        # test doesn't return inactive only when exclude_inactive set
        for acc in species.accessions:
            for plt in acc.plants:
                print(plt)
                plt.quantity = 0
        self.session.commit()
        ids = get_ids(get_species_pertinent_to([plant], self.session))
        self.assertCountEqual(ids, [1])
        prefs.prefs[prefs.exclude_inactive_pref] = True
        self.assertFalse(get_species_pertinent_to([plt], self.session).all())
        # with all objects (should not return species)
        result = get_species_pertinent_to(
            [family, genus, species, accession, plant, location, collection],
            self.session
        )
        self.assertNotIn(species, result)

    def test_get_accessions_pertinent_to(self):
        """
        Test getting the accessions from different types
        """
        family = self.session.query(Family).get(1)
        ids = get_ids(get_accessions_pertinent_to([family], self.session))
        self.assertCountEqual(ids, list(range(1, 9)))

        family = self.session.query(Family).get(1)
        family2 = self.session.query(Family).get(1)
        ids = get_ids(get_accessions_pertinent_to(
            [family, family2], self.session))
        self.assertCountEqual(ids, list(range(1, 9)))

        genus = self.session.query(Genus).get(1)
        ids = get_ids(get_accessions_pertinent_to(genus, self.session))
        self.assertCountEqual(ids, list(range(1, 5)))

        species = self.session.query(Species).get(1)
        ids = get_ids(get_accessions_pertinent_to(species, self.session))
        self.assertCountEqual(ids, [1, 2])

        accession = self.session.query(Accession).get(1)
        ids = get_ids(get_accessions_pertinent_to([accession], self.session))
        self.assertCountEqual(ids, [1])

        contact = self.session.query(SourceDetail).get(1)
        ids = get_ids(get_accessions_pertinent_to(contact, self.session))
        self.assertTrue(ids == [1], ids)

        plant = self.session.query(Plant).get(1)
        ids = get_ids(get_accessions_pertinent_to([plant], self.session))
        self.assertCountEqual(ids, [1])

        location = self.session.query(Location).get(1)
        ids = get_ids(get_accessions_pertinent_to([location], self.session))
        self.assertCountEqual(ids, [1])

        vn = self.session.query(VernacularName).get(1)
        ids = get_ids(get_accessions_pertinent_to([vn], self.session))
        self.assertCountEqual(ids, [1, 2])

        tag_objects('test', [family, genus])
        tag = self.session.query(Tag).filter_by(tag='test').one()
        ids = get_ids(get_accessions_pertinent_to([tag], self.session))
        self.assertCountEqual(ids, list(range(1, 9)))

        accession.source.collection = Collection(locale='down the road')
        self.session.add(accession)
        self.session.commit()
        collection = self.session.query(Collection).get(1)
        ids = get_ids(get_accessions_pertinent_to([collection], self.session))
        self.assertCountEqual(ids, [1])

        # now test all the objects
        ids = get_ids(get_accessions_pertinent_to(
            [family, genus, species, accession, plant, location],
            self.session))
        self.assertCountEqual(ids, list(range(1, 9)))

        # test doesn't return inactive only when exclude_inactive set
        for plt in plant.accession.plants:
            plt.quantity = 0
        self.session.commit()
        ids = get_ids(get_accessions_pertinent_to([plant], self.session))
        self.assertCountEqual(ids, [1])
        prefs.prefs[prefs.exclude_inactive_pref] = True
        self.assertFalse(get_accessions_pertinent_to([plant], self.session)
                         .all())
        # with all the objects shouldn't return plant.accession
        result = get_accessions_pertinent_to(
            [family, genus, species, accession, plant, location],
            self.session
        )
        self.assertNotIn(plant.accession, result)

    def test_get_plants_pertinent_to(self):
        """
        Test getting the plants from different types
        """
        # get plants from one family
        family = self.session.query(Family).get(1)
        ids = get_ids(get_plants_pertinent_to(family, self.session))
        self.assertCountEqual(ids, list(range(1, 17)))

        # get plants from multiple families
        family = self.session.query(Family).get(1)
        family2 = self.session.query(Family).get(2)
        ids = get_ids(get_plants_pertinent_to([family, family2], self.session))
        self.assertCountEqual(ids, list(range(1, 33)))

        genus = self.session.query(Genus).get(1)
        ids = get_ids(get_plants_pertinent_to(genus, self.session))
        self.assertCountEqual(ids, list(range(1, 9)))

        species = self.session.query(Species).get(1)
        ids = get_ids(get_plants_pertinent_to(species, self.session))
        self.assertCountEqual(ids, list(range(1, 5)))

        accession = self.session.query(Accession).get(1)
        ids = get_ids(get_plants_pertinent_to(accession, self.session))
        self.assertCountEqual(ids, list(range(1, 3)))

        contact = self.session.query(SourceDetail).get(1)
        ids = get_ids(get_plants_pertinent_to(contact, self.session))
        self.assertTrue(ids == list(range(1, 3)), ids)

        plant = self.session.query(Plant).get(1)
        ids = get_ids(get_plants_pertinent_to(plant, self.session))
        self.assertCountEqual(ids, [1])

        location = self.session.query(Location).get(1)
        plants = get_plants_pertinent_to([location], self.session)
        ids = sorted([p.id for p in plants])
        self.assertCountEqual(ids, [1])

        vn = self.session.query(VernacularName).get(1)
        ids = get_ids(get_plants_pertinent_to(vn, self.session))
        self.assertCountEqual(ids, list(range(1, 5)))

        tag_objects('test', [family, genus])
        tag = self.session.query(Tag).filter_by(tag='test').one()
        ids = get_ids(get_plants_pertinent_to(tag, self.session))
        self.assertCountEqual(ids, list(range(1, 17)))

        accession.source.collection = Collection(locale='down the road')
        self.session.add(accession)
        self.session.commit()
        collection = self.session.query(Collection).get(1)
        ids = get_ids(get_plants_pertinent_to([collection], self.session))
        self.assertCountEqual(ids, list(range(1, 3)))

        # now test all the objects
        plants = get_plants_pertinent_to(
            [family, genus, species, accession, plant, location, collection,
             tag],
            self.session)
        ids = get_ids(plants)
        self.assertCountEqual(ids, list(range(1, 17)))

        # test doesn't return inactive only when exclude_inactive set
        plant.quantity = 0
        self.session.commit()
        ids = get_ids(get_plants_pertinent_to([genus], self.session))
        self.assertCountEqual(ids, list(range(1, 9)))
        prefs.prefs[prefs.exclude_inactive_pref] = True
        ids = get_ids(get_plants_pertinent_to([genus], self.session))
        self.assertCountEqual(ids, list(range(2, 9)))
        # with all the objects shouldn't return plant (we exclude it from the
        # query)
        plants = get_plants_pertinent_to(
            [family, genus, species, accession, location, collection, tag],
            self.session)
        self.assertNotIn(plant, plants)

    def test_get_locations_pertinent_to(self):
        """
        Test getting the locations from different types
        """
        # get locations from one family
        family = self.session.query(Family).get(1)
        ids = get_ids(get_locations_pertinent_to(family, self.session))
        self.assertCountEqual(ids, list(range(1, 17)))

        # get locations from multiple families
        family = self.session.query(Family).get(1)
        family2 = self.session.query(Family).get(2)
        ids = get_ids(get_locations_pertinent_to([family, family2],
                                                 self.session))
        self.assertCountEqual(ids, list(range(1, 33)))

        genus = self.session.query(Genus).get(1)
        ids = get_ids(get_locations_pertinent_to(genus, self.session))
        self.assertCountEqual(ids, list(range(1, 9)))

        species = self.session.query(Species).get(1)
        ids = get_ids(get_locations_pertinent_to(species, self.session))
        self.assertCountEqual(ids, list(range(1, 5)))

        vn = self.session.query(VernacularName).get(1)
        ids = get_ids(get_locations_pertinent_to(vn, self.session))
        self.assertCountEqual(ids, list(range(1, 5)))

        plant = self.session.query(Plant).get(1)
        ids = get_ids(get_locations_pertinent_to(plant, self.session))
        self.assertCountEqual(ids, [1])

        accession = self.session.query(Accession).get(1)
        ids = get_ids(get_locations_pertinent_to(accession, self.session))
        self.assertCountEqual(ids, list(range(1, 3)))

        contact = self.session.query(SourceDetail).get(1)
        ids = get_ids(get_locations_pertinent_to(contact, self.session))
        self.assertTrue(ids == list(range(1, 3)))

        location = self.session.query(Location).get(1)
        locations = get_locations_pertinent_to([location], self.session)
        ids = [l.id for l in locations]
        self.assertCountEqual(ids, [1])

        tag_objects('test', [family, genus])
        tag = self.session.query(Tag).filter_by(tag='test').one()
        ids = get_ids(get_locations_pertinent_to(tag, self.session))
        self.assertCountEqual(ids, list(range(1, 17)))

        accession.source.collection = Collection(locale='down the road')
        self.session.add(accession)
        self.session.commit()
        collection = self.session.query(Collection).get(1)
        ids = get_ids(get_locations_pertinent_to([collection], self.session))
        self.assertCountEqual(ids, list(range(1, 3)))

        # now test all the objects
        locations = get_locations_pertinent_to(
            [family, genus, species, accession, plant, location, tag,
             collection],
            self.session)
        ids = get_ids(locations)
        self.assertCountEqual(ids, list(range(1, 17)))

    def test_get_geographies_pertinent_to(self):
        """
        Test getting the geographies from different types
        """
        from bauble.plugins.plants.geography import geography_importer
        from bauble.plugins.plants import SpeciesDistribution
        # at least we run it once during a test!
        [i for i in geography_importer()]
        self.assertTrue(len(self.session.query(Geography).all()) > 700)

        geo1 = self.session.query(Geography).get(330)
        geo2 = self.session.query(Geography).get(694)

        acc1 = self.session.query(Accession).get(1)
        acc1.source.collection = Collection(locale='down the road')
        acc1.source.collection.region = geo1
        self.assertIsNotNone(acc1.source.collection)
        self.session.add(acc1)
        self.session.commit()

        sp1 = self.session.query(Species).get(1)
        sp1_dist = SpeciesDistribution(species=sp1, geography=geo2)
        self.session.add(sp1_dist)
        self.session.commit()
        # self.assertEqual(sp1.distribution.geography.id, geo2.id)

        # get geographies from one geographies
        ids = get_ids(get_geographies_pertinent_to([geo1, geo2], self.session))
        self.assertCountEqual(ids, [694, 330])

        # get geographies from one family
        family = self.session.query(Family).get(1)
        ids = get_ids(get_geographies_pertinent_to(family, self.session))
        self.assertCountEqual(ids, [694])

        # get locations from multiple families
        family = self.session.query(Family).get(1)
        family2 = self.session.query(Family).get(2)
        ids = get_ids(get_geographies_pertinent_to([family, family2],
                                                   self.session))
        self.assertCountEqual(ids, [694])

        genus = self.session.query(Genus).get(1)
        ids = get_ids(get_geographies_pertinent_to(genus, self.session))
        self.assertCountEqual(ids, [694])

        species = self.session.query(Species).get(1)
        ids = get_ids(get_geographies_pertinent_to(species, self.session))
        self.assertCountEqual(ids, [694])

        vn = self.session.query(VernacularName).get(1)
        ids = get_ids(get_geographies_pertinent_to(vn, self.session))
        self.assertCountEqual(ids, [694])

        plant = self.session.query(Plant).get(1)
        ids = get_ids(get_geographies_pertinent_to(plant, self.session))
        self.assertCountEqual(ids, [694])

        accession = self.session.query(Accession).get(1)
        ids = get_ids(get_geographies_pertinent_to(accession, self.session))
        self.assertCountEqual(ids, [330])

        contact = self.session.query(SourceDetail).get(1)
        ids = get_ids(get_geographies_pertinent_to(contact, self.session))
        self.assertCountEqual(ids, [694])

        location = self.session.query(Location).get(1)
        ids = get_ids(get_geographies_pertinent_to([location], self.session))
        self.assertCountEqual(ids, [694])

        tag_objects('test', [family, genus])
        tag = self.session.query(Tag).filter_by(tag='test').one()
        ids = get_ids(get_geographies_pertinent_to(tag, self.session))
        self.assertCountEqual(ids, [694])

        accession.source.collection = Collection(locale='down the road')
        collection = self.session.query(Collection).get(1)
        ids = get_ids(get_geographies_pertinent_to([collection], self.session))
        self.assertCountEqual(ids, [330])

        # now test all the objects
        locations = get_geographies_pertinent_to(
            [family, genus, species, accession, plant, location, tag,
             collection],
            self.session)
        ids = get_ids(locations)
        self.assertCountEqual(ids, [694, 330])

    def test_get_items_pertinent_to_geographies(self):
        """get geographies from various other items
        """
        from bauble.plugins.plants.geography import geography_importer
        from bauble.plugins.plants import SpeciesDistribution
        from collections import deque
        # at least we run it once during a test!
        deque(geography_importer(), maxlen=0)
        self.assertTrue(len(self.session.query(Geography).all()) > 700)

        geo1 = self.session.query(Geography).get(330)
        geo2 = self.session.query(Geography).get(694)

        acc1 = self.session.query(Accession).get(1)
        acc1.source.collection = Collection(locale='down the road')
        acc1.source.collection.region = geo1
        self.assertIsNotNone(acc1.source.collection)
        self.session.add(acc1)
        self.session.commit()

        sp1 = self.session.query(Species).get(1)
        sp1_dist = SpeciesDistribution(species=sp1, geography=geo2)
        self.session.add(sp1_dist)
        self.session.commit()
        # self.assertEqual(sp1.distribution.geography.id, geo2.id)

        ids = get_ids(get_species_pertinent_to([geo1, geo2], self.session))
        self.assertCountEqual(ids, [1])

        ids = get_ids(get_accessions_pertinent_to([geo1, geo2], self.session))
        # distribution of the species not the region of a sources collection.
        self.assertCountEqual(ids, [1, 2])

        ids = get_ids(get_locations_pertinent_to([geo1, geo2], self.session))
        self.assertCountEqual(
            ids,
            [plt.location_id for acc in sp1.accessions for plt in acc.plants]
        )

        ids = get_ids(get_plants_pertinent_to([geo1, geo2], self.session))
        self.assertCountEqual(ids, [1, 2, 3, 4])


class ReportToolDialogTests(BaubleTestCase):
    def setUp(self):
        with mock.patch('bauble.plugins.report.xsl._fop.set_fop_command',
                        return_value=True):
            super().setUp()
        prefs.prefs[CONFIG_LIST_PREF] = {
            'plant csv': ('Mako', {'template':
                                   'plants.csv',
                                   'private': False}),
            'bed csv': ('Mako', {'template':
                                 'beds.csv',
                                 'private':
                                 False}),
        }
        prefs.prefs[DEFAULT_CONFIG_PREF] = 'plant csv'
        with (mock.patch('bauble.gui'),
              mock.patch('bauble.utils.message_dialog'),
              mock.patch('bauble.gui.window',
                         new_callable=mock.PropertyMock(
                             return_value=Gtk.Window()
                         ))):
            self.report_view = ReportToolDialogView()
            self.report_presenter = ReportToolDialogPresenter(self.report_view)

    def tearDown(self):
        self.report_view.dialog.destroy()
        super().tearDown()

    def test_set_sensative(self):
        self.report_view.set_sensitive('ok_button', True)
        self.assertTrue(self.report_view.widgets.ok_button.get_sensitive())
        self.report_view.set_sensitive('ok_button', False)
        self.assertFalse(self.report_view.widgets.ok_button.get_sensitive())

    @mock.patch('bauble.utils.message_dialog')
    def test_set_name_combo(self, _mock_dialog):
        self.report_presenter.set_names_combo(0)
        self.assertEqual(self.report_view.widgets.names_combo.get_active(), 0)
        self.report_presenter.set_names_combo(None)
        self.assertEqual(self.report_view.widgets.names_combo.get_active(), -1)
        self.report_presenter.set_names_combo('bed csv')
        self.assertEqual(self.report_view.widgets.names_combo.get_active(), 1)

    def test_set_formatter_combo(self):
        self.report_presenter.set_formatter_combo(0)
        self.assertEqual(
            self.report_view.widgets.formatter_combo.get_active(), 0
        )
        self.report_presenter.set_formatter_combo('Mako')
        self.assertEqual(
            self.report_view.widgets.formatter_combo.get_active_text(), 'Mako'
        )
        self.report_presenter.set_formatter_combo(None)
        self.assertEqual(
            self.report_view.widgets.formatter_combo.get_active(), -1
        )

    def test_on_formatter_combo_changed(self):
        prefs.prefs['report.xsl_external_fop'] = False
        name = 'bed csv'
        self.report_presenter.set_names_combo(name)
        self.assertEqual(self.report_view.widgets.names_combo.get_active(), 1)
        self.report_presenter.set_formatter_combo('XSL')
        self.assertEqual(
            self.report_view.widgets.formatter_combo.get_active_text(), 'XSL')
        update_gui()
        formatter, _settings = (prefs.prefs
                                .get(CONFIG_LIST_PREF, {})
                                .get(name, (None, None)))
        self.assertEqual(formatter, 'XSL')
        self.report_presenter.set_formatter_combo('Mako')
        self.assertEqual(
            self.report_view.widgets.formatter_combo.get_active_text(), 'Mako')
        update_gui()
        formatter, _settings = (prefs.prefs
                                .get(CONFIG_LIST_PREF, {})
                                .get(name, (None, None)))
        self.assertEqual(formatter, 'Mako')

    @mock.patch('bauble.plugins.report.Gtk.Dialog.run',
                return_value=Gtk.ResponseType.OK)
    @mock.patch('bauble.plugins.report.Gtk.Entry.get_text',
                return_value='species csv')
    def test_on_new_button_clicked(self, _mock_entry, _mock_dialog):
        self.report_presenter.on_new_button_clicked(None)
        self.assertEqual(self.report_view.widgets.names_combo.get_active(), 2)

    def test_on_remove_button_clicked(self):
        self.report_presenter.set_names_combo(0)
        self.report_presenter.on_remove_button_clicked(None)
        self.assertEqual(self.report_view.widgets.names_combo.get_active(), 0)

    def test_save_formatter_setttings(self):
        name = 'bed csv'
        self.report_presenter.set_names_combo(name)
        self.report_presenter.set_formatter_combo('XSL')
        update_gui()
        self.report_presenter.save_formatter_settings()
        formatter, _settings = (prefs.prefs
                                .get(CONFIG_LIST_PREF, {})
                                .get(name, (None, None)))
        self.assertEqual(formatter, 'XSL')


class TemplateDowloaderTests(BaubleTestCase):

    @mock.patch('gi.repository.Gtk.FileChooserNative.get_filename')
    @mock.patch('gi.repository.Gtk.FileChooserNative.run')
    def test_set_templates_root_ref(self, mock_run, mock_get_fname):
        mock_run.return_value = Gtk.ResponseType.ACCEPT
        here = str(Path('.'))
        mock_get_fname.return_value = here
        result = set_templates_root_pref()
        self.assertTrue(result)
        self.assertEqual(prefs.prefs.get(TEMPLATES_ROOT_PREF), here)

    def test_update_template_prefs(self):
        config = b"""
[report]
configs = {'species list': ('Mako', {'private': False, 'template': 'species.html'})}
"""
        from tempfile import mkstemp, mkdtemp
        handle, filename = mkstemp(suffix='.cfg')
        os.write(handle, config)
        os.close(handle)

        templates_root = mkdtemp()
        prefs.prefs[TEMPLATES_ROOT_PREF] = templates_root
        prefs.prefs.save()
        update_report_template_prefs(templates_root, filename)
        path = Path(templates_root, 'species.html')
        self.assertEqual(
            prefs.prefs.get(CONFIG_LIST_PREF),
            {'species list': ('Mako',
                              {'private': False,
                               'template': f'{path}'})})

    @mock.patch('bauble.plugins.report.template_downloader.yes_no_dialog')
    @mock.patch('bauble.plugins.report.template_downloader.get_net_sess')
    def test_download_templates(self, mock_get_sess, mock_dialog):
        import zipfile
        import io
        from tempfile import mkdtemp
        templates_root = mkdtemp()

        zip_mem = io.BytesIO()
        with zipfile.ZipFile(zip_mem, mode='w') as zf:
            # These 2 lines are a hack as zf.mkdir() was not available prior to
            # python v3.11
            zf.writestr('root/trunk/leaf/', "")
            zf.writestr('root/', "")

            zf.writestr('root/file1.txt', "test1")
            zf.writestr('root/file2.txt', "test2")
            zf.writestr('root/trunk/leaf/file3.txt', "test3")

        mock_sess = mock.Mock()
        mock_result = mock.Mock(content=zip_mem.getvalue())
        mock_sess.get.return_value = mock_result
        # mock_sess.get.return_value = str(zip_mem)

        mock_get_sess.return_value = mock_sess

        result = download_templates(templates_root)

        mock_get_sess.assert_called()
        mock_sess.get.assert_called()
        mock_dialog.assert_not_called()

        self.assertEqual(str(result), str(Path(templates_root, 'root')))

        # call a second time should ask to delete previous version
        mock_dialog.return_value = True

        result = download_templates(templates_root)

        mock_dialog.assert_called()

        self.assertEqual(str(result), str(Path(templates_root, 'root')))
