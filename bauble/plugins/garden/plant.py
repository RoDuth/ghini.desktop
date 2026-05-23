# Copyright 2008-2010 Brett Adams
# Copyright 2015-2017 Mario Frasca <mario@anche.no>.
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
#
"""
Defines the plant table and handled editing plants
"""

import logging

logger = logging.getLogger(__name__)

from collections.abc import Generator
from collections.abc import Sequence
from datetime import datetime

from gi.repository import Gtk
from sqlalchemy import Column
from sqlalchemy import ForeignKey
from sqlalchemy import Integer
from sqlalchemy import Unicode
from sqlalchemy import UnicodeText
from sqlalchemy import UniqueConstraint
from sqlalchemy import case
from sqlalchemy import event
from sqlalchemy import func
from sqlalchemy import inspect as sa_inspect
from sqlalchemy import select
from sqlalchemy import union
from sqlalchemy.ext.associationproxy import association_proxy
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import backref
from sqlalchemy.orm import deferred
from sqlalchemy.orm import object_mapper
from sqlalchemy.orm import relationship
from sqlalchemy.orm import synonym as sa_synonym
from sqlalchemy.orm import validates
from sqlalchemy.orm.attributes import get_history
from sqlalchemy.orm.session import object_session
from sqlalchemy.sql import cast
from sqlalchemy.sql.expression import ColumnElement

from bauble import btypes as types
from bauble import db
from bauble import meta
from bauble import utils
from bauble.i18n import _

from .accession import Accession
from .location import Location
from .propagation import PlantPropagation
from .propagation import Propagation

# TODO: might be worthwhile to have a label or textview next to the
# location combo that shows the description of the currently selected
# location

# meta keys
PLANT_DELIMITER_KEY = "plant_delimiter"
DEFAULT_PLANT_DELIMITER = "."
PLANT_CODE_FORMAT_KEY = "plant_code_format"
"""
Meta key for plant code format.

Values: 'alpha_lower', 'alpha_upper', 'digits'
"""
DEFAULT_PLANT_CODE_FORMAT = "digits"


# def branch_callback(objs: Sequence["Plant"], **kwargs) -> bool:
#     plants = objs
#     if plants[0].quantity <= 1:
#         msg = _(
#             "Not enough plants to split.  A plant should have at least "
#             "a quantity of 2 before it can be divided"
#         )
#         dialogs.message_dialog(msg, Gtk.MessageType.WARNING)
#         return False

#     e = PlantEditor(model=plants[0], branch_mode=True)
#     return e.start() is not None


def get_next_alpha_lower_code(codes: Sequence[str]) -> str:
    codes_lower = [
        code for code in codes if code[0].isalpha() and code[0].islower()
    ]

    if not codes_lower:
        return "a"

    last = max(codes_lower)
    stripped = last.rstrip("z")
    if stripped:
        return (
            stripped[:-1]
            + chr(ord(stripped[-1]) + 1)
            + "a" * (len(last) - len(stripped))
        )
    return "a" * (len(last) + 1)


def get_next_alpha_upper_code(codes: Sequence[str]) -> str:
    codes_upper = [
        code for code in codes if code[0].isalpha() and code[0].isupper()
    ]

    if not codes_upper:
        return "A"

    last = max(codes_upper)
    stripped = last.rstrip("Z")
    if stripped:
        return (
            stripped[:-1]
            + chr(ord(stripped[-1]) + 1)
            + "A" * (len(last) - len(stripped))
        )
    return "A" * (len(last) + 1)


def get_next_digit_code(codes: Sequence[str]) -> str:
    codes_digit = [code for code in codes if code[0].isdigit()]

    if not codes_digit:
        return "1"

    nxt = max(int(code) for code in codes_digit) + 1
    return str(nxt)


def get_next_code(acc: Accession) -> str:
    """Return the next available plant code for an accession.

    If there is an error getting the next code None is returned.
    """
    frmt: str | None = None
    frmt_meta = meta.get_default(
        PLANT_CODE_FORMAT_KEY, DEFAULT_PLANT_CODE_FORMAT
    )

    if frmt_meta:
        frmt = frmt_meta.value

    codes: Sequence[str] = [""]
    with db.engine.connect() as connection:
        codes = connection.scalars(
            select(Plant.code).join(Accession).where(Accession.id == acc.id)
        ).all()

    if frmt == "alpha_lower":
        return get_next_alpha_lower_code(codes)
    if frmt == "alpha_upper":
        return get_next_alpha_upper_code(codes)
    return get_next_digit_code(codes)


