# Copyright 2008-2010 Brett Adams
# Copyright 2015 Mario Frasca <mario@anche.no>.
# Copyright 2021-2025 Ross Demuth <rossdemuth123@gmail.com>
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
# test_search.py
#
import datetime
import logging
import unittest
import warnings
from datetime import timezone
from unittest.mock import patch

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

import pyparsing as pp
from pyparsing import ParseException

from bauble import db
from bauble import error
from bauble import prefs
from bauble import search
from bauble import utils
from bauble.plugins.garden.accession import Accession
from bauble.plugins.garden.location import Location
from bauble.plugins.garden.location import LocationPicture
from bauble.plugins.garden.plant import Plant
from bauble.plugins.garden.plant import PlantPicture
from bauble.plugins.garden.source import Source
from bauble.plugins.garden.source import SourceDetail
from bauble.plugins.plants.family import Family
from bauble.plugins.plants.genus import Genus
from bauble.plugins.plants.genus import GenusNote
from bauble.plugins.plants.geography import Geography
from bauble.plugins.plants.species_model import Species
from bauble.plugins.plants.species_model import SpeciesDistribution
from bauble.plugins.plants.species_model import SpeciesPicture
from bauble.plugins.plants.species_model import VernacularName
from bauble.plugins.plants.test_plants import setup_geographies
from bauble.search.search import result_cache
from bauble.test import BaubleClassTestCase
from bauble.test import BaubleTestCase
from bauble.test import get_setUp_data_funcs

parser = search.parser


class SearchParserTests(BaubleClassTestCase):

    def test_query_expression_token_UPPER(self):
        s = "plant where col=value"
        logger.debug(s)
        parser.statement.parse_string(s)

        s = "plant where relation.col=value"
        parser.statement.parse_string(s)

        s = "plant where relation.relation.col=value"
        parser.statement.parse_string(s)

        s = "plant where relation.relation.col=value AND col2=value2"
        parser.statement.parse_string(s)

    def test_query_expression_token_LOWER(self):
        s = "plant where relation.relation.col=value and col2=value2"
        parser.statement.parse_string(s)

    def test_domain_statement_token(self):
        """
        Test the domain_statement token
        """
        dom_parser = search.strategies.DomainSearch()
        dom_parser.update_domains()
        # allow dom=val1, val2, val3
        s = "plant=test"
        expected = "[plant = 'test']"
        results = dom_parser.statement.parse_string(s, parseAll=True)
        self.assertEqual(results.getName(), "query")
        self.assertEqual(str(results), expected)

        s = "plant==test"
        expected = "[plant == 'test']"
        results = dom_parser.statement.parse_string(s, parseAll=True)
        self.assertEqual(str(results), expected)

        s = "plant=*"
        expected = "[plant = *]"
        results = dom_parser.statement.parse_string(s, parseAll=True)
        self.assertEqual(str(results), expected)

        s = "plant in test1 test2 test3"
        expected = "[plant IN ['test1', 'test2', 'test3']]"
        results = dom_parser.statement.parse_string(s, parseAll=True)
        self.assertEqual(str(results), expected)

        s = 'plant in test1 "test2 test3" test4'
        expected = "[plant IN ['test1', 'test2 test3', 'test4']]"
        results = dom_parser.statement.parse_string(s, parseAll=True)
        self.assertEqual(str(results), expected)

        s = 'plant in "test test"'
        expected = "[plant IN ['test test']]"
        results = dom_parser.statement.parse_string(s, parseAll=True)
        self.assertEqual(str(results), expected)

    def test_integer_token(self):
        "recognizes integers or floats as floats"

        results = parser.value_token.parse_string("123")
        self.assertEqual(results.getName(), "value")
        self.assertEqual(results.value.express(None), 123.0)
        results = parser.value_token.parse_string("123.1")
        self.assertEqual(results.value.express(None), 123.1)

    def test_value_token(self):
        "value should only return the first string or raise a parse exception"

        strings = ["test", '"test"', "'test'"]
        expected = "test"
        for s in strings:
            results = parser.value_token.parse_string(s, parseAll=True)
            self.assertEqual(results.getName(), "value")
            self.assertEqual(results.value.express(None), expected)

        strings = ["123.000", "123.", "123.0"]
        expected = 123.0
        for s in strings:
            results = parser.value_token.parse_string(s)
            self.assertEqual(results.getName(), "value")
            self.assertEqual(results.value.express(None), expected)

        strings = ['"test1 test2"', "'test1 test2'"]
        expected = "test1 test2"  # this is one string! :)
        for s in strings:
            results = parser.value_token.parse_string(s, parseAll=True)
            self.assertEqual(results.getName(), "value")
            self.assertEqual(results.value.express(None), expected)

        strings = ["%.-_*", '"%.-_*"']
        expected = "%.-_*"
        for s in strings:
            results = parser.value_token.parse_string(s, parseAll=True)
            self.assertEqual(results.getName(), "value")
            self.assertEqual(results.value.express(None), expected)

        # these should be invalid
        strings = [
            "test test",
            '"test',
            "test'",
            "$",
        ]
        for s in strings:
            self.assertRaises(
                ParseException,
                parser.value_token.parse_string,
                s,
                parseAll=True,
            )

    def test_value_list_token(self):
        """value_list: should return all values"""

        strings = ["test1, test2", '"test1", test2', "test1, 'test2'"]
        expected = [["test1", "test2"]]
        for s in strings:
            results = parser.value_list_token.parse_string(s, parseAll=True)
            self.assertEqual(results.getName(), "value_list")
            self.assertEqual(str(results), str(expected))

        strings = ["test", '"test"', "'test'"]
        expected = [["test"]]
        for s in strings:
            results = parser.value_list_token.parse_string(s, parseAll=True)
            self.assertEqual(results.getName(), "value_list")
            self.assertEqual(str(results), str(expected))

        strings = ["test1 test2 test3", "\"test1\" test2 'test3'"]
        expected = [["test1", "test2", "test3"]]
        for s in strings:
            results = parser.value_list_token.parse_string(s, parseAll=True)
            self.assertEqual(str(results), str(expected))

        strings = ['"test1 test2", test3']
        expected = [["test1 test2", "test3"]]
        for s in strings:
            results = parser.value_list_token.parse_string(s, parseAll=True)
            self.assertEqual(str(results), str(expected))

        # these should be invalid
        strings = ['"test', "test'", "'test tes2", "1,2,3 4 5"]
        for s in strings:
            self.assertRaises(
                ParseException,
                parser.value_list_token.parse_string,
                s,
                parseAll=True,
            )


class SearchTests(BaubleClassTestCase):

    @classmethod
    def setUpClass(cls):
        # setup once for all tests
        super().setUpClass()
        db.engine.execute("delete from genus")
        db.engine.execute("delete from family")

        cls.family = Family(family="family1", qualifier="s. lat.")
        cls.genus = Genus(family=cls.family, genus="genus1")
        cls.Family = Family
        cls.Genus = Genus
        cls.session.add_all([cls.family, cls.genus])
        cls.session.commit()

    def test_find_correct_strategy_internal(self):
        mapper_search = search.strategies._search_strategies["MapperSearch"]
        self.assertTrue(
            isinstance(mapper_search, search.strategies.MapperSearch)
        )

    def test_find_correct_strategy(self):
        mapper_search = search.strategies.get_strategy("MapperSearch")
        self.assertTrue(
            isinstance(mapper_search, search.strategies.MapperSearch)
        )

    def test_look_for_wrong_strategy(self):
        mapper_search = search.strategies.get_strategy("NotExisting")
        self.assertIsNone(mapper_search)

    @patch("bauble.search.statements.utils.yes_no_dialog")
    def test_search_by_small_values_questions(self, mock_dialog):
        mock_dialog.return_value = False
        vl_search = search.strategies.get_strategy("ValueListSearch")
        self.assertTrue(
            isinstance(vl_search, search.strategies.ValueListSearch)
        )

        # single letter
        string = "f"
        result = vl_search.search(string, self.session)
        self.assertEqual(result, [])
        mock_dialog.assert_called()
        mock_dialog.reset_mock()

        # too many words
        string = (
            "many mostly pointles words that contain more than three letters"
        )
        result = vl_search.search(string, self.session)
        self.assertEqual(result, [])
        mock_dialog.assert_called()
        mock_dialog.reset_mock()

        # single letter number plus others
        string = "3 small words"
        result = vl_search.search(string, self.session)
        self.assertEqual(result, [])
        mock_dialog.assert_called()
        mock_dialog.reset_mock()

        mock_dialog.return_value = True
        # single letter number plus others - do search
        string = "3 fam gen"
        results = []
        for i in vl_search.search(string, self.session):
            results.extend(i)
        self.assertEqual(len(results), 2)
        mock_dialog.assert_called()
        mock_dialog.reset_mock()

    def test_search_by_values(self):
        "search by values"
        vl_search = search.strategies.get_strategy("ValueListSearch")
        self.assertTrue(
            isinstance(vl_search, search.strategies.ValueListSearch)
        )

        # search for family by family name
        s = "family1"
        results = []
        for i in vl_search.search(s, self.session):
            results.extend(i)
        self.assertEqual(len(results), 1)
        f = results[0]
        self.assertEqual(f.id, self.family.id)

        # search for genus by genus name
        s = "genus1"
        results = []
        for i in vl_search.search(s, self.session):
            results.extend(i)
        self.assertEqual(len(results), 1)
        g = results[0]
        self.assertEqual(g.id, self.genus.id)

    def test_search_by_expression_family_eq(self):
        domain_search = search.strategies.get_strategy("DomainSearch")
        self.assertTrue(
            isinstance(domain_search, search.strategies.DomainSearch)
        )

        # search for family by domain
        s = "fam=family1"
        results = []
        for i in domain_search.search(s, self.session):
            results.extend(i)
        self.assertEqual(len(results), 1)
        f = results[0]
        self.assertTrue(isinstance(f, Family))
        self.assertEqual(f.id, self.family.id)

    def test_search_by_expression_genus_eq_1match(self):
        domain_search = search.strategies.get_strategy("DomainSearch")
        self.assertTrue(
            isinstance(domain_search, search.strategies.DomainSearch)
        )

        # search for genus by domain
        s = "gen=genus1"
        results = []
        for i in domain_search.search(s, self.session):
            results.extend(i)
        self.assertEqual(len(results), 1)
        g = list(results)[0]
        self.assertTrue(isinstance(g, Genus))
        self.assertEqual(g.id, self.genus.id)

    def test_search_by_expression_genus_eq_nomatch(self):
        domain_search = search.strategies.get_strategy("DomainSearch")
        self.assertTrue(
            isinstance(domain_search, search.strategies.DomainSearch)
        )

        # search for genus by domain
        s = "genus=g"
        results = []
        for i in domain_search.search(s, self.session):
            results.extend(i)
        self.assertEqual(len(results), 0)

    def test_search_by_expression_genus_eq_everything(self):
        domain_search = search.strategies.get_strategy("DomainSearch")
        self.assertTrue(
            isinstance(domain_search, search.strategies.DomainSearch)
        )

        # search for genus by domain
        s = "genus=*"
        results = []
        for i in domain_search.search(s, self.session):
            results.extend(i)
        self.assertEqual(len(results), 1)

    def test_search_by_expression_genus_not_eq_everything(self):
        domain_search = search.strategies.get_strategy("DomainSearch")
        self.assertTrue(
            isinstance(domain_search, search.strategies.DomainSearch)
        )

        # search for genus by domain
        s = "genus!=*"
        results = []
        for i in domain_search.search(s, self.session):
            results.extend(i)
        self.assertEqual(len(results), 0)

    def test_search_by_expression_genus_gt_match(self):
        domain_search = search.strategies.get_strategy("DomainSearch")
        self.assertTrue(
            isinstance(domain_search, search.strategies.DomainSearch)
        )

        # search for genus by domain
        s = "genus>g"
        results = []
        for i in domain_search.search(s, self.session):
            results.extend(i)
        self.assertEqual(len(results), 1)

    def test_search_by_expression_genus_gt_no_match(self):
        domain_search = search.strategies.get_strategy("DomainSearch")
        self.assertTrue(
            isinstance(domain_search, search.strategies.DomainSearch)
        )

        # search for genus by domain
        s = "genus>w"
        results = []
        for i in domain_search.search(s, self.session):
            results.extend(i)
        self.assertEqual(len(results), 0)

    def test_search_by_expression_genus_lt_match(self):
        domain_search = search.strategies.get_strategy("DomainSearch")
        self.assertTrue(
            isinstance(domain_search, search.strategies.DomainSearch)
        )

        # search for genus by domain
        s = "genus<h"
        results = []
        for i in domain_search.search(s, self.session):
            results.extend(i)
        self.assertEqual(len(results), 1)

    def test_search_by_expression_genus_lt_no_match(self):
        domain_search = search.strategies.get_strategy("DomainSearch")
        self.assertTrue(
            isinstance(domain_search, search.strategies.DomainSearch)
        )

        # search for genus by domain
        s = "genus<b"
        results = []
        for i in domain_search.search(s, self.session):
            results.extend(i)
        self.assertEqual(len(results), 0)

    def test_search_by_expression_w_number_no_match_doesnt_fail(self):
        domain_search = search.strategies.get_strategy("DomainSearch")
        self.assertTrue(
            isinstance(domain_search, search.strategies.DomainSearch)
        )

        # search for genus by domain
        s = "genus = 1 "
        results = []
        for i in domain_search.search(s, self.session):
            results.extend(i)
        self.assertEqual(len(results), 0)

    def test_search_by_expression_genus_like_nomatch(self):
        domain_search = search.strategies.get_strategy("DomainSearch")
        self.assertTrue(
            isinstance(domain_search, search.strategies.DomainSearch)
        )

        # search for genus by domain
        s = "genus like gen"
        results = []
        for i in domain_search.search(s, self.session):
            results.extend(i)
        self.assertEqual(len(results), 0)
        # search for genus by domain
        s = "genus like nus%"
        results = []
        for i in domain_search.search(s, self.session):
            results.extend(i)
        self.assertEqual(len(results), 0)
        # search for genus by domain
        s = "genus like %gen"
        results = []
        for i in domain_search.search(s, self.session):
            results.extend(i)
        self.assertEqual(len(results), 0)


