# Copyright (c) 2005,2006,2007,2008,2009 Brett Adams <brett@belizebotanic.org>
# Copyright (c) 2012-2015 Mario Frasca <mario@anche.no>
# Copyright (c) 2020-2024 Ross Demuth <rossdemuth123@gmail.com>
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
import unittest

# from tempfile import NamedTemporaryFile
from pathlib import Path
from tempfile import mkstemp

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

from sqlalchemy.orm import close_all_sessions
from sqlalchemy.pool import StaticPool

import bauble
from bauble import db
from bauble import paths
from bauble import pluginmgr
from bauble import prefs
from bauble.error import BaubleError

# by default use sqlite memory uri
# uri = "sqlite:///:memory:"
uri = "sqlite:///file:testdb?mode=memory&cache=shared&uri=true"
# uri = 'postgresql://test:test@localhost/test'

# allow user to overide uri via an envar
# e.g. to run tests on postgresql:
# BAUBLE_TEST_DB_URI=postgresql://test:test@localhost/test pytest
if os.environ.get("BAUBLE_TEST_DB_URI"):
    uri = os.environ["BAUBLE_TEST_DB_URI"]

bauble.gui = None  # type: ignore[assignment]


def run_app():
    """Convenience function to start the application GUI in its current state.

    Can be used to visually check the state of the test data when debuging
    tests, e.g. add this at the point you wish to open the app::

        from bauble.test import run_app; run_app()

    NOTE: Most likely only want to use this one test at at time as do_shutdown
    deletes TEMPDIR.
    """
    from bauble import ui
    from bauble.main import Application

    bauble.gui = ui.GUI()

    app = Application()
    app.run()


def update_gui():
    """
    Flush any GTK Events.  Used for doing GUI testing.
    """
    import gi

    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk

    while Gtk.events_pending():
        Gtk.main_iteration()


def wait_on_threads():
    """Wait for any still running threads to complete"""
    import threading
    from time import sleep

    while threading.active_count() > 1:
        sleep(0.1)


def check_dupids(filename):
    """
    Return a list of duplicate ids in a glade file
    """
    ids = set()
    duplicates = set()
    import lxml.etree as etree

    tree = etree.parse(filename)
    for el in tree.getiterator():
        if el.tag == "col":
            continue
        elid = el.get("id")
        if elid not in ids:
            ids.add(elid)
        elif elid and elid not in duplicates:
            duplicates.add(elid)
    if duplicates:
        logger.warning(duplicates)
    return list(duplicates)


class BaubleClassTestCase(unittest.TestCase):
    """Test case class that only sets up once for all tests in the class.

    Intended for use cases where setting up may be time consuming and tearing
    down may not be required between tests.

    NOTE: running tests in an order other than default (all tests from the same
    class grouped together) will result in setUpClass and tearDownClass being
    called more than once.
    """

    @classmethod
    def setUpClass(cls):
        bauble.gui = None
        assert uri is not None, "The database URI is not set"
        bauble.db.engine = None
        bauble.conn_name = None
        try:
            poolclass = None
            if uri.startswith("sqlite"):
                # we know we're connecting to an empty database, use StaticPool
                # so threads work in memory database.
                poolclass = StaticPool
            db.open_conn(
                uri,
                verify=False,
                show_error_dialogs=False,
                poolclass=poolclass,
            )
        except Exception as e:  # pylint: disable=broad-except
            print(e, file=sys.stderr)
        if not bauble.db.engine:
            raise BaubleError("not connected to a database")
        Path(paths.appdata_dir()).mkdir(parents=True, exist_ok=True)
        bauble.utils.BuilderLoader.builders = {}
        # FAILS test_on_prefs_backup_restore in windows.
        # self.temp_prefs_file = NamedTemporaryFile(suffix='.cfg')
        # self.temp = self.temp_prefs_file.name
        cls.handle, cls.temp = mkstemp(suffix=".cfg", text=True)
        # reason not to use `from bauble.prefs import prefs`
        prefs.default_prefs_file = cls.temp
        prefs.prefs = prefs._prefs(filename=cls.temp)
        prefs.prefs.init()
        prefs.prefs[prefs.web_proxy_prefs] = "no_proxies"
        prefs.testing = True
        pluginmgr.plugins.clear()
        pluginmgr.load()
        db.create(import_defaults=False)
        pluginmgr.install("all", False)
        pluginmgr.init()
        cls.session = db.Session()
        bauble.logger.setLevel(logging.DEBUG)
        logging.getLogger().setLevel(logging.DEBUG)
        # clear meta cache
        bauble.meta.get_cached_value.clear_cache()
        logger.debug("prefs filename: %s", prefs.prefs._filename)

    @classmethod
    def tearDownClass(cls):
        update_gui()
        wait_on_threads()
        cls.session.rollback()
        close_all_sessions()
        db.metadata.drop_all(bind=db.engine)
        pluginmgr.plugins.clear()
        if os.path.exists(cls.temp):
            os.close(cls.handle)
            os.remove(cls.temp)
        db.engine.dispose()


