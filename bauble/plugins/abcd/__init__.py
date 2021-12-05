# Copyright (c) 2005,2006,2007,2008,2009 Brett Adams <brett@belizebotanic.org>
# Copyright (c) 2012-2016 Mario Frasca <mario@anche.no>
# Copyright (c) 2016-2021 Ross Demuth <rossdemuth123@gmail.com>
# Copyright 2017 Jardín Botánico de Quito
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
# -*- coding: utf-8 -*-
#
"""
ABCD import/exporter
"""

import os
from pathlib import Path

import logging
logger = logging.getLogger(__name__)

from gi.repository import Gtk

from sqlalchemy.orm import object_session

from bauble import db
from bauble.error import check
from bauble import paths
from bauble import utils
from bauble import pluginmgr
from bauble import prefs
from bauble.plugins.garden.plant import Plant

# NOTE: see biocase provider software for reading and writing ABCD data
# files, already downloaded software to desktop


def validate_xml(root):
    """
    Validate root against ABCD 2.06 schema

    :param root: root of an XML tree to validate against
    :returns: True or False depending if root validates correctly
    """
    schema_file = os.path.join(
        paths.lib_dir(), 'plugins', 'abcd', 'abcd_2.06.xsd')
    xmlschema_doc = etree.parse(schema_file)
    abcd_schema = etree.XMLSchema(xmlschema_doc)
    return abcd_schema.validate(root)


def verify_institution(institution):

    def verify(item):
        return item != '' and item is not None

    return verify(institution.name) and \
        verify(institution.technical_contact) and \
        verify(institution.email) and verify(institution.contact) and \
        verify(institution.code)


namespaces = {'abcd': 'http://www.tdwg.org/schemas/abcd/2.06'}


def abcd_element(parent, name, text=None, attrib=None):
    """
    append a named element to parent, with text and attributes.

    it assumes the element to be added is in the abcd namespace.

    :param parent: an element
    :param name: a string, the name of the new element
    :param text: the text attribue to set on the new element
    :param attrib: any additional attributes for the new element
    """
    if attrib is None:
        attrib = {}
    elem = SubElement(parent, '{%s}%s' % (namespaces['abcd'], name),
                      nsmap=namespaces, attrib=attrib)
    elem.text = text
    return elem


def data_sets():
    return Element('{%s}DataSets' % namespaces.get('abcd'), nsmap=namespaces)


class ABCDAdapter:
    """An abstract base class for creating ABCD adapters."""
    # TODO: create a HigherTaxonRank/HigherTaxonName iteratorator for a list
    # of all the higher taxon

    # TODO: need to mark those fields that are required and those that
    # are optional
    def extra_elements(self, unit):
        """Add extra non required elements."""
        pass

    def __init__(self, obj):
        self._object = obj

    def get_unitid(self):
        """Get a value for the UnitID."""
        pass

    def get_family(self):
        """Get a value for the family."""
        pass

    def get_fullscientificnamestring(self, authors=True):
        """Get the full scientific name string."""
        pass

    def get_genusormonomial(self):
        """Get the Genus string."""
        pass

    def get_firstepithet(self):
        """Get the first epithet."""
        pass

    def get_authorteam(self):
        """Get the Author string."""
        pass

    def get_infraspecificauthor(self):
        pass

    def get_infraspecificrank(self):
        pass

    def get_infraspecificepithet(self):
        pass

    def get_cultivarname(self):
        pass

    def get_hybridflag(self):
        pass

    def get_identificationqualifier(self):
        pass

    def get_identificationqualifierrank(self):
        pass

    def get_informalnamestring(self):
        """Get the common name string."""
        pass