def set_code_format(*_args) -> None:
    """Set the plant code format."""
    msg = _(
        "Set the default plant code format, available options are: 'digits', "
        "'alpha_lower', 'alpha_upper'."
        "\n\nNote that any plants created before this change (that used the "
        "previous plant code format) will not change, you may need to do this "
        "manually."
    )
    current_frmt = ""
    current_meta = meta.get_default(
        PLANT_CODE_FORMAT_KEY, DEFAULT_PLANT_CODE_FORMAT
    )

    if current_meta:
        current_frmt = current_meta.value or ""

    meta.set_value(PLANT_CODE_FORMAT_KEY, current_frmt, msg)


PlantNote = db.make_note_class("Plant")
PlantPicture = db.make_note_class("Plant", cls_type="picture")


def _sort_by_val[K, V: str](dic: dict[K, V]) -> dict[K, V]:
    return dict(sorted(dic.items(), key=lambda x: x[1]))


common_reasons: dict[str | None, str] = _sort_by_val(
    {
        "ERRO": _("Error correction"),
        "OTHR": _("Other"),
        None: "",
    }
)

pltd: dict[str | None, str] = {
    "PLTD": _("New planting"),
}

new_plt_reasons: dict[str | None, str] = _sort_by_val(
    {
        "NTRL": _("Capture naturalised or original"),
        "PRIR": _("Unrecorded prior planting"),
        "ESTM": _("Estimated planting date"),
    }
    | common_reasons
    | pltd
)

tbac: dict[str | None, str] = {
    "TBAC": _("Transferred back"),
}

added_reasons: dict[str | None, str] = _sort_by_val(
    {
        "SLFS": _("Self seeded"),
        "VPIP": _("Vegetative propagated (in place)"),
    }
    | common_reasons
    | tbac
)

transfer_reasons: dict[str | None, str] = _sort_by_val(
    {
        "HOSP": _("Hospitalised"),
        "QUAR": _("Quarantined"),
        "TRAN": _("Transplanted to another area"),
        "DIST": _("Distributed elsewhere"),
    }
    | common_reasons
    | tbac
)

deleted_reasons: dict[str | None, str] = _sort_by_val(
    common_reasons
    | {
        "DEAD": _("Dead"),
        "DELE": _("Deleted, yr. dead. unknown"),
        "DNGM": _("Did not germinate"),
        "DISC": _("Discarded"),
        "DISN": _("Discarded, seedling in nursery"),
        "DISW": _("Discarded, weedy"),
        "GIVE": _("Given away (specify person)"),
        "LOST": _("Lost, whereabouts unknown"),
        "STOL": _("Stolen"),
        "SUMK": _("Summer Kill"),
        "ASS#": _("Transferred to another acc.no."),
        "VAND": _("Vandalised"),
        "WETH": _("Weather or natural event"),
        "WINK": _("Winter kill"),
    }
)

split_reasons: dict[str | None, str] = (
    pltd | added_reasons | transfer_reasons | common_reasons
)

change_reasons: dict[str | None, str] = (
    common_reasons
    | new_plt_reasons
    | added_reasons
    | transfer_reasons
    | deleted_reasons
)


