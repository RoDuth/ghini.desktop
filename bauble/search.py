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
Search functionailty.

The three main searches strategies are provided here, others exist in plugins.

1) ValueListSearch strategy is a fall back search that searches all domains
against all properties (as provided via MapperSearch.add_meta) that CONTAIN any
of strings in the search string.
e.g.: `LOC1 LOC2 LOC3`

2) DomainSearch strategy is used for simple domain searches, i.e.:
    <domain|shorthand> <operator> <value>
e.g.: `loc=LOC1`

3) MapperSearch strategy provides full syntax expression searches, i.e.:
    <domain> <where> <expression>
e.g.: `location where code = LOC1`
"""
from __future__ import annotations

import logging
import typing
from abc import ABC
from abc import abstractmethod
from dataclasses import dataclass
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from functools import lru_cache

logger = logging.getLogger(__name__)


from pyparsing import CaselessLiteral
from pyparsing import Forward
from pyparsing import Group
from pyparsing import Keyword
from pyparsing import Literal
from pyparsing import OneOrMore
from pyparsing import OpAssoc
from pyparsing import ParseException
from pyparsing import ParseResults
from pyparsing import Regex
from pyparsing import Word
from pyparsing import WordEnd
from pyparsing import WordStart
from pyparsing import ZeroOrMore
from pyparsing import alphanums
from pyparsing import alphas
from pyparsing import alphas8bit
from pyparsing import delimited_list
from pyparsing import infix_notation
from pyparsing import one_of
from pyparsing import quoted_string
from pyparsing import remove_quotes
from pyparsing import srange
from pyparsing import string_end
from sqlalchemy import and_
from sqlalchemy import or_
from sqlalchemy import select
from sqlalchemy.orm import Query
from sqlalchemy.orm import QueryableAttribute
from sqlalchemy.orm import Session
from sqlalchemy.orm import aliased
from sqlalchemy.orm import class_mapper
from sqlalchemy.sql import Select
from sqlalchemy.sql import func
from sqlalchemy.sql.elements import BinaryExpression
from sqlalchemy.sql.elements import ColumnElement

import bauble
from bauble import prefs
from bauble import utils
from bauble.db import Base
from bauble.db import get_related_class
from bauble.error import check

result_cache: dict[str, list[Query]] = {}
"""Cache of search strategy results, can use instead of running the search
repeatedly. Results should be available in the same order that the search
strategies where added to `_search_strategies`."""


def search(text: str, session: Session) -> list:
    """Given a query string run the appropriate SearchStrategy(s) and return
    the collated results as a list
    """
    logger.debug("searching: `%s`", text)
    results = set()
    # clear the cache
    result_cache.clear()
    strategies = get_strategies(text)
    for strategy in strategies:
        strategy_name = type(strategy).__name__
        logger.debug(
            "applying search strategy %s from module %s",
            strategy_name,
            type(strategy).__module__,
        )
        # result_cache - cache the result list not the query
        queries = strategy.search(text, session)

        result: list[Query] = []
        for query in queries:
            if prefs.prefs.get(prefs.exclude_inactive_pref):
                table = query.column_descriptions[0]["type"]
                if hasattr(table, "active"):
                    query = query.filter(table.active.is_(True))

            # NOTE handy print statement for debugging
            # print("QUERY >>>", query)

            result.extend(query)

        result_cache[strategy_name] = result
        results.update(result)
    return list(results)


Val: typing.TypeAlias = str | float | None


def equal(attr: QueryableAttribute, val: Val) -> ColumnElement:
    return attr == val


def not_equal(attr: QueryableAttribute, val: Val) -> ColumnElement:
    return attr != val


def less_than(attr: QueryableAttribute, val: Val) -> ColumnElement:
    return attr < val


def less_than_or_equal(attr: QueryableAttribute, val: Val) -> ColumnElement:
    return attr <= val


def greater_than(attr: QueryableAttribute, val: Val) -> ColumnElement:
    return attr > val


def greater_than_or_equal(attr: QueryableAttribute, val: Val) -> ColumnElement:
    return attr >= val


def like(attr: QueryableAttribute, val: Val) -> ColumnElement:
    return utils.ilike(attr, f"{val}")


def contains(attr: QueryableAttribute, val: Val) -> ColumnElement:
    return utils.ilike(attr, f"%%{val}%%")


OPERATIONS: dict[
    str, typing.Callable[[QueryableAttribute, str | None], ColumnElement]
] = {
    "=": equal,
    "==": equal,
    "is": equal,
    "!=": not_equal,
    "<>": not_equal,
    "not": not_equal,
    "<": less_than,
    "<=": less_than_or_equal,
    ">": greater_than,
    ">=": greater_than_or_equal,
    "like": like,
    "contains": contains,
    "has": contains,
    "ilike": like,
    "icontains": contains,
    "ihas": contains,
}


@typing.overload
def create_joins(
    query: Query, cls: Base, steps: list[str], alias: bool = False
) -> tuple[Query, Base]:
    """When provided a Query return a Query"""


@typing.overload
def create_joins(
    query: Select, cls: Base, steps: list[str], alias: bool = False
) -> tuple[Select, Base]:
    """When provided a Select return a Select"""


def create_joins(
    query: Query | Select,
    cls: Base,
    steps: list[str],
    alias: bool = False,
) -> tuple[Query | Select, Base]:
    """Given a starting query, class and steps add the appropriate join()
    clauses to the query.  Returns the query and the last class in the joins.
    """
    # pylint: disable=protected-access
    if not hasattr(query, "_to_join"):
        # monkeypatch _to_join
        query._to_join = [cls]  # type: ignore[union-attr]
    if not steps:
        return (query, cls)
    step = steps[0]
    steps = steps[1:]

    if hasattr(cls, step):
        # AssociationProxy
        if hasattr(getattr(cls, step), "value_attr"):
            new_step = getattr(cls, step).value_attr
            step = getattr(cls, step).local_attr.key
            steps.insert(0, new_step)

        joinee = get_related_class(cls, step)

        if joinee in query._to_join or alias:
            joinee = aliased(joinee)
            query = query.join(getattr(cls, step).of_type(joinee))
        else:
            query = query.join(getattr(cls, step))
            query._to_join.append(joinee)  # type: ignore[union-attr]

        cls = joinee

    return create_joins(query, cls, steps, alias)


class TokenAction(ABC):
    """A pyparsing parse action class that refers to a single token or list of
    tokens. i.e. the value(s) to query for.
    """

    @abstractmethod
    def __init__(self, tokens: ParseResults) -> None:
        """Set tokens"""

    @abstractmethod
    def __repr__(self) -> str:
        """Repr for logging etc."""

    @abstractmethod
    def express(self) -> None | set[None] | list | str | float | TokenAction:
        """Returns the token value as used in queries"""


class NoneToken(TokenAction):
    """`Literal('None')`"""

    def __init__(self, tokens: ParseResults | None = None) -> None:
        logger.debug("%s::__init__(%s)", self.__class__.__name__, tokens)

    def __repr__(self) -> str:
        return "(None<NoneType>)"

    def express(self) -> None:
        return None


class EmptyToken(TokenAction):
    """`Literal('Empty')`"""

    def __init__(self, tokens: ParseResults | None = None) -> None:
        logger.debug("%s::__init__(%s)", self.__class__.__name__, tokens)

    def __repr__(self) -> str:
        return "Empty"

    def express(self) -> set:
        return set()

    def __eq__(self, other: object) -> bool:
        if isinstance(other, EmptyToken):
            return True
        if isinstance(other, set):
            return len(other) == 0
        return NotImplemented


class StringToken(TokenAction):
    """Any string, quoted or not"""

    def __init__(self, tokens: ParseResults) -> None:
        logger.debug("%s::__init__(%s)", self.__class__.__name__, tokens)
        self.value: str = tokens[0]

    def __repr__(self) -> str:
        return f"'{self.value}'"

    def express(self) -> str:
        """Returns the unquoted string."""
        return self.value


class NumericToken(TokenAction):
    """Any numeric value"""

    def __init__(self, tokens: ParseResults) -> None:
        logger.debug("%s::__init__(%s)", self.__class__.__name__, tokens)
        self.value = float(str(tokens[0]))  # store the float value
        # ValueListAction and DomainQueryAction: need the raw value
        self.raw_value: str = tokens[0]

    def __repr__(self) -> str:
        return str(self.value)

    def express(self) -> float:
        """Returns the value as a float."""
        return self.value


class ValueToken(TokenAction):
    """Any token (i.e. any TokenAction)"""

    def __init__(self, tokens: ParseResults) -> None:
        logger.debug("%s::__init__(%s)", self.__class__.__name__, tokens)
        Token: typing.TypeAlias = (
            NoneToken | EmptyToken | StringToken | NumericToken
        )
        self.value: Token = tokens[0]

    def __repr__(self) -> str:
        return str(self.value)

    def express(self) -> None | set | list | str | float:
        """Returns the result of calling express on the recieved token."""
        return self.value.express()


class ValueListToken(TokenAction):
    """A list of tokens [TokenAction, ...]"""

    def __init__(self, tokens: ParseResults) -> None:
        logger.debug("%s::__init__(%s)", self.__class__.__name__, tokens)
        self.values: ParseResults = tokens[0]

    def __repr__(self) -> str:
        return str(self.values)

    def express(self) -> list[None | set | list | str | float]:
        """Returns the results of calling express on the recieved tokens as a
        list.
        """
        return [i.express() for i in self.values]


class IdentAction(ABC):
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


class IdentifierAction(IdentAction):
    """Represents a dot joined identifier to a database model attr."""

    def __init__(self, tokens: ParseResults) -> None:
        logger.debug("IdentifierAction::__init__(%s)", tokens)
        self.steps: list[str] = tokens[0][:-2:2]
        self.leaf: str = tokens[0][-1]

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
            handler.query, cls = create_joins(
                handler.query, handler.domain, self.steps
            )
            logger.debug("create_joins cls = %s", cls)

        attr = getattr(cls, self.leaf)
        logger.debug(
            "IdentifierToken for %s, %s evaluates to %s", cls, self.leaf, attr
        )
        return (handler.query, attr)


class FilteredIdentifierAction(IdentAction):
    """Represents a dot joined identifier to a database model attr that is also
    filtered. i.e. ident.model[attr=value].attr2
    """

    def __init__(self, tokens: ParseResults) -> None:
        logger.debug("FilteredIdentifierAction::__init__(%s)", tokens)
        self.steps: list[str] = tokens[0][:-7:2]
        self.filter_attr: str = tokens[0][-6]
        self.filter_op: str = tokens[0][-5]
        self.filter_value: TokenAction = tokens[0][-4]
        self.leaf: str = tokens[0][-1]

        # cfr: SearchParser.binop
        # = == != <> < <= > >= not like contains has ilike icontains ihas is
        self.operation = OPERATIONS.get(self.filter_op)

    def __repr__(self) -> str:
        return (
            f"{'.'.join(self.steps)}"
            f"[{self.filter_attr}{self.filter_op}{self.filter_value}]"
            f".{self.leaf}"
        )

    def evaluate(
        self, handler: QueryHandler
    ) -> tuple[Query | Select, QueryableAttribute]:
        logger.debug("%s::evaluate %s", self.__class__.__name__, self)

        handler.query, cls = create_joins(
            handler.query, handler.domain, self.steps, alias=True
        )
        logger.debug("create_joins cls = %s", cls)

        attr = getattr(cls, self.filter_attr)

        def clause(val) -> ColumnElement:
            assert self.operation is not None
            return self.operation(attr, val)

        logger.debug("filtering on %s(%s)", type(attr), attr)
        handler.query = handler.query.filter(
            clause(self.filter_value.express())
        )
        attr = getattr(cls, self.leaf)
        logger.debug(
            "IdentifierToken for %s, %s evaluates to %s", cls, self.leaf, attr
        )
        return (handler.query, attr)


class AggregatingAction(IdentAction):
    """Represents an identifier that is wrapped in a sum, min, max or count
    function.

    i.e. func(IdentifierAction)
    """

    def __init__(self, tokens: ParseResults) -> None:
        logger.debug("%s::__init__(%s)", self.__class__.__name__, tokens)
        self.function = tokens[0]
        self.identifier: IdentifierAction = tokens[2]

    def __repr__(self) -> str:
        return f"({self.function} {self.identifier})"

    def evaluate(
        self, handler: QueryHandler
    ) -> tuple[Query | Select, QueryableAttribute]:
        """Let the identifier compute the query and its attribute, we do not
        need to alter anything right now since the condition on the aggregated
        identifier is applied in the HAVING and not in the WHERE.
        """
        logger.debug("%s::evaluate %s", self.__class__.__name__, self)

        return self.identifier.evaluate(handler)


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
        self.operation: typing.Callable | None = OPERATIONS.get(self.oper)
        # every second object is an operand
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
    from dateutil import parser

    from .btypes import get_date

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
        if isinstance(attr.type, bauble.btypes.DateTime):
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

        main_table = handler.query.column_descriptions[0]["entity"]

        id_ = getattr(main_table, "id")

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


@dataclass
class QueryHandler:
    session: Session
    domain: Base
    query: Query | Select


class SearchStrategy(ABC):
    """interface for adding search strategies to a view."""

    excludes_value_list_search = True
    """If this search strategy is included do not include ValueListSearch, (the
    fall back strategy when no others are appropriate)"""

    def __init__(self):
        self.session = None

    @staticmethod
    @abstractmethod
    def use(text: str) -> typing.Literal["include", "exclude", "only"]:
        """How does this search stratergy apply to the provided text.

        i.e.:
        "exclude" remove this strategy from the list of strategies to run
        "include" include this strategy from the list of strategies to run
        "only" remove all other strategies from the list of strategies to run
        """

    @abstractmethod
    def search(self, text: str, session: Session) -> list[Query]:
        """Execute the search:

        :param text: the search string
        :param session: the session to use for the search

        :return: A list of queries where query.is_single_entity == True.
        """
        if not session:
            logger.warning("session is None")
        # NOTE this logger is used in various tests
        logger.debug('SearchStrategy "%s" (%s)', text, self.__class__.__name__)
        return []


StrategyT = typing.TypeVar("StrategyT", bound=SearchStrategy)


class QueryAction(ABC, typing.Generic[StrategyT]):
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


class ExpressionQueryAction(QueryAction["MapperSearch"]):
    """Generates `domain where expression` queries.

    The most complex query type.
    """

    def __init__(self, tokens: ParseResults) -> None:
        logger.debug("%s::__init__(%s)", self.__class__.__name__, tokens)
        self.domain = tokens[0]
        self.filter = tokens[1][0]

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


BinCallable: typing.TypeAlias = typing.Callable[[list | str], BinaryExpression]


class DomainQueryAction(QueryAction["DomainSearch"]):
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

    def get_condition(self, mapper) -> typing.Callable[[str], BinCallable]:
        if self.cond in ("like", "ilike"):

            def condition(col: str) -> BinCallable:
                return lambda val: utils.ilike(mapper.c[col], str(val))

        elif self.cond in ("contains", "icontains", "has", "ihas"):

            def condition(col: str) -> BinCallable:
                return lambda val: utils.ilike(mapper.c[col], f"%%{val}%%")

        elif self.cond in ("=", "=="):

            def condition(col: str) -> BinCallable:
                return lambda val: mapper.c[col] == utils.nstr(val)

        elif self.cond == "in":

            def condition(col: str) -> BinCallable:
                return mapper.c[col].in_

        else:
            # e.g. acc > 2023.0001
            def condition(col: str) -> BinCallable:
                return mapper.c[col].op(self.cond)

        return condition

    def invoke(self, search_strategy: DomainSearch) -> list[Query]:
        logger.debug("DomainQueryAction:invoke")
        try:
            self.domain = search_strategy.shorthand.get(
                self.domain, self.domain
            )
            cls, properties = search_strategy.domains[self.domain]
        except KeyError as e:
            raise KeyError(f"Unknown search domain: {self.domain}") from e

        query = search_strategy.session.query(cls)

        # select all objects from the domain or None
        if self.values == "*":
            if self.cond in ("!=", "<>"):
                return [query.filter(False)]
            return [query]

        mapper = class_mapper(cls)

        condition = self.get_condition(mapper)

        ors = []
        for column in properties:
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
            ors.append(condition(column)(value))
        query = query.filter(or_(*ors))

        return [query]


class ValueListQueryAction(QueryAction["ValueListSearch"]):
    """Generates queries when the whole search string is a list of values.

    Search with a list of values is the broadest search and searches all the
    mapper and the properties configured with `MapperSearch.add_meta()`
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
            msg = _(  # type: ignore[name-defined]
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
                            contains(table.c[c], v)
                            for c, v in column_cross_value
                        ]
                    )
                )
                .distinct()
            )
            queries.append(query)
        return queries


