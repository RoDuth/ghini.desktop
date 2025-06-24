# Copyright 2008-2010 Brett Adams
# Copyright 2015-2017 Mario Frasca <mario@anche.no>.
# Copyright 2017 Jardín Botánico de Quito
# Copyright 2016-2025 Ross Demuth <rossdemuth123@gmail.com>
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
# connmgr.py
#

"""
The connection manager provides a GUI for creating and opening
connections. This is the first thing displayed when Ghini starts.
"""
from __future__ import annotations

import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field
from importlib import import_module
from pathlib import Path
from threading import Thread
from types import ModuleType
from typing import Literal
from typing import NotRequired
from typing import Self
from typing import TypedDict
from typing import cast

logger = logging.getLogger(__name__)

import dateutil
from gi.repository import GdkPixbuf
from gi.repository import GLib
from gi.repository import Gtk
from sqlalchemy.engine import URL

import bauble
from bauble import editor
from bauble import paths
from bauble import prefs
from bauble import utils
from bauble.i18n import _

pyodbc: ModuleType | None
try:
    import pyodbc
except ImportError:  # pragma: no cover
    pyodbc = None


def is_package_name(name: str) -> bool:
    """True if name identifies a package and it can be imported"""

    try:
        import_module(name)
        return True
    except ImportError:
        return False


DBS = [("sqlite3", "SQLite"), ("psycopg2", "PostgreSQL"), ("pyodbc", "MSSQL")]

DBTYPES = [name for package, name in DBS if is_package_name(package)]


def retrieve_latest_release_data() -> list | dict | None:
    """Using the github API to grab the latests release info and return the
    json data if successful, otherwise return None
    """
    github_releases_uri = (
        "https://api.github.com/repos/RoDuth/ghini.desktop/releases"
    )
    net_sess = utils.get_net_sess()
    try:
        response = net_sess.get(github_releases_uri, timeout=5)
        if response.ok:
            return response.json()[0]
        logger.info("error while checking for a new release")
    except Exception as e:  # pylint: disable=broad-except
        # used in tests
        logger.warning(
            "unhandled %s(%s) while checking for new release",
            type(e).__name__,
            e,
        )
    finally:
        net_sess.close()
    return None


@dataclass(order=True)
class ComparableVersion:
    major: int
    minor: int
    patch: int
    build: str = "z"


def compare_version(version: str) -> ComparableVersion:
    as_list: list = version.replace("-", ".").split(".")

    for i in range(3):
        as_list[i] = int(as_list[i])

    return ComparableVersion(*as_list)


def check_new_release(github_release_data: dict) -> Literal[False] | dict:
    """Check if the supplied json data descibes a newer release than the
    current version.

    If if is return the data, otherwise return False

    Also updates bauble.release_version and bauble.release_date
    """
    github_release = github_release_data.get("name", "")
    github_prerelease = github_release_data.get("prerelease")
    # update release_version and release_date
    if github_prerelease:
        bauble.release_version = github_release + " (prerelease)"
    else:
        bauble.release_version = github_release
    release_date = github_release_data.get("assets", [{}])[0].get("created_at")
    release_date = dateutil.parser.isoparse(release_date)
    bauble.release_date = release_date.astimezone(tz=None)

    github_version = compare_version(github_release.split()[0][1:])
    current_version = compare_version(bauble.version)
    logger.debug("latest release on github is release: %s", github_release)
    logger.debug(
        "latest release on github is a prerelease?: %s", github_prerelease
    )
    logger.debug("this version %s", current_version)

    if github_version > current_version:
        return github_release_data
    if github_version < current_version:
        logger.info("running unreleased version")

    return False


