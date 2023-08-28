# Copyright 2008-2010 Brett Adams
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
#
# test_search.py
#
import unittest

import logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

from pyparsing import ParseException

from bauble import db
from bauble import search
from bauble import prefs
from bauble.test import BaubleTestCase
prefs.testing = True


parser = search.SearchParser()


class SearchParserTests(unittest.TestCase):
    error_msg = lambda me, s, v, e:  '%s: %s == %s' % (s, v, e)

    def test_query_expression_token_UPPER(self):
        s = 'domain where col=value'
        logger.debug(s)
        parser.query.parseString(s)

        s = 'domain where relation.col=value'
        parser.query.parseString(s)

        s = 'domain where relation.relation.col=value'
        parser.query.parseString(s)

        s = 'domain where relation.relation.col=value AND col2=value2'
        parser.query.parseString(s)

    def test_query_expression_token_LOWER(self):
        s = 'domain where relation.relation.col=value and col2=value2'
        parser.query.parseString(s)

    def test_statement_token(self):
        pass

    def test_domain_expression_token(self):
        """
        Test the domain_expression token
        """
        # allow dom=val1, val2, val3
        s = 'domain=test'
        expected = "[domain = ['test']]"
        results = parser.domain_expression.parseString(s, parseAll=True)
        self.assertEqual(results.getName(), 'domain_expression')
        self.assertEqual(str(results), expected)

        s = 'domain==test'
        expected = "[domain == ['test']]"
        results = parser.domain_expression.parseString(s, parseAll=True)
        self.assertEqual(str(results), expected)

        s = 'domain=*'
        expected = "[domain = *]"
        results = parser.domain_expression.parseString(s, parseAll=True)
        self.assertEqual(str(results), expected)

        s = 'domain=test1 test2 test3'
        expected = "[domain = ['test1', 'test2', 'test3']]"
        results = parser.statement.parseString(s, parseAll=True)
        self.assertEqual(str(results), expected)

        s = 'domain=test1 "test2 test3" test4'
        expected = "[domain = ['test1', 'test2 test3', 'test4']]"
        results = parser.domain_expression.parseString(s, parseAll=True)
        self.assertEqual(str(results), expected)

        s = 'domain="test test"'
        expected = "[domain = ['test test']]"
        results = parser.domain_expression.parseString(s, parseAll=True)
        self.assertEqual(str(results), expected)

    def test_integer_token(self):
        "recognizes integers or floats as floats"

        results = parser.value.parseString('123')
        self.assertEqual(results.getName(), 'value')
        self.assertEqual(results.value.express(), 123.0)
        results = parser.value.parseString('123.1')
        self.assertEqual(results.value.express(), 123.1)

    def test_value_token(self):
        "value should only return the first string or raise a parse exception"

        strings = ['test', '"test"', "'test'"]
        expected = 'test'
        for s in strings:
            results = parser.value.parseString(s, parseAll=True)
            self.assertEqual(results.getName(), 'value')
            self.assertEqual(results.value.express(), expected)

        strings = ['123.000', '123.', "123.0"]
        expected = 123.0
        for s in strings:
            results = parser.value.parseString(s)
            self.assertEqual(results.getName(), 'value')
            self.assertEqual(results.value.express(), expected)

        strings = ['"test1 test2"', "'test1 test2'"]
        expected = 'test1 test2'  # this is one string! :)
        for s in strings:
            results = parser.value.parseString(s, parseAll=True)
            self.assertEqual(results.getName(), 'value')
            self.assertEqual(results.value.express(), expected)

        strings = ['%.-_*', '"%.-_*"']
        expected = '%.-_*'
        for s in strings:
            results = parser.value.parseString(s, parseAll=True)
            self.assertEqual(results.getName(), 'value')
            self.assertEqual(results.value.express(), expected)

        # these should be invalid
        strings = ['test test', '"test', "test'", '$', ]
        for s in strings:
            self.assertRaises(ParseException, parser.value.parseString, s, parseAll=True)

    def test_needs_join(self):
        """check the join steps"""
        # am not sure this is testing much?

        env = None
        results = parser.statement.parseString("plant where accession.species."
                                               "id=44")
        self.assertEqual(
            results.statement.content.filter.operands[0].needs_join(env),
            ['accession', 'species']
        )
        results = parser.statement.parseString("plant where accession.id=44")
        self.assertEqual(
            results.statement.content.filter.operands[0].needs_join(env),
            ['accession']
        )
        results = parser.statement.parseString("plant where accession.id=4 OR "
                                               "accession.species.id=3")
        self.assertEqual(
            results.statement.content.filter.operands[0]
            .operands[0].needs_join(env),
            ['accession']
        )
        self.assertEqual(
            results.statement.content.filter.operands[1]
            .operands[0].needs_join(env),
            ['accession', 'species']
        )

    def test_value_list_token(self):
        """value_list: should return all values
        """

        strings = ['test1, test2',
                   '"test1", test2',
                   "test1, 'test2'"]
        expected = [['test1', 'test2']]
        for s in strings:
            results = parser.value_list.parseString(s, parseAll=True)
            self.assertEqual(results.getName(), 'value_list')
            self.assertEqual(str(results), str(expected))

        strings = ['test', '"test"', "'test'"]
        expected = [['test']]
        for s in strings:
            results = parser.value_list.parseString(s, parseAll=True)
            self.assertEqual(results.getName(), 'value_list')
            self.assertEqual(str(results), str(expected))

        strings = ['test1 test2 test3', '"test1" test2 \'test3\'']
        expected = [['test1', 'test2', 'test3']]
        for s in strings:
            results = parser.value_list.parseString(s, parseAll=True)
            self.assertEqual(str(results), str(expected))

        strings = ['"test1 test2", test3']
        expected = [['test1 test2', 'test3']]
        for s in strings:
            results = parser.value_list.parseString(s, parseAll=True)
            self.assertEqual(str(results), str(expected))

        # these should be invalid
        strings = ['"test', "test'", "'test tes2", "1,2,3 4 5"]
        for s in strings:
            self.assertRaises(ParseException, parser.value_list.parseString, s, parseAll=True)