class SearchParser:  # pylint: disable=too-few-public-methods
    """The parser for bauble.search.MapperSearch"""

    date_str = Regex(
        r"\d{1,4}[/.-]{1}\d{1,2}[/.-]{1}\d{1,4}"
    ).set_parse_action(StringToken)
    numeric_value = Regex(r"[-]?\d+(\.\d*)?([eE]\d+)?").set_parse_action(
        NumericToken
    )

    unquoted_string = Word(alphanums + alphas8bit + "%.-_*;:")

    string_value = (
        quoted_string.set_parse_action(remove_quotes) | unquoted_string
    ).set_parse_action(StringToken)

    none_token = Literal("None").set_parse_action(NoneToken)
    empty_token = Literal("Empty").set_parse_action(EmptyToken)

    value = (
        date_str
        | WordStart("0123456789.-e") + numeric_value + WordEnd("0123456789.-e")
        | none_token
        | empty_token
        | string_value
    ).set_parse_action(ValueToken)("value")

    value_list = Group(
        OneOrMore(value) ^ delimited_list(value)
    ).set_parse_action(ValueListToken)("value_list")

    domain = Word(alphas, alphas + "_")
    binop = one_of(
        "= == != <> < <= > >= not like contains has ilike icontains ihas is"
    )
    binop_set = Literal("in")
    binop_date = Literal("on")

    caps = srange("[A-Z]")
    lowers = caps.lower() + "-"

    AND_ = WordStart() + (CaselessLiteral("AND") | Literal("&&")) + WordEnd()
    OR_ = WordStart() + (CaselessLiteral("OR") | Literal("||")) + WordEnd()
    NOT_ = WordStart() + (CaselessLiteral("NOT") | Literal("!")) + WordEnd()
    BETWEEN_ = WordStart() + CaselessLiteral("BETWEEN") + WordEnd()

    aggregating_func = (
        Literal("sum") | Literal("min") | Literal("max") | Literal("count")
    )

    query_expression = Forward()

    atomic_identifier = Word(alphas + "_", alphanums + "_")
    identifier = Group(
        atomic_identifier
        + ZeroOrMore("." + atomic_identifier)
        + "["
        + atomic_identifier
        + binop
        + value
        + "]"
        + "."
        + atomic_identifier
    ).set_parse_action(FilteredIdentifierAction) | Group(
        atomic_identifier + ZeroOrMore("." + atomic_identifier)
    ).set_parse_action(
        IdentifierAction
    )

    aggregated = (
        aggregating_func + Literal("(") + identifier + Literal(")")
    ).set_parse_action(AggregatingAction)
    ident_expression = (
        Group(identifier + binop + value).set_parse_action(IdentExpression)
        | Group(identifier + binop_set + value_list).set_parse_action(
            ElementSetExpression
        )
        | Group(identifier + binop_date + value).set_parse_action(
            DateOnExpression
        )
        | Group(aggregated + binop + value).set_parse_action(
            AggregatedExpression
        )
        | (Literal("(") + query_expression + Literal(")")).set_parse_action(
            ParenthesisedExpression
        )
    )
    between_expression = Group(
        identifier + BETWEEN_ + value + AND_ + value
    ).set_parse_action(BetweenExpression)
    # pylint: disable=expression-not-assigned
    query_expression << infix_notation(
        (ident_expression | between_expression),
        [
            (NOT_, 1, OpAssoc.RIGHT, SearchNotExpression),
            (AND_, 2, OpAssoc.LEFT, SearchAndExpression),
            (OR_, 2, OpAssoc.LEFT, SearchOrExpression),
        ],
    )("filter")

    query = (
        domain
        + Keyword("where", caseless=True).suppress()
        + Group(query_expression)
        + string_end
    ).set_parse_action(ExpressionQueryAction)("query")

    def parse_string(self, text: str) -> ParseResults:
        """request pyparsing object to parse text

        `text` can be either a query, or a domain expression, or a list of
        values. the `self.query` pyparsing object parses the input text
        and returns a pyparsing.ParseResults object that represents the input.
        """

        return self.query.parse_string(text)


