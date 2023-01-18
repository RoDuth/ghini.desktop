# Copyright 2008-2010 Brett Adams
# Copyright 2015-2016 Mario Frasca <mario@anche.no>.
# Copyright 2017 Jardín Botánico de Quito
# Copyright 2020-2023 Ross Demuth <rossdemuth123@gmail.com>
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
accessions module
"""

import datetime
from decimal import Decimal, ROUND_DOWN
import os
from random import random
import traceback
import weakref
import re
from functools import reduce, partial
from pathlib import Path

import logging
logger = logging.getLogger(__name__)

from gi.repository import Gtk

from gi.repository import Pango
from sqlalchemy import (ForeignKey,
                        Column,
                        Unicode,
                        Integer,
                        UnicodeText,
                        func,
                        exists)
from sqlalchemy.orm import relationship, validates, backref
from sqlalchemy.orm.session import object_session
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.sql.expression import select, case, cast

import bauble
from bauble import db
from bauble import editor
from bauble import meta
from bauble.error import check
from bauble import paths
from bauble import prefs
from bauble import btypes as types
from bauble import utils
from bauble.view import (InfoBox,
                         InfoExpander,
                         LinksExpander,
                         PropertiesExpander,
                         select_in_search_results,
                         Action)
from bauble.utils import safe_int
from ..plants.species_editor import (species_cell_data_func,
                                     species_match_func,
                                     generic_sp_get_completions,
                                     species_to_string_matcher)
from .propagation import SourcePropagationPresenter, Propagation
from .source import (SourceDetail,
                     SourceDetailPresenter,
                     Source,
                     Collection,
                     CollectionPresenter,
                     PropagationChooserPresenter,
                     source_type_values)
# TODO: underneath the species entry create a label that shows information
# about the family of the genus of the species selected as well as more
# info about the genus so we know exactly what plant is being selected
# e.g. Malvaceae (sensu lato), Hibiscus (senso stricto)

BAUBLE_ACC_CODE_FORMAT = '%Y%PD####'
"""The system default value for accession.code_format  Used as a fall back when
no other code format is described in the `bauble` table.
"""


def longitude_to_dms(decimal):
    return decimal_to_dms(Decimal(decimal), 'long')


def latitude_to_dms(decimal):
    return decimal_to_dms(Decimal(decimal), 'lat')


def decimal_to_dms(decimal, long_or_lat):
    """
    :param decimal: the value to convert
    :param long_or_lat: should be either "long" or "lat"

    :return: direction, degrees, minutes, seconds (seconds rounded to two
        decimal places)
    """
    if long_or_lat == 'long':
        check(abs(decimal) <= 180)
    else:
        check(abs(decimal) <= 90)
    dir_map = {'long': ['E', 'W'],
               'lat': ['N', 'S']}
    direction = dir_map[long_or_lat][0]
    if decimal < 0:
        direction = dir_map[long_or_lat][1]
    dec = Decimal(str(abs(decimal)))
    degs = Decimal(str(dec)).to_integral(rounding=ROUND_DOWN)
    mins = Decimal(abs((dec - degs) * 60)).to_integral(rounding=ROUND_DOWN)
    mins2 = Decimal(abs((dec - degs) * 60))
    places = 2
    quant = Decimal((0, (1,), -places))
    secs = Decimal(abs((mins2 - mins) * 60)).quantize(quant)
    return direction, degs, mins, secs


def dms_to_decimal(direction, degs, mins, secs, precision=6):
    """convert degrees, minutes, seconds to decimal return a decimal.Decimal"""
    nplaces = Decimal(10) ** -precision
    if direction in ('E', 'W'):  # longitude
        check(abs(degs) <= 180)
    else:
        check(abs(degs) <= 90)
    check(abs(mins) < 60)
    check(abs(secs) < 60)
    degs = Decimal(str(abs(degs)))
    mins = Decimal(str(mins))
    secs = Decimal(str(secs))
    dec = abs(secs / Decimal('3600')) + abs(mins / Decimal('60.0')) + degs
    if direction in ('W', 'S'):
        dec = -dec
    return dec.quantize(nplaces)


def generic_taxon_add_action(model, view, presenter, top_presenter,
                             taxon_entry):
    """user hit click on taxon add button

    new taxon goes into model.species;
    its string representation into taxon_entry.
    """

    from ..plants.species import edit_species
    committed = edit_species(parent_view=view.get_window(),
                             is_dependent_window=True)
    if committed:
        if isinstance(committed, list):
            committed = committed[0]
        logger.debug('new taxon added from within AccessionEditor')
        # add the new taxon to the session and start using it
        presenter.session.add(committed)
        taxon_entry.set_text(f"{committed}")
        presenter.remove_problem(
            hash(Gtk.Buildable.get_name(taxon_entry)), None)
        setattr(model, 'species', committed)
        presenter._dirty = True
        top_presenter.refresh_sensitivity()
    else:
        logger.debug('new taxon not added after request from AccessionEditor')


def edit_callback(accessions, page=0):
    acc_editor = AccessionEditor(model=accessions[0])
    acc_editor.presenter.view.widgets.notebook.set_current_page(page)
    return acc_editor.start()


def add_plants_callback(accessions):
    # create a temporary session so that the temporary plant doesn't
    # get added to the accession
    session = db.Session()
    acc = session.merge(accessions[0])
    plt_editor = PlantEditor(model=Plant(accession=acc))
    session.close()
    return plt_editor.start()


def remove_callback(accessions):
    acc = accessions[0]
    a_lst = []
    for acc in accessions:
        a_lst.append(utils.xml_safe(str(acc)))
        if len(acc.plants) > 0:
            safe = utils.xml_safe
            plants = [str(plant) for plant in acc.plants]
            values = dict(num_plants=len(acc.plants),
                          plant_codes=safe(', '.join(plants)))
            msg = (_('%(num_plants)s plants depend on this accession: '
                     '<b>%(plant_codes)s</b>\n\n') % values +
                   _('You cannot remove an accession with plants.'))
            utils.message_dialog(msg, typ=Gtk.MessageType.WARNING)
            return False
    msg = _("Are you sure you want to remove the following accessions "
            "<b>%s</b>?") % ', '.join(i for i in a_lst)
    if not utils.yes_no_dialog(msg):
        return False

    session = object_session(acc)
    for acc in accessions:
        session.delete(acc)
    try:
        utils.remove_from_results_view(accessions)
        session.commit()
    except Exception as e:  # pylint: disable=broad-except
        msg = _('Could not delete.\n\n%s') % utils.xml_safe(str(e))
        utils.message_details_dialog(msg, traceback.format_exc(),
                                     typ=Gtk.MessageType.ERROR)
        session.rollback()
    return True


edit_action = Action('acc_edit', _('_Edit'),
                     callback=edit_callback,
                     accelerator='<ctrl>e')

add_plant_action = Action('acc_add', _('_Add Plants'),
                          callback=add_plants_callback,
                          accelerator='<ctrl>k')

remove_action = Action('acc_remove', _('_Delete'),
                       callback=remove_callback,
                       accelerator='<ctrl>Delete', multiselect=True)


acc_context_menu = [edit_action, add_plant_action, remove_action]


ver_level_descriptions = {
    0: _('The name of the record has not been checked by any authority.'),
    1: _('The name of the record determined by comparison with other '
         'named plants.'),
    2: _('The name of the record determined by a taxonomist or by other '
         'competent persons using herbarium and/or library and/or '
         'documented living material.'),
    3: _('The name of the plant determined by taxonomist engaged in '
         'systematic revision of the group.'),
    4: _('The record is part of type gathering or propagated from type '
         'material by asexual methods.')
}


class Verification(db.Base):  # pylint: disable=too-few-public-methods
    """
    :Table name: verification

    :Columns:
      verifier: :class:`sqlalchemy.types.Unicode`
        The name of the person that made the verification.
      date: :class:`sqlalchemy.types.Date`
        The date of the verification
      reference: :class:`sqlalchemy.types.UnicodeText`
        The reference material used to make this verification
      level: :class:`sqlalchemy.types.Integer`
        Determines the level or authority of the verifier. If it is
        not known whether the name of the record has been verified by
        an authority, then this field should be None.

        Possible values:
            - 0: The name of the record has not been checked by any authority.
            - 1: The name of the record determined by comparison with
              other named plants.
            - 2: The name of the record determined by a taxonomist or by
              other competent persons using herbarium and/or library and/or
              documented living material.
            - 3: The name of the plant determined by taxonomist engaged in
              systematic revision of the group.
            - 4: The record is part of type gathering or propagated from
              type material by asexual methods

      notes: :class:`sqlalchemy.types.UnicodeText`
        Notes about this verification.
      accession_id: :class:`sqlalchemy.types.Integer`
        Foreign Key to the :class:`Accession` table.
      species_id: :class:`sqlalchemy.types.Integer`
        Foreign Key to the :class:`~bauble.plugins.plants.Species` table.
      prev_species_id: :class:`~sqlalchemy.types.Integer`
        Foreign key to the :class:`~bauble.plugins.plants.Species`
        table. What it was verified from.
    """
    __tablename__ = 'verification'

    # columns
    verifier = Column(Unicode(64), nullable=False)
    date = Column(types.Date, nullable=False)
    reference = Column(UnicodeText)

    accession_id = Column(Integer, ForeignKey('accession.id'), nullable=False)
    accession = relationship('Accession', back_populates='verifications')

    # the level of assurance of this verification
    level = Column(Integer, nullable=False, autoincrement=False)

    # what it was verified as
    species_id = Column(Integer, ForeignKey('species.id'), nullable=False)

    # what it was verified from
    prev_species_id = Column(Integer, ForeignKey('species.id'), nullable=False)

    species = relationship(
        'Species', primaryjoin='Verification.species_id==Species.id'
    )
    prev_species = relationship(
        'Species', primaryjoin='Verification.prev_species_id==Species.id'
    )

    notes = Column(UnicodeText)


class Voucher(db.Base):  # pylint: disable=too-few-public-methods
    """
    :Table name: voucher

    :Columns:
      herbarium: :class:`sqlalchemy.types.Unicode`
        The name of the herbarium.
      code: :class:`sqlalchemy.types.Unicode`
        The herbarium code for the voucher.
      parent_material: :class:`bauble.btypes.Boolean`
        Is this voucher relative to the parent material of the accession.
      accession_id: :class:`sqlalchemy.types.Integer`
        Foreign key to the :class:`Accession` .
    """
    __tablename__ = 'voucher'
    herbarium = Column(Unicode(5), nullable=False)
    code = Column(Unicode(32), nullable=False)
    parent_material = Column(types.Boolean, default=False)
    accession_id = Column(Integer, ForeignKey('accession.id'), nullable=False)
    accession = relationship('Accession', uselist=False,
                             back_populates='vouchers')


# ITF2 - E.1; Provenance Type Flag; Transfer code: prot
prov_type_values = [
    ('Wild', _('Accession of wild source')),  # W
    ('Cultivated', _('Propagule(s) from a wild source plant')),  # Z
    ('NotWild', _("Accession not of wild source")),  # G
    ('InsufficientData', _("Insufficient Data")),  # U
    (None, ''),  # do not transfer this field
]

# ITF2 - E.3; Wild Provenance Status Flag; Transfer code: wpst
#  - further specifies the W prov type flag
#  Wild/Cultivated = Cultivated in the sense that there has been regeneration
#  activities etc. to reintroduced or translocated the species at the
#  collection site.
#  Native/NoneNative = In the sense that the housing facility is within the
#  indigenous range of the species
wild_prov_status_values = [
    # Endemic found within indigenous range (i.e. the Garden is within the
    # indigenous range)
    ('WildNative', _("Wild native")),
    # Wild but found outside indigenous range (i.e. the Garden is outside the
    # indigenous range)
    ('WildNonNative', _("Wild non-native")),
    # Endemic, cultivated, reintroduced or translocated (e.g. regeneration
    # activities) within its indigenous range
    ('CultivatedNative', _("Cultivated native")),
    # cultivated, reintroduced or translocated, (e.g. regeneration activities)
    # found outside its indigenous range
    ('CultivatedNonNative', _("Cultivated non-native")),
    # Not transferred
    (None, '')
]

# not ITF2
recvd_type_values = {
    'ALAY': _('Air layer'),
    'BBPL': _('Balled & burlapped plant'),
    'BRPL': _('Bare root plant'),
    'BUDC': _('Bud cutting'),
    'BUDD': _('Budded'),
    'BULB': _('Bulb'),
    'BBIL': _('Bulbil'),
    'CLUM': _('Clump'),
    'CORM': _('Corm'),
    'DIVI': _('Division'),
    'FLAS': _('Flask seed or spore'),
    'FLAT': _('Flask tissue culture'),
    'GRAF': _('Graft'),
    'GRFS': _('Grafted standard'),
    'LAYE': _('Layer'),
    'PLTP': _('Plant punnett or plug'),
    'PLNT': _('Plant tubestock'),
    'PLTS': _('Plant potted (sml)'),
    'PLTM': _('Plant potted (med)'),
    'PLTL': _('Plant potted (lrg)'),
    'PLTX': _('Plant ex-ground'),
    'PLXA': _('Plant advanced ex-Ground'),
    'PLTO': _('Plant other'),
    'PSBU': _('Pseudobulb'),
    'RHIZ': _('Rhizome'),
    'RCUT': _('Rooted cutting'),
    'ROOC': _('Root cutting'),
    'SCKR': _('Root sucker'),
    'ROOT': _('Root'),
    'SEED': _('Seed'),
    'SEDL': _('Seedling'),
    'SCIO': _('Scion'),
    'SPOR': _('Spore'),
    'SPRL': _('Sporeling'),
    'TUBE': _('Tuber'),
    'UNKN': _('Unknown'),
    'URCU': _('Unrooted cutting'),
    'VEGS': _('Vegetative spreading'),
    None: ''
}

# no matter how they are recieved they are all are likely to become plants at
# some point
accession_type_to_plant_material = {
    'ALAY': 'Plant',
    'BBPL': 'Plant',
    'BRPL': 'Plant',
    'BUDC': 'Plant',
    'BUDD': 'Plant',
    'BULB': 'Vegetative',
    'CLUM': 'Plant',
    'CORM': 'Vegetative',
    'DIVI': 'Plant',
    'GRAF': 'Plant',
    'GRFS': 'Plant',
    'LAYE': 'Plant',
    'FLAS': 'Tissue',
    'FLAT': 'Tissue',
    'SEED': 'Seed',
    'SEDL': 'Plant',
    'PLTP': 'Plant',
    'PLNT': 'Plant',
    'PLTS': 'Plant',
    'PLTM': 'Plant',
    'PLTL': 'Plant',
    'PLTX': 'Plant',
    'PLXA': 'Plant',
    'PSBU': 'Plant',
    'RCUT': 'Plant',
    'RHIZ': 'Vegetative',
    'ROOC': 'Plant',
    'ROOT': 'Vegetative',
    'SCIO': 'Vegetative',
    'SPOR': 'Seed',
    'SPRL': 'Plant',
    'TUBE': 'Vegetative',
    'UNKN': 'Other',
    'URCU': 'Vegetative',
    'BBIL': 'Vegetative',
    'VEGS': 'Plant',
    'SCKR': 'Plant',
    None: None
}


def compute_serializable_fields(_cls, session, keys):
    result = {'accession': None}

    acc_keys = {}
    acc_keys.update(keys)
    acc_keys['code'] = keys['accession']
    accession = Accession.retrieve_or_create(
        session, acc_keys, create=(
            'taxon' in acc_keys and 'rank' in acc_keys))

    result['accession'] = accession

    return result


AccessionNote = db.make_note_class('Accession', compute_serializable_fields)


class Accession(db.Base, db.Serializable, db.WithNotes):
    """
    :Table name: accession

    :Columns:
        *code*: :class:`sqlalchemy.types.Unicode`
            the accession code

        *prov_type*: :class:`bauble.types.Enum`
            the provenance type

            Possible values:
                * first column of prov_type_values

        *wild_prov_status*:  :class:`bauble.types.Enum`
            this column can be used to give more provenance
            information

            Possible values:
                * union of first columns of wild_prov_status_values,

        *date_accd*: :class:`bauble.types.Date`
            the date this accession was accessioned

        *id_qual*: :class:`bauble.types.Enum`
            The id qualifier is used to indicate uncertainty in the
            identification of this accession

            Possible values:
                * aff. - affinity with
                * cf. - compare with
                * forsan - perhaps
                * near - close to
                * ? - questionable
                * incorrect

        *id_qual_rank*: :class:`sqlalchemy.types.Unicode`
            The rank of the species that the id_qaul refers to.

        *private*: :class:`bauble.btypes.Boolean`
            Flag to indicate where this information is sensitive and
            should be kept private

        *species_id*: :class:`sqlalchemy.types.Integer()`
            foreign key to the species table

    :Properties:
        *species*:
            the species this accession refers to

        *source*:
            source is a relation to a Source instance

        *plants*:
            a list of plants related to this accession

        *verifications*:
            a list of verifications on the identification of this accession

    :Constraints:
    """
    __tablename__ = 'accession'

    # columns
    #: the accession code
    code = Column(Unicode(20), nullable=False, unique=True)

    code_format = BAUBLE_ACC_CODE_FORMAT
    """The default format for Accession.code field, change to use another
    format.
    """

    prov_type = Column(types.Enum(values=[i[0] for i in prov_type_values],
                                  translations=dict(prov_type_values)),
                       default=None)

    wild_prov_status = Column(
        types.Enum(values=[i[0] for i in wild_prov_status_values],
                   translations=dict(wild_prov_status_values)),
        default=None)

    date_accd = Column(types.Date)
    date_recvd = Column(types.Date)
    quantity_recvd = Column(Integer, autoincrement=False)
    recvd_type = Column(types.Enum(values=list(recvd_type_values.keys()),
                                   translations=recvd_type_values),
                        default=None)

    # ITF2 - C24 - Rank Qualified Flag - Transfer code: rkql
    # B: Below Family; F: Family; G: Genus; S: Species; I: first
    # Infraspecific Epithet; J: second Infraspecific Epithet; C: Cultivar;
    id_qual_rank = Column(Unicode(10))

    # ITF2 - C25 - Identification Qualifier - Transfer code: idql
    id_qual = Column(types.Enum(values=['aff.', 'cf.', 'incorrect',
                                        'forsan', 'near', '?', None]),
                     default=None)

    private = Column(types.Boolean, default=False)

    species_id = Column(Integer, ForeignKey('species.id'), nullable=False)

    # use backref not back_populates here to avoid InvalidRequestError in
    # view.multiproc_counter
    species = relationship('Species', uselist=False,
                           backref=backref('accessions',
                                           cascade='all, delete-orphan'))

    # intended location
    intended_location_id = Column(Integer, ForeignKey('location.id'))
    intended_location = relationship(
        'Location', primaryjoin='Accession.intended_location_id==Location.id'
    )

    intended2_location_id = Column(Integer, ForeignKey('location.id'))
    intended2_location = relationship(
        'Location', primaryjoin='Accession.intended2_location_id==Location.id'
    )

    source = relationship('Source', uselist=False,
                          cascade='all, delete-orphan',
                          back_populates='accession')

    # use Plant.code for the order_by to avoid ambiguous column names
    plants = relationship('Plant', cascade='all, delete-orphan',
                          back_populates='accession')

    verifications = relationship('Verification', order_by='Verification.date',
                                 cascade='all, delete-orphan')

    vouchers = relationship('Voucher', cascade='all, delete-orphan',
                            back_populates='accession')

    retrieve_cols = ['id', 'code']

    @classmethod
    def retrieve(cls, session, keys):
        parts = {k: v for k, v in keys.items() if k in cls.retrieve_cols}

        if parts:
            return session.query(cls).filter_by(**parts).one_or_none()
        return None

    @validates('code')
    def validate_stripping(self, _key, value):  # pylint: disable=no-self-use
        if value is None:
            return None
        return value.strip()

    @classmethod
    def get_next_code(cls, code_format=None):
        """Return the next available accession code.

        the format is stored in the `bauble` table.
        the format may contain a %PD, replaced by the plant delimiter.
        date formatting is applied.

        If there is an error getting the next code None is returned.
        """
        # auto generate/increment the accession code
        session = db.Session()
        if code_format is None:
            code_format = cls.code_format
        frmt = code_format.replace('%PD', Plant.get_delimiter())
        today = datetime.date.today()
        if match := re.match(r"%\{Y-(\d+)\}", frmt):
            frmt = frmt.replace(match.group(0),
                                str(today.year - int(match.group(1))))
        frmt = today.strftime(frmt)
        start = str(frmt.rstrip('#'))
        if start == frmt:
            # fixed value
            return start
        digits = len(frmt) - len(start)
        frmt = f"{start}%0{digits}d"
        query = (session.query(Accession.code)
                 .filter(Accession.code.startswith(start)))
        nxt = None
        try:
            if query.count() > 0:
                codes = [safe_int(row[0][len(start):]) for row in query]
                nxt = frmt % (max(codes) + 1)
            else:
                nxt = frmt % 1
        except Exception as e:  # pylint: disable=broad-except
            logger.debug("%s(%s)", type(e).__name__, e)
        finally:
            session.close()
        return str(nxt)

    def search_view_markup_pair(self):
        """provide the two lines describing object for SearchView row."""
        sp_str = self.species_str(markup=True)
        if self.active:
            markup = utils.xml_safe(str(self))
            suffix = _("%(1)s plant groups in %(2)s location(s)") % {
                '1': len(set(self.plants)),
                '2': len(set(p.location for p in self.plants))
            }
            suffix = ('<span foreground="#555555" size="small" '
                      f'weight="light"> - {suffix}</span>')
            return markup + suffix, sp_str
        if self.plants:  # dead
            color = "#9900ff"
            markup = (
                f'<span foreground="{color}">{utils.xml_safe(self)}</span>'
            )
        else:  # unused
            markup = utils.xml_safe(str(self))
        return markup, sp_str

    @property
    def parent_plant(self):
        try:
            return self.source.plant_propagation.plant
        except AttributeError:
            return None

    @property
    def propagations(self):
        import operator
        return reduce(operator.add, [p.propagations for p in self.plants], [])

    @property
    def pictures(self):
        import operator
        return reduce(operator.add, [p.pictures for p in self.plants], [])

    @hybrid_property
    def active(self):
        """False when all plants have 0 quantity (e.g. all plants have died,
        deaccessioned)
        """
        if not self.plants:
            return True
        for plant in self.plants:
            if plant.active:
                return True
        return False

    @active.expression
    def active(cls):
        # pylint: disable=no-self-argument
        inactive = (select([cls.id])
                    .outerjoin(Plant)
                    .where(Plant.id.is_not(None))
                    .group_by(cls.id)
                    .having(func.sum(Plant.quantity) == 0)
                    .scalar_subquery())
        return cast(case([(cls.id.in_(inactive), 0)], else_=1),
                    types.Boolean)

    def __str__(self):
        return str(self.code)

    def species_str(self, authors=False, markup=False):
        """Return the string of the species with the id qualifier(id_qual)
        injected into the proper place.
        """
        if not self.species:
            return None

        # show a warning if the id_qual is aff. or cf. but the id_qual_rank is
        # None, but only show it once. (NOTE __init__ is not called)
        # pylint: disable=attribute-defined-outside-init
        try:
            self._warned_about_id_qual
        except AttributeError:
            self._warned_about_id_qual = False

        if (self.id_qual in ('aff.', 'cf.') and not self.id_qual_rank and
                not self._warned_about_id_qual):
            msg = _('If the id_qual is aff. or cf. '
                    'then id_qual_rank is required. %s ') % self.code
            logger.warning(msg)
            self._warned_about_id_qual = True

        if self.id_qual:
            sp_str = self.species.str(
                authors, markup, remove_zws=True,
                qualification=(self.id_qual_rank, self.id_qual))
        else:
            sp_str = self.species.str(authors, markup, remove_zws=True)

        return sp_str

    def markup(self):
        return f'{self.code} ({self.species.markup() if self.species else ""})'

    def as_dict(self):
        result = db.Serializable.as_dict(self)
        result['species'] = self.species.str(remove_zws=True, authors=False)
        if self.source and self.source.source_detail:
            result['contact'] = self.source.source_detail.name
        return result

    @classmethod
    def correct_field_names(cls, keys):
        for internal, exchange in [('species', 'taxon')]:
            if exchange in keys:
                keys[internal] = keys[exchange]
                del keys[exchange]

    @classmethod
    def compute_serializable_fields(cls, session, keys):
        logger.debug('compute_serializable_fields(session, %s)', keys)
        result = {'species': None}
        keys = dict(keys)  # make copy
        if 'species' in keys:
            keys['taxon'] = keys['species']
            keys['rank'] = 'species'
        if 'rank' in keys and 'taxon' in keys:
            # now we must connect the accession to the species it refers to
            if keys['rank'] == 'species':
                # this can only handle a binomial it would seem
                genus_name, epithet = keys['taxon'].split(' ', 1)
                sp_dict = {'ht-epithet': genus_name,
                           'epithet': epithet}
                # NOTE insert the infrasp parts if they are present issue is we
                # will need an exact match for it to work when trying to match.
                _parts = {
                    'genus',
                    'sp',
                    'hybrid',
                    'infrasp1',
                    'infrasp1_rank',
                    'infrasp2',
                    'infrasp2_rank',
                    'infrasp3',
                    'infrasp3_rank',
                    'infrasp4',
                    'infrasp4_rank'
                }
                sp_parts = {key: keys[key] for key in
                            _parts.intersection(list(keys.keys()))}
                sp_dict.update(sp_parts)
                # if have details for the species parts updating with epithet
                # is likely to just breaks things
                if any(part in sp_dict for part in _parts):
                    result['species'] = Species.retrieve_or_create(
                        session, sp_dict, create=False, update=False)
                else:
                    result['species'] = Species.retrieve_or_create(
                        session, sp_dict, create=False)
            # NOTE <rd> the rest of this is of no consequence to me as it
            # refers to attaching an accession to a higher rank (genus or
            # family) which we never do
            elif keys['rank'] == 'genus':
                result['species'] = Species.retrieve_or_create(
                    session, {'ht-epithet': keys['taxon'],
                              'epithet': 'sp'})
            elif keys['rank'] == 'familia':
                unknown_genus = 'Zzz-' + keys['taxon'][:-1]
                Genus.retrieve_or_create(
                    session, {'ht-epithet': keys['taxon'],
                              'epithet': unknown_genus})
                result['species'] = Species.retrieve_or_create(
                    session, {'ht-epithet': unknown_genus,
                              'epithet': 'sp'})
            logger.debug('compute_serializable_fields results = %s', result)
        return result

    def top_level_count(self):
        source = self.source.source_detail if self.source else None
        plants = db.get_active_children('plants', self)
        return {(1, 'Accessions'): 1,
                (2, 'Species'): set([self.species.id]),
                (3, 'Genera'): set([self.species.genus.id]),
                (4, 'Families'): set([self.species.genus.family.id]),
                (5, 'Plantings'): len(plants),
                (6, 'Living plants'): sum(p.quantity for p in plants),
                (7, 'Locations'): set(p.location.id for p in plants),
                (8, 'Sources'): set([source.id] if source else [])}

    def has_children(self):
        cls = self.__class__.plants.prop.mapper.class_
        session = object_session(self)
        return session.query(
            exists().where(cls.accession_id == self.id)
        ).scalar()

    def count_children(self):
        cls = self.__class__.plants.prop.mapper.class_
        session = object_session(self)
        query = session.query(cls.id).filter(cls.accession_id == self.id)
        if prefs.prefs.get(prefs.exclude_inactive_pref):
            query = query.filter(cls.active.is_(True))
        return query.count()


# late import after Accession is defined
from .plant import Plant, PlantEditor


class AccessionEditorView(editor.GenericEditorView):
    """AccessionEditorView provides the view part of the model/view/presenter
    paradigm.  It also acts as the view for any child presenter contained
    within the AccessionEditorPresenter.

    The primary function of the view is setup an parts of the
    interface that don't chage due to user interaction.  Although it
    also provides some utility methods for changing widget states.
    """
    expanders_pref_map = {
        # 'acc_notes_expander': 'editor.accession.notes.expanded',
        # 'acc_source_expander': 'editor.accession.source.expanded'
    }

    _tooltips = {
        'acc_species_entry': _(
            "The species must be selected from the list of completions. "
            "To add a species use the Species editor."),
        'acc_code_entry': _("The accession ID must be a unique code.  This is "
                            "usually set by auto incrementing the next "
                            "available code as described by the current ID "
                            "format"),
        'acc_id_qual_combo': _("The identification qualifier. i.e. indicates "
                               "a degree of uncertanty for the "
                               "identification of the accession."),
        'acc_id_qual_rank_combo': _('The part of the taxon name that the '
                                    'identification qualifier refers to.'),
        'acc_date_accd_entry': _('The date this species was accessioned.'),
        'acc_date_recvd_entry': _('The date this species was received.'),
        'acc_recvd_type_comboentry': _(
            'The type of the accessioned material.'),
        'acc_quantity_recvd_entry': _('The amount of plant material at the '
                                      'time it was accessioned.'),
        'intended_loc_comboentry': _('The intended location for plant '
                                     'material being accessioned.'),
        'intended2_loc_comboentry': _('The intended location for plant '
                                      'material being accessioned.'),
        'intended_loc_create_plant_checkbutton': _(
            'Immediately create a plant at this location, using all plant '
            'material.'
        ),

        'acc_prov_combo': _('The origin or source of this accession.'),
        'acc_wild_prov_combo': _('The wild status is used to clarify the '
                                 'provenance of wild source only.\n\n'
                                 '"Wild/Cultivated" refers to the collection '
                                 'site, "native/non-native" refers to the '
                                 'housing facility.\n\n"Wild" = naturally '
                                 'wild populations,\n\n"Cultivated" = '
                                 'populations that are known to have been '
                                 're-introduced or translocated (e.g. '
                                 'regeneration activities etc.)\n\n'
                                 '"Native/non-native" meaning the housing '
                                 'facility is within the species` indigenous '
                                 'range or not.'),
        'acc_private_check': _('Indicates whether this accession record '
                               'should be considered private.'),
        'acc_cancel_button': _('Cancel your changes.'),
        'acc_ok_button': _('Save your changes.'),
        'acc_ok_and_add_button': _('Save your changes and add a '
                                   'plant to this accession.'),
        'acc_next_button': _('Save your changes and add another '
                             'accession.'),

        'sources_code_entry': _("ITF2 - E7 - Donor's Accession Identifier - "
                                "donacc"),
        'acc_code_format_comboentry': _('Set the format for the Accession ID '
                                        'code generally you will not need to '
                                        'set this unless you do not want to '
                                        'use you do not want to use the '
                                        'system default.'),
        'acc_code_format_edit_btn': _("Click here to edit or add to the "
                                      "avialable ID formats."),
        'source_prop_plant_entry': _('Type a plant code or species name here '
                                     'to narrow the selections below.'),
        'source_type_combo': _('Select a type to filter by or leave blank to '
                               'select by name only.\n"Contacts (General)" '
                               'filters out Expedtions and Garden '
                               'Propagation.')
    }

    def __init__(self, parent=None):
        glade_file = os.path.join(paths.lib_dir(),
                                  'plugins',
                                  'garden',
                                  'acc_editor.glade')
        super().__init__(glade_file, parent=parent,
                         root_widget_name='accession_dialog')
        self.attach_completion('acc_species_entry',
                               cell_data_func=species_cell_data_func,
                               match_func=species_match_func)
        self.set_accept_buttons_sensitive(False)
        self.restore_state()

        # TODO: at the moment this also sets up some of the view parts
        # of child presenters like the CollectionPresenter, etc.

        # datum completions
        completion = self.attach_completion('datum_entry',
                                            minimum_key_length=1,
                                            match_func=self.datum_match_func,
                                            text_column=0)
        model = Gtk.ListStore(str)
        for abbr in sorted(datums.keys()):
            # TODO: should create a marked up string with the datum description
            model.append([abbr])
        completion.set_model(model)

        self.init_translatable_combo('acc_prov_combo', prov_type_values)
        self.init_translatable_combo('acc_wild_prov_combo',
                                     wild_prov_status_values)
        self.init_translatable_combo('acc_recvd_type_comboentry',
                                     recvd_type_values)

        completion = (self.widgets.acc_recvd_type_comboentry
                      .get_child().get_completion())
        completion.set_match_func(self.acc_recvd_type_match_func)

        adjustment = self.widgets.source_sw.get_vadjustment()
        adjustment.props.value = 0.0
        self.widgets.source_sw.set_vadjustment(adjustment)

        # set current page so we don't open the last one that was open
        self.widgets.notebook.set_current_page(0)

    def get_window(self):
        return self.widgets.accession_dialog

    def set_accept_buttons_sensitive(self, sensitive):
        """set the sensitivity of all the accept/ok buttons for the editor
        dialog
        """
        self.widgets.acc_ok_button.set_sensitive(sensitive)
        self.widgets.acc_ok_and_add_button.set_sensitive(sensitive)
        self.widgets.acc_next_button.set_sensitive(sensitive)

    def save_state(self):
        """save the current state of the gui to the preferences"""
        for expander, pref in self.expanders_pref_map.items():
            prefs.prefs[pref] = self.widgets[expander].get_expanded()

    def restore_state(self):
        """restore the state of the gui from the preferences"""
        for expander, pref in self.expanders_pref_map.items():
            expanded = prefs.prefs.get(pref, True)
            self.widgets[expander].set_expanded(expanded)

    # staticmethod ensures the AccessionEditorView gets garbage collected.
    @staticmethod
    def datum_match_func(completion, key, treeiter):
        datum = completion.get_model()[treeiter][0]
        words = datum.split(' ')
        for word in words:
            if word.lower().startswith(key.lower()):
                return True
        return False

    @staticmethod
    def acc_recvd_type_match_func(completion, key, treeiter):
        model = completion.get_model()
        value = model[treeiter][1]
        # allows completion via any matching part
        if key.lower() in str(value).lower():
            return True
        return False


class VoucherPresenter(editor.GenericEditorPresenter):

    def __init__(self, parent, model, view, session):
        super().__init__(model, view, session=session, connect_signals=False)
        self.parent_ref = weakref.ref(parent)
        self._dirty = False
        self.view.connect('voucher_add_button', 'clicked', self.on_add_clicked)
        self.view.connect('voucher_remove_button', 'clicked',
                          self.on_remove_clicked)
        self.view.connect('parent_voucher_add_button', 'clicked',
                          self.on_add_clicked, True)
        self.view.connect('parent_voucher_remove_button', 'clicked',
                          self.on_remove_clicked, True)

        self.setup_column('voucher_treeview', 'voucher_herb_column',
                          'voucher_herb_cell', 'herbarium')
        self.setup_column('voucher_treeview', 'voucher_code_column',
                          'voucher_code_cell', 'code')

        self.setup_column('parent_voucher_treeview',
                          'parent_voucher_herb_column',
                          'parent_voucher_herb_cell',
                          'herbarium')
        self.setup_column('parent_voucher_treeview',
                          'parent_voucher_code_column',
                          'parent_voucher_code_cell',
                          'code')

        # intialize vouchers treeview
        treeview = self.view.widgets.voucher_treeview
        utils.clear_model(treeview)
        model = Gtk.ListStore(object)
        for voucher in self.model.vouchers:
            if not voucher.parent_material:
                model.append([voucher])
        treeview.set_model(model)

        # initialize parent vouchers treeview
        treeview = self.view.widgets.parent_voucher_treeview
        utils.clear_model(treeview)
        model = Gtk.ListStore(object)
        for voucher in self.model.vouchers:
            if voucher.parent_material:
                model.append([voucher])
        treeview.set_model(model)

    @staticmethod
    def _voucher_data_func(_column, cell, model, treeiter, prop):
        voucher = model[treeiter][0]
        cell.set_property('text', getattr(voucher, prop))

    def setup_column(self, tree, column, cell, prop):
        column = self.view.widgets[column]
        cell = self.view.widgets[cell]
        column.clear_attributes(cell)  # get rid of some warnings
        cell.props.editable = True
        self.view.connect(cell, 'edited', self.on_cell_edited, (tree, prop))
        column.set_cell_data_func(cell, self._voucher_data_func, prop)

    def is_dirty(self):
        return self._dirty

    def on_cell_edited(self, _cell, path, new_text, data):
        treeview, prop = data
        treemodel = self.view.widgets[treeview].get_model()
        voucher = treemodel[path][0]
        if getattr(voucher, prop) == new_text:
            return  # didn't change
        setattr(voucher, prop, utils.nstr(new_text))
        self._dirty = True
        self.parent_ref().refresh_sensitivity()

    def on_remove_clicked(self, _button, parent=False):
        if parent:
            treeview = self.view.widgets.parent_voucher_treeview
        else:
            treeview = self.view.widgets.voucher_treeview
        model, treeiter = treeview.get_selection().get_selected()
        voucher = model[treeiter][0]
        voucher.accession = None
        model.remove(treeiter)
        self._dirty = True
        self.parent_ref().refresh_sensitivity()

    def on_add_clicked(self, _button, parent=False):
        if parent:
            treeview = self.view.widgets.parent_voucher_treeview
        else:
            treeview = self.view.widgets.voucher_treeview
        voucher = Voucher()
        voucher.accession = self.model
        voucher.parent_material = parent
        model = treeview.get_model()
        treeiter = model.insert(0, [voucher])
        path = model.get_path(treeiter)
        column = treeview.get_column(0)
        treeview.set_cursor(path, column, start_editing=True)


def species_comparer(row, string):
    return species_to_string_matcher(row[0], string)


@Gtk.Template(filename=str(Path(__file__).resolve().parent /
                           'acc_ver_box.glade'))
class VerificationBox(Gtk.Box):

    __gtype_name__ = 'VerificationBox'

    verifier_entry = Gtk.Template.Child()
    date_entry = Gtk.Template.Child()
    ref_entry = Gtk.Template.Child()
    prev_taxon_entry = Gtk.Template.Child()
    new_taxon_entry = Gtk.Template.Child()
    level_combo = Gtk.Template.Child()
    date_button = Gtk.Template.Child()
    taxon_add_button = Gtk.Template.Child()
    notes_textview = Gtk.Template.Child()
    remove_button = Gtk.Template.Child()
    use_taxon_button = Gtk.Template.Child()
    expander_label = Gtk.Template.Child()
    ver_expander = Gtk.Template.Child()

    def __init__(self, parent, model):
        super().__init__()
        check(not model or isinstance(model, Verification))

        self.presenter = weakref.ref(parent)
        self.model = model
        self.new = False
        if not self.model:
            self.model = Verification()
            self.new = True
            self.model.prev_species = self.presenter().model.species
            utils.set_widget_value(self.date_entry, datetime.date.today())

        if self.model.verifier:
            self.verifier_entry.set_text(self.model.verifier)

        self.presenter().view.connect(self.verifier_entry, 'changed',
                                      self.on_entry_changed, 'verifier')

        if self.model.date:
            utils.set_widget_value(self.date_entry, self.model.date)

        utils.setup_date_button(self.presenter().view, self.date_entry,
                                self.date_button)

        self.presenter().view.connect(self.date_entry,
                                      'changed',
                                      self.presenter().on_date_entry_changed,
                                      (self.model, 'date'))

        # reference entry
        if self.model.reference:
            self.ref_entry.set_text(self.model.reference)

        self.presenter().view.connect(self.ref_entry, 'changed',
                                      self.on_entry_changed, 'reference')

        self.presenter().view.attach_completion(
            self.prev_taxon_entry,
            cell_data_func=species_cell_data_func,
            match_func=species_match_func
        )
        if self.model.prev_species:
            self.prev_taxon_entry.set_text(str(self.model.prev_species))

        sp_get_completions = partial(generic_sp_get_completions,
                                     self.presenter().session)

        on_prev_sp_select = partial(self.on_sp_select, attr='prev_species')

        self.presenter().assign_completions_handler(self.prev_taxon_entry,
                                                    sp_get_completions,
                                                    on_prev_sp_select,
                                                    comparer=species_comparer)

        self.presenter().view.attach_completion(
            self.new_taxon_entry,
            cell_data_func=species_cell_data_func,
            match_func=species_match_func
        )
        if self.model.species:
            self.new_taxon_entry.set_text(self.model.species.str())

        self.presenter().assign_completions_handler(self.new_taxon_entry,
                                                    sp_get_completions,
                                                    self.on_sp_select,
                                                    comparer=species_comparer)

        # adding a taxon implies setting the new_taxon_entry
        self.presenter().view.connect(self.taxon_add_button,
                                      'clicked',
                                      self.on_taxon_add_button_clicked,
                                      self.new_taxon_entry)

        # these seem like reasonable defaults but could auto calculate with
        # size_allocate handler if they prove not to be.
        renderer = Gtk.CellRendererText(wrap_mode=Pango.WrapMode.WORD,
                                        wrap_width=400, width_chars=90)

        self.level_combo.pack_start(renderer, True)

        self.level_combo.set_cell_data_func(renderer,
                                            self.level_cell_data_func)
        model = Gtk.ListStore(int, str)
        for level, descr in ver_level_descriptions.items():
            model.append([level, descr])
        self.level_combo.set_model(model)
        if self.model.level is not None:
            utils.set_widget_value(self.level_combo, self.model.level)
        self.presenter().view.connect(self.level_combo, 'changed',
                                      self.on_level_combo_changed)

        # notes text view
        self.notes_textview.set_border_width(1)
        buff = Gtk.TextBuffer()
        if self.model.notes:
            buff.set_text(self.model.notes)
        self.notes_textview.set_buffer(buff)
        self.presenter().view.connect(buff, 'changed',
                                      self.on_entry_changed, 'notes')

        # remove button
        self.presenter().view.connect(self.remove_button, 'clicked',
                                      self.on_remove_button_clicked)

        # copy to general tab
        self.use_taxon_button.set_tooltip_text(
            "Set this accession's species to this verifications new taxon."
        )
        self.presenter().view.connect(self.use_taxon_button, 'clicked',
                                      self.on_copy_to_taxon_general_clicked)

        self.update_label()

    @staticmethod
    def level_cell_data_func(_col, cell, model, treeiter):
        level = model[treeiter][0]
        descr = model[treeiter][1]
        cell.set_property('markup', f'<b>{level}</b>  :  {descr}')

    def on_sp_select(self, value, attr='species'):
        # only set attr if is a species, i.e. not str (Avoids the first 2
        # letters prior to the completions handler kicking in.)
        if isinstance(value, Species):
            self.set_model_attr(attr, value)

    def on_copy_to_taxon_general_clicked(self, _button):
        """Copy the selected verification's 'new taxon' into the parent
        species editor.

        Sets the accession editor into the same state it would be in if the
        species entry's EntryCompletion had emitted 'matched' without the
        complexity required to do so.

        .. note:
            avoids the issue of the 'match-selected' signal not being
            emitted by :func:`editor.assign_completions_handler.on_changed`
            due to more than one potential matches (i.e. the species name
            and a cultivar or other infraspecific level of the species both
            exist and the desire is to match the species.)
        """
        if self.model.species is None:
            logger.debug('no species to copy')
            return
        msg = _("Are you sure you want to copy this verification to the "
                "general taxon?")
        if not utils.yes_no_dialog(msg):
            return
        # copy verification species to general tab
        if self.model.accession:
            parent = self.presenter().parent_ref()

            # set the entry text.
            acc_species_entry = parent.view.widgets.acc_species_entry
            logger.debug('setting species from %s to verification %s',
                         acc_species_entry.get_text(), self.model.species)
            acc_species_entry.set_text(self.model.species.str())

            # set the model value
            parent.model.species = self.model.species

            # make the presenter ready to commit the change
            self.presenter()._dirty = True
            self.presenter().parent_ref().refresh_sensitivity()

    def on_remove_button_clicked(self, _button):
        parent = self.get_parent()
        msg = _("Are you sure you want to remove this verification?")
        if not utils.yes_no_dialog(msg):
            return
        if parent:
            parent.remove(self)

        # remove verification from accession
        if self.model.accession:
            self.model.accession.verifications.remove(self.model)
        if not self.new:
            self.presenter()._dirty = True
        self.presenter().parent_ref().refresh_sensitivity()

    def on_entry_changed(self, entry, attr):
        # Don't use entry.get_text() here, fails for notes TextBuffer
        text = entry.get_property('text').strip()
        if not text:
            self.set_model_attr(attr, None)
        else:
            self.set_model_attr(attr, text)

    def on_level_combo_changed(self, combo):
        itr = combo.get_active_iter()
        level = combo.get_model()[itr][0]
        self.set_model_attr('level', level)

    def set_model_attr(self, attr, value):
        setattr(self.model, attr, value)
        if attr != 'date' and not self.model.date:
            # When we create a new verification box we set today's date
            # in the GtkEntry but not in the model so the presenter
            # doesn't appear dirty.  Now that the user is setting
            # something, we trigger the 'changed' signal on the 'date'
            # entry as well, by first clearing the entry then setting it
            # to its intended value.
            tmp = self.date_entry.get_text()
            self.date_entry.set_text('')
            self.date_entry.set_text(tmp)
        # if the verification isn't yet associated with an accession
        # then set the accession when we start changing values, this way
        # we can setup a dummy verification in the interface
        if not self.model.accession:
            self.model.accession = self.presenter().model
            logger.debug('set model accession to %s', self.model.accession)
            # self.presenter().model.verifications.append(self.model)
        self.presenter()._dirty = True
        self.update_label()
        self.presenter().parent_ref().refresh_sensitivity()

    def update_label(self):
        parts = []
        sp_markup = ''
        if self.model.date:
            parts.append('<b>%(date)s</b> : ')
        if self.model.species:
            parts.append(_('verified as %(species)s '))
            sp_markup = self.model.species.markup()
        if self.model.verifier:
            parts.append(_('by %(verifier)s'))
        label = ' '.join(parts) % dict(date=self.model.date,
                                       species=sp_markup,
                                       verifier=self.model.verifier)
        self.expander_label.set_markup(label)

    def set_expanded(self, expanded):
        self.ver_expander.set_expanded(expanded)

    def on_taxon_add_button_clicked(self, _button, taxon_entry):
        # we come here when adding a Verification, and the
        # Verification wants to refer to a new taxon.
        generic_taxon_add_action(
            self.model, self.presenter().view, self.presenter(),
            self.presenter().parent_ref(), taxon_entry
        )


class VerificationPresenter(editor.GenericEditorPresenter):
    """VerificationPresenter

    :param parent:
    :param model:
    :param view:
    :param session:
    """

    def __init__(self, parent, model, view, session):
        super().__init__(model, view, session=session, connect_signals=False)
        self.parent_ref = weakref.ref(parent)
        self.view.connect('ver_add_button', 'clicked', self.on_add_clicked)

        # remove any verification boxes that would have been added to
        # the widget in a previous run
        box = self.view.widgets.verifications_parent_box
        for child in box.get_children():
            box.remove(child)

        # order by date of the existing verifications
        for ver in model.verifications:
            expander = self.add_verification_box(model=ver)
            expander.set_expanded(False)  # all are collapsed to start

        # if no verifications were added then add an empty VerificationBox
        if len(self.view.widgets.verifications_parent_box.get_children()) < 1:
            self.add_verification_box()

        # expand the first verification expander
        first = self.view.widgets.verifications_parent_box.get_children()[0]
        first.set_expanded(True)
        self._dirty = False

    def is_dirty(self):
        return self._dirty

    def refresh_view(self):
        pass

    def on_add_clicked(self, _button):
        self.add_verification_box()

    def add_verification_box(self, model=None):
        """
        :param model:
        """
        box = VerificationBox(self, model)
        parent_box = self.view.widgets.verifications_parent_box
        parent_box.pack_start(box, False, False, 0)
        parent_box.reorder_child(box, 0)
        box.show_all()
        return box


class SourcePresenter(editor.GenericEditorPresenter):
    """SourcePresenter

    :param parent: AccessionEditorPresenter
    :param model: Accession
    :param view: AccessionEditorView
    :param session: db.Session()
    """
    # pylint: disable=too-many-instance-attributes

    GARDEN_PROP_STR = _('Garden Propagation')
    PROBLEM_UNKOWN_SOURCE = f'unknown_source:{random()}'

    def __init__(self, parent, model, view, session):
        super().__init__(model, view, session=session, connect_signals=False)
        self.parent_ref = weakref.ref(parent)
        self._dirty = False

        self.view.connect('new_source_button', 'clicked',
                          self.on_new_source_button_clicked)

        utils.hide_widgets([self.view.widgets.source_garden_prop_box,
                            self.view.widgets.source_sw])
        self.view.widgets.source_none_label.set_visible(True)

        # populate the source combo
        self.init_source_comboentry(self.on_source_select)

        if self.model.source:
            self.source = self.model.source
            self.view.widgets.sources_code_entry.set_text(
                self.source.sources_code or '')
        else:
            self.source = Source()
            self.view.widgets.sources_code_entry.set_text('')

        if self.source.collection:
            self.collection = self.source.collection
            enabled = True
        else:
            self.collection = Collection()
            enabled = False

        self._set_source_coll_enabled(enabled)

        if self.source.propagation:
            self.propagation = self.source.propagation
            enabled = True
        else:
            self.propagation = Propagation()
            enabled = False

        self._set_source_prop_enabled(enabled)

        # presenter that allows us to create a new Propagation that is
        # specific to this Source and not attached to any Plant
        self.source_prop_presenter = SourcePropagationPresenter(
            self, self.propagation, view, session
        )

        # presenter that allows us to select an existing propagation
        self.prop_chooser_presenter = PropagationChooserPresenter(
            self, self.source, view, session
        )

        # collection data
        self.collection_presenter = CollectionPresenter(self, self.collection,
                                                        view, session)

        self.view.connect('sources_code_entry', 'changed',
                          self.on_sources_code_changed)

        self.view.connect('source_coll_add_button', 'clicked',
                          self.on_coll_add_button_clicked)
        self.view.connect('source_coll_remove_button', 'clicked',
                          self.on_coll_remove_button_clicked)
        self.view.connect('source_prop_add_button', 'clicked',
                          self.on_prop_add_button_clicked)
        self.view.connect('source_prop_remove_button', 'clicked',
                          self.on_prop_remove_button_clicked)

        _source_types = [('garden_prop', self.GARDEN_PROP_STR),
                         ('contact', 'Contacts (General)')]
        _source_types.extend(source_type_values)
        self.view.init_translatable_combo('source_type_combo',
                                          _source_types)
        self.view.connect('source_type_combo',
                          'changed',
                          self.on_type_filter_changed)

    def _set_source_coll_enabled(self, enabled):
        self.view.widgets.source_coll_add_button.set_sensitive(not enabled)
        self.view.widgets.source_coll_remove_button.set_sensitive(enabled)
        self.view.widgets.source_coll_expander.set_expanded(enabled)
        self.view.widgets.source_coll_expander.set_sensitive(enabled)

    def _set_source_prop_enabled(self, enabled):
        self.view.widgets.source_prop_add_button.set_sensitive(not enabled)
        self.view.widgets.source_prop_remove_button.set_sensitive(enabled)
        self.view.widgets.source_prop_expander.set_expanded(enabled)
        self.view.widgets.source_prop_expander.set_sensitive(enabled)

    def on_sources_code_changed(self, entry, *_args):
        text = entry.get_text()
        if text.strip():
            self.source.sources_code = text
        else:
            self.source.sources_code = None
        self._dirty = True
        self.refresh_sensitivity()

    def on_source_select(self, source):
        if not source:
            self.source.source_detail = None
            self.model.source = None
        elif isinstance(source, SourceDetail):
            self.source.source_detail = source
            self.model.source = self.source
        elif source == self.GARDEN_PROP_STR:
            # setting the model.source to self.source happens when a
            # propagation is toggled in the PropagationChooserPresenter
            self.source.source_detail = None
            self.model.source = None
        else:
            logger.warning('unknown source: %s', source)

    def on_type_filter_changed(self, _combo):
        """Resets source_combo"""
        self.populate_source_combo()

    def all_problems(self):
        """Return a union of all the problems from this presenter and child
        presenters
        """
        return (self.problems | self.collection_presenter.problems |
                self.prop_chooser_presenter.problems |
                self.source_prop_presenter.problems)

    def cleanup(self):
        super().cleanup()
        self.collection_presenter.cleanup()
        self.prop_chooser_presenter.cleanup()
        self.source_prop_presenter.cleanup()

    def start(self):
        active = None
        if self.model.source:
            if self.model.source.source_detail:
                active = self.model.source.source_detail
            elif self.model.source.plant_propagation:
                active = self.GARDEN_PROP_STR
        self.populate_source_combo(active)

    def is_dirty(self):
        return (self._dirty or self.source_prop_presenter.is_dirty() or
                self.prop_chooser_presenter.is_dirty() or
                self.collection_presenter.is_dirty())

    def refresh_sensitivity(self):
        logger.debug('refresh_sensitivity: %s', str(self.problems))
        self.parent_ref().refresh_sensitivity()

    def on_coll_add_button_clicked(self, *_args):
        self.model.source.collection = self.collection
        self._set_source_coll_enabled(True)
        self._dirty = True
        self.refresh_sensitivity()

    def on_coll_remove_button_clicked(self, *_args):
        self.model.source.collection = None
        self._set_source_coll_enabled(False)
        # remove any problems
        self.collection_presenter.problems = set()
        self._dirty = True
        self.refresh_sensitivity()

    def on_prop_add_button_clicked(self, *_args):
        self.model.source.propagation = self.propagation
        self._set_source_prop_enabled(True)
        self._dirty = True
        self.refresh_sensitivity()

    def on_prop_remove_button_clicked(self, *_args):
        self.model.source.propagation = None
        self._set_source_prop_enabled(False)
        self._dirty = True
        self.refresh_sensitivity()

    def on_new_source_button_clicked(self, _button):
        """Opens a new SourceDetailEditor when clicked and repopulates the
        source combo if a new SourceDetail is created.
        """
        view = editor.GenericEditorView(
            str(Path(paths.lib_dir()) /
                "plugins/garden/source_detail_editor.glade"),
            parent=self.view.get_window(),
            root_widget_name='source_details_dialog')

        source = SourceDetail()
        source_type = self.view.widget_get_value('source_type_combo')
        source_types = None
        source_keys = dict(source_type_values).keys()

        if source_type:
            if source_type in source_keys:
                source_types = [source_type]
            if source_type == 'contact':
                source_types = [k for k in source_keys if k != 'Expedition']

        presenter = SourceDetailPresenter(source,
                                          view,
                                          do_commit=False,
                                          source_types=source_types,
                                          session=self.session)
        if presenter.start() == Gtk.ResponseType.OK:
            self.populate_source_combo(source, new=True)

    def populate_source_combo(self, active=None, new=False):
        """If active=None then set whatever was previously active before
        repopulating the combo.
        """
        combo = self.view.widgets.acc_source_comboentry
        if not active and (treeiter := combo.get_active_iter()):
            active = combo.get_model()[treeiter][0]
        combo.set_model(None)
        model = Gtk.ListStore(object)
        none_iter = model.append([''])
        value = self.view.widget_get_value('source_type_combo')
        new_button = self.view.widgets.new_source_button
        new_button.set_property('sensitive', True)

        if value == 'garden_prop':
            model.append([self.GARDEN_PROP_STR])
            active = self.GARDEN_PROP_STR
            query = []
            new_button.set_property('sensitive', False)
        elif value == 'contact':
            query = (self.session.query(SourceDetail)
                     .filter(SourceDetail.source_type != 'Expedition')
                     .order_by(func.lower(SourceDetail.name)))
        elif value:
            query = (self.session.query(SourceDetail)
                     .filter_by(source_type=value)
                     .order_by(func.lower(SourceDetail.name)))
        else:
            model.append([self.GARDEN_PROP_STR])
            query = (self.session.query(SourceDetail)
                     .order_by(func.lower(SourceDetail.name)))

        if new:
            model.append([active])
        else:
            # only allow triggering dirty if this has been called from adding a
            # new source detail.
            combo.populate = True

        for i in query:
            model.append([i])
        combo.set_model(model)
        combo.get_child().get_completion().set_model(model)

        if active:
            results = utils.search_tree_model(model, active)
            if results:
                combo.set_active_iter(results[0])
            else:
                combo.set_active_iter(none_iter)
        else:
            combo.set_active_iter(none_iter)
        combo.populate = False
        # any new SourceDetail is added to session by now

    def init_source_comboentry(self, on_select):
        """A comboentry that allows the source to be entered.

        Requires more custom setup than attach_completion and
        assign_simple_handler can provide.

        This method:
            - allows setting which widget is visible below.
            - allows completion matching by any part of the source string.
            - allows match selection by source name or string ignoring case.
            - avoids dirtying the presenter on population.

        :param on_select: called when an item is selected
        """

        def cell_data_func(_col, cell, model, treeiter):
            cell.props.text = str(model[treeiter][0])

        combo = self.view.widgets.acc_source_comboentry
        combo.clear()
        cell = Gtk.CellRendererText()
        combo.pack_start(cell, True)
        combo.set_cell_data_func(cell, cell_data_func)

        completion = Gtk.EntryCompletion()
        cell = Gtk.CellRendererText()  # set up the completion renderer
        completion.pack_start(cell, True)
        completion.set_cell_data_func(cell, cell_data_func)

        completion.set_match_func(self.source_match_func)

        self.source_entry = combo.get_child()
        self.source_entry.set_completion(completion)

        def on_match_select(_completion, model, treeiter):
            value = model[treeiter][0]
            # TODO: should we reset/store the entry values if the source is
            # changed and restore them if they are switched back?
            if not value:
                self.source_entry.set_text('')
                on_select(None)
            else:
                self.source_entry.set_text(str(value))
                on_select(value)

            # don't set the model as dirty if this is called during
            # populate_source_combo (unless due to a new source added)
            if not combo.populate:
                self._dirty = True
                self.refresh_sensitivity()
            return True

        self.view.connect(completion, 'match-selected', on_match_select)

        self.view.connect(self.source_entry, 'changed',
                          self.on_source_entry_changed)

        self.view.connect(combo, 'changed', self.on_source_combo_changed)

        self.view.connect(combo, 'format-entry-text',
                          utils.format_combo_entry_text)

    def on_source_entry_changed(self, entry):
        text = entry.get_text()
        # see if the text matches a completion string
        comp = entry.get_completion()

        def _cmp(row, data):
            if str(row[0]).lower() == data.lower():
                return True
            if hasattr(row[0], 'name'):
                return row[0].name.lower() == data.lower()
            return False

        found = utils.search_tree_model(comp.get_model(), text, cmp=_cmp)

        if len(found) == 1:
            # the model and iter here should technically be the tree
            comp.emit('match-selected', comp.get_model(), found[0])
            self.remove_problem(self.PROBLEM_UNKOWN_SOURCE, entry)
        else:
            self.add_problem(self.PROBLEM_UNKOWN_SOURCE, entry)
        self.update_visible()
        self.refresh_sensitivity()
        return True

    @staticmethod
    def source_match_func(completion, key, treeiter):
        model = completion.get_model()
        value = model[treeiter][0]
        # allows completion via any matching part
        if key.lower() in str(value).lower():
            return True
        return False

    def on_source_combo_changed(self, combo, *_args):
        active = combo.get_active_iter()
        if active:
            detail = combo.get_model()[active][0]
            # set the text value on the entry since it does all the
            # validation
            if not detail:
                combo.get_child().set_text('')
            else:
                combo.get_child().set_text(str(detail))
        self.update_visible()
        return True

    def update_visible(self):
        widget_visibility = dict(source_sw=False,
                                 source_garden_prop_box=False,
                                 source_none_label=False)
        if self.source_entry.get_text() == self.GARDEN_PROP_STR:
            widget_visibility['source_garden_prop_box'] = True
        elif not self.model.source or not self.model.source.source_detail:
            widget_visibility['source_none_label'] = True
        else:
            widget_visibility['source_sw'] = True
        for widget, value in widget_visibility.items():
            self.view.widgets[widget].set_visible(value)
        self.view.widgets.source_alignment.set_sensitive(True)


class AccessionEditorPresenter(editor.GenericEditorPresenter):
    # pylint: disable=too-many-instance-attributes

    widget_to_field_map = {
        'acc_code_entry': 'code',
        'acc_id_qual_combo': 'id_qual',
        'acc_date_accd_entry': 'date_accd',
        'acc_date_recvd_entry': 'date_recvd',
        'acc_recvd_type_comboentry': 'recvd_type',
        'acc_quantity_recvd_entry': 'quantity_recvd',
        'intended_loc_comboentry': 'intended_location',
        'intended2_loc_comboentry': 'intended2_location',
        'acc_prov_combo': 'prov_type',
        'acc_wild_prov_combo': 'wild_prov_status',
        'acc_species_entry': 'species',
        'acc_private_check': 'private',
        'intended_loc_create_plant_checkbutton': 'create_plant',
    }

    PROBLEM_DUPLICATE_ACCESSION = f'duplicate_accession:{random()}'
    PROBLEM_ID_QUAL_RANK_REQUIRED = f'id_qual_rank_required:{random()}'
    PROBLEM_BAD_RECVD_TYPE = f'bad_recvd_type:{random()}'

    def __init__(self, model, view):
        """
        :param model: an instance of class Accession
        ;param view: an instance of AccessionEditorView
        """
        super().__init__(model, view)
        self._dirty = False
        self.session = object_session(model)
        self._original_code = self.model.code
        model.create_plant = False

        # set the default code and add it to the top of the code formats
        self.populate_code_formats(model.code or '')
        self.view.widget_set_value('acc_code_format_comboentry',
                                   model.code or '')
        if not model.code:
            model.code = model.get_next_code()
            if self.model.species:
                self._dirty = True

        self.ver_presenter = VerificationPresenter(self, self.model, self.view,
                                                   self.session)
        self.voucher_presenter = VoucherPresenter(self, self.model, self.view,
                                                  self.session)
        self.source_presenter = SourcePresenter(self, self.model, self.view,
                                                self.session)

        notes_parent = self.view.widgets.notes_parent_box
        notes_parent.foreach(notes_parent.remove)
        self.notes_presenter = editor.NotesPresenter(self, 'notes',
                                                     notes_parent)

        self.init_enum_combo('acc_id_qual_combo', 'id_qual')

        # init id_qual_rank
        utils.setup_text_combobox(self.view.widgets.acc_id_qual_rank_combo)
        self.refresh_id_qual_rank_combo()

        self.view.connect('acc_id_qual_rank_combo', 'changed',
                          self.on_id_qual_rank_changed)

        # refresh_view fires signal handlers for any connected widgets.
        # the 'initializing' field tells our callbacks not to react.
        # ComboBoxes need a model, to receive values.

        from . import init_location_comboentry

        init_location_comboentry(
            self, self.view.widgets.intended_loc_comboentry,
            partial(self.on_loc_select, 'intended_location'), required=False)
        init_location_comboentry(
            self, self.view.widgets.intended2_loc_comboentry,
            partial(self.on_loc_select, 'intended2_location'), required=False)

        # put model values in view before any handlers are connected
        self.refresh_view(initializing=True)

        # connect signals
        self.assign_completions_handler(
            'acc_species_entry',
            partial(generic_sp_get_completions, self.session),
            on_select=self.on_species_select,
            comparer=species_comparer
        )
        self.assign_simple_handler('acc_prov_combo', 'prov_type')
        self.assign_simple_handler('acc_wild_prov_combo', 'wild_prov_status')

        # connect recvd_type comboentry widget and child entry
        self.view.connect('acc_recvd_type_comboentry', 'changed',
                          self.on_recvd_type_comboentry_changed)
        self.view.connect(
            self.view.widgets.acc_recvd_type_comboentry.get_child(),
            'changed', self.on_recvd_type_entry_changed
        )

        self.view.connect('acc_code_entry', 'changed',
                          self.on_acc_code_entry_changed)

        # date received
        self.view.connect('acc_date_recvd_entry', 'changed',
                          self.on_date_entry_changed,
                          (self.model, 'date_recvd'))
        utils.setup_date_button(self.view, 'acc_date_recvd_entry',
                                'acc_date_recvd_button')

        # date accessioned
        self.view.connect('acc_date_accd_entry', 'changed',
                          self.on_date_entry_changed,
                          (self.model, 'date_accd'))
        utils.setup_date_button(self.view, 'acc_date_accd_entry',
                                'acc_date_accd_button')

        if self.model in self.session.new:
            # new accession, set date accessioned to today but don't set dirty
            date_str = utils.today_str()
            utils.set_widget_value(self.view.widgets.acc_date_accd_entry,
                                   date_str)
            self._dirty = False

        self.view.connect(
            self.view.widgets.intended_loc_add_button,
            'clicked',
            self.on_loc_button_clicked,
            self.view.widgets.intended_loc_comboentry,
            'intended_location')

        self.view.connect(
            self.view.widgets.intended2_loc_add_button,
            'clicked',
            self.on_loc_button_clicked,
            self.view.widgets.intended2_loc_comboentry,
            'intended2_location')

        # add a taxon implies setting the acc_species_entry
        self.view.connect(
            self.view.widgets.acc_taxon_add_button, 'clicked',
            lambda b, w: generic_taxon_add_action(self.model, self.view, self,
                                                  self, w),
            self.view.widgets.acc_species_entry
        )

        self.has_plants = len(model.plants) > 0
        view.widget_set_sensitive('intended_loc_create_plant_checkbutton',
                                  not self.has_plants)

        self.assign_simple_handler(
            'acc_quantity_recvd_entry', 'quantity_recvd')
        self.view.connect_after(
            'acc_quantity_recvd_entry', 'changed',
            self.refresh_create_plant_checkbutton_sensitivity)
        self.assign_simple_handler('acc_id_qual_combo', 'id_qual',
                                   editor.StringOrNoneValidator())
        self.assign_simple_handler('acc_private_check', 'private')

        self.refresh_sensitivity()
        self.refresh_create_plant_checkbutton_sensitivity()

        if self.model not in self.session.new:
            self.view.widgets.acc_ok_and_add_button.set_sensitive(True)

    def on_loc_select(self, field_name, value):
        if self.initializing:
            return
        self.set_model_attr(field_name, value)
        self.refresh_create_plant_checkbutton_sensitivity()

    def on_id_qual_rank_changed(self, combo, *_args):
        itr = combo.get_active_iter()
        if not itr:
            self.set_model_attr('id_qual_rank', None)
            return
        _text, col = combo.get_model()[itr]
        self.set_model_attr('id_qual_rank', utils.nstr(col))

    def on_date_entry_changed(self, entry, prop):
        # ensure we refresh_sensitivity
        super().on_date_entry_changed(entry, prop)
        self.refresh_sensitivity()

    def refresh_create_plant_checkbutton_sensitivity(self, *_args):
        if self.has_plants:
            self.view.widget_set_sensitive(
                'intended_loc_create_plant_checkbutton', False)
            return
        location_chosen = bool(self.model.intended_location)
        has_quantity = (bool(int(self.model.quantity_recvd)) if
                        self.model.quantity_recvd else False)
        self.view.widget_set_sensitive(
            'intended_loc_create_plant_checkbutton',
            has_quantity and location_chosen)

    def on_species_select(self, value, do_set=True):
        logger.debug('on select: %s', value)
        if isinstance(value, str):
            value = Species.retrieve(self.session, {'species': value})

        for kid in self.view.widgets.message_box_parent.get_children():
            self.view.widgets.remove_parent(kid)
        if do_set:
            self.set_model_attr('species', value)
            self.refresh_id_qual_rank_combo()
        if not value:
            return
        syn = (self.session.query(SpeciesSynonym)
               .filter(SpeciesSynonym.synonym_id == value.id)
               .first())
        if not syn:
            return
        msg = (_('The species <b>%(synonym)s</b> is a synonym of '
                 '<b>%(species)s</b>.\n\nWould you like to choose '
                 '<b>%(species)s</b> instead?') %
               {'synonym': syn.synonym, 'species': syn.species})

        def on_response(_button, response):
            self.view.widgets.remove_parent(box)
            box.destroy()
            if response:
                completion = (self.view.widgets.acc_species_entry
                              .get_completion())
                utils.clear_model(completion)
                model = Gtk.ListStore(object)
                model.append([syn.species])
                completion.set_model(model)
                # remove id_qualifiers
                utils.set_widget_value(self.view.widgets.acc_id_qual_combo,
                                       None)
                # triggers this signal handler to set the model
                self.view.widgets.acc_species_entry.set_text(str(syn.species))

        box = self.view.add_message_box(utils.MESSAGE_BOX_YESNO)
        box.message = msg
        box.on_response = on_response
        box.show()

    def populate_code_formats(self, entry_one=None, values=None):
        logger.debug('populate_code_formats %s %s', entry_one, values)
        list_store = self.view.widgets.acc_code_format_comboentry.get_model()
        if entry_one is None and (itr := list_store.get_iter_first()):
            entry_one = list_store.get_value(itr, 0)
        self.view.widgets.acc_code_format_comboentry.remove_all()
        if entry_one:
            self.view.widgets.acc_code_format_comboentry.append_text(entry_one)
        if values is None:
            query = (self.session
                     .query(meta.BaubleMeta)
                     .filter(meta.BaubleMeta.name.like('acidf_%'))
                     .order_by(meta.BaubleMeta.name))
            if query.first():
                Accession.code_format = query.first().value
            values = [r.value for r in query]
        for value in values:
            # Don't append entry_one twice
            if value != entry_one:
                self.view.widgets.acc_code_format_comboentry.append_text(value)

    def on_acc_code_format_comboentry_changed(self, combobox, *_args):
        code_format = (self.view.widget_get_value(combobox) or
                       Accession.code_format)
        code = Accession.get_next_code(code_format)
        self.view.widget_set_value('acc_code_entry', code)

    def on_acc_code_format_edit_btn_clicked(self, _widget, *_args):
        view = editor.GenericEditorView(
            os.path.join(paths.lib_dir(), 'plugins', 'garden',
                         'acc_editor.glade'),
            root_widget_name='acc_codes_dialog')
        list_store = view.widgets.acc_codes_liststore
        list_store.clear()
        query = (self.session
                 .query(meta.BaubleMeta)
                 .filter(meta.BaubleMeta.name.like('acidf_%'))
                 .order_by(meta.BaubleMeta.name))
        for i, row in enumerate(query):
            list_store.append([i + 1, row.value])
        list_store.append([len(list_store) + 1, ''])

        class AccCodeFormatPresenter(editor.GenericEditorPresenter):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.view.connect('acc_cf_renderer', 'edited',
                                  self.on_acc_cf_renderer_edited)

            @staticmethod
            def on_acc_cf_renderer_edited(_widget, itr, value):
                itr = list_store.get_iter_from_string(str(itr))
                list_store.set_value(itr, 1, value)
                if list_store.iter_next(itr) is None:
                    if value:
                        list_store.append([len(list_store) + 1, ''])
                elif value == '':
                    list_store.remove(itr)
                    while itr:
                        list_store.set_value(itr, 0,
                                             list_store.get_value(itr, 0) - 1)
                        itr = list_store.iter_next(itr)

        presenter = AccCodeFormatPresenter(list_store, view,
                                           session=db.Session())

        if presenter.start() > 0:
            (presenter.session.query(meta.BaubleMeta)
             .filter(meta.BaubleMeta.name.like('acidf_%'))
             .delete(synchronize_session=False))
            i = 1
            itr = list_store.get_iter_first()
            values = []
            while itr:
                value = list_store.get_value(itr, 1)
                itr = list_store.iter_next(itr)
                i += 1
                if not value:
                    continue
                obj = meta.BaubleMeta(name=f'acidf_{i:02d}', value=value)
                values.append(value)
                presenter.session.add(obj)
            self.populate_code_formats(values=values)
            presenter.session.commit()

        presenter.session.close()

    def refresh_id_qual_rank_combo(self):
        """Populate the id_qual_rank_combo with the parts of the species string
        """
        combo = self.view.widgets.acc_id_qual_rank_combo
        utils.clear_model(combo)

        if not self.model.species:
            return

        model = Gtk.ListStore(str, str)
        species = self.model.species
        active = None

        itr = model.append([str(species.genus), 'genus'])
        if self.model.id_qual_rank == 'genus':
            active = itr

        itr = model.append([str(species.sp), 'sp'])
        if self.model.id_qual_rank == 'sp':
            active = itr

        infrasp_parts = []
        for level in (1, 2, 3, 4):
            infrasp = [s for s in species.get_infrasp(level) if s is not None]
            if infrasp:
                infrasp_parts.append(' '.join(infrasp))
        if infrasp_parts:
            itr = model.append([' '.join(infrasp_parts), 'infrasp'])

            if self.model.id_qual_rank == 'infrasp':
                active = itr

        # add None only if no active (NOTE default set in refresh_sensitivity)
        if not active:
            itr = model.append(('', None))
            active = itr
        combo.set_model(model)
        combo.set_active_iter(active)

    def on_loc_button_clicked(self, button, target_widget, target_field):
        logger.debug('on_loc_button_clicked %s, %s, %s, %s', self, button,
                     target_widget, target_field)
        from .location import LocationEditor
        loc_editor = LocationEditor(parent=self.view.get_window())
        if loc_editor.start():
            location = loc_editor.presenter.model
            self.session.add(location)
            self.remove_problem(None, target_widget)
            self.view.widget_set_value(target_widget, location)
            self.set_model_attr(target_field, location)

    def is_dirty(self):
        presenters = [self.ver_presenter, self.voucher_presenter,
                      self.notes_presenter, self.source_presenter]
        dirty_kids = [p.is_dirty() for p in presenters]
        return self._dirty or True in dirty_kids

    @staticmethod
    def on_recvd_type_comboentry_changed(combo, *_args):
        value = None
        treeiter = combo.get_active_iter()
        if not treeiter:
            # the changed handler is fired again after the
            # combo.get_child().set_text() with the activer iter set to None
            return
        value = combo.get_model()[treeiter][0]
        # the entry change handler does the validation of the model
        combo.get_child().set_text(recvd_type_values[value])

    def on_recvd_type_entry_changed(self, entry, *_args):
        text = entry.get_text()
        if not text.strip():
            self.remove_problem(self.PROBLEM_BAD_RECVD_TYPE, entry)
            self.set_model_attr('recvd_type', None)
            return
        model = entry.get_completion().get_model()

        def match_func(row, data):
            return (str(row[0]).lower() == str(data).lower() or
                    str(row[1]).lower() == str(data).lower())

        results = utils.search_tree_model(model, text, match_func)
        if results and len(results) == 1:  # is match is unique
            self.remove_problem(self.PROBLEM_BAD_RECVD_TYPE, entry)
            self.set_model_attr('recvd_type', model[results[0]][0])
        else:
            self.add_problem(self.PROBLEM_BAD_RECVD_TYPE, entry)
            self.set_model_attr('recvd_type', None)

    def on_acc_code_entry_changed(self, entry):
        text = entry.get_text()
        query = self.session.query(Accession)
        if (text != self._original_code and
                query.filter_by(code=str(text)).count() > 0):
            self.add_problem(self.PROBLEM_DUPLICATE_ACCESSION,
                             self.view.widgets.acc_code_entry)
            self.set_model_attr('code', None)
            return
        self.remove_problem(self.PROBLEM_DUPLICATE_ACCESSION,
                            self.view.widgets.acc_code_entry)
        if text == '':
            self.set_model_attr('code', None)
        else:
            self.set_model_attr('code', utils.nstr(text))

    def set_model_attr(self, attr, value, validator=None):
        """Set attributes on the model and update the GUI as expected. """
        super().set_model_attr(attr, value, validator)
        self._dirty = True
        # TODO: add a test to make sure that the change notifiers are
        # called in the expected order
        prov_sensitive = True
        wild_prov_combo = self.view.widgets.acc_wild_prov_combo
        if attr == 'prov_type':
            if self.model.prov_type == 'Wild':
                itr = wild_prov_combo.get_active_iter()
                if itr:
                    status = wild_prov_combo.get_model()[itr][0]
                    self.model.wild_prov_status = status
            else:
                # remove the value in the model from the wild_prov_combo
                prov_sensitive = False
                self.model.wild_prov_status = None
                wild_prov_combo.set_active(-1)
            wild_prov_combo.set_sensitive(prov_sensitive)
            self.view.widgets.acc_wild_prov_combo.set_sensitive(prov_sensitive)

        if self.model.id_qual and not self.model.id_qual_rank:
            self.add_problem(self.PROBLEM_ID_QUAL_RANK_REQUIRED,
                             self.view.widgets.acc_id_qual_rank_combo)
        elif not self.model.id_qual or (self.model.id_qual_rank and
                                        self.model.id_qual):
            self.remove_problem(self.PROBLEM_ID_QUAL_RANK_REQUIRED)

        self.refresh_sensitivity()

    def validate(self, add_problems=False):
        """ Validate the self.model """
        # TODO: if add_problems=True then we should add problems to
        # all the required widgets that don't have values

        if not self.model.code or not self.model.species:
            return False

        for ver in self.model.verifications:
            ignore = ('id', 'accession_id', 'species_id', 'prev_species_id')
            if (utils.get_invalid_columns(ver, ignore_columns=ignore) or
                    not ver.species or not ver.prev_species):
                return False

        for voucher in self.model.vouchers:
            ignore = ('id', 'accession_id')
            if utils.get_invalid_columns(voucher, ignore_columns=ignore):
                return False

        # validate the source if there is one
        if self.model.source:
            if utils.get_invalid_columns(self.model.source.collection):
                return False
            if utils.get_invalid_columns(self.model.source.propagation):
                return False

            if not self.model.source.propagation:
                return True

            prop = self.model.source.propagation
            prop_ignore = ['id', 'propagation_id']
            prop_model = None
            if prop:
                # pylint: disable=protected-access
                if prop.prop_type == 'Seed':
                    prop_model = prop._seed
                elif prop.prop_type == 'UnrootedCutting':
                    prop_model = prop._cutting
                elif prop.prop_type == 'Other':
                    return True
                else:
                    # should never get here.
                    logger.error('validate unknown prop_type')
                    return False

            if utils.get_invalid_columns(prop_model, prop_ignore):
                return False

        return True

    def refresh_fullname_label(self):
        sp_str = self.model.species_str(markup=True, authors=True)
        self.view.set_label('sp_fullname_label', sp_str or '--')

    def refresh_sensitivity(self):
        """Refresh the sensitivity of the fields and accept buttons according
        to the current values in the model.
        """
        self.refresh_fullname_label()
        if self.model.species and self.model.id_qual:
            self.view.widgets.acc_id_qual_rank_combo.set_sensitive(True)
            if self.model.id_qual and not self.model.id_qual_rank:
                # set default
                utils.set_widget_value(
                    self.view.widgets.acc_id_qual_rank_combo, 'genus', index=1
                )
        else:
            self.view.widgets.acc_id_qual_rank_combo.set_sensitive(False)
            if self.view.widgets.acc_id_qual_rank_combo.get_model():
                utils.set_widget_value(
                    self.view.widgets.acc_id_qual_rank_combo, None, index=1
                )

        sensitive = (self.is_dirty() and
                     self.validate() and
                     not self.problems and
                     not self.source_presenter.all_problems() and
                     not self.ver_presenter.problems and
                     not self.voucher_presenter.problems)
        self.view.set_accept_buttons_sensitive(sensitive)

    def refresh_view(self, initializing=False):
        # pylint: disable=arguments-differ
        """get the values from the model and put them in the view"""
        self.initializing = initializing
        for widget, field in self.widget_to_field_map.items():
            if field == 'species_id':
                value = self.model.species
            else:
                value = getattr(self.model, field)
            self.view.widget_set_value(widget, value)

        self.view.widget_set_value(
            'acc_wild_prov_combo',
            dict(wild_prov_status_values)[self.model.wild_prov_status],
            index=1)
        self.view.widget_set_value(
            'acc_prov_combo',
            dict(prov_type_values)[self.model.prov_type],
            index=1)
        self.view.widget_set_value(
            'acc_recvd_type_comboentry',
            recvd_type_values[self.model.recvd_type],
            index=1)

        self.view.widgets.acc_private_check.set_inconsistent(False)
        self.view.widgets.acc_private_check.set_active(
            self.model.private is True)

        sensitive = self.model.prov_type == 'Wild'
        self.view.widgets.acc_wild_prov_combo.set_sensitive(sensitive)
        self.initializing = False

    def cleanup(self):
        super().cleanup()
        # garbage collect.
        msg_box_parent = self.view.widgets.message_box_parent
        for widget in msg_box_parent.get_children():
            widget.destroy()
        self.ver_presenter.cleanup()
        self.voucher_presenter.cleanup()
        self.source_presenter.cleanup()
        self.notes_presenter.cleanup()

    def start(self):
        self.source_presenter.start()
        response = self.view.start()
        return response


class AccessionEditor(editor.GenericModelViewPresenterEditor):

    # these have to correspond to the response values in the view
    RESPONSE_OK_AND_ADD = 11
    RESPONSE_NEXT = 22
    ok_responses = (RESPONSE_OK_AND_ADD, RESPONSE_NEXT)

    def __init__(self, model=None, parent=None):
        """
        :param model: Accession instance or None
        :param parent: the parent widget
        """
        if model is None:
            model = Accession()

        super().__init__(model, parent)
        self.parent = parent
        self._committed = []

        view = AccessionEditorView(parent=parent)
        self.presenter = AccessionEditorPresenter(self.model, view)

        # set the default focus
        if self.model.species is None:
            # new accession
            view.widgets.acc_species_entry.grab_focus()
        else:
            view.widgets.acc_code_entry.grab_focus()
            # check if the current species is a synonym (and hence open a
            # message window saying so) without dirtying the presenter
            self.presenter.on_species_select(self.model.species, do_set=False)

    def handle_response(self, response):
        """handle the response from self.presenter.start() in self.start()"""
        not_ok_msg = _('Are you sure you want to lose your changes?')
        if response == Gtk.ResponseType.OK or response in self.ok_responses:
            try:
                if not self.presenter.validate():
                    # TODO: ideally the accept buttons wouldn't have
                    # been sensitive until validation had already
                    # succeeded but we'll put this here either way and
                    # show a message about filling in the fields
                    #
                    # msg = _('Some required fields have not been completed')
                    return False
                if self.presenter.is_dirty():
                    self.commit_changes()
                    self._committed.append(self.model)
            except DBAPIError as e:
                msg = (_('Error committing changes.\n\n%s') %
                       utils.xml_safe(str(e.orig)))
                utils.message_details_dialog(msg, str(e),
                                             Gtk.MessageType.ERROR)
                return False
            except Exception as e:  # pylint: disable=broad-except
                msg = (_('Unknown error when committing changes. See the '
                         'details for more information.\n\n%s') %
                       utils.xml_safe(e))
                utils.message_details_dialog(msg, traceback.format_exc(),
                                             Gtk.MessageType.ERROR)
                return False
        elif ((self.presenter.is_dirty() and
               utils.yes_no_dialog(not_ok_msg)) or
              not self.presenter.is_dirty()):
            self.session.rollback()
            return True
        else:
            return False

        # respond to responses
        more_committed = None
        if response == self.RESPONSE_NEXT:
            self.presenter.cleanup()
            acc_editor = AccessionEditor(parent=self.parent)
            more_committed = acc_editor.start()
        elif response == self.RESPONSE_OK_AND_ADD:
            plt_editor = PlantEditor(Plant(accession=self.model), self.parent)
            more_committed = plt_editor.start()

        if more_committed is not None:
            if isinstance(more_committed, list):
                self._committed.extend(more_committed)
            else:
                self._committed.append(more_committed)

        return True

    def start(self):
        if self.session.query(Species).count() == 0:
            msg = _('You must first add or import at least one species into '
                    'the database before you can add accessions.')
            utils.message_dialog(msg)
            # close session here or __del__ will commit the blank accession
            self.session.close()
            self.presenter.cleanup()
            return None

        while True:
            response = self.presenter.start()
            self.presenter.view.save_state()
            if self.handle_response(response):
                break

        self.session.close()  # cleanup session
        self.presenter.cleanup()
        return self._committed

    def commit_changes(self):
        if self.model.source:

            if not self.model.source.collection:
                utils.delete_or_expunge(
                    self.presenter.source_presenter.collection)

            self.presenter.source_presenter.propagation.clean()
            if not self.model.source.propagation:
                utils.delete_or_expunge(
                    self.presenter.source_presenter.propagation
                )

            # remove any newly created parts if they do not end up used. (i.e.
            # user backed out)
            for new in self.session.new:
                if (isinstance(new, SourceDetail) and new !=
                        self.model.source.source_detail):
                    self.session.expunge(new)
                if (isinstance(new, Collection) and new !=
                        self.model.source.collection):
                    self.session.expunge(new)
                if (isinstance(new, Propagation) and new !=
                        self.model.source.propagation):
                    self.session.expunge(new)
        else:
            utils.delete_or_expunge(
                self.presenter.source_presenter.source)
            utils.delete_or_expunge(
                self.presenter.source_presenter.collection)
            utils.delete_or_expunge(
                self.presenter.source_presenter.propagation)

        if self.model.id_qual is None:
            self.model.id_qual_rank = None

        # should we also add a plant for this accession?
        if self.model.create_plant:
            logger.debug('creating plant for new accession')
            accession = self.model
            location = accession.intended_location
            plant = Plant(
                accession=accession,
                code='1',
                quantity=accession.quantity_recvd,
                location=location,
                acc_type=accession_type_to_plant_material.get(
                    self.model.recvd_type)
            )
            self.session.add(plant)

        return super().commit_changes()


# import at the bottom to avoid circular dependencies
# pylint: disable=wrong-import-order
from ..plants.genus import Genus
from ..plants.species_model import Species, SpeciesSynonym


# TODO: i don't think this shows all field of an accession, like the
# accuracy values
class GeneralAccessionExpander(InfoExpander):
    """generic information about an accession like number of clones, provenance
    type, wild provenance type, speciess
    """

    def __init__(self, widgets):
        super().__init__(_("General"), widgets)
        general_box = self.widgets.general_box
        self.widgets.general_window.remove(general_box)
        self.vbox.pack_start(general_box, True, True, 0)

    def update(self, row):
        self.widget_set_value('acc_code_data',
                              f'<big>{utils.xml_safe(str(row.code))}</big>',
                              markup=True)

        self.widget_set_value('name_data', row.species_str(markup=True),
                              markup=True)

        session = object_session(row)
        plant_locations = {}
        for plant in row.plants:
            if plant.quantity == 0:
                continue
            qty = plant_locations.setdefault(plant.location, 0)
            plant_locations[plant.location] = qty + plant.quantity
        if plant_locations:
            strs = []
            for location, quantity in plant_locations.items():
                strs.append(_('%(quantity)s in %(location)s')
                            % dict(location=str(location), quantity=quantity))
            string = '\n'.join(strs)
        else:
            string = '0'
        self.widget_set_value('living_plants_data', string)

        nplants = session.query(Plant).filter_by(accession_id=row.id).count()
        self.widget_set_value('nplants_data', nplants)
        self.widget_set_value('date_recvd_data', row.date_recvd)
        self.widget_set_value('date_accd_data', row.date_accd)

        type_str = ''
        if row.recvd_type:
            type_str = recvd_type_values[row.recvd_type]
        self.widget_set_value('recvd_type_data', type_str)
        quantity_str = ''
        if row.quantity_recvd:
            quantity_str = row.quantity_recvd
        self.widget_set_value('quantity_recvd_data', quantity_str)

        prov_str = dict(prov_type_values)[row.prov_type]
        if row.prov_type == 'Wild' and row.wild_prov_status:
            prov_status = dict(wild_prov_status_values)[row.wild_prov_status]
            prov_str += f" ({prov_status})"

        self.widget_set_value('prov_data', prov_str, False)

        image_size = Gtk.IconSize.MENU
        icon = None
        if row.private:
            icon = 'dialog-password-symbolic'
        self.widgets.private_image.set_from_icon_name(icon, image_size)

        loc_map = (('intended_loc_data', 'intended_location'),
                   ('intended2_loc_data', 'intended2_location'))

        for label, attr in loc_map:
            location = getattr(row, attr)
            location_str = ''
            if location:
                location_str = str(location)
            self.widget_set_value(label, location_str)

        from ..plants.species import on_taxa_clicked

        utils.make_label_clickable(self.widgets.name_data, on_taxa_clicked,
                                   row.species)
        on_clicked = utils.generate_on_clicked(select_in_search_results)
        if row.source and row.source.plant_propagation:
            utils.make_label_clickable(self.widgets.parent_plant_data,
                                       on_clicked,
                                       row.source.plant_propagation.plant)

        cmd = f'plant where accession.code="{row.code}"'
        on_clicked_search = utils.generate_on_clicked(bauble.gui.send_command)
        utils.make_label_clickable(self.widgets.nplants_data,
                                   on_clicked_search, cmd)


class SourceExpander(InfoExpander):

    EXPANDED_PREF = 'infobox.accession_source_expanded'

    def __init__(self, widgets):
        super().__init__(_('Source'), widgets)
        source_box = self.widgets.source_box
        self.widgets.source_window.remove(source_box)
        self.vbox.pack_start(source_box, True, True, 0)

        self.source_detail_widgets = [self.widgets.source_name_label,
                                      self.widgets.source_name_data]
        self.source_code_widgets = [self.widgets.sources_code_data,
                                    self.widgets.sources_code_label]
        self.plt_prop_widgets = [self.widgets.parent_plant_label,
                                 self.widgets.parent_plant_eventbox]
        self.prop_widgets = [self.widgets.propagation_label,
                             self.widgets.propagation_data]
        self.collection_widgets = [self.widgets.collection_expander,
                                   self.widgets.collection_seperator]

        self.display_widgets = [*self.source_detail_widgets,
                                *self.source_code_widgets,
                                *self.plt_prop_widgets,
                                *self.prop_widgets,
                                *self.collection_widgets]

    def update_collection(self, collection):
        self.widget_set_value('loc_data', collection.locale)
        self.widget_set_value('datum_data', collection.gps_datum)

        geo_accy = collection.geo_accy
        if not geo_accy:
            geo_accy = ''
        else:
            geo_accy = f'(+/- {geo_accy}m)'

        lat_str = ''
        if collection.latitude is not None:
            direct, degs, mins, secs = latitude_to_dms(collection.latitude)
            lat_str = (f'{collection.latitude} '
                       f'({direct} {degs}°{mins}\'{secs}") {geo_accy}')
        self.widget_set_value('lat_data', lat_str)

        long_str = ''
        if collection.longitude is not None:
            direct, degs, mins, secs = longitude_to_dms(collection.longitude)
            long_str = (f'{collection.longitude} '
                        f'({direct} {degs}°{mins}\'{secs}") {geo_accy}')
        self.widget_set_value('lon_data', long_str)

        elevation = ''
        if collection.elevation:
            elevation = f'{collection.elevation}m'
            if collection.elevation_accy:
                elevation += f' (+/- {collection.elevation_accy}m)'
        self.widget_set_value('elev_data', elevation)

        self.widget_set_value('coll_data', collection.collector)
        self.widget_set_value('date_data', collection.date)
        self.widget_set_value('collid_data', collection.collectors_code)
        self.widget_set_value('habitat_data', collection.habitat)
        self.widget_set_value('collnotes_data', collection.notes)

    def update(self, row):
        self.reset()

        if row.source:
            self.set_sensitive(True)
        else:
            return

        if row.source.source_detail:
            utils.unhide_widgets(self.source_detail_widgets)
            self.widget_set_value('source_name_data',
                                  utils.nstr(row.source.source_detail))

            on_clicked = utils.generate_on_clicked(select_in_search_results)
            utils.make_label_clickable(self.widgets.source_name_data,
                                       on_clicked,
                                       row.source.source_detail)

        sources_code = ''

        if row.source.sources_code:
            utils.unhide_widgets(self.source_code_widgets)
            sources_code = row.source.sources_code
            self.widget_set_value('sources_code_data', str(sources_code))

        prop_str = ''
        if row.source.plant_propagation:
            utils.unhide_widgets(self.plt_prop_widgets)
            self.widget_set_value('parent_plant_data',
                                  str(row.source.plant_propagation.plant))
            prop_str = row.source.plant_propagation.get_summary(partial=2)

        if row.source.propagation:
            prop_str = row.source.propagation.get_summary()

        self.widget_set_value('propagation_data', prop_str)

        if prop_str:
            utils.unhide_widgets(self.prop_widgets)

        if row.source.collection:
            utils.unhide_widgets(self.collection_widgets)
            self.widgets.collection_expander.set_expanded(True)
            self.update_collection(row.source.collection)


class VerificationsExpander(InfoExpander):
    """the accession's verifications"""

    EXPANDED_PREF = 'infobox.accession_verifications_expanded'

    def __init__(self, widgets):
        super().__init__(_("Verifications"), widgets)

    def update(self, row):
        self.reset()

        for kid in self.vbox.get_children():
            self.vbox.remove(kid)

        if row.verifications:
            self.set_sensitive(True)
        else:
            return

        frmt = prefs.prefs[prefs.date_format_pref]
        for ver in sorted(row.verifications,
                          key=lambda v: v.date,
                          reverse=True):
            date = ver.date.strftime(frmt)
            date_lbl = Gtk.Label()
            date_lbl.set_markup(f'<b>{date}</b>')
            date_lbl.set_xalign(0.0)
            date_lbl.set_yalign(0.5)
            self.vbox.pack_start(date_lbl, True, True, 0)
            label = Gtk.Label()
            string = (f'verified as {ver.species.markup()} by {ver.verifier}')
            label.set_markup(string)
            label.set_xalign(0.0)
            label.set_yalign(0.5)
            self.vbox.pack_start(label, True, True, 0)
            label.show()


