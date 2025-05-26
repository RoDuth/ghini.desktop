# Copyright (c) 2015 Mario Frasca <mario@anche.no>
# Copyright (c) 2022-2025 Ross Demuth <rossdemuth123@gmail.com>
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

import copy
import os
from pathlib import Path
from tempfile import mkdtemp
from tempfile import mkstemp
from unittest import mock

import dateutil
import gi
import pyodbc
from sqlalchemy.engine import make_url

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa

import bauble
from bauble import paths
from bauble import prefs
from bauble.connmgr import DBTYPES
from bauble.connmgr import ConnectionManagerDialog
from bauble.connmgr import check_create_paths
from bauble.connmgr import check_new_release
from bauble.connmgr import is_package_name
from bauble.connmgr import notify_new_release
from bauble.connmgr import retrieve_latest_release_data
from bauble.connmgr import start_connection_manager
from bauble.test import BaubleTestCase
from bauble.test import check_dupids
from bauble.test import update_gui

RESPONSE_OK = Gtk.ResponseType.OK
RESPONSE_CANCEL = Gtk.ResponseType.CANCEL

TEMP_ROOT = mkdtemp()


def test_duplicate_ids():
    """Test for duplicate ids for all .ui file."""
    import bauble.connmgr as mod

    head, _tail = os.path.split(mod.__file__)
    assert not check_dupids(os.path.join(head, "connmgr.ui"))