def notify_new_release(
    connection_manager_dialog: ConnectionManagerDialog,
    retrieve_latest_func: Callable[[], list | dict | None],
    check_new_func: Callable[[dict], Literal[False] | None],
) -> None:
    """If the latest release on github is newer than the current version notify
    the user.

    If its a prerelease version state so.

    :param retrieve_latest_func: a function to retrieve github release data
        json i.e. :func:`retrieve_latest_release_data`
    :param check_new_func: a function to check if release data points to a new
        release and set bauble.release_version i.e. :func:`check_new_release`
    """
    github_release_data = retrieve_latest_func()
    if not isinstance(github_release_data, dict):
        # used in tests
        logger.debug("no release data")
        return
    new_release = check_new_func(github_release_data)
    if new_release:
        # used in tests
        logger.debug("notifying new release")

        def show_message():
            msg = _("New version %s available.") % bauble.release_version
            connection_manager_dialog.notify_message_label.set_label(msg)
            connection_manager_dialog.notify_revealer.set_reveal_child(True)

        GLib.idle_add(show_message)
    else:
        # used in tests
        logger.debug("not new release")


def make_absolute(path: str) -> str:
    """Replaces './' with the appdata directory."""
    if path.startswith("./") or path.startswith(".\\"):
        path = str(Path(paths.appdata_dir(), path[2:]))

    return path


def check_create_paths(directory: str) -> tuple[bool, str]:
    """Given a root directory, check and create the documents and pictures
    directories.

    :return: tuple - bool = False if any errors, error msg str
    """
    # if it's a file, things are not OK
    root = Path(make_absolute(directory))
    docs = Path(root, prefs.prefs.get(prefs.document_path_pref))
    pics = Path(root, prefs.prefs.get(prefs.picture_path_pref))
    logger.debug("root= %s, docs=%s, pics=%s", root, docs, pics)
    thumbs = Path(pics, "thumbs")
    # root should exist as a directory
    msg = ""
    all_valid = [True]
    if root:
        for path, name in (
            (root, _("Root directory")),
            (docs, _("Documents directory")),
            (pics, _("Pictures directory")),
            (thumbs, _("Thumbs directory")),
        ):
            if path.exists():
                if not path.is_dir():
                    all_valid.append(False)
                    msg += name + _(" occupied by non directory.\n")
            else:
                try:
                    path.mkdir()
                except OSError as e:
                    all_valid.append(False)
                    msg += _("DO NOT have permission to create %s:\n%s\n") % (
                        name,
                        e,
                    )

    valid = all(all_valid)
    logger.debug("check_create_paths: valid=%s; msg=%s", valid, msg)

    return valid, msg


ConnectionDict = TypedDict(
    "ConnectionDict",
    {
        "type": str,
        "file": NotRequired[str],
        "default": NotRequired[bool],
        "directory": str,
        "db": NotRequired[str],
        "host": NotRequired[str],
        "port": NotRequired[str],
        "user": NotRequired[str],
        "passwd": NotRequired[bool],
        "options": NotRequired[dict[str, str]],
    },
)


