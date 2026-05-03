# pylint: disable=no-self-use,protected-access,too-many-public-methods
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
Search tests
"""
from bauble import db
from bauble import prefs
from bauble import search
from bauble.search.search import result_cache
from bauble.search.strategies import UseStrategy
from bauble.test import BaubleTestCase

from ..family import Family
from ..genus import Genus
from ..search import BinomialSearch
from ..search import SynonymSearch
from ..species import Species


class BinomialSearchTests(BaubleTestCase):
    def setUp(self):
        super().setUp()
        db.engine.execute("delete from genus")
        db.engine.execute("delete from family")

        f1 = Family(family="family1", qualifier="s. lat.")
        g1 = Genus(family=f1, genus="genus1")
        f2 = Family(family="family2")
        g2 = Genus(family=f2, genus="genus2")
        f3 = Family(family="fam3", qualifier="s. lat.")
        g3 = Genus(family=f3, genus="Ixora")
        sp = Species(sp="coccinea", genus=g3)
        sp2 = Species(sp="peruviana", genus=g3)
        sp3 = Species(sp="chinensis", genus=g3)
        self.cv1 = Species(cultivar_epithet="Magnifica", genus=g3)
        self.cv2 = Species(
            sp="chinensis", cultivar_epithet="Prince Of Orange", genus=g3
        )
        g4 = Genus(family=f3, genus="Pachystachys")
        sp4 = Species(sp="coccinea", genus=g4)
        self.sp5 = Species(sp="rosa-sinensis", genus=g3)
        sp6 = Species(sp="speciosa", genus=g3)
        self.sp7 = Species(sp="sp.", genus=g3)
        self.session.add_all(
            [
                f1,
                f2,
                g1,
                g2,
                f3,
                g3,
                sp,
                sp2,
                sp3,
                g4,
                sp4,
                self.sp5,
                sp6,
                self.sp7,
            ]
        )
        self.session.commit()
        self.ixora, self.ic, self.pc = g3, sp, sp4

    def test_binomial_complete(self):
        strategy = search.strategies.get_strategy("BinomialSearch")
        self.assertTrue(isinstance(strategy, BinomialSearch))

        s = "Ixora coccinea"  # matches Ixora coccinea
        results = []
        for i in strategy.search(s, self.session):
            results.extend(i)
        self.assertEqual(results, [self.ic])

    def test_binomial_incomplete(self):
        strategy = search.strategies.get_strategy("BinomialSearch")
        self.assertTrue(isinstance(strategy, BinomialSearch))

        s = "Ix cocc"  # matches Ixora coccinea
        results = []
        for i in strategy.search(s, self.session):
            results.extend(i)
        self.assertEqual(results, [self.ic])

    def test_binomial_no_match(self):
        strategy = search.strategies.get_strategy("BinomialSearch")
        self.assertTrue(isinstance(strategy, BinomialSearch))

        s = "Cosito inesistente"  # matches nothing
        results = []
        for i in strategy.search(s, self.session):
            results.extend(i)
        self.assertEqual(results, [])

    def test_use(self):
        strategy = search.strategies.get_strategy("BinomialSearch")
        self.assertTrue(isinstance(strategy, BinomialSearch))

        s = "ixora coccinea"
        self.assertEqual(strategy.use(s), UseStrategy.EXCLUDE)

        s = "i c"
        self.assertEqual(strategy.use(s), UseStrategy.EXCLUDE)

        s = "I "
        self.assertEqual(strategy.use(s), UseStrategy.EXCLUDE)

        s = "I "
        self.assertEqual(strategy.use(s), UseStrategy.EXCLUDE)

        s = "I c"
        self.assertEqual(strategy.use(s), UseStrategy.INCLUDE)

        s = "Ixora coccinea"
        self.assertEqual(strategy.use(s), UseStrategy.INCLUDE)

        s = "Gre 'Roby"
        self.assertEqual(strategy.use(s), UseStrategy.INCLUDE)

        s = "Grevillea 'Robyn Gordon'"
        self.assertEqual(strategy.use(s), UseStrategy.INCLUDE)

        s = "Hibiscus rosa-sinensis"
        self.assertEqual(strategy.use(s), UseStrategy.INCLUDE)

        s = "Cyn dac 'DT-1"
        self.assertEqual(strategy.use(s), UseStrategy.INCLUDE)

        s = "Eryth sp."
        self.assertEqual(strategy.use(s), UseStrategy.INCLUDE)

        s = "Eryth ."
        self.assertEqual(strategy.use(s), UseStrategy.EXCLUDE)

        s = "Grev '"
        self.assertEqual(strategy.use(s), UseStrategy.INCLUDE)

    def test_sp_cultivar_also_matches(self):
        strategy = search.strategies.get_strategy("BinomialSearch")
        self.assertTrue(isinstance(strategy, BinomialSearch))

        g3 = self.session.query(Genus).filter(Genus.genus == "Ixora").one()
        sp5 = Species(sp="coccinea", genus=g3, cultivar_epithet="Nora Grant")
        self.session.add_all([sp5])
        self.session.commit()
        s = "Ixora coccinea"  # matches I.coccinea and Nora Grant
        results = []
        for i in strategy.search(s, self.session):
            results.extend(i)
        self.assertCountEqual(results, [self.ic, sp5])

    def test_cultivar_no_sp_search(self):
        strategy = search.strategies.get_strategy("BinomialSearch")
        self.assertTrue(isinstance(strategy, BinomialSearch))

        s = "Ixora 'Mag"
        results = []
        for i in strategy.search(s, self.session):
            results.extend(i)
        self.assertEqual(results, [self.cv1])

    def test_cultivar_w_sp_search(self):
        strategy = search.strategies.get_strategy("BinomialSearch")
        self.assertTrue(isinstance(strategy, BinomialSearch))

        s = "Ixo 'Pri"
        results = []
        for i in strategy.search(s, self.session):
            results.extend(i)
        self.assertEqual(results, [self.cv2])

    def test_cultivar_complete(self):
        strategy = search.strategies.get_strategy("BinomialSearch")
        self.assertTrue(isinstance(strategy, BinomialSearch))

        s = "Ixora chinensis 'Prince Of Orange'"
        results = []
        for i in strategy.search(s, self.session):
            results.extend(i)
        self.assertEqual(results, [self.cv2])

    def test_full_cultivar_search(self):
        strategy = search.strategies.get_strategy("BinomialSearch")
        self.assertTrue(isinstance(strategy, BinomialSearch))

        s = "Ixora 'Prince Of Orange'"
        results = []
        for i in strategy.search(s, self.session):
            results.extend(i)
        self.assertEqual(results, [self.cv2])

    def test_cultivar_partial_complete(self):
        strategy = search.strategies.get_strategy("BinomialSearch")
        self.assertTrue(isinstance(strategy, BinomialSearch))

        s = "Ixo chi 'Pri"
        results = []
        for i in strategy.search(s, self.session):
            results.extend(i)
        self.assertEqual(results, [self.cv2])

    def test_trade_name_search(self):
        self.cv2.trade_name = "Test Trade Name"
        self.session.commit()
        strategy = search.strategies.get_strategy("BinomialSearch")
        self.assertTrue(isinstance(strategy, BinomialSearch))

        s = "Ixo 'Test"
        results = []
        for i in strategy.search(s, self.session):
            results.extend(i)
        self.assertEqual(results, [self.cv2])

    def test_hyphenated_name_search(self):
        strategy = search.strategies.get_strategy("BinomialSearch")
        self.assertTrue(isinstance(strategy, BinomialSearch))

        s = "Ixo rosa-sinensis"
        results = []
        for i in strategy.search(s, self.session):
            results.extend(i)
        self.assertEqual(results, [self.sp5])

        self.sp5.cultivar_epithet = "Test-10"
        self.session.commit()

        s = "Ixo ros 'Test-1"
        results = []
        for i in strategy.search(s, self.session):
            results.extend(i)
        self.assertEqual(results, [self.sp5])

    def test_sp_dot_search(self):
        strategy = search.strategies.get_strategy("BinomialSearch")
        self.assertTrue(isinstance(strategy, BinomialSearch))

        s = "Ixo sp."
        results = []
        for i in strategy.search(s, self.session):
            results.extend(i)
        self.assertEqual(results, [self.sp7])

        s = "Ixo sp"
        results = []
        for i in strategy.search(s, self.session):
            results.extend(i)
        self.assertEqual(len(results), 2)

    def test_all_cvs_search(self):
        strategy = search.strategies.get_strategy("BinomialSearch")
        self.assertTrue(isinstance(strategy, BinomialSearch))

        s = "Ixo '"
        results = []
        for i in strategy.search(s, self.session):
            results.extend(i)
        self.assertCountEqual(results, [self.cv1, self.cv2])

        s = "Pach '"
        results = []
        for i in strategy.search(s, self.session):
            results.extend(i)
        self.assertEqual(results, [])


class SynonymSearchTest(BaubleTestCase):
    def test_search_search_uses_synonym_search(self):
        prefs.prefs["bauble.search.return_accepted"] = True
        with self.assertLogs(level="DEBUG") as logs:
            search.search("genus like %", self.session)
        string = 'SearchStrategy "genus like %" (SynonymSearch)'
        self.assertTrue(any(string in i for i in logs.output))

        with self.assertLogs(level="DEBUG") as logs:
            search.search("12.11.13", self.session)
        string = 'SearchStrategy "12.11.13" (SynonymSearch)'
        self.assertTrue(any(string in i for i in logs.output))

        with self.assertLogs(level="DEBUG") as logs:
            search.search("So ha", self.session)
        string = 'SearchStrategy "So ha" (SynonymSearch)'
        self.assertTrue(any(string in i for i in logs.output))

    def test_search_search_doesnt_use_synonym_search(self):
        prefs.prefs["bauble.search.return_accepted"] = False
        with self.assertLogs(level="DEBUG") as logs:
            search.search("genus like %", self.session)
        string = 'SearchStrategy "genus like %" (SynonymSearch)'
        self.assertFalse(any(string in i for i in logs.output))

        with self.assertLogs(level="DEBUG") as logs:
            search.search("12.11.13", self.session)
        string = 'SearchStrategy "12.11.13" (SynonymSearch)'
        self.assertFalse(any(string in i for i in logs.output))

        with self.assertLogs(level="DEBUG") as logs:
            search.search("So ha", self.session)
        string = 'SearchStrategy "So ha" (SynonymSearch)'
        self.assertFalse(any(string in i for i in logs.output))

    def test_bails_wo_return_accepted(self):
        # possibly redundant functionality?
        prefs.prefs["bauble.search.return_accepted"] = True
        fam = Family(epithet="Spam")
        fam2 = Family(epithet="Eggs")
        fam.synonyms.append(fam2)
        self.session.add(fam2)
        self.session.add(fam)
        self.session.commit()
        query = self.session.query(Family).filter_by(id=fam2.id)
        result_cache["MapperSearch"] = query.all()
        strategy = search.strategies.get_strategy("SynonymSearch")

        self.assertTrue(isinstance(strategy, SynonymSearch))

        results = []
        for i in strategy.search("", self.session):
            results.extend(i)

        self.assertEqual(results, [fam])

        # bails
        prefs.prefs["bauble.search.return_accepted"] = False

        results = []
        for i in strategy.search("", self.session):
            results.extend(i)

        self.assertEqual(results, [])
