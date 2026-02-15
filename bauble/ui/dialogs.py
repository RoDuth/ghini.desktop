# Copyright (c) 2005,2006,2007,2008,2009 Brett Adams <brett@belizebotanic.org>
# Copyright (c) 2015-2016 Mario Frasca <mario@anche.no>
# Copyright (c) 2018-2024 Ross Demuth <rossdemuth123@gmail.com>
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
Dialogs
"""
import logging

logger = logging.getLogger(__name__)

from pathlib import Path

from gi.repository import Gtk


def run_file_chooser_dialog(
    text: str,
    parent: Gtk.Window | None,
    action: Gtk.FileChooserAction,
    last_folder: str,
    target: Gtk.Entry,
    suffix: str | None = None,
) -> None:
    """Create and run a FileChooserNative, then write result in target entry
    widget.

    this is just a bit more than a wrapper. it adds 'last_folder', a
    string indicationg the location where to put the FileChooserNative,
    and 'target', an Entry widget.

    :param text: window label text.
    :param parent: the parent window or None.
    :param action: a Gtk.FileChooserAction value.
    :param last_folder: the folder to open the window at.
    :param target: widget that has it value set to the selected filename.
    :param suffix: an extension as a str (e.g. '.csv'). Used as a file filter.
    """
    chooser = Gtk.FileChooserNative.new(text, parent, action)
    if suffix:
        filter_ = Gtk.FileFilter().new()
        filter_.add_pattern("*" + suffix)
        chooser.add_filter(filter_)

    try:
        if last_folder:
            chooser.set_current_folder(last_folder)
        if chooser.run() == Gtk.ResponseType.ACCEPT:
            filename = chooser.get_filename()
            if filename:
                if suffix:
                    filename = str(Path(filename).with_suffix(suffix))
                target.set_text(filename)
                target.set_position(len(filename))
    except Exception as e:  # pylint: disable=broad-except
        logger.warning("unhandled %s exception: %s", type(e).__name__, e)
    chooser.destroy()
