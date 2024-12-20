# Copyright 2008-2010 Brett Adams
# Copyright 2012-2015 Mario Frasca <mario@anche.no>.
# Copyright 2017 Jardín Botánico de Quito
# Copyright 2021-2024 Ross Demuth <rossdemuth123@gmail.com>
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

import logging

logger = logging.getLogger(__name__)

import os
import sys
import traceback
from abc import ABC
from abc import abstractmethod
from pathlib import Path
from typing import Iterable
from typing import Protocol

from gi.repository import Gtk  # noqa
from sqlalchemy import Column
from sqlalchemy import Unicode
from sqlalchemy import select
from sqlalchemy.orm.exc import NoResultFound

import bauble
from bauble import db
from bauble import paths
from bauble import utils
from bauble.error import BaubleError
from bauble.i18n import _

plugins: dict[str, "Plugin"] = {}
commands: dict[str, type["CommandHandler"]] = {}
provided: dict[str, type[db.Base]] = {}


def register_command(handler):
    """
    Register command handlers.  If a command is a duplicate then it
    will overwrite the old command of the same name.

    :param handler:  A class which extends pluginmgr.CommandHandler
    """
    logger.debug("registering command handler %s", handler.command)
    if isinstance(handler.command, str):
        if handler.command in commands:
            logger.info("overwriting command %s", handler.command)
        commands[handler.command] = handler
    else:
        for cmd in handler.command:
            if cmd in commands:
                logger.info("overwriting command %s", cmd)
            commands[cmd] = handler


def _create_dependency_pairs(plugs):
    """calculate plugin dependencies, met and unmet

    plugs is an iterable of plugins.

    returned value is a pair, the first item is the dependency pairs that
    can be passed to utils.topological_sort.  The second item is a
    dictionary associating plugin names (from plugs) with the list of unmet
    dependencies.

    """
    depends = []
    unmet = {}
    for plug in plugs:
        for dep in plug.depends:
            try:
                depends.append((plugins[dep], plug))
            except KeyError:
                logger.debug("no dependency %s for %s", dep, plug.__name__)
                unmet_val = unmet.setdefault(plug.__name__, [])
                unmet_val.append(dep)
    return depends, unmet


