# Copyright 2008-2010 Brett Adams
# Copyright 2015 Mario Frasca <mario@anche.no>.
# Copyright 2020 Ross Demuth <rossdemuth123@gmail.com>
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
#
# ui.py
#

import os
import traceback
from pathlib import Path

import logging
logger = logging.getLogger(__name__)

from gi.repository import Gtk  # noqa
from gi.repository import Gdk
from gi.repository import GdkPixbuf

import bauble
from bauble import db
from bauble import paths
from bauble import pluginmgr
from bauble.prefs import prefs, datetime_format_pref
from bauble import search
from bauble import utils
from bauble.utils import desktop
from bauble.view import SearchView
from bauble.editor import GenericEditorView


# NOTE pluginmgr.View is a Gtk.Box vertical orientation that can take a root
# widget or glade file.
class DefaultView(pluginmgr.View):
    '''consider DefaultView a splash screen.

    it is displayed at program start and never again.
    it's the core of the "what do I do now" screen.

    DefaultView is related to the SplashCommandHandler,
    not to the view.DefaultCommandHandler
    '''
    infoboxclass = None

    def __init__(self):
        super().__init__()

        # splash window contains a hbox: left half is for the proper splash,
        # right half for infobox, only one infobox is allowed.

        self.hbox = Gtk.Box()
        self.add(self.hbox)
        self.hbox.set_hexpand(True)
        self.hbox.set_vexpand(True)

        image = Gtk.Image()
        image.set_from_file(os.path.join(paths.lib_dir(), 'images',
                                         'bauble_logo.png'))
        self.hbox.pack_start(image, True, True, 0)

        # the following means we do not have an infobox yet
        self.infobox = None

    def update(self):
        logger.debug('DefaultView::update')
        if self.infoboxclass and not self.infobox:
            logger.debug('DefaultView::update - creating infobox')
            self.infobox = self.infoboxclass()
            self.hbox.pack_end(self.infobox, False, False, 8)
            self.infobox.set_vexpand(False)
            self.infobox.set_hexpand(False)
            self.infobox.show()
        if self.infobox:
            logger.debug('DefaultView::update - updating infobox')
            self.infobox.update()


class SplashCommandHandler(pluginmgr.CommandHandler):

    def __init__(self):
        super().__init__()
        if self.view is None:
            logger.warning('SplashCommandHandler.view is None, expect trouble')

    command = ['home', 'splash']
    view = None

    def get_view(self):
        if self.view is None:
            self.view = DefaultView()
        return self.view

    def __call__(self, cmd, arg):
        self.view.update()


