# Copyright 2008-2010 Brett Adams
# Copyright 2015 Mario Frasca <mario@anche.no>.
# Copyright 2021-2022 Ross Demuth <rossdemuth123@gmail.com>
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

import itertools
from pathlib import Path
import sys
import traceback
import html
from ast import literal_eval
import threading
from collections import UserDict

import logging
logger = logging.getLogger(__name__)

from pyparsing import (ParseException,
                       oneOf,
                       quotedString,
                       removeQuotes,
                       Word,
                       ZeroOrMore,
                       printables,
                       CaselessLiteral,
                       Group,
                       alphas,
                       Regex)

from gi.repository import Gtk
from gi.repository import Gdk
from gi.repository import Gio
from gi.repository import GLib
from gi.repository import Pango

from sqlalchemy.orm import object_session
from sqlalchemy.orm.exc import ObjectDeletedError
import sqlalchemy.exc as saexc

import bauble
from bauble import db
from bauble.error import check
from bauble import paths
from bauble import pluginmgr
from bauble import prefs
from bauble import search
from bauble import utils
from bauble.utils.web import link_button_factory
from bauble import pictures_view

# use different formatting template for the result view depending on the
# platform
_mainstr_tmpl = '<b>%s</b>'
if sys.platform == 'win32':
    _substr_tmpl = '%s'
else:
    _substr_tmpl = '<small>%s</small>'

INFOBOXPAGE_WIDTH_PREF = 'infobox.page_width'
"""The preferences key for storing the InfoBoxPage width."""

SEARCH_POLL_SECS_PREF = 'bauble.search.poll_secs'
"""Preference key for how often to poll the database in search view"""

SEARCH_CACHE_SIZE_PREF = 'bauble.search.cache_size'
"""Preference key for size of search view's has_kids cache"""

SEARCH_REFRESH_PREF = 'bauble.search.refresh'
"""Preference key, should search view attempt to refresh from the database
regularly
"""

SEARCH_COUNT_FAST_PREF = 'bauble.search.count_fast'
"""Set multiprocessing processes on large searches to count top level count,

Values: int (number of processes), bool (use multiprocessing),
    str (just provide length of results)
"""


class Action:
    # pylint: disable=too-few-public-methods, too-many-arguments
    """SearchView context menu items."""
    def __init__(self,
                 name,
                 label,
                 callback=None,
                 accelerator=None,
                 multiselect=False):
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
            self.action.connect('activate', handler, callback)
            self.connected = True