class PlantChange(db.Base):
    __tablename__ = "plant_change"

    plant_id = Column(Integer, ForeignKey("plant.id"), nullable=False)
    parent_plant_id = Column(Integer, ForeignKey("plant.id"))
    child_plant_id = Column(Integer, ForeignKey("plant.id"))

    # - if to_location_id is None change is a removal
    # - if from_location_id is None then this change is a creation
    # - if to_location_id != from_location_id change is a transfer
    from_location_id = Column(Integer, ForeignKey("location.id"))
    to_location_id = Column(Integer, ForeignKey("location.id"))

    # the name of the person who made the change
    person = Column(Unicode(64), default=utils.get_user_display_name())

    quantity: int = Column(Integer, autoincrement=False, nullable=False)
    note_id = Column(Integer, ForeignKey("plant_note.id"))

    reason = Column(
        types.Enum(
            values=list(change_reasons.keys()), translations=change_reasons
        )
    )

    # date of change
    date = Column(types.DateTime(timezone=True), default=func.now())

    # relations
    plant: "Plant" = relationship(
        "Plant",
        uselist=False,
        primaryjoin="PlantChange.plant_id == Plant.id",
        backref=backref("changes", cascade="all, delete-orphan"),
    )
    parent_plant: "Plant" = relationship(
        "Plant",
        uselist=False,
        primaryjoin="PlantChange.parent_plant_id == Plant.id",
        backref=backref("branches"),
    )

    child_plant: "Plant" = relationship(
        "Plant",
        uselist=False,
        primaryjoin="PlantChange.child_plant_id == Plant.id",
        backref=backref(
            "branched_from", uselist=False, cascade="delete, delete-orphan"
        ),
    )

    from_location: "Location" = relationship(
        "Location", primaryjoin="PlantChange.from_location_id == Location.id"
    )
    to_location: "Location" = relationship(
        "Location", primaryjoin="PlantChange.to_location_id == Location.id"
    )


condition_values = {
    "Excellent": _("Excellent"),
    "Good": _("Good"),
    "Fair": _("Fair"),
    "Poor": _("Poor"),
    "Questionable": _("Questionable"),
    "Indistinguishable": _("Indistinguishable Mass"),
    "UnableToLocate": _("Unable to Locate"),
    "Dead": _("Dead"),
    None: "",
}

flowering_values = {
    "Immature": _("Immature"),
    "Flowering": _("Flowering"),
    "Old": _("Old Flowers"),
    None: "",
}

fruiting_values = {
    "Unripe": _("Unripe"),
    "Ripe": _("Ripe"),
    None: "",
}

# TODO: should sex be recorded at the species, accession or plant
# level or just as part of a check since sex can change in some species
sex_values = {"Female": _("Female"), "Male": _("Male"), "Both": ""}

# class Container(db.Base):
#     __tablename__ = 'container'
#     code = Column(Unicode)
#     name = Column(Unicode)


class PlantStatus(db.Base):
    """
    date: date checked
    status: status of plant
    comment: comments on check up
    checked_by: person who did the check
    """

    __tablename__ = "plant_status"
    date = Column(types.Date, default=func.now())
    condition = Column(
        types.Enum(
            values=list(condition_values.keys()), translations=condition_values
        )
    )
    comment = Column(UnicodeText)
    checked_by = Column(Unicode(64))

    flowering_status = Column(
        types.Enum(
            values=list(flowering_values.keys()), translations=flowering_values
        )
    )
    fruiting_status = Column(
        types.Enum(
            values=list(fruiting_values.keys()), translations=fruiting_values
        )
    )

    autumn_color_pct = Column(Integer, autoincrement=False)
    leaf_drop_pct = Column(Integer, autoincrement=False)
    leaf_emergence_pct = Column(Integer, autoincrement=False)

    sex = Column(
        types.Enum(values=list(sex_values.keys()), translations=sex_values)
    )

    # TODO: needs container table
    # container_id = Column(Integer)


acc_type_values = {
    "Plant": _("Plant"),
    "Seed": _("Seed/Spore"),
    "Vegetative": _("Vegetative Part"),
    "Tissue": _("Tissue Culture"),
    "Other": _("Other"),
    None: "",
}