class SearchTests2(BaubleTestCase):

    def setUp(self):
        super().setUp()
        db.engine.execute("delete from genus")
        db.engine.execute("delete from family")

        self.family = Family(family="family1", qualifier="s. lat.")
        self.genus = Genus(family=self.family, genus="genus1")
        self.session.add_all([self.family, self.genus])
        self.session.commit()

    def test_search_by_expression_genus_like_contains_eq(self):
        domain_search = search.strategies.get_strategy("DomainSearch")
        self.assertTrue(
            isinstance(domain_search, search.strategies.DomainSearch)
        )
        f2 = Family(family="family2")
        f3 = Family(family="afamily3")
        f4 = Family(family="fam4")
        self.session.add_all([f3, f2, f4])
        self.session.commit()

        # search for family by domain
        s = "family contains fam"
        results = []
        for i in domain_search.search(s, self.session):
            results.extend(i)
        self.assertEqual(len(results), 4)  # all do
        s = "family like f%"
        results = []
        for i in domain_search.search(s, self.session):
            results.extend(i)
        self.assertEqual(len(results), 3)  # three start by f
        s = "family like af%"
        results = []
        for i in domain_search.search(s, self.session):
            results.extend(i)
        self.assertEqual(len(results), 1)  # one starts by af
        s = "family like fam"
        results = []
        for i in domain_search.search(s, self.session):
            results.extend(i)
        self.assertEqual(len(results), 0)
        s = "family = fam"
        results = []
        for i in domain_search.search(s, self.session):
            results.extend(i)
        self.assertEqual(len(results), 0)
        s = "family = fam4"
        results = []
        for i in domain_search.search(s, self.session):
            results.extend(i)
        self.assertEqual(len(results), 1)  # exact name match
        # MSSQL may not be case sensitive depending on collation settings
        # results = list(domain_search.search('family = Fam4', self.session))
        # self.assertEqual(len(results), 0)  # = is case sensitive
        s = "family like Fam4"
        results = []
        for i in domain_search.search(s, self.session):
            results.extend(i)
        self.assertEqual(len(results), 1)  # like is case insensitive
        s = "family contains FAM"
        results = []
        for i in domain_search.search(s, self.session):
            results.extend(i)
        self.assertEqual(len(results), 4)  # they case insensitively do

    def test_search_by_query_singular(self):
        """query with MapperSearch, single table, single test"""

        # test does not depend on plugin functionality
        family2 = Family(family="family2")
        genus2 = Genus(family=family2, genus="genus2")
        self.session.add_all([family2, genus2])
        self.session.commit()

        mapper_search = search.strategies.get_strategy("MapperSearch")
        self.assertTrue(
            isinstance(mapper_search, search.strategies.MapperSearch)
        )

        # search cls.column
        s = "genus where genus=genus1"
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertEqual(len(results), 1)
        f = list(results)[0]
        self.assertTrue(isinstance(f, Genus))
        self.assertEqual(f.id, self.family.id)

    def test_search_by_or_query_w_homonym(self):
        """query with MapperSearch, single table, p1 OR p2"""

        # test does not depend on plugin functionality
        f2 = Family(family="family2")
        g2 = Genus(family=f2, genus="genus2")
        f3 = Family(family="fam3")
        # g3(homonym) is here just to have two matches on one value
        g3 = Genus(family=f3, genus="genus2")
        g4 = Genus(family=f3, genus="genus4")
        self.session.add_all([f2, g2, f3, g3, g4])
        self.session.commit()

        mapper_search = search.strategies.get_strategy("MapperSearch")
        self.assertTrue(
            isinstance(mapper_search, search.strategies.MapperSearch)
        )

        # search with or conditions
        s = "genus where genus=genus2 OR genus=genus1"
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertEqual(
            sorted([r.id for r in results]),
            [g.id for g in (self.genus, g2, g3)],
        )

    def test_search_by_gt_and_lt_query(self):
        """query with MapperSearch, single table, > AND <"""

        # test does not depend on plugin functionality
        family2 = Family(family="family2")
        genus2 = Genus(family=family2, genus="genus2")
        f3 = Family(family="fam3")
        g3 = Genus(family=f3, genus="genus2")
        g4 = Genus(family=f3, genus="genus4")
        self.session.add_all([family2, genus2, f3, g3, g4])
        self.session.commit()

        mapper_search = search.strategies.get_strategy("MapperSearch")
        self.assertTrue(
            isinstance(mapper_search, search.strategies.MapperSearch)
        )

        s = "genus where id>1 AND id<3"
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].id, 2)

        s = "genus where id>0 AND id<3"
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertEqual(len(results), 2)
        self.assertEqual(set(i.id for i in results), set([1, 2]))

    def test_search_by_query_joined_tables(self):
        """query with MapperSearch, joined tables, one predicate"""

        # test does not depend on plugin functionality
        family2 = Family(family="family2")
        genus2 = Genus(family=family2, genus="genus2")
        self.session.add_all([family2, genus2])
        self.session.commit()

        mapper_search = search.strategies.get_strategy("MapperSearch")
        self.assertTrue(
            isinstance(mapper_search, search.strategies.MapperSearch)
        )

        # search cls.parent.column
        s = "genus where family.family=family1"
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertEqual(len(results), 1)
        g0 = list(results)[0]
        self.assertTrue(isinstance(g0, Genus))
        self.assertEqual(g0.id, self.genus.id)

        # search cls.children.column
        s = "family where genera.genus=genus1"
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertEqual(len(results), 1)
        f = list(results)[0]
        self.assertEqual(len(results), 1)
        self.assertTrue(isinstance(f, Family))
        self.assertEqual(f.id, self.family.id)

    def test_search_by_and_query_joined_tables(self):
        """query with MapperSearch, joined tables, multiple predicates"""

        # test does not depend on plugin functionality
        family2 = Family(family="family2")
        g2 = Genus(family=family2, genus="genus2")
        f3 = Family(family="fam3", qualifier="s. lat.")
        g3 = Genus(family=f3, genus="genus3")
        self.session.add_all([family2, g2, f3, g3])
        self.session.commit()

        mapper_search = search.strategies.get_strategy("MapperSearch")
        self.assertTrue(
            isinstance(mapper_search, search.strategies.MapperSearch)
        )

        s = "genus where genus=genus2 AND family.family=fam3"
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertEqual(len(results), 0)

        s = "genus where genus=genus3 AND family.family=fam3"
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertEqual(len(results), 1)
        g0 = list(results)[0]
        self.assertTrue(isinstance(g0, Genus))
        self.assertEqual(g0.id, g3.id)

        s = 'genus where family.family="Orchidaceae" AND family.qualifier=""'
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertEqual(results, [])

        s = 'genus where family.family=fam3 AND family.qualifier=""'
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertEqual(results, [])

        # sqlite3 stores None as the empty string.
        s = 'genus where family.qualifier=""'
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertEqual(results, [g2])

        # test where the column is ambiguous so make sure we choose
        # the right one, in this case we want to make sure we get the
        # qualifier on the family and not the genus
        s = (
            'plant where accession.species.genus.family.family="Orchidaceae" '
            'AND accession.species.genus.family.qualifier=""'
        )
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertEqual(results, [])

    def test_search_by_symbol_query(self):
        """query with &&, ||, !"""

        # test does not depend on plugin functionality
        family2 = Family(family="family2")
        g2 = Genus(family=family2, genus="genus2")
        f3 = Family(family="fam3", qualifier="s. lat.")
        g3 = Genus(family=f3, genus="genus3")
        self.session.add_all([family2, g2, f3, g3])
        self.session.commit()

        mapper_search = search.strategies.get_strategy("MapperSearch")
        self.assertTrue(
            isinstance(mapper_search, search.strategies.MapperSearch)
        )

        s = "genus where genus=genus2 && family.family=fam3"
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertEqual(len(results), 0)

        s = "family where family=family1 || family=fam3"
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertEqual(len(results), 2)

        s = "family where ! family=family1"
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertEqual(len(results), 2)

    def test_search_by_query_none(self):
        """query with MapperSearch, joined tables, predicates using None

        results are irrelevant, because sqlite3 uses the empty string to
        represent None
        """

        # test does not depend on plugin functionality
        family2 = Family(family="family2")
        g2 = Genus(family=family2, genus="genus2")
        f3 = Family(family="fam3", qualifier="s. lat.")
        g3 = Genus(family=f3, genus="genus3")
        self.session.add_all([family2, g2, f3, g3])
        self.session.commit()

        mapper_search = search.strategies.get_strategy("MapperSearch")
        self.assertTrue(
            isinstance(mapper_search, search.strategies.MapperSearch)
        )

        s = "genus where family.qualifier is None"
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertEqual(results, [])

        # make sure None isn't treated as the string 'None' and that
        # the query picks up the is operator
        s = "genus where author is None"
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertEqual(results, [])

        # NOTE Genus.author has default of ''
        s = "genus where author not None"
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertCountEqual(results, [self.genus, g2, g3])

        s = "genus where author != None"
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertCountEqual(results, [self.genus, g2, g3])

        s = 'genus where NOT author = ""'
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertCountEqual(results, [])

    def test_search_by_query_id_joined_tables(self):
        """query with MapperSearch, joined tables, test on id of dependent
        table
        """

        # test does not depend on plugin functionality
        family2 = Family(family="family2")
        genus2 = Genus(family=family2, genus="genus2")
        f3 = Family(family="fam3")
        g3 = Genus(family=f3, genus="genus3")
        self.session.add_all([family2, genus2, f3, g3])
        self.session.commit()

        mapper_search = search.strategies.get_strategy("MapperSearch")
        self.assertTrue(
            isinstance(mapper_search, search.strategies.MapperSearch)
        )

        # id is an ambiguous column because it occurs on plant,
        # accesion and species...the results here don't matter as much
        # as the fact that the query doesn't raise and exception
        s = "plant where accession.species.id=1"
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertEqual(len(results), 0)

    def test_search_by_like_percent_query_joined_table(self):
        """query with MapperSearch, joined tables, LIKE %"""

        # test does not depend on plugin functionality
        family2 = Family(family="family2")
        family3 = Family(family="afamily3")
        family4 = Family(family="family%")
        genus21 = Genus(family=family2, genus="genus21")
        genus31 = Genus(family=family3, genus="genus31")
        genus32 = Genus(family=family3, genus="genus32")
        genus33 = Genus(family=family3, genus="genus33")
        genus41 = Genus(family=family4, genus="genus41")
        f3 = Family(family="fam3")
        g3 = Genus(family=f3, genus="genus31")
        self.session.add_all(
            [
                family4,
                family3,
                family2,
                genus21,
                genus31,
                genus32,
                genus33,
                genus41,
                f3,
                g3,
            ]
        )
        self.session.commit()

        mapper_search = search.strategies.get_strategy("MapperSearch")
        self.assertTrue(
            isinstance(mapper_search, search.strategies.MapperSearch)
        )

        # test partial string matches on a query
        s = "genus where family.family like family%"
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertCountEqual(results, [self.genus, genus21, genus41])
        # escaped
        s = "genus where family.family like 'family\\%'"
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertEqual(results, [genus41])

    def test_search_by_like_underscore_query_joined_table(self):
        """query with MapperSearch, joined tables, LIKE _"""

        # test does not depend on plugin functionality
        family2 = Family(family="family2")
        family3 = Family(family="afamily3")
        family4 = Family(family="_family4")
        family4b = Family(family="afamily4")
        genus21 = Genus(family=family2, genus="genus21")
        genus31 = Genus(family=family3, genus="genus31")
        genus32 = Genus(family=family3, genus="genus32")
        genus33 = Genus(family=family3, genus="genus33")
        genus41 = Genus(family=family4, genus="genus41")
        genus42 = Genus(family=family4b, genus="genus42")
        f3 = Family(family="fam3")
        g3 = Genus(family=f3, genus="genus31")
        self.session.add_all(
            [
                family4b,
                family4,
                family3,
                family2,
                genus21,
                genus31,
                genus32,
                genus33,
                genus41,
                genus42,
                f3,
                g3,
            ]
        )
        self.session.commit()

        mapper_search = search.strategies.get_strategy("MapperSearch")
        self.assertTrue(
            isinstance(mapper_search, search.strategies.MapperSearch)
        )

        # test _ at end of string query
        s = "genus where family.family like family_"
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertCountEqual(results, [self.genus, genus21])
        # test _ at start of string query
        s = "genus where family.family like _family3"
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertCountEqual(results, [genus31, genus32, genus33])
        # test _ in middle of string query
        s = "genus where family.family like fa_ily2"
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertEqual(results, [genus21])
        # escaped _
        s = "genus where family.family like '\\_family4'"
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertEqual(results, [genus41])
        # not escaped
        s = "genus where family.family like _family4"
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertCountEqual(results, [genus41, genus42])

    def test_search_by_datestring_query(self):

        family2 = Family(family="family2")
        g2 = Genus(family=family2, genus="genus2")
        f3 = Family(family="fam3", qualifier="s. lat.")
        g3 = Genus(family=f3, genus="Ixora")
        sp = Species(sp="coccinea", genus=g3)
        ac = Accession(species=sp, code="1979.0001")
        ac.date_recvd = datetime.date(2021, 11, 21)
        a2 = Accession(species=sp, code="1979.0002")
        a2.date_recvd = datetime.datetime.today()
        lc = Location(name="loc1", code="loc1")
        pp = Plant(accession=ac, code="01", location=lc, quantity=1)
        p2 = Plant(accession=ac, code="02", location=lc, quantity=1)

        pp._last_updated = datetime.datetime(2009, 2, 13).astimezone(
            tz=timezone.utc
        )
        yesterday = (
            datetime.datetime.now() - datetime.timedelta(days=1)
        ).astimezone(tz=timezone.utc)
        p2._last_updated = yesterday

        self.session.add_all([family2, g2, f3, g3, sp, ac, lc, pp, p2])
        self.session.commit()

        mapper_search = search.strategies.get_strategy("MapperSearch")
        self.assertTrue(
            isinstance(mapper_search, search.strategies.MapperSearch)
        )

        # DateTime type:
        s = "plant where _last_updated < 1.1.2000"
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertEqual(results, [])

        s = "plant where _created > yesterday"
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertCountEqual(results, [pp, p2])

        s = "plant where _created > -5"
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertCountEqual(results, [pp, p2])

        s = "plant where _last_updated > 1-1-2000"
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertCountEqual(results, [pp, p2])

        # isoparse
        s = "plant where _last_updated < 2000-01-01"
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertEqual(results, [])

        s = (
            "plant where _last_updated >= 13/2/2009 "
            "and _last_updated < 14/2/2009"
        )
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertEqual(results, [pp])

        s = "plant where _last_updated between 13/2/2009 and 14/2/2009"
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertEqual(results, [pp])

        logger.debug("CREATED = %s", pp._created)
        s = "plant where _last_updated between yesterday and today"
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertEqual(results, [p2])

        s = "plant where _last_updated on 13/2/2009"
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertEqual(results, [pp])

        # isoparse
        s = "plant where _last_updated on 2009-02-13"
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertEqual(results, [pp])

        s = "plant where _created on 0"
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertCountEqual(results, [pp, p2])

        s = "plant where _created on today"
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertCountEqual(results, [pp, p2])

        s = "plant where _last_updated on -1"
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertEqual(results, [p2])

        s = "plant where _last_updated on yesterday"
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertEqual(results, [p2])

        s = "plant where _created > -10"
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertCountEqual(results, [pp, p2])

        # Date type:
        s = "accession where date_recvd = today"
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertEqual(results, [a2])

        s = "accession where date_recvd = 0"
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertEqual(results, [a2])

        s = "accession where date_recvd > -10"
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertEqual(results, [a2])

        s = "accession where date_recvd on 21/11/2021"
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertEqual(results, [ac])

        # fuzzy parse
        s = "accession where date_recvd on 'the 21st of November 21`'"
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertEqual(results, [ac])

        s = "accession where date_recvd = 21/11/2021"
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertEqual(results, [ac])

        s = "accession where date_recvd on 22/11/2021"
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertEqual(results, [])

        s = "accession where date_recvd on 20/11/2021"
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertEqual(results, [])

        s = (
            "accession where date_recvd < 20/11/2021 and "
            "date_recvd > 22/11/2021"
        )
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertEqual(results, [])

        # days of week as strings search
        today_date = datetime.date.today()
        yesterday_date = today_date - datetime.timedelta(days=1)
        today_str = today_date.strftime("%A")
        yesterday_str = yesterday_date.strftime("%A")
        s = (
            "plant where _last_updated between "
            f"{yesterday_str} and {today_str}"
        )
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertEqual(results, [p2])

        # fuzzy date strings
        today_date = datetime.date.today()
        yesterday_date = today_date - datetime.timedelta(days=1)
        today_str = today_date.strftime("%A")
        yesterday_str = yesterday_date.strftime("%A")
        today_mth = today_date.strftime("%B")
        yesterday_mth = yesterday_date.strftime("%B")
        today_day = today_date.strftime("%d").lstrip("0")
        yesterday_day = yesterday_date.strftime("%d").lstrip("0")
        yesterday_day += {
            "1": "st",
            "2": "nd",
            "3": "rd",
        }.get(yesterday_day, "th")
        s = (
            "plant where _last_updated between "
            f"'{yesterday_str} the {yesterday_day} of {yesterday_mth}' and "
            f"'{today_str} {today_day} {today_mth}'"
        )
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertEqual(results, [p2])

    def test_search_by_datestring_query_tz_limits(self):

        family2 = Family(family="family2")
        g2 = Genus(family=family2, genus="genus2")
        f3 = Family(family="fam3", qualifier="s. lat.")
        g3 = Genus(family=f3, genus="Ixora")
        sp = Species(sp="coccinea", genus=g3)
        ac = Accession(species=sp, code="1979.0001")
        lc = Location(name="loc1", code="loc1")
        pp = Plant(accession=ac, code="01", location=lc, quantity=1)
        pp2 = Plant(accession=ac, code="02", location=lc, quantity=1)

        # these will store UTC datetimes relative to local time.  Both should
        # be on the same date locally but will be across 2 dates if the local
        # timezone is anything but +00:00
        start_of_day = datetime.datetime(2009, 2, 12, 0, 0, 0, 0).astimezone(
            tz=timezone.utc
        )
        pp._last_updated = start_of_day
        end_of_day = datetime.datetime(2009, 2, 12, 23, 59, 0, 0).astimezone(
            tz=timezone.utc
        )
        pp2._last_updated = end_of_day
        self.session.add_all([family2, g2, f3, g3, sp, ac, lc, pp, pp2])
        self.session.commit()

        mapper_search = search.strategies.get_strategy("MapperSearch")
        self.assertTrue(
            isinstance(mapper_search, search.strategies.MapperSearch)
        )
        logger.debug("pp last updated: %s", pp._last_updated)
        logger.debug("pp2 last updated: %s", pp2._last_updated)

        # isoparse
        s = "plant where _last_updated on 2009-02-12"
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertCountEqual(results, [pp, pp2])

        s = "plant where _last_updated on 12/2/2009"
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertCountEqual(results, [pp, pp2])

        # hybrid property
        pp.planted.date = start_of_day
        pp2.planted.date = end_of_day
        self.session.add_all([pp, pp2])
        self.session.commit()
        s = "plant where planted.date on 12/2/2009"
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertCountEqual(results, [pp, pp2])

    def test_between_evaluate(self):
        "use BETWEEN value and value"
        family2 = Family(family="family2")
        g2 = Genus(family=family2, genus="genus2")
        f3 = Family(family="fam3", qualifier="s. lat.")
        g3 = Genus(family=f3, genus="Ixora")
        sp = Species(sp="coccinea", genus=g3)
        ac = Accession(species=sp, code="1979.0001")
        self.session.add_all([family2, g2, f3, g3, sp, ac])
        self.session.commit()

        s = 'accession where code between "1978" and "1980"'
        results = search.search(s, self.session)
        self.assertEqual(results, [ac])
        s = 'accession where code between "1980" and "1980"'
        results = search.search(s, self.session)
        self.assertEqual(results, [])

    def test_search_by_query_synonyms(self):
        """SynonymSearch strategy gives all synonyms of given taxon."""
        family2 = Family(family="family2")
        g2 = Genus(family=family2, genus="genus2")
        f3 = Family(family="fam3", qualifier="s. lat.")
        g3 = Genus(family=f3, genus="Ixora")
        g4 = Genus(family=f3, genus="Schetti")
        g4.accepted = g3
        self.session.add_all([family2, g2, f3, g3, g4])
        self.session.commit()

        prefs.prefs["bauble.search.return_accepted"] = True

        s = "Schetti"
        search.search(s, self.session)
        results = result_cache.get("SynonymSearch")
        self.assertEqual(results, [g3])

    def test_search_by_query_synonyms_disabled(self):
        family2 = Family(family="family2")
        g2 = Genus(family=family2, genus="genus2")
        f3 = Family(family="fam3", qualifier="s. lat.")
        g3 = Genus(family=f3, genus="Ixora")
        g4 = Genus(family=f3, genus="Schetti")
        self.session.add_all([family2, g2, f3, g3, g4])
        g4.accepted = g3
        self.session.commit()

        prefs.prefs["bauble.search.return_accepted"] = False

        s = "Schetti"
        search.search(s, self.session)
        # SynonymsSearch should not run, nothing in results_cache
        results = result_cache.get("SynonymSearch")
        self.assertIsNone(results)

    def test_search_by_query_vernacular(self):
        family2 = Family(family="family2")
        g2 = Genus(family=family2, genus="genus2")
        f3 = Family(family="fam3", qualifier="s. lat.")
        g3 = Genus(family=f3, genus="Ixora")
        sp = Species(sp="coccinea", genus=g3)
        vn = VernacularName(name="coral rojo", language="es", species=sp)
        self.session.add_all([family2, g2, f3, g3, sp, vn])
        self.session.commit()

        vl_search = search.strategies.get_strategy("ValueListSearch")
        self.assertTrue(
            isinstance(vl_search, search.strategies.ValueListSearch)
        )

        s = "rojo"
        results = []
        for i in vl_search.search(s, self.session):
            results.extend(i)
        self.assertEqual(results, [vn])

    def test_search_ambiguous_joins_no_results(self):
        """These joins broke down when upgrading to SQLA 1.4"""
        mapper_search = search.strategies.get_strategy("MapperSearch")
        self.assertTrue(
            isinstance(mapper_search, search.strategies.MapperSearch)
        )

        s = "genus where _synonyms.synonym.id != 0"
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertEqual(results, [])

        s = (
            "geography where code = '50' or "
            "parent.code = '50' or "
            "parent.parent.code = '50'"
        )
        results = search.search(s, self.session)
        self.assertEqual(results, [])

        s = (
            "plant where accession.species.genus.family.genera.epithet "
            "= 'Ficus'"
        )
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertEqual(results, [])

        # possible: SAWarning: SELECT statement has a cartesian product between
        # FROM element(s) "species" and FROM element "species_1"
        with warnings.catch_warnings(record=True) as warns:
            warnings.simplefilter("always")
            s = (
                "species where sp = 'viminalis' and _accepted.species.sp"
                " = 'sp'"
            )
            results = []
            for i in mapper_search.search(s, self.session):
                results.extend(i)
            self.assertEqual(results, [])
            self.assertEqual(warns, [])
            warnings.resetwarnings()

    def test_search_ambiguous_joins_w_results(self):
        """These joins broke down when upgrading to SQLA 1.4"""

        setup_geographies()

        g2 = Genus(family=self.family, genus="genus2")
        self.genus.accepted = g2
        f1 = Family(epithet="Moraceae")
        g3 = Genus(family=f1, genus="Ficus")
        g4 = Genus(family=f1, genus="Artocarpus")
        sp1 = Species(genus=g3, epithet="virens")
        sp2 = Species(genus=g4, epithet="heterophyllus")
        sp3 = Species(sp="sp", genus=g3)
        self.session.add_all([g2, g3, g4, f1, sp1, sp2, sp3])
        sp1.accepted = sp3
        self.session.commit()

        mapper_search = search.strategies.get_strategy("MapperSearch")
        self.assertTrue(
            isinstance(mapper_search, search.strategies.MapperSearch)
        )

        s = "genus where _synonyms.synonym.id != 0"
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertEqual(results, [g2])

        s = (
            "geography where code = '50' or "
            "parent.code = '50' or "
            "parent.parent.code = '50'"
        )
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        expected = [
            "WAU-AC",
            "50",
            "NSW-CT",
            "QLD-CS",
            "NFK-LH",
            "NSW",
            "NSW-NS",
            "NFK-NI",
            "NFK",
            "NTA",
            "QLD",
            "QLD-QU",
            "SOA",
            "TAS",
            "VIC",
            "WAU-WA",
            "WAU",
        ]

        self.assertCountEqual([i.code for i in results], expected)

        s = "species where genus.family.genera.epithet = 'Ficus'"
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertCountEqual(results, [sp1, sp2, sp3])

        # possible: SAWarning: SELECT statement has a cartesian product between
        # FROM element(s) "species" and FROM element "species_1"
        with warnings.catch_warnings(record=True) as warns:
            warnings.simplefilter("always")
            s = (
                "species where sp = 'virens' and _accepted.species.sp"
                " = 'sp'"
            )
            results = []
            for i in mapper_search.search(s, self.session):
                results.extend(i)
            self.assertEqual(results, [sp1])
            self.assertEqual(warns, [])
            warnings.resetwarnings()

    def test_complex_query(self):
        """Something with multiple joins, and, or, parethesis, not, between, a
        filter, in, between and a hybrid property

        Tests that parsing and query formation happens as expected in complex
        queries.
        """

        g2 = Genus(family=self.family, genus="genus2")
        f1 = Family(epithet="Moraceae")
        g3 = Genus(family=f1, genus="Ficus")
        g4 = Genus(family=f1, genus="Artocarpus")
        sp1 = Species(genus=g3, epithet="virens")
        sp2 = Species(genus=g4, epithet="heterophyllus")
        sp3 = Species(sp="sp", genus=g3)
        ac = Accession(species=sp2, code="1979.0001", quantity_recvd=10)
        a2 = Accession(species=sp1, code="1979.0002", quantity_recvd=5)
        sd = SourceDetail(source_type="Individual", name="Jade Green")
        ac3 = Accession(
            species=sp2,
            code="2023.0003",
            quantity_recvd=10,
            source=Source(source_detail=sd),
        )
        lc = Location(name="loc1", code="loc1")
        lc2 = Location(name="loc2", code="loc2")
        lc3 = Location(name="Zone One", code="zone1")
        pp = Plant(accession=ac, code="01", location=lc, quantity=1)
        p2 = Plant(accession=ac, code="02", location=lc2, quantity=1)
        plt3 = Plant(accession=ac3, code="02", location=lc3, quantity=1)
        self.session.add_all(
            [g2, g3, g4, f1, sp1, sp2, sp3, ac, a2, lc, lc2, pp, p2, plt3]
        )
        self.session.commit()

        mapper_search = search.strategies.get_strategy("MapperSearch")
        self.assertTrue(
            isinstance(mapper_search, search.strategies.MapperSearch)
        )

        s = (
            "species where active is True and not "
            "(accessions[_created > -1].quantity_recvd in 5, 6 or "
            "accessions.plants.location.code = 'loc2') and id "
            "BETWEEN 1 and 20"
        )
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)

        self.assertCountEqual(results, [sp3])

        s = (
            "species where active is True and not "
            "(accessions[_created > -1].quantity_recvd in 7, 6 or "
            "accessions.plants.location.code = 'loc1') and id "
            "BETWEEN 0 and 1"
        )
        results = search.search(s, self.session)
        self.assertCountEqual(results, [sp1])

        # with filter on aggregating function
        s = (
            "species where active is True and not "
            "(sum(accessions[_created > -1].quantity_recvd) = 13 or "
            "accessions.plants.location.code = 'loc1') and id "
            "BETWEEN 0 and 1"
        )
        results = search.search(s, self.session)
        self.assertCountEqual(results, [sp1])

        s = (
            "species where active is False and not "
            "(accessions[_created > -1].quantity_recvd in 7, 6 or "
            "accessions.plants.location.code = 'loc1') and id "
            "BETWEEN 0 and 1"
        )
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)

        self.assertCountEqual(results, [])
        # include an AssociationProxy
        sp3.accepted = sp1
        self.session.commit()
        s = (
            "species where accepted.sp = 'virens' and not "
            "(accessions[_created > -1].quantity_recvd in 5, 6 or "
            "accessions.plants.location.code = 'loc2') and id "
            "BETWEEN 1 and 20"
        )
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertCountEqual(results, [sp3])

        # and and not query
        s = (
            "accession where code like '2023%' and source.source_detail.name "
            "contains 'Green' and not plants.location.code contains 'loc'"
        )
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertCountEqual(results, [ac3])

        # multiple association_proxy pointing to same table SpeciesSynonym
        # this is pointless query but still shouldn't error
        string = (
            "species where synonyms.id != 0 and "
            "accepted.distribution.geography.name = 'Queensland'"
        )
        results = []
        for i in mapper_search.search(string, self.session):
            results.extend(i)
        # not expecting a result just that it doesn't error
        self.assertCountEqual(results, [])

        # multiple association_proxy pointing to same table SpeciesSynonym...
        # including an Aggregating function
        string = "species where synonyms.id != 0 and count(synonyms.id) > 0"
        results = search.search(string, self.session)
        self.assertCountEqual(results, [sp1])

        # AND needing joins (NOTE this does not invoke
        # BinaryLogicalExpression.needs_join)
        string = (
            "plant where accession.species.epithet=heterophyllus and "
            "location.code = loc1"
        )
        results = search.search(string, self.session)
        self.assertCountEqual(results, [pp])

        # multiple filters at multiple levels (first part should fail but
        # second succeed)
        string = (
            "species where accessions[_created>-1, quantity_recvd>5]"
            ".plants[active=True].location"
            ".notes[category=test].note = test or "
            "accessions[_created>-1].plants[id>0].location.code = loc1"
        )

        results = []
        for i in mapper_search.search(string, self.session):
            results.extend(i)

        self.assertCountEqual(results, [sp2])

    def test_search_strips_leading_spaces(self):

        fam = Family(epithet="Rutaceae")
        gen = Genus(family=fam, epithet="Flindersia")
        sp = Species(genus=gen, epithet="brayleyana")
        self.session.add(sp)
        self.session.commit()
        results = search.search("  Flindersia brayleyana  ", self.session)
        self.assertEqual(results, [sp])


