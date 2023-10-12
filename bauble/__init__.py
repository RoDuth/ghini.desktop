# Copyright (c) 2005,2006,2007,2008,2009 Brett Adams <brett@belizebotanic.org>
# Copyright (c) 2012-2017 Mario Frasca <mario@anche.no>
# Copyright 2017 Jardín Botánico de Quito
# Copyright (c) 2016-2021 Ross Demuth <rossdemuth123@gmail.com>
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
The top level module for Ghini.
"""

import logging
import os
import sys
import traceback
import warnings
from datetime import datetime
from shutil import copy2
from typing import TYPE_CHECKING

import gi

gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")

from bauble import paths
from bauble.version import version

version_tuple = tuple(version.split("."))
release_date = datetime.utcfromtimestamp(0)
release_version = None
installation_date = datetime.now()

import bauble.i18n

logger = logging.getLogger(__name__)

# setup logging early
# temp set DEBUG until startup sets according to prefs
logger.setLevel(logging.DEBUG)
consoleLevel = logging.WARNING

if not os.path.exists(paths.appdata_dir()):
    os.makedirs(paths.appdata_dir())
log_file = os.path.join(paths.appdata_dir(), "bauble.log")
if os.path.exists(log_file):
    try:
        copy2(log_file, log_file + "_PREV")
    except Exception as e:  # pylint: disable=broad-except
        print("Copying previous log file failed: %s(%s)", type(e).__name__, e)
formatter = logging.Formatter(
    "%(asctime)s - %(name)s:%(lineno)d - %(levelname)s - %(thread)d "
    "- %(message)s"
)
file_handler = logging.FileHandler(log_file, "w+", "utf-8")
file_handler.setFormatter(formatter)
logging.getLogger().addHandler(file_handler)
file_handler.setLevel(logging.DEBUG)

if not paths.main_is_frozen():
    console_handler = logging.StreamHandler()
    logging.getLogger().addHandler(console_handler)
    console_handler.setFormatter(formatter)

    console_handler.setLevel(consoleLevel)


def warn_with_traceback(
    message, category, filename, lineno, file=None, line=None
):
    log = file if hasattr(file, "write") else sys.stderr
    traceback.print_stack(file=log)
    log.write(
        warnings.formatwarning(message, category, filename, lineno, line)
    )


# to print a traceback for warnings to stderr set env var:
# BAUBLE_WARN_TRACE=True
if os.environ.get("BAUBLE_WARN_TRACE"):
    warnings.showwarning = warn_with_traceback
    warnings.simplefilter("always")

# to use faulthandler set env var:
# PYTHONFAULTHANDLER=1

# to set prefs.testing set envar:
# BAUBLE_TEST=True

# to set sqlalchemy debug set envar:
# BAUBLE_SQLA_DEBUG=True


def pb_set_fraction(fraction):
    """set progressbar fraction safely

    provides a safe way to handle the progress bar if the gui isn't started,
    we use this in the tests where there is no gui
    """
    if gui is not None and gui.progressbar is not None:
        fraction = round(fraction, 3)
        gui.progressbar.set_fraction(fraction)


# make sure we look in the lib path for modules
sys.path.append(paths.lib_dir())

# set SQLAlchemy logging level
logging.getLogger("sqlalchemy").setLevel(logging.WARNING)

if TYPE_CHECKING:
    from bauble.ui import GUI

    gui: GUI | None = None
    """bauble.gui is the instance :class:`bauble.ui.GUI`"""
else:
    gui = None

# default_icon = None
default_icon = os.path.join(paths.lib_dir(), "images", "icon.png")
"""The default icon."""

conn_name = None
"""The name of the current connection."""

last_handler = None

conn_default_pref = "conn.default"
conn_list_pref = "conn.list"


def command_handler(cmd, arg):
    """Call a command handler.

    :param cmd: The name of the command to call
    :type cmd: str

    :param arg: The arg to pass to the command handler
    :type arg: list
    """
    logger.debug('command_handler cmd: %s arg: "%s"', cmd, arg)
    from gi.repository import Gtk

    from bauble import pluginmgr
    from bauble import utils

    global last_handler
    handler_cls = None
    try:
        handler_cls = pluginmgr.commands[cmd]
    except KeyError:
        if cmd is None:
            utils.message_dialog(_("No default handler registered"))
        else:
            utils.message_dialog(_("No command handler for %s") % cmd)
        return

    if not isinstance(last_handler, handler_cls):
        last_handler = handler_cls()
    handler_view = last_handler.get_view()
    old_view = gui.get_view()
    if type(old_view) is not type(handler_view) and handler_view:
        # remove the accel_group from the window if the previous view
        # had one
        # NOTE this (add/remove accel_group) is no longer required
        if hasattr(old_view, "accel_group"):
            gui.window.remove_accel_group(old_view.accel_group)
        # add the new view, and its accel_group if it has one
        gui.set_view(handler_view)
        if hasattr(handler_view, "accel_group"):
            gui.window.add_accel_group(handler_view.accel_group)
    try:
        last_handler(cmd, arg)
    except Exception as e:
        msg = utils.xml_safe(e)
        logger.error("bauble.command_handler(): %s", msg)
        utils.message_details_dialog(
            msg, traceback.format_exc(), Gtk.MessageType.ERROR
        )