class ConnectionManagerTests(BaubleTestCase):
    "Presenter manages view and model, implements view callbacks."

    def test_can_create_presenter(self):
        presenter = ConnectionManagerDialog()
        self.assertIsNotNone(presenter)
        presenter.destroy()

    def test_no_connections_then_message(self):
        presenter = ConnectionManagerDialog()

        self.assertFalse(presenter.expander.get_visible())
        self.assertTrue(presenter.noconnectionlabel.get_visible())
        presenter.destroy()

    def test_one_connection_shown_removed_message(self):
        prefs.prefs[bauble.CONN_LIST_PREF] = {
            "nugkui": {
                "default": True,
                "directory": "./nugkui",
                "type": "SQLite",
                "file": "./nugkui.db",
            }
        }
        presenter = ConnectionManagerDialog()
        # T_0
        self.assertTrue(presenter.expander.get_visible())
        self.assertFalse(presenter.noconnectionlabel.get_visible())
        # action
        presenter.remove_connection("nugkui")
        # T_1
        self.assertFalse(presenter.expander.get_visible())
        self.assertTrue(presenter.noconnectionlabel.get_visible())
        presenter.destroy()

    @mock.patch("bauble.connmgr.utils.yes_no_dialog")
    def test_on_remove_no_connection_name_bails(self, mock_dialog):
        presenter = ConnectionManagerDialog()
        presenter.connection_name = None
        presenter.on_remove_button_clicked("button")
        # nothing changes
        mock_dialog.assert_not_called()
        presenter.destroy()

    @mock.patch("bauble.connmgr.utils.yes_no_dialog")
    def test_one_connection_on_remove_confirm_negative(self, mock_dialog):
        mock_dialog.return_value = False
        prefs.prefs[bauble.CONN_LIST_PREF] = {
            "nugkui": {
                "default": True,
                "directory": "./nugkui",
                "type": "SQLite",
                "file": "./nugkui.db",
            }
        }
        presenter = ConnectionManagerDialog()
        presenter.on_remove_button_clicked("button")
        # nothing changes
        self.assertTrue(presenter.expander.get_visible())
        self.assertFalse(presenter.noconnectionlabel.get_visible())
        presenter.destroy()

    @mock.patch("bauble.connmgr.utils.yes_no_dialog")
    def test_one_connection_on_remove_confirm_positive(self, mock_dialog):
        mock_dialog.return_value = True
        prefs.prefs[bauble.CONN_LIST_PREF] = {
            "nugkui": {
                "default": True,
                "directory": "./nugkui",
                "type": "SQLite",
                "file": "./nugkui.db",
            }
        }
        presenter = ConnectionManagerDialog()
        presenter.on_remove_button_clicked("button")
        # visibility swapped
        self.assertFalse(presenter.expander.get_visible())
        self.assertTrue(presenter.noconnectionlabel.get_visible())
        presenter.destroy()

    def test_two_connection_initialize_default_first(self):
        prefs.prefs[bauble.CONN_LIST_PREF] = {
            "nugkui": {
                "default": True,
                "directory": "./nugkui",
                "type": "SQLite",
                "file": "./nugkui.db",
            },
            "btuu": {
                "default": False,
                "directory": "btuu",
                "type": "SQLite",
                "file": "btuu.db",
            },
        }
        prefs.prefs[bauble.CONN_DEFAULT_PREF] = "nugkui"
        presenter = ConnectionManagerDialog()
        self.assertEqual(presenter.connection_name, "nugkui")
        params = presenter.connections[presenter.connection_name]
        self.assertEqual(params["default"], True)
        self.assertTrue(presenter.usedefaults_chkbx.get_active())
        presenter.destroy()

    def test_two_connection_initialize_default_second(self):
        prefs.prefs[bauble.CONN_LIST_PREF] = {
            "nugkui": {
                "default": True,
                "directory": "./nugkui",
                "type": "SQLite",
                "file": "./nugkui.db",
            },
            "btuu": {
                "default": False,
                "directory": "btuu",
                "type": "SQLite",
                "file": "btuu.db",
            },
        }
        prefs.prefs[bauble.CONN_DEFAULT_PREF] = "btuu"
        presenter = ConnectionManagerDialog()
        self.assertEqual(presenter.connection_name, "btuu")
        params = presenter.connections[presenter.connection_name]
        self.assertEqual(params["default"], False)
        self.assertFalse(presenter.usedefaults_chkbx.get_active())
        presenter.destroy()

    @mock.patch("bauble.connmgr.utils.yes_no_dialog")
    def test_two_connection_on_remove_confirm_positive(self, mock_dialog):
        mock_dialog.return_value = True
        prefs.prefs[bauble.CONN_LIST_PREF] = {
            "nugkui": {
                "default": True,
                "directory": "./nugkui",
                "type": "SQLite",
                "file": "./nugkui.db",
            },
            "btuu": {
                "default": True,
                "directory": "btuu",
                "type": "SQLite",
                "file": "btuu.db",
            },
        }
        presenter = ConnectionManagerDialog()
        presenter.on_remove_button_clicked("button")
        # visibility same
        self.assertTrue(presenter.expander.get_visible())
        self.assertFalse(presenter.noconnectionlabel.get_visible())
        presenter.destroy()

    def test_one_connection_shown_and_selected_sqlite(self):
        prefs.prefs[bauble.CONN_LIST_PREF] = {
            "nugkui": {
                "default": True,
                "directory": "nugkui",
                "type": "SQLite",
                "file": "nugkui.db",
            }
        }
        prefs.prefs[bauble.CONN_DEFAULT_PREF] = "nugkui"
        presenter = ConnectionManagerDialog()
        self.assertEqual(presenter.connection_name, "nugkui")
        self.assertTrue(presenter.expander.get_visible())
        self.assertFalse(presenter.noconnectionlabel.get_visible())
        presenter.destroy()

    def test_one_connection_shown_and_selected_postgresql(self):
        prefs.prefs[bauble.CONN_LIST_PREF] = {
            "quisquis": {
                "passwd": False,
                "directory": "",
                "db": "quisquis",
                "host": "localhost",
                "user": "pg",
                "type": "PostgreSQL",
            }
        }
        prefs.prefs[bauble.CONN_DEFAULT_PREF] = "quisquis"
        presenter = ConnectionManagerDialog()
        self.assertEqual(presenter.connection_name, "quisquis")
        self.assertTrue(presenter.expander.get_visible())
        self.assertTrue(presenter.dbms_parambox.get_visible())
        self.assertFalse(presenter.sqlite_parambox.get_visible())
        self.assertFalse(presenter.noconnectionlabel.get_visible())
        presenter.destroy()

    def test_one_connection_shown_and_selected_unknown_oracle(self):
        prefs.prefs[bauble.CONN_LIST_PREF] = {
            "quisquis": {
                "passwd": False,
                "directory": "",
                "db": "quisquis",
                "host": "localhost",
                "user": "pg",
                "type": "Oracle",
            }
        }
        prefs.prefs[bauble.CONN_DEFAULT_PREF] = "quisquis"
        presenter = ConnectionManagerDialog()
        self.assertIsNone(presenter.connection_name)
        self.assertFalse(presenter.expander.get_visible())
        self.assertFalse(presenter.dbms_parambox.get_visible())
        self.assertFalse(presenter.sqlite_parambox.get_visible())
        self.assertTrue(presenter.noconnectionlabel.get_visible())
        presenter.destroy()

    def test_one_connection_shown_and_selected_mssql_w_options(self):
        prefs.prefs[bauble.CONN_LIST_PREF] = {
            "quisquis": {
                "passwd": False,
                "directory": "",
                "db": "quisquis",
                "host": "localhost",
                "user": "foo",
                "type": "MSSQL",
                "options": {
                    "driver": "ODBC Driver 17 for SQL Server",
                    "MARS_Connection": "Yes",
                },
            }
        }
        prefs.prefs[bauble.CONN_DEFAULT_PREF] = "quisquis"
        presenter = ConnectionManagerDialog()
        self.assertEqual(presenter.connection_name, "quisquis")
        self.assertTrue(presenter.expander.get_visible())
        self.assertTrue(presenter.dbms_parambox.get_visible())
        self.assertFalse(presenter.sqlite_parambox.get_visible())
        self.assertFalse(presenter.noconnectionlabel.get_visible())
        self.assertEqual(len(presenter.options_liststore), 3)
        presenter.destroy()

    def test_two_connections_wrong_default_use_first_one(self):
        prefs.prefs[bauble.CONN_DEFAULT_PREF] = "nugkui"
        prefs.prefs[bauble.CONN_LIST_PREF] = {
            "nugkui": {
                "default": True,
                "directory": "./nugkui",
                "type": "SQLite",
                "file": "./nugkui.db",
            },
            "quisquis": {
                "passwd": False,
                "directory": "",
                "db": "quisquis",
                "host": "localhost",
                "user": "pg",
                "type": "MSSQL",
            },
        }
        prefs.prefs[bauble.CONN_DEFAULT_PREF] = "nonce"
        presenter = ConnectionManagerDialog()
        as_list = presenter.connection_names
        self.assertEqual(presenter.connection_name, as_list[0])
        presenter.destroy()

    def test_when_user_selects_different_type(self):
        prefs.prefs[bauble.CONN_DEFAULT_PREF] = "nugkui"
        prefs.prefs[bauble.CONN_LIST_PREF] = {
            "nugkui": {
                "type": "SQLite",
                "default": True,
                "directory": "./nugkui",
                "file": "./nugkui.db",
            },
            "quisquis": {
                "type": "PostgreSQL",
                "passwd": False,
                "directory": "",
                "db": "quisquis",
                "host": "localhost",
                "user": "pg",
            },
        }
        presenter = ConnectionManagerDialog()
        # T_0
        self.assertEqual(presenter.connection_name, "nugkui")
        self.assertTrue(presenter.sqlite_parambox.get_visible())
        self.assertFalse(presenter.dbms_parambox.get_visible())
        # action
        presenter.name_combo.set_active(1)
        # result
        self.assertEqual(presenter.connection_name, "quisquis")
        self.assertEqual(presenter.dbtype, "PostgreSQL")
        # T_1
        self.assertTrue(presenter.dbms_parambox.get_visible())
        self.assertFalse(presenter.sqlite_parambox.get_visible())
        presenter.destroy()

    def test_set_default_toggles_sensitivity_sets_default(self):
        prefs.prefs[bauble.CONN_DEFAULT_PREF] = "nugkui"
        prefs.prefs[bauble.CONN_LIST_PREF] = {
            "nugkui": {
                "type": "SQLite",
                "default": False,
                "directory": "/somewhere/else",
                "file": "/spam.db",
            },
        }
        presenter = ConnectionManagerDialog()
        presenter.usedefaults_chkbx.set_active(True)
        self.assertFalse(presenter.file_entry.get_sensitive())
        self.assertEqual(presenter.connection_name, "nugkui")
        self.assertEqual(presenter.rootdir_entry.get_text(), "./nugkui")
        self.assertEqual(presenter.file_entry.get_text(), "./nugkui.db")
        presenter.destroy()

    def test_check_parameters_valid_not_sqlite(self):
        prefs.prefs[bauble.CONN_DEFAULT_PREF] = "quisquis"
        prefs.prefs[bauble.CONN_LIST_PREF] = {
            "quisquis": {
                "type": "PostgreSQL",
                "passwd": False,
                "directory": f"{TEMP_ROOT}/",
                "db": "quisquis",
                "host": "localhost",
                "user": "pg",
            }
        }
        presenter = ConnectionManagerDialog()
        params = presenter.connections["quisquis"]
        valid, message = presenter.check_parameters_valid(params)
        self.assertTrue(valid)
        self.assertFalse(message)
        params = copy.copy(presenter.connections["quisquis"])
        params["user"] = ""
        valid, message = presenter.check_parameters_valid(params)
        self.assertFalse(valid)
        self.assertTrue(message)
        params = copy.copy(presenter.connections["quisquis"])
        params["db"] = ""
        valid, message = presenter.check_parameters_valid(params)
        self.assertFalse(valid)
        self.assertTrue(message)
        params = copy.copy(presenter.connections["quisquis"])
        params["host"] = ""
        valid, message = presenter.check_parameters_valid(params)
        self.assertFalse(valid)
        self.assertTrue(message)
        presenter.destroy()

    def test_check_parameters_valid_sqlite(self):
        sqlite_params = {
            "type": "SQLite",
            "default": False,
            "file": f"{TEMP_ROOT}/test.db",
            "directory": f"{TEMP_ROOT}/",
        }
        presenter = ConnectionManagerDialog()
        params = copy.copy(sqlite_params)
        valid, message = presenter.check_parameters_valid(params)
        self.assertTrue(valid)
        self.assertFalse(message)
        # file doesnt exists and is not readable
        with mock.patch("os.access") as mock_access:
            mock_access.return_value = False
            valid, message = presenter.check_parameters_valid(params)
            self.assertFalse(valid)
            self.assertTrue(message)
        # file doesn't exist and isn't writable

        def access_not_writable(_path, mode):
            if mode == os.W_OK:
                return False
            return True

        with mock.patch("os.access") as mock_access:

            mock_access.side_effect = access_not_writable
            mock_access.return_value = False
            valid, message = presenter.check_parameters_valid(params)
            self.assertFalse(valid)
            self.assertTrue(message)
        # file exists and is read and writable
        handle, path = mkstemp()
        params = copy.copy(sqlite_params)
        params["file"] = path
        valid, message = presenter.check_parameters_valid(params)
        self.assertTrue(valid)
        self.assertFalse(message)
        os.close(handle)
        os.unlink(path)
        # file exists, directory not readable
        handle, path = mkstemp()
        params = copy.copy(sqlite_params)
        params["file"] = path
        with mock.patch("os.access") as mock_access:
            mock_access.return_value = False
            valid, message = presenter.check_parameters_valid(params)
            self.assertFalse(valid)
            self.assertTrue(message)

        os.close(handle)
        os.unlink(path)
        # file exists, directory not writable
        handle, path = mkstemp()
        params = copy.copy(sqlite_params)
        params["file"] = path
        with mock.patch("os.access") as mock_access:

            mock_access.side_effect = access_not_writable
            valid, message = presenter.check_parameters_valid(params)
            self.assertFalse(valid)
            self.assertTrue(message)

        os.close(handle)
        os.unlink(path)
        presenter.destroy()

    def test_check_parameters_valid_no_name(self):
        presenter = ConnectionManagerDialog()
        params = {
            "type": "PostgreSQL",
            "passwd": False,
            "directory": f"{TEMP_ROOT}/",
            "db": "",
            "host": "localhost",
            "user": "pg",
        }
        with mock.patch.object(presenter, "name_combo") as mock_combo:
            mock_combo.get_active_text.return_value = ""
            valid, message = presenter.check_parameters_valid(params)
        self.assertFalse(valid)
        self.assertEqual(message, "Please choose a name for this connection")

    def test_check_parameters_valid_sqlite_no_file(self):
        presenter = ConnectionManagerDialog()
        params = {
            "type": "SQLite",
            "default": False,
            "file": "",
            "directory": f"{TEMP_ROOT}/",
        }
        valid, message = presenter.check_parameters_valid(params)
        self.assertFalse(valid)
        self.assertEqual(message, "Please specify a database file name")

    def test_parameters_to_uri_sqlite(self):
        prefs.prefs[bauble.CONN_DEFAULT_PREF] = None
        presenter = ConnectionManagerDialog()
        params = {
            "type": "SQLite",
            "default": False,
            "file": "/tmp/test.db",
            "directory": "/tmp/",
        }
        self.assertEqual(
            presenter.parameters_to_uri(params),
            make_url("sqlite:////tmp/test.db"),
        )
        presenter.destroy()

    def test_parameters_to_uri_postgres(self):
        presenter = ConnectionManagerDialog()
        params = {
            "type": "PostgreSQL",
            "passwd": False,
            "directory": f"{TEMP_ROOT}/",
            "db": "quisquis",
            "host": "localhost",
            "user": "pg",
        }
        self.assertEqual(
            presenter.parameters_to_uri(params),
            make_url("postgresql://pg@localhost/quisquis"),
        )
        params = {
            "type": "PostgreSQL",
            "passwd": True,
            "directory": f"{TEMP_ROOT}/",
            "db": "quisquis",
            "host": "localhost",
            "user": "pg",
        }
        with mock.patch.object(presenter, "get_passwd") as mock_get_passwd:
            mock_get_passwd.return_value = "secret"
            self.assertEqual(
                presenter.parameters_to_uri(params),
                make_url("postgresql://pg:secret@localhost/quisquis"),
            )
        params = {
            "type": "PostgreSQL",
            "passwd": False,
            "directory": f"{TEMP_ROOT}/",
            "port": "9876",
            "db": "quisquis",
            "host": "localhost",
            "user": "pg",
        }
        self.assertEqual(
            presenter.parameters_to_uri(params),
            make_url("postgresql://pg@localhost:9876/quisquis"),
        )
        params = {
            "type": "PostgreSQL",
            "passwd": True,
            "directory": f"{TEMP_ROOT}/",
            "port": "9876",
            "db": "quisquis",
            "host": "localhost",
            "user": "pg",
        }
        with mock.patch.object(presenter, "get_passwd") as mock_get_passwd:
            mock_get_passwd.return_value = "secret"
            self.assertEqual(
                presenter.parameters_to_uri(params),
                make_url("postgresql://pg:secret@localhost:9876/quisquis"),
            )
        presenter.destroy()

    def test_parameters_to_uri_mssql(self):
        presenter = ConnectionManagerDialog()
        params = {
            "passwd": True,
            "directory": "",
            "db": "quisquis",
            "port": "9876",
            "host": "localhost",
            "user": "foo",
            "type": "MSSQL",
            "options": {
                "driver": "ODBC Driver 17 for SQL Server",
                "MARS_Connection": "Yes",
            },
        }
        with mock.patch.object(presenter, "get_passwd") as mock_get_passwd:
            mock_get_passwd.return_value = "secret"
            self.assertEqual(
                presenter.parameters_to_uri(params),
                make_url(
                    "mssql://foo:secret@localhost:9876/quisquis"
                    "?driver=ODBC+Driver+17+for+SQL+Server"
                    "&MARS_Connection=Yes"
                ),
            )
        presenter.destroy()

    def test_connection_uri_property(self):
        prefs.prefs[bauble.CONN_DEFAULT_PREF] = "quisquis"
        prefs.prefs[bauble.CONN_LIST_PREF] = {
            "quisquis": {
                "type": "PostgreSQL",
                "passwd": False,
                "directory": f"{TEMP_ROOT}/",
                "db": "quisquis",
                "host": "localhost",
                "port": "9876",
                "user": "pg",
            }
        }
        presenter = ConnectionManagerDialog()
        self.assertEqual(presenter.connection_name, "quisquis")
        self.assertEqual(presenter.dbtype, "PostgreSQL")
        self.assertEqual(
            presenter.connection_uri,
            make_url("postgresql://pg@localhost:9876/quisquis"),
        )
        # change it
        presenter.database_entry.set_text("new_db")
        presenter.user_entry.set_text("new_user")
        presenter.host_entry.set_text("new_host")
        presenter.port_entry.set_text("1234")
        presenter.passwd_chkbx.set_active(True)
        params = presenter.get_params()
        self.assertEqual(params["db"], "new_db")
        self.assertEqual(params["user"], "new_user")
        self.assertEqual(params["host"], "new_host")
        self.assertEqual(params["port"], "1234")
        self.assertTrue(params["passwd"])
        with mock.patch.object(presenter, "get_passwd") as mock_get_passwd:
            mock_get_passwd.return_value = "new_secret"
            self.assertEqual(
                presenter.connection_uri,
                make_url(
                    "postgresql://new_user:new_secret@new_host:1234/new_db"
                ),
            )
        presenter.destroy()

    def test_save_to_current_prefs_no_connection_bails(self):
        presenter = ConnectionManagerDialog()
        presenter.connection_name = None

        with self.assertNoLogs(level="DEBUG"):
            presenter.save_current_to_prefs()

        presenter.destroy()

    def test_save_to_current_prefs_no_pref_creates(self):
        presenter = ConnectionManagerDialog()
        del prefs.prefs[bauble.CONN_LIST_PREF]
        presenter.connection_name = "spam"
        presenter.filename = "./spam.db"
        presenter.rootdir = "./spam"
        presenter.dbtype = "SQLite"
        presenter.use_defaults = False

        self.assertNotIn(bauble.CONN_LIST_PREF, prefs.prefs)

        presenter.save_current_to_prefs()

        self.assertIn(bauble.CONN_LIST_PREF, prefs.prefs)
        conn_list = prefs.prefs[bauble.CONN_LIST_PREF]
        # pylint: disable=unsubscriptable-object
        self.assertEqual(conn_list["spam"]["file"], "./spam.db")
        self.assertEqual(conn_list["spam"]["directory"], "./spam")

        presenter.destroy()

    def test_are_prefs_already_saved(self):
        presenter = ConnectionManagerDialog()
        # no connection_name

        self.assertTrue(presenter.are_prefs_already_saved(None))

        # prefs with out the connection name
        prefs.prefs[bauble.CONN_LIST_PREF] = {}

        self.assertFalse(presenter.are_prefs_already_saved("spam"))

        # prefs with connection name and equal
        presenter.connection_name = "spam"
        presenter.filename = "./spam.db"
        presenter.rootdir = "./spam"
        presenter.dbtype = "SQLite"
        presenter.use_defaults = False
        prefs.prefs[bauble.CONN_LIST_PREF] = {
            "spam": {
                "default": False,
                "directory": "./spam",
                "type": "SQLite",
                "file": "./spam.db",
            }
        }

        self.assertTrue(presenter.are_prefs_already_saved("spam"))

        # prefs with connection name and not equal
        presenter.rootdir = "./spam_and_eggs"

        self.assertFalse(presenter.are_prefs_already_saved("spam"))

        presenter.destroy()

    @mock.patch("bauble.connmgr.utils.yes_no_dialog")
    def test_on_name_combo_changed_asks_saves_unsaved(self, mock_yn):
        mock_yn.return_value = True
        presenter = ConnectionManagerDialog()
        # no connection_name
        presenter.prev_connection_name = "spam"
        presenter.connection_names = ["spam", "eggs"]

        with mock.patch.object(
            presenter, "save_current_to_prefs"
        ) as mock_save:
            presenter.on_name_combo_changed(presenter.name_combo)
            mock_save.assert_called()

        presenter.destroy()

    @mock.patch("bauble.connmgr.utils.yes_no_dialog")
    def test_on_name_combo_changed_asks_removes_unsaved(self, mock_yn):
        mock_yn.return_value = False
        presenter = ConnectionManagerDialog()
        # no connection_name
        presenter.prev_connection_name = "spam"
        presenter.connection_names = ["spam", "eggs"]

        with (
            mock.patch.object(presenter, "save_current_to_prefs") as mock_save,
            mock.patch.object(presenter, "remove_connection") as mock_remove,
        ):
            presenter.on_name_combo_changed(presenter.name_combo)
            mock_save.assert_not_called()
            mock_remove.assert_called_once_with("spam")

        presenter.destroy()

    def test_get_passwd(self):
        presenter = ConnectionManagerDialog()
        with mock.patch.object(presenter, "run_entry_dialog") as mock_dlog:
            mock_dlog.return_value = "secret"
            passwd = presenter.get_passwd()
        self.assertEqual(passwd, "secret")
        mock_dlog.assert_called_once_with("Enter your password", visible=False)
        presenter.destroy()

    @mock.patch("bauble.connmgr.Gtk.Entry.get_text")
    @mock.patch("bauble.connmgr.Gtk.Dialog.run")
    def test_run_entry_dialog(self, mock_run, mock_get_text):
        mock_run.return_value = Gtk.ResponseType.ACCEPT
        mock_get_text.return_value = "spam"
        presenter = ConnectionManagerDialog()
        result = presenter.run_entry_dialog("Enter your name", visible=False)
        self.assertEqual(result, "spam")
        presenter.destroy()

    def test_set_params_no_connection_name_bails(self):
        presenter = ConnectionManagerDialog()
        presenter.connection_name = None
        self.assertEqual(presenter.filename, "")
        params = {
            "type": "SQLite",
            "default": False,
            "file": "./test.db",
            "directory": "./test",
        }
        presenter.set_params(params)
        self.assertEqual(presenter.filename, "")
        self.assertEqual(presenter.rootdir, "")
        self.assertEqual(presenter.dbtype, "")
        presenter.destroy()

    def test_set_defaults_only_sets_when_name_available(self):
        presenter = ConnectionManagerDialog()
        presenter.connection_name = None
        presenter.set_defaults()
        self.assertEqual(presenter.filename, "")
        self.assertEqual(presenter.rootdir, "")
        presenter.set_defaults("spam")
        self.assertEqual(presenter.filename, "./spam.db")
        self.assertEqual(presenter.rootdir, "./spam")
        presenter.connection_name = "eggs"
        presenter.set_defaults()
        self.assertEqual(presenter.filename, "./eggs.db")
        self.assertEqual(presenter.rootdir, "./eggs")
        presenter.destroy()