class SearchTests3(BaubleClassTestCase):
    @classmethod
    def setUpClass(cls):
        # setup once for all tests
        super().setUpClass()
        for func in get_setUp_data_funcs():
            func()

    def test_search_by_expression_unknown_domain_fails(self):
        domain_search = search.strategies.get_strategy("DomainSearch")
        self.assertTrue(
            isinstance(domain_search, search.strategies.DomainSearch)
        )
        string = "unknown = 2"
        self.assertRaises(
            ParseException, domain_search.search, string, self.session
        )

    def test_search_by_expression_in(self):
        domain_search = search.strategies.get_strategy("DomainSearch")
        self.assertTrue(
            isinstance(domain_search, search.strategies.DomainSearch)
        )
        string = "genus in Maxillaria, Laelia"
        results = []
        for i in domain_search.search(string, self.session):
            results.extend(i)
        self.assertEqual(len(results), 2)
        for i in results:
            self.assertIn(i.epithet, ["Maxillaria", "Laelia"])
        # numeric fields
        string = "acc in 2001.1 2020.2"
        results = []
        for i in domain_search.search(string, self.session):
            results.extend(i)
        self.assertEqual(len(results), 2)
        for i in results:
            self.assertIn(i.code, ["2001.1", "2020.2"])
        # No result
        string = "acc in 4001.1 4020.2"
        results = []
        for i in domain_search.search(string, self.session):
            results.extend(i)
        self.assertEqual(len(results), 0)

    def test_complex_query_parenthesised(self):
        # parenthesised
        string = "plant where (quantity > 1 or geojson = None) and id > 3"
        results = search.search(string, self.session)
        self.assertCountEqual([i.id for i in results], [4, 5])
        string = "plant where id > 3 and (quantity = 1 or geojson = None) "
        results = search.search(string, self.session)
        self.assertCountEqual([i.id for i in results], [4, 5])
        string = "plant where id > 3 and (quantity = 1 or geojson != None) "
        results = search.search(string, self.session)
        self.assertCountEqual([i.id for i in results], [])
        string = (
            "plant where accession.species.genus.family.epithet = "
            "'Leguminosae' and (accession.id_qual = '?' or "
            "accession.species.epithet = 'sp.')"
        )
        results = search.search(string, self.session)
        self.assertCountEqual([i.id for i in results], [5])
        string = (
            "plant where accession.species.family_name = 'Leguminosae' and "
            "(accession.id_qual = '?' or accession.species.epithet = 'sp.')"
        )
        results = search.search(string, self.session)
        self.assertCountEqual([i.id for i in results], [5])
        string = (
            "plant where (accession.id_qual = '?' or "
            "accession.species.epithet = 'sp.') and "
            "accession.species.family_name = 'Leguminosae'"
        )
        results = search.search(string, self.session)
        self.assertCountEqual([i.id for i in results], [5])
        string = (
            "plant where (accession.id_qual = '?' or "
            "accession.species.epithet = 'sp.') and "
            "(accession.species.family_name = 'Arecaceae' or "
            "accession.species.family_name = 'Leguminosae')"
        )
        results = search.search(string, self.session)
        self.assertCountEqual([i.id for i in results], [5])
        string = (
            "plant where (accession.id_qual = '?' or "
            "accession.species.genus.qualifier = 's. str') and "
            "(accession.species.family_name = 'Orchidaceae' or "
            "accession.species.family_name = 'Leguminosae')"
        )
        results = search.search(string, self.session)
        self.assertCountEqual([i.id for i in results], [1, 5])
        string = (
            "plant where (accession.id_qual = '?' and "
            "accession.species.family_name = 'Leguminosae' ) or "
            "(accession.species.genus.qualifier = 's. str' and "
            "accession.species.family_name = 'Orchidaceae')"
        )
        results = search.search(string, self.session)
        self.assertCountEqual([i.id for i in results], [1, 5])

    def test_filter_by_in_expression(self):
        # accession whith plants in only in one of these locations
        string = (
            "accession where count(plants.location[code in RBW, URBW].id) = 1"
        )
        results = search.search(string, self.session)
        self.assertCountEqual([i.id for i in results], [1, 5, 6])

        string = "plant where accession[id in 1, 4].species.id = 1"
        results = search.search(string, self.session)
        self.assertCountEqual([i.id for i in results], [1])

        string = "plant where accession[id in 1, 4].species.id = 3"
        results = search.search(string, self.session)
        self.assertCountEqual([i.id for i in results], [])

        string = "plant where accession[id in 2, 4].species.id = 2"
        results = search.search(string, self.session)
        self.assertCountEqual([i.id for i in results], [2, 3])

    def test_filter_by_in_expression_multiple(self):
        # accession with plants in only in one of these locations (note in
        # clause last as it uses comma separation)
        string = (
            "accession where count(plants.location[name!=None, "
            "description='Way up high', code in RBW, URBW].id) = 1"
        )
        results = search.search(string, self.session)
        self.assertCountEqual([i.id for i in results], [1, 5, 6])

        # note in clause first, does not use comma separate
        string = (
            "plant where accession[id in 1 4, private=True].species.id = 1"
        )
        results = search.search(string, self.session)

        # multiple in on one filter
        self.assertCountEqual([i.id for i in results], [1])
        string = (
            "plant where accession[id in 1 4, quantity_recvd in 1 10]."
            "species.id = 1"
        )
        results = search.search(string, self.session)
        self.assertCountEqual([i.id for i in results], [1])

        # not in and in on one filter
        string = (
            "plant where accession[id in 1 4, quantity_recvd not in 2 10]."
            "species.id = 1"
        )
        results = search.search(string, self.session)
        self.assertCountEqual([i.id for i in results], [1])
        # confirm above
        string = (
            "plant where accession[id in 1 4, quantity_recvd not in 1 10]."
            "species.id = 1"
        )
        results = search.search(string, self.session)
        self.assertCountEqual(results, [])

        # multiple in on one filter - should fail
        string = (
            "plant where accession[id in 1 4, quantity_recvd in 11 10]."
            "species.id = 1"
        )
        results = search.search(string, self.session)
        self.assertCountEqual([i.id for i in results], [])

        # not and not in on one filter
        string = (
            "plant where accession[id not None, quantity_recvd not in 11 10]."
            "species.id = 1"
        )
        results = search.search(string, self.session)
        self.assertCountEqual([i.id for i in results], [1])

        string = (
            "plant where accession[id in 2, 4].species[sp_author contains "
            "'(L.)', genus_id in 1, 2, 4].id = 2"
        )
        results = search.search(string, self.session)
        self.assertCountEqual([i.id for i in results], [2, 3])

    def test_recursive_expression(self):
        # plants where there is only one plant of the same species and it is in
        # this location
        string = (
            "plant where count(accession.species.accessions.plants."
            "location.id) = 1 and location.code = RBW"
        )
        results = search.search(string, self.session)
        self.assertCountEqual([i.id for i in results], [1])

    def test_recursive_function_w_distinct_expression(self):
        # plants where all plants of the same species are in this location
        string = (
            "plant where count(distinct accession.species.accessions.plants."
            "location.id) = 1 and location.code = RBW"
        )
        results = search.search(string, self.session)
        self.assertCountEqual([i.id for i in results], [1, 2, 3, 4, 5])

    def test_recursive_filtered_expression(self):
        # plant where there is only one record for this species in this
        # location
        string = (
            "plant where count(accession.species.accessions.plants."
            "location[code=RBW].id) = 1 and location.code = RBW"
        )
        results = search.search(string, self.session)
        self.assertCountEqual([i.id for i in results], [1])
        # plant where there is only one record for this species are in either
        # of these locations
        string = (
            "plant where count(accession.species.accessions.plants."
            "location[code in RBW, URBW].id) = 1 and location.code"
            " in RBW, URBW"
        )
        results = search.search(string, self.session)
        self.assertCountEqual([i.id for i in results], [1])

    def test_filter_by_like_expression(self):
        string = (
            "genus where species[epithet like cochl%].accessions."
            "plants.quantity = 1"
        )
        results = search.search(string, self.session)
        self.assertCountEqual([i.id for i in results], [2])
        # recursive should return all species of the genera
        string = (
            "species where genus[epithet like Encyc%].species.accessions."
            "plants.quantity = 1"
        )
        results = search.search(string, self.session)
        self.assertCountEqual([i.id for i in results], [2, 5, 6, 15, 20])

    def test_filter_by_contains_expression(self):
        prefs.prefs["bauble.search.return_accepted"] = False
        string = (
            "genus where species[epithet contains ochlea].accessions."
            "plants.quantity = 1"
        )
        results = search.search(string, self.session)
        self.assertCountEqual([i.id for i in results], [2])
        # recursive should return all species of the genera
        string = (
            "species where genus[epithet contains cycli].species.accessions."
            "plants.quantity = 1"
        )
        results = search.search(string, self.session)
        self.assertCountEqual([i.id for i in results], [2, 5, 6, 15, 20])

    def test_nested_functions(self):
        string = "genus where length(species.full_sci_name) = 46"
        results1 = search.search(string, self.session)

        string = "genus where max(length(species.full_sci_name)) = 46"
        results2 = search.search(string, self.session)

        self.assertNotEqual(results2, results1)
        self.assertCountEqual([i.id for i in results1], [1, 3])
        self.assertCountEqual([i.id for i in results2], [1])

    def test_not_in_expression(self):
        prefs.prefs["bauble.search.return_accepted"] = False
        string = "family where id not in 1, 2, 3, 4, 5"
        results = search.search(string, self.session)
        self.assertCountEqual(
            [i.id for i in results], [6, 7, 8, 9, 10, 11, 12]
        )

        # composite contradicting
        string = "genus where id < 3 and id not in 1, 2, 3"
        results = search.search(string, self.session)
        self.assertCountEqual(results, [])

    def test_string_with_escape_characters(self):

        note1 = GenusNote(category="bar", note="test\\test\\test", genus_id=1)
        note2 = GenusNote(category="foo", note="test\ntest", genus_id=2)
        self.session.add_all([note1, note2])
        self.session.commit()

        string = (
            "genus where notes[category='bar'].note='test\\\\test\\\\test'"
        )
        results = search.search(string, self.session)

        self.assertCountEqual([i.id for i in results], [1])

        string = "genus where notes[category='foo'].note='test\\ntest'"
        results = search.search(string, self.session)

        self.assertCountEqual([i.id for i in results], [2])

    def test_all_domains_search(self):

        # NOTE test data already has species 1 _last_updated days + 1 so need
        # to use + 2 here.
        date = utils.utcnow_naive() + datetime.timedelta(days=2)

        loc_pic = LocationPicture(
            picture="test.jpg",
            user="Jade Green",
            date=datetime.datetime.today(),
            location_id=1,
            _last_updated=date,
        )
        plt_pic = PlantPicture(
            picture="test.jpg",
            user="Jade Green",
            date=datetime.datetime.today(),
            plant_id=1,
        )
        sp_pic = SpeciesPicture(
            picture="test.jpg",
            user="Forrest Gardener",
            date=datetime.datetime.today(),
            species_id=1,
            _last_updated=date,
        )
        self.session.add_all([loc_pic, plt_pic, sp_pic])
        self.session.commit()
        prefs.prefs[prefs.return_accepted_pref] = False

        string = "domains where id = 1"
        results = search.search(string, self.session)

        self.assertCountEqual(
            {type(i) for i in results},
            search.strategies.MapperSearch.get_domain_classes().values(),
        )

        string = "domains where _pictures[date=Today].picture = test.jpg"
        results = search.search(string, self.session)

        self.assertCountEqual(
            {(type(i).__tablename__, i.id) for i in results},
            [("species", 1), ("plant", 1), ("location", 1)],
        )

        string = "domains where _pictures[user='Jade Green'].date = Today"
        results = search.search(string, self.session)

        self.assertCountEqual(
            {(type(i).__tablename__, i.id) for i in results},
            [("plant", 1), ("location", 1)],
        )

        # test updated
        string = "domains where updated on 2"
        results = search.search(string, self.session)

        self.assertCountEqual(
            {(type(i).__tablename__, i.id) for i in results},
            [("species", 1), ("location", 1)],
        )

        # test the error
        string = "domains where foo = bar"

        self.assertRaises(AttributeError, search.search, string, self.session)

    def test_search_with_whitespace_only(self):
        string = "species where epithet contains ' '"
        results = search.search(string, self.session)
        self.assertCountEqual([i.id for i in results], [27])

        string = "species where epithet like '% %'"
        results = search.search(string, self.session)
        self.assertCountEqual([i.id for i in results], [27])

    def test_chained_or_statements(self):
        # chained `or` statements (the `or` parts outside the parenthesised
        # tests Query type inside tests Select type)
        string = (
            "species where id = 31 or id = 32 or id = 33 or "
            "(epithet like gil% or epithet like noct% or epithet like asp%)"
        )

        results = search.search(string, self.session)

        self.assertCountEqual([i.id for i in results], [31, 32, 33])


