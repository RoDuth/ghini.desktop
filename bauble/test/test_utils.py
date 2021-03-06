# -*- coding: utf-8 -*-
#
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

import bauble.utils as utils
from unittest import TestCase


class Utils(TestCase):

    def test_topological_sort_total(self):
        self.assertEqual(utils.topological_sort([1,2,3], [(2,1), (3,2)]), [3, 2, 1])

    def test_topological_sort_partial(self):
        self.assertEqual(utils.topological_sort([1,2,3,4], [(2,1)]), [4, 3, 2, 1])

    def test_topological_sort_loop(self):
        self.assertEqual(utils.topological_sort([1,2], [(2,1), (1,2)]), None)


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
        self.assertEquals(v, 1)
        self.assertEquals(invoked, [1])
        v = cache.get(1, partial(getter, 1))
        self.assertEquals(v, 1)
        self.assertEquals(invoked, [1])

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
        self.assertEquals(invoked, [1, 2, 3, 4])
        self.assertEquals(sorted(cache.storage.keys()), [3, 4])

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
        self.assertEquals(invoked, [1, 2, 3, 4])
        self.assertEquals(sorted(cache.storage.keys()), [1, 4])

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
        self.assertEquals(invoked, [1, 1, 1])
        self.assertEquals(sorted(cache.storage.keys()), [1, 4])


