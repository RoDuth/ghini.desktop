# Copyright (c) 2005,2006,2007,2008,2009 Brett Adams <brett@belizebotanic.org>
# Copyright (c) 2012-2016 Mario Frasca <mario@anche.no>
# Copyright (c) 2018-2021 Ross Demuth <rossdemuth123@gmail.com>
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
from unittest import TestCase, mock
from pathlib import Path
from tempfile import TemporaryDirectory
from sqlalchemy import Table, Column, Integer, ForeignKey, MetaData, Sequence
import requests

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from bauble import paths
from bauble import utils
from bauble import prefs
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
        dlog.destroy()

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
        dlog.destroy()

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

    def test_copy_tree_w_path(self):
        src_dir = Path(paths.lib_dir(), "plugins", "report", 'xsl',
                       'stylesheets')
        dest = TemporaryDirectory()
        dest_dir = Path(dest.name)
        utils.copy_tree(src_dir, dest_dir)
        self.assertEqual(
            [i.relative_to(src_dir) for i in src_dir.glob('**/*.*')],
            [i.relative_to(dest_dir) for i in dest_dir.glob('**/*.*')]
        )
        dest.cleanup()

    def test_copy_tree_w_str(self):
        src_dir = Path(paths.lib_dir(), "plugins", "report", 'xsl',
                       'stylesheets')
        dest = TemporaryDirectory()
        dest_dir = Path(dest.name)
        utils.copy_tree(str(src_dir), str(dest_dir))
        self.assertEqual(
            [i.relative_to(src_dir) for i in src_dir.glob('**/*.*')],
            [i.relative_to(dest_dir) for i in dest_dir.glob('**/*.*')]
        )
        dest.cleanup()

    def test_copy_tree_w_suffixes(self):
        src_dir = Path(paths.lib_dir(), "plugins", "report", 'xsl',
                       'stylesheets')
        dest = TemporaryDirectory()
        dest_dir = Path(dest.name)
        utils.copy_tree(str(src_dir), str(dest_dir), ['.xsl'])
        self.assertEqual(
            [i.relative_to(src_dir) for i in src_dir.glob('**/*.xsl')],
            [i.relative_to(dest_dir) for i in dest_dir.glob('**/*.*')]
        )
        dest.cleanup()

    def test_copy_tree_w_over_write(self):
        import filecmp
        src_dir = Path(paths.lib_dir(), "plugins", "report", 'xsl',
                       'stylesheets')
        dest = TemporaryDirectory()
        dest_dir = Path(dest.name)
        utils.copy_tree(str(src_dir), str(dest_dir), ['.xsl'])
        # make a couple of differences and rerun
        dest_glob = dest_dir.glob('**/*.xsl')
        with open(next(dest_glob), 'w') as f:
            f.write('test')
        os.remove(next(dest_glob))
        os.remove(next(dest_glob))
        utils.copy_tree(str(src_dir), str(dest_dir), ['.xsl'], True)
        self.assertEqual(
            [i.relative_to(src_dir) for i in src_dir.glob('**/*.xsl')],
            [i.relative_to(dest_dir) for i in dest_dir.glob('**/*.*')]
        )
        self.assertTrue(filecmp.cmp(next(src_dir.glob('**/*.xsl')),
                                    next(dest_dir.glob('**/*.xsl'))))
        # make a couple of changes and rerun without overwrite
        dest_glob = dest_dir.glob('**/*.xsl')
        with open(next(dest_glob), 'w') as f:
            f.write('test')
        os.remove(next(dest_glob))
        os.remove(next(dest_glob))
        utils.copy_tree(str(src_dir), str(dest_dir), ['.xsl'])
        self.assertEqual(
            [i.relative_to(src_dir) for i in src_dir.glob('**/*.xsl')],
            [i.relative_to(dest_dir) for i in dest_dir.glob('**/*.*')]
        )
        self.assertFalse(filecmp.cmp(next(src_dir.glob('**/*.xsl')),
                                     next(dest_dir.glob('**/*.xsl'))))
        dest.cleanup()


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

    def setUp(self):
        super().setUp()
        self.metadata = MetaData()
        self.metadata.bind = db.engine

    def tearDown(self):
        super().tearDown()
        self.metadata.drop_all()

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
        self.insert = table.insert()  # .compile()
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


