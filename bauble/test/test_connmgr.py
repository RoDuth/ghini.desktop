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
from bauble.connmgr import ConnectionBox
from bauble.connmgr import ConnectionManagerDialog
from bauble.connmgr import ConnectionModel
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
    assert not check_dupids(os.path.join(head, "connection_manager.ui"))
    assert not check_dupids(os.path.join(head, "connection_box.ui"))


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
        presenter.remove_connection()
        # T_1
        self.assertFalse(presenter.expander.get_visible())
        self.assertTrue(presenter.noconnectionlabel.get_visible())
        presenter.destroy()

    @mock.patch("bauble.connmgr.utils.yes_no_dialog")
    def test_on_remove_no_connection_name_bails(self, mock_dialog):
        prefs.prefs[bauble.CONN_LIST_PREF] = {
            "nugkui": {
                "default": True,
                "directory": "./nugkui",
                "type": "SQLite",
                "file": "./nugkui.db",
            }
        }
        presenter = ConnectionManagerDialog()
        presenter.model.connection_name = None
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
        prefs.prefs.save()
        presenter = ConnectionManagerDialog()
        connection_box = presenter.expander.get_child()

        self.assertEqual(presenter.connection_name, "nugkui")
        self.assertTrue(presenter.model.use_defaults)
        self.assertTrue(connection_box.usedefaults_chkbx.get_active())

        presenter.destroy()

    def test_only_sets_default_on_first_run(self):
        prefs.prefs[bauble.CONN_LIST_PREF] = {
            "btuu": {
                "default": False,
                "directory": "btuu",
                "type": "SQLite",
                "file": "btuu.db",
            },
            "nugkui": {
                "default": True,
                "directory": "./nugkui",
                "type": "SQLite",
                "file": "./nugkui.db",
            },
        }
        prefs.prefs[bauble.CONN_DEFAULT_PREF] = "nugkui"
        prefs.prefs.save()
        self.assertEqual(prefs.prefs[bauble.CONN_DEFAULT_PREF], "nugkui")
        presenter = ConnectionManagerDialog()
        presenter.first_run = True
        presenter.name_combo.set_active(0)
        update_gui()
        presenter.on_dialog_response(presenter, Gtk.ResponseType.OK)
        # changes
        self.assertEqual(prefs.prefs[bauble.CONN_DEFAULT_PREF], "btuu")

        presenter.first_run = False
        presenter.name_combo.set_active(1)
        update_gui()
        presenter.on_dialog_response(presenter, Gtk.ResponseType.OK)
        # not changed
        self.assertEqual(prefs.prefs[bauble.CONN_DEFAULT_PREF], "btuu")

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
        connection_box = presenter.expander.get_child()

        self.assertEqual(presenter.connection_name, "btuu")
        self.assertFalse(presenter.model.use_defaults)
        self.assertFalse(connection_box.usedefaults_chkbx.get_active())

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
        connection_box = presenter.expander.get_child()

        self.assertEqual(presenter.connection_name, "quisquis")
        self.assertTrue(presenter.expander.get_visible())
        self.assertTrue(connection_box.dbms_parambox.get_visible())
        self.assertFalse(connection_box.sqlite_parambox.get_visible())
        self.assertFalse(presenter.noconnectionlabel.get_visible())

        presenter.destroy()

    def test_one_connection_unknown_dbtype_doesnt_show(self):
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
        self.assertIsNone(presenter.expander.get_child())
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
        connection_box = presenter.expander.get_child()

        self.assertEqual(presenter.connection_name, "quisquis")
        self.assertTrue(presenter.expander.get_visible())
        self.assertTrue(connection_box.dbms_parambox.get_visible())
        self.assertFalse(connection_box.sqlite_parambox.get_visible())
        self.assertFalse(presenter.noconnectionlabel.get_visible())
        self.assertEqual(len(connection_box.options_liststore), 3)

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
        self.assertEqual(presenter.model.connection_name, "nugkui")
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
        connection_box = presenter.expander.get_child()
        # T_0
        self.assertEqual(presenter.connection_name, "nugkui")
        self.assertTrue(connection_box.sqlite_parambox.get_visible())
        self.assertFalse(connection_box.dbms_parambox.get_visible())
        # action
        presenter.name_combo.set_active(1)
        # result
        self.assertEqual(presenter.connection_name, "quisquis")
        self.assertEqual(presenter.model.dbtype, "PostgreSQL")
        # T_1
        connection_box = presenter.expander.get_child()

        self.assertTrue(connection_box.dbms_parambox.get_visible())
        self.assertFalse(connection_box.sqlite_parambox.get_visible())

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
        connection_box = presenter.expander.get_child()

        connection_box.usedefaults_chkbx.set_active(True)
        self.assertFalse(connection_box.file_entry.get_sensitive())
        self.assertEqual(presenter.connection_name, "nugkui")
        self.assertEqual(connection_box.rootdir_entry.get_text(), "./nugkui")
        self.assertEqual(connection_box.file_entry.get_text(), "./nugkui.db")

        presenter.destroy()

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
        connection_box = presenter.expander.get_child()

        self.assertEqual(presenter.connection_name, "quisquis")
        self.assertEqual(presenter.model.dbtype, "PostgreSQL")
        self.assertEqual(
            presenter.connection_uri,
            make_url("postgresql://pg@localhost:9876/quisquis"),
        )
        # change it
        connection_box.database_entry.set_text("new_db")

        connection_box.user_entry.set_text("new_user")
        connection_box.host_entry.set_text("new_host")
        connection_box.port_entry.set_text("1234")
        connection_box.passwd_chkbx.set_active(True)
        params = presenter.model.get_params()
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

    def test_are_prefs_already_saved(self):
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
        # no connection_name

        self.assertTrue(presenter.model.is_saved())
        # prefs with out the connection name
        prefs.prefs[bauble.CONN_LIST_PREF] = {}

        self.assertFalse(presenter.model.is_saved())

        # prefs with connection name and equal
        presenter.model.connection_name = "spam"
        presenter.model.filename = "./spam.db"
        presenter.model.rootdir = "./spam"
        presenter.model.dbtype = "SQLite"
        presenter.model.use_defaults = False
        presenter.model.database = ""
        presenter.model.host = ""
        presenter.model.port = ""
        presenter.model.user = ""
        prefs.prefs[bauble.CONN_LIST_PREF] = {
            "spam": {
                "default": False,
                "directory": "./spam",
                "type": "SQLite",
                "file": "./spam.db",
            }
        }

        self.assertTrue(presenter.model.is_saved())

        # prefs with connection name and not equal
        presenter.model.rootdir = "./spam_and_eggs"

        self.assertFalse(presenter.model.is_saved())

        presenter.destroy()

    @mock.patch("bauble.connmgr.utils.yes_no_dialog")
    def test_on_name_combo_changed_asks_saves_unsaved(self, mock_yn):
        prefs.prefs[bauble.CONN_LIST_PREF] = {
            "spam": {
                "default": False,
                "directory": "./spam",
                "type": "SQLite",
                "file": "./spam.db",
            },
            "eggs": {
                "default": False,
                "directory": "./eggs",
                "type": "SQLite",
                "file": "./egss.db",
            },
        }
        mock_yn.return_value = True
        presenter = ConnectionManagerDialog()
        # make a change to prefs
        prefs.prefs[bauble.CONN_LIST_PREF] = {
            "spam": {
                "default": False,
                "directory": "./ham",
                "type": "SQLite",
                "file": "./ham.db",
            },
            "eggs": {
                "default": False,
                "directory": "./eggs",
                "type": "SQLite",
                "file": "./eggs.db",
            },
        }

        with mock.patch.object(presenter.model, "save") as mock_save:
            presenter.name_combo.set_active(1)

            mock_save.assert_called()
            mock_yn.assert_called_once()

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

    def test_problems_prevents_connecting(self):
        prefs.prefs[bauble.CONN_LIST_PREF] = {
            "spam": {
                "default": True,
                "directory": "./ham",
                "type": "SQLite",
                "file": "./ham.db",
            }
        }
        presenter = ConnectionManagerDialog()
        self.assertTrue(presenter.connect_button.get_sensitive())
        self.assertTrue(presenter.dont_ask_chkbx.get_sensitive())

        connection_box = presenter.get_connection_box()
        connection_box.add_problem(
            connection_box.PROBLEM_UNREADABLE, connection_box.file_entry
        )

        self.assertFalse(presenter.connect_button.get_sensitive())
        self.assertFalse(presenter.dont_ask_chkbx.get_sensitive())

        connection_box = presenter.get_connection_box()
        connection_box.remove_problem(
            connection_box.PROBLEM_UNREADABLE, connection_box.file_entry
        )

        self.assertTrue(presenter.connect_button.get_sensitive())
        self.assertTrue(presenter.dont_ask_chkbx.get_sensitive())

        presenter.destroy()


