# Copyright (c) 2005,2006,2007,2008,2009 Brett Adams <brett@belizebotanic.org>
# Copyright (c) 2012-2015 Mario Frasca <mario@anche.no>
# Copyright (c) 2020-2022 Ross Demuth <rossdemuth123@gmail.com>
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

import sys
import unittest
import os
from tempfile import mkstemp
# from tempfile import NamedTemporaryFile
from pathlib import Path
from sqlalchemy.pool import StaticPool

import logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

import bauble
from bauble import db
from bauble.error import BaubleError
from bauble import pluginmgr
from bauble import prefs
from bauble import paths

# for sake of testing, just use sqlite3.
uri = 'sqlite:///:memory:'


def update_gui():
    """
    Flush any GTK Events.  Used for doing GUI testing.
    """
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk

    while Gtk.events_pending():
        Gtk.main_iteration()


def check_dupids(filename):
    """
    Return a list of duplicate ids in a glade file
    """
    ids = set()
    duplicates = set()
    import lxml.etree as etree
    tree = etree.parse(filename)
    for el in tree.getiterator():
        if el.tag == 'col':
            continue
        elid = el.get('id')
        if elid not in ids:
            ids.add(elid)
        elif elid and elid not in duplicates:
            duplicates.add(elid)
    logger.warning(duplicates)
    return list(duplicates)


class MockLoggingHandler(logging.Handler):
    """Mock logging handler to check for expected logs."""

    def __init__(self, *args, **kwargs):
        self.reset()
        super().__init__(*args, **kwargs)

    def emit(self, record):
        received = self.messages.setdefault(
            record.name, {}).setdefault(
                record.levelname.lower(), [])
        received.append(self.format(record))

    def reset(self):
        self.messages = {}


class BaubleTestCase(unittest.TestCase):

    def setUp(self):
        assert uri is not None, "The database URI is not set"
        try:
            # we know we're connecting to an empty database, use StaticPool so
            # threads work in memory database.
            db.open(uri, verify=False, show_error_dialogs=False,
                    poolclass=StaticPool)
        except Exception as e:  # pylint: disable=broad-except
            print(e, file=sys.stderr)
        if not bauble.db.engine:
            raise BaubleError('not connected to a database')
        Path(paths.appdata_dir()).mkdir(parents=True, exist_ok=True)
        bauble.utils.BuilderLoader.builders = {}
        # FAILS test_on_prefs_backup_restore in windows.
        # self.temp_prefs_file = NamedTemporaryFile(suffix='.cfg')
        # self.temp = self.temp_prefs_file.name
        self.handle, self.temp = mkstemp(suffix='.cfg', text=True)
        # reason not to use `from bauble.prefs import prefs`
        prefs.default_prefs_file = self.temp
        prefs.prefs = prefs._prefs(filename=self.temp)
        prefs.prefs.init()
        prefs.prefs[prefs.web_proxy_prefs] = 'use_requests_without_proxies'
        prefs.testing = True
        bauble.pluginmgr.plugins = {}
        pluginmgr.load()
        db.create(import_defaults=False)
        pluginmgr.install('all', False, force=True)
        pluginmgr.init()
        self.session = db.Session()
        self.handler = MockLoggingHandler()
        logging.getLogger().addHandler(self.handler)
        logging.getLogger().setLevel(logging.DEBUG)
        logger.debug('prefs filename: %s', prefs.prefs._filename)

    def tearDown(self):
        update_gui()
        logging.getLogger().removeHandler(self.handler)
        self.session.close()
        db.metadata.drop_all(bind=db.engine)
        bauble.pluginmgr.commands.clear()
        pluginmgr.plugins.clear()
        os.close(self.handle)
        os.remove(self.temp)
        db.engine.dispose()
        # self.temp_prefs_file.close()


def mockfunc(msg=None, name=None, caller=None, result=False, *args, **kwargs):
    caller.invoked.append((name, msg))
    return result


def get_setUp_data_funcs():
    """Search plugins directory for tests and return setUp_data functions."""
    from importlib import import_module
    funcs = []
    root = paths.root_dir()
    for i in Path(root).glob('bauble/plugins/**/test_*.py'):
        mod_path = str(i).replace(os.sep, '.')[len(str(root)) + 1:-3]
        try:
            mod = import_module(mod_path)
            func = getattr(mod, 'setUp_data')
            funcs.append(func)
        except Exception:
            pass
    return funcs
