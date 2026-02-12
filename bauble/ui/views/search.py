# Copyright 2008-2010 Brett Adams
# Copyright 2015 Mario Frasca <mario@anche.no>.
# Copyright 2021-2026 Ross Demuth <rossdemuth123@gmail.com>
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
SearchView is the default view, it handles search query strings, runs the
search and displays the results.
"""

import logging

logger = logging.getLogger(__name__)

import itertools
import textwrap
import traceback
from collections import UserDict
from collections.abc import Callable
from collections.abc import Generator
from collections.abc import Iterable
from collections.abc import Sequence
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from typing import Any
from typing import Protocol
from typing import Self
from typing import cast

import sqlalchemy.exc as saexc
from gi.repository import Gdk
from gi.repository import Gio
from gi.repository import GLib
from gi.repository import Gtk
from mako.template import Template  # type: ignore [import-untyped]
from pyparsing import ParseException
from sqlalchemy import inspect
from sqlalchemy.orm import object_session
from sqlalchemy.orm.exc import ObjectDeletedError

import bauble
from bauble import db
from bauble import paths
from bauble import pluginmgr
from bauble import prefs
from bauble import search
from bauble import task
from bauble import utils
from bauble.error import BaubleError
from bauble.error import check
from bauble.i18n import _
from bauble.ui.views.base import View
from bauble.ui.views.infobox import INFOBOXPAGE_WIDTH_PREF
from bauble.ui.views.infobox import InfoBox
from bauble.ui.views.notes import DocumentsScroller
from bauble.ui.views.notes import NotesScroller
from bauble.ui.views.pictures import PicturesScroller

_MAINSTR_TMPL = "<b>%s</b>"
_SUBSTR_TMPL = "%s"

PIC_PANE_WIDTH_PREF = "pictures_scroller.page_width"
"""The preferences key for storing the pictures pane width."""

PIC_PANE_PAGE_PREF = "pictures_scroller.selected_page"
"""The preferences key for storing the pictures notebook selected page."""

SEARCH_POLL_SECS_PREF = "bauble.search.poll_secs"
"""Preference key for how often to poll the database in search view"""

SEARCH_CACHE_SIZE_PREF = "bauble.search.cache_size"
"""Preference key for size of search view's has_kids cache"""

SEARCH_REFRESH_PREF = "bauble.search.refresh"
"""Preference key, should search view attempt to refresh from the database
regularly
"""

EXPAND_ON_ACTIVATE_PREF = "bauble.search.expand_on_activate"
"""Preference key, should search view expand the item on double click"""

BOTTOM_NOTEBOOK_PAGE_PREF = "bauble.search.bottom_page"


class ActionCallback[T: db.Domain](Protocol):
    # pylint: disable=too-few-public-methods,undefined-variable
    def __call__(self, objs: Sequence[T], **kwargs: Any) -> bool: ...


class Action:
    # pylint: disable=too-few-public-methods
    # pylint: disable-next=too-many-positional-arguments,too-many-arguments
    def __init__(
        self,
        name: str,
        label: str,
        callback: ActionCallback,
        accelerator: str | None = None,
        multiselect: bool = False,
    ) -> None:
        """SearchView context menu items.

        :param name: name of the action as a string
        :param label: menu label of the action as a string
        :param callback: the function to call when the the action is activated,
            if anything that evaluates to True is returned triggers
            SearchView.update()
        :param accelerator: accelerator to call this action
        :param multiselect: show menu when multiple items are selected
        """
        self.name = name
        self.label = label
        self.callback = callback
        self.accelerator = accelerator
        self.multiselect = multiselect
        self.action = Gio.SimpleAction.new(name, None)
        self.connected = False

    def connect(
        self, handler: Callable[[Any, Any, ActionCallback], None]
    ) -> None:
        if not self.connected:
            self.action.connect("activate", handler, self.callback)
            self.connected = True


@dataclass
class _Node:
    type_: type[db.Domain]
    id_: int
    depth: int
    children: list[Self] = field(default_factory=list)
    expanded: bool = False
    cursor: bool = False
    selected: bool = False

    def __str__(self) -> str:
        state = [str(self.id_)]
        if self.expanded:
            state.append("expanded")

        if self.cursor:
            state.append("cursor")

        if self.selected:
            state.append("selected")

        string = (
            f"{"\t" * self.depth}> {self.type_.__name__} "
            f"({", ".join(state)})"
        )

        for child in self.children:
            string += f"\n{str(child)}"

        return string


class ViewMeta(UserDict):
    """This class shouldn't need to be instantiated directly.  Access the
    meta for the SearchView with the :class:``bauble.view.SearchView``'s
    ``row_meta`` attributes.

    ...note: can access the actual dictionary used to store the contents
    directly via the UserDict `data` attribute. e.g. to use setdefault in
    such a way that doesn't call __getitem__
    """

    class Meta:
        def __init__(self) -> None:
            self.children: (
                Callable[[db.Domain], Sequence[db.Domain]] | None
            ) = None
            self.infobox: InfoBox | None = None
            self.context_menu: Sequence[Action] = []
            self.sorter: Callable = utils.natsort_key
            self.activated_callback: Callable | None = None

        # pylint: disable-next=too-many-arguments,too-many-positional-arguments
        def set(
            self,
            children: Callable[[db.Domain], Sequence[db.Domain]] | None = None,
            infobox: InfoBox | None = None,
            context_menu: Sequence[Action] | None = None,
            sorter: Callable | None = None,
            activated_callback: Callable | None = None,
        ) -> None:
            """Set attributes for the selected meta object.

            :param children: where to find the children for this type, can
                be a callable of the form `children(row)`
            :param infobox: the infobox for this type
            :param context_menu: a dict describing the context menu used
                when the user right clicks on this type
            """
            self.children = children
            self.infobox = infobox

            if context_menu:
                self.context_menu = context_menu

            if sorter:
                self.sorter = sorter

            self.activated_callback = activated_callback

        def get_children(self, obj: db.Domain) -> Sequence[db.Domain]:
            """
            :param obj: get the children from obj according to
                self.children,

            :return: a list or list-like object of any children objects.
            """
            if self.children is None:
                return []
            if callable(self.children):
                return self.children(obj)
            return getattr(obj, self.children)

    def __getitem__(self, item: object) -> Meta:
        if item not in self:  # create on demand
            self[item] = self.Meta()
        return super().__getitem__(item)