class SubQueryTests(BaubleClassTestCase):
    @classmethod
    def setUpClass(cls):
        # setup once for all tests
        super().setUpClass()
        for func in get_setUp_data_funcs():
            func()
        prefs.prefs["bauble.search.return_accepted"] = False

    def test_identifier_search(self):
        # species with a habit entry
        string = "species where habit.code in (habit.code)"
        results = search.search(string, self.session)
        self.assertCountEqual(results, [])
        # accession with a source name
        string = (
            "accession where source.source_detail.name in (source_detail.name)"
        )
        results = search.search(string, self.session)
        self.assertCountEqual([i.id for i in results], [1, 4, 5])

    def test_identifier_search_w_correlate(self):
        # correlated identifier only
        # handy to find errors
        string = (
            "accession where count(plants.id) > 1 and quantity_recvd in "
            "(plant.quantity correlate)"
        )
        results = search.search(string, self.session)
        self.assertCountEqual([i.id for i in results], [])

        string = "accession where quantity_recvd in (plant.quantity correlate)"
        results = search.search(string, self.session)
        self.assertCountEqual([i.id for i in results], [1])

        # can't correlate unrelated
        string = (
            "accession where source.source_detail.name in "
            "(source_detail.name correlate)"
        )
        self.assertRaises(
            error.SearchException, search.search, string, self.session
        )

    def test_where_search(self):
        string = (
            "accession where plants.location.code in (location.code where "
            "plants.accession.code = '2001.1')"
        )
        results = search.search(string, self.session)
        self.assertCountEqual([i.id for i in results], [1, 2, 5, 6])
        # same as above
        string = (
            "accession where plants.location.code in (plant.location.code "
            'where accession.code = "2001.1")'
        )
        results = search.search(string, self.session)
        self.assertCountEqual([i.id for i in results], [1, 2, 5, 6])
        # Not domain
        string = (
            "location where id in (intended_location.location_id where "
            "accession.code = '2001.1')"
        )
        results = search.search(string, self.session)
        self.assertCountEqual(results, [])
        # not in
        string = (
            "location where id not in (intended_location.location_id where "
            "accession.code = '2001.1')"
        )
        results = search.search(string, self.session)
        self.assertCountEqual([i.id for i in results], [1, 2, 3])
        # not in and where in
        string = (
            "location where id not in (intended_location.location_id where "
            "accession.code in '2020.1', '2022.2')"
        )
        results = search.search(string, self.session)
        self.assertCountEqual([i.id for i in results], [1, 2, 3])

    def test_where_search_w_correlate(self):
        # correlated WHERE
        string = (
            "accession where quantity_recvd in (plant.quantity where "
            "location.code = RBW correlate)"
        )
        results = search.search(string, self.session)
        self.assertCountEqual([i.id for i in results], [1])
        string = (
            "accession where quantity_recvd in (plant.quantity where "
            "location.code = SE correlate)"
        )
        results = search.search(string, self.session)
        self.assertCountEqual(results, [])

    def test_func_search(self):
        # nested func both sides
        string = (
            "genus where max(length(species.full_sci_name)) = "
            "(max(length(species.full_sci_name)))"
        )
        results = search.search(string, self.session)
        self.assertCountEqual([i.id for i in results], [2])
        # nested func
        string = (
            "species where sum(distribution.geography.approx_area) = "
            "(max(sum(species.distribution.geography.approx_area)))"
        )
        results = search.search(string, self.session)
        self.assertCountEqual([i.id for i in results], [1, 3])
        # nested func, DISTINCT
        string = (
            "accession where count(distinct plants.location.id) = "
            "(max(count(distinct accession.plants.location.id)))"
        )
        results = search.search(string, self.session)
        self.assertCountEqual([i.id for i in results], [1, 2, 5, 6])

    def test_func_search_w_correlate(self):
        # correlated function
        string = (
            "accession where quantity_recvd = (sum(plant.quantity) correlate)"
        )
        results = search.search(string, self.session)
        self.assertCountEqual([i.id for i in results], [1])
        # with LHS AND with func
        string = (
            "accession where count(plants.id) > 1 and quantity_recvd = "
            "(sum(plant.quantity) correlate)"
        )
        results = search.search(string, self.session)
        self.assertCountEqual([i.id for i in results], [])

    def test_func_search_w_where(self):
        # Syzygium with greatest distribution
        string = (
            "species where genus.epithet = Syzygium and "
            "sum(distribution.geography.approx_area) = "
            "(min(sum(species.distribution.geography.approx_area)) where "
            "genus.epithet = Syzygium)"
        )
        results = search.search(string, self.session)
        self.assertCountEqual(results, [])
        # Maxillaria with greatest distribution
        string = (
            "species where genus.epithet = Maxillaria and "
            "sum(distribution.geography.approx_area) = "
            "(min(sum(species.distribution.geography.approx_area)) where "
            "genus.epithet = Maxillaria)"
        )
        results = search.search(string, self.session)
        self.assertCountEqual([i.id for i in results], [1])
        # last updated Maxillaria
        string = (
            "species where genus.epithet = Maxillaria and _last_updated = "
            "(max(species._last_updated) where genus.epithet = Maxillaria)"
        )
        results = search.search(string, self.session)
        self.assertCountEqual([i.id for i in results], [1])
        # first updated Maxillaria
        string = (
            "species where genus.epithet = Maxillaria and _last_updated = "
            "(min(species._last_updated) where genus.epithet = Maxillaria)"
        )
        results = search.search(string, self.session)
        self.assertCountEqual([i.id for i in results], [9])

    def test_func_search_w_where_w_correlate(self):
        # correlated function with WHERE
        string = (
            "accession where quantity_recvd = (sum(plant.quantity) where "
            "location.code = URBW correlate)"
        )
        results = search.search(string, self.session)
        self.assertCountEqual(results, [])

        string = (
            "accession where quantity_recvd = (sum(plant.quantity) where "
            "location.code = RBW correlate)"
        )
        results = search.search(string, self.session)
        self.assertCountEqual([i.id for i in results], [1])

    def test_invalid_table_name_raises(self):
        # invalid table name
        string = "species where id in (id.code)"
        self.assertRaises(
            error.SearchException, search.search, string, self.session
        )


