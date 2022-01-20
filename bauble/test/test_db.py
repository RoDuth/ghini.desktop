# Copyright 2008-2010 Brett Adams
# Copyright 2015 Mario Frasca <mario@anche.no>.
# Copyright 2021 Ross Demuth <rossdemuth123@gmail.com>
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

from bauble.test import BaubleTestCase
from bauble.plugins.plants.genus import Family, Genus, Species
from bauble.plugins.garden.accession import (AccessionNote, Accession, Plant,
                                             Contact)
from bauble.plugins.garden.location import Location
from bauble.plugins.plants.species_model import VernacularName

from bauble import db
from bauble import prefs
prefs.testing = True

# db.sqlalchemy_debug(True)


class GlobalFunctionsTests(BaubleTestCase):
    def test_class_of_object(self):
        self.assertEqual(db.class_of_object("genus"), Genus)
        self.assertEqual(db.class_of_object("accession_note"), AccessionNote)
        self.assertEqual(db.class_of_object("not_existing"), None)

    def test_get_related_class(self):
        self.assertEqual(db.get_related_class(Plant, 'accession'), Accession)
        self.assertEqual(
            db.get_related_class(Plant, 'accession.species.genus.family'),
            Family
        )
        self.assertEqual(
            db.get_related_class(Plant, 'accession.source.source_detail'),
            Contact
        )
        self.assertEqual(
            db.get_related_class(Plant, 'location'),
            Location
        )
        self.assertEqual(
            db.get_related_class(Location, 'plants'),
            Plant
        )
        self.assertEqual(
            db.get_related_class(Location,
                                 'plants.accession.source.source_detail'),
            Contact
        )
        self.assertEqual(
            db.get_related_class(Species, 'vernacular_names'),
            VernacularName
        )

    def test_get_create_or_update(self):
        loc1 = {'code': 'XYZ001',
                'name': 'A garden bed',
                'description': 'lots of plants'}
        loc1_new = db.get_create_or_update(self.session, Location, **loc1)
        self.assertEqual(len(self.session.new), 1)
        self.assertTrue(loc1_new in self.session.new)
        fam1 = {'epithet': 'Myrtaceae'}
        fam1_new = db.get_create_or_update(self.session, Family, **fam1)
        self.assertEqual(len(self.session.new), 2)
        self.assertTrue(fam1_new in self.session.new)
        gen1 = {'genus': 'Syzygium', 'family': fam1_new}
        gen1_new = db.get_create_or_update(self.session, Genus, **gen1)
        self.assertEqual(len(self.session.new), 3)
        self.assertTrue(gen1_new in self.session.new)
        sp1 = {'epithet': 'francisii', 'genus': gen1_new}
        sp1_new = db.get_create_or_update(self.session, Species, **sp1)
        self.assertEqual(len(self.session.new), 4)
        self.assertTrue(sp1_new in self.session.new)
        acc1 = {'code': 'AAA001', 'species': sp1_new}
        acc1_new = db.get_create_or_update(self.session, Accession, **acc1)
        self.assertEqual(len(self.session.new), 5)
        self.assertTrue(acc1_new in self.session.new)
        plt1 = {'code': '1',
                'quantity': 1,
                'accession': acc1_new,
                'location': loc1_new}
        plt1_new = db.get_create_or_update(self.session, Plant, **plt1)
        self.assertEqual(len(self.session.new), 6)
        self.assertEqual(len(self.session.dirty), 0)
        self.assertTrue(plt1_new in self.session.new)
        self.session.commit()
        self.assertEqual(len(self.session.new), 0)
        self.assertEqual(len(self.session.dirty), 0)
        loc2 = {'code': 'ABC001',
                'name': 'A small garden bed',
                'description': 'a few of plants'}
        loc2_new = db.get_create_or_update(self.session, Location, **loc2)
        self.assertEqual(len(self.session.new), 1)
        self.assertTrue(loc2_new in self.session.new)
        plt2 = {'code': '2',
                'quantity': 10,
                'accession': acc1_new,
                'location': loc2_new}
        plt2_new = db.get_create_or_update(self.session, Plant, **plt2)
        self.assertEqual(len(self.session.new), 2)
        self.assertEqual(len(self.session.dirty), 1)
        self.assertTrue(plt2_new in self.session.new)
        self.assertTrue(acc1_new in self.session.dirty)
        self.session.commit()
        self.assertEqual(len(self.session.new), 0)
        self.assertEqual(len(self.session.dirty), 0)
        plt1_get = db.get_create_or_update(self.session, Plant, **plt1)
        self.assertEqual(plt1_new, plt1_get)
        loc2_get = db.get_create_or_update(self.session, Location, **loc2)
        self.assertEqual(loc2_new, loc2_get)
        loc2['name'] = ''
        loc2_update = db.get_create_or_update(self.session, Location, **loc2)
        self.assertEqual(loc2_new, loc2_update)
        self.assertEqual(loc2_get, loc2_update)
        self.assertEqual(len(self.session.new), 0)
        self.assertEqual(len(self.session.dirty), 1)
        self.session.commit()
        # 2 plants should fail, returning None and not adding anything to the
        # session
        plt_any = db.get_create_or_update(self.session, Plant,
                                          accession=acc1_new)
        self.assertIsNone(plt_any)
        self.assertEqual(len(self.session.new), 0)
        self.assertEqual(len(self.session.dirty), 0)
        self.assertEqual(len(self.session.deleted), 0)
        sp1 = {'epithet': 'francisii', 'genus': gen1_new}
        sp1_update = {'sp': 'luehmanii', 'sp_author': 'F.Muell.',
                      'id': sp1_new.id}
        db.get_create_or_update(self.session, Species, **sp1_update)
        self.assertEqual(len(self.session.dirty), 1)
        self.assertEqual(sp1_new.sp, 'luehmanii')
        self.assertEqual(sp1_new.sp_author, 'F.Muell.')
        self.session.commit()
