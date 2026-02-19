# Copyright (c) 2005,2006,2007,2008,2009 Brett Adams <brett@belizebotanic.org>
# Copyright (c) 2015-2016 Mario Frasca <mario@anche.no>
# Copyright (c) 2018-2026 Ross Demuth <rossdemuth123@gmail.com>
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
from typing import cast

from gi.repository import GdkPixbuf
from gi.repository import GLib
from gi.repository import Gtk
from gi.repository import Pango

import bauble
from bauble.i18n import _


def file_chooser_dialog(
    text: str,
    parent: Gtk.Window | None,
    action: Gtk.FileChooserAction,
    last_folder: str,
    target: Gtk.Entry,
    suffix: str | None = None,
) -> None:
    """Create and run a FileChooserNative, then write result in target entry
    widget.

    This is just a bit more than a wrapper. it adds 'last_folder', a
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


def create_message_dialog(
    msg: str,
    typ: Gtk.MessageType = Gtk.MessageType.INFO,
    buttons: Gtk.ButtonsType = Gtk.ButtonsType.OK,
    parent: Gtk.Window | None = None,
    resizable: bool = True,
) -> Gtk.MessageDialog:
    """Create a message dialog.

    :param msg: The markup to use for the message. The value should be escaped
        in case it contains any HTML entities.
    :param typ: A GTK message type constant.  The default is
        Gtk.MessageType.INFO.
    :param buttons: A GTK buttons type constant.  The default is
        Gtk.ButtonsType.OK.
    :param parent: The parent window for the dialog
    :param resizable: should the dialog be resizale (can cause the window to be
        excessively large when msg is large)

    Returns a :class:`Gtk.MessageDialog`
    """
    if parent is None:
        try:  # this might get called before bauble has started
            parent = bauble.gui.window
        except AttributeError:
            parent = None
    dialog = Gtk.MessageDialog(
        modal=True,
        destroy_with_parent=True,
        transient_for=parent,
        message_type=typ,
        buttons=buttons,
    )
    dialog.set_position(Gtk.WindowPosition.CENTER)
    dialog.set_title("Ghini")
    dialog.set_markup(msg)
    if resizable:
        dialog.set_property("resizable", True)

    # get the width of a character
    context = dialog.get_pango_context()
    font_metrics = context.get_metrics(
        context.get_font_description(), context.get_language()
    )
    width = font_metrics.get_approximate_char_width()

    # if the character width is less than 300 pixels then set the
    # message dialog's label to be 300 to avoid tiny dialogs
    if width / Pango.SCALE * len(msg) < 300:
        dialog.set_property("default-width", 300)

    if dialog.get_icon() is None:
        try:
            pixbuf = GdkPixbuf.Pixbuf.new_from_file(bauble.default_icon)
            dialog.set_icon(pixbuf)
        except GLib.Error:
            pass
    dialog.set_property("skip-taskbar-hint", False)
    dialog.show_all()
    return dialog


def message_dialog(
    msg: str,
    typ: Gtk.MessageType = Gtk.MessageType.INFO,
    buttons: Gtk.ButtonsType = Gtk.ButtonsType.OK,
    parent: Gtk.Window | None = None,
) -> Gtk.ResponseType:
    """Create a message dialog, run it and destroy it.

    Returns the dialog's response.
    """
    dialog = create_message_dialog(msg, typ, buttons, parent)
    response = dialog.run()
    dialog.destroy()
    return response


def create_yes_no_dialog(
    msg: str,
    parent: Gtk.Window | None = None,
) -> Gtk.MessageDialog:
    """Create a dialog with yes/no buttons."""
    return create_message_dialog(
        msg,
        Gtk.MessageType.QUESTION,
        Gtk.ButtonsType.YES_NO,
        parent,
    )


def yes_no_dialog(
    msg: str,
    parent: Gtk.Window | None = None,
    yes_delay: int = -1,
) -> bool:
    """Create a yes/no dialog, run it and destroy it.

    Returns True if the dialog response equals Gtk.ResponseType.YES

    :param msg: the message to display in the dialog
    :param parent: the dialog's parent
    :param yes_delay: the number of seconds before the yes button should
      become sensitive
    """
    dialog = create_yes_no_dialog(msg, parent)
    if yes_delay > 0:
        dialog.set_response_sensitive(Gtk.ResponseType.YES, False)

        def on_timeout():
            if dialog.get_property(
                "visible"
            ):  # conditional avoids GTK+ warning
                dialog.set_response_sensitive(Gtk.ResponseType.YES, True)
            return False

        GLib.timeout_add(yes_delay * 1000, on_timeout)
    response = dialog.run()
    dialog.destroy()
    return response == Gtk.ResponseType.YES


def create_message_details_dialog(  # pylint: disable=too-many-locals
    msg: str,
    details: str = "",
    typ: Gtk.MessageType = Gtk.MessageType.INFO,
    buttons: Gtk.ButtonsType = Gtk.ButtonsType.OK,
    parent: Gtk.Window | None = None,
):
    """Create a message dialog with a details expander."""
    if parent is None:
        try:  # this might get called before bauble has started
            parent = bauble.gui.window
        except AttributeError:
            parent = None

    dialog = Gtk.MessageDialog(
        modal=True,
        destroy_with_parent=True,
        transient_for=parent,
        message_type=typ,
        buttons=buttons,
    )
    dialog.set_title("Ghini")
    dialog.set_markup(msg)
    # allow resize and copying error messages etc.
    dialog.set_property("resizable", True)
    box = cast(Gtk.Box, dialog.get_message_area())
    message_label = cast(Gtk.Label, box.get_children()[0])
    message_label.set_selectable(True)

    # get the width of a character
    context = dialog.get_pango_context()
    font_metrics = context.get_metrics(
        context.get_font_description(), context.get_language()
    )
    width = font_metrics.get_approximate_char_width()

    # if the character width is less than 300 pixels then set the
    # message dialog's label to be 300 to avoid tiny dialogs
    if width / Pango.SCALE * len(msg) < 300:
        dialog.set_size_request(300, -1)

    expand = Gtk.Expander()
    text_view = Gtk.TextView()
    text_view.set_editable(False)
    text_view.set_wrap_mode(Gtk.WrapMode.WORD)
    buffer = Gtk.TextBuffer()
    buffer.set_text(details)
    text_view.set_buffer(buffer)
    scroll_win = Gtk.ScrolledWindow(propagate_natural_height=True)
    scroll_win.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    # text_view.set_size_request(-1, 400)
    scroll_win.add(text_view)
    expand.add(scroll_win)
    content_box = dialog.get_content_area()
    content_box.pack_start(expand, True, True, 0)
    # make "OK" the default response
    dialog.set_default_response(Gtk.ResponseType.OK)
    if dialog.get_icon() is None:
        try:
            pixbuf = GdkPixbuf.Pixbuf.new_from_file(bauble.default_icon)
            dialog.set_icon(pixbuf)
        except GLib.Error:
            pass
        dialog.set_property("skip-taskbar-hint", False)

    dialog.show_all()
    return dialog


def truncate_message(
    string: str,
    max_lines: int = 100,
    max_line_length: int = 400,
) -> str:
    final = []
    for line in string.split("\n"):

        if len(line) > max_line_length:
            line = line[:max_line_length] + "  ..."

        final.append(line)

    if len(final) > max_lines:
        final = final[:max_lines]
        final.append("... message truncated ...")

    return "\n".join(final)


def message_details_dialog(
    message: str,
    details: str,
    type_: Gtk.MessageType = Gtk.MessageType.INFO,
    buttons: Gtk.ButtonsType = Gtk.ButtonsType.OK,
    parent: Gtk.Window | None = None,
) -> Gtk.ResponseType:
    """Create and run a message dialog with a details expander.

    If the message or details message provided is so long that it could cause
    dislay issues then they will be truncated.
    """
    message = truncate_message(message)
    details = truncate_message(details, max_lines=300)

    dialog = create_message_details_dialog(
        message,
        details,
        type_,
        buttons,
        parent,
    )
    response = dialog.run()
    dialog.destroy()
    return response


def entry_dialog(
    title: str,
    visible: bool = True,
    parent: Gtk.Window | None = None,
) -> str | None:
    """Run a minimal dialog with a single entry for user input.

    :param title: The title of the dialog.
    :param visible: If True, the entry will show the text as it is typed,
        otherwise it will be hidden (useful for passwords).
    :param parent: The parent window for the dialog.
    """
    dialog = Gtk.Dialog(
        title=title,
        transient_for=parent,
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

    entry.set_visibility(visible)

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
