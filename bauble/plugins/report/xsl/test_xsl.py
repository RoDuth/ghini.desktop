# Copyright (c) 2021 Ross Demuth <rossdemuth123@gmail.com>
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

from lxml import etree
from gi.repository import Gtk

from bauble import paths
from bauble import prefs
from bauble.error import BaubleError
from bauble.test import BaubleTestCase
# from bauble.editor import MockView, MockDialog
from bauble.plugins.garden import test_garden as garden_test
from bauble.plugins.plants import test_plants as plants_test
from bauble.plugins.plants.species import Species
from bauble.plugins.garden.accession import Accession
from . import (_fop,
               create_abcd_xml,
               PLANT_SOURCE_TYPE,
               ACCESSION_SOURCE_TYPE,
               SPECIES_SOURCE_TYPE,
               DEFAULT_SOURCE_TYPE,
               SOURCE_TYPES,
               FORMATS,
               USE_EXTERNAL_FOP_PREF,
               XSLFormatterSettingsBox,
               XSLFormatterPlugin)

from . import SettingsBox


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

    @mock.patch('bauble.utils.Gtk.FileChooserNative')
    def test_on_btnbrowse_clicked_no_previous_entry(self, mock_fcn):
        # only need to reset the widget if caching in BuilderLoader
        # self.settings_box.widgets.file_entry.set_text('')
        mock_fcn.new.return_value = mock_fcn
        mock_fcn.run.return_value = Gtk.ResponseType.ACCEPT
        selected_file = paths.templates_dir() + '/xsl/test.xsl'
        mock_fcn.get_filename.return_value = selected_file

        self.settings_box.on_btnbrowse_clicked(None)

        mock_fcn.new.assert_called_with(_('Select a stylesheet'),
                                        None,
                                        Gtk.FileChooserAction.OPEN)
        # if this fails then selected_file is also wrong
        mock_fcn.set_current_folder.assert_called_with(paths.templates_dir())

        self.assertEqual(self.settings_box.widgets.file_entry.get_text(),
                         selected_file)

    @mock.patch('bauble.utils.Gtk.FileChooserNative')
    def test_on_btnbrowse_clicked_w_previous_entry(self, mock_fcn):
        dummy_dir = '/some/stylesheet/dir'
        dummy_stylesheet = dummy_dir + '/file.xsl'
        self.settings_box.widgets.file_entry.set_text(dummy_stylesheet)
        mock_fcn.new.return_value = mock_fcn
        mock_fcn.run.return_value = Gtk.ResponseType.ACCEPT
        mock_fcn.get_filename.return_value = dummy_stylesheet

        self.settings_box.on_btnbrowse_clicked(None)

        mock_fcn.new.assert_called_with(_('Select a stylesheet'),
                                        None,
                                        Gtk.FileChooserAction.OPEN)

        mock_fcn.set_current_folder.assert_called_with(dummy_dir)

        self.assertEqual(self.settings_box.widgets.file_entry.get_text(),
                         dummy_stylesheet)

    @mock.patch('bauble.utils.Gtk.FileChooserNative')
    def test_on_out_btnbrowse_clicked_no_previous_entry(self, mock_fcn):
        mock_fcn.new.return_value = mock_fcn
        mock_fcn.run.return_value = Gtk.ResponseType.ACCEPT
        selected_file = paths.templates_dir() + '/test.pdf'
        mock_fcn.get_filename.return_value = selected_file

        self.settings_box.on_out_btnbrowse_clicked(None)

        mock_fcn.new.assert_called_with(_('Save to file'),
                                        None,
                                        Gtk.FileChooserAction.SAVE)
        # if this fails then selected_file is also wrong
        mock_fcn.set_current_folder.assert_called_with(str(Path.home()))

        self.assertEqual(self.settings_box.widgets.outfile_entry.get_text(),
                         selected_file)

    @mock.patch('bauble.utils.Gtk.FileChooserNative')
    def test_on_out_btnbrowse_clicked_w_previous_entry(self, mock_fcn):
        dummy_dir = '/some/reports/dir'
        dummy_report = dummy_dir + '/file.pdf'
        self.settings_box.widgets.outfile_entry.set_text(dummy_report)
        mock_fcn.new.return_value = mock_fcn
        mock_fcn.run.return_value = Gtk.ResponseType.ACCEPT
        mock_fcn.get_filename.return_value = dummy_report

        self.settings_box.on_out_btnbrowse_clicked(None)

        mock_fcn.new.assert_called_with(_('Save to file'),
                                        None,
                                        Gtk.FileChooserAction.SAVE)

        mock_fcn.set_current_folder.assert_called_with(dummy_dir)

        self.assertEqual(self.settings_box.widgets.outfile_entry.get_text(),
                         dummy_report)

    def test_get_report_settings_defaults(self):
        # a template should be set
        dummy_dir = '/some/stylesheet/dir'
        dummy_stylesheet = dummy_dir + '/file.xsl'
        self.settings_box.widgets.file_entry.set_text(dummy_stylesheet)
        settings = self.settings_box.get_report_settings()
        self.assertEqual(settings,
                         {'authors': False,
                          'out_file': '',
                          'out_format': 'PDF',
                          'private': False,
                          'source_type': PLANT_SOURCE_TYPE,
                          'stylesheet': dummy_stylesheet})

    def test_get_report_settings_w_values(self):
        # a template should be set
        dummy_dir = '/some/stylesheet/dir'
        dummy_stylesheet = dummy_dir + '/file.xsl'
        self.settings_box.widgets.file_entry.set_text(dummy_stylesheet)

        source_type = SOURCE_TYPES.index(ACCESSION_SOURCE_TYPE)
        self.settings_box.widgets.source_type_combo.set_active(source_type)
        self.settings_box.widgets.author_check.set_active(True)
        self.settings_box.widgets.private_check.set_active(True)
        out_format = list(FORMATS).index('XSL-FO')
        self.settings_box.widgets.format_combo.set_active(out_format)
        dummy_dir = '/some/reports/dir'
        dummy_report = dummy_dir + '/file.fo'
        self.settings_box.widgets.outfile_entry.set_text(dummy_report)
        settings = self.settings_box.get_report_settings()
        self.assertEqual(settings,
                         {'authors': True,
                          'out_file': dummy_report,
                          'out_format': 'XSL-FO',
                          'private': True,
                          'source_type': ACCESSION_SOURCE_TYPE,
                          'stylesheet': dummy_stylesheet})

    @mock.patch('bauble.plugins.report.xsl.Path.exists', return_value=True)
    def test_update_w_full_settings(self, _mock_exists):
        # a template should be set
        dummy_dir = '/some/stylesheet/dir'
        dummy_stylesheet = dummy_dir + '/file.xsl'
        dummy_dir = '/some/reports/dir'
        dummy_report = dummy_dir + '/file.fo'
        settings = {'authors': True,
                    'out_file': dummy_report,
                    'out_format': 'XSL-FO',
                    'private': True,
                    'source_type': ACCESSION_SOURCE_TYPE,
                    'stylesheet': dummy_stylesheet}
        self.settings_box.update(settings)

        self.assertEqual(self.settings_box.widgets.author_check.get_active(),
                         settings.get('authors'))
        self.assertEqual(self.settings_box.widgets.outfile_entry.get_text(),
                         settings.get('out_file'))
        self.assertEqual(
            self.settings_box.widgets.format_combo.get_active_text(),
            settings.get('out_format')
        )
        self.assertEqual(self.settings_box.widgets.private_check.get_active(),
                         settings.get('private'))
        self.assertEqual(
            self.settings_box.widgets.source_type_combo.get_active_text(),
            settings.get('source_type')
        )
        self.assertEqual(self.settings_box.widgets.file_entry.get_text(),
                         settings.get('stylesheet'))
        self.assertTrue(
            self.settings_box.widgets.options_expander.get_expanded()
        )

    # this mock should have no affect but is included incase.
    @mock.patch('bauble.plugins.report.xsl.Path.exists', return_value=True)
    def test_update_wo_settings(self, _mock_exists):
        self.settings_box.update({})

        self.assertEqual(self.settings_box.widgets.author_check.get_active(),
                         False)
        self.assertEqual(self.settings_box.widgets.outfile_entry.get_text(),
                         '')
        self.assertEqual(
            self.settings_box.widgets.format_combo.get_active_text(),
            'PDF'
        )
        self.assertEqual(self.settings_box.widgets.private_check.get_active(),
                         False)
        self.assertEqual(
            self.settings_box.widgets.source_type_combo.get_active_text(),
            DEFAULT_SOURCE_TYPE
        )
        self.assertEqual(self.settings_box.widgets.file_entry.get_text(),
                         '')
        self.assertFalse(
            self.settings_box.widgets.options_expander.get_expanded()
        )


