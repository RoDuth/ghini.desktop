# Copyright (c) 2005,2006,2007,2008,2009 Brett Adams <brett@belizebotanic.org>
# Copyright (c) 2012-2017 Mario Frasca <mario@anche.no>
# Copyright (c) 2021-2025 Ross Demuth <rossdemuth123@gmail.com>
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
Tag Model and associated.
"""
import logging

logger = logging.getLogger(__name__)

import threading
from collections.abc import Sequence
from importlib import import_module
from typing import Self

from sqlalchemy import Column
from sqlalchemy import ForeignKey
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy import Unicode
from sqlalchemy import UnicodeText
from sqlalchemy import and_
from sqlalchemy import func
from sqlalchemy import literal
from sqlalchemy import select
from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.orm import Session
from sqlalchemy.orm import relationship
from sqlalchemy.orm.exc import DetachedInstanceError
from sqlalchemy.orm.session import object_session

from bauble import db
from bauble import error
from bauble import prefs
from bauble import utils
from bauble.i18n import _


class TaggedObj(db.Base):
    """Joins tags to their objects."""

    __tablename__ = "tagged_obj"

    # columns
    obj_id: int = Column(Integer, autoincrement=False)
    obj_class: str = Column(String(128))
    tag_id: int = Column(Integer, ForeignKey("tag.id"))

    # relations
    tag: "Tag" = relationship("Tag", back_populates="objects_")

    def __str__(self) -> str:
        return f"{self.obj_class}: {self.obj_id}"


class Tag(db.Domain):

    __tablename__ = "tag"

    # columns
    tag: str = Column(Unicode(64), unique=True, nullable=False)
    description: str = Column(UnicodeText)

    # relations
    objects_: list[TaggedObj] = relationship(
        TaggedObj,
        cascade="all, delete-orphan",
        uselist=True,
        back_populates="tag",
    )

    _update_history_id: int = 0
    _last_objects: list[db.Domain] | None = None

    retrieve_cols = ["id", "tag"]
    _lock = threading.Lock()

    @classmethod
    def retrieve(cls, session: Session, keys: dict[str, str]) -> Self | None:
        parts = {k: v for k, v in keys.items() if k in cls.retrieve_cols}
        if parts:
            return session.query(cls).filter_by(**parts).one_or_none()
        return None

    def __str__(self) -> str:
        try:
            return str(self.tag)
        except DetachedInstanceError:
            return db.Base.__str__(self)

    def markup(self) -> str:
        return f"{self.tag} Tag"

    def tag_objects(self, objects: Sequence[db.Domain]) -> None:
        session = object_session(self)

        if not isinstance(session, Session):
            logger.warning("no object session bailing.")
            return

        for obj in objects:
            tagged = (
                session.query(TaggedObj.id)
                .filter(
                    and_(
                        TaggedObj.obj_class == _classname(obj),
                        TaggedObj.obj_id == obj.id,
                        TaggedObj.tag_id == self.id,
                    )
                )
                .first()
            )
            if not tagged:
                tagged_obj = TaggedObj(
                    obj_class=_classname(obj), obj_id=obj.id, tag=self
                )
                session.add(tagged_obj)

    @property
    def objects(self) -> list[db.Domain]:
        """return all tagged objects

        Reuses last result if nothing was changed in the database since
        list was retrieved.
        """
        last_history = 0

        # NOTE tests may freeze here on MSSQL if flush.  Better to commit
        if db.engine:
            with db.engine.begin() as connection:
                table = db.History.__table__
                stmt = select(func.max(table.c.id))

                last_history = connection.execute(stmt).scalar() or 0

        if last_history > self._update_history_id:
            self._last_objects = None

        if self._last_objects is None:
            self._update_history_id = last_history
            self._last_objects = self.get_tagged_objects()

        return self._last_objects

    def is_tagging(self, obj: db.Domain) -> bool:
        """Tell whether self tags obj."""
        if self.objects == []:
            return False
        return obj in self.objects

    def get_tagged_objects(self) -> list[db.Domain]:
        """Get all object tagged with tag and clean up any that are left
        hanging.
        """
        with self._lock:
            session = object_session(self)

            if not isinstance(session, Session):
                logger.warning("no object session bailing.")
                return []

            items = []
            for obj in self.objects_:
                result = _get_tagged_object_pair(obj)
                if result:
                    mapper, obj_id = result
                    rec = session.query(mapper).filter_by(id=obj_id).first()
                    if rec:
                        items.append(rec)
                    else:
                        logger.debug("deleting tagged_obj: %s", obj)
                        # delete any tagged objects no longer in the database
                        session.delete(obj)
                        session.commit()
            return items

    @staticmethod
    def attached_to(obj: db.Domain) -> list["Tag"]:
        """Return the list of tags attached to obj."""
        session = object_session(obj)

        if not isinstance(session, Session):
            logger.warning("no object session bailing.")
            return []

        modname = type(obj).__module__
        clsname = type(obj).__name__
        full_cls_name = f"{modname}.{clsname}"
        tags = (
            session.query(Tag)
            .join(TaggedObj)
            .filter(TaggedObj.obj_class == full_cls_name)
            .filter(TaggedObj.obj_id == obj.id)
        )
        return tags.all()

    def search_view_markup_pair(self) -> tuple[str, str]:
        """Provide the two lines describing object for SearchView row."""
        logging.debug("entering search_view_markup_pair %s", self)
        objects = self.objects if self.objects else ()
        classes = set(type(obj) for obj in objects)

        if len(classes) == 1:
            fine_prints = _("tagging %(1)s objects of type %(2)s") % {
                "1": len(objects),
                "2": classes.pop().__name__,
            }
        elif len(classes) == 0:
            fine_prints = _("tagging nothing")
        else:
            fine_prints = _(
                "tagging %(objs)s objects of %(clss)s different types"
            ) % {"objs": len(objects), "clss": len(classes)}
            if len(classes) < 4:
                fine_prints += ": "
                fine_prints += ", ".join(sorted(t.__name__ for t in classes))

        first = (
            f"{utils.xml_safe(self)} - "
            f'<span weight="light">{fine_prints}</span>'
        )
        fine_print = (self.description or "").replace("\n", " ")[:256]
        second = (
            f"({type(self).__name__}) - "
            f'<span weight="light">{fine_print}</span>'
        )
        return first, second

    def has_children(self) -> bool:
        result = None

        if db.engine:
            with db.engine.begin() as connection:
                stmt = (
                    select(literal(1))
                    .where(TaggedObj.__table__.c.tag_id == self.id)
                    .limit(1)
                )
                result = connection.scalar(stmt)

        return bool(result)

    def count_children(self) -> int:

        if not self.objects:
            return 0

        if prefs.prefs.get(prefs.exclude_inactive_pref):
            return len([i for i in self.objects if getattr(i, "active", True)])
        return len(self.objects)


def _classname(obj: db.Domain) -> str:
    # classname as stored in the tagged_obj table
    return f"{type(obj).__module__}.{type(obj).__name__}"


def _get_tagged_object_pair(
    obj: TaggedObj,
) -> tuple[type[db.Domain], int] | None:
    try:
        module_name, _part, cls_name = str(obj.obj_class).rpartition(".")
        module = import_module(module_name)
        cls = getattr(module, cls_name)
        return cls, obj.obj_id
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.warning(
            "_get_tagged_object_pair (%s) error: %s(%s)",
            obj,
            type(e).__name__,
            e,
        )
    return None


def untag_objects(name: str, objects: Sequence[db.Domain]) -> None:
    """Remove the tag name from objects."""

    session = object_session(objects[0])

    if not isinstance(session, Session):
        logger.warning("no object session bailing.")
        return

    try:
        tag: Tag = session.query(Tag).filter_by(tag=name).one()
    except InvalidRequestError as e:
        logger.info(
            "Can't remove non existing tag from non-empty list of "
            "objects %s - %s",
            type(e).__name__,
            e,
        )
        return

    objs_cls_id = {(_classname(obj), obj.id) for obj in objects}

    for item in tag.objects_:
        if (item.obj_class, item.obj_id) not in objs_cls_id:
            continue
        obj = session.query(TaggedObj).filter_by(id=item.id).one()
        session.delete(obj)

    session.commit()


def tag_objects(name: str, objects: Sequence[db.Domain]) -> None:
    """Add the tag to objects."""

    session = object_session(objects[0])

    if not isinstance(session, Session):
        logger.warning("no object session bailing.")
        return

    tag: Tag | None = session.query(Tag).filter_by(tag=name).one_or_none()

    if not tag:
        tag = Tag(tag=name)
        session.add(tag)

    tag.tag_objects(objects)
    session.commit()


def get_tag_ids(objects: Sequence[db.Domain]) -> tuple[set[int], set[int]]:
    """Return a tuple describing which tags apply to objects.

    The result is 2 sets.  The first set contains the IDs of the tags that
    apply to all objs.  The second set contains the IDs of the tags that apply
    to one or more objs, but not all.
    """
    session = object_session(objects[0])

    if not isinstance(session, Session):
        logger.warning("no object session bailing.")
        raise error.DatabaseError("Object has no database session.")

    tag_id_select = select(Tag.id)
    starting_now = True
    s_all = set()
    s_some = set()
    for obj in objects:
        applied_tag_ids_select = tag_id_select.join(TaggedObj).where(
            and_(
                TaggedObj.obj_class == _classname(obj),
                TaggedObj.obj_id == obj.id,
            )
        )
        applied_tag_ids = set(session.scalars(applied_tag_ids_select))
        if starting_now:
            s_all = set(applied_tag_ids)
            starting_now = False
        else:
            s_all.intersection_update(applied_tag_ids)
        s_some.update(applied_tag_ids)

    s_some.difference_update(s_all)
    return (s_all, s_some)
