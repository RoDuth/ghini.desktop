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

import logging
import re
from functools import reduce
from itertools import chain
from operator import iconcat

logger = logging.getLogger(__name__)

from sqlalchemy import CheckConstraint
from sqlalchemy import Column
from sqlalchemy import ForeignKey
from sqlalchemy import Integer
from sqlalchemy import Unicode
from sqlalchemy import UnicodeText
from sqlalchemy import UniqueConstraint
from sqlalchemy import event
from sqlalchemy import literal
from sqlalchemy.ext.associationproxy import association_proxy
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import backref
from sqlalchemy.orm import object_session
from sqlalchemy.orm import relationship
from sqlalchemy.orm import synonym as sa_synonym
from sqlalchemy.sql.expression import and_
from sqlalchemy.sql.expression import case
from sqlalchemy.sql.expression import cast
from sqlalchemy.sql.expression import or_
from sqlalchemy.sql.expression import select
from sqlalchemy.sql.expression import text

from bauble import btypes as types
from bauble import db
from bauble import utils
from bauble.i18n import _

from .geography import DistributionMap


def _remove_zws(string):
    "remove_zero_width_space"
    if string:
        return string.replace("\u200b", "")
    return string


def _italicize_part(part):
    """If part is bracketed italicize just the contents of the brackets else
    the whole part"""
    if part.startswith("(") and part.endswith(")"):
        return f"({markup_italics(part[1:-1])})"
    return markup_italics(part)


def _markup_complex_hyb(string):
    """a helper function that splits a complex hybrid formula into its parts
    and italicizes the parts.

    :param string: string containing brackets surounding 2 phrases seperated by
        a cross/multipy symbol
    """
    # break apart the name parts
    prts = string.split("×")
    len_prts = len(prts)
    left = right = find = found = 0
    result = []
    # put the bracketed parts back together
    for i, prt in enumerate(prts):
        prt = prt.strip()
        if prt.startswith("("):
            # find is the amount of closing brackets we need to find to capture
            # the whole group
            find += len(prt) - len(prt.lstrip("("))
            left = i + 1 if not left else left
        if prt.endswith(")"):
            found += len(prt) - len(prt.rstrip(")"))
            if found == find:
                right = i + 1
        if right:
            result.append(
                "".join(j for j in prts[left - 1 : right])
                .strip()
                .replace("  ", " × ")
            )
            left = right = find = found = 0
        elif left == right == find == found == 0:
            result.append(prt)
        # what if we hit the end and still haven't found the matching bracket?
        # Just return what we can.
        elif i == len_prts - 1:
            result.append(
                "".join(j for j in prts[left - 1 :])
                .strip()
                .replace("  ", " × ")
            )

    # recompile adding the cross symbols back
    return " × ".join([_italicize_part(i) for i in result])


_RE_SIMPLE_SP = re.compile(r"^[a-z-]+$")
_RE_SIMPLE_HYB = re.compile("^[a-z-]+( × [a-z-]+)*$")
_RE_SIMPLE_CV = re.compile("^'[^×'\"]+'$")
_RE_SIMPLE_INFRA_HYB = re.compile("^×[a-z-]+$")
_RE_SIMPLE_PROV = re.compile(r"^sp. \([^×]+\)$")
_RE_SIMPLE_DESC = re.compile(r"^\([^×]*\)$")
_RE_COMPLEX_DESC = re.compile(r"^[a-z-]+ \([^×]+\)$")
_RE_COMPLEX_HYB = re.compile(r"\(.+×.+\)")
_RE_OTHER_HYB = re.compile(".+ × .+")


