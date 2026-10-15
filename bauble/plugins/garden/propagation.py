# Copyright 2008-2010 Brett Adams
# Copyright 2015-2017 Mario Frasca <mario@anche.no>.
# Copyright 2021-2026 Ross Demuth <rossdemuth123@gmail.com>
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
propagation module
"""
import logging
from datetime import date

logger = logging.getLogger(__name__)

from typing import TYPE_CHECKING

from sqlalchemy import Column
from sqlalchemy import Float
from sqlalchemy import ForeignKey
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy import UniqueConstraint
from sqlalchemy import case
from sqlalchemy import cast
from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy.ext.associationproxy import association_proxy
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import relationship
from sqlalchemy.sql.expression import ColumnElement
from sqlalchemy.sql.selectable import ScalarSelect

from bauble import btypes as types
from bauble import db
from bauble import utils
from bauble.i18n import _

if TYPE_CHECKING:
    from .plant import Plant
    from .source import Source

SOURCE_TYPES = {
    "1": _("Primary"),  # should there only be one?
    "2": _("Secondary"),
    "3": _("Possible"),
    "4": _("Unlikely"),
}

SOURCE_MATERIALS = {
    "F": _("Seed"),
    "M": _("Pollen"),
    "R": _("Rootstock"),
    "S": _("Scion"),
    "V": _("Vegetative"),
    None: "",
}


class PlantPropSource(db.Base):  # pylint: disable=too-few-public-methods
    """Links plants to propagation activities"""

    __tablename__ = "plant_prop"
    __table_args__: tuple = (
        UniqueConstraint("plant_id", "propagation_id"),
        {},
    )

    source_type = Column(
        types.Enum(
            values=list(SOURCE_TYPES.keys()),
            translations=SOURCE_TYPES,
        ),
        default="1",
    )
    source_material = Column(
        types.Enum(
            values=list(SOURCE_MATERIALS.keys()),
            translations=SOURCE_MATERIALS,
        )
    )

    plant_id = Column(Integer, ForeignKey("plant.id"), nullable=False)
    plant: Mapped["Plant"] = relationship(
        "Plant",
        back_populates="_plant_props",
    )

    propagation_id = Column(
        Integer,
        ForeignKey("propagation.id"),
        nullable=False,
    )
    propagation: Mapped["Propagation"] = relationship(
        "Propagation",
        back_populates="plant_sources",
    )


class PropEventType(db.Base):  # pylint: disable=too-few-public-methods
    """Event types for propagation events"""

    __tablename__ = "prop_event_type"

    code: str = Column(String(20), unique=True, nullable=False)
    name: str = Column(String(20), unique=True, nullable=False)
    description = Column(String)


START_DEFAULT_EVENT_TYPES = (
    (1, "other", _("Other"), _("Undefined propagation event (add notes).")),
    (2, "polinate", _("Polinate"), _("Polination event.")),
    (3, "collect", _("Collect"), _("Material collected.")),
    (4, "dry", _("Dry"), _("Seed placed to dried.")),
    (5, "store", _("Store"), _("Seed banked in store.")),
    (6, "start", _("Sown/Started"), _("Seed sown, cuttings started, etc..")),
    (7, "treat", _("Treatment"), _("Propagation treated.")),
    (
        8,
        "success",
        _("Germinated/Struck"),
        _("Seed germinated, cuttings struck, etc.."),
    ),
    (9, "available", _("Available"), _("Propagation available for use.")),
    (10, "discard", _("Discarded"), _("Propagation discarded.")),
    (11, "cull", _("Cull"), _("Propagation culled.")),
    (12, "health", _("Health"), _("Propagation health issue.")),
)


def populate_default_event_types() -> None:
    """Populate the database with default propagation event types."""
    with db.engine.begin() as connection:
        count = connection.scalar(
            select(func.count()).select_from(PropEventType)
        )
        if count > 0:
            logger.info(
                "Default propagation event types exist, skipping population."
            )
            return

        for id_, code, name, description in START_DEFAULT_EVENT_TYPES:
            event_type_table = PropEventType.__table__
            connection.execute(
                event_type_table.insert(
                    {
                        "id": id_,
                        "code": code,
                        "name": name,
                        "description": description,
                    }
                )
            )
            logger.debug(
                "Adding default propagation event type: %s (%s) - %s",
                code,
                name,
                description,
            )


class PropEvent(db.Base):  # pylint: disable=too-few-public-methods
    """Records successful propagation numbers, i.e. cuttings struck, seeds
    germinated, etc..

    Can also be used to record deaths or thinning out/discarding.
    """

    __tablename__ = "prop_event"

    date = Column(types.Date, default=date.today())
    quantity = Column(Integer, autoincrement=False, default=0)
    person = Column(String(64), default=utils.get_user_display_name())
    event_type_id = Column(
        Integer,
        ForeignKey("prop_event_type.id"),
        nullable=False,
        default=1,  # default to "other" if not specified
    )
    event_type: PropEventType = relationship(
        PropEventType,
        uselist=False,
    )
    event_notes = Column(String)

    propagation_id = Column(
        Integer,
        ForeignKey("propagation.id"),
    )
    propagation: Mapped["Propagation"] = relationship(
        "Propagation",
        back_populates="events",
    )


class PropType(db.Base):  # pylint: disable=too-few-public-methods
    """Propagation types"""

    __tablename__ = "prop_type"

    code: str = Column(String(20), unique=True, nullable=False)
    name: str = Column(String(20), unique=True, nullable=False)
    description = Column(String)

    def __str__(self) -> str:
        return self.name


START_DEFAULT_PROP_TYPES = (
    (1, "other", _("Other"), _("Undefined propagation (add notes).")),
    (2, "seed", _("Seed"), _("Sexual propagation from seed.")),
    (
        3,
        "cutting",
        _("Cutting"),
        _("Asexual vegetative propagation from a cutting."),
    ),
    (
        4,
        "graft",
        _("Graft"),
        _("Asexual vegetative propagation from a rootstock and scion."),
    ),
    (
        5,
        "marcot",
        _("Marcot"),
        _("Asexual vegetative propagation from a marcot or air-layering."),
    ),
    (
        6,
        "division",
        _("Division"),
        _(
            "Asexual vegetative propagation from a division of a plant (bulb, "
            "rhizome, tuber, etc.)."
        ),
    ),
)


def populate_default_prop_types() -> None:
    """Populate the database with default propagation types."""
    with db.engine.begin() as connection:
        if connection.scalar(select(func.count()).select_from(PropType)) > 0:
            logger.info(
                "Default propagation types already exist, skipping population."
            )
            return

        for id_, code, name, description in START_DEFAULT_PROP_TYPES:
            porp_type_table = PropType.__table__
            connection.execute(
                porp_type_table.insert(
                    {
                        "id": id_,
                        "code": code,
                        "name": name,
                        "description": description,
                    }
                )
            )
            logger.debug(
                "Adding default propagation type: %s (%s) - %s",
                code,
                name,
                description,
            )


PropagationNote = db.make_note_class("Propagation")
PropagationPicture = db.make_note_class("Propagation", cls_type="picture")


class Propagation(db.Domain):
    """Propagation"""

    __tablename__ = "propagation"

    plants = association_proxy(
        "plant_sources",
        "plant",
        creator=lambda plant: PlantPropSource(plant=plant),
    )
    plant_sources: list["PlantPropSource"] = relationship(
        "PlantPropSource",
        cascade="all, delete-orphan",
        back_populates="propagation",
    )

    prop_type_id = Column(
        Integer,
        ForeignKey("prop_type.id"),
        nullable=False,
        default=1,  # default to "other" if not specified
    )
    prop_type: PropType = relationship(PropType, uselist=False)

    date = Column(types.Date, default=date.today())
    propagator = Column(String(64), default=utils.get_user_display_name())
    quantity = Column(Integer, nullable=False, autoincrement=False)
    media = Column(String(128))
    container = Column(String(128))
    location = Column(String(256))
    prop_notes = Column(String)

    events: list[PropEvent] = relationship(
        "PropEvent",
        cascade="all, delete-orphan",
        back_populates="propagation",
    )

    used_source: list["Source"] = relationship(
        "Source",
        primaryjoin="Source.plant_propagation_id==Propagation.id",
        back_populates="plant_propagation",
    )
    accessions = association_proxy(
        "used_source",
        "accession",
    )

    def has_children(self) -> bool:
        return bool(self.accessions)

    def count_children(self) -> int:
        return len(self.accessions)

    @hybrid_property
    def established_qty(self) -> int:
        return sum(event.quantity for event in self.events)

    @established_qty.expression  # type: ignore [no-redef]
    def established_qty(cls) -> ScalarSelect:
        # pylint: disable=no-self-argument
        return (
            select(func.coalesce(func.sum(PropEvent.quantity), 0))
            .where(PropEvent.propagation_id == cls.id)
            .scalar_subquery()
        )

    @hybrid_property
    def percent_success(self) -> float:
        return self.established_qty / self.quantity * 100

    @percent_success.expression  # type: ignore [no-redef]
    def percent_success(cls) -> ColumnElement[Float]:
        # pylint: disable=no-self-argument
        return case(
            [(cls.quantity == 0, 0)],
            else_=cast(cls.established_qty, Float) / cls.quantity * 100,
        )

    @hybrid_property
    def used_qty(self) -> int:
        return sum((acc.quantity_recvd for acc in self.accessions))

    @used_qty.expression  # type: ignore [no-redef]
    def used_qty(cls) -> ScalarSelect:
        # pylint: disable=no-self-argument

        from .accession import Accession
        from .source import Source

        return (
            select(func.coalesce(func.sum(Accession.quantity_recvd), 0))
            .where(Source.plant_propagation_id == cls.id)
            .where(Accession.id == Source.accession_id)
            .scalar_subquery()
        )

    @hybrid_property
    def available_qty(self) -> int:
        return self.established_qty - self.used_qty

    @available_qty.expression  # type: ignore [no-redef]
    def available_qty(cls) -> ColumnElement[Integer]:
        # pylint: disable=no-self-argument
        return cls.established_qty - cls.used_qty

    def __str__(self) -> str:

        parts: list[str] = [self.prop_type.name]

        if self.propagator:
            date_str = utils.date_string(self.date)
            parts.append(
                _("propagated by %s on %s") % (self.propagator, date_str)
            )

        if self.quantity:
            parts.append(_("Quantity: %s") % self.quantity)

        if self.media:
            parts.append(_("Media: %s") % self.media)

        if self.container:
            parts.append(_("Container: %s") % self.container)

        if self.location:
            parts.append(_("Location: %s") % self.location)

        if self.prop_notes:
            parts.append(_("Notes: %s") % self.prop_notes)

        return "; ".join(parts)
