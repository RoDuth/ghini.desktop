# Copyright (c) 2005,2006,2007,2008,2009 Brett Adams <brett@belizebotanic.org>
# Copyright (c) 2012-2016 Mario Frasca <mario@anche.no>
# Copyright (c) 2018 Ross Demuth <rossdemuth123@gmail.com>
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

from unittest import TestCase
from sqlalchemy import Table, Column, Integer, ForeignKey, MetaData, Sequence

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from bauble import utils
from bauble.error import CheckConditionError
from bauble.test import BaubleTestCase
from bauble import db


class UtilsTest(TestCase):

    def test_topological_sort_total(self):
        self.assertEqual(
            utils.topological_sort([1, 2, 3], [(2, 1), (3, 2)]), [3, 2, 1])

    def test_topological_sort_partial(self):
        self.assertEqual(
            utils.topological_sort([1, 2, 3, 4], [(2, 1)]), [4, 3, 2, 1])

    def test_topological_sort_loop(self):
        self.assertEqual(
            utils.topological_sort([1, 2], [(2, 1), (1, 2)]), None)

    def test_topological_empty_dependencies(self):
        # list contain same elements, no dependancies so order doesn't matter
        self.assertCountEqual(
            utils.topological_sort(['a', 'b', 'c'], []), ['c', 'b', 'a'])

    def test_topological_full_dependencies(self):
        # list is ordered
        self.assertEqual(
            utils.topological_sort(['a', 'b', 'c'], [('a', 'b'), ('b', 'c')]),
            ['a', 'b', 'c'])

    def test_topological_partial_dependencies(self):
        # 'e' has no dependencies so comes before or after
        self.assertEqual(
            utils.topological_sort(['b', 'e'],
                                   [('a', 'b'), ('b', 'c'), ('b', 'd')]),
            ['a', 'b', 'd', 'c', 'e'])

    def test_topological_empty_input_full_dependencies(self):
        # could return empty
        self.assertEqual(
            utils.topological_sort([], [('a', 'b'), ('b', 'c'), ('b', 'd')]),
            ['a', 'b', 'd', 'c'])

    def test_create_message_details_dialog(self):
        details = "these are the lines that I want to test\n2nd line\n3rd Line"
        msg = 'test message'

        dlog = utils.create_message_details_dialog(msg, details)
        self.assertTrue(isinstance(dlog, Gtk.MessageDialog))
        msg_label = dlog.get_message_area().get_children()[0]

        self.assertEqual(msg_label.get_text(), msg)
        expander = dlog.get_content_area().get_children()[1]
        buffer = expander.get_children()[0].get_children()[0].get_buffer()

        self.assertEqual(buffer.get_line_count(), 3)
        self.assertEqual(buffer.get_text(*buffer.get_bounds(), False), details)

    def test_create_message_dialog(self):
        msg = 'test message'
        #msg = ' this is a longer message to test that the dialog width is correct.....but what if it keeps going'
        dlog = utils.create_message_dialog(msg)
        self.assertTrue(isinstance(dlog, Gtk.MessageDialog))
        msg_label = dlog.get_message_area().get_children()[0]

        self.assertEqual(msg_label.get_text(), msg)
        contents = dlog.get_content_area().get_children()
        # should just be message_area and button_box  (no details area)
        self.assertEqual(len(contents), 2)

    def test_search_tree_model(self):
        """
        Test bauble.utils.search_tree_model
        """
        model = Gtk.TreeStore(str)

        # the rows that should be found
        to_find = []

        row = model.append(None, ['1'])
        model.append(row, ['1.1'])
        to_find.append(model.append(row, ['something']))
        model.append(row, ['1.3'])

        row = model.append(None, ['2'])
        to_find.append(model.append(row, ['something']))
        model.append(row, ['2.1'])

        to_find.append(model.append(None, ['something']))

        root = model.get_iter_first()
        results = utils.search_tree_model(model[root], 'something')
        self.assertTrue(sorted([model.get_path(r) for r in results]),
                        sorted(to_find))

    def test_xml_safe(self):
        """
        Test bauble.utils.xml_safe
        """
        class Test():
            def __str__(self):
                return repr(self)

        import re
        self.assertTrue(re.match('&lt;.*?&gt;', utils.xml_safe(str(Test()))))
        self.assertEqual(utils.xml_safe('test string'), 'test string')
        self.assertEqual(utils.xml_safe('test string'), 'test string')
        self.assertEqual(utils.xml_safe('test< string'), 'test&lt; string')
        self.assertEqual(utils.xml_safe('test< string'), 'test&lt; string')

    def test_range_builder(self):
        """Test bauble.utils.range_builder
        """
        self.assertEqual(utils.range_builder('1-3'), [1, 2, 3])
        self.assertEqual(utils.range_builder('1-3,5-7'),
                         [1, 2, 3, 5, 6, 7])
        self.assertEqual(utils.range_builder('1-3,5'), [1, 2, 3, 5])
        self.assertEqual(utils.range_builder('1-3,5,7-9'),
                         [1, 2, 3, 5, 7, 8, 9])
        self.assertEqual(utils.range_builder('1,2,3,4'), [1, 2, 3, 4])
        self.assertEqual(utils.range_builder('11'), [11])

        # bad range strings
        self.assertEqual(utils.range_builder('-1'), [])
        self.assertEqual(utils.range_builder('a-b'), [])
        self.assertRaises(CheckConditionError, utils.range_builder, '2-1')

    def test_get_urls(self):
        text = 'There a link in here: http://bauble.belizebotanic.org'
        urls = utils.get_urls(text)
        self.assertEqual(urls, [(None, 'http://bauble.belizebotanic.org')],
                         urls)

        text = ('There a link in here: http://bauble.belizebotanic.org '
                'and some text afterwards.')
        urls = utils.get_urls(text)
        self.assertEqual(urls, [(None, 'http://bauble.belizebotanic.org')],
                         urls)

        text = ('There is a link here: http://bauble.belizebotanic.org and '
                'here: https://belizebotanic.org and some text afterwards.')
        urls = utils.get_urls(text)
        self.assertEqual(urls, [(None, 'http://bauble.belizebotanic.org'),
                                (None, 'https://belizebotanic.org')], urls)

        text = ('There a labeled link in here: '
                '[BBG]http://bauble.belizebotanic.org and some text after.')
        urls = utils.get_urls(text)
        self.assertEqual(urls, [('BBG', 'http://bauble.belizebotanic.org')],
                         urls)