class SpeciesABCDAdapter(ABCDAdapter):
    """An adapter to convert a Species to an ABCD Unit.

    the SpeciesABCDAdapter does not create a valid ABCDUnit since we can't
    provide the required UnitID
    """
    def __init__(self, species, for_labels=False):
        super().__init__(species)

        # hold on to the accession so it doesn't get cleaned up and closed
        self.session = object_session(species)
        self.for_labels = for_labels
        self.species = species
        self._date_format = prefs.prefs[prefs.date_format_pref]

    def get_unitid(self):
        # **** Returning the empty string for the UnitID makes the
        # ABCD data NOT valid ABCD but it does make it work for
        # creating reports without including the accession or plant
        # code
        return utils.xml_safe(self.species.id)

    def get_datelastedited(self):
        return utils.xml_safe(self.species._last_updated.isoformat())

    def get_family(self):
        return utils.xml_safe(self.species.genus.family)

    def get_fullscientificnamestring(self, authors=True):
        sp_str = self.species.str(authors=authors, markup=False)
        return utils.xml_safe(sp_str)

    def get_genusormonomial(self):
        return utils.xml_safe(str(self.species.genus))

    def get_firstepithet(self):
        species = self.species.sp
        if species is None:
            return None
        return utils.xml_safe(str(species))

    def get_authorteam(self):
        author = self.species.sp_author
        if author is None:
            return None
        return utils.xml_safe(author)

    def get_infraspecificauthor(self):
        return utils.xml_safe(str(self.species.infraspecific_author))

    def get_infraspecificrank(self):
        return utils.xml_safe(str(self.species.infraspecific_rank))

    def get_infraspecificepithet(self):
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

    def get_cultivarname(self):
        cultivar = self.species.cultivar_epithet
        if cultivar is None:
            return 'cv.'
        if cultivar:
            return utils.xml_safe("'%s'" % cultivar)
        return ''

    def get_hybridflag(self):
        if self.species.hybrid is True:
            return utils.xml_safe(str(self.species.hybrid_char))
        return None

    def get_informalnamestring(self):
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

    def get_notes(self, unit):
        return self.notes_in_list(self.species.notes, unit, self.for_labels)

    def extra_elements(self, unit):
        # distribution isn't in the ABCD namespace so it should create an
        # invalid XML file
        if self.for_labels:
            if self.species.label_distribution:
                etree.SubElement(
                    unit, 'LabelDistribution'
                ).text = self.species.label_distribution
            if self.species.distribution:
                etree.SubElement(
                    unit, 'Distribution'
                ).text = self.species.distribution_str()
            etree.SubElement(
                unit, 'FullSpeciesName'
            ).text = self.species.str()
            # full_sp_markup = etree.HTML(self.species.str(markup=True))
            unit.append(
                etree.fromstring(
                    '<FullSpeciesNameMarkup>'
                    f'{self.species.str(markup=True)}'
                    '</FullSpeciesNameMarkup>'
                )
            )
            unit.append(
                etree.fromstring(
                    '<FullSpeciesNameMarkupAuthors>'
                    f'{self.species.str(authors=True, markup=True)}'
                    '</FullSpeciesNameMarkupAuthors>'
                )
            )