class OptionsTests(BaubleTestCase):
    def test_on_options_edited(self):
        presenter = ConnectionManagerDialog()
        self.assertEqual(len(presenter.options_liststore), 1)
        presenter.on_options_name_edited("entry", 0, "spam")
        presenter.on_options_value_edited("entry", 0, "eggs")

        self.assertEqual(len(presenter.options_liststore), 2)
        self.assertEqual(presenter.options, {"spam": "eggs"})

        presenter.destroy()

    def test_new_mssql_adds_sensible_defaults(self):
        presenter = ConnectionManagerDialog()
        with mock.patch.object(presenter, "run_entry_dialog") as mock_dlog:
            mock_dlog.return_value = "spam"
            presenter.on_add_button_clicked("button")

        self.assertEqual(presenter.connection_name, "spam")

        presenter.type_combo.set_active(DBTYPES.index("MSSQL"))

        self.assertEqual(len(presenter.options_liststore), 3)
        self.assertEqual(presenter.options_liststore[0][0], "driver")
        self.assertEqual(
            presenter.options_liststore[0][1], pyodbc.drivers()[0]
        )
        self.assertEqual(presenter.options_liststore[1][0], "MARS_Connection")
        self.assertEqual(presenter.options_liststore[1][1], "Yes")

        presenter.destroy()

    def test_existing_mssql_dont_add_sensible_defaults(self):
        prefs.prefs[bauble.CONN_LIST_PREF] = {
            "quisquis": {
                "passwd": False,
                "directory": "",
                "db": "quisquis",
                "host": "localhost",
                "port": "9876",
                "user": "foo",
                "type": "MSSQL",
                "options": {
                    "driver": "Fake driver",
                    "MARS_Connection": "No",
                },
            }
        }
        presenter = ConnectionManagerDialog()

        self.assertEqual(presenter.connection_name, "quisquis")
        self.assertEqual(presenter.options_liststore[0][0], "driver")
        self.assertEqual(presenter.options_liststore[0][1], "Fake driver")
        self.assertEqual(presenter.options_liststore[1][0], "MARS_Connection")
        self.assertEqual(presenter.options_liststore[1][1], "No")

        presenter.type_combo.set_active(DBTYPES.index("SQLite"))
        presenter.type_combo.set_active(DBTYPES.index("MSSQL"))

        self.assertEqual(presenter.options_liststore[0][0], "driver")
        self.assertEqual(presenter.options_liststore[0][1], "Fake driver")
        self.assertEqual(presenter.options_liststore[1][0], "MARS_Connection")
        self.assertEqual(presenter.options_liststore[1][1], "No")

        presenter.destroy()