class VouchersExpander(InfoExpander):
    """the accession's vouchers"""

    EXPANDED_PREF = 'infobox.accession_vouchers_expanded'

    def __init__(self, widgets):
        super().__init__(_("Vouchers"), widgets)

    def update(self, row):
        self.reset()

        for kid in self.vbox.get_children():
            self.vbox.remove(kid)

        if row.vouchers:
            self.set_sensitive(True)
        else:
            return

        parents = [v for v in row.vouchers if v.parent_material]
        for voucher in parents:
            string = f'{voucher.herbarium} {voucher.code} (parent)'
            label = Gtk.Label(label=string)
            label.set_xalign(0)
            label.set_yalign(0.5)
            self.vbox.pack_start(label, True, True, 0)
            label.show()

        not_parents = [v for v in row.vouchers if not v.parent_material]
        for voucher in not_parents:
            string = f'{voucher.herbarium} {voucher.code}'
            label = Gtk.Label(label=string)
            label.set_xalign(0)
            label.set_yalign(0.5)
            self.vbox.pack_start(label, True, True, 0)
            label.show()


class AccessionInfoBox(InfoBox):
    """Accession InfoBox
    - general info
    - source
    """
    def __init__(self):
        super().__init__()
        filename = os.path.join(paths.lib_dir(), "plugins", "garden",
                                "acc_infobox.glade")
        self.widgets = utils.load_widgets(filename)
        self.general = GeneralAccessionExpander(self.widgets)
        self.add_expander(self.general)
        self.source = SourceExpander(self.widgets)
        self.add_expander(self.source)

        self.vouchers = VouchersExpander(self.widgets)
        self.add_expander(self.vouchers)
        self.verifications = VerificationsExpander(self.widgets)
        self.add_expander(self.verifications)

        self.links = LinksExpander('notes')
        self.add_expander(self.links)

        self.props = PropertiesExpander()
        self.add_expander(self.props)

    def update(self, row):
        if isinstance(row, Collection):
            row = row.source.accession

        self.general.update(row)
        self.props.update(row)

        self.verifications.update(row)

        self.vouchers.update(row)

        self.links.update(row)

        self.source.update(row)


