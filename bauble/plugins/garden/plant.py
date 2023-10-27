# Copyright 2008-2010 Brett Adams
# Copyright 2015-2017 Mario Frasca <mario@anche.no>.
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
#

"""
Defines the plant table and handled editing plants
"""

import logging
import os
import traceback
from datetime import datetime
from pathlib import Path
from random import random

logger = logging.getLogger(__name__)

from gi.repository import Gtk
from pyparsing import Literal
from pyparsing import OneOrMore
from pyparsing import ParseException
from pyparsing import Word
from pyparsing import delimitedList
from pyparsing import oneOf
from pyparsing import printables
from pyparsing import quotedString
from pyparsing import removeQuotes
from pyparsing import stringEnd
from sqlalchemy import Column
from sqlalchemy import ForeignKey
from sqlalchemy import Integer
from sqlalchemy import Unicode
from sqlalchemy import UnicodeText
from sqlalchemy import UniqueConstraint
from sqlalchemy import and_
from sqlalchemy import event
from sqlalchemy import func
from sqlalchemy import not_
from sqlalchemy import or_
from sqlalchemy import tuple_
from sqlalchemy.exc import DBAPIError
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.associationproxy import association_proxy
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import backref
from sqlalchemy.orm import deferred
from sqlalchemy.orm import object_mapper
from sqlalchemy.orm import relationship
from sqlalchemy.orm import validates
from sqlalchemy.orm.attributes import get_history
from sqlalchemy.orm.session import object_session

from bauble import btypes as types
from bauble import db
from bauble import meta
from bauble import paths
from bauble import prefs
from bauble import utils
from bauble.editor import GenericEditorPresenter
from bauble.editor import GenericEditorView
from bauble.editor import GenericModelViewPresenterEditor
from bauble.editor import NotesPresenter
from bauble.editor import PicturesPresenter
from bauble.editor import PresenterMapMixin
from bauble.error import CheckConditionError
from bauble.search import SearchStrategy
from bauble.utils.geo import KMLMapCallbackFunctor
from bauble.view import Action
from bauble.view import InfoBox
from bauble.view import InfoExpander
from bauble.view import LinksExpander
from bauble.view import PropertiesExpander
from bauble.view import select_in_search_results

from .accession import Accession
from .location import Location
from .location import LocationEditor
from .propagation import PlantPropagation

# TODO: might be worthwhile to have a label or textview next to the
# location combo that shows the description of the currently selected
# location

plant_delimiter_key = "plant_delimiter"
default_plant_delimiter = "."


def edit_callback(plants):
    e = PlantEditor(model=plants[0])
    return e.start() is not None


def branch_callback(plants):
    if plants[0].quantity <= 1:
        msg = _(
            "Not enough plants to split.  A plant should have at least "
            "a quantity of 2 before it can be divided"
        )
        utils.message_dialog(msg, Gtk.MessageType.WARNING)
        return None

    e = PlantEditor(model=plants[0], branch_mode=True)
    return e.start() is not None


def remove_callback(plants):
    p_str = ", ".join([str(p) for p in plants])
    msg = _(
        "Are you sure you want to remove the following plants?\n\n%s\n\n"
        "<small>Note that deleting a plant can destroy related data.  If "
        "the plant has died set its quantity to zero rather than delete "
        "it.</small>"
    ) % utils.xml_safe(p_str)
    if not utils.yes_no_dialog(msg):
        return False

    session = object_session(plants[0])
    for plant in plants:
        if plant.branches:
            msg = _(
                "%s has plant(s) split from it.  Removing this plant "
                "will destroy their link back.  Are you sure you want to "
                "want to delete it?"
            ) % utils.xml_safe(plant)
            if not utils.yes_no_dialog(msg):
                plants.remove(plant)
                continue
        if plant.propagations:
            msg = _(
                "%s has propagations.  Removing this plant will destroy "
                "these propagations and possibly the source data for any "
                "accessions created from them.  Are you sure you want to "
                "want to delete it?"
            ) % utils.xml_safe(plant)
            if not utils.yes_no_dialog(msg):
                plants.remove(plant)
                continue
        session.delete(plant)
    try:
        utils.remove_from_results_view(plants)
        session.commit()
    except Exception as e:  # pylint: disable=broad-except
        msg = _("Could not delete.\n\n%s") % utils.xml_safe(e)
        logger.debug("remove_callback - (%s(%s)", type(e).__name__, e)
        utils.message_details_dialog(
            msg, traceback.format_exc(), Gtk.MessageType.ERROR
        )
        session.rollback()
    return True


PLANT_KML_MAP_PREFS = "kml_templates.plant"
"""pref for path to a custom mako kml template."""

map_kml_callback = KMLMapCallbackFunctor(
    prefs.prefs.get(
        PLANT_KML_MAP_PREFS, str(Path(__file__).resolve().parent / "plant.kml")
    )
)


edit_action = Action(
    "plant_edit", _("_Edit"), callback=edit_callback, accelerator="<ctrl>e"
)

branch_action = Action(
    "plant_branch",
    _("_Split"),
    callback=branch_callback,
    accelerator="<ctrl>b",
)

remove_action = Action(
    "plant_remove",
    _("_Delete"),
    callback=remove_callback,
    accelerator="<ctrl>Delete",
    multiselect=True,
)

map_action = Action(
    "plant_show_in_map",
    _("Show in _map"),
    callback=map_kml_callback,
    accelerator="<ctrl>m",
    multiselect=True,
)

plant_context_menu = [edit_action, branch_action, remove_action, map_action]


def get_next_code(acc):
    """Return the next available plant code for an accession.

    This function should be specific to the institution.

    If there is an error getting the next code the None is returned.
    """
    # auto generate/increment the accession code
    session = db.Session()
    codes = (
        session.query(Plant.code)
        .join(Accession)
        .filter(Accession.id == acc.id)
        .all()
    )
    nxt = 1
    if codes:
        try:
            nxt = max([int(code[0]) for code in codes]) + 1
        except Exception as e:  # pylint: disable=broad-except
            logger.debug(
                "can't get next plant code %s(%s)", type(e).__name__, e
            )
            return None
    return str(nxt)


def is_code_unique(plant, code):
    """Return True/False if the code is a unique Plant code for accession.

    This method will also take range values for code that can be passed
    to utils.range_builder()
    """
    # if the range builder only creates one number then we assume the
    # code is not a range and so we test against the string version of
    # code
    try:
        codes = [str(i) for i in utils.range_builder(code)]
    except CheckConditionError:
        return False
    if len(codes) == 1:
        codes = [str(code)]

    # reference accesssion.id instead of accession_id since
    # setting the accession on the model doesn't set the
    # accession_id until the session is flushed
    session = db.Session()
    count = (
        session.query(Plant)
        .join("accession")
        .filter(
            and_(Accession.id == plant.accession.id, Plant.code.in_(codes))
        )
        .count()
    )
    session.close()
    return count == 0