class AddConnectionTests(BaubleTestCase):

    def test_on_add_button_clicked_no_name_bails(self):
        presenter = ConnectionManagerDialog()
        with mock.patch.object(presenter, "run_entry_dialog") as mock_dlog:
            mock_dlog.return_value = None
            presenter.on_add_button_clicked("button")
        # nothing changes
        self.assertFalse(presenter.expander.get_visible())
        self.assertFalse(presenter.connect_button.get_sensitive())
        self.assertTrue(presenter.noconnectionlabel.get_visible())
        self.assertEqual(presenter.connection_names, [])
        presenter.destroy()

    @mock.patch("bauble.connmgr.utils.yes_no_dialog")
    def test_on_add_button_clicked_w_changes_asks_to_save(self, mock_yn):
        mock_yn.return_value = True
        prefs.prefs[bauble.CONN_LIST_PREF] = {
            "nugkui": {
                "default": False,
                "directory": "./nugkui",
                "type": "SQLite",
                "file": "./nugkui.db",
            }
        }
        presenter = ConnectionManagerDialog()
        presenter.rootdir = "./eggs"
        # change something
        with mock.patch.object(presenter, "run_entry_dialog") as mock_dlog:
            mock_dlog.return_value = "spam"
            presenter.on_add_button_clicked("button")

        mock_yn.assert_called_once()
        conn_list = prefs.prefs[bauble.CONN_LIST_PREF]
        # pylint: disable=unsubscriptable-object
        self.assertEqual(conn_list["nugkui"]["directory"], "./eggs")
        self.assertEqual(conn_list["nugkui"]["type"], "SQLite")
        self.assertEqual(conn_list["nugkui"]["file"], "./nugkui.db")
        params = presenter.get_params()
        self.assertEqual(params["directory"], "./spam")
        self.assertEqual(params["file"], "./spam.db")

        presenter.destroy()

    def test_no_connection_on_add_confirm_negative(self):
        presenter = ConnectionManagerDialog()
        with mock.patch.object(presenter, "run_entry_dialog") as mock_dlog:
            mock_dlog.return_value = ""
            presenter.on_add_button_clicked("button")
        # nothing changes
        self.assertFalse(presenter.expander.get_visible())
        self.assertFalse(presenter.connect_button.get_sensitive())
        self.assertTrue(presenter.noconnectionlabel.get_visible())
        presenter.destroy()

    def test_no_connection_on_add_confirm_positive(self):
        presenter = ConnectionManagerDialog()
        with mock.patch.object(presenter, "run_entry_dialog") as mock_dlog:
            mock_dlog.return_value = "spam"
            presenter.on_add_button_clicked("button")
        # visibility swapped
        self.assertTrue(presenter.expander.get_visible())
        self.assertTrue(presenter.connect_button.get_sensitive())
        self.assertFalse(presenter.noconnectionlabel.get_visible())
        presenter.destroy()

    def test_one_connection_on_add_confirm_positive(self):
        prefs.prefs[bauble.CONN_LIST_PREF] = {
            "nugkui": {
                "default": True,
                "directory": "./nugkui",
                "type": "SQLite",
                "file": "./nugkui.db",
            }
        }
        prefs.prefs[bauble.CONN_DEFAULT_PREF] = "nugkui"

        presenter = ConnectionManagerDialog()
        with mock.patch.object(presenter, "run_entry_dialog") as mock_dlog:
            mock_dlog.return_value = "spam"
            presenter.on_add_button_clicked("button")
        self.assertTrue(presenter.expander.get_visible())
        self.assertTrue(presenter.connect_button.get_sensitive())
        self.assertFalse(presenter.noconnectionlabel.get_visible())
        self.assertEqual(presenter.name_combo.get_active_text(), "spam")
        params = presenter.get_params()
        self.assertEqual(params["default"], True)
        self.assertEqual(params["directory"], "./spam")
        self.assertEqual(params["type"], "SQLite")
        self.assertEqual(params["file"], "./spam.db")
        presenter.destroy()

    def test_get_parent_folder(self):
        path = ConnectionManagerDialog.get_parent_folder("")
        self.assertEqual(paths.appdata_dir(), path)
        path = ConnectionManagerDialog.get_parent_folder(None)
        self.assertEqual(paths.appdata_dir(), path)
        relative_path = "./test/this"
        path = ConnectionManagerDialog.get_parent_folder(relative_path)
        self.assertEqual(
            str(Path(paths.appdata_dir(), relative_path[2:]).parent), path
        )
        absolute_path = Path(paths.appdata_dir(), relative_path[2:])
        absolute_parent = str(absolute_path.parent)
        path = ConnectionManagerDialog.get_parent_folder(str(absolute_path))
        self.assertEqual(absolute_parent, path)

    def test_replace_leading_appdata(self):
        presenter = ConnectionManagerDialog()
        path = str(Path(paths.appdata_dir(), "test/this"))
        presenter.rootdir_entry.set_text(path)
        presenter.replace_leading_appdata(presenter.rootdir_entry)
        self.assertEqual(presenter.rootdir_entry.get_text(), "./test/this")
        presenter.destroy()


