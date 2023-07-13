# Copyright 2008-2010 Brett Adams
# Copyright 2015-2017 Mario Frasca <mario@anche.no>.
# Copyright 2017 Jardín Botánico de Quito
# Copyright 2016-2022 Ross Demuth <rossdemuth123@gmail.com>
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
# connmgr.py
#

"""
The connection manager provides a GUI for creating and opening
connections. This is the first thing displayed when Ghini starts.
"""
import os
from pathlib import Path
import copy
from importlib import import_module

import logging
logger = logging.getLogger(__name__)

import dateutil
from gi.repository import Gtk  # noqa
from gi.repository import GdkPixbuf

import bauble
from bauble import paths, prefs, utils
from bauble.editor import GenericEditorView, GenericEditorPresenter


def is_package_name(name):
    """True if name identifies a package and it can be imported"""

    try:
        import_module(name)
        return True
    except ImportError:
        return False


DBS = [('sqlite3', 'SQLite'),
       ('psycopg2', 'PostgreSQL'),
       ('pyodbc', 'MSSQL')]
#     ('mysql', 'MySQL'),
#     ('cx_Oracle', 'Oracle'),

WORKING_DBTYPES = [second for first, second in DBS]
DBTYPES = [second for first, second in DBS if is_package_name(first)]


def type_combo_cell_data_func(_combo, renderer, model, itr):
    """passed to the gtk method set_cell_data_func

    item is sensitive if in WORKING_DBTYPES
    """
    dbtype = model[itr][0]
    sensitive = dbtype in WORKING_DBTYPES
    renderer.set_property('sensitive', sensitive)
    renderer.set_property('text', dbtype)


def set_installation_date():
    """Set bauble.installation_date"""
    # locally, read the installation timestamp
    main_init_path = bauble.__file__
    last_modified_seconds = os.stat(main_init_path).st_mtime
    from datetime import datetime
    bauble.installation_date = datetime.fromtimestamp(last_modified_seconds)


def retrieve_latest_release_data():
    """Using the github API to grab the latests release info and return the
    json data if successful, otherwise return None
    """
    github_releases_uri = ('https://api.github.com/repos/RoDuth/ghini'
                           '.desktop/releases')
    try:
        from requests import exceptions
        net_sess = utils.get_net_sess()
        response = net_sess.get(github_releases_uri, timeout=5)
        if response.ok:
            return response.json()[0]
        logger.info('error while checking for a new release')
    except exceptions.Timeout:
        logger.info('connection timed out while checking for new release')
    except exceptions.RequestException as e:
        logger.info('Requests error %s while checking for new release', e)
    except Exception as e:  # pylint: disable=broad-except
        # used in tests
        logger.warning('unhandled %s(%s) while checking for new release',
                       type(e).__name__, e)
    return None


def check_new_release(github_release_data):
    """Check if the supplied json data descibes a newer release than the
    current version.

    If if is return the data, otherwise return False

    Also updates bauble.release_version and bauble.release_date
    """
    github_release = github_release_data.get('name')
    github_prerelease = github_release_data.get('prerelease')
    # update release_version and release_date
    if github_prerelease:
        bauble.release_version = github_release + ' (prerelease)'
    else:
        bauble.release_version = github_release
    release_date = github_release_data.get(
        'assets', [{}])[0].get('created_at')
    release_date = dateutil.parser.isoparse(release_date)
    bauble.release_date = release_date.astimezone(tz=None)

    github_version = github_release.split()[0][1:]
    current_version = bauble.version
    logger.debug('latest release on github is release: %s',
                 github_release)
    logger.debug('latest release on github is a prerelease?: %s',
                 github_prerelease)
    logger.debug('this version %s', current_version)
    if github_version > current_version:
        return github_release_data
    if github_version < current_version:
        logger.info('running unreleased version')
    return False


def notify_new_release(view, retrieve_latest_func, check_new_func):
    """If the latest release on github is newer than the current version notify
    the user.

    If its a prerelease version state so.

    :param retrieve_latest_func: a function to retrieve github release data
        json i.e. :func:`retrieve_latest_release_data`
    :param check_new_func: a function to check if release data points to a new
        release and set bauble.release_version i.e. :func:`check_new_release`
    """
    github_release_data = retrieve_latest_func()
    if not github_release_data:
        # used in tests
        logger.debug('no release data')
        return
    new_release = check_new_func(github_release_data)
    if new_release:

        # used in tests
        logger.debug('notifying new release')

        def show_message_box():
            msg = _('New version %s available.') % bauble.release_version
            box = view.add_message_box()
            box.message = msg
            box.show()
            view.add_box(box)

        from gi.repository import GLib
        GLib.idle_add(show_message_box)
    else:
        # used in tests
        logger.debug('not new release')