class PlantSearch(SearchStrategy):
    @staticmethod
    def use(text: str) -> str:
        if (
            text.startswith("plant")
            and len(splt := text.split()) > 1
            and splt[1] != "where"
        ):
            logger.debug("reducing strategies to PlantSearch")
            return "only"
        return "exclude"

    def search(self, text, session):
        # pylint: disable=too-many-branches,too-many-locals,too-many-statements
        """domain search for plants, only returns a result if appropriate
        string is supplied.  Searches a combination of Accession.code,
        delimiter and Plant.code.

        special search strategy, can't be obtained in MapperSearch
        """
        super().search(text, session)
        domain = Literal("planting") | Literal("plant")
        operator = oneOf("= == != <> like contains has")
        value = quotedString.setParseAction(removeQuotes) | Word(printables)
        value_list = OneOrMore(value) | delimitedList(value)
        equals = Literal("=")
        star_value = Literal("*")
        in_op = Literal("in")
        statement = (
            (domain + equals + star_value + stringEnd)
            | (domain + operator + value + stringEnd)
            | (domain + in_op + value_list + stringEnd)
        )

        if not text.startswith("plant"):
            # Shouldn't really get here as use() filter should take care of it.
            return []
        delimiter = Plant.get_delimiter()
        try:
            parsed = statement.parseString(text)
            operator = parsed[1]
            values = parsed[2:]
        except ParseException as e:
            logger.debug("PlantSearch %s %s", type(e).__name__, e)
            return []

        if operator != "in":
            value = values[0]
            acc_code = plant_code = value
            if delimiter in value:
                acc_code, plant_code = value.rsplit(delimiter, 1)

        if operator in ["=", "==", "!=", "<>"]:
            if value == "*":
                if operator in ("!=", "<>"):
                    return []
                logger.debug('"star" PlantSearch, returning all plants')
                return [session.query(Plant)]
            if delimiter not in value:
                logger.debug("delimiter not found, can't split the code")
                return []
            if operator in ["!=", "<>"]:
                logger.debug(
                    '"not equals" PlantSearch accession: %s plant: ' "%s",
                    acc_code,
                    plant_code,
                )
                query = (
                    session.query(Plant)
                    .join(Accession)
                    .filter(
                        not_(
                            and_(
                                Plant.code == plant_code,
                                Accession.code == acc_code,
                            )
                        )
                    )
                )
            else:
                logger.debug(
                    '"equals" PlantSearch accession: %s plant: %s',
                    acc_code,
                    plant_code,
                )
                query = (
                    session.query(Plant)
                    .filter(Plant.code == plant_code)
                    .join(Accession)
                    .filter(Accession.code == acc_code)
                )

        elif operator in ["contains", "has"]:
            # could be better possibly?
            logger.debug(
                '"contains" PlantSearch accession: %s plant: %s',
                acc_code,
                plant_code,
            )
            query = (
                session.query(Plant)
                .join(Accession)
                .filter(
                    or_(
                        utils.ilike(Plant.code, f"%%{plant_code}%%"),
                        utils.ilike(Accession.code, f"%%{acc_code}%%"),
                    )
                )
            )
        elif operator == "like":
            logger.debug(
                '"like" PlantSearch accession: %s plant: %s',
                acc_code,
                plant_code,
            )
            query = (
                session.query(Plant)
                .join(Accession)
                .filter(
                    and_(
                        utils.ilike(Plant.code, plant_code),
                        utils.ilike(Accession.code, acc_code),
                    )
                )
            )
        else:
            # 'in'
            vals = []
            for value in values:
                if delimiter not in value:
                    logger.debug("delimiter not found, can't split the code")
                    return []
                acc_code, plant_code = value.rsplit(delimiter, 1)
                vals.append((acc_code, plant_code))
            logger.debug('"in" PlantSearch vals: %s', vals)
            if db.engine.name == "mssql":
                from sqlalchemy import String
                from sqlalchemy.sql import column
                from sqlalchemy.sql import exists
                from sqlalchemy.sql import values

                sql_vals = (
                    values(
                        column("acc_code", String), column("plt_code", String)
                    )
                    .data(vals)
                    .alias("val")
                )
                query = (
                    session.query(Plant)
                    .join(Accession)
                    .filter(
                        exists().where(
                            Accession.code == sql_vals.c.acc_code,
                            Plant.code == sql_vals.c.plt_code,
                        )
                    )
                )
            else:
                # sqlite, postgresql
                query = (
                    session.query(Plant)
                    .join(Accession)
                    .filter(tuple_(Accession.code, Plant.code).in_(vals))
                )

        return [query]


PlantNote = db.make_note_class("Plant")
PlantPicture = db.make_note_class("Plant", cls_type="picture")


change_reasons = {
    "NTRL": _("Capture naturalised or original"),
    "DEAD": _("Dead"),
    "DELE": _("Deleted, yr. dead. unknown"),
    "DNGM": _("Did not germinate"),
    "DISC": _("Discarded"),
    "DISN": _("Discarded, seedling in nursery"),
    "DISW": _("Discarded, weedy"),
    "DIST": _("Distributed elsewhere"),
    "ERRO": _("Error correction"),
    "ESTM": _("Estimated planting date"),
    "GIVE": _("Given away (specify person)"),
    "HOSP": _("Hospitalised"),
    "LOST": _("Lost, whereabouts unknown"),
    "PLTD": _("New planting"),
    "OTHR": _("Other"),
    "QUAR": _("Quarantined"),
    "SLFS": _("Self seeded"),
    "STOL": _("Stolen"),
    "SUMK": _("Summer Kill"),
    "TBAC": _("Transferred back"),
    "ASS#": _("Transferred to another acc.no."),
    "TRAN": _("Transplanted to another area"),
    "PRIR": _("Unrecorded prior planting"),
    "VAND": _("Vandalised"),
    "VPIP": _("Vegetative propagated (in place)"),
    "WETH": _("Weather or natural event"),
    "WINK": _("Winter kill"),
    None: "",
}

common_reasons = ["ERRO", "OTHR", None]
new_plt_reasons = ["PLTD", "NTRL", "PRIR", "ESTM"]
added_reasons = ["TBAC", "SLFS", "VPIP"]
transfer_reasons = ["HOSP", "QUAR", "TRAN", "DIST", "TBAC"]
split_reasons = ["PLTD"] + added_reasons + transfer_reasons + common_reasons


def _sort_by_val(dic):
    return dict(sorted(dic.items(), key=lambda x: x[1]))