def markup_italics(string):
    """Add italics markup to the appropriate parts of a species string.

    :param string: the taxon name as a unicode string
    """
    # store the zws to reapply later (if used)
    if string.startswith("\u200b"):
        start = "\u200b"
        string = string.strip("\u200b")
    else:
        start = ""

    string = string.strip()
    result = ""
    # simple sp.
    if string == "sp.":
        result = f"{string}"
    # simple species
    elif _RE_SIMPLE_SP.match(string):
        result = f"<i>{string}</i>"
    # simple species hybrids (lowercase words separated by a multiplication
    # symbol)
    elif _RE_SIMPLE_HYB.match(string):
        result = f"<i>{string}</i>".replace(" × ", "</i> × <i>")
    # simple cultivar (starts and ends with a ' and can be almost have anything
    # between (except further quote symbols or multiplication symbols
    elif _RE_SIMPLE_CV.match(string):
        result = f"{string}"
    # simple infraspecific hybrid with nothospecies name
    elif _RE_SIMPLE_INFRA_HYB.match(string):
        result = f"{string[0]}<i>{string[1:]}</i>"
    # simple provisory or descriptor sp.
    elif _RE_SIMPLE_PROV.match(string):
        result = f"{string}"
    # simple descriptor (brackets surrounding anything without a multiplication
    # symbol)
    elif _RE_SIMPLE_DESC.match(string):
        result = f"{string}"

    # recursive parts
    # species with descriptor (part with only lower letters + space + bracketed
    # section)
    elif _RE_COMPLEX_DESC.match(string):
        result = " ".join([markup_italics(i) for i in string.split(" ", 1)])
    # complex hybrids (contains brackets surounding 2 phrases seperated by a
    # multipy symbol) These need to be reduce to less and less complex hybrids.
    elif _RE_COMPLEX_HYB.search(string):
        result = f"{_markup_complex_hyb(string)}"
    # any other type of hybrid (i.e. cv to species, provisory to cv, etc..) try
    # breaking it apart and italicizing the parts
    elif _RE_OTHER_HYB.match(string):
        parts = [i.strip() for i in string.split(" × ")]
        result = " × ".join([markup_italics(i) for i in parts])
    # anything else with spaces in it. Break them off one by one and try
    # identify the parts.
    elif " " in string:
        result = " ".join([markup_italics(i) for i in string.split(" ", 1)])
    # lastly, what to do if we just don't know... (infraspecific ranks etc.)
    else:
        result = string

    result = result.strip()
    return start + result


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


infrasp_rank_values = {
    "subsp.": _("subsp."),
    "var.": _("var."),
    "subvar.": _("subvar"),
    "f.": _("f."),
    "subf.": _("subf."),
    None: "",
}

red_list_values = {
    "EX": _("Extinct (EX)"),
    "EW": _("Extinct in the Wild (EW)"),
    "RE": _("Regionally Extinct (RE)"),
    "CR": _("Critically Endangered (CR)"),
    "EN": _("Endangered (EN)"),
    "VU": _("Vulnerable (VU)"),
    "NT": _("Near Threatened (NT)"),
    "LC": _("Least Concern (LC)"),
    "DD": _("Data Deficient (DD)"),
    "NE": _("Not Evaluated (NE)"),
    None: "",
}

# TODO: the specific epithet should not be non-nullable but instead
# make sure that at least one of the specific epithet, cultivar name
# or cultivar group is specificed


compare_rank = {
    "familia": 1,
    "subfamilia": 10,
    "tribus": 20,
    "subtribus": 30,
    "genus": 40,
    "subgenus": 50,
    "species": 60,
    "None": 70,
    "subsp.": 80,
    "var.": 90,
    "subvar.": 100,
    "f.": 110,
    "subf.": 120,
}


