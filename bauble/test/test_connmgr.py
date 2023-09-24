# Copyright (c) 2015 Mario Frasca <mario@anche.no>
# Copyright (c) 2022 Ross Demuth <rossdemuth123@gmail.com>
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
from tempfile import mkdtemp

# just keeping it here because I am forgetful and I never recall how to
# import SkipTest otherwise! and commented out because of FlyCheck.
from unittest import SkipTest
from unittest import mock

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa

import bauble
from bauble import paths
from bauble import prefs
from bauble.connmgr import ConnMgrPresenter
from bauble.connmgr import check_create_paths
from bauble.connmgr import check_new_release
from bauble.connmgr import notify_new_release
from bauble.connmgr import retrieve_latest_release_data
from bauble.editor import MockDialog
from bauble.editor import MockView
from bauble.test import BaubleTestCase
from bauble.test import check_dupids

RESPONSE_OK = Gtk.ResponseType.OK
RESPONSE_CANCEL = Gtk.ResponseType.CANCEL


def test_duplicate_ids():
    """
    Test for duplicate ids for all .glade files in the tag plugin.
    """
    import bauble.connmgr as mod
    head, _tail = os.path.split(mod.__file__)
    assert(not check_dupids(os.path.join(head, 'connmgr.glade')))


prefs.testing = True