class SearchTests(BaubleTestCase):
    def __init__(self, *args):
        super().__init__(*args)
        prefs.testing = True

    def setUp(self):
        super().setUp()
        db.engine.execute('delete from genus')
        db.engine.execute('delete from family')
        from bauble.plugins.plants.family import Family
        from bauble.plugins.plants.genus import Genus
        self.family = Family(family='family1', qualifier='s. lat.')
        self.genus = Genus(family=self.family, genus='genus1')
        self.Family = Family
        self.Genus = Genus
        self.session.add_all([self.family, self.genus])
        self.session.commit()

    def tearDown(self):
        super().tearDown()

    def test_find_correct_strategy_internal(self):
        "verify the MapperSearch strategy is available (low-level)"

        mapper_search = search._search_strategies['MapperSearch']
        self.assertTrue(isinstance(mapper_search, search.MapperSearch))

    def test_find_correct_strategy(self):
        "verify the MapperSearch strategy is available"

        mapper_search = search.get_strategy('MapperSearch')
        self.assertTrue(isinstance(mapper_search, search.MapperSearch))

    def test_look_for_wrong_strategy(self):
        "verify the NotExisting strategy gives None"

        mapper_search = search.get_strategy('NotExisting')

        self.assertIsNone(mapper_search)

    def test_search_by_values(self):
        "search by values"
        mapper_search = search.get_strategy('MapperSearch')
        self.assertTrue(isinstance(mapper_search, search.MapperSearch))

        # search for family by family name
        results = mapper_search.search('family1', self.session)
        self.assertEqual(len(results), 1)
        f = list(results)[0]
        self.assertEqual(f.id, self.family.id)

        # search for genus by genus name
        results = mapper_search.search('genus1', self.session)
        self.assertEqual(len(results), 1)
        g = list(results)[0]
        self.assertEqual(g.id, self.genus.id)

    def test_search_by_expression_family_eq(self):
        mapper_search = search.get_strategy('MapperSearch')
        self.assertTrue(isinstance(mapper_search, search.MapperSearch))

        # search for family by domain
        results = list(mapper_search.search('fam=family1', self.session))
        self.assertEqual(len(results), 1)
        f = list(results)[0]
        self.assertTrue(isinstance(f, self.Family))
        self.assertEqual(f.id, self.family.id)

    def test_search_by_expression_genus_eq_1match(self):
        mapper_search = search.get_strategy('MapperSearch')
        self.assertTrue(isinstance(mapper_search, search.MapperSearch))

        # search for genus by domain
        results = list(mapper_search.search('gen=genus1', self.session))
        self.assertEqual(len(results), 1)
        g = list(results)[0]
        self.assertTrue(isinstance(g, self.Genus))
        self.assertEqual(g.id, self.genus.id)

    def test_search_by_expression_genus_eq_nomatch(self):
        mapper_search = search.get_strategy('MapperSearch')
        self.assertTrue(isinstance(mapper_search, search.MapperSearch))

        # search for genus by domain
        results = list(mapper_search.search('genus=g', self.session))
        self.assertEqual(len(results), 0)

    def test_search_by_expression_genus_eq_everything(self):
        mapper_search = search.get_strategy('MapperSearch')
        self.assertTrue(isinstance(mapper_search, search.MapperSearch))

        # search for genus by domain
        results = list(mapper_search.search('genus=*', self.session))
        self.assertEqual(len(results), 1)

    def test_search_by_expression_genus_like_nomatch(self):
        mapper_search = search.get_strategy('MapperSearch')
        self.assertTrue(isinstance(mapper_search, search.MapperSearch))

        # search for genus by domain
        results = list(mapper_search.search('genus like gen', self.session))
        self.assertEqual(len(results), 0)
        # search for genus by domain
        results = list(mapper_search.search('genus like nus%', self.session))
        self.assertEqual(len(results), 0)
        # search for genus by domain
        results = list(mapper_search.search('genus like %gen', self.session))
        self.assertEqual(len(results), 0)

    def test_search_by_expression_genus_like_contains_eq(self):
        mapper_search = search.get_strategy('MapperSearch')
        self.assertTrue(isinstance(mapper_search, search.MapperSearch))
        Family = self.Family
        f2 = Family(family='family2')
        f3 = Family(family='afamily3')
        f4 = Family(family='fam4')
        self.session.add_all([f3, f2, f4])
        self.session.commit()

        # search for family by domain
        results = list(mapper_search.search('family contains fam', self.session))
        self.assertEqual(len(results), 4)  # all do
        results = list(mapper_search.search('family like f%', self.session))
        self.assertEqual(len(results), 3)  # three start by f
        results = list(mapper_search.search('family like af%', self.session))
        self.assertEqual(len(results), 1)  # one starts by af
        results = list(mapper_search.search('family like fam', self.session))
        self.assertEqual(len(results), 0)
        results = list(mapper_search.search('family = fam', self.session))
        self.assertEqual(len(results), 0)
        results = list(mapper_search.search('family = fam4', self.session))
        self.assertEqual(len(results), 1)  # exact name match
        # MSSQL may not be case sensitive depending on collation settings
        # results = list(mapper_search.search('family = Fam4', self.session))
        # self.assertEqual(len(results), 0)  # = is case sensitive
        results = list(mapper_search.search('family like Fam4', self.session))
        self.assertEqual(len(results), 1)  # like is case insensitive
        results = list(mapper_search.search('family contains FAM',
                                            self.session))
        self.assertEqual(len(results), 4)  # they case insensitively do

    def test_search_by_query_singular(self):
        """query with MapperSearch, single table, single test"""

        # test does not depend on plugin functionality
        Family = self.Family
        Genus = self.Genus
        family2 = Family(family='family2')
        genus2 = Genus(family=family2, genus='genus2')
        self.session.add_all([family2, genus2])
        self.session.commit()

        mapper_search = search.get_strategy('MapperSearch')
        self.assertTrue(isinstance(mapper_search, search.MapperSearch))

        # search cls.column
        results = list(mapper_search.search('genus where genus=genus1',
                                            self.session))
        self.assertEqual(len(results), 1)
        f = list(results)[0]
        self.assertTrue(isinstance(f, Genus))
        self.assertEqual(f.id, self.family.id)

    def test_search_by_or_query_w_homonym(self):
        """query with MapperSearch, single table, p1 OR p2"""

        # test does not depend on plugin functionality
        Family = self.Family
        Genus = self.Genus
        f2 = Family(family='family2')
        g2 = Genus(family=f2, genus='genus2')
        f3 = Family(family='fam3')
        # g3(homonym) is here just to have two matches on one value
        g3 = Genus(family=f3, genus='genus2')
        g4 = Genus(family=f3, genus='genus4')
        self.session.add_all([f2, g2, f3, g3, g4])
        self.session.commit()

        mapper_search = search.get_strategy('MapperSearch')
        self.assertTrue(isinstance(mapper_search, search.MapperSearch))

        # search with or conditions
        s = 'genus where genus=genus2 OR genus=genus1'
        results = mapper_search.search(s, self.session)
        self.assertEqual(sorted([r.id for r in results]),
                          [g.id for g in (self.genus, g2, g3)])

    def test_search_by_gt_and_lt_query(self):
        """query with MapperSearch, single table, > AND <"""

        # test does not depend on plugin functionality
        Family = self.Family
        Genus = self.Genus
        family2 = Family(family='family2')
        genus2 = Genus(family=family2, genus='genus2')
        f3 = Family(family='fam3')
        g3 = Genus(family=f3, genus='genus2')
        g4 = Genus(family=f3, genus='genus4')
        self.session.add_all([family2, genus2, f3, g3, g4])
        self.session.commit()

        mapper_search = search.get_strategy('MapperSearch')
        self.assertTrue(isinstance(mapper_search, search.MapperSearch))

        s = 'genus where id>1 AND id<3'
        results = list(mapper_search.search(s, self.session))
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].id, 2)

        s = 'genus where id>0 AND id<3'
        results = list(mapper_search.search(s, self.session))
        self.assertEqual(len(results), 2)
        self.assertEqual(set(i.id for i in results), set([1, 2]))

    def test_search_by_query_joined_tables(self):
        """query with MapperSearch, joined tables, one predicate"""

        # test does not depend on plugin functionality
        Family = self.Family
        Genus = self.Genus
        family2 = Family(family='family2')
        genus2 = Genus(family=family2, genus='genus2')
        self.session.add_all([family2, genus2])
        self.session.commit()

        mapper_search = search.get_strategy('MapperSearch')
        self.assertTrue(isinstance(mapper_search, search.MapperSearch))

        # search cls.parent.column
        s = 'genus where family.family=family1'
        results = list(mapper_search.search(s, self.session))
        self.assertEqual(len(results), 1)
        g0 = list(results)[0]
        self.assertTrue(isinstance(g0, Genus))
        self.assertEqual(g0.id, self.genus.id)

        # search cls.children.column
        results = list(mapper_search.search('family where genera.genus=genus1',
                                            self.session))
        self.assertEqual(len(results), 1)
        f = list(results)[0]
        self.assertEqual(len(results), 1)
        self.assertTrue(isinstance(f, Family))
        self.assertEqual(f.id, self.family.id)

    def test_search_by_and_query_joined_tables(self):
        """query with MapperSearch, joined tables, multiple predicates"""

        # test does not depend on plugin functionality
        Family = self.Family
        Genus = self.Genus
        family2 = Family(family='family2')
        g2 = Genus(family=family2, genus='genus2')
        f3 = Family(family='fam3', qualifier='s. lat.')
        g3 = Genus(family=f3, genus='genus3')
        self.session.add_all([family2, g2, f3, g3])
        self.session.commit()

        mapper_search = search.get_strategy('MapperSearch')
        self.assertTrue(isinstance(mapper_search, search.MapperSearch))

        s = 'genus where genus=genus2 AND family.family=fam3'
        results = list(mapper_search.search(s, self.session))
        self.assertEqual(len(results), 0)

        s = 'genus where genus=genus3 AND family.family=fam3'
        results = list(mapper_search.search(s, self.session))
        self.assertEqual(len(results), 1)
        g0 = list(results)[0]
        self.assertTrue(isinstance(g0, Genus))
        self.assertEqual(g0.id, g3.id)

        s = 'genus where family.family="Orchidaceae" AND family.qualifier=""'
        results = mapper_search.search(s, self.session)
        r = list(results)
        self.assertEqual(r, [])

        s = 'genus where family.family=fam3 AND family.qualifier=""'
        results = list(mapper_search.search(s, self.session))
        self.assertEqual(results, [])

        # sqlite3 stores None as the empty string.
        s = 'genus where family.qualifier=""'
        results = list(mapper_search.search(s, self.session))
        self.assertEqual(results, [g2])

        # test where the column is ambiguous so make sure we choose
        # the right one, in this case we want to make sure we get the
        # qualifier on the family and not the genus
        s = ('plant where accession.species.genus.family.family="Orchidaceae" '
             'AND accession.species.genus.family.qualifier=""')
        results = list(mapper_search.search(s, self.session))
        self.assertEqual(results, [])

    def test_search_by_symbol_query(self):
        """query with &&, ||, !"""

        # test does not depend on plugin functionality
        Family = self.Family
        Genus = self.Genus
        family2 = Family(family='family2')
        g2 = Genus(family=family2, genus='genus2')
        f3 = Family(family='fam3', qualifier='s. lat.')
        g3 = Genus(family=f3, genus='genus3')
        self.session.add_all([family2, g2, f3, g3])
        self.session.commit()

        mapper_search = search.get_strategy('MapperSearch')
        self.assertTrue(isinstance(mapper_search, search.MapperSearch))

        s = 'genus where genus=genus2 && family.family=fam3'
        results = list(mapper_search.search(s, self.session))
        self.assertEqual(len(results), 0)

        s = 'family where family=family1 || family=fam3'
        results = list(mapper_search.search(s, self.session))
        self.assertEqual(len(results), 2)

        s = 'family where ! family=family1'
        results = list(mapper_search.search(s, self.session))
        self.assertEqual(len(results), 2)

    def test_search_by_query_none(self):
        """query with MapperSearch, joined tables, predicates using None

        results are irrelevant, because sqlite3 uses the empty string to
        represent None
        """

        # test does not depend on plugin functionality
        Family = self.Family
        Genus = self.Genus
        family2 = Family(family='family2')
        g2 = Genus(family=family2, genus='genus2')
        f3 = Family(family='fam3', qualifier='s. lat.')
        g3 = Genus(family=f3, genus='genus3')
        self.session.add_all([family2, g2, f3, g3])
        self.session.commit()

        mapper_search = search.get_strategy('MapperSearch')
        self.assertTrue(isinstance(mapper_search, search.MapperSearch))

        s = 'genus where family.qualifier is None'
        results = list(mapper_search.search(s, self.session))
        self.assertEqual(results, [])

        # make sure None isn't treated as the string 'None' and that
        # the query picks up the is operator
        s = 'genus where author is None'
        results = list(mapper_search.search(s, self.session))
        self.assertEqual(results, [])

        # NOTE Genus.author has default of ''
        s = 'genus where author not None'
        results = list(mapper_search.search(s, self.session))
        self.assertCountEqual(results, [self.genus, g2, g3])

        s = 'genus where author != None'
        results = list(mapper_search.search(s, self.session))
        self.assertCountEqual(results, [self.genus, g2, g3])

        s = 'genus where NOT author = ""'
        results = list(mapper_search.search(s, self.session))
        self.assertCountEqual(results, [])

    def test_search_by_query_id_joined_tables(self):
        """query with MapperSearch, joined tables, test on id of dependent
        table
        """

        # test does not depend on plugin functionality
        Family = self.Family
        Genus = self.Genus
        family2 = Family(family='family2')
        genus2 = Genus(family=family2, genus='genus2')
        f3 = Family(family='fam3')
        g3 = Genus(family=f3, genus='genus3')
        self.session.add_all([family2, genus2, f3, g3])
        self.session.commit()

        mapper_search = search.get_strategy('MapperSearch')
        self.assertTrue(isinstance(mapper_search, search.MapperSearch))

        # id is an ambiguous column because it occurs on plant,
        # accesion and species...the results here don't matter as much
        # as the fact that the query doesn't raise and exception
        s = 'plant where accession.species.id=1'
        results = mapper_search.search(s, self.session)
        self.assertEqual(len(list(results)), 0)

    def test_search_by_like_percent_query_joined_table(self):
        """query with MapperSearch, joined tables, LIKE %"""

        # test does not depend on plugin functionality
        Family = self.Family
        Genus = self.Genus
        family2 = Family(family='family2')
        family3 = Family(family='afamily3')
        genus21 = Genus(family=family2, genus='genus21')
        genus31 = Genus(family=family3, genus='genus31')
        genus32 = Genus(family=family3, genus='genus32')
        genus33 = Genus(family=family3, genus='genus33')
        f3 = Family(family='fam3')
        g3 = Genus(family=f3, genus='genus31')
        self.session.add_all([family3, family2, genus21, genus31, genus32,
                              genus33, f3, g3])
        self.session.commit()

        mapper_search = search.get_strategy('MapperSearch')
        self.assertTrue(isinstance(mapper_search, search.MapperSearch))

        # test partial string matches on a query
        s = 'genus where family.family like family%'
        results = mapper_search.search(s, self.session)
        self.assertEqual(set(results), set([self.genus, genus21]))

    def test_search_by_like_underscore_query_joined_table(self):
        """query with MapperSearch, joined tables, LIKE _"""

        # test does not depend on plugin functionality
        Family = self.Family
        Genus = self.Genus
        family2 = Family(family='family2')
        family3 = Family(family='afamily3')
        genus21 = Genus(family=family2, genus='genus21')
        genus31 = Genus(family=family3, genus='genus31')
        genus32 = Genus(family=family3, genus='genus32')
        genus33 = Genus(family=family3, genus='genus33')
        f3 = Family(family='fam3')
        g3 = Genus(family=f3, genus='genus31')
        self.session.add_all([family3, family2, genus21, genus31, genus32,
                              genus33, f3, g3])
        self.session.commit()

        mapper_search = search.get_strategy('MapperSearch')
        self.assertTrue(isinstance(mapper_search, search.MapperSearch))

        # test _ at end of string query
        s = 'genus where family.family like family_'
        results = mapper_search.search(s, self.session)
        self.assertEqual(set(results), set([self.genus, genus21]))
        # test _ at start of string query
        s = 'genus where family.family like _family3'
        results = mapper_search.search(s, self.session)
        self.assertEqual(set(results), set([genus31, genus32, genus33]))
        # test _ in middle of string query
        s = 'genus where family.family like fa_ily2'
        results = mapper_search.search(s, self.session)
        self.assertEqual(set(results), set([genus21]))

    def test_search_by_datestring_query(self):

        import datetime
        Family = self.Family
        Genus = self.Genus
        from bauble.plugins.plants.species_model import Species
        from bauble.plugins.garden.accession import Accession
        from bauble.plugins.garden.location import Location
        from bauble.plugins.garden.plant import Plant
        family2 = Family(family='family2')
        g2 = Genus(family=family2, genus='genus2')
        f3 = Family(family='fam3', qualifier='s. lat.')
        g3 = Genus(family=f3, genus='Ixora')
        sp = Species(sp="coccinea", genus=g3)
        ac = Accession(species=sp, code='1979.0001')
        ac.date_recvd = datetime.date(2021, 11, 21)
        a2 = Accession(species=sp, code='1979.0002')
        a2.date_recvd = datetime.datetime.today()
        lc = Location(name='loc1', code='loc1')
        pp = Plant(accession=ac, code='01', location=lc, quantity=1)
        p2 = Plant(accession=ac, code='02', location=lc, quantity=1)
        from datetime import timezone
        pp._last_updated = (datetime.datetime(2009, 2, 13)
                            .astimezone(tz=timezone.utc))
        yesterday = ((datetime.datetime.now() - datetime.timedelta(days=1))
                     .astimezone(tz=timezone.utc))
        p2._last_updated = yesterday

        self.session.add_all([family2, g2, f3, g3, sp, ac, lc, pp, p2])
        self.session.commit()

        mapper_search = search.get_strategy('MapperSearch')
        self.assertTrue(isinstance(mapper_search, search.MapperSearch))

        # DateTime type:
        s = 'plant where _last_updated < 1.1.2000'
        results = list(mapper_search.search(s, self.session))
        self.assertEqual(results, [])

        s = 'plant where _created > yesterday'
        results = list(mapper_search.search(s, self.session))
        self.assertCountEqual(results, [pp, p2])

        s = 'plant where _created > -5'
        results = list(mapper_search.search(s, self.session))
        self.assertCountEqual(results, [pp, p2])

        s = 'plant where _last_updated > 1-1-2000'
        results = list(mapper_search.search(s, self.session))
        self.assertCountEqual(results, [pp, p2])

        # isoparse
        s = 'plant where _last_updated < 2000-01-01'
        results = list(mapper_search.search(s, self.session))
        self.assertEqual(results, [])

        s = ('plant where _last_updated >= 13/2/2009 '
             'and _last_updated < 14/2/2009')
        results = list(mapper_search.search(s, self.session))
        self.assertEqual(results, [pp])

        s = ('plant where _last_updated between 13/2/2009 and 14/2/2009')
        results = list(mapper_search.search(s, self.session))
        self.assertEqual(results, [pp])

        logger.debug('CREATED = %s', pp._created)
        s = ('plant where _last_updated between yesterday and today')
        results = list(mapper_search.search(s, self.session))
        self.assertEqual(results, [p2])

        s = 'plant where _last_updated on 13/2/2009'
        results = list(mapper_search.search(s, self.session))
        self.assertEqual(results, [pp])

        # isoparse
        s = 'plant where _last_updated on 2009-02-13'
        results = list(mapper_search.search(s, self.session))
        self.assertEqual(results, [pp])

        s = 'plant where _created on 0'
        results = list(mapper_search.search(s, self.session))
        self.assertCountEqual(results, [pp, p2])

        s = 'plant where _created on today'
        results = list(mapper_search.search(s, self.session))
        self.assertCountEqual(results, [pp, p2])

        s = 'plant where _last_updated on -1'
        results = list(mapper_search.search(s, self.session))
        self.assertEqual(results, [p2])

        s = 'plant where _last_updated on yesterday'
        results = list(mapper_search.search(s, self.session))
        self.assertEqual(results, [p2])

        s = 'plant where _created > -10'
        results = list(mapper_search.search(s, self.session))
        self.assertCountEqual(results, [pp, p2])

        # Date type:
        s = 'accession where date_recvd = today'
        results = list(mapper_search.search(s, self.session))
        self.assertEqual(results, [a2])

        s = 'accession where date_recvd = 0'
        results = list(mapper_search.search(s, self.session))
        self.assertEqual(results, [a2])

        s = 'accession where date_recvd > -10'
        results = list(mapper_search.search(s, self.session))
        self.assertEqual(results, [a2])

        s = 'accession where date_recvd on 21/11/2021'
        results = list(mapper_search.search(s, self.session))
        self.assertEqual(results, [ac])

        s = 'accession where date_recvd = 21/11/2021'
        results = list(mapper_search.search(s, self.session))
        self.assertEqual(results, [ac])

        s = 'accession where date_recvd on 22/11/2021'
        results = list(mapper_search.search(s, self.session))
        self.assertEqual(results, [])

        s = 'accession where date_recvd on 20/11/2021'
        results = list(mapper_search.search(s, self.session))
        self.assertEqual(results, [])

        s = ('accession where date_recvd < 20/11/2021 and '
             'date_recvd > 22/11/2021')
        results = list(mapper_search.search(s, self.session))
        self.assertEqual(results, [])


    def test_search_by_datestring_query_tz_limits(self):

        import datetime
        Family = self.Family
        Genus = self.Genus
        from bauble.plugins.plants.species_model import Species
        from bauble.plugins.garden.accession import Accession
        from bauble.plugins.garden.location import Location
        from bauble.plugins.garden.plant import Plant
        family2 = Family(family='family2')
        g2 = Genus(family=family2, genus='genus2')
        f3 = Family(family='fam3', qualifier='s. lat.')
        g3 = Genus(family=f3, genus='Ixora')
        sp = Species(sp="coccinea", genus=g3)
        ac = Accession(species=sp, code='1979.0001')
        lc = Location(name='loc1', code='loc1')
        pp = Plant(accession=ac, code='01', location=lc, quantity=1)
        pp2 = Plant(accession=ac, code='02', location=lc, quantity=1)
        from datetime import timezone
        # these will store UTC datetimes relative to local time.  Both should
        # be on the same date locally but will be across 2 dates if the local
        # timezone is anything but +00:00
        start_of_day = (datetime.datetime(2009, 2, 12, 0, 0, 0, 0)
                        .astimezone(tz=timezone.utc))
        pp._last_updated = start_of_day
        end_of_day = (datetime.datetime(2009, 2, 12, 23, 59, 0, 0)
                      .astimezone(tz=timezone.utc))
        pp2._last_updated = end_of_day
        self.session.add_all([family2, g2, f3, g3, sp, ac, lc, pp, pp2])
        self.session.commit()

        mapper_search = search.get_strategy('MapperSearch')
        self.assertTrue(isinstance(mapper_search, search.MapperSearch))
        logger.debug('pp last updated: %s', pp._last_updated)
        logger.debug('pp2 last updated: %s', pp2._last_updated)

        # isoparse
        search_str = 'plant where _last_updated on 2009-02-12'
        results = list(mapper_search.search(search_str, self.session))
        self.assertCountEqual(results, [pp, pp2])

        search_str = 'plant where _last_updated on 12/2/2009'
        results = list(mapper_search.search(search_str, self.session))
        self.assertCountEqual(results, [pp, pp2])

        # hybrid property
        pp.planted.date = start_of_day
        pp2.planted.date = end_of_day
        self.session.add_all([pp, pp2])
        self.session.commit()
        search_str = 'plant where planted.date on 12/2/2009'
        results = list(mapper_search.search(search_str, self.session))
        self.assertCountEqual(results, [pp, pp2])


    def test_between_evaluate(self):
        'use BETWEEN value and value'
        Family = self.Family
        Genus = self.Genus
        from bauble.plugins.plants.species_model import Species
        from bauble.plugins.garden.accession import Accession
        #from bauble.plugins.garden.location import Location
        #from bauble.plugins.garden.plant import Plant
        family2 = Family(family='family2')
        g2 = Genus(family=family2, genus='genus2')
        f3 = Family(family='fam3', qualifier='s. lat.')
        g3 = Genus(family=f3, genus='Ixora')
        sp = Species(sp="coccinea", genus=g3)
        ac = Accession(species=sp, code='1979.0001')
        self.session.add_all([family2, g2, f3, g3, sp, ac])
        self.session.commit()

        mapper_search = search.get_strategy('MapperSearch')
        self.assertTrue(isinstance(mapper_search, search.MapperSearch))

        s = 'accession where code between "1978" and "1980"'
        results = list(mapper_search.search(s, self.session))
        self.assertEqual(results, [ac])
        s = 'accession where code between "1980" and "1980"'
        results = list(mapper_search.search(s, self.session))
        self.assertEqual(results, [])

    def test_search_by_query_synonyms(self):
        """SynonymSearch strategy gives all synonyms of given taxon."""
        Family = self.Family
        Genus = self.Genus
        family2 = Family(family='family2')
        g2 = Genus(family=family2, genus='genus2')
        f3 = Family(family='fam3', qualifier='s. lat.')
        g3 = Genus(family=f3, genus='Ixora')
        g4 = Genus(family=f3, genus='Schetti')
        self.session.add_all([family2, g2, f3, g3, g4])
        g4.accepted = g3
        self.session.commit()

        prefs.prefs['bauble.search.return_accepted'] = True

        s = 'Schetti'
        search.search(s, self.session)
        results = search.result_cache.get('SynonymSearch')
        self.assertEqual(results, [g3])

    def test_search_by_query_synonyms_disabled(self):
        Family = self.Family
        Genus = self.Genus
        family2 = Family(family='family2')
        g2 = Genus(family=family2, genus='genus2')
        f3 = Family(family='fam3', qualifier='s. lat.')
        g3 = Genus(family=f3, genus='Ixora')
        g4 = Genus(family=f3, genus='Schetti')
        self.session.add_all([family2, g2, f3, g3, g4])
        g4.accepted = g3
        self.session.commit()

        prefs.prefs['bauble.search.return_accepted'] = False

        s = 'Schetti'
        search.search(s, self.session)
        # SynonymsSearch should not run, nothing in results_cache
        results = search.result_cache.get('SynonymSearch')
        self.assertIsNone(results)

    def test_search_by_query_vernacular(self):

        Family = self.Family
        Genus = self.Genus
        from bauble.plugins.plants.species_model import Species
        from bauble.plugins.plants.species_model import VernacularName
        family2 = Family(family='family2')
        g2 = Genus(family=family2, genus='genus2')
        f3 = Family(family='fam3', qualifier='s. lat.')
        g3 = Genus(family=f3, genus='Ixora')
        sp = Species(sp="coccinea", genus=g3)
        vn = VernacularName(name="coral rojo", language="es", species=sp)
        self.session.add_all([family2, g2, f3, g3, sp, vn])
        self.session.commit()

        mapper_search = search.get_strategy('MapperSearch')
        self.assertTrue(isinstance(mapper_search, search.MapperSearch))

        s = "rojo"
        results = mapper_search.search(s, self.session)
        self.assertEqual(results, {vn})

    def test_search_ambiguous_joins_no_results(self):
        """These joins broke down when upgrading to SQLA 1.4"""
        mapper_search = search.get_strategy('MapperSearch')
        self.assertTrue(isinstance(mapper_search, search.MapperSearch))

        s = "genus where _synonyms.synonym.id != 0"
        results = list(mapper_search.search(s, self.session))
        self.assertEqual(results, [])

        s = ("geography where tdwg_code = '50' or "
             "parent.tdwg_code = '50' or "
             "parent.parent.tdwg_code = '50'")
        results = list(mapper_search.search(s, self.session))
        self.assertEqual(results, [])

        s = ("plant where accession.species.genus.family.genera.epithet "
             "= 'Ficus'")
        results = list(mapper_search.search(s, self.session))
        self.assertEqual(results, [])

        import warnings
        # possible: SAWarning: SELECT statement has a cartesian product between
        # FROM element(s) "species" and FROM element "species_1"
        with warnings.catch_warnings(record=True) as warns:
            warnings.simplefilter("always")
            results = list(mapper_search.search(
                "species where sp = 'viminalis' and _accepted.species.sp"
                " = 'sp'", self.session))
            self.assertEqual(results, [])
            self.assertEqual(warns, [])
            warnings.resetwarnings()

    def test_search_ambiguous_joins_w_results(self):
        """These joins broke down when upgrading to SQLA 1.4"""
        from bauble.plugins.plants.geography import geography_importer
        [_ for _ in geography_importer()]
        from bauble.plugins.plants.family import Family
        from bauble.plugins.plants.genus import Genus
        from bauble.plugins.plants.species import Species
        g2 = Genus(family=self.family, genus='genus2')
        self.genus.accepted = g2
        f1 = Family(epithet='Moraceae')
        g3 = Genus(family=f1, genus='Ficus')
        g4 = Genus(family=f1, genus='Artocarpus')
        sp1 = Species(genus=g3, epithet='virens')
        sp2 = Species(genus=g4, epithet='heterophyllus')
        sp3 = Species(sp="sp", genus=g3)
        self.session.add_all([g2, g3, g4, f1, sp1, sp2, sp3])
        sp1.accepted = sp3
        self.session.commit()

        mapper_search = search.get_strategy('MapperSearch')
        self.assertTrue(isinstance(mapper_search, search.MapperSearch))

        s = "genus where _synonyms.synonym.id != 0"
        results = list(mapper_search.search(s, self.session))
        self.assertEqual(results, [g2])

        s = ("geography where tdwg_code = '50' or "
             "parent.tdwg_code = '50' or "
             "parent.parent.tdwg_code = '50'")
        results = mapper_search.search(s, self.session)
        expected = ["WAU-AC", "50", "NSW-CT", "QLD-CS", "NFK-LH", "NSW",
                    "NSW-NS", "NFK-NI", "NFK", "NTA", "QLD", "QLD-QU", "SOA",
                    "TAS", "VIC", "WAU-WA", "WAU"]

        self.assertCountEqual([i.tdwg_code for i in results], expected)

        s = ("species where genus.family.genera.epithet = 'Ficus'")
        results = list(mapper_search.search(s, self.session))
        self.assertCountEqual(results, [sp1, sp2, sp3])

        import warnings
        # possible: SAWarning: SELECT statement has a cartesian product between
        # FROM element(s) "species" and FROM element "species_1"
        with warnings.catch_warnings(record=True) as warns:
            warnings.simplefilter("always")
            results = list(mapper_search.search(
                "species where sp = 'virens' and _accepted.species.sp"
                " = 'sp'", self.session))
            self.assertEqual(results, [sp1])
            self.assertEqual(warns, [])
            warnings.resetwarnings()

    def test_complex_query(self):
        """Something with multiple joins, and, or, parethesis, not, between, a
        filter, in, between and a hybrid property

        Tests that parsing and query formation happens as expected in complex
        queries.
        """
        from bauble.plugins.plants.family import Family
        from bauble.plugins.plants.genus import Genus
        from bauble.plugins.plants.species import Species
        from bauble.plugins.garden.accession import Accession
        from bauble.plugins.garden.source import SourceDetail, Source
        from bauble.plugins.garden.plant import Plant
        from bauble.plugins.garden.location import Location
        g2 = Genus(family=self.family, genus='genus2')
        f1 = Family(epithet='Moraceae')
        g3 = Genus(family=f1, genus='Ficus')
        g4 = Genus(family=f1, genus='Artocarpus')
        sp1 = Species(genus=g3, epithet='virens')
        sp2 = Species(genus=g4, epithet='heterophyllus')
        sp3 = Species(sp="sp", genus=g3)
        ac = Accession(species=sp2, code='1979.0001', quantity_recvd=10)
        a2 = Accession(species=sp1, code='1979.0002', quantity_recvd=5)
        sd = SourceDetail(source_type='Individual', name='Jade Green')
        ac3 = Accession(species=sp2, code='2023.0003', quantity_recvd=10,
                        source=Source(source_detail=sd))
        lc = Location(name='loc1', code='loc1')
        lc2 = Location(name='loc2', code='loc2')
        lc3 = Location(name='Zone One', code='zone1')
        pp = Plant(accession=ac, code='01', location=lc, quantity=1)
        p2 = Plant(accession=ac, code='02', location=lc2, quantity=1)
        plt3 = Plant(accession=ac3, code='02', location=lc3, quantity=1)
        self.session.add_all([g2, g3, g4, f1, sp1, sp2, sp3, ac, a2, lc, lc2,
                              pp, p2, plt3])
        self.session.commit()

        mapper_search = search.get_strategy('MapperSearch')
        self.assertTrue(isinstance(mapper_search, search.MapperSearch))

        s = ("species where active is True and not "
             "(accessions[_created > -1].quantity_recvd in 5, 6 or "
             "accessions.plants.location.code = 'loc2') and id "
             "BETWEEN 1 and 20")
        results = list(mapper_search.search(s, self.session))
        for i in results:
            print(i)
        self.assertCountEqual(results, [sp3])

        s = ("species where active is True and not "
             "(accessions[_created > -1].quantity_recvd in 7, 6 or "
             "accessions.plants.location.code = 'loc1') and id "
             "BETWEEN 0 and 1")
        results = list(mapper_search.search(s, self.session))
        for i in results:
            print(i)
        self.assertCountEqual(results, [sp1])

        s = ("species where active is False and not "
             "(accessions[_created > -1].quantity_recvd in 7, 6 or "
             "accessions.plants.location.code = 'loc1') and id "
             "BETWEEN 0 and 1")
        results = list(mapper_search.search(s, self.session))
        for i in results:
            print(i)
        self.assertCountEqual(results, [])
        # include an AssociationProxy
        sp3.accepted = sp1
        self.session.commit()
        s = ("species where accepted.sp = 'virens' and not "
             "(accessions[_created > -1].quantity_recvd in 5, 6 or "
             "accessions.plants.location.code = 'loc2') and id "
             "BETWEEN 1 and 20")
        results = list(mapper_search.search(s, self.session))
        self.assertCountEqual(results, [sp3])

        # and and not query
        s = ("accession where code like '2023%' and source.source_detail.name "
             "contains 'Green' and not plants.location.code contains 'loc'")
        results = list(mapper_search.search(s, self.session))
        for i in results:
            print(i)
        self.assertCountEqual(results, [ac3])