deleted_reasons = {
    k: v
    for k, v in change_reasons.items()
    if k not in added_reasons + new_plt_reasons
}
new_plt_reasons = _sort_by_val(
    {
        k: v
        for k, v in change_reasons.items()
        if k in new_plt_reasons + common_reasons
    }
)
added_reasons = _sort_by_val(
    {
        k: v
        for k, v in change_reasons.items()
        if k in added_reasons + common_reasons
    }
)
transfer_reasons = _sort_by_val(
    {
        k: v
        for k, v in change_reasons.items()
        if k in transfer_reasons + common_reasons
    }
)
split_reasons = _sort_by_val(
    {k: v for k, v in change_reasons.items() if k in split_reasons}
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

    quantity = Column(Integer, autoincrement=False, nullable=False)
    note_id = Column(Integer, ForeignKey("plant_note.id"))

    reason = Column(
        types.Enum(
            values=list(change_reasons.keys()), translations=change_reasons
        )
    )

    # date of change
    date = Column(types.DateTime(timezone=True), default=func.now())

    # relations
    plant = relationship(
        "Plant",
        uselist=False,
        primaryjoin="PlantChange.plant_id == Plant.id",
        backref=backref("changes", cascade="all, delete-orphan"),
    )
    parent_plant = relationship(
        "Plant",
        uselist=False,
        primaryjoin="PlantChange.parent_plant_id == Plant.id",
        backref=backref("branches"),
    )

    child_plant = relationship(
        "Plant",
        uselist=False,
        primaryjoin="PlantChange.child_plant_id == Plant.id",
        backref=backref(
            "branched_from", uselist=False, cascade="delete, delete-orphan"
        ),
    )

    from_location = relationship(
        "Location", primaryjoin="PlantChange.from_location_id == Location.id"
    )
    to_location = relationship(
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


class Plant(db.Base, db.WithNotes):
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
    __table_args__ = (UniqueConstraint("code", "accession_id"), {})

    # columns
    code = Column(Unicode(6), nullable=False)

    acc_type = Column(
        types.Enum(
            values=list(acc_type_values.keys()), translations=acc_type_values
        ),
        default=None,
    )
    memorial = Column(types.Boolean, default=False)
    quantity = Column(Integer, autoincrement=False, nullable=False)

    accession_id = Column(Integer, ForeignKey("accession.id"), nullable=False)
    accession = relationship(
        "Accession", lazy="subquery", uselist=False, back_populates="plants"
    )

    location_id = Column(Integer, ForeignKey(Location.id), nullable=False)
    # spatial data deferred mainly to avoid comparison issues in union search
    # (i.e. reports)  NOTE that deferring can lead to the instance becoming
    # dirty when merged into another session (i.e. an editor) and the column
    # has already been loaded (i.e. infobox)
    geojson = deferred(Column(types.JSON()))

    propagations = association_proxy(
        "_plant_props",
        "propagation",
        creator=lambda prop: PlantPropagation(propagation=prop),
    )
    _plant_props = relationship(
        "PlantPropagation",
        cascade="all, delete-orphan",
        uselist=True,
        backref=backref("plant", uselist=False),
    )

    # provide a way to search and use the change that recorded either a death
    # or a planting date directly.  This is not fool proof but close enough.
    death = relationship(
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

    planted = relationship(
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
        sp_str = self.accession.species_str(markup=True)
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
                plant_delimiter_key, default_plant_delimiter
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
            plant_delimiter_key, cls.get_delimiter(), msg
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

    @active.expression
    def active(cls):
        # pylint: disable=no-self-argument
        from sqlalchemy.sql.expression import case
        from sqlalchemy.sql.expression import cast

        return cast(case([(cls.quantity > 0, 1)], else_=0), types.Boolean)

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

    def top_level_count(self):
        source = self.accession.source and self.accession.source.source_detail
        return {
            (1, "Plantings"): 1,
            (2, "Accessions"): set([self.accession.id]),
            (3, "Species"): set([self.accession.species.id]),
            (4, "Genera"): set([self.accession.species.genus.id]),
            (5, "Families"): set([self.accession.species.genus.family.id]),
            (6, "Living plants"): self.quantity,
            (7, "Locations"): set([self.location.id]),
            (8, "Sources"): set([source.id] if source else []),
        }


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
        else:
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


class PlantEditorView(GenericEditorView):
    _tooltips = {
        "plant_code_entry": _(
            "The planting code must be a unique code for "
            "the accession.  You may also use ranges "
            "like 1,2,7 or 1-3 to create multiple "
            "plants."
        ),
        "plant_acc_entry": _(
            "The accession must be selected from the list "
            "of completions.  To add an accession use the "
            "Accession editor."
        ),
        "plant_loc_comboentry": _(
            "The location of the planting in your collection."
        ),
        "plant_acc_type_combo": _(
            "The type of the plant material.\n\n" "Possible values: %s"
        )
        % (", ".join(list(acc_type_values.values()))),
        "plant_loc_add_button": _("Create a new location."),
        "plant_loc_edit_button": _("Edit the selected location."),
        "prop_add_button": _(
            "Create a new propagation record for this plant."
        ),
        "pad_cancel_button": _("Cancel your changes."),
        "pad_ok_button": _("Save your changes."),
        "pad_next_button": _("Save your changes and add another plant."),
        "plant_changes_treeview": _(
            "While some minimal editing is possible here it is most often not "
            "wise to do so. Changes are normally triggered by events. "
            "Date changes may confuse the plants history and reasons are not "
            "constrained here as in the main editor.  Use at your own risk."
        ),
        "change_grid": _(
            "Changes are recorded for new entries and whenever "
            "the quantity or location is changed.\n\nThe "
            'earliest recorded change becomes the "planted" '
            "change.  The last recorded change that reduces "
            'quantity to 0 becomes the "death"'
        ),
    }

    def __init__(self, parent=None):
        glade_file = os.path.join(
            paths.lib_dir(), "plugins", "garden", "plant_editor.glade"
        )
        super().__init__(
            glade_file, parent=parent, root_widget_name="plant_dialog"
        )
        self.widgets.pad_ok_button.set_sensitive(False)
        self.widgets.pad_next_button.set_sensitive(False)

        def acc_cell_data_func(_column, renderer, model, treeiter):
            value = model[treeiter][0]
            # when cancelling an insert sometimes the session gets lost and can
            # result in a long cycle of DetachedInstanceErrors. So check first
            from sqlalchemy import inspect as sa_inspect

            if sa_inspect(value).persistent:
                renderer.set_property("text", f"{value} ({value.species})")

        self.attach_completion(
            "plant_acc_entry",
            cell_data_func=acc_cell_data_func,
            match_func=acc_match_func,
            minimum_key_length=2,
        )
        self.init_translatable_combo("plant_acc_type_combo", acc_type_values)
        self.widgets.notebook.set_current_page(0)

    def get_window(self):
        return self.widgets.plant_editor_dialog

    def save_state(self):
        pass

    def restore_state(self):
        pass


# could live in accession but is only used here so for now leave here...
def acc_to_string_matcher(accession: Accession, key: str) -> bool:
    """Helper function to match string or partial string of the pattern
    'ACCESSIONCODE Genus species' with an Accession.

    Allows partial matches (e.g. 'Den d', 'Dendr', 'XX D d' will all match
    'XXX.0001 (Dendrobium discolor)').  Searches are case insensitive.

    :param accession: an Accession table entry
    :param key: the string to search with

    :return: bool, True if the Species matches the key
    """
    key = key.lower()
    species = accession.species
    parts = key.split(" ", 1)
    acc_match = sp_match = False
    _accept_one = False
    if len(parts) == 1:
        acc_code = sp_str = key
        _accept_one = True
    else:
        acc_code = parts[0]
        sp_str = parts[1]

    # match the plant code
    if str(accession).lower().startswith(acc_code):
        acc_match = True

    # or the species
    from ..plants.species_editor import species_to_string_matcher

    if acc_match:
        sp_match = species_to_string_matcher(species, sp_str)
    elif species_to_string_matcher(species, key):
        sp_match = True
        _accept_one = True

    if _accept_one:
        return any((acc_match, sp_match))
    return all((acc_match, sp_match))


def acc_match_func(
    completion: Gtk.EntryCompletion, key: str, treeiter: int
) -> bool:
    """match_func that allows partial matches on both accession code,
    Genus and species.

    :param completion: the completion to match
    :param key: lowercase string of the entry text
    :param treeiter: the row number for the item to match

    :return: bool, True if the item at the treeiter matches the key
    """
    accession = completion.get_model()[treeiter][0]
    return acc_to_string_matcher(accession, key)


class PlantEditorPresenter(GenericEditorPresenter, PresenterMapMixin):
    widget_to_field_map = {
        "plant_code_entry": "code",
        "plant_acc_entry": "accession",
        "plant_loc_comboentry": "location",
        "plant_acc_type_combo": "acc_type",
        "plant_memorial_check": "memorial",
        "plant_quantity_entry": "quantity",
    }

    PROBLEM_DUPLICATE_PLANT_CODE = f"duplicate_plant_code:{random()}"
    PROBLEM_INVALID_QUANTITY = f"invalid_quantity:{random()}"

    def __init__(self, model, view, branch_mode=False):
        """
        :param model: should be an instance of Plant class
        :param view: should be an instance of PlantEditorView
        """
        super().__init__(model, view)
        self.session = object_session(model)
        self.branch_mode = branch_mode
        self._original_accession_id = self.model.accession_id
        self._original_code = self.model.code
        self._original_location = self.model.location

        # if the model is in session.new then it might be a branched
        # plant so don't store it....is this hacky?
        self.upper_quantity_limit = float("inf")
        if model in self.session.new:
            self._original_quantity = None
            self.lower_quantity_limit = 1
        else:
            self._original_quantity = self.model.quantity
            self.lower_quantity_limit = 0
        self._dirty = False

        # set default values for acc_type
        if self.model.id is None and self.model.acc_type is None:
            self.model.acc_type = "Plant"

        notes_parent = self.view.widgets.notes_parent_box
        notes_parent.foreach(notes_parent.remove)
        self.notes_presenter = NotesPresenter(self, "notes", notes_parent)

        pictures_parent = self.view.widgets.pictures_parent_box
        pictures_parent.foreach(pictures_parent.remove)
        self.pictures_presenter = PicturesPresenter(
            self, "pictures", pictures_parent
        )

        from bauble.plugins.garden.propagation import PropagationTabPresenter

        self.prop_presenter = PropagationTabPresenter(
            self, self.model, self.view, self.session
        )

        # if the PlantEditor has been started with a new plant but
        # the plant is already associated with an accession
        if self.model.accession and not self.model.code:
            code = get_next_code(self.model.accession)
            if code:
                # if get_next_code() returns None then there was an error
                self.set_model_attr("code", code)

        def on_location_select(location):
            if self.initializing or not isinstance(location, Location):
                return
            self.set_model_attr("location", location)
            if self.change.quantity is None:
                self.change.quantity = self.model.quantity
            self.refresh_view()

        from . import init_location_comboentry

        init_location_comboentry(
            self, self.view.widgets.plant_loc_comboentry, on_location_select
        )

        self.change = PlantChange()
        self.session.add(self.change)
        self.change.plant = self.model
        self.change.from_location = self.model.location
        self.change.quantity = self.model.quantity

        def on_reason_changed(combo):
            itr = combo.get_active_iter()
            self.change.reason = combo.get_model()[itr][0]

        self.view.connect(
            self.view.widgets.reason_combo, "changed", on_reason_changed
        )
        self.reasons = change_reasons
        # put initial model values in view and sets `initializing` to True
        self.refresh_view(initializing=True)
        # self.refresh_view()

        self.view.init_translatable_combo("reason_combo", self.reasons)

        utils.setup_date_button(
            self.view, "plant_date_entry", "plant_date_button"
        )
        date_str = utils.today_str()
        utils.set_widget_value(self.view.widgets.plant_date_entry, date_str)
        self.view.connect(
            "plant_date_entry",
            "changed",
            self.on_date_entry_changed,
            (self.change, "date"),
        )

        # assign signal handlers to monitor changes now that the view has
        # been filled in
        self.assign_completions_handler(
            "plant_acc_entry",
            self.acc_get_completions,
            on_select=self.on_select,
            comparer=lambda row, txt: acc_to_string_matcher(row[0], txt),
        )

        if self.model.accession:
            sp_str = self.model.accession.species_str(markup=True)
        else:
            sp_str = ""
        self.view.widgets.acc_species_label.set_markup(sp_str)

        self.view.connect(
            "plant_code_entry", "changed", self.on_plant_code_entry_changed
        )

        self.assign_simple_handler("plant_acc_type_combo", "acc_type")
        self.assign_simple_handler("plant_memorial_check", "memorial")
        self.view.connect(
            "plant_quantity_entry", "changed", self.on_quantity_changed
        )
        self.view.connect(
            "plant_loc_add_button",
            "clicked",
            self.on_loc_button_clicked,
            "add",
        )
        self.view.connect(
            "plant_loc_edit_button",
            "clicked",
            self.on_loc_button_clicked,
            "edit",
        )
        if self.model.quantity == 0:
            self.view.widgets.notebook.set_sensitive(False)
            msg = _(
                "This plant is marked with quantity zero. \n"
                "In practice, it is not any more part of the collection.\n"
                "Are you sure you want to edit it anyway?"
            )
            box = None

            def on_response(_button, response):
                self.view.remove_box(box)
                if response:
                    self.view.widgets.notebook.set_sensitive(True)

            box = self.view.add_message_box(utils.MESSAGE_BOX_YESNO)
            box.message = msg
            box.on_response = on_response
            box.show()
            self.view.add_box(box)
        # done initializing, reset it
        self.initializing = False
        self.history_expanded = False

        self.init_changes_history_view()
        self.kml_template = prefs.prefs.get(
            PLANT_KML_MAP_PREFS,
            str(Path(__file__).resolve().parent / "plant.kml"),
        )

    def acc_get_completions(self, text):
        """Get completions with any of the following combinations:
        'accession_code',
        'genus',
        'accession_code genus'
        'genus species',
        'genus cv',
        'genus trade_name',
        """
        text = text.lower()
        parts = text.split(" ", 1)
        from bauble.utils import ilike

        from ..plants.genus import Genus
        from ..plants.species_model import Species

        if len(parts) == 1:
            # try straight accession code search first
            query = (
                self.session.query(Accession)
                .join(Species)
                .join(Genus)
                .filter(
                    or_(
                        ilike(Genus.epithet, f"{text}%%"),
                        ilike(Accession.code, f"{text}%%"),
                    )
                )
                .order_by(Accession.code)
            )
        else:
            part0 = parts[0]
            part1 = parts[1].split(" ")[0]
            partc = part1.strip("'")
            query = (
                self.session.query(Accession)
                .join(Species)
                .join(Genus)
                .filter(
                    or_(
                        and_(
                            ilike(Accession.code, f"{part0}%%"),
                            ilike(Genus.epithet, f"{part1}%%"),
                        ),
                        and_(
                            ilike(Genus.epithet, f"{part0}%%"),
                            or_(
                                ilike(Species.epithet, f"{part1}%%"),
                                ilike(Species.cultivar_epithet, f"{partc}%%"),
                                ilike(Species.trade_name, f"{partc}%%"),
                            ),
                        ),
                    )
                )
                .order_by(Accession.code)
            )
        return query.limit(80)

    def on_select(self, value):
        # We need value to be an Accession object before we can do anything
        # with it. (Avoids the first 2 letters prior to the completions
        # handler kicking in - i.e. when called programatically.)
        if not isinstance(value, Accession):
            return
        self.set_model_attr("accession", value)
        # reset the plant code to check that this is a valid code for the
        # new accession, fixes bug #103946
        self.view.widgets.acc_species_label.set_markup("")
        if value is not None:
            sp_str = self.model.accession.species_str(markup=True)
            self.view.widgets.acc_species_label.set_markup(sp_str)
            # set the plant code to the next available
            code = get_next_code(self.model.accession)
            if code:
                # if get_next_code() returns None there was an error
                self.view.widgets.plant_code_entry.set_text(code)

    def init_changes_history_view(self):
        default_cell_data_func = utils.default_cell_data_func
        frmt = prefs.prefs[prefs.date_format_pref]

        self.view.widgets.changes_date_column.set_cell_data_func(
            self.view.widgets.changes_date_cell,
            default_cell_data_func,
            func_data=lambda obj: obj.date.strftime(frmt),
        )

        changes_treeview = self.view.widgets.plant_changes_treeview

        def on_date_cell_edited(_cell, path, new_text):
            treemodel = changes_treeview.get_model()
            obj = treemodel[path][0]
            if obj.date.strftime(frmt) == new_text:
                return
            from dateutil import parser

            val = parser.parse(
                new_text,
                dayfirst=prefs.prefs[prefs.parse_dayfirst_pref],
                yearfirst=prefs.prefs[prefs.parse_yearfirst_pref],
            )
            obj.date = val
            self._dirty = True
            self.refresh_sensitivity()

        def on_cell_edited(_cell, path, new_text, prop):
            treemodel = changes_treeview.get_model()
            obj = treemodel[path][0]
            if getattr(obj, prop) == new_text:
                return  # didn't change
            setattr(obj, prop, str(new_text))
            self._dirty = True
            self.refresh_sensitivity()

        self.view.connect(
            self.view.widgets.changes_date_cell, "edited", on_date_cell_edited
        )

        self.view.widgets.changes_quantity_column.set_cell_data_func(
            self.view.widgets.changes_quantity_cell,
            default_cell_data_func,
            func_data=lambda obj: str(obj.quantity or ""),
        )

        self.view.widgets.changes_from_column.set_cell_data_func(
            self.view.widgets.changes_from_cell,
            default_cell_data_func,
            func_data=(
                lambda obj: obj.from_location.code if obj.from_location else ""
            ),
        )

        self.view.widgets.changes_to_column.set_cell_data_func(
            self.view.widgets.changes_to_cell,
            default_cell_data_func,
            func_data=(
                lambda obj: obj.to_location.code if obj.to_location else ""
            ),
        )

        self.view.widgets.changes_parent_column.set_cell_data_func(
            self.view.widgets.changes_parent_cell,
            default_cell_data_func,
            func_data=lambda obj: str(obj.parent_plant or ""),
        )

        self.view.widgets.changes_child_column.set_cell_data_func(
            self.view.widgets.changes_child_cell,
            default_cell_data_func,
            func_data=lambda obj: str(obj.child_plant or ""),
        )

        # TODO can/should the options be limited to appropriate values only?
        reason_store = Gtk.ListStore(str, str)
        for key, val in change_reasons.items():
            reason_store.append([key, val])

        self.view.widgets.changes_reason_cell.props.model = reason_store

        self.view.widgets.changes_reason_column.set_cell_data_func(
            self.view.widgets.changes_reason_cell,
            default_cell_data_func,
            func_data=lambda obj: str(change_reasons.get(obj.reason) or ""),
        )

        def on_reason_cell_changed(widget, path, new_iter):
            treemodel = changes_treeview.get_model()
            obj = treemodel[path][0]
            obj.reason = widget.props.model[new_iter][0]
            self._dirty = True
            self.refresh_sensitivity()

        self.view.connect(
            self.view.widgets.changes_reason_cell,
            "changed",
            on_reason_cell_changed,
        )

        self.view.widgets.changes_user_column.set_cell_data_func(
            self.view.widgets.changes_user_cell,
            default_cell_data_func,
            func_data=lambda obj: str(obj.person or ""),
        )

        self.view.connect(
            self.view.widgets.changes_user_cell,
            "edited",
            on_cell_edited,
            "person",
        )

        utils.clear_model(changes_treeview)
        store = Gtk.ListStore(object)

        # all but the current/active change
        for change in sorted(
            self.model.changes[:-1], key=lambda row: (row.date, row.id)
        ):
            store.append([change])

        changes_treeview.set_model(store)

    def is_dirty(self):
        return (
            self.pictures_presenter.is_dirty()
            or self.notes_presenter.is_dirty()
            or self.prop_presenter.is_dirty()
            or self._dirty
        )

    def on_quantity_changed(self, entry):
        value = entry.props.text
        try:
            value = int(value)
        except ValueError as e:
            logger.debug("quantity change %s(%s)", type(e).__name__, e)
            value = None
        self.set_model_attr("quantity", value)
        # incase splitting into multiple
        codes = utils.range_builder(self.model.code)
        tru_value = value
        if len(codes) > 1:
            tru_value = value * len(codes)
        if (
            value is None
            or tru_value < self.lower_quantity_limit
            or tru_value >= self.upper_quantity_limit
        ):
            self.add_problem(self.PROBLEM_INVALID_QUANTITY, entry)
        else:
            self.remove_problem(self.PROBLEM_INVALID_QUANTITY, entry)
        self.refresh_sensitivity()
        if value is None:
            return
        if self._original_quantity:
            self.change.quantity = abs(
                self._original_quantity - self.model.quantity
            )
        else:
            self.change.quantity = self.model.quantity
        self.refresh_view()

    def on_plant_code_entry_changed(self, entry):
        """Validates the accession number and the plant code from the editors."""
        text = utils.nstr(entry.get_text())
        if text == "":
            self.set_model_attr("code", None)
        else:
            self.set_model_attr("code", utils.nstr(text))

        if not self.model.accession:
            self.remove_problem(self.PROBLEM_DUPLICATE_PLANT_CODE, entry)
            self.refresh_sensitivity()
            return

        # add a problem if the code is not unique but not if it's the
        # same accession and plant code that we started with when the
        # editor was opened
        if (
            self.model.code is not None
            and not is_code_unique(self.model, self.model.code)
            and not (
                self._original_accession_id == self.model.accession.id
                and self.model.code == self._original_code
            )
        ):
            self.add_problem(self.PROBLEM_DUPLICATE_PLANT_CODE, entry)
        else:
            # remove_problem() won't complain if problem doesn't exist
            self.remove_problem(self.PROBLEM_DUPLICATE_PLANT_CODE, entry)

        self.refresh_sensitivity()

    def refresh_sensitivity(self):
        logger.debug("refresh_sensitivity()")
        try:
            logger.debug(
                (
                    self.model.accession is not None,
                    self.model.code is not None,
                    self.model.location is not None,
                    self.model.quantity is not None,
                    self.is_dirty(),
                    len(self.problems) == 0,
                )
            )
        except OperationalError as e:
            logger.debug("(%s)%s", type(e).__name__, e)
            return
        logger.debug(self.problems)

        # TODO: because we don't call refresh_sensitivity() every time a
        # character is entered then the edit button doesn't sensitize
        # properly
        #
        # combo_entry = self.view.widgets.plant_loc_comboentry.get_child()
        # self.view.widgets.plant_loc_edit_button.\
        #     set_sensitive(self.model.location is not None \
        #                       and not self.has_problems(combo_entry))
        sensitive = (
            (
                self.model.accession is not None
                and self.model.code is not None
                and self.model.location is not None
                and self.model.quantity is not None
            )
            and self.is_dirty()
            and len(self.problems) == 0
        )
        self.view.widgets.pad_ok_button.set_sensitive(sensitive)
        self.view.widgets.pad_next_button.set_sensitive(sensitive)

    def set_model_attr(self, attr, value, validator=None):
        logger.debug("set_model_attr(%s, %s)", attr, value)
        super().set_model_attr(attr, value, validator)
        self._dirty = True
        self.refresh_sensitivity()

    def on_loc_button_clicked(self, _button, cmd=None):
        location = self.model.location
        combo = self.view.widgets.plant_loc_comboentry
        if cmd == "edit" and location:
            LocationEditor(location, parent=self.view.get_window()).start()
            self.session.refresh(location)
            self.view.widget_set_value(combo, location)
        else:
            editor = LocationEditor(parent=self.view.get_window())
            if editor.start():
                location = self.model.location = editor.presenter.model
                self.session.add(location)
                self.remove_problem(None, combo)
                self.view.widget_set_value(combo, location)
                self.set_model_attr("location", location)

    def refresh_view(self, initializing=False):
        self.initializing = initializing
        for widget, field in self.widget_to_field_map.items():
            value = getattr(self.model, field)
            self.view.widget_set_value(widget, value)
            logger.debug("%s: %s = %s", widget, field, value)

        self.view.widget_set_value(
            "plant_acc_type_combo",
            acc_type_values[self.model.acc_type],
            index=1,
        )
        self.view.widgets.plant_memorial_check.set_inconsistent(False)
        self.view.widgets.plant_memorial_check.set_active(
            self.model.memorial is True
        )

        self._init_reason_combo()

        self.refresh_sensitivity()

    def _init_reason_combo(self):
        reasons = {}
        default = None
        if self.branch_mode:
            reasons = split_reasons
        elif self.model in self.session.new:
            reasons = new_plt_reasons
            default = "PLTD"
        elif self.model.location != self._original_location:
            reasons = transfer_reasons
        elif self.model.quantity > self._original_quantity:
            reasons = added_reasons
        elif self.model.quantity < self._original_quantity:
            reasons = deleted_reasons
        else:
            reasons = change_reasons

        if self.change.reason in reasons:
            default = self.change.reason

        if self.reasons != reasons:
            self.reasons = reasons
            self.view.init_translatable_combo(
                "reason_combo", reasons, default=default
            )

    def cleanup(self):
        super().cleanup()
        msg_box_parent = self.view.widgets.message_box_parent
        for widget in msg_box_parent.get_children():
            msg_box_parent.remove(widget)
        # the entry is made not editable for branch mode
        self.view.widgets.plant_acc_entry.props.editable = True
        self.view.get_window().props.title = _("Plant Editor")
        self.remove_map_action_group()
        self.notes_presenter.cleanup()
        self.pictures_presenter.cleanup()

    def start(self):
        return self.view.start()


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


class PlantEditor(GenericModelViewPresenterEditor):
    # pylint: disable=protected-access

    # these have to correspond to the response values in the view
    RESPONSE_NEXT = 22
    ok_responses = (RESPONSE_NEXT,)

    def __init__(self, model=None, parent=None, branch_mode=False):
        """
        :param model: Plant instance or None
        :param parent: None
        :param branch_mode:
        """
        if branch_mode:
            if model is None:
                raise CheckConditionError("branch_mode requires a model")
            if object_session(model) and model in object_session(model).new:
                raise CheckConditionError("cannot split a new plant")

        if model is None:
            model = Plant()

        super().__init__(model, parent)

        self.branched_plant = None
        if branch_mode:
            # duplicate the model so we can branch from it without
            # destroying the first
            logger.debug("branching %s", model)
            self.branched_plant = self.model
            self.model = self.model.duplicate(code=None, session=self.session)
            self.model.quantity = 1

        if self.branched_plant and self.branched_plant not in self.session:
            # make a copy of the branched plant for this session
            self.branched_plant = self.session.merge(self.branched_plant)

        import bauble

        if not parent and bauble.gui:
            parent = bauble.gui.window
        self.parent = parent
        self._committed = []

        view = PlantEditorView(parent=self.parent)
        self.presenter = PlantEditorPresenter(
            self.model, view, branch_mode=branch_mode
        )
        if self.branched_plant:
            self.presenter.upper_quantity_limit = self.branched_plant.quantity

        # set default focus
        if self.model.accession is None:
            view.widgets.plant_acc_entry.grab_focus()
        else:
            view.widgets.plant_code_entry.grab_focus()

    def compute_plant_split_changes(self):
        move_quantity_between_plants(
            from_plant=self.branched_plant,
            to_plant=self.model,
            to_plant_change=self.presenter.change,
        )

    def commit_changes(self):
        codes = utils.range_builder(self.model.code)
        if (
            len(codes) <= 1
            or self.model not in self.session.new
            and not self.branched_plant
        ):
            change = self.presenter.change
            if self.branched_plant:
                self.compute_plant_split_changes()
            elif change.quantity is None or (
                change.quantity == self.model.quantity
                and change.from_location == self.model.location
                and change.quantity == self.presenter._original_quantity
            ):
                # if quantity and location haven't changed, nothing changed.
                if change in self.model.changes:
                    self.model.changes.remove(change)
                # is this needed?
                utils.delete_or_expunge(change)
            else:
                if self.model.location != change.from_location:
                    # transfer
                    change.to_location = self.model.location
                elif (
                    int(self.model.quantity or 0)
                    > int(self.presenter._original_quantity or 0)
                    and not change.to_location
                ):
                    # additions should use to_location
                    change.to_location = self.model.location
                    change.from_location = None
                else:
                    # removal
                    change.quantity = -change.quantity
            super().commit_changes()
            self._committed.append(self.model)
            return

        # TODO possibly offer a way to allow separate locations and quantities
        # this method will create new plants from self.model even if
        # the plant code is not a range....it's a small price to pay
        plants = []

        # TODO: precompute the _created and _last_updated attributes
        # in case we have to create lots of plants. it won't be too slow

        # we have to set the properties on the new objects
        # individually since session.merge won't create a new object
        # since the object is already in the session
        for code in codes:
            new_plant = self.model.duplicate(
                code=str(code), session=self.session
            )
            new_plant.id = None
            new_plant._created = None
            new_plant._last_updated = None
            # new_plant.location = self.model.location
            plants.append(new_plant)
            # copy over change (this gets reason, date etc.)
            change = self.presenter.change
            new_change = PlantChange()
            for prop in object_mapper(change).iterate_properties:
                setattr(new_change, prop.key, getattr(change, prop.key))
            # add the plant and location
            new_change.plant = new_plant
            new_change.to_location = new_plant.location
            # if we are branching need to transfer and record changes
            if self.branched_plant:
                move_quantity_between_plants(
                    from_plant=self.branched_plant,
                    to_plant=new_plant,
                    to_plant_change=new_change,
                )
            for note in self.model.notes:
                new_note = PlantNote()
                for prop in object_mapper(note).iterate_properties:
                    setattr(new_note, prop.key, getattr(note, prop.key))
                new_note.plant = new_plant
        try:
            for note in self.model.notes:
                self.session.expunge(note)

            self.session.expunge(self.model)
            super().commit_changes()
        except Exception:
            self.session.add(self.model)
            raise
        self._committed.extend(plants)

    def handle_response(self, response):
        not_ok_msg = _("Are you sure you want to lose your changes?")
        if response == Gtk.ResponseType.OK or response in self.ok_responses:
            try:
                if self.presenter.is_dirty():
                    # commit_changes() will append the commited plants
                    # to self._committed
                    self.commit_changes()
            except DBAPIError as e:
                exc = traceback.format_exc()
                logger.debug(exc)
                msg = _("Error committing changes.\n\n%s") % e.orig
                utils.message_details_dialog(
                    msg, str(e), Gtk.MessageType.ERROR
                )
                self.session.rollback()
                return False
            except Exception as e:
                msg = _(
                    "Unknown error when committing changes. See the "
                    "details for more information.\n\n%s"
                ) % utils.xml_safe(e)
                logger.debug(traceback.format_exc())
                utils.message_details_dialog(
                    msg, traceback.format_exc(), Gtk.MessageType.ERROR
                )
                self.session.rollback()
                return False
        elif (
            self.presenter.is_dirty() and utils.yes_no_dialog(not_ok_msg)
        ) or not self.presenter.is_dirty():
            self.session.rollback()
            return True
        else:
            return False

        # respond to responses
        more_committed = None
        if response == self.RESPONSE_NEXT:
            self.presenter.cleanup()
            e = PlantEditor(
                Plant(accession=self.model.accession), parent=self.parent
            )
            more_committed = e.start()

        if more_committed is not None:
            self._committed = [self._committed]
            if isinstance(more_committed, list):
                self._committed.extend(more_committed)
            else:
                self._committed.append(more_committed)

        return True

    def start(self):
        sub_editor = None
        if self.session.query(Accession).count() == 0:
            msg = (
                "You must first add or import at least one Accession into "
                "the database before you can add plants.\n\nWould you like "
                "to open the Accession editor?"
            )
            if utils.yes_no_dialog(msg):
                # cleanup in case we start a new PlantEditor
                self.presenter.cleanup()
                from bauble.plugins.garden.accession import AccessionEditor

                sub_editor = AccessionEditor()
                result = sub_editor.start()
                if result:
                    self._committed.extend(result)
        if self.session.query(Location).count() == 0:
            msg = (
                "You must first add or import at least one Location into "
                "the database before you can add plants.\n\nWould you "
                "like to open the Location editor?"
            )
            if utils.yes_no_dialog(msg):
                # cleanup in case we start a new PlantEditor
                self.presenter.cleanup()
                sub_editor = LocationEditor()
                result = sub_editor.start()
                if result:
                    self._committed.extend(result)

        if self.branched_plant:
            # set title if in branch mode
            window = self.presenter.view.get_window()
            window.props.title += " - " + _("Split Mode")
            message_box_parent = self.presenter.view.widgets.message_box_parent
            for child in message_box_parent.get_children():
                message_box_parent.remove(child)
            msg = _(
                "Splitting from %(plant_code)s.  The quantity will "
                "be subtracted from %(plant_code)s"
            ) % {"plant_code": str(self.branched_plant)}
            box = self.presenter.view.add_message_box(utils.MESSAGE_BOX_INFO)
            box.message = msg
            box.show_all()

            # don't allow editing the accession code in a branched plant
            self.presenter.view.widgets.plant_acc_entry.props.editable = False

        if not sub_editor:
            while True:
                response = self.presenter.start()
                self.presenter.view.save_state()
                if self.handle_response(response):
                    break

        self.session.close()  # cleanup session
        self.presenter.cleanup()
        return self._committed


class GeneralPlantExpander(InfoExpander):
    """general expander for the PlantInfoBox"""

    def __init__(self, widgets):
        super().__init__(_("General"), widgets)
        general_box = self.widgets.general_box
        self.widgets.remove_parent(general_box)
        self.vbox.pack_start(general_box, True, True, 0)

    def update(self, row):
        acc_code = str(row.accession)
        plant_code = str(row)
        head, tail = plant_code[: len(acc_code)], plant_code[len(acc_code) :]

        self.widget_set_value(
            "acc_code_data", f"<big>{utils.xml_safe(head)}</big>", markup=True
        )
        self.widget_set_value(
            "plant_code_data",
            f"<big>{utils.xml_safe(tail)}</big>",
            markup=True,
        )
        self.widget_set_value(
            "name_data", row.accession.species_str(markup=True), markup=True
        )
        self.widget_set_value("location_data", str(row.location))
        self.widget_set_value("quantity_data", row.quantity)
        # NOTE don't load geojson from the row or history will always record
        # an unpdate and _last_updated will always chenge when a relationship
        # (note, propagation, etc.) is edited. (e.g. `shape = row.geojson...`
        # instead use a temp session)
        temp = db.Session()
        geojson = temp.query(Plant.geojson).filter_by(id=row.id).scalar()
        shape = geojson.get("type", "") if geojson else ""
        temp.close()
        self.widget_set_value("geojson_type", shape)

        status_str = _("Alive")
        if row.quantity <= 0:
            status_str = _("Dead")
        self.widget_set_value("status_data", status_str, False)

        self.widget_set_value(
            "type_data", acc_type_values[row.acc_type], False
        )

        image_size = Gtk.IconSize.MENU
        icon = None
        if row.memorial:
            icon = "emblem-ok-symbolic"
        self.widgets.memorial_image.set_from_icon_name(icon, image_size)

        on_clicked = utils.generate_on_clicked(select_in_search_results)
        utils.make_label_clickable(
            self.widgets.acc_code_data, on_clicked, row.accession
        )

        from ..plants.species import on_taxa_clicked

        utils.make_label_clickable(
            self.widgets.name_data, on_taxa_clicked, row.accession.species
        )
        utils.make_label_clickable(
            self.widgets.location_data, on_clicked, row.location
        )


class ChangesExpander(InfoExpander):
    """ChangesExpander"""

    EXPANDED_PREF = "infobox.plant_changes_expanded"

    def __init__(self, widgets):
        super().__init__(_("Changes"), widgets)
        self.add_change_grid()

    def add_change_grid(self):
        self.change_grid = Gtk.Grid()
        self.change_grid.set_column_spacing(3)
        self.change_grid.set_row_spacing(3)
        self.vbox.pack_start(self.change_grid, False, False, 0)

    def update(self, row):
        self.reset()
        self.vbox.remove(self.change_grid)
        self.add_change_grid()
        if not row.changes:
            return
        self.set_sensitive(True)

        on_clicked = utils.generate_on_clicked(select_in_search_results)

        frmt = prefs.prefs[prefs.date_format_pref]
        count = 0
        for change in sorted(
            row.changes, key=lambda x: (x.date, x.id), reverse=True
        ):
            date = change.date.strftime(frmt)
            date_lbl = Gtk.Label()
            if change.reason == "PLTD":
                date_lbl.set_markup(f"<b>{date}</b> (Planted)")
            else:
                date_lbl.set_markup(f"<b>{date}</b>")
            date_lbl.set_xalign(0.0)
            date_lbl.set_yalign(0.0)
            self.change_grid.attach(date_lbl, 0, count, 1, 1)
            count += 1

            if change.to_location and change.from_location:
                summary = (
                    f"{change.quantity} Transferred from "
                    f"{change.from_location} to {change.to_location}"
                )
            elif change.quantity < 0:
                summary = (
                    f"{-change.quantity} Removed from "
                    f"{change.from_location}"
                )
            elif change.quantity > 0:
                txt = "Added to"
                if change.reason == "PLTD":
                    txt = "Planted in"
                if change.reason == "ESTM":
                    txt = "Planted (estm.) in"
                if change.reason in ["NTRL", "PRIR"]:
                    txt = "Captured in"
                summary = f"{change.quantity} {txt} {change.to_location}"
            else:
                summary = (
                    f"{change.quantity}: {change.from_location} -> "
                    f"{change.to_location}"
                )
            summary_lbl = Gtk.Label()
            summary_lbl.set_text(summary)
            summary_lbl.set_xalign(0.0)
            summary_lbl.set_yalign(0.0)
            summary_lbl.set_line_wrap(True)
            self.change_grid.attach(summary_lbl, 0, count, 1, 1)
            count += 1

            if change.reason and not change.reason == "PLTD":
                reason_lbl = Gtk.Label()
                reason_lbl.set_text(change_reasons.get(change.reason))
                reason_lbl.set_xalign(0.0)
                reason_lbl.set_yalign(0.0)
                self.change_grid.attach(reason_lbl, 0, count, 1, 1)
                count += 1

            if change.parent_plant:
                parent_lbl = Gtk.Label()
                parent_lbl.set_markup(
                    f"<i>Split from {utils.xml_safe(change.parent_plant)}</i>"
                )
                eventbox = Gtk.EventBox()
                eventbox.add(parent_lbl)
                self.change_grid.attach(eventbox, 0, count, 1, 1)
                count += 1

                utils.make_label_clickable(
                    parent_lbl, on_clicked, change.parent_plant
                )

            if change.child_plant:
                div_lbl = Gtk.Label()
                div_lbl.set_markup(
                    f"<i>Split as {utils.xml_safe(change.child_plant)}</i>"
                )
                eventbox = Gtk.EventBox()
                eventbox.add(div_lbl)
                self.change_grid.attach(eventbox, 0, count, 1, 1)
                count += 1

                utils.make_label_clickable(
                    div_lbl, on_clicked, change.child_plant
                )

        # trigger resize
        self.get_preferred_size()


class PropagationExpander(InfoExpander):
    """Propagation Expander"""

    EXPANDED_PREF = "infobox.plant_proagations_expanded"

    def __init__(self, widgets):
        super().__init__(_("Propagations"), widgets)
        self.add_prop_grid()

    def add_prop_grid(self):
        self.prop_grid = Gtk.Grid()
        self.prop_grid.set_column_spacing(3)
        self.prop_grid.set_row_spacing(3)
        self.vbox.pack_start(self.prop_grid, False, False, 0)

    def update(self, row):
        self.reset()
        self.vbox.remove(self.prop_grid)
        self.add_prop_grid()
        if not row.propagations:
            return
        self.set_sensitive(True)
        frmt = prefs.prefs[prefs.date_format_pref]
        count = 0

        on_clicked = utils.generate_on_clicked(select_in_search_results)

        for prop in row.propagations:
            date_lbl = Gtk.Label()
            date = prop.date.strftime(frmt)
            date_lbl.set_markup(f"<b>{date}</b>")
            date_lbl.set_xalign(0.0)
            date_lbl.set_yalign(0.0)
            self.prop_grid.attach(date_lbl, 0, count, 2, 1)
            count += 1

            if prop.accessions:
                used_lbl = Gtk.Label()
                used_lbl.set_text("Parent of: ")
                used_lbl.set_xalign(1.0)
                used_lbl.set_yalign(0.0)
                self.prop_grid.attach(used_lbl, 0, count, 1, 1)
                for acc in prop.accessions:
                    accession_lbl = Gtk.Label()
                    eventbox = Gtk.EventBox()
                    eventbox.add(accession_lbl)
                    accession_lbl.set_xalign(0.0)
                    accession_lbl.set_yalign(0.0)
                    accession_lbl.set_text(acc.code)

                    utils.make_label_clickable(accession_lbl, on_clicked, acc)
                    self.prop_grid.attach(eventbox, 1, count, 2, 1)
                    count += 1

            summary_label = Gtk.Label()
            self.prop_grid.attach(summary_label, 0, count, 2, 1)

            summary_label.set_text(prop.get_summary(partial=2))
            summary_label.set_line_wrap(True)
            summary_label.set_xalign(0.0)
            summary_label.set_yalign(0.0)
            summary_label.set_size_request(-1, -1)
            count += 1
        # trigger resize
        self.get_preferred_size()


class PlantInfoBox(InfoBox):
    """an InfoBox for a Plants table row"""

    def __init__(self):
        super().__init__()
        filename = os.path.join(
            paths.lib_dir(), "plugins", "garden", "plant_infobox.glade"
        )
        self.widgets = utils.load_widgets(filename)
        self.general = GeneralPlantExpander(self.widgets)
        self.add_expander(self.general)

        self.changes = ChangesExpander(self.widgets)
        self.add_expander(self.changes)

        self.propagations = PropagationExpander(self.widgets)
        self.add_expander(self.propagations)

        self.links = LinksExpander("notes")
        self.add_expander(self.links)

        self.props = PropertiesExpander()
        self.add_expander(self.props)

    def update(self, row):
        self.general.update(row)
        self.changes.update(row)

        if row.propagations:
            self.propagations.set_sensitive(True)
        else:
            self.propagations.set_sensitive(False)

        self.propagations.update(row)

        self.links.update(row)

        self.props.update(row)


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
    from ..plants.species_editor import species_to_string_matcher

    if plt_match:
        sp_match = species_to_string_matcher(species, sp_str)
    elif species_to_string_matcher(species, text):
        sp_match = True
        _accept_one = True

    if _accept_one:
        return any((plt_match, sp_match))
    return all((plt_match, sp_match))


def plant_match_func(
    completion: Gtk.EntryCompletion, key: str, treeiter: int
) -> bool:
    """match_func that allows partial matches on both plant code, Genus and
    species.

    :param completion: the completion to match
    :param key: lowercase string of the entry text
    :param treeiter: the row number for the item to match

    :return: bool, True if the item at the treeiter matches the key
    """
    plant = completion.get_model()[treeiter][0]
    return plant_to_string_matcher(plant, key)
