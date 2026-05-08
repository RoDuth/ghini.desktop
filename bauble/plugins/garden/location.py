# Copyright 2008-2010 Brett Adams
# Copyright 2015 Mario Frasca <mario@anche.no>.
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
Location table definition and related
"""
import logging

logger = logging.getLogger(__name__)

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Column
from sqlalchemy import Unicode
from sqlalchemy import UnicodeText
from sqlalchemy import case
from sqlalchemy import func
from sqlalchemy import literal
from sqlalchemy import select
from sqlalchemy import union
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import Session
from sqlalchemy.orm import backref
from sqlalchemy.orm import deferred
from sqlalchemy.orm import relationship
from sqlalchemy.orm import validates
from sqlalchemy.orm.session import object_session
from sqlalchemy.sql.expression import ColumnElement

from bauble import btypes as types
from bauble import db
from bauble import prefs
from bauble import utils

if TYPE_CHECKING:
    from .accession import IntendedLocation
    from .plant import Plant


LocationNote = db.make_note_class("Location")
LocationPicture = db.make_note_class("Location", cls_type="_picture")
LocationDocument = db.make_note_class(
    "Location",
    cls_type="document",
    extra_columns={"note": Column(UnicodeText)},
)


class Location(db.Domain, db.WithNotes):
    """
    :Table name: location

    :Columns:
        *code*:
            unique

        *name*:

        *description*:

        *geojson*:
            spatial data

    :Relationships:
        *plants*:

    """

    __tablename__ = "location"

    # columns
    # refers to beds by unique codes
    code = Column(Unicode(12), unique=True, nullable=False)
    name = Column(Unicode(128))
    description = Column(UnicodeText)
    # spatial data deferred mainly to avoid comparison issues in union search
    # (i.e. reports)  NOTE that deferring can lead to the instance becoming
    # dirty when merged into another session (i.e. an editor) and the column
    # has already been loaded (i.e. infobox).  This can be avoided using a
    # separate db connection.
    # Also, NOTE that if not loaded (read) prior to changing a single list
    # history change will be recoorded with no indication of its value to the
    # change.  Can use something like:
    # `if loc.geojson != val: loc.geojson = val`
    geojson = deferred(Column(types.JSON()))

    # relations
    plants: list["Plant"] = relationship(
        "Plant", backref=backref("location", uselist=False)
    )
    intended_accessions: list["IntendedLocation"] = relationship(
        "IntendedLocation",
        cascade="all, delete-orphan",
        back_populates="location",
    )

    retrieve_cols = ["id", "code"]

    @property
    def pictures(self) -> list[db.Picture]:
        """Return pictures from any attached plants and any in _pictures."""
        session = object_session(self)
        if not isinstance(session, Session):
            return []
        # avoid circular imports
        from ..garden import Plant
        from ..garden.plant import PlantPicture

        plt_pics = (
            session.query(PlantPicture)
            .join(Plant, Location)
            .filter(Location.id == self.id)
        )
        if prefs.prefs.get(prefs.exclude_inactive_pref):
            plt_pics = plt_pics.filter(Plant.active.is_(True))  # type: ignore [attr-defined] # noqa
        return plt_pics.all() + self._pictures

    @classmethod
    def retrieve(cls, session, keys):
        parts = {k: v for k, v in keys.items() if k in cls.retrieve_cols}

        if parts:
            return session.query(cls).filter_by(**parts).one_or_none()
        return None

    def search_view_markup_pair(self) -> tuple[str, str]:
        """provide the two lines describing object for SearchView row."""
        if self.description is not None:
            return (
                utils.xml_safe(str(self)),
                utils.xml_safe(str(self.description)),
            )
        return utils.xml_safe(str(self)), type(self).__name__

    @staticmethod
    @validates("code", "name")
    def validate_stripping(_key, value):
        if value is None:
            return None
        return value.strip()

    def __str__(self):
        if self.name:
            return f"({self.code}) {self.name}"
        return str(self.code)

    @hybrid_property
    def updated(self) -> datetime:
        updates = [self._last_updated]

        if self.notes:
            updates.append(max(i._last_updated for i in self.notes))

        if self.pictures:
            updates.append(max(i._last_updated for i in self.pictures))

        return max(updates)

    @updated.expression  # type: ignore [no-redef]
    def updated(cls) -> types.DateTime:
        # pylint: disable=no-self-argument,no-self-use,arguments-renamed
        self_select = select([cls._last_updated, cls.id])

        note_select = select([LocationNote._last_updated, cls.id]).join(cls)

        pic_select = select([LocationPicture._last_updated, cls.id]).join(cls)

        doc_select = select([LocationDocument._last_updated, cls.id]).join(cls)

        dates = union(
            self_select,
            note_select,
            pic_select,
            doc_select,
        ).alias("dates")

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

        from ..plants import Family
        from ..plants import Genus
        from ..plants import Species
        from . import Accession
        from . import Plant
        from . import Source
        from . import SourceDetail

        base_ids_stmt = (
            select(
                Family.id,
                Genus.id,
                Species.id,
                Accession.id,
                Plant.top_level_count_id(exclude_inactive),
                cls.id,
                SourceDetail.id,
            )
            .select_from(cls)
            .outerjoin(Plant)
            .outerjoin(Accession)
            .outerjoin(Species)
            .outerjoin(Genus)
            .outerjoin(Family)
            .outerjoin(Source)
            .outerjoin(SourceDetail)
        )

        base_count_stmt = (
            select(
                func.sum(Plant.quantity),
            )
            .select_from(cls)
            .join(Plant)
        )

        if exclude_inactive:
            # pylint: disable=no-member
            base_ids_stmt = base_ids_stmt.where(
                Accession.active.is_(True),  # type: ignore [attr-defined]
            )

        args = cls._top_level_counter_helper(
            base_ids_stmt, base_count_stmt, ids
        )
        return db.TopLevelCount(*args)

    def has_children(self):
        cls = self.__class__.plants.prop.mapper.class_
        from sqlalchemy import exists

        session = object_session(self)
        return bool(
            session.query(literal(True))
            .filter(exists().where(cls.location_id == self.id))
            .scalar()
        )

    @classmethod
    def top_level_count_id(cls, exclude_inactive: bool) -> ColumnElement:
        from .plant import Plant

        if exclude_inactive:
            return case(
                [(Plant.quantity > 0, cls.id)],
                else_=None,
            )
        return cls.id

    def count_children(self):
        cls = self.__class__.plants.prop.mapper.class_
        session = object_session(self)
        query = session.query(cls.id).filter(cls.location_id == self.id)
        if prefs.prefs.get(prefs.exclude_inactive_pref):
            query = query.filter(cls.active.is_(True))
        return query.count()
