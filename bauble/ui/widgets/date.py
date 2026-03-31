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
Generic date picking widgets
"""
from datetime import datetime

from gi.repository import GObject
from gi.repository import Gtk

from bauble.btypes import parse_str_date
from bauble.ui import utils


class DatePickerButton(Gtk.MenuButton):
    """A simple MenuButton with Calendar Popover."""

    def __init__(self, *args):
        image = Gtk.Image.new_from_icon_name(
            "x-office-calendar-symbolic",
            Gtk.IconSize.BUTTON,
        )

        popover = Gtk.Popover()
        self.calendar = Gtk.Calendar()

        popover.add(self.calendar)
        self.calendar.show()

        super().__init__(
            *args,
            tooltip_text="Pick a date",
            image=image,
            popover=popover,
        )


class DatePickerBox(Gtk.Box):
    """Date picker widget for use in editors that require dates.

    Provides a box which contains a date Entry and MenuButton with a Calendar
    popover for selecting the date.  When the user double clicks a date the
    entry is updated.  The ``changed`` signal is emitted either when the user
    double clicks a date or changes the entry text.

    To use, include the widget, either in the ``.ui`` file or directly then
    call ``init`` on instantiation. General you will want to use the entry
    widget for the value and connect to the ``changed`` signal. e.g.::

        XML = '''<?xml version="1.0" encoding="UTF-8"?>
        <interface>
          <template class="Dialog" parent="GtkDialog">
            <property name="default-width">300</property>
            <property name="default-height">150</property>
            <child internal-child="vbox">
              <object class="GtkBox">
                <property name="visible">True</property>
                <property name="can-focus">False</property>
                <property name="orientation">vertical</property>
                <child>
                  <object class="DatePickerBox" id="date_picker">
                    <property name="visible">True</property>
                    <signal name="changed" handler="on_date_entry_changed"/>
                  </object>
                  <packing>
                    <property name="expand">False</property>
                    <property name="fill">False</property>
                    <property name="position">0</property>
                  </packing>
                </child>
              </object>
            </child>
          </template>
        </interface>
        '''

        @Gtk.Template(string=XML)
        class Dialog(GenericPresenter, Gtk.Dialog):

            __gtype_name__ = "Dialog"

            datepicker = cast(DatePickerBox, Gtk.Template.Child())

            on_date_changed = EntryHandler(
                [Validator(validate_date, "invalid_date")],
                lambda value, *_args: parse_str_date(value, as_date=True),
            )

            def __init__(self, model) -> None:
                super().__init__(model, self)
                self.datepicker.init()
                self.date_entry = self.datepicker.entry
                self.widgets_to_model_map = {
                    self.date_entry: "date",
                }

            @Gtk.Template.Callback()
            def on_date_entry_changed(self, datepicker: DatePickerBox) -> None:
                self.on_date_changed(datepicker.entry)

    """

    __gtype_name__ = "DatePickerBox"

    __gsignals__: dict = {"changed": (GObject.SignalFlags.RUN_FIRST, None, ())}

    def __init__(self) -> None:
        super().__init__()
        self.button: DatePickerButton
        self.entry: Gtk.Entry
        self._entry_sid: int

    def init(self) -> None:
        self.entry = Gtk.Entry(width_chars=15)
        self._entry_sid = self.entry.connect("changed", self.on_entry_changed)
        self.button = DatePickerButton()
        self.add(self.entry)
        self.add(self.button)

        self.button.calendar.connect(
            "day-selected-double-click",
            self.on_date_selected,
        )

    def on_entry_changed(self, entry: Gtk.Entry) -> None:
        text = entry.get_text()
        date = parse_str_date(text)
        date = date or datetime.today()
        self.button.calendar.select_month(date.month - 1, date.year)
        self.button.calendar.select_day(date.day)
        self.emit("changed")

    def on_date_selected(self, calendar):
        year, month, day = calendar.get_date()

        date = datetime(year, month + 1, day).date()
        self.entry.handler_block(self._entry_sid)
        utils.set_widget_value(self.entry, date)
        self.entry.handler_unblock(self._entry_sid)

        self.button.get_popover().popdown()

        self.emit("changed")