class UtilsDBTests(BaubleTestCase):

    def test_find_dependent_tables(self):
        """
        Test bauble.utils.find_dependent_tables
        """

        metadata = MetaData()
        metadata.bind = db.engine

        # table1 does't depend on any tables
        table1 = Table('table1', metadata,
                       Column('id', Integer, primary_key=True))

        # table2 depends on table1
        table2 = Table('table2', metadata,
                       Column('id', Integer, primary_key=True),
                       Column('table1', Integer, ForeignKey('table1.id')))

        # table3 depends on table2
        table3 = Table('table3', metadata,
                       Column('id', Integer, primary_key=True),
                       Column('table2', Integer, ForeignKey('table2.id')),
                       Column('table4', Integer, ForeignKey('table4.id'))
                       )

        # table4 depends on table2
        table4 = Table('table4', metadata,
                       Column('id', Integer, primary_key=True),
                       Column('table2', Integer, ForeignKey('table2.id')))

        # tables that depend on table 1 are 3, 4, 2
        depends = list(utils.find_dependent_tables(table1, metadata))
        self.assertTrue(list(depends) == [table2, table4, table3])

        # tables that depend on table 2 are 3, 4
        depends = list(utils.find_dependent_tables(table2, metadata))
        self.assertTrue(depends == [table4, table3])

        # no tables depend on table 3
        depends = list(utils.find_dependent_tables(table3, metadata))
        self.assertTrue(depends == [])

        # table that depend on table 4 are 3
        depends = list(utils.find_dependent_tables(table4, metadata))
        self.assertTrue(depends == [table3])


