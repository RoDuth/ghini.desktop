# pylint: disable=no-self-use,protected-access,too-many-public-methods
# pylint: disable=too-many-lines,too-many-statements
# Copyright 2008-2010 Brett Adams
# Copyright 2015 Mario Frasca <mario@anche.no>.
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
Species models tests
"""
from datetime import datetime
from functools import partial
from unittest import TestCase

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.exc import StatementError
from sqlalchemy.orm.exc import NoResultFound

from bauble import btypes
from bauble import db
from bauble import prefs
from bauble.meta import BaubleMeta
from bauble.test import BaubleTestCase
from bauble.test import get_setUp_data_funcs

from ...garden import Plant
from ..family import Family
from ..genus import Genus
from ..geography import Geography
from ..species import DefaultVernacularName
from ..species import Species
from ..species import SpeciesDistribution
from ..species import SpeciesNote
from ..species import SpeciesPicture
from ..species import SpeciesSynonym
from ..species import VernacularName
from ..species import _remove_zws as remove_zws
from ..species import markup_italics
from ..species import register_custom_column
from ..species import update_all_full_names_task
from .test_plants import PlantTestCase
from .test_plants import setUp_data as setup_plants_data

species_str_map = {
    1: "Maxillaria s. str variabilis",
    2: "Encyclia cochleata",
    3: "Abrus precatorius",
    4: "Campyloneurum × alapense",
    5: "Encyclia cochleata var. cochleata",
    6: "Encyclia cochleata 'Black Night'",
    7: "Abrus precatorius SomethingRidiculous Group",
    8: "Abrus precatorius (SomethingRidiculous Group) 'Hot Rio Nights'",
    9: "Maxillaria s. str × generalis 'Red'",
    10: "Maxillaria s. str × generalis (SomeGroup Group) 'Red'",
    11: "Maxillaria s. str generalis agg.",
    12: "Maxillaria s. str SomeGroup Group",
    13: "Maxillaria s. str 'Red'",
    14: "Maxillaria s. str 'Red & Blue'",
    15: "Encyclia cochleata subsp. cochleata var. cochleata 'Black'",
    16: "Maxillaria s. str test subsp. test SomeGroup Group",
    25: "+ Crataegomespilus dardarii",
    26: "× Butyagrus nabonnandii",
    27: "Cynodon dactylon × transvaalensis 'DT-1' (PBR) TIFTUF™",
    28: "Abrus precatorius subsp. africanus",
    29: "Paphiopedilum Jim Kie grex 'Springwater'",
    33: "Eucalyptus gillii s. lat.",
    34: "× Rhynchosophrocattleya Marie Lemon Stick grex Francis Suzuki Group",
    35: "Bletilla Penway Prelude grex (Penway Dancer Group) 'Ballerina'",
}

species_markup_map = {
    1: "<i>Maxillaria</i> s. str <i>variabilis</i>",
    2: "<i>Encyclia</i> <i>cochleata</i>",
    3: "<i>Abrus</i> <i>precatorius</i>",
    4: "<i>Campyloneurum</i> × <i>alapense</i>",
    5: "<i>Encyclia</i> <i>cochleata</i> var. <i>cochleata</i>",
    6: "<i>Encyclia</i> <i>cochleata</i> 'Black Night'",
    12: "<i>Maxillaria</i> s. str SomeGroup Group",
    14: "<i>Maxillaria</i> s. str 'Red &amp; Blue'",
    15: (
        "<i>Encyclia</i> <i>cochleata</i> subsp. <i>"
        "cochleata</i> var. <i>cochleata</i> 'Black'"
    ),
    25: "+ <i>Crataegomespilus</i> <i>dardarii</i>",
    26: "× <i>Butyagrus</i> <i>nabonnandii</i>",
    27: (
        "<i>Cynodon</i> <i>dactylon</i> × <i>transvaalensis</i> 'DT-1' "
        "<small>(PBR)</small> T<small>IF</small>T<small>UF</small>™"
    ),
    29: "<i>Paphiopedilum</i> Jim Kie grex 'Springwater'",
    34: (
        "× <i>Rhynchosophrocattleya</i> Marie Lemon Stick grex "
        "Francis Suzuki Group"
    ),
    35: (
        "<i>Bletilla</i> Penway Prelude grex (Penway Dancer Group) "
        "'Ballerina'"
    ),
}

species_str_authors_map = {
    1: "Maxillaria s. str variabilis Bateman ex Lindl.",
    2: "Encyclia cochleata (L.) Lem\xe9e",
    3: "Abrus precatorius L.",
    4: "Campyloneurum × alapense F\xe9e",
    5: "Encyclia cochleata (L.) Lem\xe9e var. cochleata",
    6: "Encyclia cochleata (L.) Lem\xe9e 'Black Night'",
    7: "Abrus precatorius L. SomethingRidiculous Group",
    8: "Abrus precatorius L. (SomethingRidiculous Group) 'Hot Rio Nights'",
    15: (
        "Encyclia cochleata L. subsp. "
        "cochleata L. var. cochleata L. 'Black'"
    ),
    28: "Abrus precatorius subsp. africanus Verdc.",
}

species_markup_authors_map = {
    1: "<i>Maxillaria</i> s. str <i>variabilis</i> Bateman ex Lindl.",
    2: "<i>Encyclia</i> <i>cochleata</i> (L.) Lem\xe9e",
    3: "<i>Abrus</i> <i>precatorius</i> L.",
    4: "<i>Campyloneurum</i> × <i>alapense</i> F\xe9e",
    5: "<i>Encyclia</i> <i>cochleata</i> (L.) Lem\xe9e var. <i>cochleata</i>",
    6: "<i>Encyclia</i> <i>cochleata</i> (L.) Lem\xe9e 'Black Night'",
}

species_searchview_markup_map = {
    1: (
        '<i>Maxillaria</i> s. str <i>variabilis</i> <span weight="light">'
        "Bateman ex Lindl.</span>"
    ),
    27: (
        "<i>Cynodon</i> <i>dactylon</i> × <i>transvaalensis</i> 'DT-1' "
        '<span weight="light"><small>(PBR)</small></span> '
        "T<small>IF</small>T<small>UF</small>™"
    ),
    28: (
        "<i>Abrus</i> <i>precatorius</i> subsp. <i>africanus</i> "
        '<span weight="light">Verdc.</span>'
    ),
}


class SpeciesTests(PlantTestCase):
    def test_str(self):
        """
        Test the Species.string() method
        """

        def get_sp_str(id_, **kwargs):
            return self.session.get(Species, id_).string(**kwargs)

        for sid, expect in species_str_map.items():
            sp = self.session.get(Species, sid)
            printable_name = remove_zws(str(sp))
            self.assertEqual(expect, printable_name)
            spstr = get_sp_str(sid)
            self.assertEqual(remove_zws(spstr), expect)

            self.assertTrue(
                all(
                    i not in sp.str_basic for i in ("s. lat", "s. str", "agg.")
                )
            )

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
            spstr = get_sp_str(
                sid, markup=True, authors=True, for_search_view=True
            )
            self.assertEqual(remove_zws(spstr), expect)

    def test_search_view_markup_pair(self):
        sp1 = (
            self.session.query(Species)
            .join(Genus)
            .filter(Genus.epithet == "Maxillaria")
            .filter(Species.epithet == "variabilis")
            .one()
        )
        sp2 = (
            self.session.query(Species)
            .join(Genus)
            .filter(Genus.epithet == "Laelia")
            .filter(Species.epithet == "lobata")
            .one()
        )
        # set the default
        sp1.default_vernacular_name = sp1.vernacular_names[0]
        first, second = sp1.search_view_markup_pair()
        self.assertTrue(
            remove_zws(first).startswith(
                "<i>Maxillaria</i> s. str <i>variabilis</i>"
            )
        )
        expect = (
            '<i>Maxillaria</i> s. str <i>variabilis</i> <span weight="light">'
            'Bateman ex Lindl.</span><span foreground="#555555" size="small" '
            'weight="light"> - synonym of <i>Encyclia</i> <i>cochleata</i> '
            "(L.) Lemée</span>"
        )
        self.assertEqual(remove_zws(first), expect)
        self.assertEqual(
            second,
            "Orchidaceae -- "
            "SomeName, "
            '<span foreground="#555555" weight="light">SomeName 2</span>',
        )
        first, second = sp2.search_view_markup_pair()
        self.assertEqual(remove_zws(first), "<i>Laelia</i> <i>lobata</i>")
        self.assertEqual(second, "Orchidaceae")

    def test_lexicographic_order__unspecified_precedes_specified(self):
        def get_sp_str(id_, **kwargs):
            return self.session.get(Species, id_).string(**kwargs)

        self.assertTrue(get_sp_str(1) > get_sp_str(22))
        self.assertTrue(get_sp_str(1) > get_sp_str(23))
        self.assertTrue(get_sp_str(1) > get_sp_str(24))
        self.assertTrue(get_sp_str(16) > get_sp_str(22))
        self.assertTrue(get_sp_str(16) > get_sp_str(23))
        self.assertTrue(get_sp_str(16) > get_sp_str(24))

    def test_vernacular_name(self):
        """
        Test the Species.vernacular_name property
        """
        family = Family(family="family")
        genus = Genus(family=family, genus="genus")
        sp = Species(genus=genus, sp="sp")
        self.session.add_all([family, genus, sp])
        self.session.commit()

        # add a name
        vn = VernacularName(name="name")
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
        family = Family(family="family")
        genus = Genus(family=family, genus="genus")
        sp = Species(genus=genus, sp="sp")
        vn = VernacularName(name="name")
        sp.vernacular_names.append(vn)
        self.session.add_all([family, genus, sp, vn])
        self.session.commit()

        # test that setting the default vernacular names
        default = VernacularName(name="default")
        sp.default_vernacular_name = default
        self.session.commit()
        self.assertTrue(vn in sp.vernacular_names)
        self.assertTrue(sp.default_vernacular_name == default)

        # test that set_attr work on default vernacular name
        default = VernacularName(name="default2")
        setattr(sp, "default_vernacular_name", default)
        self.session.commit()
        self.assertTrue(vn in sp.vernacular_names)
        self.assertTrue(default in sp.vernacular_names)
        self.assertTrue(sp.default_vernacular_name == default)

        # test that if you set the default_vernacular_name on a
        # species then it automatically adds it to vernacular_names
        default = VernacularName(name="default3")
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
        vn1 = VernacularName(name="vn1")
        vn2 = VernacularName(name="vn2")
        sp.default_vernacular_name = vn1
        sp.default_vernacular_name = vn2
        self.session.commit()

        # test hybrid property setter and expression
        q = (
            self.session.query(Species)
            .filter(Species.default_vernacular_name == "vn2")
            .one()
        )
        self.assertEqual(q, sp)
        sp.default_vernacular_name = "hybrid set"
        self.session.commit()
        self.assertEqual(sp.default_vernacular_name.name, "hybrid set")
        self.assertIsNone(sp.default_vernacular_name.language)
        # Test the language is added
        sp.default_vernacular_name = "set hybrid:Lang"
        self.session.commit()
        self.assertEqual(sp.default_vernacular_name.name, "set hybrid")
        self.assertEqual(sp.default_vernacular_name.language, "Lang")

    def test_accepted_low_level(self):
        sp1 = self.session.get(Species, 2)
        sp2 = self.session.get(Species, 3)
        sp3 = self.session.get(Species, 4)
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
        # test that appending a synonym works using species.synonyms
        sp1 = self.session.get(Species, 1)
        sp2 = self.session.get(Species, 2)
        sp1.synonyms.append(sp2)
        self.session.flush()
        self.assertTrue(sp2 in sp1.synonyms)

        # test that removing a synonyms works using species.synonyms
        sp1.synonyms.remove(sp2)
        self.session.flush()
        self.assertFalse(sp2 in sp1.synonyms)

        self.session.expunge_all()

        # test that appending a synonym works using species._synonyms
        sp1 = self.session.get(Species, 1)
        sp2 = self.session.get(Species, 2)
        syn = SpeciesSynonym(synonym=sp2)
        sp1._synonyms.append(syn)
        self.session.flush()
        self.assertTrue(sp2 in sp1.synonyms)

        # test that removing a synonyms works using species._synonyms
        sp1._synonyms.remove(syn)
        self.session.flush()
        self.assertFalse(sp2 in sp1.synonyms)

        # test adding a species and then immediately remove it
        self.session.expunge_all()
        sp1 = self.session.get(Species, 1)
        sp2 = self.session.get(Species, 2)
        sp1.synonyms.append(sp2)
        sp1.synonyms.remove(sp2)
        import warnings

        # SAWarning: Object of type <SpeciesSynonym> not in session, add
        # operation along 'Species._accepted' will not proceed
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            self.session.commit()
        assert sp2 not in sp1.synonyms

        # add a species and immediately add the same species
        sp2 = self.session.get(Species, 2)
        sp1.synonyms.append(sp2)
        sp1.synonyms.remove(sp2)
        sp1.synonyms.append(sp2)
        # self.session.flush() # shouldn't raise an error
        self.session.commit()
        assert sp2 in sp1.synonyms

        # test that deleting a species removes it from the synonyms list
        assert sp2 in sp1.synonyms
        self.session.delete(sp2)
        self.session.commit()
        assert sp2 not in sp1.synonyms
        # but doesn't delete the species it referes to.
        self.assertTrue(self.session.get(Species, sp1.id))

        # test that deleting a species that has synonyms deletes all
        # the synonyms that refer to that species
        sp3 = Species(genus=self.session.get(Genus, 1), epithet="three")
        self.session.add(sp3)
        sp1.synonyms.append(sp3)
        self.session.commit()
        self.session.delete(sp1)
        self.session.commit()
        self.assertTrue(self.session.query(SpeciesSynonym).count() == 0)

    def test_adding_synonym_doesnt_add_sp_history_entry(self):
        # update all full names so listens_for doesn't make the a change
        list(update_all_full_names_task())
        sp1 = self.session.get(Species, 5)
        sp2 = self.session.get(Species, 6)
        hist_start = self.session.query(db.History).count()
        # this should not update the species
        sp1.synonyms.append(sp2)
        self.session.commit()
        hist_end = self.session.query(db.History).count()
        self.assertEqual(hist_end, hist_start + 1)

    def test_no_synonyms_means_itself_accepted(self):
        def create_tmp_sp(id_):
            sp = Species(id=id_, epithet=f"sp{id_}", genus_id=1)
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
        def create_tmp_sp(id_):
            sp = Species(id=id_, epithet=f"sp{id_}", genus_id=1)
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
        self.assertEqual(sp2.accepted.epithet, sp1.epithet)  # just added
        self.assertEqual(sp3.accepted.epithet, sp1.epithet)  # no change
        sp2.accepted = sp4  # (1 3), (4 2)
        self.session.flush()
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

    def test_synonym_str(self):
        syn = self.session.execute(select(SpeciesSynonym)).scalar()
        self.assertEqual(str(syn), syn.synonym.string(author=True))

    def test_synonym_markup(self):
        syn = self.session.execute(select(SpeciesSynonym)).scalar()
        self.assertEqual(syn.markup(), syn.synonym.markup(authors=True))

    def test_active_no_accessions(self):

        fam = Family(family="Myrtaceae")
        gen = Genus(epithet="Syzygium", family=fam)
        sp = Species(epithet="australe", genus=gen)
        self.session.add_all([fam, gen, sp])
        self.session.commit()
        self.assertTrue(sp.active)
        # test the hybrid_property expression
        # pylint: disable=no-member
        sp_active_in_db = self.session.query(Species).filter(
            Species.active.is_(True)
        )
        self.assertIn(sp, sp_active_in_db)

    def test_active_no_plants(self):
        from ...garden.accession import Accession

        fam = Family(family="Myrtaceae")
        gen = Genus(epithet="Syzygium", family=fam)
        sp = Species(epithet="australe", genus=gen)
        acc = Accession(species=sp, code="1")
        self.session.add_all([fam, gen, sp, acc])
        self.session.commit()
        self.assertTrue(sp.active)
        # test the hybrid_property expression
        # pylint: disable=no-member
        sp_active_in_db = self.session.query(Species).filter(
            Species.active.is_(True)
        )
        self.assertIn(sp, sp_active_in_db)

    def test_active_plants_w_qty(self):
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
        self.assertTrue(sp.active)
        # test the hybrid_property expression
        # pylint: disable=no-member
        sp_active_in_db = self.session.query(Species).filter(
            Species.active.is_(True)
        )
        self.assertIn(sp, sp_active_in_db)

    def test_active_plants_wo_qty(self):
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
        self.assertFalse(sp.active)
        self.assertFalse(plant.active)
        # test the hybrid_property expression
        # pylint: disable=no-member
        sp_active_in_db = self.session.query(Species).filter(
            Species.active.is_(True)
        )
        self.assertNotIn(sp, sp_active_in_db)

    def test_count_children_wo_plants(self):
        from ...garden import Accession

        fam = Family(family="Myrtaceae")
        gen = Genus(epithet="Syzygium", family=fam)
        sp = Species(epithet="australe", genus=gen)
        acc = Accession(species=sp, code="1")
        self.session.add_all([fam, gen, sp, acc])
        self.session.commit()

        self.assertEqual(sp.count_children(), 1)

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

        self.assertEqual(sp.count_children(), 1)

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

        self.assertEqual(sp.count_children(), 1)

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

        self.assertEqual(sp.count_children(), 1)

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

        self.assertEqual(sp.count_children(), 0)

    def test_custom_column_acts_as_unicode_before_init(self):
        sp = self.session.query(Species).first()
        sp._sp_custom1 = "test"
        self.session.commit()
        self.assertEqual(sp._sp_custom1, "test")

    def test_custom_column(self):
        meta = BaubleMeta(
            name="_sp_custom1",
            value=(
                "{'field_name': 'nca_status', "
                "'display_name': 'NCA Status', "
                "'values': ('extinct', 'vulnerable', None)}"
            ),
        )
        self.session.add(meta)
        self.session.commit()

        register_custom_column("_sp_custom1")

        self.assertTrue(hasattr(Species, "nca_status"))
        self.assertEqual(
            Species._sp_custom1.prop.columns[0].type.values,
            ("extinct", "vulnerable", None),
        )
        self.assertRaises(
            btypes.EnumError,
            Species._sp_custom1.prop.columns[0].type.process_bind_param,
            "test",
            None,
        )
        sp = self.session.get(Species, 1)
        self.assertEqual(
            sp.__table__.c["_sp_custom1"].type.values,
            ("extinct", "vulnerable", None),
        )
        self.assertRaises(
            btypes.EnumError,
            sp.__table__.c["_sp_custom1"].type.process_bind_param,
            "test",
            None,
        )

        sp.nca_status = "vulnerable"
        self.session.commit()

        # restart connection
        self.session.close()
        db.open_conn(db.engine.url)
        self.session = db.Session()
        sp = self.session.get(Species, 1)

        self.assertEqual(sp.nca_status, "vulnerable")
        # can't set value when not in values
        with self.assertRaises(AttributeError):
            sp.nca_status = "test"
        self.assertEqual(sp.nca_status, "vulnerable")

        with self.assertRaises(StatementError):
            sp._sp_custom1 = "test"
            self.session.commit()
        self.session.rollback()
        self.assertEqual(sp.nca_status, "vulnerable")
        sp.nca_status = "extinct"
        self.session.commit()
        # test can filter by custom column
        session = db.Session()
        qry = session.query(Species).filter(Species.nca_status == "extinct")
        self.assertEqual(qry.first().id, sp.id)
        session.close()
        # cleanup
        self.session.delete(meta)
        self.session.commit()
        register_custom_column("_sp_custom1")

        # reset the connection (similar to opening a new connection, also
        # reruns register_custom_column etc.)
        # tearDown needed to delete temp config file or conftest.py will fail
        # to cleanup tempfiles at end of tests
        self.tearDown()
        self.setUp()
        self.assertFalse(hasattr(Species, "nca_status"))

    def test_family_name_hybrid_property(self):
        # property
        sp = self.session.get(Species, 1)
        self.assertEqual(sp.family_name, "Orchidaceae")
        # expression
        palms = self.session.query(Species.id).filter(
            Species.family_name == "Arecaceae"
        )
        palm_ids = [i[0] for i in palms]
        self.assertCountEqual(palm_ids, [26])

    def test_pictures_property_wo_pics(self):
        sp = self.session.get(Species, 1)
        self.assertEqual(sp.pictures, [])

    def test_pictures_property_w_pics(self):
        sp = self.session.get(Species, 1)
        pic1 = SpeciesPicture(picture="test1.jpg")
        sp._pictures.append(pic1)
        self.assertEqual(sp.pictures, [pic1])

    def test_pictures_property_w_plant_pics(self):
        from ...garden import Accession
        from ...garden import Location
        from ...garden.plant import PlantPicture

        fam = Family(family="Myrtaceae")
        gen = Genus(epithet="Syzygium", family=fam)
        sp = Species(epithet="australe", genus=gen)
        acc = Accession(species=sp, code="1")
        loc = Location(name="site", code="STE")
        plant = Plant(
            accession=acc,
            quantity=1,
            location=loc,
            code="1",
        )
        pic1 = PlantPicture(picture="test1.jpg")
        plant.pictures.append(pic1)
        plant2 = Plant(
            accession=acc,
            quantity=1,
            location=loc,
            code="2",
        )
        pic2 = PlantPicture(picture="test2.jpg")
        plant2.pictures.append(pic2)
        self.session.add_all([plant, plant2])
        self.session.commit()
        self.assertCountEqual(sp.pictures, [pic1, pic2])

    def test_pictures_property_w_pics_and_plant_pics(self):
        from ...garden import Accession
        from ...garden import Location
        from ...garden.plant import PlantPicture

        fam = Family(family="Myrtaceae")
        gen = Genus(epithet="Syzygium", family=fam)
        sp = Species(epithet="australe", genus=gen)
        pic1 = SpeciesPicture(picture="test1.jpg")
        sp._pictures.append(pic1)
        acc = Accession(species=sp, code="1")
        loc = Location(name="site", code="STE")
        plant = Plant(
            accession=acc,
            quantity=1,
            location=loc,
            code="1",
        )
        pic2 = PlantPicture(picture="test1.jpg")
        plant.pictures.append(pic2)
        plant2 = Plant(
            accession=acc,
            quantity=1,
            location=loc,
            code="2",
        )
        pic3 = PlantPicture(picture="test2.jpg")
        plant2.pictures.append(pic3)
        self.session.add_all([plant, plant2])
        self.session.commit()
        self.assertCountEqual(sp.pictures, [pic1, pic2, pic3])
        # exclude inactive
        plant2.quantity = 0
        self.session.commit()
        prefs.prefs[prefs.exclude_inactive_pref] = True
        self.assertCountEqual(sp.pictures, [pic1, pic2])
        # detached returns empty
        self.session.expunge(sp)
        self.assertEqual(sp.pictures, [])

    def test_get_kids(self):
        sp = self.session.get(Species, 1)
        self.assertEqual(partial(db.natsort, "accessions")(sp), [])


class SpeciesUpdatedTests(BaubleTestCase):

    def test_updated_self(self):
        fam = Family(epithet="Myrtaceae")
        gen = Genus(epithet="Syzygium", family=fam)
        sp = Species(epithet="luehmannii", genus=gen)
        self.session.add(sp)
        self.session.commit()

        self.assertIs(
            self.session.query(Species)
            .filter(Species.updated > "Today")
            .first(),
            sp,
        )

        # the python function
        self.assertEqual(sp.updated, sp._last_updated)

        date = datetime(2001, 1, 1, 0)
        sp._last_updated = date
        self.session.commit()

        self.assertIs(
            self.session.query(Species)
            .filter(Species.updated == date)
            .first(),
            sp,
        )

        # the python function
        self.assertEqual(sp.updated, sp._last_updated)

    def test_updated_notes(self):
        date = datetime(2001, 1, 1, 0)
        fam = Family(epithet="Myrtaceae")
        gen = Genus(epithet="Syzygium", family=fam)
        sp = Species(epithet="luehmannii", genus=gen, _last_updated=date)
        note = SpeciesNote(category="Spam", note="Eggs", species=sp)
        self.session.add_all([sp, note])
        self.session.commit()

        self.assertIs(
            self.session.query(Species)
            .filter(Species.updated > "Today")
            .first(),
            sp,
        )

        # the python function
        self.assertEqual(sp.updated, note._last_updated)

        note._last_updated = datetime(2000, 1, 1, 0)
        self.session.commit()

        self.assertIs(
            self.session.query(Species)
            .filter(Species.updated == date)
            .first(),
            sp,
        )

        # the python function
        self.assertEqual(sp.updated, sp._last_updated)

    def test_updated_pictures(self):
        date = datetime(2001, 1, 1, 0)
        fam = Family(epithet="Myrtaceae")
        gen = Genus(epithet="Syzygium", family=fam)
        sp = Species(epithet="luehmannii", genus=gen, _last_updated=date)
        pic = SpeciesPicture(category="Spam", picture="Eggs.png", species=sp)
        self.session.add_all([sp, pic])
        self.session.commit()

        self.assertIs(
            self.session.query(Species)
            .filter(Species.updated > "Today")
            .first(),
            sp,
        )

        # the python function
        self.assertEqual(sp.updated, pic._last_updated)

        pic._last_updated = datetime(2000, 1, 1, 0)
        self.session.commit()

        self.assertIs(
            self.session.query(Species)
            .filter(Species.updated == date)
            .first(),
            sp,
        )

        # the python function
        self.assertEqual(sp.updated, sp._last_updated)

    def test_updated_synonym(self):
        # make sure the date is not now
        date = datetime(2001, 1, 1, 0)
        fam = Family(epithet="Myrtaceae")
        gen = Genus(epithet="Melaleuca", family=fam)
        gen2 = Genus(epithet="Callistemon", family=fam)
        sp1 = Species(epithet="viminalis", genus=gen, _last_updated=date)
        sp2 = Species(epithet="viminalis", genus=gen2, _last_updated=date)
        sp2.accepted = sp1
        self.session.add_all([sp1, sp2])
        self.session.commit()

        self.assertIs(
            self.session.query(Species)
            .filter(Species.updated > "Today")
            .first(),
            sp2,
        )

        # the python function
        self.assertEqual(sp2.updated, sp2._accepted._last_updated)

    def test_updated_distribution(self):
        # make sure the date is not now
        date = datetime(2001, 1, 1, 0)
        fam = Family(epithet="Myrtaceae")
        gen = Genus(epithet="Melaleuca", family=fam)
        sp = Species(epithet="viminalis", genus=gen, _last_updated=date)
        geo = Geography(name="Fiji", code="FIJ", level="1")
        sp.distribution.append(SpeciesDistribution(geography=geo))
        self.session.add(sp)
        self.session.commit()

        self.assertIs(
            self.session.query(Species)
            .filter(Species.updated > "Today")
            .first(),
            sp,
        )

        # the python function
        self.assertEqual(sp.updated, sp.distribution[0]._last_updated)
        self.assertNotEqual(sp.updated, sp._last_updated)

    def test_updated_vernacular_name(self):
        # make sure the date is not now
        date = datetime(2001, 1, 1, 0)
        fam = Family(epithet="Myrtaceae")
        gen = Genus(epithet="Melaleuca", family=fam)
        sp = Species(epithet="viminalis", genus=gen, _last_updated=date)
        vern = VernacularName(name="Bottle Brush")
        sp.vernacular_names.append(vern)
        self.session.add(sp)
        self.session.commit()

        self.assertIs(
            self.session.query(Species)
            .filter(Species.updated > "Today")
            .first(),
            sp,
        )

        # the python function
        self.assertEqual(sp.updated, sp.vernacular_names[0]._last_updated)
        self.assertNotEqual(sp.updated, sp._last_updated)


class SpeciesTopLevelCountTests(BaubleTestCase):
    def setUp(self):
        super().setUp()
        for data_func in get_setUp_data_funcs():
            data_func()

    def test_top_level_count_w_plant_qty(self):

        expected = (
            "Families: 2, "
            "Genera: 2, "
            "Species: 2, "
            "Accessions: 4, "
            "Plantings: 3, "
            "Living plants: 4, "
            "Locations: 1, "
            "Sources: 1"
        )

        self.assertEqual(str(Species.top_level_count([1, 3])), expected)

    def test_top_level_count_wo_plant_qty(self):
        plt = self.session.get(Plant, 1)
        self.session.delete(plt)
        plt = self.session.get(Plant, 2)
        plt.quantity = 0
        self.session.commit()

        expected = (
            "Families: 2, "
            "Genera: 2, "
            "Species: 2, "
            "Accessions: 4, "
            "Plantings: 2, "
            "Living plants: 3, "
            "Locations: 1, "
            "Sources: 1"
        )

        self.assertEqual(str(Species.top_level_count([1, 3])), expected)

    def test_top_level_count_wo_plant_qty_exclude_inactive_set(self):
        plt = self.session.get(Plant, 1)
        self.session.delete(plt)
        plt = self.session.get(Plant, 2)
        plt.quantity = 0
        self.session.commit()

        expected = (
            "Families: 2, "
            "Genera: 2, "
            "Species: 2, "
            "Accessions: 3, "
            "Plantings: 1, "
            "Living plants: 3, "
            "Locations: 1, "
            "Sources: 1"
        )

        self.assertEqual(str(Species.top_level_count([1, 3], True)), expected)

    def test_top_level_count_sp_wo_plant_qty_exclude_inactive_set(self):
        plt = self.session.get(Plant, 1)
        for acc in plt.accession.species.accessions:

            if not acc.plants:
                self.session.delete(acc)
                continue

            for plt in acc.plants:
                plt.quantity = 0

        self.session.commit()

        expected = (
            "Families: 1, "
            "Genera: 1, "
            "Species: 1, "
            "Accessions: 1, "
            "Plantings: 1, "
            "Living plants: 3, "
            "Locations: 1, "
            "Sources: 0"
        )

        self.assertEqual(str(Species.top_level_count([1, 3], True)), expected)

    def test_top_level_count_sp_no_accessions(self):

        expected = (
            "Families: 2, "
            "Genera: 2, "
            "Species: 2, "
            "Accessions: 2, "
            "Plantings: 1, "
            "Living plants: 1, "
            "Locations: 1, "
            "Sources: 1"
        )

        # 4 has no accessions
        self.assertEqual(str(Species.top_level_count([1, 4])), expected)


class VernacularNameTests(BaubleTestCase):

    def test_search_view_markup_pair(self):
        setup_plants_data()
        ver_name = self.session.get(VernacularName, 1)
        first, second = ver_name.search_view_markup_pair()
        self.assertEqual(
            remove_zws(second), "<i>Maxillaria</i> s. str <i>variabilis</i>"
        )
        self.assertEqual(first, "SomeName")

    def test_has_children_same_as_species(self):
        for vern in self.session.query(VernacularName):

            self.assertEqual(vern.has_children(), vern.species.has_children())

    def test_count_children_same_as_species(self):
        for vern in self.session.query(VernacularName):

            self.assertEqual(
                vern.count_children(), vern.species.count_children()
            )

    def test_pictures_same_as_species(self):
        for vern in self.session.query(VernacularName):
            sp_pic = SpeciesPicture(picture="foo.jpg")
            vern.species.pictures.append(sp_pic)

            self.assertEqual(vern.pictures, vern.species.pictures)

    def test_active_same_as_species(self):
        for vern in self.session.query(VernacularName):

            self.assertEqual(vern.active, vern.species.active)

    def test_active_expresion_returns_same_as_species(self):
        # pylint: disable=no-member
        verns = self.session.query(VernacularName).filter(
            VernacularName.active.is_(True)
        )
        spp = self.session.query(Species).filter(Species.active.is_(True))

        self.assertCountEqual(
            [i.id for i in spp], [i.species.id for i in verns]
        )

    def test_top_level_count_same_as_species(self):
        for data_func in get_setUp_data_funcs():
            data_func()

        verns = self.session.query(VernacularName).all()
        vern_ids = [i.id for i in verns]
        sp_ids = [i.species_id for i in verns]

        self.assertEqual(
            str(VernacularName.top_level_count(vern_ids)),
            str(Species.top_level_count(sp_ids)),
        )

        self.assertEqual(
            VernacularName.top_level_count(vern_ids, True),
            Species.top_level_count(sp_ids, True),
        )

    def test_vernname_get_kids(self):
        setup_plants_data()
        ver_name = self.session.get(VernacularName, 1)
        self.assertEqual(
            partial(db.natsort, "species.accessions")(ver_name), []
        )


class MarkupItalicsTests(TestCase):
    def test_markup_simple(self):
        self.assertEqual(markup_italics("sp."), "sp.")
        self.assertEqual(markup_italics("spp."), "spp.")
        self.assertEqual(markup_italics("cv."), "cv.")
        self.assertEqual(markup_italics("cvs."), "cvs.")
        self.assertEqual(markup_italics("viminalis"), "<i>viminalis</i>")
        # with ZWS
        self.assertEqual(
            markup_italics("\u200bviminalis"), "\u200b<i>viminalis</i>"
        )
        self.assertEqual(markup_italics("crista-galli"), "<i>crista-galli</i>")

    def test_markup_provisory(self):
        self.assertEqual(
            markup_italics("sp. (Shute Harbour L.J.Webb+ 7916)"),
            "sp. (Shute Harbour L.J.Webb+ 7916)",
        )
        self.assertEqual(
            markup_italics("caerulea (Shute Harbour)"),
            "<i>caerulea</i> (Shute Harbour)",
        )

    def test_markup_nothospecies(self):
        self.assertEqual(
            markup_italics("\xd7 grandiflora"), "\xd7 <i>grandiflora</i>"
        )
        self.assertEqual(
            markup_italics("\xd7grandiflora"), "\xd7<i>grandiflora</i>"
        )

    def test_markup_species_hybrid(self):
        self.assertEqual(
            markup_italics("lilliputiana \xd7 compacta \xd7 ampullacea"),
            "<i>lilliputiana</i> \xd7 <i>compacta</i> \xd7 <i>ampullacea</i>",
        )

    def test_markup_infraspecific_hybrid(self):
        self.assertEqual(
            markup_italics(
                "wilsonii subsp. cryptophlebium \xd7 wilsonii subsp. wilsonii"
            ),
            "<i>wilsonii</i> subsp. <i>cryptophlebium</i> \xd7 "
            "<i>wilsonii</i> subsp. <i>wilsonii</i>",
        )
        # with ZWS
        self.assertEqual(
            markup_italics(
                "\u200bwilsonii subsp. cryptophlebium \xd7 wilsonii subsp. "
                "wilsonii"
            ),
            "\u200b<i>wilsonii</i> subsp. <i>cryptophlebium</i> \xd7 "
            "<i>wilsonii</i> subsp. <i>wilsonii</i>",
        )

    def test_markup_species_cv_hybrid(self):
        self.assertEqual(
            markup_italics("carolinae \xd7 'Hot Wizz'"),
            "<i>carolinae</i> \xd7 'Hot Wizz'",
        )

    def test_markup_complex_hybrid(self):
        self.assertEqual(
            markup_italics(
                "(carolinae \xd7 'Purple Star') \xd7 (compacta \xd7 sp.)"
            ),
            "(<i>carolinae</i> \xd7 'Purple Star') \xd7 (<i>compacta</i> "
            "\xd7 sp.)",
        )

        self.assertEqual(
            markup_italics(
                "(('Gee Whizz' \xd7 'Fireball' \xd7 compacta) \xd7 "
                "'Purple Star') \xd7 lilliputiana"
            ),
            "(('Gee Whizz' \xd7 'Fireball' \xd7 <i>compacta</i>) \xd7 "
            "'Purple Star') \xd7 <i>lilliputiana</i>",
        )
        self.assertEqual(
            markup_italics(
                "'Gee Whizz' \xd7 ('Fireball' \xd7 (compacta \xd7 "
                "'Purple Star')) \xd7 lilliputiana"
            ),
            "'Gee Whizz' \xd7 ('Fireball' \xd7 (<i>compacta</i> \xd7 "
            "'Purple Star')) \xd7 <i>lilliputiana</i>",
        )
        self.assertEqual(
            markup_italics("carolinae 'Tricolor' \xd7 compacta"),
            "<i>carolinae</i> 'Tricolor' \xd7 <i>compacta</i>",
        )
        self.assertEqual(
            markup_italics("carolinae \xd7 sp. (pink and red)"),
            "<i>carolinae</i> \xd7 sp. (pink and red)",
        )

    def test_markup_complex_hybrid_zws(self):
        self.assertEqual(
            markup_italics(
                "\u200b(carolinae \xd7 'Purple Star') \xd7 (compacta "
                "\xd7 sp.)"
            ),
            "\u200b(<i>carolinae</i> \xd7 'Purple Star') \xd7 "
            "(<i>compacta</i> \xd7 sp.)",
        )
        self.assertEqual(
            markup_italics("\u200bcarolinae \xd7 sp. (pink and red)"),
            "\u200b<i>carolinae</i> \xd7 sp. (pink and red)",
        )

    def test_markup_provisory_hybrid(self):
        self.assertEqual(
            markup_italics(
                "sp. \xd7 sp. (South Molle Island J.P.GrestyAQ208995)"
            ),
            "sp. \xd7 sp. (South Molle Island J.P.GrestyAQ208995)",
        )

    def test_markup_nothospecies_hybrid(self):
        self.assertEqual(
            markup_italics("gymnocarpa \xd7 \xd7grandiflora"),
            "<i>gymnocarpa</i> \xd7 \xd7<i>grandiflora</i>",
        )
        self.assertEqual(
            markup_italics("gymnocarpa \xd7 \xd7 grandiflora"),
            "<i>gymnocarpa</i> \xd7 \xd7 <i>grandiflora</i>",
        )
        # with ZWS
        self.assertEqual(
            markup_italics("\u200b\xd7 grandiflora"),
            "\u200b\xd7 <i>grandiflora</i>",
        )

    def test_markup_junk(self):
        # check junk doesn't crash
        self.assertEqual(
            markup_italics(
                "\ub0aaN\ua001\U00055483\u01d6\u059e/C\U00103e9aG|\U0010eb876"
            ),
            "\ub0aaN\ua001\U00055483\u01d6\u059e/C\U00103e9aG|\U0010eb876",
        )

    def test_markup_complex_hybrid_mismatched_bracket(self):
        # check that mismatch brackets can produce something close to a desired
        # outcome.
        self.assertEqual(
            markup_italics(
                "((carolinae \xd7 'Purple Star') \xd7 (compacta \xd7 sp.)"
            ),
            "((<i>carolinae</i> \xd7 'Purple Star') \xd7 (compacta \xd7 sp.)",
        )
        self.assertEqual(
            markup_italics(
                "(carolinae \xd7 'Purple Star')) \xd7 (lilliputiana \xd7 "
                "compacta \xd7 sp.)"
            ),
            "(<i>carolinae</i> \xd7 'Purple Star')) \xd7 (lilliputiana \xd7 "
            "<i>compacta</i> \xd7 sp.)",
        )


class SpeciesFullNameTests(PlantTestCase):
    def test_full_name_is_created_on_species_insert(self):
        gen = self.session.query(Genus).first()
        sp = Species(genus=gen, sp="sp. nov.")
        self.assertFalse(sp.full_name)
        self.session.add(sp)
        self.session.commit()
        self.assertEqual(sp.full_name, str(sp))
        hist_query = (
            self.session.query(db.History.values)
            .filter(db.History.table_name == "species")
            .filter(db.History.table_id == sp.id)
        )
        hist_entry = [
            entry for entry in hist_query if entry[0]["full_name"] == str(sp)
        ]
        self.assertEqual(len(hist_entry), 1)

    def test_full_name_is_created_on_all_insert(self):
        fam = Family(epithet="Fabaceae")
        gen = Genus(epithet="Acacia", family=fam)
        sp = Species(
            genus=gen,
            sp="dealbata",
            infrasp1_rank="subsp.",
            infrasp1="dealbata",
        )
        self.assertFalse(sp.full_name)
        self.session.add(sp)
        self.session.commit()
        self.assertEqual(sp.full_name, "Acacia dealbata subsp. dealbata")
        hist_query = (
            self.session.query(db.History.values)
            .filter(db.History.table_name == "species")
            .filter(db.History.table_id == sp.id)
        )
        hist_entry = [
            entry for entry in hist_query if entry[0]["full_name"] == str(sp)
        ]
        self.assertEqual(len(hist_entry), 1)

    def test_full_name_updated_on_species_update(self):
        # check update any epithet, infrasp or ranks, group, cv, etc.
        # Epithet
        sp = self.session.get(Species, 1)
        sp.epithet = "sophronitis"
        self.session.add(sp)
        self.session.commit()
        self.assertEqual(sp.full_name, str(sp))
        # infrasp
        sp.infrasp1_rank = "var."
        sp.infrasp1 = "sophronitis"
        self.session.add(sp)
        self.session.commit()
        self.assertEqual(sp.full_name, str(sp))
        # group
        sp.group = "Test"
        self.session.add(sp)
        self.session.commit()
        self.assertEqual(sp.full_name, str(sp))
        # cv
        start = sp.full_name
        sp.cultivar_epithet = "Red"
        self.session.add(sp)
        self.session.commit()
        self.assertEqual(sp.full_name, str(sp))
        hist_query = (
            self.session.query(db.History.values)
            .filter(db.History.table_name == "species")
            .filter(db.History.table_id == 1)
        )
        hist_entry = [
            entry
            for entry in hist_query
            if entry[0]["full_name"] == [str(sp), start]
        ]
        self.assertEqual(len(hist_entry), 1)

    def test_full_name_updated_on_genus_update(self):
        # check epithet, hybrid, etc.
        # new genus
        fam = self.session.get(Family, 1)
        gen = Genus(epithet="Ornithidium", family=fam)
        sp = self.session.get(Species, 1)
        sp.genus = gen
        self.session.add(gen)
        self.session.commit()
        self.assertEqual(sp.full_name, str(sp))
        # update genus name
        sp.genus.epithet = "Anguloa"
        self.session.add(sp)
        self.session.commit()
        self.assertEqual(gen.epithet, "Anguloa")
        self.assertEqual(sp.full_name, str(sp))
        hist_query = (
            self.session.query(db.History.values)
            .filter(db.History.table_name == "species")
            .filter(db.History.table_id == 1)
        )
        hist_entry = [
            entry
            for entry in hist_query
            if entry[0]["full_name"]
            == ["Anguloa variabilis", "Ornithidium variabilis"]
        ]
        self.assertEqual(len(hist_entry), 1)
        # update genus hybrid
        sp.genus.hybrid = "×"
        self.session.add(sp)
        self.session.commit()
        self.assertEqual(sp.full_name, str(sp))
        hist_query = (
            self.session.query(db.History.values)
            .filter(db.History.table_name == "species")
            .filter(db.History.table_id == 1)
        )
        hist_entry = [
            entry
            for entry in hist_query
            if entry[0]["full_name"]
            == ["× Anguloa variabilis", "Anguloa variabilis"]
        ]
        self.assertEqual(len(hist_entry), 1)

    def test_full_name_updated_on_genus_and_sp_update(self):
        # change to another existing genus
        sp = self.session.get(Species, 1)
        start = sp.full_name
        gen = self.session.get(Genus, sp.genus_id + 1)
        sp.genus = gen
        sp.epither = "test_new"
        self.session.add(sp)
        self.session.commit()
        self.assertEqual(sp.full_name, str(sp))
        self.assertNotEqual(sp.full_name, start)
        hist_query = (
            self.session.query(db.History.values)
            .filter(db.History.table_name == "species")
            .filter(db.History.table_id == 1)
        )
        hist_entry = [
            entry
            for entry in hist_query
            if entry[0]["full_name"] == [str(sp), start]
        ]
        self.assertEqual(len(hist_entry), 1)

    def test_full_name_no_change_no_update_no_history(self):
        # set full_names (test data is added not triggering event.listens_for)
        list(update_all_full_names_task())
        hist_query = (
            self.session.query(db.History.values)
            .filter(db.History.table_name == "species")
            .filter(db.History.table_id == 1)
        )
        start_count = hist_query.count()
        sp = self.session.get(Species, 1)
        start = sp.full_name
        sp.epithet = "variabilis"
        self.session.add(sp)
        self.session.commit()
        self.assertEqual(sp.full_name, str(sp))
        self.assertEqual(sp.full_name, start)
        end_count = hist_query.count()
        self.assertEqual(start_count, end_count)

    def test_update_all_full_names_task(self):
        hist_query = self.session.query(db.History.values).filter(
            db.History.table_name == "species"
        )
        start_count = hist_query.count()
        list(update_all_full_names_task())
        sp_query = self.session.query(Species)
        for sp in sp_query:
            if sp.id in species_str_map:
                self.assertEqual(sp.full_name, species_str_map.get(sp.id))
        end_count = hist_query.count()
        # one history entry per species
        self.assertEqual(end_count, start_count + sp_query.count())


class SpeciesInfraspecificProp(PlantTestCase):
    def test_infraspecific_1(self):
        cinnamomum = Genus(
            family=Family(epithet="Lauraceae"),
            epithet="Cinnamomum",
        )
        cinnamomum_camphora = Species(genus=cinnamomum, epithet="camphora")
        self.session.add(cinnamomum_camphora)
        self.session.commit()
        obj = Species(
            genus=cinnamomum,
            sp="camphora",
            infrasp1_rank="f.",
            infrasp1="linaloolifera",
            infrasp1_author="(Y.Fujita) Sugim.",
        )
        self.assertEqual(obj.infraspecific_rank, "f.")
        self.assertEqual(obj.infraspecific_epithet, "linaloolifera")
        self.assertEqual(obj.infraspecific_author, "(Y.Fujita) Sugim.")

    def test_infraspecific_2(self):
        cinnamomum = Genus(
            family=Family(epithet="Lauraceae"),
            epithet="Cinnamomum",
        )
        cinnamomum_camphora = Species(genus=cinnamomum, epithet="camphora")
        self.session.add(cinnamomum_camphora)
        self.session.commit()
        obj = Species(
            genus=cinnamomum,
            sp="camphora",
            infrasp2_rank="f.",
            infrasp2="linaloolifera",
            infrasp2_author="(Y.Fujita) Sugim.",
        )
        self.assertEqual(obj.infraspecific_rank, "f.")
        self.assertEqual(obj.infraspecific_epithet, "linaloolifera")
        self.assertEqual(obj.infraspecific_author, "(Y.Fujita) Sugim.")

    def test_variety_and_cultivar_1(self):
        gleditsia = Genus(
            family=Family(epithet="Fabaceae"),
            epithet="Gleditsia",
        )
        gleditsia_triacanthos = Species(
            genus=gleditsia,
            epithet="triacanthos",
        )
        self.session.add(gleditsia_triacanthos)
        self.session.commit()
        obj = Species(
            genus=gleditsia,
            sp="triacanthos",
            infrasp1_rank="var.",
            infrasp1="inermis",
            cultivar_epithet="Sunburst",
        )
        self.assertEqual(obj.infraspecific_rank, "var.")
        self.assertEqual(obj.infraspecific_epithet, "inermis")
        self.assertEqual(obj.infraspecific_author, "")
        self.assertEqual(obj.cultivar_epithet, "Sunburst")

    def test_variety_and_cultivar_2(self):
        gleditsia = Genus(
            family=Family(epithet="Fabaceae"),
            epithet="Gleditsia",
        )
        gleditsia_triacanthos = Species(
            genus=gleditsia,
            epithet="triacanthos",
        )
        self.session.add(gleditsia_triacanthos)
        self.session.commit()
        obj = Species(
            genus=gleditsia,
            sp="triacanthos",
            infrasp2_rank="var.",
            infrasp2="inermis",
            cultivar_epithet="Sunburst",
        )
        self.assertEqual(obj.infraspecific_rank, "var.")
        self.assertEqual(obj.infraspecific_epithet, "inermis")
        self.assertEqual(obj.infraspecific_author, "")
        self.assertEqual(obj.cultivar_epithet, "Sunburst")

    def test_infraspecific_props_is_lowest_ranked(self):
        """Saxifraga aizoon var. aizoon subvar. brevifolia f. multicaulis
        subf. surculosa"""
        genus = Genus(
            family=Family(epithet="Saxifragaceae"), epithet="Saxifraga"
        )
        subvar = Species(
            genus=genus,
            sp="aizoon",
            infrasp1_rank="var.",
            infrasp1="aizoon",
            infrasp2_rank="subvar.",
            infrasp2="brevifolia",
        )
        subf = Species(
            genus=genus,
            sp="aizoon",
            infrasp2_rank="var.",
            infrasp2="aizoon",
            infrasp1_rank="subvar.",
            infrasp1="brevifolia",
            infrasp3_rank="f.",
            infrasp3="multicaulis",
            infrasp4_rank="subf.",
            infrasp4="surculosa",
        )
        self.assertEqual(subvar.infraspecific_rank, "subvar.")
        self.assertEqual(subvar.infraspecific_epithet, "brevifolia")
        self.assertEqual(subvar.infraspecific_author, "")
        self.assertIsNone(subf.cultivar_epithet)
        self.assertEqual(subf.infraspecific_rank, "subf.")
        self.assertEqual(subf.infraspecific_epithet, "surculosa")
        self.assertEqual(subf.infraspecific_author, "")
        self.assertIsNone(subf.cultivar_epithet)
        # Saxifraga aizoon var. aizoon subvar. brevifolia f. multicaulis
        # cv. 'Bellissima'
        cv = Species(
            genus=genus,
            sp="aizoon",
            infrasp4_rank="var.",
            infrasp4="aizoon",
            infrasp1_rank="subvar.",
            infrasp1="brevifolia",
            infrasp3_rank="f.",
            infrasp3="multicaulis",
            cultivar_epithet="Bellissima",
        )
        self.assertEqual(cv.infraspecific_rank, "f.")
        self.assertEqual(cv.infraspecific_epithet, "multicaulis")
        self.assertEqual(cv.infraspecific_author, "")
        self.assertEqual(cv.cultivar_epithet, "Bellissima")

    def test_infraspecific_hybrid_properties(self):
        # NOTE some of this and similar test are no longer relevant
        family = Family(family="family")
        genus = Genus(family=family, genus="genus")
        sp = Species(genus=genus, sp="sp")
        # Check all parts end up where they should
        parts = "var. variety f. form"
        sp.infraspecific_parts = parts
        cul = "Cultivar In Parts"
        sp.cultivar_epithet = cul
        self.session.add_all([family, genus, sp])
        self.session.commit()
        # Make sure we cover the expression for each
        q = (
            self.session.query(Species)
            .filter_by(infraspecific_rank=parts.split()[-2])
            .one()
        )
        self.assertEqual(sp, q)
        q = (
            self.session.query(Species)
            .filter_by(infraspecific_epithet=parts.split()[-1])
            .one()
        )
        self.assertEqual(sp, q)
        q = self.session.query(Species).filter_by(cultivar_epithet=cul).one()
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
        family = Family(family="family")
        genus = Genus(family=family, genus="genus")
        sp = Species(genus=genus, sp="sp")
        parts = "var. variety f. form"
        sp.infraspecific_parts = parts
        self.session.add_all([family, genus, sp])
        self.session.commit()
        # test 'cv.'
        cul = "cv."
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
        family = Family(family="family")
        genus = Genus(family=family, genus="genus")
        sp = Species(genus=genus, sp="sp")
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


class RetrieveTests(PlantTestCase):
    def test_vernacular_name_retreives_full_sp_data(self):
        keys = {
            "species.sp": "cochleata",
            "species.genus.genus": "Encyclia",
            "species.infrasp1_rank": "subsp.",
            "species.infrasp1": "cochleata",
            "species.infrasp2_rank": "var.",
            "species.infrasp2": "cochleata",
            "species.cultivar_epithet": "Black",
        }
        vname = VernacularName.retrieve(self.session, keys)
        self.assertEqual(vname.id, 5)
        # using hybrid properties
        keys = {
            "species.epithet": "cochleata",
            "species.genus.epithet": "Encyclia",
            "species.infrasp_parts": "subsp. cochleata var. cochleata",
            "species.cultivar_epithet": "Black",
        }
        vname = VernacularName.retrieve(self.session, keys)
        self.assertEqual(vname.id, 5)

    def test_vernacular_name_retreives_incomplete_sp_data_one_sp(self):
        keys = {
            "species.epithet": "cochleata",
            "species.genus.epithet": "Encyclia",
            "species.cultivar_epithet": "Black",
        }
        vname = VernacularName.retrieve(self.session, keys)
        self.assertEqual(vname.id, 5)

    def test_vernacular_name_doesnt_retreive_incomplete_sp_data_multiple(self):
        keys = {
            "species.genus.epithet": "Encyclia",
            "species.epithet": "cochleata",
        }
        vname = VernacularName.retrieve(self.session, keys)
        self.assertIsNone(vname)

    def test_vernacular_name_doesnt_retreive_sp_data_multiple_vnames(self):
        keys = {
            "species.genus.epithet": "Maxillaria",
            "species.epithet": "variabilis",
        }
        vname = VernacularName.retrieve(self.session, keys)
        self.assertIsNone(vname)

    def test_vernacular_name_retreives_vn_parts_only_one_sp(self):
        keys = {
            "name": "SomeName",
            "language": "English",
        }
        vname = VernacularName.retrieve(self.session, keys)
        self.assertEqual(vname.id, 1)

    def test_vernacular_name_doesnt_retreive_vn_parts_only_multiple_sp(self):
        keys = {
            "name": "Clamshell Orchid",
            "language": "English",
        }
        vname = VernacularName.retrieve(self.session, keys)
        self.assertIsNone(vname)

    def test_vernacular_name_retreives_full_data(self):
        keys = {
            "name": "SomeName",
            "language": "English",
            "species.epithet": "variabilis",
            "species.genus.epithet": "Maxillaria",
        }
        vname = VernacularName.retrieve(self.session, keys)
        self.assertEqual(vname.id, 1)

    def test_vernacular_name_retreives_id_only(self):
        keys = {"id": 5}
        vname = VernacularName.retrieve(self.session, keys)
        self.assertEqual(vname.species.id, 15)

    def test_vernacular_name_retreives_sp_id_only(self):
        keys = {"species.id": 15}
        vname = VernacularName.retrieve(self.session, keys)
        self.assertEqual(vname.id, 5)

    def test_vernacular_name_retreives_name_only_exists_once(self):
        keys = {"name": "Toé"}
        vname = VernacularName.retrieve(self.session, keys)
        self.assertEqual(vname.id, 4)

    def test_vernacular_name_doesnt_retreive_non_existent_name(self):
        keys = {"name": "NonExistent"}
        vname = VernacularName.retrieve(self.session, keys)
        self.assertIsNone(vname)
        # mismatch
        keys = {
            "name": "Clamshell orchid",
            "language": "English",
            "species.epithet": "variabilis",
            "species.genus.epithet": "Maxillaria",
        }
        vname = VernacularName.retrieve(self.session, keys)
        self.assertIsNone(vname)

    def test_vernacular_name_doesnt_retreive_wrong_keys(self):
        keys = {"name": "Somewhere Else", "code": "SE"}
        vname = VernacularName.retrieve(self.session, keys)
        self.assertIsNone(vname)

    def test_vernacular_name_doesnt_retreive_for_sp_non_existent_vname(self):
        keys = {
            "species.genus": "Campyloneurum",
            "species.sp": "alapense",
            "species.hybrid": "×",
        }
        with self.assertLogs(level="DEBUG") as logs:
            vname = VernacularName.retrieve(self.session, keys)
        string = f"retrieved species {species_str_map[4]}"
        self.assertTrue(any(string in i for i in logs.output))
        self.assertIsNone(vname)

    def test_species_retreives_full_sp_data(self):
        keys = {
            "sp": "cochleata",
            "genus.genus": "Encyclia",
            "infrasp1_rank": "subsp.",
            "infrasp1": "cochleata",
            "infrasp2_rank": "var.",
            "infrasp2": "cochleata",
            "cultivar_epithet": "Black",
        }
        sp = Species.retrieve(self.session, keys)
        self.assertEqual(sp.id, 15)
        # using hybrid property infrasp_parts
        keys = {
            "epithet": "cochleata",
            "genus.epithet": "Encyclia",
            "infrasp_parts": "subsp. cochleata var. cochleata",
            "cultivar_epithet": "Black",
        }
        sp = Species.retrieve(self.session, keys)
        self.assertEqual(sp.id, 15)

    def test_species_retreives_id_only(self):
        keys = {"id": 15}
        sp = Species.retrieve(self.session, keys)
        self.assertEqual(str(sp), species_str_map[15])

    def test_species_doesnt_retreive_incomplete_sp_data_multiple(self):
        keys = {
            "genus.epithet": "Encyclia",
            "epithet": "cochleata",
        }
        sp = Species.retrieve(self.session, keys)
        self.assertIsNone(sp)

    def test_species_doesnt_retreive_non_existent(self):
        keys = {
            "genus.epithet": "Encyclia",
            "epithet": "nonexistennt",
        }
        sp = Species.retrieve(self.session, keys)
        self.assertIsNone(sp)

    def test_species_doesnt_retreive_wrong_keys(self):
        keys = {"name": "Somewhere Else", "code": "SE"}
        sp = Species.retrieve(self.session, keys)
        self.assertIsNone(sp)
