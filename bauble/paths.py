# Copyright (c) 2005,2006,2007,2008,2009 Brett Adams <brett@belizebotanic.org>
# Copyright (c) 2012-2016,2018 Mario Frasca <mario@anche.no>
# Copyright (c) 2016-2022 Ross Demuth <rossdemuth123@gmail.com>
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
# provide paths that bauble will need
#
"""
Access to standard paths used by Ghini.
"""
import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

import tempfile

TEMPDIR = tempfile.mkdtemp()
"""global temp directory, deleted on application shutdown."""

tempfile.tempdir = TEMPDIR


def main_is_frozen():
    """tell if running a frozen (pyinstaller) executable."""
    return hasattr(sys, "frozen")


def main_dir():
    """Returns the path of the bauble executable."""
    if main_is_frozen():
        directory = os.path.dirname(sys.executable)
    else:
        directory = os.path.dirname(sys.argv[0])
    if directory == "":
        directory = os.curdir
    return os.path.abspath(directory)


def root_dir():
    """return the root directory we are running from."""
    if main_is_frozen():
        root = Path(sys.executable).parent
    else:
        root = Path(__file__).parent.parent
    return root


def lib_dir():
    """Returns the path of the bauble module."""
    if main_is_frozen():
        directory = os.path.join(main_dir(), "bauble")
    else:
        directory = os.path.dirname(__file__)
    return os.path.abspath(directory)


def locale_dir():
    """Returns the root path of the locale files"""

    directory = os.path.join(installation_dir(), "share", "locale")
    return os.path.abspath(directory)


def installation_dir():
    """Returns the root path of the installation target"""

    if sys.platform in ("linux", "darwin"):
        # installation_dir, relative to this file, is 7 levels up.
        this_file_location = __file__.split(os.path.sep)
        try:
            index_of_lib = this_file_location.index("lib")
        except ValueError:
            index_of_lib = 0
        directory = os.path.sep.join(this_file_location[: -index_of_lib - 1])
    elif sys.platform == "win32":
        # main_dir is the location of the scripts, which is located in the
        # installation_dir:
        directory = main_dir()
    else:
        raise NotImplementedError(
            "This platform does not support " f"translations: {sys.platform}"
        )
    return os.path.abspath(directory)


def appdata_dir():
    """Returns the path to where application data and settings are saved."""
    if sys.platform == "win32":
        if is_portable_installation():
            appd = os.path.join(main_dir(), "Appdata")
        elif "APPDATA" in os.environ:
            appd = os.path.join(os.environ["APPDATA"], "Bauble")
        elif "USERPROFILE" in os.environ:
            appd = os.path.join(
                os.environ["USERPROFILE"], "Application Data", "Bauble"
            )
        else:
            raise Exception(
                "Could not get path for user settings: no "
                "APPDATA or USERPROFILE variable"
            )
    elif sys.platform == "darwin":
        # pylint: disable=no-name-in-module
        from AppKit import (  # type: ignore [import-untyped]  # noqa
            NSApplicationSupportDirectory,
        )
        from AppKit import NSSearchPathForDirectoriesInDomains
        from AppKit import NSUserDomainMask

        appd = os.path.join(
            NSSearchPathForDirectoriesInDomains(
                NSApplicationSupportDirectory, NSUserDomainMask, True
            )[0],
            "Bauble",
        )
    elif sys.platform == "linux":
        # using os.expanduser is more reliable than os.environ['HOME']
        # because if the user runs bauble with sudo then it will
        # return the path of the user that used sudo instead of ~root
        try:
            appd = os.path.join(
                os.path.expanduser("~%s" % os.environ["USER"]), ".bauble"
            )
        except Exception as e:
            raise Exception(
                "Could not get path for user settings: could not expand $HOME "
                f'for user {os.environ["USER"]}'
            ) from e
    else:
        raise Exception(
            "Could not get path for user settings: unsupported platform"
        )
    return os.path.abspath(appd)


def is_portable_installation():
    """tell whether ghini is running on a USB stick

    only relevant on Windows

    if the installation_dir contains a writable appdata.dir, then we are
    running on a USB stick, and we are keeping appdata there.
    """

    if sys.platform != "win32":
        return False
    if not main_is_frozen():
        return False
    try:
        test_file_name = os.path.join(main_dir(), "Appdata", "temp.tmp")
        with open(test_file_name, "w+") as f:
            f.write("test")
        os.remove(test_file_name)
        return True
    except Exception:
        return False


def templates_dir():
    """This is mostly just a wrapper for prefs templates_root_pref for
    convenience.

    :return: the template root directory if one is set else the example
        templates directory in appdata.
    """
    from . import pluginmgr

    if "ReportToolPlugin" in pluginmgr.plugins:
        from . import prefs
        from .plugins.report.template_downloader import TEMPLATES_ROOT_PREF

        return prefs.prefs.get(
            TEMPLATES_ROOT_PREF, os.path.join(appdata_dir(), "templates")
        )
    # no report plugin no templates.
    return None