class CacheTest(TestCase):
    def test_create_store_retrieve(self):
        from bauble.utils import Cache
        from functools import partial
        invoked = []

        def getter(x):
            invoked.append(x)
            return x

        cache = Cache(2)
        v = cache.get(1, partial(getter, 1))
        self.assertEqual(v, 1)
        self.assertEqual(invoked, [1])
        v = cache.get(1, partial(getter, 1))
        self.assertEqual(v, 1)
        self.assertEqual(invoked, [1])

    def test_respect_size(self):
        from bauble.utils import Cache
        from functools import partial
        invoked = []

        def getter(x):
            invoked.append(x)
            return x

        cache = Cache(2)
        cache.get(1, partial(getter, 1))
        cache.get(2, partial(getter, 2))
        cache.get(3, partial(getter, 3))
        cache.get(4, partial(getter, 4))
        self.assertEqual(invoked, [1, 2, 3, 4])
        self.assertEqual(sorted(cache.storage.keys()), [3, 4])

    def test_respect_timing(self):
        from bauble.utils import Cache
        from functools import partial
        invoked = []

        def getter(x):
            invoked.append(x)
            return x

        cache = Cache(2)
        from time import sleep
        cache.get(1, partial(getter, 1))
        sleep(0.01)
        cache.get(2, partial(getter, 2))
        sleep(0.01)
        cache.get(1, partial(getter, 1))
        sleep(0.01)
        cache.get(3, partial(getter, 3))
        sleep(0.01)
        cache.get(1, partial(getter, 1))
        sleep(0.01)
        cache.get(4, partial(getter, 4))
        self.assertEqual(invoked, [1, 2, 3, 4])
        self.assertEqual(sorted(cache.storage.keys()), [1, 4])

    def test_cache_on_hit(self):
        from bauble.utils import Cache
        from functools import partial
        invoked = []

        def getter(x):
            return x

        cache = Cache(2)
        from time import sleep
        cache.get(1, partial(getter, 1), on_hit=invoked.append)
        sleep(0.01)
        cache.get(1, partial(getter, 1), on_hit=invoked.append)
        sleep(0.01)
        cache.get(2, partial(getter, 2), on_hit=invoked.append)
        sleep(0.01)
        cache.get(1, partial(getter, 1), on_hit=invoked.append)
        sleep(0.01)
        cache.get(3, partial(getter, 3), on_hit=invoked.append)
        sleep(0.01)
        cache.get(1, partial(getter, 1), on_hit=invoked.append)
        sleep(0.01)
        cache.get(4, partial(getter, 4), on_hit=invoked.append)
        self.assertEqual(invoked, [1, 1, 1])
        self.assertEqual(sorted(cache.storage.keys()), [1, 4])


class ResetSequenceTests(BaubleTestCase):
    # TODO Is this and the function it tests redundant?

    def setUp(self):
        super().setUp()
        self.metadata = MetaData()
        self.metadata.bind = db.engine

    def tearDown(self):
        super().tearDown()
        self.metadata.drop_all()

    @staticmethod
    def get_currval(col):
        if db.engine.name == 'postgresql':
            name = '%s_%s_seq' % (col.table.name, col.name)
            stmt = "select currval('%s');" % name
            return db.engine.execute(stmt).fetchone()[0]
        elif db.engine.name == 'sqlite':
            stmt = 'select max(%s) from %s' % (col.name, col.table.name)
            return db.engine.execute(stmt).fetchone()[0] + 1

    def test_no_col_sequence(self):
        """
        Test utils.reset_sequence on a column without a Sequence()

        This only tests that reset_sequence() doesn't fail if there is
        no sequence.
        """

        # test that a column without an explicit sequence works
        table = Table('test_reset_sequence', self.metadata,
                      Column('id', Integer, primary_key=True))
        self.metadata.create_all()
        self.insert = table.insert()  #.compile()
        db.engine.execute(self.insert, values=[{'id': 1}])
        utils.reset_sequence(table.c.id)

    def test_empty_col_sequence(self):
        """
        Test utils.reset_sequence on a column without a Sequence()

        This only tests that reset_sequence() doesn't fail if there is
        no sequence.
        """

        # test that a column without an explicit sequence works
        table = Table('test_reset_sequence', self.metadata,
                      Column('id', Integer, primary_key=True))
        self.metadata.create_all()
        # self.insert = table.insert()#.compile()
        # db.engine.execute(self.insert, values=[{'id': 1}])
        utils.reset_sequence(table.c.id)

    def test_with_col_sequence(self):
        """
        Test utils.reset_sequence on a column that has an Sequence()
        """
        # UPDATE: 10/18/2011 -- we don't use Sequence() explicitly,
        # just autoincrement=True on primary_key columns so this test
        # probably isn't necessary
        table = Table('test_reset_sequence', self.metadata,
                      Column('id', Integer,
                             Sequence('test_reset_sequence_id_seq'),
                             primary_key=True, unique=True))
        self.metadata.create_all()
        rangemax = 10
        for i in range(1, rangemax + 1):
            table.insert().values(id=i).execute()
        utils.reset_sequence(table.c.id)
        currval = self.get_currval(table.c.id)
        self.assertTrue(currval > rangemax, currval)


