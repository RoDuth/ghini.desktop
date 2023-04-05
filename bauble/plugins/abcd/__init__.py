# Copyright (c) 2005,2006,2007,2008,2009 Brett Adams <brett@belizebotanic.org>
# Copyright (c) 2012-2016 Mario Frasca <mario@anche.no>
# Copyright (c) 2016-2023 Ross Demuth <rossdemuth123@gmail.com>
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

from abc import ABC, abstractmethod
from collections.abc import Iterable, Generator
from datetime import datetime
import os
from pathlib import Path

import logging
logger = logging.getLogger(__name__)

from lxml import etree
from lxml.etree import Element, SubElement, ElementTree

from gi.repository import Gtk

from sqlalchemy.orm import object_session

from bauble import db, pb_set_fraction, task
from bauble import utils
from bauble import pluginmgr
from bauble import prefs
from bauble.plugins.garden.plant import Plant
from bauble.plugins.garden import institution

# NOTE: see biocase provider software for reading and writing ABCD data
# files, already downloaded software to desktop


def validate_xml(root, feedback=False):
    """Validate root against ABCD 2.06 schema

    :param root: root of an XML tree to validate against
    :returns: True or False depending if root validates correctly.  If feedback
        is True also return the validation error message.
    """
    abcd_schema = etree.XMLSchema(
        file=str(Path(__file__).resolve().parent / 'abcd_2.06.xsd')
    )

    if feedback:
        msg = ''
        validates = False
        try:
            abcd_schema.assertValid(root)
            validates = True
        except etree.DocumentInvalid as e:
            msg = e
        return validates, msg
    return abcd_schema.validate(root)


def verify_institution(inst):

    def verify(item):
        return item != '' and item is not None

    return (verify(inst.name) and
            verify(inst.technical_contact) and
            verify(inst.email) and
            verify(inst.contact) and
            verify(inst.code))


namespaces = {'abcd': 'http://www.tdwg.org/schemas/abcd/2.06'}


def abcd_element(parent, name, text=None, attrib=None):
    """Append a named element to parent, with text and attributes.

    it assumes the element to be added is in the abcd namespace.

    :param parent: an element
    :param name: a string, the name of the new element
    :param text: the text attribue to set on the new element
    :param attrib: any additional attributes for the new element
    """
    if attrib is None:
        attrib = {}
    elem = SubElement(parent, f'{{{namespaces["abcd"]}}}{name}',
                      nsmap=namespaces, attrib=attrib)
    elem.text = text
    return elem


def data_sets():
    return Element(f'{{{namespaces.get("abcd")}}}DataSets', nsmap=namespaces)


class ABCDAdapter(ABC):
    """An abstract base class for creating ABCD adapters."""
    # TODO: create a HigherTaxonRank/HigherTaxonName iteratorator for a list
    # of all the higher taxon

    # TODO: need to mark those fields that are required and those that
    # are optional
    @abstractmethod
    def get_unitid(self):
        """Get a value for the UnitID."""
        ...

    @abstractmethod
    def get_family(self):
        """Get a value for the family."""
        ...

    @abstractmethod
    def get_fullscientificnamestring(self, authors=True):
        """Get the full scientific name string."""
        ...

    @abstractmethod
    def get_genusormonomial(self):
        """Get the Genus string."""
        ...

    @abstractmethod
    def get_firstepithet(self):
        """Get the first epithet."""
        ...

    @abstractmethod
    def get_authorteam(self):
        """Get the Author string."""
        ...

    @abstractmethod
    def get_infraspecificauthor(self):
        ...

    @abstractmethod
    def get_infraspecificrank(self):
        ...

    @abstractmethod
    def get_infraspecificepithet(self):
        ...

    @abstractmethod
    def get_cultivarname(self):
        ...

    @abstractmethod
    def get_hybridflag(self):
        ...

    def get_identificationqualifier(self):
        pass

    def get_identificationqualifierrank(self):
        pass

    @abstractmethod
    def get_informalnamestring(self):
        """Get the common name string."""
        ...

    @abstractmethod
    def extra_elements(self, unit):
        """Add extra non required elements."""
        ...

    @abstractmethod
    def species_markup(self, unit):
        ...