class Species(db.Base, db.WithNotes):
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

    __tablename__ = "species"
    __table_args__ = (UniqueConstraint("full_sci_name", name="sp_name"), {})

    # for internal use when importing records, accounts for the lack of
    # UniqueConstraint and the complex of hybrid_properties etc.
    uniq_props = [
        "genus",
        "genus_id",
        "sp",
        "epithet",
        "sp_author",
        "hybrid",
        "sp_qual",
        "infrasp1",
        "infrasp1_rank",
        "infrasp2",
        "infrasp2_rank",
        "infrasp3",
        "infrasp3_rank",
        "infrasp4",
        "infrasp4_rank",
        "infraspecific_parts",
        "infraspecific_epithet",
        "infraspecific_rank",
        "cultivar_epithet",
        "grex",
    ]

    rank = "species"
    link_keys = ["accepted"]

    # columns
    subgenus = Column(Unicode(64))
    section = Column(Unicode(64))
    subsection = Column(Unicode(64))
    series = Column(Unicode(64))
    subseries = Column(Unicode(64))

    sp = Column(Unicode(128), index=True)
    epithet = sa_synonym("sp")
    sp_author = Column(Unicode(128))
    hybrid = Column(types.Enum(values=["×", "+", None]), default=None)
    sp_qual = Column(
        types.Enum(values=["agg.", "s. lat.", "s. str.", None]), default=None
    )
    cv_group = Column(Unicode(50))
    trade_name = Column(Unicode(64))
    trademark_symbol = Column(Unicode(4))
    grex = Column(Unicode(64))
    pbr_protected = Column(types.Boolean, default=False)

    infrasp1 = Column(Unicode(64))
    infrasp1_rank = Column(
        types.Enum(
            values=list(infrasp_rank_values.keys()),
            translations=infrasp_rank_values,
        )
    )
    infrasp1_author = Column(Unicode(64))

    infrasp2 = Column(Unicode(64))
    infrasp2_rank = Column(
        types.Enum(
            values=list(infrasp_rank_values.keys()),
            translations=infrasp_rank_values,
        )
    )
    infrasp2_author = Column(Unicode(64))

    infrasp3 = Column(Unicode(64))
    infrasp3_rank = Column(
        types.Enum(
            values=list(infrasp_rank_values.keys()),
            translations=infrasp_rank_values,
        )
    )
    infrasp3_author = Column(Unicode(64))

    infrasp4 = Column(Unicode(64))
    infrasp4_rank = Column(
        types.Enum(
            values=list(infrasp_rank_values.keys()),
            translations=infrasp_rank_values,
        )
    )
    infrasp4_author = Column(Unicode(64))

    cultivar_epithet = Column(Unicode(64))

    genus_id = Column(Integer, ForeignKey("genus.id"), nullable=False)
    # the Species.genus property is defined as backref in Genus.species

    label_distribution = Column(UnicodeText)
    label_markup = Column(UnicodeText)

    # relations
    synonyms = association_proxy(
        "_synonyms", "synonym", creator=lambda sp: SpeciesSynonym(synonym=sp)
    )
    _synonyms = relationship(
        "SpeciesSynonym",
        primaryjoin="Species.id==SpeciesSynonym.species_id",
        cascade="all, delete-orphan",
        uselist=True,
        backref="species",
    )

    # make cascading work
    _accepted = relationship(
        "SpeciesSynonym",
        primaryjoin="Species.id==SpeciesSynonym.synonym_id",
        cascade="all, delete-orphan",
        uselist=False,
        backref="synonym",
    )
    accepted = association_proxy(
        "_accepted", "species", creator=lambda sp: SpeciesSynonym(species=sp)
    )

    # VernacularName.species gets defined here too.
    vernacular_names = relationship(
        "VernacularName",
        cascade="all, delete-orphan",
        collection_class=VNList,
        backref=backref("species", uselist=False),
    )
    _default_vernacular_name = relationship(
        "DefaultVernacularName",
        uselist=False,
        cascade="all, delete-orphan",
        backref=backref("species", uselist=False),
    )
    distribution = relationship(
        "SpeciesDistribution",
        cascade="all, delete-orphan",
        backref=backref("species", uselist=False),
    )

    habit_id = Column(Integer, ForeignKey("habit.id"), default=None)
    habit = relationship("Habit", uselist=False, backref="species")

    flower_color_id = Column(Integer, ForeignKey("color.id"), default=None)
    flower_color = relationship("Color", uselist=False, backref="species")

    full_name = Column(Unicode(512), index=True)
    full_sci_name = Column(Unicode(512), index=True)

    # hardiness_zone = Column(Unicode(4))

    awards = Column(UnicodeText)

    # see retrieve classmethod.
    retrieve_cols = uniq_props + ["id", "genus.genus", "genus.epithet"]

    _cites = Column(types.Enum(values=["I", "II", "III", None]), default=None)
    red_list = Column(
        types.Enum(
            values=list(red_list_values.keys()), translations=red_list_values
        )
    )

    _sp_custom1 = Column(types.CustomEnum(64))
    _sp_custom2 = Column(types.CustomEnum(64))
    # don't use back_populates, can lead to InvalidRequestError
    # accessions = relationship('Accession', cascade='all, delete-orphan',
    #                           back_populates='species')

    @classmethod
    def retrieve(cls, session, keys):
        logger.debug("retrieve species with keys %s", keys)
        from .genus import Genus

        parts = cls.uniq_props[:]
        parts.remove("genus")
        parts.append("id")

        sp_parts = {k: v for k, v in keys.items() if k in parts}

        if not sp_parts:
            return None

        logger.debug("sp_parts in keys %s", sp_parts)
        gen = (
            keys.get("genus")
            or keys.get("genus.genus")
            or keys.get("genus.epithet")
        )

        logger.debug(
            "retrieve species with sp_parts %s and genus %s", sp_parts, gen
        )

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
                vnames = ", ".join([str(v) for v in self.vernacular_names])
                substring = f"{self.genus.family} -- {vnames}"
            else:
                substring = f"{self.genus.family}"
            trail = ""
            if self.accepted:
                trail += (
                    '<span foreground="#555555" size="small" '
                    'weight="light"> - ' + _("synonym of %s") + "</span>"
                ) % self.accepted.markup(authors=True)
            citation = self.markup(authors=True, for_search_view=True)
            return citation + trail, substring
        except Exception:  # pylint: disable=broad-except
            return "...", "..."

    @hybrid_property
    def cites(self):
        """the cites status of this taxon, or None

        cites appendix number, one of I, II, or III.
        """
        return self._cites or self.genus.cites

    @cites.expression
    def cites(cls):
        # pylint: disable=no-self-argument,protected-access
        from .family import Family
        from .genus import Genus

        # subqueries required to get the joins in
        gen_cites = (
            select([Genus._cites])
            .where(cls.genus_id == Genus.id)
            .scalar_subquery()
        )
        fam_cites = (
            select([Family.cites])
            .where(cls.genus_id == Genus.id)
            .where(Genus.family_id == Family.id)
            .scalar_subquery()
        )
        return case(
            (cls._cites.is_not(None), cls._cites),
            (gen_cites.is_not(None), gen_cites),
            else_=fam_cites,
        )

    @cites.setter
    def cites(self, value):
        self._cites = value

    @property
    def condition(self):
        """the condition of this taxon, or None

        this is referred to what the garden conservator considers the
        area of interest. it is really an interpretation, not a fact.
        """
        # one of, but not forcibly so:
        # [_('endemic'), _('indigenous'), _('native'), _('introduced')]

        notes = [
            i.note for i in self.notes if i.category.lower() == "condition"
        ]
        return (notes + [None])[0]

    def __lowest_infraspecific(self):
        infrasp = [
            (self.infrasp1_rank, self.infrasp1, self.infrasp1_author),
            (self.infrasp2_rank, self.infrasp2, self.infrasp2_author),
            (self.infrasp3_rank, self.infrasp3, self.infrasp3_author),
            (self.infrasp4_rank, self.infrasp4, self.infrasp4_author),
        ]
        infrasp = [i for i in infrasp if i[0] not in ["cv.", "", None]]
        if infrasp == []:
            return ("", "", "")
        return sorted(infrasp, key=lambda a: compare_rank.get(str(a[0]), 150))[
            -1
        ]

    @hybrid_property
    def infraspecific_rank(self):
        return self.__lowest_infraspecific()[0] or ""

    @infraspecific_rank.expression
    def infraspecific_rank(cls):
        # pylint: disable=no-self-argument
        # use the last epithet that is not 'cv'. available (the user should be
        # keeping their infraspecific parts in order)
        return case(
            [
                (cls.infrasp4_rank.is_not(None), cls.infrasp4_rank),
                (cls.infrasp3_rank.is_not(None), cls.infrasp3_rank),
                (cls.infrasp2_rank.is_not(None), cls.infrasp2_rank),
                (cls.infrasp1_rank.is_not(None), cls.infrasp1_rank),
            ]
        ).label("infraspecific_rank")

    @hybrid_property
    def infraspecific_epithet(self):
        return self.__lowest_infraspecific()[1] or ""

    @infraspecific_epithet.expression
    def infraspecific_epithet(cls):
        # pylint: disable=no-self-argument
        # use the last epithet that is not 'cv'.
        return case(
            [
                (cls.infrasp4_rank.is_not(None), cls.infrasp4),
                (cls.infrasp3_rank.is_not(None), cls.infrasp3),
                (cls.infrasp2_rank.is_not(None), cls.infrasp2),
                (cls.infrasp1_rank.is_not(None), cls.infrasp1),
            ]
        ).label("infraspecific_epithet")

    @property
    def infraspecific_author(self):
        return self.__lowest_infraspecific()[2] or ""

    @hybrid_property
    def infraspecific_parts(self):
        parts = []
        for rank, epithet in [
            (self.infrasp1_rank, self.infrasp1),
            (self.infrasp2_rank, self.infrasp2),
            (self.infrasp3_rank, self.infrasp3),
            (self.infrasp4_rank, self.infrasp4),
        ]:
            if rank not in [None, "", "cv."]:
                parts.append(rank)
                parts.append(epithet)
        parts = " ".join(parts)
        return parts

    @infraspecific_parts.expression
    def infraspecific_parts(cls):
        # pylint: disable=no-self-argument
        from sqlalchemy.types import String

        return case(
            [
                (
                    cls.infrasp4_rank.is_not(None),
                    cast(
                        cls.infrasp1_rank
                        + text("' '")
                        + cls.infrasp1
                        + text("' '")
                        + cls.infrasp2_rank
                        + text("' '")
                        + cls.infrasp2
                        + text("' '")
                        + cls.infrasp3_rank
                        + text("' '")
                        + cls.infrasp3
                        + text("' '")
                        + cls.infrasp4_rank
                        + text("' '")
                        + cls.infrasp4,
                        String,
                    ),
                ),
                (
                    cls.infrasp3_rank.is_not(None),
                    cast(
                        cls.infrasp1_rank
                        + text("' '")
                        + cls.infrasp1
                        + text("' '")
                        + cls.infrasp2_rank
                        + text("' '")
                        + cls.infrasp2
                        + text("' '")
                        + cls.infrasp3_rank
                        + text("' '")
                        + cls.infrasp3,
                        String,
                    ),
                ),
                (
                    cls.infrasp2_rank.is_not(None),
                    cast(
                        cls.infrasp1_rank
                        + text("' '")
                        + cls.infrasp1
                        + text("' '")
                        + cls.infrasp2_rank
                        + text("' '")
                        + cls.infrasp2,
                        String,
                    ),
                ),
                (
                    cls.infrasp1_rank.is_not(None),
                    cast(
                        cls.infrasp1_rank + text("' '") + cls.infrasp1, String
                    ),
                ),
            ]
        ).label("infraspecific_parts")

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
            .where(
                and_(
                    DefaultVernacularName.species_id == cls.id,
                    VernacularName.id
                    == DefaultVernacularName.vernacular_name_id,
                )
            )
            .label("default_vernacular_name")
        )

    @default_vernacular_name.setter
    def default_vernacular_name(self, vernacular):
        if isinstance(vernacular, str):
            logger.debug("vernacular_name is a string: %s", vernacular)
            lang = None
            if ":" in vernacular:
                vernacular, lang = vernacular.split(":")
            kwargs = {"name": vernacular, "species": self}
            if lang:
                kwargs["language"] = lang
            vnobj = None
            session = object_session(self)
            if session:
                vnobj = db.get_create_or_update(
                    session, VernacularName, **kwargs
                )
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

    @hybrid_property
    def family_name(self):
        return self.genus.family.epithet

    @family_name.expression
    def family_name(cls):
        # pylint: disable=no-self-argument
        from .family import Family
        from .genus import Genus

        return (
            select([Family.epithet])
            .where(Genus.id == cls.genus_id)
            .where(Genus.family_id == Family.id)
            .label("family_name")
        )

    def distribution_str(self):
        if self.distribution is None:
            return ""
        dist = [f"{d}" for d in self.distribution]
        return str(", ").join(sorted(dist))

    def markup(self, authors=False, genus=True, for_search_view=False):
        """returns this object as a string with markup

        :param authors: whether the authorship should be included
        :param genus: whether the genus name should be included
        :param for_search_view: in search view authorship is in light text
        """
        return self.str(
            authors, markup=True, genus=genus, for_search_view=for_search_view
        )

    def __str__(self):
        """return the default string representation for self."""
        return self.str()

    def str(
        self,
        authors=False,
        markup=False,
        remove_zws=True,
        genus=True,
        qualification=None,
        for_search_view=False,
    ):
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

        if qualifier == "incorrect":
            qual_rank = None

        if inspect(self).detached:
            session = db.Session()
            session.enable_relationship_loading(self)
        if genus is True:
            genus = ""
            if qual_rank == "genus":
                genus = qualifier + " "
            if markup:
                genus += self.genus.markup()
            else:
                genus += str(self.genus)
        else:
            genus = ""
        if session:
            session.close()

        if self.sp and not remove_zws:
            sp = "\u200b" + self.sp  # prepend with zero_width_space
        else:
            sp = self.sp

        if markup:
            escape = utils.xml_safe
            italicize = markup_italics
            if sp is not None:
                sp = italicize(escape(sp))
        else:
            italicize = escape = lambda x: x

        if self.hybrid:
            sp = self.hybrid + " " + sp

        if qual_rank == "sp":
            sp = qualifier + " " + sp

        author = None
        if authors and self.sp_author:
            author = escape(self.sp_author)
            if for_search_view:
                author = '<span weight="light">' + author + "</span>"

        infrasp = (
            (self.infrasp1_rank, self.infrasp1, self.infrasp1_author),
            (self.infrasp2_rank, self.infrasp2, self.infrasp2_author),
            (self.infrasp3_rank, self.infrasp3, self.infrasp3_author),
            (self.infrasp4_rank, self.infrasp4, self.infrasp4_author),
        )

        infrasp_parts = []
        for level, (rank, epithet, iauthor) in enumerate(infrasp, 1):
            if qual_rank == f"infrasp{level}" and any([rank, epithet]):
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
                    iauthor = '<span weight="light">' + iauthor + "</span>"
                infrasp_parts.append(iauthor)

        if self.grex:
            infrasp_parts.append(self.grex)

        if self.cv_group:
            if self.cultivar_epithet:
                infrasp_parts.append(
                    _("(%(group)s Group)") % dict(group=self.cv_group)
                )
            else:
                infrasp_parts.append(
                    _("%(group)s Group") % dict(group=self.cv_group)
                )

        if self.cultivar_epithet and qual_rank == "cv":
            infrasp_parts.append(qualifier)

        if self.cultivar_epithet in ("cv.", "cvs."):
            infrasp_parts.append(self.cultivar_epithet)
        elif self.cultivar_epithet:
            infrasp_parts.append(f"'{escape(self.cultivar_epithet)}'")

        if self.pbr_protected:
            pbr = "(PBR)"
            if markup:
                # would like to use <sup> here but get
                # Pango-WARNING **: Leftover font scales
                pbr = f"<small>{pbr}</small>"
            if for_search_view:
                pbr = f'<span weight="light">{pbr}</span>'
            infrasp_parts.append(pbr)

        def _small_caps(txt):
            # using <span variant="smallcaps"> pango can have trouble finding
            # the right fonts in macos at least  This approach achieves
            # acceptable results without having concerns about the font.
            result = ""
            small = False
            for i in txt:
                if i.isupper():
                    if small:
                        result += "</small>"
                        small = False
                    result += i
                else:
                    if not small:
                        result += "<small>"
                        small = True
                    result += i.upper()

            if small:
                result += "</small>"

            return result

        if self.trade_name:
            trade_name = escape(self.trade_name)
            if markup:
                infrasp_parts.append(
                    _small_caps(trade_name) + (self.trademark_symbol or "")
                )
            else:
                infrasp_parts.append(
                    trade_name.upper() + (self.trademark_symbol or "")
                )

        # create the binomial part
        binomial = [genus, sp, author]

        # create the tail, ie: anything to add on to the end
        tail = []
        if not qual_rank and qualifier:
            tail.append(f"({qualifier})")
        if self.sp_qual:
            tail.append(self.sp_qual)

        parts = chain(binomial, infrasp_parts, tail)
        string = " ".join(i for i in parts if i)
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
        active = (
            select([cls.id])
            .outerjoin(acc_cls)
            .outerjoin(plt_cls)
            .where(or_(plt_cls.id.is_(None), plt_cls.quantity > 0))
            .scalar_subquery()
        )
        return cast(case([(cls.id.in_(active), 1)], else_=0), types.Boolean)

    @property
    def pictures(self) -> list:
        """Return pictures from any attached plants and any in _pictures."""
        pics = [a.pictures for a in self.accessions]
        plant_pics: list = reduce(iconcat, pics, [])
        return plant_pics + self._pictures

    infrasp_attr = {
        1: {
            "rank": "infrasp1_rank",
            "epithet": "infrasp1",
            "author": "infrasp1_author",
        },
        2: {
            "rank": "infrasp2_rank",
            "epithet": "infrasp2",
            "author": "infrasp2_author",
        },
        3: {
            "rank": "infrasp3_rank",
            "epithet": "infrasp3",
            "author": "infrasp3_author",
        },
        4: {
            "rank": "infrasp4_rank",
            "epithet": "infrasp4",
            "author": "infrasp4_author",
        },
    }

    def get_infrasp(self, level):
        """Get the 3 fields of infrasp at `level` as a tuple

        :param level: 1-4
        """
        return (
            getattr(self, self.infrasp_attr[level]["rank"]),
            getattr(self, self.infrasp_attr[level]["epithet"]),
            getattr(self, self.infrasp_attr[level]["author"]),
        )

    def set_infrasp(self, level, rank, epithet, author=None):
        """set the rank, epithet and author fields of infrasp at `level`

        :param level: 1-4
        """
        setattr(self, self.infrasp_attr[level]["rank"], rank)
        setattr(self, self.infrasp_attr[level]["epithet"], epithet)
        setattr(self, self.infrasp_attr[level]["author"], author)

    def distribution_map(self) -> DistributionMap:
        return DistributionMap([i.geography.id for i in self.distribution])

    def top_level_count(self):
        accessions = db.get_active_children("accessions", self)
        plants = [
            p for a in accessions for p in db.get_active_children("plants", a)
        ]
        return {
            (1, "Species"): 1,
            (2, "Genera"): set([self.genus.id]),
            (3, "Families"): set([self.genus.family.id]),
            (4, "Accessions"): len(accessions),
            (5, "Plantings"): len(plants),
            (6, "Living plants"): sum(p.quantity for p in plants),
            (7, "Locations"): set(p.location.id for p in plants),
            (8, "Sources"): set(
                a.source.source_detail.id
                for a in self.accessions
                if a.source and a.source.source_detail
            ),
        }

    def has_children(self):
        cls = self.__class__.accessions.prop.mapper.class_
        from sqlalchemy import exists

        session = object_session(self)
        return bool(
            session.query(literal(True))
            .filter(exists().where(cls.species_id == self.id))
            .scalar()
        )

    def count_children(self):
        cls = self.__class__.accessions.prop.mapper.class_
        session = object_session(self)
        from bauble import prefs

        query = session.query(cls.id).filter(cls.species_id == self.id)
        if prefs.prefs.get(prefs.exclude_inactive_pref):
            query = query.filter(cls.active.is_(True))
        return query.count()