class GlobalFuncsTests(BaubleTestCase):
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

    def test_chunks(self):
        val = 'abcdefghijklmnop'
        for i, out in enumerate(utils.chunks(val, 3)):
            self.assertEqual(val[i * 3: (i + 1) * 3], out)
        val = ['abd', 'def', 'ghi', 'jkl']
        for i, out in enumerate(utils.chunks(val, 2)):
            self.assertEqual(val[i * 2: (i + 1) * 2], out)

    def test_read_in_chunks(self):
        from io import StringIO
        data = 'abcdefghijklmnopqrstuvwxyz'
        mock_file = StringIO(data)
        for i, out in enumerate(utils.read_in_chunks(mock_file, 3)):
            self.assertEqual(data[i * 3: (i + 1) * 3], out)

    def test_copy_picture_with_thumbnail_wo_basename(self):
        import filecmp
        from PIL import Image
        img = Image.new('CMYK', size=(2000, 2000), color=(155, 0, 0))
        temp_source = TemporaryDirectory()
        temp_img_path = str(Path(temp_source.name, 'test.jpg'))
        img.save(temp_img_path, format='JPEG')
        with TemporaryDirectory() as temp_dir:
            thumbs_dir = Path(temp_dir, 'pictures', 'thumbs')
            os.makedirs(thumbs_dir)
            prefs.prefs[prefs.root_directory_pref] = temp_dir
            out = utils.copy_picture_with_thumbnail(temp_img_path)
            filecmp.cmp(temp_img_path,
                        str(Path(temp_dir, 'pictures', 'test.jpg')))
            self.assertIsNotNone(thumbs_dir / 'test.jpg')
        temp_source.cleanup()
        self.assertEqual(len(out), 10464)

    def test_copy_picture_with_thumbnail_w_basename(self):
        import filecmp
        from PIL import Image
        img = Image.new('CMYK', size=(2000, 2000), color=(155, 0, 0))
        temp_source = TemporaryDirectory()
        temp_img_path = str(Path(temp_source.name, 'test.jpg'))
        img.save(temp_img_path, format='JPEG')
        path, basename = os.path.split(temp_img_path)
        with TemporaryDirectory() as temp_dir:
            thumbs_dir = Path(temp_dir, 'pictures', 'thumbs')
            os.makedirs(thumbs_dir)
            prefs.prefs[prefs.root_directory_pref] = temp_dir
            out = utils.copy_picture_with_thumbnail(path, basename)
            filecmp.cmp(temp_img_path,
                        str(Path(temp_dir, 'pictures', 'test.jpg')))
            self.assertIsNotNone(thumbs_dir / 'test.jpg')
        temp_source.cleanup()
        self.assertEqual(len(out), 10464)

    def test_copy_picture_with_thumbnail_w_basename_rename(self):
        import filecmp
        from PIL import Image
        img = Image.new('CMYK', size=(2000, 2000), color=(155, 0, 0))
        temp_source = TemporaryDirectory()
        temp_img_path = str(Path(temp_source.name, 'test.jpg'))
        img.save(temp_img_path, format='JPEG')
        path, basename = os.path.split(temp_img_path)
        rename = 'test123.jpg'
        with TemporaryDirectory() as temp_dir:
            thumbs_dir = Path(temp_dir, 'pictures', 'thumbs')
            os.makedirs(thumbs_dir)
            prefs.prefs[prefs.root_directory_pref] = temp_dir
            out = utils.copy_picture_with_thumbnail(path, basename, rename)
            filecmp.cmp(temp_img_path,
                        str(Path(temp_dir, 'pictures', rename)))
            self.assertIsNotNone(thumbs_dir / rename)
        temp_source.cleanup()
        self.assertEqual(len(out), 10464)

    def test_get_temp_path(self):
        temp_path = utils.get_temp_path()
        # test file is where we expect it
        self.assertTrue(str(temp_path).startswith(paths.TEMPDIR))
        # test file exists
        self.assertTrue(temp_path.exists())
        # test file can be opened
        self.assertTrue(temp_path.open())
        # test we can remove the file
        try:
            temp_path.unlink()
        except Exception as e:
            self.fail(f'exception {e} raised trying to delete the file')
        # test file no longer exists
        self.assertFalse(temp_path.exists())


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


