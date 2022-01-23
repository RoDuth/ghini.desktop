# Copyright (c) 2005,2006,2007,2008,2009 Brett Adams <brett@belizebotanic.org>
# Copyright (c) 2012-2015 Mario Frasca <mario@anche.no>
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

from unittest import mock
from tempfile import mkstemp
import logging
logger = logging.getLogger(__name__)

from gi.repository import Gtk

from bauble.test import BaubleTestCase
from bauble import prefs
from bauble import version_tuple


class PreferencesTests(BaubleTestCase):

    def test_create_does_not_save(self):
        handle, pname = mkstemp(suffix='.dict')
        p = prefs._prefs(pname)
        p.init()
        with open(pname) as f:
            self.assertEqual(f.read(), '')

    def test_assert_initial_values(self):
        handle, pname = mkstemp(suffix='.dict')
        p = prefs._prefs(pname)
        p.init()
        self.assertTrue(prefs.config_version_pref in p)
        self.assertTrue(prefs.picture_root_pref in p)
        self.assertTrue(prefs.date_format_pref in p)
        self.assertTrue(prefs.units_pref in p)
        self.assertEqual(p[prefs.config_version_pref], version_tuple[:2])
        self.assertEqual(p[prefs.picture_root_pref], '')
        self.assertEqual(p[prefs.date_format_pref], '%d-%m-%Y')
        self.assertEqual(p[prefs.time_format_pref], '%I:%M:%S %p')
        self.assertEqual(p[prefs.units_pref], 'metric')
        # generated
        self.assertEqual(p[prefs.parse_dayfirst_pref], True)
        self.assertEqual(p[prefs.parse_yearfirst_pref], False)
        self.assertEqual(p[prefs.datetime_format_pref], '%d-%m-%Y %I:%M:%S %p')

    def test_not_saved_while_testing(self):
        prefs.testing = True
        handle, pname = mkstemp(suffix='.dict')
        p = prefs._prefs(pname)
        p.init()
        p.save()
        with open(pname) as f:
            self.assertEqual(f.read(), '')

    def test_can_force_save(self):
        prefs.testing = True
        handle, pname = mkstemp(suffix='.dict')
        p = prefs._prefs(pname)
        p.init()
        p.save(force=True)
        with open(pname) as f:
            self.assertFalse(f.read() == '')

    def test_get_does_not_store_values(self):
        handle, pname = mkstemp(suffix='.dict')
        p = prefs._prefs(pname)
        p.init()
        self.assertFalse('not_there_yet.1' in p)
        self.assertIsNone(p['not_there_yet.1'])
        self.assertEqual(p.get('not_there_yet.2', 33), 33)
        self.assertIsNone(p.get('not_there_yet.3', None))
        self.assertFalse('not_there_yet.1' in p)
        self.assertFalse('not_there_yet.2' in p)
        self.assertFalse('not_there_yet.3' in p)
        self.assertFalse('not_there_yet.4' in p)

    def test_use___setitem___to_store_value_and_create_section(self):
        handle, pname = mkstemp(suffix='.dict')
        p = prefs._prefs(pname)
        p.init()
        self.assertFalse('test.not_there_yet-1' in p)
        p['test.not_there_yet-1'] = 'all is a ball'
        self.assertTrue('test.not_there_yet-1' in p)
        self.assertEqual(p['test.not_there_yet-1'], 'all is a ball')
        self.assertEqual(p.get('test.not_there_yet-1', 33), 'all is a ball')

    def test_most_values_converted_to_string(self):
        handle, pname = mkstemp(suffix='.dict')
        p = prefs._prefs(pname)
        p.init()
        self.assertFalse('test.not_there_yet-1' in p)
        p['test.not_there_yet-1'] = 1
        self.assertTrue('test.not_there_yet-1' in p)
        self.assertEqual(p['test.not_there_yet-1'], 1)

    def test_none_stays_none(self):
        # is this really useful?
        handle, pname = mkstemp(suffix='.dict')
        p = prefs._prefs(pname)
        p.init()
        p['test.not_there_yet-3'] = None
        self.assertEqual(p['test.not_there_yet-3'], None)

    def test_boolean_values_stay_boolean(self):
        handle, pname = mkstemp(suffix='.dict')
        p = prefs._prefs(pname)
        p.init()
        self.assertFalse('test.not_there_yet-1' in p)
        p['test.not_there_yet-1'] = True
        self.assertEqual(p['test.not_there_yet-1'], True)
        p['test.not_there_yet-2'] = False
        self.assertEqual(p['test.not_there_yet-2'], False)

    def test_saved_dictionary_like_ini_file(self):
        handle, pname = mkstemp(suffix='.dict')
        p = prefs._prefs(pname)
        p.init()
        self.assertFalse('test.not_there_yet-1' in p)
        p['test.not_there_yet-1'] = 1
        self.assertTrue('test.not_there_yet-1' in p)
        p.save(force=True)
        with open(pname) as f:
            content = f.read()
            self.assertTrue(content.index('not_there_yet-1 = 1') > 0)
            self.assertTrue(content.index('[test]') > 0)

    def test_generated_dayfirst_yearfirst(self):
        prefs.prefs[prefs.date_format_pref] = '%Y-%m-%d'
        self.assertTrue(prefs.prefs.get(prefs.parse_yearfirst_pref))
        self.assertFalse(prefs.prefs.get(prefs.parse_dayfirst_pref))
        prefs.prefs[prefs.date_format_pref] = '%d-%m-%Y'
        self.assertFalse(prefs.prefs.get(prefs.parse_yearfirst_pref))
        self.assertTrue(prefs.prefs.get(prefs.parse_dayfirst_pref))

    def test_generated_datetime_format(self):
        prefs.prefs[prefs.date_format_pref] = 'date'
        prefs.prefs[prefs.time_format_pref] = 'time'
        self.assertEqual(prefs.prefs.get(prefs.datetime_format_pref),
                         'date time')

    def test_itersection(self):
        for i in range(5):
            prefs.prefs[f'testsection.option{i}'] = f'value{i}'
        for i, (option, value) in enumerate(
                prefs.prefs.itersection('testsection')):
            self.assertEqual(option, f'option{i}')
            self.assertEqual(value, f'value{i}')

    def test__delitem__(self):
        prefs.prefs['testsection.option1'] = 'value1'
        prefs.prefs['testsection.option2'] = 'value2'
        self.assertTrue(prefs.prefs.config.has_option('testsection',
                                                      'option1'))
        self.assertTrue(prefs.prefs.config.has_option('testsection',
                                                      'option2'))
        del prefs.prefs['testsection.option2']
        self.assertFalse(prefs.prefs.config.has_option('testsection',
                                                       'option3'))
        self.assertTrue(prefs.prefs.has_section('testsection'))
        del prefs.prefs['testsection.option1']
        self.assertFalse(prefs.prefs.has_section('testsection'))
        self.assertFalse(prefs.prefs.has_section('nonexistent_section'))
        del prefs.prefs['nonexistent_section.option']
        self.assertFalse(prefs.prefs.has_section('nonexistent_section'))