# Listen for changes and update the full_name strings
@event.listens_for(Species, "before_update")
def species_before_update(_mapper, _connection, target):
    target.full_name = str(target)
    target.full_sci_name = target.str(authors=True)


@event.listens_for(Species, "before_insert")
def species_before_insert(_mapper, _connection, target):
    target.full_name = str(target)
    target.full_sci_name = target.str(authors=True)


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
        sp.full_sci_name = sp.str(authors=True)
        if done % five_percent == 0:
            session.commit()
            pb_set_fraction(done / count)
            yield
    session.commit()
    session.close()


def update_all_full_names_handler(*_args):
    """Handler to update all the species full names."""
    import traceback

    from gi.repository import Gtk

    from bauble.task import queue

    try:
        queue(update_all_full_names_task())
    except Exception as e:  # pylint: disable=broad-except
        utils.message_details_dialog(
            utils.xml_safe(str(e)),
            traceback.format_exc(),
            Gtk.MessageType.ERROR,
        )
        logger.debug(traceback.format_exc())


SpeciesNote = db.make_note_class("Species")
SpeciesPicture = db.make_note_class("Species", cls_type="_picture")


class SpeciesSynonym(db.Base):
    """
    :Table name: species_synonym
    """

    __tablename__ = "species_synonym"
    __table_args__ = (CheckConstraint("species_id != synonym_id"),)

    # columns
    species_id = Column(Integer, ForeignKey("species.id"), nullable=False)
    synonym_id = Column(
        Integer, ForeignKey("species.id"), nullable=False, unique=True
    )
    is_one_to_one = True

    def __str__(self):
        return str(self.synonym)


