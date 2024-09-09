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
from pathlib import Path
from random import shuffle
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest import mock

import gi
from sqlalchemy import Column
from sqlalchemy import ForeignKey
from sqlalchemy import Integer
from sqlalchemy import MetaData
from sqlalchemy import Table

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from bauble import db
from bauble import paths
from bauble import prefs
from bauble import utils
from bauble.error import CheckConditionError
from bauble.test import BaubleTestCase
from bauble.test import update_gui
from bauble.test import wait_on_threads


class UtilsTest(TestCase):
    def test_topological_sort_total(self):
        self.assertEqual(
            utils.topological_sort([1, 2, 3], [(2, 1), (3, 2)]), [3, 2, 1]
        )

    def test_topological_sort_partial(self):
        self.assertEqual(
            utils.topological_sort([1, 2, 3, 4], [(2, 1)]), [4, 3, 2, 1]
        )

    def test_topological_sort_loop(self):
        self.assertEqual(
            utils.topological_sort([1, 2], [(2, 1), (1, 2)]), None
        )

    def test_topological_empty_dependencies(self):
        # list contain same elements, no dependancies so order doesn't matter
        self.assertCountEqual(
            utils.topological_sort(["a", "b", "c"], []), ["c", "b", "a"]
        )

    def test_topological_full_dependencies(self):
        # list is ordered
        self.assertEqual(
            utils.topological_sort(["a", "b", "c"], [("a", "b"), ("b", "c")]),
            ["a", "b", "c"],
        )

    def test_topological_partial_dependencies(self):
        # 'e' has no dependencies so comes before or after
        self.assertEqual(
            utils.topological_sort(
                ["b", "e"], [("a", "b"), ("b", "c"), ("b", "d")]
            ),
            ["a", "b", "d", "c", "e"],
        )

    def test_topological_empty_input_full_dependencies(self):
        # could return empty
        self.assertEqual(
            utils.topological_sort([], [("a", "b"), ("b", "c"), ("b", "d")]),
            ["a", "b", "d", "c"],
        )

    def test_create_message_details_dialog(self):
        details = "these are the lines that I want to test\n2nd line\n3rd Line"
        msg = "test message"

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
        msg = "test message"
        # msg = ' this is a longer message to test that the dialog width is correct.....but what if it keeps going'
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

        row = model.append(None, ["1"])
        model.append(row, ["1.1"])
        to_find.append(model.append(row, ["something"]))
        model.append(row, ["1.3"])

        row = model.append(None, ["2"])
        to_find.append(model.append(row, ["something"]))
        model.append(row, ["2.1"])

        to_find.append(model.append(None, ["something"]))

        root = model.get_iter_first()
        results = utils.search_tree_model(model[root], "something")
        self.assertTrue(
            sorted([model.get_path(r) for r in results]), sorted(to_find)
        )

    def test_xml_safe(self):
        """
        Test bauble.utils.xml_safe
        """

        class Test:
            def __str__(self):
                return repr(self)

        import re

        self.assertTrue(re.match("&lt;.*?&gt;", utils.xml_safe(str(Test()))))
        self.assertEqual(utils.xml_safe("test string"), "test string")
        self.assertEqual(utils.xml_safe("test string"), "test string")
        self.assertEqual(utils.xml_safe("test< string"), "test&lt; string")
        self.assertEqual(utils.xml_safe("test< string"), "test&lt; string")

    def test_range_builder(self):
        """Test bauble.utils.range_builder"""
        # int
        self.assertEqual(utils.range_builder("1-3"), [1, 2, 3])
        self.assertEqual(utils.range_builder("9-11"), [9, 10, 11])
        self.assertEqual(utils.range_builder("1-3,5-7"), [1, 2, 3, 5, 6, 7])
        self.assertEqual(utils.range_builder("1-3,5"), [1, 2, 3, 5])
        self.assertEqual(
            utils.range_builder("1-3,5,7-9"), [1, 2, 3, 5, 7, 8, 9]
        )
        self.assertEqual(utils.range_builder("1,2,3,4"), [1, 2, 3, 4])
        self.assertEqual(utils.range_builder("11"), [11])

        # alpha
        self.assertEqual(utils.range_builder("a-d"), ["a", "b", "c", "d"])
        self.assertEqual(utils.range_builder("Y-b"), ["Y", "Z", "a", "b"])
        self.assertEqual(
            utils.range_builder("A-C,a-c"), ["A", "B", "C", "a", "b", "c"]
        )
        self.assertEqual(utils.range_builder("a-c,f"), ["a", "b", "c", "f"])
        self.assertEqual(
            utils.range_builder("a-c,f,h-j"),
            ["a", "b", "c", "f", "h", "i", "j"],
        )
        self.assertEqual(utils.range_builder("a,f,h,j"), ["a", "f", "h", "j"])
        self.assertEqual(utils.range_builder("b"), ["b"])
        self.assertEqual(utils.range_builder("ab"), ["ab"])

        # bad range strings
        self.assertEqual(utils.range_builder("-1"), [])
        self.assertRaises(CheckConditionError, utils.range_builder, "2-1")
        self.assertRaises(CheckConditionError, utils.range_builder, "1-1")
        self.assertRaises(CheckConditionError, utils.range_builder, "Z-A")
        self.assertRaises(CheckConditionError, utils.range_builder, "a-A")
        self.assertRaises(ValueError, utils.range_builder, "a-1")
        self.assertRaises(ValueError, utils.range_builder, "1-Z")
        self.assertRaises(ValueError, utils.range_builder, "ab-c")

    def test_get_urls(self):
        text = "There a link in here: http://bauble.belizebotanic.org"
        urls = utils.get_urls(text)
        self.assertEqual(
            urls, [(None, "http://bauble.belizebotanic.org")], urls
        )

        text = (
            "There a link in here: http://bauble.belizebotanic.org "
            "and some text afterwards."
        )
        urls = utils.get_urls(text)
        self.assertEqual(
            urls, [(None, "http://bauble.belizebotanic.org")], urls
        )

        text = (
            "There is a link here: http://bauble.belizebotanic.org and "
            "here: https://belizebotanic.org and some text afterwards."
        )
        urls = utils.get_urls(text)
        self.assertEqual(
            urls,
            [
                (None, "http://bauble.belizebotanic.org"),
                (None, "https://belizebotanic.org"),
            ],
            urls,
        )

        text = (
            "There a labeled link in here: "
            "[BBG]http://bauble.belizebotanic.org and some text after."
        )
        urls = utils.get_urls(text)
        self.assertEqual(
            urls, [("BBG", "http://bauble.belizebotanic.org")], urls
        )

    def test_copy_tree_w_path(self):
        src_dir = Path(
            paths.lib_dir(), "plugins", "report", "xsl", "stylesheets"
        )
        dest = TemporaryDirectory()
        dest_dir = Path(dest.name)
        utils.copy_tree(src_dir, dest_dir)
        self.assertEqual(
            [i.relative_to(src_dir) for i in src_dir.glob("**/*.*")],
            [i.relative_to(dest_dir) for i in dest_dir.glob("**/*.*")],
        )
        dest.cleanup()

    def test_copy_tree_w_str(self):
        src_dir = Path(
            paths.lib_dir(), "plugins", "report", "xsl", "stylesheets"
        )
        dest = TemporaryDirectory()
        dest_dir = Path(dest.name)
        utils.copy_tree(str(src_dir), str(dest_dir))
        self.assertEqual(
            [i.relative_to(src_dir) for i in src_dir.glob("**/*.*")],
            [i.relative_to(dest_dir) for i in dest_dir.glob("**/*.*")],
        )
        dest.cleanup()

    def test_copy_tree_w_suffixes(self):
        src_dir = Path(
            paths.lib_dir(), "plugins", "report", "xsl", "stylesheets"
        )
        dest = TemporaryDirectory()
        dest_dir = Path(dest.name)
        utils.copy_tree(str(src_dir), str(dest_dir), [".xsl"])
        self.assertEqual(
            [i.relative_to(src_dir) for i in src_dir.glob("**/*.xsl")],
            [i.relative_to(dest_dir) for i in dest_dir.glob("**/*.*")],
        )
        dest.cleanup()

    def test_copy_tree_w_over_write(self):
        import filecmp

        src_dir = Path(
            paths.lib_dir(), "plugins", "report", "xsl", "stylesheets"
        )
        dest = TemporaryDirectory()
        dest_dir = Path(dest.name)
        utils.copy_tree(str(src_dir), str(dest_dir), [".xsl"])
        # make a couple of differences and rerun
        dest_glob = dest_dir.glob("**/*.xsl")
        with open(next(dest_glob), "w") as f:
            f.write("test")
        os.remove(next(dest_glob))
        os.remove(next(dest_glob))
        utils.copy_tree(str(src_dir), str(dest_dir), [".xsl"], True)
        self.assertEqual(
            [i.relative_to(src_dir) for i in src_dir.glob("**/*.xsl")],
            [i.relative_to(dest_dir) for i in dest_dir.glob("**/*.*")],
        )
        self.assertTrue(
            filecmp.cmp(
                next(src_dir.glob("**/*.xsl")), next(dest_dir.glob("**/*.xsl"))
            )
        )
        # make a couple of changes and rerun without overwrite
        dest_glob = dest_dir.glob("**/*.xsl")
        with open(next(dest_glob), "w") as f:
            f.write("test")
        os.remove(next(dest_glob))
        os.remove(next(dest_glob))
        utils.copy_tree(str(src_dir), str(dest_dir), [".xsl"])
        self.assertEqual(
            [i.relative_to(src_dir) for i in src_dir.glob("**/*.xsl")],
            [i.relative_to(dest_dir) for i in dest_dir.glob("**/*.*")],
        )
        self.assertFalse(
            filecmp.cmp(
                next(src_dir.glob("**/*.xsl")), next(dest_dir.glob("**/*.xsl"))
            )
        )
        dest.cleanup()

    def test_natsort_key_orders_by_string_of_object(self):
        # also test a large sort
        # Create a large shuffled list of objects
        mock_objs = [mock.MagicMock() for i in range(200)]
        for i, mockobj in enumerate(mock_objs):
            mockobj.__str__.return_value = f"XYZ.{i}"
        # copy list to check they get shuffled
        mock_objs_start = mock_objs.copy()
        shuffle(mock_objs)
        # confirm they are shuffled
        self.assertNotEqual(mock_objs, mock_objs_start)

        mock_objs.sort(key=utils.natsort_key)
        for i in range(200):
            self.assertEqual(
                str(mock_objs[i]).rsplit(".", maxsplit=1)[-1], str(i)
            )

    def test_natsort_key_a_before_z(self):
        # alphabetical
        lst = ["z", "b", "a"]
        self.assertEqual(sorted(lst, key=utils.natsort_key), ["a", "b", "z"])

    def test_natsort_key_0_before_9(self):
        # numerical
        lst = ["9", "0", "3"]
        self.assertEqual(sorted(lst, key=utils.natsort_key), ["0", "3", "9"])

    def test_natsort_key_orders_numbers_first(self):
        lst = ["2X", "X2", "1X"]
        self.assertEqual(
            sorted(lst, key=utils.natsort_key), ["1X", "2X", "X2"]
        )

    def test_natsort_key_10_after_1(self):
        lst = ["10.X", "1.X"]
        self.assertEqual(sorted(lst, key=utils.natsort_key), ["1.X", "10.X"])
        lst = ["X.10", "X.1"]
        self.assertEqual(sorted(lst, key=utils.natsort_key), ["X.1", "X.10"])

    def test_natsort_key_01_before_1(self):
        lst = ["1.X", "01.X"]
        self.assertEqual(sorted(lst, key=utils.natsort_key), ["01.X", "1.X"])
        lst = ["X.1", "X.01"]
        self.assertEqual(sorted(lst, key=utils.natsort_key), ["X.01", "X.1"])

    def test_natsort_key_01_before_x(self):
        lst = ["X", "01"]
        self.assertEqual(sorted(lst, key=utils.natsort_key), ["01", "X"])

    def test_natsort_handles_non_ascii_chars(self):
        # really only to check it doesn't error
        lst = ["ゥ", "ク", "カ", "ァ", "エ"]
        self.assertEqual(
            sorted(lst, key=utils.natsort_key), ["ァ", "ゥ", "エ", "カ", "ク"]
        )
        lst = ["3$", "1络", "2@"]
        self.assertEqual(
            sorted(lst, key=utils.natsort_key), ["1络", "2@", "3$"]
        )
        lst = ["இந்தியா.2", "இந்தியா.3", "இந்தியா.1"]
        self.assertEqual(
            sorted(lst, key=utils.natsort_key),
            ["இந்தியா.1", "இந்தியா.2", "இந்தியா.3"],
        )

    def test_natsort_key_numerically_equivalent_sorts_by_string(self):
        # i.e. string length
        lst = ["001", "01", "00001", "1"]
        self.assertEqual(
            sorted(lst, key=utils.natsort_key), ["00001", "001", "01", "1"]
        )