class AccessionABCDAdapter(SpeciesABCDAdapter):
    """An adapter to convert a Plant to an ABCD Unit"""
    def __init__(self, accession, for_labels=False):
        super().__init__(accession.species, for_labels)
        self.accession = accession

    def get_unitid(self):
        return utils.xml_safe(str(self.accession))

    def get_fullscientificnamestring(self, authors=True):
        sp_str = self.accession.species_str(authors=authors, markup=False)
        return utils.xml_safe(sp_str)

    def get_identificationqualifier(self):
        idqual = self.accession.id_qual
        if idqual is None:
            return None
        if idqual in ('forsan', 'near', 'incorrect'):
            idqual = '(%s)' % idqual
        return utils.xml_safe(idqual)

    def get_identificationqualifierrank(self):
        idqrank = self.accession.id_qual_rank
        if idqrank is None:
            return None
        return utils.xml_safe(idqrank)

    def get_datelastedited(self):
        return utils.xml_safe(self.accession._last_updated.isoformat())

    def get_notes(self, unit):
        return self.notes_in_list(self.accession.notes, unit, self.for_labels)

    def extra_elements(self, unit):
        super().extra_elements(unit)

        if self.accession.source and self.accession.source.collection:
            collection = self.accession.source.collection
            gathering = abcd_element(unit, 'Gathering')

            if collection.collectors_code:
                abcd_element(gathering, 'Code',
                             text=utils.xml_safe(collection.collectors_code))

            # TODO: get date pref for DayNumberBegin
            if collection.date:
                date_time = abcd_element(gathering, 'DateTime')
                abcd_element(date_time, 'DateText',
                             utils.xml_safe(collection.date.isoformat()))

            if collection.collector:
                agents = abcd_element(gathering, 'Agents')
                agent = abcd_element(agents, 'GatheringAgent')
                abcd_element(agent, 'AgentText',
                             text=utils.xml_safe(collection.collector))

            if collection.locale:
                abcd_element(gathering, 'LocalityText',
                             text=utils.xml_safe(collection.locale))

            if collection.region:
                named_areas = abcd_element(gathering, 'NamedAreas')
                named_area = abcd_element(named_areas, 'NamedArea')
                abcd_element(named_area, 'AreaName',
                             text=utils.xml_safe(collection.region))

            if collection.habitat:
                abcd_element(gathering, 'AreaDetail',
                             text=utils.xml_safe(collection.habitat))

            if collection.longitude or collection.latitude:
                site_coords = abcd_element(gathering, 'SiteCoordinateSets')
                coord = abcd_element(site_coords, 'SiteCoordinates')
                lat_long = abcd_element(coord, 'CoordinatesLatLong')
                abcd_element(lat_long, 'LongitudeDecimal',
                             text=utils.xml_safe(collection.longitude))
                abcd_element(lat_long, 'LatitudeDecimal',
                             text=utils.xml_safe(collection.latitude))
                if collection.gps_datum:
                    abcd_element(lat_long, 'SpatialDatum',
                                 text=utils.xml_safe(collection.gps_datum))
                if collection.geo_accy:
                    abcd_element(coord, 'CoordinateErrorDistanceInMeters',
                                 text=utils.xml_safe(collection.geo_accy))

            if collection.elevation:
                altitude = abcd_element(gathering, 'Altitude')
                if collection.elevation_accy:
                    text = '%sm (+/- %sm)' % (collection.elevation,
                                              collection.elevation_accy)
                else:
                    text = '%sm' % collection.elevation
                abcd_element(altitude, 'MeasurementOrFactText', text=text)

            if collection.notes:
                abcd_element(gathering, 'Notes',
                             utils.xml_safe(collection.notes))


class PlantABCDAdapter(AccessionABCDAdapter):
    """An adapter to convert a Plant to an ABCD Unit."""
    def __init__(self, plant, for_labels=False):
        super().__init__(plant.accession, for_labels)
        self.plant = plant

    def get_unitid(self):
        return utils.xml_safe(str(self.plant))

    def get_datelastedited(self):
        return utils.xml_safe(self.plant._last_updated.isoformat())

    def get_notes(self, unit):
        return self.notes_in_list(self.plant.notes, unit, self.for_labels)

    def extra_elements(self, unit):
        bg_unit = abcd_element(unit, 'BotanicalGardenUnit')
        abcd_element(bg_unit, 'AccessionSpecimenNumbers',
                     text=utils.xml_safe(self.plant.quantity))
        abcd_element(bg_unit, 'LocationInGarden',
                     text=utils.xml_safe(str(self.plant.location)))
        # TODO: AccessionStatus, AccessionMaterialtype,
        # ProvenanceCategory, AccessionLineage, DonorCategory,
        # PlantingDate, Propagation
        super().extra_elements(unit)