class XSLFormatterPluginTests(XSLTestCase):
    FOP_PATH = 'test/fop'
    if sys.platform == 'win32':
        FOP_PATH = 'test/fop.bat'

    def setUp(self):
        super().setUp()
        from bauble import prefs
        prefs.prefs[USE_EXTERNAL_FOP_PREF] = True
        self.formatter = XSLFormatterPlugin()

    def test_get_settings_box_returns_settings_box(self):
        # redundant?
        self.assertIsInstance(self.formatter.get_settings_box(),
                              SettingsBox)
        self.assertIsInstance(self.formatter.get_settings_box(),
                              XSLFormatterSettingsBox)

    @mock.patch('bauble.utils.message_dialog')
    def test_format_no_stylesheet_notifies(self, mock_dialog):
        # NOTE this will not get to open the file step becuase fop is not run
        # and hence no file is created
        objs = self.session.query(Species).all()
        # create the file so format finishes
        settings = {'authors': False,
                    'out_file': '',
                    'out_format': 'PDF',
                    'private': False,
                    'source_type': DEFAULT_SOURCE_TYPE,
                    'stylesheet': ''}
        self.formatter.format(objs, **settings)
        self.assertEqual(mock_dialog.call_args.args[0],
                         'Please select a stylesheet.')

    @mock.patch('bauble.plugins.report.xsl._fop.set_fop_command')
    @mock.patch('bauble.utils.message_dialog')
    def test_format_min_settings_no_fop_notifies(self, mock_dialog,
                                                 mock_set_fop):
        # NOTE this will not get to open the file step becuase fop is not run
        # and hence no file is created
        mock_set_fop.return_value = False
        _fop.fop = None
        objs = self.session.query(Species).all()
        dummy_stylesheet = self.temp_dir.name + '/file.xsl'
        # create the file so format finishes
        settings = {'authors': False,
                    'out_file': '',
                    'out_format': 'PDF',
                    'private': False,
                    'source_type': DEFAULT_SOURCE_TYPE,
                    'stylesheet': dummy_stylesheet}
        self.formatter.format(objs, **settings)
        self.assertIn('Could not find Apache FOP',
                      mock_dialog.call_args.args[0])

    @mock.patch('bauble.plugins.report.xsl._fop.set_fop_command')
    @mock.patch('bauble.plugins.report.xsl.subprocess.run')
    @mock.patch('bauble.utils.message_dialog')
    def test_format_min_settings_no_fop_output_notifies(
            self, mock_dialog, mock_run, mock_set_fop):
        mock_set_fop.return_value = True
        _fop.fop = self.FOP_PATH
        # NOTE this will not get to open the file step becuase fop is not run
        # and hence no file is created
        objs = self.session.query(Species).all()
        dummy_stylesheet = self.temp_dir.name + '/file.xsl'
        # create the file so format finishes
        settings = {'authors': False,
                    'out_file': '',
                    'out_format': 'PDF',
                    'private': False,
                    'source_type': DEFAULT_SOURCE_TYPE,
                    'stylesheet': dummy_stylesheet}
        self.formatter.format(objs, **settings)
        run_args = mock_run.call_args
        self.assertEqual(run_args.args[0][0], self.FOP_PATH)
        self.assertEqual(run_args.args[0][1], '-xml')
        self.assertEqual(run_args.args[0][3], '-xsl')
        self.assertEqual(run_args.args[0][4], dummy_stylesheet)
        self.assertEqual(run_args.args[0][5], '-pdf')
        self.assertIsNotNone(run_args.args[0][6])
        self.assertIn('Error creating the file',
                      mock_dialog.call_args.args[0])

    @mock.patch('bauble.plugins.report.xsl._fop.set_fop_command')
    @mock.patch('bauble.plugins.report.xsl.subprocess.run')
    @mock.patch('bauble.utils.desktop.open')
    def test_format_full_settings_fake_fop_runs(self, mock_open, mock_run,
                                                mock_set_fop):
        mock_set_fop.return_value = True
        _fop.fop = self.FOP_PATH
        objs = self.session.query(Species).all()
        dummy_stylesheet = self.temp_dir.name + '/file.xsl'
        dummy_report = self.temp_dir.name + '/file.fo'
        # create the file so format finishes (fake fop succeeds)
        Path(dummy_report).touch()
        settings = {'authors': True,
                    'out_file': dummy_report,
                    'out_format': 'XSL-FO',
                    'private': True,
                    'source_type': ACCESSION_SOURCE_TYPE,
                    'stylesheet': dummy_stylesheet}
        self.formatter.format(objs, **settings)
        run_args = mock_run.call_args
        self.assertEqual(str(mock_open.call_args.args[0]), self.temp_dir.name)
        self.assertEqual(run_args.args[0][0], self.FOP_PATH)
        self.assertEqual(run_args.args[0][1], '-xml')
        self.assertEqual(run_args.args[0][3], '-xsl')
        self.assertEqual(run_args.args[0][4], dummy_stylesheet)
        self.assertEqual(run_args.args[0][5], '-foout')
        self.assertEqual(run_args.args[0][6], dummy_report)