class GetNetSessionTest(BaubleTestCase):
    def test_w_pref_not_dict_returns_requests_session_wo_proxies_(self):
        prefs.prefs[prefs.web_proxy_prefs] = 'use_requests_without_proxies'
        sess = utils.NetSessionFunctor.get_net_sess()
        self.assertIsInstance(sess, requests.Session)
        self.assertFalse(sess.proxies)

    def test_get_net_sess_not_called_twice_wo_pacsession(self):
        prefs.prefs[prefs.web_proxy_prefs] = 'use_requests_without_proxies'
        utils.get_net_sess.net_sess = None
        sess = utils.get_net_sess()
        sess2 = utils.get_net_sess()
        self.assertIsInstance(sess, requests.Session)
        self.assertIsInstance(sess2, requests.Session)
        self.assertFalse(sess.proxies)
        self.assertFalse(sess2.proxies)
        self.assertIs(sess, sess2)

    def test_w_pref_dict_returns_requests_session_w_proxies_(self):
        proxies = {
            "https": "http://10.10.10.10/8000",
            "http": "http://10.10.10.10:8000"
        }
        prefs.prefs[prefs.web_proxy_prefs] = proxies
        sess = utils.NetSessionFunctor.get_net_sess()
        self.assertIsInstance(sess, requests.Session)
        self.assertEqual(sess.proxies, proxies)

    @mock.patch('pypac.PACSession')
    def test_wo_pref_return_pypac_pacsession_if_pac_file(self,
                                                         mock_pacsession):
        del prefs.prefs[prefs.web_proxy_prefs]
        pac_inst = mock_pacsession.return_value
        pac_inst.get_pac.return_value = 'test'
        utils.NetSessionFunctor.get_net_sess()
        mock_pacsession.get_pac.called_once()
        self.assertIsNone(prefs.prefs.get(prefs.web_proxy_prefs))

    @mock.patch('pypac.PACSession')
    def test_wo_pref_return_requests_session_if_no_pac_file(self,
                                                            mock_pacsession):
        del prefs.prefs[prefs.web_proxy_prefs]
        pac_inst = mock_pacsession.return_value
        pac_inst.get_pac.return_value = None
        utils.NetSessionFunctor.get_net_sess()
        mock_pacsession.get_pac.called_once()
        self.assertEqual(prefs.prefs.get(prefs.web_proxy_prefs), 'no_pac_file')

    @mock.patch('pypac.PACSession')
    def test_get_net_sess_not_called_twice_wo_pac_file(self, mock_pacsession):
        del prefs.prefs[prefs.web_proxy_prefs]
        utils.get_net_sess.net_sess = None
        pac_inst = mock_pacsession.return_value
        pac_inst.get_pac.return_value = None
        sess = utils.get_net_sess()
        self.assertEqual(prefs.prefs.get(prefs.web_proxy_prefs), 'no_pac_file')
        sess2 = utils.get_net_sess()
        mock_pacsession.get_pac.called_once()
        self.assertIs(sess, sess2)

    @mock.patch('pypac.PACSession')
    def test_get_net_sess_not_called_twice_w_pac_file(self, mock_pacsession):
        del prefs.prefs[prefs.web_proxy_prefs]
        utils.get_net_sess.net_sess = None
        pac_inst = mock_pacsession.return_value
        pac_inst.get_pac.return_value = 'test'
        sess = utils.get_net_sess()
        self.assertIsNone(prefs.prefs.get(prefs.web_proxy_prefs))
        sess2 = utils.get_net_sess()
        mock_pacsession.get_pac.called_once()
        self.assertIs(sess, sess2)