class InOperatorSearch(BaubleClassTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        db.engine.execute("delete from genus")
        db.engine.execute("delete from family")

        cls.family = Family(family="family1", qualifier="s. lat.", id=1)
        cls.g1 = Genus(family=cls.family, genus="genus1", id=1)
        cls.g2 = Genus(family=cls.family, genus="genus2", id=2)
        cls.g3 = Genus(family=cls.family, genus="genus3", id=3)
        cls.g4 = Genus(family=cls.family, genus="genus4", id=4)
        cls.Family = Family
        cls.Genus = Genus
        cls.session.add_all([cls.family, cls.g1, cls.g2, cls.g3, cls.g4])
        cls.session.commit()

    def test_in_singleton(self):
        mapper_search = search.strategies.get_strategy("MapperSearch")
        self.assertTrue(
            isinstance(mapper_search, search.strategies.MapperSearch)
        )

        s = "genus where id in 1"
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertEqual(results, [self.g1])

    def test_in_list(self):
        mapper_search = search.strategies.get_strategy("MapperSearch")
        self.assertTrue(
            isinstance(mapper_search, search.strategies.MapperSearch)
        )

        s = "genus where id in 1,2,3"
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertCountEqual(results, [self.g1, self.g2, self.g3])

    def test_in_list_no_result(self):
        mapper_search = search.strategies.get_strategy("MapperSearch")
        self.assertTrue(
            isinstance(mapper_search, search.strategies.MapperSearch)
        )

        s = "genus where id in 5,6"
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertEqual(results, [])

    def test_in_composite_expression(self):
        mapper_search = search.strategies.get_strategy("MapperSearch")
        self.assertTrue(
            isinstance(mapper_search, search.strategies.MapperSearch)
        )

        s = "genus where id in 1,2 or id>8"
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertCountEqual(results, [self.g1, self.g2])

    def test_in_composite_expression_excluding(self):
        mapper_search = search.strategies.get_strategy("MapperSearch")
        self.assertTrue(
            isinstance(mapper_search, search.strategies.MapperSearch)
        )

        s = "genus where id in 1,2,4 and id<3"
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertCountEqual(results, [self.g1, self.g2])


class BuildingSQLStatements(BaubleClassTestCase):
    def test_canfindspeciesfromgenus(self):
        "can find species from genus"

        text = "species where species.genus=genus1"
        results = search.parser.parse_string(text)
        self.assertEqual(
            str(results.query),
            "SELECT * FROM species WHERE (species.genus = 'genus1')",
        )

    def test_canuselogicaloperators(self):
        "can use logical operators"

        results = search.parser.parse_string(
            "species where species.genus=genus1 OR "
            "species.sp=name AND species.genus.family"
            ".family=name"
        )
        self.assertEqual(
            str(results.query),
            "SELECT * FROM species WHERE "
            "((species.genus = 'genus1') OR ((species.sp = 'name'"
            ") AND (species.genus.family.family = 'name')))",
        )

        results = search.parser.parse_string(
            "species where species.genus=genus1 || "
            "species.sp=name && species.genus.family."
            "family=name"
        )
        self.assertEqual(
            str(results.query),
            "SELECT * FROM species WHERE "
            "((species.genus = 'genus1') OR ((species.sp = 'name'"
            ") AND (species.genus.family.family = 'name')))",
        )

    def test_canfindfamilyfromgenus(self):
        "can find family from genus"

        results = search.parser.parse_string(
            "family where family.genus=genus1"
        )
        self.assertEqual(
            str(results.query),
            "SELECT * FROM family WHERE (" "family.genus = 'genus1')",
        )

    def test_canfindgenusfromfamily(self):
        "can find genus from family"

        results = search.parser.parse_string(
            "genus where genus.family=family2"
        )
        self.assertEqual(
            str(results.query),
            "SELECT * FROM genus WHERE (" "genus.family = 'family2')",
        )

    def test_canfindplantbyaccession(self):
        "can find plant from the accession id"

        results = search.parser.parse_string(
            "plant where accession.species.id=113"
        )
        self.assertEqual(
            str(results.query),
            "SELECT * FROM plant WHERE (" "accession.species.id = 113.0)",
        )

    def test_canuseNOToperator(self):
        "can use the NOT operator"

        results = search.parser.parse_string(
            "species where NOT species.genus.family." "family=name"
        )
        self.assertEqual(
            str(results.query),
            "SELECT * FROM species WHERE "
            "NOT (species.genus.family.family = 'name')",
        )
        results = search.parser.parse_string(
            "species where ! species.genus.family.family" "=name"
        )
        self.assertEqual(
            str(results.query),
            "SELECT * FROM species WHERE "
            "NOT (species.genus.family.family = 'name')",
        )
        results = search.parser.parse_string(
            "species where family=1 OR family=2 AND NOT genus.id=3"
        )
        self.assertEqual(
            str(results.query),
            "SELECT * FROM species WHERE "
            "((family = 1.0) OR ((family = 2.0) AND NOT (genus.id"
            " = 3.0)))",
        )

    def test_canuse_lowercase_operators(self):
        "can use the operators in lower case"

        results = search.parser.parse_string(
            "species where not species.genus.family." "family=name"
        )
        self.assertEqual(
            str(results.query),
            "SELECT * FROM species WHERE "
            "NOT (species.genus.family.family = 'name')",
        )
        results = search.parser.parse_string(
            "species where ! species.genus.family.family" "=name"
        )
        self.assertEqual(
            str(results.query),
            "SELECT * FROM species WHERE "
            "NOT (species.genus.family.family = 'name')",
        )
        results = search.parser.parse_string(
            "species where family=1 or family=2 and not genus.id=3"
        )
        self.assertEqual(
            str(results.query),
            "SELECT * FROM species WHERE "
            "((family = 1.0) OR ((family = 2.0) AND NOT (genus.id"
            " = 3.0)))",
        )

    def test_notes_is_not_not_es(self):
        "acknowledges word boundaries"

        results = search.parser.parse_string("species where notes.id!=0")
        self.assertEqual(
            str(results.query),
            "SELECT * FROM species WHERE (notes.id != 0.0)",
        )

    def test_between_just_parse_0(self):
        "use BETWEEN value and value"
        results = search.parser.parse_string(
            "species where id between 0 and 1"
        )
        self.assertEqual(
            str(results.query),
            "SELECT * FROM species WHERE (BETWEEN id 0.0 1.0)",
        )

    def test_between_just_parse_1(self):
        "use BETWEEN value and value"
        results = search.parser.parse_string(
            "species where step.id between 0 and 1"
        )
        self.assertEqual(
            str(results.query),
            "SELECT * FROM species WHERE (BETWEEN step.id 0.0 1.0)",
        )

    def test_between_just_parse_2(self):
        "use BETWEEN value and value"
        results = search.parser.parse_string(
            "species where step.step.step.step[a=1].id between 0 and 1"
        )
        self.assertEqual(
            str(results.query),
            "SELECT * FROM species WHERE (BETWEEN "
            "step.step.step.step[a=1.0].id 0.0 1.0)",
        )


class FilterThenMatchTests(BaubleClassTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        db.engine.execute("delete from genus")
        db.engine.execute("delete from family")
        db.engine.execute("delete from genus_note")

        cls.family = Family(family="family1", qualifier="s. lat.")
        cls.genus1 = Genus(family=cls.family, genus="genus1")
        cls.genus2 = Genus(family=cls.family, genus="genus2")
        cls.genus3 = Genus(family=cls.family, genus="genus3")
        cls.genus4 = Genus(family=cls.family, genus="genus4", author="me")
        n1 = GenusNote(category="commentarii", note="olim", genus=cls.genus1)
        n2 = GenusNote(category="commentarii", note="erat", genus=cls.genus1)
        n3 = GenusNote(category="commentarii", note="verbum", genus=cls.genus2)
        n4 = GenusNote(category="test", note="olim", genus=cls.genus3)
        n5 = GenusNote(category="test", note="verbum", genus=cls.genus3)
        cls.session.add_all(
            [
                cls.family,
                cls.genus1,
                cls.genus2,
                cls.genus3,
                cls.genus4,
                n1,
                n2,
                n3,
                n4,
                n5,
            ]
        )
        cls.session.commit()

    def test_can_filter_match_notes(self):
        mapper_search = search.strategies.get_strategy("MapperSearch")
        self.assertTrue(
            isinstance(mapper_search, search.strategies.MapperSearch)
        )

        s = "genus where notes.note='olim'"
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertCountEqual(results, [self.genus1, self.genus3])

        s = "genus where notes[category='test'].note='olim'"
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertCountEqual(results, [self.genus3])

        s = "genus where notes.category='commentarii'"
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertCountEqual(results, [self.genus1, self.genus2])

        s = "genus where notes[note='verbum'].category='commentarii'"
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertEqual(results, [self.genus2])

    def test_can_find_empty_set(self):
        mapper_search = search.strategies.get_strategy("MapperSearch")
        self.assertTrue(
            isinstance(mapper_search, search.strategies.MapperSearch)
        )

        s = "genus where notes=Empty"
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)

        self.assertEqual(results, [self.genus4])

        # IS
        s = "genus where notes is Empty"
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)

        self.assertEqual(results, [self.genus4])

    def test_can_find_non_empty_set(self):
        mapper_search = search.strategies.get_strategy("MapperSearch")
        self.assertTrue(
            isinstance(mapper_search, search.strategies.MapperSearch)
        )

        s = "genus where notes!=Empty"
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)

        self.assertCountEqual(results, [self.genus1, self.genus2, self.genus3])

        # NOT
        s = "genus where notes not Empty"
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)

        self.assertCountEqual(results, [self.genus1, self.genus2, self.genus3])

    def test_can_match_list_of_values(self):
        mapper_search = search.strategies.get_strategy("MapperSearch")
        self.assertTrue(
            isinstance(mapper_search, search.strategies.MapperSearch)
        )

        s = "genus where notes.note in 'olim', 'erat', 'verbum'"
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertEqual(results, [self.genus1, self.genus2, self.genus3])

        s = (
            "genus where notes[category='test'].note in 'olim', 'erat', "
            "'verbum'"
        )
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertEqual(results, [self.genus3])

    def test_parenthesised_search(self):
        mapper_search = search.strategies.get_strategy("MapperSearch")
        self.assertTrue(
            isinstance(mapper_search, search.strategies.MapperSearch)
        )

        s = "genus where (notes!=Empty) and (notes=Empty)"
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertEqual(results, [])

    def test_multiple_filters(self):
        mapper_search = search.strategies.get_strategy("MapperSearch")
        self.assertTrue(
            isinstance(mapper_search, search.strategies.MapperSearch)
        )

        s = "genus where notes[category='test', note='olim'].id > 0"
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertCountEqual(results, [self.genus3])

    def test_multiple_filters_multiple_depths(self):
        mapper_search = search.strategies.get_strategy("MapperSearch")
        self.assertTrue(
            isinstance(mapper_search, search.strategies.MapperSearch)
        )

        s = "family where genera[epithet=genus4,author=me].notes.note = olim"
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertCountEqual(results, [])

        s = "family where genera[epithet=genus3,author=''].notes.note = olim"
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertCountEqual(results, [self.family])

        s = (
            "family where genera[epithet=genus3,author='']"
            ".notes[category=test].note = olim"
        )
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertCountEqual(results, [self.family])