class Plant(db.Domain, db.WithNotes):
    """
    :Table name: plant

    :Columns:
        *code*: :class:`sqlalchemy.types.Unicode`
            The plant code

        *acc_type*: :class:`bauble.types.Enum`
            The accession type

            Possible values:
                * Plant: Whole plant

                * Seed/Spore: Seed or Spore

                * Vegetative Part: Vegetative Part

                * Tissue Culture: Tissue culture

                * Other: Other, probably see notes for more information

                * None: no information, unknown

        *accession_id*: :class:`sqlalchemy.types.Integer`
            Required.

        *location_id*: :class:`sqlalchemy.types.Integer`
            Required.

        *geojson*:
            spatial data

    :Properties:
        *accession*:
            The accession for this plant.
        *location*:
            The location for this plant.
        *notes*:
            The notes for this plant.

    :Constraints:
        The combination of code and accession_id must be unique.
    """

    __tablename__ = "plant"
    __table_args__: tuple = (UniqueConstraint("code", "accession_id"), {})

    # columns
    code: str = Column(Unicode(6), nullable=False)

    acc_type = Column(
        types.Enum(
            values=list(acc_type_values.keys()), translations=acc_type_values
        ),
        default=None,
    )
    memorial = Column(types.Boolean, default=False)
    quantity: int = Column(Integer, autoincrement=False, nullable=False)

    accession_id = Column(Integer, ForeignKey("accession.id"), nullable=False)
    accession: "Accession" = relationship(
        "Accession", lazy="subquery", uselist=False, back_populates="plants"
    )

    location: Location
    location_id = Column(Integer, ForeignKey("location.id"), nullable=False)
    # spatial data deferred mainly to avoid comparison issues in union search
    # (i.e. reports)  NOTE that deferring can lead to the instance becoming
    # dirty when merged into another session (i.e. an editor) and the column
    # has already been loaded (i.e. infobox).  This can be avoided using a
    # separate db connection.
    # Also, NOTE that if not loaded (read) prior to changing a single list
    # history change will be recoorded with no indication of its value to the
    # change.  Can use something like:
    # `if plt.geojson != val: plt.geojson = val`
    geojson = deferred(Column(types.JSON()))

    propagations = association_proxy(
        "_plant_props",
        "propagation",
        creator=lambda prop: PlantPropagation(propagation=prop),
    )
    _plant_props: list["PlantPropagation"] = relationship(
        "PlantPropagation",
        cascade="all, delete-orphan",
        uselist=True,
        backref=backref("plant", uselist=False),
    )

    _pictures: db.Base = sa_synonym("pictures")

    # provide a way to search and use the change that recorded either a death
    # or a planting date directly.  This is not fool proof but close enough.
    death: "PlantChange" = relationship(
        "PlantChange",
        primaryjoin="and_(PlantChange.plant_id == Plant.id, "
        "PlantChange.id == select([PlantChange.id])"
        ".where(and_("
        "PlantChange.plant_id == Plant.id, "
        "PlantChange.from_location_id is not None, "
        "Plant.quantity == 0, "
        "PlantChange.quantity < 0))"
        ".correlate(Plant)"
        ".order_by(desc(PlantChange.date))"
        ".limit(1)"
        ".scalar_subquery())",
        viewonly=True,
        uselist=False,
    )

    planted: "PlantChange" = relationship(
        "PlantChange",
        primaryjoin="and_("
        "PlantChange.plant_id == Plant.id, "
        "PlantChange.id == select([PlantChange.id])"
        ".where(and_("
        "PlantChange.plant_id == Plant.id, "
        "PlantChange.to_location_id != None, "
        "PlantChange.child_plant_id == None, "
        "PlantChange.quantity > 0))"
        ".correlate(Plant)"
        ".order_by(PlantChange.date)"
        ".limit(1)"
        ".scalar_subquery())",
        viewonly=True,
        uselist=False,
    )

    _delimiter = None
    # see retrieve classmethod.
    retrieve_cols = ["id", "code", "accession", "accession.code"]

    @classmethod
    def retrieve(cls, session, keys):
        parts = ["id", "code"]
        plt_parts = {k: v for k, v in keys.items() if k in parts}

        if not plt_parts:
            return None

        query = session.query(cls).filter_by(**plt_parts)
        acc = keys.get("accession") or keys.get("accession.code")

        if acc:
            query = query.join(Accession).filter(Accession.code == acc)

        from sqlalchemy.orm.exc import MultipleResultsFound

        try:
            return query.one_or_none()
        except MultipleResultsFound:
            return None

    @validates("code")
    def validate_stripping(self, _key, value):  # pylint: disable=no-self-use
        if value is None:
            return None
        return value.strip()

    def search_view_markup_pair(self):
        """provide the two lines describing object for SearchView row."""
        sp_str = self.accession.species_str(markup=True, details=True)
        dead_color = "#9900ff"
        if self.quantity <= 0:
            dead_markup = (
                f'<span foreground="{dead_color}">'
                f"{utils.xml_safe(self)}</span>"
            )
            return dead_markup, sp_str
        located_counted = (
            f"{utils.xml_safe(self)} "
            '<span foreground="#555555" size="small" '
            f'weight="light">- {self.quantity} alive in '
            f"{utils.xml_safe(self.location)}</span>"
        )
        return located_counted, sp_str

    @classmethod
    def get_delimiter(cls, refresh=False):
        """Get the plant delimiter from the BaubleMeta table.

        The delimiter is cached the first time it is retrieved.  To refresh
        the delimiter from the database call with refresh=True.
        """
        if cls._delimiter is None or refresh:
            cls._delimiter = meta.get_default(
                PLANT_DELIMITER_KEY, DEFAULT_PLANT_DELIMITER
            ).value
        return cls._delimiter

    @classmethod
    def set_delimiter(cls, *_args):
        """Set the plant delimiter from user imput and refresh it."""
        msg = _(
            "Set the plant delimiter, a single character is recommended."
            "\n\nNote that any accession numbers/codes created before "
            "this change (that used the previous plant delimiter) will "
            "not change, you may need to do this manually."
        )
        delimeter = meta.set_value(
            PLANT_DELIMITER_KEY, cls.get_delimiter(), msg
        )
        if delimeter:
            cls._delimiter = delimeter[0].value
        return cls._delimiter

    @property
    def delimiter(self):
        return Plant.get_delimiter()

    @hybrid_property
    def active(self):
        return self.quantity > 0

    @active.expression  # type: ignore [no-redef]
    def active(cls):
        # pylint: disable=no-self-argument

        return cast(case([(cls.quantity > 0, 1)], else_=0), types.Boolean)

    @hybrid_property
    def updated(self) -> datetime:
        updates = [self._last_updated]

        if self.notes:
            updates.append(max(i._last_updated for i in self.notes))

        if self.pictures:
            updates.append(max(i._last_updated for i in self.pictures))

        if self.propagations:
            updates.append(max(i._last_updated for i in self.propagations))

        if self.changes:
            updates.append(max(i._last_updated for i in self.changes))

        return max(updates)

    @updated.expression  # type: ignore [no-redef]
    def updated(cls) -> types.DateTime:
        # pylint: disable=no-self-argument,no-self-use,arguments-renamed
        self_select = select([cls._last_updated, cls.id])

        note_select = select([PlantNote._last_updated, cls.id]).join(cls)

        pic_select = select([PlantPicture._last_updated, cls.id]).join(cls)

        prop_select = (
            select([Propagation._last_updated, cls.id])
            .join(
                PlantPropagation,
                PlantPropagation.propagation_id == Propagation.id,
            )
            .join(cls)
        )

        change_select = select([PlantChange._last_updated, cls.id]).join(
            cls, PlantChange.plant_id == cls.id
        )

        dates = union(
            self_select,
            note_select,
            pic_select,
            prop_select,
            change_select,
        ).alias("dates")

        return (
            select([func.max(dates.c._last_updated)])
            .where(dates.c.id == cls.id)
            .label("updated")
        )

    def __str__(self):
        return f"{self.accession}{self.delimiter}{self.code}"

    def duplicate(self, code=None, session=None):
        """Return a Plant that is a flat (not deep) duplicate of self. For
        notes, changes and propagations, you should refer to the original
        plant.

        :param code: the new plants code
        :param session: the session to add the duplicate to.

        ... Note if no session is supplied it will be in the same session
        as the plant currently is.  This is most likely not what you want.
        """
        plant = Plant()
        if not session:
            session = object_session(self)
            if session:
                session.add(plant)

        include = (
            "acc_type",
            "memorial",
            "quantity",
            "accession_id",
            "location_id",
            "accession",
            "location",
        )
        for prop in include:
            val = getattr(self, prop)
            logger.debug("duplicating plant with %s: %s", prop, val)
            setattr(plant, prop, val)
        plant.code = code

        return plant

    def markup(self):
        return (
            f"{self.accession}{self.delimiter}{self.code} "
            f"({self.accession.species_str(markup=True)})"
        )

    def parent_objects(self) -> Generator[tuple[db.Domain, ...], None, None]:
        yield (self.location,)

        source = self.accession.source and self.accession.source.source_detail
        if source:
            yield (source,)

        yield (
            self.accession.species.genus.family,
            self.accession.species.genus,
            self.accession.species,
            self.accession,
        )

        collection = self.accession.source and self.accession.source.collection
        if collection:
            yield (collection,)

        vern_names = self.accession.species.vernacular_names
        for name in vern_names:
            yield (name, self.accession)

        dists = self.accession.species.distribution
        for dist in dists:
            yield (dist.geography, self.accession.species, self.accession)

    @classmethod
    def top_level_count(
        cls,
        ids: list[int],
        exclude_inactive: bool = False,
    ) -> db.TopLevelCount:

        from ..plants import Family
        from ..plants import Genus
        from ..plants import Species
        from . import Source
        from . import SourceDetail

        base_ids_stmt = (
            select(
                Family.id,
                Genus.id,
                Species.id,
                Accession.id,
                cls.id,
                Location.id,
                SourceDetail.id,
            )
            .select_from(cls)
            .join(Accession)
            .join(Species)
            .join(Genus)
            .join(Family)
            .join(Location)
            .outerjoin(Source)
            .outerjoin(SourceDetail)
        )

        base_count_stmt = select(
            func.sum(Plant.quantity),
        ).select_from(cls)

        result = cls._top_level_counter_helper(
            base_ids_stmt, base_count_stmt, ids
        )
        return db.TopLevelCount(*result)

    @classmethod
    def top_level_count_id(cls, exclude_inactive: bool) -> ColumnElement:
        if exclude_inactive:
            return case([(cls.quantity > 0, cls.id)], else_=None)
        return cls.id


