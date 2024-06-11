# Copyright (c) 2005,2006,2007,2008,2009 Brett Adams <brett@belizebotanic.org>
# Copyright (c) 2012-2017 Mario Frasca <mario@anche.no>
# Copyright (c) 2021-2024 Ross Demuth <rossdemuth123@gmail.com>
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
Custom database types.
"""
# pylint: disable=abstract-method # re TypeDecorator
import logging

logger = logging.getLogger(__name__)

from collections.abc import Callable
from collections.abc import Sequence
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from operator import ge
from operator import gt
from operator import le
from operator import lt
from typing import Any

import dateutil.parser as date_parser
from sqlalchemy import types
from sqlalchemy.engine import Dialect
from sqlalchemy.sql.elements import ClauseElement
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.sql.expression import case

from bauble import error
from bauble.i18n import _


class EnumError(error.BaubleError):
    """Raised when a bad value is inserted or returned from the Enum type"""


class Enum(types.TypeDecorator):
    """A database independent Enum type. The value is stored in the database as
    a Unicode string.

    < > <= >= are supported with reference to the order values are provided.
    """

    impl = types.Unicode

    cache_ok = False

    def __init__(
        self,
        values: Sequence,
        empty_to_none: bool = False,
        translations: dict | None = None,
        **kwargs: Any,
    ):
        self.init(
            values,
            empty_to_none=empty_to_none,
            translations=translations,
            **kwargs,
        )
        # the length of the string/unicode column should be the
        # longest string in values
        size = max(len(v) for v in self.values if v is not None)
        super().__init__(size, **kwargs)

    def init(
        self,
        values: Sequence,
        empty_to_none: bool = False,
        translations: dict | None = None,
    ):
        """Initilise the column.

        :param values: A list of valid values for column.
        :param empty_to_none: Treat the empty string '' as None.  None
            must be in the values list in order to set empty_to_none=True.
        :param translations: A dictionary of values->translation
        """
        logger.debug("init enum with values: %s", values)
        if values is None or len(values) == 0:
            raise EnumError(_("Enum requires a list of values"))

        for val in values:
            if val is not None and not isinstance(val, str):
                raise EnumError(_("Enum requires string values (or None)"))

        if len(values) != len(set(values)):
            raise EnumError(_("Enum requires the values to be different"))

        self.translations = translations or dict((v, v) for v in values)

        if empty_to_none and None not in values:
            raise EnumError(
                _(
                    "You have configured empty_to_none=True but "
                    "None is not in the values lists"
                )
            )

        self.values = values[:]
        self.reverse_values = values[::-1]
        self.empty_to_none = empty_to_none
        logger.debug("values = %s", self.values)

    def to_int(self, obj: Any) -> ColumnElement:
        """Returns a case clause that converts to an int based of the index in
        values reversed.
        """
        return case(
            [
                (
                    obj == val,
                    self.reverse_values.index(val),
                )
                for val in self.values
            ]
        )

    def process_bind_param(self, value: str | None, dialect: Dialect) -> Any:
        """Process the value going into the database."""
        if hasattr(self, "values"):
            if self.empty_to_none and value == "":
                value = None
            if value is None and None not in self.values and "" in self.values:
                value = ""
            if value not in self.values:
                raise EnumError(
                    _('"%(value)s" not in Enum.values: %(all_values)s')
                    % {"value": value, "all_values": self.values}
                )
        return value

    class Comparator(types.TypeDecorator.Comparator):
        parent: "Enum"

        def operate(
            self,
            op: Callable[[Any, Any], ClauseElement],
            *other: Any,
            **kwargs: Any,
        ):
            if hasattr(self.parent, "values") and op in (lt, le, gt, ge):
                this = self.parent.to_int(self)
                # other is a string
                if len(other) == 1 and isinstance(other[0], str):
                    return op(
                        this,
                        self.parent.reverse_values.index(*other),
                        **kwargs,
                    )
                # other is a subquery etc.
                return op(
                    this,
                    self.parent.to_int(*other),
                    **kwargs,
                )

            return super().operate(op, *other, **kwargs)

    @property
    def comparator_factory(self):
        """Supply a comparator class with access to self."""
        return type(
            "EnumComparator",
            (self.Comparator,),
            {"parent": self},
        )


class CustomEnum(Enum):
    """An Enum appropriate for custom columns that require initialisation to be
    delayed until values are known.

    When instantiating provide :param size:. Choose a size reasonable enough to
    accommodate expected uses.

    Call `self.init(values, empty_to_none, translations)` when ready to
    initialise, may also need to reopen connection if the connection has been
    in use, due to SQLA caching of Columns.
    e.g.: `db.conn(str(db.engine.url))`
    """

    cache_ok = False

    def __init__(self, size: str, **kwargs: Any) -> None:
        """Pass the size parameter to impl column (Unicode).

        To complete initialisation call `self.init` when values become
        available.
        """
        super(Enum, self).__init__(size, **kwargs)

    def unset_values(self) -> None:
        """Return state to pre init state."""
        logger.debug("unsetting custom column")
        if hasattr(self, "values"):
            del self.values
        if hasattr(self, "empty_to_none"):
            del self.empty_to_none
        if hasattr(self, "translations"):
            del self.translations


def get_date(val: str | float) -> datetime | None:
    offset = None
    if isinstance(val, float):
        offset = val
    elif val.strip().lower() == _("today"):
        offset = 0
    elif val.strip().lower() == _("yesterday"):
        offset = -1
    if offset is not None:
        return datetime.now().replace(
            hour=0, minute=0, second=0, microsecond=0
        ) + timedelta(offset)
    return None


class DateTime(types.TypeDecorator):
    """A DateTime type that allows strings and tries to always return local
    time.
    """

    impl = types.DateTime
    _dayfirst = None
    _yearfirst = None

    cache_ok = True

    class comparator_factory(types.DateTime.Comparator):
        # pylint: disable=invalid-name
        def operate(self, op, *other, **kwargs):
            vals = []
            for val in other:
                if isinstance(val, (str, float)):
                    date = get_date(val)
                    if date:
                        val = date.astimezone(tz=timezone.utc)
                vals.append(val)
            other = tuple(vals)
            return super().operate(op, *other, **kwargs)

    def process_bind_param(self, value, dialect):
        if not isinstance(value, str):
            if value.tzinfo:
                # incoming datetime values with a timezone set, convert to utc
                return value.astimezone(tz=timezone.utc)
            return value

        if not self._dayfirst or not self._yearfirst:
            from bauble import prefs  # avoid circular imports

            # pylint: disable=protected-access
            self.__class__._dayfirst = prefs.prefs[prefs.parse_dayfirst_pref]
            self.__class__._yearfirst = prefs.prefs[prefs.parse_yearfirst_pref]

        try:
            # try parsing as iso8601 first
            result = date_parser.isoparse(value)
        except ValueError:
            try:
                result = date_parser.parse(
                    value,
                    dayfirst=DateTime._dayfirst,
                    yearfirst=DateTime._yearfirst,
                )
            except ValueError:
                return None
        return result.astimezone(tz=timezone.utc)

    def process_result_value(self, value, dialect):
        # no tz (utc naive tz) sqlite func.now(), datetime.utcnow(), string
        # dates are all stored in utc but have no tz
        if not value.tzinfo:
            return value.replace(tzinfo=timezone.utc).astimezone(tz=None)
        # with a tz - Postgres func.now(), string dates, datetime.utcnow() are
        # all stored utc
        return value.astimezone(tz=None)


class Date(types.TypeDecorator):
    """A Date type that allows Date strings.

    NOTE: timezone agnostic."""

    impl = types.Date
    _dayfirst = None
    _yearfirst = None

    cache_ok = True

    class comparator_factory(types.Date.Comparator):
        # pylint: disable=invalid-name
        def operate(self, op, *other, **kwargs):
            vals = []
            for val in other:
                if isinstance(val, (str, float)):
                    date = get_date(val)
                    if date:
                        val = date
                vals.append(val)
            other = tuple(vals)
            return super().operate(op, *other, **kwargs)

    def process_bind_param(self, value, dialect):
        if not isinstance(value, str):
            return value

        if not self._dayfirst or not self._yearfirst:
            from bauble import prefs

            # pylint: disable=protected-access
            self.__class__._dayfirst = prefs.prefs[prefs.parse_dayfirst_pref]
            self.__class__._yearfirst = prefs.prefs[prefs.parse_yearfirst_pref]

        try:
            # try parsing as iso8601 first
            result = date_parser.isoparse(value)
        except ValueError:
            try:
                result = date_parser.parse(
                    value, dayfirst=Date._dayfirst, yearfirst=Date._yearfirst
                )
            except ValueError:
                return None
        return result.date()


class JSON(types.TypeDecorator):
    """Platform-independent JSON type

    Use JSONB for postgresql JSON for all others
    """

    impl = types.JSON()

    cache_ok = True

    def load_dialect_impl(self, dialect):
        # NOTE does not provide access to the JSONB specific comparators
        # has_any, has_key, etc.. For consistent use the value of impl above
        # sets the available SQL operations regardless of the type used to
        # store the data.
        if dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import JSONB

            return dialect.type_descriptor(JSONB(none_as_null=True))
        return dialect.type_descriptor(types.JSON(none_as_null=True))

    def coerce_compared_value(self, op, value):
        return self.impl.coerce_compared_value(op, value)


class Boolean(types.TypeDecorator):
    """A Boolean type that allows True/False as strings.

    For compatibility with MSSQL converts is_() to = and is_not() to !="""

    impl = types.Boolean

    cache_ok = True

    class comparator_factory(types.Boolean.Comparator):
        # pylint: disable=invalid-name

        def is_(self, other):
            """override is_"""
            return self.op("=")(other)

        def is_not(self, other):
            """override is_not"""
            return self.op("!=")(other)

    def process_bind_param(self, value, dialect):
        if not isinstance(value, str):
            return value
        if value == "True":
            return True
        if value == "False":
            return False
        return None


class TruncatedString(types.TypeDecorator):
    """A String type that truncates anything past its designated length"""

    impl = types.String

    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value:
            return value[: self.impl.length]
        return None
