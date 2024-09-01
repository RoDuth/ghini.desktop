# Copyright 2008-2010 Brett Adams
# Copyright 2015 Mario Frasca <mario@anche.no>.
# Copyright 2021-2024 Ross Demuth <rossdemuth123@gmail.com>
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
Description: the default view
"""

import html
import itertools
import json
import logging
import sys
import textwrap
import threading
import traceback
from collections import UserDict
from collections.abc import Callable
from datetime import timedelta
from datetime import timezone
from pathlib import Path
from textwrap import shorten
from typing import Protocol
from typing import cast

logger = logging.getLogger(__name__)

import sqlalchemy.exc as saexc
from gi.repository import Gdk
from gi.repository import Gio
from gi.repository import GLib
from gi.repository import Gtk
from gi.repository import Pango
from pyparsing import CaselessLiteral
from pyparsing import Group
from pyparsing import Literal
from pyparsing import ParseException
from pyparsing import ParserElement
from pyparsing import ParseResults
from pyparsing import Regex
from pyparsing import Word
from pyparsing import ZeroOrMore
from pyparsing import alphas
from pyparsing import one_of
from pyparsing import printables
from pyparsing import quoted_string
from pyparsing import remove_quotes
from sqlalchemy import and_
from sqlalchemy.orm import Query
from sqlalchemy.orm import Session
from sqlalchemy.orm import object_session
from sqlalchemy.orm.exc import DetachedInstanceError
from sqlalchemy.orm.exc import ObjectDeletedError
from sqlalchemy.sql import ColumnElement

import bauble
from bauble import db
from bauble import paths
from bauble import pluginmgr
from bauble import prefs
from bauble import search
from bauble import utils
from bauble.error import check
from bauble.i18n import _
from bauble.meta import BaubleMeta
from bauble.utils.web import BaubleLinkButton
from bauble.utils.web import LinkDict
from bauble.utils.web import link_button_factory

# use different formatting template for the result view depending on the
# platform
_mainstr_tmpl = "<b>%s</b>"
if sys.platform == "win32":
    _substr_tmpl = "%s"
else:
    _substr_tmpl = "<small>%s</small>"

INFOBOXPAGE_WIDTH_PREF = "infobox.page_width"
"""The preferences key for storing the InfoBoxPage width."""

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

SEARCH_COUNT_FAST_PREF = "bauble.search.count_fast"
"""Set multiprocessing processes on large searches to count top level count,

Values: int (number of processes), bool (use multiprocessing),
    str (just provide length of results)
"""

EXPAND_ON_ACTIVATE_PREF = "bauble.search.expand_on_activate"
"""Preference key, should search view expand the item on double click"""


class Action:
    # pylint: disable=too-few-public-methods, too-many-arguments
    """SearchView context menu items."""

    def __init__(
        self, name, label, callback=None, accelerator=None, multiselect=False
    ):
        """
        :param callback: the function to call when the the action is activated,
            if anything that evaluates to True is returned triggers
            SearchView.update()
        :param accelerator: accelerator to call this action
        :param multiselect: show menu when multiple items are selected
        """
        self.label = label
        self.name = name
        self.callback = callback
        self.multiselect = multiselect
        self.accelerator = accelerator
        self.action = Gio.SimpleAction.new(name, None)
        self.connected = False

    def connect(self, _action, handler, callback):
        if not self.connected:
            self.action.connect("activate", handler, callback)
            self.connected = True


class InfoExpander(Gtk.Expander):
    """An abstract class that is really just a generic expander with a vbox
    to extend this you just have to implement the update() method
    """

    # preference for storing the expanded state
    EXPANDED_PREF = ""

    def __init__(self, label, widgets=None):
        """
        :param label: the name of this info expander, this is displayed on the
        expander's expander

        :param widgets: a bauble.utils.BuilderWidgets instance
        """
        super().__init__(label=label)
        self.vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.vbox.set_border_width(5)
        self.add(self.vbox)
        self.widgets = widgets
        self.display_widgets = []
        if not self.EXPANDED_PREF:
            self.set_expanded(True)
        self.connect("notify::expanded", self.on_expanded)

    def on_expanded(self, expander, *_args):
        if self.EXPANDED_PREF:
            prefs.prefs[self.EXPANDED_PREF] = expander.get_expanded()
            prefs.prefs.save()

    def widget_set_value(self, widget_name, value, markup=False, default=None):
        """A shorthand for `bauble.utils.set_widget_value()`"""
        utils.set_widget_value(
            self.widgets[widget_name], value, markup, default
        )

    def unhide_widgets(self):
        utils.unhide_widgets(self.display_widgets)

    def reset(self):
        """Hide `display_widgets`, set set sensitive False and restore expanded
        state.
        """
        if self.display_widgets:
            utils.hide_widgets(self.display_widgets)
        self.set_sensitive(False)
        self.set_expanded(prefs.prefs.get(self.EXPANDED_PREF, True))

    def update(self, row):
        """This method should be implimented in subclass to update from the
        selected row
        """
        raise NotImplementedError("InfoExpander.update(): not implemented")


class PropertiesExpander(InfoExpander):
    EXPANDED_PREF = "infobox.generic_properties_expanded"

    def __init__(self):
        super().__init__(_("Properties"))
        table = Gtk.Grid()
        table.set_column_spacing(15)
        table.set_row_spacing(8)

        # database id
        id_label = Gtk.Label(label="<b>" + _("ID:") + "</b>")
        id_label.set_use_markup(True)
        id_label.set_xalign(1)
        id_label.set_yalign(0.5)
        table.attach(id_label, 0, 0, 1, 1)

        id_event = Gtk.EventBox()
        self.id_data = Gtk.Label(label="--", selectable=True)
        self.id_data.set_xalign(0)
        self.id_data.set_yalign(0.5)
        id_event.add(self.id_data)
        table.attach(id_event, 1, 0, 1, 1)
        id_event.connect("button_press_event", self.on_id_button_press)

        # object type
        type_label = Gtk.Label(label="<b>" + _("Type:") + "</b>")
        type_label.set_use_markup(True)
        type_label.set_xalign(1)
        type_label.set_yalign(0.5)
        self.type_data = Gtk.Label(label="--")
        self.type_data.set_xalign(0)
        self.type_data.set_yalign(0.5)
        table.attach(type_label, 0, 1, 1, 1)
        table.attach(self.type_data, 1, 1, 1, 1)

        # date created
        created_label = Gtk.Label(label="<b>" + _("Date created:") + "</b>")
        created_label.set_use_markup(True)
        created_label.set_xalign(1)
        created_label.set_yalign(0.5)
        self.created_data = Gtk.Label(label="--", selectable=True)
        self.created_data.set_xalign(0)
        self.created_data.set_yalign(0.5)
        table.attach(created_label, 0, 2, 1, 1)
        table.attach(self.created_data, 1, 2, 1, 1)

        # date last updated
        updated_label = Gtk.Label(label="<b>" + _("Last updated:") + "</b>")
        updated_label.set_use_markup(True)
        updated_label.set_xalign(1)
        updated_label.set_yalign(0.5)
        self.updated_data = Gtk.Label(label="--", selectable=True)
        self.updated_data.set_xalign(0)
        self.updated_data.set_yalign(0.5)
        table.attach(updated_label, 0, 3, 1, 1)
        table.attach(self.updated_data, 1, 3, 1, 1)

        box = Gtk.Box()
        box.pack_start(table, expand=False, fill=False, padding=0)
        self.vbox.pack_start(box, expand=False, fill=False, padding=0)

    def update(self, row):
        """ "Update the widget in the expander."""
        self.set_expanded(prefs.prefs.get(self.EXPANDED_PREF, True))
        self.id_data.set_text(str(row.id))
        self.type_data.set_text(str(type(row).__name__))
        fmat = prefs.prefs.get(prefs.datetime_format_pref)
        # pylint: disable=protected-access
        self.created_data.set_text(
            row._created.strftime(fmat) if row._created else ""
        )
        self.updated_data.set_text(
            row._last_updated.strftime(fmat) if row._last_updated else ""
        )

    def on_id_button_press(self, _widget, event):
        """Copy the ID value to clipboard."""
        # pylint: disable=protected-access
        if event.button == 1 and event.type == Gdk.EventType._2BUTTON_PRESS:
            # Copy the ID on a double click
            string = self.id_data.get_text()
            if bauble.gui:
                bauble.gui.get_display_clipboard().set_text(string, -1)
            return True
        return False