class UtilsDBTests(BaubleTestCase):
    def test_find_dependent_tables(self):
        """
        Test bauble.utils.find_dependent_tables
        """

        metadata = MetaData()
        metadata.bind = db.engine

        # table1 does't depend on any tables
        table1 = Table(
            "table1", metadata, Column("id", Integer, primary_key=True)
        )

        # table2 depends on table1
        table2 = Table(
            "table2",
            metadata,
            Column("id", Integer, primary_key=True),
            Column("table1", Integer, ForeignKey("table1.id")),
        )

        # table3 depends on table2
        table3 = Table(
            "table3",
            metadata,
            Column("id", Integer, primary_key=True),
            Column("table2", Integer, ForeignKey("table2.id")),
            Column("table4", Integer, ForeignKey("table4.id")),
        )

        # table4 depends on table2
        table4 = Table(
            "table4",
            metadata,
            Column("id", Integer, primary_key=True),
            Column("table2", Integer, ForeignKey("table2.id")),
        )

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


class CacheTests(TestCase):
    def test_create_store_retrieve(self):
        from functools import partial

        from bauble.utils import Cache

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
        from functools import partial

        from bauble.utils import Cache

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
        from functools import partial

        from bauble.utils import Cache

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
        from functools import partial

        from bauble.utils import Cache

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
        table = Table(
            "test_reset_sequence",
            self.metadata,
            Column("id", Integer, primary_key=True),
        )
        self.metadata.create_all()
        self.insert = table.insert()  # .compile()
        db.engine.execute(self.insert, values=[{"id": 1}])
        utils.reset_sequence(table.c.id)

    def test_empty_col_sequence(self):
        """
        Test utils.reset_sequence on a column without a Sequence()

        This only tests that reset_sequence() doesn't fail if there is
        no sequence.
        """

        # test that a column without an explicit sequence works
        table = Table(
            "test_reset_sequence",
            self.metadata,
            Column("id", Integer, primary_key=True),
        )
        self.metadata.create_all()
        # self.insert = table.insert()#.compile()
        # db.engine.execute(self.insert, values=[{'id': 1}])
        utils.reset_sequence(table.c.id)