def make_absolute(path):
    if path.startswith('./') or path.startswith('.\\'):
        path = str(Path(paths.appdata_dir(), path[2:]))
    return path


def check_create_paths(directory):
    """Given a root directory, check and create the documents and pictures
    directories.

    :return: tuple - bool = False if any errors, error msg str
    """
    # if it's a file, things are not OK
    root = make_absolute(directory)
    logger.debug('root directory = %s', root)
    docs = os.path.join(root, prefs.prefs.get(prefs.document_path_pref))
    pics = os.path.join(root, prefs.prefs.get(prefs.picture_path_pref))
    thumbs = os.path.join(pics, 'thumbs')
    # root should exist as a directory
    msg = ''
    valid = [True]
    if root:
        for path, name in ((root, _('Root directory')),
                           (docs, _('Documents directory')),
                           (pics, _('Pictures directory')),):
            if os.path.exists(path):
                if not os.path.isdir(path):
                    valid.append(False)
                    msg += name + _(" name occupied by non directory.\n")
            else:
                os.mkdir(path)

        if os.path.exists(pics) and os.path.isdir(pics):
            if os.path.exists(thumbs):
                if not os.path.isdir(thumbs):
                    valid.append(False)
                    msg += _("Thumbs directory name occupied by non "
                             "directory")
            else:
                os.mkdir(thumbs)
    valid = all(valid)
    logger.debug('check_create_paths: valid=%s; msg=%s', valid, msg)

    return valid, msg