class InfoBoxPage(Gtk.ScrolledWindow):
    """A `Gtk.ScrolledWindow` that contains `bauble.view.InfoExpander`
    objects.
    """

    def __init__(self):
        super().__init__()
        self.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.vbox.set_spacing(10)
        viewport = Gtk.Viewport()
        viewport.add(self.vbox)
        self.add(viewport)
        self.expanders = {}
        self.label = None
        self.connect("size-allocate", self.on_resize)

    @staticmethod
    def on_resize(_window, allocation):
        prefs.prefs[INFOBOXPAGE_WIDTH_PREF] = allocation.width

    def add_expander(self, expander):
        """Add an expander to the dictionary of exanders in this infobox using
        the label name as the key.

        :param expander: the bauble.view.InfoExpander to add to this infobox
        """
        self.vbox.pack_start(expander, expand=False, fill=True, padding=5)
        self.expanders[expander.get_property("label")] = expander

        expander._sep = Gtk.Separator()
        self.vbox.pack_start(expander._sep, False, False, padding=0)

    def get_expander(self, label):
        """Get an expander by the expander's label name.

        :param label: the name of the expander to return
        :return: expander or None
        """
        if label in self.expanders:
            return self.expanders[label]
        return None

    def remove_expander(self, label):
        """Remove expander from the infobox by the expander's label name.

        :param label: the name of th expander to remove

        Return the expander that was removed from the infobox.
        """
        if label in self.expanders:
            return self.vbox.remove(self.expanders[label])
        return None

    def update(self, row):
        """Updates the infobox with values from row.

        :param row: the mapper instance to use to update this infobox,
            this is passed to each of the infoexpanders in turn
        """
        for expander in list(self.expanders.values()):
            expander.update(row)


class InfoBox(Gtk.Notebook):
    """Holds list of expanders with an optional tabbed layout.

    The default is to not use tabs. To create the InfoBox with tabs
    use InfoBox(tabbed=True).  When using tabs then you can either add
    expanders directly to the InfoBoxPage or using
    InfoBox.add_expander with the page_num argument.

    Also, it's not recommended to create a subclass of a subclass of
    InfoBox since if they both use bauble.utils.BuilderWidgets then
    the widgets will be parented to the infobox that is created first
    and the expanders of the second infobox will appear empty.
    """

    def __init__(self, tabbed=False):
        super().__init__()
        self.row = None
        self.set_property("show-border", False)
        if not tabbed:
            page = InfoBoxPage()
            self.insert_page(page, tab_label=None, position=0)
            self.set_property("show-tabs", False)
        self.set_current_page(0)
        self.connect("switch-page", self.on_switch_page)

    # notebook == self could be a static method and just use the notebook?
    def on_switch_page(self, _notebook, _page, page_num, *_args):
        """Called when a page is switched."""
        if not self.row:
            return
        page = self.get_nth_page(page_num)
        page.update(self.row)

    def add_expander(self, expander, page_num=0):
        """Add an expander to a page.

        :param expander: The expander to add.
        :param page_num: The page number in the InfoBox to add the expander.
        """
        page = self.get_nth_page(page_num)
        page.add_expander(expander)

    def update(self, row):
        """Update the current page with row."""
        self.row = row
        page_num = self.get_current_page()
        self.get_nth_page(page_num).update(row)


class LinksExpander(InfoExpander):
    EXPANDED_PREF = "infobox.generic_links_expanded"

    def __init__(
        self, notes: str | None = None, links: list[LinkDict] | None = None
    ):
        """
        :param notes: the name of the notes property on the row
        """
        super().__init__(_("Links"))
        links = links or []
        self.dynamic_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.vbox.pack_start(self.dynamic_box, False, False, 0)
        self.link_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.vbox.pack_start(self.link_box, False, False, 0)
        self.notes = notes
        self.buttons: list[BaubleLinkButton] = []
        for link in sorted(links, key=lambda i: i["title"]):
            try:
                btn = link_button_factory(link)
                self.buttons.append(btn)
                self.link_box.pack_start(btn, False, False, 0)
            except Exception as e:  # pylint: disable=broad-except
                # broad except, user data.
                logger.debug(
                    "wrong link definition %s, %s(%s)",
                    link,
                    type(e).__name__,
                    e,
                )
        self._sep = None

    def update(self, row: db.Base) -> None:
        self.set_expanded(prefs.prefs.get(self.EXPANDED_PREF, True))
        note_buttons: list[BaubleLinkButton] = []
        for btn in self.buttons:
            btn.set_string(row)
        for child in self.dynamic_box.get_children():
            self.dynamic_box.remove(child)
        if self.notes:
            for note in getattr(row, self.notes):
                for label, url in utils.get_urls(note.note):
                    if not label:
                        label = url
                    try:
                        category = note.category
                        link: LinkDict = {
                            "title": label,
                            "tooltip": f"from note of category {category}",
                        }
                        button = link_button_factory(link)
                        button.set_uri(url)
                        note_buttons.append(button)
                    except Exception as e:  # pylint: disable=broad-except
                        # broad except, user data.
                        logger.debug(
                            "wrong link definition %s, %s(%s)",
                            link,
                            type(e).__name__,
                            e,
                        )
            for button in sorted(note_buttons, key=lambda i: i.title):
                self.dynamic_box.pack_start(button, False, False, 0)

            if note_buttons and self.buttons:
                sep = Gtk.Separator(margin_start=15, margin_end=15)
                self.dynamic_box.pack_start(sep, False, False, 0)

        widgets = [self]
        if self._sep:
            widgets.append(self._sep)

        if note_buttons or self.buttons:
            utils.unhide_widgets(widgets)
            self.show_all()
        else:
            utils.hide_widgets(widgets)


class AddOneDot(threading.Thread):
    @staticmethod
    def callback(dotno):
        statusbar = bauble.gui.widgets.statusbar
        sbcontext_id = statusbar.get_context_id("searchview.nresults")
        statusbar.pop(sbcontext_id)
        statusbar.push(sbcontext_id, _("counting results") + "." * dotno)

    def __init__(self, group=None, **kwargs):
        super().__init__(group=group, target=None, name=None)
        self.__stopped = threading.Event()
        self.dotno = 0

    def cancel(self):
        self.__stopped.set()

    def run(self):
        while not self.__stopped.wait(1.0):
            self.dotno += 1
            GLib.idle_add(self.callback, self.dotno)


def multiproc_counter(url, klass, ids):
    """multiprocessing worker to get top level count for a group of items.

    :param url: database url as a string.
    :param klass: sqlalchemy table class.
    :param ids: a list of id numbers to query.
    """
    if sys.platform == "darwin":
        # only on macos
        # TODO need to investigate this further.  Dock icons pop up for every
        # process produced.  The below suppresses the icon AFTER it has already
        # popped up meaning you get a bunch of icons appearing for a
        # around a second and then disappearing.
        import AppKit

        AppKit.NSApp.setActivationPolicy_(1)  # 2 also works
    db.open_conn(url)
    # get tables across plugins (e.g. plants - Genus, garden - Accession )
    pluginmgr.load()
    session = db.Session()
    results = {}
    for id_ in ids:
        item = session.query(klass).get(id_)
        # item has since been deleted elsewhere
        if not item:
            continue
        for k, v in item.top_level_count().items():
            if isinstance(v, set):
                # need strings to pickle results
                new_v = {str(i) for i in v}
                results[k] = new_v.union(results.get(k, set()))
            else:
                results[k] = v + results.get(k, 0)
    session.close()
    db.engine.dispose()
    return results


