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
import logging
import sys
import traceback

from gi.repository import Gdk
from gi.repository import Gio
from gi.repository import Gtk

import bauble
from bauble import db
from bauble import error as err
from bauble import paths
from bauble import pluginmgr
from bauble import prefs
from bauble import utils
from bauble.connmgr import start_connection_manager
from bauble.i18n import _

logger = logging.getLogger(__name__)


class Application(Gtk.Application):
    def __init__(self):
        super().__init__(
            application_id="org.gnome.GhiniDesktop",
            flags=Gio.ApplicationFlags.FLAGS_NONE,
        )
        self.connect("activate", self.on_activate)

    def do_startup(self, *args, **kwargs):
        # first
        Gtk.Application.do_startup(self, *args, **kwargs)

        # initialise prefs
        prefs.prefs.init()

        # set the logging level to debug level per module as listed in prefs
        # reset to WARNING (set DEBUG in bauble.__init__ to capture early)
        bauble.logger.setLevel(logging.WARNING)
        for handler in prefs.prefs.get(prefs.debug_logging_prefs, []):
            logging.getLogger(handler).setLevel(logging.DEBUG)

        # log TEMPDIR
        logger.debug("tempdir: %s", paths.TEMPDIR)

        open_exc = self._get_connection()
        self._load_plugins()
        bauble.gui.init()
        # add any prefs menus etc.
        prefs.post_gui()
        bauble.gui.show()
        # bail early if no connection
        if open_exc is False:
            logger.debug("bailing early, no connection")
            return

        if not self._post_loop(open_exc):
            self.quit()
            return

        logger.info(
            "This version installed on: %s; "
            "This version installed at: %s; "
            "Latest published version: %s; "
            "Publication date: %s",
            bauble.installation_date.strftime(
                prefs.prefs.get(prefs.datetime_format_pref)
            ),
            __file__,
            bauble.release_version,
            bauble.release_date.strftime(
                prefs.prefs.get(prefs.datetime_format_pref)
            ),
        )

        # Keep clipboard contents after application exit
        clip = Gtk.Clipboard.get_default(Gdk.Display.get_default())
        clip.set_can_store(None)

    def _get_connection(self):
        # allow opening the app in current state when debuging tests
        if getattr(bauble.db, "engine", None):
            return

        uri = None
        conn_name = None
        open_exc = None
        while True:
            if not uri or not conn_name:
                conn_name, uri = start_connection_manager()
                logger.debug("conn_name = %s")
                if conn_name is None:
                    self.quit()
                    return False
                bauble.conn_name = conn_name
            try:
                # testing, database initialized at current version.  or we
                # get two different exceptions.
                if db.open_conn(uri, True, True):
                    prefs.prefs[bauble.conn_default_pref] = conn_name
                    break
                uri = conn_name = None
            except err.VersionError as e:
                logger.warning("%s(%s)", type(e).__name__, e)
                db.open_conn(uri, False)
                break
            except (
                err.EmptyDatabaseError,
                err.MetaTableError,
                err.TimestampError,
                err.RegistryError,
            ) as e:
                logger.info("%s(%s)", type(e).__name__, e)
                open_exc = e
                # reopen without verification so that db.Session and
                # db.engine, db.metadata will be bound to an engine
                db.open_conn(uri, False)
                break
            except err.DatabaseError as e:
                logger.debug("%s(%s)", type(e).__name__, e)
                open_exc = e
            except Exception as e:  # pylint: disable=broad-except
                logger.debug("%s(%s)", type(e).__name__, e)
                msg = _("Could not open connection.\n\n%s") % e
                utils.message_details_dialog(
                    msg, traceback.format_exc(), Gtk.MessageType.ERROR
                )
                uri = None
        return open_exc

    @staticmethod
    def _load_plugins():
        # load the plugins
        pluginmgr.load()

        # save any changes made in the conn manager before anything else has
        # chance to crash
        prefs.prefs.save()

    @staticmethod
    def _post_loop(open_exc):
        logger.debug("entering _post_loop")
        try:
            if isinstance(open_exc, err.DatabaseError):
                msg = _(
                    "Would you like to create a new Ghini database at "
                    "the current connection?\n\n<i>Warning: If there is "
                    "already a database at this connection any existing "
                    "data will be destroyed!</i>"
                )
                if utils.yes_no_dialog(msg, yes_delay=2):
                    try:
                        db.create()
                        # db.create() creates all tables registered with
                        # the default metadata so the pluginmgr should be
                        # loaded after the database is created so we don't
                        # inadvertantly create tables from the plugins
                        pluginmgr.init()
                        # set the default connection
                        prefs.prefs[bauble.conn_default_pref] = (
                            bauble.conn_name
                        )
                    except Exception as e:  # pylint: disable=broad-except
                        utils.message_details_dialog(
                            utils.xml_safe(e),
                            traceback.format_exc(),
                            Gtk.MessageType.ERROR,
                        )
                        logger.error("%s(%s)", type(e).__name__, e)
                        return False
            else:
                pluginmgr.init()
        except Exception as e:  # pylint: disable=broad-except
            logger.warning(
                "%s\n%s(%s)", traceback.format_exc(), type(e).__name__, e
            )
            msg = utils.xml_safe(f"{type(e).__name__}({e})")
            utils.message_dialog(msg, Gtk.MessageType.WARNING)
            return False
        # updates the splashscreen
        bauble.gui.get_view().update()
        return True

    def on_activate(self, *_args, **_kwargs):
        # second
        self.add_window(bauble.gui.window)
        self._build_menubar()

    def _build_menubar(self):
        actions = (
            ("open", bauble.gui.on_file_menu_open),
            ("new", bauble.gui.on_file_menu_new),
            ("quit", bauble.gui.on_quit),
            ("preferences", bauble.gui.on_edit_menu_preferences),
            ("history", bauble.gui.on_edit_menu_history),
            ("home", bauble.gui.on_home_clicked),
            ("previous", bauble.gui.on_prev_view_clicked),
            ("next", bauble.gui.on_next_view_clicked),
            ("help_contents", bauble.gui.on_help_menu_contents),
            ("help_bug", bauble.gui.on_help_menu_bug),
            ("help_log", bauble.gui.on_help_menu_logfile),
            ("about", bauble.gui.on_help_menu_about),
        )
        for name, handler in actions:
            if not db.current_user.is_admin and name == "new":
                continue
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", handler)
            self.add_action(action)
            if name in ["open", "new"]:
                bauble.gui.disable_on_busy_actions.add(action)

        # TODO temp solution to get menubar working for windows/linux
        if sys.platform in ["win32", "linux"]:
            menu_bar = Gtk.MenuBar.new_from_model(bauble.gui.menubar)
            menu_bar.show_all()
            bauble.gui.widgets.menu_box.pack_start(menu_bar, True, True, 0)
        else:
            self.set_menubar(bauble.gui.menubar)

    def do_shutdown(self, *args, **kwargs):
        logger.debug("Application shutdown")
        prefs.prefs.save()
        import shutil

        # delete global tempdir
        shutil.rmtree(paths.TEMPDIR)
        Gtk.Application.do_shutdown(self, *args, **kwargs)


def main():
    app = Application()
    return app.run(sys.argv)