def create_abcd(decorated_objects, authors=True, validate=True):
    """
    :param objects: a list/tuple of objects that implement the ABCDDecorator
      interface
    :param authors: flag to control whether to include the authors in the
      species name
    :param validate: whether we should validate the data before returning
    :returns: a valid ABCD ElementTree
    """
    from bauble.plugins.garden import institution
    inst = institution.Institution()
    if not verify_institution(inst):
        msg = _('Some or all of the information about your institution or '
                'business is not complete. Please make sure that the '
                'Name, Technical Contact, Email, Contact and Institution '
                'Code fields are filled in.')
        utils.message_dialog(msg)
        institution.InstitutionTool().start()
        return create_abcd(decorated_objects, authors, validate)

    datasets = data_sets()
    dataset = abcd_element(datasets, 'DataSet')
    tech_contacts = abcd_element(dataset, 'TechnicalContacts')
    tech_contact = abcd_element(tech_contacts, 'TechnicalContact')

    # TODO: need to include contact information in bauble meta when
    # creating a new database
    abcd_element(tech_contact, 'Name', text=inst.technical_contact)
    abcd_element(tech_contact, 'Email', text=inst.email)
    cont_contacts = abcd_element(dataset, 'ContentContacts')
    cont_contact = abcd_element(cont_contacts, 'ContentContact')
    abcd_element(cont_contact, 'Name', text=inst.contact)
    abcd_element(cont_contact, 'Email', text=inst.email)
    metadata = abcd_element(dataset, 'Metadata', )
    description = abcd_element(metadata, 'Description')

    # TODO: need to get the localized language
    representation = abcd_element(description, 'Representation',
                                  attrib={'language': 'en'})
    revision = abcd_element(metadata, 'RevisionData')
    abcd_element(revision, 'DateModified', text='2001-03-01T00:00:00')
    abcd_element(representation, 'Title', text='TheTitle')
    units = abcd_element(dataset, 'Units')

    # build the ABCD unit
    for obj in decorated_objects:
        unit = abcd_element(units, 'Unit')
        abcd_element(unit, 'SourceInstitutionID', text=inst.code)

        # TODO: don't really understand the SourceID element
        abcd_element(unit, 'SourceID', text='Ghini')

        abcd_element(unit, 'UnitID', text=obj.get_unitid())
        abcd_element(unit, 'DateLastEdited', text=obj.get_datelastedited())

        # TODO: add list of verifications to Identifications

        # scientific name identification
        identifications = abcd_element(unit, 'Identifications')
        identification = abcd_element(identifications, 'Identification')
        result = abcd_element(identification, 'Result')
        taxon_identified = abcd_element(result, 'TaxonIdentified')
        higher_taxa = abcd_element(taxon_identified, 'HigherTaxa')
        higher_taxon = abcd_element(higher_taxa, 'HigherTaxon')

        # TODO: ABCDDecorator should provide an iterator so that we can
        # have multiple HigherTaxonName's
        abcd_element(higher_taxon, 'HigherTaxonName', text=obj.get_family())
        abcd_element(higher_taxon, 'HigherTaxonRank', text='familia')

        scientific_name = abcd_element(taxon_identified, 'ScientificName')
        abcd_element(scientific_name, 'FullScientificNameString',
                     text=obj.get_fullscientificnamestring(authors))

        name_atomised = abcd_element(scientific_name, 'NameAtomised')
        botanical = abcd_element(name_atomised, 'Botanical')
        abcd_element(botanical, 'GenusOrMonomial',
                     text=obj.get_genusormonomial())
        abcd_element(botanical, 'FirstEpithet', text=obj.get_firstepithet())
        if obj.get_infraspecificepithet():
            abcd_element(botanical, 'InfraspecificEpithet',
                         text=obj.get_infraspecificepithet())
            abcd_element(botanical, 'Rank',
                         text=obj.get_infraspecificrank())
        if obj.get_hybridflag():
            abcd_element(botanical, 'HybridFlag', text=obj.get_hybridflag())
        if obj.get_cultivarname():
            abcd_element(botanical, 'CultivarName',
                         text=obj.get_cultivarname())
        author_team = obj.get_authorteam()
        if author_team is not None:
            abcd_element(botanical, 'AuthorTeam', text=author_team)
        abcd_element(identification, 'PreferredFlag', text='true')

        # vernacular name identification
        # TODO: should we include all the vernacular names or only the default
        # one
        vernacular_name = obj.get_informalnamestring()
        if vernacular_name is not None:
            identification = abcd_element(identifications, 'Identification')
            result = abcd_element(identification, 'Result')
            taxon_identified = abcd_element(result, 'TaxonIdentified')
            abcd_element(taxon_identified, 'InformalNameString',
                         text=vernacular_name)
        if obj.get_identificationqualifier():
            abcd_element(scientific_name, 'IdentificationQualifier',
                         text=obj.get_identificationqualifier(),
                         attrib={'insertionpoint':
                                 obj.get_identificationqualifierrank()})
        # add all the extra non standard elements
        obj.extra_elements(unit)
        # TODO: handle verifiers/identifiers
        # TODO: RecordBasis

        # notes are last in the schema and extra_elements() shouldn't
        # add anything that comes past Notes, e.g. RecordURI,
        # EAnnotations, UnitExtension
        notes_list = obj.get_notes(unit)
        notes_str = ''
        if notes_list:
            for note in notes_list:
                for key, value in note.items():
                    note[key] = value.replace('|', '_')
                # make a string of notes using | as seperator
                notes_str += '%s = %s (%s : %s)|' % (
                    note['category'],
                    note['text'],
                    note['user'],
                    note['date'],
                )
            abcd_element(unit, 'Notes', text=utils.xml_safe(str(notes_str)))

    if validate:
        check(validate_xml(datasets), 'ABCD data not valid')

    return ElementTree(datasets)


