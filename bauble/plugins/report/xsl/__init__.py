# Copyright (c) 2005,2006,2007,2008,2009 Brett Adams <brett@belizebotanic.org>
# Copyright (c) 2012-2015 Mario Frasca <mario@anche.no>
# Copyright (c) 2018-2024 Ross Demuth <rossdemuth123@gmail.com>
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
The XSL report generator module.

This module takes a list of objects, gets all the species, accessions or plants
from these objects, converts them to the ABCD XML format, transforms the ABCD
data to an XSL formatting stylesheet and uses FOP to convert this stylesheet to
a document (PDF, PostScript, etc.).
"""
import logging
import os
import subprocess
import sys
from operator import attrgetter
from pathlib import Path

logger = logging.getLogger(__name__)

from gi.repository import Gtk
from lxml import etree

from bauble import paths
from bauble import prefs
from bauble import task
from bauble import utils
from bauble.error import BaubleError
from bauble.i18n import _
from bauble.plugins.abcd import ABCDCreator
from bauble.plugins.abcd import AccessionABCDAdapter
from bauble.plugins.abcd import PlantABCDAdapter
from bauble.plugins.abcd import SpeciesABCDAdapter

from .. import FormatterPlugin
from .. import SettingsBox
from .. import get_accessions_pertinent_to
from .. import get_plants_pertinent_to
from .. import get_species_pertinent_to

# TODO: need to make sure we can't select the OK button if we haven't selected
# a value for everything required.

PLANT_SOURCE_TYPE = _("Plant/Clone")
ACCESSION_SOURCE_TYPE = _("Accession")
SPECIES_SOURCE_TYPE = _("Species")
SOURCE_TYPES = (SPECIES_SOURCE_TYPE, ACCESSION_SOURCE_TYPE, PLANT_SOURCE_TYPE)
DEFAULT_SOURCE_TYPE = PLANT_SOURCE_TYPE
FORMATS = {
    "PDF": ("-pdf", "pdf"),
    "PostScript": ("-ps", "ps"),
    "RTF": ("-rtf", "rtf"),
    "PCL": ("-pcl", "pcl"),
    "AFP": ("-afp", "afp"),
    "TIFF": ("-tiff", "tiff"),
    "PNG": ("-png", "png"),
    "XSL-FO": ("-foout", "fo"),
    "SVG": ("-svg", "svg"),
}


class FOP:
    def __init__(self) -> None:
        self.java: str | None = None
        self.fop: str | None = None

    def set_fop_command(self) -> bool:
        """Set values for fop and java.

        :return: bool, True if both fop and java commands are found, used to
            determine if XSLFormatterPlugin is included when the
            ReportToolPlugin is loaded
        """
        self.java = None
        self.fop = None
        fop_cmd = "fop.bat" if sys.platform == "win32" else "fop"
        java_cmd = "java.exe" if sys.platform == "win32" else "java"
        logger.debug("commands fop: %s, jre: %s", fop_cmd, java_cmd)

        path = os.environ.get("PATH", "").split(os.pathsep)

        # prepend internal install paths
        path = [
            str(Path(paths.root_dir()) / "jre/bin"),
            str(Path(paths.root_dir()) / "fop/fop"),
        ] + path

        if (
            not prefs.testing
            and sys.platform == "darwin"
            and paths.main_is_frozen()
        ):
            # add homebrew and macports paths
            path.append("/usr/local/bin")
            path.append("/opt/local/bin")

        logger.debug("PATH = %s", path)

        self.fop = utils.which(fop_cmd, path=path)
        self.java = utils.which(java_cmd, path=path)

        logger.debug("fop: %s, jre: %s", self.fop, self.java)

        return bool(self.fop) and bool(self.java)


_fop = FOP()


def create_abcd_xml(path, source_type, include_private, authors, objs):
    """convert objects to ABCDAdapters depending on source type.

    :param path: Path object of file to save to.
    :param source_type: type to create: PLANT_SOURCE_TYPE, SPECIES_SOURCE_TYPE,
        ACCESSION_SOURCE_TYPE
    :param include_private: include private entries?
    :param authors: include authors?
    :param objs: SQLAlchemy objects to be converted
    """
    if source_type == PLANT_SOURCE_TYPE:
        get_pertinent = get_plants_pertinent_to
        msg = _(
            "There are no plants in the search results.  Please try "
            "another search."
        )
        private_path = "accession.private"
        Adapter = PlantABCDAdapter

    elif source_type == ACCESSION_SOURCE_TYPE:
        get_pertinent = get_accessions_pertinent_to
        msg = _(
            "There are no accessions in the search results.  Please try "
            "another search."
        )
        private_path = "private"
        Adapter = AccessionABCDAdapter

    elif source_type == SPECIES_SOURCE_TYPE:
        get_pertinent = get_species_pertinent_to
        msg = _(
            "There are no accessions in the search results.  Please try "
            "another search."
        )
        private_path = None
        Adapter = SpeciesABCDAdapter

    else:
        raise NotImplementedError("unknown source type")

    objs = get_pertinent(objs, as_task=True)

    def unit_generator():
        records_done = None
        for records_done, obj in enumerate(objs):
            if include_private or not private_path:
                yield Adapter(obj, for_reports=True)
            elif private_path and not attrgetter(private_path)(obj):
                yield Adapter(obj, for_reports=True)
        if records_done is None:
            raise BaubleError(msg)

    abcd = ABCDCreator(unit_generator(), authors=authors)
    task.queue(abcd.generate_elements())

    if len(abcd.units) == 0:
        # nothing adapted....possibly everything was private
        msg = _("No objects could be adapted to ABCD units.")
        if not include_private:
            msg += (
                " You chose not to include private entries.  All items "
                "maybe marked private?"
            )
        raise BaubleError(msg)

    abcd_data = abcd.get_element_tree()

    # use for debugging only (dumps to stdout):
    # etree.dump(abcd_data.getroot())

    with path.open("w", encoding="utf-8") as f:
        f.write(etree.tostring(abcd_data, encoding="unicode"))

    return str(path)


class XSLFormatterSettingsBox(SettingsBox):
    def __init__(self, *args):
        super().__init__(*args)
        filename = os.path.join(
            paths.lib_dir(), "plugins", "report", "xsl", "gui.glade"
        )
        self.widgets = utils.load_widgets(filename)

        for source in SOURCE_TYPES:
            self.widgets.source_type_combo.append_text(source)

        self.widgets.source_type_combo.set_active(2)

        for frmt in FORMATS:
            self.widgets.format_combo.append_text(frmt)

        self.widgets.format_combo.set_active(0)

        self.widgets.format_combo.set_tooltip_text(
            _(
                "Select an output format, NOTE: not all formats will work "
                "with every template. SVG is experimental."
            )
        )
        self.widgets.outfile_box.set_tooltip_text(
            _(
                "Select a file to save to. If not set report will be created "
                "in a temporary directory and opened in the default viewer, "
                "if set the directory containing the report will be opened."
            )
        )
        self.widgets.author_check.set_tooltip_text(
            _("Has no effect if your stylesheet does not support authors.")
        )
        self.widgets.private_check.set_tooltip_text(
            _(
                "Accession and plant source reports only, Does not affect "
                "species reports"
            )
        )
        self.widgets.outfile_btnbrowse.connect(
            "clicked", self.on_out_btnbrowse_clicked
        )
        self.widgets.outfile_entry.connect(
            "changed", self.on_out_entry_changed
        )
        self.widgets.format_combo.connect(
            "changed", self.on_format_combo_changed
        )
        self.widgets.file_entry.connect("changed", self.on_file_entry_changed)

        # keep a reference to settings box so it doesn't get destroyed in
        # remove_parent()
        self.settings_box = self.widgets.settings_box
        self.widgets.remove_parent(self.widgets.settings_box)
        self.pack_start(self.settings_box, True, True, 0)
        self.widgets.file_btnbrowse.connect(
            "clicked", self.on_btnbrowse_clicked
        )

    def on_btnbrowse_clicked(self, _widget):
        if previously := self.widgets.file_entry.get_text():
            last_folder = str(Path(previously).parent)
        else:
            last_folder = paths.templates_dir()
        utils.run_file_chooser_dialog(
            _("Select a stylesheet"),
            None,
            Gtk.FileChooserAction.OPEN,
            last_folder,
            self.widgets.file_entry,
        )

    def on_file_entry_changed(self, widget):
        text = widget.get_text()
        if Path(text).is_file():
            widget.get_style_context().remove_class("problem")
        else:
            widget.get_style_context().add_class("problem")

    def on_out_btnbrowse_clicked(self, _widget):
        if previously := self.widgets.outfile_entry.get_text():
            last_folder = str(Path(previously).parent)
        else:
            last_folder = str(Path.home())
        utils.run_file_chooser_dialog(
            _("Save to file"),
            None,
            Gtk.FileChooserAction.SAVE,
            last_folder,
            self.widgets.outfile_entry,
        )

    def on_out_entry_changed(self, entry):
        out_format = self.widgets.format_combo.get_active_text()
        _flag, file_ext = FORMATS.get(out_format or "PDF")
        filename = entry.get_text()
        if filename:
            filepath = Path(filename)
            if filepath.suffix != file_ext:
                filename = str(filepath.with_suffix(f".{file_ext}"))
                entry.set_text(filename)
                entry.set_position(len(filename))

    def on_format_combo_changed(self, _combo):
        self.on_out_entry_changed(self.widgets.outfile_entry)

    def get_report_settings(self):
        stylesheet = self.widgets.file_entry.get_text()
        if stylesheet:
            widgets = self.widgets
            return {
                "stylesheet": stylesheet,
                "source_type": widgets.source_type_combo.get_active_text(),
                "authors": widgets.author_check.get_active(),
                "private": widgets.private_check.get_active(),
                "out_format": widgets.format_combo.get_active_text(),
                "out_file": widgets.outfile_entry.get_text(),
            }
        return {}

    def update(self, settings):
        stylesheet = settings.get("stylesheet")
        source_type = authors = private = out_format = out_file = None

        if stylesheet and Path(stylesheet).exists():
            self.widgets.file_entry.set_text(stylesheet)
            self.widgets.file_entry.set_position(len(stylesheet))
            source_type = settings.get("source_type")
            authors = settings.get("authors")
            private = settings.get("private")
            out_format = settings.get("out_format")
            out_file = settings.get("out_file")
        else:
            self.widgets.file_entry.set_text("")

        if out_format and out_format != "PDF" or out_file:
            logger.debug("out_format: %s, out_file: %s", out_format, out_file)
            self.widgets.options_expander.set_expanded(True)
        else:
            self.widgets.options_expander.set_expanded(False)

        source_type = SOURCE_TYPES.index(source_type or DEFAULT_SOURCE_TYPE)
        self.widgets.source_type_combo.set_active(source_type)
        self.widgets.author_check.set_active(authors or False)
        self.widgets.private_check.set_active(private or False)
        out_format = list(FORMATS).index(out_format or "PDF")
        self.widgets.format_combo.set_active(out_format)
        self.widgets.outfile_entry.set_text(out_file or "")


_settings_box = XSLFormatterSettingsBox()


class XSLFormatterPlugin(FormatterPlugin):
    title = _("XSL")

    @classmethod
    def install(cls, import_defaults=True):
        logger.debug("installing xsl plugin")

    @classmethod
    def init(cls):
        """Copy default template files to appdata_dir or (if exists)
        templates_root.

        we do this in the initialization instead of installation because new
        version of plugin might provide new templates.
        """
        src_dir = Path(
            paths.lib_dir(), "plugins", "report", "xsl", "stylesheets"
        )
        templates_root = Path(paths.templates_dir(), "ghini_examples", "xsl")

        utils.copy_tree(
            src_dir, templates_root, (".xsl", ".png", ".svg", ".jpg")
        )

    @staticmethod
    def get_settings_box():
        return _settings_box

    @staticmethod
    def format(selfobjs, **kwargs):
        # kwargs is inherited
        stylesheet = kwargs.get("stylesheet")
        source_type = kwargs.get("source_type")
        if not stylesheet:
            msg = _("Please select a stylesheet.")
            utils.message_dialog(msg, Gtk.MessageType.WARNING)
            logger.debug(msg)
            return False

        logger.debug("fop command: %s", _fop.fop)
        if not _fop.fop:
            msg = _(
                "Could not find Apache FOP renderer.  Have you changed "
                "your preferences?  You may need to install FOP and java."
            )
            utils.message_dialog(msg, Gtk.MessageType.ERROR)
            logger.debug(msg)
            return False

        fop_flag, file_ext = FORMATS.get(kwargs.get("out_format"))

        xml_filename = create_abcd_xml(
            Path(stylesheet).parent / ".temp_data.xml",
            source_type,
            kwargs.get("private"),
            kwargs.get("authors"),
            selfobjs,
        )

        if not xml_filename:
            return False

        # suppress command prompt in windows
        creationflags = 0
        if sys.platform == "win32":
            creationflags = subprocess.CREATE_NO_WINDOW

        filename = kwargs.get("out_file") or str(
            utils.get_temp_path().with_suffix(f".{file_ext}")
        )

        env = os.environ.copy()
        env["JAVACMD"] = _fop.java

        logger.debug("JAVACMD: %s", _fop.java)

        # Don't use check so we can log output etc.  Errors will be picked up
        # by the lack of file
        # pylint: disable=subprocess-run-check
        fop_out = subprocess.run(
            [
                _fop.fop,
                "-xml",
                xml_filename,
                "-xsl",
                stylesheet,
                fop_flag,
                filename,
            ],
            capture_output=True,
            creationflags=creationflags,
            env=env,
        )

        os.remove(xml_filename)

        logger.debug("FOP return code: %s", fop_out.returncode)
        logger.debug("FOP stderr: %s", fop_out.stderr)
        logger.debug("FOP stdout: %s", fop_out.stdout)
        logger.debug(filename)

        if not Path(filename).exists():
            utils.message_dialog(
                _(
                    "Error creating the file. Please "
                    "ensure that your formatter is "
                    "properly installed."
                ),
                Gtk.MessageType.ERROR,
            )
            return False
        try:
            if kwargs.get("out_file"):
                utils.desktop.open(Path(filename).parent)
            else:
                utils.desktop.open(filename)
        except OSError:
            if kwargs.get("out_file"):
                msg = (
                    _(
                        "Could not open the report directory. You can open "
                        "the directory manually at %s"
                    )
                    % Path(filename).parent
                )
            else:
                msg = (
                    _(
                        "Could not open the report with the default program. "
                        "You can open the file manually at %s"
                    )
                    % filename
                )
            utils.message_dialog(msg)
            logger.debug(msg)

        return True


formatter_plugin = XSLFormatterPlugin