def load(path=None):
    """Search the plugin path for modules that provide a plugin. If path
    is a directory then search the directory for plugins. If path is
    None then use the default plugins path, bauble.plugins.

    This method populates the pluginmgr.plugins dict and imports the
    plugins but doesn't do any plugin initialization.

    :param path: the path where to look for the plugins
    :type path: str
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
        name = ", ".join(sorted(errors.keys()))
        exc_info = list(errors.values())[0]
        exc_str = utils.xml_safe(exc_info[1])
        tb_str = "".join(traceback.format_tb(exc_info[2]))
        utils.message_details_dialog(
            "Could not load plugin: \n\n<i>%s</i>\n\n%s" % (name, exc_str),
            tb_str,
            typ=Gtk.MessageType.ERROR,
        )

    if len(found) == 0:
        logger.debug("No plugins found at path: %s", path)

    for plugin in found:
        # plugin should be unique
        if isinstance(plugin, type):
            plugins[plugin.__name__] = plugin
            logger.debug("registering plugin %s: %s", plugin.__name__, plugin)
        else:
            plugins[plugin.__class__.__name__] = plugin
            logger.debug(
                "registering plugin %s: %s", plugin.__class__.__name__, plugin
            )


def init(force=False):
    """Initialize the plugin manager.

    1. Check for and install any plugins in the plugins dict that
    aren't in the registry.
    2. Call each init() for each plugin the registry in order of dependency
    3. Register the command handlers in the plugin's commands[]

    NOTE: This is called after the GUI has been created and a connection has
    been established to a database with db.open_conn()
    """
    logger.debug("bauble.pluginmgr.init()")
    # ******
    # NOTE: Be careful not to keep any references to
    # PluginRegistry open here as it will cause a deadlock if you try
    # to create a new database. For example, don't query the
    # PluginRegistry with a session without closing the session.
    # ******

    # search for plugins that are in the plugins dict but not in the registry
    registered = list(plugins.values())
    logger.debug("registered plugins: %s", plugins)
    try:
        # try to access the plugin registry, if the table does not exist
        # then it might mean that we are opening a pre 0.9 database, in this
        # case we just assume all the plugins have been installed and
        # registered, this might not be the right thing to do but at least it
        # allows you to connect to a pre bauble 0.9 database and use it to
        # upgrade to a >=0.9 database
        registered_names = PluginRegistry.names()
        not_installed = [
            p for n, p in plugins.items() if n not in registered_names
        ]
        if len(not_installed) > 0:
            not_registered = ", ".join(
                p.__class__.__name__ for p in not_installed
            )
            msg = _(
                "The following plugins were not found in the plugin "
                f"registry:\n\n<b>{not_registered}</b>\n\n<i>Would you "
                "like to install them now?</i>"
            )
            if force or utils.yes_no_dialog(msg):
                install(not_installed)

        # sort plugins in the registry by their dependencies
        not_registered = []
        for name in PluginRegistry.names():
            try:
                registered.append(plugins[name])
            except KeyError as e:
                logger.debug(
                    "Could not find '%s' plugin. Removing from database", e
                )
                not_registered.append(utils.nstr(name))
                PluginRegistry.remove(name=name)

        if not_registered:
            not_loaded_str = str(", ".join(sorted(not_registered)))
            msg = _(
                "The following plugins are in the registry but could not "
                f"be loaded:\n\n{not_loaded_str}"
            )
            utils.message_dialog(
                utils.xml_safe(msg), typ=Gtk.MessageType.WARNING
            )

    except Exception as e:
        logger.warning("unhandled exception %s", e)
        raise

    if not registered:
        # no plugins to initialize
        return

    deps, _unmet = _create_dependency_pairs(registered)
    ordered = utils.topological_sort(registered, deps)
    if not ordered:
        raise BaubleError(
            _(
                "The plugins contain a dependency loop. This "
                "can happen if two plugins directly or "
                "indirectly rely on each other"
            )
        )

    # call init() for each of the plugins
    for plugin in ordered:
        logger.debug("about to invoke init on: %s", plugin)
        try:
            plugin.init()
            logger.debug("plugin %s initialized", plugin)
        except KeyError:
            # keep the plugin in the registry so if we find it again we do
            # not offer the user the option to reinstall it, something which
            # could overwrite data
            ordered.remove(plugin)
            msg = (
                _(
                    "The %s plugin is listed in the registry "
                    "but wasn't found in the plugin directory"
                )
                % plugin.__class__.__name__
            )
            logger.warning(msg)
        except Exception as e:
            logger.error("%s(%s)", type(e).__name__, e)
            ordered.remove(plugin)
            logger.info(traceback.format_exc())
            safe = utils.xml_safe
            values = dict(
                entry_name=plugin.__class__.__name__, exception=safe(e)
            )
            utils.message_details_dialog(
                _(
                    "Error: Couldn't initialize %(entry_name)s\n\n"
                    "%(exception)s."
                )
                % values,
                traceback.format_exc(),
                Gtk.MessageType.ERROR,
            )

    # register the plugin commands separately from the plugin initialization
    for plugin in ordered:
        if plugin.commands in (None, []):
            continue
        for cmd in plugin.commands:
            try:
                register_command(cmd)
            except Exception as e:
                logger.debug(
                    "exception %s while registering command %s", e, cmd
                )
                msg = (
                    "Error: Could not register command handler.\n\n%s"
                    % utils.xml_safe(str(e))
                )
                utils.message_dialog(msg, Gtk.MessageType.ERROR)

    # add any default configuration entries
    for plugin in ordered:
        from inspect import getfile

        directory = Path(getfile(plugin.__class__)).parent
        logger.debug("plugin directory: %s", directory)
        conf_file = Path(directory) / "default/config.cfg"
        if conf_file.exists():
            logger.debug("plugin conf file found at: %s", conf_file)
            from bauble import prefs

            prefs.update_prefs(conf_file)
    # don't build the tools menu if we're running from the tests and
    # we don't have a gui
    if bauble.gui is not None:
        bauble.gui.build_tools_menu()

    bauble.search.parser.update_domains()


def install(plugins_to_install, import_defaults=True, force=False):
    """
    :param plugins_to_install: A list of plugins to install. If the
        string "all" is passed then install all plugins listed in the
        bauble.pluginmgr.plugins dict that aren't already listed in
        the plugin registry.

    :param import_defaults: Flag passed to the plugin's install()
        method to indicate whether it should import its default data.
    :type import_defaults: bool

    :param force:  Force, don't ask questions.
    :type force: bool
    """

    logger.debug("pluginmgr.install(%s)", str(plugins_to_install))
    if plugins_to_install == "all":
        to_install = list(plugins.values())
    else:
        to_install = plugins_to_install

    if len(to_install) == 0:
        # no plugins to install
        return

    # sort the plugins by their dependency
    depends, unmet = _create_dependency_pairs(list(plugins.values()))
    logger.debug("%s - the dependencies pairs", str(depends))
    if unmet != {}:
        logger.debug("unmet dependecies: %s", str(unmet))
        raise BaubleError("unmet dependencies")
    to_install = utils.topological_sort(to_install, depends)
    logger.debug("%s - this is after topological sort", str(to_install))
    if not to_install:
        raise BaubleError(
            _(
                "The plugins contain a dependency loop. This "
                "means that two plugins "
                "(possibly indirectly) rely on each other"
            )
        )

    try:
        for p in to_install:
            logger.debug("install: %s", p)
            p.install(import_defaults=import_defaults)
            # issue #28: here we make sure we don't add the plugin to the
            # registry twice but we should really update the version number
            # in the future when we accept versioned plugins (if ever)
            if not PluginRegistry.exists(p):
                logger.debug("%s - adding to registry", p)
                PluginRegistry.add(p)
    except Exception as e:
        logger.warning("bauble.pluginmgr.install(): %s", utils.nstr(e))
        raise


class PluginRegistry(db.Base):
    """The PluginRegistry contains a list of plugins that have been installed
    in a particular instance.

    At the moment it only includes the name and version of the plugin but this
    is likely to change in future versions.
    """

    __tablename__ = "plugin"
    name = Column(Unicode(64), unique=True)
    version = Column(Unicode(12))

    @staticmethod
    def add(plugin):
        """Add a plugin to the registry.

        Warning: Adding a plugin to the registry does not install it.  It
        should be installed before adding.
        """
        table = PluginRegistry.__table__
        stmt = table.insert().values(
            name=plugin.__class__.__name__, version=plugin.version
        )
        stmt.execute()

    @staticmethod
    def remove(plugin=None, name=None):
        """Remove a plugin from the registry by name."""
        if name is None:
            name = plugin.__class__.__name__

        table = PluginRegistry.__table__
        stmt = table.delete().where(table.c.name == str(name))
        stmt.execute()

    @staticmethod
    def all(session):
        close_session = False
        if not session:
            close_session = True
            session = db.Session()
        qry = session.query(PluginRegistry)
        results = list(qry)
        if close_session:
            session.close()
        return results

    @staticmethod
    def names(bind=None):
        table = PluginRegistry.__table__
        results = select([table.c.name], bind=bind).execute(bind=bind)
        names = [n[0] for n in results]
        results.close()
        return names

    @staticmethod
    def exists(plugin):
        """Check if plugin exists in the plugin registry."""
        if isinstance(plugin, str):
            name = plugin
            version = None
        else:
            name = plugin.__class__.__name__
            version = plugin.version
        session = db.Session()
        try:
            logger.debug("not using value of version (%s).", version)
            session.query(PluginRegistry).filter_by(
                name=utils.nstr(name)
            ).one()
            return True
        except NoResultFound as e:
            logger.debug("%s(%s)", type(e).__name__, e)
            return False
        finally:
            session.close()


class Plugin:
    """
    commands:
      a map of commands this plugin handled with callbacks,
      e.g dict('cmd', lambda x: handler)
    tools:
      a list of Tool classes that this plugin provides, the
      tools' category and label will be used in Ghini's "Tool" menu
    depends:
      a list of class names that inherit from Plugin that this
      plugin depends on
    provides:
      a dictionary name->class exported by this plugin
    description:
      a short description of the plugin
    """

    commands: list[type["CommandHandler"]] = []
    tools: list[type["Tool"]] = []
    depends: list[str] = []
    provides: dict[str, type] = {}
    description = ""
    version = "0.0"

    @classmethod
    def __init__(cls):
        pass

    @classmethod
    def init(cls):
        """run when first started"""
        pass

    @classmethod
    def install(cls, import_defaults=True):
        """install() is run when a new plugin is installed, it is usually
        only run once for the lifetime of the plugin
        """
        pass


class Tool:  # pylint: disable=too-few-public-methods
    category: str | None = None
    label: str
    enabled = True

    @classmethod
    def start(cls):
        pass


class ViewThread(Protocol):
    def cancel(self):
        """Cancel thread."""

    def join(self):
        """Join to the thread"""

    def start(self):
        """Start thread"""


class View:
    def __init__(self, *args, **kwargs) -> None:
        """If a class extends this View it will most likely also inherit from
        Gtk.Box and should call this __init__.
        """
        super().__init__(*args, **kwargs)
        self.running_threads: list[ViewThread] = []
        self.prevent_threads = False

    def cancel_threads(self) -> None:
        for thread in self.running_threads:
            thread.cancel()
        for thread in self.running_threads:
            thread.join()
        self.running_threads = []

    def start_thread(self, thread: ViewThread) -> ViewThread:
        self.running_threads.append(thread)
        thread.start()
        if self.prevent_threads:
            self.cancel_threads()
        return thread

    def update(self, *args: str | None) -> None:
        raise NotImplementedError


class Viewable(Protocol):
    """Describes a View subclass, which is likely to also subclass Gtk.Box."""

    def cancel_threads(self) -> None:
        """Cancel running threads"""

    def start_thread(self, thread: ViewThread) -> ViewThread:
        """Start a thread"""

    def set_visible(self, visible: bool) -> None:
        """Set visible property, most likely from subclassing Gtk.Box"""

    def show_all(self) -> None:
        """Set visible property, most likely from subclassing Gtk.Box"""


class CommandHandler(ABC):
    command: str | Iterable[str | None]

    def get_view(self) -> View | None:
        """return the view for this command handler"""
        return None

    @abstractmethod
    def __call__(self, cmd: str, arg: str | None) -> None:
        """do what this command handler does"""


def _find_module_names(path):
    """
    :param path: where to look for modules
    """
    modules = []
    for root, subdirs, files in os.walk(path):
        if root != path and any(i.startswith("__init__.p") for i in files):
            modules.append(root[len(path) + 1 :].replace(os.sep, "."))
    return modules


def _find_plugins(path):
    """Return the plugins at path."""
    import bauble.plugins

    plugins_list = []
    errors = {}

    plugin_names = [
        f"bauble.plugins.{module}" for module in _find_module_names(path)
    ]

    from importlib import import_module

    for name in plugin_names:
        mod = None
        # Fast path: see if the module has already been imported.

        if name in sys.modules:
            mod = sys.modules[name]
        else:
            try:
                mod = import_module(name, bauble.plugins)
            except Exception as e:
                logger.debug(
                    "Could not import the %s module. %s(%s)",
                    name,
                    type(e).__name__,
                    e,
                )
                errors[name] = sys.exc_info()
        if not hasattr(mod, "plugin"):
            continue

        # if mod.plugin is a function it should return a plugin or list of
        # plugins
        if callable(mod.plugin):
            mod_plugin = mod.plugin()
            logger.debug(
                "module %s contains callable plugin: %s", mod, mod_plugin
            )
        else:
            mod_plugin = mod.plugin
            logger.debug(
                "module %s contains non callable plugin: %s", mod, mod_plugin
            )

        def is_plugin_class(obj):
            return isinstance(obj, type) and issubclass(obj, Plugin)

        if isinstance(mod_plugin, (list, tuple)):
            for plug in mod_plugin:
                if is_plugin_class(plug):
                    logger.debug("append plugin class %s:%s", name, plug)
                    plugins_list.append(plug())
                elif isinstance(plug, Plugin):
                    logger.debug("append plugin instance %s:%s", name, plug)
                    plugins_list.append(plug)
        elif is_plugin_class(mod_plugin):
            logger.debug("append plugin class %s:%s", name, mod_plugin)
            plugins_list.append(mod_plugin())
        elif isinstance(mod_plugin, Plugin):
            logger.debug("append plugin instance %s:%s", name, mod_plugin)
            plugins_list.append(mod_plugin)
        else:
            logger.warning(
                "%s.plugin is not an instance of pluginmgr.Plugin",
                mod.__name__,
            )
    return plugins_list, errors
