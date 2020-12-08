# pylint: disable=too-few-public-methods
# Copyright (c) 2020 Ross Demuth <rossdemuth123@gmail.com>
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
A basic system to keep sync with an online repository of templates.
Avoids the need to update the software to update the templates.
Will not update the online repository with any local changes, will simply
overwrite them.  You need to update (or store templates) seperately.
Intended for users who will never "look under the hood" of a report template
and just want a bunch of reliable templates to use.
"""

import os

import logging
import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa

from requests import exceptions
from bauble.utils import get_net_sess, yes_no_dialog
from bauble import pluginmgr  # , task
from bauble.prefs import prefs, templates_root_pref
from bauble.task import set_message

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

CONFIG_LIST_PREF = 'report.configs'
TEMPLATES_URI = ('https://github.com/RoDuth/ghini_report_templates/archive'
                 '/master.zip')


def set_template_save_to_dir(path=None):
    """set the root directory to store templates"""
    if path is None:
        dlog = Gtk.FileChooserNative.new('Select a templates directory...',
                                         None,
                                         Gtk.FileChooserAction.SELECT_FOLDER,
                                         None, None)
        response = dlog.run()
        path = dlog.get_filename()
        dlog.destroy()
        if response != Gtk.ResponseType.ACCEPT:
            return

    if not os.path.exists(path):
        raise ValueError(_("local path does not exist.\n%s") % path)

    prefs[templates_root_pref] = path
    prefs.save()


def update_report_template_prefs(root):
    # Add config to prefs and save it
    conf_file = os.path.join(root,
                             'ghini_report_templates-master/config.cfg')
    if os.path.exists(conf_file):
        from bauble.prefs import _prefs
        from configparser import RawConfigParser
        temp_prefs = _prefs(filename=conf_file)
        temp_prefs.config = RawConfigParser()
        temp_prefs.config.read(temp_prefs._filename) \
            # noqa # pylint: disable=protected-access
        default_formatters = temp_prefs.get(CONFIG_LIST_PREF, None)
        if default_formatters:
            formatters = prefs.get(CONFIG_LIST_PREF, {})
            for k, v in default_formatters.items():
                template_path = v[1].get('template')
                if template_path:
                    v[1]['template'] = os.path.join(root, template_path)
                stylesheet_path = v[1].get('stylesheet')
                if stylesheet_path:
                    v[1]['stylesheet'] = os.path.join(root,
                                                      stylesheet_path)
                formatters[k] = v
            prefs[CONFIG_LIST_PREF] = formatters
            prefs.save()


def download_templates(root):
    # grab the templates zip file
    try:
        net_sess = get_net_sess()
        result = net_sess.get(TEMPLATES_URI, timeout=5)

    except exceptions.Timeout:
        msg = 'connection timed out while getting templates'
        logger.info(msg)
        return
    except exceptions.RequestException as e:
        logger.info('Requests error %s while getting templates', e)
        return
    except Exception as e:   # pylint: disable=broad-except
        logger.warning('unhandled %s(%s) getting templates',
                       type(e).__name__, e)
        return

    # unzip them
    try:
        from zipfile import ZipFile
        from io import BytesIO
        with ZipFile(BytesIO(result.content)) as zipped:
            # the smallest directory is the root directory
            zip_root = min(
                [i for i in zipped.namelist() if i.endswith('/')],
                key=len
            )
            zip_root = os.path.join(root, zip_root)
            if os.path.exists(zip_root):
                msg = _('Delete previous version?\n\n'  # noqa
                        'Yes keeps local version matching online exactly, '
                        'but...\n'
                        'WARNING: if you have added templates to this '
                        'directory selecting yes will delete them.')
                if yes_no_dialog(msg):
                    import shutil
                    shutil.rmtree(zip_root)
            zipped.extractall(root)
    except Exception as e:   # pylint: disable=broad-except
        logger.warning('unhandled %s(%s) extracting templates',
                       type(e).__name__, e)
        return


class TemplateDownloadTool(pluginmgr.Tool):

    category = _("Report")
    label = _("Update Templates")

    @classmethod
    def start(cls):
        # make sure we have the directory to save to first
        if templates_root_pref not in prefs:
            set_template_save_to_dir()
        root = prefs.get(templates_root_pref, None)

        msg = 'Download online reports?\n\nSource: {}?'.format(TEMPLATES_URI)
        if yes_no_dialog(msg):
            download_templates(root)
            update_report_template_prefs(root)
            set_message(_('Templates update complete'))
