# Copyright (c) 2022 Ross Demuth <rossdemuth123@gmail.com>
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
The main application
"""
import os
import sys
import logging
import traceback

from gi.repository import Gtk
from gi.repository import Gio
from gi.repository import Gdk

import bauble
from bauble import paths
from bauble import error as err
from bauble import prefs
from bauble import pluginmgr
from bauble import utils
from bauble import db
from bauble import task
from bauble.connmgr import start_connection_manager
from .ui import GUI

logger = logging.getLogger(__name__)
consoleLevel = logging.WARNING


class Application(Gtk.Application):
    def __init__(self):
        super().__init__(application_id='org.gnome.GhiniDesktop',
                         flags=Gio.ApplicationFlags.FLAGS_NONE)
        self.connect('activate', self.on_activate)

    def do_startup(self, *args, **kwargs):
        # first
        Gtk.Application.do_startup(self, *args, **kwargs)
        if not os.path.exists(paths.appdata_dir()):
            os.makedirs(paths.appdata_dir())
        self._setup_logging()
        # initialise prefs
        prefs.prefs.init()
        # set the logging level to debug level per module as listed in prefs
        for handler in prefs.prefs.get(prefs.debug_logging_prefs, []):
            logging.getLogger(handler).setLevel(logging.DEBUG)

        open_exc = self._get_connection()
        self._load_plugins()
        bauble.gui = GUI()
        bauble.gui.show()
        # bail early if no connection
        if open_exc is False:
            return
        self._post_loop(open_exc)

        logger.info('This version installed on: %s; '
                    'This version installed at: %s; '
                    'Latest published version: %s; '
                    'Publication date: %s',
                    bauble.installation_date.strftime(
                        prefs.prefs.get(prefs.datetime_format_pref)),
                    __file__,
                    bauble.release_version,
                    bauble.release_date.strftime(
                        prefs.prefs.get(prefs.datetime_format_pref)))

        # Keep clipboard contents after application exit
        clip = Gtk.Clipboard.get_default(Gdk.Display.get_default())
        clip.set_can_store(None)

    def _get_connection(self):
        uri = None
        conn_name = None
        open_exc = None
        while True:
            if not uri or not conn_name:
                conn_name, uri = start_connection_manager()
                if conn_name is None:
                    self.quit()
                    return False
                bauble.conn_name = conn_name
            try:
                # testing, database initialized at current version.  or we
                # get two different exceptions.
                if db.open(uri, True, True):
                    prefs.prefs[bauble.conn_default_pref] = conn_name
                    break
                uri = conn_name = None
            except err.VersionError as e:
                logger.warning("%s(%s)", type(e).__name__, e)
                db.open(uri, False)
                break
            except (err.EmptyDatabaseError, err.MetaTableError,
                    err.TimestampError, err.RegistryError) as e:
                logger.info("%s(%s)", type(e).__name__, e)
                open_exc = e
                # reopen without verification so that db.Session and
                # db.engine, db.metadata will be bound to an engine
                db.open(uri, False)
                break
            except err.DatabaseError as e:
                logger.debug("%s(%s)", type(e).__name__, e)
                open_exc = e
            except Exception as e:  # pylint: disable=broad-except
                msg = _("Could not open connection.\n\n%s") % e
                utils.message_details_dialog(msg, traceback.format_exc(),
                                             Gtk.MessageType.ERROR)
                uri = None
        return open_exc

    @staticmethod
    def _load_plugins():
        # load the plugins
        pluginmgr.load()

        # save any changes made in the conn manager before anything else has
        # chance to crash
        prefs.prefs.save()

        # set the default command handler
        from bauble.view import DefaultCommandHandler
        pluginmgr.register_command(DefaultCommandHandler)

    @staticmethod
    def _setup_logging():
        # add console root handler, and file root handler, set it at the
        # logging level specified by BAUBLE_LOGGING, or at INFO level.
        filename = os.path.join(paths.appdata_dir(), 'bauble.log')
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s:%(lineno)d - %(levelname)s - %(thread)d '
            '- %(message)s')
        file_handler = logging.FileHandler(filename, 'w+', 'utf-8')
        file_handler.setFormatter(formatter)
        logging.getLogger().addHandler(file_handler)
        file_handler.setLevel(logging.DEBUG)

        if not paths.main_is_frozen():
            console_handler = logging.StreamHandler()
            logging.getLogger().addHandler(console_handler)
            console_handler.setFormatter(formatter)

            console_handler.setLevel(consoleLevel)

    @staticmethod
    def _post_loop(open_exc):
        try:
            if isinstance(open_exc, err.DatabaseError):
                msg = _('Would you like to create a new Ghini database at '
                        'the current connection?\n\n<i>Warning: If there is '
                        'already a database at this connection any existing '
                        'data will be destroyed!</i>')
                if utils.yes_no_dialog(msg, yes_delay=2):
                    try:
                        db.create()
                        # db.create() creates all tables registered with
                        # the default metadata so the pluginmgr should be
                        # loaded after the database is created so we don't
                        # inadvertantly create tables from the plugins
                        pluginmgr.init()
                        # set the default connection
                        prefs.prefs[
                            bauble.conn_default_pref
                        ] = bauble.conn_name
                    except Exception as e:   # pylint: disable=broad-except
                        utils.message_details_dialog(utils.xml_safe(e),
                                                     traceback.format_exc(),
                                                     Gtk.MessageType.ERROR)
                        logger.error("%s(%s)", type(e).__name__, e)
            else:
                pluginmgr.init()
        except Exception as e:   # pylint: disable=broad-except
            logger.warning("%s\n%s(%s)", traceback.format_exc(),
                           type(e).__name__, e)
            msg = utils.xml_safe(f'{type(e).__name__}({e})')
            utils.message_dialog(msg, Gtk.MessageType.WARNING)
        bauble.gui.get_view().update()

    def on_activate(self, *_args, **_kwargs):
        # second
        self.add_window(bauble.gui.window)
        self._build_menubar()

    def _build_menubar(self):
        actions = (
            ('open', bauble.gui.on_file_menu_open),
            ('new', bauble.gui.on_file_menu_new),
            ('quit', bauble.gui.on_quit),
            ('preferences', bauble.gui.on_edit_menu_preferences),
            ('history', bauble.gui.on_edit_menu_history),
            ('home', bauble.gui.on_home_clicked),
            ('previous', bauble.gui.on_prev_view_clicked),
            ('help_contents', bauble.gui.on_help_menu_contents),
            ('help_bug', bauble.gui.on_help_menu_bug),
            ('help_log', bauble.gui.on_help_menu_logfile),
            ('about', bauble.gui.on_help_menu_about),
        )
        for name, handler in actions:
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", handler)
            self.add_action(action)
            if name in ['open', 'new']:
                bauble.gui.disable_on_busy_actions.add(action)

        self.set_menubar(bauble.gui.menubar)

        # TODO temp solution to get menubar working for windows/linux
        if sys.platform in ['win32', 'linux']:
            menu_bar = Gtk.MenuBar.new_from_model(bauble.gui.menubar)
            menu_bar.show_all()
            bauble.gui.widgets.menu_box.pack_end(menu_bar, True, True, 0)

    def do_shutdown(self, *args, **kwargs):
        prefs.prefs.save()
        Gtk.Application.do_shutdown(self, *args, **kwargs)


def main():
    app = Application()
    return app.run(sys.argv)