class InOperatorSearch(BaubleTestCase):
    def __init__(self, *args):
        super().__init__(*args)

    def setUp(self):
        super().setUp()
        db.engine.execute('delete from genus')
        db.engine.execute('delete from family')
        from bauble.plugins.plants.family import Family
        from bauble.plugins.plants.genus import Genus
        self.family = Family(family='family1', qualifier='s. lat.', id=1)
        self.g1 = Genus(family=self.family, genus='genus1', id=1)
        self.g2 = Genus(family=self.family, genus='genus2', id=2)
        self.g3 = Genus(family=self.family, genus='genus3', id=3)
        self.g4 = Genus(family=self.family, genus='genus4', id=4)
        self.Family = Family
        self.Genus = Genus
        self.session.add_all([self.family, self.g1, self.g2, self.g3, self.g4])
        self.session.commit()

    def test_in_singleton(self):
        mapper_search = search.get_strategy('MapperSearch')
        self.assertTrue(isinstance(mapper_search, search.MapperSearch))

        s = 'genus where id in 1'
        results = list(mapper_search.search(s, self.session))
        self.assertEqual(results, [self.g1])

    def test_in_list(self):
        mapper_search = search.get_strategy('MapperSearch')
        self.assertTrue(isinstance(mapper_search, search.MapperSearch))

        s = 'genus where id in 1,2,3'
        results = list(mapper_search.search(s, self.session))
        self.assertCountEqual(results, [self.g1, self.g2, self.g3])

    def test_in_list_no_result(self):
        mapper_search = search.get_strategy('MapperSearch')
        self.assertTrue(isinstance(mapper_search, search.MapperSearch))

        s = 'genus where id in 5,6'
        results = list(mapper_search.search(s, self.session))
        self.assertEqual(results, [])

    def test_in_composite_expression(self):
        mapper_search = search.get_strategy('MapperSearch')
        self.assertTrue(isinstance(mapper_search, search.MapperSearch))

        s = 'genus where id in 1,2 or id>8'
        results = list(mapper_search.search(s, self.session))
        self.assertCountEqual(results, [self.g1, self.g2])

    def test_in_composite_expression_excluding(self):
        mapper_search = search.get_strategy('MapperSearch')
        self.assertTrue(isinstance(mapper_search, search.MapperSearch))

        s = 'genus where id in 1,2,4 and id<3'
        results = list(mapper_search.search(s, self.session))
        self.assertCountEqual(results, [self.g1, self.g2])