class SpeciesABCDAdapter(ABCDAdapter):
    """An adapter to convert a Species to an ABCD Unit.

    the SpeciesABCDAdapter does not create a valid ABCDUnit since we can't
    provide the required UnitID
    """
    def __init__(self, species, for_reports=False):

        # hold on to the accession so it doesn't get cleaned up and closed
        self.session = object_session(species)
        self.for_reports = for_reports
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
        return self.species.genus.epithet

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
        if cultivar == 'cv.':
            return 'cv.'
        if cultivar:
            return utils.xml_safe(f"'{cultivar}'")
        return ''

    def get_hybridflag(self):
        if self.species.genus.hybrid:
            return self.species.genus.hybrid, '1'
        if self.species.hybrid:
            return self.species.hybrid, '2'
        return None

    def get_informalnamestring(self):
        vernacular_name = self.species.default_vernacular_name
        if vernacular_name is None:
            return None
        return utils.xml_safe(vernacular_name)

    @staticmethod
    def notes_in_list(notes, unit, for_reports):
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

        # not ABCD so not in the namespace and only create for reports
        if for_reports:
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
        return self.notes_in_list(self.species.notes, unit, self.for_reports)

    def extra_elements(self, unit):
        # distribution isn't in the ABCD namespace so it should create an
        # invalid XML file
        if self.for_reports:
            if self.species.label_distribution:
                etree.SubElement(
                    unit, 'LabelDistribution'
                ).text = self.species.label_distribution

            if self.species.distribution:
                etree.SubElement(
                    unit, 'Distribution'
                ).text = self.species.distribution_str()

    def species_markup(self, unit):
        if self.for_reports:
            # first the non marked up version
            etree.SubElement(
                unit, 'FullSpeciesName'
            ).text = self.species.str()

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
    def __init__(self, accession, for_reports=False):
        super().__init__(accession.species, for_reports)
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
            idqual = f'({idqual})'
        return utils.xml_safe(idqual)

    def get_identificationqualifierrank(self):
        idqrank = self.accession.id_qual_rank
        if idqrank is None:
            return None
        # as only the last infraspecific part is used always set to 3 for
        # infraspecifics
        return {'genus': '1',
                'sp': '2',
                'infrasp1': '3',
                'infrasp2': '3',
                'infrasp3': '3',
                'infrasp4': '3'}.get(idqrank, '1')

    def get_datelastedited(self):
        return utils.xml_safe(self.accession._last_updated.isoformat())

    def get_notes(self, unit):
        return self.notes_in_list(self.accession.notes, unit, self.for_reports)

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
                    abcd_element(lat_long, 'CoordinateErrorDistanceInMeters',
                                 text=utils.xml_safe(collection.geo_accy))

            if collection.elevation:
                altitude = abcd_element(gathering, 'Altitude')
                if collection.elevation_accy:
                    text = (f'{collection.elevation}m '
                            f'(+/- {collection.elevation_accy}m)')
                else:
                    text = f'{collection.elevation}m'
                abcd_element(altitude, 'MeasurementOrFactText', text=text)

            if collection.notes:
                abcd_element(gathering, 'Notes',
                             utils.xml_safe(collection.notes))

    def species_markup(self, unit):
        if self.for_reports:
            # first the non marked up version
            etree.SubElement(
                unit, 'FullSpeciesName'
            ).text = self.accession.species_str()

            unit.append(
                etree.fromstring(
                    '<FullSpeciesNameMarkup>'
                    f'{self.accession.species_str(markup=True)}'
                    '</FullSpeciesNameMarkup>'
                )
            )

            unit.append(
                etree.fromstring(
                    '<FullSpeciesNameMarkupAuthors>'
                    f'{self.accession.species_str(authors=True, markup=True)}'
                    '</FullSpeciesNameMarkupAuthors>'
                )
            )


class PlantABCDAdapter(AccessionABCDAdapter):
    """An adapter to convert a Plant to an ABCD Unit."""
    def __init__(self, plant, for_reports=False):
        super().__init__(plant.accession, for_reports)
        self.plant = plant

    def get_unitid(self):
        return utils.xml_safe(str(self.plant))

    def get_datelastedited(self):
        return utils.xml_safe(self.plant._last_updated.isoformat())

    def get_notes(self, unit):
        return self.notes_in_list(self.plant.notes, unit, self.for_reports)

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


