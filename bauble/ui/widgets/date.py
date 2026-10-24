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
import logging

logger = logging.getLogger(__name__)

from calendar import monthrange
from datetime import date as dt_date
from datetime import datetime
from typing import cast

from gi.repository import GObject
from gi.repository import Gtk

from bauble import error
from bauble.btypes import parse_str_date
from bauble.i18n import _
from bauble.ui import utils


class DatePickerButton(Gtk.MenuButton):
    """A simple MenuButton with Calendar Popover."""

    def __init__(self, *args):
        image = Gtk.Image.new_from_icon_name(
            "x-office-calendar-symbolic",
            Gtk.IconSize.BUTTON,
        )

        self.calendar = Gtk.Calendar()
        self.calendar.set_tooltip_text(
            _(
                "Double click to select a date, if a range constraint is set "
                "the allowed days will display in bold"
            )
        )
        box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            halign=Gtk.Align.CENTER,
        )
        box.add(self.calendar)

        self.today_button = Gtk.Button(label=_("Today"))
        self.today_button.set_name("tiny-btn")
        self.today_button.set_tooltip_text(
            _("Return to todays date (if it is within the allowed range).")
        )
        box.add(self.today_button)

        popover = Gtk.Popover()
        popover.add(box)

        box.show_all()

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

            date_picker = cast(DatePickerBox, Gtk.Template.Child())

            on_date_changed = EntryHandler(
                [Validator(validate_date, "invalid_date")],
                lambda value, *_args: parse_str_date(value, as_date=True),
            )

            def __init__(self, model) -> None:
                super().__init__(model, self)
                self.date_picker.init()
                # optionally constain the available dates
                self.date_picker.constrain_range(
                    date(2026, 1, 1), date(2026, 12, 31)
                )
                self.date_entry = self.datepicker.entry
                self.widgets_to_model_map = {
                    self.date_entry: "date",
                }

            @Gtk.Template.Callback()
            def on_date_entry_changed(
                self,
                date_picker: DatePickerBox
            ) -> None:
                self.on_date_changed(date_picker.entry)

            # optionally add the validator if the date range is constrained
            @on_date_changed.validator(problem_name="not_in_range")
            def validate_date_range(self, date: datetime.date, *_args) -> bool:
                return self.date_picker.validate_date_in_range(date)

    """

    __gtype_name__ = "DatePickerBox"

    __gsignals__: dict = {"changed": (GObject.SignalFlags.RUN_FIRST, None, ())}

    def __init__(self) -> None:
        super().__init__()
        self.button: DatePickerButton
        self.entry: Gtk.Entry
        self._entry_sid: int
        self._day_sid: int
        self.start_date: dt_date | None = None
        self.end_date: dt_date | None = None
        self.last_valid_date = datetime.today().date()
        self._first_click: dt_date | None = None

    def init(self) -> None:
        self.entry = Gtk.Entry(width_chars=15)
        self._entry_sid = self.entry.connect("changed", self.on_entry_changed)
        self.entry.connect("activate", self.on_entry_activate)
        self.button = DatePickerButton()
        self.add(self.entry)
        self.add(self.button)

        self.button.connect("toggled", self.on_calendar_toggled)
        self.button.today_button.connect("clicked", self.on_today_clicked)
        self.button.calendar.connect(
            "day-selected-double-click",
            self.on_date_double_clicked,
        )
        self._day_sid = self.button.calendar.connect(
            "day-selected",
            self.on_date_selected,
        )
        self.button.calendar.connect("month-changed", self.on_month_changed)
        self.show_all()

    def constrain_range(
        self,
        start_date: dt_date | None,
        end_date: dt_date | None,
    ) -> None:
        """Set a start and end date range constraint.

        :param start_date: earliest allowed date or None.
        :param end_date: latest allowed date or None.
        """
        if start_date and end_date and start_date > end_date:
            raise error.BaubleError(
                f"Start date {start_date} can not me less than end date "
                f"{end_date}"
            )

        logger.debug("setting constraint start_date = %s", start_date)
        logger.debug("setting constraint end_date = %s", end_date)

        self.start_date = start_date
        self.end_date = end_date
        self.button.calendar.emit("month-changed")

    def is_date_in_range(self, date: dt_date) -> bool:
        """Is the supplied date within the constrained date range.

        If no range is set returns True.
        """
        if self.start_date is None and self.end_date is None:
            return True

        too_late = too_early = False

        if self.start_date:
            too_early = bool(date) and date < self.start_date

        if self.end_date:
            too_late = bool(date) and date > self.end_date

        if too_early or too_late:
            return False
        return True

    def on_month_changed(self, calendar: Gtk.Calendar) -> None:
        """Only when a range constraint exists constrain the display.

        Mark available dates, move to the last or first available date if
        outside the range.
        """
        if self.start_date is None and self.end_date is None:
            return

        date = self.get_calendar_date()
        logger.debug("setting month to %s", date.month)

        calendar.clear_marks()

        for day in range(1, monthrange(date.year, date.month)[1] + 1):
            if self.is_date_in_range(dt_date(date.year, date.month, day)):
                calendar.mark_day(day)

        calendar.handler_block(self._day_sid)
        if (
            self.start_date
            and self.start_date.month == date.month
            and date < self.start_date
        ):
            logger.debug("%s is too early in month", date)
            # too early in month
            self.button.calendar.select_day(self.start_date.day)
        elif (
            self.end_date
            and self.end_date.month == date.month
            and date > self.end_date
        ):
            logger.debug("%s is too late in month", date)
            # too late in the month
            self.button.calendar.select_day(self.end_date.day)
        calendar.handler_unblock(self._day_sid)

    def validate_date_in_range(self, date: dt_date | str) -> bool:
        """Validates the supplied date is within the constrained range.

        If the date is outside the range or invalid then selects an appropriate
        date within the range in the calendar widget and return False.

        Intended for use in the parent presenter as a validator for the
        EntryHandler. e.g.::

            @on_date_changed.validator(problem_name="not_in_range")
            def validate_date_range(self, date: datetime.date, *_args) -> bool:
                return self.date_picker.validate_date_in_range(date)

        :param date: datetime.date or string date.
        """
        logger.debug(
            "validating date %s is within %s - %s)",
            date,
            self.start_date,
            self.end_date,
        )

        if isinstance(date, str):
            parsed_date = parse_str_date(date, as_date=True)
            logger.debug("parsed_date %s", parsed_date)

            if parsed_date is None:
                self.set_selected_date(None)
                return False

            date = parsed_date

        if self.start_date or self.end_date:

            if self.is_date_in_range(date) is False:
                logger.debug("date not in range")
                self.set_selected_date(date)
                return False

        return True

    def set_selected_date(self, date: dt_date | None) -> None:
        """Sets the selected date on the calendar widget.

        :param date: The date to select or None, if None select the next most
            appropriate date from ``last_valid_date``, ``start_date`` or todays
            date.
        """
        logger.debug(
            "last_valid_date %s, provided date %s",
            self.last_valid_date,
            date,
        )

        last_valid = None
        if self.is_date_in_range(self.last_valid_date):
            last_valid = self.last_valid_date
            logger.debug("last_valid %s is in range", last_valid)

        if date is None:
            date = last_valid or datetime.today().date()
            logger.debug("None date set to %s", date)

        # check range
        if self.is_date_in_range(date) is False:
            if self.start_date and date < self.start_date:
                new_date = last_valid or self.start_date
                logger.debug("%s is too early using %s", date, new_date)
                date = new_date
            elif self.end_date and date > self.end_date:
                new_date = last_valid or self.end_date
                logger.debug("%s is too late using %s", date, new_date)
                date = new_date

        # no range set, no last_valid
        date = date or datetime.today().date()

        self.last_valid_date = date

        logger.debug("setting selected date to %s", date)

        self.button.calendar.select_month(date.month - 1, date.year)
        self.button.calendar.select_day(date.day)

    def on_entry_changed(self, entry: Gtk.Entry) -> None:
        """Update the calendar and emmit changed signal."""
        text = entry.get_text()
        date = parse_str_date(text, as_date=True)
        logger.debug("entry date %s", date)
        self.set_selected_date(date)

        self.emit("changed")

    def on_entry_activate(self, entry: Gtk.Entry) -> None:
        """Update the entry to the formatted date string if it is parsable.

        e.g. if using a different format or fuzzy in any way, convert it to the
        ``prefs.date_format_pref`` formatted string.
        Achieved by emitting ``day-selected-double-click`` on the calendar.
        """
        if parse_str_date(entry.get_text()):
            self.button.calendar.emit("day-selected-double-click")

    def on_today_clicked(self, _button: Gtk.Button) -> None:
        self.set_selected_date(datetime.today().date())

    def on_calendar_toggled(self, button: DatePickerButton) -> None:
        """Ensures allways reverts back to the entry value where possible."""
        if button.get_active():
            text = self.entry.get_text()
            date = parse_str_date(text, as_date=True)
            logger.debug("entry date %s", date)
            self.set_selected_date(date)

    def get_calendar_date(self) -> dt_date:
        """Given the calendar widget return the selected date as a
        datetime.date object.
        """
        year, month, day = self.button.calendar.get_date()
        month += 1

        return dt_date(year, month, day)

    def on_date_selected(self, calendar: Gtk.Calendar) -> None:
        """Prevent double-clicking from setting an invalid date."""
        date = self.get_calendar_date()
        logger.debug("%s selected", date)

        if self.is_date_in_range(date):
            self._first_click = date
        else:
            self._first_click = None

        calendar.handler_block(self._day_sid)
        self.set_selected_date(date)
        calendar.handler_unblock(self._day_sid)

    def on_date_double_clicked(self, _calendar: Gtk.Calendar) -> None:
        """Sets the date and emits changed signal."""

        date = self.get_calendar_date()

        if date == self._first_click and self.is_date_in_range(date):

            self._first_click = None

            self.entry.handler_block(self._entry_sid)
            utils.set_widget_value(self.entry, date)
            self.entry.handler_unblock(self._entry_sid)

            cast(Gtk.Popover, self.button.get_popover()).popdown()

            self.emit("changed")
            return

        logger.debug("unable to change date to %s", date)

        self.set_selected_date(None)