class ConnMgrPresenter(GenericEditorPresenter):
    """The main class that starts the connection manager GUI.

    :param default: the name of the connection to select from the list
      of connection names
    """

    widget_to_field_map = {
        'name_combo': 'connection_name',  # and self.connection_names
        'usedefaults_chkbx': 'use_defaults',
        'type_combo': 'dbtype',
        'file_entry': 'filename',
        'database_entry': 'database',
        'host_entry': 'host',
        'port_entry': 'port',
        'user_entry': 'user',
        'passwd_chkbx': 'passwd',
        'rootdir2_entry': 'rootdir',
        'rootdir_entry': 'rootdir',
    }

    view_accept_buttons = ['cancel_button', 'connect_button']

    def __init__(self, view=None):
        self.filename = None
        self.database = None
        self.host = None
        self.port = None
        self.user = None
        self.rootdir = None
        self.connection_name = None
        self.ignore = None
        self.prev_connection_name = None
        self.use_defaults = True
        self.passwd = False
        # following two look like overkill, since they will be initialized
        # in the parent class constructor. but we need these attributes in
        # place before we can invoke get_params
        # TODO can this be better?
        self.model = self
        self.view = view

        # initialize comboboxes, so we can fill them in
        view.combobox_init('name_combo')
        view.combobox_init('type_combo', DBTYPES, type_combo_cell_data_func)
        self.connection_names = []
        self.connections = prefs.prefs.get(bauble.conn_list_pref, {})
        for ith_connection_name in sorted(self.connections):
            view.comboboxtext_append_text('name_combo', ith_connection_name)
            self.connection_names.append(ith_connection_name)
        if self.connection_names:
            self.connection_name = prefs.prefs[bauble.conn_default_pref]
            if self.connection_name not in self.connections:
                self.connection_name = self.connection_names[0]
                self.prev_connection_name = self.connection_name
            self.dbtype = None
            self.set_params()
        else:
            self.dbtype = ''
            self.connection_name = None
        super().__init__(model=self, view=view, refresh_view=True,
                         session=False)
        logo_path = os.path.join(paths.lib_dir(), "images", "bauble_logo.png")
        view.image_set_from_file('logo_image', logo_path)
        view.set_title(f'Ghini {bauble.version}')
        view.set_icon(GdkPixbuf.Pixbuf.new_from_file(bauble.default_icon))

        from threading import Thread
        set_installation_date()
        logger.debug('checking for new version')
        if not prefs.testing:
            self.start_thread(Thread(target=notify_new_release,
                                     args=[self.view,
                                           retrieve_latest_release_data,
                                           check_new_release]))

    def on_file_btnbrowse_clicked(self, *_args):
        previously = self.view.widget_get_value('file_entry')
        last_folder = self.get_parent_folder(previously)
        self.view.run_file_chooser_dialog(
            _("Choose a file…"),
            None,
            action=Gtk.FileChooserAction.SAVE,
            last_folder=last_folder, target='file_entry')
        self.replace_leading_appdata('file_entry')

    def on_rootdir_btnbrowse_clicked(self, *_args):
        previously = self.view.widget_get_value('rootdir_entry')
        last_folder = self.get_parent_folder(previously)
        self.view.run_file_chooser_dialog(
            _("Choose a file…"),
            None,
            action=Gtk.FileChooserAction.CREATE_FOLDER,
            last_folder=last_folder,
            target='rootdir_entry')
        self.replace_leading_appdata('rootdir_entry')

    def on_rootdir2_btnbrowse_clicked(self, *_args):
        previously = self.view.widget_get_value('rootdir2_entry')
        last_folder = self.get_parent_folder(previously)
        self.view.run_file_chooser_dialog(
            _("Choose a file…"),
            None,
            action=Gtk.FileChooserAction.CREATE_FOLDER,
            last_folder=last_folder, target='rootdir2_entry')
        self.replace_leading_appdata('rootdir2_entry')

    def replace_leading_appdata(self, entry):
        value = self.view.widget_get_value(entry)
        if value.startswith(paths.appdata_dir()):
            value = './' + value[len(paths.appdata_dir()) + 1:]
            self.view.widget_set_value(entry, value)

    @staticmethod
    def get_parent_folder(path):
        if not path:
            return paths.appdata_dir()
        if path.startswith('.'):
            path = Path(paths.appdata_dir()) / Path(path)
            return str(path.parent)
        return str(Path(path).parent)

    def refresh_view(self):
        super().refresh_view()
        conn_dict = self.connections
        if conn_dict is None or len(list(conn_dict.keys())) == 0:
            self.view.widget_set_visible('noconnectionlabel', True)
            self.view.widget_set_visible('expander', False)
            self.prev_connection_name = None
            self.view.widget_set_sensitive('connect_button', False)
        else:
            self.view.widget_set_visible('expander', True)
            self.view.widget_set_visible('noconnectionlabel', False)
            self.view.widget_set_sensitive('connect_button', True)
            if self.dbtype == 'SQLite':
                self.view.widget_set_visible('sqlite_parambox', True)
                self.view.widget_set_visible('dbms_parambox', False)
                self.refresh_entries_sensitive()
            else:
                self.view.widget_set_visible('dbms_parambox', True)
                self.view.widget_set_visible('sqlite_parambox', False)

    def on_usedefaults_chkbx_toggled(self, widget, *args):
        self.on_check_toggled(widget, *args)
        self.refresh_entries_sensitive()

    def refresh_entries_sensitive(self):
        sensitive = not self.use_defaults
        self.view.widget_set_sensitive('file_entry', sensitive)
        self.view.widget_set_sensitive('rootdir_entry', sensitive)
        self.view.widget_set_sensitive('file_btnbrowse', sensitive)
        self.view.widget_set_sensitive('rootdirectory_btnbrowse', sensitive)

    def on_dialog_response(self, dialog, response):
        """The dialog's response signal handler."""
        if response == Gtk.ResponseType.OK:
            settings = self.get_params()
            valid, msg = self.check_parameters_valid(settings)
            if not valid:
                self.view.run_message_dialog(msg, Gtk.MessageType.ERROR)
            if valid:
                # grab directory location from global setting
                prefs.prefs[prefs.root_directory_pref] = make_absolute(
                    settings['directory']
                )
                self.save_current_to_prefs()
        elif response in (Gtk.ResponseType.CANCEL,
                          Gtk.ResponseType.DELETE_EVENT):
            if not self.are_prefs_already_saved(self.connection_name):
                msg = _("Do you want to save your changes?")
                if self.view.run_yes_no_dialog(msg):
                    self.save_current_to_prefs()

        # system-defined GtkDialog responses are always negative, in which
        # case we want to hide it
        if response < 0:
            dialog.hide()

        return response

    def on_dialog_close_or_delete(self, _dialog, _event=None):
        self.view.get_window().hide()
        return True

    def remove_connection(self, name):
        """remove named connection, from combobox and from self"""
        if name in self.connections:
            position = self.connection_names.index(name)
            del self.connection_names[position]
            del self.connections[name]
            self.view.combobox_remove('name_combo', position)
            self.refresh_view()
        prefs.prefs[bauble.conn_list_pref] = self.connections
        prefs.prefs.save()

    def on_remove_button_clicked(self, _button):
        """remove the connection from connection list, this does not affect
        the database or its data
        """
        msg = (_('Are you sure you want to remove "%s"?\n\n'
                 '<i>Note: This only removes the connection to the database '
                 'and does not affect the database or its data</i>')
               % self.connection_name)

        if not self.view.run_yes_no_dialog(msg):
            return
        self.remove_connection(self.connection_name)

    def on_add_button_clicked(self, _button):
        if not self.are_prefs_already_saved(self.prev_connection_name):
            msg = (_("Do you want to save your changes to %s ?")
                   % self.prev_connection_name)
            if self.view.run_yes_no_dialog(msg):
                self.save_current_to_prefs()
        self.prev_connection_name = None
        name = self.view.run_entry_dialog(
            _("Enter a connection name"),
            self.view.get_window(),
            buttons=('OK', Gtk.ResponseType.ACCEPT),
            modal=True,
            destroy_with_parent=True
        )
        if name != '':
            self.connection_name = name
            self.connection_names.insert(0, name)
            self.connections[name] = self.get_params(new=name)
            self.view.comboboxtext_prepend_text('name_combo', name)
            self.view.widget_set_expanded('expander', True)
            self.view.combobox_set_active('name_combo', 0)
            self.refresh_view()

    def save_current_to_prefs(self):
        """add current named params to saved connections"""
        if self.connection_name is None:
            return
        logger.debug('save current to prefs')
        if bauble.conn_list_pref not in prefs.prefs:
            prefs.prefs[bauble.conn_list_pref] = {}
        params = copy.copy(self.get_params())
        conn_dict = self.connections
        conn_dict[self.connection_name] = params
        prefs.prefs[bauble.conn_list_pref] = conn_dict
        prefs.prefs.save()

    def are_prefs_already_saved(self, name):
        """are current prefs already saved under given name?"""
        if not name:  # no name, no need to check
            return True

        if name == self.ignore:  # generally development only
            return True

        conn_dict = prefs.prefs.get(bauble.conn_list_pref, {})

        if conn_dict is None or name not in conn_dict:
            return False

        stored_params = conn_dict[name]
        params = copy.copy(self.get_params())

        return params == stored_params

    def on_name_combo_changed(self, combo, data=None):
        """the name changed so fill in everything else"""
        logger.debug('on_name_combo_changing from %s to %s',
                     self.prev_connection_name, self.connection_name)

        self.view.widgets.type_combo.set_sensitive(True)

        conn_dict = self.connections
        if (self.prev_connection_name is not None and
                self.prev_connection_name in self.connection_names):
            # we are leaving some valid settings
            if self.prev_connection_name not in conn_dict:
                msg = _("Do you want to save %s?") % self.prev_connection_name
                if self.view.run_yes_no_dialog(msg):
                    self.save_current_to_prefs()
                else:
                    self.remove_connection(self.prev_connection_name)
            elif not self.are_prefs_already_saved(self.prev_connection_name):
                msg = (_("Do you want to save your changes to %s ?")
                       % self.prev_connection_name)
                if self.view.run_yes_no_dialog(msg):
                    self.save_current_to_prefs()

        if self.connection_names:
            self.on_combo_changed(combo, data)  # this updates connection_name
        logger.debug('on_name_combo_changed %s', self.connection_name)
        logger.debug("changing form >%s< to >%s<", self.prev_connection_name,
                     self.connection_name)

        if self.connection_name in conn_dict:
            # we are retrieving connection info from the global settings
            if conn_dict[self.connection_name]['type'] not in DBTYPES:
                # in case the connection type has changed or isn't supported
                # on this computer
                self.view.widgets.type_combo.set_active(-1)
                self.view.widgets.type_combo.set_sensitive(False)
                self.ignore = self.connection_name
            else:
                index = DBTYPES.index(conn_dict[self.connection_name]
                                      ["type"])
                self.view.combobox_set_active('type_combo', index)
                self.set_params(conn_dict[self.connection_name])
        else:  # this is for new connections
            self.view.combobox_set_active('type_combo', 0)
        self.refresh_view()
        self.prev_connection_name = self.connection_name

        self.replace_leading_appdata('file_entry')
        self.replace_leading_appdata('rootdir_entry')
        self.replace_leading_appdata('rootdir2_entry')

    def get_passwd(self):
        """Show a dialog with and entry and return the value entered."""
        passwd = self.view.run_entry_dialog(
            _("Enter your password"),
            None,
            ('OK', Gtk.ResponseType.ACCEPT),
            visible=False,
            modal=True,
            destroy_with_parent=True
        )
        return passwd

    def parameters_to_uri(self, params):
        """return connections paramaters as a uri"""
        subs = copy.copy(params)
        if params['type'].lower() == "sqlite":
            filename = make_absolute(params['file'].replace('\\', '/'))
            uri = "sqlite:///" + filename
            return uri
        subs['type'] = params['type'].lower()
        if params.get('port') is not None:
            template = "%(type)s://%(user)s@%(host)s:%(port)s/%(db)s"
        else:
            template = "%(type)s://%(user)s@%(host)s/%(db)s"
        if params["passwd"] is True:
            subs["passwd"] = self.get_passwd()
            if subs["passwd"]:
                template = template.replace('@', ':%(passwd)s@')
        uri = template % subs
        options = []
        if 'options' in params:
            options = '&'.join(params['options'])
            uri += '?'
            uri += options
        return uri

    @property
    def connection_uri(self):
        params = copy.copy(self.get_params())
        return self.parameters_to_uri(params)

    def check_parameters_valid(self, params):
        """check for errors in the connection params,
        return a tuple:
        first is a boolean indicating validity;
        second is the localized error message.
        """
        if self.view.combobox_get_active_text('name_combo') == "":
            return False, _("Please choose a name for this connection")
        valid = True
        msg = None
        # first check connection parameters, then directory path
        if params['type'] == 'SQLite':
            filename = make_absolute(params['file'])
            if not os.path.exists(filename):
                path, _f = os.path.split(filename)
                if not os.access(path, os.R_OK):
                    valid = False
                    msg = _("Ghini does not have permission to "
                            "read the directory:\n\n%s") % path
                elif not os.access(path, os.W_OK):
                    valid = False
                    msg = _("Ghini does not have permission to "
                            "write to the directory:\n\n%s") % path
            elif not os.access(filename, os.R_OK):
                valid = False
                msg = _("Ghini does not have permission to read the "
                        "database file:\n\n%s") % filename
            elif not os.access(filename, os.W_OK):
                valid = False
                msg = _("Ghini does not have permission to "
                        "write to the database file:\n\n%s") % filename
        else:
            missing_fields = []
            if params["user"] == "":
                valid = False
                missing_fields.append(_("user name"))
            if params["db"] == "":
                valid = False
                missing_fields.append(_("database name"))
            if params["host"] == "":
                valid = False
                missing_fields.append(_("DBMS host name"))
            if not valid:
                msg = _("Current connection does not specify the fields:\n"
                        "%s\nPlease specify and try again."
                        ) % "\n".join(missing_fields)
        if not valid:
            return valid, msg
        # now check the params['directory']
        valid, msg = check_create_paths(params['directory'])

        return valid, msg

    def get_params(self, new=None):
        if new is not None:
            self.dbtype = 'SQLite'
            self.use_defaults = True
        if self.dbtype == 'SQLite':
            if self.use_defaults is True:
                name = new or self.connection_name
                self.filename = os.path.join('.', name + '.db')
                self.rootdir = os.path.join('.', name)
            result = {'file': self.filename,
                      'default': self.use_defaults,
                      'directory': self.rootdir}
        else:
            result = {'db': self.database,
                      'host': self.host,
                      'port': self.port,
                      'user': self.user,
                      'directory': self.rootdir,
                      'passwd': self.passwd}
        result['type'] = self.dbtype
        return result

    def set_params(self, params=None):
        if params is None:
            params = self.connections[self.connection_name]
        self.dbtype = params['type']
        if self.dbtype == 'SQLite':
            self.filename = params['file']
            self.use_defaults = params['default']
            self.rootdir = params.get('directory', '')
        else:
            self.database = params['db']
            self.host = params['host']
            self.port = params.get('port')
            self.user = params['user']
            self.rootdir = params.get('directory', '')
            self.passwd = params['passwd']
        self.refresh_view()


def start_connection_manager(msg=None):
    """activate connection manager and return connection name and uri"""
    glade_path = os.path.join(paths.lib_dir(), "connmgr.glade")
    tooltips = {
        'rootdir2_entry': _('Set a directory to store file data in.  If left '
                            'blank you can set a global directory in the '
                            'database via the options menu.'),
        'rootdir_entry': _('Set a directory to store file data in.  If left '
                           'blank you can set a global directory in the '
                           'database via the options menu.')
    }
    view = GenericEditorView(
        glade_path,
        parent=None,
        root_widget_name='main_dialog',
        tooltips=tooltips
    )
    if msg:
        view.widgets.image_box.remove(view.widgets.logo_image)
        label = Gtk.Label()
        label.set_markup(msg)
        label.set_margin_top(10)
        view.widgets.image_box.pack_start(label, True, True, 12)
        view.widgets.image_box.show_all()

    con_mgr = ConnMgrPresenter(view)
    result = con_mgr.start()
    if result == Gtk.ResponseType.OK:
        con_mgr.view.get_window().destroy()
        return con_mgr.connection_name, con_mgr.connection_uri
    return None, None