@Gtk.Template(filename=str(Path(paths.lib_dir(), "search_view.ui")))
class SearchView(View, Gtk.Box):
    # pylint: disable=too-many-public-methods,too-many-instance-attributes
    """The SearchView is the main view for Ghini.

    Manages the search results returned when search strings are entered into
    the main text entry (found in ui.GUI).

    Should be treated as a singleton/global object, only instantiated once.

    If, for testing, there is a need to instantiate a second instance care has
    to be taken not to leave the global instance in an unusual state, e.g.
    class attributes restored, widgets detached/reattached, etc..
    (``_remove_bottom_pages`` is provided specifically for this use case.  You
    may need to call it before and after tests followed by recalling
    ``_add_bottom_pages`` on the global instance). Also, consider using
    ``mock.patch.object`` on the global instance when mocking is needed.
    """

    __gtype_name__ = "SearchView"

    bottom_notebook = cast(Gtk.Notebook, Gtk.Template.Child())
    results_view = cast(Gtk.TreeView, Gtk.Template.Child())
    info_pane = cast(Gtk.Paned, Gtk.Template.Child())
    pic_pane = cast(Gtk.Paned, Gtk.Template.Child())
    pic_pane_notebook = cast(Gtk.Notebook, Gtk.Template.Child())
    pics_box = cast(Gtk.Paned, Gtk.Template.Child())
    error_box = cast(Gtk.Box, Gtk.Template.Child())
    error_label = cast(Gtk.Label, Gtk.Template.Child())

    row_meta = ViewMeta()

    bottom_pages: set[tuple[Gtk.Widget, Gtk.Label]] = set()
    """Widegts added here will be appended to the bottom_notebook and the label
    used for its notebook tab.
    Widgets should implement an ``update`` method that can be passed the
    currently selected row.
    """

    pic_pane_notebook_pages: set[tuple[Gtk.Widget, int, str]] = set()
    """Widgets added here will be added to the pic_pane_notebook.
    Items are a tuple - (widget, tab position, tab label)
    """

    context_menu_callbacks: set[
        Callable[[list[db.Domain]], Gio.Menu | None]
    ] = set()
    """Callbacks for constructing context menus for selected items.
    Callbacks should recieve a single argument containing the selected items
    and return a single menu section of type Gio.Menu
    """

    cursor_changed_callbacks: set[Callable[[list[db.Domain]], None]] = set()
    """Callbacks called each time the cursor changes"""

    populate_callbacks: set[Callable[[Sequence[db.Domain]], None]] = set()
    """Callbacks called each time SearchView populates"""

    extra_signals: set[tuple[str, str, Callable]] = set()
    """Add extra signals here to be setup at init.
    Items are a tuple - (widget name, signal name, handler)
    """

    def __init__(self) -> None:
        logger.debug("SearchView::__init__")

        super().__init__()

        column = cast(Gtk.TreeViewColumn, self.results_view.get_column(0))
        renderer = cast(Gtk.CellRendererText, column.get_cells()[0])
        column.set_cell_data_func(renderer, self.cell_data_func)

        self.selection: Gtk.TreeSelection = self.results_view.get_selection()
        self._selection_changed_sigid = self.selection.connect(
            "changed", self.on_selection_changed
        )

        self.add_pic_pane_notebook_pages()

        self.pictures_scroller = PicturesScroller()
        self.pictures_scroller.connect(
            "picture-selected", self.select_from_picture
        )
        self.pics_box.add(self.pictures_scroller)
        self.pics_box.show_all()
        self.restore_position: int = prefs.prefs.get(PIC_PANE_WIDTH_PREF, -1)
        self.pic_pane.set_position(self.restore_position)
        self.pic_pane_notebook.set_current_page(
            prefs.prefs.get(PIC_PANE_PAGE_PREF, 0)
        )
        self.infobox: InfoBox | None = None
        self.info_pane.connect("destroy", self.on_destroy)
        self.history_action: Gio.SimpleAction | None = None

        # keep all the search results in the same session, this should
        # be cleared when we do a new search
        self.session = db.Session()

        self._add_bottom_pages(prefs.prefs.get(BOTTOM_NOTEBOOK_PAGE_PREF, 0))

        self.actions: set[str] = set()
        self.context_menu_model = Gio.Menu()

        poll_secs = prefs.prefs.get(SEARCH_POLL_SECS_PREF)
        if poll_secs:
            self.has_kids.set_secs(poll_secs)  # pylint: disable=no-member

        cache_size = prefs.prefs.get(SEARCH_CACHE_SIZE_PREF)
        if cache_size:
            self.has_kids.set_size(cache_size)  # pylint: disable=no-member

        self.refresh = prefs.prefs.get(SEARCH_REFRESH_PREF, True)
        self.btn_1_timer = (0, 0, 0)

        for widget_name, signal, handler in self.extra_signals:
            self.connect_signal(widget_name, signal, handler)

        self.last_search: str = ""
        self.no_result = True

    def connect_signal(
        self, widget_name: str, signal: str, handler: Callable
    ) -> None:
        widget = getattr(self, widget_name)
        widget.connect(signal, handler)

    def _add_bottom_pages(self, selected_page: int = 0) -> None:
        for page, label in sorted(
            self.bottom_pages, key=lambda i: i[1].get_text()
        ):
            self.bottom_notebook.append_page(page, label)

        self.bottom_notebook.set_current_page(selected_page)

    def _remove_bottom_pages(self) -> None:
        for page, _label in sorted(
            self.bottom_pages, key=lambda i: i[1].get_text()
        ):
            if parent := cast(Gtk.Container, page.get_parent()):
                parent.remove(page)

    def add_pic_pane_notebook_pages(self) -> None:
        for page in self.pic_pane_notebook_pages:
            self.add_page_to_pic_pane_notebook(*page)

    def add_page_to_pic_pane_notebook(
        self, widget: Gtk.Widget, position: int, label: str
    ) -> None:
        """Add a page to the pic_pane notebook.

        :param widget: the Gtk.Widget to place in the page
        :param position: the tabs position in the notebook
        :param label: the text to place in the tabs label
        """
        if not widget.get_parent():  # for testing don't keep attaching
            self.pic_pane_notebook.append_page(widget, Gtk.Label(label=label))
            self.pic_pane_notebook.reorder_child(widget, position)
            self.pic_pane_notebook.show_all()

    def update_bottom_notebook(self, selected_values: list[db.Domain]) -> None:
        """Update the bottom_notebook from the currently selected row.

        Only one selected value is allowed, anything else and the bottom
        notebook is hidden.

        Calls ``update`` on each page.
        """
        # Only one should be selected
        if len(selected_values or []) != 1:
            self.bottom_notebook.hide()
            return

        row = selected_values[0]

        for page in self.bottom_notebook.get_children():
            if hasattr(page, "update"):
                page.update(row)

    def update_infobox(self, selected_values: list[db.Domain]) -> None:
        """Sets the infobox according to the currently selected row.

        no infobox is shown if nothing is selected
        """
        # start of update_infobox
        # NOTE log used in tests
        logger.debug("SearchView::update_infobox")
        if not selected_values or not selected_values[0]:
            self.set_infobox_from_row(None)
            return

        if object_session(selected_values[0]) is None:
            logger.debug("cannot populate info box from detached object")
            return

        sensitive = len(selected_values) == 1

        try:
            # send an object (e.g. a Plant instance)
            self.set_infobox_from_row(selected_values[0], sensitive)
        except Exception as e:  # pylint: disable=broad-except
            # if an error occurrs, log it and empty infobox.
            logger.debug("%s(%s)", type(e).__name__, e)
            logger.debug(traceback.format_exc())
            logger.debug(selected_values)
            self.set_infobox_from_row(None)
            raise

    def _set_info_pane_position_from_pref(self) -> None:
        # set width from pref once per session.
        # for tests when no gui
        width = 100
        if bauble.gui:
            size = cast(Gdk.Rectangle, bauble.gui.window.get_size())
            width = size.width
        info_width = prefs.prefs.get(INFOBOXPAGE_WIDTH_PREF, 300)
        pane_pos = width - info_width - 1
        logger.debug("setting info_pane position to %s", pane_pos)
        self.info_pane.set_position(pane_pos)

    def set_infobox_from_row(
        self, row: db.Domain | None, sensitive: bool = True
    ) -> None:
        """Sets up an appropriate info_box for the current row."""

        logger.debug("set_infobox_from_row: %s --  %s", row, repr(row))
        # remove the current infobox if there is one
        if infobox := self.info_pane.get_child2():
            self.info_pane.remove(infobox)

        if row is None:
            return

        # set width from pref once per session.
        if self.infobox is None:
            self._set_info_pane_position_from_pref()

        selected_type = type(row)
        self.infobox = self.row_meta[selected_type].infobox
        logger.debug("infobox now %s", self.infobox)

        # update the infobox and put it in the pane
        if self.infobox is not None:
            try:
                self.infobox.update(row)
                self.info_pane.pack2(self.infobox, resize=False, shrink=True)
                self.infobox.set_sensitive(sensitive)
                self.info_pane.show_all()
            except Exception:  # pylint: disable=broad-exception-caught
                logger.warning(traceback.format_exc())
                raise

    def get_selected_values(self) -> list[db.Domain]:
        """Get the values in all the selected rows."""
        model, rows = self.selection.get_selected_rows()
        if model is None or rows is None:
            return []
        return [model[row][0] for row in rows]

    def on_selection_changed(self, _tree_selection) -> None:
        """Update the infobox and bottom notebooks. Switch context_menus,
        actions and accelerators depending on the type of the rows selected.
        """
        # NOTE log used in tests
        logger.debug("SearchView::on_selection_changed")
        # grab values once
        selected_values = self.get_selected_values()
        # update all forward-looking info boxes
        self.update_infobox(selected_values)
        # update all backward-looking info boxes
        self.update_bottom_notebook(selected_values)

        self.pictures_scroller.update(selected_values)

        self.update_context_menus(selected_values)

        for callback in self.cursor_changed_callbacks:
            callback(selected_values)

    def on_action_activate(
        self,
        _action,
        _param,
        callback: ActionCallback,
    ) -> None:
        result = False
        try:
            values = self.get_selected_values()
            result = callback(values)
        except Exception as e:  # pylint: disable=broad-except
            msg = utils.xml_safe(str(e))
            trace = utils.xml_safe(traceback.format_exc())
            utils.message_details_dialog(msg, trace, Gtk.MessageType.ERROR)
            logger.warning(traceback.format_exc())
        if result:
            # can lead to update called twice but ensures its called when not
            # an editor.  Editors will also call update from insert menu.
            self.update()

    def _add_meta_actions_to_context_menu(
        self, selected_values: list[db.Domain]
    ) -> None:

        selected_types = set(map(type, selected_values))

        # avoid accessing self.row_meta[None] as this will create a new
        # ViewMeta entry for None
        context_menu_actions: Sequence[Action] = []
        if len(selected_types) == 1:
            selected_type = selected_types.pop()
            context_menu_actions = self.row_meta[selected_type].context_menu

        current_actions = set()

        for action in context_menu_actions:
            current_actions.add(action.name)

            if bauble.gui and not bauble.gui.lookup_action(action.name):
                self.actions.add(action.name)
                bauble.gui.window.add_action(action.action)

                action.connect(self.on_action_activate)
                # pylint: disable-next=no-value-for-parameter
                app = Gio.Application.get_default()
                if app is not None and hasattr(app, "set_accels_for_action"):
                    app.set_accels_for_action(
                        f"win.{action.name}", [action.accelerator]
                    )

            menu_item = Gio.MenuItem.new(action.label, f"win.{action.name}")
            self.context_menu_model.append_item(menu_item)

            if (len(selected_values) > 1 and action.multiselect) or len(
                selected_values
            ) == 1:
                action.action.set_enabled(True)
            else:
                action.action.set_enabled(False)

        for action_name in self.actions.copy():
            if action_name not in current_actions:
                if bauble.gui:
                    bauble.gui.remove_action(action_name)
                self.actions.remove(action_name)

    def _add_copy_selection_to_context_menu(self) -> None:
        copy_selection_action_name = "copy_selection_strings"

        if bauble.gui and not bauble.gui.lookup_action(
            copy_selection_action_name
        ):
            bauble.gui.add_action(
                copy_selection_action_name, self.on_copy_selection
            )

        copy_selection_menu_item = Gio.MenuItem.new(
            _("Copy Selection"), f"win.{copy_selection_action_name}"
        )
        self.context_menu_model.append_item(copy_selection_menu_item)

    def _add_get_history_to_context_menu(
        self, selected_values: list[db.Domain]
    ) -> None:

        get_history_action_name = "get_history"

        if bauble.gui:
            if not bauble.gui.lookup_action(get_history_action_name):
                self.history_action = bauble.gui.add_action(
                    get_history_action_name, self.on_get_history
                )
            if self.history_action:
                if len(selected_values) == 1:
                    self.history_action.set_enabled(True)
                else:
                    self.history_action.set_enabled(False)

        get_history_menu_item = Gio.MenuItem.new(
            _("Show History"), f"win.{get_history_action_name}"
        )
        self.context_menu_model.append_item(get_history_menu_item)

    def update_context_menus(self, selected_values: list[db.Domain]) -> None:
        """Update the context menu dependant on selected values."""

        self.context_menu_model.remove_all()

        if not selected_values:
            return

        self._add_meta_actions_to_context_menu(selected_values)
        self._add_copy_selection_to_context_menu()
        self._add_get_history_to_context_menu(selected_values)

        if bauble.gui:
            edit_context_menu = bauble.gui.edit_context_menu
            edit_context_menu.remove_all()
            edit_context_menu.insert_section(0, None, self.context_menu_model)

    def on_copy_selection(self, _action, _param) -> None:
        selected_values = self.get_selected_values()

        if not selected_values:
            return

        out = []

        try:
            for value in selected_values:
                domain = type(value).__name__.lower()
                pref_key = f"copy_templates.{domain}"
                template_str = prefs.prefs.get(
                    pref_key, "${value}, ${type(value).__name__}"
                )
                template = Template(template_str)
                out.append(template.render(value=value))
        except Exception as e:  # pylint: disable=broad-except
            logger.debug("%s(%s)", type(e).__name__, e)
            msg = _(
                "Copy error.  Check your copy_templates in Preferences?"
                "\n\n%s"
            ) % utils.xml_safe(str(e))
            utils.message_details_dialog(
                msg, traceback.format_exc(), Gtk.MessageType.ERROR
            )

        string = "\n".join(out)
        if bauble.gui:
            bauble.gui.get_display_clipboard().set_text(string, -1)

    def on_get_history(self, _action, _param) -> None:
        selected_values = self.get_selected_values()
        if not selected_values:
            return

        selected = selected_values[0]
        # include timestamp because IDs can get reused in some situations
        search_str = (
            f":history = table_name = {selected.__tablename__} "
            f"and table_id = {selected.id} "
            f'and timestamp >= "{selected._created}"'
        )

        if bauble.gui:
            bauble.gui.send_command(search_str)

    def _reset(self) -> None:
        # stop whatever it might still be doing
        self.cancel_threads()
        self.session.close()
        # clear the caches to avoid stale items.
        self.has_kids.clear_cache()  # pylint: disable=no-member
        self.count_kids.clear_cache()  # pylint: disable=no-member
        self.get_markup_pair.clear_cache()  # pylint: disable=no-member

        self.session = db.Session()
        # clear last result
        for callback in self.populate_callbacks:
            callback([])

        # avoid triggering on_selection_changed
        self.selection.handler_block(self._selection_changed_sigid)
        utils.clear_model(self.results_view)
        self.selection.handler_unblock(
            handler_id=self._selection_changed_sigid
        )

    def search(self, text: str) -> None:
        """search the database using :param text:"""

        logger.debug("SearchView.search(%s)", repr(text))
        self.last_search = text
        self.no_result = False

        self._reset()

        error_msg = None
        error_details_msg = None
        results = []

        try:
            results = search.search(text, self.session)
        except ParseException as err:
            error_msg = _("Error in search string at column %s") % err.column
            error_details_msg = err.explain()
        except Exception as e:  # pylint: disable=broad-except
            logger.debug(traceback.format_exc())
            error_msg = _("** Error: %s") % utils.xml_safe(e)
            error_details_msg = utils.xml_safe(traceback.format_exc())

        if error_msg and bauble.gui:
            self.last_search = ""
            bauble.gui.show_error_box(error_msg, error_details_msg)
            self.show_error(True)
            self.update_statusbar([])
            self.on_selection_changed(None)
            return

        self.populate(text, results)

    def populate(self, text: str, results: Sequence[db.Domain]) -> None:

        if len(results) > 30000:
            msg = _(
                "This query returned %s results.  It may take a "
                "while to display all the data. Are you sure you "
                "want to continue?"
            ) % len(results)
            if not utils.yes_no_dialog(msg):
                return

        # no result (not error)
        if len(results) == 0:
            self.show_error(True, text)
            self.update_statusbar(results)
        else:
            self.show_error(False)
            self.error_box.set_visible(False)
            self.populate_results(results)
            self.update_statusbar(results)
            # pylint: disable=no-value-for-parameter
            self.results_view.set_cursor(Gtk.TreePath.new_first())
            self.results_view.scroll_to_cell(
                Gtk.TreePath.new_first(), None, True, 0.5, 0.0
            )

    def show_error(self, active: bool, search_text: str = "") -> None:
        self.no_result = active

        if len(search_text) > 200:
            search_text = "\n".join(textwrap.wrap(search_text, 150))

        if search_text:
            msg = (
                _('Could not find anything for search: \n\n"%s"') % search_text
            )

            if prefs.prefs.get(prefs.exclude_inactive_pref):
                msg += "\n\n\n"
                msg += _(
                    "CONSIDER: uncheck 'Exclude Inactive' in options menu"
                )

            self.error_label.set_text(msg)
        else:
            self.error_label.set_text("")

        if active:
            self.info_pane.set_visible(False)
            self.error_box.set_visible(True)
        else:
            self.info_pane.set_visible(True)
            self.error_box.set_visible(False)

    @staticmethod
    def update_statusbar(
        results: Sequence[db.Domain],
        *,
        statusbar: Gtk.Statusbar | None = None,
    ) -> None:

        if statusbar is None:
            if bauble.gui:
                statusbar = bauble.gui.widgets.statusbar
            else:
                return

        sbcontext_id = statusbar.get_context_id("searchview.nresults")
        statusbar.pop(sbcontext_id)

        if len(results) == 0 or not isinstance(results[0], db.Domain):
            return

        if len(set(item.__class__ for item in results)) == 1:
            class_ = results[0].__class__
            statusbar.pop(sbcontext_id)
            statusbar.push(
                sbcontext_id,
                _("TOP LEVEL COUNT: %s")
                % class_.top_level_count(
                    [i.id for i in results],
                    prefs.prefs.get(prefs.exclude_inactive_pref, False),
                ),
            )
            return
        statusbar.push(
            sbcontext_id,
            _("size of non homogeneous result: %s") % len(results),
        )

    def _get_expanded_tree(
        self,
        expanded_rows: list[Gtk.TreePath],
        cursor_path: Gtk.TreePath,
        selected_paths: list[Gtk.TreePath],
    ) -> _Node:
        """Creates a tree structure representing the nodes that are currently
        expanded, selected or the current cursor path.

        Maps the paths to their objects type and id, for use where the paths
        can not be relied upon (i.e. a rerun search has potentially removed
        or added objects).
        """

        all_rows = expanded_rows.copy()

        for path in selected_paths:
            if path in expanded_rows:
                continue
            all_rows.append(path)

        all_rows.sort(key=str)

        model = cast(Gtk.ListStore, self.results_view.get_model())
        # for the sake of type annotations just use Domain for root node
        root = _Node(db.Domain, 0, 0)

        nodes = [root]

        for path in all_rows:
            depth = path.get_depth()
            obj = model[path][0]

            node = _Node(
                type(obj),
                obj.id,
                depth,
                expanded=path in expanded_rows,
                cursor=path == cursor_path,
                selected=path in selected_paths,
            )

            # keep track of where we are in the tree.
            for __ in range(len(nodes)):
                last = nodes[-1]
                if depth > last.depth:
                    nodes.append(node)
                    last.children.append(node)
                    break
                nodes.pop()

        return root

    def expand_from_tree(
        self,
        tree_root: _Node,
        selected: list[Gtk.TreePath] | None = None,
    ) -> None:
        """Expand rows, set the cursor and selects paths as described by the
        provided tree of ``_Node``s.
        """

        model = self.results_view.get_model()

        if model is None:
            # used in test
            logger.debug("no results_view model - bailing")
            return

        if selected is None:
            # set selected on first call, reuse in further recursions
            selected = []

        def expand(
            model: Gtk.ListStore,
            path: Gtk.TreePath,
            itr: Gtk.TreeIter,
            node: _Node,
            selected: list[Gtk.TreePath],
        ) -> bool:
            obj = model[itr][0]

            if isinstance(obj, node.type_) and obj.id == node.id_:
                if node.expanded:
                    self.on_test_expand_row(self.results_view, itr, path)
                    self.results_view.expand_to_path(path)
                    self.expand_from_tree(node, selected)

                if node.cursor:
                    self.results_view.set_cursor(path)

                if node.selected:
                    selected.append(path)

                return True

            return False

        for node in tree_root.children:

            model.foreach(expand, node, selected)

        if tree_root.depth == 0:
            # run after all recursions have returned
            for path in selected:
                self.selection.select_path(path)

        return

    def rerun_last_search(self) -> None:
        """Rerun the last search and restore view to previous position.

        Intended for use after toggling exclude_inactive where the results may
        differ.
        """
        if self.last_search:
            cursor_path, _column = self.results_view.get_cursor()
            expanded_rows = self.get_expanded_rows()
            _model, selected_paths = self.selection.get_selected_rows()

            # don't expand when too many or no result
            if (
                self.no_result is False
                and len(selected_paths) < 20
                and len(expanded_rows) < 20
            ):
                expanded_tree_root = self._get_expanded_tree(
                    expanded_rows,
                    cursor_path,
                    selected_paths,
                )

                self.search(self.last_search)

                self.expand_from_tree(expanded_tree_root)
            else:
                self.search(self.last_search)

    def refresh_statusbar(self) -> None:
        model = self.results_view.get_model()
        if model:
            objs = [i[0] for i in model]
            self.update_statusbar(objs)

    @staticmethod
    def remove_children(model: Gtk.TreeStore, parent: Gtk.TreeIter) -> None:
        """Remove all children of some parent in the model.

        Reverse iterate through them so you don't invalidate the iter.
        """
        logger.debug("remove_children called")
        while model.iter_has_child(parent):
            nkids = model.iter_n_children(parent)
            child = model.iter_nth_child(parent, nkids - 1)
            if child:
                model.remove(child)

    @Gtk.Template.Callback()
    def on_test_expand_row(
        self,
        treeview: Gtk.TreeView,
        treeiter: Gtk.TreeIter,
        path: Gtk.TreePath,
    ) -> bool:
        """Look up the table type of the selected row and if it has any
        children then add them to the row.

        Returns False to allow expansion, True to reject.
        """
        model = cast(Gtk.TreeStore, treeview.get_model())
        obj = model.get_value(treeiter, 0)
        treeview.collapse_row(path)
        self.remove_children(model, treeiter)

        def sorter(obj) -> tuple[str, Any]:
            cls = type(obj)
            row_sorter = self.row_meta[cls].sorter
            return cls.__name__, row_sorter(obj)

        try:
            kids = self.row_meta[type(obj)].get_children(obj)

            if len(kids) == 0:
                return True

        except saexc.InvalidRequestError as e:
            logger.debug("on_test_expand_row: %s:%s", type(e).__name__, e)

            # model no longer in database, remove
            for found in utils.search_tree_model(model, obj):
                model.remove(found)

            return True
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.debug("on_test_expand_row: %s:%s", type(e).__name__, e)
            logger.debug(traceback.format_exc())
            return True

        self.append_children(model, treeiter, sorted(kids, key=sorter))
        return False

    def populate_results(self, results: Sequence[db.Domain]) -> None:
        """Adds results to the search view."""
        # don't bother with a task if the results are small,
        # this keeps the screen from flickering when the main
        # window is set to a busy state
        if len(results) > 3000:
            task.queue(self._populate_worker(results))
        else:
            populate_task = self._populate_worker(results)
            while True:
                try:
                    next(populate_task)
                except StopIteration:
                    break

        for callback in self.populate_callbacks:
            callback(results)

    def _populate_worker(
        self, results: Sequence[db.Domain]
    ) -> Generator[None]:
        """Generator function for adding the search results to the
        model.

        This method is usually called by ``self.populate_results()``
        """
        len_results = len(results)
        model = Gtk.TreeStore(object)
        # remove sorting function (i.e. has_default_sort_func returns false)
        model.set_sort_column_id(
            Gtk.TREE_SORTABLE_UNSORTED_SORT_COLUMN_ID, Gtk.SortType.ASCENDING
        )
        logger.debug("_populate_worker clear model")
        utils.clear_model(self.results_view)

        five_percent = int(len_results / 20) or 200
        steps_so_far = 0

        # iterate over slice of size "steps", yield every 5%
        added = set()
        for obj in self._group_sort_results(results):

            if steps_so_far % five_percent == 0:
                percent = float(steps_so_far) / float(len_results)
                if 0 < percent < 1.0:
                    bauble.gui.progressbar.set_fraction(percent)
                yield

            if obj in added:  # only add unique object
                continue

            added.add(obj)

            parent = model.prepend(None, [obj])
            steps_so_far += 1

            if (
                not self.refresh
                and self.row_meta[type(obj)].children is not None
            ):
                model.prepend(parent, ["-"])

        # avoid triggering on_selection_changed
        self.selection.handler_block(self._selection_changed_sigid)
        self.results_view.set_model(model)
        self.selection.handler_unblock(
            handler_id=self._selection_changed_sigid
        )

    def _group_sort_results(
        self, results: Sequence[db.Domain]
    ) -> Iterable[db.Domain]:
        groups = []

        # sort by type so that groupby works properly
        results_sorted = sorted(results, key=lambda x: str(type(x)))

        for cls, group in itertools.groupby(results_sorted, key=type):
            sorter = self.row_meta[cls].sorter
            # return groups by type and sort each of the groups
            groups.append(sorted(group, key=sorter, reverse=True))

        # sort the groups by type so we more or less always get the
        # results by type in the same order
        groups = sorted(groups, key=lambda x: str(type(x[0])), reverse=True)
        return itertools.chain(*groups)

    def append_children(
        self,
        model: Gtk.TreeStore,
        parent: Gtk.TreeIter,
        kids: Sequence[db.Domain],
    ) -> None:
        """Append object to a parent iter in the model.

        :param model: the model to append to
        :param parent:  the parent Gtk.TreeIter
        :param kids: a list of kids to append
        """
        check(parent is not None, "append_children(): need a parent")
        for kid in kids:

            itr = model.append(parent, [kid])
            if self.refresh:
                if (
                    self.row_meta[type(kid)].children is not None
                    and kid.has_children()
                ):
                    model.append(itr, ["-"])
            else:
                if self.row_meta[type(kid)].children is not None:
                    model.append(itr, ["-"])

    def remove_row(self, obj: db.Domain) -> None:
        """Remove the row containing ``obj`` from the results_view."""
        # NOTE used in testing...
        logger.info("remove_row called")

        model = cast(Gtk.TreeStore, self.results_view.get_model())

        for found in utils.search_tree_model(model, obj):
            model.remove(found)

    @utils.timed_cache()
    def has_kids(self, obj: db.Domain) -> bool:
        """Expire and check for children

        Results are cached to avoid expiring too regularly.
        """
        # expire so that any external updates are picked up.
        # (e.g. another user has deleted while we are also using it.)
        self.session.expire(obj)
        return obj.has_children()

    @staticmethod
    @utils.timed_cache(size=20, secs=0.2)
    def count_kids(obj: db.Domain) -> int:
        """Get the count of children.

        Minimally cached to avoid repeated database calls for same value.
        """
        return obj.count_children()

    @staticmethod
    @utils.timed_cache(size=200, secs=0.2)
    def get_markup_pair(obj: db.Domain) -> tuple[str, str]:
        """Get the markup pair.

        Minimally cached to avoid repeated database calls for same value.
        """
        return obj.search_view_markup_pair()

    def cell_data_func(
        self,
        _col,
        cell: Gtk.CellRendererText,
        model: Gtk.TreeModel,
        treeiter: Gtk.TreeIter,
        _data,
    ) -> None:
        model = cast(Gtk.TreeStore, model)

        obj = model[treeiter][0]

        try:
            if self.refresh:
                row_meta = self.row_meta[type(obj)]
                if row_meta.children is not None and self.has_kids(obj):
                    path = model.get_path(treeiter)
                    # check if any items added/removed
                    if self.results_view.row_expanded(path):
                        if model.iter_n_children(treeiter) != self.count_kids(
                            obj
                        ):
                            logger.debug("cell_data_func: refreshing children")
                            self.on_test_expand_row(
                                self.results_view, treeiter, path
                            )
                            self.results_view.expand_to_path(path)
                    elif not model.iter_has_child(treeiter):
                        model.prepend(treeiter, ["-"])
                else:
                    self.remove_children(model, treeiter)

            main, substr = self.get_markup_pair(obj)

            cell.set_property(
                "markup",
                f"{_MAINSTR_TMPL % main}\n{_SUBSTR_TMPL % substr}",
            )

        except (saexc.InvalidRequestError, ObjectDeletedError, TypeError) as e:
            logger.debug("cell_data_func: (%s)%s", type(e).__name__, e)

            GLib.idle_add(self.remove_row, obj)

        except Exception as e:
            logger.error("cell_data_func: %s(%s)", type(e).__name__, e)
            raise

    def get_expanded_rows(self) -> list[Gtk.TreePath]:
        """Get the TreePaths to all the rows in the model that are expanded."""
        expanded_rows = []

        self.results_view.map_expanded_rows(
            lambda view, path: expanded_rows.append(path)
        )

        return expanded_rows

    def expand_to_all_rows(self, expanded_rows: list[Gtk.TreePath]) -> None:
        """Expand results_view to all supplied paths."""
        for path in expanded_rows:
            self.results_view.expand_to_path(path)

    @Gtk.Template.Callback()
    def on_view_button_press(
        self, view: Gtk.TreeView, event: Gdk.EventButton
    ) -> bool:
        """Ignore the mouse right-click event.

        This makes sure that we don't remove the multiple selection on a
        right click.
        """
        if event.button == 1:
            self.btn_1_timer = (event.time, int(event.x), int(event.y))
            logger.debug("button 1 timer: %s", self.btn_1_timer)

        logger.debug(
            "button press event: %s type: %s button: %s",
            event,
            event.type,
            event.button,
        )
        if event.button == 3:
            pos = view.get_path_at_pos(int(event.x), int(event.y))
            # NOTE used in test...
            logger.debug("view button 3 press, pos = %s", pos)
            # occasionally pos will return None and can't be unpacked
            if not pos:
                return False

            path, _column, _x, _y = pos

            if path is None or not view.get_selection().path_is_selected(path):
                return False
            # emulate 'cursor-changed' signal
            self.on_selection_changed(None)
            return True
        return False

    @Gtk.Template.Callback()
    def on_view_button_release(
        self, view: Gtk.TreeView, event: Gdk.EventButton
    ) -> bool:
        """right-mouse-button release.

        Popup a context menu on the selected row.
        """
        logger.debug(
            "button release event: %s type: %s button: %s",
            event,
            event.type,
            event.button,
        )
        logger.debug("button 1 timer: %s", self.btn_1_timer)

        # imitate right button on long (> 1 sec) press - targets tablet use
        if (
            event.button == 1
            and event.time - self.btn_1_timer[0] > 1000
            and self.btn_1_timer[1] == int(event.x)
            and self.btn_1_timer[2] == int(event.y)
        ):
            event.button = 3

        # if not right click - bail (but allow propagating the event further)
        if event.button != 3:
            return False

        selected = self.get_selected_values()
        if not selected:
            return True

        menu_model = Gio.Menu()
        menu_model.insert_section(0, None, self.context_menu_model)

        for callback in self.context_menu_callbacks:
            section = callback(selected)
            if section:
                menu_model.append_section(None, section)

        menu = Gtk.Menu.new_from_model(menu_model)
        menu.attach_to_widget(view)

        menu.popup_at_pointer(event)
        return True

    def remove_non_persistent_results_view_roots(self) -> None:
        """Removes any tree roots that are no longer persistent (deleted)."""

        model = self.results_view.get_model()

        if not isinstance(model, Gtk.TreeStore):
            # used in test
            logger.warning("results_view is not Treestore")
            return

        for row in model:
            state = inspect(row[0])

            if not state.persistent:
                model.remove(row.iter)

    def update(self, *_args) -> None:
        """Expire all the children in the model, collapse everything, reexpand
        the rows to the previous state where possible.

        Infoboxes are updated in on_selection_changed which this should trigger
        """
        # used in tests
        logger.debug("SearchView::update")

        # remove root nodes that have been deleted first. Nodes on the branches
        # are dealt with later by collapsing and re-expanding.
        self.remove_non_persistent_results_view_roots()

        model, tree_paths = self.selection.get_selected_rows()

        cursor_path, _column = self.results_view.get_cursor()

        refs = []
        for tree_path in tree_paths:
            refs.append(Gtk.TreeRowReference(model, tree_path))

        self.session.expire_all()
        self.has_kids.clear_cache()  # pylint: disable=no-member

        expanded_rows = self.get_expanded_rows()

        # avoid triggering on_selection_changed (happens later)
        self.selection.handler_block(self._selection_changed_sigid)
        self.results_view.collapse_all()
        self.selection.handler_unblock(
            handler_id=self._selection_changed_sigid
        )

        # expand_to_all_rows will invalidate the ref so get the path first
        tree_paths = []
        for ref in refs:
            if ref.valid():
                path = ref.get_path()
                if path:
                    tree_paths.append(path)

        self.expand_to_all_rows(expanded_rows)

        if cursor_path:
            self.results_view.set_cursor(cursor_path)

        if tree_paths:
            for path in tree_paths:
                self.selection.select_path(path)

    @Gtk.Template.Callback()
    def on_view_row_activated(
        self,
        view: Gtk.TreeView,
        path: Gtk.TreePath,
        column: Gtk.TreeViewColumn,
    ) -> None:
        """Open the activation_callback on row activation or expand the row.

        To make expanding the row the default set EXPAND_ON_ACTIVATE_PREF.
        """
        logger.debug(
            "SearchView::on_view_row_activated %s %s %s", view, path, column
        )
        if prefs.prefs.get(EXPAND_ON_ACTIVATE_PREF):
            view.expand_row(path, False)
            return

        selected = self.get_selected_values()
        if not selected:
            return

        call_back = self.row_meta[type(selected[0])].activated_callback
        if call_back:
            call_back(selected)

    def select_from_picture(
        self, _pic_scroller: PicturesScroller, picture: db.Picture
    ) -> None:
        """Select the owner of the picture in the SearchView,

        If the object is already the one selected check if it has a child that
        owns the picture and if so select the child instead.
        """
        logger.debug("selecting object %s", picture.owner)
        model = self.results_view.get_model()

        if not model:
            logger.debug("no model")
            return

        selected = self.get_selected_values()

        if selected == [picture.owner]:
            logger.debug("already selected")
            return

        if selected is not None and picture.owner in selected:
            # make sure we select the object if multiple selected
            select_in_search_results(picture.owner)
            logger.debug("reducing to selected")
            return

        for obj in selected:
            if picture in obj.pictures:
                self._select_child_from_picture(picture, obj, model)

    def _select_child_from_picture(
        self,
        picture: db.Picture,
        obj: db.Domain,
        model: Gtk.TreeModel,
    ) -> None:
        logger.debug("object = %s(%s)", type(obj).__name__, obj)
        kids = self.row_meta[type(obj)].get_children(obj)
        for kid in kids:

            if picture in kid.pictures:
                itr = utils.search_tree_model(model, obj)[0]
                path = model.get_path(itr)
                # expand (on_test_expand_row needed for test)
                self.on_test_expand_row(self.results_view, itr, path)
                self.results_view.expand_to_path(path)
                if kid is picture.owner:
                    itr = select_in_search_results(kid)
                    path = model.get_path(itr)
                    self.results_view.scroll_to_cell(
                        path, None, True, 0.5, 0.0
                    )
                else:
                    # traverse to source
                    self._select_child_from_picture(picture, kid, model)

    def on_destroy(self, _info_pane) -> None:
        """Save bottom_notebook page and pic_pane size and page."""

        width = self.pic_pane.get_position()
        logger.debug("setting PIC_PANE_WIDTH_PREF to %s", width)
        prefs.prefs[PIC_PANE_WIDTH_PREF] = width

        selected = self.pic_pane_notebook.get_current_page()
        logger.debug("setting PIC_PANE_PAGE_PREF to %s", selected)
        prefs.prefs[PIC_PANE_PAGE_PREF] = selected

        bottom_page_num = self.bottom_notebook.get_current_page()
        prefs.prefs[BOTTOM_NOTEBOOK_PAGE_PREF] = bottom_page_num
        self._remove_bottom_pages()


