# Copyright (c) 2005,2006,2007,2008,2009 Brett Adams <brett@belizebotanic.org>
# Copyright (c) 2012-2015 Mario Frasca <mario@anche.no>
# Copyright (c) 2018-2021 Ross Demuth <rossdemuth123@gmail.com>
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

This module takes a list of objects, get all the plants from the objects,
converts them to the ABCD XML format, transforms the ABCD data to an XSL
formatting stylesheet and uses FOP to convert the stylesheet to an a document.
"""
import sys
import os
import subprocess
import tempfile
from pathlib import Path
from operator import attrgetter

import logging
logger = logging.getLogger(__name__)

from gi.repository import Gtk

from bauble import paths
from bauble import prefs
from bauble.plugins.abcd import (create_abcd,
                                 SpeciesABCDAdapter,
                                 AccessionABCDAdapter,
                                 PlantABCDAdapter)
from bauble.plugins.report import (get_plants_pertinent_to,
                                   get_species_pertinent_to,
                                   get_accessions_pertinent_to,
                                   FormatterPlugin,
                                   SettingsBox)
from bauble.error import BaubleError
from bauble import utils

# TODO: need to make sure we can't select the OK button if we haven't selected
# a value for everything required.

PLANT_SOURCE_TYPE = _('Plant/Clone')
ACCESSION_SOURCE_TYPE = _('Accession')
SPECIES_SOURCE_TYPE = _('Species')
SOURCE_TYPES = (SPECIES_SOURCE_TYPE,
                ACCESSION_SOURCE_TYPE,
                PLANT_SOURCE_TYPE)
DEFAULT_SOURCE_TYPE = PLANT_SOURCE_TYPE
FORMATS = {'PDF': ('-pdf', 'pdf'),
           'PostScript': ('-ps', 'ps'),
           'RTF': ('-rtf', 'rtf'),
           'PCL': ('-pcl', 'pcl'),
           'AFP': ('-afp', 'afp'),
           'TIFF': ('-tiff', 'tiff'),
           'PNG': ('-png', 'png'),
           'XSL-FO': ('-foout', 'fo'),
           'SVG': ('-svg', 'svg')}

USE_EXTERNAL_FOP_PREF = 'report.xsl_external_fop'
"""
the preferences key for using the internal fop or not.
"""


class FOP:
    def __init__(self):
        self.java = None
        self.fop = None
        self.class_path = ''
        self.external_fop_pref = None

    def init(self):
        # if pref doesn't exist assume False
        self.external_fop_pref = prefs.prefs.get(USE_EXTERNAL_FOP_PREF, False)
        self.set_fop_command()
        if not self.external_fop_pref:
            self.set_fop_classpath()

    def update(self):
        """Check if the preference has changed and re-init if it has"""
        # if pref doesn't exist assume False
        external_fop = prefs.prefs.get(USE_EXTERNAL_FOP_PREF, False)
        if self.external_fop_pref != external_fop:
            self.init()

    def set_fop_classpath(self):
        if not self.fop:
            return
        fop_root = Path(self.fop).parent
        class_path = ''
        last_jars = ''
        for jar in fop_root.glob('**/*.jar'):
            if jar.parent.name == 'build':
                last_jars += str(jar) + os.pathsep
            class_path += str(jar) + os.pathsep
        class_path += str(last_jars)
        self.class_path = class_path.strip(os.pathsep)

    def set_fop_command(self):
        """Search for fop (and possibly java).

        If USE_EXTERNAL_FOP_PREF is True search PATH only.  Otherwise look for
        a version of fop (and jre) in the root path first.
        """
        self.java = None
        self.fop = None
        logger.debug('looking for fop')
        fop_cmd = 'fop.bat' if sys.platform == "win32" else 'fop'
        java_cmd = 'java.exe' if sys.platform == "win32" else 'java'
        logger.debug('commands fop: %s, jre: %s', fop_cmd, java_cmd)
        if not self.external_fop_pref:
            root = paths.root_dir()
            logging.debug('searching local dir: %s', str(root))
            included_fop = None
            for cmd in root.glob(f'fop*/fop/{fop_cmd}'):
                # should only be one or None
                included_fop = cmd
            if included_fop and included_fop.exists():
                logger.debug('found FOP : %s', included_fop)
                self.fop = str(included_fop)
                included_java = root / f'jre/bin/{java_cmd}'
                if included_java.exists():
                    logger.debug('found JRE : %s', included_java)
                    self.java = str(included_java)
                    return True
                return True

        # could use utils.which or shutil.which except the path is not always
        # as complete as it should be
        path = os.environ.get('PATH')

        if (not prefs.testing and sys.platform == 'darwin' and
                paths.main_is_frozen()):
            # add homebrew and macports paths to base Finder launched PATH.
            path += f'{os.pathsep}/usr/local/bin{os.pathsep}/opt/local/bin'

        logger.debug('PATH = %s', path)
        if not path:
            return True
        for pth in path.split(os.pathsep):
            candidate = Path(pth, fop_cmd)
            if candidate.is_file():
                logger.debug('found FOP on PATH %s', str(candidate))
                self.fop = str(candidate)
                self.external_fop_pref = True
                return True
        logger.debug('FOP not found')
        return False


_fop = FOP()


def create_abcd_xml(directory, source_type, include_private, authors, objs):
    """convert objects to ABCDAdapters depending on source type for passing to
    create_abcd.

    :param directory: directory to save to
    :param source_type: type to create: PLANT_SOURCE_TYPE, SPECIES_SOURCE_TYPE,
        ACCESSION_SOURCE_TYPE
    :param include_private: include private entries?
    :param authors: include authors?
    :param objs: SQLAlchemy objects to be converted
    """
    adapted = []
    if source_type == PLANT_SOURCE_TYPE:
        get_pertinent = get_plants_pertinent_to
        msg = _('There are no plants in the search results.  Please try '
                'another search.')
        private_path = 'accession.private'
        Adapter = PlantABCDAdapter

    elif source_type == ACCESSION_SOURCE_TYPE:
        get_pertinent = get_accessions_pertinent_to
        msg = _('There are no accessions in the search results.  Please try '
                'another search.')
        private_path = 'private'
        Adapter = AccessionABCDAdapter

    elif source_type == SPECIES_SOURCE_TYPE:
        get_pertinent = get_species_pertinent_to
        msg = _('There are no accessions in the search results.  Please try '
                'another search.')
        private_path = None
        Adapter = SpeciesABCDAdapter

    else:
        raise NotImplementedError('unknown source type')

    objs = sorted(get_pertinent(objs), key=utils.natsort_key)

    if len(objs) == 0:
        utils.message_dialog(msg)
        return False

    for obj in objs:
        if include_private or not private_path:
            adapted.append(Adapter(obj, for_labels=True))
        elif private_path and not attrgetter(private_path)(obj):
            adapted.append(Adapter(obj, for_labels=True))

    if len(adapted) == 0:
        # nothing adapted....possibly everything was private
        msg = _('No objects could be adapted to ABCD units.')
        if not include_private:
            msg += (' You chose not to include private entries.  All items '
                    'maybe marked private?')
        raise BaubleError(msg)
    abcd_data = create_abcd(adapted, authors=authors, validate=False)

    # use for debugging only (dumps to stdout):
    # etree.dump(abcd_data.getroot())

    handle, xml_filename = tempfile.mkstemp(suffix='.xml', dir=directory)
    with open(xml_filename, 'w', encoding='utf-8') as f:
        f.write(etree.tostring(abcd_data, encoding='unicode'))

    # Close the handle here so can delete the file later (win32 at least)
    os.close(handle)

    return xml_filename


class XSLFormatterSettingsBox(SettingsBox):

    def __init__(self, *args):
        super().__init__(*args)
        filename = os.path.join(paths.lib_dir(), "plugins", "report", 'xsl',
                                'gui.glade')
        self.widgets = utils.load_widgets(filename)

        for source in SOURCE_TYPES:
            self.widgets.source_type_combo.append_text(source)

        self.widgets.source_type_combo.set_active(2)

        for frmt in FORMATS:
            self.widgets.format_combo.append_text(frmt)

        self.widgets.format_combo.set_active(0)

        self.widgets.format_combo.set_tooltip_text(
            _('Select an output format, NOTE: not all formats will work with '
              'every template. SVG is experimental.')
        )
        self.widgets.outfile_box.set_tooltip_text(
            _('Select a file to save to. If not set report will be created '
              'in a temporary directory and opened in the default viewer, if '
              'set the directory containing the report will be opened.')
        )
        self.widgets.private_check.set_tooltip_text(
            _('Accession and plant source reports only, Does not affect '
              'species reports')
        )
        self.widgets.outfile_btnbrowse.connect('clicked',
                                               self.on_out_btnbrowse_clicked)
        self.widgets.outfile_entry.connect('changed',
                                           self.on_out_entry_changed)
        self.widgets.format_combo.connect('changed',
                                          self.on_format_combo_changed)

        # keep a refefence to settings box so it doesn't get destroyed in
        # remove_parent()
        self.settings_box = self.widgets.settings_box
        self.widgets.remove_parent(self.widgets.settings_box)
        self.pack_start(self.settings_box, True, True, 0)
        self.widgets.file_btnbrowse.connect('clicked',
                                            self.on_btnbrowse_clicked)

    def on_btnbrowse_clicked(self, _widget):
        if previously := self.widgets.file_entry.get_text():
            last_folder = str(Path(previously).parent)
        else:
            last_folder = paths.templates_dir()
        utils.run_file_chooser_dialog(_('Select a stylesheet'),
                                      None,
                                      Gtk.FileChooserAction.OPEN,
                                      last_folder,
                                      self.widgets.file_entry)

    def on_out_btnbrowse_clicked(self, _widget):
        if previously := self.widgets.outfile_entry.get_text():
            last_folder = str(Path(previously).parent)
        else:
            last_folder = str(Path.home())
        utils.run_file_chooser_dialog(_('Save to file'),
                                      None,
                                      Gtk.FileChooserAction.SAVE,
                                      last_folder,
                                      self.widgets.outfile_entry)

    def on_out_entry_changed(self, entry):
        out_format = self.widgets.format_combo.get_active_text()
        _flag, file_ext = FORMATS.get(out_format or 'PDF')
        filename = entry.get_text()
        if filename:
            filepath = Path(filename)
            if filepath.suffix != file_ext:
                filename = str(filepath.with_suffix(f'.{file_ext}'))
                entry.set_text(filename)
                entry.set_position(len(filename))

    def on_format_combo_changed(self, _combo):
        self.on_out_entry_changed(self.widgets.outfile_entry)

    def get_report_settings(self):
        return {
            'stylesheet': self.widgets.file_entry.get_text(),
            'source_type': self.widgets.source_type_combo.get_active_text(),
            'authors': self.widgets.author_check.get_active(),
            'private': self.widgets.private_check.get_active(),
            'out_format': self.widgets.format_combo.get_active_text(),
            'out_file': self.widgets.outfile_entry.get_text()
        }

    def update(self, settings):
        stylesheet = settings.get('stylesheet')
        source_type = authors = private = out_format = out_file = None

        if stylesheet and Path(stylesheet).exists():
            self.widgets.file_entry.set_text(stylesheet)
            self.widgets.file_entry.set_position(len(stylesheet))
            source_type = settings.get('source_type')
            authors = settings.get('authors')
            private = settings.get('private')
            out_format = settings.get('out_format')
            out_file = settings.get('out_file')
        else:
            self.widgets.file_entry.set_text('')

        if out_format and out_format != 'PDF' or out_file:
            logger.debug('out_format: %s, out_file: %s', out_format, out_file)
            self.widgets.options_expander.set_expanded(True)
        else:
            self.widgets.options_expander.set_expanded(False)

        source_type = SOURCE_TYPES.index(source_type or DEFAULT_SOURCE_TYPE)
        self.widgets.source_type_combo.set_active(source_type)
        self.widgets.author_check.set_active(authors or False)
        self.widgets.private_check.set_active(private or False)
        out_format = list(FORMATS).index(out_format or 'PDF')
        self.widgets.format_combo.set_active(out_format)
        self.widgets.outfile_entry.set_text(out_file or '')


_settings_box = XSLFormatterSettingsBox()


class XSLFormatterPlugin(FormatterPlugin):

    title = _('XSL')

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
        src_dir = Path(paths.lib_dir(), "plugins", "report", 'xsl',
                       'stylesheets')
        templates_root = Path(paths.templates_dir(), "ghini_examples", "xsl")

        utils.copy_tree(src_dir, templates_root,
                        ('.xsl', '.png', '.svg', '.jpg'))

    @staticmethod
    def get_settings_box():
        return _settings_box

    @staticmethod
    def format(selfobjs, **kwargs):
        # kwargs is inherited
        stylesheet = kwargs.get('stylesheet')
        source_type = kwargs.get('source_type')
        if not stylesheet:
            msg = _('Please select a stylesheet.')
            utils.message_dialog(msg, Gtk.MessageType.WARNING)
            logger.debug(msg)
            return False

        _fop.update()

        logger.debug('fop command: %s', _fop.fop)
        if not _fop.fop:
            msg = _('Could not find Apache FOP renderer.  Have you changed '
                    'your preferences?  You may need to install FOP and java.')
            utils.message_dialog(msg, Gtk.MessageType.ERROR)
            logger.debug(msg)
            return False

        fop_flag, file_ext = FORMATS.get(kwargs.get('out_format'))

        xml_filename = create_abcd_xml(str(Path(stylesheet).parent),
                                       source_type,
                                       kwargs.get('private'),
                                       kwargs.get('authors'),
                                       selfobjs)

        if not xml_filename:
            return False

        # suppress command prompt in windows
        creationflags = 0
        if sys.platform == 'win32':
            creationflags = subprocess.CREATE_NO_WINDOW

        if _fop.external_fop_pref:
            fop_cmd = [_fop.fop]
        else:
            fop_cmd = [_fop.java,
                       '-classpath',
                       f'"{_fop.class_path}"',
                       'org.apache.fop.cli.Main']
        logger.debug('fop_cmd: %s', fop_cmd)

        # Don't use check so we can log output etc.  Errors will be picked up
        # by the lack of file
        # pylint: disable=subprocess-run-check
        temp = str(Path(tempfile.mkstemp()[1]).with_suffix(f'.{file_ext}'))
        filename = kwargs.get('out_file') or temp
        fop_out = subprocess.run(
            [*fop_cmd, '-xml', xml_filename, '-xsl', stylesheet, fop_flag,
             filename],
            capture_output=True,
            creationflags=creationflags,
        )

        logger.debug('FOP return code: %s', fop_out.returncode)
        logger.debug('FOP stderr: %s', fop_out.stderr)
        logger.debug('FOP stdout: %s', fop_out.stdout)
        logger.debug(filename)

        os.remove(xml_filename)

        if not Path(filename).exists():
            utils.message_dialog(_('Error creating the file. Please '
                                   'ensure that your formatter is '
                                   'properly installed.'),
                                 Gtk.MessageType.ERROR)
            return False
        try:
            if kwargs.get('out_file'):
                utils.desktop.open(Path(filename).parent)
            else:
                utils.desktop.open(filename)
        except OSError:
            if kwargs.get('out_file'):
                msg = _('Could not open the report directory. You can open '
                        'the directory manually at %s') % Path(filename).parent
            else:
                msg = _('Could not open the report with the default program. '
                        'You can open the file manually at %s') % filename
            utils.message_dialog(msg)
            logger.debug(msg)

        return True


# expose the formatter
try:
    from lxml import etree
except ImportError:
    utils.message_dialog('The <i>lxml</i> package is required for the '
                         'XSL report plugin')
else:
    # Is this still used?
    formatter_plugin = XSLFormatterPlugin
