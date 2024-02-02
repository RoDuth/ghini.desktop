# Copyright (c) 2021-2022 Ross Demuth <rossdemuth123@gmail.com>
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
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from gi.repository import Gtk
from lxml import etree

from bauble import paths
from bauble import prefs
from bauble.error import BaubleError
from bauble.plugins.garden import test_garden as garden_test
from bauble.plugins.garden.accession import Accession
from bauble.plugins.plants import test_plants as plants_test
from bauble.plugins.plants.species import Species
from bauble.test import BaubleTestCase

from . import ACCESSION_SOURCE_TYPE
from . import DEFAULT_SOURCE_TYPE
from . import FORMATS
from . import PLANT_SOURCE_TYPE
from . import SOURCE_TYPES
from . import SPECIES_SOURCE_TYPE
from . import SettingsBox
from . import XSLFormatterPlugin
from . import XSLFormatterSettingsBox
from . import _fop
from . import create_abcd_xml


class XSLTestCase(BaubleTestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        super().setUp()
        plants_test.setUp_data()
        garden_test.setUp_data()
        # create data with 4 species (1 has no accessions), 3 accessions (1
        # private), 3 plants

    def tearDown(self):
        self.temp_dir.cleanup()
        super().tearDown()

    def test_settings_box(self):
        pass


class XSLFormatterSettingsBoxTests(XSLTestCase):
    def setUp(self):
        super().setUp()
        self.settings_box = XSLFormatterSettingsBox()

    @mock.patch("bauble.utils.Gtk.FileChooserNative")
    def test_on_btnbrowse_clicked_no_previous_entry(self, mock_fcn):
        # only need to reset the widget if caching in BuilderLoader
        # self.settings_box.widgets.file_entry.set_text('')
        mock_fcn.new.return_value = mock_fcn
        mock_fcn.run.return_value = Gtk.ResponseType.ACCEPT
        selected_file = paths.templates_dir() + "/xsl/test.xsl"
        mock_fcn.get_filename.return_value = selected_file

        self.settings_box.on_btnbrowse_clicked(None)

        mock_fcn.new.assert_called_with(
            _("Select a stylesheet"), None, Gtk.FileChooserAction.OPEN
        )
        # if this fails then selected_file is also wrong
        mock_fcn.set_current_folder.assert_called_with(paths.templates_dir())

        self.assertEqual(
            self.settings_box.widgets.file_entry.get_text(), selected_file
        )

    @mock.patch("bauble.utils.Gtk.FileChooserNative")
    def test_on_btnbrowse_clicked_w_previous_entry(self, mock_fcn):
        dummy_dir = "/some/stylesheet/dir"
        dummy_stylesheet = dummy_dir + "/file.xsl"
        self.settings_box.widgets.file_entry.set_text(dummy_stylesheet)
        mock_fcn.new.return_value = mock_fcn
        mock_fcn.run.return_value = Gtk.ResponseType.ACCEPT
        mock_fcn.get_filename.return_value = dummy_stylesheet

        self.settings_box.on_btnbrowse_clicked(None)

        mock_fcn.new.assert_called_with(
            _("Select a stylesheet"), None, Gtk.FileChooserAction.OPEN
        )

        mock_fcn.set_current_folder.assert_called_with(dummy_dir)

        self.assertEqual(
            self.settings_box.widgets.file_entry.get_text(), dummy_stylesheet
        )

    @mock.patch("bauble.utils.Gtk.FileChooserNative")
    def test_on_out_btnbrowse_clicked_no_previous_entry(self, mock_fcn):
        mock_fcn.new.return_value = mock_fcn
        mock_fcn.run.return_value = Gtk.ResponseType.ACCEPT
        selected_file = paths.templates_dir() + "/test.pdf"
        mock_fcn.get_filename.return_value = selected_file

        self.settings_box.on_out_btnbrowse_clicked(None)

        mock_fcn.new.assert_called_with(
            _("Save to file"), None, Gtk.FileChooserAction.SAVE
        )
        # if this fails then selected_file is also wrong
        mock_fcn.set_current_folder.assert_called_with(str(Path.home()))

        self.assertEqual(
            self.settings_box.widgets.outfile_entry.get_text(), selected_file
        )

    @mock.patch("bauble.utils.Gtk.FileChooserNative")
    def test_on_out_btnbrowse_clicked_w_previous_entry(self, mock_fcn):
        dummy_dir = "/some/reports/dir"
        dummy_report = dummy_dir + "/file.pdf"
        self.settings_box.widgets.outfile_entry.set_text(dummy_report)
        mock_fcn.new.return_value = mock_fcn
        mock_fcn.run.return_value = Gtk.ResponseType.ACCEPT
        mock_fcn.get_filename.return_value = dummy_report

        self.settings_box.on_out_btnbrowse_clicked(None)

        mock_fcn.new.assert_called_with(
            _("Save to file"), None, Gtk.FileChooserAction.SAVE
        )

        mock_fcn.set_current_folder.assert_called_with(dummy_dir)

        self.assertEqual(
            self.settings_box.widgets.outfile_entry.get_text(), dummy_report
        )

    def test_get_report_settings_defaults(self):
        # a template should be set
        dummy_dir = "/some/stylesheet/dir"
        dummy_stylesheet = dummy_dir + "/file.xsl"
        self.settings_box.widgets.file_entry.set_text(dummy_stylesheet)
        settings = self.settings_box.get_report_settings()
        self.assertEqual(
            settings,
            {
                "authors": False,
                "out_file": "",
                "out_format": "PDF",
                "private": False,
                "source_type": PLANT_SOURCE_TYPE,
                "stylesheet": dummy_stylesheet,
            },
        )

    def test_get_report_settings_wo_stylesheet(self):
        settings = self.settings_box.get_report_settings()
        self.assertEqual(settings, {})

    @mock.patch("bauble.plugins.report.xsl.Path.is_file")
    def test_on_file_entry_changed_is_file(self, mock_is_file):
        mock_is_file.return_value = True
        mock_widget = mock.Mock()
        mock_widget.get_text.return_value = "test/file.xsl"
        self.settings_box.on_file_entry_changed(mock_widget)
        mock_widget.get_style_context().remove_class.assert_called_with(
            "problem"
        )

    @mock.patch("bauble.plugins.report.xsl.Path.is_file")
    def test_on_file_entry_changed_is_not_file(self, mock_is_file):
        mock_is_file.return_value = False
        mock_widget = mock.Mock()
        mock_widget.get_text.return_value = "test/file.xsl"
        self.settings_box.on_file_entry_changed(mock_widget)
        mock_widget.get_style_context().add_class.assert_called_with("problem")

    def test_get_report_settings_w_values(self):
        # a template should be set
        dummy_dir = "/some/stylesheet/dir"
        dummy_stylesheet = dummy_dir + "/file.xsl"
        self.settings_box.widgets.file_entry.set_text(dummy_stylesheet)

        source_type = SOURCE_TYPES.index(ACCESSION_SOURCE_TYPE)
        self.settings_box.widgets.source_type_combo.set_active(source_type)
        self.settings_box.widgets.author_check.set_active(True)
        self.settings_box.widgets.private_check.set_active(True)
        out_format = list(FORMATS).index("XSL-FO")
        self.settings_box.widgets.format_combo.set_active(out_format)
        dummy_dir = "/some/reports/dir"
        dummy_report = dummy_dir + "/file.fo"
        self.settings_box.widgets.outfile_entry.set_text(dummy_report)
        settings = self.settings_box.get_report_settings()
        self.assertEqual(
            settings,
            {
                "authors": True,
                "out_file": dummy_report,
                "out_format": "XSL-FO",
                "private": True,
                "source_type": ACCESSION_SOURCE_TYPE,
                "stylesheet": dummy_stylesheet,
            },
        )

    @mock.patch("bauble.plugins.report.xsl.Path.exists", return_value=True)
    def test_update_w_full_settings(self, _mock_exists):
        # a template should be set
        dummy_dir = "/some/stylesheet/dir"
        dummy_stylesheet = dummy_dir + "/file.xsl"
        dummy_dir = "/some/reports/dir"
        dummy_report = dummy_dir + "/file.fo"
        settings = {
            "authors": True,
            "out_file": dummy_report,
            "out_format": "XSL-FO",
            "private": True,
            "source_type": ACCESSION_SOURCE_TYPE,
            "stylesheet": dummy_stylesheet,
        }
        self.settings_box.update(settings)

        self.assertEqual(
            self.settings_box.widgets.author_check.get_active(),
            settings.get("authors"),
        )
        self.assertEqual(
            self.settings_box.widgets.outfile_entry.get_text(),
            settings.get("out_file"),
        )
        self.assertEqual(
            self.settings_box.widgets.format_combo.get_active_text(),
            settings.get("out_format"),
        )
        self.assertEqual(
            self.settings_box.widgets.private_check.get_active(),
            settings.get("private"),
        )
        self.assertEqual(
            self.settings_box.widgets.source_type_combo.get_active_text(),
            settings.get("source_type"),
        )
        self.assertEqual(
            self.settings_box.widgets.file_entry.get_text(),
            settings.get("stylesheet"),
        )
        self.assertTrue(
            self.settings_box.widgets.options_expander.get_expanded()
        )

    # this mock should have no affect but is included incase.
    @mock.patch("bauble.plugins.report.xsl.Path.exists", return_value=True)
    def test_update_wo_settings(self, _mock_exists):
        self.settings_box.update({})

        self.assertEqual(
            self.settings_box.widgets.author_check.get_active(), False
        )
        self.assertEqual(
            self.settings_box.widgets.outfile_entry.get_text(), ""
        )
        self.assertEqual(
            self.settings_box.widgets.format_combo.get_active_text(), "PDF"
        )
        self.assertEqual(
            self.settings_box.widgets.private_check.get_active(), False
        )
        self.assertEqual(
            self.settings_box.widgets.source_type_combo.get_active_text(),
            DEFAULT_SOURCE_TYPE,
        )
        self.assertEqual(self.settings_box.widgets.file_entry.get_text(), "")
        self.assertFalse(
            self.settings_box.widgets.options_expander.get_expanded()
        )


class XSLFormatterPluginTests(XSLTestCase):
    FOP_PATH = "test/fop"
    if sys.platform == "win32":
        FOP_PATH = "test/fop.bat"

    def setUp(self):
        super().setUp()
        from bauble import prefs

        self.formatter = XSLFormatterPlugin()

    def test_get_settings_box_returns_settings_box(self):
        # redundant?
        self.assertIsInstance(self.formatter.get_settings_box(), SettingsBox)
        self.assertIsInstance(
            self.formatter.get_settings_box(), XSLFormatterSettingsBox
        )

    @mock.patch("bauble.utils.message_dialog")
    def test_format_no_stylesheet_notifies(self, mock_dialog):
        # NOTE this will not get to open the file step becuase fop is not run
        # and hence no file is created
        objs = self.session.query(Species).all()
        # create the file so format finishes
        settings = {
            "authors": False,
            "out_file": "",
            "out_format": "PDF",
            "private": False,
            "source_type": DEFAULT_SOURCE_TYPE,
            "stylesheet": "",
        }
        self.formatter.format(objs, **settings)
        self.assertEqual(
            mock_dialog.call_args.args[0], "Please select a stylesheet."
        )

    @mock.patch("bauble.plugins.report.xsl._fop.set_fop_command")
    @mock.patch("bauble.utils.message_dialog")
    def test_format_min_settings_no_fop_notifies(
        self, mock_dialog, mock_set_fop
    ):
        # NOTE this will not get to open the file step becuase fop is not run
        # and hence no file is created
        mock_set_fop.return_value = False
        _fop.fop = None
        objs = self.session.query(Species).all()
        dummy_stylesheet = self.temp_dir.name + "/file.xsl"
        # create the file so format finishes
        settings = {
            "authors": False,
            "out_file": "",
            "out_format": "PDF",
            "private": False,
            "source_type": DEFAULT_SOURCE_TYPE,
            "stylesheet": dummy_stylesheet,
        }
        self.formatter.format(objs, **settings)
        self.assertIn(
            "Could not find Apache FOP", mock_dialog.call_args.args[0]
        )

    @mock.patch("bauble.plugins.report.xsl._fop.set_fop_command")
    @mock.patch("bauble.plugins.report.xsl.subprocess.run")
    @mock.patch("bauble.utils.message_dialog")
    def test_format_min_settings_no_fop_output_notifies(
        self, mock_dialog, mock_run, mock_set_fop
    ):
        mock_set_fop.return_value = True
        _fop.fop = self.FOP_PATH
        # NOTE this will not get to open the file step becuase fop is not run
        # and hence no file is created
        objs = self.session.query(Species).all()
        dummy_stylesheet = self.temp_dir.name + "/file.xsl"
        # create the file so format finishes
        settings = {
            "authors": False,
            "out_file": "",
            "out_format": "PDF",
            "private": False,
            "source_type": DEFAULT_SOURCE_TYPE,
            "stylesheet": dummy_stylesheet,
        }
        self.formatter.format(objs, **settings)
        run_args = mock_run.call_args
        self.assertEqual(run_args.args[0][0], self.FOP_PATH)
        self.assertEqual(run_args.args[0][1], "-xml")
        self.assertEqual(run_args.args[0][3], "-xsl")
        self.assertEqual(run_args.args[0][4], dummy_stylesheet)
        self.assertEqual(run_args.args[0][5], "-pdf")
        self.assertIsNotNone(run_args.args[0][6])
        self.assertIn("Error creating the file", mock_dialog.call_args.args[0])

    @mock.patch("bauble.plugins.report.xsl._fop.set_fop_command")
    @mock.patch("bauble.plugins.report.xsl.subprocess.run")
    @mock.patch("bauble.utils.desktop.open")
    def test_format_full_settings_fake_fop_runs(
        self, mock_open, mock_run, mock_set_fop
    ):
        mock_set_fop.return_value = True
        _fop.fop = self.FOP_PATH
        objs = self.session.query(Species).all()
        dummy_stylesheet = self.temp_dir.name + "/file.xsl"
        dummy_report = self.temp_dir.name + "/file.fo"
        # create the file so format finishes (fake fop succeeds)
        Path(dummy_report).touch()
        settings = {
            "authors": True,
            "out_file": dummy_report,
            "out_format": "XSL-FO",
            "private": True,
            "source_type": ACCESSION_SOURCE_TYPE,
            "stylesheet": dummy_stylesheet,
        }
        self.formatter.format(objs, **settings)
        run_args = mock_run.call_args
        self.assertEqual(str(mock_open.call_args.args[0]), self.temp_dir.name)
        self.assertEqual(run_args.args[0][0], self.FOP_PATH)
        self.assertEqual(run_args.args[0][1], "-xml")
        self.assertEqual(run_args.args[0][3], "-xsl")
        self.assertEqual(run_args.args[0][4], dummy_stylesheet)
        self.assertEqual(run_args.args[0][5], "-foout")
        self.assertEqual(run_args.args[0][6], dummy_report)


class FOPTests(XSLTestCase):
    command = "test/command"

    @mock.patch("bauble.plugins.report.xsl.utils.which")
    def test_set_fop_command_java_fop_exist(self, mock_which):
        mock_which.return_value = self.command
        self.assertTrue(_fop.set_fop_command())
        self.assertEqual(_fop.fop, self.command)
        self.assertEqual(_fop.java, self.command)

    @mock.patch("bauble.plugins.report.xsl.utils.which")
    def test_set_fop_command_java_fop_dont_exist(self, mock_which):
        mock_which.return_value = None
        self.assertFalse(_fop.set_fop_command())
        self.assertIsNone(_fop.fop)
        self.assertIsNone(_fop.java)

    @mock.patch("bauble.plugins.report.xsl.utils.which")
    def test_set_fop_command_java_doesnt_exist_fop_exist(self, mock_which):
        def which_side_effect(cmd, path):
            if cmd.startswith("java"):
                return None
            return self.command

        mock_which.side_effect = which_side_effect
        self.assertFalse(_fop.set_fop_command())
        self.assertEqual(_fop.fop, self.command)
        self.assertIsNone(_fop.java)

    @mock.patch("bauble.plugins.report.xsl.utils.which")
    def test_set_fop_command_java_exist_fop_doesnt_exist(self, mock_which):
        def which_side_effect(cmd, path):
            if cmd.startswith("fop"):
                return None
            return self.command

        mock_which.side_effect = which_side_effect
        self.assertFalse(_fop.set_fop_command())
        self.assertIsNone(_fop.fop)
        self.assertEqual(_fop.java, self.command)

    @mock.patch.dict(os.environ, PATH="test_path")
    @mock.patch("bauble.plugins.report.xsl.utils.which")
    def test_set_fop_command_java_path_fop_cmd_java_cmd(self, mock_which):
        mock_which.return_value = self.command
        path = [
            str(Path(paths.root_dir()) / "jre/bin"),
            str(Path(paths.root_dir()) / "fop/fop"),
            "test_path",
        ]
        with mock.patch("bauble.plugins.report.xsl.sys") as mock_sys:
            mock_sys.platform = "win32"
            _fop.set_fop_command()
            calls = [
                mock.call("fop.bat", path=path),
                mock.call("java.exe", path=path),
            ]
            mock_which.assert_has_calls(calls)
        with mock.patch("bauble.plugins.report.xsl.sys") as mock_sys:
            mock_sys.platform = "not_win32"
            _fop.set_fop_command()
            calls = [
                mock.call("fop", path=path),
                mock.call("java", path=path),
            ]
            mock_which.assert_has_calls(calls)


class GlobalFunctionsTests(XSLTestCase):
    def setUp(self):
        super().setUp()
        self.temp_path = Path(self.temp_dir.name) / ".testABCDdata.xml"

    def test_create_abcd_xml_all_plants(self):
        objs = self.session.query(Species).all()
        test_xml = create_abcd_xml(
            self.temp_path, PLANT_SOURCE_TYPE, True, False, objs
        )
        # test well formed xml
        self.assertTrue(etree.parse(test_xml))
        os.remove(test_xml)

    def test_create_abcd_xml_all_plants_exclude_private(self):
        objs = self.session.query(Species).all()
        test_xml = create_abcd_xml(
            self.temp_path, PLANT_SOURCE_TYPE, False, False, objs
        )
        # test well formed xml
        self.assertTrue(etree.parse(test_xml))
        os.remove(test_xml)

    def test_create_abcd_xml_all_accession(self):
        objs = self.session.query(Species).all()
        test_xml = create_abcd_xml(
            self.temp_path, ACCESSION_SOURCE_TYPE, True, True, objs
        )
        # test well formed xml
        self.assertTrue(etree.parse(test_xml))
        os.remove(test_xml)

    def test_create_abcd_xml_all_accession_exlude_private(self):
        objs = self.session.query(Species).all()
        test_xml = create_abcd_xml(
            self.temp_path, ACCESSION_SOURCE_TYPE, False, True, objs
        )
        # test well formed xml
        self.assertTrue(etree.parse(test_xml))
        os.remove(test_xml)

    def test_create_abcd_xml_all_species(self):
        objs = self.session.query(Species).all()
        test_xml = create_abcd_xml(
            self.temp_path, SPECIES_SOURCE_TYPE, True, False, objs
        )
        # test well formed xml
        self.assertTrue(etree.parse(test_xml))
        os.remove(test_xml)

    def test_create_abcd_xml_all_species_exclude_private_succeeds(self):
        objs = self.session.query(Species).all()
        test_xml = create_abcd_xml(
            self.temp_path, SPECIES_SOURCE_TYPE, False, False, objs
        )
        # test well formed xml
        self.assertTrue(etree.parse(test_xml))
        os.remove(test_xml)

    def test_create_abcd_xml_plants_private_only_exlude_raises(self):
        objs = [self.session.query(Accession).get(1)]
        # plants
        with self.assertRaises(BaubleError):
            create_abcd_xml(
                self.temp_path, PLANT_SOURCE_TYPE, False, False, objs
            )

    def test_create_abcd_xml_accessions_private_only_exclude_raises(self):
        objs = [self.session.query(Accession).get(1)]
        # test does not create xml
        with self.assertRaises(BaubleError):
            create_abcd_xml(
                self.temp_path, ACCESSION_SOURCE_TYPE, False, False, objs
            )

    def test_create_abcd_xml_accessions_private_only_include_succeeds(self):
        objs = [self.session.query(Accession).get(1)]
        test_xml = create_abcd_xml(
            self.temp_path, ACCESSION_SOURCE_TYPE, True, True, objs
        )
        # test well formed xml
        self.assertTrue(etree.parse(test_xml))
        os.remove(test_xml)

    def test_create_abcd_xml_species_without_accessions_raises(self):
        objs = (
            self.session.query(Species).filter(~Species.accessions.any()).all()
        )
        # accessions
        with self.assertRaises(BaubleError):
            create_abcd_xml(
                self.temp_path, ACCESSION_SOURCE_TYPE, True, True, objs
            )

    def test_create_abcd_xml_species_without_plants_raises(self):
        objs = (
            self.session.query(Species).filter(~Species.accessions.any()).all()
        )
        # plants
        with self.assertRaises(BaubleError):
            create_abcd_xml(
                self.temp_path, PLANT_SOURCE_TYPE, True, True, objs
            )

    def test_create_abcd_xml_species_without_accession_species_succeeds(self):
        objs = (
            self.session.query(Species).filter(~Species.accessions.any()).all()
        )
        # species
        test_xml = create_abcd_xml(
            self.temp_path, SPECIES_SOURCE_TYPE, True, False, objs
        )
        # test well formed xml
        self.assertTrue(etree.parse(test_xml))
        os.remove(test_xml)