class TimedCacheTest(TestCase):
    def test_cache_size_one_calls_every_new_param(self):
        mock_func = mock.Mock()
        mock_func.return_value = 'result'
        decorated = utils.timed_cache(size=1)(mock_func)
        # make 2 calls
        result = decorated('test')
        mock_func.assert_called_with('test')
        self.assertEqual(result, 'result')
        mock_func.return_value = 'result2'
        result = decorated('test2')
        mock_func.assert_called_with('test2')
        self.assertEqual(result, 'result2')
        # make the same 2 calls but with different return values
        mock_func.return_value = 'result3'
        result = decorated('test')
        mock_func.assert_called_with('test')
        self.assertEqual(result, 'result3')
        mock_func.return_value = 'result4'
        result = decorated('test2')
        mock_func.assert_called_with('test2')
        self.assertEqual(result, 'result4')

    def test_multipe_identical_calls_do_cache(self):
        mock_func = mock.Mock()
        mock_func.return_value = 'result'
        decorated = utils.timed_cache(size=10)(mock_func)
        result = decorated('test')
        mock_func.assert_called_with('test')
        self.assertEqual(result, 'result')
        for _ in range(10):
            result = decorated('test')
            self.assertEqual(result, 'result')
            self.assertEqual(mock_func.call_count, 1)

    def test_func_calls_when_cache_overflows(self):
        mock_func = mock.Mock()
        mock_func.return_value = 'result'
        decorated = utils.timed_cache(size=10)(mock_func)
        for i in range(10):
            result = decorated(f'test{i}')
            self.assertEqual(result, 'result')
            mock_func.assert_called_with(f'test{i}')

        self.assertEqual(mock_func.call_count, 10)
        start = mock_func.call_count

        # make the same calls and check not called
        for i in range(10):
            mock_func.return_value = f'result{i}'
            result = decorated(f'test{i}')
            self.assertEqual(result, 'result')

        # one more overflows
        mock_func.return_value = 'end'
        result = decorated('end')
        self.assertEqual(result, 'end')

        end = mock_func.call_count
        self.assertEqual(end, start + 1)

    def test_func_calls_again_after_secs(self):
        mock_func = mock.Mock()
        mock_func.return_value = 'result'
        decorated = utils.timed_cache(size=10, secs=0.2)(mock_func)
        # preload cache
        mock_func.return_value = 'result'
        result = decorated('test')
        self.assertEqual(mock_func.call_count, 1)
        self.assertEqual(result, 'result')
        # make some calls and only 1 mock_func call no value change
        for i in range(5):
            mock_func.return_value = f'result{i}'
            result = decorated('test')
            self.assertEqual(mock_func.call_count, 1)
            self.assertEqual(result, 'result')

        from time import sleep
        sleep(0.2)
        # make same call after pause and this time it does call
        mock_func.return_value = 'end'
        result = decorated('test')
        self.assertEqual(mock_func.call_count, 2)
        self.assertEqual(result, 'end')

    def test_set_size(self):
        # set size via param to 1 then via set_size and check for overflow
        mock_func = mock.Mock()
        mock_func.return_value = 'result'
        decorated = utils.timed_cache(size=1, secs=10)(mock_func)
        decorated.set_size(10)

        for i in range(10):
            result = decorated(f'test{i}')
            self.assertEqual(result, 'result')
            mock_func.assert_called_with(f'test{i}')

        for i in range(10):
            result = decorated(f'test{i}')
            self.assertEqual(result, 'result')
            mock_func.assert_called_with('test9')

        self.assertEqual(mock_func.call_count, 10)

        # one extra cal creates once extra call
        mock_func.return_value = 'end'
        result = decorated('end')
        self.assertEqual(result, 'end')
        mock_func.assert_called_with('end')

        self.assertEqual(mock_func.call_count, 11)

    def test_set_secs(self):
        mock_func = mock.Mock()
        mock_func.return_value = 'result'
        decorated = utils.timed_cache(size=10, secs=10.0)(mock_func)
        decorated.set_secs(0.2)
        # preload cache
        mock_func.return_value = 'result'
        result = decorated('test')
        self.assertEqual(mock_func.call_count, 1)
        self.assertEqual(result, 'result')
        # make some calls and only 1 mock_func call no value change
        for i in range(5):
            mock_func.return_value = f'result{i}'
            result = decorated('test')
            self.assertEqual(mock_func.call_count, 1)
            self.assertEqual(result, 'result')

        from time import sleep
        sleep(0.2)
        # make same call after pause and this time it does call
        mock_func.return_value = 'end'
        result = decorated('test')
        self.assertEqual(mock_func.call_count, 2)
        self.assertEqual(result, 'end')

    def test_clear_cache(self):
        mock_func = mock.Mock()
        mock_func.return_value = 'result'
        decorated = utils.timed_cache(size=100, secs=10)(mock_func)
        decorated.set_size(10)

        for i in range(10):
            result = decorated(f'test{i}')
            self.assertEqual(result, 'result')
            mock_func.assert_called_with(f'test{i}')

        for i in range(10):
            result = decorated(f'test{i}')
            self.assertEqual(result, 'result')
            mock_func.assert_called_with('test9')

        self.assertEqual(mock_func.call_count, 10)

        decorated.clear_cache()
        # cache clear does call
        mock_func.return_value = 'end'
        result = decorated('test9')
        self.assertEqual(result, 'end')
        mock_func.assert_called_with('test9')

        self.assertEqual(mock_func.call_count, 11)