class BaubleTestCase(unittest.TestCase):
    """The main test case to use

    This version setup a new database for every test.
    """

    def setUp(self):
        assert uri is not None, "The database URI is not set"
        bauble.db.engine = None
        bauble.conn_name = None
        try:
            poolclass = None
            if uri.startswith("sqlite"):
                # we know we're connecting to an empty database, use StaticPool
                # so threads work in memory database.
                poolclass = StaticPool
            db.open_conn(
                uri,
                verify=False,
                show_error_dialogs=False,
                poolclass=poolclass,
            )
        except Exception as e:  # pylint: disable=broad-except
            print(e, file=sys.stderr)
        if not bauble.db.engine:
            raise BaubleError("not connected to a database")
        Path(paths.appdata_dir()).mkdir(parents=True, exist_ok=True)
        bauble.utils.BuilderLoader.builders = {}
        # FAILS test_on_prefs_backup_restore in windows.
        # self.temp_prefs_file = NamedTemporaryFile(suffix='.cfg')
        # self.temp = self.temp_prefs_file.name
        self.handle, self.temp = mkstemp(suffix=".cfg", text=True)
        # reason not to use `from bauble.prefs import prefs`
        prefs.default_prefs_file = self.temp
        prefs.prefs = prefs._prefs(filename=self.temp)
        prefs.prefs.init()
        prefs.prefs[prefs.web_proxy_prefs] = "no_proxies"
        prefs.testing = True
        pluginmgr.plugins.clear()
        pluginmgr.load()
        db.create(import_defaults=False)
        pluginmgr.install("all", False)
        pluginmgr.init()
        self.session = db.Session()
        bauble.logger.setLevel(logging.DEBUG)
        logging.getLogger().setLevel(logging.DEBUG)
        # clear meta cache
        bauble.meta.get_cached_value.clear_cache()
        logger.debug("prefs filename: %s", prefs.prefs._filename)

    def tearDown(self):
        update_gui()
        wait_on_threads()
        self.session.rollback()
        close_all_sessions()
        db.metadata.drop_all(bind=db.engine)
        pluginmgr.plugins.clear()
        os.close(self.handle)
        if os.path.exists(self.temp):
            os.remove(self.temp)
        db.engine.dispose()


def mockfunc(msg=None, name=None, caller=None, result=False, *args, **kwargs):
    caller.invoked.append((name, msg))
    return result


def get_setUp_data_funcs():
    """Search plugins directory for tests and return setUp_data functions."""
    from importlib import import_module

    funcs = []
    root = paths.root_dir()
    for i in Path(root).glob("bauble/plugins/**/test_*.py"):
        mod_path = str(i).replace(os.sep, ".")[len(str(root)) + 1 : -3]
        try:
            mod = import_module(mod_path)
            func = getattr(mod, "setUp_data")
            funcs.append(func)
        except Exception:
            pass
    return sorted(funcs, key=lambda func: func.order)