# ensure an appropriate change has been capture for all changes or insertions.
# In the editor this will create 2 changes if both the location and the
# quantity are changed (using the supplied reason). The current change will be
# corrected and a new one adding.  In imports etc. this should trigger the
# creation of an appropriate change without a reason.
@event.listens_for(Plant, "after_update")
def plant_after_update(
    _mapper, connection, target
):  # pylint: disable=too-many-locals
    changes = []
    to_update = None
    session = object_session(target)
    reason = date = None
    for change in target.changes:
        if change in session.new:
            logger.debug("%s has new change %s", target, change.__dict__)
            reason = str(change.reason) if change.reason else None
            date = str(change.date) if change.date else None
            # capture change to use below
            to_update = change
            # bail early if a split change
            if to_update.child_plant:
                logger.debug("is split change bailing early")
                return

    loc_history = get_history(target, "location_id")
    qty_history = get_history(target, "quantity")
    from_loc = loc_history.deleted[0] if loc_history.deleted else None
    to_loc = loc_history.added[0] if loc_history.added else None
    # NOTE if both location and quantity have changed likely want 2 changes
    if qty_history.has_changes():
        # NOTE has_changes can pick up str/int/etc changes and not just ints so
        # to be sure convert to int first.  It also possible that only added or
        # deleted will exist not both.
        added = int(qty_history.added[0] if qty_history.added else 0)
        deleted = int(qty_history.deleted[0] if qty_history.deleted else 0)
        quantity_change = added - deleted
        logger.debug("%s has quantity change %s", target, quantity_change)
        if quantity_change > 0:
            logger.debug(
                "%s has quantity increase %s", target, quantity_change
            )
            values = {
                "plant_id": target.id,
                "date": date,
                "reason": reason,
                "quantity": quantity_change,
                "to_location_id": target.location_id,
            }
            values = {k: v for k, v in values.items() if v is not None}
            changes.append(values)
        elif quantity_change < 0:
            logger.debug(
                "%s has quantity decrease %s", target, quantity_change
            )
            values = {
                "plant_id": target.id,
                "date": date,
                "reason": reason,
                "quantity": quantity_change,
                "from_location_id": target.location_id,
            }
            values = {k: v for k, v in values.items() if v is not None}
            changes.append(values)

    if loc_history.has_changes():
        quantity_change = (
            qty_history.deleted[0] if qty_history.deleted else target.quantity
        )
        logger.debug("%s has location change %s->%s", target, from_loc, to_loc)
        values = {
            "plant_id": target.id,
            "date": date,
            "reason": reason,
            "quantity": quantity_change,
            "from_location_id": from_loc,
            "to_location_id": to_loc,
        }
        values = {k: v for k, v in values.items() if v is not None}
        changes.append(values)

    for values in changes:
        if to_update:
            logger.debug("update existing change with %s", values)
            to_update.to_location_id = None
            to_update.from_location_id = None
            for k, v in values.items():
                setattr(to_update, k, v)
            to_update = None
        else:
            logger.debug("creating new change with %s", values)
            result = connection.execute(
                PlantChange.__table__.insert().values(values)
            )
            # add a history entry to the database, new_change created here is
            # throw away
            if date is None:
                values["date"] = str(datetime.now())
            new_change = PlantChange(
                **values, id=result.inserted_primary_key[0]
            )
            db.History.event_add(
                "insert",
                object_mapper(new_change).local_table,
                connection,
                new_change,
            )


