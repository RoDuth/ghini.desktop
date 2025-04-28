# Copyright 2008-2010 Brett Adams
# Copyright 2012-2015 Mario Frasca <mario@anche.no>.
# Copyright 2017 Jardín Botánico de Quito
# Copyright 2021-2025 Ross Demuth <rossdemuth123@gmail.com>
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
#
# pluginmgr.py
#

"""
Manage plugin registry, loading, initialization and installation.  The
plugin manager should be started in the following order:

1. load the plugins: search the plugin directory for plugins,
populates the plugins dict (happens in load())

2. install the plugins if not in the registry, add properly
installed plugins in to the registry (happens in load())

3. initialize the plugins (happens in init())
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


import os
import traceback
import types
from abc import ABC
from abc import abstractmethod
from collections.abc import Sequence
from importlib import import_module
from inspect import getfile
from pathlib import Path
from typing import Iterable
from typing import Literal
from typing import Protocol

from gi.repository import Gtk  # noqa
from sqlalchemy import Column
from sqlalchemy import Unicode
from sqlalchemy import literal
from sqlalchemy import select

import bauble.plugins
from bauble import db
from bauble import paths
from bauble import prefs
from bauble import utils
from bauble.error import BaubleError
from bauble.i18n import _
from bauble.search import parser

plugins: dict[str, Plugin] = {}
commands: dict[str | None, type[CommandHandler]] = {}


def register_command(handler: type[CommandHandler]) -> None:
    """Register command handlers.

    If a command is a duplicate then it will overwrite the old command of the
    same name.

    Plugins have their ``CommandHandlers`` registered during ``init`` by
    including them in their ``Plugin.commands`` list.

    Command handlers that are not part of a plugin need to be registered
    independently e.g.::

        class FooCommandHandler(pluginmgr.CommandHandler):
            command = ["foo"]
            ...

        pluginmgr.register_command(FooCommandHandler)
    """
    logger.debug("registering command handler %s", handler.command)
    for cmd in handler.command:
        if cmd in commands:
            logger.info("overwriting command %s", cmd)
        commands[cmd] = handler


def _create_dependency_pairs(
    plugs: Sequence[Plugin],
) -> tuple[list[tuple[Plugin, Plugin]], dict[str, list[str]]]:
    """Calculate plugin dependencies, met and unmet.

    Returned value is a pair, the first item is the dependency pairs that
    can be passed to ``utils.topological_sort``.  The second item is a
    dictionary associating plugin names (from :param plugs:) with the list of
    unmet dependencies.
    """
    depends: list[tuple[Plugin, Plugin]] = []
    unmet: dict[str, list[str]] = {}

    for plug in plugs:
        for dep in plug.depends:
            try:
                depends.append((plugins[dep], plug))
            except KeyError:
                logger.debug(
                    "no dependency %s for %s", dep, type(plug).__name__
                )
                unmet_val = unmet.setdefault(type(plug).__name__, [])
                unmet_val.append(dep)

    return depends, unmet


def load(path: str | None = None) -> None:
    """Search the plugin path for modules that provide a plugin. If path
    is a directory then search the directory for plugins. If path is
    None then use the default plugins path, bauble.plugins.

    This method populates the pluginmgr.plugins dict and imports the
    plugins but doesn't do any plugin initialization.

    :param path: the path where to look for the plugins
    """

    if path is None:
        path = os.path.join(paths.lib_dir(), "plugins")

    logger.debug("pluginmgr.load(%s)", path)
    found, errors = _find_plugins(path)
    logger.debug("found=%s, errors=%s", found, errors)

    # show error dialog for plugins that couldn't be loaded...we only
    # give details for the first error and assume the others are the
    # same...and if not then it doesn't really help anyways
    if errors:
        error = list(errors.values())[0]
        exc_str = utils.xml_safe(error)
        values = {"name": ", ".join(sorted(errors.keys())), "exc_str": exc_str}
        tb_str = "".join(traceback.format_tb(error.__traceback__))
        utils.message_details_dialog(
            _("Could not load plugin: \n\n%(name)s\n\n%(exc_str)s") % values,
            tb_str,
            Gtk.MessageType.ERROR,
        )

    if not found:
        logger.error("No plugins found at path: %s", path)

    for plugin in found:
        # plugin should be unique
        plugins[type(plugin).__name__] = plugin
        logger.debug(
            "registering plugin %s: %s", type(plugin).__name__, plugin
        )


def init(force: bool = False) -> None:
    """Initialize the plugin manager.

    1. Check for and install any plugins in the plugins dict that aren't in the
       registry.
    2. Call each init() for each plugin the registry in order of dependency
    3. Register the command handlers in the plugin's commands[]
    4. Update prefs if the plugin supplies any defaults
    5. Build the tools menu from the tools provided by plugins
    6. Update the search parser's domains list from the plugins

    NOTE: This is called after the GUI has been created and a connection has
    been established to a database with db.open_conn()

    :param force:  Force, don't ask questions.
    """
    logger.debug("bauble.pluginmgr.init()")

    _install_unregistered(force)
    registered, unregistered = _get_registered_unregistered()

    if unregistered:
        not_loaded_str = str(", ".join(sorted(unregistered)))
        msg = (
            _(
                "The following plugins are in the registry but could not "
                "be loaded:\n\n%s"
            )
            % not_loaded_str
        )
        utils.message_dialog(utils.xml_safe(msg), typ=Gtk.MessageType.WARNING)

    if not registered:
        logging.warning("no plugins to initialise")
        # no plugins to initialize
        return

    deps, _unmet = _create_dependency_pairs(registered)
    registered = utils.topological_sort(registered, deps)

    # call init() for each of the plugins
    failed: list[str] = []
    for plugin in registered.copy():
        logger.debug("about to invoke init on: %s", plugin)

        try:
            if any(name in failed for name in plugin.depends):
                raise BaubleError(
                    "dependencies for {plugin.name} plugin are missing"
                )

            plugin.init()
            logger.debug("plugin %s initialized", plugin)
        except Exception as e:  # pylint: disable=broad-except
            logger.error("%s(%s)", type(e).__name__, e)
            registered.remove(plugin)
            failed.append(type(plugin).__name__)
            logger.info(traceback.format_exc())
            values = {
                "entry_name": type(plugin).__name__,
                "exception": utils.xml_safe(e),
            }
            utils.message_details_dialog(
                _(
                    "Error: Couldn't initialize %(entry_name)s\n\n"
                    "%(exception)s."
                )
                % values,
                traceback.format_exc(),
                Gtk.MessageType.ERROR,
            )

    _register_commands(registered)

    _update_prefs(registered)

    if bauble.gui is not None:
        bauble.gui.build_tools_menu()

    parser.update_domains()


def _update_prefs(registered: list[Plugin]) -> None:
    """Add any default prefs configuration entries provided by the supplied
    Plugins.

    All supplied Plugins are expected to have been added to the PluginRegistry
    first.
    """
    for plugin in registered:

        directory = Path(getfile(plugin.__class__)).parent
        logger.debug("plugin directory: %s", directory)
        conf_file = Path(directory) / "default/config.cfg"
        if conf_file.exists():
            logger.debug("plugin conf file found at: %s", conf_file)

            prefs.update_prefs(conf_file)


def _register_commands(registered: list[Plugin]) -> None:
    """Register any CommandHandlers provided by supplied Plugins.

    All supplied Plugins are expected to have been added to the PluginRegistry
    first.
    """
    for plugin in registered:

        if not plugin.commands:
            continue

        for cmd in plugin.commands:
            try:
                register_command(cmd)
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.debug(
                    "exception %s(%s) while registering command %s",
                    type(e).__name__,
                    e,
                    cmd,
                )
                msg = _(
                    "Error: Could not register command handler.\n\n" f"{cmd}"
                )
                utils.message_dialog(msg, Gtk.MessageType.ERROR)


def _get_registered_unregistered() -> tuple[list[Plugin], list[str]]:
    """If there are currently any registered plugins that didn't successfully
    install (failed to load, etc. i.e. they can not be found in ``plugins``)
    remove them.

    Return the list of registered plugins and unregistered plugin names.
    """
    registered: list[Plugin] = []
    unregistered: list[str] = []
    for name in PluginRegistry.names():
        try:
            registered.append(plugins[name])
        except KeyError:
            logger.debug(
                "Could not find '%s' plugin. Removing from database", name
            )
            unregistered.append(name)
            PluginRegistry.remove(name=name)
    return registered, unregistered


def _install_unregistered(force: bool = False) -> None:
    """Look for any plugins in the plugins dict that are not currently in the
    PluginRegistry and ask the user if they want to install them now.

    This should be called at the start of ``init`` to pick up any new plugins.
    """

    registered_names = PluginRegistry.names()
    not_installed = [
        plugin
        for name, plugin in plugins.items()
        if name not in registered_names
    ]

    if not_installed:
        not_registered_str = ", ".join(
            type(plugin).__name__ for plugin in not_installed
        )
        msg = (
            _(
                "The following plugins were not found in the plugin "
                "registry:\n\n<b>%s</b>\n\n<i>Would you like to install them "
                "now?</i>"
            )
            % not_registered_str
        )
        if force or utils.yes_no_dialog(msg):
            install(not_installed)


def install(
    to_install: Sequence[Plugin] | Literal["all"],
    import_defaults: bool = True,
) -> None:
    """Install Plugins in the correct order.

    :param to_install: the plugins to install. If the string "all" is passed
        then install all plugins listed in the bauble.pluginmgr.plugins dict
        that aren't already listed in the plugin registry.
    :param import_defaults: Flag passed to the plugin's install()
        method to indicate whether it should import its default data.
    """
    if isinstance(to_install, str):
        if to_install == "all":
            to_install = list(plugins.values())
        else:
            raise ValueError("Invalid value for to_install: {to_install}")

    logger.debug("pluginmgr.install(%s)", str(plugins))

    if not to_install:
        logger.debug("no plugins to install")
        return

    # sort the plugins by their dependencies
    depends, unmet = _create_dependency_pairs(list(plugins.values()))
    logger.debug("%s - the dependencies pairs", str(depends))

    if unmet:
        logger.warning("unmet dependencies: %s", str(unmet))
        raise BaubleError("unmet dependencies")

    to_install = utils.topological_sort(to_install, depends)
    logger.debug("%s - this is after topological sort", str(to_install))

    if not to_install:
        raise BaubleError(
            "The plugins contain a dependency loop. This means that two "
            "plugins (possibly indirectly) rely on each other"
        )

    try:
        for plugin in to_install:
            logger.debug("install: %s", plugin)
            plugin.install(import_defaults=import_defaults)
            # NOTE consider, here we make sure we don't add the plugin to the
            # registry twice but we should really update the version number
            # in the future when we accept versioned plugins (if ever)
            if not PluginRegistry.exists(plugin):
                logger.debug("%s - adding to registry", plugin)
                PluginRegistry.add(plugin)
    except Exception as e:
        logger.warning(
            "installing plugins: %s caused: %s(%s)",
            to_install,
            type(e).__name__,
            e,
        )
        raise


class PluginRegistry(db.Base):
    """The PluginRegistry contains a list of plugins that have been installed
    in a particular instance.
    """

    # NOTE At the moment this only includes the name and version of the plugin
    # but this is likely to change in future versions.

    __tablename__ = "plugin"

    name: str = Column(Unicode(64), unique=True)
    version: str = Column(Unicode(12))

    @staticmethod
    def add(plugin: Plugin) -> None:
        """Add a plugin to the registry.

        Warning: Adding a plugin to the registry does not install it.  It
        should be installed before adding.
        """
        table = PluginRegistry.__table__
        stmt = table.insert().values(
            name=plugin.__class__.__name__, version=plugin.version
        )
        with db.engine.begin() as connection:
            connection.execute(stmt)

    @staticmethod
    def remove(plugin: Plugin | None = None, name: str | None = None) -> None:
        """Remove a plugin from the registry by name."""
        if name is None:
            name = type(plugin).__name__

        table = PluginRegistry.__table__
        stmt = table.delete().where(table.c.name == str(name))
        with db.engine.begin() as connection:
            connection.execute(stmt)

    @staticmethod
    def names() -> list[str]:
        table = PluginRegistry.__table__
        stmt = select([table.c.name])
        with db.engine.begin() as connection:
            return connection.execute(stmt).scalars().all()

    @staticmethod
    def exists(plugin: Plugin) -> bool:
        """Check if plugin exists in the plugin registry."""
        name = type(plugin).__name__
        version = plugin.version
        logger.debug("not using value of version (%s).", version)
        table = PluginRegistry.__table__
        stmt = select(literal(True)).where(table.c.name == name)

        with db.engine.begin() as connection:
            return bool(connection.execute(stmt).scalar())


class Plugin:
    """All modules to be treated as plugins (generally on the bauble.plugins
    path) should contain a class derived from this class and make them
    discoverable by that module's ``plugin`` attribute.

    These subclasses describe each plugin module, and provide methods to
    install (on the plugins first use) and initialise (each time the app
    starts) the plugin. If required to avoid conflicts they should also supply
    which other plugins they depend upon (i.e. to ensure correct initialisation
    order).  They also reveal the ``CommandHandler``s and ``Tool``s the plugin
    provides.
    """

    commands: list[type[CommandHandler]] = []
    tools: list[type[Tool]] = []
    depends: list[str] = []
    description = ""
    version = "0.0"

    @classmethod
    def init(cls) -> None:
        """Called at application startup"""

    @classmethod
    def install(cls, import_defaults: bool = True) -> None:
        """Called when a new plugin is installed.

        it is usually only run once for the lifetime of the plugin.  It
        provides a place to do any setup required for the plugin (e.g.
        populating database tables with starting values, etc.)
        """


class Tool(ABC):  # pylint: disable=too-few-public-methods
    """Base class for plugin tools for the ``bauble.gui.tools_menu``.

    :cvar category: is the name of the submenu to place the tool in.  If None
        they will be at the root of the menu.
    "cvar label: the menu label for the tool.
    """

    category: str | None = None
    label: str
    # enabled = True  UNUSED

    @classmethod
    @abstractmethod
    def start(cls) -> None: ...


class ViewThread(Protocol):
    def cancel(self): ...
    def join(self): ...
    def start(self): ...


class Viewable(Protocol):
    """Describes a View subclass, which is likely to also subclass Gtk.Box."""

    prevent_threads: bool

    def cancel_threads(self) -> None: ...
    def start_thread(self, thread: ViewThread) -> ViewThread: ...
    def update(self) -> None: ...
    def set_visible(self, visible: bool) -> None: ...
    def show_all(self) -> None: ...


class CommandHandler(ABC):
    """A base class to provide a 'command' and what to do when it is called.

    CommandHandlers provide a way to call functionality via a string without
    having to know the exact details of the functionality being called.

    If a ``View`` is required for this functionality it should be returned by
    the ``get_view`` classmethod.

    Commands are most commonly called by the main UI (``bauble.gui``) by the
    user but may also be called by menu actions, other plugins, etc.. (via
    ``bauble.command_handler``). Most, but not all, are associated with a
    ``Plugin``.
    """

    command: Iterable[str | None]

    @classmethod
    def get_view(cls) -> Viewable | None:
        """return the view for this command handler"""
        return None

    @abstractmethod
    def __call__(self, cmd: str, arg: str | None) -> None:
        """do what this command handler does"""


def _find_module_names(path: str) -> list[str]:
    """
    :param path: where to look for modules
    """
    modules = []
    for root, _subdirs, files in os.walk(path):
        if root != path and any(i.startswith("__init__.p") for i in files):
            modules.append(root[len(path) + 1 :].replace(os.sep, "."))
    return modules


def _find_plugins(path: str) -> tuple[list[Plugin], dict[str, BaseException]]:
    """Return the plugins at path."""

    plugins_list: list[Plugin] = []
    errors: dict[str, BaseException] = {}

    plugin_names = [
        f"bauble.plugins.{module}" for module in _find_module_names(path)
    ]

    def append_plugins(mod_plugin: Plugin | list[type[Plugin]]) -> None:
        logger.debug("module %s contains plugin: %s", mod, mod_plugin)

        if isinstance(mod_plugin, list):
            for plug in mod_plugin:
                plugin = plug()

                append_plugins(plugin)

        elif isinstance(mod_plugin, Plugin):
            logger.debug("append plugin instance %s:%s", name, mod_plugin)
            plugins_list.append(mod_plugin)
        else:
            logger.warning(
                "%s.plugin is not an instance of pluginmgr.Plugin",
                mod.__name__,
            )

    for name in plugin_names:
        mod: types.ModuleType | None = None

        try:
            mod = import_module(name, "bauble.plugins")
        except ModuleNotFoundError as e:
            logger.debug(
                "Could not import the %s module. %s(%s)",
                name,
                type(e).__name__,
                e,
            )
            errors[name] = e

        if not mod or not hasattr(mod, "plugin"):
            continue

        append_plugins(mod.plugin())

    return plugins_list, errors
