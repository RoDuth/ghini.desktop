# Copyright 2008-2010 Brett Adams
# Copyright 2015 Mario Frasca <mario@anche.no>.
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
Core user interface
"""

import logging
import os
import traceback
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Literal
from typing import Protocol

logger = logging.getLogger(__name__)

from gi.repository import Gdk
from gi.repository import GdkPixbuf
from gi.repository import Gio
from gi.repository import GLib
from gi.repository import Gtk
from pyparsing import StringEnd
from pyparsing import StringStart
from pyparsing import Word
from pyparsing import alphanums
from pyparsing import rest_of_line

import bauble
from bauble import db
from bauble import paths
from bauble import pluginmgr
from bauble import prefs
from bauble import utils
from bauble.i18n import _
from bauble.prefs import datetime_format_pref
from bauble.search.query_builder import QueryBuilder
from bauble.utils import desktop
from bauble.view import SearchView


class SimpleSearchBox(Gtk.Frame):
    """Provides a simple search for the splash screen."""

    def __init__(self):
        super().__init__(label=_("Simple Search"))
        tooltip = _(
            "Simple search provides a quick way to access basic expression "
            "searches with the convenience of auto-completion. For more "
            "advanced searches the query builder provides a better starting "
            "point.\n\nTo return all of a domain use = *"
        )
        self.set_tooltip_text(tooltip)
        self.domain = None
        self.columns = None
        self.short_domain = None
        box = Gtk.Box(margin=10)
        self.add(box)
        self.domain_combo = Gtk.ComboBoxText()
        self.domain_combo.connect("changed", self.on_domain_combo_changed)
        box.add(self.domain_combo)
        self.cond_combo = Gtk.ComboBoxText()
        for cond in ["=", "contains", "like"]:
            self.cond_combo.append_text(cond)
        self.cond_combo.set_active(0)
        box.add(self.cond_combo)
        self.entry = Gtk.Entry()
        liststore = Gtk.ListStore(str)
        completion = Gtk.EntryCompletion()
        completion.set_model(liststore)
        completion.set_text_column(0)
        completion.set_minimum_key_length(2)
        completion.set_popup_completion(True)
        self.entry.set_completion(completion)
        self.entry.connect("activate", self.on_entry_activated)
        self.entry.connect("changed", self.on_entry_changed)
        box.pack_start(self.entry, True, True, 0)
        self.completion_getter = None

    def on_entry_activated(self, entry):
        condition = self.cond_combo.get_active_text()
        text = entry.get_text()
        if text != "*":
            text = repr(text)
        search_str = f"{self.short_domain} {condition} {text}"
        if bauble.gui:
            bauble.gui.send_command(search_str)

    def on_domain_combo_changed(self, combo):
        from bauble import search

        mapper_search = search.strategies.get_strategy("MapperSearch")
        domain = combo.get_active_text()
        # domain is None when resetting
        if domain:
            self.domain, self.columns = mapper_search.domains[domain]
            self.short_domain = min(
                (
                    min((k, v), key=len)
                    for k, v in mapper_search.shorthand.items()
                    if v == domain
                ),
                key=len,
            )
            self.completion_getter = mapper_search.completion_funcs.get(domain)

    def on_entry_changed(self, entry):
        text = entry.get_text()
        completion = entry.get_completion()
        key_length = completion.get_minimum_key_length()
        utils.clear_model(completion)
        if len(text) < key_length:
            return
        completion_model = Gtk.ListStore(str)
        session = db.Session()
        if self.completion_getter:
            for val in self.completion_getter(session, text):
                completion_model.append([val])
        else:
            for column in self.columns:
                vals = (
                    session.query(getattr(self.domain, column))
                    .filter(
                        utils.ilike(getattr(self.domain, column), f"{text}%%")
                    )
                    .distinct()
                    .limit(10)
                )
                for val in vals:
                    completion_model.append([str(val[0])])
        session.close()
        completion.set_model(completion_model)

    def update(self):
        from bauble import search

        mapper_search = search.strategies.get_strategy("MapperSearch")
        self.domain_combo.remove_all()
        for domain in sorted(mapper_search.domains.keys()):
            self.domain_combo.append_text(domain)
        self.domain_combo.set_active(0)
        self.cond_combo.set_active(0)
        self.entry.set_text("")


class Updateable(Protocol):  # pylint: disable=too-few-public-methods
    def update(self):
        """Update the widget"""


# best solution I could come up with for the MetaClass conflict between
# Protocol and GObject
PMeta: type = type(Protocol)


WMeta: type = type(Gtk.Widget)


class _UWMeta(PMeta, WMeta):
    pass


class UpdateableWidget(Gtk.Widget, Updateable, metaclass=_UWMeta):
    pass


class DefaultView(pluginmgr.View, Gtk.Box):
    """consider DefaultView a splash screen.

    It is displayed at program start and when home is selected.  it's the core
    of the "what do I do now" screen.

    DefaultView is related to the SplashCommandHandler, not to the
    view.DefaultCommandHandler
    """

    infoboxclass: type[UpdateableWidget] | None = None
    main_widget: UpdateableWidget | Gtk.Widget | None = None

    def __init__(self) -> None:
        super().__init__()

        # splash window contains a hbox: left half is for the proper splash,
        # right half for infobox, only one infobox is allowed.

        self.hbox = Gtk.Box()
        self.pack_start(self.hbox, True, True, 0)

        self.vbox = Gtk.Box(spacing=0, orientation=Gtk.Orientation.VERTICAL)
        self.search_box = SimpleSearchBox()
        self.search_box.set_valign(Gtk.Align.START)
        self.search_box.set_vexpand(False)
        self.vbox.pack_start(self.search_box, False, True, 5)

        self.hbox.pack_start(self.vbox, True, True, 0)

        self.infobox: UpdateableWidget | None = None
        self._main_widget: UpdateableWidget | Gtk.Widget | None = None

    def update(self, *_args) -> None:
        logger.debug("DefaultView::update")

        self.search_box.update()

        if self.infoboxclass and not self.infobox:
            logger.debug("DefaultView::update - creating infobox")
            self.infobox = self.infoboxclass()  # pylint: disable=not-callable
            self.hbox.pack_end(self.infobox, False, False, 8)
            self.infobox.set_vexpand(False)
            self.infobox.set_hexpand(False)
            self.infobox.show()
        if self.infobox:
            logger.debug("DefaultView::update - updating infobox")
            self.infobox.update()
        self.set_main_widget()
        # pylint: disable=no-member
        if (
            self._main_widget
            and hasattr(self._main_widget, "update")
            and callable(self._main_widget.update)
        ):
            self._main_widget.update()

    def set_main_widget(self) -> None:
        # update after db change
        if self._main_widget and self._main_widget is not self.main_widget:
            self.vbox.remove(self._main_widget)
            self._main_widget = None

        if not self._main_widget:
            if self.main_widget:
                self._main_widget = self.main_widget
            else:
                self._main_widget = Gtk.Image()
                self._main_widget.set_from_file(
                    os.path.join(paths.lib_dir(), "images", "bauble_logo.png")
                )
                self._main_widget.set_valign(Gtk.Align.START)
                self.main_widget = self._main_widget
            self.vbox.pack_start(self._main_widget, True, True, 10)
            self.vbox.show_all()


class SplashCommandHandler(pluginmgr.CommandHandler):
    command = ["home", "splash"]
    view = None

    def __init__(self):
        super().__init__()
        if self.view is None:
            logger.warning("SplashCommandHandler.view is None, expect trouble")

    def get_view(self):
        if self.view is None:
            self.view = DefaultView()
        return self.view

    def __call__(self, cmd, arg):
        self.view.update()


class GUI:
    entry_history_pref = "bauble.history"
    history_size_pref = "bauble.history_size"
    entry_history_pins_pref = "bauble.history_pins"
    history_pins_size_pref = "bauble.history_pins_size"
    window_geometry_pref = "bauble.geometry"

    _default_history_size = 26
    _default_history_pin_size = 10

    # TODO a global approach to css
    _css = Gtk.CssProvider()
    _css.load_from_data(
        b".err-bg * {background-image: image(#FF9999);}"
        b".inf-bg * {background-image: image(#B6DAF2);}"
        b".click-label {color: blue;}"
        b".problem {background-color: #FFDCDF;}"
        b".problem-bg * {background-image: image(#FFDCDF);}"
        b".err-btn * {color: #FF9999;}"
        b"#unsaved-entry {color: blue;}"
    )
    if screen := Gdk.Screen.get_default():
        Gtk.StyleContext.add_provider_for_screen(
            screen,
            _css,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

    set_view_callbacks: set[Callable] = set()
    """Any callbacks added to this list will be called each time the set_view
    is called.
    """
    main_entry_completion_callbacks: set[Callable] = set()
    """Callbacks added here will be called to generate completion strings for
    the main entry
    """
    disable_on_busy_actions: set[Gio.SimpleAction] = set()
    """Any Gio.Action added to this will be enabled/disabled when the gui
    window is set_busy.
    """

    def __init__(self) -> None:
        filename = os.path.join(paths.lib_dir(), "bauble.glade")
        self.widgets = utils.load_widgets(filename)
        self.window = self.widgets.main_window
        self.window.hide()
        self.views: deque[pluginmgr.Viewable] = deque()
        # default location of LICENSE for about window, if not available will
        # be changed when about is first opened
        self.lic_path = Path(paths.main_dir()) / "share/ghini/LICENSE"

        # restore the window size
        geometry = prefs.prefs.get(self.window_geometry_pref)
        if geometry is not None:
            self.window.set_default_size(*geometry)
            self.window.set_position(Gtk.WindowPosition.CENTER)

        self.window.connect("destroy", self.on_destroy)
        self.window.connect("delete-event", self.on_delete_event)
        self.window.connect("size_allocate", self.on_resize)
        self.window.set_title(self.title)
        actions = (
            ("cut", self.on_edit_menu_cut),
            ("copy", self.on_edit_menu_copy),
            ("paste", self.on_edit_menu_paste),
        )

        for name, handler in actions:
            self.add_action(name, handler)

        self.create_main_menu()

        try:
            logger.debug("loading icon from %s", bauble.default_icon)
            pixbuf = GdkPixbuf.Pixbuf.new_from_file(bauble.default_icon)
            self.window.set_icon(pixbuf)
        except Exception:  # pylint: disable=broad-except
            logger.warning(
                _("Could not load icon from %s"), bauble.default_icon
            )
            logger.warning(traceback.format_exc())

        combo = self.widgets.main_comboentry
        combo.connect("changed", self.on_main_combo_changed)
        model = Gtk.ListStore(str)
        combo.set_model(model)
        self.widgets.main_comboentry_entry.connect(
            "icon-press", self.on_history_pinned_clicked
        )
        self.hist_completions: list[str] = []
        self.populate_main_entry()

        main_entry = combo.get_child()
        main_entry.connect("activate", self.on_main_entry_activate)
        accel_group = Gtk.AccelGroup()
        main_entry.add_accelerator(
            "grab-focus",
            accel_group,
            ord("L"),
            Gdk.ModifierType.CONTROL_MASK,
            Gtk.AccelFlags.VISIBLE,
        )
        self.window.add_accel_group(accel_group)

        self.widgets.home_button.connect("clicked", self.on_home_clicked)

        self.widgets.prev_view_button.connect(
            "clicked", self.on_prev_view_clicked
        )
        self.widgets.next_view_button.connect(
            "clicked", self.on_next_view_clicked
        )

        self.widgets.go_button.connect("clicked", self.on_go_button_clicked)

        self.widgets.query_button.connect(
            "clicked", self.on_query_button_clicked
        )

        self.set_default_view()

        # add a progressbar to the status bar
        # Warning: this relies on Gtk.Statusbar internals and could break in
        # future versions of gtk
        statusbar = self.widgets.statusbar
        statusbar.set_spacing(10)
        self._cids: list[int] = []

        def on_statusbar_push(_statusbar, context_id: int, _txt) -> None:
            if context_id not in self._cids:
                self._cids.append(context_id)

        statusbar.connect("text-pushed", on_statusbar_push)

        # remove label from frame
        frame = statusbar.get_children()[0]
        label = frame.get_children()[0]
        frame.remove(label)

        # replace label with hbox and put label and progress bar in hbox
        hbox = Gtk.Box(homogeneous=False, spacing=5)
        frame.add(hbox)
        hbox.pack_start(label, True, True, 0)
        vbox = Gtk.Box(
            homogeneous=True, spacing=0, orientation=Gtk.Orientation.VERTICAL
        )
        hbox.pack_end(vbox, False, True, 15)
        self.progressbar = Gtk.ProgressBar()
        vbox.pack_start(self.progressbar, False, False, 0)
        self.progressbar.set_size_request(-1, 10)
        vbox.show()
        hbox.show()

        cmd = (
            StringStart()
            + ":"
            + Word(alphanums + "-_").set_results_name("cmd")
        )
        arg = rest_of_line.set_results_name("arg")
        self.cmd_parser = (cmd + StringEnd()) | (cmd + "=" + arg) | arg

        combo.grab_focus()

    def add_action(self, name, handler, value=None, param_type=None):
        """Used to add a basic SimpleAction to the window.

        If you require anything more complex i.e. one that is stateful, do not
        use this method.  Instead create and attach the action to the window
        yourself.
        """
        action = Gio.SimpleAction.new(name, param_type)
        if value:
            action.connect("activate", handler, value)
        else:
            action.connect("activate", handler)
        self.window.add_action(action)
        return action

    def remove_action(self, name):
        self.window.remove_action(name)

    def lookup_action(self, name):
        return self.window.lookup_action(name)

    def close_message_box(self):
        parent = self.widgets.msg_box_parent
        for kid in self.widgets.msg_box_parent:
            parent.remove(kid)

    def show_yesno_box(self, msg):
        self.close_message_box()
        box = utils.add_message_box(
            self.widgets.msg_box_parent, utils.MESSAGE_BOX_YESNO
        )
        box.message = msg
        box.show()

    def show_error_box(self, msg, details=None):
        self.close_message_box()
        box = utils.add_message_box(
            self.widgets.msg_box_parent, utils.MESSAGE_BOX_INFO
        )
        box.message = msg
        box.details = details
        # set red background
        box.get_style_context().add_class("err-bg")

        box.show()

    def show_message_box(self, msg):
        """Show an info message in the message drop down box."""
        self.close_message_box()
        box = utils.add_message_box(
            self.widgets.msg_box_parent, utils.MESSAGE_BOX_INFO
        )
        box.message = msg
        # set a light blue background
        box.get_style_context().add_class("inf-bg")

        box.show()

    def show(self):
        self.window.present()

    @property
    def history_size(self):
        history = prefs.prefs[self.history_size_pref]
        if history is None:
            prefs.prefs[self.history_size_pref] = self._default_history_size
        return int(prefs.prefs[self.history_size_pref])

    @property
    def history_pins_size(self):
        pins = prefs.prefs[self.history_pins_size_pref]
        if pins is None:
            prefs.prefs[self.history_pins_size_pref] = (
                self._default_history_pin_size
            )
        return int(prefs.prefs[self.history_pins_size_pref])

    def send_command(self, command):
        self.widgets.main_comboentry.get_child().set_text(command)
        self.widgets.go_button.emit("clicked")

    def on_main_combo_changed(self, widget):
        entry = widget.get_child()
        history_pins = prefs.prefs.get(self.entry_history_pins_pref, [])
        text = entry.get_text()
        if text in history_pins:
            entry.set_icon_from_icon_name(
                Gtk.EntryIconPosition.SECONDARY, "starred-symbolic"
            )
            tooltip = _(
                "Query string is a favourite: click to return it the "
                "standard search history."
            )
            entry.set_icon_tooltip_text(
                Gtk.EntryIconPosition.SECONDARY, tooltip
            )
        elif not text:
            entry.set_icon_from_icon_name(
                Gtk.EntryIconPosition.SECONDARY, None
            )
        else:
            entry.set_icon_from_icon_name(
                Gtk.EntryIconPosition.SECONDARY, "non-starred-symbolic"
            )
            tooltip = _(
                "Clip this query string to the top of your search "
                "history as a favourite"
            )
            entry.set_icon_tooltip_text(
                Gtk.EntryIconPosition.SECONDARY, tooltip
            )

    def on_main_entry_activate(self, _widget):
        self.widgets.go_button.emit("clicked")

    @staticmethod
    def on_home_clicked(*_args):
        # Need args here to use from both menu action and button
        bauble.command_handler("home", None)

    def on_prev_view_clicked(self, *_args) -> None:
        # Need args here to use from both menu action and button
        self.widgets.main_comboentry.get_child().set_text("")
        self.set_view("previous")

    def on_next_view_clicked(self, *_args) -> None:
        # Need args here to use from both menu action and button
        self.widgets.main_comboentry.get_child().set_text("")
        self.set_view("next")

    def on_go_button_clicked(self, _widget):
        self.close_message_box()
        text = self.widgets.main_comboentry.get_child().get_text().strip()
        if text == "":
            return
        self.add_to_history(text)
        tokens = self.cmd_parser.parseString(text)
        cmd = tokens.get("cmd")
        arg = tokens.get("arg")

        bauble.command_handler(cmd, arg)

    def on_query_button_clicked(self, _widget):
        query_builder = QueryBuilder(transient_for=self.window)
        query_builder.set_query(
            self.widgets.main_comboentry.get_child().get_text()
        )
        response = query_builder.run()
        if response == Gtk.ResponseType.OK:
            query = query_builder.get_query()
            self.widgets.main_comboentry.get_child().set_text(query)
            self.widgets.go_button.emit("clicked")
        query_builder.destroy()

    def on_history_pinned_clicked(self, widget, _icon_pos, _event):
        """add or remove a pin search string to the history pins."""
        text = widget.get_text()

        # bail early if no text or the text is too long
        if not text or len(text) > 1000:
            return

        history_pins = prefs.prefs.get(self.entry_history_pins_pref, [])
        history = prefs.prefs.get(self.entry_history_pref, [])
        # already pinned entry - remove the pin and add it back history
        if text in history_pins:
            history_pins.remove(text)
            prefs.prefs[self.entry_history_pins_pref] = history_pins
            self.add_to_history(text)
            self.populate_main_entry()
            return

        if text in history:
            history.remove(text)
            prefs.prefs[self.entry_history_pref] = history

        # trim the history_pins if the size is larger than the pref
        while len(history_pins) >= self.history_pins_size - 1:
            history_pins.pop()

        history_pins.insert(0, text)
        prefs.prefs[self.entry_history_pins_pref] = history_pins
        self.populate_main_entry()

    def add_to_history(self, text, index=0):
        """add text to history, if text is already in the history then set its
        index to index parameter
        """
        # bail early if no text or the text is too long
        if not text or len(text) > 1000:
            return

        if index < 0 or index > self.history_size:
            raise ValueError(
                _(
                    "index must be greater than zero and less than "
                    "the history size"
                )
            )
        history = prefs.prefs.get(self.entry_history_pref, [])
        if text in history:
            history.remove(text)
        # if its a pinned history entry bail
        history_pins = prefs.prefs.get(self.entry_history_pins_pref, [])
        if text in history_pins:
            return

        # trim the history if the size is larger than the history_size pref
        while len(history) >= self.history_size - 1:
            history.pop()

        history.insert(index, text)
        prefs.prefs[self.entry_history_pref] = history
        self.populate_main_entry()

    def populate_main_entry(self):
        history_pins = prefs.prefs.get(self.entry_history_pins_pref, [])
        history = prefs.prefs.get(self.entry_history_pref, [])
        main_combo = self.widgets.main_comboentry

        def separate(model, tree_iter):
            if model.get(tree_iter, 0) == ("--separator--",):
                return True
            return False

        main_combo.set_row_separator_func(separate)
        model = main_combo.get_model()
        model.clear()
        main_entry = self.widgets.main_comboentry.get_child()
        completion = main_entry.get_completion()
        if completion is None:
            completion = Gtk.EntryCompletion()
            completion.set_text_column(0)
            main_entry.set_completion(completion)
            compl_model = Gtk.ListStore(str)
            completion.set_model(compl_model)
            completion.set_minimum_key_length(2)
            completion.set_match_func(self.main_entry_match_func)
            main_entry.connect("changed", self.on_main_entry_changed)
        else:
            compl_model = completion.get_model()

        self.hist_completions.clear()

        if history_pins is not None:
            for pin in history_pins:
                logger.debug("adding pin to main entry: %s", pin)
                model.append([pin])
                self.hist_completions.append(pin)

        model.append(["--separator--"])

        if history is not None:
            for herstory in history:
                model.append([herstory])
                self.hist_completions.append(herstory)

    @staticmethod
    def main_entry_match_func(
        completion: Gtk.EntryCompletion, key: str, treeiter: Gtk.TreeIter
    ) -> bool:
        model = completion.get_model()

        if not model:
            return False

        value = model[treeiter][0].lower()

        if value.startswith(key):
            return True

        key_parts = key.split()
        value_parts = value.split()

        if len(key_parts) > len(value_parts):
            return False

        for key_part, value_part in zip(key_parts, value_parts):
            if not value_part.startswith(key_part):
                return False

        return True

    def on_main_entry_changed(self, entry: Gtk.Entry) -> None:
        text = entry.get_text()
        completion = entry.get_completion()
        key_length = completion.get_minimum_key_length()

        if len(text) < key_length:
            return

        utils.clear_model(completion)
        completion_model = Gtk.ListStore(str)

        for i in self.hist_completions:
            completion_model.append([i])

        for callback in self.main_entry_completion_callbacks:
            for i in sorted(callback(text)):
                if i not in self.hist_completions:
                    completion_model.append([i])

        completion.set_model(completion_model)

    @property
    def title(self):
        if bauble.conn_name is None:
            return f"Ghini {bauble.version}"
        return f"Ghini {bauble.version} - {bauble.conn_name}"

    def set_busy_actions(self, busy: bool) -> None:
        for action in self.disable_on_busy_actions:
            action.set_enabled(not busy)

    def set_busy(self, busy, name="wait"):
        if busy:
            display = Gdk.Display.get_default()
            cursor = Gdk.Cursor.new_from_name(display, name)
            window = self.window.get_property("window")
            if window:
                window.set_cursor(cursor)
        else:
            window = self.window.get_property("window")
            if window:
                window.set_cursor(None)
        self.set_busy_actions(busy)
        self.widgets.main_box.set_sensitive(not busy)

    def set_default_view(self):
        main_entry = self.widgets.main_comboentry.get_child()
        if main_entry is not None:
            main_entry.set_text("")
        SplashCommandHandler.view = DefaultView()
        self.set_view(SplashCommandHandler.view)
        pluginmgr.register_command(SplashCommandHandler)

    def set_view(
        self, view: pluginmgr.Viewable | Literal["previous", "next"]
    ) -> None:
        if isinstance(view, str):
            if view == "previous" and self.views:
                self.views.rotate()
                view = self.views[-1]
                self.get_view().set_visible(False)
                view.set_visible(True)
            elif view == "next" and self.views:
                self.views.rotate(-1)
                view = self.views[-1]
                self.get_view().set_visible(False)
                view.set_visible(True)
            return

        view_box = self.widgets.view_box

        # add new views
        if view not in view_box.get_children():
            view_box.pack_start(view, True, True, 0)
            self.views.append(view)

        for kid in view_box.get_children():
            if view == kid:
                # make selected visible
                kid.set_visible(True)
            else:
                # make not selected views not visible and stop their threads
                kid.set_visible(False)
                kid.cancel_threads()

        # make sure current view is the last view
        current = self.get_view()
        if current in self.views and not self.views[-1] is current:
            self.views.remove(current)
            self.views.append(current)

        for callback in self.set_view_callbacks:
            GLib.idle_add(callback)
        # remove the edit menu SearchView selection context part (get rebuilt
        # each time selection changes in SearchView)
        self.edit_context_menu.remove_all()
        view.show_all()

    def get_view(self):
        """return the current view in the view box."""
        for kid in self.widgets.view_box.get_children():
            if kid.get_visible():
                return kid
        return None

    @staticmethod
    def get_display_clipboard():
        return Gtk.Clipboard.get_default(Gdk.Display.get_default())

    def create_main_menu(self):
        """get the main menu from the XML description, add its actions and
        return the menubar
        """
        menu_builder = Gtk.Builder()
        menu_builder.add_from_file(os.path.join(paths.lib_dir(), "bauble.ui"))
        menu_builder.connect_signals(self)
        self.menubar = menu_builder.get_object("menubar")

        self.insert_menu = menu_builder.get_object("insert_menu")
        self.edit_context_menu = menu_builder.get_object("edit_context_menu")
        self.tools_menu = menu_builder.get_object("tools_menu")
        self.options_menu = menu_builder.get_object("options_menu")

        return self.menubar

    def remove_menu(self, position):
        """remove a menu from the menubar"""
        self.menubar.remove(position)

    def add_menu(self, name, menu, from_end=1):
        """add a menu to the menubar

        :param name: the name of the menu to add
        :param menu: the menu to add
        :param from_end: places from the end of the menubar as an int

        :return: position in the menu as an int
        """
        position = self.menubar.get_n_items() - from_end
        self.menubar.insert_submenu(position, name, menu)
        return position

    def add_to_insert_menu(self, editor, label):
        """add an editor to the insert menu

        :param editor: the editor to add to the menu
        :param label: the label for the menu item
        """
        action_name = f"{label.lower()}_activated"
        action = self.add_action(
            action_name, self.on_insert_menu_item_activate, editor
        )
        self.disable_on_busy_actions.add(action)
        item = Gio.MenuItem.new(label, f"win.{action_name}")
        self.insert_menu.append_item(item)

    def build_tools_menu(self):
        """Build the tools menu from the tools provided by the plugins.

        This method is generally called after plugin initialization
        """
        item_num = 0
        self.tools_menu.remove_all()
        tools = {"__root": []}
        # categorize the tools into a dict
        for plugin in list(pluginmgr.plugins.values()):
            for tool in plugin.tools:
                if tool.category is not None:
                    tools.setdefault(tool.category, []).append(tool)
                else:
                    tools["__root"].append(tool)

        # add the tools with no category to the root menu
        root_tools = sorted(tools.pop("__root"), key=lambda tool: tool.label)
        for tool in root_tools:
            action_name = f"tool{item_num}_activated"
            item_num += 1
            action = self.add_action(
                action_name, self.on_tools_menu_item_activate, tool
            )
            self.disable_on_busy_actions.add(action)
            item = Gio.MenuItem.new(tool.label, f"win.{action_name}")
            self.tools_menu.append_item(item)
            if not tool.enabled:
                item.set_sensitive(False)

        # create submenus for the categories and add the tools
        for category in sorted(tools.keys()):
            submenu = Gio.Menu()
            self.tools_menu.append_submenu(category, submenu)
            for tool in sorted(tools[category], key=lambda tool: tool.label):
                action_name = f"tool{item_num}_activated"
                item_num += 1
                action = self.add_action(
                    action_name, self.on_tools_menu_item_activate, tool
                )
                self.disable_on_busy_actions.add(action)
                item = Gio.MenuItem.new(tool.label, f"win.{action_name}")
                submenu.append_item(item)
                if not tool.enabled:
                    item.set_sensitive(False)

    @staticmethod
    def on_tools_menu_item_activate(_action, _param, tool):
        """Start a tool on the Tool menu."""
        try:
            tool.start()
        except Exception as e:  # pylint: disable=broad-except
            utils.message_details_dialog(
                utils.xml_safe(str(e)),
                traceback.format_exc(),
                Gtk.MessageType.ERROR,
            )
            logger.debug(traceback.format_exc())

    def on_insert_menu_item_activate(self, _action, _param, editor_cls):
        try:
            view = self.get_view()
            if isinstance(view, SearchView):
                expanded_rows = view.get_expanded_rows()
            # editor_cls can be a class, of which we get an instance, and we
            # invoke the `start` method of this instance. or it is a
            # callable, then we just use its return value and we are done.
            if isinstance(editor_cls, type(lambda x: x)):
                editor = None
                committed = editor_cls()
            else:
                editor = editor_cls()
                committed = editor.start()
            if committed is not None and isinstance(view, SearchView):
                view.results_view.collapse_all()
                view.expand_to_all_rows(expanded_rows)
        except Exception as e:  # pylint: disable=broad-except
            utils.message_details_dialog(
                utils.xml_safe(str(e)),
                traceback.format_exc(),
                Gtk.MessageType.ERROR,
            )
            logger.error(
                "%s(%s)\n%s", type(e).__name__, e, traceback.format_exc()
            )
            return

        if editor is None:
            return

        presenter_cls = view_cls = None
        if hasattr(editor, "presenter"):
            presenter_cls = type(editor.presenter)
            view_cls = type(editor.presenter.view)

        # delete the editor
        del editor

        # check for leaks
        obj = utils.gc_objects_by_type(editor_cls)
        if obj != []:
            logger.warning("%s leaked: %s", editor_cls.__name__, obj)

        if presenter_cls:
            obj = utils.gc_objects_by_type(presenter_cls)
            if obj != []:
                logger.warning("%s leaked: %s", presenter_cls.__name__, obj)
            obj = utils.gc_objects_by_type(view_cls)
            if obj != []:
                logger.warning("%s leaked: %s", view_cls.__name__, obj)

    def on_edit_menu_cut(self, _action, _param):
        self.widgets.main_comboentry.get_child().cut_clipboard()

    def on_edit_menu_copy(self, _action, _param):
        self.widgets.main_comboentry.get_child().copy_clipboard()

    def on_edit_menu_paste(self, _action, _param):
        self.widgets.main_comboentry.get_child().paste_clipboard()

    @staticmethod
    def on_edit_menu_preferences(_action, _param):
        bauble.command_handler("prefs", None)

    @staticmethod
    def on_edit_menu_history(_action, _param):
        bauble.command_handler("history", None)

    def on_file_menu_new(self, _action, _param):
        msg = _(
            "<b>CAUTION! This will wipe all data for the current "
            "connection</b>\n\n"
            "If a database already exists at this connection then "
            "creating a new database will destroy your current data.\n\n"
            "<i>Are you sure this is what you want to do?</i>"
        )

        if not utils.yes_no_dialog(msg, yes_delay=2):
            return

        bauble.command_handler("home", None)
        try:
            self.insert_menu.remove_all()
            db.create()
            pluginmgr.init()
        except Exception as e:  # pylint: disable=broad-except
            msg = _("Could not create a new database.\n\n%s") % utils.xml_safe(
                e
            )
            traceb = utils.xml_safe(traceback.format_exc())
            utils.message_details_dialog(msg, traceb, Gtk.MessageType.ERROR)
            return

    def on_file_menu_open(self, _action, _param):
        """Open the connection manager."""
        from .connmgr import start_connection_manager

        name, uri = start_connection_manager()
        if name is None:
            return

        engine = None
        try:
            engine = db.open_conn(uri, True, True)
        except Exception as e:  # pylint: disable=broad-except
            msg = _("Could not open connection.\n\n%s") % e
            utils.message_details_dialog(
                msg, traceback.format_exc(), Gtk.MessageType.ERROR
            )
            logger.warning(e)
            self.on_file_menu_open(None, None)

        if engine is None:
            # the database wasn't opened
            return

        # everything seems to have passed ok so setup the rest of bauble
        bauble.conn_name = name
        self.window.set_title(self.title)
        # TODO: come up with a better way to reset the handler than have
        # to bauble.last_handler = None
        #
        # we have to set last_handler to None since although the
        # view is changing the handler isn't so we might end up
        # using the same instance of a view that could have old
        # settings from the previous handler...
        bauble.last_handler = None
        self.insert_menu.remove_all()
        self.statusbar_clear()
        pluginmgr.init()
        bauble.command_handler("home", None)

    def statusbar_clear(self):
        """Call Gtk.Statusbar.pop() for each context_id that had previously
        been pushed() onto the the statusbar stack.

        This might not clear all the messages in the statusbar but it's the
        best we can do without knowing how many messages are in the stack.
        """
        # TODO: to clear everything in the statusbar we would probably
        # have to subclass Gtk.Statusbar to keep track of the message
        # ids and context ids so we can properly clear the statusbar.
        for cid in self._cids:
            self.widgets.statusbar.pop(cid)

    @staticmethod
    def on_help_menu_contents(_action, _param):
        desktop.open(
            "http://ghini.readthedocs.io/en/ghini-1.0-dev/",
            dialog_on_error=True,
        )

    @staticmethod
    def on_help_menu_bug(_action, _param):
        desktop.open(
            "https://github.com/RoDuth/ghini.desktop/issues/new",
            dialog_on_error=True,
        )

    @staticmethod
    def on_help_menu_logfile(_action, _param):
        logger.debug("opening log file from help menu")
        filename = os.path.join(paths.appdata_dir(), "bauble.log")
        desktop.open(filename, dialog_on_error=True)

    def on_help_menu_about(self, _action, _param):
        about = Gtk.AboutDialog(transient_for=self.window)
        about.set_program_name("Ghini Desktop")
        about.set_version(bauble.version)
        # about.set_website(_("http://ghini.github.io"))
        f = os.path.join(paths.lib_dir(), "images", "icon.svg")
        logger.debug("about using icon: %s", f)
        pixbuf = GdkPixbuf.Pixbuf.new_from_file(f)
        about.set_logo(pixbuf)
        about.set_copyright(_("Copyright © by its contributors."))

        if not self.lic_path.exists():
            # most likely only when run from source
            self.lic_path = list(paths.root_dir().glob("**/LICENSE"))[0]

        logger.debug("about using license at %s", self.lic_path)

        with self.lic_path.open("r", encoding="utf-8") as f:
            lics = f.read()
        about.set_license(lics)  # not translated
        about.set_comments(
            _(
                "This version installed on: %s\n"
                "Latest published version: %s\n"
                "Publication date: %s"
            )
            % (
                bauble.installation_date.strftime(
                    prefs.prefs.get(datetime_format_pref)
                ),
                bauble.release_version,
                bauble.release_date.strftime(
                    prefs.prefs.get(datetime_format_pref)
                ),
            )
        )
        about.run()
        about.destroy()

    @staticmethod
    def on_delete_event(_widget, _event):
        if bauble.task.running():
            msg = _("Would you like to cancel the current tasks?")
            if not utils.yes_no_dialog(msg):
                # stop other handlers from being invoked for this event
                return True
            bauble.task.kill()
            msg = _("Close Ghini?")
            if not utils.yes_no_dialog(msg):
                # don't close
                return True
        return False

    def on_destroy(self, _window):
        active_view = self.get_view()
        if active_view:
            active_view.cancel_threads()
            active_view.prevent_threads = True
        bauble.task.kill()

    def on_resize(self, _widget, _data):
        rect = self.window.get_size()
        prefs.prefs[self.window_geometry_pref] = rect.width, rect.height

    def on_quit(self, _action, _param):
        self.window.destroy()