@event.listens_for(Plant, "after_insert")
def plant_after_insert(_mapper, connection, target):
    session = object_session(target)
    for change in target.changes:
        if change in session.new:
            logger.debug("new plant has change")
            # Imports etc. may not have added these.  Add them when needed.
            if change.quantity is None:
                logger.debug("new plant change, adding quantity")
                change.quantity = target.quantity
            if change.to_location is None:
                # this wont deal with a branched/split plants, branches should
                # only happen in the editor
                logger.debug("new plant change, adding location")
                change.to_location_id = target.location_id
            return

    # get here for imports etc. editor should always supply a change
    logger.debug("new plant adding a change")
    plant_changes_table = PlantChange.__table__

    values = {
        "plant_id": target.id,
        "quantity": target.quantity,
        "to_location_id": target.location_id,
        "date": str(datetime.now()),
    }
    result = connection.execute(plant_changes_table.insert().values(values))

    # add a history entry to the database, new_change created here is throw
    # away
    new_change = PlantChange(**values, id=result.inserted_primary_key[0])
    db.History.event_add(
        "insert", object_mapper(new_change).local_table, connection, new_change
    )


def move_quantity_between_plants(from_plant, to_plant, to_plant_change=None):
    session = object_session(to_plant)
    logger.debug("from_plant = %s", from_plant)
    if to_plant_change is None:
        to_plant_change = PlantChange()
        session.add(to_plant_change)
    from_plant_change = PlantChange()
    session.add(from_plant_change)

    from_plant.quantity -= to_plant.quantity

    to_plant_change.plant = to_plant
    to_plant_change.parent_plant = from_plant
    to_plant_change.quantity = to_plant.quantity
    to_plant_change.to_location = to_plant.location
    to_plant_change.from_location = from_plant.location

    from_plant_change.plant = from_plant
    from_plant_change.child_plant = to_plant
    from_plant_change.quantity = to_plant.quantity
    from_plant_change.date = to_plant_change.date
    from_plant_change.reason = to_plant_change.reason
    from_plant_change.to_location = to_plant.location
    from_plant_change.from_location = from_plant.location


