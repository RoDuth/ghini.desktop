# pylint: disable=no-self-use,protected-access,too-many-public-methods
# Copyright (c) 2005,2006,2007,2008,2009 Brett Adams <brett@belizebotanic.org>
# Copyright (c) 2012-2015 Mario Frasca <mario@anche.no>
# Copyright 2017 Jardín Botánico de Quito
# Copyright (c) 2025 Ross Demuth <rossdemuth123@gmail.com>
#
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
test plugin manager
"""

import logging
import os
from pathlib import Path
from tempfile import mkdtemp
from types import SimpleNamespace
from unittest import TestCase
from unittest import mock

logger = logging.getLogger(__name__)

from gi.repository import Gtk
from sqlalchemy.engine import make_url

from bauble import db
from bauble import paths
from bauble import pluginmgr
from bauble.error import BaubleError
from bauble.test import BaubleTestCase
from bauble.test import uri


class DumbHandler(pluginmgr.CommandHandler):
    command = ["dumb"]

    def __call__(self, cmd, arg) -> None:
        return


class A(pluginmgr.Plugin):
    initialized = False
    installed = False
    commands = [DumbHandler]

    @classmethod
    def init(cls):
        cls.initialized = True

    @classmethod
    def install(cls, import_defaults=True):
        cls.installed = True


class B(pluginmgr.Plugin):
    depends = ["A"]
    initialized = False
    installed = False

    @classmethod
    def init(cls):
        cls.initialized = True

    @classmethod
    def install(cls, import_defaults=True):
        cls.installed = True


class C(pluginmgr.Plugin):
    depends = ["B"]
    initialized = False
    installed = False

    @classmethod
    def init(cls):
        assert A.initialized and B.initialized
        cls.initialized = True

    @classmethod
    def install(cls, import_defaults=True):
        cls.installed = True


class FailingInitPlugin(pluginmgr.Plugin):
    initialized = False
    installed = False

    @classmethod
    def init(cls):
        cls.initialized = True
        raise BaubleError("can't init")

    @classmethod
    def install(cls, import_defaults=True):
        cls.installed = True


class DependsOnFailingInitPlugin(pluginmgr.Plugin):
    depends = ["FailingInitPlugin"]
    initialized = False
    installed = False

    @classmethod
    def init(cls):
        cls.initialized = True

    @classmethod
    def install(cls, import_defaults=True):
        cls.installed = True


class FailingInstallPlugin(pluginmgr.Plugin):
    initialized = False
    installed = False

    @classmethod
    def init(cls):
        cls.initialized = True

    @classmethod
    def install(cls, import_defaults=True):
        cls.installed = True
        raise BaubleError("can't install")


class DependsOnFailingInstallPlugin(pluginmgr.Plugin):
    depends = ["FailingInstallPlugin"]
    initialized = False
    installed = False

    @classmethod
    def init(cls):
        cls.initialized = True

    @classmethod
    def install(cls, import_defaults=True):
        cls.installed = True


class PluginMgrTests(BaubleTestCase):
    def test_install(self):
        """Test importing default data from plugin."""

        # this emulates the PlantsPlugin install() method but only
        # imports the family.csv file...if PlantsPlugin.install()
        # changes we should change this method as well
        class Dummy(pluginmgr.Plugin):
            @classmethod
            def init(cls):
                pass

            @classmethod
            def install(cls, import_defaults=True):

                if not import_defaults:
                    return
                path = os.path.join(
                    paths.lib_dir(), "plugins", "plants", "default"
                )
                filenames = os.path.join(path, "family.csv")
                from bauble.plugins.imex.csv_ import CSVRestore

                csv = CSVRestore()
                try:
                    csv.start([filenames], metadata=db.metadata, force=True)
                except Exception as e:
                    logger.error(e)
                    raise
                from bauble.plugins.plants import Family

                self.assertEqual(self.session.query(Family).count(), 1387)

        pluginmgr.plugins[Dummy.__name__] = Dummy
        pluginmgr.install([Dummy])


class GlobalFunctionsTests(TestCase):
    def setUp(self):
        A.initialized = A.installed = False
        B.initialized = B.installed = False
        C.initialized = C.installed = False
        pluginmgr.plugins = {}

    def tearDown(self):
        pluginmgr.plugins = {}

    def test_create_dependency_pairs(self):
        plug_a = A()
        plug_b = B()
        plug_c = C()
        pluginmgr.plugins[C.__name__] = plug_c
        pluginmgr.plugins[B.__name__] = plug_b
        pluginmgr.plugins[A.__name__] = plug_a
        dep, unmet = pluginmgr._create_dependency_pairs(
            [plug_a, plug_b, plug_c]
        )
        self.assertEqual(dep, [(plug_a, plug_b), (plug_b, plug_c)])
        self.assertEqual(unmet, {})

    def test_create_dependency_pairs_missing_base(self):
        plug_b = B()
        plug_c = C()
        pluginmgr.plugins[C.__name__] = plug_c
        pluginmgr.plugins[B.__name__] = plug_b
        dep, unmet = pluginmgr._create_dependency_pairs([plug_b, plug_c])
        self.assertEqual(dep, [(plug_b, plug_c)])
        self.assertEqual(unmet, {"B": ["A"]})

    def test_find_plugins_no_plugins(self):
        plugins, errors = pluginmgr._find_plugins("foo/bar")

        self.assertEqual(plugins, [])
        self.assertEqual(errors, {})

    def test_find_plugins_error(self):
        directory = mkdtemp()
        path = Path(directory, "test")
        path.mkdir()
        init = path / "__init__.py"
        init.touch()
        plugins, errors = pluginmgr._find_plugins(directory)

        self.assertEqual(plugins, [])
        self.assertEqual(
            {k: str(v) for k, v in errors.items()},
            {
                "bauble.plugins.test": str(
                    ModuleNotFoundError(
                        "No module named 'bauble.plugins.test'"
                    )
                )
            },
        )

    @mock.patch("bauble.pluginmgr.import_module")
    def test_find_plugins_not_a_plugin_warns(self, mock_import):
        mock_import.return_value = SimpleNamespace(
            plugin=object, __name__="FOO"
        )
        path = Path(paths.lib_dir(), "plugins")

        with self.assertLogs(level="WARNING") as logs:
            plugins, errors = pluginmgr._find_plugins(str(path))

        self.assertIn(
            "FOO.plugin is not an instance of pluginmgr.Plugin", logs.output[0]
        )
        self.assertEqual(plugins, [])
        self.assertEqual(errors, {})

    @mock.patch("bauble.pluginmgr.utils.message_details_dialog")
    def test_load_w_error_notifies(self, mock_dialog):
        directory = mkdtemp()
        path = Path(directory, "test")
        path.mkdir()
        init = path / "__init__.py"
        init.touch()

        with self.assertLogs(level="DEBUG") as logs:
            pluginmgr.load(directory)

        self.assertTrue(
            any(
                f"No plugins found at path: {directory}" in i
                for i in logs.output
            )
        )
        mock_dialog.assert_called()
        self.assertIn("Could not load", mock_dialog.call_args[0][0])

    def test_get_registered_unregistered_all_unregistered(self):
        db.open_conn(make_url(uri), verify=False)
        db.metadata.drop_all(db.engine, checkfirst=True)
        db.metadata.create_all(db.engine)
        plug_a = A()
        plug_b = B()
        plug_c = C()
        pluginmgr.PluginRegistry.add(plug_a)
        pluginmgr.PluginRegistry.add(plug_b)
        pluginmgr.PluginRegistry.add(plug_c)
        reg, unreg = pluginmgr._get_registered_unregistered()

        self.assertEqual([], reg)
        self.assertCountEqual(
            [type(i).__name__ for i in [plug_a, plug_b, plug_c]], unreg
        )

    def test_get_registered_unregistered_all_registered(self):
        db.open_conn(make_url(uri), verify=False)
        db.metadata.drop_all(db.engine, checkfirst=True)
        db.metadata.create_all(db.engine)
        plug_a = A()
        plug_b = B()
        plug_c = C()
        pluginmgr.plugins[C.__name__] = plug_c
        pluginmgr.plugins[B.__name__] = plug_b
        pluginmgr.plugins[A.__name__] = plug_a
        pluginmgr.PluginRegistry.add(plug_a)
        pluginmgr.PluginRegistry.add(plug_b)
        pluginmgr.PluginRegistry.add(plug_c)
        reg, unreg = pluginmgr._get_registered_unregistered()

        self.assertCountEqual([plug_c, plug_b, plug_a], reg)
        self.assertEqual([], unreg)

    def test_get_registered_unregistered_removes_not_in_plugins(self):
        db.open_conn(make_url(uri), verify=False)
        db.metadata.drop_all(db.engine, checkfirst=True)
        db.metadata.create_all(db.engine)
        plug_a = A()
        plug_b = B()
        plug_c = C()
        pluginmgr.plugins[C.__name__] = plug_c
        pluginmgr.plugins[B.__name__] = plug_b
        pluginmgr.PluginRegistry.add(plug_a)
        pluginmgr.PluginRegistry.add(plug_b)
        pluginmgr.PluginRegistry.add(plug_c)
        reg, unreg = pluginmgr._get_registered_unregistered()

        self.assertCountEqual([plug_c, plug_b], reg)
        self.assertEqual([type(plug_a).__name__], unreg)
        self.assertFalse(pluginmgr.PluginRegistry.exists(plug_a))

    @mock.patch("bauble.pluginmgr.register_command")
    @mock.patch("bauble.pluginmgr.utils.message_dialog")
    def test_register_commands_exception(self, mock_dialog, mock_reg):
        mock_reg.side_effect = ValueError("Boom")
        plug_a = A()
        plug_b = B()
        plug_c = C()
        pluginmgr._register_commands([plug_a, plug_b, plug_c])

        mock_dialog.assert_called_with(
            "Error: Could not register command handler.\n\n" f"{DumbHandler}",
            Gtk.MessageType.ERROR,
        )


class StandalonePluginMgrTests(TestCase):
    def setUp(self):
        A.initialized = A.installed = False
        B.initialized = B.installed = False
        C.initialized = C.installed = False
        pluginmgr.plugins = {}
        pluginmgr.commands = {}

    def tearDown(self):
        for z in [A, B, C]:
            z.initialized = z.installed = False

    def test_successful_init(self):
        "pluginmgr.init() should be successful"

        db.open_conn(make_url(uri), verify=False)
        db.create(False)
        pluginmgr.plugins[C.__name__] = C()
        pluginmgr.plugins[B.__name__] = B()
        pluginmgr.plugins[A.__name__] = A()
        pluginmgr.init(force=True)

        self.assertTrue(A.initialized)
        self.assertTrue(B.initialized)
        self.assertTrue(C.initialized)

        # Test that the command handlers get properly registered...
        self.assertEqual(pluginmgr.commands, {"dumb": DumbHandler})

        # and re-registering doesn't change
        pluginmgr.register_command(DumbHandler)

        self.assertEqual(pluginmgr.commands, {"dumb": DumbHandler})

        # just for the coverage
        self.assertIsNone(DumbHandler.get_view())

    @mock.patch("bauble.pluginmgr.utils.message_dialog")
    @mock.patch("bauble.pluginmgr._get_registered_unregistered")
    def test_init_unregistered(self, mock_unreg, mock_dialog):
        db.open_conn(make_url(uri), verify=False)
        db.create(False)
        plug_a = A()
        mock_unreg.return_value = ([plug_a], ["foo"])
        pluginmgr.plugins[A.__name__] = plug_a

        pluginmgr.init(force=True)

        mock_dialog.assert_called_with(
            "The following plugins are in the registry but could not "
            "be loaded:\n\nfoo",
            typ=Gtk.MessageType.WARNING,
        )

    @mock.patch("bauble.pluginmgr._create_dependency_pairs")
    @mock.patch("bauble.pluginmgr._get_registered_unregistered")
    def test_init_no_registered_bails(self, mock_unreg, mock_deps):
        db.open_conn(make_url(uri), verify=False)
        db.metadata.drop_all(db.engine, checkfirst=True)
        db.metadata.create_all(db.engine)
        mock_unreg.return_value = ([], [])
        mock_deps.return_value = ([], {})
        plug_a = A()
        pluginmgr.plugins[A.__name__] = plug_a

        with self.assertLogs(level="WARNING") as logs:
            pluginmgr.init(force=True)

        self.assertIn("no plugins to initialise", logs.output[0])
        mock_deps.assert_called_once()

    def test_init_with_problem(self):
        """pluginmgr.init() using plugin which can't initialize"""

        db.open_conn(make_url(uri), verify=False)
        db.create(False)
        pluginmgr.plugins[FailingInitPlugin.__name__] = FailingInitPlugin()
        pluginmgr.plugins[DependsOnFailingInitPlugin.__name__] = (
            DependsOnFailingInitPlugin()
        )
        with mock.patch("bauble.utils.message_details_dialog") as mock_dialog:
            pluginmgr.init(force=True)

            mock_dialog.assert_called()

        self.assertFalse(DependsOnFailingInitPlugin.initialized)

    def test_init_with_dependancy_problem_raises(self):
        "pluginmgr.init() using plugin which can't install"

        db.open_conn(make_url(uri), verify=False)
        db.create(False)
        pluginmgr.plugins[FailingInstallPlugin.__name__] = (
            FailingInstallPlugin()
        )
        pluginmgr.plugins[DependsOnFailingInstallPlugin.__name__] = (
            DependsOnFailingInstallPlugin()
        )

        self.assertRaises(BaubleError, pluginmgr.init, force=True)

    def test_install(self):
        """Test pluginmgr.install()"""

        plug_a = A()
        plug_b = B()
        plug_c = C()
        pluginmgr.plugins[C.__name__] = plug_c
        pluginmgr.plugins[B.__name__] = plug_b
        pluginmgr.plugins[A.__name__] = plug_a
        db.open_conn(make_url(uri), verify=False)
        db.create(False)
        pluginmgr.install((plug_a, plug_b, plug_c))

        self.assertTrue(A.installed and B.installed and C.installed)

    def test_install_dependencies_b_a(self):
        """test that loading B will also load A but not C"""

        plug_a = A()
        plug_b = B()
        plug_c = C()
        pluginmgr.plugins[B.__name__] = plug_b
        pluginmgr.plugins[A.__name__] = plug_a
        pluginmgr.plugins[C.__name__] = plug_c
        self.assertFalse(C.installed)
        self.assertFalse(B.installed)
        self.assertFalse(A.installed)
        db.open_conn(make_url(uri), verify=False)
        db.create(False)
        # the creation of the database installed all plugins, so we manually
        # reset everything, just to make sure we really test the logic
        C.installed = B.installed = A.installed = False
        # should try to load the A plugin
        pluginmgr.install((plug_b,))

        self.assertTrue(B.installed)
        self.assertTrue(A.installed)
        # TODO is this correct?
        # self.assertFalse(C.installed)

    def test_install_dependencies_c_b_a(self):
        """test that loading C will load B and consequently A"""

        plug_a = A()
        plug_b = B()
        plug_c = C()
        pluginmgr.plugins[B.__name__] = plug_b
        pluginmgr.plugins[A.__name__] = plug_a
        pluginmgr.plugins[C.__name__] = plug_c
        self.assertFalse(C.installed)
        self.assertFalse(B.installed)
        self.assertFalse(A.installed)
        db.open_conn(make_url(uri), verify=False)
        db.create(False)
        # the creation of the database installed all plugins, so we manually
        # reset everything, just to make sure we really test the logic
        C.installed = B.installed = A.installed = False
        # should try to load the A plugin
        pluginmgr.install((plug_c,))

        self.assertTrue(C.installed)
        self.assertTrue(B.installed)
        self.assertTrue(A.installed)

    def test_install_bad_str_raise(self):
        self.assertRaises(ValueError, pluginmgr.install, "any")

    @mock.patch("bauble.pluginmgr._create_dependency_pairs")
    def test_install_unmet_raise(self, mock_dep_pairs):

        plug_a = A()
        plug_b = B()
        plug_c = C()
        pluginmgr.plugins[C.__name__] = plug_c
        pluginmgr.plugins[B.__name__] = plug_b
        pluginmgr.plugins[A.__name__] = plug_a
        deps = [(plug_b, plug_c), (plug_a, plug_b)]
        mock_dep_pairs.return_value = (deps, {"a": ["d", "e"]})

        with self.assertRaises(BaubleError) as cm:
            pluginmgr.install((plug_a, plug_b, plug_c))
        self.assertIn("unmet dependencies", str(cm.exception))

    @mock.patch("bauble.pluginmgr.utils.topological_sort")
    def test_install_no_to_install_raise(self, mock_sort):
        plug_a = A()
        plug_b = B()
        plug_c = C()
        pluginmgr.plugins[C.__name__] = plug_c
        pluginmgr.plugins[B.__name__] = plug_b
        pluginmgr.plugins[A.__name__] = plug_a
        mock_sort.return_value = []

        with self.assertRaises(BaubleError) as cm:
            pluginmgr.install((plug_a, plug_b, plug_c))
        self.assertIn("contain a dependency loop", str(cm.exception))


class PluginRegistryTests(BaubleTestCase):
    def test_registry(self):
        """Test pluginmgr.PluginRegistry"""

        # this is the plugin object
        plugin = A()

        # test that adding works
        pluginmgr.PluginRegistry.add(plugin)
        self.assertTrue(pluginmgr.PluginRegistry.exists(plugin))

        # test that removing works
        pluginmgr.PluginRegistry.remove(plugin)
        self.assertTrue(not pluginmgr.PluginRegistry.exists(plugin))