class EmptySetEqualityTest(unittest.TestCase):
    def test_EmptyToken_equals(self):
        et1 = search.tokens.EmptyToken()
        et2 = search.tokens.EmptyToken()
        self.assertEqual(et1, et2)
        self.assertTrue(et1 == et2)
        self.assertTrue(et1 == set())

    def test_empty_token_otherwise(self):
        et1 = search.tokens.EmptyToken()
        self.assertFalse(et1 is None)
        self.assertFalse(et1 == 0)
        self.assertFalse(et1 == "")
        self.assertFalse(et1 == set([1, 2, 3]))

    def test_EmptyToken_representation(self):
        et1 = search.tokens.EmptyToken()
        self.assertEqual("%s" % et1, "Empty")
        self.assertEqual(et1.express(None), set())

    def test_NoneToken_representation(self):
        nt1 = search.tokens.NoneToken()
        self.assertEqual("%s" % nt1, "(None<NoneType>)")
        self.assertEqual(nt1.express(None), None)


class FunctionsTests(BaubleClassTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        db.engine.execute("delete from genus")
        db.engine.execute("delete from family")
        db.engine.execute("delete from species")
        db.engine.execute("delete from accession")

        f1 = Family(family="Rutaceae", qualifier="")
        g1 = Genus(family=f1, genus="Citrus")
        sp1 = Species(sp="medica", genus=g1)
        sp2 = Species(sp="maxima", genus=g1)
        sp3 = Species(sp="aurantium", genus=g1)

        geo1 = Geography(name="Test1", code="T1", level=1)
        geo2 = Geography(name="Test2", code="T2", level=1)
        sp1.distribution = [
            SpeciesDistribution(geography=geo1),
            SpeciesDistribution(geography=geo2),
        ]

        f2 = Family(family="Sapotaceae")
        g2 = Genus(family=f2, genus="Manilkara")
        sp4 = Species(sp="zapota", genus=g2)
        sp5 = Species(sp="zapotilla", genus=g2)
        sp5.synonyms.append(sp4)
        g3 = Genus(family=f2, genus="Pouteria")
        sp6 = Species(sp="stipitata", _cites="II", genus=g3)

        f3 = Family(family="Musaceae")
        g4 = Genus(family=f3, genus="Musa")
        cls.session.add_all(
            [f1, f2, f3, g1, g2, g3, g4, sp1, sp2, sp3, sp4, sp5, sp6]
        )
        cls.session.commit()

    def test_count(self):
        mapper_search = search.strategies.get_strategy("MapperSearch")
        self.assertTrue(
            isinstance(mapper_search, search.strategies.MapperSearch)
        )

        s = "genus where count(species.id) > 3"
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertEqual(len(results), 0)

        s = "genus where count(species.id) > 2"
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertEqual(len(results), 1)
        result = results.pop()
        self.assertEqual(result.id, 1)

        s = "genus where count(species.id) == 2"
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertEqual(len(results), 1)
        result = results.pop()
        self.assertEqual(result.id, 2)

    def test_count_just_parse(self):
        s = "genus where count(species.id) == 2"
        results = search.parser.parse_string(s)
        self.assertEqual(
            str(results.query),
            "SELECT * FROM genus WHERE (count(species.id) == 2.0)",
        )
        s = "genus where count(distinct species.id) == 2"
        results = search.parser.parse_string(s)
        self.assertEqual(
            str(results.query),
            "SELECT * FROM genus WHERE (count(DISTINCT species.id) == 2.0)",
        )

    def test_count_complex_query(self):
        mapper_search = search.strategies.get_strategy("MapperSearch")
        self.assertTrue(
            isinstance(mapper_search, search.strategies.MapperSearch)
        )

        s = "genus where species.epithet like za% and count(species.id) > 1"
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].id, 2)
        sp1 = self.session.query(Species).first()

        s = (
            "species where count(distribution.id) > 1 and "
            "distribution.geography.name = 'Test1'"
        )
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].id, sp1.id)

        s = (
            "species where distribution.geography.name = 'Test2' "
            "and count(distribution.geography.id) > 1"
        )
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].id, sp1.id)

        s = (
            "species where distribution.geography.name = 'Test2' "
            "and count(distribution.geography.id) > 1 or id = 2"
        )
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertEqual(len(results), 2)

    def test_min(self):
        mapper_search = search.strategies.get_strategy("MapperSearch")
        s = "genus where min(species.id) = 1"
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].id, 1)

    def test_max(self):
        mapper_search = search.strategies.get_strategy("MapperSearch")
        s = "genus where max(species.id) = 3"
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].id, 1)

    def test_sum(self):
        mapper_search = search.strategies.get_strategy("MapperSearch")
        s = "genus where sum(species.id) = 9"
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].id, 2)

    def test_sum_w_filter(self):
        mapper_search = search.strategies.get_strategy("MapperSearch")
        s = "genus where sum(species[epithet=stipitata].id) = 6"
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].id, 3)

    def test_multiple_aggregate_funcs(self):
        mapper_search = search.strategies.get_strategy("MapperSearch")
        s = "genus where sum(species.id) = 9 and count(species.id) = 2"
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].id, 2)

    def test_aggregate_funcs_self_reference(self):
        mapper_search = search.strategies.get_strategy("MapperSearch")
        s = "species where count(synonyms.id) = 1"
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].id, 5)
        mapper_search = search.strategies.get_strategy("MapperSearch")
        s = "species where count(_synonyms.species.id) = 1"
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].id, 5)
        s = "species where sum(_synonyms.species.id) > 0"
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].id, 5)
        s = "species where max(_synonyms.species.id) > 0"
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].id, 5)
        s = "geography where count(children.id) >17"
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertEqual(len(results), 0)

    def test_non_aggregate_function(self):
        mapper_search = search.strategies.get_strategy("MapperSearch")
        s = "species where length(epithet) = 9"
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertEqual(len(results), 3)
        expected = ["aurantium", "zapotilla", "stipitata"]
        for result in results:
            self.assertIn(result.sp, expected)
        # with filter
        s = "genus where length(species[_cites='II'].epithet) = 9"
        results = []
        for i in mapper_search.search(s, self.session):
            results.extend(i)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].epithet, "Pouteria")