class CountResultsTask(threading.Thread):
    """Threading task to calculate top level count and place it on the status
    bar

    if search is large will deligate the counting task to multiprocessing
    workers.
    """

    def __init__(self, klass, ids, dots_thread, group=None):
        super().__init__(group=group, target=None, name=None)
        self.klass = klass
        self.ids = ids
        self.dots_thread = dots_thread
        self.__cancel = False

    def cancel(self):
        self.__cancel = True

    def callback(self, items):
        """Collate the results into a string.

        when using multiprocessing this is used as callback for the worker"""
        items_dct = {}
        if isinstance(items, list):
            for itm in items:
                for k, v in itm.items():
                    if isinstance(v, set):
                        items_dct[k] = v.union(items_dct.get(k, set()))
                    else:
                        items_dct[k] = v + items_dct.get(k, 0)
        else:
            items_dct = items
        result = []
        for k, v in sorted(items_dct.items()):
            if isinstance(k, tuple):
                k = k[1]
            if isinstance(v, set):
                v = len(v)
            result.append(f"{k}: {v}")
            if self.__cancel:  # check whether caller asks to cancel
                break
        value = _("top level count: %s") % (", ".join(result))
        self.set_statusbar(value)

    def error(self, e):
        """error_callback for multiprocessing worker.

        Cancels dots_thread and logs error
        """
        self.dots_thread.cancel()
        logger.debug("%s (%s)", type(e).__name__, e)
        self.set_statusbar(f"{type(e).__name__} error counting results")

    def set_statusbar(self, value):
        """Put the results on the statusbar."""
        if bauble.gui:
            statusbar = bauble.gui.widgets.statusbar

            def sb_call(text):
                sbcontext_id = statusbar.get_context_id("searchview.nresults")
                statusbar.pop(sbcontext_id)
                statusbar.push(sbcontext_id, text)

            if not self.__cancel:  # check whether caller asks to cancel
                self.dots_thread.cancel()
                GLib.idle_add(sb_call, value)
        else:
            self.dots_thread.cancel()
            logger.debug("showing text %s", value)
        # NOTE log used in tests
        logger.debug("counting results class:%s complete", self.klass.__name__)

    def run(self):
        """Runs thread, decide whether to use multiprocessing or not.

        Results are handed to self.callback either by the multiprocessing
        worker or directly
        """
        count_fast = prefs.prefs.get(SEARCH_COUNT_FAST_PREF, True)
        # NOTE these figures were arrived at by trial and error on a particular
        # dataset. No guarantee they are ideal in all situations.
        if self.klass.__name__ in ["Family", "Location"]:
            max_ids = 30
            chunk_size = 10
        else:
            max_ids = 300
            chunk_size = 100
        if count_fast and len(self.ids) > max_ids:
            from functools import partial
            from multiprocessing import get_context

            proc = partial(multiproc_counter, str(db.engine.url), self.klass)
            processes = None
            # pylint: disable=unidiomatic-typecheck # bool is subclass of int,
            # isinstance won't work.
            if type(count_fast) is int:
                processes = count_fast
            logger.debug(
                "counting results multiprocessing, processes=%s", processes
            )
            with get_context("spawn").Pool(processes) as pool:
                amap = pool.map_async(
                    proc,
                    utils.chunks(self.ids, chunk_size),
                    callback=self.callback,
                    error_callback=self.error,
                )
                # keeps the thread alive and allow cancel
                while not amap.ready():
                    if self.__cancel:  # check whether caller asks to cancel
                        pool.terminate()
                        break
                    amap.wait(0.5)
        else:
            session = db.Session()
            results = {}
            for id_ in self.ids:
                item = session.query(self.klass).get(id_)
                if self.__cancel:  # check whether caller asks to cancel
                    break
                # item has been deleted elswhere (race condition)
                if not item:
                    continue
                for k, v in item.top_level_count().items():
                    if isinstance(v, set):
                        results[k] = v.union(results.get(k, set()))
                    else:
                        results[k] = v + results.get(k, 0)
            session.close()
            self.callback(results)


class Picture(Protocol):
    category: str
    picture: str


class PicturesScroller(Gtk.ScrolledWindow):
    """Shows pictures corresponding to selection.

    PicturesScroller object will ask each object in the selection to return
    pictures to display.
    """

    first_run: bool = True

    START_PAGE_SIZE = 6

    def __init__(self, parent: Gtk.Paned, pic_pane: Gtk.Paned) -> None:
        logger.debug("entering PicturesScroller.__init__(parent=%s)", parent)
        super().__init__()
        parent.add(self)
        self.parent = parent
        self.pic_pane = pic_pane
        self.set_width_and_notebook_page()
        self.restore_position: int | None = prefs.prefs.get(
            PIC_PANE_WIDTH_PREF
        )
        pic_pane.show_all()
        self.pictures_box = Gtk.FlowBox()
        self.add(self.pictures_box)
        self.last_result_succeed = False
        self.show()
        # connect to the grandparent to capture parent's values first
        if pic_parent := self.pic_pane.get_parent():
            pic_parent.connect("destroy", self.on_destroy)
        self.single_button_press_timer: threading.Timer | None = None
        self.get_vadjustment().connect("value-changed", self.on_scrolled)
        self.max_allocated_height = 0
        self.last_pic: Gtk.Box | None = None
        self.all_pics: list[tuple[Picture, db.Base]] = []
        self.count = 0
        self.page_size = self.START_PAGE_SIZE
        self.waiting_on_realise = 0

    def on_scrolled(self, *_args):
        """On scrolling add more pictures as needed.

        Uses the furthest picture and the largest size allocation (of the last
        batch after they are realised) to calculate if the end is close.
        """
        if self.last_pic:
            relative_coords = self.translate_coordinates(
                self.last_pic, 0, self.max_allocated_height
            )
            if not relative_coords or (
                relative_coords
                and relative_coords[-1] > -self.max_allocated_height - 100
            ):
                self.add_rows()

    def on_image_size_allocated(self, image: Gtk.Image, *_args) -> None:
        """After an image has had its size allocated use its `pic_box` height
        allocation to calculate the maximum height allocation of the current
        batch of pictures.

        Also triggers on_scrolled in case more images are needed on the page.
        """
        pic_box = cast(Gtk.Box, image.get_parent())

        allocated_height = pic_box.get_allocated_height()
        if allocated_height > self.max_allocated_height:
            self.max_allocated_height = allocated_height

        # avoid making negative in case of an overlap (i.e. user changes
        # selection prior to image realising)
        if self.waiting_on_realise > 0:
            self.waiting_on_realise -= 1

        # check if more should be added (e.g. first run, so we get a scrollbar)
        if self.waiting_on_realise <= 0:
            self.on_scrolled()

    def on_destroy(self, _widget) -> None:
        width = self.pic_pane.get_position()
        logger.debug("setting PIC_PANE_WIDTH_PREF to %s", width)
        prefs.prefs[PIC_PANE_WIDTH_PREF] = width
        if pic_pane_notebook := cast(Gtk.Notebook, self.parent.get_parent()):
            selected = pic_pane_notebook.get_current_page()
        logger.debug("setting PIC_PANE_PAGE_PREF to %s", selected)
        prefs.prefs[PIC_PANE_PAGE_PREF] = selected

    def _hide_restore_pic_pane(self, selection: list[db.Base] | None) -> None:
        if self.last_result_succeed:
            self.restore_position = self.pic_pane.get_position()
        if self.first_run:
            if bauble.gui:
                width = bauble.gui.window.get_size().width
                self.pic_pane.set_position(width - 6)
        if not selection:
            # No result or error
            if bauble.gui and not self.first_run:
                width = bauble.gui.window.get_size().width
                self.pic_pane.set_position(width - 6)
            self.last_result_succeed = False
        else:
            # successful
            if self.restore_position:
                if self.last_result_succeed:
                    self.pic_pane.set_position(self.restore_position)
                    self.first_run = False
                else:
                    # first_run need to wait for everything to initialise or
                    # will get a pic_pane even when one isn't intended
                    GLib.idle_add(
                        self.pic_pane.set_position, self.restore_position
                    )

            self.last_result_succeed = True

    def populate_from_selection(self, selection: list[db.Base] | None) -> None:
        logger.debug("PicturesScroller.populate_from_selection(%s)", selection)

        for kid in self.pictures_box.get_children():
            kid.destroy()

        self.all_pics.clear()

        selection = selection or []
        for obj in selection:
            pics = getattr(obj, "pictures", [])

            for pic in pics:
                # NOTE this will skip examples where species_picture and
                # plant_picture are the same, etc..
                if pic in {pic for pic, obj in self.all_pics}:
                    continue
                self.all_pics.append((pic, obj))

        self.count = 0
        self.page_size = self.START_PAGE_SIZE
        self.waiting_on_realise = 0

        self._hide_restore_pic_pane(selection)
        self.add_rows()

    def add_rows(self) -> None:
        """Add a page of pictures."""
        if self.count == len(self.all_pics):
            # bail early if already finished adding rows
            return

        self.max_allocated_height = 0

        page_end = self.count + self.page_size
        for pic, obj in self.all_pics[self.count : page_end]:
            logger.debug("object %s has picture %s", obj, pic)
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            if pic.category:
                label = Gtk.Label(label="category: " + pic.category)
                box.add(label)
            event_box = Gtk.EventBox()
            event_box.connect(
                "button-press-event",
                self.on_button_press,
                pic.picture,
                obj,
            )
            pic_box = Gtk.Box()
            self.waiting_on_realise += 1
            utils.ImageLoader(
                pic_box,
                pic.picture,
                on_size_allocated=self.on_image_size_allocated,
            ).start()
            pic_box.set_hexpand(True)
            pic_box.set_vexpand(True)
            event_box.add(pic_box)
            box.pack_start(event_box, True, True, 0)
            self.pictures_box.add(box)
            box.show_all()
            self.count += 1

        self.last_pic = pic_box

        self.pictures_box.show_all()

    def set_width_and_notebook_page(self) -> None:
        # for tests when no gui
        width = 1000
        if bauble.gui:
            width = bauble.gui.window.get_size().width
        pics_width = prefs.prefs.get(PIC_PANE_WIDTH_PREF, 300)

        info_width = prefs.prefs.get(INFOBOXPAGE_WIDTH_PREF, 300)
        # no search results == no infobox
        if (
            bauble.gui
            and isinstance(bauble.gui.get_view(), SearchView)
            and bauble.gui.get_view().infobox is None
        ):
            info_width = 0

        pane_pos = width - info_width - pics_width - 6
        logger.debug("setting pic_pane position to %s", pane_pos)
        self.pic_pane.set_position(pane_pos)
        selected = prefs.prefs.get(PIC_PANE_PAGE_PREF)
        if selected is not None:
            notebook = cast(Gtk.Notebook, self.parent.get_parent())
            if notebook:
                notebook.set_current_page(selected)

    def on_button_press(
        self, _view, event: Gdk.EventButton, link: str, obj: db.Base
    ) -> None:
        """On double click open the image in the default viewer. On single
        click select the item in the search view, if its already selected check
        if the picture comes from a child and if so select it.
        """
        # hack single click
        if self.single_button_press_timer:
            self.single_button_press_timer.cancel()
            self.single_button_press_timer = None
        # pylint: disable=protected-access
        if event.button == 1:
            if event.type == Gdk.EventType._2BUTTON_PRESS:
                # if it is not a url append the picture_root and open, if it is
                # a URL just open it.
                full_path = None
                if not (
                    link.startswith("http://") or link.startswith("https://")
                ):
                    pic_root = prefs.prefs.get(prefs.picture_root_pref)
                    full_path = Path(pic_root, link)
                utils.desktop.open(full_path or link)
            elif event.type == Gdk.EventType.BUTTON_PRESS:
                self.single_button_press_timer = threading.Timer(
                    0.3, self._on_single_button_press, (link, obj)
                )
                self.single_button_press_timer.start()

    def _on_single_button_press(self, link: str, obj: db.Base) -> None:
        self.single_button_press_timer = None
        GLib.idle_add(self.select_object, link, obj)

    def select_object(self, link: str, obj: db.Base) -> None:
        """Select the object in the SearchView,

        If the object is already the one selected check if it has a child that
        owns the picture and if so select the child instead.
        """
        if bauble.gui and isinstance(
            search_view := bauble.gui.get_view(), SearchView
        ):
            model = search_view.results_view.get_model()
            if not model:
                return
            selected = search_view.get_selected_values()
            obj_is_owner = self._obj_owns_picture(obj, link)

            if selected == [obj] and obj_is_owner:
                self.pictures_box.unselect_all()
                return

            if selected is not None and obj in selected and obj_is_owner:
                # make sure we select the object if multiple selected
                select_in_search_results(obj)
                return

            self._select_child_obj(link, obj, model, search_view)

    def _select_child_obj(
        self,
        link: str,
        obj: db.Base,
        model: Gtk.TreeModel,
        search_view: "SearchView",
    ) -> None:
        logger.debug("object = %s(%s)", type(obj).__name__, obj)
        kids = search_view.row_meta[type(obj)].get_children(obj)
        for kid in kids:
            for pic in getattr(kid, "pictures", []):
                if pic.picture == link:
                    itr = utils.search_tree_model(model, obj)[0]
                    path = model.get_path(itr)
                    # expand (on_test_expand_row needed for test)
                    search_view.on_test_expand_row(
                        search_view.results_view, itr, path
                    )
                    search_view.results_view.expand_to_path(path)
                    if self._obj_owns_picture(kid, link):
                        itr = select_in_search_results(kid)
                        path = model.get_path(itr)
                        search_view.results_view.scroll_to_cell(
                            path, None, True, 0.5, 0.0
                        )
                    else:
                        # traverse to source
                        self._select_child_obj(link, kid, model, search_view)

    @staticmethod
    def _obj_owns_picture(obj: db.Base, link: str) -> bool:
        obj_name = type(obj).__name__
        return any(
            pic.picture == link
            and type(pic).__name__.removesuffix("Picture") == obj_name
            for pic in getattr(obj, "pictures", [])
        )