class ConnectionModelTests(BaubleTestCase):
    def test_no_connection_name_raises(self):
        self.assertRaises(ValueError, ConnectionModel, None)
        self.assertRaises(ValueError, ConnectionModel, "")

    def test_use_defaults(self):
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
        model = ConnectionModel("quisquis")
        model.connection_name = None
        model.use_defaults = True
        self.assertEqual(model.filename, "")
        self.assertEqual(model.rootdir, "")
        model = ConnectionModel("quisquis")
        model.use_defaults = True
        self.assertEqual(model.filename, "./quisquis.db")
        self.assertEqual(model.rootdir, "./quisquis")
        model.connection_name = "eggs"
        model.use_defaults = True
        self.assertEqual(model.filename, "./eggs.db")
        self.assertEqual(model.rootdir, "./eggs")

    def test_save_no_connection_bails(self):
        model = ConnectionModel("spam")
        model.connection_name = None

        with self.assertNoLogs(level="DEBUG"):
            model.save()

    def test_save_no_prefs_creates(self):
        model = ConnectionModel("spam")
        del prefs.prefs[bauble.CONN_LIST_PREF]
        model.filename = "./spam.db"
        model.rootdir = "./spam"
        model.dbtype = "SQLite"
        model.use_defaults = False

        self.assertNotIn(bauble.CONN_LIST_PREF, prefs.prefs)

        model.save()

        self.assertIn(bauble.CONN_LIST_PREF, prefs.prefs)
        conn_list = prefs.prefs[bauble.CONN_LIST_PREF]
        # pylint: disable=unsubscriptable-object
        self.assertEqual(conn_list["spam"]["file"], "./spam.db")
        self.assertEqual(conn_list["spam"]["directory"], "./spam")


