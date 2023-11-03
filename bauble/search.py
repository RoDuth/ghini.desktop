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
"""

import logging
import typing
from abc import ABC
from abc import abstractmethod
from datetime import timedelta
from datetime import timezone

logger = logging.getLogger(__name__)


from pyparsing import CaselessLiteral
from pyparsing import Forward
from pyparsing import Group
from pyparsing import Keyword
from pyparsing import Literal
from pyparsing import OneOrMore
from pyparsing import OpAssoc
from pyparsing import ParseException
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
from sqlalchemy.orm import Session
from sqlalchemy.orm import class_mapper

import bauble
from bauble import prefs
from bauble import utils
from bauble.db import Base
from bauble.db import get_related_class
from bauble.error import check

result_cache: dict[str, list[Query]] = {}
"""Cache of search strategy results, can use instead of running the search
repeatedly. MapperSearch results should be available first."""


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


def equal(attr, val):
    return attr == val


def not_equal(attr, val):
    return attr != val


def less_than(attr, val):
    return attr < val


def less_than_or_equal(attr, val):
    return attr <= val


def greater_than(attr, val):
    return attr > val


def greater_than_or_equal(attr, val):
    return attr >= val


def like(attr, val):
    return utils.ilike(attr, f"{val}")


def contains(attr, val):
    return utils.ilike(attr, f"%%{val}%%")


OPERATIONS = {
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


def create_joins(query, cls, steps, alias=False):
    """Given a starting query, class and steps add the appropriate join()
    clauses to the query.  Returns the query and the last class in the joins.
    """
    # pylint: disable=protected-access
    if not hasattr(query, "_to_join"):
        query._to_join = [cls]
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
            from sqlalchemy.orm import aliased

            joinee = aliased(joinee)
            query = query.join(getattr(cls, step).of_type(joinee))
        else:
            query = query.join(getattr(cls, step))
            # query = query.join(joinee)
            query._to_join.append(joinee)

        cls = joinee

    return create_joins(query, cls, steps, alias)


class NoneToken:
    def __init__(self, token=None):
        pass

    def __repr__(self):
        return "(None<NoneType>)"

    def express(self):
        return None


class EmptyToken:
    def __init__(self, token=None):
        pass

    def __repr__(self):
        return "Empty"

    def express(self):
        return set()

    def __eq__(self, other):
        if isinstance(other, EmptyToken):
            return True
        if isinstance(other, set):
            return len(other) == 0
        return NotImplemented


class ValueABC(ABC):
    # abstract base class.

    def __init__(self, token):
        self.value = token[0]

    @abstractmethod
    def __repr__(self):
        """Derived classes should impliment a repr"""

    def express(self):
        return self.value


class ValueToken(ValueABC):
    def __repr__(self):
        return str(self.value)

    def express(self):
        return self.value.express()


class StringToken(ValueABC):
    def __repr__(self):
        return f"'{self.value}'"


class NumericToken(ValueABC):
    def __init__(self, token):  # pylint: disable=super-init-not-called
        self.value = float(token[0])  # store the float value
        self.raw_value = token[0]  # ValueListAction.invoke: use the raw value

    def __repr__(self):
        return str(self.value)


class IdentifierAction:
    def __init__(self, tokens):
        logger.debug("IdentifierAction::__init__(%s)", tokens)
        self.steps = tokens[0][:-2:2]
        self.leaf = tokens[0][-1]

    def __repr__(self):
        return ".".join(self.steps + [self.leaf])

    def evaluate(self, env):
        """return pair (query, attribute)

        the value associated to the identifier is an altered query where the
        joinpoint is the one relative to the attribute, and the attribute
        itself.
        """
        logger.debug("%s::evaluate %s", self.__class__.__name__, self)
        if len(self.steps) == 0:
            # identifier is an attribute of the table being queried
            cls = env.domain
        else:
            # identifier is an attribute of a joined table
            env.query, cls = create_joins(env.query, env.domain, self.steps)
            logger.debug("create_joins cls = %s", cls)

        attr = getattr(cls, self.leaf)
        logger.debug(
            "IdentifierToken for %s, %s evaluates to %s", cls, self.leaf, attr
        )
        return (env.query, attr)

    def needs_join(self, _env):
        return self.steps


class FilteredIdentifierAction:
    def __init__(self, tokens):
        logger.debug("FilteredIdentifierAction::__init__(%s)", tokens)
        self.steps = tokens[0][:-7:2]
        self.filter_attr = tokens[0][-6]
        self.filter_op = tokens[0][-5]
        self.filter_value = tokens[0][-4]
        self.leaf = tokens[0][-1]

        # cfr: SearchParser.binop
        # = == != <> < <= > >= not like contains has ilike icontains ihas is
        self.operation = OPERATIONS.get(self.filter_op)

    def __repr__(self):
        return (
            f"{'.'.join(self.steps)}"
            f"[{self.filter_attr}{self.filter_op}{self.filter_value}]"
            f".{self.leaf}"
        )

    def evaluate(self, env):
        """return pair (query, attribute)"""
        logger.debug("%s::evaluate %s", self.__class__.__name__, self)

        if len(self.steps) == 0:
            # identifier is an attribute of the table being queried
            cls = env.domain
        else:
            # identifier is an attribute of a joined table
            env.query, cls = create_joins(
                env.query, env.domain, self.steps, alias=True
            )
            logger.debug("create_joins cls = %s", cls)

        attr = getattr(cls, self.filter_attr)

        def clause(val):
            return self.operation(attr, val)

        logger.debug("filtering on %s(%s)", type(attr), attr)
        env.query = env.query.filter(clause(self.filter_value.express()))
        attr = getattr(cls, self.leaf)
        logger.debug(
            "IdentifierToken for %s, %s evaluates to %s", cls, self.leaf, attr
        )
        return (env.query, attr)

    def needs_join(self, _env):
        return self.steps


class IdentExpression:
    def __init__(self, tokens):
        logger.debug("IdentExpression::__init__(%s)", tokens)
        self.oper = tokens[0][1]

        # cfr: SearchParser.binop
        # = == != <> < <= > >= not like contains has ilike icontains ihas is
        self.operation = OPERATIONS.get(self.oper)
        self.operands = tokens[0][0::2]  # every second object is an operand

    def __repr__(self):
        return f"({self.operands[0]} {self.oper} {self.operands[1]})"

    def evaluate(self, env):
        logger.debug("%s::evaluate %s", self.__class__.__name__, self)
        env.query, attr = self.operands[0].evaluate(env)
        if self.operands[1].express() == set():
            # check against the empty set
            if self.oper in ("is", "=", "=="):
                env.query = env.query.filter(~attr.any())
                return env.query
            if self.oper in ("not", "<>", "!="):
                env.query = env.query.filter(attr.any())
                return env.query

        def clause(val):
            return self.operation(attr, val)

        logger.debug("filtering on %s(%s)", type(attr), attr)
        env.query = env.query.filter(clause(self.operands[1].express()))
        return env.query

    def needs_join(self, _env):
        # Its not here but in operands[0] that the join should be created.
        return []


class ElementSetExpression(IdentExpression):
    # currently only implements `in`

    def evaluate(self, env):
        logger.debug("%s::evaluate %s", self.__class__.__name__, self)
        env.query, attr = self.operands[0].evaluate(env)
        env.query = env.query.filter(attr.in_(self.operands[1].express()))
        return env.query


def get_datetime(value):
    from dateutil import parser

    from .btypes import get_date

    result = get_date(value)
    if not result:
        try:
            # try parsing as iso8601 first
            result = parser.isoparse(value)
        except ValueError:
            try:
                result = parser.parse(
                    value,
                    dayfirst=prefs.prefs[prefs.parse_dayfirst_pref],
                    yearfirst=prefs.prefs[prefs.parse_yearfirst_pref],
                )
            except ValueError:
                result = parser.parse(value, fuzzy=True)
    return result.replace(hour=0, minute=0, second=0, microsecond=0)


class DateOnExpression(IdentExpression):
    # implements `on` for date matching

    def evaluate(self, env):
        logger.debug("%s::evaluate %s", self.__class__.__name__, self)
        env.query, attr = self.operands[0].evaluate(env)
        date_val = self.operands[1].express()
        if isinstance(date_val, (str, float)):
            date_val = get_datetime(date_val)
        if isinstance(attr.type, bauble.btypes.DateTime):
            logger.debug("is DateTime")
            today = date_val.astimezone(tz=timezone.utc)
            tomorrow = today + timedelta(1)
            logger.debug("today: %s", today)
            logger.debug("tomorrow: %s", tomorrow)
            env.query = env.query.filter(and_(attr >= today, attr < tomorrow))
        else:
            # btype.Date - only need the date
            env.query = env.query.filter(attr == date_val.date())
        return env.query


class AggregatedExpression(IdentExpression):
    """Select on value of aggregated function.

    this one looks like ident.binop.value, but the ident is an
    aggregating function, so that the query has to be altered
    differently: not filter, but group_by and having.
    """

    def __init__(self, tokens):
        super().__init__(tokens)
        logger.debug("AggregatedExpression::__init__(%s)", tokens)

    def evaluate(self, env):
        logger.debug("%s::evaluate %s", self.__class__.__name__, self)
        # operands[0] is the function/identifier pair
        # operands[1] is the value against which to test
        # operation implements the clause
        env.query, __ = self.operands[0].identifier.evaluate(env)
        from sqlalchemy.sql import func

        function = getattr(func, self.operands[0].function)

        main_table = env.query.column_descriptions[0]["type"]

        id_ = getattr(main_table, "id")

        sub_query = select(id_).group_by(id_)

        joins = self.operands[0].needs_join(env)
        sub_query, cls = create_joins(sub_query, main_table, joins)

        attr = getattr(cls, self.operands[0].identifier.leaf)

        def clause(val):
            return self.operation(function(attr), val)

        having = clause(self.operands[1].express())
        sub_query = sub_query.having(having)
        env.query = env.query.filter(id_.in_(sub_query))

        return env.query


class BetweenExpressionAction:
    def __init__(self, tokens):
        self.operands = tokens[0][0::2]  # every second object is an operand

    def __repr__(self):
        return f"(BETWEEN {' '.join(str(i) for i in self.operands)})"

    def evaluate(self, env):
        logger.debug("%s::evaluate %s", self.__class__.__name__, self)
        env.query, attr = self.operands[0].evaluate(env)

        env.query = env.query.filter(
            and_(
                self.operands[1].express() <= attr,
                attr <= self.operands[2].express(),
            )
        )
        return env.query

    def needs_join(self, env):
        return [self.operands[0].needs_join(env)]


class UnaryLogical(ABC):
    # abstract base class. `name` is defined in derived classes
    def __init__(self, tokens):
        logger.debug("%s::__init__(%s)", self.__class__.__name__, tokens)
        self.oper, self.operand = tokens[0]

    def __repr__(self):
        return f"{self.name} {str(self.operand)}"

    def needs_join(self, env):
        return self.operand.needs_join(env)

    @property
    @abstractmethod
    def name(self):
        """Derived classes should provide a `name` property."""

    @abstractmethod
    def evaluate(self, env):
        """Derived classes should provide an `evaluate` method"""


class BinaryLogical(ABC):
    def __init__(self, tokens):
        logger.debug("%s::__init__(%s)", self.__class__.__name__, tokens)
        self.oper = tokens[0][1]
        self.operands = tokens[0][0::2]  # every second object is an operand

    def __repr__(self):
        name = f" {self.name} "
        string = name.join(str(operand) for operand in self.operands)
        return f"({string})"

    def needs_join(self, env):
        return self.operands[0].needs_join(env) + self.operands[1].needs_join(
            env
        )

    @property
    @abstractmethod
    def name(self):
        """Derived classes should provide a `name` property."""

    @abstractmethod
    def evaluate(self, env):
        """Derived classes should provide an `evaluate` method"""


class SearchAndAction(BinaryLogical):
    name = "AND"

    def evaluate(self, env):
        logger.debug("%s::evaluate %s", self.__class__.__name__, self)
        for operand in self.operands:
            logger.debug("SearchAndAction::operand %s", operand)
            logger.debug("SearchAndAction::type(operand) %s", type(operand))

            env.query = operand.evaluate(env)

        return env.query


class SearchOrAction(BinaryLogical):
    name = "OR"

    def evaluate(self, env):
        logger.debug("%s::evaluate %s", self.__class__.__name__, self)
        # capture the env.query prior to adding unions
        start_env_query = self.operands[0].evaluate(env)
        for operand in self.operands[1:]:
            # start a new query
            if isinstance(env.query, Query):
                env.query = env.session.query(env.domain)
            else:
                env.query = select(env.domain.id)
            start_env_query = start_env_query.union(operand.evaluate(env))
        env.query = start_env_query
        return env.query


class SearchNotAction(UnaryLogical):
    name = "NOT"

    def evaluate(self, env):
        logger.debug("%s::evaluate %s", self.__class__.__name__, self)
        # capture the env.query prior to adding except_
        start_env_query = env.query
        env.query = env.session.query(env.domain)
        env.query = start_env_query.except_(self.operand.evaluate(env))
        return env.query


class ParenthesisedQuery:
    def __init__(self, tokens):
        logger.debug("%s::__init__(%s)", self.__class__.__name__, tokens)
        self.content = tokens[1]

    def __repr__(self):
        return f"({self.content})"

    def evaluate(self, env):
        logger.debug("%s::evaluate %s", self.__class__.__name__, self)
        logger.debug(
            "ParenthesisedQuery::type(content) %s", type(self.content)
        )
        # capture the env.query prior to constructing select sub_query
        start_env_query = env.query
        env.query = select(env.domain.id)
        sub_query = self.content.evaluate(env)
        env.query = start_env_query.filter(env.domain.id.in_(sub_query))
        return env.query

    def needs_join(self, env):
        return self.content.needs_join(env)


class QueryAction:
    def __init__(self, tokens):
        logger.debug("%s::__init__(%s)", self.__class__.__name__, tokens)
        self.domain = tokens[0]
        self.filter = tokens[1][0]
        self.session = None
        self.joined_cls = None
        self.query = None

    def __repr__(self):
        return f"SELECT * FROM {self.domain} WHERE {self.filter}"

    def invoke(self, search_strategy):
        """update search_strategy object with statement results

        Queries can use more database specific features.  This also
        means that the same query might not work the same on different
        database types. For example, on a PostgreSQL database you can
        use ilike but this would raise an error on SQLite.
        """

        logger.debug(
            "QueryAction:invoke - domain: %s(%s) filter: %s(%s)",
            type(self.domain).__name__,
            self.domain,
            type(self.filter).__name__,
            self.filter,
        )
        check(
            self.domain in search_strategy.domains
            or self.domain in search_strategy.shorthand,
            f"Unknown search domain: {self.domain}",
        )
        self.domain = search_strategy.shorthand.get(self.domain, self.domain)
        self.domain = search_strategy.domains[self.domain][0]

        if search_strategy.session is not None:
            self.session = search_strategy.session
            self.query = self.session.query(self.domain)
            self.filter.evaluate(self)  # self becomes env

        return self.query


class DomainExpressionAction:
    """Created when the parser hits a domain_expression token.

    Searching using domain expressions is a little more magical than an
    explicit query. you give a domain, a binary_operator and a value,
    the domain expression will return all object with at least one
    property (as passed to add_meta) matching (according to the binop)
    the value.
    """

    def __init__(self, tokens):
        logger.debug("%s::__init__(%s)", self.__class__.__name__, tokens)
        self.domain = tokens[0]
        self.cond = tokens[1]
        self.values = tokens[2]

    def __repr__(self):
        return f"{self.domain} {self.cond} {self.values}"

    def invoke(self, search_strategy):
        logger.debug("DomainExpressionAction:invoke")
        try:
            self.domain = search_strategy.shorthand.get(
                self.domain, self.domain
            )
            cls, properties = search_strategy.domains[self.domain]
        except KeyError as e:
            raise KeyError(_("Unknown search domain: %s") % self.domain) from e

        query = search_strategy.session.query(cls)

        # here is the place where to optionally filter out unrepresented
        # domain values. each domain class should define its own 'I have
        # accessions' filter. see issue #42

        # select all objects from the domain
        if self.values == "*":
            if self.cond in ("!=", "<>"):
                return []
            return query

        mapper = class_mapper(cls)

        if self.cond in ("like", "ilike"):

            def condition(col):
                return lambda val: utils.ilike(mapper.c[col], str(val))

        elif self.cond in ("contains", "icontains", "has", "ihas"):

            def condition(col):
                return lambda val: utils.ilike(mapper.c[col], f"%%{val}%%")

        elif self.cond in ("=", "=="):

            def condition(col):
                return lambda val: mapper.c[col] == utils.nstr(val)

        else:

            def condition(col):
                return mapper.c[col].op(self.cond)

        ors = []
        for column in properties:
            for value in self.values.values:
                if value.value and hasattr(value.value, "raw_value"):
                    value = value.value.raw_value
                else:
                    value = value.express()
            ors.append(condition(column)(value))
        query = query.filter(or_(*ors))

        return query


class AggregatingAction:
    def __init__(self, tokens):
        logger.debug("%s::__init__(%s)", self.__class__.__name__, tokens)
        self.function = tokens[0]
        self.identifier = tokens[2]

    def __repr__(self):
        return f"({self.function} {self.identifier})"

    def needs_join(self, env):
        joins = self.identifier.needs_join(env)
        if isinstance(joins, list):
            return joins
        return [joins]

    def evaluate(self, env):
        """return pair (query, attribute)

        let the identifier compute the query and its attribute, we do
        not need alter anything right now since the condition on the
        aggregated identifier is applied in the HAVING and not in the
        WHERE.
        """
        logger.debug("%s::evaluate %s", self.__class__.__name__, self)

        return self.identifier.evaluate(env)


class ValueListAction:
    def __init__(self, tokens):
        logger.debug("%s::__init__(%s)", self.__class__.__name__, tokens)
        self.values = tokens[0]

    def __repr__(self):
        return str(self.values)

    def express(self):
        return [i.express() for i in self.values]

    def invoke(self, search_strategy):
        """Called when the whole search string is a value list.

        Search with a list of values is the broadest search and
        searches all the mapper and the properties configured with
        add_meta()
        """

        logger.debug("ValueListAction:invoke")
        if any(len(str(i)) < 4 for i in self.values) or len(self.values) > 3:
            logger.debug("contains single letter")
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
    ).set_parse_action(ValueListAction)("value_list")

    domain = Word(alphas, alphas + "_")
    binop = one_of(
        "= == != <> < <= > >= not like contains has ilike icontains ihas is"
    )
    binop_set = Literal("in")
    binop_date = Literal("on")
    equals = Literal("=")

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
            ParenthesisedQuery
        )
    )
    between_expression = Group(
        identifier + BETWEEN_ + value + AND_ + value
    ).set_parse_action(BetweenExpressionAction)
    # pylint: disable=expression-not-assigned
    query_expression << infix_notation(
        (ident_expression | between_expression),
        [
            (NOT_, 1, OpAssoc.RIGHT, SearchNotAction),
            (AND_, 2, OpAssoc.LEFT, SearchAndAction),
            (OR_, 2, OpAssoc.LEFT, SearchOrAction),
        ],
    )("filter")

    query = (
        domain
        + Keyword("where", caseless=True).suppress()
        + Group(query_expression)
        + string_end
    ).set_parse_action(QueryAction)("query")

    def parse_string(self, text):
        """request pyparsing object to parse text

        `text` can be either a query, or a domain expression, or a list of
        values. the `self.query` pyparsing object parses the input text
        and returns a pyparsing.ParseResults object that represents the input.
        """

        return self.query.parse_string(text)


class SearchStrategy(ABC):
    """interface for adding search strategies to a view."""

    excludes_value_list_search = True
    """If this search strategy is included do not include ValueListSearch"""

    def __init__(self):
        self.session = None

    @staticmethod
    @abstractmethod
    def use(text: str) -> typing.Literal["include", "exclude", "only"]:
        """How does this search stratergy apply to the provided text"""

    @abstractmethod
    def search(self, text: str, session: Session) -> list[Query]:
        """
        :param text: the search string
        :param session: the session to use for the search

        :return: A list of queries where query.is_single_entity == True.
        """
        if not session:
            logger.warning("session is None")
        # NOTE this logger is used in various tests
        logger.debug('SearchStrategy "%s" (%s)', text, self.__class__.__name__)
        return []


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


class MapperSearch(SearchStrategy):

    """
    Mapper Search support three types of search expression:
    1. value searches: search that are just list of values, e.g. value1,
    value2, value3, searches all domains and registered columns for values
    2. expression searches: searched of the form domain=value, resolves the
    domain and searches specific columns from the mapping
    3. query searchs: searches of the form domain where ident.ident = value,
    resolve the domain and identifiers and search for value
    """

    domains: dict[str, tuple[Base, list[str]]] = {}
    shorthand: dict[str, str] = {}
    properties: dict[Base, list[str]] = {}
    # placed here for simple search convenience.
    completion_funcs: dict[str, typing.Callable] = {}

    def __init__(self):
        super().__init__()
        self.parser = SearchParser()

    @staticmethod
    def use(text: str) -> typing.Literal["include", "exclude", "only"]:
        atomised = text.split()
        if atomised[0] in MapperSearch.domains and atomised[1] == "where":
            return "include"
        return "exclude"

    def add_meta(self, domain, cls, properties):
        """Add a domain to the search space

        an example of domain is a database table, where the properties would
        be the table columns to consider in the search.  continuing this
        example, a record is be selected if any of the fields matches the
        searched value.

        NOTE: get_domain_classes will only return the first entry per class so
        add the default first.

        :param domain: a string, list or tuple of domains that will resolve
                       a search string to cls.  domain act as a shorthand to
                       the class name.
        :param cls: the class the domain will resolve to
        :param properties: a list of string names of the properties to
                           search by default
        """

        logger.debug("%s.add_meta(%s, %s, %s)", self, domain, cls, properties)

        check(
            isinstance(properties, list),
            _(
                "MapperSearch.add_meta(): "
                "default_columns argument must be list"
            ),
        )
        check(
            len(properties) > 0,
            _(
                "MapperSearch.add_meta(): "
                "default_columns argument cannot be empty"
            ),
        )
        if isinstance(domain, (list, tuple)):
            self.domains[domain[0]] = cls, properties
            for dom in domain[1:]:
                self.shorthand[dom] = domain[0]
        else:
            self.domains[domain] = cls, properties
        self.properties[cls] = properties

    @classmethod
    def get_domain_classes(cls) -> dict[str, Base]:
        """Returns a dictionary of domains names, as strings, to the classes
        they point to.

        Only the first domain name per class, as added via add_meta, is
        returned.
        """
        domains: dict[str, Base] = {}
        _classes: set[Base] = set()
        for domain, item in cls.domains.items():
            if item[0] not in _classes:
                _classes.add(item[0])
                domains.setdefault(domain, item[0])
        return domains

    def search(self, text, session):
        """Returns list of queries for the text search string."""
        super().search(text, session)
        self.session = session
        statement = self.parser.parse_string(text).query
        logger.debug("statement : %s(%s)", type(statement), statement)
        query = statement.invoke(self)

        return [query]


class DomainSearch(MapperSearch):
    """Supports expression searches of the form:
        <domain> <exp> <value | value_list>

    resolves the domain and searches specific columns from the mapping
    """

    value_list = SearchParser.value_list
    domain = SearchParser.domain
    binop = SearchParser.binop

    star_value = Literal("*")
    domain_values = value_list.copy()("domain_values")
    domain_expression = (domain + binop + star_value + string_end) | (
        domain + binop + domain_values + string_end
    ).set_parse_action(DomainExpressionAction)("statement")

    @staticmethod
    def use(text: str) -> typing.Literal["include", "exclude", "only"]:
        try:
            DomainSearch.domain_expression.parse_string(text)
            logger.debug("including DomainSearch in strategies")
            return "include"
        except ParseException:
            pass
        return "exclude"

    def search(self, text: str, session: Session) -> list[Query]:
        """Returns list of queries for the text search string."""
        super(MapperSearch, self).search(text, session)
        self.session = session
        statement = self.domain_expression.parse_string(text).statement
        logger.debug("statement : %s(%s)", type(statement), statement)
        query = statement.invoke(self)

        return [query]


class ValueListSearch(MapperSearch):
    """Supports searches that are just list of values.

    Searches all domains and registered columns for values.  Least desirable
    search.
    """

    value_list = SearchParser.value_list

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

    def search(self, text, session):
        """Returns list of queries for the text search string."""
        super(MapperSearch, self).search(text, session)
        self.session = session
        statement = self.value_list.parse_string(text).value_list
        logger.debug("statement : %s(%s)", type(statement), statement)
        queries = statement.invoke(self)

        return queries


# search strategies to be tried on each search string
_search_strategies: dict[str, SearchStrategy] = {
    "MapperSearch": MapperSearch(),
    "DomainSearch": DomainSearch(),
    "ValueListSearch": ValueListSearch(),
}


def add_strategy(strategy: type[SearchStrategy]):
    logger.debug("adding strategy: %s", strategy.__name__)
    obj = strategy()
    _search_strategies[strategy.__name__] = obj


def get_strategy(name):
    return _search_strategies.get(name)
