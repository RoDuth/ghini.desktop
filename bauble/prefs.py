# Copyright 2008-2010 Brett Adams
# Copyright 2015 Mario Frasca <mario@anche.no>.
# Copyright 2019-2022 Ross Demuth <rossdemuth123@gmail.com>
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
The prefs module exposes an API for getting and setting user preferences in the
config file.

To use the preferences import bauble.prefs and access the prefs object
using a dictionary like interface. e.g. ::

    from bauble import prefs
    prefs.prefs[key] = value

Can also access the preference keys e.g. ::

    prefs.date_format_pref
"""


import logging
import os
from ast import literal_eval
from collections import UserDict
from configparser import ConfigParser
from configparser import Error
from datetime import datetime
from pathlib import Path
from shutil import copy2

from filelock import FileLock

logger = logging.getLogger(__name__)

from gi.repository import Gio
from gi.repository import Gtk

import bauble
from bauble import db
from bauble import meta
from bauble import paths
from bauble import pluginmgr
from bauble import utils

testing = os.environ.get('BAUBLE_TEST')  # set this to True when testing

# TODO: maybe we should have a create method that creates the preferences
# to do a one time thing if the files doesn't exist

# TODO: Consider using ConfigObj since it does validation, type
# conversion and unicode automatically...the cons are that it adds
# another dependency and we would have to change the prefs interface
# throughout bauble

default_filename = 'config'
default_prefs_file = os.path.join(paths.appdata_dir(), default_filename)
"""
The default file for the preference settings file.
"""

config_version_pref = 'bauble.config.version'
"""
The preferences key for the bauble version of the preferences file.
"""

config_version = bauble.version_tuple[0], bauble.version_tuple[1]

date_format_pref = 'bauble.default_date_format'
"""
The preferences key for the default date format.
"""

time_format_pref = 'bauble.default_time_format'
"""
The preferences key for the default time format.
"""

datetime_format_pref = 'bauble.default_datetime_format'
"""
The preferences key for the default date and time format.  This is generated
by combining the date_format_pref and time_format_pref string. It is NOT saved
to the config file.
"""

parse_dayfirst_pref = 'bauble.parse_dayfirst'
"""
The preferences key for determining whether the day should come first when
parsing date strings.  This is generated from the date_format_pref string. It
is NOT saved to the config file.

For more information see the.
:meth:`dateutil.parser.parse` method.

Values: True, False
"""

parse_yearfirst_pref = 'bauble.parse_yearfirst'
"""
The preferences key for determining whether the year should come first when
parsing date strings.  This is generated from the date_format_pref string. It
is NOT saved to the config file.

 For more information see the
:meth:`dateutil.parser.parse` method.

Values: True, False
"""

root_directory_pref = 'bauble.root_directory'
"""
The preferences key for the default directory root
"""

document_path_pref = 'bauble.documents_path'
"""
The preferences key for the name of the documents subdirectory
"""

picture_path_pref = 'bauble.pictures_path'
"""
The preferences key for the name of the documents subdirectory
"""

document_root_pref = 'bauble.document_root'
"""
The preferences key for the default documents root, This is generated from the
root_directory_pref.
"""

picture_root_pref = 'bauble.picture_root'
"""
The preferences key for the default pictures root, This is generated from the
root_directory_pref.
"""

units_pref = 'bauble.units'
"""
The preferences key for the default units for Ghini.

Values: metric, imperial
"""

use_sentry_client_pref = 'bauble.use_sentry_client'
"""
During normal usage, Ghini produces a log file which contains
invaluable information for tracking down errors. This information is
normally saved in a file on the local workstation.

This preference key controls the option of sending exceptional
conditions (WARNING and ERROR, normally related to software problems)
to a central logging server, and developers will be notified by email
of the fact that you encountered a problem.

Logging messages at the levels Warning and Error do not contain personal
information. If you have completed the registration steps, a developer
might contact you to ask for further details, as it could be the
complete content of your log file.

Values: True, False (Default: False)
"""

debug_logging_prefs = "bauble.debug_logging_modules"
"""
Modules listed here will have debug level logging.  The level is inherited by
sub modules.  To enable all set it to:

debug_logging_modules = ['bauble']

Values: a list of modules names e.g.:

['bauble.plugins.plants.species', 'bauble.plugins.garden']
"""

web_proxy_prefs = 'web.proxies'
"""
If None then we use pypac to try to find proxy settings.
To manually set proxies (and use requests over pypac) add something like
this to your config file:

[web]
proxies = {"https": "http://10.10.10.10/8000", "http": "http://10.10.10.10:8000"}

To just make sure we use requests over PACSession then use anything other
than a dict for the value of proxies e.g.:

proxies = "no"
"""   # noqa

return_accepted_pref = 'bauble.search.return_accepted'
"""
The preferences key for also returning accepted names for results that are
considered synonyms.
"""

exclude_inactive_pref = 'bauble.search.exclude_inactive'
"""
The preferences key for ignoring inactive (deaccessioned etc.) search results.
"""

query_builder_recurse = 'bauble.query_builder.recurse'
"""
The preferences key for allowing recurse in QueryBuilder's SchemaMenu.
i.e. accessions.species.accessions.species
"""

query_builder_advanced = 'bauble.query_builder.advanced'
"""
The preferences key for displaying QueryBuilder's SchemaMenu in advanced view.
"""

query_builder_excludes = 'bauble.query_builder.basic_excludes'
"""
The preferences key for which columns to exclude from the SchemaMenu in basic
view.
"""

# althought these relate to plugins they are only strings and best placed here.
QB_EXCLUDE_DEFAULTS = ['Genus.genus',
                       'Genus.subfamily',
                       'Genus.tribe',
                       'Genus.subtribe',
                       'Genus.author',
                       'Genus.qualifier',
                       'Family.family',
                       'Family.order',
                       'Family.suborder',
                       'Family.author',
                       'Family.qualifier',
                       'Species.active',
                       'Species.awards',
                       'Species.cv_group',
                       'Species.full_sci_name',
                       'Species.hybrid',
                       'Species.infrasp1',
                       'Species.infrasp1_author',
                       'Species.infrasp1_rank',
                       'Species.infrasp2',
                       'Species.infrasp2_author',
                       'Species.infrasp2_rank',
                       'Species.infrasp3',
                       'Species.infrasp3_author',
                       'Species.infrasp3_rank',
                       'Species.infrasp4',
                       'Species.infrasp4_author',
                       'Species.infrasp4_rank',
                       'Species.infraspecific_epithet',
                       'Species.infraspecific_rank',
                       'Species.label_distribution',
                       'Species.label_markup',
                       'Species.trademark_symbol',
                       'Species.section',
                       'Species.series',
                       'Species.sp',
                       'Species.sp_author',
                       'Species.sp_qual',
                       'Species.subgenus',
                       'Species.subsection',
                       'Species.subseries']


class _prefs(UserDict):

    def __init__(self, filename=default_prefs_file):
        super().__init__()
        self._filename = filename
        self._lock_filename = filename + '.lock'
        self._lock_timeout = 6
        self.config = None

    def init(self):
        """initialize the preferences, should only be called from app.main"""
        # create directory tree of filename if it doesn't yet exist
        logger.debug('init prefs with filename: %s', self._filename)
        head, _tail = os.path.split(self._filename)
        if not os.path.exists(head):
            os.makedirs(head)

        self.config = ConfigParser(interpolation=None, strict=False)

        # set the version if the file doesn't exist
        if not os.path.exists(self._filename):
            self[config_version_pref] = config_version
            logger.debug('filename does not exist: %s', self._filename)
        else:
            try:
                copy2(self._filename, self._filename + '_PREV')
            except Exception as e:  # pylint: disable=broad-except
                logger.debug('try copy previous config failed: %s(%s)',
                             type(e).__name__, e)
            logger.debug('reading config from %s', self._filename)

            with FileLock(self._lock_filename, timeout=self._lock_timeout):
                try:
                    self.config.read(self._filename, encoding='utf-8')
                except Error as e:
                    logger.warning('reading config raised: %s(%s)',
                                   type(e).__name__, e)
                    # keep a copy and keep logging at debug level if reading
                    # config fails
                    try:
                        tstamp = datetime.now().strftime('%Y%m%d%M%S')
                        copy2(self._filename, self._filename + 'CRPT' + tstamp)
                    except Exception as e:  # pylint: disable=broad-except
                        logger.debug('try copy corrupt config failed: %s(%s)',
                                     type(e).__name__, e)
                    self[debug_logging_prefs] = ['bauble']

        version = self[config_version_pref]

        if version is None:
            logger.debug('%s has no config version pref', self._filename)
            logger.debug('setting the config version to %s.%s',
                         config_version[0], config_version[1])
            self[config_version_pref] = config_version

        # set some defaults if they don't exist (not added using update_prefs
        # because they are added even if the section already exists)
        defaults = [(root_directory_pref, ''),
                    (date_format_pref, '%d-%m-%Y'),
                    (time_format_pref, '%I:%M:%S %p'),
                    (units_pref, 'metric'),
                    (debug_logging_prefs, []),
                    (query_builder_recurse, False),
                    (query_builder_advanced, False),
                    (query_builder_excludes, QB_EXCLUDE_DEFAULTS)]

        for key, value in defaults:
            self.add_default(key, value)

    @property
    def dayfirst(self):
        # pylint: disable=no-member
        fmat = self[date_format_pref]
        if fmat.find('%d') < fmat.find('%m'):
            return True
        return False

    @property
    def yearfirst(self):
        # pylint: disable=no-member
        fmat = self[date_format_pref]
        if fmat.startswith('%Y') or fmat.startswith('%y'):
            return True
        return False

    @property
    def datetime_format(self):
        # could provide an option for the seperator?
        fmat = f'{self.get(date_format_pref)} {self.get(time_format_pref)}'
        return fmat

    @staticmethod
    def _get_meta_value_or_default(name, default):
        """Returns the value from BaubleMeta if available else the default

        NOTE: If the database is not yet connected (i.e. connmgr) returns
        default.
        """
        if db.Session:
            return meta.get_cached_value(name) or default
        return default

    @property
    def root_directory(self):
        section, option = self._parse_key(root_directory_pref)
        if (self.config.has_section(section) and
                self.config.has_option(section, option)):
            root = self.config.get(section, option)
            if root:
                logger.debug('root_directory = %s', root)
                return root
        return self._get_meta_value_or_default(
            root_directory_pref.split('.')[1], ''
        )

    @property
    def document_root(self):
        return os.path.join(self[root_directory_pref],
                            self[document_path_pref])

    @property
    def documents_path(self):
        section, option = self._parse_key(document_path_pref)
        if (self.config.has_section(section) and
                self.config.has_option(section, option)):
            path = self.config.get(section, option)
            if path:
                return path
        return self._get_meta_value_or_default(
            document_path_pref.split('.')[1], 'documents'
        )

    @documents_path.setter
    def documents_path(self, path):
        if path != self[document_path_pref]:
            if os.path.exists(self.document_root):
                os.rename(self.document_root,
                          os.path.join(self.root_directory, path))

    @property
    def picture_root(self):
        return os.path.join(self[root_directory_pref],
                            self[picture_path_pref])

    @property
    def pictures_path(self):
        section, option = self._parse_key(picture_path_pref)
        if (self.config.has_section(section) and
                self.config.has_option(section, option)):
            path = self.config.get(section, option)
            if path:
                return path
        return self._get_meta_value_or_default(
            picture_path_pref.split('.')[1], 'pictures'
        )

    @pictures_path.setter
    def pictures_path(self, path):
        if path != self[picture_path_pref]:
            if os.path.exists(self.picture_root):
                os.rename(self.picture_root,
                          os.path.join(self.root_directory, path))

    def add_default(self, key, value):
        if key not in self:
            logger.debug('setting default %s = %s', key, value)
            self[key] = value

    def reload(self):
        """Update the current preferences to any external changes in the file,
        """
        # make a new instance and reread the file into it.
        self.config = ConfigParser(interpolation=None, strict=False)
        logger.debug('reload config from %s', self._filename)
        with FileLock(self._lock_filename, timeout=self._lock_timeout):
            self.config.read(self._filename, encoding='utf-8')

    @staticmethod
    def _parse_key(name):
        section, _, item = name.rpartition('.')
        return section, item

    def get(self, key, default=None):
        """get value for key else return default"""
        value = self[key]
        if value is None:
            return default
        return value

    def __getitem__(self, key):
        # Avoid errors when init has not been called (e.g. multiproc_counter)
        if self.config is None:
            return None
        if key == parse_dayfirst_pref:
            return self.dayfirst
        if key == parse_yearfirst_pref:
            return self.yearfirst
        if key == datetime_format_pref:
            return self.datetime_format
        if key == root_directory_pref:
            return self.root_directory
        if key == document_root_pref:
            return self.document_root
        if key == document_path_pref:
            return self.documents_path
        if key == picture_root_pref:
            return self.picture_root
        if key == picture_path_pref:
            return self.pictures_path

        section, option = self._parse_key(key)
        # this doesn't allow None values for preferences
        if (not self.config.has_section(section) or
                not self.config.has_option(section, option)):
            return None
        item = self.config.get(section, option)

        # avoid excessively long values
        if len(item) > 20000:
            logger.warning('%s appears corrupted - ignoring', key)
            item = ''

        if item == '':
            return item

        try:
            item = literal_eval(item)
        except (ValueError, SyntaxError):
            pass

        return item

    def __delitem__(self, key):
        section, option = self._parse_key(key)
        if (not self.config.has_section(section) or
                not self.config.has_option(section, option)):
            return
        section_options = self.config.options(section)
        logger.debug('section %s has options: %s', section, section_options)
        if len(section_options) == 1 and section_options[0] == option:
            logger.debug('deleting section: %s', section)
            self.config.remove_section(section)
        else:
            logger.debug('deleting option: %s', str(section + '.' + option))
            self.config.remove_option(section, option)

    def iteritems(self):
        for section in sorted(self.config.sections()):
            for name, value in self.config.items(section):
                yield (f'{section}.{name}', value)

    def itersection(self, section):
        if self.has_section(section):
            for option in self.config[section]:
                yield option, self.get(f'{section}.{option}')

    def __setitem__(self, key, value):
        # avoid excessively long values
        if len(str(value)) > 20000:
            logger.warning('%s appears corrupt not saving', key)
            return
        if key == document_path_pref:
            self.documents_path = value
        if key == picture_path_pref:
            self.pictures_path = value
        section, option = self._parse_key(key)
        if not self.config.has_section(section):
            self.config.add_section(section)
        self.config.set(section, option, str(value))

    def __contains__(self, key):
        section, option = self._parse_key(key)
        if (self.config.has_section(section) and
                self.config.has_option(section, option)):
            return True
        return False

    def has_section(self, section):
        return self.config.has_section(section)

    def save(self, force=False):
        logger.debug('saving prefs')
        logger.debug('prefs sections = %s', self.config.sections())
        if testing and not force:
            return
        with FileLock(self._lock_filename, timeout=self._lock_timeout):
            try:
                with open(self._filename, "w+", encoding='utf-8') as f:
                    self.config.write(f)
            except Exception:  # pylint: disable=broad-except
                msg = (_("Can't save your user preferences. \n\nPlease check "
                         "the file permissions of your config file:\n %s")
                       % self._filename)
                if bauble.gui is not None and bauble.gui.window is not None:
                    utils.message_dialog(msg, typ=Gtk.MessageType.ERROR,
                                         parent=bauble.gui.window)
                else:
                    logger.error(msg)


def update_prefs(conf_file):
    """Given a config file with sections add the sections to the current users
    config (prefs) if the section does not already exist.
    """
    config = ConfigParser(interpolation=None)

    config.read(conf_file)
    # return config
    # defaults = config.sections()
    logger.debug('looking for prefs sections in %s', conf_file)
    for section in config.sections():
        if not prefs.has_section(section):
            logger.debug('adding section: %s', section)
            for option in config[section]:
                prefs[f'{section}.{option}'] = config.get(section, option)
        elif (config.has_section(section) and
              config.has_option(section, '_extend')):
            for option in config[section]:
                if option != '_extend' and f'{section}.{option}' not in prefs:
                    prefs[f'{section}.{option}'] = config.get(section, option)
    prefs.save()


def set_global_root(*_args):
    """Ask user to set the global root directory in the BaubleMeta table."""
    # NOTE this would require the user to first remove prefs for documents_path
    # and pictures_path if set.  Also, it would be up to the user to move the
    # pictures and documents root if they rename them.
    msg = _('Set a global root directory that can be used by not setting the '
            '"Root directory" option in the connection manager (user can '
            'still override).'
            '\n\nSetting pictures_path and documents_path allows setting the '
            'subdirectory names used for these.')
    names = [root_directory_pref.split('.')[1],
             picture_path_pref.split('.')[1],
             document_path_pref.split('.')[1]]
    from bauble.connmgr import check_create_paths
    from bauble.connmgr import make_absolute
    defaults = [make_absolute(prefs.get(root_directory_pref)),
                prefs.get(picture_path_pref),
                prefs.get(document_path_pref)]
    meta_paths = meta.set_value(names, defaults, msg)
    if meta_paths:
        check_create_paths(meta_paths[0].value)


def post_gui():
    """Do any setup that requires bauble.gui to be set first."""
    bauble.gui.add_action("set_global_root", set_global_root)

    item = Gio.MenuItem.new(_('Set Global Directory'), 'win.set_global_root')
    bauble.gui.options_menu.append_item(item)


@Gtk.Template(filename=str(Path(paths.lib_dir(), 'prefs_view.ui')))
class PrefsView(pluginmgr.View, Gtk.Box):
    """The PrefsView displays the values in the plugin registry and displays
    and allows limited editing of preferences, only after warning users of
    possible dangers.
    """

    __gtype_name__ = 'PrefsView'

    prefs_ls = Gtk.Template.Child()
    plugins_ls = Gtk.Template.Child()
    prefs_tv = Gtk.Template.Child()
    prefs_data_renderer = Gtk.Template.Child()
    prefs_edit_chkbx = Gtk.Template.Child()

    def __init__(self):
        logger.debug('PrefsView::__init__')
        super().__init__()
        self.button_press_id = None
        self.init_menu()

    def init_menu(self):
        action_group_name = 'prefs_view'
        action_group = Gio.SimpleActionGroup()
        action = Gio.SimpleAction.new('insert', None)
        action.connect('activate', self.on_prefs_insert_activate)
        action_group.add_action(action)
        item = Gio.MenuItem.new(_('_Insert'),
                                f'{action_group_name}.insert')
        menu_model = Gio.Menu()
        menu_model.append_item(item)
        self.context_menu = Gtk.Menu.new_from_model(menu_model)
        self.context_menu.attach_to_widget(self.prefs_tv)
        self.prefs_tv.insert_action_group(action_group_name, action_group)

    def on_button_press_event(self, _widget, event):
        logger.debug('event.button %s', event.button)
        if event.button == 3:

            self.context_menu.popup_at_pointer(event)

    def on_prefs_insert_activate(self, _action, _param):
        try:
            model, tree_path = (self.prefs_tv
                                .get_selection()
                                .get_selected_rows())
            logger.debug('model: %s tree_path: %s', model, tree_path)
            if not model or not tree_path:
                logger.debug('no model or tree_path')
                return
            self.add_new(model, tree_path)
        except Exception as e:   # pylint: disable=broad-except
            msg = utils.xml_safe(str(e))
            logger.warning(msg)

    @staticmethod
    def add_new(model, tree_path, text=None):
        msg = _('New option name')
        selected = [model[row][0] for row in tree_path][0]
        section = selected.rsplit('.', 1)[0]
        logger.debug('start a dialog for new section %s', section)
        dialog = utils.create_message_dialog(msg=msg)
        message_area = dialog.get_message_area()
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        option_entry = Gtk.Entry()
        if not text:
            text = f'{section}.'
        option_entry.set_text(text)
        box.add(option_entry)
        message_area.add(box)
        dialog.resize(1, 1)
        dialog.show_all()
        new_iter = None
        if dialog.run() == Gtk.ResponseType.OK:
            tree_iter = model.get_iter(tree_path)
            option = option_entry.get_text()
            new_iter = model.insert_after(
                tree_iter, row=[option, '', None])
            logger.debug('adding new pref option %s', option)
        dialog.destroy()
        return new_iter

    @Gtk.Template.Callback()
    def on_prefs_edit_toggled(self, widget):
        state = widget.get_active()
        logger.debug('edit state %s', state)
        msg = _(
            '\n\n<b>CAUTION! Making incorrect changes to your preferences '
            'could be detrimental.\n\nDO YOU WISH TO PROCEED?</b>\n\nSome '
            'changes will not take effect until restarted.'
        )
        parent = bauble.gui.window if bauble.gui else None
        if state and utils.yes_no_dialog(msg, parent=parent):
            logger.debug('enable editing prefs')
            self.prefs_data_renderer.set_property('editable', state)
            self.button_press_id = self.prefs_tv.connect(
                "button-press-event", self.on_button_press_event)

        else:
            logger.debug('disable editing prefs')
            widget.set_active(False)
            self.prefs_data_renderer.set_property('editable', False)
            if self.button_press_id:
                self.prefs_tv.disconnect(self.button_press_id)
                self.button_press_id = None

    @Gtk.Template.Callback()
    def on_prefs_edited(self, _renderer, path, new_text):
        key, repr_str, type_str = self.prefs_ls[path]
        if new_text == '':
            msg = _('Delete the %s preference key?') % key
            parent = bauble.gui.window if bauble.gui else None
            if utils.yes_no_dialog(msg, parent=parent):
                del prefs[key]
                prefs.save()
                self.refresh_view()
                logger.debug('deleting: %s', key)
                self.prefs_ls.remove(
                    self.prefs_ls.get_iter_from_string(str(path))
                )
                return

        try:
            new_val = literal_eval(new_text)
        except (ValueError, SyntaxError):
            new_val = new_text

        if isinstance(new_val, str):
            if key.endswith('root_directory') and not Path(new_val).exists():
                new_val = ''

        new_val_type = type(new_val).__name__

        if type_str and (new_val == '' or new_val_type != type_str):
            self.prefs_ls[path][1] = repr_str
            return

        prefs[key] = new_val
        self.prefs_ls[path][1] = str(new_val)
        self.prefs_ls[path][2] = new_val_type
        prefs.save()
        self.refresh_view()

    @Gtk.Template.Callback()
    @staticmethod
    def on_prefs_backup_clicked(_widget):
        copy2(default_prefs_file, default_prefs_file + 'BAK')

    @Gtk.Template.Callback()
    def on_prefs_restore_clicked(self, _widget):
        # pylint: disable=using-constant-test
        if Path(default_prefs_file + 'BAK').exists():
            copy2(default_prefs_file + 'BAK', default_prefs_file)
            prefs.reload()
            self.update()
        else:
            utils.message_dialog(_('No backup found'))

    def update(self, *_args):
        self.prefs_ls.clear()
        for key, value in sorted(prefs.iteritems()):
            logger.debug('update prefs: %s, %s, %s', key, value,
                         prefs[key].__class__.__name__)
            self.prefs_ls.append((key, value, prefs[key].__class__.__name__))

        self.plugins_ls.clear()
        from bauble.pluginmgr import PluginRegistry
        session = db.Session()
        plugins = session.query(PluginRegistry.name, PluginRegistry.version)
        for item in plugins:
            self.plugins_ls.append(item)
        session.close()
        self.refresh_view()

    @staticmethod
    def refresh_view():
        if bauble.gui is not None:
            # may be more to do here yet...
            bauble.gui.populate_main_entry()


class PrefsCommandHandler(pluginmgr.CommandHandler):

    command = ('prefs', 'config')
    view = None

    def __call__(self, cmd, arg):
        pass

    def get_view(self):
        if self.view is None:
            self.__class__.view = PrefsView()
        self.view.update()
        return self.view


pluginmgr.register_command(PrefsCommandHandler)

# NOTE mainly for the sake of testing and using a temp pref file its best to
# avoid importing prefs directly

prefs = _prefs()
"""The prefs instance.  Should only be instantiated once.

Do not import this directly. Instead use:

    from bauble import prefs
    pref.pref.get('key')
"""