class GlobalFuncs(TestCase):
    def test_safe_int_valid(self):
        self.assertEquals(utils.safe_int('123'), 123)

    def test_safe_int_valid_not(self):
        self.assertEquals(utils.safe_int('123.2'), 0)

    def test_safe_numeric_valid(self):
        self.assertEquals(utils.safe_numeric('123'), 123)

    def test_safe_numeric_valid_decimal(self):
        self.assertEquals(utils.safe_numeric('123.2'), 123.2)

    def test_safe_numeric_valid_not(self):
        self.assertEquals(utils.safe_numeric('123a.2'), 0)

    def test_xml_safe_name(self):
        self.assertEqual(utils.xml_safe_name('abc'), 'abc')
        self.assertEqual(utils.xml_safe_name('a b c'), 'a_b_c')
        self.assertEqual(utils.xml_safe_name('{[ab]<c>}'), 'abc')
        self.assertEqual(utils.xml_safe_name(''), '_')
        self.assertEqual(utils.xml_safe_name(' '), '_')
        self.assertEqual(utils.xml_safe_name(u'\u2069\ud8ff'), '_')
        self.assertEqual(utils.xml_safe_name('123'), '_123')
        self.assertEqual(utils.xml_safe_name('<:>'), '_')
        self.assertEqual(utils.xml_safe_name('<picture>'), 'picture')

    def test_markup_italics(self):
        self.assertEqual(utils.markup_italics('sp.'), u'sp.')
        self.assertEqual(
            utils.markup_italics('viminalis'), u'<i>viminalis</i>'
        )
        self.assertEqual(
            utils.markup_italics('crista-galli'),
            u'<i>crista-galli</i>'
        )
        self.assertEqual(
            utils.markup_italics(
                u"lilliputiana \xd7 compacta \xd7 ampullacea"
            ),
            u'<i>lilliputiana</i> \xd7 <i>compacta</i> \xd7 <i>ampullacea</i>'
        )
        self.assertEqual(
            utils.markup_italics('sp. (Shute Harbour L.J.Webb+ 7916)'),
            u'sp. (Shute Harbour L.J.Webb+ 7916)'
        )
        self.assertEqual(
            utils.markup_italics('caerulea (Shute Harbour)'),
            u'<i>caerulea</i> (Shute Harbour)'
        )
        self.assertEqual(
            utils.markup_italics(
                u"(carolinae \xd7 'Purple Star') \xd7 (compacta \xd7 sp.)"
            ),
            u"(<i>carolinae</i> \xd7 'Purple Star') \xd7 (<i>compacta</i> "
            U"\xd7 sp.)"
        )
        self.assertEqual(
            utils.markup_italics(
                u"(('Gee Whizz' \xd7 'Fireball' \xd7 compacta) \xd7 "
                u"'Purple Star') \xd7 lilliputiana"
            ),
            u"(('Gee Whizz' \xd7 'Fireball' \xd7 <i>compacta</i>) \xd7 "
            u"'Purple Star') \xd7 <i>lilliputiana</i>"
        )
        self.assertEqual(
            utils.markup_italics(
                u"'Gee Whizz' \xd7 ('Fireball' \xd7 (compacta \xd7 "
                u"'Purple Star')) \xd7 lilliputiana"
            ),
            u"'Gee Whizz' \xd7 ('Fireball' \xd7 (<i>compacta</i> \xd7 "
            u"'Purple Star')) \xd7 <i>lilliputiana</i>"
        )
        self.assertEqual(
            utils.markup_italics(u"carolinae \xd7 'Hot Wizz'"),
            u"<i>carolinae</i> \xd7 'Hot Wizz'"
        )
        self.assertEqual(
            utils.markup_italics(
                u'sp. \xd7 sp. (South Molle Island J.P.GrestyAQ208995)'
            ),
            u'sp. \xd7 sp. (South Molle Island J.P.GrestyAQ208995)'
        )
        self.assertEqual(
            utils.markup_italics(u"carolinae 'Tricolor' \xd7 compacta"),
            u"<i>carolinae</i> 'Tricolor' \xd7 <i>compacta</i>"
        )
        self.assertEqual(
            utils.markup_italics(u'carolinae \xd7 sp. (pink and red)'),
            u'<i>carolinae</i> \xd7 sp. (pink and red)'
        )
        self.assertEqual(
            utils.markup_italics(u"gymnocarpa \xd7 \xd7grandiflora"),
            u'<i>gymnocarpa</i> \xd7 \xd7<i>grandiflora</i>'
        )
        self.assertEqual(
            utils.markup_italics(u"gymnocarpa \xd7 \xd7 grandiflora"),
            u'<i>gymnocarpa</i> \xd7 \xd7 <i>grandiflora</i>'
        )
        self.assertEqual(
            utils.markup_italics(
                u"wilsonii subsp. cryptophlebium \xd7 wilsonii subsp. wilsonii"
            ),
            u'<i>wilsonii</i> subsp. <i>cryptophlebium</i> \xd7 '
            u'<i>wilsonii</i> subsp. <i>wilsonii</i>'
        )
        self.assertEqual(
            utils.markup_italics(u"\xd7 grandiflora"),
            u'\xd7 <i>grandiflora</i>'
        )
        self.assertEqual(
            utils.markup_italics(u"\xd7grandiflora"),
            u'\xd7<i>grandiflora</i>'
        )
        self.assertEqual(
            utils.markup_italics(u'\u200bviminalis'),
            u'\u200b<i>viminalis</i>'
        )
        self.assertEqual(
            utils.markup_italics(
                u"\u200b(carolinae \xd7 'Purple Star') \xd7 (compacta "
                u"\xd7 sp.)"
            ),
            u"\u200b(<i>carolinae</i> \xd7 'Purple Star') \xd7 "
            u"(<i>compacta</i> \xd7 sp.)"
        )
        self.assertEqual(
            utils.markup_italics(u'\u200bcarolinae \xd7 sp. (pink and red)'),
            u'\u200b<i>carolinae</i> \xd7 sp. (pink and red)'
        )
        self.assertEqual(
            utils.markup_italics(
                u"\u200bwilsonii subsp. cryptophlebium \xd7 wilsonii subsp. "
                u"wilsonii"
            ),
            u'\u200b<i>wilsonii</i> subsp. <i>cryptophlebium</i> \xd7 '
            u'<i>wilsonii</i> subsp. <i>wilsonii</i>'
        )
        self.assertEqual(
            utils.markup_italics(u"\u200b\xd7 grandiflora"),
            u'\u200b\xd7 <i>grandiflora</i>'
        )
        # check tht junk doesn't crash it
        self.assertEqual(
            utils.markup_italics(
                u'\ub0aaN\ua001\U00055483\u01d6\u059e/C\U00103e9aG|\U0010eb876'
            ),
            u'\ub0aaN\ua001\U00055483\u01d6\u059e/C\U00103e9aG|\U0010eb876'
        )
        # check that mismatch brackets can produce something close to a desired
        # outcome.
        self.assertEqual(
            utils.markup_italics(
                u"((carolinae \xd7 'Purple Star') \xd7 (compacta \xd7 sp.)"
            ),
            u"((<i>carolinae</i> \xd7 'Purple Star') \xd7 (compacta \xd7 sp.)"
        )
        self.assertEqual(
            utils.markup_italics(
                u"(carolinae \xd7 'Purple Star')) \xd7 (lilliputiana \xd7 "
                u"compacta \xd7 sp.)"
            ),
            u"(<i>carolinae</i> \xd7 'Purple Star')) \xd7 (lilliputiana \xd7 "
            u"<i>compacta</i> \xd7 sp.)"
        )
