# Copyright 2008-2010 Brett Adams
# Copyright 2015 Mario Frasca <mario@anche.no>.
# Copyright 2017 Jardín Botánico de Quito
# Copyright 2020-2026 Ross Demuth <rossdemuth123@gmail.com>
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
Genera table module
"""

import logging

logger = logging.getLogger(__name__)

import os
import traceback
from datetime import datetime
from typing import Self
from typing import cast as t_cast

from gi.repository import Gtk  # noqa
from sqlalchemy import CheckConstraint
from sqlalchemy import Column
from sqlalchemy import ForeignKey
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy import Unicode
from sqlalchemy import UniqueConstraint
from sqlalchemy import and_
from sqlalchemy import case
from sqlalchemy import cast
from sqlalchemy import event
from sqlalchemy import exists
from sqlalchemy import func
from sqlalchemy import inspect as sa_inspect
from sqlalchemy import literal
from sqlalchemy import or_
from sqlalchemy import select
from sqlalchemy import union
from sqlalchemy import update
from sqlalchemy.engine import Connection
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.associationproxy import association_proxy
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import Session
from sqlalchemy.orm import backref
from sqlalchemy.orm import object_mapper
from sqlalchemy.orm import relationship
from sqlalchemy.orm import synonym as sa_synonym
from sqlalchemy.orm.exc import MultipleResultsFound
from sqlalchemy.orm.query import Query
from sqlalchemy.orm.session import object_session

import bauble
from bauble import btypes as types
from bauble import db
from bauble import editor
from bauble import error
from bauble import paths
from bauble import prefs
from bauble import utils
from bauble.i18n import _
from bauble.ui.presenter import Response

from .model import Synonym
from .model import Taxon

# TODO: warn the user that a duplicate genus name is being entered
# even if only the author or qualifier is different


class Genus(Taxon, db.WithNotes):
    """
    :Table name: genus

    :Columns:
        *genus*:
            The name of the genus.  In addition to standard generic
            names any additional hybrid flags or genera should included here.

        *qualifier*:
            Designates the botanical status of the genus.

            Possible values:
                * s. lat.: aggregrate genus (sensu lato)

                * s. str.: segregate genus (sensu stricto)

        *author*:
            The name or abbreviation of the author who published this genus.

    :Properties:
        *family*:
            The family of the genus.

        *synonyms*:
            The list of genera who are synonymous with this genus.  If
            a genus is listed as a synonym of this genus then this
            genus should be considered the current and valid name for
            the synonym.

    :Contraints:
        The combination of genus, author, qualifier and family_id must be
        unique.
    """

    __tablename__ = "genus"
    __table_args__: tuple = (
        UniqueConstraint("genus", "author", "qualifier", "family_id"),
        {},
    )

    rank = "genus"
    link_keys = ["accepted"]

    # columns
    hybrid: str = Column(types.Enum(values=["×", "+", None]), default=None)

    subfamily: str = Column(Unicode(64))
    tribe: str = Column(Unicode(64))
    subtribe: str = Column(Unicode(64))

    genus: str = Column(String(64), nullable=False, index=True)
    epithet: str = sa_synonym("genus")

    # use '' instead of None so that the constraints will work propertly
    author: str = Column(Unicode(128), default="")

    qualifier: str = Column(
        types.Enum(values=["s. lat.", "s. str", ""]), default=""
    )

    family_id: int = Column(Integer, ForeignKey("family.id"), nullable=False)

    # relations
    # `species` relation is defined outside of `Genus` class definition
    synonyms = association_proxy(
        "_synonyms", "synonym", creator=lambda gen: GenusSynonym(synonym=gen)
    )
    _synonyms: list["GenusSynonym"] = relationship(
        "GenusSynonym",
        primaryjoin="Genus.id==GenusSynonym.genus_id",
        cascade="all, delete-orphan",
        uselist=True,
        backref="genus",
    )

    # this is a dummy relation, it is only here to make cascading work
    # correctly and to ensure that all synonyms related to this genus
    # get deleted if this genus gets deleted
    _accepted: "GenusSynonym" = relationship(
        "GenusSynonym",
        primaryjoin="Genus.id==GenusSynonym.synonym_id",
        cascade="all, delete-orphan",
        uselist=False,
        backref="synonym",
    )
    accepted = association_proxy(
        "_accepted", "genus", creator=lambda gen: GenusSynonym(genus=gen)
    )

    species: list["Species"] = relationship(
        "Species",
        cascade="all, delete-orphan",
        order_by="Species.sp",
        backref=backref("genus", lazy="subquery", uselist=False),
    )
    family: "Family" = relationship("Family", back_populates="genera")

    _cites: str = Column(
        types.Enum(values=["I", "II", "III", None]), default=None
    )

    retrieve_cols = [
        "id",
        "epithet",
        "genus",
        "hybrid",
        "author",
        "family",
        "family.epithet",
        "family.family",
    ]

    @classmethod
    def retrieve(cls, session: Session, keys: dict) -> Self | None:
        parts = ["id", "epithet", "genus", "hybrid", "author"]

        gen_parts = {k: v for k, v in keys.items() if k in parts}

        if not gen_parts:
            return None

        query = session.query(cls).filter_by(**gen_parts)
        fam = (
            keys.get("family.epithet")
            or keys.get("family.family")
            or keys.get("family")
        )

        if fam:
            query.join(Family).filter(Family.family == fam)

        try:
            return query.one_or_none()
        except MultipleResultsFound:
            return None
        return None

    def search_view_markup_pair(self) -> tuple[str, str]:
        """provide the two lines describing object for SearchView row."""
        citation = self.markup(authors=True, for_search_view=True)
        return citation, utils.xml_safe(self.family)

    @property
    def pictures(self) -> list[db.Picture]:
        session = object_session(self)
        if not isinstance(session, Session):
            return []
        # avoid circular imports
        from ..garden import Accession
        from ..garden import Plant
        from ..garden.plant import PlantPicture
        from .species_model import SpeciesPicture

        sp_pics = (
            session.query(SpeciesPicture)
            .join(Species, Genus)
            .filter(Genus.id == self.id)
        )
        plt_pics = (
            session.query(PlantPicture)
            .join(Plant, Accession, Species, Genus)
            .filter(Genus.id == self.id)
        )
        if prefs.prefs.get(prefs.exclude_inactive_pref):
            plt_pics = plt_pics.filter(Plant.active.is_(True))  # type: ignore [attr-defined] # noqa
        return sp_pics.all() + plt_pics.all()

    @hybrid_property
    def cites(self) -> str | None:
        """the cites status of this taxon, or None

        cites appendix number, one of I, II, or III.
        """
        return self._cites or self.family.cites

    @cites.expression  # type: ignore [no-redef]
    def cites(cls) -> types.Enum | None:
        # pylint: disable=no-self-argument,protected-access
        # subquery required to get the joins in
        fam_cites = (
            select([Family.cites])
            .where(cls.family_id == Family.id)
            .scalar_subquery()
        )
        return case((cls._cites.is_not(None), cls._cites), else_=fam_cites)

    @cites.setter  # type: ignore [no-redef]
    def cites(self, value: str | None) -> None:
        self._cites = value

    def __str__(self) -> str:
        return self.string()

    def string(self, **kwargs) -> str:
        """Return the string representation of the genus.

        :param author: bool, include the author in the string
        :param sensu: bool, include the qualifier in the string
        """

        if self.genus is None:
            return ""

        author = kwargs.get("author", False)
        sensu = kwargs.get("sensu", True)

        parts = [self.hybrid, self.genus]

        if sensu:
            parts.append(self.qualifier)

        if author and self.author:
            parts.append(self.author)

        return " ".join([str(s) for s in parts if s not in ("", None)]).strip()

    @property
    def str_basic(self) -> str:
        """Return the base string, without authors or qualifiers. i.e. just the
        name part (including the hybrid flag).

        Handy for link buttons (where a species qualifier can cause issues with
        searches), reports, etc.
        """
        return self.string(author=False, sensu=False)

    def markup(
        self,
        authors: bool = False,
        for_search_view: bool = False,
        sensu: bool = True,
    ) -> str:
        escape = utils.xml_safe
        string = ""
        if self.hybrid:
            string += self.hybrid + " "
        if self.genus.isupper():
            string += escape(self.genus)
        else:
            string += f"<i>{escape(self.genus)}</i>"
        if self.qualifier and sensu:
            string += " " + self.qualifier
        if authors and self.author:
            author = escape(self.author)
            if for_search_view:
                author = '<span weight="light">' + author + "</span>"
            string += " " + author
        return string

    @hybrid_property
    def active(self) -> bool:
        """False when all accessions have been deaccessioned
        (e.g. all plants have died)
        """
        for spp in self.species:
            if spp.active:
                return True
        return False

    @active.expression  # type: ignore [no-redef]
    def active(cls) -> types.Boolean:
        # pylint: disable=no-self-argument,no-self-use,arguments-renamed
        from ..garden import Accession
        from ..garden import Plant

        active = (
            select([cls.id])
            .join(Species)
            .outerjoin(Accession)
            .outerjoin(Plant)
            .where(or_(Plant.id.is_(None), Plant.quantity > 0))
            .scalar_subquery()
        )
        return cast(case([(cls.id.in_(active), 1)], else_=0), types.Boolean)

    @hybrid_property
    def updated(self) -> datetime:
        updates = [self._last_updated]

        if self._accepted:
            updates.append(self._accepted._last_updated)

        if self.notes:
            updates.append(max(i._last_updated for i in self.notes))

        return max(updates)

    @updated.expression  # type: ignore [no-redef]
    def updated(cls) -> types.DateTime:
        # pylint: disable=no-self-argument,no-self-use,arguments-renamed
        self_select = select([cls._last_updated, cls.id])

        note_select = select([GenusNote._last_updated, cls.id]).join(cls)

        accepted_select = select([GenusSynonym._last_updated, cls.id]).join(
            cls, cls.id == GenusSynonym.synonym_id
        )

        dates = union(self_select, note_select, accepted_select).alias("dates")

        return (
            select([func.max(dates.c._last_updated)])
            .where(dates.c.id == cls.id)
            .label("updated")
        )

    @classmethod
    def top_level_count(
        cls,
        ids: list[int],
        exclude_inactive: bool = False,
    ) -> db.TopLevelCount:

        from ..garden import Accession
        from ..garden import Location
        from ..garden import Plant
        from ..garden import Source
        from ..garden import SourceDetail

        base_ids_stmt = (
            select(
                Family.id,
                cls.id,
                Species.id,
                Accession.id,
                Plant.id,
                Location.id,
                SourceDetail.id,
            )
            .select_from(cls)
            .join(Family)
            .outerjoin(Species)
            .outerjoin(Accession)
            .outerjoin(Plant)
            .outerjoin(Location)
            .outerjoin(Source)
            .outerjoin(SourceDetail)
        )

        base_count_stmt = (
            select(
                func.sum(Plant.quantity),
            )
            .select_from(cls)
            .join(Species)
            .join(Accession)
            .join(Plant)
        )

        if exclude_inactive:
            # pylint: disable=no-member
            base_ids_stmt = base_ids_stmt.where(
                Accession.active.is_(True),  # type: ignore [attr-defined]
            )

        result = cls._top_level_counter_helper(
            base_ids_stmt, base_count_stmt, ids
        )
        return db.TopLevelCount(*result)

    def has_children(self) -> bool:

        session = object_session(self)
        if not isinstance(session, Session):
            raise error.DatabaseError("Could not connect to database session.")

        query = session.query(literal(True))

        if prefs.prefs.get(prefs.exclude_inactive_pref):
            # pylint: disable=no-member,line-too-long
            query = query.filter(
                exists().where(
                    and_(
                        Species.genus_id == self.id,
                        Species.active.is_(True),  # type: ignore [attr-defined] # noqa
                    )
                )
            )
        else:
            query = query.filter(exists().where(Species.genus_id == self.id))

        # bool converts None to False
        return bool(query.scalar())

    def count_children(self) -> int:
        cls = self.__class__.species.prop.mapper.class_

        session = object_session(self)
        if not isinstance(session, Session):
            raise error.DatabaseError("Could not connect to database session.")

        query = session.query(cls.id).filter(cls.genus_id == self.id)

        if prefs.prefs.get(prefs.exclude_inactive_pref):
            query = query.filter(cls.active.is_(True))

        return query.count()


# Listen for changes and update the full_name strings
@event.listens_for(Genus, "before_update")
def genus_before_update(
    _mapper,
    connection: Connection,
    target: Genus,
) -> None:
    for sp in target.species:
        session = t_cast(Session, object_session(sp))

        if sp in session.new or sp in session.dirty:
            # skip species that will trigger their own full name update
            return

        if sp.full_sci_name != sp.string(authors=True):
            vals = {
                "full_name": str(sp),
                "full_sci_name": sp.string(authors=True),
            }
            sp_table = Species.__table__
            connection.execute(
                update(sp_table).where(sp_table.c.id == sp.id).values(vals)
            )
            # update history because above does not trigger history
            db.History.event_add(
                "update", object_mapper(sp).local_table, connection, sp, **vals
            )


GenusNote = db.make_note_class("Genus")


class GenusSynonym(Synonym):
    """
    :Table name: genus_synonym
    """

    __tablename__ = "genus_synonym"
    __table_args__ = (CheckConstraint("genus_id != synonym_id"),)

    # columns
    genus_id: int = Column(Integer, ForeignKey("genus.id"), nullable=False)

    # a genus can only be a synonum of one other genus
    synonym_id: int = Column(
        Integer, ForeignKey("genus.id"), nullable=False, unique=True
    )
    is_one_to_one = True
    synonym: Mapped["Genus"]
    genus: Mapped["Genus"]

    def __str__(self) -> str:
        return f"{str(self.synonym)} ({self.synonym.family})"


def generic_gen_get_completions(session: Session, text: str) -> Query:
    """A generic genus get_completion.

    intended use is by supplying the local session via `functools.partial`

    e.g.:
    `completions = partial(generic_sp_get_completions, self.session)`

    :param session: a local session to use for the query.
    :param text: a string to search for
    """
    query = session.query(Genus)
    hybrid = ""
    genus = text.removeprefix("×").removeprefix("+").strip()
    try:
        if text[0] in ["×", "+"]:
            hybrid = text[0]
    except (AttributeError, IndexError):
        pass
    query = query.filter(utils.ilike(Genus.genus, f"{genus}%"))
    if hybrid:
        query = query.filter(Genus.hybrid == hybrid)
    return query.order_by(Genus.genus)


def genus_to_string_matcher(
    genus: Genus,
    key: str,
    gen_path: str = "",
) -> bool:
    """Helper function to match string or partial string.

    :param genus: a Genus table entry
    :param key: the string to search with
    :param gen_path: optional path for model obects to get to the genus

    :return: bool, True if the genus matches the key
    """
    if gen_path:
        from operator import attrgetter

        genus = attrgetter(gen_path)(genus)
    key = key.removeprefix("× ").removeprefix("+ ").lower()
    return genus.genus.lower().startswith(key)


def genus_match_func(
    completion: Gtk.EntryCompletion,
    key: str,
    treeiter: int,
    gen_path: str = "",
) -> bool:
    """match_func that allows partial matches.

    :param completion: the completion to match
    :param key: lowercase string of the entry text
    :param treeiter: the row number for the item to match
    :param gen_path: optional path for model obects to get to the genus

    :return: bool, True if the item at the treeiter matches the key
    """
    tree_model = completion.get_model()
    if not tree_model:
        raise AttributeError(f"can't get TreeModel from {completion}")
    genus = tree_model[treeiter][0]
    if not sa_inspect(genus).persistent:
        return False
    return genus_to_string_matcher(genus, key, gen_path)


def genus_cell_data_func(
    _column,
    renderer: Gtk.CellRendererText,
    model: Gtk.ListStore,
    treeiter: Gtk.TreeIter,
) -> None:
    value = model[treeiter][0]
    author = ""
    if value.author:
        author = utils.xml_safe(str(value.author))
    hybrid = ""
    if value.hybrid:
        hybrid = f"{value.hybrid} "
    # occassionally the session gets lost and can result in
    # DetachedInstanceErrors. So check first
    if sa_inspect(value).persistent:
        renderer.set_property(
            "markup",
            f"{hybrid}<i>{value.epithet}</i> {author} "
            f"(<small>{Family.string(value.family)}</small>)",
        )


# late bindings
from .family import Family
from .species_model import Species
