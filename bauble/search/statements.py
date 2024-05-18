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
Search statement parse actions

Statement actions are the final parse action called when parsing a full
statement.  They are used by a search strategy and return a list of SQLA
queries when invoked.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

import typing
from abc import ABC
from abc import abstractmethod
from collections.abc import Callable

from pyparsing import ParseResults
from sqlalchemy import or_
from sqlalchemy.orm import Query
from sqlalchemy.orm import class_mapper
from sqlalchemy.sql.elements import BinaryExpression

from bauble import utils
from bauble.error import check
from bauble.i18n import _

from .clauses import QueryHandler
from .operations import OPERATIONS
from .tokens import ValueListToken

if typing.TYPE_CHECKING:
    from .strategies import DomainSearch
    from .strategies import MapperSearch
    from .strategies import SearchStrategy
    from .strategies import ValueListSearch

StrategyT = typing.TypeVar("StrategyT", bound="SearchStrategy")


class StatementAction(ABC, typing.Generic[StrategyT]):
    """A pyparsing parse action class that when `invoke`d produces the final
    SQLA ORM query.

    Returned within the ParseResults from `parse_string`.
    """

    @abstractmethod
    def __init__(self, tokens: ParseResults) -> None:
        """Set tokens"""

    @abstractmethod
    def __repr__(self) -> str:
        """Repr for logging etc."""

    @abstractmethod
    def invoke(self, search_strategy: StrategyT) -> list[Query]:
        """Produce a query"""


class MapperStatement(StatementAction["MapperSearch"]):
    """Generates `domain where clause` queries.

    The most complex query type.
    """

    def __init__(self, tokens: ParseResults) -> None:
        logger.debug("%s::__init__(%s)", self.__class__.__name__, tokens)
        self.domain = tokens[0]
        self.filter = tokens[1]

    def __repr__(self) -> str:
        return f"SELECT * FROM {self.domain} WHERE {self.filter}"

    def invoke(self, search_strategy: MapperSearch) -> list[Query]:
        logger.debug(
            "ExpressionQueryAction:invoke - domain: %s(%s) filter: %s(%s)",
            type(self.domain).__name__,
            self.domain,
            type(self.filter).__name__,
            self.filter,
        )
        check(
            self.domain in search_strategy.domains,
            f"Unknown search domain: {self.domain}",
        )
        check(
            search_strategy.session is not None,
            f"No session provided by: {search_strategy}",
        )

        session = search_strategy.session
        domain = search_strategy.domains[self.domain][0]
        query = search_strategy.session.query(domain)
        query_handler = QueryHandler(
            session=session, domain=domain, query=query
        )
        self.filter.evaluate(query_handler)

        return [typing.cast(Query, query_handler.query)]


BinCallable: typing.TypeAlias = Callable[[list | str], BinaryExpression]


class DomainStatement(StatementAction["DomainSearch"]):
    """Generates `domain operator value` queries

    Searching using domain expressions is a little more magical than an
    explicit query. you give a domain, a binary_operator and a value,
    the domain expression will return all object with at least one
    property (as passed to add_meta) matching (according to the binop)
    the value.
    """

    def __init__(self, tokens: ParseResults) -> None:
        logger.debug("%s::__init__(%s)", self.__class__.__name__, tokens)
        self.domain = tokens[0]
        self.cond = tokens[1]
        self.values = tokens[2]

    def __repr__(self) -> str:
        return f"{self.domain} {self.cond} {self.values}"

    def invoke(self, search_strategy: DomainSearch) -> list[Query]:
        logger.debug("DomainQueryAction:invoke")
        self.domain = search_strategy.shorthand.get(self.domain, self.domain)
        cls, properties = search_strategy.domains[self.domain]

        query = search_strategy.session.query(cls)

        # select all objects from the domain or None
        if self.values == "*":
            if self.cond in ("!=", "<>"):
                return [query.filter(False)]
            return [query]

        operation = OPERATIONS[self.cond.lower()]

        mapper = class_mapper(cls)

        ors = []
        for column in properties:
            attr = mapper.c[column]
            if isinstance(self.values, ValueListToken):
                value = []
                for val in self.values.values:
                    if hasattr(val.value, "raw_value"):
                        value.append(val.value.raw_value)
                    else:
                        value.append(val.express())
            elif hasattr(self.values.value, "raw_value"):
                value = self.values.value.raw_value
            else:
                value = self.values.express()
            ors.append(operation(attr, value))
        query = query.filter(or_(*ors))

        return [query]


class ValueListStatement(StatementAction["ValueListSearch"]):
    """Generates queries when the whole search string is a list of values.

    Search with a list of values is the broadest search and searches all the
    mapper and the properties configured with `SearchStrategy.add_meta()`
    """

    def __init__(self, tokens: ParseResults) -> None:
        logger.debug("%s::__init__(%s)", self.__class__.__name__, tokens)
        self.values = tokens[0]

    def __repr__(self) -> str:
        return str(self.values)

    def invoke(self, search_strategy: ValueListSearch) -> list[Query]:
        logger.debug("ValueListQueryAction:invoke %s", self.values)
        if any(len(str(i)) < 4 for i in self.values) or len(self.values) > 3:
            # a single letter (i.e. 'a' including the parentheses) in the
            # values or too many values
            logger.debug("Warn, no specific query")
            msg = _(
                "The search string provided contains no specific query "
                "and will search against all fields in all tables. It "
                "also contains content that could take a long time to "
                "return results.\n\n"
                "<b>Is this what you intended?</b>\n\n"
            )
            if not utils.yes_no_dialog(msg, yes_delay=1):
                logger.debug("user aborted")
                return []

        queries = []
        for cls, columns in search_strategy.properties.items():
            column_cross_value = []
            for column in columns:
                for value in self.values:
                    if value.value and hasattr(value.value, "raw_value"):
                        value = value.value.raw_value
                    else:
                        value = value.express()
                    column_cross_value.append((column, value))

            table = class_mapper(cls)
            query = (
                search_strategy.session.query(cls)
                .filter(
                    or_(
                        *[
                            utils.ilike(table.c[c], f"%{v}%")
                            for c, v in column_cross_value
                        ]
                    )
                )
                .distinct()
            )
            queries.append(query)
        return queries