class ConnMgrPresenterTests(BaubleTestCase):
    'Presenter manages view and model, implements view callbacks.'

    def test_can_create_presenter(self):
        view = MockView(combos={'name_combo': [],
                                'type_combo': []})
        presenter = ConnMgrPresenter(view)
        self.assertEqual(presenter.view, view)

    def test_no_connections_then_message(self):
        view = MockView(combos={'name_combo': [],
                                'type_combo': []})
        presenter = ConnMgrPresenter(view)

        self.assertFalse(presenter.view.widget_get_visible(
            'expander'))
        self.assertTrue(presenter.view.widget_get_visible(
            'noconnectionlabel'))

    def test_one_connection_shown_removed_message(self):
        view = MockView(combos={'name_combo': [],
                                'type_combo': []})
        prefs.prefs[bauble.conn_list_pref] = {
            'nugkui': {'default': True,
                       'directory': 'nugkui',
                       'type': 'SQLite',
                       'file': 'nugkui.db'}}
        presenter = ConnMgrPresenter(view)
        # T_0
        self.assertTrue(presenter.view.widget_get_visible(
            'expander'))
        self.assertFalse(presenter.view.widget_get_visible(
            'noconnectionlabel'))
        # action
        presenter.remove_connection('nugkui')
        # T_1
        self.assertTrue(presenter.view.widget_get_visible(
            'noconnectionlabel'))
        self.assertFalse(presenter.view.widget_get_visible(
            'expander'))

    def test_one_connection_on_remove_confirm_negative(self):
        view = MockView(combos={'name_combo': [],
                                'type_combo': []})
        prefs.prefs[bauble.conn_list_pref] = {
            'nugkui': {'default': True,
                       'directory': 'nugkui',
                       'type': 'SQLite',
                       'file': 'nugkui.db'}}
        presenter = ConnMgrPresenter(view)
        presenter.view.reply_yes_no_dialog.append(False)
        presenter.on_remove_button_clicked('button')
        ## nothing changes
        self.assertTrue(presenter.view.widget_get_visible(
            'expander'))
        self.assertFalse(presenter.view.widget_get_visible(
            'noconnectionlabel'))

    def test_one_connection_on_remove_confirm_positive(self):
        view = MockView(combos={'name_combo': [],
                                'type_combo': []})
        prefs.prefs[bauble.conn_list_pref] = {
            'nugkui': {'default': True,
                       'directory': 'nugkui',
                       'type': 'SQLite',
                       'file': 'nugkui.db'}}
        presenter = ConnMgrPresenter(view)
        presenter.view.reply_yes_no_dialog.append(True)
        presenter.on_remove_button_clicked('button')
        ## visibility swapped
        self.assertFalse(presenter.view.widget_get_visible(
            'expander'))
        self.assertTrue(presenter.view.widget_get_visible(
            'noconnectionlabel'))

    def test_two_connection_initialize_default_first(self):
        view = MockView(combos={'name_combo': [],
                                'type_combo': []})
        prefs.prefs[bauble.conn_list_pref] = {
            'nugkui': {'default': True,
                       'directory': 'nugkui',
                       'type': 'SQLite',
                       'file': 'nugkui.db'},
            'btuu': {'default': False,
                     'directory': 'btuu',
                     'type': 'SQLite',
                     'file': 'btuu.db'}}
        prefs.prefs[bauble.conn_default_pref] = 'nugkui'
        presenter = ConnMgrPresenter(view)
        self.assertEqual(presenter.connection_name, 'nugkui')
        params = presenter.connections[presenter.connection_name]
        self.assertEqual(params['default'], True)
        self.assertTrue(view.widget_get_value('usedefaults_chkbx'))

    def test_two_connection_initialize_default_second(self):
        view = MockView(combos={'name_combo': [],
                                'type_combo': []})
        prefs.prefs[bauble.conn_list_pref] = {
            'nugkui': {'default': True,
                       'directory': 'nugkui',
                       'type': 'SQLite',
                       'file': 'nugkui.db'},
            'btuu': {'default': False,
                     'directory': 'btuu',
                     'type': 'SQLite',
                     'file': 'btuu.db'}}
        prefs.prefs[bauble.conn_default_pref] = 'bruu'
        presenter = ConnMgrPresenter(view)
        self.assertEqual(presenter.connection_name, 'btuu')
        params = presenter.connections[presenter.connection_name]
        self.assertEqual(params['default'], False)
        self.assertFalse(view.widget_get_value('usedefaults_chkbx'))

    def test_two_connection_on_remove_confirm_positive(self):
        view = MockView(combos={'name_combo': [],
                                'type_combo': []})
        prefs.prefs[bauble.conn_list_pref] = {
            'nugkui': {'default': True,
                       'directory': 'nugkui',
                       'type': 'SQLite',
                       'file': 'nugkui.db'},
            'btuu': {'default': True,
                     'directory': 'btuu',
                     'type': 'SQLite',
                     'file': 'btuu.db'}}
        presenter = ConnMgrPresenter(view)
        presenter.view.reply_yes_no_dialog.append(True)
        presenter.on_remove_button_clicked('button')
        ## visibility same
        self.assertTrue(presenter.view.widget_get_visible(
            'expander'))
        self.assertFalse(presenter.view.widget_get_visible(
            'noconnectionlabel'))

    def test_one_connection_shown_and_selected_sqlite(self):
        view = MockView(combos={'name_combo': [],
                                'type_combo': []})
        prefs.prefs[bauble.conn_list_pref] = {
            'nugkui': {'default': True,
                       'directory': 'nugkui',
                       'type': 'SQLite',
                       'file': 'nugkui.db'}}
        prefs.prefs[bauble.conn_default_pref] = 'nugkui'
        presenter = ConnMgrPresenter(view)
        self.assertEqual(presenter.connection_name, 'nugkui')
        self.assertTrue(presenter.view.widget_get_visible(
            'expander'))
        self.assertFalse(presenter.view.widget_get_visible(
            'noconnectionlabel'))

    def test_one_connection_shown_and_selected_postgresql(self):
        view = MockView(combos={'name_combo': [],
                                'type_combo': []})
        prefs.prefs[bauble.conn_list_pref] = {
            'quisquis': {'passwd': False,
                         'directory': '',
                         'db': 'quisquis',
                         'host': 'localhost',
                         'user': 'pg',
                         'type': 'PostgreSQL'}}
        prefs.prefs[bauble.conn_default_pref] = 'quisquis'
        presenter = ConnMgrPresenter(view)
        self.assertEqual(presenter.connection_name, 'quisquis')
        self.assertTrue(presenter.view.widget_get_visible(
            'expander'))
        self.assertTrue(presenter.view.widget_get_visible(
            'dbms_parambox'))
        self.assertFalse(presenter.view.widget_get_visible(
            'sqlite_parambox'))
        self.assertFalse(presenter.view.widget_get_visible(
            'noconnectionlabel'))

    def test_one_connection_shown_and_selected_oracle(self):
        view = MockView(combos={'name_combo': [],
                                'type_combo': []})
        prefs.prefs[bauble.conn_list_pref] = {
            'quisquis': {'passwd': False,
                         'directory': '',
                         'db': 'quisquis',
                         'host': 'localhost',
                         'user': 'pg',
                         'type': 'Oracle'}}
        prefs.prefs[bauble.conn_default_pref] = 'quisquis'
        presenter = ConnMgrPresenter(view)
        self.assertEqual(presenter.connection_name, 'quisquis')
        self.assertTrue(presenter.view.widget_get_visible(
            'expander'))
        self.assertTrue(presenter.view.widget_get_visible(
            'dbms_parambox'))
        self.assertFalse(presenter.view.widget_get_visible(
            'sqlite_parambox'))
        self.assertFalse(presenter.view.widget_get_visible(
            'noconnectionlabel'))

    def test_two_connections_wrong_default_use_first_one(self):
        view = MockView(combos={'name_combo': [],
                                'type_combo': []})
        prefs.prefs[bauble.conn_default_pref] = 'nugkui'
        prefs.prefs[bauble.conn_list_pref] = {
            'nugkui': {'default': True,
                       'directory': 'nugkui',
                       'type': 'SQLite',
                       'file': 'nugkui.db'},
            'quisquis': {'passwd': False,
                         'directory': '',
                         'db': 'quisquis',
                         'host': 'localhost',
                         'user': 'pg',
                         'type': 'Oracle'}}
        prefs.prefs[bauble.conn_default_pref] = 'nonce'
        presenter = ConnMgrPresenter(view)
        as_list = presenter.connection_names
        self.assertEqual(presenter.connection_name, as_list[0])

    def test_when_user_selects_different_type(self):
        view = MockView(combos={'name_combo': [],
                                'type_combo': []})
        prefs.prefs[bauble.conn_default_pref] = 'nugkui'
        prefs.prefs[bauble.conn_list_pref] = {
            'nugkui': {'type': 'SQLite',
                       'default': True,
                       'directory': 'nugkui',
                       'file': 'nugkui.db'},
            'quisquis': {'type': 'PostgreSQL',
                         'passwd': False,
                         'directory': '',
                         'db': 'quisquis',
                         'host': 'localhost',
                         'user': 'pg'}}
        presenter = ConnMgrPresenter(view)
        # T_0
        self.assertEqual(presenter.connection_name, 'nugkui')
        self.assertTrue(presenter.view.widget_get_visible(
            'sqlite_parambox'))
        # action
        view.widget_set_value('name_combo', 'quisquis')
        presenter.dbtype = 'PostgreSQL'  # who to trigger this in tests?
        presenter.on_name_combo_changed('name_combo')
        # result
        self.assertEqual(presenter.connection_name, 'quisquis')
        presenter.refresh_view()  # in reality this is triggered by gtk view
        self.assertEqual(presenter.dbtype, 'PostgreSQL')
        ## if the above succeeds, the following is riggered by the view!
        #presenter.on_combo_changed('type_combo', 'PostgreSQL')
        # T_1
        self.assertTrue(presenter.view.widget_get_visible(
            'dbms_parambox'))

    def test_set_default_toggles_sensitivity(self):
        view = MockView(combos={'name_combo': [],
                                'type_combo': []})
        prefs.prefs[bauble.conn_default_pref] = 'nugkui'
        prefs.prefs[bauble.conn_list_pref] = {
            'nugkui': {'type': 'SQLite',
                       'default': True,
                       'directory': 'nugkui',
                       'file': 'nugkui.db'},
            }
        presenter = ConnMgrPresenter(view)
        view.widget_set_value('usedefaults_chkbx', True)
        presenter.on_usedefaults_chkbx_toggled('usedefaults_chkbx')
        self.assertFalse(view.widget_get_sensitive('file_entry'))

    def test_check_parameters_valid(self):
        import copy
        view = MockView(combos={'name_combo': [],
                                'type_combo': []})
        prefs.prefs[bauble.conn_default_pref] = 'quisquis'
        prefs.prefs[bauble.conn_list_pref] = {
            'quisquis': {'type': 'PostgreSQL',
                         'passwd': False,
                         'directory': '/tmp/',
                         'db': 'quisquis',
                         'host': 'localhost',
                         'user': 'pg'}}
        presenter = ConnMgrPresenter(view)
        params = presenter.connections['quisquis']
        valid, message = presenter.check_parameters_valid(params)
        self.assertTrue(valid)
        params = copy.copy(presenter.connections['quisquis'])
        params['user'] = ''
        valid, message = presenter.check_parameters_valid(params)
        self.assertFalse(valid)
        params = copy.copy(presenter.connections['quisquis'])
        params['db'] = ''
        valid, message = presenter.check_parameters_valid(params)
        self.assertFalse(valid)
        params = copy.copy(presenter.connections['quisquis'])
        params['host'] = ''
        valid, message = presenter.check_parameters_valid(params)
        self.assertFalse(valid)
        sqlite_params = {'type': 'SQLite',
                         'default': False,
                         'file': '/tmp/test.db',
                         'directory': '/tmp/'}
        params = copy.copy(sqlite_params)
        valid, message = presenter.check_parameters_valid(params)
        self.assertTrue(valid)
        params = copy.copy(sqlite_params)
        params['file'] = '/usr/bin/sh'
        valid, message = presenter.check_parameters_valid(params)
        self.assertFalse(valid)

    def test_parameters_to_uri_sqlite(self):
        view = MockView(combos={'name_combo': [],
                                'type_combo': []})
        prefs.prefs[bauble.conn_default_pref] = None
        presenter = ConnMgrPresenter(view)
        params = {'type': 'SQLite',
                  'default': False,
                  'file': '/tmp/test.db',
                  'directory': '/tmp/'}
        self.assertEqual(presenter.parameters_to_uri(params),
                          'sqlite:////tmp/test.db')
        params = {'type': 'PostgreSQL',
                  'passwd': False,
                  'directory': '/tmp/',
                  'db': 'quisquis',
                  'host': 'localhost',
                  'user': 'pg'}
        self.assertEqual(presenter.parameters_to_uri(params),
                          'postgresql://pg@localhost/quisquis')
        params = {'type': 'PostgreSQL',
                  'passwd': True,
                  'directory': '/tmp/',
                  'db': 'quisquis',
                  'host': 'localhost',
                  'user': 'pg'}
        view.reply_entry_dialog.append('secret')
        self.assertEqual(presenter.parameters_to_uri(params),
                          'postgresql://pg:secret@localhost/quisquis')
        params = {'type': 'PostgreSQL',
                  'passwd': False,
                  'directory': '/tmp/',
                  'port': '9876',
                  'db': 'quisquis',
                  'host': 'localhost',
                  'user': 'pg'}
        self.assertEqual(presenter.parameters_to_uri(params),
                          'postgresql://pg@localhost:9876/quisquis')
        params = {'type': 'PostgreSQL',
                  'passwd': True,
                  'directory': '/tmp/',
                  'port': '9876',
                  'db': 'quisquis',
                  'host': 'localhost',
                  'user': 'pg'}
        view.reply_entry_dialog.append('secret')
        self.assertEqual(presenter.parameters_to_uri(params),
                          'postgresql://pg:secret@localhost:9876/quisquis')
        params = {'type': 'PostgreSQL',
                  'passwd': False,
                  'directory': '/tmp/',
                  'options': ['is_this_possible=no',
                              'why_do_we_test=because'],
                  'db': 'quisquis',
                  'host': 'localhost',
                  'user': 'pg'}
        self.assertEqual(presenter.parameters_to_uri(params),
                          'postgresql://pg@localhost/quisquis?'
                          'is_this_possible=no&why_do_we_test=because')

    def test_connection_uri_property(self):
        view = MockView(combos={'name_combo': [],
                                'type_combo': []})
        prefs.prefs[bauble.conn_default_pref] = 'quisquis'
        prefs.prefs[bauble.conn_list_pref] = {
            'quisquis': {'type': 'PostgreSQL',
                         'passwd': False,
                         'directory': '/tmp/',
                         'db': 'quisquis',
                         'host': 'localhost',
                         'user': 'pg'}}
        presenter = ConnMgrPresenter(view)
        self.assertEqual(presenter.connection_name, 'quisquis')
        self.assertEqual(presenter.dbtype, 'PostgreSQL')
        ## we need trigger all signals that would go by gtk
        p = presenter.connections[presenter.connection_name]
        presenter.view.widget_set_value('database_entry', p['db'])
        presenter.on_text_entry_changed('database_entry')
        presenter.view.widget_set_value('user_entry', p['user'])
        presenter.on_text_entry_changed('user_entry')
        presenter.view.widget_set_value('host_entry', p['host'])
        presenter.on_text_entry_changed('host_entry')
        self.assertEqual(presenter.connection_uri,
                          'postgresql://pg@localhost/quisquis')