class BaubleSearchSearchTest(BaubleTestCase):
    def test_search_search_uses_domain_search(self):
        with self.assertLogs(level="DEBUG") as logs:
            search.search("genus like %", self.session)
        string = 'SearchStrategy "genus like %" (DomainSearch)'
        self.assertTrue(any(string in i for i in logs.output))

    def test_search_search_uses_value_list_search(self):
        with self.assertLogs(level="DEBUG") as logs:
            search.search("12.11.13", self.session)
        string = 'SearchStrategy "12.11.13" (ValueListSearch)'
        self.assertTrue(any(string in i for i in logs.output))

    def test_search_search_uses_mapper_search(self):
        with self.assertLogs(level="DEBUG") as logs:
            search.search("genus where id = 1", self.session)
        string = 'SearchStrategy "genus where id = 1" (MapperSearch)'
        self.assertTrue(any(string in i for i in logs.output))

    def test_search_exclude_inactive_set(self):

        fam1 = Family(epithet="Moraceae")
        gen1 = Genus(family=fam1, genus="Ficus")
        gen2 = Genus(family=fam1, genus="Artocarpus")
        # inactive
        sp1 = Species(genus=gen1, epithet="virens")
        sp2 = Species(genus=gen2, epithet="heterophyllus")
        sp3 = Species(sp="sp", genus=gen1)
        acc1 = Accession(species=sp2, code="1979.0001", quantity_recvd=10)
        # inactive
        acc2 = Accession(species=sp1, code="1979.0002", quantity_recvd=5)
        loc1 = Location(name="loc1", code="loc1")
        loc2 = Location(name="loc2", code="loc2")
        plt1 = Plant(accession=acc1, code="01", location=loc1, quantity=1)
        # inactive
        plt2 = Plant(accession=acc2, code="02", location=loc2, quantity=0)
        self.session.add_all(
            [
                gen1,
                gen2,
                fam1,
                sp1,
                sp2,
                sp3,
                acc1,
                acc2,
                loc1,
                loc2,
                plt1,
                plt2,
            ]
        )
        self.session.commit()

        # Don't exclude inactive
        prefs.prefs[prefs.exclude_inactive_pref] = False
        result = search.search("plant=*", self.session)
        self.assertCountEqual(result, [plt1, plt2])
        result = search.search("accession where id != 0", self.session)
        self.assertCountEqual(result, [acc1, acc2])
        result = search.search("Fic vir", self.session)
        self.assertCountEqual(result, [sp1])
        result = search.search("virens", self.session)
        self.assertEqual(result, [sp1])
        result = search.search("Fic sp", self.session)
        self.assertEqual(result, [sp3])
        string = (
            "species where active is False and not "
            "(accessions[_created > -1].quantity_recvd in 10, 11 or "
            "accessions.plants.location.code = 'loc1') and id "
            "BETWEEN 1 and 20"
        )
        result = search.search(string, self.session)
        self.assertEqual(result, [sp1])

        # exclude inactive
        prefs.prefs[prefs.exclude_inactive_pref] = True
        result = search.search("plant=*", self.session)
        self.assertCountEqual(result, [plt1])
        result = search.search("accession where id != 0", self.session)
        self.assertCountEqual(result, [acc1])
        result = search.search("Fic vir", self.session)
        self.assertEqual(result, [])
        result = search.search("virens", self.session)
        self.assertEqual(result, [])
        result = search.search("Fic sp", self.session)
        self.assertEqual(result, [sp3])
        string = (
            "species where active is False and not "
            "(accessions[_created > -1].quantity_recvd in 10, 11 or "
            "accessions.plants.location.code = 'loc1') and id "
            "BETWEEN 1 and 20"
        )
        result = search.search(string, self.session)
        self.assertEqual(result, [])