class GUI():

    entry_history_pref = 'bauble.history'
    history_size_pref = 'bauble.history_size'
    entry_history_pins_pref = 'bauble.history_pins'
    history_pins_size_pref = 'bauble.history_pins_size'
    window_geometry_pref = "bauble.geometry"

    _default_history_size = 26
    _default_history_pin_size = 10

    # TODO a global approach to css
    _css = Gtk.CssProvider()
    _css.load_from_data(
        b'.err-bg * {background-color: #FF9999;}'
        b'.inf-bg * {background-color: #b6daf2;}'
        b'.click-label {color: blue;}'
        b'.problem {background-color: #FFDCDF;}'
        b'.err-btn * {color: #FF9999;}'
    )
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(), _css,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def __init__(self):
        filename = os.path.join(paths.lib_dir(), 'bauble.glade')
        self.widgets = utils.load_widgets(filename)
        self.window = self.widgets.main_window
        self.window.hide()
        self.previous_view = None

        # restore the window size
        geometry = prefs[self.window_geometry_pref]
        if geometry is not None:
            self.window.set_default_size(*geometry)
            self.window.set_position(Gtk.WindowPosition.CENTER)

        self.window.connect('delete-event', self.on_delete_event)
        self.window.connect("destroy", self.on_quit)
        self.window.connect("size_allocate", self.on_resize)
        self.window.set_title(self.title)

        try:
            logger.debug("loading icon from %s" % bauble.default_icon)
            pixbuf = GdkPixbuf.Pixbuf.new_from_file(bauble.default_icon)
            self.window.set_icon(pixbuf)
        except Exception:
            logger.warning(_('Could not load icon from %s')
                           % bauble.default_icon)
            logger.warning(traceback.format_exc())

        menubar = self.create_main_menu()
        self.widgets.menu_box.pack_start(menubar, True, True, 0)

        combo = self.widgets.main_comboentry
        model = Gtk.ListStore(str)
        combo.set_model(model)
        self.widgets.main_comboentry_entry.connect(
            'icon-press',
            self.on_history_pinned_clicked
        )
        self.populate_main_entry()

        main_entry = combo.get_child()
        main_entry.connect('activate', self.on_main_entry_activate)
        accel_group = Gtk.AccelGroup()
        main_entry.add_accelerator("grab-focus", accel_group, ord('L'),
                                   Gdk.ModifierType.CONTROL_MASK,
                                   Gtk.AccelFlags.VISIBLE)
        self.window.add_accel_group(accel_group)

        self.widgets.home_button.connect(
            'clicked', self.on_home_button_clicked)

        self.widgets.prev_view_button.connect(
            'clicked', self.on_prev_view_button_clicked)

        self.widgets.go_button.connect(
            'clicked', self.on_go_button_clicked)

        self.widgets.query_button.connect(
            'clicked', self.on_query_button_clicked)

        self.set_default_view()

        # add a progressbar to the status bar
        # Warning: this relies on Gtk.Statusbar internals and could break in
        # future versions of gtk
        statusbar = self.widgets.statusbar
        statusbar.set_spacing(10)
        # statusbar.set_has_resize_grip(True)
        self._cids = []

        def on_statusbar_push(sb, cid, txt):
            if cid not in self._cids:
                self._cids.append(cid)

        statusbar.connect('text-pushed', on_statusbar_push)

        # remove label from frame
        frame = statusbar.get_children()[0]
        label = frame.get_children()[0]
        frame.remove(label)

        # replace label with hbox and put label and progress bar in hbox
        hbox = Gtk.Box(False, 5)
        frame.add(hbox)
        hbox.pack_start(label, True, True, 0)
        vbox = Gtk.Box(True, 0, orientation=Gtk.Orientation.VERTICAL)
        hbox.pack_end(vbox, False, True, 15)
        self.progressbar = Gtk.ProgressBar()
        vbox.pack_start(self.progressbar, False, False, 0)
        self.progressbar.set_size_request(-1, 10)
        vbox.show()
        hbox.show()

        from pyparsing import StringStart, Word, alphanums, restOfLine, \
            StringEnd
        cmd = StringStart() + ':' + Word(
            alphanums + '-_').setResultsName('cmd')
        arg = restOfLine.setResultsName('arg')
        self.cmd_parser = (cmd + StringEnd()) | (cmd + '=' + arg) | arg

        combo.grab_focus()

    def close_message_box(self, *args):
        parent = self.widgets.msg_box_parent
        for kid in self.widgets.msg_box_parent:
            parent.remove(kid)
        return

    def show_yesno_box(self, msg):
        self.close_message_box()
        box = utils.add_message_box(self.widgets.msg_box_parent,
                                    utils.MESSAGE_BOX_YESNO)
        box.message = msg
        box.show()

    def show_error_box(self, msg, details=None):
        self.close_message_box()
        box = utils.add_message_box(self.widgets.msg_box_parent,
                                    utils.MESSAGE_BOX_INFO)
        box.message = msg
        box.details = details
        # set red background
        box.get_style_context().add_class('err-bg')

        box.show()

    def show_message_box(self, msg):
        """
        Show an info message in the message drop down box
        """
        self.close_message_box()
        box = utils.add_message_box(self.widgets.msg_box_parent,
                                    utils.MESSAGE_BOX_INFO)
        box.message = msg
        # set a light blue background
        box.get_style_context().add_class('inf-bg')

        box.show()

    def show(self):
        self.window.show()

    @property
    def history_size(self):
        history = prefs[self.history_size_pref]
        if history is None:
            prefs[self.history_size_pref] = self._default_history_size
        return int(prefs[self.history_size_pref])

    @property
    def history_pins_size(self):
        pins = prefs[self.history_pins_size_pref]
        if pins is None:
            prefs[self.history_pins_size_pref] = self._default_history_pin_size
        return int(prefs[self.history_pins_size_pref])

    def send_command(self, command):
        self.widgets.main_comboentry.get_child().set_text(command)
        self.widgets.go_button.emit("clicked")

    def on_main_entry_activate(self, widget, data=None):
        self.widgets.go_button.emit("clicked")

    def on_home_button_clicked(self, widget):
        bauble.command_handler('home', None)

    def on_prev_view_button_clicked(self, widget):
        self.widgets.main_comboentry.get_child().set_text('')
        bauble.gui.set_view('previous')

    def on_go_button_clicked(self, widget):
        self.close_message_box()
        text = self.widgets.main_comboentry.get_child().get_text()
        if text == '':
            return
        self.add_to_history(text)
        tokens = self.cmd_parser.parseString(text)
        cmd = None
        arg = None
        try:
            cmd = tokens['cmd']
        except KeyError as e:
            logger.debug("%s(%s)" % (type(e).__name__, e))

        try:
            arg = tokens['arg']
        except KeyError as e:
            logger.debug("%s(%s)" % (type(e).__name__, e))

        bauble.command_handler(cmd, arg)

    def on_query_button_clicked(self, widget):
        gladefilepath = os.path.join(paths.lib_dir(), "querybuilder.glade")
        view = GenericEditorView(
            gladefilepath,
            parent=None,
            root_widget_name='main_dialog')
        qb = search.QueryBuilder(view)
        qb.set_query(self.widgets.main_comboentry.get_child().get_text())
        response = qb.start()
        if response == Gtk.ResponseType.OK:
            query = qb.get_query()
            self.widgets.main_comboentry.get_child().set_text(query)
            self.widgets.go_button.emit("clicked")
        qb.cleanup()

    def on_history_pinned_clicked(self, widget, icon_pos, event):
        """
        add or remove a pin search string to the history pins
        """
        text = widget.get_text()

        history_pins = prefs.get(self.entry_history_pins_pref, [])
        history = prefs.get(self.entry_history_pref, [])
        # already pinned entry - remove the pin and add it back history
        if text in history_pins:
            history_pins.remove(text)
            prefs[self.entry_history_pins_pref] = history_pins
            self.add_to_history(text)
            self.populate_main_entry()
            return

        if text in history:
            history.remove(text)
            prefs[self.entry_history_pref] = history

        # trim the history_pins if the size is larger than the pref
        while len(history_pins) >= self.history_pins_size - 1:
            history_pins.pop()

        history_pins.insert(0, text)
        prefs[self.entry_history_pins_pref] = history_pins
        self.populate_main_entry()

    def add_to_history(self, text, index=0):
        """
        add text to history, if text is already in the history then set its
        index to index parameter
        """
        if index < 0 or index > self.history_size:
            raise ValueError(_('history size must be greater than zero and '
                               'less than the history size'))
        history = prefs.get(self.entry_history_pref, [])
        if text in history:
            history.remove(text)
        # if its a pinned history entry bail
        history_pins = prefs.get(self.entry_history_pins_pref, [])
        if text in history_pins:
            return

        # trim the history if the size is larger than the history_size pref
        while len(history) >= self.history_size - 1:
            history.pop()

        history.insert(index, text)
        prefs[self.entry_history_pref] = history
        self.populate_main_entry()

    def populate_main_entry(self):
        history_pins = prefs[self.entry_history_pins_pref]
        history = prefs[self.entry_history_pref]
        main_combo = self.widgets.main_comboentry

        def separate(model, tree_iter):
            if model.get(tree_iter, 0) == ('--separator--', ):
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
            completion.set_popup_completion(False)
            completion.set_inline_completion(True)
            completion.set_minimum_key_length(2)
        else:
            compl_model = completion.get_model()

        if history_pins is not None:
            for pin in history_pins:
                logger.debug('adding pin to main entry: %s', pin)
                model.append([pin, ])
                compl_model.append([pin])

        model.append(['--separator--', ])

        if history is not None:
            for herstory in history:
                model.append([herstory, ])
                compl_model.append([herstory])

    def __get_title(self):
        if bauble.conn_name is None:
            return '%s %s' % ('Ghini', bauble.version)
        else:
            return '%s %s - %s' % ('Ghini', bauble.version,
                                   bauble.conn_name)
    title = property(__get_title)

    def set_busy(self, busy):
        self.widgets.main_box.set_sensitive(not busy)
        if busy:
            self.window.get_property('window').set_cursor(
                Gdk.Cursor.new(Gdk.CursorType.WATCH))
        else:
            self.window.get_property('window').set_cursor(None)

    def set_default_view(self):
        main_entry = self.widgets.main_comboentry.get_child()
        if main_entry is not None:
            main_entry.set_text('')
        SplashCommandHandler.view = DefaultView()
        self.set_view(SplashCommandHandler.view)
        pluginmgr.register_command(SplashCommandHandler)

    def set_view(self, view=None):
        '''
        set the view, if view is None then remove any views currently set

        :param view: default=None
        '''
        if view == 'previous':
            view = self.previous_view
            self.previous_view = None
        if view is None:
            return
        view_box = self.widgets.view_box
        must_add_this_view = True
        for kid in view_box.get_children():
            if view == kid:
                must_add_this_view = False
                kid.set_visible(True)
            else:
                if kid.get_visible() is True:
                    self.previous_view = kid
                kid.set_visible(False)
                kid.cancel_threads()
        if must_add_this_view:
            view_box.pack_start(view, True, True, 0)
        view.show_all()

    def get_view(self):
        '''
        return the current view in the view box
        '''
        for kid in self.widgets.view_box.get_children():
            if kid.get_visible():
                return kid
        return None

    def create_main_menu(self):
        """
        get the main menu from the UIManager XML description, add its actions
        and return the menubar
        """
        self.ui_manager = Gtk.UIManager()

        # add accel group
        accel_group = self.ui_manager.get_accel_group()
        self.window.add_accel_group(accel_group)

        # TODO: get rid of new, open, and just have a connection
        # menu item

        # create and addaction group for menu actions
        menu_actions = Gtk.ActionGroup("MenuActions")
        menu_actions.add_actions([("file", None, _("_File")),
                                  ("file_new", Gtk.STOCK_NEW, _("_New"),
                                   None, None, self.on_file_menu_new),
                                  ("file_open", Gtk.STOCK_OPEN, _("_Open"),
                                   '<ctrl>o', None, self.on_file_menu_open),
                                  ("file_quit", Gtk.STOCK_QUIT, _("_Quit"),
                                   None, None, self.on_quit),
                                  ("edit", None, _("_Edit")),
                                  ("edit_cut", Gtk.STOCK_CUT, _("_Cut"), None,
                                   None, self.on_edit_menu_cut),
                                  ("edit_copy", Gtk.STOCK_COPY, _("_Copy"),
                                   None, None, self.on_edit_menu_copy),
                                  ("edit_paste", Gtk.STOCK_PASTE, _("_Paste"),
                                   None, None, self.on_edit_menu_paste),
                                  ("edit_prefs", Gtk.STOCK_PREFERENCES,
                                   _("_Preferences"), None, None,
                                   self.on_edit_menu_preferences),
                                  ("edit_history", Gtk.STOCK_HARDDISK,
                                   _("_View History"), None, None,
                                   self.on_edit_menu_history),
                                  ("insert", None, _("_Insert")),
                                  ("tools", None, _("_Tools")),
                                  ("help", None, _("_Help")),
                                  ("help_contents", Gtk.STOCK_HELP,
                                   _("Contents"), None, None,
                                   self.on_help_menu_contents),
                                  ("help_bug", None, _("Report a bug"), None,
                                   None, self.on_help_menu_bug),
                                  ("help_logfile", Gtk.STOCK_PROPERTIES,
                                   _("Open the log-file"), None,
                                   None, self.on_help_menu_logfile),
                                  ("help_web.devel", Gtk.STOCK_HOME,
                                   _("Ghini development website"), None,
                                   None, self.on_help_menu_web_devel),
                                  ("help_web.wiki", Gtk.STOCK_EDIT,
                                   _("Ghini news"), None,
                                   None, self.on_help_menu_web_wiki),
                                  ("help_web.forum", Gtk.STOCK_JUSTIFY_LEFT,
                                   _("Ghini forum"), None,
                                   None, self.on_help_menu_web_forum),
                                  ("help_about", Gtk.STOCK_ABOUT, _("About"),
                                   None, None, self.on_help_menu_about),
                                  ])
        self.ui_manager.insert_action_group(menu_actions, 0)

        # TODO: The menubar was made available in Gtk.Builder in Gtk+
        # 2.16 so whenever we decide 2.16 is the minimum version we
        # should get rid of this .ui file

        # load ui
        ui_filename = os.path.join(paths.lib_dir(), 'bauble.ui')
        self.ui_manager.add_ui_from_file(ui_filename)

        # get menu bar from ui manager
        self.menubar = self.ui_manager.get_widget("/MenuBar")

        self.clear_menu('/ui/MenuBar/insert_menu')
        self.clear_menu('/ui/MenuBar/tools_menu')

        self.insert_menu = self.ui_manager.get_widget(
            '/ui/MenuBar/insert_menu')
        return self.menubar

    def clear_menu(self, path):
        """
        remove all the menus items from a menu
        """
        # clear out the insert an tools menus
        menu = self.ui_manager.get_widget(path)
        submenu = menu.get_submenu()
        for c in submenu.get_children():
            submenu.remove(c)
        menu.show()

    def add_menu(self, name, menu, index=-1):
        '''
        add a menu to the menubar

        :param name:
        :param menu:
        :param index:
        '''
        menu_item = Gtk.MenuItem(name)
        menu_item.set_submenu(menu)
        self.menubar.insert(menu_item, len(self.menubar.get_children())-1)
        self.menubar.show_all()
        return menu_item

    __insert_menu_cache = {}

    def add_to_insert_menu(self, editor, label):
        """
        add an editor to the insert menu

        :param editor: the editor to add to the menu
        :param label: the label for the menu item
        """
        menu = self.ui_manager.get_widget('/ui/MenuBar/insert_menu')
        submenu = menu.get_submenu()
        item = Gtk.MenuItem(label)
        item.connect('activate', self.on_insert_menu_item_activate, editor)
        submenu.append(item)
        self.__insert_menu_cache[label] = item
        item.show()
        # sort items
        i = 0
        for label in sorted(self.__insert_menu_cache.keys()):
            submenu.reorder_child(self.__insert_menu_cache[label], i)
            i += 1

    def build_tools_menu(self):
        """
        Build the tools menu from the tools provided by the plugins.

        This method is generally called after plugin initialization
        """
        topmenu = self.ui_manager.get_widget('/ui/MenuBar/tools_menu')
        menu = topmenu.get_submenu()
        for child in menu.get_children():
            menu.remove(child)
        menu.show()
        tools = {'__root': []}
        # categorize the tools into a dict
        for p in list(pluginmgr.plugins.values()):
            for tool in p.tools:
                if tool.category is not None:
                    try:
                        tools[tool.category].append(tool)
                    except KeyError:
                        ## initialize tools dictionary
                        tools[tool.category] = []
                        tools[tool.category].append(tool)
                else:
                    tools['__root'].append(tool)

        # add the tools with no category to the root menu
        root_tools = sorted(tools.pop('__root'), key=lambda tool: tool.label)
        for tool in root_tools:
            item = Gtk.MenuItem(tool.label)
            item.show()
            item.connect("activate", self.on_tools_menu_item_activate, tool)
            menu.append(item)
            if not tool.enabled:
                item.set_sensitive(False)

        # create submenus for the categories and add the tools
        for category in sorted(tools.keys()):
            submenu = Gtk.Menu()
            submenu_item = Gtk.MenuItem(category)
            submenu_item.set_submenu(submenu)
            menu.append(submenu_item)
            for tool in sorted(tools[category], key=lambda tool: tool.label):
                item = Gtk.MenuItem(tool.label)
                item.connect("activate", self.on_tools_menu_item_activate,
                             tool)
                submenu.append(item)
                if not tool.enabled:
                    item.set_sensitive(False)
        menu.show_all()
        return menu

    def on_tools_menu_item_activate(self, widget, tool):
        """
        Start a tool on the Tool menu.
        """
        try:
            tool.start()
        except Exception as e:
            utils.message_details_dialog(utils.xml_safe(str(e)),
                                         traceback.format_exc(),
                                         Gtk.MessageType.ERROR)
            logger.debug(traceback.format_exc())

    def on_insert_menu_item_activate(self, widget, editor_cls):
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
                view.expand_to_all_refs(expanded_rows)
        except Exception as e:
            utils.message_details_dialog(utils.xml_safe(str(e)),
                                         traceback.format_exc(),
                                         Gtk.MessageType.ERROR)
            logger.error('bauble.gui.on_insert_menu_item_activate():\n %s'
                         % traceback.format_exc())
            return

        if editor is None:
            return

        presenter_cls = view_cls = None
        if hasattr(editor, 'presenter'):
            presenter_cls = type(editor.presenter)
            view_cls = type(editor.presenter.view)

        # delete the editor
        del editor

        # check for leaks
        obj = utils.gc_objects_by_type(editor_cls)
        if obj != []:
            logger.warning('%s leaked: %s', editor_cls.__name__, obj)

        if presenter_cls:
            obj = utils.gc_objects_by_type(presenter_cls)
            if obj != []:
                logger.warning('%s leaked: %s', presenter_cls.__name__, obj)
            obj = utils.gc_objects_by_type(view_cls)
            if obj != []:
                logger.warning('%s leaked: %s', view_cls.__name__, obj)

    # pylint: disable=unused-argument
    def on_edit_menu_cut(self, _widget, data=None):
        self.widgets.main_comboentry.get_child().cut_clipboard()

    def on_edit_menu_copy(self, _widget, data=None):
        self.widgets.main_comboentry.get_child().copy_clipboard()

    def on_edit_menu_paste(self, _widget, data=None):
        self.widgets.main_comboentry.get_child().paste_clipboard()

    @staticmethod
    def on_edit_menu_preferences(_widget, data=None):
        bauble.command_handler('prefs', None)

    @staticmethod
    def on_edit_menu_history(_widget, data=None):
        bauble.command_handler('history', None)

    def on_file_menu_new(self, widget, data=None):
        msg = "If a database already exists at this connection then creating "\
              "a new database could destroy your data.\n\n<i>Are you sure "\
              "this is what you want to do?</i>"

        if not utils.yes_no_dialog(msg, yes_delay=2):
            return

        # if gui is not None and hasattr(gui, 'insert_menu'):
        submenu = self.insert_menu.get_submenu()
        for child in submenu.get_children():
            submenu.remove(child)
        self.insert_menu.show()
        try:
            db.create()
            pluginmgr.init()
        except Exception as e:  # pylint: disable=broad-except
            msg = (_('Could not create a new database.\n\n%s') %
                   utils.xml_safe(e))
            traceb = utils.xml_safe(traceback.format_exc())
            utils.message_details_dialog(msg, traceb, Gtk.MessageType.ERROR)
            return
        bauble.command_handler('home', None)

    def on_file_menu_open(self, widget, data=None):
        """
        Open the connection manager.
        """
        from .connmgr import start_connection_manager
        default_conn = prefs[bauble.conn_default_pref]
        name, uri = start_connection_manager(default_conn)
        if name is None:
            return

        engine = None
        try:
            engine = db.open(uri, True, True)
        except Exception as e:
            # we don't do anything to handle the exception since db.open()
            # should have shown an error dialog if there was a problem
            # opening the database as long as the show_error_dialogs
            # parameter is True
            logger.warning(e)

        if engine is None:
            # the database wasn't open
            return

        # everything seems to have passed ok so setup the rest of bauble
        if engine is not None:
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
            self.clear_menu('/ui/MenuBar/insert_menu')
            self.statusbar_clear()
            pluginmgr.init()
            bauble.command_handler('home', None)

    def statusbar_clear(self):
        """
        Call Gtk.Statusbar.pop() for each context_id that had previously
        been pushed() onto the the statusbar stack.  This might not clear
        all the messages in the statusbar but it's the best we can do
        without knowing how many messages are in the stack.
        """
        # TODO: to clear everything in the statusbar we would probably
        # have to subclass Gtk.Statusbar to keep track of the message
        # ids and context ids so we can properly clear the statusbar.
        for cid in self._cids:
            self.widgets.statusbar.pop(cid)

    def on_help_menu_contents(self, widget, data=None):
        desktop.open('http://ghini.readthedocs.io/en/ghini-1.0-dev/',
                     dialog_on_error=True)

    def on_help_menu_bug(self, widget, data=None):
        desktop.open('https://github.com/RoDuth/ghini.desktop/issues/new',
                     dialog_on_error=True)

    def on_help_menu_logfile(self, widget, data=None):
        logger.debug('opening log file from help menu')
        filename = os.path.join(paths.appdata_dir(), 'bauble.log')
        desktop.open(filename, dialog_on_error=True)

    def on_help_menu_web_devel(self, widget, data=None):
        desktop.open('http://github.com/RoDuth/ghini.desktop/',
                     dialog_on_error=True)

    def on_help_menu_web_wiki(self, widget, data=None):
        desktop.open('http://ghini.github.io/',
                     dialog_on_error=True)

    def on_help_menu_web_forum(self, widget, data=None):
        desktop.open('https://groups.google.com/forum/#!forum/bauble',
                     dialog_on_error=True)

    def on_help_menu_about(self, widget, data=None):
        about = Gtk.AboutDialog()
        about.set_program_name('Ghini (BBG)')
        about.set_version(bauble.version)
        about.set_website(_('http://ghini.github.io'))
        f = os.path.join(paths.lib_dir(), 'images', 'icon.svg')
        logger.debug('about using icon: %s', f)
        pixbuf = GdkPixbuf.Pixbuf.new_from_file(f)
        about.set_logo(pixbuf)
        about.set_copyright(_('Copyright © by its contributors.'))

        lic_path = Path(paths.main_dir(), 'share', 'ghini', 'LICENSE')

        if not lic_path.exists():
            lic_path = Path(paths.main_dir(), 'LICENSE')

        logger.debug('about using license at %s', lic_path)

        with open(lic_path) as f:
            lics = f.read()
        about.set_license(lics)  # not translated
        about.set_comments(_('This version installed on: %s\n'
                             'Latest published version: %s\n'
                             'Publication date: %s') % (
                                 bauble.installation_date.strftime(
                                     prefs.get(datetime_format_pref)),
                                 bauble.release_version,
                                 bauble.release_date.strftime(
                                     prefs.get(datetime_format_pref))))
        about.run()
        about.destroy()

    def on_delete_event(self, *args):
        from bauble import task
        if task.running():
            msg = _('Would you like to cancel the current tasks?')
            if not utils.yes_no_dialog(msg):
                # stop other handlers for being invoked for this event
                return True
            task.kill()
        return False

    def on_resize(self, widget, data):
        rect = self.window.get_size()
        prefs[self.window_geometry_pref] = rect.width, rect.height

    def on_quit(self, widget, data=None):
        bauble.quit()
