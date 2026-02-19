# Copyright 2026 Ross Demuth <rossdemuth123@gmail.com>
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
Utils for the desktop environment.
"""
import os
import subprocess
import sys

from bauble.ui import dialogs


def open(target: str, dialog_on_error: bool = False) -> None:
    # pylint: disable=redefined-builtin
    """Opens a file, url, etc. using the default application on Windows, macOS,
    or Linux.
    """
    try:
        if sys.platform == "darwin":
            subprocess.call(["open", target])
        elif sys.platform == "win32":
            os.startfile(target)
        elif sys.platform == "linux":
            subprocess.call(["xdg-open", target])
        else:
            raise OSError(f"Unsupported operating system: {sys.platform}")
    except Exception as e:  # pylint: disable=broad-except
        if dialog_on_error:
            dialogs.message_dialog(str(e))
        else:
            raise