#
# Map Datum List - this list should be available as a list of completions for
# the datum text entry....the best way is that is to show the abbreviation
# with the long string in parenthesis or with different markup but selecting
# the completion will enter the abbreviation....though the entry should be
# free text....this list complements of:
# http://www8.garmin.com/support/faqs/MapDatumList.pdf
#
# Abbreviation: Name
datums = {"Adindan": "Adindan- Ethiopia, Mali, Senegal, Sudan",
          "Afgooye": "Afgooye- Somalia",
          "AIN EL ABD": "'70 AIN EL ANBD 1970- Bahrain Island, Saudi Arabia",
          "Anna 1 Ast '65": "Anna 1 Astro '65- Cocos I.",
          "ARC 1950": ("ARC 1950- Botswana, Lesotho, Malawi, Swaziland, "
                       "Zaire, Zambia"),
          "ARC 1960": "Kenya, Tanzania",
          "Ascnsn Isld '58": "Ascension Island '58- Ascension Island",
          "Astro Dos 71/4": "Astro Dos 71/4- St. Helena",
          "Astro B4 Sorol": "Sorol Atoll- Tern Island",
          "Astro Bcn \"E\"": "Astro Beacon \"E\"- Iwo Jima",
          "Astr Stn '52": "Astronomic Stn '52- Marcus Island",
          "Aus Geod '66": "Australian Geod '66- Australia, Tasmania Island",
          "Aus Geod '84": "Australian Geod '84- Australia, Tasmania Island",
          "Austria": "Austria",
          "Bellevue (IGN)": "Efate and Erromango Islands",
          "Bermuda 1957": "Bermuda 1957- Bermuda Islands",
          "Bogota Observ": "Bogata Obsrvatry- Colombia",
          "Campo Inchspe": "Campo Inchauspe- Argentina",
          "Canton Ast '66": "Canton Astro 1966- Phoenix Islands",
          "Cape": "Cape- South Africa",
          "Cape Canavrl": "Cape Canaveral- Florida, Bahama Islands",
          "Carthage": "Carthage- Tunisia",
          "CH-1903": "CH 1903- Switzerland",
          "Chatham 1971": "Chatham 1971- Chatham Island (New Zealand)",
          "Chua Astro": "Chua Astro- Paraguay",
          "Corrego Alegr": "Corrego Alegre- Brazil",
          "Croatia": "Croatia",
          "Djakarta": "Djakarta (Batavia)- Sumatra Island (Indonesia)",
          "Dos 1968": "Dos 1968- Gizo Island (New Georgia Islands)",
          "Dutch": "Dutch",
          "Easter Isld 67": "Easter Island 1967",
          "European 1950": ("European 1950- Austria, Belgium, Denmark, "
                            "Finland, France, Germany, Gibraltar, Greece, "
                            "Italy, Luxembourg, Netherlands, Norway, "
                            "Portugal, Spain, Sweden, Switzerland"),
          "European 1979": ("European 1979- Austria, Finland, Netherlands, "
                            "Norway, Spain, Sweden, Switzerland"),
          "Finland Hayfrd": "Finland Hayford- Finland",
          "Gandajika Base": "Gandajika Base- Republic of Maldives",
          "GDA": "Geocentric Datum of Australia",
          "Geod Datm '49": "Geodetic Datum '49- New Zealand",
          "Guam 1963": "Guam 1963- Guam Island",
          "Gux 1 Astro": "Guadalcanal Island",
          "Hjorsey 1955": "Hjorsey 1955- Iceland",
          "Hong Kong '63": "Hong Kong",
          "Hu-Tzu-Shan": "Taiwan",
          "Indian Bngldsh": "Indian- Bangladesh, India, Nepal",
          "Indian Thailand": "Indian- Thailand, Vietnam",
          "Indonesia 74": "Indonesia 1974- Indonesia",
          "Ireland 1965": "Ireland 1965- Ireland",
          "ISTS 073 Astro": "ISTS 073 ASTRO '69- Diego Garcia",
          "Johnston Island": "Johnston Island NAD27 Central",
          "Kandawala": "Kandawala- Sri Lanka",
          "Kergueln Island": "Kerguelen Island",
          "Kertau 1948": "West Malaysia, Singapore",
          "L.C. 5 Astro": "Cayman Brac Island",
          "Liberia 1964": "Liberia 1964- Liberia",
          "Luzon Mindanao": "Luzon- Mindanao Island",
          "Luzon Philippine": "Luzon- Philippines (excluding Mindanao Isl.)",
          "Mahe 1971": "Mahe 1971- Mahe Island",
          "Marco Astro": "Marco Astro- Salvage Isl.",
          "Massawa": "Massawa- Eritrea (Ethiopia)",
          "Merchich": "Merchich- Morocco",
          "Midway Ast '61": "Midway Astro '61- Midway",
          "Minna": "Minna- Nigeria",
          "NAD27 Alaska": "North American 1927- Alaska",
          "NAD27 Bahamas": "North American 1927- Bahamas",
          "NAD27 Canada": "North American 1927- Canada and Newfoundland",
          "NAD27 Canal Zn": "North American 1927- Canal Zone",
          "NAD27 Caribbn": ("North American 1927- Caribbean (Barbados, "
                            "Caicos Islands, Cuba, Dominican Repuplic, Grand "
                            "Cayman, Jamaica, Leeward and Turks Islands)"),
          "NAD27 Central": ("North American 1927- Central America (Belize, "
                            "Costa Rica, El Salvador, Guatemala, Honduras, "
                            "Nicaragua)"),
          "NAD27 CONUS": "North American 1927- Mean Value (CONUS)",
          "NAD27 Cuba": "North American 1927- Cuba",
          "NAD27 Grnland": "North American 1927- Greenland (Hayes Peninsula)",
          "NAD27 Mexico": "North American 1927- Mexico",
          "NAD27 San Sal": "North American 1927- San Salvador Island",
          "NAD83": ("North American 1983- Alaska, Canada, Central America, "
                    "CONUS, Mexico"),
          "Naparima BWI": "Naparima BWI- Trinidad and Tobago",
          "Nhrwn Masirah": "Nahrwn- Masirah Island (Oman)",
          "Nhrwn Saudi A": "Nahrwn- Saudi Arabia",
          "Nhrwn United A": "Nahrwn- United Arab Emirates",
          "Obsrvtorio '66": ("Observatorio 1966- Corvo and Flores Islands "
                             "(Azores)"),
          "Old Egyptian": "Old Egyptian- Egypt",
          "Old Hawaiian": "Old Hawaiian- Mean Value",
          "Oman": "Oman- Oman",
          "Old Srvy GB": ("Old Survey Great Britain- England, Isle of Man, "
                          "Scotland, Shetland Isl., Wales"),
          "Pico De Las Nv": "Canary Islands",
          "Potsdam": "Potsdam-Germany",
          "Prov S Am '56": ("Prov  Amricn '56- Bolivia, Chile,Colombia, "
                            "Ecuador, Guyana, Peru, Venezuela"),
          "Prov S Chln '63": "So. Chilean '63- S. Chile",
          "Ptcairn Ast '67": "Pitcairn Astro '67- Pitcairn",
          "Puerto Rico": "Puerto Rico & Virgin Isl.",
          "Qatar National": "Qatar National- Qatar South Greenland",
          "Qornoq": "Qornoq- South Greenland",
          "Reunion": "Reunion- Mascarene Island",
          "Rome 1940": "Rome 1940- Sardinia Isl.",
          "RT 90": "Sweden",
          "Santo (Dos)": "Santo (Dos)- Espirito Santo",
          "Sao Braz": "Sao Braz- Sao Miguel, Santa Maria Islands",
          "Sapper Hill '43": "Sapper Hill 1943- East Falkland Island",
          "Schwarzeck": "Schwarzeck- Namibia",
          "SE Base": "Southeast Base- Porto Santo and Madiera Islands",
          "South Asia": "South Asia- Singapore",
          "Sth Amrcn '69": ("S. American '69- Argentina, Bolivia, Brazil, "
                            "Chile, Colombia, Ecuador, Guyana, Paraguay, "
                            "Peru, Venezuela, Trin/Tobago"),
          "SW Base": ("Southwest Base- Faial, Graciosa, Pico, Sao Jorge and "
                      "Terceira"),
          "Taiwan": "Taiwan",
          "Timbalai 1948": ("Timbalai 1948- Brunei and E. Malaysia (Sarawak "
                            "and Sabah)"),
          "Tokyo": "Tokyo- Japan, Korea, Okinawa",
          "Tristan Ast '68": "Tristan Astro 1968- Tristan da Cunha",
          "Viti Levu 1916": "Viti Levu 1916- Viti Levu/Fiji Islands",
          "Wake-Eniwetok": "Wake-Eniwetok- Marshall",
          "WGS 72": "World Geodetic System 72",
          "WGS 84": "World Geodetic System 84",
          "Zanderij": "Zanderij- Surinam (excluding San Salvador Island)",
          "USER": "USER-DEFINED CUSTOM DATUM"}