@dataclass
class ConnectionModel:
    """A model for a connection, used to store the connection parameters.

    Provides an interface to the stored prefs.  To use instantiate with
    connection_name only and it will load the rest from you prefs or provide
    sane defaults for a new connection. e.g.::

        model = ConnectionModel("spam")

    """

    connection_name: str

    dbtype: str = field(init=False, default="")
    filename: str = field(init=False, default="")
    database: str = field(init=False, default="")
    host: str = field(init=False, default="")
    port: str = field(init=False, default="")
    user: str = field(init=False, default="")
    rootdir: str = field(init=False, default="")
    passwd: bool = field(init=False, default=False)
    options: dict[str, str] = field(default_factory=dict)

    _use_defaults: bool = field(init=False, repr=False, default=True)

    def __post_init__(self) -> None:
        if not self.connection_name:
            raise ValueError("Must supply a valid connection_name")

        self.load_from_prefs()

    def load_from_prefs(self) -> None:
        params = prefs.prefs.get(bauble.CONN_LIST_PREF, {}).get(
            self.connection_name
        )

        if params:
            self._set_from_params(params)
        else:
            self.use_defaults = True

    def _set_defaults(self) -> None:
        """If a name is available set the defaults."""
        if self.connection_name:
            self.dbtype = "SQLite"
            # use os.path.join here so we get ./
            self.filename = os.path.join(".", self.connection_name + ".db")
            self.rootdir = os.path.join(".", self.connection_name)

    @property
    def use_defaults(self) -> bool:
        return self._use_defaults

    @use_defaults.setter
    def use_defaults(self, value: bool) -> None:
        self._use_defaults = value
        if value:
            self._set_defaults()

    def get_params(self) -> ConnectionDict:
        """Return the params as they should be in prefs."""

        result: ConnectionDict = {
            "type": self.dbtype,
            "directory": self.rootdir,
        }

        if self.dbtype == "SQLite":
            result["file"] = self.filename
            result["directory"] = self.rootdir
            result["default"] = self.use_defaults
        else:
            result["directory"] = self.rootdir
            result["db"] = self.database
            result["host"] = self.host
            result["port"] = self.port
            result["user"] = self.user
            result["passwd"] = self.passwd
            result["options"] = self.options

        return result

    def _set_from_params(self, params: ConnectionDict) -> None:
        self.dbtype = params["type"]

        if self.dbtype == "SQLite":
            self.filename = params.get("file", "")
            self.use_defaults = params.get("default", True)
            self.rootdir = params.get("directory", "")
            self.database = ""
            self.host = ""
            self.port = ""
            self.user = ""
            self.options = {}
            self.passwd = False
        else:
            self.database = params.get("db", "")
            self.host = params.get("host", "")
            self.port = params.get("port", "")
            self.user = params.get("user", "")
            self.rootdir = params.get("directory", "")
            self.passwd = params.get("passwd", False)
            self.options = params.get("options", {})
            self.filename = ""
            self.use_defaults = False

    def save(self) -> None:
        """Save this connection to prefs."""
        if self.connection_name is None:
            return

        logger.debug("save current to prefs")

        connections: dict[str, ConnectionDict] = prefs.prefs.get(
            bauble.CONN_LIST_PREF, {}
        )

        connections[self.connection_name] = self.get_params()
        prefs.prefs[bauble.CONN_LIST_PREF] = connections
        prefs.prefs.save()

    def is_saved(self) -> bool:
        """Check if this connection's parameters are already saved in prefs in
        their current state.
        """
        connections = prefs.prefs.get(bauble.CONN_LIST_PREF, {})
        if self.connection_name not in connections:
            return False

        stored = self.__class__(self.connection_name)
        logger.debug("stored: %s", stored)
        logger.debug("local: %s", self)

        return self == stored

    def remove(self) -> None:
        """Remove this connection from the saved connections."""

        logger.debug("removing connection %s", self.connection_name)

        connections = prefs.prefs.get(bauble.CONN_LIST_PREF, {})
        if self.connection_name in connections:
            del connections[self.connection_name]
            prefs.prefs[bauble.CONN_LIST_PREF] = connections
            prefs.prefs.save()