class HelperTests(unittest.TestCase):
    def test_infix_notation(self):

        token = pp.Word(pp.alphas).set_name("string token")
        binop = pp.one_of("= < > !=").set_name("binary operator")
        value = pp.Word(pp.nums).set_name("value")
        or_ = pp.Literal("or").set_name("or")
        and_ = pp.Literal("and").set_name("and")
        not_ = pp.Literal("not").set_name("not")
        binary_expr = pp.Group(token + binop + value).set_name("binary clause")

        infix = search.helpers.infix_notation(
            binary_expr,
            [
                (not_, pp.OpAssoc.RIGHT, lambda t: t),
                (and_, pp.OpAssoc.LEFT, lambda t: t),
                (or_, pp.OpAssoc.LEFT, lambda t: t),
            ],
        )
        result = infix.parse_string("xyz = 2 or abc = 2 and xyz = 3")
        self.assertEqual(
            result.as_list(),
            [
                [
                    ["xyz", "=", "2"],
                    "or",
                    [["abc", "=", "2"], "and", ["xyz", "=", "3"]],
                ]
            ],
            result,
        )
        result = infix.parse_string("xyz = 2 and abc = 2 or xyz = 3")
        self.assertEqual(
            result.as_list(),
            [
                [
                    [["xyz", "=", "2"], "and", ["abc", "=", "2"]],
                    "or",
                    ["xyz", "=", "3"],
                ]
            ],
            result,
        )
        result = infix.parse_string("xyz > 2 or abc != 2 and xyz < 3")
        self.assertEqual(
            result.as_list(),
            [
                [
                    ["xyz", ">", "2"],
                    "or",
                    [["abc", "!=", "2"], "and", ["xyz", "<", "3"]],
                ]
            ],
            result,
        )
        result = infix.parse_string("xyz = 2 and abc = 2 or not xyz = 3")
        self.assertEqual(
            result.as_list(),
            [
                [
                    [["xyz", "=", "2"], "and", ["abc", "=", "2"]],
                    "or",
                    ["not", ["xyz", "=", "3"]],
                ]
            ],
            result,
        )
        result = infix.parse_string("not xyz = 2 and abc = 2 or xyz = 3")
        self.assertEqual(
            result.as_list(),
            [
                [
                    [["not", ["xyz", "=", "2"]], "and", ["abc", "=", "2"]],
                    "or",
                    ["xyz", "=", "3"],
                ]
            ],
            result,
        )
        # test errors: invalid OpAssoc
        self.assertRaises(
            ValueError,
            search.helpers.infix_notation,
            binary_expr,
            [
                (not_, None, lambda t: t),
                (and_, pp.OpAssoc.LEFT, lambda t: t),
                (or_, pp.OpAssoc.LEFT, lambda t: t),
            ],
        )
