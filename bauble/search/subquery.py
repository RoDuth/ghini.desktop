# Copyright 2024 Ross Demuth <rossdemuth123@gmail.com>
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
Logical parts required to create a subquery usable as a right hand side value.
"""

import logging
from abc import ABC
from abc import abstractmethod
from typing import cast

logger = logging.getLogger(__name__)

from pyparsing import ParseResults
from sqlalchemy import alias
from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy.orm import QueryableAttribute
from sqlalchemy.orm import Session
from sqlalchemy.orm import class_mapper
from sqlalchemy.sql import Select
from sqlalchemy.sql import distinct
from sqlalchemy.sql.selectable import ScalarSelect

from bauble.db import Base
from bauble.db import get_model_by_name
from bauble.db import get_related_class
from bauble.error import SearchException

from .clauses import AGGREGATE_FUNC_NAMES
from .clauses import QueryHandler
from .identifiers import UnfilteredIdentifier
from .identifiers import create_joins
from .operations import OPERATIONS
from .tokens import TokenAction


def get_table_model(tokens: ParseResults) -> type[Base]:
    model = get_model_by_name(tokens[0])
    if not model:
        raise SearchException(f"unknown table {tokens[0]}")
    return model


def correlate_subquery(
    query: Select, domain: type[Base], steps: list[str]
) -> Select:
    """Given a starting subquery, class and steps add the appropriate `filter`
    clauses to the subquery as required for correlation and return it.
    """
    steps = steps.copy()
    step = steps[0]

    join_step = None
    for r in class_mapper(domain).relationships:
        if r.mapper.class_.__tablename__ == step:
            join_step = r.key

    if not join_step:
        raise SearchException(
            "Correlated subquery property must begin with a directly "
            f"related table - `{domain.__tablename__}` "
            f"is not related to `{step}`"
        )

    steps[0] = join_step
    logger.debug("correlate: %s", steps)

    current = domain

    for step in steps:

        relation = getattr(class_mapper(current).relationships, step)
        query = query.filter(relation.primaryjoin)

        current = get_related_class(current, step)

    return query.correlate(domain)


class SubQueryAction(ABC):
    """Parse action class to extend the subquery select statement."""

    @abstractmethod
    def __init__(self, tokens: ParseResults) -> None:
        """Set tokens"""

    @abstractmethod
    def __repr__(self) -> str:
        """Repr for logging etc."""

    @abstractmethod
    def evaluate(  # pylint: disable=too-many-arguments
        self,
        session: Session,
        sub_query: Select,
        table: type[Base],
        domain: type[Base],
        steps: list[str],
    ) -> Select:
        """return select attribute pair."""


class CorrelateAction(SubQueryAction):
    """Correlate the subquery (i.e. execute for each row of the outer query)"""

    def __init__(self, tokens: ParseResults) -> None:
        logger.debug("%s::__init__(%s)", self.__class__.__name__, tokens)
        # no need for tokens in this case, parser deals with it
        pass

    def __repr__(self) -> str:
        return "CORRELATE"

    def evaluate(
        self,
        _session: Session,
        sub_query: Select,
        _table: type[Base],
        domain: type[Base],
        steps: list[str],
    ) -> Select:

        logger.debug("%s::evaluate %s", self.__class__.__name__, self)

        sub_query = correlate_subquery(sub_query, domain, steps)
        return sub_query


class WhereAction(SubQueryAction):
    """Add a WHERE clause to the subquery."""

    def __init__(self, tokens: ParseResults) -> None:
        logger.debug("%s::__init__(%s)", self.__class__.__name__, tokens)
        self.identifier: UnfilteredIdentifier = tokens[0]
        self.binop: str = tokens[1]
        self.value: TokenAction = tokens[2]
        self.steps: list[str] = self.identifier.steps

    def __repr__(self) -> str:
        return f"WHERE {self.identifier} {self.binop} {self.value}"

    def evaluate(
        self,
        session: Session,
        sub_query: Select,
        table: type[Base],
        _domain: type[Base],
        _steps: list[str],
    ) -> Select:

        logger.debug("%s::evaluate %s", self.__class__.__name__, self)

        operation = OPERATIONS[self.binop.lower()]

        subq_handler = QueryHandler(session, table, sub_query)

        sub_query, attr = self.identifier.evaluate(subq_handler)
        value = self.value.express(subq_handler)
        return sub_query.filter(operation(attr, value))


class SubQueryIdentifierAction(ABC):
    """A pyparsing parse action class that refers to a database identifier as
    used in a subquery select statement.
    """

    steps: list[str]
    table: type[Base]

    @abstractmethod
    def __init__(self, tokens: ParseResults) -> None:
        """Set tokens"""

    @abstractmethod
    def __repr__(self) -> str:
        """Repr for logging etc."""

    @abstractmethod
    def evaluate(
        self, handler: QueryHandler, correlate: bool, optional_parts
    ) -> tuple[Select, QueryableAttribute]:
        """return select attribute pair."""


class SubQueryIdentifier(SubQueryIdentifierAction):
    """Identifier that begins with a table name and is dot joined to an attr.

    i.e. table.ident.attr
    """

    def __init__(self, tokens: ParseResults) -> None:
        logger.debug("%s::__init__(%s)", self.__class__.__name__, tokens)
        self.table: type[Base] = tokens[0]
        self.table_name: str = self.table.__tablename__
        self.leaf_path: UnfilteredIdentifier = tokens[1]
        self.steps = [self.table_name] + self.leaf_path.steps

    def __repr__(self) -> str:
        return f"{self.table_name}.{self.leaf_path}"

    def evaluate(
        self, handler: QueryHandler, correlate: bool, _optional_parts
    ) -> tuple[Select, QueryableAttribute]:

        logger.debug("%s::evaluate %s", self.__class__.__name__, self)
        subq_handler = QueryHandler(handler.session, self.table, select())
        # evaluate to get the attr
        __, attr = self.leaf_path.evaluate(subq_handler)
        # create the select and evaluate again for the joins
        sub_query = select(attr)
        subq_handler.query = sub_query
        sub_query, attr = self.leaf_path.evaluate(subq_handler)

        if correlate:
            sub_query = select(attr)

        return (sub_query, attr)


class SubQueryFuncIdentifier(SubQueryIdentifierAction):
    """Wraps the subquery identifier in a function call(s)."""

    def __init__(self, tokens: ParseResults) -> None:
        logger.debug("%s::__init__(%s)", self.__class__.__name__, tokens)
        self.function: str = tokens[0].lower()
        self.distinct: str = tokens[1].lower() if len(tokens) == 3 else ""
        self.identifier: SubQueryIdentifierAction = tokens[-1]
        # get the steps and table, may be nested
        identifier = self.identifier
        self.steps: list[str]
        self.table: type[Base]
        while True:
            if isinstance(identifier, SubQueryFuncIdentifier):
                self.distinct = identifier.distinct
            else:
                self.steps = identifier.steps
                self.table = identifier.table

            ident = getattr(identifier, "identifier", None)
            if not ident:
                break

            identifier = ident

    def __repr__(self) -> str:
        distinct_str = "DISTINCT " if self.distinct else ""
        return f"{self.function}({distinct_str}{self.identifier})"

    def evaluate(  # pylint: disable=too-many-locals
        self, handler: QueryHandler, correlate: bool, optional_parts
    ) -> tuple[Select, QueryableAttribute]:

        logger.debug("%s::evaluate %s", self.__class__.__name__, self)

        funcs: list = []
        identifier: SubQueryIdentifierAction = self
        aggregates = 0

        while True:
            if isinstance(identifier, SubQueryFuncIdentifier):
                if identifier.function in AGGREGATE_FUNC_NAMES:
                    aggregates += 1

                funcs.append(getattr(func, identifier.function))
                identifier = identifier.identifier
                continue

            __, attr = identifier.evaluate(handler, correlate, optional_parts)

            if self.distinct:
                # treat as a QueryableAttribute
                attr = cast(QueryableAttribute, distinct(attr))

            break

        # only accounts for 2 function calls, should be enough?
        if len(funcs) == 2 and aggregates == 2:
            # when an aggregate function wraps another aggregate function the
            # intention would surely be to query against all other members of
            # the domain so the inner function call needs to create a table for
            # the outer function to use as you can not aggregate something that
            # is already aggregated. (i.e. max(1) will fail, max([1]) will not)
            sub_query = select(funcs[1](attr).label("inner"))
            sub_query, _cls, _alias = create_joins(
                sub_query, self.table, self.steps[1:]
            )
            # need to consume the optional parts here in this case. i.e. where
            # filter and/or correlate
            for part in optional_parts:
                sub_query = part.evaluate(
                    handler.session,
                    sub_query,
                    self.table,
                    handler.domain,
                    self.steps,
                )

            optional_parts.clear()
            table = alias(
                sub_query.group_by(getattr(self.table, "id")).subquery()
            )
            sub_query = select(funcs[0](table.c.inner))
        else:
            for f in reversed(funcs):
                attr = f(attr)

            sub_query = select(attr)

        return (sub_query, attr)


class SubQueryValue(TokenAction):
    """Subquery that may be used in place of a value or value list token."""

    def __init__(self, tokens: ParseResults) -> None:
        logger.debug("%s::__init__(%s)", self.__class__.__name__, tokens)
        self.identifier: SubQueryIdentifierAction = tokens[0]
        self.optional_parts: list[SubQueryAction] = tokens[1:]

    def __repr__(self) -> str:
        optional_parts = " ".join(str(p) for p in self.optional_parts)
        optional_parts = " " + optional_parts if optional_parts else ""
        return f"{self.identifier}{optional_parts}"

    def express(self, handler: QueryHandler) -> ScalarSelect:
        logger.debug("%s::express %s", self.__class__.__name__, self)

        correlate = False

        if self.optional_parts:
            correlate = isinstance(self.optional_parts[-1], CorrelateAction)

        sub_query, __ = self.identifier.evaluate(
            handler, correlate, self.optional_parts
        )

        for part in self.optional_parts:
            sub_query = part.evaluate(
                handler.session,
                sub_query,
                self.identifier.table,
                handler.domain,
                self.identifier.steps,
            )

        return sub_query.scalar_subquery()