class AddConnectionTests(BaubleTestCase):

    def test_no_connection_on_add_confirm_negative(self):
        view = MockView(combos={'name_combo': [],
                                'type_combo': []})
        presenter = ConnMgrPresenter(view)
        presenter.view.reply_entry_dialog.append('')
        presenter.on_add_button_clicked('button')
        ## nothing changes
        self.assertFalse(presenter.view.widget_get_visible(
            'expander'))
        self.assertFalse(presenter.view.widget_get_sensitive(
            'connect_button'))
        self.assertTrue(presenter.view.widget_get_visible(
            'noconnectionlabel'))

    def test_no_connection_on_add_confirm_positive(self):
        view = MockView(combos={'name_combo': [],
                                'type_combo': []})
        presenter = ConnMgrPresenter(view)
        presenter.view.reply_entry_dialog.append('conn_name')
        presenter.on_add_button_clicked('button')
        presenter.refresh_view()  # this is done by gtk
        ## visibility swapped
        self.assertTrue(presenter.view.widget_get_visible(
            'expander'))
        self.assertTrue(presenter.view.widget_get_sensitive(
            'connect_button'))
        self.assertFalse(presenter.view.widget_get_visible(
            'noconnectionlabel'))

    def test_one_connection_on_add_confirm_positive(self):
        view = MockView(combos={'name_combo': [],
                                'type_combo': []})
        prefs.prefs[bauble.conn_list_pref] = {
            'nugkui': {'default': True,
                       'directory': 'nugkui',
                       'type': 'SQLite',
                       'file': 'nugkui.db'}}
        prefs.prefs[bauble.conn_default_pref] = 'nugkui'
        presenter = ConnMgrPresenter(view)
        presenter.view.reply_entry_dialog.append('new_conn')
        presenter.on_add_button_clicked('button')
        presenter.refresh_view()  # this is done by gtk
        self.assertTrue(('comboboxtext_prepend_text',
                         ['name_combo', 'new_conn'])
                        in presenter.view.invoked_detailed)
        self.assertTrue(('widget_set_value', ['name_combo', 'new_conn', ()])
                        in presenter.view.invoked_detailed)
        raise SkipTest("related to issue #194")

    def test_get_parent_folder(self):
        path = ConnMgrPresenter.get_parent_folder('')
        self.assertEqual(paths.appdata_dir(), path)
        path = ConnMgrPresenter.get_parent_folder(None)
        self.assertEqual(paths.appdata_dir(), path)
        relative_path = './test/this'
        path = ConnMgrPresenter.get_parent_folder(relative_path)
        self.assertEqual(
            str(Path(paths.appdata_dir(), relative_path[2:]).parent), path
        )
        absolute_path = Path(paths.appdata_dir(), relative_path[2:])
        absolute_parent = str(absolute_path.parent)
        path = ConnMgrPresenter.get_parent_folder(str(absolute_path))
        self.assertEqual(absolute_parent, path)

    def test_replace_leading_appdata(self):
        view = MockView(combos={'name_combo': [],
                                'type_combo': []})
        presenter = ConnMgrPresenter(view)
        path = str(Path(paths.appdata_dir(), 'test/this'))
        presenter.view.widget_set_value('rootdir_entry', path)
        presenter.replace_leading_appdata('rootdir_entry')
        self.assertEqual(presenter.view.widget_get_value('rootdir_entry'),
                         './test/this')