class VernacularName(db.Base):
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

    __tablename__ = "vernacular_name"
    name = Column(Unicode(128), nullable=False)
    language = Column(Unicode(128))
    species_id = Column(Integer, ForeignKey("species.id"), nullable=False)
    __table_args__ = (
        UniqueConstraint("name", "language", "species_id", name="vn_index"),
        {},
    )

    # NOTE 'id' is included in Species.retrieve_cols
    sp_retrieve_cols = [f"species.{i}" for i in Species.retrieve_cols]
    retrieve_cols = ["id", "name", "language"] + sp_retrieve_cols

    @classmethod
    def retrieve(cls, session, keys):
        s_parts = cls.sp_retrieve_cols
        sp_keys = {
            k.removeprefix("species."): v
            for k, v in keys.items()
            if k in s_parts
        }
        logger.debug(sp_keys)
        retrieved_sp = Species.retrieve(session, sp_keys)
        if sp_keys and not retrieved_sp:
            return None
        v_parts = ["id", "name", "language"]
        vn_parts = {k: v for k, v in keys.items() if k in v_parts}
        query = session.query(cls)
        if vn_parts:
            query = query.filter_by(**vn_parts)
        if retrieved_sp:
            # NOTE log entry used in test
            logger.debug("retrieved species %s", retrieved_sp)
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
        return self.name or ""

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

    __tablename__ = "default_vernacular_name"
    __table_args__ = (
        UniqueConstraint(
            "species_id", "vernacular_name_id", name="default_vn_index"
        ),
        {},
    )

    # columns
    species_id = Column(Integer, ForeignKey("species.id"), nullable=False)
    vernacular_name_id = Column(
        Integer, ForeignKey("vernacular_name.id"), nullable=False
    )

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

    __tablename__ = "species_distribution"

    # columns
    species: Species
    species_id = Column(Integer, ForeignKey("species.id"), nullable=False)
    geography_id = Column(Integer, ForeignKey("geography.id"), nullable=False)
    geography = relationship("Geography", back_populates="distribution")

    def __str__(self):
        return str(self.geography)


class Habit(db.Base):
    __tablename__ = "habit"

    name = Column(Unicode(64))
    code = Column(Unicode(8), unique=True)

    def __str__(self):
        if self.name:
            return f"{self.name} ({self.code})"
        return str(self.code)


class Color(db.Base):
    __tablename__ = "color"

    name = Column(Unicode(32))
    code = Column(Unicode(8), unique=True)

    def __str__(self):
        if self.name:
            return f"{self.name} ({self.code})"
        return str(self.code)


db.Species = Species
db.SpeciesNote = SpeciesNote
db.SpeciesPicture = SpeciesPicture
db.VernacularName = VernacularName