class GlobalFuncs(TestCase):
    def test_safe_int_valid(self):
        self.assertEqual(utils.safe_int('123'), 123)

    def test_safe_int_valid_not(self):
        self.assertEqual(utils.safe_int('123.2'), 0)

    def test_safe_numeric_valid(self):
        self.assertEqual(utils.safe_numeric('123'), 123)

    def test_safe_numeric_valid_decimal(self):
        self.assertEqual(utils.safe_numeric('123.2'), 123.2)

    def test_safe_numeric_valid_not(self):
        self.assertEqual(utils.safe_numeric('123a.2'), 0)

    def test_xml_safe_name(self):
        self.assertEqual(utils.xml_safe_name('abc'), 'abc')
        self.assertEqual(utils.xml_safe_name('a b c'), 'a_b_c')
        self.assertEqual(utils.xml_safe_name('{[ab]<c>}'), 'abc')
        self.assertEqual(utils.xml_safe_name(''), '_')
        self.assertEqual(utils.xml_safe_name(' '), '_')
        self.assertEqual(utils.xml_safe_name('\u2069\ud8ff'), '_')
        self.assertEqual(utils.xml_safe_name('123'), '_123')
        self.assertEqual(utils.xml_safe_name('<:>'), '_')
        self.assertEqual(utils.xml_safe_name('<picture>'), 'picture')