class GlobalFuncsTests(BaubleTestCase):
    def test_safe_int_valid(self):
        self.assertEqual(utils.safe_int("123"), 123)

    def test_safe_int_valid_not(self):
        self.assertEqual(utils.safe_int("123.2"), 0)

    def test_safe_numeric_valid(self):
        self.assertEqual(utils.safe_numeric("123"), 123)

    def test_safe_numeric_valid_decimal(self):
        self.assertEqual(utils.safe_numeric("123.2"), 123.2)

    def test_safe_numeric_valid_not(self):
        self.assertEqual(utils.safe_numeric("123a.2"), 0)

    def test_xml_safe_name(self):
        self.assertEqual(utils.xml_safe_name("abc"), "abc")
        self.assertEqual(utils.xml_safe_name("a b c"), "a_b_c")
        self.assertEqual(utils.xml_safe_name("{[ab]<c>}"), "abc")
        self.assertEqual(utils.xml_safe_name(""), "_")
        self.assertEqual(utils.xml_safe_name(" "), "_")
        self.assertEqual(utils.xml_safe_name("\u2069\ud8ff"), "_")
        self.assertEqual(utils.xml_safe_name("123"), "_123")
        self.assertEqual(utils.xml_safe_name("<:>"), "_")
        self.assertEqual(utils.xml_safe_name("<picture>"), "picture")

    def test_chunks(self):
        val = "abcdefghijklmnop"
        for i, out in enumerate(utils.chunks(val, 3)):
            self.assertEqual(val[i * 3 : (i + 1) * 3], out)
        val = ["abd", "def", "ghi", "jkl"]
        for i, out in enumerate(utils.chunks(val, 2)):
            self.assertEqual(val[i * 2 : (i + 1) * 2], out)

    def test_read_in_chunks(self):
        from io import StringIO

        data = "abcdefghijklmnopqrstuvwxyz"
        mock_file = StringIO(data)
        for i, out in enumerate(utils.read_in_chunks(mock_file, 3)):
            self.assertEqual(data[i * 3 : (i + 1) * 3], out)

    def test_copy_picture_with_thumbnail_wo_basename(self):
        import filecmp

        from PIL import Image

        img = Image.new("CMYK", size=(2000, 2000), color=(155, 0, 0))
        temp_source = TemporaryDirectory()
        temp_img_path = str(Path(temp_source.name, "test.jpg"))
        img.save(temp_img_path, format="JPEG")
        with TemporaryDirectory() as temp_dir:
            thumbs_dir = Path(temp_dir, "pictures", "thumbs")
            os.makedirs(thumbs_dir)
            prefs.prefs[prefs.root_directory_pref] = temp_dir
            utils.copy_picture_with_thumbnail(temp_img_path)
            filecmp.cmp(
                temp_img_path, str(Path(temp_dir, "pictures", "test.jpg"))
            )
            self.assertTrue((thumbs_dir / "test.jpg").is_file())
        temp_source.cleanup()

    def test_copy_picture_with_thumbnail_w_basename(self):
        import filecmp

        from PIL import Image

        img = Image.new("CMYK", size=(2000, 2000), color=(155, 0, 0))
        temp_source = TemporaryDirectory()
        temp_img_path = str(Path(temp_source.name, "test.jpg"))
        img.save(temp_img_path, format="JPEG")
        path, basename = os.path.split(temp_img_path)
        with TemporaryDirectory() as temp_dir:
            thumbs_dir = Path(temp_dir, "pictures", "thumbs")
            os.makedirs(thumbs_dir)
            prefs.prefs[prefs.root_directory_pref] = temp_dir
            utils.copy_picture_with_thumbnail(path, basename)
            filecmp.cmp(
                temp_img_path, str(Path(temp_dir, "pictures", "test.jpg"))
            )
            self.assertTrue((thumbs_dir / "test.jpg").is_file())
        temp_source.cleanup()

    def test_copy_picture_with_thumbnail_w_basename_rename(self):
        import filecmp

        from PIL import Image

        img = Image.new("CMYK", size=(2000, 2000), color=(155, 0, 0))
        temp_source = TemporaryDirectory()
        temp_img_path = str(Path(temp_source.name, "test.jpg"))
        img.save(temp_img_path, format="JPEG")
        path, basename = os.path.split(temp_img_path)
        rename = "test123.jpg"
        with TemporaryDirectory() as temp_dir:
            thumbs_dir = Path(temp_dir, "pictures", "thumbs")
            os.makedirs(thumbs_dir)
            prefs.prefs[prefs.root_directory_pref] = temp_dir
            utils.copy_picture_with_thumbnail(path, basename, rename)
            filecmp.cmp(temp_img_path, str(Path(temp_dir, "pictures", rename)))
            self.assertTrue((thumbs_dir / rename).is_file())
        temp_source.cleanup()

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
            self.fail(f"exception {e} raised trying to delete the file")
        # test file no longer exists
        self.assertFalse(temp_path.exists())