class OptionsTests(BaubleTestCase):
    def test_on_options_edited(self):
        model = ConnectionModel("ham")
        connection_box = ConnectionBox(model)
        connection_box.type_combo.set_active(DBTYPES.index("PostgreSQL"))

        self.assertEqual(len(connection_box.options_liststore), 1)
        connection_box.on_options_name_edited("entry", 0, "spam")
        connection_box.on_options_value_edited("entry", 0, "eggs")

        self.assertEqual(len(connection_box.options_liststore), 2)
        self.assertEqual(model.options, {"spam": "eggs"})

        connection_box.destroy()

    def test_new_mssql_adds_sensible_defaults(self):
        presenter = ConnectionManagerDialog()
        with mock.patch.object(presenter, "run_entry_dialog") as mock_dlog:
            mock_dlog.return_value = "spam"
            presenter.on_add_button_clicked(presenter.name_combo)

        self.assertEqual(presenter.connection_name, "spam")

        connection_box = presenter.get_connection_box()
        connection_box.type_combo.set_active(DBTYPES.index("MSSQL"))

        self.assertEqual(len(connection_box.options_liststore), 3)
        self.assertEqual(connection_box.options_liststore[0][0], "driver")
        self.assertTrue(
            connection_box.options_liststore[0][1].startswith("ODBC Driver")
        )
        self.assertEqual(
            connection_box.options_liststore[1][0], "MARS_Connection"
        )
        self.assertEqual(connection_box.options_liststore[1][1], "Yes")

        presenter.destroy()

    @mock.patch("bauble.connmgr.pyodbc", new=None)
    def test_new_mssql_no_pyodbc_bails(self):
        presenter = ConnectionManagerDialog()
        with mock.patch.object(presenter, "run_entry_dialog") as mock_dlog:
            mock_dlog.return_value = "spam"
            presenter.on_add_button_clicked(presenter.name_combo)

        self.assertEqual(presenter.connection_name, "spam")

        connection_box = presenter.get_connection_box()
        with self.assertLogs(level="DEBUG") as logs:
            connection_box.type_combo.set_active(DBTYPES.index("MSSQL"))

        self.assertTrue(any("no pyodbc bailing" in i for i in logs.output))
        self.assertEqual(len(connection_box.options_liststore), 1)

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
        connection_box = presenter.get_connection_box()

        self.assertEqual(presenter.connection_name, "quisquis")
        self.assertEqual(connection_box.options_liststore[0][0], "driver")
        self.assertEqual(connection_box.options_liststore[0][1], "Fake driver")
        self.assertEqual(
            connection_box.options_liststore[1][0], "MARS_Connection"
        )
        self.assertEqual(connection_box.options_liststore[1][1], "No")

        connection_box.type_combo.set_active(DBTYPES.index("SQLite"))
        connection_box.type_combo.set_active(DBTYPES.index("MSSQL"))

        self.assertEqual(connection_box.options_liststore[0][0], "driver")
        self.assertEqual(connection_box.options_liststore[0][1], "Fake driver")
        self.assertEqual(
            connection_box.options_liststore[1][0], "MARS_Connection"
        )
        self.assertEqual(connection_box.options_liststore[1][1], "No")

        presenter.destroy()