def plant_to_string_matcher(plant: Plant, text: str) -> bool:
    """Helper function to match string or partial string of the pattern
    'PLANTCODE Genus species' with a Plant.

    Allows partial matches (e.g. 'Den d', 'Dendr', 'XXX D d', 'XX' will all
    match 'XXXX.0001.1 (Dendrobium discolor)').  Searches are case insensitive.

    :param plant: a Plant table entry
    :param text: the string to search with

    :return: bool, True if the Plant matches the key
    """
    text = text.lower()

    if not sa_inspect(plant).persistent:
        return False

    species = plant.accession.species
    parts = text.split(" ", 1)
    plt_match = sp_match = False
    _accept_one = False
    if len(parts) == 1:
        plt_code = sp_str = text
        _accept_one = True
    else:
        plt_code = parts[0]
        sp_str = parts[1]

    # match the plant code
    if str(plant).lower().startswith(plt_code):
        plt_match = True

    # or the species
    from ..plants.ui.widgets.species import species_to_string_matcher

    if plt_match:
        sp_match = species_to_string_matcher(species, sp_str)
    elif species_to_string_matcher(species, text):
        sp_match = True
        _accept_one = True

    if _accept_one:
        return any((plt_match, sp_match))
    return all((plt_match, sp_match))


def plant_match_func(
    completion: Gtk.EntryCompletion,
    key: str,
    treeiter: int,
) -> bool:
    """match_func that allows partial matches on both plant code, Genus and
    species.

    :param completion: the completion to match
    :param key: lowercase string of the entry text
    :param treeiter: the row number for the item to match

    :return: bool, True if the item at the treeiter matches the key
    """
    tree_model = completion.get_model()
    if not tree_model:
        raise AttributeError(f"can't get TreeModel from {completion}")
    plant = tree_model[treeiter][0]
    return plant_to_string_matcher(plant, key)