class MockRenderer(dict):
    def set_property(self, prop, value):
        self[prop] = value


class GlobalFunctionsTests(BaubleTestCase):

    def test_make_absolute(self):
        path = str(Path(paths.appdata_dir(), 'test/this'))
        self.assertEqual(bauble.connmgr.make_absolute('./test/this'),
                         path)
        path = str(Path(paths.appdata_dir(), 'test\\this'))
        self.assertEqual(bauble.connmgr.make_absolute('.\\test\\this'),
                         path)

    @mock.patch('bauble.connmgr.WORKING_DBTYPES', ['a', 'd'])
    @mock.patch('bauble.connmgr.DBTYPES', ['a', 'b', 'c', 'd'])
    def test_combo_cell_data_func(self):

        renderer = MockRenderer()
        for itr, name in enumerate(bauble.connmgr.DBTYPES):
            bauble.connmgr.type_combo_cell_data_func(
                None, renderer, bauble.connmgr.DBTYPES, itr)
            self.assertEqual(renderer['sensitive'],
                             name in bauble.connmgr.WORKING_DBTYPES)
            self.assertEqual(renderer['text'], name)

    def test_is_package_name(self):
        from bauble.connmgr import is_package_name
        self.assertTrue(is_package_name("sqlite3"))
        self.assertFalse(is_package_name("sqlheavy42"))

    def test_check_new_release(self):
        created_date = '2021-01-01T00:00:00Z'
        test_data = {'name': 'v1.3.0-a (BBG Branch)',
                     'prerelease': True,
                     'assets': [{'created_at': created_date}]}
        test_data['name'] = 'v1.3.999-a (BBG Branch)'
        self.assertEqual(check_new_release(test_data), test_data)
        test_data['name'] = 'v1.4999-a (BBG Branch)'
        self.assertEqual(check_new_release(test_data), test_data)
        test_data['name'] = 'v1.3 (BBG Branch)'
        self.assertFalse(check_new_release(test_data))
        test_data['name'] = 'v1.3.999 (MRBG Branch)'
        self.assertEqual(check_new_release(test_data), test_data)
        test_data['name'] = 'v1.3.999 (BBG Branch)'
        test_data['prerelease'] = False
        self.assertEqual(check_new_release(test_data), test_data)
        test_data['prerelease'] = True
        self.assertTrue(check_new_release(test_data) and True or False)
        test_data['name'] = 'v1.0.0 (BBG Branch)'
        test_data['prerelease'] = False
        self.assertFalse(check_new_release(test_data))
        test_data['name'] = 'v1.0.0-a (BBG Branch)'
        self.assertFalse(check_new_release(test_data))
        test_data['name'] = 'v1.0.0-b (BBG Branch)'
        self.assertFalse(check_new_release(test_data) and True or False)
        import dateutil
        self.assertEqual(bauble.release_date,
                         dateutil.parser.isoparse(created_date))

    @mock.patch('bauble.connmgr.utils.get_net_sess')
    def test_retrieve_latest_release_data_returns_none_wo_bad_response(
            self, mock_get_net_sess
    ):
        mock_response = mock.Mock()
        mock_response.json.return_value = ['test']
        mock_response.ok = False
        mock_net_sess = mock.Mock(**{'get.return_value': mock_response})
        mock_get_net_sess.return_value = mock_net_sess
        self.assertIsNone(retrieve_latest_release_data())
        mock_response.get.asset_called()
        mock_response.json.asset_not_called()

    @mock.patch('bauble.connmgr.utils.get_net_sess')
    def test_retrieve_latest_release_data_returns_none_w_error(
            self, mock_get_net_sess
    ):
        mock_net_sess = mock.Mock(**{'get.side_effect': Exception()})
        mock_get_net_sess.return_value = mock_net_sess
        with self.assertLogs(level='DEBUG') as logs:
            self.assertIsNone(retrieve_latest_release_data())
        self.assertEqual(len(logs), 2)
        self.assertEqual(
            'unhandled Exception() while checking for new release',
            logs.records[0].getMessage()
        )

    @mock.patch('bauble.connmgr.utils.get_net_sess')
    def test_retrieve_latest_release_data_returns_response(self,
                                                           mock_get_net_sess):
        mock_response = mock.Mock()
        mock_response.json.return_value = ['test']
        mock_response.ok = True
        mock_net_sess = mock.Mock(**{'get.return_value': mock_response})
        mock_get_net_sess.return_value = mock_net_sess
        self.assertEqual(retrieve_latest_release_data(), 'test')
        mock_response.get.asset_called()
        mock_response.json.asset_called()

    def test_notify_new_release_notifies_when_new_release(self):
        mock_view = mock.Mock()
        mock_retrieve_latest = mock.Mock()
        mock_check_new = mock.Mock()
        with self.assertLogs(level='DEBUG') as logs:
            notify_new_release(mock_view, mock_retrieve_latest, mock_check_new)
        mock_retrieve_latest.assert_called()
        mock_check_new.assert_called()
        self.assertEqual(
            'notifying new release',
            logs.records[0].getMessage()
        )

    def test_notify_new_release_doesnt_notify_when_not_new_release(self):
        mock_view = mock.Mock()
        mock_retrieve_latest = mock.Mock()
        mock_check_new = mock.Mock()
        mock_check_new.return_value = False
        with self.assertLogs(level='DEBUG') as logs:
            notify_new_release(mock_view, mock_retrieve_latest, mock_check_new)
        mock_retrieve_latest.assert_called()
        mock_check_new.assert_called()
        self.assertEqual(
            'not new release',
            logs.records[0].getMessage()
        )

    def test_notify_new_release_doesnt_notify_when_no_data(self):
        mock_view = mock.Mock()
        mock_retrieve_latest = mock.Mock()
        mock_retrieve_latest.return_value = None
        mock_check_new = mock.Mock()
        with self.assertLogs(level='DEBUG') as logs:
            notify_new_release(mock_view, mock_retrieve_latest, mock_check_new)
        mock_retrieve_latest.assert_called()
        mock_check_new.assert_not_called()
        self.assertEqual(
            'no release data',
            logs.records[0].getMessage()
        )

    def test_check_create_paths(self):
        temp_dir = mkdtemp()
        valid, msg = check_create_paths(temp_dir)
        self.assertTrue(valid)
        self.assertFalse(msg)
        self.assertTrue(os.path.isdir(os.path.join(temp_dir, 'pictures')))
        self.assertTrue(
            os.path.isdir(os.path.join(temp_dir, 'pictures', 'thumbs'))
        )
        self.assertTrue(os.path.isdir(os.path.join(temp_dir, 'documents')))
        temp_dir = mkdtemp()
        Path(temp_dir, 'documents').touch()
        Path(temp_dir, 'pictures').mkdir()
        Path(temp_dir, 'pictures', 'thumbs').touch()
        valid, msg = check_create_paths(temp_dir)
        self.assertFalse(valid)
        self.assertTrue(msg)
        self.assertTrue(os.path.isdir(os.path.join(temp_dir, 'pictures')))
        self.assertFalse(
            os.path.isdir(os.path.join(temp_dir, 'pictures', 'thumbs'))
        )
        self.assertFalse(os.path.isdir(os.path.join(temp_dir, 'documents')))