SearchView.bottom_pages.add((NotesScroller(), NotesScroller.label))
SearchView.bottom_pages.add((DocumentsScroller(), DocumentsScroller.label))


class DefaultCommandHandler(pluginmgr.CommandHandler):
    command = (None, "SQL")
    view: SearchView | None = None

    @classmethod
    def get_view(cls) -> SearchView:
        if cls.view is None:
            cls.view = SearchView()
        return cls.view

    def __call__(self, cmd: str | None, arg: str | None) -> None:

        if cmd:
            arg = f"{cmd}:{arg or ''}"

        self.get_view().search(arg or "")


pluginmgr.register_command(DefaultCommandHandler)


def get_search_view() -> SearchView:
    """A convenience function that, regardless of the current view, returns the
    global SearchView instance.
    """
    return DefaultCommandHandler.get_view()


def get_search_view_selected() -> list[db.Domain] | None:
    """If SearchView is the current view return the selected objects."""
    selected: list[db.Domain] | None = None
    if bauble.gui and isinstance(view := bauble.gui.get_view(), SearchView):
        selected = view.get_selected_values()
    return selected


def select_in_search_results(obj, expand_current_first=False) -> Gtk.TreeIter:
    """Search the tree model for obj if it exists then select it if not
    then add it and select it.

    :param obj: the object the select
    :param expand_current_first: if True and the current selection has
        children then expand it first before searching/adding obj (intended for
        use in infoboxes where the current selection is known)
    :return: a Gtk.TreeIter to the selected row
    """
    check(obj is not None, "select_in_search_results: arg is None")
    view = bauble.gui.get_view()

    if not isinstance(view, SearchView):
        logger.warning("current view is not SearchView")
        raise BaubleError(
            "select_in_search_results called when current view is not "
            "SearchView."
        )

    if expand_current_first:
        selected = view.get_selected_values()
        if (
            selected
            and len(selected) == 1
            and view.row_meta[type(selected[0])].children is not None
        ):
            model = view.results_view.get_model()
            found = utils.search_tree_model(model, selected[0])
            if found and model:
                path = model.get_path(found[0])
                view.on_test_expand_row(view.results_view, found[0], path)
                view.results_view.expand_to_path(path)

    logger.debug(
        "select_in_search_results %s is in session %s",
        obj,
        obj in view.session,
    )
    model = view.results_view.get_model()

    if not isinstance(model, Gtk.TreeStore):
        logger.warning("results_view is not Treestore")
        raise BaubleError(
            "select_in_search_results called when results_view is None."
        )

    found = utils.search_tree_model(model, obj)
    row_iter = None

    if len(found) > 0:
        row_iter = found[0]
    else:
        row_iter = model.append(None, [obj])
        model.append(row_iter, ["-"])
        # NOTE used in test...
        logger.debug("%s added to search results", obj)
        view.refresh_statusbar()

    view.results_view.set_cursor(model.get_path(row_iter))

    return row_iter


def _send_command(call: str) -> None:
    """Sends command to ``bauble.gui.send_command`` only if its available.

    For the sake of tests.
    """
    if bauble.gui:
        bauble.gui.send_command(call)


on_clicked_search = utils.generate_on_clicked(_send_command)
"""Clickable labels convienence function for running a new search,
e.g.::

    utils.make_label_clickable(label, on_clicked_select, "loc=LOC1")
"""

on_clicked_select = utils.generate_on_clicked(select_in_search_results)
"""Clickable labels convienence function for selecting in search view,
e.g.::

    utils.make_label_clickable(label, on_clicked_select, object)
"""