@Gtk.Template(filename=str(Path(paths.lib_dir(), "connection_box.ui")))
class ConnectionBox(editor.GenericPresenter[ConnectionModel], Gtk.Box):
    """The connection manager GUI."""

    __gtype_name__ = "ConnectionBox"

    __gsignals__ = editor.GenericPresenter.gsignals

    type_combo = cast(Gtk.ComboBoxText, Gtk.Template.Child())
    usedefaults_chkbx = cast(Gtk.CheckButton, Gtk.Template.Child())
    file_entry = cast(Gtk.Entry, Gtk.Template.Child())
    file_btnbrowse = cast(Gtk.Button, Gtk.Template.Child())
    database_entry = cast(Gtk.Entry, Gtk.Template.Child())
    host_entry = cast(Gtk.Entry, Gtk.Template.Child())
    port_entry = cast(Gtk.Entry, Gtk.Template.Child())
    user_entry = cast(Gtk.Entry, Gtk.Template.Child())
    passwd_chkbx = cast(Gtk.CheckButton, Gtk.Template.Child())
    rootdir_entry = cast(Gtk.Entry, Gtk.Template.Child())
    rootdirectory_btnbrowse = cast(Gtk.Button, Gtk.Template.Child())
    rootdir2_entry = cast(Gtk.Entry, Gtk.Template.Child())
    rootdirectory2_btnbrowse = cast(Gtk.Button, Gtk.Template.Child())
    sqlite_parambox = cast(Gtk.Box, Gtk.Template.Child())
    dbms_parambox = cast(Gtk.Box, Gtk.Template.Child())
    # defined twice to convince pylint that it is iterable
    options_liststore = Gtk.ListStore(str, str)
    options_liststore = cast(Gtk.ListStore, Gtk.Template.Child())

    PROBLEM_UNREADABLE = editor.Problem("unreadable_file")

    def __init__(self, model: ConnectionModel) -> None:
        super().__init__(model, self)
        self.widgets_to_model_map = {
            self.type_combo: "dbtype",
            self.file_entry: "filename",
            self.database_entry: "database",
            self.host_entry: "host",
            self.port_entry: "port",
            self.user_entry: "user",
            self.rootdir_entry: "rootdir",
            self.rootdir2_entry: "rootdir",
            self.usedefaults_chkbx: "use_defaults",
            self.passwd_chkbx: "passwd",
        }

        # initialize comboboxes
        for dbapi in DBTYPES:
            self.type_combo.append_text(dbapi)

    def btnbrowse_clicked(
        self, entry: Gtk.Entry, action: Gtk.FileChooserAction
    ) -> None:
        """Generic button browse handler for file and directory entries."""
        previously = entry.get_text()
        last_folder = self.get_parent_folder(previously)
        utils.run_file_chooser_dialog(
            _("Choose a file…"),
            None,
            action=action,
            last_folder=last_folder,
            target=entry,
        )
        self.replace_leading_appdata(entry)

    @Gtk.Template.Callback()
    def on_file_btnbrowse_clicked(self, *_args) -> None:
        self.btnbrowse_clicked(
            self.file_entry,
            Gtk.FileChooserAction.OPEN,
        )

    @Gtk.Template.Callback()
    def on_rootdir_btnbrowse_clicked(self, *_args) -> None:
        self.btnbrowse_clicked(
            self.rootdir_entry,
            Gtk.FileChooserAction.CREATE_FOLDER,
        )

    @Gtk.Template.Callback()
    def on_rootdir2_btnbrowse_clicked(self, *_args) -> None:
        self.btnbrowse_clicked(
            self.rootdir2_entry,
            Gtk.FileChooserAction.CREATE_FOLDER,
        )

    @staticmethod
    def replace_leading_appdata(entry: Gtk.Entry) -> None:
        """Replace leading appdata directory with './' in the entry text."""
        value = entry.get_text()

        if value.startswith(paths.appdata_dir()):
            value = "./" + value[len(paths.appdata_dir()) + 1 :]
            entry.set_text(value)

    @staticmethod
    def get_parent_folder(path: str) -> str:
        """Return the parent folder of the given path, considering './' paths
        are relative to the appdata directory.
        """
        if not path:
            return paths.appdata_dir()

        if path.startswith("."):
            return str(Path(paths.appdata_dir()) / Path(path).parent)

        return str(Path(path).parent)

    @Gtk.Template.Callback()
    def on_type_combo_changed(self, combo: Gtk.ComboBoxText) -> None:
        if self.model.dbtype != combo.get_active_text():
            # if changed reload from prefs (drop any changes)
            self.model.load_from_prefs()

        super().on_combobox_changed(combo)

        if self.model.dbtype == "MSSQL":
            self.add_mssql_default_options()

        if self.model.dbtype == "SQLite":
            self.refresh_sqlite()
        else:
            self.refresh_dbms()

    def refresh_dbms(self) -> None:
        logger.debug("refresh dbms")
        self.sqlite_parambox.set_visible(False)
        self.dbms_parambox.set_visible(True)
        self.problems.clear()
        self.refresh_all_widgets_from_model()
        self.refresh_options_liststore()
        self.database_entry.emit("changed")
        self.host_entry.emit("changed")
        self.port_entry.emit("changed")
        self.user_entry.emit("changed")

    def refresh_sqlite(self) -> None:
        logger.debug("refresh sqlite")
        self.sqlite_parambox.set_visible(True)
        self.dbms_parambox.set_visible(False)
        self.problems.clear()
        self.refresh_all_widgets_from_model()
        self.refresh_entries_sensitive()
        self.file_entry.emit("changed")

    def add_mssql_default_options(self) -> None:
        """Add sensible defaults for new MSSQL connections."""
        if any(
            (
                self.model.database,
                self.model.host,
                self.model.port,
                self.model.options,
            )
        ):
            logger.debug("Model is not new bailing.")
            # not new bail
            return

        if pyodbc is None:
            logger.debug("no pyodbc bailing.")
            return

        drivers = [i for i in pyodbc.drivers() if i.startswith("ODBC Driver")]

        if drivers:
            self.model.options["driver"] = drivers[0]

        self.model.options["MARS_Connection"] = "Yes"
        logger.debug("adding MSSQL sensible defaults %s", self.model.options)

    @Gtk.Template.Callback()
    def on_usedefaults_chkbx_toggled(
        self, check_button: Gtk.CheckButton, *_args
    ) -> None:
        self.model.use_defaults = check_button.get_active()
        self.refresh_all_widgets_from_model()
        self.refresh_entries_sensitive()

    def refresh_entries_sensitive(self) -> None:
        """Set the sensitivity of the entries based on whether defaults are
        used or not.
        """
        sensitive = not self.model.use_defaults
        self.file_entry.set_sensitive(sensitive)
        self.rootdir_entry.set_sensitive(sensitive)
        self.file_btnbrowse.set_sensitive(sensitive)
        self.rootdirectory_btnbrowse.set_sensitive(sensitive)

    @Gtk.Template.Callback()
    def on_file_entry_changed(self, entry: Gtk.Entry) -> None:
        value = super()._on_non_empty_text_entry_changed(entry)

        file = Path(make_absolute(value))
        if file.exists() and os.access(file, os.R_OK):
            self.remove_problem(self.PROBLEM_UNREADABLE, entry)
        elif (
            not file.exists()
            and os.access(file.parent, os.R_OK)
            and os.access(file.parent, os.W_OK)
        ):
            self.remove_problem(self.PROBLEM_UNREADABLE, entry)
        else:
            self.add_problem(self.PROBLEM_UNREADABLE, entry)

    @Gtk.Template.Callback()
    def on_non_empty_text_entry_changed(self, entry: Gtk.Entry) -> None:
        super().on_non_empty_text_entry_changed(entry)

    @Gtk.Template.Callback()
    def on_port_entry_changed(self, entry: Gtk.Entry) -> None:
        # don't allow 0, replace with ''
        value = entry.get_text()
        if value == "0":
            entry.set_text("")

        super().on_text_entry_changed(entry)

    @Gtk.Template.Callback()
    def on_text_entry_changed(self, entry: Gtk.Entry) -> None:
        super().on_text_entry_changed(entry)

    @Gtk.Template.Callback()
    def on_passwd_chkbx_toggled(self, check_button: Gtk.CheckButton) -> None:
        self.model.passwd = check_button.get_active()

    def refresh_options_liststore(self) -> None:
        """Refresh the options liststore with the current options."""
        self.options_liststore.clear()

        for name, value in self.model.options.items():
            self.options_liststore.append([name, value])

        self.options_liststore.append(["", ""])

    def options_edited(
        self,
        path: Gtk.TreePath,
        column: int,
        text: str,
    ) -> None:
        """Generic handler for editing options in the liststore."""
        self.options_liststore[path][column] = text
        name: str
        value: str

        for name, value in self.options_liststore:  # type: ignore[misc]
            if name:
                self.model.options[name] = value

        self.refresh_options_liststore()

    @Gtk.Template.Callback()
    def on_options_name_edited(
        self,
        _cell: Gtk.CellRendererText,
        path: Gtk.TreePath,
        text: str,
    ) -> None:
        self.options_edited(path, 0, text)

    @Gtk.Template.Callback()
    def on_options_value_edited(
        self,
        _cell: Gtk.CellRendererText,
        path: Gtk.TreePath,
        text: str,
    ) -> None:
        self.options_edited(path, 1, text)