class GlobalFunctionsTests(BaubleTestCase):
    def test_make_absolute(self):
        path = str(Path(paths.appdata_dir(), "test/this"))
        self.assertEqual(bauble.connmgr.make_absolute("./test/this"), path)
        path = str(Path(paths.appdata_dir(), "test\\this"))
        self.assertEqual(bauble.connmgr.make_absolute(".\\test\\this"), path)

    def test_is_package_name(self):
        self.assertTrue(is_package_name("sqlite3"))
        self.assertFalse(is_package_name("sqlheavy42"))

    def test_check_new_release(self):
        created_date = "2021-01-01T00:00:00Z"
        test_data = {
            "name": "v1.3.0-a",
            "prerelease": True,
            "assets": [{"created_at": created_date}],
        }
        test_data["name"] = "v1.3.999-a"
        self.assertEqual(check_new_release(test_data), test_data)
        test_data["name"] = "v1.4.999-a"
        self.assertEqual(check_new_release(test_data), test_data)
        test_data["name"] = "v1.3.0"
        self.assertFalse(check_new_release(test_data))
        test_data["name"] = "v1.3.999"
        self.assertEqual(check_new_release(test_data), test_data)
        test_data["name"] = "v1.3.999"
        test_data["prerelease"] = False
        self.assertEqual(check_new_release(test_data), test_data)
        test_data["prerelease"] = True
        self.assertTrue(check_new_release(test_data) and True or False)
        test_data["name"] = "v1.0.0"
        test_data["prerelease"] = False
        self.assertFalse(check_new_release(test_data))
        test_data["name"] = "v1.0.0-a"
        self.assertFalse(check_new_release(test_data))
        test_data["name"] = "v1.0.0-b"
        self.assertFalse(check_new_release(test_data) and True or False)
        bauble.version = "1.3.10"
        test_data["name"] = "v1.3.9"
        self.assertFalse(check_new_release(test_data))

        self.assertEqual(
            bauble.release_date, dateutil.parser.isoparse(created_date)
        )

    @mock.patch("bauble.connmgr.utils.get_net_sess")
    def test_retrieve_latest_release_data_returns_none_wo_bad_response(
        self, mock_get_net_sess
    ):
        mock_response = mock.Mock()
        mock_response.json.return_value = ["test"]
        mock_response.ok = False
        mock_net_sess = mock.Mock(**{"get.return_value": mock_response})
        mock_get_net_sess.return_value = mock_net_sess
        self.assertIsNone(retrieve_latest_release_data())
        mock_response.get.asset_called()
        mock_response.json.asset_not_called()

    @mock.patch("bauble.connmgr.utils.get_net_sess")
    def test_retrieve_latest_release_data_returns_none_w_error(
        self, mock_get_net_sess
    ):
        mock_net_sess = mock.Mock(**{"get.side_effect": Exception()})
        mock_get_net_sess.return_value = mock_net_sess
        with self.assertLogs(level="DEBUG") as logs:
            self.assertIsNone(retrieve_latest_release_data())
        self.assertEqual(len(logs), 2)
        self.assertEqual(
            "unhandled Exception() while checking for new release",
            logs.records[0].getMessage(),
        )

    @mock.patch("bauble.connmgr.utils.get_net_sess")
    def test_retrieve_latest_release_data_returns_response(
        self, mock_get_net_sess
    ):
        mock_response = mock.Mock()
        mock_response.json.return_value = ["test"]
        mock_response.ok = True
        mock_net_sess = mock.Mock(**{"get.return_value": mock_response})
        mock_get_net_sess.return_value = mock_net_sess
        self.assertEqual(retrieve_latest_release_data(), "test")
        mock_response.get.asset_called()
        mock_response.json.asset_called()

    def test_notify_new_release_notifies_when_new_release(self):
        mock_dialog = mock.Mock()
        mock_retrieve_latest = mock.Mock(return_value={})
        mock_check_new = mock.Mock(return_value=True)
        with self.assertLogs(level="DEBUG") as logs:
            notify_new_release(
                mock_dialog, mock_retrieve_latest, mock_check_new
            )
        mock_retrieve_latest.assert_called()
        mock_check_new.assert_called()
        self.assertEqual("notifying new release", logs.records[0].getMessage())

    def test_notify_new_release_notify_relevealer_when_new_release(self):
        dialog = ConnectionManagerDialog()
        bauble.release_version = "15.15.15"
        mock_retrieve_latest = mock.Mock(return_value={})
        mock_check_new = mock.Mock(return_value=True)
        notify_new_release(dialog, mock_retrieve_latest, mock_check_new)
        update_gui()
        mock_retrieve_latest.assert_called()
        mock_check_new.assert_called()
        self.assertEqual(
            dialog.notify_message_label.get_text(),
            "New version 15.15.15 available.",
        )
        self.assertTrue(dialog.notify_revealer.get_child_revealed())
        dialog.notify_close_button.clicked()
        self.assertFalse(dialog.notify_revealer.get_child_revealed())
        dialog.destroy()

    def test_notify_new_release_doesnt_notify_when_not_new_release(self):
        mock_dialog = mock.Mock()
        mock_retrieve_latest = mock.Mock(return_value={})
        mock_check_new = mock.Mock(return_value=False)
        with self.assertLogs(level="DEBUG") as logs:
            notify_new_release(
                mock_dialog, mock_retrieve_latest, mock_check_new
            )
        mock_retrieve_latest.assert_called()
        mock_check_new.assert_called()
        self.assertEqual("not new release", logs.records[0].getMessage())

    def test_notify_new_release_doesnt_notify_when_no_data(self):
        mock_dialog = mock.Mock()
        mock_retrieve_latest = mock.Mock(return_value=None)
        mock_check_new = mock.Mock()
        with self.assertLogs(level="DEBUG") as logs:
            notify_new_release(
                mock_dialog, mock_retrieve_latest, mock_check_new
            )
        mock_retrieve_latest.assert_called()
        mock_check_new.assert_not_called()
        self.assertEqual("no release data", logs.records[0].getMessage())

    def test_notify_new_release_doesnt_notify_when_not_dict(self):
        mock_dialog = mock.Mock()
        mock_retrieve_latest = mock.Mock(return_value="spam")
        mock_check_new = mock.Mock()
        with self.assertLogs(level="DEBUG") as logs:
            notify_new_release(
                mock_dialog, mock_retrieve_latest, mock_check_new
            )
        mock_retrieve_latest.assert_called()
        mock_check_new.assert_not_called()
        self.assertEqual("no release data", logs.records[0].getMessage())

    def test_check_create_paths(self):
        temp_dir = mkdtemp()
        valid, msg = check_create_paths(temp_dir)
        self.assertTrue(valid)
        self.assertFalse(msg)
        self.assertTrue(os.path.isdir(os.path.join(temp_dir, "pictures")))
        self.assertTrue(
            os.path.isdir(os.path.join(temp_dir, "pictures", "thumbs"))
        )
        self.assertTrue(os.path.isdir(os.path.join(temp_dir, "documents")))
        temp_dir = mkdtemp()
        Path(temp_dir, "documents").touch()
        Path(temp_dir, "pictures").mkdir()
        Path(temp_dir, "pictures", "thumbs").touch()
        valid, msg = check_create_paths(temp_dir)
        self.assertFalse(valid)
        self.assertTrue(msg)
        self.assertTrue(os.path.isdir(os.path.join(temp_dir, "pictures")))
        self.assertFalse(
            os.path.isdir(os.path.join(temp_dir, "pictures", "thumbs"))
        )
        self.assertFalse(os.path.isdir(os.path.join(temp_dir, "documents")))

    @mock.patch("bauble.connmgr.Path.mkdir")
    def test_check_create_paths_no_permission(self, mock_mkdir):
        mock_mkdir.side_effect = OSError("BOOM")
        temp_dir = mkdtemp()
        valid, msg = check_create_paths(temp_dir)
        self.assertFalse(valid)
        self.assertTrue(msg)
        self.assertFalse(os.path.isdir(os.path.join(temp_dir, "pictures")))
        self.assertFalse(
            os.path.isdir(os.path.join(temp_dir, "pictures", "thumbs"))
        )
        self.assertFalse(os.path.isdir(os.path.join(temp_dir, "documents")))
        self.assertIn("DO NOT have permission", msg)


