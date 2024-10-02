# Copyright 2008, 2009, 2010 Brett Adams
# Copyright 2014-2015 Mario Frasca <mario@anche.no>.
# Copyright 2021-2024 Ross Demuth <rossdemuth123@gmail.com>
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
Search identifiers

Search identifiers are pyparsing parse actions that refers to the left hand
side of a database query. i.e. the object to be compared with the value token.
The most basic is a table column address (e.g. `ident.ident.ident`).
"""

import logging

logger = logging.getLogger(__name__)

import typing
from abc import ABC
from abc import abstractmethod

from pyparsing import ParseResults
from sqlalchemy.orm import Query
from sqlalchemy.orm import QueryableAttribute
from sqlalchemy.orm import aliased
from sqlalchemy.sql import Select
from sqlalchemy.sql import distinct
from sqlalchemy.sql.elements import ColumnElement

from bauble.db import Base
from bauble.db import get_related_class

from .clauses import QueryHandler
from .operations import OPERATIONS


@typing.overload
def create_joins(
    query: Query,
    cls: Base,
    steps: list[str],
    alias: bool = False,
    alias_return: str = "",
    _current: Base | None = None,
) -> tuple[Query, Base, Base]:
    """When provided a Query and alias_return return a Query and include the
    alias."""


@typing.overload
def create_joins(
    query: Query,
    cls: Base,
    steps: list[str],
    alias: bool = False,
    alias_return: None = None,
    _current: Base | None = None,
) -> tuple[Query, Base, Base | None]:
    """When provided a Query return a Query"""


@typing.overload
def create_joins(
    query: Select,
    cls: Base,
    steps: list[str],
    alias: bool = False,
    alias_return: str | None = None,
    _current: Base | None = None,
) -> tuple[Select, Base, None]:
    """When provided a Select return a Select"""


def create_joins(
    query: Query | Select,
    cls: Base,
    steps: list[str],
    alias: bool = False,
    alias_return: str | None = None,
    _current: Base | None = None,
) -> tuple[Query | Select, Base, Base | None]:
    """Given a starting query, class and steps add the appropriate `join()`
    clauses to the query.  Returns the query and the last class in the joins.
    """
    # pylint: disable=protected-access
    if not hasattr(query, "_to_join"):
        # monkeypatch _to_join so it is available at all steps of creating the
        # query or will not alias correctly
        query._to_join = [cls]  # type: ignore[union-attr]
    if not steps:
        return (query, cls, _current)
    step = steps[0]
    steps = steps[1:]

    # AssociationProxy
    if hasattr(associationproxy := getattr(cls, step), "value_attr"):
        new_step = associationproxy.value_attr
        step = associationproxy.local_attr.key
        steps.insert(0, new_step)

    joinee = get_related_class(cls, step)

    attribute = getattr(cls, step)

    if joinee in query._to_join or alias:
        logger.debug("Aliasing %s", joinee)
        joinee = aliased(joinee)
        query = query.join(attribute.of_type(joinee))
        if step == alias_return:
            _current = joinee
    else:
        query = query.join(attribute)
        query._to_join.append(joinee)

    return create_joins(query, joinee, steps, alias, alias_return, _current)


class IdentifierAction(ABC):
    """A pyparsing parse action class that refers to a database identifier as
    used in a SQLA ORM query.  i.e. The field to be queried against the value
    of the token.
    """

    @abstractmethod
    def __init__(self, tokens: ParseResults) -> None:
        """Set tokens"""

    @abstractmethod
    def __repr__(self) -> str:
        """Repr for logging etc."""

    @abstractmethod
    def evaluate(
        self, handler: QueryHandler
    ) -> tuple[Query | Select, QueryableAttribute]:
        """return pair (query, attribute) where query is an altered query where
        the joinpoint is the one relative to the attribute, and attribute is
        the attribute itself.
        """


class UnfilteredIdentifier(IdentifierAction):
    """Represents a dot joined identifier to a database model attr.

    i.e. ident.ident2.attr
    """

    def __init__(self, tokens: ParseResults) -> None:
        logger.debug("%s::__init__(%s)", self.__class__.__name__, tokens)
        self.steps: list[str] = tokens[:-1]
        self.leaf: str = tokens[-1]

    def __repr__(self) -> str:
        return ".".join(self.steps + [self.leaf])

    def evaluate(
        self, handler: QueryHandler
    ) -> tuple[Query | Select, QueryableAttribute]:
        logger.debug("%s::evaluate %s", self.__class__.__name__, self)
        if len(self.steps) == 0:
            # identifier is an attribute of the table being queried
            cls = handler.domain
        else:
            # identifier is an attribute of a joined table
            handler.query, cls, __ = create_joins(
                handler.query, handler.domain, self.steps
            )

        attr = getattr(cls, self.leaf)
        logger.debug(
            "IdentifierToken for %s, %s evaluates to %s", cls, self.leaf, attr
        )
        return (handler.query, attr)


class FilteredIdentifier(IdentifierAction):
    """Represents a dot joined identifier to a database model attr that is also
    filtered by other binary clauses.

    e.g. ident.model[attr2=value2, attr3=value3].attr[atr4=value4].attr
    """

    def __init__(self, tokens: ParseResults) -> None:
        logger.debug("%s::__init__(%s)", self.__class__.__name__, tokens)
        self.filtered_steps: list[ParseResults] = tokens[:-1]
        self.leaf_indentifier: UnfilteredIdentifier = tokens[-1]

    def __repr__(self) -> str:
        filter_str = ""
        for identifier, filters in self.filtered_steps:
            filter_str += ".".join(identifier.steps + [identifier.leaf])
            filter_str += "["
            filter_str += ",".join(
                ["".join(str(i) for i in filter_) for filter_ in filters]
            )
            filter_str += "]"
        return f"{filter_str}.{self.leaf_indentifier}"

    @staticmethod
    def add_filter_clauses(
        filter_: ParseResults, handler: QueryHandler, this_cls: Base
    ) -> None:
        filter_attr = filter_[0]
        filter_op = filter_[1]
        filter_value = filter_[2]

        def clause(attr, operation, val) -> ColumnElement:
            assert operation is not None
            return operation(attr, val)

        operation = OPERATIONS.get(filter_op.lower())
        attr = getattr(this_cls, filter_attr)

        logger.debug("filtering on %s(%s)", type(attr), attr)
        handler.query = handler.query.filter(
            clause(attr, operation, filter_value.express(handler))
        )

    def evaluate(
        self, handler: QueryHandler
    ) -> tuple[Query | Select, QueryableAttribute]:
        logger.debug("%s::evaluate %s", self.__class__.__name__, self)

        this_cls = handler.domain
        for identifier, filters in self.filtered_steps:
            steps = identifier.steps + [identifier.leaf]
            handler.query, _cls, this_cls = create_joins(
                handler.query,
                this_cls,
                steps,
                alias=True,
                alias_return=steps[-1],
            )

            for filter_ in filters:
                self.add_filter_clauses(filter_, handler, this_cls)

        handler.query, cls, _this = create_joins(
            typing.cast(Query, handler.query),
            this_cls,
            self.leaf_indentifier.steps,
        )
        attr = getattr(cls, self.leaf_indentifier.leaf)
        return (handler.query, attr)


class FunctionIdentifier(IdentifierAction):
    """Represents an identifier that is wrapped in a function.

    Note that while this is the parse action for the function call expression
    it only atempts to handle the identifier within the functional call, not
    the whole expression.

    i.e. func(IdentifierAction)
    """

    def __init__(self, tokens: ParseResults) -> None:
        logger.debug("%s::__init__(%s)", self.__class__.__name__, tokens)
        self.function: str = tokens[0].lower()
        self.distinct: str = tokens[1].lower() if len(tokens) == 3 else None
        self.identifier: IdentifierAction = tokens[-1]

    def __repr__(self) -> str:
        distinct_str = self.distinct.upper() + " " if self.distinct else ""
        return f"{self.function}({distinct_str}{self.identifier})"

    def evaluate(
        self, handler: QueryHandler
    ) -> tuple[Query | Select, QueryableAttribute]:
        """Let the identifier compute the query and its attribute, no need to
        alter anything right now since the condition on the identifier is
        applied in the HAVING and not in the WHERE for aggreate functions and
        the clause will decide this.
        """
        logger.debug("%s::evaluate %s", self.__class__.__name__, self)
        query, attr = self.identifier.evaluate(handler)

        if self.distinct:
            # believe it is safe to treat it as a QueryableAttribute
            attr = typing.cast(QueryableAttribute, distinct(attr))

        return query, attr