class BinomialSearchTests(BaubleTestCase):
    def __init__(self, *args):
        super().__init__(*args)

    def setUp(self):
        super().setUp()
        db.engine.execute('delete from genus')
        db.engine.execute('delete from family')
        from bauble.plugins.plants.family import Family
        from bauble.plugins.plants.genus import Genus
        from bauble.plugins.plants.species import Species
        f1 = Family(family='family1', qualifier='s. lat.')
        g1 = Genus(family=f1, genus='genus1')
        f2 = Family(family='family2')
        g2 = Genus(family=f2, genus='genus2')
        f3 = Family(family='fam3', qualifier='s. lat.')
        g3 = Genus(family=f3, genus='Ixora')
        sp = Species(sp="coccinea", genus=g3)
        sp2 = Species(sp="peruviana", genus=g3)
        sp3 = Species(sp="chinensis", genus=g3)
        self.cv1 = Species(cultivar_epithet="Magnifica", genus=g3)
        self.cv2 = Species(sp="chinensis", cultivar_epithet="Prince Of Orange",
                           genus=g3)
        g4 = Genus(family=f3, genus='Pachystachys')
        sp4 = Species(sp='coccinea', genus=g4)
        self.session.add_all([f1, f2, g1, g2, f3, g3, sp, sp2, sp3, g4, sp4])
        self.session.commit()
        self.ixora, self.ic, self.pc = g3, sp, sp4

    def tearDown(self):
        super().tearDown()

    def test_binomial_complete(self):
        mapper_search = search.get_strategy('MapperSearch')
        self.assertTrue(isinstance(mapper_search, search.MapperSearch))

        s = 'Ixora coccinea'  # matches Ixora coccinea
        results = list(mapper_search.search(s, self.session))
        self.assertEqual(results, [self.ic])

    def test_binomial_incomplete(self):
        mapper_search = search.get_strategy('MapperSearch')
        self.assertTrue(isinstance(mapper_search, search.MapperSearch))

        s = 'Ix cocc'  # matches Ixora coccinea
        results = list(mapper_search.search(s, self.session))
        self.assertEqual(results, [self.ic])

    def test_binomial_no_match(self):
        mapper_search = search.get_strategy('MapperSearch')
        self.assertTrue(isinstance(mapper_search, search.MapperSearch))

        s = 'Cosito inesistente'  # matches nothing
        results = list(mapper_search.search(s, self.session))
        self.assertEqual(results, [])

    def test_almost_binomial(self):
        mapper_search = search.get_strategy('MapperSearch')
        self.assertTrue(isinstance(mapper_search, search.MapperSearch))

        s = 'ixora coccinea'  # matches Ixora, I.coccinea, P.coccinea
        results = list(mapper_search.search(s, self.session))
        expected = [sp for sp in self.ixora.species] + [self.ixora, self.pc]
        self.assertCountEqual(results, expected)

    def test_sp_cultivar_also_matches(self):
        mapper_search = search.get_strategy('MapperSearch')
        self.assertTrue(isinstance(mapper_search, search.MapperSearch))

        from bauble.plugins.plants.species import Species
        from bauble.plugins.plants.genus import Genus
        g3 = self.session.query(Genus).filter(Genus.genus == 'Ixora').one()
        sp5 = Species(sp="coccinea", genus=g3,
                      cultivar_epithet='Nora Grant')
        self.session.add_all([sp5])
        self.session.commit()
        s = 'Ixora coccinea'  # matches I.coccinea and Nora Grant
        results = list(mapper_search.search(s, self.session))
        self.assertCountEqual(results, [self.ic, sp5])

    def test_cultivar_no_sp_search(self):
        mapper_search = search.get_strategy('MapperSearch')
        self.assertTrue(isinstance(mapper_search, search.MapperSearch))

        s = "Ixora 'Mag"
        results = list(mapper_search.search(s, self.session))
        self.assertEqual(results, [self.cv1])

    def test_cultivar_w_sp_search(self):
        mapper_search = search.get_strategy('MapperSearch')
        self.assertTrue(isinstance(mapper_search, search.MapperSearch))

        s = "Ixo 'Pri"
        results = list(mapper_search.search(s, self.session))
        self.assertEqual(results, [self.cv2])

    def test_full_cultivar_search(self):
        mapper_search = search.get_strategy('MapperSearch')
        self.assertTrue(isinstance(mapper_search, search.MapperSearch))

        s = "Ixora 'Prince Of Orange'"
        results = list(mapper_search.search(s, self.session))
        self.assertEqual(results, [self.cv2])

    def test_trade_name_search(self):
        self.cv2.trade_name = 'Test Trade Name'
        self.session.commit()
        mapper_search = search.get_strategy('MapperSearch')
        self.assertTrue(isinstance(mapper_search, search.MapperSearch))

        string = "Ixo 'Test"
        results = list(mapper_search.search(string, self.session))
        self.assertEqual(results, [self.cv2])


