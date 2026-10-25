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

logger = logging.getLogger(__name__)

import datetime
from typing import TYPE_CHECKING
from typing import Literal
from typing import TypedDict

import pyparsing as pp
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


prefix = pp.one_of("+- -+ - +")("action")
attribute = pp.one_of("Q S A")("attr")
flag = pp.Group(prefix + attribute)
option_grammar = pp.Optional(pp.OneOrMore(flag))


class AddReduceDict(TypedDict):
    adds: bool
    reduces: bool


class OptionDict(TypedDict):
    Q: AddReduceDict
    S: AddReduceDict
    A: AddReduceDict


class PropEventType(db.Base):  # pylint: disable=too-few-public-methods
    """Event types for propagation events"""

    __tablename__ = "prop_event_type"

    code: str = Column(String(20), unique=True, nullable=False)
    name: str = Column(String(20), unique=True, nullable=False)
    description = Column(String)
    # e.g. for all use "+-Q+-S+-A" for just adding to quantity use "+Q"
    option_str = Column(String(4))

    def parsed_options(self) -> OptionDict:
        result: OptionDict = {
            "Q": {"adds": False, "reduces": False},
            "A": {"adds": False, "reduces": False},
            "S": {"adds": False, "reduces": False},
        }
        parsed = option_grammar.parse_string(self.option_str or "")

        for item in parsed:
            attr: Literal["Q", "S", "A"] = item["attr"]
            action = item["action"]
            can_add = "+" in action
            can_reduce = "-" in action

            result[attr] = {"adds": can_add, "reduces": can_reduce}

        return result

    def __str__(self) -> str:
        return self.name or ""


