# pylint: disable=no-self-use,protected-access
# Copyright (c) 2024 Ross Demuth <rossdemuth123@gmail.com>
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
"""
main.py tests

NOTE that we need to run these in their own processes as "The result of calling
Gio.Application.run() again after it returns is unspecified." i.e. after
app.quit() the process is expected to end
"""
import os
from multiprocessing import Process
from multiprocessing import SimpleQueue
from tempfile import mkstemp
from unittest import TestCase
from unittest import mock

from gi.repository import GLib
from gi.repository import Gtk
from sqlalchemy.engine import make_url
from sqlalchemy.orm import close_all_sessions

import bauble
import bauble.main
from bauble import db
from bauble import paths
from bauble import pluginmgr
from bauble import prefs
from bauble import ui

uri = make_url("sqlite:///:memory:")


def setup_prefs():
    handle, temp = mkstemp(suffix=".cfg", text=True)
    prefs.prefs = prefs._prefs(filename=temp)
    prefs.prefs.init()
    prefs.prefs[prefs.web_proxy_prefs] = "no_proxies"
    prefs.prefs[prefs.debug_logging_prefs] = ["bauble"]
    prefs.prefs.save()
    os.close(handle)


def run_in_prcess(target, *args):
    que = SimpleQueue()
    proc = Process(target=target, args=(que, *args))
    proc.start()
    proc.join()
    return que


def quits_if_connmgr_cancels(que):
    setup_prefs()
    bauble.gui = ui.GUI()
    mock_splash = mock.Mock()
    with mock.patch("bauble.main.start_connection_manager") as mock_cm:
        mock_cm.return_value = None, None
        app = bauble.main.Application(mock_splash)
        err = app.run()
    mock_cm.assert_called()
    que.put(bauble.conn_name)
    que.put(err)
    que.put(mock_splash.destroy.call_count)


def connect_empty_db_dont_populate(que):
    bauble.gui = ui.GUI()
    setup_prefs()
    with (
        mock.patch("bauble.utils.message_dialog") as mock_msg_dialog,
        mock.patch("bauble.main.utils.yes_no_dialog") as mock_yn_dialog,
        mock.patch("bauble.main.start_connection_manager") as mock_connmgr,
    ):
        mock_connmgr.return_value = "test", uri
        mock_yn_dialog.return_value = False
        app = bauble.main.Application(Gtk.Window())
        GLib.idle_add(app.quit)
        err = app.run()
        que.put(mock_connmgr.called)
        que.put(mock_yn_dialog.called)
        que.put(mock_msg_dialog.called)
    que.put(bauble.conn_name)
    que.put(err)
    app.quit()


def post_loop_fails_quits(que):
    bauble.gui = ui.GUI()
    setup_prefs()
    prefs.prefs[bauble.CONN_DONT_ASK_PREF] = True
    with (
        mock.patch("bauble.main.Application._post_loop") as mock_post_loop,
        mock.patch("bauble.utils.message_dialog") as mock_dialog,
        mock.patch("bauble.main.start_connection_manager") as mock_connmgr,
    ):
        mock_connmgr.return_value = "test", uri
        mock_post_loop.return_value = False
        app = bauble.main.Application(Gtk.Window())
        err = app.run()
        que.put(mock_connmgr.called)
        que.put(mock_dialog.called)
        que.put(mock_post_loop.called)
    que.put(bauble.conn_name)
    que.put(err)
    que.put(prefs.prefs[bauble.CONN_DONT_ASK_PREF])
    app.quit()


def connect_empty_populate(que):
    bauble.gui = ui.GUI()
    setup_prefs()
    with (
        mock.patch("bauble.utils.message_dialog") as mock_msg_dialog,
        mock.patch("bauble.main.utils.yes_no_dialog") as mock_yn_dialog,
        mock.patch("bauble.main.start_connection_manager") as mock_connmgr,
        mock.patch("bauble.plugins.garden.start_institution_editor") as m_inst,
    ):
        mock_connmgr.return_value = "test", uri
        mock_yn_dialog.return_value = True
        app = bauble.main.Application(Gtk.Window())
        GLib.idle_add(app.quit)
        err = app.run()
        que.put(mock_connmgr.called)
        que.put(mock_yn_dialog.called)
        que.put(mock_msg_dialog.called)
        que.put(m_inst.called)
    que.put(bauble.conn_name)
    que.put(err)
    app.quit()


class NewDBTests(TestCase):
    """Runs tests in processes as result of calling Gio.Application.run() after
    quit is unspecified.
    """

    @mock.patch("bauble.main.Application")
    def test_main_runs_app(self, mock_app):
        bauble.main.main(Gtk.Window())
        mock_app().run.assert_called()

    def test_app_run_quits_if_connmgr_cancels(self):
        que = run_in_prcess(quits_if_connmgr_cancels)

        self.assertIsNone(que.get())
        self.assertEqual(0, que.get())
        self.assertEqual(1, que.get())

    def test_app_connect_empty_db_dont_populate(self):
        que = run_in_prcess(connect_empty_db_dont_populate)

        self.assertTrue(que.get(), "connmgr not called")
        self.assertTrue(que.get(), "yes_no_dialog not called")
        self.assertTrue(que.get(), "dialog not called")
        self.assertEqual("test", que.get())
        self.assertEqual(0, que.get())

    def test_app_post_loop_fails_quits(self):
        que = run_in_prcess(post_loop_fails_quits)

        self.assertTrue(que.get(), "connmgr not called")
        self.assertTrue(que.get(), "dialog not called")
        self.assertTrue(que.get(), "post_loop not called")
        self.assertEqual("test", que.get())
        self.assertEqual(0, que.get())
        self.assertFalse(que.get())

    def test_app_connect_empty_db_populate(self):
        que = run_in_prcess(connect_empty_populate)

        self.assertTrue(que.get(), "connmgr not called")
        self.assertTrue(que.get(), "yes_no_dialog not called")
        self.assertTrue(que.get(), "dialog not called")
        self.assertTrue(que.get(), "institution editor not called")
        self.assertEqual("test", que.get())
        self.assertEqual(0, que.get())


