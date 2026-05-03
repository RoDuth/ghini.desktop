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
Genus models tests
"""

from datetime import datetime

from sqlalchemy.exc import IntegrityError

from bauble import prefs
from bauble.test import BaubleTestCase
from bauble.test import get_setUp_data_funcs

from ...garden import Plant
from ..family import Family
from ..genus import Genus
from ..genus import GenusNote
from ..genus import GenusSynonym
from ..species import Species
from ..species import SpeciesPicture
from .test_plants import PlantTestCase


class GenusTests(PlantTestCase):
    def test_synonyms(self):
        family = Family(family="family")
        genus = Genus(family=family, genus="genus")
        genus2 = Genus(family=family, genus="genus2")
        genus.synonyms.append(genus2)
        self.session.add_all([genus, genus2])
        self.session.commit()

        # test that genus2 was added as a synonym to genus
        genus = self.session.query(Genus).filter_by(genus="genus").one()
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
        self.assertTrue(self.session.get(Genus, genus.id))

        # test that deleting a genus that has synonyms deletes all
        # the synonyms that refer to that genus
        genus2 = Genus(family=family, genus="genus2")
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
        family = Family(family="family")
        self.session.add(family)

        # if any of these values are inserted twice they should raise
        # an IntegrityError because the UniqueConstraint on Genus
        values = [
            {"family": family, "genus": "genus"},
            {"family": family, "genus": "genus", "author": "author"},
            {"family": family, "genus": "genus", "qualifier": "s. lat."},
            {
                "family": family,
                "genus": "genus",
                "qualifier": "s. lat.",
                "author": "author",
            },
        ]
        for v in values:
            self.session.add(Genus(**v))
            self.session.add(Genus(**v))
            self.assertRaises(IntegrityError, self.session.commit)
            self.session.rollback()

    def test_string(self):

        genus_str_map = {
            1: "Maxillaria s. str",
            2: "Encyclia",
        }

        genus_str_author_map = {
            1: "Maxillaria s. str Ruiz & Pav.",
            2: "Encyclia",
        }

        for gid, expected in genus_str_map.items():
            gen = self.session.get(Genus, gid)

            self.assertEqual(str(gen), expected)

            self.assertTrue(
                all(i not in gen.str_basic for i in ("s. lat", "s. str"))
            )

        for gid, expected in genus_str_author_map.items():
            gen = self.session.get(Genus, gid)

            self.assertEqual(gen.string(author=True), expected)

        self.assertEqual(str(Genus()), "")

        self.assertEqual(Genus(genus="SPAM").markup(), "SPAM")

        self.assertEqual(
            Genus(genus="Spam", qualifier="s. lat.").markup(),
            "<i>Spam</i> s. lat.",
        )

    def test_can_use_epithet_field(self):
        family = Family(epithet="family")
        genus = Genus(family=family, genus="genus")
        self.session.add_all([family, genus])
        self.session.commit()
        g1 = self.session.query(Genus).filter(Genus.epithet == "genus").one()
        g2 = self.session.query(Genus).filter(Genus.genus == "genus").one()
        self.assertEqual(g1, g2)
        self.assertEqual(g1.genus, "genus")
        self.assertEqual(g2.epithet, "genus")

    def test_count_children_wo_plants(self):
        from ...garden import Accession

        fam = Family(family="Myrtaceae")
        gen = Genus(epithet="Syzygium", family=fam)
        sp = Species(epithet="australe", genus=gen)
        acc = Accession(species=sp, code="1")
        self.session.add_all([fam, gen, sp, acc])
        self.session.commit()

        self.assertEqual(gen.count_children(), 1)

    def test_count_children_w_plant_w_qty(self):
        from ...garden import Accession
        from ...garden import Location

        fam = Family(family="Myrtaceae")
        gen = Genus(epithet="Syzygium", family=fam)
        sp = Species(epithet="australe", genus=gen)
        acc = Accession(species=sp, code="1")
        plant = Plant(
            accession=acc,
            quantity=1,
            location=Location(name="site", code="STE"),
            code="1",
        )
        self.session.add_all([fam, gen, sp, acc, plant])
        self.session.commit()

        self.assertEqual(gen.count_children(), 1)

    def test_count_children_w_plant_w_qty_exclude_inactive_set(self):
        # should be the same as if exclude inactive not set.
        from ...garden import Accession
        from ...garden import Location

        fam = Family(family="Myrtaceae")
        gen = Genus(epithet="Syzygium", family=fam)
        sp = Species(epithet="australe", genus=gen)
        acc = Accession(species=sp, code="1")
        plant = Plant(
            accession=acc,
            quantity=1,
            location=Location(name="site", code="STE"),
            code="1",
        )
        self.session.add_all([fam, gen, sp, acc, plant])
        self.session.commit()

        prefs.prefs[prefs.exclude_inactive_pref] = True

        self.assertEqual(gen.count_children(), 1)

    def test_count_children_w_plant_wo_qty(self):
        from ...garden import Accession
        from ...garden import Location

        fam = Family(family="Myrtaceae")
        gen = Genus(epithet="Syzygium", family=fam)
        sp = Species(epithet="australe", genus=gen)
        acc = Accession(species=sp, code="1")
        plant = Plant(
            accession=acc,
            quantity=0,
            location=Location(name="site", code="STE"),
            code="1",
        )
        self.session.add_all([fam, gen, sp, acc, plant])
        self.session.commit()

        self.assertEqual(gen.count_children(), 1)

    def test_count_children_w_plant_wo_qty_exclude_inactive_set(self):
        from ...garden import Accession
        from ...garden import Location

        fam = Family(family="Myrtaceae")
        gen = Genus(epithet="Syzygium", family=fam)
        sp = Species(epithet="australe", genus=gen)
        acc = Accession(species=sp, code="1")
        plant = Plant(
            accession=acc,
            quantity=0,
            location=Location(name="site", code="STE"),
            code="1",
        )
        self.session.add_all([fam, gen, sp, acc, plant])
        self.session.commit()

        prefs.prefs[prefs.exclude_inactive_pref] = True

        self.assertEqual(gen.count_children(), 0)

    def test_pictures(self):
        from ...garden import Accession
        from ...garden import Location
        from ...garden.plant import PlantPicture

        gen = self.session.query(Genus).first()
        self.assertEqual(gen.pictures, [])
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
        self.assertEqual(gen.pictures, [spic, ppic])
        plt.quantity = 0
        self.session.commit()
        # exclude inactive
        prefs.prefs[prefs.exclude_inactive_pref] = True
        self.assertEqual(gen.pictures, [spic])
        # detached returns empty
        self.session.expunge(gen)
        self.assertEqual(gen.pictures, [])

    def test_has_children(self):
        from ...garden import Accession
        from ...garden import Location

        gen = self.session.get(Genus, 1)
        sp1 = self.session.get(Species, 22)
        acc = Accession(species=sp1, code="1")
        plt = Plant(
            accession=acc,
            quantity=1,
            location=Location(name="site", code="STE"),
            code="1",
        )
        self.session.add(plt)
        self.session.commit()

        self.assertTrue(gen.has_children())

        plt.quantity = 0
        self.session.commit()

        self.assertTrue(gen.has_children())

        prefs.prefs[prefs.exclude_inactive_pref] = True

        # some species active
        self.assertTrue(gen.has_children())

        # make sure only the not active species left
        for sp in gen.species:
            if sp.id != sp1.id:
                self.session.delete(sp)

        self.session.commit()

        self.assertFalse(gen.has_children())

    def test_active_no_species(self):
        gen = self.session.get(Genus, 11)
        # check genus has no species
        self.assertEqual(len(gen.species), 0)
        self.assertFalse(gen.active)
        # test the hybrid_property expression
        # pylint: disable=no-member  # is_
        fam_active_in_db = self.session.query(Genus).filter(
            Genus.active.is_(True)
        )
        self.assertNotIn(gen, fam_active_in_db)

    def test_active_no_accession(self):
        gen = self.session.get(Genus, 9)
        # check this is a family with no accession
        self.assertEqual(
            len([acc for sp in gen.species for acc in sp.accessions]),
            0,
        )
        self.assertTrue(gen.active)
        # test the hybrid_property expression
        # pylint: disable=no-member  # is_
        gen_active_in_db = self.session.query(Genus).filter(
            Genus.active.is_(True)
        )
        self.assertIn(gen, gen_active_in_db)

    def test_active_no_plants(self):
        from ...garden import Accession

        sp = self.session.get(Species, 26)
        gen = sp.genus
        # check this is a family with no plants
        self.assertEqual(
            len(
                [
                    plt
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

        self.assertTrue(gen.active)
        # test the hybrid_property expression
        # pylint: disable=no-member  # is_
        gen_active_in_db = self.session.query(Genus).filter(
            Genus.active.is_(True)
        )
        self.assertIn(gen, gen_active_in_db)

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
        gen = sp.genus

        self.assertTrue(gen.active)
        # test the hybrid_property expression
        # pylint: disable=no-member  # is_
        gen_active_in_db = self.session.query(Genus).filter(
            Genus.active.is_(True)
        )
        self.assertIn(gen, gen_active_in_db)

    def test_active_one_plants_wo_qty(self):
        from ...garden import Accession
        from ...garden import Location

        sp = self.session.get(Species, 26)
        gen = sp.genus
        acc = Accession(code="foo", species=sp)
        plt = Plant(
            code="1", accession=acc, quantity=0, location=Location(code="bar")
        )
        self.session.add_all([acc, plt])
        self.session.commit()

        self.assertFalse(gen.active)
        # test the hybrid_property expression
        # pylint: disable=no-member  # is_
        gen_active_in_db = self.session.query(Genus).filter(
            Genus.active.is_(True)
        )
        self.assertNotIn(gen, gen_active_in_db)


class GenusUpdatedTests(BaubleTestCase):

    def test_updated_self(self):
        fam = Family(epithet="Myrtaceae")
        gen = Genus(epithet="Syzygium", family=fam)
        self.session.add(gen)
        self.session.commit()

        self.assertIs(
            self.session.query(Genus).filter(Genus.updated > "Today").first(),
            gen,
        )

        # the python function
        self.assertEqual(gen.updated, gen._last_updated)

        date = datetime(2001, 1, 1, 0)
        gen._last_updated = date
        self.session.commit()

        self.assertIs(
            self.session.query(Genus).filter(Genus.updated == date).first(),
            gen,
        )

        # the python function
        self.assertEqual(gen.updated, gen._last_updated)

    def test_updated_notes(self):
        date = datetime(2001, 1, 1, 0)
        fam = Family(epithet="Myrtaceae")
        gen = Genus(epithet="Syzygium", family=fam, _last_updated=date)
        note = GenusNote(category="Spam", note="Eggs", genus=gen)
        self.session.add_all([gen, note])
        self.session.commit()

        self.assertIs(
            self.session.query(Genus).filter(Genus.updated > "Today").first(),
            gen,
        )

        # the python function
        self.assertEqual(gen.updated, note._last_updated)

        note._last_updated = datetime(2000, 1, 1, 0)
        self.session.commit()

        self.assertIs(
            self.session.query(Genus).filter(Genus.updated == date).first(),
            gen,
        )

        # the python function
        self.assertEqual(gen.updated, gen._last_updated)

    def test_updated_synonym(self):
        # make sure the date is not now
        date = datetime(2001, 1, 1, 0)
        fam = Family(epithet="Myrtaceae")
        gen = Genus(epithet="Melaleuca", family=fam, _last_updated=date)
        gen2 = Genus(epithet="Callistemon", family=fam, _last_updated=date)
        gen2.accepted = gen
        self.session.add_all([gen, gen2])
        self.session.commit()

        self.assertIs(
            self.session.query(Genus).filter(Genus.updated > "Today").first(),
            gen2,
        )

        # the python function
        self.assertEqual(gen2.updated, gen2._accepted._last_updated)


class GenusTopLevelCountTests(BaubleTestCase):
    def setUp(self):
        super().setUp()
        for data_func in get_setUp_data_funcs():
            data_func()

    def test_top_level_count_w_plant_qty(self):

        expected = (
            "Families: 2, "
            "Genera: 2, "
            "Species: 15, "
            "Accessions: 4, "
            "Plantings: 3, "
            "Living plants: 4, "
            "Locations: 1, "
            "Sources: 1"
        )

        self.assertEqual(str(Genus.top_level_count([1, 3])), expected)

    def test_top_level_count_wo_species(self):
        fam = Family(epithet="Welwitschiaceae")
        gen = Genus(epithet="Welwitschia", family=fam)
        self.session.add(gen)
        self.session.commit()

        expected = (
            "Families: 2, "
            "Genera: 2, "
            "Species: 11, "
            "Accessions: 2, "
            "Plantings: 1, "
            "Living plants: 1, "
            "Locations: 1, "
            "Sources: 1"
        )

        self.assertEqual(str(Genus.top_level_count([1, gen.id])), expected)

    def test_top_level_count_wo_plant_qty(self):
        plt = self.session.get(Plant, 1)
        self.session.delete(plt)
        plt = self.session.get(Plant, 2)
        plt.quantity = 0
        self.session.commit()

        expected = (
            "Families: 2, "
            "Genera: 2, "
            "Species: 15, "
            "Accessions: 4, "
            "Plantings: 2, "
            "Living plants: 3, "
            "Locations: 1, "
            "Sources: 1"
        )

        self.assertEqual(str(Genus.top_level_count([1, 3])), expected)

    def test_top_level_count_wo_plant_qty_exclude_inactive_set(self):
        plt = self.session.get(Plant, 1)
        self.session.delete(plt)
        plt = self.session.get(Plant, 2)
        plt.quantity = 0
        self.session.commit()

        expected = (
            "Families: 2, "
            "Genera: 2, "
            "Species: 15, "
            "Accessions: 3, "
            "Plantings: 1, "
            "Living plants: 3, "
            "Locations: 1, "
            "Sources: 1"
        )

        self.assertEqual(str(Genus.top_level_count([1, 3], True)), expected)


class GenusSynonymyTests(PlantTestCase):
    def setUp(self):
        super().setUp()
        f = (
            self.session.query(Family)
            .filter(Family.family == "Orchidaceae")
            .one()
        )
        bu = Genus(family=f, genus="Bulbophyllum")  # accepted
        zy = Genus(family=f, genus="Zygoglossum")  # synonym
        bu.synonyms.append(zy)
        self.session.add_all([f, bu, zy])
        self.session.commit()

    def test_forward_synonyms(self):
        "a taxon has a list of synonyms"
        bu = (
            self.session.query(Genus)
            .filter(Genus.genus == "Bulbophyllum")
            .one()
        )
        zy = (
            self.session.query(Genus)
            .filter(Genus.genus == "Zygoglossum")
            .one()
        )
        self.assertEqual(bu.synonyms, [zy])
        self.assertEqual(zy.synonyms, [])

    def test_backward_synonyms(self):
        "synonymy is used to get the accepted taxon"
        bu = (
            self.session.query(Genus)
            .filter(Genus.genus == "Bulbophyllum")
            .one()
        )
        zy = (
            self.session.query(Genus)
            .filter(Genus.genus == "Zygoglossum")
            .one()
        )
        self.assertEqual(zy.accepted, bu)
        self.assertEqual(bu.accepted, None)

    def test_define_accepted(self):
        # notice that same test should be also in Species and Family
        bu = (
            self.session.query(Genus)
            .filter(Genus.genus == "Bulbophyllum")
            .one()
        )
        f = (
            self.session.query(Family)
            .filter(Family.family == "Orchidaceae")
            .one()
        )
        he = Genus(family=f, genus="Henosis")  # one more synonym
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
        claceae = Family(family="Crassulaceae")  # J. St.-Hil.
        villa = Genus(family=claceae, genus="Villadia", author="Rose")
        alta = Genus(family=claceae, genus="Altamiranoa", author="Rose")
        alta.accepted = villa
        self.session.add_all([claceae, alta, villa])
        self.session.commit()

        sedum = Genus(family=claceae, genus="Sedum", author="L.")
        alta.accepted = sedum
        self.session.commit()

    def test_no_synonyms_means_itself_accepted(self):
        gen = Genus(id=51, epithet="TestGenus", family_id=1)
        self.session.add(gen)
        self.session.commit()

        self.assertEqual(gen.accepted, None)

    def test_synonyms_and_accepted_properties(self):
        def create_tmp_gen(id_):
            gen = Genus(id=id_, epithet=f"gen{id_}", family_id=1)
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


class RetrieveTests(PlantTestCase):

    def test_genus_retreives_full_data(self):
        keys = {
            "epithet": "Encyclia",
            "family.epithet": "Orchidaceae",
        }
        gen = Genus.retrieve(self.session, keys)
        self.assertEqual(gen.id, 2)

        keys = {
            "genus": "Encyclia",
            "family.family": "Orchidaceae",
        }
        gen = Genus.retrieve(self.session, keys)
        self.assertEqual(gen.id, 2)

    def test_genus_retreives_genus_only_unique_genus(self):
        keys = {
            "epithet": "Encyclia",
        }
        gen = Genus.retrieve(self.session, keys)
        self.assertEqual(gen.id, 2)

        keys = {
            "genus": "Encyclia",
        }
        gen = Genus.retrieve(self.session, keys)
        self.assertEqual(gen.id, 2)

    def test_genus_retreives_id_only(self):
        keys = {"id": 5}
        genus = Genus.retrieve(self.session, keys)
        self.assertEqual(genus.genus, "Paphiopedilum")

    def test_genus_doesnt_retreive_family_only(self):
        keys = {
            "family.family": "Orchidaceae",
        }
        genus = Genus.retrieve(self.session, keys)
        self.assertIsNone(genus)
        # single genus family
        keys = {
            "family.family": "Solanaceae",
        }
        genus = Genus.retrieve(self.session, keys)
        self.assertIsNone(genus)

    def test_genus_doesnt_retreive_non_existent(self):
        keys = {"family.family": "Orchidaceae", "genus": "Nonexistent"}
        genus = Genus.retrieve(self.session, keys)
        self.assertIsNone(genus)

    def test_genus_doesnt_retreive_wrong_keys(self):
        keys = {
            "name": "Somewhere Else",
            "code": "SE",
        }
        genus = Genus.retrieve(self.session, keys)
        self.assertIsNone(genus)

    def test_genus_retreive_2_entries_diff_authors(self):
        eric = Family(family="Ericaceae")
        g1 = Genus(genus="Azalea", author="L.", family=eric)
        g2 = Genus(genus="Azalea", author="Gaertn.", family=eric)
        self.session.add_all([g1, g2])
        self.session.commit()
        # fails, not unique
        keys = {
            "family": "Ericaceae",
            "genus": "Azalea",
        }
        genus = Genus.retrieve(self.session, keys)
        self.assertIsNone(genus)
        # with author suceeds
        keys = {"family": "Ericaceae", "genus": "Azalea", "author": "L."}
        genus = Genus.retrieve(self.session, keys)
        self.assertEqual(genus, g1)

        keys = {"family": "Ericaceae", "genus": "Azalea", "author": "Gaertn."}
        genus = Genus.retrieve(self.session, keys)
        self.assertEqual(genus, g2)
