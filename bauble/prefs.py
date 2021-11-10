# Copyright 2008-2010 Brett Adams
# Copyright 2015 Mario Frasca <mario@anche.no>.
# Copyright 2019-2021 Ross Demuth <rossdemuth123@gmail.com>
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

import os
from collections import UserDict
from pathlib import Path
from ast import literal_eval
from configparser import ConfigParser

import logging
logger = logging.getLogger(__name__)

from gi.repository import Gtk  # noqa

import bauble
from bauble import db
from bauble import paths
from bauble import pluginmgr
from bauble import utils

testing = os.environ.get('BAUBLE_TEST')  # set this to True when testing
# can be set using the BAUBLE_TEST environment variable. (Handy for python
# (IPython, etc.) REPL use)
# i.e. in bash or similar shells use:
# BAUBLE_TEST=True python
# in windows you would use something like this?:
# cmd /V /C "set BAUBLE_TEST=True&& ipython"

"""
The prefs module exposes an API for getting and setting user
preferences in the Ghini config file.

To use the preferences import bauble.prefs and access the prefs object
using a dictionary like interface. e.g. ::

    from bauble import prefs
    prefs.prefs[key] = value

Can also access the preference keys e.g. ::

    prefs.date_format_pref
"""

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

picture_root_pref = 'bauble.picture_root'
"""
The preferences key for the default pictures root
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

templates_root_pref = 'template_downloader.root_dir'
"""
Directory to store downloaded templates and their config etc..
"""

PLT_DEFAULTS = {
    'search_by': ['plt_code', 'accession'],
    'fields': {
        'plt_id': 'id',
        'plt_label': 'plant',
        'sp_label': 'accession.species',
        'accession': 'accession.code',
        'plt_code': 'code',
        'quantity': 'quantity',
        'bed': 'location.code',
        'family': 'accession.species.genus.family.epithet',
        'genus': 'accession.species.genus.epithet',
        'species': 'accession.species.epithet',
        'infrasp': 'accession.species.infraspecific_parts',
        'cultivar': 'accession.species.cultivar_epithet',
        'vernacular': 'accession.species.default_vernacular_name',
        'field_note': 'Note',
    }
}

plant_shapefile_prefs = 'shapefile.plant'
"""
The default search_by, field map and read only field definitions that are safe
to use for records based on Plant objects.  PLT_DEFAULTS contains the base
defaults.
"""

LOC_DEFAULTS = {
    'search_by': ['loc_code'],
    'fields': {
        'loc_id': 'id',
        'loc_code': 'code',
        'name': 'name',
        'descript': 'description',
        'field_note': 'Note'
    }
}

location_shapefile_prefs = 'shapefile.location'
"""
The default search_by, field map and read only field definitions that are safe
to use for records based on Location objects.  LOC_DEFAULTS contains the base
defaults.
"""


class _prefs(UserDict):

    def __init__(self, filename=default_prefs_file):
        super().__init__()
        self._filename = filename
        logger.debug('init prefs with filename: %s', filename)
        self.config = None

    def init(self):
        """
        initialize the preferences, should only be called from app.main
        """
        # create directory tree of filename if it doesn't yet exist
        head, _tail = os.path.split(self._filename)
        if not os.path.exists(head):
            os.makedirs(head)

        self.config = ConfigParser(interpolation=None)

        # set the version if the file doesn't exist
        if not os.path.exists(self._filename):
            self[config_version_pref] = config_version
        else:
            self.config.read(self._filename)
        version = self[config_version_pref]
        if version is None:
            logger.warning('%s has no config version pref', self._filename)
            logger.warning('setting the config version to %s.%s',
                           config_version[0], config_version[1])
            self[config_version_pref] = config_version

        # set some defaults if they don't exist
        defaults = [(picture_root_pref, ''),
                    (date_format_pref, '%d-%m-%Y'),
                    (time_format_pref, '%I:%M:%S %p'),
                    (units_pref, 'metric'),
                    (debug_logging_prefs, [])]

        for key, value in defaults:
            self.add_default(key, value)

        for k, v in LOC_DEFAULTS.items():
            section = f'{location_shapefile_prefs}.{k}'
            self.add_default(section, v)
        for k, v in PLT_DEFAULTS.items():
            section = f'{plant_shapefile_prefs}.{k}'
            self.add_default(section, v)

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
        if fmat.find('%Y') == 0 or fmat.find('%y') == 0:
            return True
        return False

    @property
    def datetime_format(self):
        # could provide an option for the seperator?
        fmat = f'{self.get(date_format_pref)} {self.get(time_format_pref)}'
        return fmat

    def add_default(self, key, value):
        if key not in self:
            self[key] = value

    def reload(self):
        """
        Update the current preferences to any external changes in the file,
        """
        # make a new instance and reread the file into it.
        self.config = ConfigParser(interpolation=None)
        self.config.read(self._filename)

    @staticmethod
    def _parse_key(name):
        index = name.rfind(".")
        return name[:index], name[index + 1:]

    def get(self, key, default=None):
        """
        get value for key else return default
        """
        value = self[key]
        if value is None:
            return default
        return value

    def __getitem__(self, key):
        if key == parse_dayfirst_pref:
            return self.dayfirst
        if key == parse_yearfirst_pref:
            return self.yearfirst
        if key == datetime_format_pref:
            return self.datetime_format

        section, option = _prefs._parse_key(key)
        # this doesn't allow None values for preferences
        if (not self.config.has_section(section) or
                not self.config.has_option(section, option)):
            return None
        i = self.config.get(section, option)

        if i == '':
            return i

        try:
            i = literal_eval(i)
        except (ValueError, SyntaxError):
            pass

        return i

    def __delitem__(self, key):
        section, option = _prefs._parse_key(key)
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
        return [('%s.%s' % (section, name), value)
                for section in sorted(self.config.sections())
                for name, value in self.config.items(section)]

    def __setitem__(self, key, value):
        section, option = _prefs._parse_key(key)
        if not self.config.has_section(section):
            self.config.add_section(section)
        self.config.set(section, option, str(value))

    def __contains__(self, key):
        section, option = _prefs._parse_key(key)
        if self.config.has_section(section) and \
           self.config.has_option(section, option):
            return True
        return False

    def save(self, force=False):
        if testing and not force:
            return
        try:
            with open(self._filename, "w+") as f:
                self.config.write(f)
        except Exception:  # pylint: disable=broad-except
            msg = (_("Ghini can't save your user preferences. \n\nPlease "
                     "check the file permissions of your config file:\n %s")
                   % self._filename)
            if bauble.gui is not None and bauble.gui.window is not None:
                utils.message_dialog(msg, typ=Gtk.MessageType.ERROR,
                                     parent=bauble.gui.window)
            else:
                logger.error(msg)


class PrefsView(pluginmgr.View):
    """The PrefsView displays the values in the plugin registry and displays
    and allows limited editing of preferences, only after warning users of
    possible dangers.
    """

    def __init__(self):
        logger.debug('PrefsView::__init__')
        super().__init__(
            filename=os.path.join(paths.lib_dir(), 'bauble.glade'),
            root_widget_name='prefs_window')
        self.view.connect_signals(self)
        self.prefs_ls = self.view.widgets.prefs_prefs_ls
        self.plugins_ls = self.view.widgets.prefs_plugins_ls
        self.prefs_tv = self.view.widgets.prefs_prefs_tv
        # TODO should really be using Gio.SimpleAction/Gio.Action
        self.action = bauble.view.Action('prefs_insert', _('_Insert'),
                                         callback=self.add_new)
        self.button_press_id = None

    def on_button_press_event(self, widget, event):
        logger.debug('event.button %s', event.button)
        if event.button == 3:
            def on_activate(_item, callback):
                try:
                    model, tree_path = (self.prefs_tv
                                        .get_selection()
                                        .get_selected_rows())
                    logger.debug('model: %s tree_path: %s', model, tree_path)
                    if not model or not tree_path:
                        logger.debug('no model or tree_path')
                        return
                    callback(model, tree_path)
                except Exception as e:   # pylint: disable=broad-except
                    msg = utils.xml_safe(str(e))
                    logger.warning(msg)
            item = self.action.create_menu_item()
            item.connect('activate', on_activate, self.action.callback)
            menu = Gtk.Menu()
            menu.append(item)
            menu.attach_to_widget(widget)
            logger.debug('attaching menu to %s', widget)
            menu.popup(None, None, None, None, event.button, event.time)

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
        if dialog.run() == Gtk.ResponseType.OK:
            tree_iter = model.get_iter(tree_path)
            option = option_entry.get_text()
            new_iter = model.insert_after(
                tree_iter, row=[option, '', None])
            logger.debug('adding new pref option %s', option)
        dialog.destroy()
        return new_iter

    def on_prefs_edit_toggled(self, widget):
        state = widget.get_active()
        logger.debug('edit state %s', state)
        msg = _(
            '<b>CAUTION! this functionality is at BETA level and may change '
            'in future releases:</b>\n\n(NOTE: backup/restore buttons for '
            'your current state is provided - use them first.)\n\nSome '
            'changes will not take effect until restarted.\n\n<b>Making '
            'incorrect changes to your preferences could be detrimental.'
            '\n\nDO YOU WISH TO PROCEED?</b>'
        )
        if state and utils.yes_no_dialog(msg, parent=self.view.get_window()):
            logger.debug('enable editing prefs')
            self.view.widgets.prefs_data_renderer.set_property(
                'editable', state)
            self.button_press_id = self.prefs_tv.connect(
                "button-press-event", self.on_button_press_event)

        else:
            logger.debug('disable editing prefs')
            widget.set_active(False)
            self.view.widgets.prefs_data_renderer.set_property(
                'editable', False)
            if self.button_press_id:
                self.prefs_tv.disconnect(self.button_press_id)
                self.button_press_id = None

    def on_prefs_edited(self, _renderer, path, new_text):
        key, repr_str, type_str = self.prefs_ls[path]
        if new_text == '':
            msg = _('Delete the %s preference key?') % key
            if utils.yes_no_dialog(msg, parent=self.view.get_window()):
                del prefs[key]
                prefs.save()
                logger.debug('deleting: %s', key)
                self.prefs_ls.remove(self.prefs_ls.get_iter_from_string(
                    str(path)))
                return

        try:
            new_val = literal_eval(new_text)
        except (ValueError, SyntaxError):
            new_val = new_text

        if isinstance(new_val, str):
            if key.endswith('picture_root') and not Path(new_val).exists():
                new_val = ''

        new_val_type = type(new_val).__name__

        if type_str and (new_val == '' or new_val_type != type_str):
            self.prefs_ls[path][1] = repr_str
            return

        prefs[key] = new_val
        self.prefs_ls[path][1] = str(new_val)
        self.prefs_ls[path][2] = new_val_type
        prefs.save()

    @staticmethod
    def on_prefs_backup_clicked(_widget):
        from shutil import copy2
        copy2(default_prefs_file, default_prefs_file + 'BAK')

    def on_prefs_restore_clicked(self, _widget):
        from shutil import copy2
        # pylint: disable=using-constant-test
        if Path(default_prefs_file + 'BAK').exists():
            copy2(default_prefs_file + 'BAK', default_prefs_file)
            prefs.reload()
            self.update()
        else:
            utils.message_dialog(_('No backup found'))

    def update(self):
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
