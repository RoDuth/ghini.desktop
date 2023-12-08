# Copyright 2008, 2009, 2010 Brett Adams
# Copyright 2014-2015 Mario Frasca <mario@anche.no>.
# Copyright 2021-2023 Ross Demuth <rossdemuth123@gmail.com>
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
Search expressions

Search expression are pyparsing parse actions that refers to a database query
expression. i.e. some logic between a value(s) and an identifier(s) or between
queries/subqueries.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

import typing
from abc import ABC
from abc import abstractmethod
from dataclasses import dataclass
from datetime import datetime
from datetime import timedelta
from datetime import timezone

from dateutil import parser
from pyparsing import ParseResults
from sqlalchemy import and_
from sqlalchemy import select
from sqlalchemy.orm import Query
from sqlalchemy.orm import Session
from sqlalchemy.sql import Select
from sqlalchemy.sql import func
from sqlalchemy.sql.elements import ColumnElement

from bauble import prefs
from bauble.btypes import DateTime
from bauble.btypes import get_date
from bauble.db import Base

from .operations import OPERATIONS


@dataclass
class QueryHandler:
    session: Session
    domain: Base
    query: Query | Select


class ExpressionAction(ABC):
    """A pyparsing parse action class that refers to a database expression as
    used in a SQLA ORM query.  i.e. the criterion to apply.
    """

    @abstractmethod
    def __init__(self, tokens: ParseResults) -> None:
        """Set tokens"""

    @abstractmethod
    def __repr__(self) -> str:
        """For logging etc."""

    @abstractmethod
    def evaluate(self, handler: QueryHandler) -> Query | Select:
        """Adjusts the query."""


class IdentExpression(ExpressionAction):
    """Impliments a basic `ident operator value` query."""

    def __init__(self, tokens: ParseResults) -> None:
        logger.debug("%s::init(%s)", self.__class__.__name__, tokens)
        self.oper: str = tokens[0][1]

        # cfr: SearchParser.binop
        # = == != <> < <= > >= not like contains has ilike icontains ihas is
        self.operation: typing.Callable | None = OPERATIONS.get(
            self.oper.lower()
        )
        # every second object is an operand (i.e. an IdentAction)
        self.operands: ParseResults = tokens[0][0::2]

    def __repr__(self) -> str:
        return f"({self.operands[0]} {self.oper} {self.operands[1]})"

    def evaluate(self, handler: QueryHandler) -> Query | Select:
        logger.debug("%s::evaluate %s", self.__class__.__name__, self)
        handler.query, attr = self.operands[0].evaluate(handler)

        if self.operands[1].express() == set():
            # check against the empty set
            if self.oper in ("is", "=", "=="):
                handler.query = handler.query.filter(~attr.any())
                return handler.query
            if self.oper in ("not", "<>", "!="):
                handler.query = handler.query.filter(attr.any())
                return handler.query

        def clause(val) -> ColumnElement:
            assert self.operation is not None
            return self.operation(attr, val)

        logger.debug("filtering on %s(%s)", type(attr), attr)
        handler.query = handler.query.filter(
            clause(self.operands[1].express())
        )
        return handler.query


# why is pylint complaining here?
# pylint: disable=too-few-public-methods
class ElementSetExpression(IdentExpression):
    """implements `in` in a `ident in value_list` query."""

    def evaluate(self, handler: QueryHandler) -> Query | Select:
        logger.debug("%s::evaluate %s", self.__class__.__name__, self)
        handler.query, attr = self.operands[0].evaluate(handler)
        handler.query = handler.query.filter(
            attr.in_(self.operands[1].express())
        )
        return handler.query


def get_datetime(value: str | float) -> datetime:
    result = get_date(value)
    if not result:
        try:
            # try parsing as iso8601 first
            result = parser.isoparse(str(value))
        except ValueError:
            try:
                result = parser.parse(
                    str(value),
                    dayfirst=prefs.prefs[prefs.parse_dayfirst_pref],
                    yearfirst=prefs.prefs[prefs.parse_yearfirst_pref],
                )
            except ValueError:
                result = parser.parse(str(value), fuzzy=True)
    return result.replace(hour=0, minute=0, second=0, microsecond=0)


class DateOnExpression(IdentExpression):
    """Implements `on` in a `ident on date_str` query."""

    def evaluate(self, handler: QueryHandler) -> Query | Select:
        logger.debug("%s::evaluate %s", self.__class__.__name__, self)
        handler.query, attr = self.operands[0].evaluate(handler)
        date_val = self.operands[1].express()
        if isinstance(date_val, (str, float)):
            date_val = get_datetime(date_val)
        if isinstance(attr.type, DateTime):
            logger.debug("is DateTime")
            today = date_val.astimezone(tz=timezone.utc)
            tomorrow = today + timedelta(1)
            logger.debug("today: %s", today)
            logger.debug("tomorrow: %s", tomorrow)
            handler.query = handler.query.filter(
                and_(attr >= today, attr < tomorrow)
            )
        else:
            # btype.Date - only need the date
            handler.query = handler.query.filter(attr == date_val.date())
        return handler.query