class PrefsViewTests(BaubleTestCase):

    def test_prefs_view_starts_updates(self):
        prefs_view = prefs.PrefsView()
        self.assertIsNone(prefs_view.button_press_id)
        prefs_view.update()
        self.assertTrue(len(prefs_view.prefs_ls) > 8)

    @mock.patch('bauble.prefs.Gtk.MessageDialog.run',
                return_value=Gtk.ResponseType.OK)
    def test_on_button_press_event_adds_menu_can_active(self, mock_dialog):
        # NOTE causes a deprecation warning re Gtk.Menu.popup_for_device,
        # Gtk.Action.create_menu_item
        # also:
        # Gdk-CRITICAL **: ... gdk_window_get_device_position_double:
        # assertion 'GDK_IS_WINDOW (window)' failed
        from datetime import datetime
        prefs_view = prefs.PrefsView()
        prefs_view.update()

        prefs_tv = prefs_view.prefs_tv
        mock_event = mock.Mock(button=3, time=datetime.now().timestamp())

        with mock.patch('bauble.prefs.Gtk.Menu.append') as mock_append:
            prefs_view.on_button_press_event(prefs_tv, mock_event)

            mock_append.assert_called()

        selection = Gtk.TreePath.new_first()
        prefs_tv.get_selection().select_path(selection)

        with mock.patch('bauble.prefs.Gtk.Menu.append') as mock_append:
            prefs_view.on_button_press_event(prefs_tv, mock_event)

            mock_append.assert_called()
            mock_append.call_args.args[0].activate()
            mock_dialog.assert_called()
        log_str = f'model: {prefs_view.prefs_ls} tree_path: [<Gtk.TreePath obj'
        self.assertTrue(
            [i for i in self.handler.messages['bauble.prefs']['debug'] if
             i.startswith(log_str)])

    def test_on_prefs_edit_toggled(self):
        from bauble import utils
        orig_yes_no_dialog = utils.yes_no_dialog
        prefs_view = prefs.PrefsView()

        # starts without editing
        self.assertFalse(
            prefs_view.view.widgets.prefs_data_renderer.props.editable)
        self.assertIsNone(prefs_view.button_press_id)

        # toggle editing to True with yes to dialog
        utils.yes_no_dialog = lambda x, parent: True
        prefs_view.view.widgets.prefs_edit_chkbx.set_active(True)
        prefs_view.on_prefs_edit_toggled(
            prefs_view.view.widgets.prefs_edit_chkbx)

        self.assertTrue(
            prefs_view.view.widgets.prefs_data_renderer.props.editable)
        self.assertIsNotNone(prefs_view.button_press_id)

        # toggle editing to False
        prefs_view.view.widgets.prefs_edit_chkbx.set_active(False)
        prefs_view.on_prefs_edit_toggled(
            prefs_view.view.widgets.prefs_edit_chkbx)

        self.assertFalse(
            prefs_view.view.widgets.prefs_data_renderer.props.editable)
        self.assertIsNone(prefs_view.button_press_id)

        # toggle editing to True with no to dialog
        utils.yes_no_dialog = lambda x, parent: False
        prefs_view.view.widgets.prefs_edit_chkbx.set_active(True)
        prefs_view.on_prefs_edit_toggled(
            prefs_view.view.widgets.prefs_edit_chkbx)

        self.assertFalse(
            prefs_view.view.widgets.prefs_data_renderer.props.editable)
        self.assertIsNone(prefs_view.button_press_id)

        utils.yes_no_dialog = orig_yes_no_dialog

    def test_on_prefs_edited(self):
        key = 'bauble.keys'
        prefs.prefs[key] = True
        prefs_view = prefs.PrefsView()
        prefs_view.update()
        path = [i.path for i in prefs_view.prefs_ls if i[0] == key][0]
        self.assertTrue(prefs.prefs[key])

        # wrong type
        prefs_view.on_prefs_edited(None, path, 'xyz')
        self.assertTrue(prefs.prefs[key])

        # correct type
        prefs_view.on_prefs_edited(None, path, 'False')
        self.assertFalse(prefs.prefs[key])

        # picture root does not accept non existing path
        key = prefs.picture_root_pref
        orig = prefs.prefs[key]
        path = [i.path for i in prefs_view.prefs_ls if i[0] == key][0]
        prefs_view.on_prefs_edited(None, path, 'xxrandomstringxx')
        self.assertEqual(prefs.prefs[key], orig)

        # add new entry
        key = 'bauble.test.option'
        self.assertIsNone(prefs.prefs[key])
        tree_iter = prefs_view.prefs_ls.get_iter(path)
        prefs_view.prefs_ls.insert_after(tree_iter,
                                         row=[key, '', None])
        path = [i.path for i in prefs_view.prefs_ls if i[0] == key][0]
        prefs_view.on_prefs_edited(None, path, '{"this": "that"}')
        self.assertEqual(prefs.prefs[key], {"this": "that"})

        # delete option
        from bauble import utils
        orig_yes_no_dialog = utils.yes_no_dialog
        utils.yes_no_dialog = lambda x, parent: True
        prefs_view.on_prefs_edited(None, path, '')
        self.assertIsNone(prefs.prefs[key])
        utils.yes_no_dialog = orig_yes_no_dialog

    @mock.patch('bauble.prefs.Gtk.MessageDialog.run',
                return_value=Gtk.ResponseType.OK)
    def test_add_new(self, mock_dialog):
        prefs_view = prefs.PrefsView()
        prefs_view.update()
        path = Gtk.TreePath.new_first()
        key = 'bauble.test.option'
        new_iter = prefs_view.add_new(prefs_view.prefs_ls, path, text=key)
        mock_dialog.assert_called()
        self.assertIsNotNone(new_iter)
        self.assertTrue(f'adding new pref option {key}' in
                        self.handler.messages['bauble.prefs']['debug'])

    @mock.patch('bauble.prefs.utils.message_dialog')
    def test_on_prefs_backup_restore(self, mock_dialog):
        prefs.prefs.save(force=True)
        prefs_view = prefs.PrefsView()
        prefs_view.update()
        # restore no backup
        prefs_view.on_prefs_restore_clicked(None)
        mock_dialog.assert_called()
        mock_dialog.assert_called_with('No backup found')
        # create backup and check they are the same
        prefs_view.on_prefs_backup_clicked(None)
        with open(self.temp, 'r') as f:
            start = f.read()
        with open(self.temp + 'BAK') as f:
            backup = f.read()
        self.assertEqual(start, backup)
        # save a change and check they differ
        self.assertIsNone(prefs.prefs['bauble.test.option'])
        prefs.prefs['bauble.test.option'] = 'test'
        self.assertIsNotNone(prefs.prefs['bauble.test.option'])
        prefs.prefs.save(force=True)
        with open(self.temp, 'r') as f:
            start = f.read()
        with open(self.temp + 'BAK') as f:
            backup = f.read()
        self.assertNotEqual(start, backup)
        # restore
        prefs_view.on_prefs_restore_clicked(None)
        self.assertIsNone(prefs.prefs['bauble.test.option'])