class FOPTests(XSLTestCase):
    FOP_PATH = 'test/fop'
    if sys.platform == 'win32':
        FOP_PATH = 'test/fop.bat'

    def setUp(self):
        super().setUp()
        prefs.prefs[USE_EXTERNAL_FOP_PREF] = True

    def test_update_calls_init_w_pref_changed(self):
        _fop.update()
        self.assertTrue(_fop.external_fop_pref)
        with mock.patch('bauble.plugins.report.xsl._fop.init') as mock_init:
            prefs.prefs[USE_EXTERNAL_FOP_PREF] = False
            _fop.update()
            mock_init.assert_called()

    def test_update_not_call_init_w_pref_unchanged(self):
        _fop.update()
        self.assertTrue(_fop.external_fop_pref)
        with mock.patch('bauble.plugins.report.xsl._fop.init') as mock_init:
            prefs.prefs[USE_EXTERNAL_FOP_PREF] = True
            _fop.update()
            mock_init.assert_not_called()

    @mock.patch('bauble.plugins.report.xsl.Path.glob')
    @mock.patch('bauble.plugins.report.xsl.Path.__truediv__')
    @mock.patch('bauble.plugins.report.xsl.Path.exists', return_value=True)
    def test_set_fop_command_internal_fop_and_jre(self, _mock_exists, mock_div,
                                                  mock_glob):
        mock_path = Path('test')
        mock_glob.return_value = [mock_path]
        mock_div.return_value = mock_path
        prefs.prefs[USE_EXTERNAL_FOP_PREF] = False
        _fop.update()
        self.assertFalse(_fop.external_fop_pref)
        self.assertEqual(_fop.fop, 'test')
        self.assertEqual(_fop.java, 'test')

    @mock.patch.dict(os.environ, {"PATH": "test"})
    @mock.patch('bauble.plugins.report.xsl.Path.is_file', return_value=True)
    def test_get_fop_path_fop_exists(self, _mock_is_file):
        _fop.set_fop_command()
        self.assertEqual(_fop.fop, self.FOP_PATH)

    @mock.patch.dict(os.environ, {"PATH": "test"})
    @mock.patch('bauble.plugins.report.xsl.Path.is_file', return_value=False)
    def test_get_fop_path_fop_doesnt_exist(self, _mock_is_file):
        _fop.set_fop_command()
        self.assertIsNone(_fop.fop)

    @mock.patch('bauble.plugins.report.xsl.Path.glob')
    def test_set_fop_classpath(self, mock_glob):
        mock_jars = ['build/fop.sandbox.jar',
                     'lib/test.jar',
                     'lib/test2.jar',
                     'build/fop.jar']
        mock_glob.return_value = [Path(i) for i in mock_jars]
        _fop.fop = '/test_root/{self.FOP_PATH}'
        _fop.set_fop_classpath()
        result = ''.join(i + os.pathsep for i in mock_jars)
        result += ''.join(i + os.pathsep for i in mock_jars if 'build' in i)
        self.assertEqual(_fop.class_path, result.strip(os.pathsep))


