# Copyright 2008-2010 Brett Adams
# Copyright 2015-2017 Mario Frasca <mario@anche.no>.
# Copyright 2020-2025 Ross Demuth <rossdemuth123@gmail.com>
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
Description: a collection of functions and abstract classes for creating
editors
"""
import datetime
import json
import logging
import os
import re
import threading
import weakref
from collections.abc import Callable
from pathlib import Path
from typing import Self
from typing import cast

logger = logging.getLogger(__name__)

import dateutil.parser as date_parser
from gi.repository import GdkPixbuf
from gi.repository import Gio
from gi.repository import GLib
from gi.repository import GObject
from gi.repository import Gtk
from lxml import etree
from sqlalchemy.orm import Session
from sqlalchemy.orm import object_mapper
from sqlalchemy.orm import object_session

import bauble
from bauble import db
from bauble import paths
from bauble import prefs
from bauble import utils
from bauble.error import CheckConditionError
from bauble.error import check
from bauble.i18n import _
from bauble.utils import desktop
from bauble.utils.web import FIELD_RE
from bauble.utils.web import LinkDict
from bauble.view import get_search_view

# TODO: create a generic date entry that can take a mask for the date format
# see the date entries for the accession and accession source presenters


class ValidatorError(Exception):
    """Custom validation exception, raised when validation fails"""


class Validator:
    """The interface that other validators should implement."""

    # pylint: disable=too-few-public-methods

    def to_python(self, value):
        raise NotImplementedError


class DateValidator(Validator):
    """Validate that string is parseable with dateutil"""

    # pylint: disable=too-few-public-methods

    def to_python(self, value):
        if not value:
            return None
        dayfirst = prefs.prefs[prefs.parse_dayfirst_pref]
        yearfirst = prefs.prefs[prefs.parse_yearfirst_pref]
        default_year = 1
        default = datetime.date(1, 1, default_year)
        try:
            date = date_parser.parse(
                value, dayfirst=dayfirst, yearfirst=yearfirst, default=default
            )
            if date.year == default_year:
                raise ValueError
        except Exception as e:
            raise ValidatorError from e
        return value


class StringOrNoneValidator(Validator):
    """If the value is an empty string then return None, else return the
    str() of the value.
    """

    # pylint: disable=too-few-public-methods

    def to_python(self, value):
        if value in ("", None):
            return None
        return str(value)


class StringOrEmptyValidator(Validator):
    """If the value is an empty string then return '', else return the
    the value.
    """

    # pylint: disable=too-few-public-methods

    def to_python(self, value):
        if not value.strip():
            return ""
        return value


class IntOrNoneStringValidator(Validator):
    """If the value is an int, long or can be cast to int then return the
    number, else return None
    """

    # pylint: disable=too-few-public-methods

    def to_python(self, value):
        if value is None or (isinstance(value, str) and value == ""):
            return None
        if isinstance(value, int):
            return value
        try:
            return int(value)
        except Exception as e:
            raise ValidatorError from e


class FloatOrNoneStringValidator(Validator):
    """If the value is an int, long, float or can be cast to float then return
    the number, else return None
    """

    # pylint: disable=too-few-public-methods

    def to_python(self, value):
        if value is None or (isinstance(value, str) and value == ""):
            return None
        if isinstance(value, (int, float)):
            return value
        try:
            return float(value)
        except Exception as e:
            raise ValidatorError from e


def default_completion_cell_data_func(_column, renderer, model, treeiter):
    """the default completion cell data function for
    GenericEditorView.attach_completions
    """
    v = model[treeiter][0]
    renderer.set_property("markup", utils.nstr(v))


def default_completion_match_func(completion, key_string, treeiter):
    """the default completion match function for
    GenericEditorView.attach_completions,

    does a case-insensitive string comparison of the the completions
    model[iter][0]
    """
    value = completion.get_model()[treeiter][0]
    return str(value).lower().startswith(key_string.lower())


class GenericEditorView:
    """A generic class meant (not) to be subclassed, to provide the view for
    the Ghini Model-View-Presenter pattern.

    The idea is that you subclass the Presenter alone, and that the View
    remains as 'stupid' as it is conceivable.

    The presenter should interact with the view by the sole interface, please
    consider all members of the view as private, this is particularly true for
    the ones having anything to do with GTK.

    :param filename: a Gtk.Builder UI definition
    :param parent: a Gtk.Window or subclass to use as the parent window, if
        parent=None then bauble.gui.window is used
    """

    _tooltips: dict[str, str] = {}
    accept_buttons: list[str] = []

    def __init__(
        self, filename, parent=None, root_widget_name=None, tooltips=None
    ):
        if tooltips is not None:
            self._tooltips = tooltips
        self.root_widget_name = root_widget_name
        builder = Gtk.Builder()
        builder.add_from_file(filename)
        self.filename = filename
        self.widgets = utils.BuilderWidgets(builder)
        if parent:
            self.get_window().set_transient_for(parent)
            self.get_window().set_destroy_with_parent(True)
        elif bauble.gui:
            self.get_window().set_transient_for(bauble.gui.window)
            self.get_window().set_destroy_with_parent(True)
        self.response = None
        self.__attached_signals = []
        self.boxes = set()

        # set the tooltips...use Gtk.Tooltip api introducted in GTK+ 2.12
        for widget_name, markup in self._tooltips.items():
            try:
                self.widgets[widget_name].set_tooltip_markup(markup)
            except Exception as e:
                logger.debug(
                    "Couldn't set the tooltip on widget %s\n\n%s",
                    widget_name,
                    e,
                )

        try:
            window = self.get_window()
        except Exception:
            window = None
        if window is not None:
            self.connect(window, "delete-event", self.on_window_delete)
            if isinstance(window, Gtk.Dialog):
                self.connect(window, "close", self.on_dialog_close)
                self.connect(window, "response", self.on_dialog_response)
        self.box = set()  # the top level, meant for warnings.

    def cancel_threads(self):
        pass

    def update(self):
        pass

    def run_file_chooser_dialog(
        self, text, parent, action, last_folder, target, suffix=None
    ):
        """create and run FileChooser, then write result in target

        This is just a bit more than a wrapper for
        `utils.run_file_chooser_dialog` allowing the Entry widget or its name
        as a string.

        :param text: window label text.
        :param parent: the parent window or None.
        :param action: a Gtk.FileChooserAction value.
        :param last_folder: the folder to open the window at.
        :param target: the Entry widget or its name as a string that has it
            value set to the selected filename.
        :param suffix: an extension as a str (e.g. '.csv'). Used as a file
            filter.
        """
        target = self.__get_widget(target)
        utils.run_file_chooser_dialog(
            text, parent, action, last_folder, target, suffix
        )

    @staticmethod
    def run_entry_dialog(title, parent, buttons, visible=True, **kwargs):
        dialog = Gtk.Dialog(title=title, transient_for=parent, **kwargs)
        dialog.add_buttons(*buttons)
        dialog.set_default_response(Gtk.ResponseType.ACCEPT)
        dialog.set_default_size(250, -1)
        dialog.set_position(Gtk.WindowPosition.CENTER)
        dialog.set_destroy_with_parent(True)
        entry = Gtk.Entry()
        if visible is not True:
            entry.set_visibility(False)
        entry.connect(
            "activate", lambda entry: dialog.response(Gtk.ResponseType.ACCEPT)
        )
        dialog.get_content_area().pack_start(entry, True, True, 0)
        dialog.show_all()
        dialog.run()
        user_reply = entry.get_text()
        dialog.destroy()
        return user_reply

    @staticmethod
    def run_message_dialog(
        msg, typ=Gtk.MessageType.INFO, buttons=Gtk.ButtonsType.OK, parent=None
    ):
        utils.message_dialog(msg, typ, buttons, parent)

    @staticmethod
    def run_yes_no_dialog(msg, parent=None, yes_delay=-1):
        return utils.yes_no_dialog(msg, parent, yes_delay)

    def get_selection(self):
        """return the selection in the graphic interface"""
        from bauble.view import SearchView

        view = bauble.gui.get_view()
        try:
            check(isinstance(view, SearchView))
            tree_view = view.results_view.get_model()
            check(tree_view is not None)
        except CheckConditionError:
            self.run_message_dialog(_("Search for something first."))
            return None

        return [row[0] for row in tree_view]

    def set_title(self, title):
        self.get_window().set_title(title)

    def set_icon(self, icon):
        self.get_window().set_icon(icon)

    def image_set_from_file(self, widget, value):
        widget = (
            widget if isinstance(widget, Gtk.Widget) else self.widgets[widget]
        )
        widget.set_from_file(value)

    def set_label(self, widget_name, value):
        getattr(self.widgets, widget_name).set_markup(value)

    def set_button_label(self, widget_name, value):
        getattr(self.widgets, widget_name).set_label(value)

    def close_boxes(self):
        while self.boxes:
            logger.debug("box is being forcibly removed")
            box = self.boxes.pop()
            self.widgets.remove_parent(box)
            box.destroy()

    def add_box(self, box):
        logger.debug("box is being added")
        self.boxes.add(box)

    def remove_box(self, box):
        logger.debug("box is being removed")
        if box in self.boxes:
            self.boxes.remove(box)
            self.widgets.remove_parent(box)
            box.destroy()
            self.get_window().resize(1, 1)
        else:
            logger.debug("box to be removed is not there")

    def add_message_box(self, message_box_type=utils.MESSAGE_BOX_INFO):
        """add a message box to the message_box_parent container

        :param type: one of MESSAGE_BOX_INFO, MESSAGE_BOX_ERROR or
          MESSAGE_BOX_YESNO
        """
        return utils.add_message_box(
            self.widgets.message_box_parent, message_box_type
        )

    def connect_signals(self, target):
        """connect all signals declared in the glade file"""
        if not hasattr(self, "signals"):
            doc = etree.parse(self.filename)
            # pylint: disable=attribute-defined-outside-init
            self.signals = doc.xpath("//signal")
        for signal in self.signals:
            try:
                handler = getattr(target, signal.get("handler"))
            except AttributeError as e:
                logger.debug("%s(%s)", type(e).__name__, e)
                continue
            signaller = getattr(self.widgets, signal.getparent().get("id"))
            handler_id = signaller.connect(signal.get("name"), handler)
            self.__attached_signals.append((signaller, handler_id))

    def set_accept_buttons_sensitive(self, sensitive):
        """set the sensitivity of all the accept/ok buttons"""
        if not self.accept_buttons:
            return
        for wname in self.accept_buttons:
            getattr(self.widgets, wname).set_sensitive(sensitive)

    def connect(self, obj, signal, callback, *args):
        """Attach a signal handler for signal on obj.

        For more information see :meth:`GObject.connect`

        :param obj: An instance of a subclass of gobject that will
          receive the signal
        :param signal: the name of the signal the object will receive
        :param callback: the function or method to call the object
          receives the signal
        :param args: extra args to pass the the callback
        """
        if isinstance(obj, str):
            obj = self.widgets[obj]
        sid = obj.connect(signal, callback, *args)
        self.__attached_signals.append((obj, sid))
        return sid

    def connect_after(self, obj, signal, callback, *args):  # data=None):
        """Attach a signal handler for signal on obj.

        For more information see :meth:`GObject.connect_after`

        :param obj: An instance of a subclass of gobject that will
          receive the signal
        :param signal: the name of the signal the object will receive
        :param callback: the function or method to call the object
          receives the signal
        :param args: extra args to pass the the callback
        """
        if isinstance(obj, str):
            obj = self.widgets[obj]
        sid = obj.connect_after(signal, callback, *args)
        # if data:
        #     sid = obj.connect_after(signal, callback, data)
        # else:
        #     sid = obj.connect_after(signal, callback)
        self.__attached_signals.append((obj, sid))
        return sid

    def disconnect_all(self):
        """Disconnects all the signal handlers attached with
        :meth:`GenericEditorView.connect` or
        :meth:`GenericEditorView.connect_after`
        """
        logger.debug("%s:disconnect_all", self.__class__.__name__)
        for obj, sid in self.__attached_signals:
            obj.disconnect(sid)
        del self.__attached_signals[:]

    def disconnect_widget_signals(self, widget):
        """disconnect all signals attached to widget"""
        widget = self.__get_widget(widget)

        removed = []
        for obj, sid in self.__attached_signals:
            if obj == widget:
                widget.disconnect(sid)
                removed.append((obj, sid))

        for item in removed:
            self.__attached_signals.remove(item)

    def get_window(self):
        """Return the top level window for view."""
        if self.root_widget_name is not None:
            return getattr(self.widgets, self.root_widget_name)
        raise NotImplementedError

    def __get_widget(self, widget):
        ref = widget
        if isinstance(widget, Gtk.Widget):
            return widget
        if isinstance(widget, tuple):
            if len(widget) == 1:
                return self.__get_widget(widget[0])
            parent, widget = widget[:-1], widget[-1]
            parent = self.__get_widget(parent)
            for child in parent.get_children():
                if Gtk.Buildable.get_name(child) == widget:
                    return child
        else:
            return self.widgets[widget]
        logger.warning("cannot solve widget reference %s", str(ref))
        return None

    def widget_append_page(self, widget, page, label):
        widget = self.__get_widget(widget)
        widget.append_page(page, label)

    def widget_add(self, widget, child):
        widget = self.__get_widget(widget)
        widget.add(child)

    def widget_get_model(self, widget):
        widget = self.__get_widget(widget)
        return widget.get_model()

    def widget_grab_focus(self, widget):
        widget = self.__get_widget(widget)
        return widget.grab_focus()

    def widget_get_active(self, widget):
        widget = self.__get_widget(widget)
        return widget.get_active()

    def widget_set_active(self, widget, active=True):
        widget = self.__get_widget(widget)
        return widget.set_active(active)

    def widget_set_attributes(self, widget, attribs):
        widget = self.__get_widget(widget)
        return widget.set_attributes(attribs)

    def widget_set_inconsistent(self, widget, value):
        widget = self.__get_widget(widget)
        widget.set_inconsistent(value)

    def combobox_init(self, widget, values=None, cell_data_func=None):
        combo = self.__get_widget(widget)
        model = Gtk.ListStore(str)
        combo.clear()
        combo.set_model(model)
        renderer = Gtk.CellRendererText()
        combo.pack_start(renderer, True)
        combo.add_attribute(renderer, "text", 0)
        self.combobox_setup(combo, values, cell_data_func)

    @staticmethod
    def combobox_setup(combo, values, cell_data_func):
        if values is None:
            return None
        return utils.setup_text_combobox(combo, values, cell_data_func)

    def combobox_remove(self, widget, item):
        widget = self.__get_widget(widget)
        if isinstance(item, str):
            # remove matching
            model = widget.get_model()
            for i, row in enumerate(model):
                if item == row[0]:
                    widget.remove(i)
                    break
            logger.warning("combobox_remove - not found >%s<", item)
        elif isinstance(item, int):
            # remove at position
            widget.remove(item)
        else:
            logger.warning(
                "invoked combobox_remove with item=(%s)%s", type(item), item
            )

    def comboboxtext_append_text(self, widget, value):
        # only works on a GtkComboBoxText not a standard GtkComboBox,
        widget = self.__get_widget(widget)
        widget.append_text(value)

    def comboboxtext_prepend_text(self, widget, value):
        # only works on a GtkComboBoxText not a standard GtkComboBox,
        widget = self.__get_widget(widget)
        widget.prepend_text(value)

    def combobox_get_active_text(self, widget):
        widget = self.__get_widget(widget)
        return widget.get_active_text()

    def combobox_get_active(self, widget):
        widget = self.__get_widget(widget)
        return widget.get_active()

    def combobox_set_active(self, widget, index):
        widget = self.__get_widget(widget)
        path = Gtk.TreePath.new_from_string(f"0:{index}")
        widget.get_child().set_displayed_row(path)

    def combobox_get_model(self, widget):
        "get the list of values in the combo"
        widget = self.__get_widget(widget)
        return widget.get_model()

    def widget_emit(self, widget, value):
        widget = self.__get_widget(widget)
        widget.emit(value)

    def widget_set_expanded(self, widget, value):
        widget = self.__get_widget(widget)
        widget.set_expanded(value)

    def widget_set_sensitive(self, widget, value=True):
        widget = self.__get_widget(widget)
        widget.set_sensitive(value and True or False)

    def widget_set_visible(self, widget, visible=True):
        widget = self.__get_widget(widget)
        widget.set_visible(visible)

    def widget_get_visible(self, widget):
        widget = self.__get_widget(widget)
        return widget.get_visible()

    def widget_set_text(self, widget, text):
        widget = self.__get_widget(widget)
        widget.set_text(text)

    def widget_get_text(self, widget):
        widget = self.__get_widget(widget)
        return widget.get_text()

    def widget_get_value(self, widget):
        widget = self.__get_widget(widget)
        return utils.get_widget_value(widget)

    def widget_set_value(
        self, widget, value, markup=False, default=None, index=0
    ):
        """This method calls bauble.utils.set_widget_value()

        :param widget: a widget or name of a widget in self.widgets
        :param value: the value to put in the widgets
        :param markup: whether the data in value uses pango markup
        :param default: the default value to put in the widget if value is None
        :param index: the row index to use for those widgets who use a model
        """
        if isinstance(widget, Gtk.Widget):
            utils.set_widget_value(widget, value, markup, default, index)
        else:
            utils.set_widget_value(
                self.widgets[widget], value, markup, default, index
            )

    def on_dialog_response(self, dialog, response, *_args):
        """Called if self.get_window() is a Gtk.Dialog and it receives the
        response signal.
        """
        logger.debug("on_dialog_response")
        dialog.hide()
        self.response = response
        return response

    @staticmethod
    def on_dialog_close(dialog, _event=None):
        """Called if self.get_window() is a Gtk.Dialog and it receives the
        close signal.
        """
        logger.debug("on_dialog_close")
        dialog.hide()
        return False

    @staticmethod
    def on_window_delete(window, _event=None):
        """Called when the window return by get_window() receives the delete
        event.
        """
        logger.debug("on_window_delete")
        window.hide()
        return False

    def attach_completion(
        self,
        entry,
        cell_data_func=default_completion_cell_data_func,
        match_func=default_completion_match_func,
        minimum_key_length=1,
        text_column=-1,
    ):
        """Attach an entry completion to a Gtk.Entry.

        The defaults values for this attach_completion assumes the completion
        popup only shows text and that the text is in the first column of the
        model.

        NOTE: If you are selecting completions from strings in your model
        you must set the text_column parameter to the column in the
        model that holds the strings or else when you select the string
        from the completions it won't get set properly in the entry
        even though you call entry.set_text().

        :param entry: the name of the entry to attach the completion
        :param cell_data_func: the function to use to display the rows in
          the completion popup
        :param match_func: a function that returns True/False if the
          value from the model should be shown in the completions
        :param minimum_key_length: default=1
        :param text_column: the value of the text-column property on the entry,
          default is -1

        :return: the completion attached to the entry.
        """

        # TODO: we should add a default ctrl-space to show the list of
        # completions regardless of the length of the string
        completion = Gtk.EntryCompletion()
        cell = Gtk.CellRendererText()  # set up the completion renderer
        completion.pack_start(cell, True)
        completion.set_cell_data_func(cell, cell_data_func)
        completion.set_match_func(match_func)
        completion.set_property("text-column", text_column)
        completion.set_minimum_key_length(minimum_key_length)
        completion.set_popup_completion(True)
        completion.props.popup_set_width = False
        if isinstance(entry, str):
            self.widgets[entry].set_completion(completion)
        else:
            entry.set_completion(completion)

        return completion

    def init_translatable_combo(
        self, combo, translations, default=None, key=None
    ):
        """Initialize a Gtk.ComboBox with translations values where
        model[row][0] is the value that will be stored in the database and
        model[row][1] is the value that will be visible in the Gtk.ComboBox.

        A Gtk.ComboBox initialized with this method should work with
        self.assign_simple_handler()

        :param combo:
        :param translations: a list of pairs, or a dictionary,
            of values->translation.
        :param default: the intial value as found in the first column of the
            model.
        :param key: a callable that returns a key for sorting
        """
        if isinstance(combo, str):
            combo = self.widgets[combo]
        combo.clear()
        model = Gtk.ListStore(str, str)
        if isinstance(translations, dict):
            translations = sorted(
                iter(translations.items()), key=lambda x: x[1]
            )

        if key is not None:
            translations = sorted(translations, key=key)
        for k, v in translations:
            model.append([k, v])
        combo.set_model(model)
        cell = Gtk.CellRendererText()
        combo.pack_start(cell, True)
        combo.add_attribute(cell, "text", 1)

        # only place completions seem to be needed is accession
        # acc_recvd_type_comboentry
        if combo.get_has_entry():
            # add completion using the first column of the model for the text
            entry = combo.get_child()
            completion = Gtk.EntryCompletion()
            entry.set_completion(completion)
            completion.set_model(model)
            completion.set_text_column(1)
            completion.set_popup_completion(True)
            completion.set_inline_completion(True)
            completion.set_inline_selection(True)
            # completion.set_minimum_key_length(2)

            combo.connect("format-entry-text", utils.format_combo_entry_text)

        if default is not None:
            treeiter = utils.combo_get_value_iter(combo, default)
            combo.set_active_iter(treeiter)

    def save_state(self):
        """Save the state of the view by setting a value in the preferences
        that will be called restored in restore_state

        e.g. prefs[pref_string] = pref_value
        """
        # TODO
        pass

    def restore_state(self):
        """Restore the state of the view, this is usually done by getting a
        value by the preferences and setting the equivalent in the interface
        """
        # TODO
        pass

    def start(self):
        if bauble.gui:
            bauble.gui.set_busy_actions(True)
        result = self.get_window().run()
        if bauble.gui:
            bauble.gui.set_busy_actions(False)
        return result

    def cleanup(self):
        """Should be called when after self.start() returns.

        Calls self.disconnect_all() and destroys the window if root_widget_name
        is defined.
        """
        logger.debug("%s::cleanup", self.__class__.__name__)
        self.disconnect_all()
        if self.root_widget_name:
            GLib.idle_add(self.get_window().destroy)


class MockDialog:
    def __init__(self):
        self.hidden = False
        self.content_area = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.message_area = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.size = None
        self.response = Gtk.ResponseType.OK

    def hide(self):
        self.hidden = True

    def run(self):
        return self.response

    def show(self):
        pass

    def show_all(self):
        pass

    def set_keep_above(self, val):
        pass

    def add_accel_group(self, group):
        pass

    def get_content_area(self):
        return self.content_area

    def get_message_area(self):
        return self.message_area

    def resize(self, x, y):
        self.size = (x, y)

    def get_size(self):
        return self.size

    def destroy(self):
        pass


class MockView:
    """mocking the view, but so generic that we share it among clients"""

    def __init__(self, **kwargs):
        from unittest import mock

        self.widgets = mock.Mock()
        self.models = {}  # dictionary of list of tuples
        self.invoked = []
        self.invoked_detailed = []
        self.visible = {}
        self.sensitive = {}
        self.expanded = {}
        self.values = {}
        self.index = {}
        self.selection = []
        self.reply_entry_dialog = []
        self.reply_yes_no_dialog = []
        self.reply_file_chooser_dialog = []
        self.__window = MockDialog()
        for name, value in list(kwargs.items()):
            setattr(self, name, value)
        self.boxes = set()

    def init_translatable_combo(self, *args):
        self.invoked.append("init_translatable_combo")
        self.invoked_detailed.append((self.invoked[-1], args))

    def get_selection(self):
        "fakes main UI search result - selection"
        return self.selection

    def image_set_from_file(self, *args):
        self.invoked.append("image_set_from_file")
        self.invoked_detailed.append((self.invoked[-1], args))

    def run_file_chooser_dialog(
        self, text, parent, action, last_folder, target, suffix=None
    ):
        args = [text, parent, action, last_folder, target, suffix]
        self.invoked.append("run_file_chooser_dialog")
        self.invoked_detailed.append((self.invoked[-1], args))
        try:
            reply = self.reply_file_chooser_dialog.pop()
        except Exception:
            reply = ""
        self.widget_set_value(target, reply)

    def run_entry_dialog(self, *args, **kwargs):
        self.invoked.append("run_entry_dialog")
        self.invoked_detailed.append((self.invoked[-1], args))
        try:
            return self.reply_entry_dialog.pop()
        except Exception:
            return ""

    def run_message_dialog(
        self,
        msg,
        typ=Gtk.MessageType.INFO,
        buttons=Gtk.ButtonsType.OK,
        parent=None,
    ):
        self.invoked.append("run_message_dialog")
        args = [msg, typ, buttons, parent]
        self.invoked_detailed.append((self.invoked[-1], args))

    def run_yes_no_dialog(self, msg, parent=None, yes_delay=-1):
        self.invoked.append("run_yes_no_dialog")
        args = [msg, parent, yes_delay]
        self.invoked_detailed.append((self.invoked[-1], args))
        try:
            return self.reply_yes_no_dialog.pop()
        except Exception:
            return True

    def set_title(self, *args):
        self.invoked.append("set_title")
        self.invoked_detailed.append((self.invoked[-1], args))

    def set_icon(self, *args):
        self.invoked.append("set_icon")
        self.invoked_detailed.append((self.invoked[-1], args))

    def combobox_init(self, name, values=None, *args):
        self.invoked.append("combobox_init")
        self.invoked_detailed.append((self.invoked[-1], [name, values, args]))
        self.models[name] = []
        for i in values or []:
            self.models[name].append((i,))

    def connect_signals(self, *args):
        self.invoked.append("connect_signals")
        self.invoked_detailed.append((self.invoked[-1], args))

    def set_label(self, *args):
        self.invoked.append("set_label")
        self.invoked_detailed.append((self.invoked[-1], args))

    def set_button_label(self, *args):
        self.invoked.append("set_button_label")
        self.invoked_detailed.append((self.invoked[-1], args))

    def connect_after(self, *args):
        self.invoked.append("connect_after")
        self.invoked_detailed.append((self.invoked[-1], args))

    def widget_get_value(self, widget, *args):
        self.invoked.append("widget_get_value")
        self.invoked_detailed.append((self.invoked[-1], [widget, args]))
        return self.values.get(widget)

    def widget_set_value(self, widget, value, *args):
        self.invoked.append("widget_set_value")
        self.invoked_detailed.append((self.invoked[-1], [widget, value, args]))
        self.values[widget] = value
        if widget in self.models:
            if (value,) in self.models[widget]:
                self.index[widget] = self.models[widget].index((value,))
            else:
                self.index[widget] = -1

    def connect(self, *args):
        self.invoked.append("connect")
        self.invoked_detailed.append((self.invoked[-1], args))

    def widget_get_visible(self, name):
        self.invoked.append("widget_get_visible")
        self.invoked_detailed.append((self.invoked[-1], [name]))
        return self.visible.get(name)

    def widget_set_visible(self, name, value=True):
        self.invoked.append("widget_set_visible")
        self.invoked_detailed.append((self.invoked[-1], [name, value]))
        self.visible[name] = value

    def widget_set_expanded(self, widget, value):
        self.invoked.append("widget_set_expanded")
        self.invoked_detailed.append((self.invoked[-1], [widget, value]))
        self.expanded[widget] = value

    def widget_set_sensitive(self, name, value=True):
        self.invoked.append("widget_set_sensitive")
        self.invoked_detailed.append((self.invoked[-1], [name, value]))
        self.sensitive[name] = value

    def widget_get_sensitive(self, name):
        self.invoked.append("widget_get_sensitive")
        self.invoked_detailed.append((self.invoked[-1], [name]))
        return self.sensitive[name]

    def widget_set_inconsistent(self, *args):
        self.invoked.append("widget_set_inconsistent")
        self.invoked_detailed.append((self.invoked[-1], args))

    def widget_get_text(self, widget, *args):
        self.invoked.append("widget_get_text")
        self.invoked_detailed.append((self.invoked[-1], [widget, args]))
        return self.values[widget]

    def widget_set_text(self, *args):
        self.invoked.append("widget_set_text")
        self.invoked_detailed.append((self.invoked[-1], args))
        self.values[args[0]] = args[1]

    def widget_grab_focus(self, *args):
        self.invoked.append("widget_grab_focus")
        self.invoked_detailed.append((self.invoked[-1], args))

    def widget_set_active(self, *args):
        self.invoked.append("widget_set_active")
        self.invoked_detailed.append((self.invoked[-1], args))

    def widget_set_attributes(self, *args):
        self.invoked.append("widget_set_attributes")
        self.invoked_detailed.append((self.invoked[-1], args))

    def get_window(self):
        self.invoked.append("get_window")
        self.invoked_detailed.append((self.invoked[-1], []))
        return self.__window

    widget_get_active = widget_get_value

    def combobox_remove(self, name, item):
        self.invoked.append("combobox_remove")
        self.invoked_detailed.append((self.invoked[-1], [name, item]))
        model = self.models.setdefault(name, [])
        if isinstance(item, int):
            del model[item]
        else:
            model.remove((item,))

    def comboboxtext_append_text(self, name, value):
        self.invoked.append("comboboxtext_append_text")
        self.invoked_detailed.append((self.invoked[-1], [name, value]))
        model = self.models.setdefault(name, [])
        model.append((value,))

    def comboboxtext_prepend_text(self, name, value):
        self.invoked.append("comboboxtext_prepend_text")
        self.invoked_detailed.append((self.invoked[-1], [name, value]))
        model = self.models.setdefault(name, [])
        model.insert(0, (value,))

    def combobox_set_active(self, widget, index):
        self.invoked.append("combobox_set_active")
        self.invoked_detailed.append((self.invoked[-1], [widget, index]))
        self.index[widget] = index
        self.values[widget] = self.models[widget][index][0]

    def combobox_get_active_text(self, widget):
        self.invoked.append("combobox_get_active_text")
        self.invoked_detailed.append(
            (
                self.invoked[-1],
                [
                    widget,
                ],
            )
        )
        return self.values[widget]

    def combobox_get_active(self, widget):
        self.invoked.append("combobox_get_active")
        self.invoked_detailed.append(
            (
                self.invoked[-1],
                [
                    widget,
                ],
            )
        )
        return self.index.setdefault(widget, 0)

    def combobox_get_model(self, widget):
        self.invoked.append("combobox_get_model")
        self.invoked_detailed.append(
            (
                self.invoked[-1],
                [
                    widget,
                ],
            )
        )
        return self.models[widget]

    def set_accept_buttons_sensitive(self, sensitive=True):
        self.invoked.append("set_accept_buttons_sensitive")
        self.invoked_detailed.append(
            (
                self.invoked[-1],
                [
                    sensitive,
                ],
            )
        )

    def add_message_box(self, message_box_type=utils.MESSAGE_BOX_INFO):
        self.invoked.append("set_accept_buttons_sensitive")
        self.invoked_detailed.append(
            (
                self.invoked[-1],
                [
                    message_box_type,
                ],
            )
        )
        return MockDialog()

    def add_box(self, box):
        self.invoked.append("add_box")
        self.invoked_detailed.append(
            (
                self.invoked[-1],
                [
                    box,
                ],
            )
        )
        self.boxes.add(box)

    def remove_box(self, box):
        self.invoked.append("remove_box")
        self.invoked_detailed.append(
            (
                self.invoked[-1],
                [
                    box,
                ],
            )
        )
        if box in self.boxes:
            self.boxes.remove(box)


class Problem:  # pylint: disable=too-few-public-methods
    """Problem descriptor,

    provides a string that states the problem_type, class and the instance
    identifier. Makes logs entries easier to follow.
    """

    __slots__: tuple[str, ...] = ("problem_type",)

    def __init__(self, problem_type: str) -> None:
        self.problem_type = problem_type

    def __get__[T](self, instance: T, class_: type[T]) -> str:
        return f"{self.problem_type}::{class_.__name__}::{id(instance)}"


class GenericPresenter:
    """A presenter with a model that can be used with a Gtk.Template decorated
    class as the view.

    Can be used either as a mixin on the Gtk.Template class itself or inherited
    from to create a more conventional MVP style (composition).

    Example as a Mixin::

        @Gtk.Template(filename="/path/to/file.ui"))
        class Foo(GenericPresenter, Gtk.Dialog):

            __gtype_name__ = "Foo"

            bar = cast(Gtk.Entry, Gtk.Template.Child())

            def __init__(self, model: FooModel) -> None:
                super().__init__(model, self)

            # signal handlers defined in the .ui file
            @Gtk.Template.Callback()
            def on_text_entry_changed(self, entry: Gtk.Entry) -> None:
                super().on_text_entry_changed(entry)

        model = FooModel()
        presenter = Foo(model)

    Example as a separate presenter classes::

        @Gtk.Template(filename="/path/to/file.ui"))
        class FooView(GenericPresenter, Gtk.Dialog):

            __gtype_name__ = "Foo"

            bar = cast(Gtk.Entry, Gtk.Template.Child())


        class FooPresenter(editor.GenericPresenter):
            def __init__(
                    self, model: FooModel, view: FooView
            ) -> None:
                self.view: FooView
                super().__init__(model, view)

            view.bar.connect("changed", self.on_text_entry_changed)

        model = FooModel()
        view = FooView()
        presenter = FooPresenter(model, view)
    """

    PROBLEM_NOT_UNIQUE = Problem("not_unique")
    PROBLEM_EMPTY = Problem("empty")

    def __init__(
        self, model: object, view: Self | Gtk.Widget, *args, **kwargs
    ) -> None:

        self.widgets_to_model_map: dict[GObject.Object, str]
        self.problems: set[tuple[str, Gtk.Widget]] = set()

        self.model = model
        self.view = view
        # Incase of use as a Gtk.Template mixin call the widgets init
        super().__init__(*args, **kwargs)

    def refresh_all_widgets_from_model(self) -> None:
        for widget, field in self.widgets_to_model_map.items():
            value = getattr(self.model, field)
            utils.set_widget_value(widget, value)

    def add_problem(self, problem_id: str, widget: Gtk.Widget) -> None:
        """Add problem_id to self.problems and change widgets background.

        :param problem_id: A unique identifier for the problem.
        :param widget: the widget whose background color should change to
            indicate a problem
        """

        self.problems.add((problem_id, widget))

        # Should always be true (except GOject.Objects i.e. TextBuffer).
        if isinstance(widget, Gtk.Widget):
            widget.get_style_context().add_class("problem")

        logger.debug("problems now: %s", self.problems)

    def remove_problem(
        self, problem_id: str | None = None, widget: Gtk.Widget | None = None
    ) -> None:
        """Remove problem from self.problems and reset the widgets background.

        If widget is None remove problem_id for all widgets.
        If problem_id is None remove all problem ids for widget.
        If not matching problem exists nothing happens.

        :param problem_id: A unique id for the problem.
        :param widget: the problem widget
        """
        for prob, widg in self.problems.copy():
            # pylint: disable=too-many-boolean-expressions
            if (
                (widg == widget and prob == problem_id)
                or (widget is None and prob == problem_id)
                or (widg == widget and problem_id is None)
            ):
                if isinstance(widg, Gtk.Widget):
                    widg.get_style_context().remove_class("problem")
                self.problems.remove((prob, widg))
        logger.debug("problems now: %s", self.problems)

    def __on_text_entry_changed(self, entry: Gtk.Entry) -> str:
        # Private, name mangled so cannot be overridden, for internal use
        value = entry.get_text()
        field = self.widgets_to_model_map[entry]
        logger.debug(
            "on_text_entry_changed(%s, %s) - %s -> %s",
            entry,
            field,
            getattr(self.model, field),
            value,
        )
        setattr(self.model, field, value)
        return value

    def on_text_entry_changed(self, entry: Gtk.Entry) -> None:
        self.__on_text_entry_changed(entry)

    def _on_non_empty_text_entry_changed(self, entry: Gtk.Entry) -> str:
        value = self.__on_text_entry_changed(entry)

        if not value:
            self.add_problem(self.PROBLEM_EMPTY, entry)
        else:
            self.remove_problem(self.PROBLEM_EMPTY, entry)
        return value

    def on_non_empty_text_entry_changed(self, entry: Gtk.Entry) -> None:
        """If the entry is not empty adds PROBLEM_EMPTY to self.problems.

        If addition functionality is required you can overide this method and
        use the private version to get widgets value. e.g.::

            @Gtk.Template.Callback()
            def on_non_empty_text_entry_changed(self, entry):
                value = super()._on_non_empty_text_entry_changed(entry)

                if not value:
                    raise Exception("EMPTY")
        """
        self._on_non_empty_text_entry_changed(entry)

    def on_unique_text_entry_changed(
        self, entry: Gtk.Entry, /, non_empty: bool = True
    ) -> None:
        """If the entry is not not unique adds PROBLEM_NOT_UNIQUE to problems.

        If the value is permitted to be empty, call with ``non_empty=False``
        When used with Gtk.Template and @Gtk.Template.Callback() decorator, to
        avoid linter complaints, name your signal handler differently (don't
        override) and use ``super`` to call. e.g.::

            @Gtk.Template.Callback()
            def on_unique_entry_changed(self, entry):
                super().on_unique_text_entry_changed(entry)

        Only works if model has an object_session.
        """
        if non_empty:
            value = self._on_non_empty_text_entry_changed(entry)
            if not value:
                return
        else:
            value = self.__on_text_entry_changed(entry)

        field = self.widgets_to_model_map[entry]
        class_ = self.model.__class__
        column = getattr(class_, field)

        session = object_session(self.model)

        if isinstance(session, Session):
            exists = session.query(class_).filter(column == value).first()
            if exists is not None and exists is not self.model:
                self.add_problem(self.PROBLEM_NOT_UNIQUE, entry)
            else:
                self.remove_problem(self.PROBLEM_NOT_UNIQUE, entry)

    def on_text_buffer_changed(self, buffer: Gtk.TextBuffer) -> None:
        value = buffer.get_text(*buffer.get_bounds(), False)
        field = self.widgets_to_model_map[buffer]
        logger.debug(
            "on_text_buffer_changed(%s, %s) - %s -> %s",
            buffer,
            field,
            getattr(self.model, field),
            value,
        )
        setattr(self.model, field, value)

    def on_combobox_changed(self, combobox: Gtk.ComboBox) -> None:
        if combobox.get_has_entry():
            value = cast(Gtk.Entry, combobox.get_child()).get_text()
        else:
            model = combobox.get_model()
            itr = combobox.get_active_iter()
            if model is None or itr is None:
                value = None
            else:
                value = model[itr][0]
        field = self.widgets_to_model_map[combobox]
        logger.debug(
            "on_combobox_changed(%s, %s) - %s -> %s",
            combobox,
            field,
            getattr(self.model, field),
            value,
        )
        setattr(self.model, field, value)


class GenericEditorPresenter:
    """The presenter of the Model View Presenter Pattern

    The presenter should usually be initialized in the following order:
    1. initialize the widgets
    2. refresh the view, put values from the model into the widgets
    3. connect the signal handlers

    :param model: an object instance mapped to an SQLAlchemy table
    :param view: should be an instance of GenericEditorView
    :param refresh_view: if True fill the values in the widgets from the
        approapriate fields values from the model.
    :param session: instance of db.Session, if None try to get appropriate one,
        if False then a session is not needed for this editor.
    :param committing_results: list of ResponseTypes that if returned from the
        view should trigger a session.commit.
    """

    widget_to_field_map: dict[str, str] = {}
    view_accept_buttons: list[str] = []

    PROBLEM_DUPLICATE = Problem("duplicate")
    PROBLEM_EMPTY = Problem("empty")
    PROBLEM_NOT_FOUND = Problem("not_found")

    def __init__(
        self,
        model,
        view: GenericEditorView,
        refresh_view=False,
        session=None,
        do_commit=False,
        connect_signals=True,
        committing_results=[Gtk.ResponseType.OK],
    ):
        logger.debug("%s::__init__", type(self).__name__)
        self.model = model
        self.view = view
        self.problems: set[tuple[str, Gtk.Widget]] = set()
        self._dirty = False
        self.is_committing_presenter = do_commit
        self.committing_results = committing_results
        self.running_threads: list[threading.Thread] = []
        self.owns_session = False
        self.session = session
        if session is False:
            self.session = None
            self.owns_session = False
            logger.debug("GenericEditorPresenter::__init__ - sessionless")
        elif session is None:
            logger.debug("session is None")
            try:
                self.session = object_session(model)
            except Exception as e:
                logger.debug("%s(%s)", type(e).__name__, e)

            if self.session is None:  # object_session gave None without error
                logger.debug("creating own session")
                self.session = db.Session()
                self.owns_session = True
                if isinstance(model, db.Base):
                    logger.debug("merging model into own session")
                    # creates a new object if it is new
                    self.model = model = self.session.merge(model)

        if view:
            view.accept_buttons = self.view_accept_buttons
            if model and refresh_view:
                self.refresh_view()
            if connect_signals:
                view.connect_signals(self)
        # for PresenterMapMixin
        super().__init__()

    def refresh_sensitivity(self):
        logger.debug("you should implement this in your subclass")

    def refresh_view(self):
        """fill the values in the widgets as the field values in the model

        for radio button groups, we have several widgets all referring
        to the same model attribute.
        """
        for widget, attr in self.widget_to_field_map.items():
            value = getattr(self.model, attr)
            value = value if value is not None else ""
            self.view.widget_set_value(widget, value)

    def cancel_threads(self):
        for k in self.running_threads:
            try:
                k.cancel()
            except AttributeError:
                pass
        for k in self.running_threads:
            k.join()
        self.running_threads = []

    def start_thread(self, thread):
        self.running_threads.append(thread)
        thread.start()
        return thread

    def commit_changes(self):
        """Commit the changes to self.session()"""
        objs = list(self.session)
        try:
            self.session.commit()
            try:
                bauble.gui.get_view().update()
            except Exception as e:
                logger.debug("%s(%s)", type(e).__name__, e)
        except Exception as e:
            self.session.rollback()
            self.session.add_all(objs)
            logger.debug("%s(%s)", type(e).__name__, e)
            raise
        finally:
            if self.owns_session:
                self.session.close()
        return True

    def __set_model_attr(self, attr, value):
        if getattr(self.model, attr) != value:
            setattr(self.model, attr, value)
            self._dirty = True
            self.view._dirty = True
            self.view.set_accept_buttons_sensitive(not self.has_problems())

    @staticmethod
    def __get_widget_name(widget):
        return (
            widget
            if isinstance(widget, str)
            else Gtk.Buildable.get_name(widget)
        )

    widget_get_name = __get_widget_name

    def __get_widget_attr(self, widget):
        return self.widget_to_field_map.get(self.__get_widget_name(widget))

    def on_date_entry_changed(self, entry, prop):
        """Handler for 'changed' signal on a date widget.

        :prop entry: the date widget
        :param prop: a tuple of the form (model, property as a string) that
            will be set.
        """
        widget_name = Gtk.Buildable.get_name(entry)
        logger.debug("on_date_entry_changed(%s, %s)", entry, prop)
        value = None
        try:
            value = DateValidator().to_python(entry.props.text)
        except ValidatorError as e:
            logger.debug("%s(%s)", type(e).__name__, e)
            self.add_problem(f"BAD_DATE::{widget_name}", entry)
        else:
            self.remove_problem(f"BAD_DATE::{widget_name}", entry)
            self._dirty = True
            self.view._dirty = True
        setattr(*prop, value)

    def on_textbuffer_changed(self, widget, value=None, attr=None):
        """handle 'changed' signal on textbuffer widgets.

        :param attr: name of the model field to set, NOTE: must be supplied.
        """
        # NOTE TextBuffer being just a kind of datastore is not Gtk.Buildable
        # nor aware of the TextView(s) using it.  This is why attr must be
        # supplied here rather than using __get_widget_attr
        if attr is None:
            return

        if value is None:
            value = widget.get_text(*widget.get_bounds(), False)
        logger.debug(
            "on_textbuffer_changed(%s, %s) - %s -> %s",
            widget,
            attr,
            getattr(self.model, attr),
            value,
        )
        self.__set_model_attr(attr, value)

    def on_text_entry_changed(self, widget, value=None):
        """handle 'changed' signal on generic text entry widgets."""

        attr = self.__get_widget_attr(widget)
        if attr is None:
            return None
        value = self.view.widget_get_value(widget)
        logger.debug(
            "on_text_entry_changed(%s, %s) - %s -> %s",
            widget,
            attr,
            getattr(self.model, attr),
            value,
        )
        self.__set_model_attr(attr, value)
        return value

    def on_numeric_text_entry_changed(self, widget, value=None):
        """handle 'changed' signal on numeric text entry widgets."""

        attr = self.__get_widget_attr(widget)
        if attr is None:
            return None
        value = self.view.widget_get_value(widget)
        if value == "":
            value = 0
        try:
            value = int(value)
            logger.debug(
                "on_numeric_entry_changed(%s, %s) - %s → %s",
                widget,
                attr,
                getattr(self.model, attr),
                value,
            )
            self.__set_model_attr(attr, value)
        except Exception:
            value = getattr(self.model, attr)
            self.view.widget_set_value(widget, value)
        return value

    def on_non_empty_text_entry_changed(self, widget, value=None):
        """handle 'changed' signal on compulsory text entry widgets."""

        value = self.on_text_entry_changed(widget, value)
        if not value:
            self.add_problem(self.PROBLEM_EMPTY, widget)
        else:
            self.remove_problem(self.PROBLEM_EMPTY, widget)
        return value

    def on_unique_text_entry_changed(self, widget, value=None):
        """handle 'changed' signal on text entry widgets with an uniqueness
        constraint."""

        attr = self.__get_widget_attr(widget)
        if attr is None:
            return
        if value is None:
            value = widget.props.text
            value = utils.nstr(value)
        if not value:
            self.add_problem(self.PROBLEM_EMPTY, widget)
        else:
            self.remove_problem(self.PROBLEM_EMPTY, widget)
        if getattr(self.model, attr) == value:
            return
        logger.debug(
            "on_unique_text_entry_changed(%s, %s) - %s → %s",
            widget,
            attr,
            getattr(self.model, attr),
            value,
        )
        # check uniqueness
        klass = self.model.__class__
        k_attr = getattr(klass, attr)
        query = self.session.query(klass)
        query = query.filter(k_attr == value)
        omonym = query.first()
        if omonym is not None and omonym is not self.model:
            self.add_problem(self.PROBLEM_DUPLICATE, widget)
        else:
            self.remove_problem(self.PROBLEM_DUPLICATE, widget)
        # ok
        self.__set_model_attr(attr, value)

    def on_check_toggled(self, widget, value=None):
        """handle toggled signal on check buttons"""
        attr = self.__get_widget_attr(widget)
        if value is None:
            value = self.view.widget_get_active(widget)
            self.view.widget_set_inconsistent(widget, False)
        if attr is not None:
            self.__set_model_attr(attr, value)
        else:
            logging.debug(
                "presenter %s does not know widget %s",
                self.__class__.__name__,
                self.__get_widget_name(widget),
            )

    def on_group_changed(self, widget, *args):
        """handle group-changed signal on radio-button"""
        if args:
            logger.warning(
                "on_group_changed received extra arguments %s", str(args)
            )
        attr = self.__get_widget_attr(widget)
        value = self.__get_widget_name(widget)
        self.__set_model_attr(attr, value)

    def on_combo_changed(self, widget, value=None):
        """handle changed signal on combo box

        value is only specified while testing
        """
        attr = self.__get_widget_attr(widget)
        if value is None:
            index = self.view.combobox_get_active(widget)
            widget_model = self.view.combobox_get_model(widget)
            value = widget_model[index][0]
        self.__set_model_attr(attr, value)
        self.refresh_view()

    # whether the presenter should be commited or not
    def is_dirty(self):
        """is the presenter dirty?

        the presenter is dirty depending on whether it has changed anything
        that needs to be committed.  This doesn't necessarily imply that the
        session is not dirty nor is it required to change back to True if the
        changes are committed.
        """
        return self._dirty

    def has_problems(self, widget=None):
        """Return True/False depending on if widget has any problems attached
        to it. if no widget is specified, result is True if there is any
        problem at all.
        """
        if widget is None:
            return bool(self.problems)
        for _prob, widg in self.problems:
            if widget == widg:
                return True
        return False

    def clear_problems(self):
        """Clear all the problems from all widgets associated with the
        presenter
        """
        for prob in self.problems.copy():
            self.remove_problem(prob[0], prob[1])
        self.problems.clear()

    def remove_problem(self, problem_id, widget=None):
        """Remove problem_id from self.problems and reset the background
        color of the widget.

        If problem_id is None and widget is None then method won't do
        anything.

        :param problem_id: the problem to remove, if None then remove
             all problems from the widget
        :param widget: a Gtk.Widget instance to remove the problem from, if
             None then remove all occurrences of problem_id regardless of the
             widget
        """
        logger.debug(
            "remove_problem(%s, %s, %s)",
            self.__class__.__name__,
            problem_id,
            widget,
        )
        if problem_id is None and widget is None:
            logger.warning("invoke remove_problem with None, None")
            # if no problem id and not problem widgets then don't do anything
            return

        if not isinstance(widget, (Gtk.Widget, type(None))):
            try:
                widget = getattr(self.view.widgets, widget)
            except (AttributeError, TypeError):
                logger.info("can't get widget %s", widget)

        tmp = self.problems.copy()
        for prob, widg in tmp:
            if (
                (widg == widget and prob == problem_id)
                or (widget is None and prob == problem_id)
                or (widg == widget and problem_id is None)
            ):
                if isinstance(widg, Gtk.Widget) and not prefs.testing:
                    widg.get_style_context().remove_class("problem")
                    widg.get_style_context().remove_class("problem-bg")
                self.problems.remove((prob, widg))
        logger.debug("problems now: %s", self.problems)

    def add_problem(
        self,
        problem_id: str,
        widget: Gtk.Widget | str,
    ) -> None:
        """Add problem_id to self.problems and change the background of widget.

        :param problem_id: A unique id for the problem.
        :param widget: either a widget or list of widgets
              whose background color should change to indicate a problem
              (default=None)
        """
        logger.debug(
            "add_problem(%s, %s, %s)",
            self.__class__.__name__,
            problem_id,
            widget,
        )

        if isinstance(widget, str):
            widget = cast(Gtk.Widget, getattr(self.view.widgets, widget))

        self.problems.add((problem_id, widget))
        # Should always be true (except some tests).
        if isinstance(widget, Gtk.Widget):
            # THIS was in place for id_qual_rank, may be obsoete now
            if isinstance(widget, Gtk.ComboBox):
                widget.get_style_context().add_class("problem-bg")
            else:
                widget.get_style_context().add_class("problem")
        logger.debug("problems now: %s", self.problems)

    def init_enum_combo(self, widget_name, field):
        """Initialize a Gtk.ComboBox widget with name widget_name from enum
        values in self.model.field

        :param widget_name:
        :param field:
        """
        combo = self.view.widgets[widget_name]
        mapper = object_mapper(self.model)
        values = sorted(
            mapper.c[field].type.values, key=lambda val: str(val or "")
        )
        utils.setup_text_combobox(combo, values)

    def set_model_attr(self, attr, value, validator=None):
        """It is best to use this method to set values on the model rather than
        setting them directly.  Derived classes can override this method to
        take action when the model changes.

        :param attr: the attribute on self.model to set
        :param value: the value the attribute will be set to
        :param validator: validates the value before setting it
        """
        logger.debug("editor.set_model_attr(%s, %s)", attr, value)
        if validator:
            try:
                value = validator.to_python(value)
                self.remove_problem(f"BAD_VALUE_{attr}")
            except ValidatorError as e:
                logger.debug("GenericEditorPresenter.set_model_attr %s", e)
                self.add_problem(f"BAD_VALUE_{attr}")
            else:
                setattr(self.model, attr, value)
        else:
            setattr(self.model, attr, value)

    def assign_simple_handler(self, widget_name, model_attr, validator=None):
        """Assign handlers to widgets to change fields in the model.

        Note: Where widget is a Gtk.ComboBox or Gtk.ComboBoxEntry then
        the value is assumed to be stored in model[row][0]

        :param widget_name:
        :param model_attr:
        :param validator:
        """
        logger.debug("assign_simple_handler %s", widget_name)
        widget = self.view.widgets[widget_name]
        check(widget is not None, _("no widget with name %s") % widget_name)

        class ProblemValidator(Validator):
            def __init__(self, presenter, wrapped):
                self.presenter = presenter
                self.wrapped = wrapped

            def to_python(self, value):
                try:
                    value = self.wrapped.to_python(value)
                    self.presenter.remove_problem(
                        f"BAD_VALUE_{model_attr}", widget
                    )
                except Exception as e:
                    logger.debug(
                        "GenericEditorPresenter.ProblemValidator"
                        ".to_python %s",
                        e,
                    )
                    self.presenter.add_problem(
                        f"BAD_VALUE_{model_attr}", widget
                    )
                    raise
                return value

        if validator:
            validator = ProblemValidator(self, validator)

        if isinstance(widget, Gtk.Entry):  # also catches SpinButtons

            def on_changed(entry):
                self.set_model_attr(model_attr, entry.get_text(), validator)

            self.view.connect(widget, "changed", on_changed)
        elif isinstance(widget, Gtk.TextView):

            def on_changed(textbuff):
                self.set_model_attr(model_attr, textbuff.props.text, validator)

            buff = widget.get_buffer()
            self.view.connect(buff, "changed", on_changed)
        elif isinstance(widget, Gtk.ComboBox):
            # this also handles Gtk.ComboBoxEntry since it extends
            # Gtk.ComboBox
            def combo_changed(combo, data=None):
                if not combo.get_active_iter():
                    # get here if there is no model on the ComboBoxEntry
                    return
                model = combo.get_model()
                value = model[combo.get_active_iter()][0]
                if model is None or combo.get_active_iter() is None:
                    return
                value = combo.get_model()[combo.get_active_iter()][0]
                if widget.get_has_entry():
                    widget.get_child().set_text(utils.nstr(value))
                self.set_model_attr(model_attr, value, validator)

            def entry_changed(entry, data=None):
                self.set_model_attr(model_attr, entry.props.text, validator)

            self.view.connect(widget, "changed", combo_changed)
            if widget.get_has_entry():
                self.view.connect(widget.get_child(), "changed", entry_changed)
        elif isinstance(
            widget, (Gtk.ToggleButton, Gtk.CheckButton, Gtk.RadioButton)
        ):

            def toggled(button, data=None):
                active = button.get_active()
                logger.debug("toggled %s: %s", widget_name, active)
                button.set_inconsistent(False)
                self.set_model_attr(model_attr, active, validator)

            self.view.connect(widget, "toggled", toggled)
        else:
            raise ValueError(
                "assign_simple_handler() -- "
                "widget type not supported: %s" % type(widget)
            )

    def assign_completions_handler(
        self,
        widget: Gtk.Entry | str,
        get_completions: Callable,
        on_select: Callable = lambda v: v,
        comparer: Callable | None = None,
        set_problems: bool = True,
    ) -> None:
        """Dynamically handle completions on a Gtk.Entry.

        Attach a handler to widgets 'changed' signal that reconstructs the
        widgets model if appropriate and adds/removes a PROBLEM.

        :param widget: a Gtk.Entry instance or widget name
        :param get_completions: the callable to invoke when a list of
            completions is requested, accepts the string typed, returns an
            iterable of completions
        :param on_select: callback for when a value is selected from
            the list of completions
        :param comparer: a function that returns a bool, to be used with
            :func:`utils.search_tree_model` to check whether each item is a
            match or not
        """

        logger.debug("assign_completions_handler %s", widget)
        if not isinstance(widget, Gtk.Entry):
            widget = cast(Gtk.Entry, self.view.widgets[widget])

        def add_completions(text):
            """Reconstruct the widgets model (Gtk.ListStore)"""
            if get_completions is None:
                logger.debug("completion model has static list")
                # get_completions is None usually means that the
                # completions model already has a static list of
                # completions
                return

            values = get_completions(text)

            completion = widget.get_completion()
            utils.clear_model(completion)
            completion_model = Gtk.ListStore(object)
            for v in values:
                completion_model.append([v])
            completion.set_model(completion_model)

            logger.debug("completions to add: %s", values)

        def on_changed(entry, *args):
            """If entry's text is greater than widget's minimum_key_length call
            :func:`add_completions` to reconstruct the widgets model.  Also
            calls :func:`_callback` with the entry's text to add remove
            PROBLEM_NOT_FOUND or select an item if appropriate.

            :param entry: a Gtk.Entry widget
            """
            logger.debug(
                "assign_completions_handler::on_changed %s %s", entry, args
            )
            text = entry.get_text()

            key_length = widget.get_completion().get_minimum_key_length()
            if len(text) > key_length:
                logger.debug("recomputing completions matching %s", text)
                add_completions(text)

            def _callback(text, comparer):
                logger.debug("on_changed - part two")
                comp = entry.get_completion()
                comp_model = comp.get_model()
                found = []
                if comp_model:
                    comp_model.foreach(
                        lambda m, p, i, ud: logger.debug(
                            "item(%s) of comp_model: %s", p, m[p][0]
                        ),
                        None,
                    )
                    # search the tree model to see if the text in the
                    # entry matches one of the completions, if so then
                    # emit the match-selected signal, this allows us to
                    # type a match in the entry without having to select
                    # it from the popup

                    def _cmp(row, data):
                        return str(row[0])[: len(text)].lower() == data.lower()

                    if comparer is None:
                        comparer = _cmp

                    found = utils.search_tree_model(comp_model, text, comparer)
                    logger.debug("matches found in ListStore: %s", str(found))
                    if not found:
                        logger.debug("nothing found, nothing to select from")
                        on_select(None)
                    elif len(found) == 1:
                        logger.debug(
                            "one match, decide whether to select it - %s",
                            found[0],
                        )
                        v = comp.get_model()[found[0]][0]
                        # only auto select if the full string has been entered
                        if text.lower() == utils.nstr(v).lower():
                            comp.emit("match-selected", comp_model, found[0])
                        else:
                            on_select(None)
                    else:
                        logger.debug(
                            "multiple matches, we cannot select any - %s",
                            str(found),
                        )
                        on_select(None)

                if (
                    set_problems
                    and text != ""
                    and not found
                    and (self.PROBLEM_NOT_FOUND, widget) not in self.problems
                ):
                    self.add_problem(self.PROBLEM_NOT_FOUND, widget)
                    on_select(None)
                elif (
                    found and (self.PROBLEM_NOT_FOUND, widget) in self.problems
                ):
                    self.remove_problem(self.PROBLEM_NOT_FOUND, widget)

                # if entry is empty select nothing and remove all problem
                if text == "":
                    on_select(None)
                    self.remove_problem(self.PROBLEM_NOT_FOUND, widget)
                elif not comp_model:
                    # completion model is not in place when object is forced
                    # programmatically.
                    # `on_select` will know how to convert the text into a
                    # properly typed value.
                    on_select(text)
                    self.remove_problem(self.PROBLEM_NOT_FOUND, widget)
                logger.debug("on_changed - part two - returning")

            # callback keeps comparer in scope
            _callback(text, comparer)
            logger.debug("on_changed - part one - returning")
            return True

        def on_match_select(_completion, compl_model, treeiter):
            value = compl_model[treeiter][0]
            # temporarily block the changed ID so that this function
            # doesn't get called twice
            with widget.handler_block(_changed_sid):
                widget.props.text = str(value)
            self.remove_problem(self.PROBLEM_NOT_FOUND, widget)
            on_select(value)
            return True  # return True or on_changed() will be called with ''

        completion = widget.get_completion()
        check(
            completion is not None,
            f"Gtk.Entry {widget.get_name()} has no completion attached",
        )

        _changed_sid = self.view.connect(widget, "changed", on_changed)
        self.view.connect(completion, "match-selected", on_match_select)

    def start(self):
        """run the dialog associated to the view"""
        result = self.view.start()
        if (
            self.is_committing_presenter
            and result in self.committing_results
            and self._dirty
        ):
            self.commit_changes()
        return result

    def cleanup(self):
        """Revert any changes the presenter might have done to the widgets so
        that next time the same widgets are open everything will be normal.

        By default it only calls self.view.cleanup()
        """
        logger.debug("%s::cleanup", self.__class__.__name__)
        self.clear_problems()
        if isinstance(self.view, GenericEditorView):
            self.view.cleanup()


class PresenterLinksMixin:
    """Presenter mixin to provide a GtkMenuButton to selected web link buttons.

    To use this mixin the presenter must provide `LINK_BUTTONS_PREF_KEY`, a
    view with a GtkMenuButton widget named `link_menu_btn`, call
    `self.init_links_menu` to setup the menu, then call
    `self.remove_link_action_group` on cleanup.
    """

    LINK_BUTTONS_PREF_KEY: str
    # not entirely correct...  see: https://github.com/python/typing/issues/246
    model: db.Domain
    view: GenericEditorView

    def init_links_menu(self) -> None:
        """Initialise the menu button adding any links with `editor_button` set
        to True
        """
        menu = Gio.Menu()
        # pylint: disable=line-too-long
        action_name = self.model.__tablename__.lower() + "_link"
        action_group = Gio.SimpleActionGroup()

        menu_has_items = False
        for name, button in sorted(
            prefs.prefs.itersection(self.LINK_BUTTONS_PREF_KEY)
        ):
            if not button.get("editor_button"):
                continue
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", self.on_item_selected, button)
            action_group.add_action(action)
            menu_item = Gio.MenuItem.new(
                button.get("title"), f"{action_name}.{name}"
            )
            menu.append_item(menu_item)
            menu_has_items = True

        menu_btn: Gtk.MenuButton = self.view.widgets.link_menu_btn
        if menu_has_items:
            menu_btn.set_menu_model(menu)
            menu_btn.insert_action_group(action_name, action_group)
        else:
            utils.hide_widgets([menu_btn])

    def on_item_selected(self, _action, _param, button: LinkDict) -> None:
        desktop.open(self.get_url(button))

    def get_url(self, link: LinkDict) -> str:
        _base_uri = link["_base_uri"]
        fields = FIELD_RE.findall(_base_uri)
        if fields:
            values = {}
            for key in fields:
                val: str | db.Domain = self.model
                for step in key.split("."):
                    val = getattr(val, step, "-")
                values[key] = val if val == str(val) else ""
            url = _base_uri % values
        else:
            # remove any zws (species string)
            string = (
                str(self.model)
                .replace("\u200b", "")
                .replace(" ", link.get("_space", " "))
            )
            url = _base_uri % string
        return url

    def remove_link_action_group(self):
        """Remove the action group from map_menu_btn widget."""
        action_name = self.model.__tablename__.lower() + "_link"
        self.view.widgets.link_menu_btn.insert_action_group(action_name, None)


class PresenterMapMixin:
    """Mixin for presenters that include a map GtkMenuButton.

    Classes that use this mixin must:
    - subclass `GenericEditorPresenter`
    - have a `view` attribute that points to an instance of `GenericEditorView`
    - provide a GtkMenuButton widget named `map_menu_btn` that contains a
      GtkImage widget named `map_btn_icon` within the view's widgets
    - supply a valid string path to a mako kml template via the
      `self.kml_template` attribute
    - call `self.remove_map_action_group()` on close. (e.g. in `self.cleanup`)
    - have a `model` attribute with a `geojson` attribute that returns valid a
      geojson feature geometry part with "type" and "coordinates" keys.
    """

    def __init__(self):
        logger.debug("%s::__init__", type(self).__name__)
        self.kml_template = None
        self.init_map_menu()

    def on_map_copy(self, *_args):
        # convert to JSON string and copy to clipboard
        geojson = json.dumps(self.model.geojson)
        if bauble.gui:
            bauble.gui.get_display_clipboard().set_text(geojson, -1)

    def on_map_paste(self, *_args):
        if bauble.gui:
            text = bauble.gui.get_display_clipboard().wait_for_text()
            if re.match(r"-?\d{1,2}\.\d*, -?\d{1,3}\.\d*", text):
                text = utils.geo.web_mercator_point_coords_to_geojson(text)
            elif text.startswith("<?xml"):
                text = utils.geo.kml_string_to_geojson(text)
            try:
                geojson = json.loads(text)
                # basic validation...
                if not set(geojson.keys()) == {"type", "coordinates"}:
                    raise AttributeError(
                        "wrong keys, need 'type' and 'coordinates'"
                    )
                if self.model.geojson != geojson:
                    self.model.geojson = geojson
                    self._dirty = True
                    self.refresh_sensitivity()
            except (AttributeError, json.JSONDecodeError) as e:
                logger.debug("geojson paste %s(%s)", type(e).__name__, e)
                logger.debug("geojson paste %s", text)
                self.view.run_message_dialog(
                    _("Paste failed, invalid geojson?")
                )
        self.init_map_menu()

    def on_map_delete(self, *_args):
        msg = _("Are you sure you want to delete spatial data?")
        if self.view.run_yes_no_dialog(msg, yes_delay=1):
            if self.model.geojson:
                self.model.geojson = None
                self._dirty = True
                self.refresh_sensitivity()
                self.init_map_menu()

    def on_map_kml_show(self, *_args):
        import tempfile

        from mako.template import Template  # type: ignore [import-untyped]

        template = Template(
            filename=self.kml_template,
            input_encoding="utf-8",
            output_encoding="utf-8",
        )
        file_handle, filename = tempfile.mkstemp(suffix=".kml")
        out = template.render(value=self.model)
        os.write(file_handle, out)
        os.close(file_handle)
        try:
            utils.desktop.open(filename)
        except OSError:
            self.view.run_message_dialog(
                _(
                    "Could not open the kml file. You can open the file "
                    "manually at %s"
                )
                % filename
            )

    def init_map_menu(self):
        """Initialise the map menu button.

        Sets an appropriate icon on the button, appends an appropriate menu and
        inserts an action group to the map_menu_btn widget.  The action group
        should be removed on close for the editor to be garbage collected.
        """
        menu = Gio.Menu()
        action_name = self.model.__tablename__.lower() + "_map"
        action_group = Gio.SimpleActionGroup()
        menu_items = (
            (_("Copy"), "copy", self.on_map_copy),
            (_("Paste"), "paste", self.on_map_paste),
            (_("Delete"), "delete", self.on_map_delete),
            (_("Show"), "show", self.on_map_kml_show),
        )
        if not self.model.geojson:
            menu_items = (menu_items[1],)
            self.view.widgets.map_btn_icon.set_from_icon_name(
                "location-services-disabled-symbolic", Gtk.IconSize.BUTTON
            )
        else:
            self.view.widgets.map_btn_icon.set_from_icon_name(
                "location-services-active-symbolic", Gtk.IconSize.BUTTON
            )
        for label, name, handler in menu_items:
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", handler)
            action_group.add_action(action)
            menu_item = Gio.MenuItem.new(label, f"{action_name}.{name}")
            menu.append_item(menu_item)

        map_menu_btn = self.view.widgets.map_menu_btn
        map_menu_btn.set_menu_model(menu)
        map_menu_btn.insert_action_group(action_name, action_group)

    def remove_map_action_group(self):
        """Remove the action group from map_menu_btn widget."""
        action_name = self.model.__tablename__.lower() + "_map"
        self.view.widgets.map_menu_btn.insert_action_group(action_name, None)


class ChildPresenter(GenericEditorPresenter):
    """This Presenter acts as a proxy to another presenter that shares the same
    view. This avoids circular references by not having a presenter within a
    presenter that both hold references to the view.

    This Presenter keeps a weakref to the parent presenter and provides a pass
    through to the parent presenter for calling methods that reference the
    view.
    """

    def __init__(self, model, view, session=None):
        super().__init__(model, view, session=session, connect_signals=False)

    @property
    def view(self):
        return self._view_ref()

    @view.setter
    def view(self, view):
        if isinstance(view, GenericEditorView):
            self._view_ref = weakref.ref(view)
        else:
            raise ValueError("view must be an instance of GenericEditorView")


class GenericModelViewPresenterEditor:
    """GenericModelViewPresenterEditor assume that model is an instance
    of object mapped to a SQLAlchemy table

    The editor creates its own session and merges the model into
    it.  If the model is already in another session that original
    session will not be effected.

    When creating a subclass of this editor then you should explicitly
    close the session when you are finished with it.

    :param model: an instance of an object mapped to a SQLAlchemy Table, the
        model will be copied and merged into self.session so that the original
        model will not be changed
    :param parent: the parent windows for the view or None
    """

    ok_responses: tuple[int, ...] = ()

    def __init__(self, model, parent=None):
        self.session = db.Session()
        self.model = self.session.merge(model)

    def commit_changes(self):
        """Commit the changes to self.session()"""
        objs = list(self.session)
        try:
            self.session.commit()
            if bauble.gui:
                bauble.gui.get_view().update()
        except Exception as e:
            logger.warning("can't commit changes: (%s)%s", type(e).__name__, e)
            self.session.rollback()
            self.session.add_all(objs)
            raise
        return True

    def __del__(self):
        if hasattr(self, "session"):
            self.session.close()


class GenericNoteBox:
    """Generic note box class meant to be subclassed by a Gtk.Template
    decoratated class that can supply appropriate widget members:

        note_expander
        category_comboentry
        date_entry
        date_button
        user_entry
        notes_remove_button
    """

    # pylint: disable=no-member

    PROBLEM_BAD_DATE = Problem("bad_date")

    note_attr = ""

    def __init__(self, presenter, model=None):
        # super required here to work with Gtk.Template in the subclasses
        super().__init__()

        self.session = object_session(presenter.model)
        self.presenter = presenter
        if model:
            self.model = model
        else:
            self.model = presenter.note_cls()
            # new note, append our model and set default date and user.
            self.presenter.notes.append(self.model)
            self.set_model_attr(
                "user", utils.get_user_display_name(), dirty=False
            )
            date_str = utils.today_str()
            self.set_model_attr("date", date_str, dirty=False)

        self.note_expander.set_label("")

        # set the model values on the widgets
        mapper = object_mapper(self.model)
        values = utils.get_distinct_values(mapper.c["category"], self.session)
        utils.setup_text_combobox(self.category_comboentry, values)
        utils.set_widget_value(
            self.category_comboentry, self.model.category or ""
        )
        utils.setup_date_button(None, self.date_entry, self.date_button)
        date_str = utils.today_str()
        if self.model.date:
            try:
                fmat = prefs.prefs[prefs.date_format_pref]
                date_str = self.model.date.strftime(fmat)
            except AttributeError:
                # new note, date already a string
                pass
        utils.set_widget_value(self.date_entry, date_str)

        utils.set_widget_value(self.user_entry, self.model.user or "")

        self.set_content(getattr(self.model, self.note_attr))

        # connect the signal handlers
        self.date_entry.connect("changed", self.on_date_entry_changed)
        self.user_entry.connect("changed", self.on_user_entry_changed)
        # connect category comboentry widget and child entry
        self.category_comboentry.connect(
            "changed", self.on_category_combo_changed
        )
        self.category_comboentry.get_child().connect(
            "changed", self.on_category_entry_changed
        )

        self.notes_remove_button.connect(
            "clicked", self.on_notes_remove_button
        )

        self.update_label()
        self.show_all()

    def set_content(self, text):
        raise NotImplementedError

    def set_expanded(self, expanded):
        self.note_expander.set_expanded(expanded)

    def on_notes_remove_button(self, _button, *_args):
        self.presenter.refresh()
        if self.model in self.presenter.notes:
            self.presenter.notes.remove(self.model)
        # self.widgets.remove_parent(self.widgets.note_box)
        # self.get_parent().remove(self)
        self.destroy()
        self.presenter._dirty = True
        self.presenter.parent_ref().refresh_sensitivity()

    def on_date_entry_changed(self, entry, *_args):
        text = entry.get_text()
        try:
            text = DateValidator().to_python(text)
        except ValidatorError as e:
            logger.debug("%s(%s)", type(e).__name__, e)
            self.presenter.add_problem(self.PROBLEM_BAD_DATE, entry)
        else:
            self.presenter.remove_problem(self.PROBLEM_BAD_DATE, entry)
            self.set_model_attr("date", text)

    def on_user_entry_changed(self, entry, *_args):
        value = entry.get_text()
        # only want either empty string or a name (a string), not None.
        # Presetting new notes with the current users display name ensures this
        self.set_model_attr("user", value)

    def on_category_combo_changed(self, combo, *_args):
        """Sets the text on the entry.

        The model value is set in the entry "changed" handler.
        """
        text = ""
        treeiter = combo.get_active_iter()
        if treeiter:
            text = utils.nstr(combo.get_model()[treeiter][0])
        else:
            return
        self.category_comboentry.get_child().set_text(utils.nstr(text))

    def on_category_entry_changed(self, entry, *_args):
        value = utils.nstr(entry.get_text())
        if not value:  # if value == ''
            value = None
        self.set_model_attr("category", value)

    def update_label(self):
        label = []
        date_str = None
        if self.model.date and isinstance(self.model.date, datetime.date):
            fmat = prefs.prefs[prefs.date_format_pref]
            date_str = utils.xml_safe(self.model.date.strftime(fmat))
        elif self.model.date:
            date_str = utils.xml_safe(self.model.date)
        else:
            date_str = self.date_entry.get_text()

        if self.model.user and date_str:  # and self.model.date:
            label.append(
                _("%(user)s on %(date)s")
                % dict(user=utils.xml_safe(self.model.user), date=date_str)
            )
        elif date_str:
            label.append(date_str)
        elif self.model.user:
            label.append(utils.xml_safe(self.model.user))

        if self.model.category:
            label.append(f"({self.model.category})")

        if text := getattr(self.model, self.note_attr):
            note_str = " : "
            note_str += utils.xml_safe(text).replace("\n", "  ")
            max_length = 25
            # label.props.ellipsize doesn't work properly on a
            # label in an expander we just do it ourselves here
            if len(text) > max_length:
                label.append(f"{note_str[0:max_length - 1]} …")
            else:
                label.append(note_str)

        self.note_expander.set_label(" ".join(label))

    def set_model_attr(self, attr, value, dirty=True):
        setattr(self.model, attr, value)
        self.presenter._dirty = dirty

        self.update_label()

        self.presenter.parent_ref().refresh_sensitivity()


# NOTE that due to the way PyGObject handles templated classes and inheritance
# NoteBox and PictureBox use two near identical UI files


@Gtk.Template(filename=str(Path(paths.lib_dir(), "note_box.ui")))
class NoteBox(GenericNoteBox, Gtk.Box):
    __gtype_name__ = "NoteBox"

    note_expander = Gtk.Template.Child()
    category_comboentry = Gtk.Template.Child()
    date_entry = Gtk.Template.Child()
    date_button = Gtk.Template.Child()
    user_entry = Gtk.Template.Child()
    notes_remove_button = Gtk.Template.Child()
    note_textview = Gtk.Template.Child()

    note_attr = "note"

    def set_content(self, text):
        buff = Gtk.TextBuffer()
        self.note_textview.set_buffer(buff)
        utils.set_widget_value(self.note_textview, text or "")
        if not text:
            self.presenter.add_problem(
                self.presenter.PROBLEM_EMPTY, self.note_textview
            )
        buff.connect(
            "changed", self.on_note_buffer_changed, self.note_textview
        )

    def on_note_buffer_changed(self, buff, widget, *_args):
        value = utils.nstr(buff.props.text)
        if not value:  # if value == ''
            value = None
            self.presenter.add_problem(self.presenter.PROBLEM_EMPTY, widget)
        else:
            self.presenter.remove_problem(self.presenter.PROBLEM_EMPTY, widget)
        self.set_model_attr("note", value)


class NoteBoxMenuBtnMixin:
    MENU_ACTIONGRP_NAME = "document_box"
    ROOT_PREF_KEY = prefs.document_root_pref

    def init_menu(self):
        """Initialise the menu button context menu.

        Create the ActionGroup and Menu, set the MenuButton menu model to the
        Menu and insert the ActionGroup.
        """
        menu = Gio.Menu()
        action_group = Gio.SimpleActionGroup()
        menu_items = (
            (_("Open file"), "open", self.on_file_open_clicked),
            (_("Copy file name"), "copy", self.on_copy_filename),
        )
        for label, name, handler in menu_items:
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", handler)
            action_group.add_action(action)
            menu_item = Gio.MenuItem.new(
                label, f"{self.MENU_ACTIONGRP_NAME}.{name}"
            )
            menu.append_item(menu_item)

        self.file_menu_btn.set_menu_model(menu)

        self.file_menu_btn.insert_action_group(
            self.MENU_ACTIONGRP_NAME, action_group
        )

    def on_file_open_clicked(self, *_args):
        file = os.path.join(
            prefs.prefs[self.ROOT_PREF_KEY], self.file_entry.get_text()
        )
        utils.desktop.open(file)

    def on_copy_filename(self, *_args):
        if bauble.gui:
            clipboard = bauble.gui.get_display_clipboard()
            clipboard.set_text(self.file_entry.get_text(), -1)


@Gtk.Template(filename=str(Path(paths.lib_dir(), "picture_box.ui")))
class PictureBox(GenericNoteBox, NoteBoxMenuBtnMixin, Gtk.Box):
    __gtype_name__ = "PictureBox"

    note_expander = cast(Gtk.Expander, Gtk.Template.Child())
    category_comboentry = cast(Gtk.ComboBox, Gtk.Template.Child())
    date_entry = cast(Gtk.Entry, Gtk.Template.Child())
    date_button = cast(Gtk.Button, Gtk.Template.Child())
    user_entry = cast(Gtk.Entry, Gtk.Template.Child())
    notes_remove_button = cast(Gtk.Entry, Gtk.Template.Child())
    file_set_box = cast(Gtk.Entry, Gtk.Template.Child())
    file_btnbrowse = cast(Gtk.Button, Gtk.Template.Child())
    file_entry = cast(Gtk.Entry, Gtk.Template.Child())
    picture_box = cast(Gtk.Box, Gtk.Template.Child())
    file_menu_btn = cast(Gtk.MenuButton, Gtk.Template.Child())

    last_folder = str(Path.home())

    note_attr = "picture"

    MENU_ACTIONGRP_NAME = "picture_box"
    ROOT_PREF_KEY = prefs.picture_root_pref

    def __init__(self, presenter, model=None):
        super().__init__(presenter, model)
        self.presenter._dirty = False

        self._txt_sid = self.file_entry.connect(
            "changed", self.on_text_entry_changed
        )
        self.file_btnbrowse.connect("clicked", self.on_file_btnbrowse_clicked)

        self.init_menu()

    def set_content(self, text):
        text = text or ""
        # because _txt_id can't be defined before calling super.. need to check
        # it exists here, first run of this it won't be.
        if hasattr(self, "_txt_sid"):
            self.file_entry.handler_block(self._txt_sid)
        self.file_entry.set_text(text)
        if hasattr(self, "_txt_sid"):
            self.file_entry.handler_unblock(self._txt_sid)
        # NOTE text param here is the filename as a string
        for widget in list(self.picture_box.get_children()):
            widget.destroy()
        if text.startswith("http://") or text.startswith("https://"):
            img = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            utils.ImageLoader(img, text).start()
            self.file_btnbrowse.set_sensitive(False)
        elif text:
            img = Gtk.Image()
            try:
                thumbname = os.path.join(
                    prefs.prefs[prefs.picture_root_pref], "thumbs", text
                )
                filename = os.path.join(
                    prefs.prefs[prefs.picture_root_pref], text
                )
                if os.path.isfile(thumbname):
                    pixbuf = GdkPixbuf.Pixbuf.new_from_file(thumbname)
                else:
                    fullbuf = GdkPixbuf.Pixbuf.new_from_file(filename)
                    fullbuf = fullbuf.apply_embedded_orientation()
                    scale_x = fullbuf.get_width() / 400.0
                    scale_y = fullbuf.get_height() / 400.0
                    scale = max(scale_x, scale_y, 1)
                    x = int(fullbuf.get_width() / scale)
                    y = int(fullbuf.get_height() / scale)
                    pixbuf = fullbuf.scale_simple(
                        x, y, GdkPixbuf.InterpType.BILINEAR
                    )
                img.set_from_pixbuf(pixbuf)
                self.file_set_box.set_sensitive(False)
            except GLib.GError as e:
                logger.debug("picture %s caused GLib.GError %s", text, e)
                label = _("picture file %s not found.") % text
                img = Gtk.Label()
                img.set_text(label)
            except Exception as e:  # pylint: disable=broad-except
                logger.warning("can't commit changes: (%s) %s", type(e), e)
                img = Gtk.Label()
                img.set_text(e)
        else:
            # make button hold some text
            img = Gtk.Label()
            img.set_text(_("Choose a file or enter a URL…"))
        img.show()
        self.picture_box.add(img)
        self.picture_box.show()

    def on_notes_remove_button(self, _button, *_args):
        text = self.model.picture or ""
        thumbname = os.path.join(
            prefs.prefs[prefs.picture_root_pref], "thumbs", text
        )
        filename = os.path.join(prefs.prefs[prefs.picture_root_pref], text)
        if os.path.isfile(thumbname) or os.path.isfile(filename):
            # for testing
            parent = None
            if self.presenter.parent_ref().view:
                parent = self.presenter.parent_ref().view.get_window()
            msg = _("File %s exist, would you like to delete?") % text

            # check if file exists in other pictures first...
            tables = [
                table
                for name, table in db.metadata.tables.items()
                if name.endswith("_picture")
            ]
            for table in tables:
                others = self.session.query(table).filter(
                    table.c.picture == self.model.picture
                )

                if self.model.__tablename__ == table.name:
                    others = others.filter(table.c.id != self.model.id)

                others = others.count()

                if others:
                    msg += _(
                        " %s other picture(s) of type %s exist using "
                        "the same file, "
                    ) % (others, table.name)
            if utils.yes_no_dialog(msg, parent=parent, yes_delay=0.5):
                try:
                    if os.path.isfile(thumbname):
                        os.remove(thumbname)
                    if os.path.isfile(filename):
                        os.remove(filename)
                except Exception as e:
                    logger.debug("%s(%s)", type(e).__name__, e)
                    utils.create_message_details_dialog(
                        _("Error removing file...  File in use?"),
                        parent=parent,
                        details=e,
                    )
                    return
        get_search_view().pictures_scroller.selection = []
        super().on_notes_remove_button(_button, *_args)

    def on_file_btnbrowse_clicked(self, _widget) -> None:
        file_chooser_dialog = Gtk.FileChooserNative.new(
            _("Select picture(s) to add…"),
            None,
            Gtk.FileChooserAction.OPEN,
        )
        file_chooser_dialog.set_select_multiple(True)
        file_chooser_dialog.set_current_folder(self.last_folder)
        file_chooser_dialog.run()
        filenames = file_chooser_dialog.get_filenames()
        boxes = [self]
        boxes += [
            self.presenter.add_note() for __ in range(len(filenames) - 1)
        ]
        try:
            for box, filename in zip(boxes, filenames):
                # remember chosen location for next time
                self.__class__.last_folder, basename = os.path.split(filename)
                logger.debug("new current folder is: %s", self.last_folder)
                # copy file to picture_root_dir (if not yet there),
                # check if the file already exists.
                if os.path.isfile(
                    os.path.join(
                        prefs.prefs[prefs.picture_root_pref], basename
                    )
                ):
                    msg = _(
                        'A file with that name already exists, select "Yes" '
                        "and the name will be appended with a unique "
                        "identifier, if you wish to change the name "
                        'yourself select "No" to stop here so you can rename '
                        "it before returning."
                    )
                    # for testing
                    parent = None
                    if self.presenter.parent_ref().view:
                        parent = self.presenter.parent_ref().view.get_window()
                    if utils.yes_no_dialog(msg, parent=parent):
                        name, ext = os.path.splitext(basename)
                        tstamp = datetime.datetime.now().strftime("%Y%m%d%M%S")
                        rename = name + "_" + tstamp + ext
                        self._copy_picture(box, basename, rename)
                    else:
                        if box.model in self.presenter.notes:
                            self.presenter.notes.remove(box.model)
                        box.destroy()
                        box.presenter.parent_ref().refresh_sensitivity()
                else:
                    self._copy_picture(box, basename)
        except Exception as e:  # pylint: disable=broad-except
            logger.warning("unhandled exception: (%s)%s", type(e).__name__, e)
        finally:
            file_chooser_dialog.destroy()

    def _copy_picture(
        self, box: Self, name: str, rename: str | None = None
    ) -> None:
        utils.copy_picture_with_thumbnail(self.last_folder, name, rename)
        box.file_entry.set_text(name)
        utils.set_widget_value(
            box.category_comboentry, self.model.category or ""
        )
        box.set_expanded(True)

    def on_text_entry_changed(self, widget):
        self.set_model_attr("picture", widget.get_text())
        self.set_content(widget.get_text())
        get_search_view().pictures_scroller.selection = []


@Gtk.Template(filename=str(Path(paths.lib_dir(), "document_box.ui")))
class DocumentBox(GenericNoteBox, NoteBoxMenuBtnMixin, Gtk.Box):
    __gtype_name__ = "DocumentBox"

    note_expander = Gtk.Template.Child()
    category_comboentry = Gtk.Template.Child()
    date_entry = Gtk.Template.Child()
    date_button = Gtk.Template.Child()
    user_entry = Gtk.Template.Child()
    notes_remove_button = Gtk.Template.Child()
    file_set_box = Gtk.Template.Child()
    file_btnbrowse = Gtk.Template.Child()
    file_entry = Gtk.Template.Child()
    file_menu_btn = Gtk.Template.Child()
    note_textview = Gtk.Template.Child()

    last_folder = str(Path.home())

    note_attr = "document"

    def __init__(self, presenter, model=None):
        super().__init__(presenter, model)
        self.set_note_content(self.model.note)

        self.presenter._dirty = False

        self._txt_sid = self.file_entry.connect(
            "changed", self.on_text_entry_changed
        )
        self.file_btnbrowse.connect("clicked", self.on_file_btnbrowse_clicked)

        self.init_menu()

    def set_content(self, text):
        text = text or ""
        # because _txt_id can't be defined before calling super.. need to check
        # it exists here, first run of this it won't be.
        if hasattr(self, "_txt_sid"):
            self.file_entry.handler_block(self._txt_sid)
        self.file_entry.set_text(text)
        if hasattr(self, "_txt_sid"):
            self.file_entry.handler_unblock(self._txt_sid)
        # NOTE text param here is the filename or URL as a string
        if text.startswith("http://") or text.startswith("https://"):
            self.file_btnbrowse.set_sensitive(False)
            return
        filename = os.path.join(prefs.prefs[prefs.document_root_pref], text)
        if os.path.isfile(filename):
            self.file_set_box.set_sensitive(False)
            self.file_menu_btn.set_sensitive(True)

    def set_note_content(self, text):
        buff = Gtk.TextBuffer()
        self.note_textview.set_buffer(buff)
        utils.set_widget_value(self.note_textview, text or "")
        if not text:
            self.presenter.add_problem(
                self.presenter.PROBLEM_EMPTY, self.note_textview
            )
        buff.connect(
            "changed", self.on_note_buffer_changed, self.note_textview
        )

    def on_note_buffer_changed(self, buff, widget, *_args):
        value = utils.nstr(buff.props.text)
        if not value:  # if value == ''
            value = None
            self.presenter.add_problem(self.presenter.PROBLEM_EMPTY, widget)
        else:
            self.presenter.remove_problem(self.presenter.PROBLEM_EMPTY, widget)
        self.set_model_attr("note", value)

    def on_notes_remove_button(self, _button, *_args):
        text = self.model.document or ""
        filename = os.path.join(prefs.prefs[prefs.document_root_pref], text)
        if os.path.isfile(filename):
            # for testing
            parent = None
            if self.presenter.parent_ref().view:
                parent = self.presenter.parent_ref().view.get_window()
            msg = _("File %s exist, would you like to delete?") % text

            # check if file exists in other documents first...
            tables = [
                table
                for name, table in db.metadata.tables.items()
                if name.endswith("_document")
            ]
            for table in tables:
                others = self.session.query(table).filter(
                    table.c.document == self.model.document
                )

                if self.model.__tablename__ == table.name:
                    others = others.filter(table.c.id != self.model.id)

                others = others.count()

                if others:
                    msg += _(
                        " %s other documents(s) of type %s exist using "
                        "the same file, "
                    ) % (others, table.name)
            if utils.yes_no_dialog(msg, parent=parent, yes_delay=0.5):
                try:
                    if os.path.isfile(filename):
                        os.remove(filename)
                except Exception as e:
                    logger.debug("%s(%s)", type(e).__name__, e)
                    utils.create_message_details_dialog(
                        _("Error removing file...  File in use?"),
                        parent=parent,
                        details=e,
                    )
                    return
        super().on_notes_remove_button(_button, *_args)

    def on_file_btnbrowse_clicked(self, _widget):
        file_chooser_dialog = Gtk.FileChooserNative()
        try:
            logger.debug("about to set current folder - %s", self.last_folder)
            file_chooser_dialog.set_current_folder(self.last_folder)
            file_chooser_dialog.run()
            filename = file_chooser_dialog.get_filename()
            if filename:
                # remember chosen location for next time
                self.__class__.last_folder, basename = os.path.split(filename)
                logger.debug("new current folder is: %s", self.last_folder)
                # check if the file already exists.
                if os.path.isfile(
                    os.path.join(
                        prefs.prefs[prefs.document_root_pref], basename
                    )
                ):
                    msg = _(
                        'A file with that name already exists, select "Yes" '
                        "and the name will be appended with a unique "
                        "identifier, if you wish to change the name "
                        'yourself select "No" to stop here so you can rename '
                        "it before returning."
                    )
                    # for testing
                    parent = None
                    if self.presenter.parent_ref().view:
                        parent = self.presenter.parent_ref().view.get_window()
                    if utils.yes_no_dialog(msg, parent=parent):
                        name, ext = os.path.splitext(basename)
                        tstamp = datetime.datetime.now().strftime("%Y%m%d%M%S")
                        basename = name + "_" + tstamp + ext
                    else:
                        self.destroy()
                        self.presenter.parent_ref().refresh_sensitivity()
                        return

                destination = os.path.join(
                    prefs.prefs[prefs.document_root_pref], basename
                )

                import shutil

                shutil.copy(filename, destination)
                self.file_entry.set_text(basename)
        except Exception as e:  # pylint: disable=broad-except
            logger.warning("unhandled exception: (%s)%s", type(e).__name__, e)
        finally:
            file_chooser_dialog.destroy()

    def on_text_entry_changed(self, widget):
        self.set_model_attr("document", widget.get_text())
        self.set_content(widget.get_text())


class NotesPresenter(GenericEditorPresenter):
    """The NotesPresenter provides a generic presenter for editor notes
    on an item in the database.

    This presenter requires that notes_property provide a specific interface.
    Must also call cleanup when finished to ensure it is correctly garbage
    collected.

    :param presenter: the parent presenter of this presenter
    :param notes_property: the string name of the notes property of the
        presenter.model
    :param parent_container: the Gtk.Container to add the notes editor box to
    """

    CONTENTBOX: type[GenericNoteBox] = NoteBox

    def __init__(self, presenter, notes_property, parent_container):
        super().__init__(presenter.model, None)

        filename = str(Path(paths.lib_dir(), "notes.glade"))
        self.widgets = utils.BuilderWidgets(filename)

        self.parent_ref = weakref.ref(presenter)
        self.note_cls = (
            object_mapper(presenter.model)
            .get_property(notes_property)
            .mapper.class_
        )
        self.notes_property = notes_property
        self.refresh()
        parent_container.add(self.widgets.notes_editor_box)

        # the `expander`s are added to self.box
        self.box = self.widgets.notes_expander_box

        valid_notes_count = 0
        for note in self.notes:
            box = self.add_note(note)
            box.set_expanded(False)
            valid_notes_count += 1

        logger.debug("notes: %s", self.notes)
        logger.debug("children: %s", self.box.get_children())

        self.widgets.notes_add_button.connect(
            "clicked", self.on_add_button_clicked
        )
        self.box.show_all()

    def refresh(self):
        self.notes = getattr(self.parent_ref().model, self.notes_property)

    def cleanup(self):
        # garbage collect (esp. the on_add_button_clicked signal handler),
        # idle_add avoids double-linked list warning
        GLib.idle_add(self.widgets.notes_editor_box.destroy)
        super().cleanup()

    def on_add_button_clicked(self, _button):
        box = self.add_note()
        box.set_expanded(True)

    def add_note(self, note=None):
        """Add a new note to the model."""
        box = self.CONTENTBOX(self, note)
        self.box.pack_start(box, False, False, 0)
        self.box.reorder_child(box, 0)
        box.show_all()
        return box


class PicturesPresenter(NotesPresenter):
    """Pictures are very similar to notes.

    you add a picture and you see a picture but the database will just hold
    the name of the corresponding file.

    as for other presenters, you can expand/collapse each inserted
    picture, you add or remove pictures, you see them on screen.

    this class works just the same as the NotesPresenter, with the
    note_textview replaced by a Button containing an Image.
    """

    CONTENTBOX = PictureBox

    def __init__(self, presenter, notes_property, parent_container):
        super().__init__(presenter, notes_property, parent_container)

        notes = self.box.get_children()
        if notes:
            notes[0].set_expanded(False)  # expand none


class DocumentsPresenter(NotesPresenter):
    """Documents are very similar to notes.

    This class works just the same as the NotesPresenter
    """

    CONTENTBOX = DocumentBox

    def __init__(self, presenter, notes_property, parent_container):
        super().__init__(presenter, notes_property, parent_container)

        notes = self.box.get_children()
        if notes:
            notes[0].set_expanded(False)  # expand none