class ButtonBrowseButtons(BaubleTestCase):
    def test_file_chosen(self):
        view = MockView(combos={'name_combo': [],
                                'type_combo': []})
        view.reply_file_chooser_dialog.append('chosen')
        presenter = ConnMgrPresenter(view)
        presenter.on_file_btnbrowse_clicked()
        presenter.on_text_entry_changed('file_entry')
        self.assertEqual(presenter.filename, 'chosen')

    def test_file_not_chosen(self):
        view = MockView(combos={'name_combo': [],
                                'type_combo': []})
        view.reply_file_chooser_dialog = []
        presenter = ConnMgrPresenter(view)
        presenter.filename = 'previously'
        presenter.on_file_btnbrowse_clicked()
        self.assertEqual(presenter.filename, 'previously')

    def test_rootdir_chosen(self):
        view = MockView(combos={'name_combo': [],
                                'type_combo': []})
        view.reply_file_chooser_dialog.append('chosen')
        presenter = ConnMgrPresenter(view)
        presenter.on_rootdir_btnbrowse_clicked()
        presenter.on_text_entry_changed('rootdir_entry')
        self.assertEqual(presenter.rootdir, 'chosen')

    def test_rootdir_not_chosen(self):
        view = MockView(combos={'name_combo': [],
                                'type_combo': []})
        view.reply_file_chooser_dialog = []
        presenter = ConnMgrPresenter(view)
        presenter.rootdir = 'previously'
        presenter.on_rootdir_btnbrowse_clicked()
        self.assertEqual(presenter.rootdir, 'previously')

    def test_rootdir2_chosen(self):
        view = MockView(combos={'name_combo': [],
                                'type_combo': []})
        view.reply_file_chooser_dialog.append('chosen')
        presenter = ConnMgrPresenter(view)
        presenter.on_rootdir2_btnbrowse_clicked()
        presenter.on_text_entry_changed('rootdir2_entry')
        self.assertEqual(presenter.rootdir, 'chosen')

    def test_rootdir2_not_chosen(self):
        view = MockView(combos={'name_combo': [],
                                'type_combo': []})
        view.reply_file_chooser_dialog = []
        presenter = ConnMgrPresenter(view)
        presenter.rootdir = 'previously'
        presenter.on_rootdir2_btnbrowse_clicked()
        self.assertEqual(presenter.rootdir, 'previously')


