# pylint: disable=no-self-use,protected-access,too-many-public-methods
# Copyright 2008-2010 Brett Adams
# Copyright 2015 Mario Frasca <mario@anche.no>.
# Copyright 2017 Jardín Botánico de Quito
# Copyright 2021-2026 Ross Demuth <rossdemuth123@gmail.com>
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
Family model tests
"""

from datetime import datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import NoResultFound

from bauble import prefs
from bauble.test import BaubleTestCase
from bauble.test import get_setUp_data_funcs

from ...garden import Plant
from ..family import Family
from ..family import FamilyNote
from ..family import FamilySynonym
from ..genus import Genus
from ..species import Species
from ..species import SpeciesPicture
from .test_plants import PlantTestCase


class FamilyTests(PlantTestCase):
    """Tests for Family and FamilySynonym"""

    def test_cascades(self):
        """
        Test that cascading is set up properly
        """
        family = Family(family="family")
        genus = Genus(family=family, genus="genus")
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
        family = Family(family="family")
        family2 = Family(family="family2")
        family.synonyms.append(family2)
        self.session.add_all([family, family2])
        self.session.commit()

        # test that family2 was added as a synonym to family
        family = self.session.query(Family).filter_by(family="family").one()
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
        self.assertEqual(len(family.synonyms), 0)

        # test that deleting a family that is a synonym of another family
        # deletes all the dangling objects
        family.synonyms.append(family2)
        self.session.commit()
        self.session.delete(family2)
        self.session.commit()
        self.assertEqual(len(family.synonyms), 0)

        # test that deleting the previous synonyms didn't delete the
        # family that it refered to
        self.assertTrue(self.session.get(Family, family.id))

        # test that deleting a family that has synonyms deletes all
        # the synonyms that refer to that family deletes all the
        family2 = Family(family="family2")
        self.session.add(family2)
        family.synonyms.append(family2)
        self.session.commit()
        self.session.delete(family)
        self.session.commit()
        # NOTE there is one synonym added as part of the test_data
        self.assertEqual(self.session.query(FamilySynonym).count(), 1)

    def test_constraints(self):
        """Test that the family constraints were created correctly"""

        values = [
            {"family": "family"},
            {"family": "family", "qualifier": "s. lat."},
        ]
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
        f = Family()
        self.assertTrue(str(f) == repr(f))
        f = Family(family="fam")
        self.assertTrue(str(f) == "fam")
        f.qualifier = "s. lat."
        self.assertTrue(str(f) == "fam s. lat.")
        f.author = "arthur"
        self.assertTrue(f.string(author=True) == "fam s. lat. arthur")

    def test_search_view_markup_pair(self):
        fam = Family(epithet="Myrtaceae", author="Juss.")
        self.assertEqual(
            fam.search_view_markup_pair(),
            ('Myrtaceae <span weight="light">Juss.</span>', "Family"),
        )

    def test_synonym_str(self):
        fam = Family(family="Fam", qualifier="s. lat.", author="Arthur")
        new = Family(family="Newname")
        syn = FamilySynonym(family=new, synonym=fam)
        self.assertEqual(str(syn), fam.string(author=True))

    def test_synonym_markup(self):
        fam = Family(family="Fam", qualifier="s. lat.", author="Arthur")
        new = Family(family="Newname")
        syn = FamilySynonym(family=new, synonym=fam)
        self.assertEqual(str(syn), fam.string(author=True))

    def test_no_synonyms_means_itself_accepted(self):
        fam = Family(id=51, epithet="TestFamily")
        self.session.add(fam)
        self.session.commit()
        self.assertEqual(fam.accepted, None)

    def test_synonyms_and_accepted_properties(self):
        def create_tmp_fam(id_):
            fam = Family(id=id_, epithet=f"fam{id_}")
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

    def test_pictures(self):
        from ...garden import Accession
        from ...garden import Location
        from ...garden.plant import PlantPicture

        fam = self.session.query(Family).first()
        gen = fam.genera[0]
        self.assertEqual(fam.pictures, [])
        sp = gen.species[0]
        acc = Accession(species=sp, code="1")
        plt = Plant(
            accession=acc,
            quantity=0,
            location=Location(name="site", code="STE"),
            code="1",
        )
        self.session.add_all([sp, acc, plt])
        self.session.commit()
        spic = SpeciesPicture(picture="test1.jpg", species=sp)
        ppic = PlantPicture(picture="test2.jpg", plant=plt)
        self.session.commit()
        self.assertEqual(fam.pictures, [spic, ppic])
        plt.quantity = 0
        self.session.commit()
        # exclude inactive
        prefs.prefs[prefs.exclude_inactive_pref] = True
        self.assertEqual(fam.pictures, [spic])
        # detached returns empty
        self.session.expunge(fam)
        self.assertEqual(fam.pictures, [])

    def test_active_no_genera(self):
        fam = self.session.get(Family, 12)
        self.assertFalse(fam.active)
        # test the hybrid_property expression
        # pylint: disable=no-member  # is_
        fam_active_in_db = self.session.query(Family).filter(
            Family.active.is_(True)
        )
        self.assertNotIn(fam, fam_active_in_db)

    def test_active_no_species(self):
        fam = self.session.get(Family, 8)
        self.assertFalse(fam.active)
        # test the hybrid_property expression
        # pylint: disable=no-member  # is_
        fam_active_in_db = self.session.query(Family).filter(
            Family.active.is_(True)
        )
        self.assertNotIn(fam, fam_active_in_db)

    def test_active_no_accession(self):
        fam = self.session.get(Family, 1)
        # check this is a family with no accession
        self.assertEqual(
            len(
                [
                    acc
                    for gen in fam.genera
                    for sp in gen.species
                    for acc in sp.accessions
                ]
            ),
            0,
        )
        self.assertTrue(fam.active)
        # test the hybrid_property expression
        # pylint: disable=no-member  # is_
        fam_active_in_db = self.session.query(Family).filter(
            Family.active.is_(True)
        )
        self.assertIn(fam, fam_active_in_db)

    def test_active_no_plants(self):
        from ...garden import Accession

        sp = self.session.get(Species, 26)
        fam = sp.genus.family
        # check this is a family with no plants
        self.assertEqual(
            len(
                [
                    plt
                    for gen in fam.genera
                    for sp in gen.species
                    for acc in sp.accessions
                    for plt in acc.plants
                ]
            ),
            0,
        )
        acc = Accession(code="foo", species=sp)
        self.session.add(acc)
        self.session.commit()

        self.assertTrue(fam.active)
        # test the hybrid_property expression
        # pylint: disable=no-member  # is_
        fam_active_in_db = self.session.query(Family).filter(
            Family.active.is_(True)
        )
        self.assertIn(fam, fam_active_in_db)

    def test_active_one_plants_w_qty(self):
        from ...garden import Accession
        from ...garden import Location

        sp = self.session.get(Species, 26)
        acc = Accession(code="foo", species=sp)
        plt = Plant(
            code="1", accession=acc, quantity=1, location=Location(code="bar")
        )
        self.session.add_all([acc, plt])
        self.session.commit()
        fam = sp.genus.family

        self.assertTrue(fam.active)
        # test the hybrid_property expression
        # pylint: disable=no-member  # is_
        fam_active_in_db = self.session.query(Family).filter(
            Family.active.is_(True)
        )
        self.assertIn(fam, fam_active_in_db)

    def test_active_one_plants_wo_qty(self):
        from ...garden import Accession
        from ...garden import Location

        sp = self.session.get(Species, 26)
        fam = sp.genus.family
        self.assertEqual(
            len(
                [
                    plt
                    for gen in fam.genera
                    for sp in gen.species
                    for acc in sp.accessions
                    for plt in acc.plants
                ]
            ),
            0,
        )
        acc = Accession(code="foo", species=sp)
        plt = Plant(
            code="1", accession=acc, quantity=0, location=Location(code="bar")
        )
        self.session.add_all([acc, plt])
        self.session.commit()

        self.assertFalse(fam.active)
        # test the hybrid_property expression
        # pylint: disable=no-member  # is_
        fam_active_in_db = self.session.query(Family).filter(
            Family.active.is_(True)
        )
        self.assertNotIn(fam, fam_active_in_db)

    def test_has_children(self):
        from ...garden import Accession
        from ...garden import Location

        fam = Family(epithet="Welwitschiaceae")
        gen = Genus(epithet="Welwitschia", family=fam)
        sp = Species(epithet="mirablis", genus=gen)
        acc = Accession(species=sp, code="1")
        loc = Location(code="LOC10")
        plant = Plant(
            accession=acc,
            quantity=0,
            location=loc,
            code="1",
        )
        self.session.add(plant)
        self.session.commit()

        prefs.prefs[prefs.exclude_inactive_pref] = True

        # plant qty 0 exclude inactive true
        self.assertEqual(fam.has_children(), False)

        prefs.prefs[prefs.exclude_inactive_pref] = False

        # plant qty 0 exclude inactive false
        self.assertEqual(fam.has_children(), True)

        plant.quantity = 1
        self.session.commit()

        # plant qty 1 exclude inactive false
        self.assertEqual(fam.has_children(), True)

        prefs.prefs[prefs.exclude_inactive_pref] = True

        # plant qty 1 exclude inactive true
        self.assertEqual(fam.has_children(), True)

        self.session.delete(plant)
        self.session.commit()

        # no plant exclude inactive true
        self.assertEqual(fam.has_children(), True)

        prefs.prefs[prefs.exclude_inactive_pref] = False

        # no plant exclude inactive false
        self.assertEqual(fam.has_children(), True)


class FamilyUpdatedTests(BaubleTestCase):

    def test_updated_self(self):
        fam = Family(epithet="Myrtaceae")
        self.session.add(fam)
        self.session.commit()

        self.assertIs(
            self.session.query(Family)
            .filter(Family.updated > "Today")
            .first(),
            fam,
        )

        # the python function
        self.assertEqual(fam.updated, fam._last_updated)

        date = datetime(2001, 1, 1, 0)
        fam._last_updated = date
        self.session.commit()

        self.assertIs(
            self.session.query(Family).filter(Family.updated == date).first(),
            fam,
        )

        # the python function
        self.assertEqual(fam.updated, fam._last_updated)

    def test_updated_notes(self):
        date = datetime(2001, 1, 1, 0)
        fam = Family(epithet="Myrtaceae", _last_updated=date)
        note = FamilyNote(category="Spam", note="Eggs", family=fam)
        self.session.add_all([fam, note])
        self.session.commit()

        self.assertIs(
            self.session.query(Family)
            .filter(Family.updated > "Today")
            .first(),
            fam,
        )

        # the python function
        self.assertEqual(fam.updated, note._last_updated)

        note._last_updated = datetime(2001, 1, 1, 0)
        self.session.commit()

        self.assertIs(
            self.session.query(Family).filter(Family.updated == date).first(),
            fam,
        )

        # the python function
        self.assertEqual(fam.updated, fam._last_updated)

    def test_updated_synonym(self):
        # make sure the date is not now
        date = datetime(2001, 1, 1, 0)
        fam = Family(epithet="Myrtaceae", _last_updated=date)
        fam2 = Family(epithet="Kaniaceae", _last_updated=date)
        fam2.accepted = fam
        self.session.add_all([fam, fam2])
        self.session.commit()

        self.assertIs(
            self.session.query(Family)
            .filter(Family.updated > "Today")
            .first(),
            fam2,
        )

        # the python function
        self.assertEqual(fam2.updated, fam2._accepted._last_updated)


class FamilyTopLevelCountTests(BaubleTestCase):
    def setUp(self):
        super().setUp()
        for data_func in get_setUp_data_funcs():
            data_func()

    def test_top_level_count_w_plant_qty(self):

        expected = (
            "Families: 2, "
            "Genera: 8, "
            "Species: 27, "
            "Accessions: 6, "
            "Plantings: 5, "
            "Living plants: 6, "
            "Locations: 1, "
            "Sources: 1"
        )

        self.assertEqual(str(Family.top_level_count([1, 2])), expected)

    def test_top_level_count_wo_genera(self):
        fam = Family(epithet="Welwitschiaceae")
        self.session.add(fam)
        self.session.commit()

        expected = (
            "Families: 2, "
            "Genera: 7, "
            "Species: 23, "
            "Accessions: 4, "
            "Plantings: 3, "
            "Living plants: 3, "
            "Locations: 1, "
            "Sources: 1"
        )

        self.assertEqual(str(Family.top_level_count([1, fam.id])), expected)

    def test_top_level_count_wo_species_in_genera(self):

        gen = self.session.get(Genus, 14)
        for sp in gen.species:
            self.session.delete(sp)
        self.session.commit()

        expected = (
            "Families: 2, "
            "Genera: 8, "
            "Species: 26, "
            "Accessions: 6, "
            "Plantings: 5, "
            "Living plants: 6, "
            "Locations: 1, "
            "Sources: 1"
        )

        self.assertEqual(str(Family.top_level_count([1, 2])), expected)

    def test_top_level_count_wo_species_in_genera_exclude_inactive_set(self):

        gen = self.session.get(Genus, 14)
        for sp in gen.species:
            self.session.delete(sp)
        self.session.commit()

        expected = (
            "Families: 2, "
            "Genera: 7, "
            "Species: 26, "
            "Accessions: 5, "
            "Plantings: 4, "
            "Living plants: 6, "
            "Locations: 1, "
            "Sources: 1"
        )

        self.assertEqual(str(Family.top_level_count([1, 2], True)), expected)

    def test_top_level_count_wo_plant_qty(self):
        plt = self.session.get(Plant, 1)
        self.session.delete(plt)
        plt = self.session.get(Plant, 2)
        plt.quantity = 0
        self.session.commit()

        expected = (
            "Families: 2, "
            "Genera: 8, "
            "Species: 27, "
            "Accessions: 6, "
            "Plantings: 4, "
            "Living plants: 4, "
            "Locations: 1, "
            "Sources: 1"
        )

        self.assertEqual(str(Family.top_level_count([1, 2])), expected)

    def test_top_level_count_wo_plant_qty_exclude_inactive_set(self):
        plt = self.session.get(Plant, 1)
        self.session.delete(plt)
        plt = self.session.get(Plant, 2)
        plt.quantity = 0
        self.session.commit()

        expected = (
            "Families: 2, "
            "Genera: 8, "
            "Species: 27, "
            "Accessions: 5, "
            "Plantings: 2, "
            "Living plants: 4, "
            "Locations: 1, "
            "Sources: 1"
        )

        self.assertEqual(str(Family.top_level_count([1, 2], True)), expected)


class RetrieveTests(PlantTestCase):

    def test_family_retreives(self):
        keys = {
            "epithet": "Orchidaceae",
        }
        fam = Family.retrieve(self.session, keys)
        self.assertEqual(fam.id, 1)
        keys = {
            "family": "Orchidaceae",
        }
        fam = Family.retrieve(self.session, keys)
        self.assertEqual(fam.id, 1)

    def test_family_retreives_id_only(self):
        keys = {"id": 4}
        fam = Family.retrieve(self.session, keys)
        self.assertEqual(fam.family, "Solanaceae")

    def test_family_doesnt_retreive_non_existent(self):
        keys = {"epithet": "Nonexistent"}
        fam = Family.retrieve(self.session, keys)
        self.assertIsNone(fam)

    def test_family_doesnt_retreive_wrong_keys(self):
        keys = {"name": "Somewhere Else", "accession": "2001.1"}
        fam = Family.retrieve(self.session, keys)
        self.assertIsNone(fam)