class MapperSearch(SearchStrategy):
    """Supports query of the form: `domain where expression`

    This is the main search strategy, other strategies can use the meta_data
    added here.
    """

    domains: dict[str, tuple[Base, list[str]]] = {}
    shorthand: dict[str, str] = {}
    properties: dict[Base, list[str]] = {}
    # placed here for simple search convenience.
    completion_funcs: dict[str, typing.Callable] = {}

    def __init__(self) -> None:
        super().__init__()
        self.parser = SearchParser()

    @staticmethod
    def use(text: str) -> typing.Literal["include", "exclude", "only"]:
        atomised = text.split()
        if atomised[0] in MapperSearch.domains and atomised[1] == "where":
            return "include"
        return "exclude"

    def add_meta(
        self, domain: tuple[str, ...], cls: Base, properties: list[str]
    ) -> None:
        """Add a domain to the search space

        an example of domain is a database table, where the properties would
        be the table columns to consider in the search.  continuing this
        example, a record is be selected if any of the fields matches the
        searched value.

        NOTE: get_domain_classes will only return the first entry per class so
        add the default first.

        :param domain: a tuple of domain names as strings that will resolve
                       a search string to cls.  domain act as a shorthand to
                       the class name.
        :param cls: the class the domain will resolve to
        :param properties: a list of string names of the properties to
                           search by default
        """

        logger.debug("%s.add_meta(%s, %s, %s)", self, domain, cls, properties)

        check(
            isinstance(properties, list),
            _("default_columns argument must be list"),  # type: ignore[name-defined]  # noqa
        )
        check(
            len(properties) > 0,
            _("default_columns argument cannot be empty"),  # type: ignore[name-defined]  # noqa
        )
        self.domains[domain[0]] = cls, properties
        for dom in domain[1:]:
            self.shorthand[dom] = domain[0]
        self.properties[cls] = properties

    @classmethod
    def get_domain_classes(cls) -> dict[str, Base]:
        """Returns a dictionary of domains names, as strings, to the classes
        they point to.

        Only the first domain name per class, as added via add_meta, is
        returned.
        """
        domains: dict[str, Base] = {}
        for domain, item in cls.domains.items():
            if item[0] not in domains.values():
                domains.setdefault(domain, item[0])
        return domains

    def search(self, text: str, session: Session) -> list[Query]:
        """Returns list of queries for the text search string."""
        super().search(text, session)
        self.session = session
        result = self.parser.parse_string(text).query
        logger.debug("result : %s(%s)", type(result), result)
        query = result.invoke(self)

        return query