class AddConnectionTests(BaubleTestCase):

    def test_on_add_button_clicked_no_name_bails(self):
        presenter = ConnectionManagerDialog()
        self.assertFalse(presenter.expander.get_visible())
        with mock.patch.object(presenter, "run_entry_dialog") as mock_dlog:
            mock_dlog.return_value = ""
            self.assertTrue(presenter.noconnectionlabel.get_visible())
            presenter.on_add_button_clicked(presenter.name_combo)
            self.assertTrue(presenter.noconnectionlabel.get_visible())
        # nothing changes
        self.assertFalse(presenter.expander.get_visible())
        self.assertFalse(presenter.connect_button.get_sensitive())
        self.assertTrue(presenter.noconnectionlabel.get_visible())
        self.assertIsNone(presenter.get_connection_box())
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
        presenter.model.rootdir = "./eggs"
        # change something
        with mock.patch.object(presenter, "run_entry_dialog") as mock_dlog:
            mock_dlog.return_value = "spam"
            presenter.on_add_button_clicked(presenter.name_combo)

        mock_yn.assert_called_once()
        conn_list = prefs.prefs[bauble.CONN_LIST_PREF]
        # pylint: disable=unsubscriptable-object
        self.assertEqual(conn_list["nugkui"]["directory"], "./eggs")
        self.assertEqual(conn_list["nugkui"]["type"], "SQLite")
        self.assertEqual(conn_list["nugkui"]["file"], "./nugkui.db")
        params = presenter.model.get_params()
        self.assertEqual(params["directory"], "./spam")
        self.assertEqual(params["file"], "./spam.db")

        presenter.destroy()

    def test_no_connection_on_add_confirm_negative(self):
        presenter = ConnectionManagerDialog()
        with mock.patch.object(presenter, "run_entry_dialog") as mock_dlog:
            mock_dlog.return_value = ""
            presenter.on_add_button_clicked(presenter.name_combo)
        # nothing changes
        self.assertFalse(presenter.expander.get_visible())
        self.assertFalse(presenter.connect_button.get_sensitive())
        self.assertTrue(presenter.noconnectionlabel.get_visible())
        presenter.destroy()

    def test_no_connection_on_add_confirm_positive(self):
        presenter = ConnectionManagerDialog()
        with mock.patch.object(presenter, "run_entry_dialog") as mock_dlog:
            mock_dlog.return_value = "spam"
            presenter.on_add_button_clicked(presenter.name_combo)
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
            presenter.on_add_button_clicked(presenter.name_combo)
        self.assertTrue(presenter.expander.get_visible())
        self.assertTrue(presenter.connect_button.get_sensitive())
        self.assertFalse(presenter.noconnectionlabel.get_visible())
        self.assertEqual(presenter.name_combo.get_active_text(), "spam")
        params = presenter.model.get_params()
        self.assertEqual(params["default"], True)
        self.assertEqual(params["directory"], "./spam")
        self.assertEqual(params["type"], "SQLite")
        self.assertEqual(params["file"], "./spam.db")
        presenter.destroy()