START_DEFAULT_EVENT_TYPES = (
    (
        "STRT",
        _("Started"),
        _("Seed sown, cuttings started, division taken, etc.."),
        "+Q",
    ),
    (
        "CULQ",
        _("Cull quantity"),
        _("Propagations culled or discarded prior to success."),
        "-Q",
    ),
    ("SUCC", _("Success"), _("Seed germinated, cuttings struck, etc.."), "+S"),
    (
        "CULS",
        _("Cull success"),
        _("Successful propagations culled."),
        "-S",
    ),
    ("AVLB", _("Available"), _("Propagules available for use."), "+A"),
    (
        "DISC",
        _("Discard"),
        _("Available propagules discarded, no longer available to accession."),
        "-A",
    ),
    (
        "HLTH",
        _("Health"),
        _("Propagation health issue, either observation or to report deaths."),
        "-Q-S-A",
    ),
    ("TREA", _("Treatment"), _("Propagation treated to assist success."), ""),
    ("POLL", _("Pollinate"), _("Pollination event."), ""),
    ("COLL", _("Collect"), _("Material collected."), ""),
    ("DRYD", _("Dry"), _("Seed placed to be dried."), ""),
    ("STOR", _("Store"), _("Seed banked in store."), ""),
    (
        "OTHR",
        _("Other"),
        _("Undefined propagation event (add notes)."),
        "+_Q+-S+-A",
    ),
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

        for id_, values in enumerate(START_DEFAULT_EVENT_TYPES):
            code, name, description, option_str = values

            event_type_table = PropEventType.__table__
            connection.execute(
                event_type_table.insert(
                    {
                        "id": id_,
                        "code": code,
                        "name": name,
                        "description": description,
                        "option_str": option_str,
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

    date: datetime.date = Column(types.Date, default=datetime.date.today())

    # start quantity (i.e. how many seeds, cuttings, etc.)
    quantity: int = Column(Integer, autoincrement=False, default=0)
    # success - germinations, etc. only these should become available, should
    # not exceed quantity
    success: int = Column(Integer, autoincrement=False, default=0)
    # made available, shouldn't exceed success
    available: int = Column(Integer, autoincrement=False, default=0)

    person: str = Column(String(64), default=utils.get_user_display_name())
    event_notes: str = Column(String)

    event_type_id: int = Column(
        Integer,
        ForeignKey("prop_event_type.id"),
        nullable=False,
        default=1,  # default to "start" if not specified
    )
    event_type: PropEventType = relationship(
        PropEventType,
        uselist=False,
    )

    propagation_id: int = Column(
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
    description: str = Column(String)

    def __str__(self) -> str:
        return self.name


START_DEFAULT_PROP_TYPES = (
    ("other", _("Other"), _("Undefined propagation (add notes).")),
    ("seed", _("Seed"), _("Sexual propagation from seed.")),
    (
        "cutting",
        _("Cutting"),
        _("Asexual vegetative propagation from a cutting."),
    ),
    (
        "graft",
        _("Graft"),
        _("Asexual vegetative propagation from a rootstock and scion."),
    ),
    (
        "marcot",
        _("Marcot"),
        _("Asexual vegetative propagation from a marcot or air-layering."),
    ),
    (
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

        for id_, values in enumerate(START_DEFAULT_PROP_TYPES):
            code, name, description = values

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
    )
    prop_type: PropType = relationship(PropType, uselist=False)

    date = Column(types.Date, default=datetime.date.today())
    propagator = Column(String(64), default=utils.get_user_display_name())
    media = Column(String(128))
    container = Column(String(128))
    location = Column(String(256))
    prop_notes = Column(String)

    events: list[PropEvent] = relationship(
        "PropEvent",
        cascade="all, delete-orphan",
        back_populates="propagation",
        order_by=(PropEvent.date, PropEvent.id),
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
    def quantity(self) -> int:
        """The current quantity after all culled removed."""
        return sum(event.quantity for event in self.events)

    @quantity.expression  # type: ignore [no-redef]
    def quantity(cls) -> ScalarSelect:
        # pylint: disable=no-self-argument
        return (
            select(func.coalesce(func.sum(PropEvent.quantity), 0))
            .where(PropEvent.propagation_id == cls.id)
            .scalar_subquery()
        )

    @hybrid_property
    def total_quantity(self) -> int:
        """Total start quantity, excluding culled."""
        return sum(
            event.quantity or 0 for event in self.events if event.quantity > 0
        )

    @total_quantity.expression  # type: ignore [no-redef]
    def total_quantity(cls) -> ScalarSelect:
        # pylint: disable=no-self-argument
        return (
            select(func.coalesce(func.sum(PropEvent.quantity), 0))
            .where(PropEvent.quantity > 0)
            .where(PropEvent.propagation_id == cls.id)
            .scalar_subquery()
        )

    @hybrid_property
    def culled_quantity(self) -> int:
        """The amount culled from the starting quantity, prior to success."""
        return abs(
            sum(event.quantity for event in self.events if event.quantity < 0)
        )

    @culled_quantity.expression  # type: ignore [no-redef]
    def culled_quantity(cls) -> ScalarSelect:
        # pylint: disable=no-self-argument
        return (
            select(func.abs(func.coalesce(func.sum(PropEvent.quantity), 0)))
            .where(PropEvent.quantity < 0)
            .where(PropEvent.propagation_id == cls.id)
            .scalar_subquery()
        )

    @hybrid_property
    def success(self) -> int:
        """Current successful after all culled removed."""
        return sum(event.success for event in self.events)

    @success.expression  # type: ignore [no-redef]
    def success(cls) -> int:
        # pylint: disable=no-self-argument
        return (
            select(func.coalesce(func.sum(PropEvent.success), 0))
            .where(PropEvent.propagation_id == cls.id)
            .scalar_subquery()
        )

    @hybrid_property
    def total_success(self) -> int:
        """Total of success, excluding culled."""
        return sum(event.success for event in self.events if event.success > 0)

    @total_success.expression  # type: ignore [no-redef]
    def total_success(cls) -> int:
        # pylint: disable=no-self-argument
        return (
            select(func.coalesce(func.sum(PropEvent.success), 0))
            .where(PropEvent.success > 0)
            .where(PropEvent.propagation_id == cls.id)
            .scalar_subquery()
        )

    @hybrid_property
    def remaining_success(self) -> int:
        """Total of success, excluding available."""
        return self.success - self.available

    @remaining_success.expression  # type: ignore [no-redef]
    def remaining_success(cls) -> int:
        # pylint: disable=no-self-argument
        return cls.success - cls.available

    @hybrid_property
    def culled_success(self) -> int:
        """The amount culled from success."""
        return abs(
            sum(event.success for event in self.events if event.success < 0)
        )

    @culled_success.expression  # type: ignore [no-redef]
    def culled_success(cls) -> ScalarSelect:
        # pylint: disable=no-self-argument
        return (
            select(func.abs(func.coalesce(func.sum(PropEvent.success), 0)))
            .where(PropEvent.success < 0)
            .where(PropEvent.propagation_id == cls.id)
            .scalar_subquery()
        )

    @hybrid_property
    def percent_success(self) -> float:
        """Percent successful propagations.

        Calculated from total_success and current quantity."""
        if self.quantity:  # pylint: disable=using-constant-test
            return self.total_success / self.quantity * 100
        return 0

    @percent_success.expression  # type: ignore [no-redef]
    def percent_success(cls) -> ColumnElement[Float]:
        # pylint: disable=no-self-argument,comparison-with-callable
        return case(
            [(cls.quantity == 0, 0)],
            else_=cast(cls.total_success, Float) / cls.quantity * 100,
        )

    @hybrid_property
    def available(self) -> int:
        """Total that has ever been made available, excluding discarded."""
        return sum(event.available for event in self.events)

    @available.expression  # type: ignore [no-redef]
    def available(cls) -> ScalarSelect:
        # pylint: disable=no-self-argument
        return (
            select(func.coalesce(func.sum(PropEvent.available), 0))
            .where(PropEvent.propagation_id == cls.id)
            .scalar_subquery()
        )

    @hybrid_property
    def made_available(self) -> int:
        """Total that has ever been made available, excluding discarded."""
        return sum(
            event.available for event in self.events if event.available > 0
        )

    @made_available.expression  # type: ignore [no-redef]
    def made_available(cls) -> ScalarSelect:
        # pylint: disable=no-self-argument
        return (
            select(func.coalesce(func.sum(PropEvent.available), 0))
            .where(PropEvent.available > 0)
            .where(PropEvent.propagation_id == cls.id)
            .scalar_subquery()
        )

    @hybrid_property
    def discarded(self) -> int:
        """The amount discarded after becoming available."""
        return abs(
            sum(
                event.available for event in self.events if event.available < 0
            )
        )

    @discarded.expression  # type: ignore [no-redef]
    def discarded(cls) -> ScalarSelect:
        # pylint: disable=no-self-argument
        return (
            select(func.abs(func.coalesce(func.sum(PropEvent.available), 0)))
            .where(PropEvent.available < 0)
            .where(PropEvent.propagation_id == cls.id)
            .scalar_subquery()
        )

    @hybrid_property
    def used(self) -> int:
        return sum(acc.quantity_recvd or 0 for acc in self.accessions)

    @used.expression  # type: ignore [no-redef]
    def used(cls) -> ScalarSelect:
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
    def unused(self) -> int:
        """The quantity still available, after used or culled."""
        return self.available - self.used

    @unused.expression  # type: ignore [no-redef]
    def unused(cls) -> ScalarSelect:
        # pylint: disable=no-self-argument
        return cls.available - cls.used

    def __str__(self) -> str:

        parts: list[str] = [self.prop_type.name]

        if self.propagator:
            date_str = utils.date_string(self.date)
            parts.append(
                _("propagated by %s on %s") % (self.propagator, date_str)
            )

        if self.quantity:  # pylint: disable=using-constant-test
            parts.append(_("Quantity: %s") % self.quantity)

        if self.media:
            parts.append(_("Media: %s") % self.media)

        if self.container:
            parts.append(_("Container: %s") % self.container)

        if self.location:
            parts.append(_("Location: %s") % self.location)

        if self.prop_notes:
            parts.append(_("Notes: %s") % self.prop_notes)

        if self.success:  # pylint: disable=using-constant-test
            parts.append(_("Success: %s%%") % self.success)

        if self.unused:  # pylint: disable=using-constant-test
            parts.append(_("Available: %s") % self.unused)

        return "; ".join(parts)