class DomainSearch(SearchStrategy):
    """Supports searches of the form: `domain operator value`

    resolves the domain and searches specific columns from the mapping
    """

    shorthand = MapperSearch.shorthand
    domains = MapperSearch.domains

    value = SearchParser.value
    value_list = SearchParser.value_list
    domain = SearchParser.domain
    binop = SearchParser.binop
    in_op = SearchParser.binop_set

    star_value = Literal("*")
    domain_values = value_list.copy()("domain_values")
    domain_expression = (
        domain + binop + star_value + string_end
        | domain + binop + value + string_end
        | domain + in_op + domain_values + string_end
    ).set_parse_action(DomainQueryAction)("query")

    @staticmethod
    @lru_cache(maxsize=8)
    def use(text: str) -> typing.Literal["include", "exclude", "only"]:
        # cache the result to avoid calling multiple times...
        try:
            DomainSearch.domain_expression.parse_string(text)
            logger.debug("including DomainSearch in strategies")
            return "include"
        except ParseException:
            pass
        return "exclude"

    def search(self, text: str, session: Session) -> list[Query]:
        """Returns list of queries for the text search string."""
        super().search(text, session)
        self.session = session
        result = self.domain_expression.parse_string(text).query
        logger.debug("result : %s(%s)", type(result), result)
        query = result.invoke(self)

        return query


