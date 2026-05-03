# Copyright 2008-2010 Brett Adams
# Copyright 2014-2015 Mario Frasca <mario@anche.no>.
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
Family table definition
"""

import logging

logger = logging.getLogger(__name__)

from collections.abc import Sequence
from datetime import datetime

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
from sqlalchemy import exists
from sqlalchemy import func
from sqlalchemy import literal
from sqlalchemy import or_
from sqlalchemy import select
from sqlalchemy import union
from sqlalchemy.ext.associationproxy import association_proxy
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import Session
from sqlalchemy.orm import relationship
from sqlalchemy.orm import synonym as sa_synonym
from sqlalchemy.orm import validates
from sqlalchemy.orm.session import object_session

from bauble import btypes as types
from bauble import db
from bauble import prefs
from bauble import utils

from .model import Synonym
from .model import Taxon
from .species import Species
from .species import SpeciesPicture


class Family(Taxon, db.WithNotes):
    """
    :Table name: family

    :Columns:
        *family*:
            The name of the family. Required.

        *author*

        *qualifier*:
            The family qualifier.

            Possible values:
                * s. lat.: aggregrate family (senso lato)

                * s. str.: segregate family (senso stricto)

                * '': the empty string

    :Properties:
        *synonyms*:
            An association to _synonyms that will automatically
            convert a Family object and create the synonym.

    :Constraints:
        The family table has a unique constraint on family/qualifier.
    """

    __tablename__ = "family"
    __table_args__: tuple = (
        UniqueConstraint("family", "author", "qualifier"),
        {},
    )

    rank = "familia"
    link_keys = ["accepted"]

    # columns
    order = Column(Unicode(64))
    suborder = Column(Unicode(64))

    family = Column(String(45), nullable=False, index=True)
    epithet: "str" = sa_synonym("family")

    # use '' instead of None so that the constraints will work propertly
    author = Column(Unicode(128), default="")

    # we use the blank string here instead of None so that the
    # contraints will work properly,
    qualifier = Column(
        types.Enum(values=["s. lat.", "s. str.", ""]), default=""
    )

    # relations
    synonyms = association_proxy(
        "_synonyms", "synonym", creator=lambda fam: FamilySynonym(synonym=fam)
    )
    _synonyms: Sequence["FamilySynonym"] = relationship(
        "FamilySynonym",
        primaryjoin="Family.id==FamilySynonym.family_id",
        cascade="all, delete-orphan",
        uselist=True,
        backref="family",
    )

    _accepted: "FamilySynonym" = relationship(
        "FamilySynonym",
        primaryjoin="Family.id==FamilySynonym.synonym_id",
        cascade="all, delete-orphan",
        uselist=False,
        backref="synonym",
    )
    accepted = association_proxy(
        "_accepted", "family", creator=lambda fam: FamilySynonym(family=fam)
    )

    genera: list["Genus"] = relationship(
        "Genus",
        order_by="Genus.genus",
        back_populates="family",
        cascade="all, delete-orphan",
    )

    cites = Column(types.Enum(values=["I", "II", "III", None]), default=None)

    retrieve_cols = ["id", "epithet", "family"]

    @property
    def pictures(self) -> list[db.Picture]:
        session = object_session(self)
        if not isinstance(session, Session):
            return []
        from ..garden import Accession
        from ..garden import Plant
        from ..garden.plant import PlantPicture

        sp_pics = (
            session.query(SpeciesPicture)
            .join(Species, Genus, Family)
            .filter(Family.id == self.id)
        )
        plt_pics = (
            session.query(PlantPicture)
            .join(Plant, Accession, Species, Genus, Family)
            .filter(Family.id == self.id)
        )
        if prefs.prefs.get(prefs.exclude_inactive_pref):
            plt_pics = plt_pics.filter(
                Plant.active.is_(True),  # type: ignore [attr-defined]
            )
        return sp_pics.all() + plt_pics.all()

    @classmethod
    def retrieve(cls, session, keys):
        fam_parts = {k: v for k, v in keys.items() if k in cls.retrieve_cols}

        if fam_parts:
            return session.query(cls).filter_by(**fam_parts).one_or_none()
        return None

    @staticmethod
    @validates("family")
    def validate_stripping(_key, value):
        if value is None:
            return None
        return value.strip()

    def __str__(self):
        return self.string()

    def string(self, **kwargs) -> str:
        """Returns a string representation of the family.

        :param author: if True, include the author in the string.
        """
        author = kwargs.get("author", False)
        if self.family is None:
            return db.Base.__repr__(self)

        parts = [self.family, self.qualifier]
        if author and self.author:
            parts.append(utils.xml_safe(self.author))

        return " ".join([str(s) for s in parts if s not in (None, "")])

    def search_view_markup_pair(self) -> tuple[str, str]:
        author = utils.xml_safe(self.author)
        author = f' <span weight="light">{author}</span>'
        return f"{self}{author}", "Family"

    @hybrid_property
    def active(self) -> bool:
        """False when all accessions have been deaccessioned or no genera or
        species attached.
        """
        if not self.genera:
            return False
        for genus in self.genera:
            if genus.active:
                return True
        return False

    @active.expression  # type: ignore [no-redef]
    def active(cls) -> types.Boolean:
        # pylint: disable=no-self-argument,no-self-use,arguments-renamed
        from ..garden import Accession
        from ..garden import Plant

        active = (
            select([cls.id])
            .join(Genus)
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

        note_select = select([FamilyNote._last_updated, cls.id]).join(cls)

        accepted_select = select([FamilySynonym._last_updated, cls.id]).join(
            cls, cls.id == FamilySynonym.synonym_id
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

        # avoid circular imports
        from ..garden import Accession
        from ..garden import Location
        from ..garden import Plant
        from ..garden import Source
        from ..garden import SourceDetail

        base_ids_stmt = (
            select(
                cls.id,
                Genus.id,
                Species.id,
                Accession.id,
                Plant.top_level_count_id(exclude_inactive),
                Location.id,
                SourceDetail.id,
            )
            .select_from(cls)
            .outerjoin(Genus)
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
            .join(Genus)
            .join(Species)
            .join(Accession)
            .join(Plant)
        )

        if exclude_inactive:
            # pylint: disable=no-member
            base_ids_stmt = base_ids_stmt.where(
                Accession.active.is_(True),  # type: ignore [attr-defined]
            )
            base_ids_stmt = base_ids_stmt.where(Species.id.is_not(None))

        result = cls._top_level_counter_helper(
            base_ids_stmt, base_count_stmt, ids
        )
        return db.TopLevelCount(*result)

    def has_children(self):
        cls = self.__class__.genera.prop.mapper.class_

        session = object_session(self)

        if prefs.prefs.get(prefs.exclude_inactive_pref):
            # probably not much point for searchview as would be exluded anyway
            return bool(
                session.query(literal(True))
                .filter(
                    exists().where(
                        and_(
                            cls.family_id == self.id,
                            cls.active.is_(True),
                        )
                    )
                )
                .scalar()
            )
        return bool(
            session.query(literal(True))
            .filter(exists().where(cls.family_id == self.id))
            .scalar()
        )

    def count_children(self):
        cls = self.__class__.genera.prop.mapper.class_
        session = object_session(self)
        query = session.query(cls.id).filter(cls.family_id == self.id)
        if prefs.prefs.get(prefs.exclude_inactive_pref):
            query = query.filter(cls.active.is_(True))
        return query.count()


FamilyNote = db.make_note_class("Family")


class FamilySynonym(Synonym):  # pylint: disable=too-few-public-methods
    """
    :Table name: family_synonyms

    :Columns:
        *family_id*:

        *synonyms_id*:

    :Properties:
        *synonyms*:

        *family*:
    """

    __tablename__ = "family_synonym"
    __table_args__ = (CheckConstraint("family_id != synonym_id"),)

    # columns
    family_id: int = Column(Integer, ForeignKey("family.id"), nullable=False)
    synonym_id: int = Column(
        Integer, ForeignKey("family.id"), nullable=False, unique=True
    )
    is_one_to_one = True
    synonym: Mapped["Family"]
    family: Mapped["Family"]

    def __str__(self) -> str:
        return self.synonym.string(author=True)

    def markup(self) -> str:
        # no markup for family
        return self.synonym.string(author=True)


# avoid circular imports
from .genus import Genus