class ViewMeta(UserDict):
    """This class shouldn't need to be instantiated directly.  Access the
    meta for the SearchView with the :class:`bauble.view.SearchView`'s
    `row_meta` or `bottom_info` attributes.

    ...note: can access the actual dictionary used to store the contents
    directly via the UserDict `data` attribute. e.g. to use setdefault in
    such a way that doesn't call __getitem__
    """

    class Meta:
        def __init__(self):
            self.children = None
            self.infobox = None
            self.context_menu = None
            self.actions = []
            self.sorter = utils.natsort_key
            self.activated_callback = None

        def set(
            self,
            children=None,
            infobox=None,
            context_menu=None,
            sorter=None,
            activated_callback=None,
        ):
            """Set attributes for the selected meta object.

            :param children: where to find the children for this type, can
                be a callable of the form `children(row)`
            :param infobox: the infobox for this type
            :param context_menu: a dict describing the context menu used
                when the user right clicks on this type
            """
            self.children = children
            self.infobox = infobox
            self.context_menu = context_menu
            if sorter:
                self.sorter = sorter

            self.actions = []
            if self.context_menu:
                self.actions = [
                    x for x in self.context_menu if isinstance(x, Action)
                ]
            self.activated_callback = activated_callback

        def get_children(self, obj):
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

    def __getitem__(self, item):
        if item not in self:  # create on demand
            self[item] = self.Meta()
        return super().__getitem__(item)