class BuildingSQLStatements(BaubleTestCase):
    import bauble.search
    SearchParser = bauble.search.SearchParser

    def test_canfindspeciesfromgenus(self):
        'can find species from genus'

        text = 'species where species.genus=genus1'
        sp = self.SearchParser()
        results = sp.parse_string(text)
        self.assertEqual(
            str(results.statement),
            "SELECT * FROM species WHERE (species.genus = 'genus1')")

    def test_canuselogicaloperators(self):
        'can use logical operators'

        sp = self.SearchParser()
        results = sp.parse_string('species where species.genus=genus1 OR '
                                  'species.sp=name AND species.genus.family'
                                  '.family=name')
        self.assertEqual(str(results.statement), "SELECT * FROM species WHERE "
                         "((species.genus = 'genus1') OR ((species.sp = 'name'"
                         ") AND (species.genus.family.family = 'name')))")

        sp = self.SearchParser()
        results = sp.parse_string('species where species.genus=genus1 || '
                                  'species.sp=name && species.genus.family.'
                                  'family=name')
        self.assertEqual(str(results.statement), "SELECT * FROM species WHERE "
                         "((species.genus = 'genus1') OR ((species.sp = 'name'"
                         ") AND (species.genus.family.family = 'name')))")

    def test_canfindfamilyfromgenus(self):
        'can find family from genus'

        sp = self.SearchParser()
        results = sp.parse_string('family where family.genus=genus1')
        self.assertEqual(str(results.statement), "SELECT * FROM family WHERE ("
                         "family.genus = 'genus1')")

    def test_canfindgenusfromfamily(self):
        'can find genus from family'

        sp = self.SearchParser()
        results = sp.parse_string('genus where genus.family=family2')
        self.assertEqual(str(results.statement), "SELECT * FROM genus WHERE ("
                         "genus.family = 'family2')")

    def test_canfindplantbyaccession(self):
        'can find plant from the accession id'

        sp = self.SearchParser()
        results = sp.parse_string('plant where accession.species.id=113')
        self.assertEqual(str(results.statement), 'SELECT * FROM plant WHERE ('
                         'accession.species.id = 113.0)')

    def test_canuseNOToperator(self):
        'can use the NOT operator'

        sp = self.SearchParser()
        results = sp.parse_string('species where NOT species.genus.family.'
                                  'family=name')
        self.assertEqual(str(results.statement), "SELECT * FROM species WHERE "
                         "NOT (species.genus.family.family = 'name')")
        results = sp.parse_string('species where ! species.genus.family.family'
                                  '=name')
        self.assertEqual(str(results.statement), "SELECT * FROM species WHERE "
                         "NOT (species.genus.family.family = 'name')")
        results = sp.parse_string('species where family=1 OR family=2 AND NOT '
                                  'genus.id=3')
        self.assertEqual(str(results.statement), "SELECT * FROM species WHERE "
                         "((family = 1.0) OR ((family = 2.0) AND NOT (genus.id"
                         " = 3.0)))")

    def test_canuse_lowercase_operators(self):
        'can use the operators in lower case'

        sp = self.SearchParser()
        results = sp.parse_string('species where not species.genus.family.'
                                  'family=name')
        self.assertEqual(str(results.statement), "SELECT * FROM species WHERE "
                         "NOT (species.genus.family.family = 'name')")
        results = sp.parse_string('species where ! species.genus.family.family'
                                  '=name')
        self.assertEqual(str(results.statement), "SELECT * FROM species WHERE "
                         "NOT (species.genus.family.family = 'name')")
        results = sp.parse_string('species where family=1 or family=2 and not '
                                  'genus.id=3')
        self.assertEqual(str(results.statement), "SELECT * FROM species WHERE "
                         "((family = 1.0) OR ((family = 2.0) AND NOT (genus.id"
                         " = 3.0)))")

    def test_notes_is_not_not_es(self):
        'acknowledges word boundaries'

        sp = self.SearchParser()
        results = sp.parse_string('species where notes.id!=0')
        self.assertEqual(str(results.statement),
                         "SELECT * FROM species WHERE (notes.id != 0.0)")

    def test_between_just_parse_0(self):
        'use BETWEEN value and value'
        sp = self.SearchParser()
        results = sp.parse_string('species where id between 0 and 1')
        self.assertEqual(str(results.statement),
                         "SELECT * FROM species WHERE (BETWEEN id 0.0 1.0)")

    def test_between_just_parse_1(self):
        'use BETWEEN value and value'
        sp = self.SearchParser()
        results = sp.parse_string('species where step.id between 0 and 1')
        self.assertEqual(str(results.statement),
                         "SELECT * FROM species WHERE (BETWEEN step.id 0.0 1.0)")

    def test_between_just_parse_2(self):
        'use BETWEEN value and value'
        sp = self.SearchParser()
        results = sp.parse_string('species where step.step.step.step[a=1].id between 0 and 1')
        self.assertEqual(str(results.statement),
                         "SELECT * FROM species WHERE (BETWEEN step.step.step.step[a=1.0].id 0.0 1.0)")