class ButtonBrowseButtons(BaubleTestCase):
    @mock.patch("utils.Gtk.FileChooserNative.new")
    def test_file_chosen(self, mock_file_chooser):
        mock_file_chooser().run.return_value = Gtk.ResponseType.ACCEPT
        mock_file_chooser().get_filename.return_value = "chosen"
        presenter = ConnectionManagerDialog()
        presenter.on_file_btnbrowse_clicked()
        self.assertEqual(presenter.filename, "chosen")
        presenter.destroy()

    @mock.patch("utils.Gtk.FileChooserNative.new")
    def test_file_not_chosen(self, mock_file_chooser):
        mock_file_chooser().run.return_value = Gtk.ResponseType.ACCEPT
        mock_file_chooser().get_filename.return_value = ""
        presenter = ConnectionManagerDialog()
        presenter.filename = "previously"
        presenter.on_file_btnbrowse_clicked()
        self.assertEqual(presenter.filename, "previously")
        presenter.destroy()

    @mock.patch("utils.Gtk.FileChooserNative.new")
    def test_rootdir_chosen(self, mock_file_chooser):
        mock_file_chooser().run.return_value = Gtk.ResponseType.ACCEPT
        mock_file_chooser().get_filename.return_value = "chosen"
        presenter = ConnectionManagerDialog()
        presenter.on_rootdir_btnbrowse_clicked()
        self.assertEqual(presenter.rootdir, "chosen")
        presenter.destroy()

    @mock.patch("utils.Gtk.FileChooserNative.new")
    def test_rootdir_not_chosen(self, mock_file_chooser):
        mock_file_chooser().run.return_value = Gtk.ResponseType.ACCEPT
        mock_file_chooser().get_filename.return_value = ""
        presenter = ConnectionManagerDialog()
        presenter.rootdir = "previously"
        presenter.on_rootdir_btnbrowse_clicked()
        self.assertEqual(presenter.rootdir, "previously")
        presenter.destroy()

    @mock.patch("utils.Gtk.FileChooserNative.new")
    def test_rootdir2_chosen(self, mock_file_chooser):
        mock_file_chooser().run.return_value = Gtk.ResponseType.ACCEPT
        mock_file_chooser().get_filename.return_value = "chosen"
        presenter = ConnectionManagerDialog()
        presenter.on_rootdir2_btnbrowse_clicked()
        self.assertEqual(presenter.rootdir, "chosen")
        presenter.destroy()

    @mock.patch("utils.Gtk.FileChooserNative.new")
    def test_rootdir2_not_chosen(self, mock_file_chooser):
        mock_file_chooser().run.return_value = Gtk.ResponseType.ACCEPT
        mock_file_chooser().get_filename.return_value = ""
        presenter = ConnectionManagerDialog()
        presenter.rootdir = "previously"
        presenter.on_rootdir2_btnbrowse_clicked()
        self.assertEqual(presenter.rootdir, "previously")
        presenter.destroy()