class InfoExpander(Gtk.Expander):
    """An abstract class that is really just a generic expander with a vbox
    to extend this you just have to implement the update() method
    """

    # preference for storing the expanded state
    EXPANDED_PREF = None

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
        utils.set_widget_value(self.widgets[widget_name], value,
                               markup, default)

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

    EXPANDED_PREF = 'infobox.generic_properties_expanded'

    def __init__(self):
        super().__init__(_('Properties'))
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
        self.id_data = Gtk.Label(label='--')
        self.id_data.set_xalign(0)
        self.id_data.set_yalign(0.5)
        id_event.add(self.id_data)
        table.attach(id_event, 1, 0, 1, 1)
        id_event.connect('button_press_event', self.on_id_button_press)

        # object type
        type_label = Gtk.Label(label="<b>" + _("Type:") + "</b>")
        type_label.set_use_markup(True)
        type_label.set_xalign(1)
        type_label.set_yalign(0.5)
        self.type_data = Gtk.Label(label='--')
        self.type_data.set_xalign(0)
        self.type_data.set_yalign(0.5)
        table.attach(type_label, 0, 1, 1, 1)
        table.attach(self.type_data, 1, 1, 1, 1)

        # date created
        created_label = Gtk.Label(label="<b>" + _("Date created:") + "</b>")
        created_label.set_use_markup(True)
        created_label.set_xalign(1)
        created_label.set_yalign(0.5)
        self.created_data = Gtk.Label(label='--')
        self.created_data.set_xalign(0)
        self.created_data.set_yalign(0.5)
        table.attach(created_label, 0, 2, 1, 1)
        table.attach(self.created_data, 1, 2, 1, 1)

        # date last updated
        updated_label = Gtk.Label(label="<b>" + _("Last updated:") + "</b>")
        updated_label.set_use_markup(True)
        updated_label.set_xalign(1)
        updated_label.set_yalign(0.5)
        self.updated_data = Gtk.Label(label='--')
        self.updated_data.set_xalign(0)
        self.updated_data.set_yalign(0.5)
        table.attach(updated_label, 0, 3, 1, 1)
        table.attach(self.updated_data, 1, 3, 1, 1)

        box = Gtk.Box()
        box.pack_start(table, expand=False, fill=False, padding=0)
        self.vbox.pack_start(box, expand=False, fill=False, padding=0)

    def update(self, row):
        """"Update the widget in the expander."""
        self.set_expanded(prefs.prefs.get(self.EXPANDED_PREF, True))
        self.id_data.set_text(str(row.id))
        self.type_data.set_text(str(type(row).__name__))
        fmat = prefs.prefs.get(prefs.datetime_format_pref)
        # pylint: disable=protected-access
        self.created_data.set_text(
            row._created.strftime(fmat) if row._created else '')
        self.updated_data.set_text(
            row._last_updated.strftime(fmat) if row._last_updated else '')

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
    """A `Gtk.ScrolledWindow` that contains `bauble.view.InfoExpander` objects.
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
        self.connect('size-allocate', self.on_resize)

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
        self.set_property('show-border', False)
        if not tabbed:
            page = InfoBoxPage()
            self.insert_page(page, tab_label=None, position=0)
            self.set_property('show-tabs', False)
        self.set_current_page(0)
        self.connect('switch-page', self.on_switch_page)

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

    EXPANDED_PREF = 'infobox.generic_links_expanded'

    def __init__(self, notes=None, links=None):
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
        self.buttons = []
        for link in links:
            try:
                btn = link_button_factory(link)
                self.buttons.append(btn)
                self.link_box.pack_start(btn, False, False, 0)
            except Exception as e:  # pylint: disable=broad-except
                # broad except, user data.
                logger.debug('wrong link definition %s, %s(%s)', link,
                             type(e).__name__, e)

    def update(self, row):
        self.set_expanded(prefs.prefs.get(self.EXPANDED_PREF, True))
        hide = True
        separator = False
        for btn in self.buttons:
            btn.set_string(row)
            hide = False
        for child in self.dynamic_box.get_children():
            self.dynamic_box.remove(child)
        if self.notes:
            for note in getattr(row, self.notes):
                if note.category == '<picture>':
                    continue
                for label, url in utils.get_urls(note.note):
                    if not label:
                        label = url
                    try:
                        link = {
                            'title': label,
                            'tooltip': f'from note of category {note.category}'
                        }
                        button = link_button_factory(link)
                        button.set_uri(url)
                        self.dynamic_box.pack_start(button, False, False, 0)
                        separator = True
                        hide = False
                    except Exception as e:  # pylint: disable=broad-except
                        # broad except, user data.
                        logger.debug('wrong link definition %s, %s(%s)', link,
                                     type(e).__name__, e)

            if separator and self.buttons:
                sep = Gtk.Separator(margin_start=15, margin_end=15)
                self.dynamic_box.pack_start(sep, False, False, 0)

        if hide:
            utils.hide_widgets([self, self._sep])
        else:
            utils.unhide_widgets([self, self._sep])
            self.show_all()


class AddOneDot(threading.Thread):

    @staticmethod
    def callback(dotno):
        statusbar = bauble.gui.widgets.statusbar
        sbcontext_id = statusbar.get_context_id('searchview.nresults')
        statusbar.pop(sbcontext_id)
        statusbar.push(sbcontext_id, _('counting results') + '.' * dotno)

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
    """multiproccessing worker to get top level count for a group of items.

    :param url: database url as a string.
    :param klass: sqlalchemy table class.
    :param ids: a list of id numbers to query.
    """
    if sys.platform == 'darwin':
        # only on macos
        # TODO need to investigate this further.  Dock icons pop up for every
        # process produced.  The below suppresses the icon AFTER it has already
        # popped up meaning you get a bunch of icons appearing for a
        # around a second and then disappearing.
        import AppKit
        AppKit.NSApp.setActivationPolicy_(1)   # 2 also works
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
        logger.debug('%s (%s)', type(e).__name__, e)
        self.set_statusbar(f'{type(e).__name__} error counting results')

    def set_statusbar(self, value):
        """Put the results on the statusbar."""
        if bauble.gui:
            def sb_call(text):
                statusbar = bauble.gui.widgets.statusbar
                sbcontext_id = statusbar.get_context_id('searchview.nresults')
                statusbar.pop(sbcontext_id)
                statusbar.push(sbcontext_id, text)
            if not self.__cancel:  # check whether caller asks to cancel
                self.dots_thread.cancel()
                GLib.idle_add(sb_call, value)
        else:
            self.dots_thread.cancel()
            logger.debug("showing text %s", value)
        # NOTE log used in tests
        logger.debug('counting results class:%s complete', self.klass.__name__)

    def run(self):
        """Runs thread, decide whether to use multiprocessing or not.

        Results are handed to self.callback either by the multiprocessing
        worker or directly
        """
        count_fast = prefs.prefs.get(SEARCH_COUNT_FAST_PREF, True)
        # NOTE these figures were arrived at by trial and error on a particular
        # dataset. No guarantee they are ideal in all situations.
        if self.klass.__name__ in ['Family', 'Location']:
            max_ids = 30
            chunk_size = 10
        else:
            max_ids = 300
            chunk_size = 100
        if count_fast and len(self.ids) > max_ids:
            from multiprocessing import get_context
            from functools import partial
            proc = partial(multiproc_counter, str(db.engine.url), self.klass)
            processes = None
            # pylint: disable=unidiomatic-typecheck # bool is subclass of int,
            # isinstance won't work.
            if type(count_fast) is int:
                processes = count_fast
            logger.debug('counting results multiprocessing, processes=%s',
                         processes)
            with get_context('spawn').Pool(processes) as pool:
                amap = pool.map_async(proc,
                                      utils.chunks(self.ids, chunk_size),
                                      callback=self.callback,
                                      error_callback=self.error)
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


@Gtk.Template(filename=str(Path(paths.lib_dir(), 'search_view.ui')))
class SearchView(pluginmgr.View, Gtk.Box):
    """The SearchView is the main view for Ghini.

    Manages the search results returned when search strings are entered into
    the main text entry.
    """

    __gtype_name__ = 'SearchView'

    bottom_notebook = Gtk.Template.Child()
    results_view = Gtk.Template.Child()
    info_pane = Gtk.Template.Child()
    pic_pane = Gtk.Template.Child()

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

            def set(self, children=None, infobox=None, context_menu=None):
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
                self.actions = []
                if self.context_menu:
                    self.actions = [x for x in self.context_menu if
                                    isinstance(x, Action)]

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

    row_meta = ViewMeta()
    bottom_info = ViewMeta()

    context_menu_callbacks = set()
    """Callbacks for constructing context menus for selected items.
    Callbacks should recieve a single argument containing the selected items
    and return a single menu section of type Gio.Menu
    """

    cursor_changed_callbacks = set()
    """Callbacks called each time the cursor changes"""

    def __init__(self):
        logger.debug('SearchView::__init__')
        super().__init__()

        self.create_gui()

        pictures_view.floating_window = pictures_view.PicturesView(
            parent=self.pic_pane
        )

        # the context menu cache holds the context menus by type in the results
        # view so that we don't have to rebuild them every time
        self.context_menu_cache = {}
        self.infobox_cache = {}
        self.infobox = None

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

    def add_notes_page_to_bottom_notebook(self):
        """add notebook page for notes

        this is a temporary function, will be removed when notes are
        implemented as a plugin. then notes will be added with the
        generic add_page_to_bottom_notebook.
        """
        glade_name = str(Path(paths.lib_dir(), 'notes_page.glade'))
        widgets = utils.BuilderWidgets(glade_name)
        page = widgets['notes_scrolledwindow']
        # create the label object
        label = Gtk.Label(label='Notes')
        self.bottom_notebook.append_page(page, label)
        self.bottom_info[Note] = {
            'fields_used': ['date', 'user', 'category', 'note'],
            'tree': page.get_children()[0],
            'label': label,
            'name': _('Notes'),
        }
        widgets.notes_treeview.connect("row-activated",
                                       self.on_note_row_activated)

    def on_note_row_activated(self, tree, path, _column):
        try:
            # retrieve the selected row from the results view (we know it's
            # one), and we only need it's domain name
            selected = self.get_selected_values()[0]
            domain = selected.__class__.__name__.lower()
            # retrieve the activated row
            row = tree.get_model()[path]
            cat = None if row[2] == '' else repr(row[2])
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
            logger.debug('on_note_row_actived %s(%s)', type(e).__name__, e)
        return None

    def add_page_to_bottom_notebook(self, bottom_info):
        """add notebook page for a plugin class."""
        glade_name = bottom_info['glade_name']
        widgets = utils.BuilderWidgets(glade_name)
        page = widgets[bottom_info['page_widget']]
        # 2: detach it from parent (its container)
        widgets.remove_parent(page)
        # 3: create the label object
        label = Gtk.Label(label=bottom_info['name'])
        # 4: add the page, non sensitive
        self.bottom_notebook.append_page(page, label)
        # 5: store the values for later use
        bottom_info['tree'] = page.get_children()[0]
        if row_activated := bottom_info.get('row_activated'):
            bottom_info['tree'].connect("row-activated",
                                        row_activated)
        bottom_info['label'] = label

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
            self.pic_pane.get_child2().hide()
            return

        row = selected_values[0]  # the selected row

        # loop over bottom_info plugin classes (eg: Tag)
        for klass, bottom_info in self.bottom_info.items():
            if 'label' not in bottom_info:  # late initialization
                self.add_page_to_bottom_notebook(bottom_info)
            label = bottom_info['label']
            if not hasattr(klass, 'attached_to'):
                logging.warning('class %s does not implement attached_to',
                                klass)
                continue
            objs = klass.attached_to(row)
            model = bottom_info['tree'].get_model()
            model.clear()
            if not objs or not isinstance(objs, list):
                label.set_use_markup(False)
                label.set_label(bottom_info['name'])
            else:
                label.set_use_markup(True)
                label.set_label(f'<b>{bottom_info["name"]}</b>')
                for obj in objs:
                    model.append([str(getattr(obj, k) or '')
                                  for k in bottom_info['fields_used']])
        self.bottom_notebook.show()

    def update_infobox(self, selected_values):
        """Sets the infobox according to the currently selected row.

        no infobox is shown if nothing is selected
        """
        # start of update_infobox
        # NOTE log used in tests
        logger.debug('SearchView::update_infobox')
        if not selected_values or not selected_values[0]:
            self.set_infobox_from_row(None)
            return

        if object_session(selected_values[0]) is None:
            logger.debug('cannot populate info box from detached object')
            return

        sensitive = len(selected_values) == 1

        try:
            # send an object (e.g. a Plant instance)
            self.set_infobox_from_row(selected_values[0], sensitive)
        except Exception as e:  # pylint: disable=broad-except
            # if an error occurrs, log it and empty infobox.
            logger.debug('%s(%s)', type(e).__name__, e)
            logger.debug(traceback.format_exc())
            logger.debug(selected_values)
            self.set_infobox_from_row(None)

    def set_infobox_from_row(self, row, sensitive=True):
        """implement the logic for update_infobox"""

        logger.debug('set_infobox_from_row: %s --  %s', row, repr(row))
        # remove the current infobox if there is one and it is not needed
        if row is None:
            if (self.infobox is not None and
                    self.infobox.get_parent() == self.info_pane):
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
            logger.debug('setting pane position to %s', pane_pos)
            self.info_pane.set_position(pane_pos)

        selected_type = type(row)
        # if we have already created an infobox of this type:
        new_infobox = self.infobox_cache.get(selected_type)

        if not new_infobox:
            # it might be in cache under different name
            for infobox in self.infobox_cache.values():
                if isinstance(infobox, self.row_meta[selected_type].infobox):
                    logger.debug('found same infobox under different name')
                    new_infobox = infobox
            # otherwise create one and put in the infobox_cache
            if not new_infobox:
                logger.debug('not found infobox, we make a new one')
                new_infobox = self.row_meta[selected_type].infobox()
            self.infobox_cache[selected_type] = new_infobox

        logger.debug('created or retrieved infobox %s %s',
                     type(new_infobox).__name__, new_infobox)

        # remove any old infoboxes connected to the pane
        if (self.infobox is not None and type(self.infobox) is not
                type(new_infobox)):
            if self.infobox.get_parent() == self.info_pane:
                self.info_pane.remove(self.infobox)

        # update the infobox and put it in the pane
        self.infobox = new_infobox
        if self.infobox is not None:
            self.infobox.update(row)
            self.info_pane.pack2(self.infobox, resize=False, shrink=True)
            self.infobox.set_sensitive(sensitive)
            self.info_pane.show_all()

    def get_selected_values(self):
        """Get the values in all the selected rows."""
        model, rows = self.results_view.get_selection().get_selected_rows()
        if model is None or rows is None:
            return None
        return [model[row][0] for row in rows]

    def on_selection_changed(self, _tree_selection):
        """Update the infobox and bottom notebooks. Switch context_menus,
        actions and accelerators depending on the type of the rows selected.
        """
        # NOTE log used in tests
        logger.debug('SearchView::on_selection_changed')
        # grab values once
        selected_values = self.get_selected_values()
        # update all forward-looking info boxes
        self.update_infobox(selected_values)
        # update all backward-looking info boxes
        self.update_bottom_notebook(selected_values)

        self.update_context_menus(selected_values)

        for callback in self.cursor_changed_callbacks:
            callback(selected_values)

    def on_action_activate(self, _action, _param, call_back):
        result = False
        try:
            values = self.get_selected_values()
            result = call_back(values)
        except Exception as e:   # pylint: disable=broad-except
            msg = utils.xml_safe(str(e))
            trace = utils.xml_safe(traceback.format_exc())
            utils.message_details_dialog(
                msg, trace, Gtk.MessageType.ERROR)
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

        pictures_view.floating_window.set_selection(selected_values)

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

                action.connect('activate', self.on_action_activate,
                               action.callback)
                app = Gio.Application.get_default()
                app.set_accels_for_action(f'win.{action.name}',
                                          [action.accelerator])

            menu_item = Gio.MenuItem.new(action.label,
                                         f'win.{action.name}')
            self.context_menu_model.append_item(menu_item)

            if ((len(selected_values) > 1 and action.multiselect) or
                    len(selected_values) == 1):
                action.action.set_enabled(True)
            else:
                action.action.set_enabled(False)

        copy_selection_action_name = 'copy_selection_strings'

        if (bauble.gui and not
                bauble.gui.lookup_action(copy_selection_action_name)):
            bauble.gui.add_action(copy_selection_action_name,
                                  self.on_copy_selection)

        apply_active_tag_menu_item = Gio.MenuItem.new(
            _('Copy Selection'), f'win.{copy_selection_action_name}'
        )
        self.context_menu_model.append_item(apply_active_tag_menu_item)

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
                pref_key = f'copy_templates.{domain}'
                template_str = prefs.prefs.get(
                    pref_key, '${value}, ${type(value).__name__}'
                )
                template = Template(template_str)
                out.append(template.render(value=value))
        except Exception as e:  # pylint: disable=broad-except
            logger.debug("%s(%s)", type(e).__name__, e)
            msg = (_('Copy error.  Check your copy_templates in Preferences?'
                     '\n\n%s') % utils.xml_safe(str(e)))
            utils.message_details_dialog(msg, traceback.format_exc(),
                                         typ=Gtk.MessageType.ERROR)

        string = '\n'.join(out)
        if bauble.gui:
            bauble.gui.get_display_clipboard().set_text(string, -1)
            return None
        # NOTE used in testing
        return string

    def search(self, text):
        """search the database using text"""
        # set the text in the entry even though in most cases the entry already
        # has the same text in it, this is in case this method was called from
        # outside the class so the entry and search results match
        logger.debug('SearchView.search(%s)', text)
        error_msg = None
        error_details_msg = None
        # stop whatever it might still be doing
        self.cancel_threads()
        self.session.close()
        # clear the caches to avoid stale items.
        self.has_kids.clear_cache()  # pylint: disable=no-member
        self.count_kids.clear_cache()  # pylint: disable=no-member
        self.get_markup_pair.clear_cache()  # pylint: disable=no-member
        self.session = db.Session()
        bold = '<b>%s</b>'
        results = []
        try:
            results = search.search(text, self.session)
        except ParseException as err:
            error_msg = _('Error in search string at column %s') % err.column
        except Exception as e:  # pylint: disable=broad-except
            logger.debug(traceback.format_exc())
            error_msg = _('** Error: %s') % utils.xml_safe(e)
            error_details_msg = utils.xml_safe(traceback.format_exc())

        if error_msg:
            bauble.gui.show_error_box(error_msg, error_details_msg)
            return

        # not error
        utils.clear_model(self.results_view)
        if bauble.gui:
            statusbar = bauble.gui.widgets.statusbar
        else:
            # for testing...
            statusbar = Gtk.Statusbar()
        sbcontext_id = statusbar.get_context_id('searchview.nresults')
        statusbar.pop(sbcontext_id)
        if len(results) == 0:
            model = Gtk.ListStore(str)
            msg = bold % html.escape(
                _('Could not find anything for search: "%s"') % text)
            model.append([msg])
            self.results_view.set_model(model)
        else:
            statusbar.push(sbcontext_id, _("Retrieving %s search "
                                           "results…") % len(results))
            if len(results) > 30000:
                msg = _('This query returned %s results.  It may take a '
                        'while to display all the data. Are you sure you '
                        'want to continue?') % len(results)
                if not utils.yes_no_dialog(msg):
                    return
            self.populate_results(results)
            statusbar.pop(sbcontext_id)
            statusbar.push(sbcontext_id, _('counting results'))
            count_fast = prefs.prefs.get(SEARCH_COUNT_FAST_PREF, True)
            if isinstance(count_fast, str):
                statusbar.push(sbcontext_id,
                               _('size of result: %s') % len(results))
            elif len(set(item.__class__ for item in results)) == 1:
                dots_thread = self.start_thread(AddOneDot())
                self.start_thread(CountResultsTask(
                    results[0].__class__, [i.id for i in results],
                    dots_thread))
            else:
                statusbar.push(sbcontext_id,
                               _('size of non homogeneous result: %s') %
                               len(results))
            self.results_view.set_cursor(0)

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
        else:
            self.append_children(model,
                                 treeiter,
                                 sorted(kids, key=utils.natsort_key))
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
        model.set_sort_column_id(Gtk.TREE_SORTABLE_UNSORTED_SORT_COLUMN_ID,
                                 Gtk.SortType.ASCENDING)
        logger.debug('_populate_worker clear model')
        utils.clear_model(self.results_view)

        groups = []

        # sort by type so that groupby works properly
        results = sorted(results, key=lambda x: str(type(x)))

        for _key, group in itertools.groupby(results, key=type):
            # return groups by type and natural sort each of the
            # groups by their strings
            groups.append(sorted(group, key=utils.natsort_key, reverse=True))

        # sort the groups by type so we more or less always get the
        # results by type in the same order
        groups = sorted(groups, key=lambda x: str(type(x[0])), reverse=True)

        five_percent = int(nresults / 20) or 200
        steps_so_far = 0

        # iterate over slice of size "steps", yield after adding each
        # slice to the model
        added = set()
        for obj in itertools.chain(*groups):
            if obj in added:  # only add unique object
                continue
            added.add(obj)
            parent = model.prepend(None, [obj])
            steps_so_far += 1
            if (not self.refresh and self.row_meta[type(obj)].children is not
                    None):
                model.prepend(parent, ['-'])
            if steps_so_far % five_percent == 0:
                percent = float(steps_so_far) / float(nresults)
                if 0 < percent < 1.0:
                    bauble.gui.progressbar.set_fraction(percent)
                yield
        self.results_view.freeze_child_notify()
        self.results_view.set_model(model)
        self.results_view.thaw_child_notify()

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
                if (self.row_meta[type(kid)].children is not None and
                        kid.has_children()):
                    model.append(itr, ['-'])
            else:
                if self.row_meta[type(kid)].children is not None:
                    model.append(itr, ['-'])

    def remove_row(self, value):
        """Remove a row from the results_view"""
        # NOTE used in testing...
        logger.info('remove_row called')

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
            cell.set_property('markup', value)
            return

        meta = self.row_meta[type(value)]
        try:
            if self.refresh:
                if (meta.children is not None and self.has_kids(value)):
                    path = model.get_path(treeiter)
                    # check if any new items added externally
                    if self.results_view.row_expanded(path):
                        if (model.iter_n_children(treeiter) !=
                                self.count_kids(value)):
                            self.on_test_expand_row(self.results_view,
                                                    treeiter,
                                                    path)
                            self.results_view.expand_to_path(path)
                    elif not model.iter_has_child(treeiter):
                        model.prepend(treeiter, ['-'])
                else:
                    self.remove_children(model, treeiter)
            rep = self.get_markup_pair(value)
            try:
                main, substr = rep
            except ValueError:
                main = rep
                substr = f'({type(value).__name__})'
            cell.set_property('markup',
                              f'{_mainstr_tmpl % utils.nstr(main)}\n'
                              f'{_substr_tmpl % utils.nstr(substr)}')

        except (saexc.InvalidRequestError, ObjectDeletedError, TypeError) as e:
            logger.debug('cell_data_func: (%s)%s', type(e).__name__, e)

            GLib.idle_add(self.remove_row, value)

        except Exception as e:
            logger.error('cell_data_func: (%s)%s', type(e).__name__, e)
            raise

    def get_expanded_rows(self):
        """Get all the rows in the model that are expanded """
        expanded_rows = []

        def expand(view, path):
            expanded_rows.append(Gtk.TreeRowReference(view.get_model(), path))

        self.results_view.map_expanded_rows(expand)
        # seems to work better if we passed the reversed rows to
        # self.expand_to_all_refs
        expanded_rows.reverse()
        return expanded_rows

    def expand_to_all_refs(self, references):
        """
        :param references: a list of TreeRowReferences to expand to

        Note: This method calls get_path() on each
        Gtk.TreeRowReference in <references> which apparently
        invalidates the reference.
        """
        for ref in references:
            if ref.valid():
                self.results_view.expand_to_path(ref.get_path())

    def on_view_button_press(self, view, event):
        """Ignore the mouse right-click event.

        This makes sure that we don't remove the multiple selection on a
        right click.
        """
        if event.button == 1:
            self.btn_1_timer = (event.time, int(event.x), int(event.y))
            logger.debug('button 1 timer: %s', self.btn_1_timer)

        logger.debug('button press event: %s type: %s button: %s', event,
                     event.type, event.button)
        if event.button == 3:
            pos = view.get_path_at_pos(int(event.x), int(event.y))
            # NOTE used in test...
            logger.debug('view button 3 press, pos = %s', pos)
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
        logger.debug('button release event: %s type: %s button: %s', event,
                     event.type, event.button)
        logger.debug('button 1 timer: %s', self.btn_1_timer)

        # imitate right button on long (> 1 sec) press - targets tablet use
        if (event.button == 1 and
                event.time - self.btn_1_timer[0] > 1000 and
                self.btn_1_timer[1] == int(event.x) and
                self.btn_1_timer[2] == int(event.y)):
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

    def update(self, *_args):
        """Expire all the children in the model, collapse everything, reexpand
        the rows to the previous state where possible.

        Infoboxes are update in on_selection_changed which this should trigger.
        """
        # NOTE log used in tests
        logger.debug('SearchView::update')
        selection = self.results_view.get_selection()
        model, tree_paths = selection.get_selected_rows()
        ref = None
        try:
            # try to get the reference to the selected object, if the
            # object has been deleted then we won't try to reselect it later
            ref = Gtk.TreeRowReference(model, tree_paths[0])
        except IndexError as e:
            logger.debug('unable to get ref to selected object: %s(%s)',
                         type(e).__name__, e)

        self.session.expire_all()
        self.has_kids.clear_cache()  # pylint: disable=no-member

        expanded_rows = self.get_expanded_rows()

        self.results_view.collapse_all()

        # expand_to_all_refs will invalidate the ref so get the path first
        if not ref:
            return
        path = None
        if ref.valid():
            path = ref.get_path()
        self.expand_to_all_refs(expanded_rows)
        self.results_view.set_cursor(path)

    @staticmethod
    def on_view_row_activated(view, path, column):
        """Expand the row on activation."""
        logger.debug("SearchView::on_view_row_activated %s %s %s", view, path,
                     column)
        view.expand_row(path, False)

    def create_gui(self):
        """Create the interface."""
        logger.debug('SearchView::create_gui')
        # create the results view and info box
        self.results_view.set_headers_visible(False)
        # self.results_view.set_rules_hint(True)  # depricated
        self.results_view.set_fixed_height_mode(True)

        selection = self.results_view.get_selection()
        selection.set_mode(Gtk.SelectionMode.MULTIPLE)
        self.results_view.set_rubber_banding(True)

        renderer = Gtk.CellRendererText()
        renderer.set_fixed_height_from_font(2)
        renderer.set_property('ellipsize', Pango.EllipsizeMode.END)
        column = Gtk.TreeViewColumn("Name", renderer)
        column.set_sizing(Gtk.TreeViewColumnSizing.FIXED)
        column.set_cell_data_func(renderer, self.cell_data_func)
        self.results_view.append_column(column)

        # view signals
        results_view_selection = self.results_view.get_selection()
        results_view_selection.connect('changed', self.on_selection_changed)

        self.results_view.connect("test-expand-row",
                                  self.on_test_expand_row)

        self.results_view.connect("button-press-event",
                                  self.on_view_button_press)
        self.results_view.connect("button-release-event",
                                  self.on_view_button_release)

        self.results_view.connect("row-activated",
                                  self.on_view_row_activated)


class Note:
    # pylint: disable=too-few-public-methods
    """temporary patch before we implement Notes as a plugin."""

    @classmethod
    def attached_to(cls, obj):
        """return the list of notes connected to obj"""

        if hasattr(obj, 'notes') and obj.notes:
            return obj.notes
        return []


class AppendThousandRows(threading.Thread):

    def __init__(self, view, arg=None, group=None, **kwargs):
        super().__init__(group=group, target=None, name=None)
        self.__stopped = threading.Event()
        self.arg = arg
        self.view = view

    def callback(self, rows):
        for row in rows:
            self.view.add_row(row)

    def cancel_callback(self):
        row = [None]
        row += ['---'] * 6
        row[4] = '** ' + _('interrupted') + ' **'
        self.view.liststore.append(row)

    def cancel(self):
        self.__stopped.set()

    def get_query_filters(self):
        """Parse the string provided in arg and return the equivalent as
        consumed by sqlalchemy query `filter()` method."""
        operator = oneOf('= != < > like contains has')
        numeric_value = Regex(
            r'[-]?\d+(\.\d*)?([eE]\d+)?'
        ).setParseAction(lambda s, l, t: [float(t[0])])
        value = (quotedString.setParseAction(removeQuotes) |
                 numeric_value |
                 Word(printables))
        and_ = CaselessLiteral("and").suppress()
        identifier = Word(alphas + '_')
        ident_expression = Group(identifier + operator + value)
        expression = ident_expression + ZeroOrMore(and_ + ident_expression)

        filters = []
        for part in expression.parseString(self.arg):
            attr = getattr(db.History, part[0])
            val = part[2]
            operation = search.OPERATIONS.get(part[1])
            filters.append(operation(attr, val))

        return filters

    def run(self):
        session = db.Session()
        query = session.query(db.History)
        if self.arg:
            query = query.filter(*self.get_query_filters())
        query = query.order_by(db.History.timestamp.desc())
        # add rows in small batches
        offset = 0
        step = 200
        count = query.count()
        while offset < count and not self.__stopped.is_set():
            rows = query.offset(offset).limit(step).all()
            GLib.idle_add(self.callback, rows)
            offset += step
        session.close()
        if offset < count:
            GLib.idle_add(self.cancel_callback)


@Gtk.Template(filename=str(Path(paths.lib_dir(), 'history_view.ui')))
class HistoryView(pluginmgr.View, Gtk.Box):
    """Show the tables row in the order they were last updated."""

    __gtype_name__ = 'HistoryView'

    liststore = Gtk.Template.Child()
    history_tv = Gtk.Template.Child()

    TVC_OBJ = 0
    TVC_TIMESTAMP = 1
    TVC_OPERATION = 2
    TVC_USER = 3
    TVC_TABLE = 4
    TVC_USER_FRIENDLY = 5

    queries = {}

    def __init__(self):
        logger.debug('HistoryView::__init__')
        super().__init__()

        # setup context_menu
        menu_model = Gio.Menu()
        copy_values_action_name = 'copy_hist_selection_values'
        copy_geojson_action_name = 'copy_hist_selection_geojson'

        if bauble.gui:
            bauble.gui.add_action(copy_values_action_name,
                                  self.on_copy_values)
            bauble.gui.add_action(copy_geojson_action_name,
                                  self.on_copy_geojson)

        copy_values = Gio.MenuItem.new(
            _('Copy values'), f'win.{copy_values_action_name}'
        )
        copy_geojson = Gio.MenuItem.new(
            _('Copy geojson'), f'win.{copy_geojson_action_name}'
        )
        menu_model.append_item(copy_values)
        menu_model.append_item(copy_geojson)

        self.context_menu = Gtk.Menu.new_from_model(menu_model)
        self.context_menu.attach_to_widget(self.history_tv)

    def cmp_items_key(self, val):
        """Sort by the key after putting id first, changes second and None
        values last.
        """
        k, v = val
        if k == 'id':
            return (0, k)
        if isinstance(self.show_typed_value(v), list):
            return (1, k)
        if v == 'None':
            return (3, k)
        return (2, k)

    @staticmethod
    def show_typed_value(v):
        try:
            return literal_eval(v)
        except (ValueError, SyntaxError):
            # most likely a string
            return repr(v)

    def add_row(self, item):
        dct = literal_eval(item.values)
        del dct['_created']
        del dct['_last_updated']
        friendly = ', '.join(f"{k}: {self.show_typed_value(v) or repr('')}"
                             for k, v in sorted(list(dct.items()),
                                                key=self.cmp_items_key))
        frmt = prefs.prefs.get(prefs.datetime_format_pref)
        self.liststore.append([
            item,
            item.timestamp.strftime(frmt),
            item.operation,
            item.user,
            item.table_name,
            friendly,
            str(item.geojson or ''),
        ])

    def get_selected_value(self):
        """Get the selected rows object from column 0."""
        model, itr = self.history_tv.get_selection().get_selected()
        if model is None or itr is None:
            return None
        return model[itr][0]

    @Gtk.Template.Callback()
    def on_button_release(self, _view, event):
        if event.button != 3:
            return False

        self.context_menu.popup_at_pointer(event)
        return True

    def on_copy_values(self, _action, _param):
        if selected := self.get_selected_value():
            string = str(selected.values)
            if bauble.gui:
                bauble.gui.get_display_clipboard().set_text(string, -1)

    def on_copy_geojson(self, _action, _param):
        if selected := self.get_selected_value():
            string = str(selected.geojson)
            if bauble.gui:
                bauble.gui.get_display_clipboard().set_text(string, -1)

    @classmethod
    def add_translation_query(cls, table_name, domain, query):
        cls.queries[table_name] = (domain, query)

    @Gtk.Template.Callback()
    def on_row_activated(self, _tree, path, _column):
        """Search for the correct domain for the selected row's item.

        This generally will only work if the item is not deleted.
        """
        row = self.liststore[path]  # pylint: disable=unsubscriptable-object
        obj = row[self.TVC_OBJ]
        if not obj:
            return None
        table = row[self.TVC_TABLE]
        obj_id = row[self.TVC_OBJ].table_id

        table, query = self.queries.get(
            table, (table, '{table} where id={obj_id}')
        )

        if table in search.MapperSearch.domains:
            query = query.format(table=table, obj_id=obj_id)
            if bauble.gui:
                bauble.gui.send_command(query)
            else:
                # for testing...
                return query
        return None

    def update(self, *args):
        """Add the history items to the view."""
        self.cancel_threads()
        GLib.idle_add(self.liststore.clear)
        self.start_thread(AppendThousandRows(self, args[0]))


class HistoryCommandHandler(pluginmgr.CommandHandler):

    command = 'history'
    view = None

    def get_view(self):
        if not self.view:
            self.__class__.view = HistoryView()
        return self.view

    def __call__(self, cmd, arg):
        self.view.update(arg)


pluginmgr.register_command(HistoryCommandHandler)


def select_in_search_results(obj):
    """Search the tree model for obj if it exists then select it if not
    then add it and select it.

    :param obj: the object the select
    :return: a Gtk.TreeIter to the selected row
    """
    check(obj is not None, 'select_in_search_results: arg is None')
    view = bauble.gui.get_view()
    if not isinstance(view, SearchView):
        return None
    logger.debug("select_in_search_results %s is in session %s", obj,
                 obj in view.session)
    model = view.results_view.get_model()
    found = utils.search_tree_model(model, obj)
    row_iter = None
    if len(found) > 0:
        row_iter = found[0]
    else:
        row_iter = model.append(None, [obj])
        model.append(row_iter, ['-'])
        # NOTE used in test...
        logger.debug('%s added to search results', obj)
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