class ABCDCreator:

    def __init__(self,
                 decorated_objects: Iterable[ABCDAdapter],
                 authors: bool = True) -> None:
        """
        :param decorated_objects: iterable of ABCDAdapter objects, to extend
            task functionality of `generate_elements` supply a generator.
        :param authors: flag to control whether to include the authors in the
            species name
        """
        self.decorated_objects = decorated_objects
        self.authors = authors
        self.datasets = data_sets()
        self.units = None
        self.inst = institution.Institution()

    def _create_units_element(self) -> SubElement:
        """Create the base of the 'Units' subelement"""
        if not verify_institution(self.inst):
            msg = _('Some or all of the information about your institution or '
                    'business is not complete. Please make sure that the '
                    'Name, Technical Contact, Email, Contact and Institution '
                    'Code fields are filled in.')
            utils.message_dialog(msg)
            institution.InstitutionTool().start()
            self.inst = institution.Institution()
            return self._create_units_element()

        dataset = abcd_element(self.datasets, 'DataSet')
        tech_contacts = abcd_element(dataset, 'TechnicalContacts')
        tech_contact = abcd_element(tech_contacts, 'TechnicalContact')

        abcd_element(tech_contact, 'Name', text=self.inst.technical_contact)
        abcd_element(tech_contact, 'Email', text=self.inst.email)
        cont_contacts = abcd_element(dataset, 'ContentContacts')
        cont_contact = abcd_element(cont_contacts, 'ContentContact')
        abcd_element(cont_contact, 'Name', text=self.inst.contact)
        abcd_element(cont_contact, 'Email', text=self.inst.email)
        metadata = abcd_element(dataset, 'Metadata', )
        description = abcd_element(metadata, 'Description')

        # TODO: need to get the localized language
        representation = abcd_element(description, 'Representation',
                                      attrib={'language': 'en'})
        revision = abcd_element(metadata, 'RevisionData')

        abcd_element(revision, 'DateModified',
                     text=datetime.today().isoformat())
        abcd_element(representation, 'Title', text='Exported data')
        return abcd_element(dataset, 'Units')

    def generate_elements(self) -> Generator[None, None, None]:
        """Generator that can be used as a task to create the ABCD elements.

        To extend task functionality supply `decorated_objects` as a generator
        with extra functionality included.
        """
        if self.units is None:
            self.units = self._create_units_element()
        for obj in self.decorated_objects:
            unit = abcd_element(self.units, 'Unit')
            abcd_element(unit, 'SourceInstitutionID', text=self.inst.code)

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

            # TODO: ABCDAdapter should provide an iterator so that we can
            # have multiple HigherTaxonName's
            abcd_element(higher_taxon, 'HigherTaxonName',
                         text=obj.get_family())
            abcd_element(higher_taxon, 'HigherTaxonRank', text='familia')

            scientific_name = abcd_element(taxon_identified, 'ScientificName')
            abcd_element(scientific_name, 'FullScientificNameString',
                         text=obj.get_fullscientificnamestring(self.authors))

            name_atomised = abcd_element(scientific_name, 'NameAtomised')
            botanical = abcd_element(name_atomised, 'Botanical')
            abcd_element(botanical, 'GenusOrMonomial',
                         text=obj.get_genusormonomial())
            abcd_element(botanical, 'FirstEpithet',
                         text=obj.get_firstepithet())
            if obj.get_infraspecificepithet() and obj.get_infraspecificrank():
                abcd_element(botanical, 'InfraspecificEpithet',
                             text=obj.get_infraspecificepithet())
                abcd_element(botanical, 'Rank',
                             text=obj.get_infraspecificrank())
            if obj.get_hybridflag():
                text, insertionpoint = obj.get_hybridflag()
                abcd_element(botanical, 'HybridFlag',
                             text=text,
                             attrib={'insertionpoint': insertionpoint})
            author_team = obj.get_authorteam()
            if author_team is not None:
                abcd_element(botanical, 'AuthorTeam', text=author_team)
            if obj.get_cultivarname():
                abcd_element(botanical, 'CultivarName',
                             text=obj.get_cultivarname())
            abcd_element(identification, 'PreferredFlag', text='true')

            # vernacular name identification
            # TODO: should we include all the vernacular names or only the
            # default one
            vernacular_name = obj.get_informalnamestring()
            if vernacular_name is not None:
                identification = abcd_element(identifications,
                                              'Identification')
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
            obj.species_markup(unit)
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
                    notes_str += (f'{note["category"]} = {note["text"]} '
                                  f'({note["user"]} : {note["date"]})|')
                abcd_element(unit, 'Notes',
                             text=utils.xml_safe(str(notes_str)))
            yield

    def get_element_tree(self) -> ElementTree:
        """Call after `generate_elements` has been called."""
        return ElementTree(self.datasets)


class ABCDExporter:
    """Export Plants to an ABCD file."""
    def __init__(self):
        self.nplants = 0

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
            self.nplants = len(plants)
        else:
            self.nplants = db.Session().query(Plant).count()

        logger.debug('ABCDExporter exporting %s plant records', self.nplants)
        if self.nplants > 3000:
            msg = (_('You are exporting %(nplants)s plants to ABCD format.  '
                     'Exporting this many plants may take a while.'
                     '\n\n<i>Would you like to continue?</i>') %
                   {'nplants': self.nplants})
            if not utils.yes_no_dialog(msg):
                return
        self.run(filename, plants)

    def unit_generator(self, plants, notify=None):
        if notify is None:
            notify = self.nplants > 100

        five_percent = int(self.nplants / 20) or 1

        for records_done, plant in enumerate(plants):
            if notify and records_done % five_percent == 0:
                pb_set_fraction(records_done / self.nplants)
            yield PlantABCDAdapter(plant)

    def run(self, filename, plants=None):
        if filename is None:
            raise ValueError("filename can not be None")

        if os.path.exists(filename) and not os.path.isfile(filename):
            raise ValueError(f"{filename} exists and is not a a regular file")

        # if plants is None then export all plants, this could be huge
        # TODO: do something about this, like list the number of plants
        # to be returned and make sure this is what the user wants
        if plants is None:
            plants = db.Session().query(Plant)

        abcd = ABCDCreator(self.unit_generator(plants))
        task.queue(abcd.generate_elements())
        data = abcd.get_element_tree()

        # is this right for unicode?
        data.write_c14n(filename)

        # let the user know when the file isn't valid ABCD
        valid, e = validate_xml(data, feedback=True)
        if not valid:
            msg = (_("The ABCD file was created but failed to validate "
                     "correctly against the ABCD standard.\n\n%s") %
                   utils.xml_safe(e))
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


plugin = ABCDImexPlugin
