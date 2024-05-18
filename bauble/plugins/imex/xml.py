# Copyright (c) 2005,2006,2007,2008,2009 Brett Adams <brett@belizebotanic.org>
# Copyright (c) 2012-2015 Mario Frasca <mario@anche.no>
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
XML import/export plugin

Description: handle import and exporting from a simple XML format
"""

import logging
import os
import traceback
from pathlib import Path

logger = logging.getLogger(__name__)

from gi.repository import Gtk  # noqa

import bauble
from bauble import db
from bauble import pb_set_fraction
from bauble import pluginmgr
from bauble import task
from bauble import utils
from bauble.editor import GenericEditorPresenter
from bauble.editor import GenericEditorView
from bauble.i18n import _


def element_factory(parent, name, **kwargs):
    text = kwargs.pop("text", None)
    elm = etree.SubElement(parent, name, **kwargs)
    if text is not None:
        elm.text = str(text)
    return elm


class XMLImportDialogPresenter(GenericEditorPresenter):
    widget_to_field_map = {
        "one_file_chkbtn": "one_file",
        "filename_entry": "filename",
    }

    view_accept_buttons = ["exp_button_ok"]

    PROBLEM_INVALID_FILENAME = "invalid_filename"

    last_file = None

    def __init__(self, model, view):
        super().__init__(model=model, view=view, session=False)
        self.refresh_view()
        self.refresh_sensitivity()

    def on_btnbrowse_clicked(self, _button):
        utils.run_file_chooser_dialog(
            _("Select a folder"),
            None,
            Gtk.FileChooserAction.CREATE_FOLDER,
            str(Path.home()),
            self.view.widgets.filename_entry,
        )

    def on_filename_entry_changed(self, entry):
        self.remove_problem(self.PROBLEM_INVALID_FILENAME)
        val = self.on_non_empty_text_entry_changed(entry)
        path = Path(val)
        logger.debug("filename changed to %s", str(path))

        if not (path.exists() and path.is_dir()):
            self.add_problem(self.PROBLEM_INVALID_FILENAME, entry)

        self.refresh_sensitivity()

    def refresh_sensitivity(self):
        sensitive = False
        if self.is_dirty() and not self.has_problems():
            sensitive = True
        # accept buttons
        self.view.set_accept_buttons_sensitive(sensitive)


class XMLExporter:
    def __init__(self):
        self.filename = None
        self.one_file = True
        view = GenericEditorView(
            str(Path(__file__).resolve().parent / "xml.glade"),
            root_widget_name="xml_export_dialog",
        )
        self.presenter = XMLImportDialogPresenter(self, view)

    def start(self, path=None):
        if path:
            if not Path(path).exists():
                raise ValueError(
                    _("XML Export: path does not exist.\n%s") % path
                )
            self.filename = path.strip()
            self.run()
            return None
        response = self.presenter.start()
        if response == Gtk.ResponseType.OK:
            self.run()
            self.presenter.cleanup()
        logger.debug("responded %s", response)
        return response

    def run(self):
        """Queues the export task"""
        task.clear_messages()
        task.set_message("exporting XML")
        task.queue(self._export_task(self.filename, self.one_file))
        task.set_message("export completed")

    @staticmethod
    def _export_task(path, one_file=True):
        ntables = len(db.metadata.tables)
        steps_so_far = 0
        five_percent = int(ntables / 20) or 1
        if one_file:
            tableset_el = etree.Element("tableset")

        for table_name, table in db.metadata.tables.items():
            steps_so_far += 1
            if not one_file:
                tableset_el = etree.Element("tableset")
            logger.info("exporting %s…", table_name)
            table_el = element_factory(
                tableset_el, "table", attrib={"name": table_name}
            )
            results = table.select().execute().fetchall()
            columns = list(table.c.keys())
            try:
                for row in results:
                    row_el = element_factory(table_el, "row")
                    for col in columns:
                        element_factory(
                            row_el,
                            "column",
                            attrib={"name": col},
                            text=row[col],
                        )
            except ValueError as e:
                utils.message_details_dialog(
                    utils.xml_safe(e),
                    traceback.format_exc(),
                    Gtk.MessageType.ERROR,
                )
                return
            else:
                if not one_file:
                    tree = etree.ElementTree(tableset_el)
                    filename = os.path.join(path, f"{table_name}.xml")
                    logger.debug("writing xml to %s", filename)
                    tree.write(filename, encoding="utf8", xml_declaration=True)

            if ntables % five_percent == 0:
                pb_set_fraction(steps_so_far / ntables)
                yield

        if one_file:
            tree = etree.ElementTree(tableset_el)
            # use the database connection name for single file.
            file = "".join(
                c
                for c in str(bauble.conn_name)
                if c.isalnum() or c in ["_", "-"]
            )
            filename = os.path.join(path, f"{file}.xml")
            logger.debug("writing xml to %s", filename)
            tree.write(filename, encoding="utf8", xml_declaration=True)


class XMLExportCommandHandler(pluginmgr.CommandHandler):
    command = "exxml"

    def __call__(self, cmd, arg):
        logger.debug("XMLExportCommandHandler(%s)", arg)
        exporter = XMLExporter()
        logger.debug("starting")
        exporter.start(arg)
        logger.debug("started")


class XMLExportTool(pluginmgr.Tool):
    category = _("Export")
    label = _("XML")

    @classmethod
    def start(cls):
        exporter = XMLExporter()
        exporter.start()


class XMLImexPlugin(pluginmgr.Plugin):
    tools = [XMLExportTool]
    commands = [XMLExportCommandHandler]


try:
    from lxml import etree
except ImportError:
    utils.message_dialog(
        "The <i>lxml</i> package is required for the "
        "XML Import/Exporter plugin"
    )