class ValueListSearch(SearchStrategy):
    """Supports searches that are just list of values.

    Searches all domains and registered columns for values.

    Least desirable search as it is not specific and can take a lot of time.
    """

    properties = MapperSearch.properties

    value = SearchParser.value
    value_list = Group(
        OneOrMore(value) ^ delimited_list(value)
    ).set_parse_action(ValueListQueryAction)("query")

    @staticmethod
    def use(text: str) -> typing.Literal["include", "exclude", "only"]:
        for strategy in _search_strategies.values():
            if isinstance(strategy, ValueListSearch):
                continue
            if strategy.excludes_value_list_search and strategy.use(text) in (
                "include",
                "only",
            ):
                return "exclude"
        return "include"

    def search(self, text: str, session: Session) -> list[Query]:
        """Returns list of queries for the text search string."""
        super().search(text, session)
        self.session = session
        result = self.value_list.parse_string(text).query
        logger.debug("result : %s(%s)", type(result), result)
        queries = result.invoke(self)

        return queries


# search strategies to be tried on each search string
_search_strategies: dict[str, SearchStrategy] = {
    "MapperSearch": MapperSearch(),
    "DomainSearch": DomainSearch(),
    "ValueListSearch": ValueListSearch(),
}


def add_strategy(strategy: type[SearchStrategy]) -> None:
    logger.debug("adding strategy: %s", strategy.__name__)
    obj = strategy()
    _search_strategies[strategy.__name__] = obj


def get_strategy(name: str) -> SearchStrategy | None:
    return _search_strategies.get(name)


def get_strategies(text: str) -> list[SearchStrategy]:
    """Provided the search text return appropriate strategies.

    Each strategy should have a `use` method that, given the search text will
    return one of:
        'only' - use only the strategy
        'include' - include the strategy
        'exclude' - exclude the strategy

    :param text: the search string
    """
    all_strategies = _search_strategies.values()
    selected_strategies: list[SearchStrategy] = []
    for strategy in all_strategies:
        logger.debug("strategy: %s", strategy)
        use = strategy.use(text)
        if use == "only":
            logger.debug("filtered strategies [%s]", strategy)
            return [strategy]
        if use == "include":
            selected_strategies.append(strategy)
        elif use == "exclude":
            if strategy in selected_strategies:
                selected_strategies.remove(strategy)
    logger.debug("filtered strategies %s", selected_strategies)
    return selected_strategies