@Gtk.Template(filename=str(Path(paths.lib_dir(), "search_view.ui")))
class SearchView(pluginmgr.View, Gtk.Box):
    """The SearchView is the main view for Ghini.

    Manages the search results returned when search strings are entered into
    the main text entry.
    """

    __gtype_name__ = "SearchView"

    bottom_notebook = cast(Gtk.Notebook, Gtk.Template.Child())
    results_view = cast(Gtk.TreeView, Gtk.Template.Child())
    info_pane = cast(Gtk.Paned, Gtk.Template.Child())
    pic_pane = cast(Gtk.Paned, Gtk.Template.Child())
    pic_pane_notebook = cast(Gtk.Notebook, Gtk.Template.Child())
    pics_box = cast(Gtk.Paned, Gtk.Template.Child())

    row_meta = ViewMeta()
    bottom_info = ViewMeta()

    pic_pane_notebook_pages: set[tuple[Gtk.Widget, int, str]] = set()
    """Widgets added here will be added to the pic_pane_notebook.
    Items are a tuple - (widget, tab position, tab label)
    """

    context_menu_callbacks: set[Callable] = set()
    """Callbacks for constructing context menus for selected items.
    Callbacks should recieve a single argument containing the selected items
    and return a single menu section of type Gio.Menu
    """

    cursor_changed_callbacks: set[Callable] = set()
    """Callbacks called each time the cursor changes"""

    populate_callbacks: set[Callable] = set()
    """Callbacks called each time SearchView populates"""

    extra_signals: set[tuple[str, str, Callable]] = set()
    """Add extra signals here to be setup at init.
    Items are a tuple - (widget name, signal name, handler)
    """

    first_run: bool = True

    def __init__(self):
        logger.debug("SearchView::__init__")
        super().__init__()

        self.create_gui()

        self.add_pic_pane_notebook_pages()

        self.pictures_scroller = PicturesScroller(
            parent=self.pics_box, pic_pane=self.pic_pane
        )

        # the context menu cache holds the context menus by type in the results
        # view so that we don't have to rebuild them every time
        self.context_menu_cache = {}
        self.infobox_cache = {}
        self.infobox = None
        self.history_action = None

        # keep all the search results in the same session, this should
        # be cleared when we do a new search
        self.session = db.Session()
        self.add_notes_page_to_bottom_notebook()
        self.running_threads = []
        self.actions = set()
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

    def connect_signal(
        self, widget_name: str, signal: str, handler: Callable
    ) -> None:
        widget = getattr(self, widget_name)
        widget.connect(signal, handler)

    def add_pic_pane_notebook_pages(self) -> None:
        for page in self.pic_pane_notebook_pages:
            self.add_page_to_pic_pane_notebook(*page)

    def add_notes_page_to_bottom_notebook(self):
        """add notebook page for notes

        this is a temporary function, will be removed when notes are
        implemented as a plugin. then notes will be added with the
        generic add_page_to_bottom_notebook.
        """
        glade_name = str(Path(paths.lib_dir(), "notes_page.glade"))
        widgets = utils.BuilderWidgets(glade_name)
        page = widgets.notes_scrolledwindow
        # create the label object
        label = Gtk.Label(label="Notes")
        self.bottom_notebook.append_page(page, label)

        def sorter(notes):
            return sorted(notes, key=lambda note: note.date, reverse=True)

        self.bottom_info[Note] = {
            "fields_used": ["date", "user", "category", "note"],
            "tree": widgets.notes_treeview,
            "label": label,
            "name": _("Notes"),
            "sorter": sorter,
        }
        widgets.notes_treeview.connect(
            "row-activated", self.on_note_row_activated
        )

    def on_note_row_activated(self, tree, path, _column):
        try:
            # retrieve the selected row from the results view (we know it's
            # one), and we only need it's domain name
            selected = self.get_selected_values()[0]
            domain = selected.__class__.__name__.lower()
            # retrieve the activated row
            row = tree.get_model()[path]
            cat = None if row[2] == "" else repr(row[2])
            note = repr(row[3])
            # construct the query
            query = f"{domain} where notes[category={cat}].note={note}"
            # fire it
            if bauble.gui:
                bauble.gui.send_command(query)
            else:
                # NOTE used in testing
                return query
        except Exception as e:
            logger.debug("on_note_row_actived %s(%s)", type(e).__name__, e)
        return None

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

    def add_page_to_bottom_notebook(self, bottom_info):
        """add notebook page for a plugin class."""
        glade_name = bottom_info["glade_name"]
        widgets = utils.BuilderWidgets(glade_name)
        page = widgets[bottom_info["page_widget"]]
        # 2: detach it from parent (its container)
        widgets.remove_parent(page)
        # 3: create the label object
        label = Gtk.Label(label=bottom_info["name"])
        # 4: add the page, non sensitive
        self.bottom_notebook.append_page(page, label)
        # 5: store the values for later use
        bottom_info["tree"] = page.get_children()[0]
        if row_activated := bottom_info.get("row_activated"):
            bottom_info["tree"].connect("row-activated", row_activated)
        bottom_info["label"] = label

    def update_bottom_notebook(self, selected_values):
        """Update the bottom_notebook from the currently selected row.

        bottom_notebook has one page per type of information. Every page
        is registered by its plugin, which adds an entry to the
        dictionary self.bottom_info.

        the GtkNotebook pages are ScrolledWindow containing a TreeView,
        this should have a model, and the ordered names of the fields to
        be stored in the model is in bottom_info['fields_used'].
        """
        # Only one should be selected
        if len(selected_values or []) != 1:
            self.bottom_notebook.hide()
            return

        row = selected_values[0]  # the selected row

        # loop over bottom_info plugin classes (eg: Tag)
        for klass, bottom_info in self.bottom_info.items():
            if "label" not in bottom_info:  # late initialization
                self.add_page_to_bottom_notebook(bottom_info)
            label = bottom_info["label"]
            if not hasattr(klass, "attached_to"):
                logging.warning(
                    "class %s does not implement attached_to", klass
                )
                continue
            objs = klass.attached_to(row)
            model = bottom_info["tree"].get_model()
            model.clear()
            if not objs or not isinstance(objs, list):
                label.set_use_markup(False)
                label.set_label(bottom_info["name"])
            else:
                label.set_use_markup(True)
                label.set_label(f'<b>{bottom_info["name"]}</b>')
                sorter = bottom_info.get("sorter", reversed)
                for obj in sorter(objs):
                    values = []
                    for k in bottom_info["fields_used"]:
                        if k == "date" and (date := getattr(obj, k)):
                            values.append(
                                date.strftime(
                                    prefs.prefs.get(prefs.date_format_pref)
                                )
                            )
                        else:
                            values.append(getattr(obj, k) or "")
                    model.append(values)
        self.bottom_notebook.show()

    def update_infobox(self, selected_values):
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

    def set_infobox_from_row(self, row, sensitive=True):
        """implement the logic for update_infobox"""

        logger.debug("set_infobox_from_row: %s --  %s", row, repr(row))
        # remove the current infobox if there is one and it is not needed
        if row is None:
            if (
                self.infobox is not None
                and self.infobox.get_parent() == self.info_pane
            ):
                self.info_pane.remove(self.infobox)
            return

        # set width from pref once per session.
        if self.infobox is None:
            # for tests when no gui
            width = 100
            if bauble.gui:
                width = bauble.gui.window.get_size().width
            info_width = prefs.prefs.get(INFOBOXPAGE_WIDTH_PREF, 300)
            pane_pos = width - info_width - 1
            logger.debug("setting info_pane position to %s", pane_pos)
            self.info_pane.set_position(pane_pos)

        selected_type = type(row)
        # if we have already created an infobox of this type:
        new_infobox = self.infobox_cache.get(selected_type)

        if not new_infobox:
            # it might be in cache under different name
            for infobox in self.infobox_cache.values():
                if isinstance(infobox, self.row_meta[selected_type].infobox):
                    logger.debug("found same infobox under different name")
                    new_infobox = infobox
            # otherwise create one and put in the infobox_cache
            if not new_infobox:
                logger.debug("not found infobox, we make a new one")
                new_infobox = self.row_meta[selected_type].infobox()
            self.infobox_cache[selected_type] = new_infobox

        logger.debug(
            "created or retrieved infobox %s %s",
            type(new_infobox).__name__,
            new_infobox,
        )

        # remove any old infoboxes connected to the pane
        if self.infobox is not None and type(self.infobox) is not type(
            new_infobox
        ):
            if self.infobox.get_parent() == self.info_pane:
                self.info_pane.remove(self.infobox)

        # update the infobox and put it in the pane
        self.infobox = new_infobox
        if self.infobox is not None:
            self.infobox.update(row)
            self.info_pane.pack2(self.infobox, resize=False, shrink=True)
            self.infobox.set_sensitive(sensitive)
            self.info_pane.show_all()

    def get_selected_values(self) -> list[db.Base] | None:
        """Get the values in all the selected rows."""
        model, rows = self.selection.get_selected_rows()
        if model is None or rows is None:
            return None
        return [model[row][0] for row in rows]

    def on_selection_changed(self, _tree_selection):
        """Update the infobox and bottom notebooks. Switch context_menus,
        actions and accelerators depending on the type of the rows selected.
        """
        # NOTE log used in tests
        logger.debug("SearchView::on_selection_changed")
        # grab values once
        selected_values = self.get_selected_values()
        # bail early if failed search
        if selected_values and isinstance(selected_values[0], str):
            logger.debug("cannot update from str object")
            return
        # update all forward-looking info boxes
        self.update_infobox(selected_values)
        # update all backward-looking info boxes
        self.update_bottom_notebook(selected_values)

        self.pictures_scroller.populate_from_selection(selected_values)

        self.update_context_menus(selected_values)

        for callback in self.cursor_changed_callbacks:
            callback(selected_values)

    def on_action_activate(self, _action, _param, call_back):
        result = False
        try:
            values = self.get_selected_values()
            result = call_back(values)
        except Exception as e:  # pylint: disable=broad-except
            msg = utils.xml_safe(str(e))
            trace = utils.xml_safe(traceback.format_exc())
            utils.message_details_dialog(msg, trace, Gtk.MessageType.ERROR)
            logger.warning(traceback.format_exc())
        if result:
            # can lead to update called twice but ensures its called when not
            # an editor.  Editors will also call update from insert menu.
            self.update()

    def update_context_menus(self, selected_values):
        """Update the context menu dependant on selected values."""

        self.context_menu_model.remove_all()

        if not selected_values:
            return
        selected_types = set(map(type, selected_values))

        selected_type = None
        if len(selected_types) == 1:
            selected_type = selected_types.pop()

        current_actions = set()

        # if selected_type is None this should not return any actions
        for action in self.row_meta[selected_type].actions:
            current_actions.add(action.name)

            if bauble.gui and not bauble.gui.lookup_action(action.name):
                self.actions.add(action.name)
                bauble.gui.window.add_action(action.action)

                action.connect(
                    "activate", self.on_action_activate, action.callback
                )
                app = Gio.Application.get_default()
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

        get_history_action_name = "get_history"

        if bauble.gui:
            if not bauble.gui.lookup_action(get_history_action_name):
                self.history_action = bauble.gui.add_action(
                    get_history_action_name, self.on_get_history
                )
            if len(selected_values) == 1:
                self.history_action.set_enabled(True)
            else:
                self.history_action.set_enabled(False)

        get_history_menu_item = Gio.MenuItem.new(
            _("Show History"), f"win.{get_history_action_name}"
        )
        self.context_menu_model.append_item(get_history_menu_item)

        for action_name in self.actions.copy():
            if action_name not in current_actions:
                if bauble.gui:
                    bauble.gui.remove_action(action_name)
                self.actions.remove(action_name)

        if bauble.gui:
            edit_context_menu = bauble.gui.edit_context_menu
            edit_context_menu.remove_all()
            edit_context_menu.insert_section(0, None, self.context_menu_model)

    def on_copy_selection(self, _action, _param):
        selected_values = self.get_selected_values()
        if not selected_values:
            return None

        out = []
        from mako.template import Template

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
                msg, traceback.format_exc(), typ=Gtk.MessageType.ERROR
            )

        string = "\n".join(out)
        if bauble.gui:
            bauble.gui.get_display_clipboard().set_text(string, -1)
            return None
        # NOTE used in testing
        return string

    def on_get_history(self, _action, _param):
        selected_values = self.get_selected_values()
        if not selected_values:
            return None

        selected = selected_values[0]
        # include timestamp because IDs can get reused in some situations
        search_str = (
            f":history = table_name = {selected.__tablename__} "
            f"and table_id = {selected.id} "
            f'and timestamp >= "{selected._created}"'
        )

        if bauble.gui:
            bauble.gui.send_command(search_str)
            return None
        # NOTE used in testing
        return search_str

    def search(self, text: str) -> None:
        """search the database using text"""
        logger.debug("SearchView.search(%s)", text)
        error_msg = None
        error_details_msg = None
        # stop whatever it might still be doing
        self.cancel_threads()
        self.session.close()
        # clear the caches to avoid stale items.
        self.has_kids.clear_cache()  # pylint: disable=no-member
        self.count_kids.clear_cache()  # pylint: disable=no-member
        self.get_markup_pair.clear_cache()  # pylint: disable=no-member
        if not db.Session:
            return
        self.session = db.Session()
        bold = "<b>%s</b>"
        results = []
        try:
            results = search.search(text, self.session)
        except ParseException as err:
            error_msg = _("Error in search string at column %s") % err.column
        except Exception as e:  # pylint: disable=broad-except
            logger.debug(traceback.format_exc())
            error_msg = _("** Error: %s") % utils.xml_safe(e)
            error_details_msg = utils.xml_safe(traceback.format_exc())

        # clear last result
        for callback in self.populate_callbacks:
            callback([])

        # avoid triggering on_selection_changed
        self.selection.handler_block(self._sc_sid)
        utils.clear_model(self.results_view)
        self.selection.handler_unblock(self._sc_sid)

        if error_msg and bauble.gui:
            bauble.gui.show_error_box(error_msg, error_details_msg)
            self.on_selection_changed(None)
            return

        # not error
        if bauble.gui:
            statusbar = bauble.gui.widgets.statusbar
        else:
            # for testing...
            statusbar = Gtk.Statusbar()
        sbcontext_id = statusbar.get_context_id("searchview.nresults")
        statusbar.pop(sbcontext_id)
        if len(results) == 0:
            model = Gtk.ListStore(str)
            msg = bold % html.escape(
                _('Could not find anything for search: "%s"') % text
            )
            model.append([msg])
            if prefs.prefs.get(prefs.exclude_inactive_pref):
                msg = bold % _(
                    "CONSIDER: uncheck 'Exclude Inactive' in options menu and "
                    "search again."
                )
                model.append([msg])
            self.results_view.set_model(model)
        else:
            statusbar.push(
                sbcontext_id,
                _("Retrieving %s search results…") % len(results),
            )
            if len(results) > 30000:
                msg = _(
                    "This query returned %s results.  It may take a "
                    "while to display all the data. Are you sure you "
                    "want to continue?"
                ) % len(results)
                if not utils.yes_no_dialog(msg):
                    return
            self.populate_results(results)
            statusbar.pop(sbcontext_id)
            statusbar.push(sbcontext_id, _("counting results"))
            count_fast = prefs.prefs.get(SEARCH_COUNT_FAST_PREF, True)
            if isinstance(count_fast, str):
                statusbar.push(
                    sbcontext_id, _("size of result: %s") % len(results)
                )
            elif len(set(item.__class__ for item in results)) == 1:
                dots_thread = self.start_thread(AddOneDot())
                self.start_thread(
                    CountResultsTask(
                        results[0].__class__,
                        [i.id for i in results],
                        dots_thread,
                    )
                )
            else:
                statusbar.push(
                    sbcontext_id,
                    _("size of non homogeneous result: %s") % len(results),
                )
            if self.first_run:
                # not sure why the first row is hidden on the first search but
                # this fixes it
                self.first_run = False
                GLib.idle_add(
                    self.results_view.set_cursor, Gtk.TreePath.new_first()
                )
            self.results_view.set_cursor(Gtk.TreePath.new_first())

    @staticmethod
    def remove_children(model, parent):
        """Remove all children of some parent in the model.

        Reverse iterate through them so you don't invalidate the iter.
        """
        while model.iter_has_child(parent):
            nkids = model.iter_n_children(parent)
            child = model.iter_nth_child(parent, nkids - 1)
            model.remove(child)

    def on_test_expand_row(self, view, treeiter, path):
        """Look up the table type of the selected row and if it has any
        children then add them to the row.
        """
        model = view.get_model()
        row = model.get_value(treeiter, 0)
        view.collapse_row(path)
        self.remove_children(model, treeiter)
        try:
            kids = self.row_meta[type(row)].get_children(row)
            if len(kids) == 0:
                return True
            sorter = utils.natsort_key
            if len({type(i) for i in kids}) == 1:
                sorter = self.row_meta[type(kids[0])].sorter
        except saexc.InvalidRequestError as e:
            logger.debug("on_test_expand_row: %s:%s", type(e).__name__, e)
            model = self.results_view.get_model()
            for found in utils.search_tree_model(model, row):
                model.remove(found)
            return True
        except Exception as e:
            logger.debug("on_test_expand_row: %s:%s", type(e).__name__, e)
            logger.debug(traceback.format_exc())
            return True
        self.append_children(model, treeiter, sorted(kids, key=sorter))
        return False

    def populate_results(self, results):
        """Adds results to the search view in a task.

        :param results: a list or list-like object
        """
        # don't bother with a task if the results are small,
        # this keeps the screen from flickering when the main
        # window is set to a busy state
        if len(results) > 3000:
            bauble.task.queue(self._populate_worker(results))
        else:
            task = self._populate_worker(results)
            while True:
                try:
                    next(task)
                except StopIteration:
                    break

        for callback in self.populate_callbacks:
            callback(results)

    def _populate_worker(self, results):
        """Generator function for adding the search results to the
        model.

        This method is usually called by `self.populate_results()`
        """
        nresults = len(results)
        model = Gtk.TreeStore(object)
        # docs suggests this method and did work in pygtk but now doesn't
        # model.set_default_sort_func(None)
        # now this seems the only way to remove sorting function (i.e.
        # has_default_sort_func returns false)
        model.set_sort_column_id(
            Gtk.TREE_SORTABLE_UNSORTED_SORT_COLUMN_ID, Gtk.SortType.ASCENDING
        )
        logger.debug("_populate_worker clear model")
        utils.clear_model(self.results_view)

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

        five_percent = int(nresults / 20) or 200
        steps_so_far = 0

        # iterate over slice of size "steps", yield every 5%
        added = set()
        for obj in itertools.chain(*groups):
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
            if steps_so_far % five_percent == 0:
                percent = float(steps_so_far) / float(nresults)
                if 0 < percent < 1.0:
                    bauble.gui.progressbar.set_fraction(percent)
                yield

        # avoid triggering on_selection_changed
        self.selection.handler_block(self._sc_sid)
        self.results_view.set_model(model)
        self.selection.handler_unblock(self._sc_sid)

    def append_children(self, model, parent, kids):
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

    def remove_row(self, value):
        """Remove a row from the results_view"""
        # NOTE used in testing...
        logger.info("remove_row called")

        model = self.results_view.get_model()
        for found in utils.search_tree_model(model, value):
            model.remove(found)

    @utils.timed_cache()
    def has_kids(self, value):
        """Expire and check for children

        Results are cached to avoid expiring too regularly"""
        # expire so that any external updates are picked up.
        # (e.g. another user has deleted while we are also using it.)
        self.session.expire(value)
        return value.has_children()

    @staticmethod
    @utils.timed_cache(size=20, secs=0.2)
    def count_kids(value):
        """Get the count of children.

        Minimally cached to avoid repeated database calls for same value.
        """
        return value.count_children()

    @staticmethod
    @utils.timed_cache(size=200, secs=0.2)
    def get_markup_pair(value):
        """Get the markup pair.

        Minimally cached to avoid repeated database calls for same value.
        """
        return value.search_view_markup_pair()

    def cell_data_func(self, _col, cell, model, treeiter, _data):
        # now update the the cell
        value = model[treeiter][0]

        # could not find anything message.
        if isinstance(value, str):
            cell.set_property("markup", value)
            return

        meta = self.row_meta[type(value)]
        try:
            if self.refresh:
                if meta.children is not None and self.has_kids(value):
                    path = model.get_path(treeiter)
                    # check if any items added/removed
                    if self.results_view.row_expanded(path):
                        if model.iter_n_children(treeiter) != self.count_kids(
                            value
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
            rep = self.get_markup_pair(value)
            try:
                main, substr = rep
            except ValueError:
                main = rep
                substr = f"({type(value).__name__})"
            cell.set_property(
                "markup",
                f"{_mainstr_tmpl % utils.nstr(main)}\n"
                f"{_substr_tmpl % utils.nstr(substr)}",
            )

        except (saexc.InvalidRequestError, ObjectDeletedError, TypeError) as e:
            logger.debug("cell_data_func: (%s)%s", type(e).__name__, e)

            GLib.idle_add(self.remove_row, value)

        except Exception as e:
            logger.error("cell_data_func: (%s)%s", type(e).__name__, e)
            raise

    def get_expanded_rows(self):
        """Get the TreePath to all the rows in the model that are expanded."""
        expanded_rows = []

        self.results_view.map_expanded_rows(
            lambda view, path: expanded_rows.append(path)
        )

        return expanded_rows

    def expand_to_all_rows(self, expanded_rows):
        """
        :param expanded_rows: a list of TreePaths to expand to
        """
        for path in expanded_rows:
            self.results_view.expand_to_path(path)

    def on_view_button_press(self, view, event):
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
            path, __, __, __ = pos
            if not view.get_selection().path_is_selected(path):
                return False
            # emulate 'cursor-changed' signal
            self.on_selection_changed(None)
            return True
        return False

    def on_view_button_release(self, view, event):
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
        if not selected or isinstance(selected[0], str):
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

    def update(self, *_args):
        """Expire all the children in the model, collapse everything, reexpand
        the rows to the previous state where possible.

        Infoboxes are updated in on_selection_changed which this should trigger
        """
        # NOTE log used in tests
        logger.debug("SearchView::update")
        model, tree_paths = self.selection.get_selected_rows()
        ref = None
        try:
            # try to get the reference to the selected object, if the
            # object has been deleted then we won't try to reselect it later
            ref = Gtk.TreeRowReference(model, tree_paths[0])
        except IndexError as e:
            logger.debug(
                "unable to get ref to selected object: %s(%s)",
                type(e).__name__,
                e,
            )

        self.session.expire_all()
        self.has_kids.clear_cache()  # pylint: disable=no-member

        expanded_rows = self.get_expanded_rows()

        self.results_view.collapse_all()

        # expand_to_all_rows will invalidate the ref so get the path first
        if not ref:
            return
        path = None
        if ref.valid():
            path = ref.get_path()
        self.expand_to_all_rows(expanded_rows)
        if path is not None:
            self.results_view.set_cursor(path)

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
        if not selected or isinstance(selected[0], str):
            return

        if call_back := self.row_meta[type(selected[0])].activated_callback:
            call_back(selected)

    def create_gui(self):
        """Create the interface."""
        logger.debug("SearchView::create_gui")
        # create the results view and info box
        self.results_view.set_headers_visible(False)
        self.results_view.set_fixed_height_mode(True)

        self.selection = self.results_view.get_selection()
        self.selection.set_mode(Gtk.SelectionMode.MULTIPLE)
        self.results_view.set_rubber_banding(True)

        renderer = Gtk.CellRendererText()
        renderer.set_fixed_height_from_font(2)
        renderer.set_property("ellipsize", Pango.EllipsizeMode.END)
        column = Gtk.TreeViewColumn("Name", renderer)
        column.set_sizing(Gtk.TreeViewColumnSizing.FIXED)
        column.set_cell_data_func(renderer, self.cell_data_func)
        self.results_view.append_column(column)

        # view signals
        self._sc_sid = self.selection.connect(
            "changed", self.on_selection_changed
        )

        self.results_view.connect("test-expand-row", self.on_test_expand_row)

        self.results_view.connect(
            "button-press-event", self.on_view_button_press
        )
        self.results_view.connect(
            "button-release-event", self.on_view_button_release
        )

        self.results_view.connect("row-activated", self.on_view_row_activated)


class Note:
    # pylint: disable=too-few-public-methods
    """temporary patch before we implement Notes as a plugin."""

    @classmethod
    def attached_to(cls, obj):
        """return the list of notes connected to obj"""

        try:
            return obj.notes
        except (AttributeError, DetachedInstanceError):
            return []


@Gtk.Template(filename=str(Path(paths.lib_dir(), "history_view.ui")))
class HistoryView(pluginmgr.View, Gtk.Box):
    """Show the tables row in the order they were last updated."""

    __gtype_name__ = "HistoryView"

    liststore = cast(Gtk.ListStore, Gtk.Template.Child())
    history_tv = cast(Gtk.TreeView, Gtk.Template.Child())

    TVC_OBJ = 0
    TVC_ID = 1
    TVC_TIMESTAMP = 2
    TVC_OPERATION = 3
    TVC_USER = 4
    TVC_TABLE = 5
    TVC_USER_FRIENDLY = 6
    STEP = 1000
    TRUNCATE = 100

    queries: dict[str, tuple[str, str]] = {}

    def __init__(self) -> None:
        logger.debug("HistoryView::__init__")
        super().__init__()

        # setup context_menu
        menu_model = Gio.Menu()
        revert_action_name = "revert_hist_to_selection"
        copy_values_action_name = "copy_hist_selection_values"
        copy_geojson_action_name = "copy_hist_selection_geojson"

        if bauble.gui:
            bauble.gui.add_action(
                revert_action_name, self.on_revert_to_history
            )
            bauble.gui.add_action(copy_values_action_name, self.on_copy_values)
            bauble.gui.add_action(
                copy_geojson_action_name, self.on_copy_geojson
            )

        revert = Gio.MenuItem.new(_("Revert to"), f"win.{revert_action_name}")
        copy_values = Gio.MenuItem.new(
            _("Copy values"), f"win.{copy_values_action_name}"
        )
        copy_geojson = Gio.MenuItem.new(
            _("Copy geojson"), f"win.{copy_geojson_action_name}"
        )
        menu_model.append_item(revert)
        menu_model.append_item(copy_values)
        menu_model.append_item(copy_geojson)

        self.context_menu = Gtk.Menu.new_from_model(menu_model)
        self.context_menu.attach_to_widget(self.history_tv)

        self.clone_hist_id = 0
        self.offset = 0
        self.hist_count = 0
        self.last_row_in_tree = 0

        self.last_arg = ""

        Gtk.Scrollable.get_vadjustment(self.history_tv).connect(
            "value-changed", self.on_history_tv_value_changed
        )

    def on_history_tv_value_changed(self, *_args) -> None:
        """When scrolling lazy load another batch of rows as needed.

        i.e. more than half way throught the the last batch and more rows
        remain
        """
        visible = self.history_tv.get_visible_range()
        if visible:
            tree_iter = self.liststore.get_iter(visible[1])
            bottom_line_id = int(self.liststore.get_value(tree_iter, 1))

            if (
                bottom_line_id - self.last_row_in_tree <= self.STEP / 2
                and self.hist_count > self.offset
            ):
                self.add_rows()

    @staticmethod
    def _cmp_items_key(val: tuple[str, object]) -> tuple[int, str]:
        """Sort by the key after putting id first, changes second and None
        values last.
        """
        k, v = val
        if k == "id":
            return (0, k)
        if isinstance(v, list):
            return (1, k)
        if v is None:
            return (3, k)
        return (2, k)

    def _shorten_list(self, lst: list) -> str:
        part1 = json.dumps(lst[0])
        part2 = json.dumps(lst[1])
        len1 = len(part1)
        len2 = len(part2)
        if len1 + len2 < self.TRUNCATE - 4:
            return f"[{part1}, {part2}]"
        if len1 < 10 and len2 > self.TRUNCATE - len1 - 4:
            short2 = shorten(
                part2,
                self.TRUNCATE - len1 - 4,
                placeholder="…",
            )
            return f"[{part1}, {short2}]"
        if len2 < 10 and len1 > self.TRUNCATE - len2 - 4:
            short1 = shorten(
                part1,
                self.TRUNCATE - len2 - 4,
                placeholder="…",
            )
            return f"[{short1}, {part2}]"
        perc = len1 / (len1 + len2)
        short1 = shorten(
            part1,
            round(self.TRUNCATE * perc) - 2,
            placeholder="…",
        )
        short2 = shorten(
            part2,
            round(self.TRUNCATE * (1 - perc)) - 2,
            placeholder="…",
        )
        return f"[{short1}, {short2}]"

    def add_row(self, item: db.History) -> None:
        if not (item.id and item.timestamp and item.values):
            return

        dct = dict(item.values)
        del dct["_created"]
        del dct["_last_updated"]

        geojson = dct.get("geojson")
        if geojson:
            if isinstance(geojson, list) and len(geojson) == 2:
                geojson = self._shorten_list(geojson)
            else:
                geojson = shorten(
                    json.dumps(geojson), self.TRUNCATE, placeholder="…"
                )
            del dct["geojson"]

        friendly = ", ".join(
            f"{k}: {repr('') if v is None else v}"
            for k, v in sorted(list(dct.items()), key=self._cmp_items_key)
        )
        friendly = "\n".join(textwrap.wrap(friendly, 200))
        frmt = prefs.prefs.get(prefs.datetime_format_pref)
        is_cloned = item.id <= self.clone_hist_id
        self.liststore.append(
            [
                item,
                str(item.id),
                item.timestamp.strftime(frmt),
                item.operation,
                item.user,
                item.table_name,
                friendly,
                geojson,
                is_cloned,
            ]
        )

    def get_selected_value(self) -> db.History | None:
        """Get the selected rows object from column 0."""
        model, itr = self.history_tv.get_selection().get_selected()
        if model is None or itr is None:
            return None
        return model[itr][0]

    @Gtk.Template.Callback()
    def on_button_release(self, _view, event: Gdk.EventButton) -> bool:
        if event.button != 3:
            return False

        self.context_menu.popup_at_pointer(event)
        return True

    def on_revert_to_history(self, _action, _paramm) -> None:
        selected = self.get_selected_value()
        if not (selected and selected.id):
            return

        if selected.id <= self.clone_hist_id:
            msg = (
                _(
                    "<b>WARNING: Can not revert past clone point</b>\n\nThis "
                    "database was cloned at line %s"
                )
                % self.clone_hist_id
            )
            utils.message_dialog(msg)
            return

        logger.debug(
            "reverting to selected %s id: %s",
            selected.table_name,
            selected.table_id,
        )

        if db.Session:
            with db.Session() as session:
                rows = (
                    session.query(db.History)
                    .filter(db.History.id >= selected.id)
                    .count()
                )

        msg = (
            _(
                "<b>CAUTUION: reverting database is permanent.</b>\n\nYou "
                "have selected to revert %s changes.\n\nDo you wish to "
                "proceed?"
            )
            % rows
        )
        if utils.yes_no_dialog(msg):
            if selected:
                db.History.revert_to(selected.id)
            self.update(self.last_arg)

    def on_copy_values(self, _action, _param) -> None:
        if selected := self.get_selected_value():
            if not selected.values:
                return
            values = dict(selected.values)
            if values.get("geojson"):
                del values["geojson"]
            string = json.dumps(values)
            if bauble.gui:
                bauble.gui.get_display_clipboard().set_text(string, -1)

    def on_copy_geojson(self, _action, _param) -> None:
        if selected := self.get_selected_value():
            if not selected.values:
                return
            string = json.dumps(selected.values.get("geojson"))
            if bauble.gui:
                bauble.gui.get_display_clipboard().set_text(string, -1)

    @classmethod
    def add_translation_query(
        cls, table_name: str, domain: str, query: str
    ) -> None:
        """Allows plugins to add search strings for the best domain for a
        selected history line's table name.
        """
        cls.queries[table_name] = (domain, query)

    @Gtk.Template.Callback()
    def on_row_activated(self, _tree, path, _column) -> None:
        """Search for the correct domain for the selected row's item.

        This generally will only work if the item is not deleted.
        """
        row = self.liststore[path]  # pylint: disable=unsubscriptable-object
        hist_obj = row[self.TVC_OBJ]
        table = row[self.TVC_TABLE]
        obj_id = hist_obj.table_id

        table, query = self.queries.get(
            table, (table, "{table} where id={obj_id}")
        )

        if table in search.strategies.MapperSearch.domains:
            query = query.format(table=table, obj_id=obj_id)
            if bauble.gui:
                bauble.gui.send_command(query)

    @staticmethod
    def get_expression() -> ParserElement:
        """Pyparsing parser for history searches."""
        operator = one_of("= != < <= > >= like contains has")
        on_operator = Literal("on")
        time_stamp_ident = Literal("timestamp")
        numeric_value = Regex(r"[-]?\d+(\.\d*)?([eE]\d+)?").set_parse_action(
            lambda _s, _l, t: [float(t[0])]
        )
        date_str = Regex(
            r"\d{1,4}[/.-]{1}\d{1,2}[/.-]{1}\d{1,4}"
        ).set_parse_action(lambda _s, _l, t: [str(t[0])])
        value = (
            quoted_string.set_parse_action(remove_quotes)
            | date_str
            | numeric_value
            | Word(printables)
        )
        _and = CaselessLiteral("and").suppress()
        identifier = Word(alphas + "_")
        ident_expression = Group(identifier + operator + value) | Group(
            time_stamp_ident + on_operator + value
        )
        to_sync = Literal("to_sync")
        expression = (
            to_sync + ZeroOrMore(_and + ident_expression)
        ) | ZeroOrMore(ident_expression + ZeroOrMore(_and + ident_expression))
        return expression

    def get_query_filters(self) -> list[ColumnElement]:
        """Parse the string provided in arg and return the equivalent as
        consumed by sqlalchemy query `filter()` method.
        """

        filters = []
        expression = self.get_expression()
        for part in expression.parse_string(self.last_arg, parse_all=True):
            if part == "to_sync":
                if self.clone_hist_id:
                    filters.append(db.History.id > self.clone_hist_id)
                else:
                    # show nothing if database doesn't appear to be a clone
                    filters.append(db.History.id.is_(None))
                continue
            if part[0] == "timestamp" and part[1] == "on":
                filters.append(self.get_on_timestamp_filter(part))
            else:
                attr = getattr(db.History, part[0])
                val = part[2]
                operation = search.operations.OPERATIONS[part[1]]
                filters.append(operation(attr, val))

        return filters

    def get_on_timestamp_filter(self, part: ParseResults) -> ColumnElement:
        """sqlalchemy query `filter()` statement specific to timestamp `on`
        searches
        """
        attr = getattr(db.History, part[0])
        try:
            val = float(part[2])
        except ValueError:
            val = part[2]
        date_val = search.clauses.get_datetime(val)
        today = date_val.astimezone(tz=timezone.utc)
        tomorrow = today + timedelta(1)
        return and_(attr >= today, attr < tomorrow)

    def update(self, *args: str | None) -> None:
        """Start to add the history items to the view."""

        self.liststore.clear()
        self.offset = 0
        self.hist_count = 0
        self.last_row_in_tree = 0
        self.last_arg = args[0] or ""

        if db.Session:
            with db.Session() as session:
                clone_hist_id = (
                    session.query(BaubleMeta.value)
                    .filter(BaubleMeta.name == "clone_history_id")
                    .scalar()
                )
                self.clone_hist_id = int(clone_hist_id or 0)
                self.hist_count = self.query(session).count()

        logger.debug("hist_count = %s", self.hist_count)
        self.add_rows()

    def query(self, session: Session) -> Query:
        """Given a session attach the appropriate query and filters."""
        query = session.query(db.History)
        if self.last_arg:
            query = query.filter(*self.get_query_filters())
        query = query.order_by(db.History.id.desc())
        return query

    def add_rows(self) -> None:
        """Add a batch of rows to the view."""
        if not db.Session:
            return
        try:
            with db.Session() as session:
                query = self.query(session)
                # add rows in small batches
                rows = query.offset(self.offset).limit(self.STEP).all()
                id_ = 0
                for row in rows:
                    self.add_row(row)
                    id_ = row.id
                self.last_row_in_tree = id_
                self.offset += self.STEP
                logger.debug("offset = %s", self.offset)
        except Exception as e:
            logger.debug("%s(%s)", type(e).__name__, e)
            msg = utils.xml_safe(e)
            details = utils.xml_safe(traceback.format_exc())
            if bauble.gui:
                self.show_error_box(msg, details)

    def show_error_box(self, msg: str, details: str) -> None:
        if bauble.gui:
            bauble.gui.show_error_box(msg, details)


class HistoryCommandHandler(pluginmgr.CommandHandler):
    command = "history"
    view: HistoryView | None = None

    def get_view(self) -> HistoryView:
        if not self.__class__.view:
            self.__class__.view = HistoryView()
        return self.__class__.view

    def __call__(self, cmd: str, arg: str | None) -> None:
        if self.view:
            self.view.update(arg)


pluginmgr.register_command(HistoryCommandHandler)


def select_in_search_results(obj):
    """Search the tree model for obj if it exists then select it if not
    then add it and select it.

    :param obj: the object the select
    :return: a Gtk.TreeIter to the selected row
    """
    check(obj is not None, "select_in_search_results: arg is None")
    view = bauble.gui.get_view()
    if not isinstance(view, SearchView):
        return None
    logger.debug(
        "select_in_search_results %s is in session %s",
        obj,
        obj in view.session,
    )
    model = view.results_view.get_model()
    found = utils.search_tree_model(model, obj)
    row_iter = None
    if len(found) > 0:
        row_iter = found[0]
    else:
        row_iter = model.append(None, [obj])
        model.append(row_iter, ["-"])
        # NOTE used in test...
        logger.debug("%s added to search results", obj)
    view.results_view.set_cursor(model.get_path(row_iter))
    return row_iter


class DefaultCommandHandler(pluginmgr.CommandHandler):
    command = [None]
    view = None

    def get_view(self):
        if self.__class__.view is None:
            self.__class__.view = SearchView()
        return self.__class__.view

    def __call__(self, cmd, arg):
        self.view.search(arg)