class ConnectionBoxTests(BaubleTestCase):

    def test_get_parent_folder(self):
        path = ConnectionBox.get_parent_folder("")
        self.assertEqual(paths.appdata_dir(), path)
        path = ConnectionBox.get_parent_folder(None)
        self.assertEqual(paths.appdata_dir(), path)
        relative_path = "./test/this"
        path = ConnectionBox.get_parent_folder(relative_path)
        self.assertEqual(
            str(Path(paths.appdata_dir(), relative_path[2:]).parent), path
        )
        absolute_path = Path(paths.appdata_dir(), relative_path[2:])
        absolute_parent = str(absolute_path.parent)
        path = ConnectionBox.get_parent_folder(str(absolute_path))
        self.assertEqual(absolute_parent, path)

    def test_replace_leading_appdata(self):
        model = ConnectionModel("spam")
        box = ConnectionBox(model)
        path = str(Path(paths.appdata_dir(), "test/this"))
        box.rootdir_entry.set_text(path)
        box.replace_leading_appdata(box.rootdir_entry)
        self.assertEqual(box.rootdir_entry.get_text(), "./test/this")
        box.destroy()

    def test_on_file_entry_changed_empty_problems(self):
        model = ConnectionModel("spam")
        box = ConnectionBox(model)
        box.refresh_all_widgets_from_model()

        self.assertFalse(box.problems)
        # empty
        box.file_entry.set_text("")

        self.assertEqual(
            box.problems,
            {(box.PROBLEM_EMPTY, box.file_entry)},
        )
        # fix
        box.file_entry.set_text("eggs.db")

        self.assertFalse(box.problems)

    def test_on_file_entry_changed_unreadable_problems(self):
        # file exists but unreadable
        model = ConnectionModel("spam")
        box = ConnectionBox(model)
        box.refresh_all_widgets_from_model()

        self.assertFalse(box.problems)
        # exists
        path = f"{TEMP_ROOT}/nugkui.db"
        Path(path).touch()

        def access_not_readable(_path, mode):
            if mode == os.R_OK:
                return False
            return True

        with mock.patch("os.access") as mock_access:
            mock_access.side_effect = access_not_readable
            box.file_entry.set_text(path)

        self.assertEqual(
            box.problems,
            {(box.PROBLEM_UNREADABLE, box.file_entry)},
        )
        # fix
        box.file_entry.set_text("./nugkui.db")

        self.assertFalse(box.problems)

    def test_on_file_entry_changed_unwritable_dir_problems(self):
        # file doesn't exist and parent unwritable
        model = ConnectionModel("spam")
        box = ConnectionBox(model)
        box.refresh_all_widgets_from_model()

        self.assertFalse(box.problems)
        # doesn't exist
        path = f"{TEMP_ROOT}/nugkui.db"
        if Path(path).exists():
            Path(path).unlink()

        def access_not_readable(_path, mode):
            if mode == os.W_OK:
                return False
            return True

        with mock.patch("os.access") as mock_access:
            mock_access.side_effect = access_not_readable
            box.file_entry.set_text(path)

        self.assertEqual(
            box.problems,
            {(box.PROBLEM_UNREADABLE, box.file_entry)},
        )
        # fix
        box.file_entry.set_text("./nugkui.db")

        self.assertFalse(box.problems)

    def test_on_port_entry_changed(self):
        model = ConnectionModel("spam")
        box = ConnectionBox(model)
        # only allows numeric - stays blank
        box.port_entry.set_text("blah")
        box.port_entry.update()

        self.assertEqual(box.port_entry.get_text(), "")
        # no floats - stays blank
        box.port_entry.set_text("0.01")
        box.port_entry.update()

        self.assertEqual(box.port_entry.get_text(), "")
        # 0 is blank
        box.port_entry.set_text("0")
        box.port_entry.update()

        self.assertEqual(box.port_entry.get_text(), "")
        # not over 65535
        box.port_entry.set_text("70000")
        box.port_entry.update()

        self.assertEqual(box.port_entry.get_text(), "65535")
        # numbers work as expected
        box.port_entry.set_text("1234")
        box.port_entry.update()

        self.assertEqual(box.port_entry.get_text(), "1234")

    def test_on_type_combo_changed_new(self):
        model = ConnectionModel("spam")
        box = ConnectionBox(model)
        box.refresh_all_widgets_from_model()
        params = model.get_params()
        # starting state
        self.assertEqual(params["type"], "SQLite")
        self.assertEqual(params["default"], True)
        self.assertEqual(params["file"], "./spam.db")
        self.assertFalse(box.problems)

        box.type_combo.set_active(DBTYPES.index("PostgreSQL"))
        params = model.get_params()

        self.assertEqual(params["type"], "PostgreSQL")
        self.assertEqual(params.get("file"), None)
        self.assertTrue(box.problems)

        box.type_combo.set_active(DBTYPES.index("SQLite"))
        params = model.get_params()
        # returns to starting state
        self.assertEqual(params["type"], "SQLite")
        self.assertEqual(params["default"], True)
        self.assertEqual(params["file"], "./spam.db")
        self.assertFalse(box.problems)

    def test_on_type_combo_changed_existing(self):
        prefs.prefs[bauble.CONN_LIST_PREF] = {
            "spam": {
                "default": False,
                "directory": "./eggs",
                "type": "SQLite",
                "file": "./eggs.db",
            }
        }
        model = ConnectionModel("spam")
        box = ConnectionBox(model)
        box.refresh_all_widgets_from_model()
        params = model.get_params()
        # starting state
        self.assertEqual(params["type"], "SQLite")
        self.assertEqual(params["default"], False)
        self.assertEqual(params["file"], "./eggs.db")
        self.assertFalse(box.problems)
        # create a problem
        box.file_entry.set_text("")

        self.assertTrue(box.problems)
        # switch to other and back
        box.type_combo.set_active(DBTYPES.index("PostgreSQL"))
        box.type_combo.set_active(DBTYPES.index("SQLite"))
        # returns to start position
        self.assertEqual(params["type"], "SQLite")
        self.assertEqual(params["default"], False)
        self.assertEqual(params["file"], "./eggs.db")
        self.assertFalse(box.problems)


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
        model = ConnectionModel("spam")
        connection_box = ConnectionBox(model)
        connection_box.on_file_btnbrowse_clicked()
        self.assertEqual(connection_box.model.filename, "chosen")
        connection_box.destroy()

    @mock.patch("utils.Gtk.FileChooserNative.new")
    def test_file_not_chosen(self, mock_file_chooser):
        mock_file_chooser().run.return_value = Gtk.ResponseType.ACCEPT
        mock_file_chooser().get_filename.return_value = ""
        model = ConnectionModel("spam")
        connection_box = ConnectionBox(model)
        connection_box.model.filename = "previously"
        connection_box.on_file_btnbrowse_clicked()
        self.assertEqual(connection_box.model.filename, "previously")
        connection_box.destroy()

    @mock.patch("utils.Gtk.FileChooserNative.new")
    def test_rootdir_chosen(self, mock_file_chooser):
        mock_file_chooser().run.return_value = Gtk.ResponseType.ACCEPT
        mock_file_chooser().get_filename.return_value = "chosen"
        model = ConnectionModel("spam")
        connection_box = ConnectionBox(model)
        connection_box.on_rootdir_btnbrowse_clicked()
        self.assertEqual(model.rootdir, "chosen")
        connection_box.destroy()

    @mock.patch("utils.Gtk.FileChooserNative.new")
    def test_rootdir_not_chosen(self, mock_file_chooser):
        mock_file_chooser().run.return_value = Gtk.ResponseType.ACCEPT
        mock_file_chooser().get_filename.return_value = ""
        model = ConnectionModel("spam")
        connection_box = ConnectionBox(model)
        model.rootdir = "previously"
        connection_box.on_rootdir_btnbrowse_clicked()
        self.assertEqual(model.rootdir, "previously")
        connection_box.destroy()

    @mock.patch("utils.Gtk.FileChooserNative.new")
    def test_rootdir2_chosen(self, mock_file_chooser):
        mock_file_chooser().run.return_value = Gtk.ResponseType.ACCEPT
        mock_file_chooser().get_filename.return_value = "chosen"
        model = ConnectionModel("spam")
        connection_box = ConnectionBox(model)
        connection_box.on_rootdir2_btnbrowse_clicked()
        self.assertEqual(model.rootdir, "chosen")
        connection_box.destroy()

    @mock.patch("utils.Gtk.FileChooserNative.new")
    def test_rootdir2_not_chosen(self, mock_file_chooser):
        mock_file_chooser().run.return_value = Gtk.ResponseType.ACCEPT
        mock_file_chooser().get_filename.return_value = ""
        model = ConnectionModel("spam")
        connection_box = ConnectionBox(model)
        model.rootdir = "previously"
        connection_box.on_rootdir2_btnbrowse_clicked()
        self.assertEqual(model.rootdir, "previously")
        connection_box.destroy()


class OnDialogResponseTests(BaubleTestCase):
    @mock.patch("bauble.connmgr.utils.message_dialog")
    def test_on_dialog_response_ok_invalid_params(self, mock_dialog):
        presenter = ConnectionManagerDialog()
        # emit here to avoid warning "no emission of signal "response" to stop"
        presenter.emit("response", RESPONSE_OK)
        mock_dialog.assert_called()
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
        connection_box = presenter.get_connection_box()
        # change something
        connection_box.usedefaults_chkbx.set_active(True)
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
        connection_box = presenter.get_connection_box()
        # change something
        connection_box.usedefaults_chkbx.set_active(True)
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
        self.assertTrue(Path(f"{temp_dir}/pictures").is_dir())
        self.assertTrue(Path(f"{temp_dir}/pictures/thumbs").is_dir())
        self.assertTrue(Path(f"{temp_dir}/documents").is_dir())
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
