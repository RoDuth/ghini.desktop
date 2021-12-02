# Copyright (c) 2005,2006,2007,2008,2009 Brett Adams <brett@belizebotanic.org>
# Copyright (c) 2012-2015 Mario Frasca <mario@anche.no>
# Copyright (c) 2018-2020 Ross Demuth <rossdemuth123@gmail.com>
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
The PDF report generator module.

This module takes a list of objects, get all the plants from the
objects, converts them to the ABCD XML format, transforms the ABCD
data to an XSL formatting stylesheet and uses a XSL-PDF renderer to
convert the stylesheet to PDF.
"""
import shutil
import sys
import os
import subprocess
import tempfile

import logging
logger = logging.getLogger(__name__)

from gi.repository import Gtk

from sqlalchemy.orm import object_session

from bauble import db
from bauble import paths
from bauble.plugins.abcd import create_abcd, ABCDAdapter, ABCDElement
from bauble.plugins.report import (get_plants_pertinent_to,
                                   get_species_pertinent_to,
                                   get_accessions_pertinent_to,
                                   FormatterPlugin,
                                   SettingsBox)
from bauble import prefs
from bauble import utils
from bauble.utils import desktop



# TODO: need to make sure we can't select the OK button if we haven't selected
# a value for everything

plant_source_type = _('Plant/Clone')
accession_source_type = _('Accession')
species_source_type = _('Species')
default_source_type = plant_source_type


def get_fop():
    fop_cmd = 'fop.bat' if sys.platform == "win32" else 'fop'
    path = os.environ['PATH']
    if not path:
        return None
    for pth in path.split(os.pathsep):
        try:
            # handle exceptions in case the path doesn't exist
            if fop_cmd in os.listdir(pth):
                return os.path.join(pth, fop_cmd)
        except FileNotFoundError as e:
            logger.debug('path search: %s(%s)', type(e).__name__, e)
    return None


class SpeciesABCDAdapter(ABCDAdapter):
    """
    An adapter to convert a Species to an ABCD Unit, the SpeciesABCDAdapter
    does not create a valid ABCDUnit since we can't provide the required UnitID
    """
    def __init__(self, species, for_labels=False):
        super().__init__(species)

        # hold on to the accession so it doesn't get cleaned up and closed
        self.session = object_session(species)
        self.for_labels = for_labels
        self.species = species
        self._date_format = prefs.prefs[prefs.date_format_pref]

    def get_UnitID(self):
        # **** Returning the empty string for the UnitID makes the
        # ABCD data NOT valid ABCD but it does make it work for
        # creating reports without including the accession or plant
        # code
        return utils.xml_safe(self.species.id)

    def get_DateLastEdited(self):
        return utils.xml_safe(self.species._last_updated.isoformat())

    def get_family(self):
        return utils.xml_safe(self.species.genus.family)

    def get_FullScientificNameString(self, authors=True):
        sp_str = self.species.str(authors=authors, markup=False)
        return utils.xml_safe(sp_str)

    def get_GenusOrMonomial(self):
        return utils.xml_safe(str(self.species.genus))

    def get_FirstEpithet(self):
        species = self.species.sp
        if species is None:
            return None
        return utils.xml_safe(str(species))

    def get_AuthorTeam(self):
        author = self.species.sp_author
        if author is None:
            return None
        return utils.xml_safe(author)

    def get_InfraspecificAuthor(self):
        return utils.xml_safe(str(self.species.infraspecific_author))

    def get_InfraspecificRank(self):
        return utils.xml_safe(str(self.species.infraspecific_rank))

    def get_InfraspecificEpithet(self):
        infrasp = ''
        infrasp1 = self.species.infrasp1
        cultivar = self.species.cultivar_epithet
        rank = self.species.infraspecific_rank
        # if not a cultivar or normal infrspecific part return the unranked
        # part.  A better solution would be to have a seperate field for
        # additional (informal, descriptive...) parts
        if all(part in (None, '') for part in (cultivar, rank)) and infrasp1:
            infrasp = infrasp1
        else:
            infrasp = self.species.infraspecific_epithet

        return utils.xml_safe(str(infrasp))

    def get_CultivarName(self):
        cultivar = self.species.cultivar_epithet
        if cultivar is None:
            return 'cv.'
        if cultivar:
            return utils.xml_safe("'%s'" % cultivar)
        return ''

    def get_HybridFlag(self):
        if self.species.hybrid is True:
            return utils.xml_safe(str(self.species.hybrid_char))
        return None

    def get_InformalNameString(self):
        vernacular_name = self.species.default_vernacular_name
        if vernacular_name is None:
            return None
        return utils.xml_safe(vernacular_name)

    @staticmethod
    def notes_in_list(notes, unit, for_labels):
        if not notes:
            return None
        notes_list = []
        for note in notes:
            date = utils.xml_safe(note.date.isoformat())
            user = utils.xml_safe(note.user) if note.user else ''
            # category being a tag name we prefer 'None' or '_' over ''
            category = utils.xml_safe(note.category)
            category_name = utils.xml_safe_name(note.category)
            text = note.note
            notes_list.append(dict(date=date,
                                   user=user,
                                   category=category,
                                   category_name=category_name,
                                   text=text))

        # not abcd so not in the namespace and only create when making labels
        if for_labels:
            note_unit = etree.SubElement(unit, 'Notes')
            for note in notes_list:
                etree.SubElement(
                    note_unit,
                    note['category_name'],
                    attrib={'User': note['user'],
                            'Date': note['date']}
                ).text = note['text']

        return notes_list

    def get_Notes(self, unit):
        return self.notes_in_list(self.species.notes, unit, self.for_labels)

    def extra_elements(self, unit):
        # distribution isn't in the ABCD namespace so it should create an
        # invalid XML file
        if self.for_labels:
            if self.species.label_distribution:
                etree.SubElement(unit, 'distribution').text = \
                    self.species.label_distribution
            elif self.species.distribution:
                etree.SubElement(unit, 'distribution').text = \
                    self.species.distribution_str()


class AccessionABCDAdapter(SpeciesABCDAdapter):
    """An adapter to convert a Plant to an ABCD Unit"""
    def __init__(self, accession, for_labels=False):
        super().__init__(accession.species, for_labels)
        self.accession = accession

    def get_UnitID(self):
        return utils.xml_safe(str(self.accession))

    def get_FullScientificNameString(self, authors=True):
        sp_str = self.accession.species_str(authors=authors, markup=False)
        return utils.xml_safe(sp_str)

    def get_IdentificationQualifier(self):
        idqual = self.accession.id_qual
        if idqual is None:
            return None
        if idqual in ('forsan', 'near', 'incorrect'):
            idqual = '(%s)' % idqual
        return utils.xml_safe(idqual)

    def get_IdentificationQualifierRank(self):
        idqrank = self.accession.id_qual_rank
        if idqrank is None:
            return None
        return utils.xml_safe(idqrank)

    def get_DateLastEdited(self):
        return utils.xml_safe(self.accession._last_updated.isoformat())

    def get_Notes(self, unit):
        return self.notes_in_list(self.accession.notes, unit, self.for_labels)

    def extra_elements(self, unit):
        super().extra_elements(unit)

        if self.accession.source and self.accession.source.collection:
            collection = self.accession.source.collection
            gathering = ABCDElement(unit, 'Gathering')

            if collection.collectors_code:
                ABCDElement(gathering, 'Code',
                            text=utils.xml_safe(collection.collectors_code))

            # TODO: get date pref for DayNumberBegin
            if collection.date:
                date_time = ABCDElement(gathering, 'DateTime')
                ABCDElement(date_time, 'DateText',
                            utils.xml_safe(collection.date.isoformat()))

            if collection.collector:
                agents = ABCDElement(gathering, 'Agents')
                agent = ABCDElement(agents, 'GatheringAgent')
                ABCDElement(agent, 'AgentText',
                            text=utils.xml_safe(collection.collector))

            if collection.locale:
                ABCDElement(gathering, 'LocalityText',
                            text=utils.xml_safe(collection.locale))

            if collection.region:
                named_areas = ABCDElement(gathering, 'NamedAreas')
                named_area = ABCDElement(named_areas, 'NamedArea')
                ABCDElement(named_area, 'AreaName',
                            text=utils.xml_safe(collection.region))

            if collection.habitat:
                ABCDElement(gathering, 'AreaDetail',
                            text=utils.xml_safe(collection.habitat))

            if collection.longitude or collection.latitude:
                site_coords = ABCDElement(gathering, 'SiteCoordinateSets')
                coord = ABCDElement(site_coords, 'SiteCoordinates')
                lat_long = ABCDElement(coord, 'CoordinatesLatLong')
                ABCDElement(lat_long, 'LongitudeDecimal',
                            text=utils.xml_safe(collection.longitude))
                ABCDElement(lat_long, 'LatitudeDecimal',
                            text=utils.xml_safe(collection.latitude))
                if collection.gps_datum:
                    ABCDElement(lat_long, 'SpatialDatum',
                                text=utils.xml_safe(collection.gps_datum))
                if collection.geo_accy:
                    ABCDElement(coord, 'CoordinateErrorDistanceInMeters',
                                text=utils.xml_safe(collection.geo_accy))

            if collection.elevation:
                altitude = ABCDElement(gathering, 'Altitude')
                if collection.elevation_accy:
                    text = '%sm (+/- %sm)' % (collection.elevation,
                                              collection.elevation_accy)
                else:
                    text = '%sm' % collection.elevation
                ABCDElement(altitude, 'MeasurementOrFactText', text=text)

            if collection.notes:
                ABCDElement(gathering, 'Notes',
                            utils.xml_safe(collection.notes))


class PlantABCDAdapter(AccessionABCDAdapter):
    """
    An adapter to convert a Plant to an ABCD Unit
    """
    def __init__(self, plant, for_labels=False):
        super().__init__(plant.accession, for_labels)
        self.plant = plant

    def get_UnitID(self):
        return utils.xml_safe(str(self.plant))

    def get_DateLastEdited(self):
        return utils.xml_safe(self.plant._last_updated.isoformat())

    def get_Notes(self, unit):
        return self.notes_in_list(self.plant.notes, unit, self.for_labels)

    def extra_elements(self, unit):
        bg_unit = ABCDElement(unit, 'BotanicalGardenUnit')
        ABCDElement(bg_unit, 'AccessionSpecimenNumbers',
                    text=utils.xml_safe(self.plant.quantity))
        ABCDElement(bg_unit, 'LocationInGarden',
                    text=utils.xml_safe(str(self.plant.location)))
        # TODO: AccessionStatus, AccessionMaterialtype,
        # ProvenanceCategory, AccessionLineage, DonorCategory,
        # PlantingDate, Propagation
        super().extra_elements(unit)


class XSLFormatterSettingsBox(SettingsBox):

    def __init__(self, *args):
        super().__init__(*args)
        filename = os.path.join(paths.lib_dir(), "plugins", "report", 'xsl',
                                'gui.glade')
        self.widgets = utils.load_widgets(filename)

        combo = self.widgets.source_type_combo
        values = [_('Accession'), _('Plant/Clone'), _('Species')]
        utils.setup_text_combobox(combo, values=values)

        # keep a refefence to settings box so it doesn't get destroyed in
        # remove_parent()
        self.settings_box = self.widgets.settings_box
        self.widgets.remove_parent(self.widgets.settings_box)
        self.pack_start(self.settings_box, True, True, 0)
        self.widgets.file_btnbrowse.connect('clicked',
                                            self.on_btnbrowse_clicked)

    def on_btnbrowse_clicked(self, _widget):
        from pathlib import Path
        previously = self.widgets.file_entry.get_text()
        if previously:
            last_folder = str(Path(previously).parent)
        else:
            examples_root = os.path.join(paths.appdata_dir(), 'templates',
                                         'xsl')
            last_folder = prefs.prefs.get(prefs.templates_root_pref,
                                          examples_root)
        chooser = Gtk.FileChooserNative.new(_("Choose a file…"),
                                            None,
                                            Gtk.FileChooserAction.OPEN)

        try:
            if last_folder:
                chooser.set_current_folder(last_folder)
            if chooser.run() == Gtk.ResponseType.ACCEPT:
                filename = chooser.get_filename()
                if filename:
                    self.widgets.file_entry.set_text(filename)
                    self.widgets.file_entry.set_position(len(filename))
        except Exception as e:
            logger.warning("%s : %s", type(e).__name__, e)
        chooser.destroy()

    def get_settings(self):
        """return a dict of settings from the settings box gui."""
        stylesheet = self.widgets.file_entry.get_text()
        additional = os.path.splitext(stylesheet)[0]
        try:
            os.listdir(additional)
        except OSError:
            additional = False

        source_iter = self.widgets.source_type_combo.get_active_iter()
        source_model = self.widgets.source_type_combo.get_model()
        source_entry = source_model[source_iter][0]

        return {
            'stylesheet': stylesheet,
            'additional': additional,
            'source_type': source_entry,
            'authors': self.widgets.author_check.get_active(),
            'private': self.widgets.private_check.get_active()
        }

    def update(self, settings):
        stylesheet = settings.get('stylesheet')
        source_type = authors = private = None

        if stylesheet:
            self.widgets.file_entry.set_text(stylesheet)
            self.widgets.file_entry.set_position(len(stylesheet))
            source_type = settings.get('source_type')
            authors = settings.get('authprs')
            private = settings.get('private')
        else:
            self.widgets.file_entry.set_text('')

        if source_type:
            utils.combo_set_active_text(self.widgets.source_type_combo,
                                        source_type)
        else:
            utils.combo_set_active_text(self.widgets.source_type_combo,
                                        default_source_type)

        if authors:
            self.widgets.author_check.set_active(authors)
        else:
            self.widgets.author_check.set_active(False)

        if private:
            self.widgets.private_check.set_active(private)
        else:
            self.widgets.private_check.set_active(False)


_settings_box = XSLFormatterSettingsBox()


class XSLFormatterPlugin(FormatterPlugin):

    title = _('XSL')

    @classmethod
    def install(cls, import_defaults=True):
        "create templates dir on plugin installation"
        logger.debug("installing xsl plugin")
        container_dir = os.path.join(paths.appdata_dir(), "templates")
        if not os.path.exists(container_dir):
            os.mkdir(container_dir)
        cls.plugin_dir = os.path.join(paths.appdata_dir(), "templates", "xsl")
        if not os.path.exists(cls.plugin_dir):
            os.mkdir(cls.plugin_dir)

    @classmethod
    def init(cls):
        """copy default template files to appdata_dir

        we do this in the initialization instead of installation
        because new version of plugin might provide new templates.

        """
        cls.install()  # plugins still not versioned...

        src_dir = os.path.join(paths.lib_dir(), "plugins", "report", 'xsl',
                               'stylesheets')
        stylesheets = []
        for root, _, filenames in os.walk(src_dir):
            for fname in filenames:
                dest = os.path.split(root.replace(src_dir, ''))[1]
                if fname.endswith(('xsl', 'png', 'svg', 'jpg')):
                    stylesheets.append((dest, fname))

        # If user has selected a directory to store templates add the examples
        # to it otherwise use appdata
        templates_root = prefs.prefs.get(prefs.templates_root_pref, None)
        if templates_root:
            templates_root = os.path.join(templates_root, "ghini_examples",
                                          "xsl")
            if not os.path.exists(templates_root):
                os.makedirs(templates_root)
        else:
            templates_root = cls.plugin_dir

        for dest, stylesheet in stylesheets:
            src = os.path.join(src_dir, dest, stylesheet)
            dst_dir = os.path.join(templates_root, dest)
            dst = os.path.join(dst_dir, stylesheet)
            if not os.path.exists(dst_dir):
                os.mkdir(dst_dir)
            if not os.path.exists(dst) and os.path.exists(src):
                shutil.copy(src, dst)

    @staticmethod
    def get_settings_box():
        return _settings_box

    @staticmethod
    def format(objs, **kwargs):
        # kwargs is inherited
        stylesheet = kwargs.get('stylesheet')
        additional = kwargs.get('additional')
        authors = kwargs.get('authors')
        source_type = kwargs.get('source_type')
        use_private = kwargs.get('private')
        error_msg = None
        if not stylesheet:
            error_msg = _('Please select a stylesheet.')
        if error_msg is not None:
            utils.message_dialog(error_msg, Gtk.MessageType.WARNING)
            return False

        fop_cmd = get_fop()
        logger.debug('fop command: %s', fop_cmd)
        if not fop_cmd:
            if sys.platform == 'win32' and paths.main_is_frozen:
                utils.message_dialog(
                    _('Could not find Apache FOP renderer.  You may need to '
                      'install it. The installer you used may contain FOP and '
                      'Java as extra components.'),
                    Gtk.MessageType.ERROR
                )
            else:
                utils.message_dialog(
                    _('Could not find Apache FOP renderer.  You may need to '
                      'install it.'),
                    Gtk.MessageType.ERROR
                )
            return False

        session = db.Session()

        # convert objects to ABCDAdapters depending on source type for
        # passing to create_abcd
        adapted = []
        if source_type == plant_source_type:
            plants = sorted(get_plants_pertinent_to(objs, session=session),
                            key=utils.natsort_key)
            if len(plants) == 0:
                utils.message_dialog(_('There are no plants in the search '
                                       'results.  Please try another search.'))
                return False
            for plt in plants:
                if use_private:
                    adapted.append(PlantABCDAdapter(plt, for_labels=True))
                elif not plt.accession.private:
                    adapted.append(PlantABCDAdapter(plt, for_labels=True))
        elif source_type == species_source_type:
            species = sorted(get_species_pertinent_to(objs, session=session),
                             key=utils.natsort_key)
            if len(species) == 0:
                utils.message_dialog(_('There are no species in the search '
                                       'results.  Please try another search.'))
                return False
            for sp in species:
                adapted.append(SpeciesABCDAdapter(sp, for_labels=True))
        elif source_type == accession_source_type:
            accessions = sorted(get_accessions_pertinent_to(objs,
                                                            session=session),
                                key=utils.natsort_key)
            if len(accessions) == 0:
                utils.message_dialog(_('There are no accessions in the search '
                                       'results.  Please try another search.'))
                return False
            for acc in accessions:
                if use_private:
                    adapted.append(AccessionABCDAdapter(acc, for_labels=True))
                elif not acc.private:
                    adapted.append(AccessionABCDAdapter(acc, for_labels=True))
        else:
            raise NotImplementedError('unknown source type')

        if len(adapted) == 0:
            # nothing adapted....possibly everything was private
            # TODO: if everything was private and that is really why we got
            # here then it is probably better to show a dialog with a message
            # and raise and exception which appears as an error
            raise Exception('No objects could be adapted to ABCD units.')
        abcd_data = create_abcd(adapted, authors=authors, validate=False)

        session.close()

        # for debugging only:
        # etree.dump(abcd_data.getroot())

        # create xsl fo file
        dummy, fo_filename = tempfile.mkstemp()
        style_etree = etree.parse(stylesheet)
        transform = etree.XSLT(style_etree)
        result = transform(abcd_data)
        fo_outfile = open(fo_filename, 'w')
        fo_outfile.write(str(result))
        fo_outfile.close()
        dummy, filename = tempfile.mkstemp()
        filename = '%s.pdf' % filename

        # TODO <RD> is there a better method?
        if additional:
            from distutils.dir_util import copy_tree
            fo_dir = os.path.dirname(fo_filename)
            copy_tree(additional, fo_dir)

        # supress command prompt in windows
        creationflags = 0
        if sys.platform == 'win32':
            creationflags = subprocess.CREATE_NO_WINDOW

        # run the report to produce the pdf file
        fop_out = subprocess.run(
            [fop_cmd, '-fo', fo_filename, '-pdf', filename],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
            creationflags=creationflags
        )
        logger.debug('FOP return code: %s', fop_out.returncode)
        logger.debug('FOP stderr: %s', fop_out.stderr)
        logger.debug('FOP stdout: %s', fop_out.stdout)
        logger.debug(filename)
        if not os.path.exists(filename):
            utils.message_dialog(_('Error creating the PDF file. Please '
                                   'ensure that your PDF formatter is '
                                   'properly installed.'),
                                 Gtk.MessageType.ERROR)
            return False
        try:
            desktop.open(filename)
        except OSError:
            utils.message_dialog(_('Could not open the report with the '
                                   'default program. You can open the '
                                   'file manually at %s') % filename)

        return True


# expose the formatter
try:
    import lxml.etree as etree
except ImportError:
    utils.message_dialog('The <i>lxml</i> package is required for the '
                         'XSL report plugin')
else:
    formatter_plugin = XSLFormatterPlugin
