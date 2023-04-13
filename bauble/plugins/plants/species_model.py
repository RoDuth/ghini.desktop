# Copyright 2008-2010 Brett Adams
# Copyright 2012-2016 Mario Frasca <mario@anche.no>.
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
The species database model
"""

from itertools import chain

import logging
logger = logging.getLogger(__name__)

from sqlalchemy.ext.associationproxy import association_proxy

from sqlalchemy import (Column,
                        Unicode,
                        Integer,
                        ForeignKey,
                        UnicodeText,
                        UniqueConstraint,
                        func,
                        literal,
                        event,
                        CheckConstraint)
from sqlalchemy.orm import relationship, backref, object_session
from sqlalchemy.orm import synonym as sa_synonym
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.sql.expression import select, case, cast, and_, text, or_
from bauble import db
from bauble import error
from bauble import utils
from bauble import btypes as types


def _remove_zws(string):
    "remove_zero_width_space"
    if string:
        return string.replace('\u200b', '')
    return string


class VNList(list):
    """A Collection class for Species.vernacular_names

    This makes it possible to automatically remove a
    default_vernacular_name if the vernacular_name is removed from the
    list.
    """
    def remove(self, vernacular):
        super().remove(vernacular)
        try:
            # see if the deleted vernacular name is the default then remove
            # from both if it is.
            session = object_session(vernacular)
            vn_sp = session.query(Species).get(vernacular.species_id)
            if vn_sp.default_vernacular_name == vernacular:
                del vn_sp.default_vernacular_name
        except Exception as e:  # pylint: disable=broad-except
            logger.debug("VNList: %s(%s)", type(e).__name__, e)


infrasp_rank_values = {'subsp.': _('subsp.'),
                       'var.': _('var.'),
                       'subvar.': _('subvar'),
                       'f.': _('f.'),
                       'subf.': _('subf.'),
                       None: ''}


# TODO: there is a trade_name column but there's no support yet for editing
# the trade_name or for using the trade_name when building the string
# for the species, for more information about trade_names see,
# http://www.hortax.org.uk/gardenplantsnames.html

# TODO: the specific epithet should not be non-nullable but instead
# make sure that at least one of the specific epithet, cultivar name
# or cultivar group is specificed


compare_rank = {
    'familia': 1,
    'subfamilia': 10,
    'tribus': 20,
    'subtribus': 30,
    'genus': 40,
    'subgenus': 50,
    'species': 60,
    'None': 70,
    'subsp.': 80,
    'var.': 90,
    'subvar.': 100,
    'f.': 110,
    'subf.': 120,
}


class Species(db.Base, db.Serializable, db.WithNotes):
    """
    :Table name: species

    :Columns:
        *sp*:
        *sp_author*:

        *hybrid*:
            Hybrid flag

        *infrasp1*:
        *infrasp1_rank*:
        *infrasp1_author*:

        *infrasp2*:
        *infrasp2_rank*:
        *infrasp2_author*:

        *infrasp3*:
        *infrasp3_rank*:
        *infrasp3_author*:

        *infrasp4*:
        *infrasp4_rank*:
        *infrasp4_author*:

        *cv_group*:
        *trade_name*:
        *trademark_symbol*:
        *grex*:
        *pbr_protected*:

        *sp_qual*:
            Species qualifier

            Possible values:
                *agg.*: An aggregate species

                *s. lat.*: aggregrate species (sensu lato)

                *s. str.*: segregate species (sensu stricto)

        *label_distribution*:
            UnicodeText
            This field is optional and can be used for the label in case
            str(self.distribution) is too long to fit on the label.

    :Properties:
        *accessions*:

        *vernacular_names*:

        *default_vernacular_name*:

        *synonyms*:

        *distribution*:
    """
    __tablename__ = 'species'

    # for internal use when importing records, accounts for the lack of
    # UniqueConstraint and the complex of hybrid_properties etc.
    uniq_props = [
        'genus',
        'genus_id',
        'sp',
        'epithet',
        'sp_author',
        'hybrid',
        'sp_qual',
        'infrasp1',
        'infrasp1_rank',
        'infrasp2',
        'infrasp2_rank',
        'infrasp3',
        'infrasp3_rank',
        'infrasp4',
        'infrasp4_rank',
        'infraspecific_parts',
        'infraspecific_epithet',
        'infraspecific_rank',
        'cultivar_epithet'
    ]

    rank = 'species'
    link_keys = ['accepted']

    # columns
    sp = Column(Unicode(128), index=True)
    epithet = sa_synonym('sp')
    sp_author = Column(Unicode(128))
    hybrid = Column(types.Enum(values=['×', '+', None]), default=None)
    sp_qual = Column(types.Enum(values=['agg.', 's. lat.', 's. str.', None]),
                     default=None)
    cv_group = Column(Unicode(50))
    trade_name = Column(Unicode(64))
    trademark_symbol = Column(Unicode(4))
    grex = Column(Unicode(64))
    pbr_protected = Column(types.Boolean, default=False)

    infrasp1 = Column(Unicode(64))
    infrasp1_rank = Column(types.Enum(values=list(infrasp_rank_values.keys()),
                                      translations=infrasp_rank_values))
    infrasp1_author = Column(Unicode(64))

    infrasp2 = Column(Unicode(64))
    infrasp2_rank = Column(types.Enum(values=list(infrasp_rank_values.keys()),
                                      translations=infrasp_rank_values))
    infrasp2_author = Column(Unicode(64))

    infrasp3 = Column(Unicode(64))
    infrasp3_rank = Column(types.Enum(values=list(infrasp_rank_values.keys()),
                                      translations=infrasp_rank_values))
    infrasp3_author = Column(Unicode(64))

    infrasp4 = Column(Unicode(64))
    infrasp4_rank = Column(types.Enum(values=list(infrasp_rank_values.keys()),
                                      translations=infrasp_rank_values))
    infrasp4_author = Column(Unicode(64))

    cultivar_epithet = Column(Unicode(64))

    genus_id = Column(Integer, ForeignKey('genus.id'), nullable=False)
    # the Species.genus property is defined as backref in Genus.species

    label_distribution = Column(UnicodeText)
    label_markup = Column(UnicodeText)

    # relations
    synonyms = association_proxy(
        '_synonyms', 'synonym', creator=lambda sp: SpeciesSynonym(synonym=sp)
    )
    _synonyms = relationship(
        'SpeciesSynonym',
        primaryjoin='Species.id==SpeciesSynonym.species_id',
        cascade='all, delete-orphan',
        uselist=True,
        backref='species')

    # make cascading work
    _accepted = relationship(
        'SpeciesSynonym',
        primaryjoin='Species.id==SpeciesSynonym.synonym_id',
        cascade='all, delete-orphan',
        uselist=False,
        backref='synonym'
    )
    accepted = association_proxy(
        '_accepted', 'species', creator=lambda sp: SpeciesSynonym(species=sp)
    )

    # VernacularName.species gets defined here too.
    vernacular_names = relationship('VernacularName',
                                    cascade='all, delete-orphan',
                                    collection_class=VNList,
                                    backref=backref('species', uselist=False))
    _default_vernacular_name = relationship('DefaultVernacularName',
                                            uselist=False,
                                            cascade='all, delete-orphan',
                                            backref=backref('species',
                                                            uselist=False))
    distribution = relationship('SpeciesDistribution',
                                cascade='all, delete-orphan',
                                backref=backref('species', uselist=False))

    habit_id = Column(Integer, ForeignKey('habit.id'), default=None)
    habit = relationship('Habit', uselist=False, backref='species')

    flower_color_id = Column(Integer, ForeignKey('color.id'), default=None)
    flower_color = relationship('Color', uselist=False, backref='species')

    full_name = Column(Unicode(512), index=True)

    # hardiness_zone = Column(Unicode(4))

    awards = Column(UnicodeText)

    # see retrieve classmethod.
    retrieve_cols = uniq_props + ['id', 'genus.genus', 'genus.epithet']

    # don't use back_populates, can lead to InvalidRequestError
    # accessions = relationship('Accession', cascade='all, delete-orphan',
    #                           back_populates='species')

    @classmethod
    def retrieve(cls, session, keys):
        logger.debug('retrieve species with keys %s', keys)
        from .genus import Genus
        parts = cls.uniq_props[:]
        parts.remove('genus')

        # NOTE don't include id in json taxon imports (can break tests)
        if not keys.get('ht-epithet'):
            parts.append('id')

        sp_parts = {k: v for k, v in keys.items() if k in parts}

        if not sp_parts:
            return None

        logger.debug('sp_parts in keys %s', sp_parts)
        gen = (keys.get('genus') or keys.get('ht-epithet') or
               keys.get('genus.genus') or keys.get('genus.epithet'))
        logger.debug('retrieve species with sp_parts %s and genus %s',
                     sp_parts, gen)

        query = session.query(cls).filter_by(**sp_parts)

        if gen:
            # most likely only skipped if id is in sp_parts
            query = query.join(Genus).filter(Genus.genus == gen)

        from sqlalchemy.orm.exc import MultipleResultsFound
        try:
            return query.one_or_none()
        except MultipleResultsFound:
            return None

    def search_view_markup_pair(self):
        """provide the two lines describing object for SearchView row."""
        try:
            if len(self.vernacular_names) > 0:
                vnames = ', '.join([str(v) for v in self.vernacular_names])
                substring = f'{self.genus.family} -- {vnames}'
            else:
                substring = f'{self.genus.family}'
            trail = ''
            if self.accepted:
                trail += ('<span foreground="#555555" size="small" '
                          'weight="light"> - ' + _("synonym of %s") + "</span>"
                          ) % self.accepted.markup(authors=True)
            citation = self.markup(authors=True, for_search_view=True)
            return citation + trail, substring
        except Exception:  # pylint: disable=broad-except
            return '...', '...'

    @property
    def cites(self):
        """the cites status of this taxon, or None

        cites appendix number, one of I, II, or III.
        not enforced by the software in v1.0.x
        """

        cites_notes = [i.note for i in self.notes
                       if i.category and i.category.upper() == 'CITES']
        if not cites_notes:
            return self.genus.cites
        return cites_notes[0]

    @property
    def conservation(self):
        """the IUCN conservation status of this taxon, or DD

        one of: EX, RE, CR, EN, VU, NT, LC, DD
        not enforced by the software in v1.0.x
        """

        # {'EX': _('Extinct (EX)'),
        #  'EW': _('Extinct Wild (EW)'),
        #  'RE': _('Regionally Extinct (RE)'),
        #  'CR': _('Critically Endangered (CR)'),
        #  'EN': _('Endangered (EN)'),
        #  'VU': _('Vulnerable (VU)'),
        #  'NT': _('Near Threatened (NT)'),
        #  'LV': _('Least Concern (LC)'),
        #  'DD': _('Data Deficient (DD)'),
        #  'NE': _('Not Evaluated (NE)')}

        notes = [i.note for i in self.notes
                 if i.category and i.category.upper() == 'IUCN']
        return (notes + ['DD'])[0]

    @property
    def condition(self):
        """the condition of this taxon, or None

        this is referred to what the garden conservator considers the
        area of interest. it is really an interpretation, not a fact.
        """
        # one of, but not forcibly so:
        # [_('endemic'), _('indigenous'), _('native'), _('introduced')]

        notes = [i.note for i in self.notes
                 if i.category.lower() == 'condition']
        return (notes + [None])[0]

    def __lowest_infraspecific(self):
        infrasp = [(self.infrasp1_rank, self.infrasp1,
                    self.infrasp1_author),
                   (self.infrasp2_rank, self.infrasp2,
                    self.infrasp2_author),
                   (self.infrasp3_rank, self.infrasp3,
                    self.infrasp3_author),
                   (self.infrasp4_rank, self.infrasp4,
                    self.infrasp4_author)]
        infrasp = [i for i in infrasp if i[0] not in ['cv.', '', None]]
        if infrasp == []:
            return ('', '', '')
        return sorted(infrasp,
                      key=lambda a: compare_rank.get(str(a[0]), 150))[-1]

    @hybrid_property
    def infraspecific_rank(self):
        return self.__lowest_infraspecific()[0] or ''

    @infraspecific_rank.expression
    def infraspecific_rank(cls):
        # pylint: disable=no-self-argument
        # use the last epithet that is not 'cv'. available (the user should be
        # keeping their infraspecific parts in order)
        return (
            case([
                (cls.infrasp4_rank.is_not(None), cls.infrasp4_rank),
                (cls.infrasp3_rank.is_not(None), cls.infrasp3_rank),
                (cls.infrasp2_rank.is_not(None), cls.infrasp2_rank),
                (cls.infrasp1_rank.is_not(None), cls.infrasp1_rank),
            ])
            .label('infraspecific_rank')
        )

    @hybrid_property
    def infraspecific_epithet(self):
        return self.__lowest_infraspecific()[1] or ''

    @infraspecific_epithet.expression
    def infraspecific_epithet(cls):
        # pylint: disable=no-self-argument
        # use the last epithet that is not 'cv'.
        return (
            case([
                (cls.infrasp4_rank.is_not(None), cls.infrasp4),
                (cls.infrasp3_rank.is_not(None), cls.infrasp3),
                (cls.infrasp2_rank.is_not(None), cls.infrasp2),
                (cls.infrasp1_rank.is_not(None), cls.infrasp1),
            ])
            .label('infraspecific_epithet')
        )

    @property
    def infraspecific_author(self):
        return self.__lowest_infraspecific()[2] or ''

    @hybrid_property
    def infraspecific_parts(self):
        parts = []
        for rank, epithet in [(self.infrasp1_rank, self.infrasp1),
                              (self.infrasp2_rank, self.infrasp2),
                              (self.infrasp3_rank, self.infrasp3),
                              (self.infrasp4_rank, self.infrasp4)]:
            if rank not in [None, '', 'cv.']:
                parts.append(rank)
                parts.append(epithet)
        parts = ' '.join(parts)
        return parts

    @infraspecific_parts.expression
    def infraspecific_parts(cls):
        # pylint: disable=no-self-argument
        from sqlalchemy.types import String
        return case([
            (cls.infrasp4_rank.is_not(None), cast(
                cls.infrasp1_rank + text("' '") + cls.infrasp1 + text("' '") +
                cls.infrasp2_rank + text("' '") + cls.infrasp2 + text("' '") +
                cls.infrasp3_rank + text("' '") + cls.infrasp3 + text("' '") +
                cls.infrasp4_rank + text("' '") + cls.infrasp4, String)),
            (cls.infrasp3_rank.is_not(None), cast(
                cls.infrasp1_rank + text("' '") + cls.infrasp1 + text("' '") +
                cls.infrasp2_rank + text("' '") + cls.infrasp2 + text("' '") +
                cls.infrasp3_rank + text("' '") + cls.infrasp3, String)),
            (cls.infrasp2_rank.is_not(None), cast(
                cls.infrasp1_rank + text("' '") + cls.infrasp1 + text("' '") +
                cls.infrasp2_rank + text("' '") + cls.infrasp2, String)),
            (cls.infrasp1_rank.is_not(None), cast(
                cls.infrasp1_rank + text("' '") + cls.infrasp1, String)),
        ]).label('infraspecific_parts')

    @infraspecific_parts.setter
    def infraspecific_parts(self, value):
        if value:
            parts = value.split()
            parts = list(zip(parts[0::2], parts[1::2]))
        else:
            parts = []
        for i in range(4):
            if i < len(parts):
                self.set_infrasp(i + 1, *parts[i])
            else:
                # set remainder to null
                self.set_infrasp(i + 1, None, None)

    @hybrid_property
    def default_vernacular_name(self):
        if self._default_vernacular_name is None:
            return None
        return self._default_vernacular_name.vernacular_name

    @default_vernacular_name.expression
    def default_vernacular_name(cls):
        # pylint: disable=no-self-argument
        return (
            select([VernacularName.name])
            .where(and_(
                DefaultVernacularName.species_id == cls.id,
                VernacularName.id == DefaultVernacularName.vernacular_name_id))
            .label('default_vernacular_name')
        )

    @default_vernacular_name.setter
    def default_vernacular_name(self, vernacular):
        if isinstance(vernacular, str):
            logger.debug('vernacular_name is a string: %s', vernacular)
            lang = None
            if ':' in vernacular:
                vernacular, lang = vernacular.split(':')
            kwargs = {'name': vernacular, 'species': self}
            if lang:
                kwargs['language'] = lang
            vnobj = None
            session = object_session(self)
            if session:
                vnobj = db.get_create_or_update(session, VernacularName,
                                                **kwargs)
            if not vnobj:
                vernacular = VernacularName(**kwargs)
            else:
                vernacular = vnobj
        if vernacular is None:
            del self.default_vernacular_name
            return
        if vernacular not in self.vernacular_names:
            self.vernacular_names.append(vernacular)
        default_vernacular = DefaultVernacularName()
        default_vernacular.vernacular_name = vernacular
        self._default_vernacular_name = default_vernacular

    @default_vernacular_name.deleter
    def default_vernacular_name(self):
        if self._default_vernacular_name:
            utils.delete_or_expunge(self._default_vernacular_name)
            del self._default_vernacular_name

    def distribution_str(self):
        if self.distribution is None:
            return ''
        dist = [f'{d}' for d in self.distribution]
        return str(', ').join(sorted(dist))

    def markup(self, authors=False, genus=True, for_search_view=False):
        """returns this object as a string with markup

        :param authors: whether the authorship should be included
        :param genus: whether the genus name should be included
        :param for_search_view: in search view authorship is in light text
        """
        return self.str(authors, markup=True, genus=genus,
                        for_search_view=for_search_view)

    def __str__(self):
        """return the default string representation for self."""
        return self.str()

    def str(self, authors=False, markup=False, remove_zws=True, genus=True,
            qualification=None, for_search_view=False):
        """Returns a string for species.

        :param authors: flag to toggle whether authorship should be included
        :param markup: flag to toggle whether the returned text is marked up
            to show italics on the epithets
        :param remove_zws: flag to toggle zero width spaces, helping
            semantically correct lexicographic order.
        :param genus: flag to toggle leading genus name.
        :param qualification: pair or None. if specified, first is the
            qualified rank, second is the qualification.
        :param for_search_view: in search view authorship is in light text
        """
        session = False
        from sqlalchemy import inspect

        qual_rank, qualifier = qualification if qualification else (None, None)

        if qualifier == 'incorrect':
            qual_rank = None

        if inspect(self).detached:
            session = db.Session()
            session.enable_relationship_loading(self)
        if genus is True:
            genus = ''
            if qual_rank == 'genus':
                genus = qualifier + ' '
            if markup:
                genus += self.genus.markup()
            else:
                genus += str(self.genus)
        else:
            genus = ''
        if session:
            session.close()

        if self.sp and not remove_zws:
            sp = '\u200b' + self.sp  # prepend with zero_width_space
        else:
            sp = self.sp

        if markup:
            escape = utils.xml_safe
            italicize = utils.markup_italics
            if sp is not None:
                sp = italicize(escape(sp))
        else:
            italicize = escape = lambda x: x

        if qual_rank == 'sp':
            sp = qualifier + ' ' + sp

        author = None
        if authors and self.sp_author:
            author = escape(self.sp_author)
            if for_search_view:
                author = '<span weight="light">' + author + '</span>'

        infrasp = ((self.infrasp1_rank, self.infrasp1,
                    self.infrasp1_author),
                   (self.infrasp2_rank, self.infrasp2,
                    self.infrasp2_author),
                   (self.infrasp3_rank, self.infrasp3,
                    self.infrasp3_author),
                   (self.infrasp4_rank, self.infrasp4,
                    self.infrasp4_author))

        infrasp_parts = []
        for level, (rank, epithet, iauthor) in enumerate(infrasp, 1):
            if qual_rank == f'infrasp{level}' and any([rank, epithet]):
                infrasp_parts.append(qualifier)
            if rank:
                infrasp_parts.append(rank)
            if epithet and rank:
                infrasp_parts.append(italicize(epithet))
            elif epithet:
                infrasp_parts.append(escape(epithet))

            if authors and iauthor:
                iauthor = escape(iauthor)
                if for_search_view:
                    iauthor = '<span weight="light">' + iauthor + '</span>'
                infrasp_parts.append(iauthor)

        if self.grex:
            infrasp_parts.append(self.grex)

        if self.cv_group:
            if self.cultivar_epithet:
                infrasp_parts.append(_("(%(group)s Group)") %
                                     dict(group=self.cv_group))
            else:
                infrasp_parts.append(_("%(group)s Group") %
                                     dict(group=self.cv_group))

        if self.cultivar_epithet and qual_rank == 'cv':
            infrasp_parts.append(qualifier)

        if self.cultivar_epithet == 'cv.':
            infrasp_parts.append('cv.')
        elif self.cultivar_epithet:
            infrasp_parts.append(f"'{escape(self.cultivar_epithet)}'")

        if self.pbr_protected:
            pbr = '(PBR)'
            if markup:
                # would like to use <sup> here but get
                # Pango-WARNING **: Leftover font scales
                pbr = f'<small>{pbr}</small>'
            if for_search_view:
                pbr = f'<span weight="light">{pbr}</span>'
            infrasp_parts.append(pbr)

        def _small_caps(txt):
            # using <span variant="smallcaps"> pango can have trouble finding
            # the right fonts in macos at least  This approach achieves
            # acceptable results without having concerns about the font.
            result = ''
            small = False
            for i in txt:
                if i.isupper():
                    if small:
                        result += '</small>'
                        small = False
                    result += i
                else:
                    if not small:
                        result += '<small>'
                        small = True
                    result += i.upper()

            if small:
                result += '</small>'

            return result

        if self.trade_name:
            trade_name = escape(self.trade_name)
            if markup:
                infrasp_parts.append(_small_caps(trade_name) +
                                     (self.trademark_symbol or ''))
            else:
                infrasp_parts.append(trade_name.upper() +
                                     (self.trademark_symbol or ''))

        # create the binomial part
        binomial = [genus, self.hybrid, sp, author]

        # create the tail, ie: anything to add on to the end
        tail = []
        if not qual_rank and qualifier:
            tail.append(f'({qualifier})')
        if self.sp_qual:
            tail.append(self.sp_qual)

        parts = chain(binomial, infrasp_parts, tail)
        string = ' '.join(i for i in parts if i)
        return string

    @hybrid_property
    def active(self):
        """False when all accessions have been deaccessioned
        (e.g. all plants have died)
        """
        if not self.accessions:
            return True
        for acc in self.accessions:
            if acc.active:
                return True
        return False

    @active.expression
    def active(cls):
        # pylint: disable=no-self-argument
        acc_cls = cls.accessions.prop.mapper.class_
        plt_cls = acc_cls.plants.prop.mapper.class_
        active = (select([cls.id])
                  .outerjoin(acc_cls)
                  .outerjoin(plt_cls)
                  .where(or_(plt_cls.id.is_(None), plt_cls.quantity > 0))
                  .scalar_subquery())
        return cast(case([(cls.id.in_(active), 1)], else_=0),
                    types.Boolean)

    infrasp_attr = {1: {'rank': 'infrasp1_rank',
                        'epithet': 'infrasp1',
                        'author': 'infrasp1_author'},
                    2: {'rank': 'infrasp2_rank',
                        'epithet': 'infrasp2',
                        'author': 'infrasp2_author'},
                    3: {'rank': 'infrasp3_rank',
                        'epithet': 'infrasp3',
                        'author': 'infrasp3_author'},
                    4: {'rank': 'infrasp4_rank',
                        'epithet': 'infrasp4',
                        'author': 'infrasp4_author'}}

    def get_infrasp(self, level):
        """Get the 3 fields of infrasp at `level` as a tuple

        :param level: 1-4
        """
        return (getattr(self, self.infrasp_attr[level]['rank']),
                getattr(self, self.infrasp_attr[level]['epithet']),
                getattr(self, self.infrasp_attr[level]['author']))

    def set_infrasp(self, level, rank, epithet, author=None):
        """set the rank, epithet and author fields of infrasp at `level`

        :param level: 1-4
        """
        setattr(self, self.infrasp_attr[level]['rank'], rank)
        setattr(self, self.infrasp_attr[level]['epithet'], epithet)
        setattr(self, self.infrasp_attr[level]['author'], author)

    def as_dict(self, recurse=True):
        result = dict((col, getattr(self, col))
                      for col in list(self.__table__.columns.keys())
                      if col not in ['id', 'sp'] and
                      col[0] != '_' and
                      getattr(self, col) is not None and
                      not col.endswith('_id'))
        if result.get('full_name'):
            del result['full_name']
        result['object'] = 'taxon'
        result['rank'] = 'species'
        result['epithet'] = self.sp
        result['ht-rank'] = 'genus'
        result['ht-epithet'] = self.genus.genus
        if recurse and self.accepted is not None:
            result['accepted'] = self.accepted.as_dict(recurse=False)
        return result

    @classmethod
    def correct_field_names(cls, keys):
        for internal, exchange in [('sp_author', 'author'),
                                   ('sp', 'epithet')]:
            if exchange in keys:
                keys[internal] = keys[exchange]
                del keys[exchange]

    @classmethod
    def compute_serializable_fields(cls, session, keys):
        from .genus import Genus
        result = {'genus': None}
        # retrieve genus object
        specifies_family = keys.get('familia')
        result['genus'] = Genus.retrieve_or_create(
            session, {'epithet': keys['ht-epithet'],
                      'ht-epithet': specifies_family},
            create=(specifies_family is not None))
        if result['genus'] is None:
            raise error.NoResultException()
        return result

    def top_level_count(self):
        accessions = db.get_active_children('accessions', self)
        plants = [p for a in accessions for p in
                  db.get_active_children('plants', a)]
        return {(1, 'Species'): 1,
                (2, 'Genera'): set([self.genus.id]),
                (3, 'Families'): set([self.genus.family.id]),
                (4, 'Accessions'): len(accessions),
                (5, 'Plantings'): len(plants),
                (6, 'Living plants'): sum(p.quantity for p in plants),
                (7, 'Locations'): set(p.location.id for p in plants),
                (8, 'Sources'): set(a.source.source_detail.id for a in
                                    self.accessions if a.source and
                                    a.source.source_detail)}

    def has_children(self):
        cls = self.__class__.accessions.prop.mapper.class_
        from sqlalchemy import exists
        session = object_session(self)
        return bool(session.query(literal(True))
                    .filter(exists().where(cls.species_id == self.id))
                    .scalar())

    def count_children(self):
        cls = self.__class__.accessions.prop.mapper.class_
        session = object_session(self)
        from bauble import prefs
        query = session.query(cls.id).filter(cls.species_id == self.id)
        if prefs.prefs.get(prefs.exclude_inactive_pref):
            query = query.filter(cls.active.is_(True))
        return query.count()


# Listen for changes and update the full_name string
@event.listens_for(Species, 'before_update')
def species_before_update(_mapper, _connection, target):
    target.full_name = str(target)


@event.listens_for(Species, 'before_insert')
def species_before_insert(_mapper, _connection, target):
    target.full_name = str(target)


def update_all_full_names_task():
    """Task to update all the species full names.

    Yields occassionally to update the progress bar
    """
    from bauble import pb_set_fraction
    session = db.Session()
    query = session.query(Species)
    count = query.count()
    five_percent = int(count / 20) or 1
    for done, sp in enumerate(session.query(Species)):
        sp.full_name = str(sp)
        if done % five_percent == 0:
            session.commit()
            pb_set_fraction(done / count)
            yield
    session.close()


def update_all_full_names_handler(*_args):
    """Handler to update all the species full names."""
    from bauble.task import queue
    queue(update_all_full_names_task())


def as_dict(self):
    result = db.Serializable.as_dict(self)
    result['species'] = self.species.str(self.species, remove_zws=True)
    return result


def compute_serializable_fields(_cls, session, keys):
    logger.debug('compute_serializable_fields(session, %s)', keys)
    result = {}
    genus_name, epithet = keys['species'].split(' ', 1)
    sp_dict = {'ht-epithet': genus_name,
               'epithet': epithet}
    result['species'] = Species.retrieve_or_create(
        session, sp_dict, create=False)
    return result


def retrieve(cls, session, keys):
    from .genus import Genus
    genus, epithet = keys['species'].split(' ', 1)
    try:
        return (session.query(cls)
                .filter(cls.category == keys['category'])
                .join(Species)
                .filter(Species.sp == epithet)
                .join(Genus)
                .filter(Genus.genus == genus).one())
    except Exception:
        return None


SpeciesNote = db.make_note_class('Species', compute_serializable_fields,
                                 as_dict, retrieve)
SpeciesPicture = db.make_note_class('Species', compute_serializable_fields,
                                    as_dict, retrieve, cls_type='picture')


class SpeciesSynonym(db.Base):
    """
    :Table name: species_synonym
    """
    __tablename__ = 'species_synonym'
    __table_args__ = (CheckConstraint("species_id != synonym_id"),)

    # columns
    species_id = Column(Integer, ForeignKey('species.id'),
                        nullable=False)
    synonym_id = Column(Integer, ForeignKey('species.id'),
                        nullable=False, unique=True)

    def __str__(self):
        return str(self.synonym)


class VernacularName(db.Base, db.Serializable):
    """
    :Table name: vernacular_name

    :Columns:
        *name*:
            the vernacular name

        *language*:
            language is free text and could include something like UK
            or US to identify the origin of the name

        *species_id*:
            key to the species this vernacular name refers to

    :Properties:

    :Constraints:
    """
    __tablename__ = 'vernacular_name'
    name = Column(Unicode(128), nullable=False)
    language = Column(Unicode(128))
    species_id = Column(Integer, ForeignKey('species.id'), nullable=False)
    __table_args__ = (UniqueConstraint('name', 'language',
                                       'species_id', name='vn_index'), {})

    # NOTE 'id' is included in Species.retrieve_cols
    sp_retrieve_cols = [f'species.{i}' for i in Species.retrieve_cols]
    retrieve_cols = ['id', 'name', 'language'] + sp_retrieve_cols

    @classmethod
    def retrieve(cls, session, keys):
        # for json imports
        from .genus import Genus
        if sp_val := keys.get('species'):
            g_epithet, s_epithet = sp_val.split(' ', 1)
            sp = (session.query(Species)
                  .filter(Species.sp == s_epithet)
                  .join(Genus)
                  .filter(Genus.genus == g_epithet)
                  .first())
            if sp:
                from sqlalchemy.exc import SQLAlchemyError
                try:
                    # pylint: disable=no-member
                    return (session.query(cls)
                            .filter(cls.species == sp,
                                    cls.language == keys.get('language'))
                            .one())
                except SQLAlchemyError:
                    return None

        # for other imports
        s_parts = cls.sp_retrieve_cols
        sp_keys = {k.removeprefix('species.'): v for k, v in keys.items() if
                   k in s_parts}
        logger.debug(sp_keys)
        retrieved_sp = Species.retrieve(session, sp_keys)
        if sp_keys and not retrieved_sp:
            return None
        v_parts = ['id', 'name', 'language']
        vn_parts = {k: v for k, v in keys.items() if k in v_parts}
        query = session.query(cls)
        if vn_parts:
            query = query.filter_by(**vn_parts)
        if retrieved_sp:
            # NOTE log entry used in test
            logger.debug('retrieved species %s', retrieved_sp)
            query = query.join(Species).filter(Species.id == retrieved_sp.id)
        if vn_parts or retrieved_sp:
            from sqlalchemy.orm.exc import MultipleResultsFound
            try:
                return query.one_or_none()
            except MultipleResultsFound:
                return None
        return None

    def search_view_markup_pair(self):
        """provide the two lines describing object for SearchView row."""
        # pylint: disable=no-member
        return str(self), self.species.markup(authors=False)

    def __str__(self):
        return self.name or ''

    def as_dict(self):
        result = db.Serializable.as_dict(self)
        # pylint: disable=no-member
        result['species'] = self.species.str(self.species, remove_zws=True)
        return result

    @classmethod
    def compute_serializable_fields(cls, session, keys):
        logger.debug('compute_serializable_fields(session, %s)', keys)
        result = {'species': None}
        if 'species' in keys:
            # now we must connect the name to the species it refers to
            genus_name, epithet = keys['species'].split(' ', 1)
            sp_dict = {'ht-epithet': genus_name,
                       'epithet': epithet}
            result['species'] = Species.retrieve_or_create(
                session, sp_dict, create=False)
        return result

    @property
    def pictures(self):
        # pylint: disable=no-member
        return self.species.pictures

    def has_children(self):
        # pylint: disable=no-member
        return self.species.has_children()

    def count_children(self):
        # pylint: disable=no-member
        return self.species.count_children()


class DefaultVernacularName(db.Base):
    """
    :Table name: default_vernacular_name

    DefaultVernacularName is not meant to be instantiated directly.
    Usually the default vernacular name is set on a species by setting
    the default_vernacular_name property on Species to a
    VernacularName instance

    :Columns:
        *id*:
            Integer, primary_key

        *species_id*:
            foreign key to species.id, nullable=False

        *vernacular_name_id*:

    :Properties:

    :Constraints:
    """
    __tablename__ = 'default_vernacular_name'
    __table_args__ = (UniqueConstraint('species_id', 'vernacular_name_id',
                                       name='default_vn_index'), {})

    # columns
    species_id = Column(Integer, ForeignKey('species.id'), nullable=False)
    vernacular_name_id = Column(Integer, ForeignKey('vernacular_name.id'),
                                nullable=False)

    # relations
    vernacular_name = relationship(VernacularName, uselist=False)

    def __str__(self):
        return str(self.vernacular_name)


class SpeciesDistribution(db.Base):
    """
    :Table name: species_distribution

    :Columns:

    :Properties:

    :Constraints:
    """
    __tablename__ = 'species_distribution'

    # columns
    species_id = Column(Integer, ForeignKey('species.id'), nullable=False)
    geography_id = Column(Integer, ForeignKey('geography.id'), nullable=False)
    geography = relationship('Geography',
                             back_populates='distribution')

    def __str__(self):
        return str(self.geography)


class Habit(db.Base):
    __tablename__ = 'habit'

    name = Column(Unicode(64))
    code = Column(Unicode(8), unique=True)

    def __str__(self):
        if self.name:
            return f'{self.name} ({self.code})'
        return str(self.code)


class Color(db.Base):
    __tablename__ = 'color'

    name = Column(Unicode(32))
    code = Column(Unicode(8), unique=True)

    def __str__(self):
        if self.name:
            return f'{self.name} ({self.code})'
        return str(self.code)


db.Species = Species
db.SpeciesNote = SpeciesNote
db.SpeciesPicture = SpeciesPicture
db.VernacularName = VernacularName
