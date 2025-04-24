# Copyright (c) 2005,2006,2007,2008,2009 Brett Adams <brett@belizebotanic.org>
# Copyright (c) 2012-2015 Mario Frasca <mario@anche.no>
# Copyright (c) 2021-2024 Ross Demuth <rossdemuth123@gmail.com>
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
import logging
import os
import sys
from pathlib import Path
from tempfile import mkdtemp
from tempfile import mkstemp
from unittest import mock

logger = logging.getLogger(__name__)

from gi.repository import Gtk

from bauble import prefs
from bauble import version_tuple
from bauble.meta import BaubleMeta
from bauble.test import BaubleTestCase


class PreferencesTests(BaubleTestCase):
    def test_create_does_not_save(self):
        handle, pname = mkstemp(suffix=".dict")
        p = prefs._prefs(pname)
        p.init()
        with open(pname) as f:
            self.assertEqual(f.read(), "")
        os.close(handle)

    def test_assert_initial_values(self):
        handle, pname = mkstemp(suffix=".dict")
        p = prefs._prefs(pname)
        p.init()
        self.assertTrue(prefs.config_version_pref in p)
        self.assertTrue(prefs.root_directory_pref in p)
        self.assertTrue(prefs.date_format_pref in p)
        self.assertTrue(prefs.units_pref in p)
        self.assertEqual(p[prefs.config_version_pref], version_tuple[:2])
        self.assertEqual(p[prefs.root_directory_pref], "")
        self.assertEqual(p[prefs.date_format_pref], "%d-%m-%Y")
        self.assertEqual(p[prefs.time_format_pref], "%I:%M:%S %p")
        self.assertEqual(p[prefs.units_pref], "metric")
        # generated
        self.assertEqual(p[prefs.parse_dayfirst_pref], True)
        self.assertEqual(p[prefs.parse_yearfirst_pref], False)
        self.assertEqual(p[prefs.datetime_format_pref], "%d-%m-%Y %I:%M:%S %p")
        os.close(handle)

    def test_not_saved_while_testing(self):
        prefs.testing = True
        handle, pname = mkstemp(suffix=".dict")
        p = prefs._prefs(pname)
        p.init()
        p.save()
        with open(pname) as f:
            self.assertEqual(f.read(), "")
        os.close(handle)

    def test_can_force_save(self):
        prefs.testing = True
        handle, pname = mkstemp(suffix=".dict")
        p = prefs._prefs(pname)
        p.init()
        p.save(force=True)
        with open(pname) as f:
            self.assertFalse(f.read() == "")
        os.close(handle)

    def test_get_does_not_store_values(self):
        handle, pname = mkstemp(suffix=".dict")
        p = prefs._prefs(pname)
        p.init()
        self.assertFalse("not_there_yet.1" in p)
        self.assertIsNone(p["not_there_yet.1"])
        self.assertEqual(p.get("not_there_yet.2", 33), 33)
        self.assertIsNone(p.get("not_there_yet.3", None))
        self.assertFalse("not_there_yet.1" in p)
        self.assertFalse("not_there_yet.2" in p)
        self.assertFalse("not_there_yet.3" in p)
        self.assertFalse("not_there_yet.4" in p)
        os.close(handle)

    def test_use___setitem___to_store_value_and_create_section(self):
        handle, pname = mkstemp(suffix=".dict")
        p = prefs._prefs(pname)
        p.init()
        self.assertFalse("test.not_there_yet-1" in p)
        p["test.not_there_yet-1"] = "all is a ball"
        self.assertTrue("test.not_there_yet-1" in p)
        self.assertEqual(p["test.not_there_yet-1"], "all is a ball")
        self.assertEqual(p.get("test.not_there_yet-1", 33), "all is a ball")
        os.close(handle)

    def test_most_values_converted_to_string(self):
        handle, pname = mkstemp(suffix=".dict")
        p = prefs._prefs(pname)
        p.init()
        self.assertFalse("test.not_there_yet-1" in p)
        p["test.not_there_yet-1"] = 1
        self.assertTrue("test.not_there_yet-1" in p)
        self.assertEqual(p["test.not_there_yet-1"], 1)
        os.close(handle)

    def test_none_stays_none(self):
        # is this really useful?
        handle, pname = mkstemp(suffix=".dict")
        p = prefs._prefs(pname)
        p.init()
        p["test.not_there_yet-3"] = None
        self.assertEqual(p["test.not_there_yet-3"], None)
        os.close(handle)

    def test_boolean_values_stay_boolean(self):
        handle, pname = mkstemp(suffix=".dict")
        p = prefs._prefs(pname)
        p.init()
        self.assertFalse("test.not_there_yet-1" in p)
        p["test.not_there_yet-1"] = True
        self.assertEqual(p["test.not_there_yet-1"], True)
        p["test.not_there_yet-2"] = False
        self.assertEqual(p["test.not_there_yet-2"], False)
        os.close(handle)

    def test_saved_dictionary_like_ini_file(self):
        handle, pname = mkstemp(suffix=".dict")
        p = prefs._prefs(pname)
        p.init()
        self.assertFalse("test.not_there_yet-1" in p)
        p["test.not_there_yet-1"] = 1
        self.assertTrue("test.not_there_yet-1" in p)
        p.save(force=True)
        with open(pname) as f:
            content = f.read()
            self.assertTrue(content.index("not_there_yet-1 = 1") > 0)
            self.assertTrue(content.index("[test]") > 0)
        os.close(handle)

    def test_generated_dayfirst_yearfirst(self):
        prefs.prefs[prefs.date_format_pref] = "%Y-%m-%d"
        self.assertTrue(prefs.prefs.get(prefs.parse_yearfirst_pref))
        self.assertFalse(prefs.prefs.get(prefs.parse_dayfirst_pref))
        prefs.prefs[prefs.date_format_pref] = "%d-%m-%Y"
        self.assertFalse(prefs.prefs.get(prefs.parse_yearfirst_pref))
        self.assertTrue(prefs.prefs.get(prefs.parse_dayfirst_pref))

    def test_generated_datetime_format(self):
        prefs.prefs[prefs.date_format_pref] = "date"
        prefs.prefs[prefs.time_format_pref] = "time"
        self.assertEqual(
            prefs.prefs.get(prefs.datetime_format_pref), "date time"
        )

    def test_itersection(self):
        for i in range(5):
            prefs.prefs[f"testsection.option{i}"] = f"value{i}"
        for i, (option, value) in enumerate(
            prefs.prefs.itersection("testsection")
        ):
            self.assertEqual(option, f"option{i}")
            self.assertEqual(value, f"value{i}")

    def test__delitem__(self):
        prefs.prefs["testsection.option1"] = "value1"
        prefs.prefs["testsection.option2"] = "value2"
        self.assertTrue(
            prefs.prefs.config.has_option("testsection", "option1")
        )
        self.assertTrue(
            prefs.prefs.config.has_option("testsection", "option2")
        )
        del prefs.prefs["testsection.option2"]
        self.assertFalse(
            prefs.prefs.config.has_option("testsection", "option3")
        )
        self.assertTrue(prefs.prefs.has_section("testsection"))
        del prefs.prefs["testsection.option1"]
        self.assertFalse(prefs.prefs.has_section("testsection"))
        self.assertFalse(prefs.prefs.has_section("nonexistent_section"))
        del prefs.prefs["nonexistent_section.option"]
        self.assertFalse(prefs.prefs.has_section("nonexistent_section"))

    def test_generated_picture_root(self):
        temp_dir = mkdtemp()
        prefs.prefs[prefs.root_directory_pref] = temp_dir
        prefs.prefs[prefs.picture_path_pref] = "ata"
        self.assertEqual(
            prefs.prefs.get(prefs.picture_root_pref),
            os.path.join(temp_dir, "ata"),
        )

    def test_picture_path_change_moves_directory(self):
        temp_dir = mkdtemp()
        prefs.prefs[prefs.root_directory_pref] = temp_dir
        os.makedirs(os.path.join(temp_dir, "pictures", "thumbs"))
        Path(temp_dir, "pictures", "test.jpg").touch()
        Path(temp_dir, "pictures", "thumbs", "test.jpg").touch()
        self.assertTrue(
            os.path.isfile(os.path.join(temp_dir, "pictures", "test.jpg"))
        )
        prefs.prefs[prefs.picture_path_pref] = "Biller"
        self.assertTrue(
            os.path.isfile(os.path.join(temp_dir, "Biller", "test.jpg"))
        )
        self.assertTrue(
            os.path.isdir(os.path.join(temp_dir, "Biller", "thumbs"))
        )

    def test_generated_document_root(self):
        temp_dir = mkdtemp()
        prefs.prefs[prefs.root_directory_pref] = temp_dir
        prefs.prefs[prefs.document_path_pref] = "documentos"
        self.assertEqual(
            prefs.prefs.get(prefs.document_root_pref),
            os.path.join(temp_dir, "documentos"),
        )

    def test_document_path_change_moves_directory(self):
        temp_dir = mkdtemp()
        prefs.prefs[prefs.root_directory_pref] = temp_dir
        os.mkdir(os.path.join(temp_dir, "documents"))
        Path(temp_dir, "documents", "test.txt").touch()
        self.assertTrue(
            os.path.isfile(os.path.join(temp_dir, "documents", "test.txt"))
        )
        prefs.prefs[prefs.document_path_pref] = "documentos"
        self.assertTrue(
            os.path.isfile(os.path.join(temp_dir, "documentos", "test.txt"))
        )

    def test_global_root_returns_as_pref_if_pref_not_set(self):
        temp_dir = mkdtemp()
        self.session.add(BaubleMeta(name="root_directory", value=temp_dir))
        self.session.add(BaubleMeta(name="documents_path", value="tuhinga"))
        self.session.add(BaubleMeta(name="pictures_path", value="фотографії"))
        self.session.commit()
        del prefs.prefs[prefs.root_directory_pref]
        self.assertEqual(prefs.prefs[prefs.root_directory_pref], temp_dir)
        self.assertEqual(
            prefs.prefs[prefs.document_root_pref],
            os.path.join(temp_dir, "tuhinga"),
        )
        self.assertEqual(
            prefs.prefs[prefs.picture_root_pref],
            os.path.join(temp_dir, "фотографії"),
        )

    def test_init_corrupt_file_creates_a_copy(self):
        handle, pname = mkstemp()
        os.close(handle)
        glob = str(Path(pname).name + "*")
        # create junk data
        with open(pname, "w", encoding="utf-8") as f:
            f.writelines(["kjdsfiuoewndfaj", "[[]]hh[sad]", "1234*&^%$BSJDKH"])
        self.assertEqual(len(list(Path(pname).parent.glob(glob))), 1)
        p = prefs._prefs(pname)
        p.init()
        # NOTE includes lock file if not windows (always config, +PREV, +CRPT+)
        file_count = 3 if sys.platform == "win32" else 4
        self.assertEqual(len(list(Path(pname).parent.glob(glob))), file_count)

    def test_init_corrupt_file_overwrites(self):
        handle, pname = mkstemp()
        os.close(handle)
        name = str(Path(pname).name)
        # create junk data
        junk_lines = ["kjdsfiuoewndfaj\n", "[[]]hh[sad]\n", "1234*&^%$BSJH\n"]
        with open(pname, "w", encoding="utf-8") as f:
            f.writelines(junk_lines)
        p = prefs._prefs(pname)
        p.init()
        # NOTE includes lock file if not windows (always config, +PREV, +CRPT+)
        file_count = 3 if sys.platform == "win32" else 4
        self.assertEqual(
            len(list(Path(pname).parent.glob(name + "*"))), file_count
        )
        corrupt = list(Path(pname).parent.glob(name + "CRPT*"))[0]
        with corrupt.open("r", encoding="utf-8") as f:
            lines = f.readlines()
        self.assertEqual(len(lines), 3)
        self.assertListEqual(lines, junk_lines)

        p.save(force=True)
        with Path(pname).open("r", encoding="utf-8") as f:
            lines = f.readlines()

        self.assertGreater(len(lines), 3)
        for line in (
            prefs.root_directory_pref.rsplit(".", 1)[1] + " = \n",
            prefs.date_format_pref.rsplit(".", 1)[1] + " = %d-%m-%Y\n",
            prefs.time_format_pref.rsplit(".", 1)[1] + " = %I:%M:%S %p\n",
            prefs.units_pref.rsplit(".", 1)[1] + " = metric\n",
            prefs.debug_logging_prefs.rsplit(".", 1)[1] + " = ['bauble']\n",
        ):
            self.assertIn(line, lines)

        for line in junk_lines:
            self.assertNotIn(line, lines)

        # just to be certain we have overwritten
        for line in lines:
            self.assertNotIn(line, junk_lines)


class GlobalFunctionsTests(BaubleTestCase):
    @mock.patch("bauble.utils.create_message_dialog")
    def test_set_global_root_creates_directories(self, mock_create):
        temp_dir = mkdtemp()
        prefs.prefs[prefs.root_directory_pref] = temp_dir
        mock_dialog = mock.Mock()
        mock_dialog.run.return_value = Gtk.ResponseType.OK
        mock_create.return_value = mock_dialog
        prefs.set_global_root()
        mock_dialog.run.assert_called()
        mock_create.assert_called()
        self.assertTrue(os.path.isdir(os.path.join(temp_dir, "pictures")))
        self.assertTrue(
            os.path.isdir(os.path.join(temp_dir, "pictures", "thumbs"))
        )
        self.assertTrue(os.path.isdir(os.path.join(temp_dir, "documents")))