class FilterThenMatchTests(BaubleTestCase):
    def __init__(self, *args):
        super().__init__(*args)
        prefs.testing = True

    def setUp(self):
        super().setUp()
        db.engine.execute('delete from genus')
        db.engine.execute('delete from family')
        db.engine.execute('delete from genus_note')
        from bauble.plugins.plants.family import Family
        from bauble.plugins.plants.genus import Genus, GenusNote
        self.family = Family(family='family1', qualifier='s. lat.')
        self.genus1 = Genus(family=self.family, genus='genus1')
        self.genus2 = Genus(family=self.family, genus='genus2')
        self.genus3 = Genus(family=self.family, genus='genus3')
        self.genus4 = Genus(family=self.family, genus='genus4')
        n1 = GenusNote(category='commentarii', note='olim', genus=self.genus1)
        n2 = GenusNote(category='commentarii', note='erat', genus=self.genus1)
        n3 = GenusNote(category='commentarii', note='verbum', genus=self.genus2)
        n4 = GenusNote(category='test', note='olim', genus=self.genus3)
        n5 = GenusNote(category='test', note='verbum', genus=self.genus3)
        self.session.add_all([self.family, self.genus1, self.genus2, self.genus3, self.genus4, n1, n2, n3, n4, n5])
        self.session.commit()

    def tearDown(self):
        super().tearDown()

    def test_can_filter_match_notes(self):
        mapper_search = search.get_strategy('MapperSearch')
        self.assertTrue(isinstance(mapper_search, search.MapperSearch))

        s = "genus where notes.note='olim'"
        results = list(mapper_search.search(s, self.session))
        self.assertCountEqual(results, [self.genus1, self.genus3])

        s = "genus where notes[category='test'].note='olim'"
        results = list(mapper_search.search(s, self.session))
        self.assertCountEqual(results, [self.genus3])

        s = "genus where notes.category='commentarii'"
        results = list(mapper_search.search(s, self.session))
        self.assertCountEqual(results, [self.genus1, self.genus2])

        s = "genus where notes[note='verbum'].category='commentarii'"
        results = list(mapper_search.search(s, self.session))
        self.assertEqual(results, [self.genus2])

    def test_can_find_empty_set(self):
        mapper_search = search.get_strategy('MapperSearch')
        self.assertTrue(isinstance(mapper_search, search.MapperSearch))

        s = "genus where notes=Empty"
        results = list(mapper_search.search(s, self.session))
        self.assertEqual(results, [self.genus4])

    def test_can_find_non_empty_set(self):
        mapper_search = search.get_strategy('MapperSearch')
        self.assertTrue(isinstance(mapper_search, search.MapperSearch))

        s = "genus where notes!=Empty"
        results = list(mapper_search.search(s, self.session))
        self.assertCountEqual(results, [self.genus1, self.genus2, self.genus3])

    def test_can_match_list_of_values(self):
        mapper_search = search.get_strategy('MapperSearch')
        self.assertTrue(isinstance(mapper_search, search.MapperSearch))

        s = "genus where notes.note in 'olim', 'erat', 'verbum'"
        results = list(mapper_search.search(s, self.session))
        self.assertEqual(results, [self.genus1, self.genus2, self.genus3])

        s = "genus where notes[category='test'].note in 'olim', 'erat', 'verbum'"
        results = list(mapper_search.search(s, self.session))
        self.assertEqual(results, [self.genus3])

    def test_parenthesised_search(self):
        mapper_search = search.get_strategy('MapperSearch')
        self.assertTrue(isinstance(mapper_search, search.MapperSearch))

        s = "genus where (notes!=Empty) and (notes=Empty)"
        results = list(mapper_search.search(s, self.session))
        self.assertEqual(results, [])