class TimedCacheTest(TestCase):
    def test_cache_size_one_calls_every_new_param(self):
        mock_func = mock.Mock()
        mock_func.return_value = "result"
        decorated = utils.timed_cache(size=1)(mock_func)
        # make 2 calls
        result = decorated("test")
        mock_func.assert_called_with("test")
        self.assertEqual(result, "result")
        mock_func.return_value = "result2"
        result = decorated("test2")
        mock_func.assert_called_with("test2")
        self.assertEqual(result, "result2")
        # make the same 2 calls but with different return values
        mock_func.return_value = "result3"
        result = decorated("test")
        mock_func.assert_called_with("test")
        self.assertEqual(result, "result3")
        mock_func.return_value = "result4"
        result = decorated("test2")
        mock_func.assert_called_with("test2")
        self.assertEqual(result, "result4")

    def test_multipe_identical_calls_do_cache(self):
        mock_func = mock.Mock()
        mock_func.return_value = "result"
        decorated = utils.timed_cache(size=10)(mock_func)
        result = decorated("test")
        mock_func.assert_called_with("test")
        self.assertEqual(result, "result")
        for _ in range(10):
            result = decorated("test")
            self.assertEqual(result, "result")
            self.assertEqual(mock_func.call_count, 1)

    def test_func_calls_when_cache_overflows(self):
        mock_func = mock.Mock()
        mock_func.return_value = "result"
        decorated = utils.timed_cache(size=10)(mock_func)
        for i in range(10):
            result = decorated(f"test{i}")
            self.assertEqual(result, "result")
            mock_func.assert_called_with(f"test{i}")

        self.assertEqual(mock_func.call_count, 10)
        start = mock_func.call_count

        # make the same calls and check not called
        for i in range(10):
            mock_func.return_value = f"result{i}"
            result = decorated(f"test{i}")
            self.assertEqual(result, "result")

        # one more overflows
        mock_func.return_value = "end"
        result = decorated("end")
        self.assertEqual(result, "end")

        end = mock_func.call_count
        self.assertEqual(end, start + 1)

    def test_func_calls_again_after_secs(self):
        mock_func = mock.Mock()
        mock_func.return_value = "result"
        decorated = utils.timed_cache(size=10, secs=0.2)(mock_func)
        # preload cache
        mock_func.return_value = "result"
        result = decorated("test")
        self.assertEqual(mock_func.call_count, 1)
        self.assertEqual(result, "result")
        # make some calls and only 1 mock_func call no value change
        for i in range(5):
            mock_func.return_value = f"result{i}"
            result = decorated("test")
            self.assertEqual(mock_func.call_count, 1)
            self.assertEqual(result, "result")

        from time import sleep

        sleep(0.2)
        # make same call after pause and this time it does call
        mock_func.return_value = "end"
        result = decorated("test")
        self.assertEqual(mock_func.call_count, 2)
        self.assertEqual(result, "end")

    def test_set_size(self):
        # set size via param to 1 then via set_size and check for overflow
        mock_func = mock.Mock()
        mock_func.return_value = "result"
        decorated = utils.timed_cache(size=1, secs=10)(mock_func)
        decorated.set_size(10)

        for i in range(10):
            result = decorated(f"test{i}")
            self.assertEqual(result, "result")
            mock_func.assert_called_with(f"test{i}")

        for i in range(10):
            result = decorated(f"test{i}")
            self.assertEqual(result, "result")
            mock_func.assert_called_with("test9")

        self.assertEqual(mock_func.call_count, 10)

        # one extra cal creates once extra call
        mock_func.return_value = "end"
        result = decorated("end")
        self.assertEqual(result, "end")
        mock_func.assert_called_with("end")

        self.assertEqual(mock_func.call_count, 11)

    def test_set_secs(self):
        mock_func = mock.Mock()
        mock_func.return_value = "result"
        decorated = utils.timed_cache(size=10, secs=10.0)(mock_func)
        decorated.set_secs(0.2)
        # preload cache
        mock_func.return_value = "result"
        result = decorated("test")
        self.assertEqual(mock_func.call_count, 1)
        self.assertEqual(result, "result")
        # make some calls and only 1 mock_func call no value change
        for i in range(5):
            mock_func.return_value = f"result{i}"
            result = decorated("test")
            self.assertEqual(mock_func.call_count, 1)
            self.assertEqual(result, "result")

        from time import sleep

        sleep(0.2)
        # make same call after pause and this time it does call
        mock_func.return_value = "end"
        result = decorated("test")
        self.assertEqual(mock_func.call_count, 2)
        self.assertEqual(result, "end")

    def test_clear_cache(self):
        mock_func = mock.Mock()
        mock_func.return_value = "result"
        decorated = utils.timed_cache(size=100, secs=10)(mock_func)
        decorated.set_size(10)

        for i in range(10):
            result = decorated(f"test{i}")
            self.assertEqual(result, "result")
            mock_func.assert_called_with(f"test{i}")

        for i in range(10):
            result = decorated(f"test{i}")
            self.assertEqual(result, "result")
            mock_func.assert_called_with("test9")

        self.assertEqual(mock_func.call_count, 10)

        decorated.clear_cache()
        # cache clear does call
        mock_func.return_value = "end"
        result = decorated("test9")
        self.assertEqual(result, "end")
        mock_func.assert_called_with("test9")

        self.assertEqual(mock_func.call_count, 11)


