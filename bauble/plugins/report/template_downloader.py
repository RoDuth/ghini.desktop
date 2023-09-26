# pylint: disable=too-few-public-methods
# Copyright (c) 2020-2022 Ross Demuth <rossdemuth123@gmail.com>
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

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

from gi.repository import Gtk  # noqa
from requests import exceptions

from bauble import pluginmgr  # , task
from bauble import prefs
from bauble.task import set_message
from bauble.utils import get_net_sess
from bauble.utils import yes_no_dialog

CONFIG_LIST_PREF = "report.configs"

TEMPLATES_DEFAULT_URL = (
    "https://github.com/RoDuth/ghini_report_templates" "/archive/master.zip"
)

TEMPLATES_URL_PREF = "template_downloader.url"
"""
Directory to store downloaded templates and their config etc..
"""

TEMPLATES_ROOT_PREF = "template_downloader.root_dir"
"""
Directory to store downloaded templates and their config etc..
"""


def set_templates_root_pref(path=None):
    """set the root directory to store templates"""
    if path is None:
        dlog = Gtk.FileChooserNative.new(
            _("Select a templates directory..."),
            None,
            Gtk.FileChooserAction.CREATE_FOLDER,
            None,
            None,
        )
        home_folder = str(Path.home())
        dlog.set_current_folder(home_folder)
        response = dlog.run()
        if response != Gtk.ResponseType.ACCEPT:
            return False
        path = Path(dlog.get_filename())
        dlog.destroy()

    if not path.exists():
        raise ValueError(_("directory does not exist.\n%s") % path)

    prefs.prefs[TEMPLATES_ROOT_PREF] = str(path)
    prefs.prefs.save()
    return True


def update_report_template_prefs(root, conf_file):
    # Add config to prefs and save it
    if Path(conf_file).exists():
        from configparser import ConfigParser

        from bauble.prefs import _prefs

        temp_prefs = _prefs(filename=conf_file)
        temp_prefs.config = ConfigParser(interpolation=None)
        temp_prefs.config.read(
            temp_prefs._filename
        )  # noqa # pylint: disable=protected-access
        default_formatters = temp_prefs.get(CONFIG_LIST_PREF, {})
        if default_formatters:
            formatters = prefs.prefs.get(CONFIG_LIST_PREF, {})
            for k, v in default_formatters.items():
                template_path = v[1].get("template")
                if template_path:
                    v[1]["template"] = str(Path(root, template_path))
                stylesheet_path = v[1].get("stylesheet")
                if stylesheet_path:
                    v[1]["stylesheet"] = str(Path(root, stylesheet_path))
                formatters[k] = v
            prefs.prefs[CONFIG_LIST_PREF] = formatters
            prefs.prefs.save()


def download_templates(root):
    # grab the templates zip file
    try:
        net_sess = get_net_sess()
        url = prefs.prefs.get(TEMPLATES_URL_PREF, TEMPLATES_DEFAULT_URL)
        result = net_sess.get(url, timeout=5)

    except exceptions.Timeout:
        msg = "connection timed out while getting templates"
        logger.info(msg)
        return None
    except exceptions.RequestException as e:
        logger.info("Requests error %s while getting templates", e)
        return None
    except Exception as e:  # pylint: disable=broad-except
        logger.warning(
            "unhandled %s(%s) getting templates", type(e).__name__, e
        )
        return None

    try:
        from io import BytesIO
        from zipfile import ZipFile

        with ZipFile(BytesIO(result.content)) as zipped:
            # the smallest directory is the root directory
            zip_root = min(  # pylint: disable=consider-using-generator
                [i for i in zipped.namelist() if i.endswith("/")], key=len
            )
            zip_root = Path(root, zip_root)
            if zip_root.exists():
                msg = _(
                    "Delete previous version?\n\n"  # noqa
                    "Yes keeps local version matching online exactly, "
                    "but...\n"
                    "WARNING: if you have added templates to this "
                    "directory selecting yes will delete them."
                )
                if yes_no_dialog(msg):
                    import shutil

                    shutil.rmtree(zip_root)
            zipped.extractall(root)
    except Exception as e:  # pylint: disable=broad-except
        logger.warning(
            "unhandled %s(%s) extracting templates", type(e).__name__, e
        )
        return None

    return zip_root


class TemplateDownloadTool(pluginmgr.Tool):
    category = _("Report")
    label = _("Update Templates")

    @classmethod
    def start(cls):
        # get the directory to save to first
        if TEMPLATES_ROOT_PREF not in prefs.prefs:
            if not set_templates_root_pref():
                return
        root = prefs.prefs.get(TEMPLATES_ROOT_PREF, None)

        if yes_no_dialog(
            _(
                "Download online report templates?\n\nSource: %s?"
                % prefs.prefs.get(TEMPLATES_URL_PREF, TEMPLATES_DEFAULT_URL)
            )
        ):
            dload_root = download_templates(root)
            msg = _("Templates update complete")
            # look for config files to update prefs with.
            if dload_root and dload_root.exists():
                for cfg in dload_root.glob("**/config.cfg"):
                    update_report_template_prefs(root, cfg)
                    # delete the config file...
                    cfg.unlink()
                # delete all the README files to avoid clutter
                for readme in dload_root.glob("**/README.md"):
                    readme.unlink()
            else:
                msg = _(
                    "there was an error downloading templates, try again "
                    "later"
                )
            set_message(msg)