def connect_existing(que, db_uri):
    bauble.gui = ui.GUI()
    setup_prefs()
    with (
        mock.patch("bauble.utils.message_dialog") as mock_msg_dialog,
        mock.patch("bauble.main.utils.yes_no_dialog") as mock_yn_dialog,
        mock.patch("bauble.main.start_connection_manager") as mock_connmgr,
        mock.patch("bauble.plugins.garden.start_institution_editor"),
    ):
        mock_connmgr.return_value = "test", db_uri
        app = bauble.main.Application(Gtk.Window())
        GLib.idle_add(app.quit)
        err = app.run()
        que.put(mock_connmgr.called)
        que.put(mock_yn_dialog.called)
        que.put(mock_msg_dialog.called)
    que.put(bauble.conn_name)
    que.put(err)
    app.quit()


class ExistingDBTests(TestCase):
    """Runs tests in processes as result of calling Gio.Application.run() after
    quit is unspecified.
    """

    def setUp(self):
        filename = os.path.join(paths.TEMPDIR, "test.db")
        self.db_uri = make_url(f"sqlite:////{filename.strip('C:/')}")
        db.open_conn(
            self.db_uri,
            verify=False,
            show_error_dialogs=False,
        )
        pluginmgr.plugins.clear()
        pluginmgr.load()
        db.create(import_defaults=False)

    def tearDown(self):
        close_all_sessions()
        pluginmgr.plugins.clear()
        db.engine.dispose()

    def test_app_connects_existing_db(self):
        que = run_in_prcess(connect_existing, self.db_uri)

        self.assertTrue(que.get(), "connmgr not called")
        self.assertFalse(que.get(), "yes_no_dialog called")
        self.assertFalse(que.get(), "dialog called")
        self.assertEqual("test", que.get())
        self.assertEqual(0, que.get())


class MethodTests(TestCase):
    @mock.patch("bauble.main.utils.yes_no_dialog")
    @mock.patch("bauble.db.create")
    @mock.patch("bauble.main.utils.message_details_dialog")
    def test_post_loop_create_errors(
        self, mock_msg_dialog, mock_create, mock_yn_dialog
    ):
        mock_create.side_effect = Exception("boom")
        self.assertFalse(
            bauble.main.Application._post_loop(bauble.error.DatabaseError())
        )
        mock_yn_dialog.assert_called()
        mock_create.assert_called()
        mock_msg_dialog.assert_called()

    @mock.patch("bauble.main.pluginmgr.init")
    @mock.patch("bauble.main.utils.message_dialog")
    def test_post_loop_pluginmgr_errors(self, mock_dialog, mock_init):
        mock_init.side_effect = Exception("boom")
        self.assertFalse(bauble.main.Application._post_loop(None))
        mock_dialog.assert_called()
        mock_init.assert_called()

    @mock.patch("bauble.main.utils.message_details_dialog")
    @mock.patch("bauble.main.start_connection_manager")
    @mock.patch("bauble.db.open_conn")
    def test_get_connection_open_conn_fails(
        self, mock_open, mock_connmgr, mock_dialog
    ):
        setup_prefs()
        db.engine = None
        mock_connmgr.return_value = "test", "test_uri"
        exc = bauble.error.DatabaseError()
        mock_open.side_effect = [
            None,
            Exception,
            None,
            exc,
            bauble.error.VersionError(1.0),
            None,
        ]

        self.assertEqual(exc, bauble.main.Application._get_connection(None))
        mock_dialog.assert_called()

    @mock.patch("bauble.gui")
    def test_build_menubar(self, mock_gui):
        mock_app = mock.Mock()
        menu_builder = Gtk.Builder()
        menu_builder.add_from_file(os.path.join(paths.lib_dir(), "bauble.ui"))
        menu_builder.connect_signals(self)
        mock_gui.menubar = menu_builder.get_object("menubar")
        with mock.patch("sys.platform", "win32"):
            bauble.main.Application._build_menubar(mock_app)
        mock_gui.widgets.menu_box.pack_start.assert_called()
        mock_app = mock.Mock()
        with mock.patch("sys.platform", "darwin"):
            bauble.main.Application._build_menubar(mock_app)
        mock_app.set_menubar.assert_called()

    def test_on_activate_bails_on_connection_manager_cancel(self):
        db.engine = None
        with mock.patch.object(bauble.main.Application, "add_window") as mad:
            bauble.main.Application.on_activate(None)
            mad.assert_not_called()