class MarkupItalicsTests(TestCase):
    def test_markup_simple(self):
        self.assertEqual(utils.markup_italics('sp.'), 'sp.')
        self.assertEqual(
            utils.markup_italics('viminalis'), '<i>viminalis</i>'
        )
        # with ZWS
        self.assertEqual(
            utils.markup_italics('\u200bviminalis'),
            '\u200b<i>viminalis</i>'
        )
        self.assertEqual(
            utils.markup_italics('crista-galli'),
            '<i>crista-galli</i>'
        )

    def test_markup_provisory(self):
        self.assertEqual(
            utils.markup_italics('sp. (Shute Harbour L.J.Webb+ 7916)'),
            'sp. (Shute Harbour L.J.Webb+ 7916)'
        )
        self.assertEqual(
            utils.markup_italics('caerulea (Shute Harbour)'),
            '<i>caerulea</i> (Shute Harbour)'
        )

    def test_markup_nothospecies(self):
        self.assertEqual(
            utils.markup_italics("\xd7 grandiflora"),
            '\xd7 <i>grandiflora</i>'
        )
        self.assertEqual(
            utils.markup_italics("\xd7grandiflora"),
            '\xd7<i>grandiflora</i>'
        )

    def test_markup_species_hybrid(self):
        self.assertEqual(
            utils.markup_italics(
                "lilliputiana \xd7 compacta \xd7 ampullacea"
            ),
            '<i>lilliputiana</i> \xd7 <i>compacta</i> \xd7 <i>ampullacea</i>'
        )

    def test_markup_infraspecific_hybrid(self):
        self.assertEqual(
            utils.markup_italics(
                "wilsonii subsp. cryptophlebium \xd7 wilsonii subsp. wilsonii"
            ),
            '<i>wilsonii</i> subsp. <i>cryptophlebium</i> \xd7 '
            '<i>wilsonii</i> subsp. <i>wilsonii</i>'
        )
        # with ZWS
        self.assertEqual(
            utils.markup_italics(
                "\u200bwilsonii subsp. cryptophlebium \xd7 wilsonii subsp. "
                "wilsonii"
            ),
            '\u200b<i>wilsonii</i> subsp. <i>cryptophlebium</i> \xd7 '
            '<i>wilsonii</i> subsp. <i>wilsonii</i>'
        )

    def test_markup_species_cv_hybrid(self):
        self.assertEqual(
            utils.markup_italics("carolinae \xd7 'Hot Wizz'"),
            "<i>carolinae</i> \xd7 'Hot Wizz'"
        )

    def test_markup_complex_hybrid(self):
        self.assertEqual(
            utils.markup_italics(
                "(carolinae \xd7 'Purple Star') \xd7 (compacta \xd7 sp.)"
            ),
            "(<i>carolinae</i> \xd7 'Purple Star') \xd7 (<i>compacta</i> "
            "\xd7 sp.)"
        )

        self.assertEqual(
            utils.markup_italics(
                "(('Gee Whizz' \xd7 'Fireball' \xd7 compacta) \xd7 "
                "'Purple Star') \xd7 lilliputiana"
            ),
            "(('Gee Whizz' \xd7 'Fireball' \xd7 <i>compacta</i>) \xd7 "
            "'Purple Star') \xd7 <i>lilliputiana</i>"
        )
        self.assertEqual(
            utils.markup_italics(
                "'Gee Whizz' \xd7 ('Fireball' \xd7 (compacta \xd7 "
                "'Purple Star')) \xd7 lilliputiana"
            ),
            "'Gee Whizz' \xd7 ('Fireball' \xd7 (<i>compacta</i> \xd7 "
            "'Purple Star')) \xd7 <i>lilliputiana</i>"
        )
        self.assertEqual(
            utils.markup_italics("carolinae 'Tricolor' \xd7 compacta"),
            "<i>carolinae</i> 'Tricolor' \xd7 <i>compacta</i>"
        )
        self.assertEqual(
            utils.markup_italics('carolinae \xd7 sp. (pink and red)'),
            '<i>carolinae</i> \xd7 sp. (pink and red)'
        )

    def test_markup_complex_hybrid_zws(self):
        self.assertEqual(
            utils.markup_italics(
                "\u200b(carolinae \xd7 'Purple Star') \xd7 (compacta "
                "\xd7 sp.)"
            ),
            "\u200b(<i>carolinae</i> \xd7 'Purple Star') \xd7 "
            "(<i>compacta</i> \xd7 sp.)"
        )
        self.assertEqual(
            utils.markup_italics('\u200bcarolinae \xd7 sp. (pink and red)'),
            '\u200b<i>carolinae</i> \xd7 sp. (pink and red)'
        )

    def test_markup_provisory_hybrid(self):
        self.assertEqual(
            utils.markup_italics(
                'sp. \xd7 sp. (South Molle Island J.P.GrestyAQ208995)'
            ),
            'sp. \xd7 sp. (South Molle Island J.P.GrestyAQ208995)'
        )

    def test_markup_nothospecies_hybrid(self):
        self.assertEqual(
            utils.markup_italics("gymnocarpa \xd7 \xd7grandiflora"),
            '<i>gymnocarpa</i> \xd7 \xd7<i>grandiflora</i>'
        )
        self.assertEqual(
            utils.markup_italics("gymnocarpa \xd7 \xd7 grandiflora"),
            '<i>gymnocarpa</i> \xd7 \xd7 <i>grandiflora</i>'
        )
        # with ZWS
        self.assertEqual(
            utils.markup_italics("\u200b\xd7 grandiflora"),
            '\u200b\xd7 <i>grandiflora</i>'
        )

    def test_markup_junk(self):
        # check junk doesn't crash
        self.assertEqual(
            utils.markup_italics(
                '\ub0aaN\ua001\U00055483\u01d6\u059e/C\U00103e9aG|\U0010eb876'
            ),
            '\ub0aaN\ua001\U00055483\u01d6\u059e/C\U00103e9aG|\U0010eb876'
        )

    def test_markup_complex_hybrid_mismatched_bracket(self):
        # check that mismatch brackets can produce something close to a desired
        # outcome.
        self.assertEqual(
            utils.markup_italics(
                "((carolinae \xd7 'Purple Star') \xd7 (compacta \xd7 sp.)"
            ),
            "((<i>carolinae</i> \xd7 'Purple Star') \xd7 (compacta \xd7 sp.)"
        )
        self.assertEqual(
            utils.markup_italics(
                "(carolinae \xd7 'Purple Star')) \xd7 (lilliputiana \xd7 "
                "compacta \xd7 sp.)"
            ),
            "(<i>carolinae</i> \xd7 'Purple Star')) \xd7 (lilliputiana \xd7 "
            "<i>compacta</i> \xd7 sp.)"
        )