class OnDialogResponseTests(BaubleTestCase):
    @mock.patch("bauble.connmgr.utils.message_dialog")
    def test_on_dialog_response_ok_invalid_params(self, mock_dialog):
        presenter = ConnectionManagerDialog()
        response = presenter.on_dialog_response(presenter, RESPONSE_OK)
        mock_dialog.assert_called()
        self.assertTrue(response)
        presenter.destroy()

    def test_on_dialog_response_ok_valid_params(self):
        prefs.prefs[bauble.CONN_LIST_PREF] = {
            "nugkui": {
                "default": False,
                "directory": f"{TEMP_ROOT}/nugkui",
                "type": "SQLite",
                "file": f"{TEMP_ROOT}/nugkui.db",
            }
        }
        prefs.prefs[bauble.CONN_DEFAULT_PREF] = "nugkui"
        prefs.prefs[prefs.root_directory_pref] = f"{TEMP_ROOT}"
        presenter = ConnectionManagerDialog()
        response = presenter.on_dialog_response(presenter, RESPONSE_OK)
        self.assertFalse(response)
        self.assertEqual(
            prefs.prefs[prefs.picture_root_pref],
            f"{TEMP_ROOT}/nugkui/pictures",
        )
        presenter.destroy()

    def test_on_dialog_response_cancel(self):
        prefs.prefs[bauble.CONN_LIST_PREF] = {
            "nugkui": {
                "default": False,
                "directory": f"{TEMP_ROOT}/nugkui",
                "type": "SQLite",
                "file": f"{TEMP_ROOT}/nugkui.db",
            }
        }
        prefs.prefs[bauble.CONN_DEFAULT_PREF] = "nugkui"
        prefs.prefs[prefs.root_directory_pref] = f"{TEMP_ROOT}"
        presenter = ConnectionManagerDialog()
        response = presenter.on_dialog_response(presenter, RESPONSE_CANCEL)
        self.assertFalse(response)
        self.assertEqual(
            prefs.prefs[prefs.root_directory_pref], f"{TEMP_ROOT}"
        )
        presenter.destroy()

    @mock.patch("bauble.connmgr.utils.yes_no_dialog")
    def test_on_dialog_response_cancel_params_changed_dont_save(
        self, mock_dialog
    ):
        mock_dialog.return_value = False
        con_pref = {
            "nugkui": {
                "default": False,
                "directory": f"{TEMP_ROOT}/nugkui",
                "type": "SQLite",
                "file": f"{TEMP_ROOT}/nugkui.db",
            }
        }
        prefs.prefs[bauble.CONN_LIST_PREF] = copy.copy(con_pref)
        prefs.prefs[bauble.CONN_DEFAULT_PREF] = "nugkui"
        presenter = ConnectionManagerDialog()
        # change something
        presenter.usedefaults_chkbx.set_active(True)
        presenter.on_dialog_response(presenter, RESPONSE_CANCEL)
        # asked to save but said no
        mock_dialog.assert_called()
        self.assertEqual(prefs.prefs[bauble.CONN_LIST_PREF], con_pref)
        presenter.destroy()

    @mock.patch("bauble.connmgr.utils.yes_no_dialog")
    def test_on_dialog_response_cancel_params_changed_do_save(
        self, mock_dialog
    ):
        mock_dialog.return_value = True
        con_pref = {
            "nugkui": {
                "default": False,
                "directory": f"{TEMP_ROOT}/nugkui",
                "type": "SQLite",
                "file": f"{TEMP_ROOT}/nugkui.db",
            }
        }
        prefs.prefs[bauble.CONN_LIST_PREF] = copy.copy(con_pref)
        prefs.prefs[bauble.CONN_DEFAULT_PREF] = "nugkui"
        presenter = ConnectionManagerDialog()
        # change something
        presenter.usedefaults_chkbx.set_active(True)
        presenter.on_dialog_response(presenter, RESPONSE_CANCEL)
        # asked to save but said no
        mock_dialog.assert_called()
        self.assertNotEqual(prefs.prefs[bauble.CONN_LIST_PREF], con_pref)
        presenter.destroy()

    def test_on_dialog_response_ok_creates_folders(self):
        prefs.prefs[bauble.CONN_LIST_PREF] = {
            "nugkui": {
                "default": False,
                "directory": f"{TEMP_ROOT}/nugkui",
                "type": "SQLite",
                "file": f"{TEMP_ROOT}/nugkui.db",
            }
        }
        prefs.prefs[bauble.CONN_DEFAULT_PREF] = "nugkui"
        presenter = ConnectionManagerDialog()
        response = presenter.on_dialog_response(presenter, RESPONSE_OK)
        self.assertFalse(response)
        self.assertTrue(Path(f"{TEMP_ROOT}/nugkui/pictures").is_dir())
        self.assertTrue(Path(f"{TEMP_ROOT}/nugkui/pictures/thumbs").is_dir())
        self.assertTrue(Path(f"{TEMP_ROOT}/nugkui/documents").is_dir())
        presenter.destroy()

    def test_on_dialog_response_ok_creates_folders_half_exist(self):
        # make sure pictures and thumbs folders respectively do and do not
        # already exist as folders.
        path = mkdtemp()
        prefs.prefs[bauble.CONN_LIST_PREF] = {
            "nugkui": {
                "default": False,
                "directory": path,
                "type": "SQLite",
                "file": path + "test.db",
            }
        }
        presenter = ConnectionManagerDialog()
        # invoke action
        presenter.on_dialog_response(presenter, RESPONSE_OK)
        # check existence of pictures folder
        self.assertTrue(Path(path, "pictures").is_dir())
        # check existence of thumbnails folder
        self.assertTrue(Path(path, "pictures", "thumbs").is_dir())
        # check documents exists
        self.assertTrue(Path(path, "documents").is_dir())
        presenter.destroy()

    def test_on_dialog_response_ok_creates_folders_exists(self):
        temp_dir = mkdtemp()
        Path(temp_dir, "documents").mkdir()
        Path(temp_dir, "pictures").mkdir()
        Path(temp_dir, "pictures", "thumbs").mkdir()
        prefs.prefs[bauble.CONN_LIST_PREF] = {
            "nugkui": {
                "default": False,
                "directory": temp_dir,
                "type": "SQLite",
                "file": f"{temp_dir}/nugkui.db",
            }
        }
        prefs.prefs[bauble.CONN_DEFAULT_PREF] = "nugkui"
        presenter = ConnectionManagerDialog()
        response = presenter.on_dialog_response(presenter, RESPONSE_OK)
        self.assertFalse(response)
        self.assertTrue(Path(f"{TEMP_ROOT}/pictures").is_dir())
        self.assertTrue(Path(f"{TEMP_ROOT}/pictures/thumbs").is_dir())
        self.assertTrue(Path(f"{TEMP_ROOT}/documents").is_dir())
        presenter.destroy()

    def test_on_dialog_response_ok_creates_folders_exists_occupied(self):
        # make sure doesn't wipeout existing data
        temp_dir = mkdtemp()
        Path(temp_dir, "documents").mkdir()
        Path(temp_dir, "documents", "spam.csv").touch()
        Path(temp_dir, "pictures").mkdir()
        Path(temp_dir, "pictures", "eggs.jpg").touch()
        Path(temp_dir, "pictures", "thumbs").mkdir()
        Path(temp_dir, "pictures", "thumbs", "eggs.jpg").touch()
        prefs.prefs[bauble.CONN_LIST_PREF] = {
            "nugkui": {
                "default": False,
                "directory": temp_dir,
                "type": "SQLite",
                "file": f"{temp_dir}/nugkui.db",
            }
        }
        prefs.prefs[bauble.CONN_DEFAULT_PREF] = "nugkui"
        presenter = ConnectionManagerDialog()
        response = presenter.on_dialog_response(presenter, RESPONSE_OK)
        self.assertFalse(response)
        self.assertTrue(Path(f"{temp_dir}/pictures/eggs.jpg").exists())
        self.assertTrue(Path(f"{temp_dir}/pictures/thumbs/eggs.jpg").exists())
        self.assertTrue(Path(f"{temp_dir}/documents/spam.csv").exists())
        presenter.destroy()