class EmptySetEqualityTest(unittest.TestCase):
    def test_EmptyToken_equals(self):
        et1 = search.EmptyToken()
        et2 = search.EmptyToken()
        self.assertEqual(et1, et2)
        self.assertTrue(et1 == et2)
        self.assertTrue(et1 == set())

    def test_empty_token_otherwise(self):
        et1 = search.EmptyToken()
        self.assertFalse(et1 is None)
        self.assertFalse(et1 == 0)
        self.assertFalse(et1 == '')
        self.assertFalse(et1 == set([1, 2, 3]))

    def test_EmptyToken_representation(self):
        et1 = search.EmptyToken()
        self.assertEqual("%s" % et1, "Empty")
        self.assertEqual(et1.express(), set())

    def test_NoneToken_representation(self):
        nt1 = search.NoneToken()
        self.assertEqual("%s" % nt1, "(None<NoneType>)")
        self.assertEqual(nt1.express(), None)


class AggregatingFunctions(BaubleTestCase):
    def __init__(self, *args):
        super().__init__(*args)
        prefs.testing = True

    def setUp(self):
        super().setUp()
        db.engine.execute('delete from genus')
        db.engine.execute('delete from family')
        db.engine.execute('delete from species')
        db.engine.execute('delete from accession')
        from bauble.plugins.plants import Family, Genus, Species
        f1 = Family(family='Rutaceae', qualifier='')
        g1 = Genus(family=f1, genus='Citrus')
        sp1 = Species(sp="medica", genus=g1)
        sp2 = Species(sp="maxima", genus=g1)
        sp3 = Species(sp="aurantium", genus=g1)

        f2 = Family(family='Sapotaceae')
        g2 = Genus(family=f2, genus='Manilkara')
        sp4 = Species(sp='zapota', genus=g2)
        sp5 = Species(sp='zapotilla', genus=g2)
        g3 = Genus(family=f2, genus='Pouteria')
        sp6 = Species(sp='stipitata', genus=g3)

        f3 = Family(family='Musaceae')
        g4 = Genus(family=f3, genus='Musa')
        self.session.add_all([f1, f2, f3, g1, g2, g3, g4,
                              sp1, sp2, sp3, sp4, sp5, sp6])
        self.session.commit()

    def tearDown(self):
        super().tearDown()

    def test_count(self):
        mapper_search = search.get_strategy('MapperSearch')
        self.assertTrue(isinstance(mapper_search, search.MapperSearch))

        s = 'genus where count(species.id) > 3'
        results = list(mapper_search.search(s, self.session))
        self.assertEqual(len(results), 0)

        s = 'genus where count(species.id) > 2'
        results = list(mapper_search.search(s, self.session))
        self.assertEqual(len(results), 1)
        result = results.pop()
        self.assertEqual(result.id, 1)

        s = 'genus where count(species.id) == 2'
        results = list(mapper_search.search(s, self.session))
        self.assertEqual(len(results), 1)
        result = results.pop()
        self.assertEqual(result.id, 2)

    def test_count_just_parse(self):
        import bauble.search
        SearchParser = bauble.search.SearchParser
        sp = SearchParser()
        s = 'genus where count(species.id) == 2'
        results = sp.parse_string(s)
        self.assertEqual(
            str(results.statement),
            "SELECT * FROM genus WHERE ((count species.id) == 2.0)")

    def test_count_complex_query(self):
        mapper_search = search.get_strategy('MapperSearch')
        self.assertTrue(isinstance(mapper_search, search.MapperSearch))

        string = ('genus where species.epithet like za% and '
                  'count(species.id) > 1')
        results = list(mapper_search.search(string, self.session))
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].id, 2)

        from bauble.plugins.plants.geography import Geography
        from bauble.plugins.plants import Species, SpeciesDistribution
        geo1 = Geography(name='Test1', tdwg_code='T1', tdwg_level=1)
        geo2 = Geography(name='Test2', tdwg_code='T2', tdwg_level=1)
        sp1 = self.session.query(Species).first()
        sp1.distribution = [SpeciesDistribution(geography=geo1),
                            SpeciesDistribution(geography=geo2)]

        self.session.commit()
        string = ("species where count(distribution.id) > 1 and "
                  "distribution.geography.name = 'Test1'")
        results = list(mapper_search.search(string, self.session))
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].id, sp1.id)

        string = ("species where distribution.geography.name = 'Test2' "
                  "and count(distribution.geography.id) > 1")
        results = list(mapper_search.search(string, self.session))
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].id, sp1.id)

        string = ("species where distribution.geography.name = 'Test2' "
                  "and count(distribution.geography.id) > 1 or id = 2")
        results = list(mapper_search.search(string, self.session))
        self.assertEqual(len(results), 2)

    def test_min(self):
        mapper_search = search.get_strategy('MapperSearch')
        string = ("genus where min(species.id) = 1")
        results = list(mapper_search.search(string, self.session))
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].id, 1)

    def test_max(self):
        mapper_search = search.get_strategy('MapperSearch')
        string = ("genus where max(species.id) = 3")
        results = list(mapper_search.search(string, self.session))
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].id, 1)

    def test_sum(self):
        mapper_search = search.get_strategy('MapperSearch')
        string = ("genus where sum(species.id) = 9")
        results = list(mapper_search.search(string, self.session))
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].id, 2)

    def test_multiple_aggregate_funcs(self):
        mapper_search = search.get_strategy('MapperSearch')
        string = ("genus where sum(species.id) = 9 and count(species.id) = 2")
        results = list(mapper_search.search(string, self.session))
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].id, 2)


class BaubleSearchSearchTest(BaubleTestCase):
    def test_search_search_uses_Mapper_Search(self):
        search.search("genus like %", self.session)
        self.assertTrue('SearchStrategy "genus like %" (MapperSearch)' in
                        self.handler.messages['bauble.search']['debug'])
        self.handler.reset()
        search.search("12.11.13", self.session)
        self.assertTrue('SearchStrategy "12.11.13" (MapperSearch)' in
                        self.handler.messages['bauble.search']['debug'])
        self.handler.reset()
        search.search("So ha", self.session)
        self.assertTrue('SearchStrategy "So ha" (MapperSearch)' in
                        self.handler.messages['bauble.search']['debug'])