@Gtk.Template(filename=str(Path(paths.lib_dir(), "connection_manager.ui")))
class ConnectionManagerDialog(Gtk.Dialog):
    """The connection manager GUI."""

    __gtype_name__ = "ConnectionManagerDialog"

    name_combo = cast(Gtk.ComboBoxText, Gtk.Template.Child())
    remove_button = cast(Gtk.Button, Gtk.Template.Child())
    cancel_button = cast(Gtk.Button, Gtk.Template.Child())
    connect_button = cast(Gtk.Button, Gtk.Template.Child())
    expander = cast(Gtk.Expander, Gtk.Template.Child())
    logo_image = cast(Gtk.Image, Gtk.Template.Child())
    image_box = cast(Gtk.Box, Gtk.Template.Child())
    noconnectionlabel = cast(Gtk.Label, Gtk.Template.Child())
    notify_message_label = cast(Gtk.Label, Gtk.Template.Child())
    notify_close_button = cast(Gtk.Button, Gtk.Template.Child())
    notify_revealer = cast(Gtk.Revealer, Gtk.Template.Child())
    dont_ask_chkbx = cast(Gtk.CheckButton, Gtk.Template.Child())

    first_run = True

    def __init__(self) -> None:
        super().__init__(
            title=f"Ghini {bauble.version}",
            transient_for=bauble.gui.window if bauble.gui else None,
            destroy_with_parent=True,
        )
        self.model: ConnectionModel

        self.setup_name_combo()

        logo_path = Path(paths.lib_dir(), "images", "bauble_logo.png")
        self.logo_image.set_from_file(str(logo_path))
        self.set_icon(GdkPixbuf.Pixbuf.new_from_file(bauble.default_icon))

        logger.debug("checking for new version")
        if self.first_run:
            Thread(
                target=notify_new_release,
                args=[
                    self,
                    retrieve_latest_release_data,
                    check_new_release,
                ],
            ).start()

        self.dont_ask_chkbx.set_active(
            prefs.prefs.get(bauble.CONN_DONT_ASK_PREF, False)
        )

    def setup_name_combo(self) -> None:
        connections = self.filter_supported(
            prefs.prefs.get(bauble.CONN_LIST_PREF, {})
        )

        connection_names = []
        for connection_name in sorted(connections):
            self.name_combo.append_text(connection_name)
            connection_names.append(connection_name)

        if connection_names:
            connection_name = prefs.prefs[bauble.CONN_DEFAULT_PREF]

            if connection_name not in connections:
                connection_name = connection_names[0]

            if connection_name:
                self.name_combo.set_active(
                    connection_names.index(connection_name)
                )

    @staticmethod
    def filter_supported(
        connections: dict[str, ConnectionDict],
    ) -> dict[str, ConnectionDict]:
        """Filter the connections to only include those with a supported
        dbtypes.
        """
        filtered_connections = {}
        for name, params in connections.items():
            if params.get("type") in DBTYPES:
                filtered_connections[name] = params
            else:
                logger.warning(
                    "Connection %s has unsupported type %s",
                    name,
                    params.get("type"),
                )
        return filtered_connections

    def get_connection_box(self) -> ConnectionBox | None:
        connection_box = self.expander.get_child()
        if connection_box:
            return cast(ConnectionBox, connection_box)
        return None

    @Gtk.Template.Callback()
    def on_dialog_response(
        self,
        dialog: Self,
        response: Gtk.ResponseType,
    ) -> bool:
        """The dialog's response signal handler."""
        if response == Gtk.ResponseType.OK:
            msg = ""
            valid = True

            if not getattr(self, "model", None):
                msg = _("No connection set")
                valid = False
            elif self.model.rootdir:  # no value - a global may have been set
                valid, msg = check_create_paths(self.model.rootdir)

            if not valid:
                # don't close the dialog
                utils.message_dialog(msg, Gtk.MessageType.ERROR)
                dialog.stop_emission_by_name("response")
                return True

            prefs.prefs[prefs.root_directory_pref] = make_absolute(
                self.model.rootdir
            )
            self.model.save()

            if self.first_run:
                prefs.prefs[bauble.CONN_DEFAULT_PREF] = (
                    self.name_combo.get_active_text()
                )

        elif response in (
            Gtk.ResponseType.CANCEL,
            Gtk.ResponseType.DELETE_EVENT,
        ):
            connection_box = self.get_connection_box()
            if (
                connection_box
                and not connection_box.problems
                and not self.model.is_saved()
            ):
                # if the model is not saved, ask the user if they want to save
                # their changes before closing the dialog
                msg = (
                    _("Do you want to save your changes to %s?")
                    % self.model.connection_name
                )
                if utils.yes_no_dialog(msg):
                    self.model.save()

        return False

    @Gtk.Template.Callback()
    def on_name_combo_changed(self, combo: Gtk.ComboBoxText) -> None:
        """The name changed so fill in everything else"""
        previous = None

        connection_box = self.get_connection_box()
        if connection_box and not connection_box.problems:
            previous = getattr(self, "model", None)

        connection_name = cast(str, combo.get_active_text())
        logger.debug("name_combo now at %s", connection_name)

        if connection_name:
            self.expander.set_visible(True)
            self.dont_ask_chkbx.set_sensitive(True)
            self.noconnectionlabel.set_visible(False)
            self.swap_connections(previous, connection_name)
        else:
            self.expander.set_visible(False)
            self.dont_ask_chkbx.set_sensitive(False)
            self.noconnectionlabel.set_visible(True)

    def on_problems_changed(
        self, _box: ConnectionBox, has_problems: bool
    ) -> None:
        self.connect_button.set_sensitive(not has_problems)
        self.dont_ask_chkbx.set_sensitive(not has_problems)

    def swap_connections(
        self,
        previous_model: ConnectionModel | None,
        new_name: str,
    ) -> None:
        self.model = ConnectionModel(new_name)
        connection_box = ConnectionBox(self.model)
        self.connect_button.set_sensitive(not bool(connection_box.problems))
        connection_box.connect("problems-changed", self.on_problems_changed)

        child = self.expander.get_child()
        if child:
            self.expander.remove(child)
            child.destroy()

        self.expander.add(connection_box)
        connection_box.show_all()

        connection_box.refresh_all_widgets_from_model()
        connection_box.refresh_options_liststore()

        logger.debug(
            "on_name_combo_changing from %s to %s",
            previous_model and previous_model.connection_name,
            self.model.connection_name,
        )

        if previous_model and not previous_model.is_saved():
            msg = _("Do you want to save %s?") % repr(
                previous_model.connection_name
            )

            if utils.yes_no_dialog(msg):
                previous_model.save()

    @Gtk.Template.Callback()
    @staticmethod
    def on_dont_ask_toggled(check_button: Gtk.CheckButton) -> None:
        prefs.prefs[bauble.CONN_DONT_ASK_PREF] = check_button.get_active()

    @Gtk.Template.Callback()
    def on_notify_close_button_clicked(self, _button) -> None:
        """Close the notification revealer."""
        self.notify_revealer.set_reveal_child(False)

    # TODO put this in utils - can we provide a simple problems validator?
    # i.e. here it would just need to check that the value was not in the
    # current connection names...  (This would also disallow OK)
    def run_entry_dialog(self, title: str, visible: bool = True) -> str | None:
        """Run a minimal dialog with a single entry for user input.

        :param title: The title of the dialog.
        :param visible: If True, the entry will show the text as it is typed,
            otherwise it will be hidden (useful for passwords).
        """
        dialog = Gtk.Dialog(
            title=title,
            transient_for=self,
            modal=True,
            destroy_with_parent=True,
        )
        dialog.add_buttons(
            _("OK"),
            Gtk.ResponseType.ACCEPT,
            _("Cancel"),
            Gtk.ResponseType.CANCEL,
        )
        dialog.set_default_response(Gtk.ResponseType.ACCEPT)
        dialog.set_default_size(250, -1)
        dialog.set_position(Gtk.WindowPosition.CENTER)
        dialog.set_destroy_with_parent(True)
        entry = Gtk.Entry()

        if not visible:
            entry.set_visibility(False)

        entry.connect(
            "activate", lambda entry: dialog.response(Gtk.ResponseType.ACCEPT)
        )
        dialog.get_content_area().pack_start(entry, True, True, 0)
        dialog.show_all()

        user_reply: str | None = None
        if dialog.run() == Gtk.ResponseType.ACCEPT:
            user_reply = entry.get_text()

        dialog.destroy()
        return user_reply

    def remove_connection(self) -> None:
        """Remove current selected connection from combobox and from prefs."""
        self.model.remove()

        connection_box = self.get_connection_box()
        if connection_box:
            self.expander.remove(connection_box)

        self.connect_button.set_sensitive(False)
        self.name_combo.remove(self.name_combo.get_active())
        self.name_combo.set_active(0)

    @Gtk.Template.Callback()
    def on_remove_button_clicked(self, _button: Gtk.Button) -> None:
        """remove the connection from connection list, this does not affect
        the database or its data
        """
        if not self.connection_name:
            return

        msg = (
            _(
                'Are you sure you want to remove "%s"?\n\n'
                "<i>Note: This only removes the connection to the database "
                "and does not affect the database or its data</i>"
            )
            % self.connection_name
        )

        if not utils.yes_no_dialog(msg):
            return

        self.remove_connection()

    @Gtk.Template.Callback()
    def on_add_button_clicked(self, _button: Gtk.Button) -> None:
        if getattr(self, "model", None) and not self.model.is_saved():
            msg = (
                _("Do you want to save your changes to %s ?")
                % self.model.connection_name
            )

            if utils.yes_no_dialog(msg):
                self.model.save()

        name = self.run_entry_dialog(_("Enter a connection name"))
        logger.debug("new name = %s", repr(name))

        if not name:
            return

        connections = prefs.prefs.get(bauble.CONN_LIST_PREF, {})

        if name not in connections:
            self.name_combo.prepend_text(name)
            self.expander.set_expanded(True)
            self.name_combo.set_active(0)

    def get_passwd(self) -> str | None:
        """Show a dialog with and entry and return the value entered."""
        passwd = self.run_entry_dialog(_("Enter your password"), visible=False)
        return passwd

    def parameters_to_uri(self, params: ConnectionDict) -> URL:
        """return connections paramaters as a SQLAlchemy URL object."""
        database = params.get(
            "db",
            make_absolute(params.get("file", "").replace("\\", "/")),
        )
        uri = URL.create(
            drivername=params["type"].lower(),
            username=params.get("user"),
            password=self.get_passwd() if params.get("passwd") else None,
            host=params.get("host"),
            port=int(params["port"]) if params.get("port") else None,
            database=database,
            query=params.get("options", {}),
        )
        return uri

    @property
    def connection_uri(self) -> URL:
        params = self.model.get_params()
        return self.parameters_to_uri(params)

    @property
    def connection_name(self) -> str | None:
        if hasattr(self, "model"):
            return self.model.connection_name
        return None


def start_connection_manager(
    msg: str | None = None,
) -> tuple[str | None, URL | None]:
    """Activate connection manager and return connection name and its
    SQLAlchemy URL object.
    """
    first_run = ConnectionManagerDialog.first_run

    con_mgr = ConnectionManagerDialog()

    if msg:
        con_mgr.dont_ask_chkbx.set_visible(False)
        con_mgr.image_box.remove(con_mgr.logo_image)
        label = Gtk.Label()
        label.set_markup(msg)
        label.set_margin_top(10)
        con_mgr.image_box.pack_start(label, True, True, 12)
        con_mgr.image_box.show_all()

    result: tuple[str | None, URL | None] = None, None

    dont_ask = False
    if first_run:
        # prevent window starting in background - pyinstaller frozen build
        con_mgr.set_keep_above(True)
        dont_ask = prefs.prefs.get(bauble.CONN_DONT_ASK_PREF, False)

    if dont_ask or con_mgr.run() == Gtk.ResponseType.OK:
        result = con_mgr.connection_name, con_mgr.connection_uri

    con_mgr.destroy()

    return result