class StartConnectionManagerTests(BaubleTestCase):
    @mock.patch("bauble.connmgr.ConnectionManagerDialog.run")
    def test_start_connection_manager_runs_dialog(self, mock_run):
        mock_run.return_value = RESPONSE_OK
        prefs.prefs[bauble.CONN_DEFAULT_PREF] = "nugkui"
        prefs.prefs[bauble.CONN_LIST_PREF] = {
            "nugkui": {
                "default": True,
                "directory": "./nugkui",
                "type": "SQLite",
                "file": "./nugkui.db",
            }
        }

        name, uri = start_connection_manager()

        self.assertEqual(name, "nugkui")
        self.assertTrue(
            uri, make_url("sqlite:////{paths.appdata_dir()}/test.db")
        )
        mock_run.assert_called_once()

    def test_start_connection_manager_w_msg_replaces_image_box(self):
        prefs.prefs[bauble.CONN_DEFAULT_PREF] = "nugkui"
        prefs.prefs[bauble.CONN_LIST_PREF] = {
            "nugkui": {
                "default": True,
                "directory": "./nugkui",
                "type": "SQLite",
                "file": "./nugkui.db",
            }
        }

        with mock.patch(
            "bauble.connmgr.ConnectionManagerDialog"
        ) as mock_con_mgr:
            start_connection_manager("choose a connection")
            mock_con_mgr().image_box.remove.assert_called_once()

    @mock.patch("bauble.connmgr.ConnectionManagerDialog.run")
    def test_start_connection_manager_dont_ask_wont_run_dialog(self, mock_run):
        prefs.prefs[bauble.CONN_DONT_ASK_PREF] = True
        ConnectionManagerDialog.first_run = True
        prefs.prefs[bauble.CONN_DEFAULT_PREF] = "nugkui"
        prefs.prefs[bauble.CONN_LIST_PREF] = {
            "nugkui": {
                "default": True,
                "directory": "./nugkui",
                "type": "SQLite",
                "file": "./nugkui.db",
            }
        }

        name, uri = start_connection_manager()
        self.assertEqual(name, "nugkui")
        self.assertTrue(
            uri, make_url("sqlite:////{paths.appdata_dir()}/test.db")
        )
        mock_run.assert_not_called()

    @mock.patch("bauble.connmgr.ConnectionManagerDialog.run")
    def test_start_connection_manager_reponse_cancel_returns_none(
        self, mock_run
    ):
        mock_run.return_value = RESPONSE_CANCEL
        prefs.prefs[bauble.CONN_DEFAULT_PREF] = "nugkui"
        prefs.prefs[bauble.CONN_LIST_PREF] = {
            "nugkui": {
                "default": True,
                "directory": "./nugkui",
                "type": "SQLite",
                "file": "./nugkui.db",
            }
        }

        name, uri = start_connection_manager()

        self.assertIsNone(name)
        self.assertIsNone(uri)
        mock_run.assert_called_once()