class ABCDExporter:
    """Export Plants to an ABCD file."""

    def start(self, filename=None, plants=None):
        if filename is None:  # no filename, ask the user
            dialog = Gtk.FileChooserNative.new(
                _("Choose a file to export to..."),
                None,
                Gtk.FileChooserAction.SAVE
            )
            dialog.set_current_folder(str(Path.home()))
            filename = None
            if dialog.run() == Gtk.ResponseType.ACCEPT:
                filename = dialog.get_filename()
            dialog.destroy()
            if not filename:
                return

        if plants:
            nplants = len(plants)
        else:
            nplants = db.Session().query(Plant).count()

        logger.debug('ABCDExporter exporting %s plant records', nplants)
        if nplants > 3000:
            msg = _('You are exporting %(nplants)s plants to ABCD format.  '
                    'Exporting this many plants may take several minutes.  '
                    '\n\n<i>Would you like to continue?</i>') \
                % ({'nplants': nplants})
            if not utils.yes_no_dialog(msg):
                return
        self.run(filename, plants)

    @staticmethod
    def run(filename, plants=None):
        if filename is None:
            raise ValueError("filename can not be None")

        if os.path.exists(filename) and not os.path.isfile(filename):
            raise ValueError("%s exists and is not a a regular file"
                             % filename)

        # if plants is None then export all plants, this could be huge
        # TODO: do something about this, like list the number of plants
        # to be returned and make sure this is what the user wants
        if plants is None:
            plants = db.Session().query(Plant).all()

        data = create_abcd([PlantABCDAdapter(p) for p in plants],
                           validate=False)

        data.write_c14n(filename)

        # validate after the file is written so we still have some
        # output but let the user know the file isn't valid ABCD
        if not validate_xml(data):
            msg = _("The ABCD file was created but failed to validate "
                    "correctly against the ABCD standard.")
            utils.message_dialog(msg, Gtk.MessageType.WARNING)


class ABCDExportTool(pluginmgr.Tool):
    category = _("Export")
    label = _("ABCD")

    @classmethod
    def start(cls):
        ABCDExporter().start()


class ABCDImexPlugin(pluginmgr.Plugin):
    tools = [ABCDExportTool]
    depends = ["PlantsPlugin"]


try:
    from lxml import etree
    from lxml.etree import Element, SubElement, ElementTree
except ImportError:
    utils.message_dialog(_('The <i>lxml</i> package is required for the '
                           'ABCD plugin'))
else:
    plugin = ABCDImexPlugin