class GlobalFunctionsTests(XSLTestCase):
    FOP_PATH = 'test/fop'
    if sys.platform == 'win32':
        FOP_PATH = 'test/fop.bat'

    def setUp(self):
        super().setUp()
        prefs.prefs[USE_EXTERNAL_FOP_PREF] = True

    def test_create_abcd_xml_all_plants(self):
        objs = self.session.query(Species).all()
        test_xml = create_abcd_xml(self.temp_dir.name, PLANT_SOURCE_TYPE, True,
                                   False, objs)
        # test well formed xml
        self.assertTrue(etree.parse(test_xml))
        os.remove(test_xml)

    def test_create_abcd_xml_all_plants_exclude_private(self):
        objs = self.session.query(Species).all()
        test_xml = create_abcd_xml(self.temp_dir.name, PLANT_SOURCE_TYPE,
                                   False, False, objs)
        # test well formed xml
        self.assertTrue(etree.parse(test_xml))
        os.remove(test_xml)

    def test_create_abcd_xml_all_accession(self):
        objs = self.session.query(Species).all()
        test_xml = create_abcd_xml(self.temp_dir.name, ACCESSION_SOURCE_TYPE,
                                   True, True, objs)
        # test well formed xml
        self.assertTrue(etree.parse(test_xml))
        os.remove(test_xml)

    def test_create_abcd_xml_all_accession_exlude_private(self):
        objs = self.session.query(Species).all()
        test_xml = create_abcd_xml(self.temp_dir.name, ACCESSION_SOURCE_TYPE,
                                   False, True, objs)
        # test well formed xml
        self.assertTrue(etree.parse(test_xml))
        os.remove(test_xml)

    def test_create_abcd_xml_all_species(self):
        objs = self.session.query(Species).all()
        test_xml = create_abcd_xml(self.temp_dir.name, SPECIES_SOURCE_TYPE,
                                   True, False, objs)
        # test well formed xml
        self.assertTrue(etree.parse(test_xml))
        os.remove(test_xml)

    def test_create_abcd_xml_all_species_exclude_private_succeeds(self):
        objs = self.session.query(Species).all()
        test_xml = create_abcd_xml(self.temp_dir.name, SPECIES_SOURCE_TYPE,
                                   False, False, objs)
        # test well formed xml
        self.assertTrue(etree.parse(test_xml))
        os.remove(test_xml)

    def test_create_abcd_xml_plants_private_only_exlude_raises(self):
        objs = [self.session.query(Accession).get(1)]
        # plants
        with self.assertRaises(BaubleError):
            create_abcd_xml(self.temp_dir.name, PLANT_SOURCE_TYPE, False,
                            False, objs)

    def test_create_abcd_xml_accessions_private_only_exclude_raises(self):
        objs = [self.session.query(Accession).get(1)]
        # test does not create xml
        with self.assertRaises(BaubleError):
            create_abcd_xml(self.temp_dir.name, ACCESSION_SOURCE_TYPE, False,
                            False, objs)

    def test_create_abcd_xml_accessions_private_only_include_succeeds(self):
        objs = [self.session.query(Accession).get(1)]
        test_xml = create_abcd_xml(self.temp_dir.name, ACCESSION_SOURCE_TYPE,
                                   True, True, objs)
        # test well formed xml
        self.assertTrue(etree.parse(test_xml))
        os.remove(test_xml)

    @mock.patch('bauble.utils.message_dialog')
    def test_create_abcd_xml_species_without_accessions_notifies_user(
            self, mock_dialog):
        objs = (self.session.query(Species)
                .filter(~Species.accessions.any())
                .all())
        # accessions
        test_xml = create_abcd_xml(self.temp_dir.name, ACCESSION_SOURCE_TYPE,
                                   True, True, objs)
        mock_dialog.assert_called()
        self.assertFalse(test_xml)

    @mock.patch('bauble.utils.message_dialog')
    def test_create_abcd_xml_species_without_plants_notifies_user(self,
                                                                  mock_dialog):
        objs = (self.session.query(Species)
                .filter(~Species.accessions.any())
                .all())
        # plants
        test_xml = create_abcd_xml(self.temp_dir.name, PLANT_SOURCE_TYPE,
                                   True, True, objs)
        mock_dialog.assert_called()
        self.assertFalse(test_xml)

    def test_create_abcd_xml_species_without_accession_species_succeeds(self):
        objs = (self.session.query(Species)
                .filter(~Species.accessions.any())
                .all())
        # species
        test_xml = create_abcd_xml(self.temp_dir.name, SPECIES_SOURCE_TYPE,
                                   True, False, objs)
        # test well formed xml
        self.assertTrue(etree.parse(test_xml))
        os.remove(test_xml)