class OnDialogResponseTests(BaubleTestCase):
    def test_on_dialog_response_ok_invalid_params(self):
        view = MockView(combos={'name_combo': [],
                                'type_combo': []})
        view.reply_file_chooser_dialog = []
        presenter = ConnMgrPresenter(view)
        dialog = MockDialog()
        presenter.on_dialog_response(dialog, RESPONSE_OK)
        self.assertTrue('run_message_dialog' in view.invoked)
        self.assertTrue(dialog.hidden)

    def test_on_dialog_response_ok_valid_params(self):
        view = MockView(combos={'name_combo': [],
                                'type_combo': []})
        prefs.prefs[bauble.conn_list_pref] = {
            'nugkui': {'default': False,
                       'directory': '/tmp/nugkui',
                       'type': 'SQLite',
                       'file': '/tmp/nugkui.db'}}
        prefs.prefs[bauble.conn_default_pref] = 'nugkui'
        prefs.prefs[prefs.root_directory_pref] = '/tmp'
        view.reply_file_chooser_dialog = []
        presenter = ConnMgrPresenter(view)
        dialog = MockDialog()
        view.invoked = []
        presenter.on_dialog_response(dialog, RESPONSE_OK)
        self.assertFalse('run_message_dialog' in view.invoked)
        self.assertTrue(dialog.hidden)
        self.assertEqual(prefs.prefs[prefs.picture_root_pref],
                         '/tmp/nugkui/pictures')

    def test_on_dialog_response_cancel(self):
        view = MockView(combos={'name_combo': [],
                                'type_combo': []})
        view.reply_file_chooser_dialog = []
        presenter = ConnMgrPresenter(view)
        dialog = MockDialog()
        view.reply_yes_no_dialog = [False]
        presenter.on_dialog_response(dialog, RESPONSE_CANCEL)
        self.assertFalse('run_message_dialog' in view.invoked)
        self.assertTrue(dialog.hidden)

    def test_on_dialog_response_cancel_params_changed(self):
        view = MockView(combos={'name_combo': [],
                                'type_combo': []})
        prefs.prefs[bauble.conn_list_pref] = {
            'nugkui': {'default': False,
                       'directory': '/tmp/nugkui',
                       'type': 'SQLite',
                       'file': '/tmp/nugkui.db'}}
        prefs.prefs[bauble.conn_default_pref] = 'nugkui'
        view.reply_file_chooser_dialog = []
        presenter = ConnMgrPresenter(view)
        ## change something
        view.widget_set_value('usedefaults_chkbx', True)
        presenter.on_usedefaults_chkbx_toggled('usedefaults_chkbx')
        ## press escape
        dialog = MockDialog()
        view.reply_yes_no_dialog = [True]
        view.invoked = []
        presenter.on_dialog_response(dialog, RESPONSE_CANCEL)
        ## question was asked whether to save
        self.assertFalse('run_message_dialog' in view.invoked)
        self.assertTrue('run_yes_no_dialog' in view.invoked)
        self.assertTrue(dialog.hidden)

    def test_on_dialog_close_or_delete(self):
        view = MockView(combos={'name_combo': [],
                                'type_combo': []})
        view.reply_file_chooser_dialog = []
        presenter = ConnMgrPresenter(view)
        # T_0
        self.assertFalse(view.get_window().hidden)
        # action
        presenter.on_dialog_close_or_delete("widget")
        # T_1
        self.assertTrue(view.get_window().hidden)

    def test_on_dialog_response_ok_creates_picture_folders_exist(self):
        # make sure thumbnails and pictures folder already exist as folders.
        # create view and presenter
        # invoke action
        # superfluous action is not performed, view is closed
        raise SkipTest('related to issue 157')

    def test_on_dialog_response_ok_creates_picture_folders_half_exist(self):
        # make sure pictures and thumbs folders respectively do and do not
        # already exist as folders.
        import tempfile
        fd, path = tempfile.mkstemp()
        os.close(fd)
        os.unlink(path)
        os.mkdir(path)
        view = MockView(combos={'name_combo': [],
                                'type_combo': []})
        prefs.prefs[bauble.conn_list_pref] = {
            'nugkui': {'default': False,
                       'directory': path,
                       'type': 'SQLite',
                       'file': path + '.db'}}
        (prefs.prefs[prefs.root_directory_pref],
         prefs.prefs[bauble.conn_default_pref],
         ) = os.path.split(path)
        view.reply_file_chooser_dialog = []
        presenter = ConnMgrPresenter(view)
        dialog = MockDialog()
        view.invoked = []
        # invoke action
        presenter.on_dialog_response(dialog, RESPONSE_OK)

        # superfluous action is not performed, view is closed
        # check existence of pictures folder
        self.assertTrue(os.path.isdir(path))
        # check existence of thumbnails folder
        self.assertTrue(
            os.path.isdir(os.path.join(path, 'pictures', 'thumbs'))
        )

    def test_on_dialog_response_ok_creates_picture_folders_no_exist(self):
        # make sure thumbnails and pictures folder do not exist.
        import tempfile
        fd, path = tempfile.mkstemp()
        os.close(fd)
        os.unlink(path)
        # create view and presenter.
        view = MockView(combos={'name_combo': [],
                                'type_combo': []})
        prefs.prefs[bauble.conn_list_pref] = {
            'nugkui': {'default': False,
                       'directory': path,
                       'type': 'SQLite',
                       'file': path + '.db'}}
        (prefs.prefs[prefs.picture_root_pref],
         prefs.prefs[bauble.conn_default_pref],
         ) = os.path.split(path)
        view.reply_file_chooser_dialog = []
        presenter = ConnMgrPresenter(view)
        dialog = MockDialog()
        view.invoked = []
        # invoke action
        presenter.on_dialog_response(dialog, RESPONSE_OK)

        # check existence of pictures folder
        self.assertTrue(os.path.isdir(path))
        # check existence of thumbnails folder
        self.assertTrue(
            os.path.isdir(os.path.join(path, 'pictures', 'thumbs'))
        )

    def test_on_dialog_response_ok_creates_picture_folders_occupied(self):
        # make sure thumbnails and pictures folder already exist as files
        # create view and presenter
        # invoke action
        # action is not performed, view is not closed
        raise SkipTest('related to issue 157')
