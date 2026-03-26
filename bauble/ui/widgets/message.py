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
Message boxes for editor dialogs
"""

from collections.abc import Callable
from typing import cast

from gi.repository import Gtk


class YesNoMessageBox(Gtk.Box):
    """Gtk.Box widget containing yes/no message dialog functionality.

    Intended to be added to Gtk.Revealer or similar.

    :param message: The message to display above the buttons. Must be a string
        with Pango markup for styling.  Make xml_safe where needed.
    :param on_yes_response: Callback for when the "Yes" button is clicked.
    :param on_no_response: Callback for when the "No" button is clicked.
    """

    def __init__(
        self,
        message: str,
        on_yes_response: Callable[[Gtk.Button], None],
        on_no_response: Callable[[Gtk.Button], None],
    ) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)

        label = Gtk.Label(use_markup=True, label=message)
        label.set_line_wrap(True)
        self.pack_start(label, True, True, 0)

        button_box = Gtk.ButtonBox(orientation=Gtk.Orientation.HORIZONTAL)
        button_box.set_layout(Gtk.ButtonBoxStyle.SPREAD)

        yes_button = Gtk.Button(label="Yes")
        no_button = Gtk.Button(label="No")

        button_box.add(yes_button)
        button_box.add(no_button)

        yes_button.connect("clicked", on_yes_response)
        no_button.connect("clicked", on_no_response)

        self.get_style_context().add_class("app-notification")

        self.pack_start(button_box, False, False, 0)


class MessageBox(Gtk.Box):
    """Gtk.Box widget containing a message.

    Intended to be added to Gtk.Revealer.

    :param message: The message to display above the buttons. Must be a string
        with Pango markup for styling.  Make xml_safe where needed.
    """

    def __init__(
        self,
        message: str,
    ) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        close_button = Gtk.Button.new_from_icon_name(
            "window-close-symbolic",
            Gtk.IconSize.BUTTON,
        )
        close_button.set_relief(Gtk.ReliefStyle.NONE)
        close_button.connect("clicked", self.on_close_clicked)
        box.pack_end(close_button, False, False, 0)
        self.pack_start(box, False, False, 0)

        label = Gtk.Label(use_markup=True, label=message)
        label.set_line_wrap(True)
        self.pack_start(label, True, True, 0)

        self.get_style_context().add_class("app-notification")

    def on_close_clicked(self, _button: Gtk.Button) -> None:
        cast(Gtk.Revealer, self.get_parent()).set_reveal_child(False)