class AggregatedExpression(IdentExpression):
    """Impliments `func` in a `func(ident) operator value` query.

    This looks like `ident operation value`, but the ident is an aggregating
    function, so that the query has to be altered differently: filter on a
    subquery that uses group_by and having.
    """

    def evaluate(self, handler: QueryHandler) -> Query | Select:
        logger.debug("%s::evaluate %s", self.__class__.__name__, self)
        # operands[0] is the function/identifier pair
        # operands[1] is the value against which to test
        # operation implements the clause

        function = getattr(func, self.operands[0].function)

        id_ = getattr(handler.domain, "id")

        sub_query: Select = select(id_)
        subq_handler = QueryHandler(handler.session, handler.domain, sub_query)
        sub_query, attr = self.operands[0].evaluate(subq_handler)

        def clause(val) -> ColumnElement:
            assert self.operation is not None
            return self.operation(function(attr), val)

        having = clause(self.operands[1].express())
        sub_query = sub_query.having(having)
        sub_query = sub_query.group_by(id_)
        handler.query = handler.query.filter(id_.in_(sub_query))

        return handler.query


class BetweenExpression(IdentExpression):
    """Implements a `ident BETWEEN value AND value2` query."""

    def __repr__(self) -> str:
        return f"(BETWEEN {' '.join(str(i) for i in self.operands)})"

    def evaluate(self, handler: QueryHandler) -> Query | Select:
        logger.debug("%s::evaluate %s", self.__class__.__name__, self)
        handler.query, attr = self.operands[0].evaluate(handler)

        handler.query = handler.query.filter(
            and_(
                self.operands[1].express() <= attr,
                attr <= self.operands[2].express(),
            )
        )
        return handler.query


class BinaryLogicalExpression(IdentExpression):
    """Parent class for binary search actions."""

    name = ""

    def __repr__(self) -> str:
        name = f" {self.name} "
        string = name.join(str(operand) for operand in self.operands)
        return f"({string})"

    @abstractmethod
    def evaluate(self, handler: QueryHandler) -> Query | Select:
        """Must be implimented in subclasses"""


class SearchAndExpression(BinaryLogicalExpression):
    """Implements a `expression AND expression` query."""

    name = "AND"

    def evaluate(self, handler: QueryHandler) -> Query | Select:
        logger.debug("%s::evaluate %s", self.__class__.__name__, self)
        for operand in self.operands:
            logger.debug("SearchAndExpression::operand %s", operand)

            handler.query = operand.evaluate(handler)

        return handler.query


class SearchOrExpression(BinaryLogicalExpression):
    """Implements a `expression OR expression` query."""

    name = "OR"

    def evaluate(self, handler: QueryHandler) -> Query | Select:
        logger.debug("%s::evaluate %s", self.__class__.__name__, self)
        handler.query = self.operands[0].evaluate(handler)
        for operand in self.operands[1:]:
            # start a new query
            if isinstance(handler.query, Query):
                query = handler.session.query(handler.domain)
                or_handler = QueryHandler(
                    handler.session, handler.domain, query
                )
            else:
                select_ = select(handler.domain.id)  # type: ignore[attr-defined]  # noqa
                or_handler = QueryHandler(
                    handler.session, handler.domain, select_
                )
            handler.query = typing.cast(
                Query, handler.query.union(operand.evaluate(or_handler))
            )
        return handler.query


# pylint: enable=too-few-public-methods
class SearchNotExpression(ExpressionAction):
    """Implements a `NOT expression` query."""

    name = "NOT"

    def __init__(self, tokens: ParseResults) -> None:
        logger.debug("%s::__init__(%s)", self.__class__.__name__, tokens)
        self.oper, self.operand = tokens[0]

    def __repr__(self) -> str:
        return f"{self.name} {str(self.operand)}"

    def evaluate(self, handler: QueryHandler) -> Query | Select:
        logger.debug("%s::evaluate %s", self.__class__.__name__, self)
        query = handler.session.query(handler.domain)
        not_handler = QueryHandler(handler.session, handler.domain, query)
        handler.query = typing.cast(
            Query, handler.query.except_(self.operand.evaluate(not_handler))
        )
        return handler.query


class ParenthesisedExpression(ExpressionAction):
    """Implements a `(expression)` query as a subquery."""

    def __init__(self, tokens: ParseResults) -> None:
        logger.debug("%s::__init__(%s)", self.__class__.__name__, tokens)
        self.content = tokens[1]

    def __repr__(self) -> str:
        return f"({self.content})"

    def evaluate(self, handler: QueryHandler) -> Query | Select:
        logger.debug("%s::evaluate %s", self.__class__.__name__, self)
        select_ = select(handler.domain.id)  # type: ignore[attr-defined]
        paren_handler = QueryHandler(handler.session, handler.domain, select_)
        sub_query = self.content.evaluate(paren_handler)
        filter_ = handler.domain.id.in_(sub_query)  # type: ignore[attr-defined]  # noqa
        handler.query = handler.query.filter(filter_)
        return handler.query