class ImageLoaderTests(BaubleTestCase):
    def setUp(self):
        super().setUp()
        utils.ImageLoader.cache.storage.clear()

    def test_image_loader_local_url(self):
        path = os.path.join(paths.lib_dir(), "images", "bauble_logo.png")
        pic_box = Gtk.Box()
        # needs a window for size-allocate signal
        win = Gtk.Window(title="test_window")
        win.add(pic_box)
        win.show_all()
        mock_size_alloc = mock.Mock()
        mock_size_alloc.return_value = False
        utils.ImageLoader(
            pic_box,
            path,
            on_size_allocated=mock_size_alloc,
        ).start()
        mock_size_alloc.assert_not_called()
        wait_on_threads()
        update_gui()
        image = pic_box.get_children()[0]
        self.assertIsInstance(image, Gtk.Image)
        while not mock_size_alloc.called:
            # WARNING this could deadlock if the signal hanlder doesn't call
            # but is required for the nested idle_add
            update_gui()
        # kind of redundant
        mock_size_alloc.assert_called()
        self.assertIsInstance(mock_size_alloc.call_args.args[0], Gtk.Image)
        win.destroy()

    @mock.patch("bauble.utils.get_net_sess")
    def test_image_loader_global_url(self, mock_get_sess):
        mock_resp = mock.Mock()
        path = Path(paths.lib_dir(), "images", "bauble_logo.png")
        with path.open("rb") as f:
            img = f.read()
        mock_resp.content = img
        mock_get_sess().get.return_value = mock_resp
        pic_box = Gtk.Box()
        # needs a window for size-allocate signal
        win = Gtk.Window(title="test_window")
        win.add(pic_box)
        win.show_all()
        mock_size_alloc = mock.Mock()
        mock_size_alloc.return_value = False
        utils.ImageLoader(
            pic_box,
            "https://test.org",
            on_size_allocated=mock_size_alloc,
        ).start()
        mock_size_alloc.assert_not_called()
        wait_on_threads()
        update_gui()
        self.assertIsInstance(pic_box.get_children()[0], Gtk.Image)
        while not mock_size_alloc.called:
            # WARNING this could deadlock if the signal hanlder doesn't call
            # but is required for the nested idle_add
            update_gui()
        # kind of redundant
        mock_size_alloc.assert_called()
        self.assertIsInstance(mock_size_alloc.call_args.args[0], Gtk.Image)

    @mock.patch("bauble.utils.get_net_sess")
    def test_image_loader_global_url_fails_to_retrieve(self, mock_get_sess):
        # failure to retrieve
        mock_get_sess().get.side_effect = Exception
        pic_box = Gtk.Box()
        # needs a window for size-allocate signal
        win = Gtk.Window(title="test_window")
        win.add(pic_box)
        win.show_all()
        mock_size_alloc = mock.Mock()
        mock_size_alloc.return_value = False
        utils.ImageLoader(
            pic_box,
            "https://test.org",
            on_size_allocated=mock_size_alloc,
        ).start()
        mock_size_alloc.assert_not_called()
        wait_on_threads()
        update_gui()
        self.assertIsInstance(pic_box.get_children()[0], Gtk.Label)
        while not mock_size_alloc.called:
            # WARNING this could deadlock if the signal hanlder doesn't call
            # but is required for the nested idle_add
            update_gui()
        # kind of redundant
        mock_size_alloc.assert_called()
        self.assertIsInstance(mock_size_alloc.call_args.args[0], Gtk.Label)
        win.destroy()

    def test_image_loader_glib_error(self):
        pic_box = Gtk.Box()
        # needs a window for size-allocate signal
        win = Gtk.Window(title="test_window")
        win.add(pic_box)
        win.show_all()
        mock_size_alloc = mock.Mock()
        mock_size_alloc.return_value = False
        utils.ImageLoader(
            pic_box,
            "junk_data",
            on_size_allocated=mock_size_alloc,
        ).start()
        mock_size_alloc.assert_not_called()
        wait_on_threads()
        update_gui()
        self.assertIsInstance(pic_box.get_children()[0], Gtk.Label)
        mock_size_alloc.assert_called()
        self.assertIsInstance(mock_size_alloc.call_args.args[0], Gtk.Label)
        win.destroy()

    def test_image_loader_exception(self):
        # exactly the same test as test_image_loader_local_url except for
        # raising an Exception
        path = os.path.join(paths.lib_dir(), "images", "bauble_logo.png")
        pic_box = Gtk.Box()
        # needs a window for size-allocate signal
        win = Gtk.Window(title="test_window")
        win.add(pic_box)
        win.show_all()
        mock_size_alloc = mock.Mock()
        mock_size_alloc.return_value = False
        img_loader = utils.ImageLoader(
            pic_box,
            path,
            on_size_allocated=mock_size_alloc,
        )
        mock_loader = mock.Mock()
        mock_loader.close.side_effect = Exception
        img_loader.loader = mock_loader
        img_loader.start()
        mock_size_alloc.assert_not_called()
        wait_on_threads()
        update_gui()
        self.assertIsInstance(pic_box.get_children()[0], Gtk.Label)
        mock_size_alloc.assert_called()
        self.assertIsInstance(mock_size_alloc.call_args.args[0], Gtk.Label)
        win.destroy()
