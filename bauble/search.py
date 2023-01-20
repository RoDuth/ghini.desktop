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

from abc import ABC, abstractmethod
from datetime import timedelta, timezone
import logging
logger = logging.getLogger(__name__)


from sqlalchemy import or_, and_
from sqlalchemy.orm import class_mapper, Query
from pyparsing import (Word,
                       alphas8bit,
                       removeQuotes,
                       delimitedList,
                       Regex,
                       ZeroOrMore,
                       OneOrMore,
                       oneOf,
                       alphas,
                       alphanums,
                       Group,
                       Literal,
                       CaselessLiteral,
                       WordStart,
                       WordEnd,
                       srange,
                       stringEnd,
                       Keyword,
                       quotedString,
                       infixNotation,
                       opAssoc,
                       Forward)

import bauble
from bauble.db import get_related_class
from bauble.error import check
from bauble import utils
from bauble import prefs


result_cache = {}
"""Cache of search strategy results, can use instead of running the search
repeatedly. MapperSearch results should be available first."""


def search(text: str, session: bauble.db.Session) -> list:
    """Given a query string run the appropriate SearchStrategy(s) and return
    the collated results as a list
    """
    results = set()
    # clear the cache
    result_cache.clear()
    strategies = get_strategies(text)
    for strategy in strategies:
        strategy_name = type(strategy).__name__
        logger.debug("applying search strategy %s from module %s",
                     strategy_name, type(strategy).__module__)
        # result_cache - cache the result list not the query
        result = list(strategy.search(text, session))

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
    return utils.ilike(attr, f'{val}')


def contains(attr, val):
    return utils.ilike(attr, f'%%{val}%%')


OPERATIONS = {
    '=': equal,
    '==': equal,
    'is': equal,
    '!=': not_equal,
    '<>': not_equal,
    'not': not_equal,
    '<': less_than,
    '<=': less_than_or_equal,
    '>': greater_than,
    '>=': greater_than_or_equal,
    'like': like,
    'contains': contains,
    'has': contains,
    'ilike': like,
    'icontains': contains,
    'ihas': contains,
}


def create_joins(query, cls, steps, aliased=False):
    """Given a starting query, class and steps add the appropriate join()
    clauses to the query.  Returns the query and the last class in the joins.
    """
    to_join = [cls]
    for step in steps:
        if hasattr(cls, step):
            joinee = get_related_class(cls, step)

            if joinee in to_join or aliased:
                from sqlalchemy.orm import aliased
                joinee = aliased(joinee)
                query = query.join(
                    getattr(cls, step).of_type(joinee)
                )
            else:
                query = query.join(getattr(cls, step))
                to_join.append(joinee)

            cls = joinee

    return (query, cls)


class NoneToken:
    def __init__(self, token=None):
        pass

    def __repr__(self):
        return '(None<NoneType>)'

    def express(self):
        return None


class EmptyToken:
    def __init__(self, token=None):
        pass

    def __repr__(self):
        return 'Empty'

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
        ...

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
        logger.debug('IdentifierAction::__init__(%s)', tokens)
        self.steps = tokens[0][:-2:2]
        self.leaf = tokens[0][-1]

    def __repr__(self):
        return '.'.join(self.steps + [self.leaf])

    def evaluate(self, env):
        """return pair (query, attribute)

        the value associated to the identifier is an altered query where the
        joinpoint is the one relative to the attribute, and the attribute
        itself.
        """
        query = env.session.query(env.domain)
        if len(self.steps) == 0:
            # identifier is an attribute of the table being queried
            cls = env.domain
        elif env.joined_cls:
            # joins have already been applied due to AND clause
            cls = env.joined_cls
        else:
            # identifier is an attribute of a joined table
            query, cls = create_joins(query, env.domain, self.steps)

        attr = getattr(cls, self.leaf)
        logger.debug('IdentifierToken for %s, %s evaluates to %s', cls,
                     self.leaf, attr)
        return (query, attr)

    def needs_join(self, _env):
        return self.steps


class FilteredIdentifierAction:
    def __init__(self, tokens):
        logger.debug('FilteredIdentifierAction::__init__(%s)', tokens)
        self.steps = tokens[0][:-7:2]
        self.filter_attr = tokens[0][-6]
        self.filter_op = tokens[0][-5]
        self.filter_value = tokens[0][-4]
        self.leaf = tokens[0][-1]

        # cfr: SearchParser.binop
        # = == != <> < <= > >= not like contains has ilike icontains ihas is
        self.operation = OPERATIONS.get(self.filter_op)

    def __repr__(self):
        return (f"{'.'.join(self.steps)}"
                f"[{self.filter_attr}{self.filter_op}{self.filter_value}]"
                f".{self.leaf}")

    def evaluate(self, env):
        """return pair (query, attribute)"""
        query = env.session.query(env.domain)
        # identifier is an attribute of a joined table

        if env.joined_cls:
            # joins have already been applied due to AND clause
            cls = env.joined_cls
        else:
            query, cls = create_joins(query, env.domain, self.steps,
                                      aliased=True)

        attr = getattr(cls, self.filter_attr)

        def clause(val):
            return self.operation(attr, val)

        logger.debug('filtering on %s(%s)', type(attr), attr)
        query = query.filter(clause(self.filter_value.express()))
        attr = getattr(cls, self.leaf)
        logger.debug('IdentifierToken for %s, %s evaluates to %s', cls,
                     self.leaf, attr)
        return (query, attr)

    def needs_join(self, _env):
        return self.steps


class IdentExpression:
    def __init__(self, tokens):
        logger.debug('IdentExpression::__init__(%s)', tokens)
        self.oper = tokens[0][1]

        # cfr: SearchParser.binop
        # = == != <> < <= > >= not like contains has ilike icontains ihas is
        self.operation = OPERATIONS.get(self.oper)
        self.operands = tokens[0][0::2]  # every second object is an operand

    def __repr__(self):
        return f"({self.operands[0]} {self.oper} {self.operands[1]})"

    def evaluate(self, env):
        query, attr = self.operands[0].evaluate(env)
        if self.operands[1].express() == set():
            # check against the empty set
            if self.oper in ('is', '=', '=='):
                return query.filter(~attr.any())
            if self.oper in ('not', '<>', '!='):
                return query.filter(attr.any())

        def clause(val):
            return self.operation(attr, val)

        logger.debug('filtering on %s(%s)', type(attr), attr)
        query = query.filter(clause(self.operands[1].express()))
        return query

    def needs_join(self, _env):
        # Its not here but in operands[0] that the join should be created.
        return []


class ElementSetExpression(IdentExpression):
    # currently only implements `in`

    def evaluate(self, env):
        query, attr = self.operands[0].evaluate(env)
        return query.filter(attr.in_(self.operands[1].express()))


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
                    yearfirst=prefs.prefs[prefs.parse_yearfirst_pref]
                )
            except ValueError:
                result = parser.parse(value, fuzzy=True)
    return result.replace(hour=0, minute=0, second=0, microsecond=0)


class DateOnExpression(IdentExpression):
    # implements `on` for date matching

    def evaluate(self, env):
        query, attr = self.operands[0].evaluate(env)
        date_val = self.operands[1].express()
        if isinstance(date_val, (str, float)):
            date_val = get_datetime(date_val)
        if isinstance(attr.type, bauble.btypes.DateTime):
            logger.debug('is DateTime')
            today = date_val.astimezone(tz=timezone.utc)
            tomorrow = today + timedelta(1)
            logger.debug('today: %s', today)
            logger.debug('tomorrow: %s', tomorrow)
            return query.filter(and_(attr >= today, attr < tomorrow))
        # btype.Date - only need the date
        return query.filter(attr == date_val.date())


class AggregatedExpression(IdentExpression):
    """Select on value of aggregated function.

    this one looks like ident.binop.value, but the ident is an
    aggregating function, so that the query has to be altered
    differently: not filter, but group_by and having.
    """

    def __init__(self, tokens):
        super().__init__(tokens)
        logger.debug('AggregatedExpression::__init__(%s)', tokens)

    def evaluate(self, env):
        # operands[0] is the function/identifier pair
        # operands[1] is the value against which to test
        # operation implements the clause
        query, attr = self.operands[0].identifier.evaluate(env)
        from sqlalchemy.sql import func
        function = getattr(func, self.operands[0].function)

        def clause(val):
            return self.operation(function(attr), val)

        # group by main ID
        # apply having
        main_table = query.column_descriptions[0]['type']
        mta = getattr(main_table, 'id')
        logger.debug('filtering on %s(%s)', type(mta), mta)
        result = query.group_by(mta).having(clause(self.operands[1].express()))
        return result


class BetweenExpressionAction:
    def __init__(self, tokens):
        self.operands = tokens[0][0::2]  # every second object is an operand

    def __repr__(self):
        return f"(BETWEEN {' '.join(str(i) for i in self.operands)})"

    def evaluate(self, env):
        query, attr = self.operands[0].evaluate(env)

        return query.filter(and_(self.operands[1].express() <= attr,
                                 attr <= self.operands[2].express()))

    def needs_join(self, env):
        return [self.operands[0].needs_join(env)]


class UnaryLogical(ABC):
    # abstract base class. `name` is defined in derived classes
    def __init__(self, tokens):
        self.oper, self.operand = tokens[0]

    def __repr__(self):
        return f"{self.name} {str(self.operand)}"

    def needs_join(self, env):
        return self.operand.needs_join(env)

    @property
    @abstractmethod
    def name(self):
        ...

    @abstractmethod
    def evaluate(self, env):
        ...


class BinaryLogical(ABC):
    # abstract base class. `name` is defined in derived classes
    def __init__(self, tokens):
        self.oper = tokens[0][1]
        self.operands = tokens[0][0::2]  # every second object is an operand

    def __repr__(self):
        return f"({self.operands[0]} {self.name} {self.operands[1]})"

    def needs_join(self, env):
        return (self.operands[0].needs_join(env) +
                self.operands[1].needs_join(env))

    @property
    @abstractmethod
    def name(self):
        ...

    @abstractmethod
    def evaluate(self, env):
        ...


class SearchAndAction(BinaryLogical):
    name = 'AND'

    def evaluate(self, env):
        # need to create joins here then add in the whereclause, for a
        # SearchNotAction no whereclause will be returned, instead an except_
        # will be available, containing relevent joins.
        query = self.operands[0].evaluate(env)
        for operand in self.operands[1:]:
            if (isinstance(operand, IdentExpression) and
                    (joins := operand.operands[0].needs_join(env))):
                query, cls = create_joins(query, env.domain, joins)
                # let the operand know how to formulate the whereclause
                env.joined_cls = cls

            where = operand.evaluate(env).whereclause

            # either add the whereclause or except_
            if where is not None:
                # IdentExpression or FilteredIdentifierAction
                query = query.filter(where)
            elif hasattr(operand, 'except_') and operand.except_:
                # SearchNotAction
                query = query.except_(operand.except_)

        return query


class SearchOrAction(BinaryLogical):
    name = 'OR'

    def evaluate(self, env):
        query = self.operands[0].evaluate(env)
        for operand in self.operands[1:]:
            query = query.union(operand.evaluate(env))
        return query


class SearchNotAction(UnaryLogical):
    name = 'NOT'

    def __init__(self, tokens):
        super().__init__(tokens)
        self.except_ = None

    def evaluate(self, env):
        query = env.session.query(env.domain)
        for steps in self.operand.needs_join(env):
            if steps:
                query, __ = create_joins(query, env.domain, steps)
        self.except_ = self.operand.evaluate(env)
        query = query.except_(self.except_)
        return query


class ParenthesisedQuery:
    def __init__(self, tokens):
        self.content = tokens[1]

    def __repr__(self):
        return f"({self.content})"

    def evaluate(self, env):
        return self.content.evaluate(env)

    def needs_join(self, env):
        return self.content.needs_join(env)


class QueryAction:
    def __init__(self, tokens):
        self.domain = tokens[0]
        self.filter = tokens[1][0]
        self.session = None
        self.joined_cls = None

    def __repr__(self):
        return f"SELECT * FROM {self.domain} WHERE {self.filter}"

    def invoke(self, search_strategy):
        """update search_strategy object with statement results

        Queries can use more database specific features.  This also
        means that the same query might not work the same on different
        database types. For example, on a PostgreSQL database you can
        use ilike but this would raise an error on SQLite.
        """

        logger.debug('QueryAction:invoke - %s(%s) %s(%s)', type(self.domain),
                     self.domain, type(self.filter), self.filter)
        check(self.domain in search_strategy.domains or
              self.domain in search_strategy.shorthand,
              f'Unknown search domain: {self.domain}')
        self.domain = search_strategy.shorthand.get(self.domain, self.domain)
        self.domain = search_strategy.domains[self.domain][0]

        if search_strategy.session is not None:
            self.session = search_strategy.session
            query = self.filter.evaluate(self)

        return query


class StatementAction:  # pylint: disable=too-few-public-methods
    def __init__(self, tokens):
        self.content = tokens[0]
        self.invoke = self.content.invoke

    def __repr__(self):
        return str(self.content)


# TODO move this to its own strategy and place it in species.py
class BinomialNameAction:
    """created when the parser hits a binomial_name token.

    Partial or complete cultivar names are also matched if started with a '

    Searching using binomial names returns one or more species objects.
    """

    def __init__(self, tokens):
        self.genus_epithet = tokens[0]
        if tokens[1].startswith("'"):
            self.cultivar_epithet = tokens[1].strip("'")
            self.species_epithet = None
        else:
            self.cultivar_epithet = None
            self.species_epithet = tokens[1]

    def __repr__(self):
        if self.species_epithet:
            return f'{self.genus_epithet} {self.species_epithet}'
        return f'{self.genus_epithet} {self.cultivar_epithet}'

    def invoke(self, search_strategy):
        logger.debug('BinomialNameAction:invoke')
        from bauble.plugins.plants.genus import Genus
        from bauble.plugins.plants.species import Species

        if self.species_epithet:
            logger.debug('binomial search sp: %s, gen: %s',
                         self.species_epithet, self.genus_epithet)
            query = (search_strategy.session.query(Species)
                     .filter(Species.sp.startswith(self.species_epithet))
                     .join(Genus)
                     .filter(Genus.genus.startswith(self.genus_epithet)))
        else:
            logger.debug('cultivar search cv: %s, gen: %s',
                         self.cultivar_epithet, self.genus_epithet)
            # pylint: disable=no-member  # re: cultivar_epithet.startswith
            query = (search_strategy.session.query(Species)
                     .filter(Species.cultivar_epithet
                             .startswith(self.cultivar_epithet))
                     .join(Genus)
                     .filter(Genus.genus.startswith(self.genus_epithet)))
        return query


class DomainExpressionAction:
    """created when the parser hits a domain_expression token.

    Searching using domain expressions is a little more magical than an
    explicit query. you give a domain, a binary_operator and a value,
    the domain expression will return all object with at least one
    property (as passed to add_meta) matching (according to the binop)
    the value.
    """

    def __init__(self, tokens):
        self.domain = tokens[0]
        self.cond = tokens[1]
        self.values = tokens[2]

    def __repr__(self):
        return f"{self.domain} {self.cond} {self.values}"

    def invoke(self, search_strategy):
        logger.debug('DomainExpressionAction:invoke')
        try:
            if self.domain in search_strategy.shorthand:
                self.domain = search_strategy.shorthand[self.domain]
            cls, properties = search_strategy.domains[self.domain]
        except KeyError as e:
            raise KeyError(_('Unknown search domain: %s') % self.domain) from e

        query = search_strategy.session.query(cls)

        # here is the place where to optionally filter out unrepresented
        # domain values. each domain class should define its own 'I have
        # accessions' filter. see issue #42

        # select all objects from the domain
        if self.values == '*':
            return query

        mapper = class_mapper(cls)

        if self.cond in ('like', 'ilike'):
            def condition(col):
                return lambda val: utils.ilike(mapper.c[col], str(val))
        elif self.cond in ('contains', 'icontains', 'has', 'ihas'):
            def condition(col):
                return lambda val: utils.ilike(mapper.c[col], f'%%{val}%%')
        elif self.cond in ('=', '=='):
            def condition(col):
                return lambda val: mapper.c[col] == utils.nstr(val)
        else:
            def condition(col):
                return mapper.c[col].oper(self.cond)

        ors = [condition(col)(i) for i in self.values.express() for
               col in properties]
        query = query.filter(or_(*ors))

        return query


class AggregatingAction:

    def __init__(self, tokens):
        logger.debug("AggregatingAction::__init__(%s)", tokens)
        self.function = tokens[0]
        self.identifier = tokens[2]

    def __repr__(self):
        return f"({self.function} {self.identifier})"

    def needs_join(self, env):
        return [self.identifier.needs_join(env)]

    def evaluate(self, env):
        """return pair (query, attribute)

        let the identifier compute the query and its attribute, we do
        not need alter anything right now since the condition on the
        aggregated identifier is applied in the HAVING and not in the
        WHERE.
        """

        return self.identifier.evaluate(env)


class ValueListAction:

    def __init__(self, tokens):
        logger.debug("ValueListAction::__init__(%s)", tokens)
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

        logger.debug('ValueListAction:invoke')
        if any(len(str(i)) < 4 for i in self.values) or len(self.values) > 3:
            logger.debug('contains single letter')
            msg = _('The search string provided contains no specific query '
                    'and will search against all fields in all tables. It '
                    'also contains content that could take a long time to '
                    'return results.\n\n'
                    '<b>Is this what you intended?</b>\n\n')
            if not utils.yes_no_dialog(msg, yes_delay=1):
                logger.debug('user aborted')
                return []

        result = set()
        for cls, columns in search_strategy.properties.items():
            column_cross_value = []
            for column in columns:
                for value in self.values:
                    if value.value and hasattr(value.value, 'raw_value'):
                        value = value.value.raw_value
                    else:
                        value = value.express()
                    column_cross_value.append((column, value))

            table = class_mapper(cls)
            query = (search_strategy.session.query(cls)
                     .filter(or_(*[contains(table.c[c], v) for c, v in
                                   column_cross_value])))
            result.update(query.all())
        return result


wordStart, wordEnd = WordStart(), WordEnd()


class SearchParser:  # pylint: disable=too-few-public-methods
    """The parser for bauble.search.MapperSearch"""

    date_str = Regex(
        r'\d{1,4}[/.-]{1}\d{1,2}[/.-]{1}\d{1,4}'
    ).set_parse_action(StringToken)
    numeric_value = Regex(
        r'[-]?\d+(\.\d*)?([eE]\d+)?'
    ).set_parse_action(NumericToken)

    unquoted_string = Word(alphanums + alphas8bit + '%.-_*;:')

    string_value = (
        quotedString.set_parse_action(removeQuotes) | unquoted_string
    ).set_parse_action(StringToken)

    none_token = Literal('None').set_parse_action(NoneToken)
    empty_token = Literal('Empty').set_parse_action(EmptyToken)

    value = (
        date_str |
        WordStart('0123456789.-e') + numeric_value + WordEnd('0123456789.-e') |
        none_token |
        empty_token |
        string_value
    ).set_parse_action(ValueToken)('value')

    value_list = Group(
        OneOrMore(value) ^ delimitedList(value)
    ).set_parse_action(ValueListAction)('value_list')

    domain = Word(alphas, alphas + '_')
    binop = oneOf('= == != <> < <= > >= not like contains has ilike '
                  'icontains ihas is')
    binop_set = oneOf('in')
    binop_date = oneOf('on')
    equals = Literal('=')
    star_value = Literal('*')
    domain_values = (value_list.copy())('domain_values')
    domain_expression = (
        (domain + equals + star_value + stringEnd) |
        (domain + binop + domain_values + stringEnd)
    ).set_parse_action(DomainExpressionAction)('domain_expression')

    caps = srange("[A-Z]")
    lowers = caps.lower() + '-'
    binomial_name = (
        Word(caps, lowers) + (
            Word(lowers) | Word("'", caps + lowers + " ") + Literal("'") |
            Word("'", caps + lowers))
    ).set_parse_action(BinomialNameAction)('binomial_name')

    AND_ = wordStart + (CaselessLiteral("AND") | Literal("&&")) + wordEnd
    OR_ = wordStart + (CaselessLiteral("OR") | Literal("||")) + wordEnd
    NOT_ = wordStart + (CaselessLiteral("NOT") | Literal('!')) + wordEnd
    BETWEEN_ = wordStart + CaselessLiteral("BETWEEN") + wordEnd

    aggregating_func = (Literal('sum') | Literal('min') | Literal('max') |
                        Literal('count'))

    query_expression = Forward()

    atomic_identifier = Word(alphas + '_', alphanums + '_')
    identifier = (
        Group(atomic_identifier + ZeroOrMore('.' + atomic_identifier) + '[' +
              atomic_identifier + binop + value + ']' + '.' +
              atomic_identifier).set_parse_action(FilteredIdentifierAction) |
        Group(atomic_identifier + ZeroOrMore('.' + atomic_identifier)
              ).set_parse_action(IdentifierAction))

    aggregated = (aggregating_func + Literal('(') + identifier + Literal(')')
                  ).set_parse_action(AggregatingAction)
    ident_expression = (Group(identifier + binop + value
                              ).set_parse_action(IdentExpression) |
                        Group(identifier + binop_set + value_list
                              ).set_parse_action(ElementSetExpression) |
                        Group(identifier + binop_date + value
                              ).set_parse_action(DateOnExpression) |
                        Group(aggregated + binop + value
                              ).set_parse_action(AggregatedExpression) |
                        (Literal('(') + query_expression + Literal(')')
                         ).set_parse_action(ParenthesisedQuery))
    between_expression = Group(
        identifier + BETWEEN_ + value + AND_ + value
    ).set_parse_action(BetweenExpressionAction)
    # pylint: disable=expression-not-assigned
    query_expression << infixNotation(
        (ident_expression | between_expression),
        [(NOT_, 1, opAssoc.RIGHT, SearchNotAction),
         (AND_, 2, opAssoc.LEFT, SearchAndAction),
         (OR_, 2, opAssoc.LEFT, SearchOrAction)])('filter')

    query = (domain + Keyword('where', caseless=True).suppress() +
             Group(query_expression) + stringEnd).set_parse_action(QueryAction)

    statement = (query('query') |
                 domain_expression('domain') |
                 binomial_name('binomial') |
                 value_list('value_list')
                 ).set_parse_action(StatementAction)('statement')

    def parse_string(self, text):
        """request pyparsing object to parse text

        `text` can be either a query, or a domain expression, or a list of
        values. the `self.statement` pyparsing object parses the input text
        and return a pyparsing.ParseResults object that represents the input
        """

        return self.statement.parseString(text)


class SearchStrategy(ABC):
    """interface for adding search strategies to a view."""

    def __init__(self):
        self.session = None

    @staticmethod
    @abstractmethod
    def use(text):
        ...

    def search(self, text, session):
        """
        :param text: the search string
        :param session: the session to use for the search

        Return an iterator that iterates over mapped classes retrieved
        from the search.
        """
        if not session:
            logger.warning('session is None')
        # NOTE this logger is used in various tests
        logger.debug('SearchStrategy "%s" (%s)', text, self.__class__.__name__)


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
    selected_strategies = []
    for strategy in all_strategies:
        if strategy.use(text) == 'only':
            logger.debug('filtered strategies %s', strategy)
            return [strategy]
        if strategy.use(text) == 'include':
            selected_strategies.append(strategy)
        elif strategy.use(text) == 'exclude':
            if strategy in selected_strategies:
                selected_strategies.remove(strategy)
    logger.debug('filtered strategies %s', selected_strategies)
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

    domains = {}
    shorthand = {}
    properties = {}
    # placed here for simple search convenience.
    completion_funcs = {}

    def __init__(self):
        super().__init__()
        self.parser = SearchParser()

    @staticmethod
    def use(_text):
        return 'include'

    def add_meta(self, domain, cls, properties):
        """Add a domain to the search space

        an example of domain is a database table, where the properties would
        be the table columns to consider in the search.  continuing this
        example, a record is be selected if any of the fields matches the
        searched value.

        :param domain: a string, list or tuple of domains that will resolve
                       a search string to cls.  domain act as a shorthand to
                       the class name.
        :param cls: the class the domain will resolve to
        :param properties: a list of string names of the properties to
                           search by default
        """

        logger.debug('%s.add_meta(%s, %s, %s)', self, domain, cls, properties)

        check(isinstance(properties, list),
              _('MapperSearch.add_meta(): '
                'default_columns argument must be list'))
        check(len(properties) > 0,
              _('MapperSearch.add_meta(): '
                'default_columns argument cannot be empty'))
        if isinstance(domain, (list, tuple)):
            self.domains[domain[0]] = cls, properties
            for dom in domain[1:]:
                self.shorthand[dom] = domain[0]
        else:
            self.domains[domain] = cls, properties
        self.properties[cls] = properties

    @classmethod
    def get_domain_classes(cls):
        domains = {}
        for domain, item in cls.domains.items():
            domains.setdefault(domain, item[0])
        return domains

    def search(self, text, session):
        """Returns an interable of database hits for the text search string.
        """
        super().search(text, session)
        self.session = session
        statement = self.parser.parse_string(text).statement
        logger.debug("statement : %s(%s)", type(statement), statement)
        results_or_query = statement.invoke(self)

        # NOTE handy print statement for development
        # if isinstance(results_or_query, Query):
        #     print(results_or_query)

        if prefs.prefs.get(prefs.exclude_inactive_pref):
            # handle within the database when possible
            if (isinstance(results_or_query, Query) and
                    results_or_query.is_single_entity):
                table = results_or_query.column_descriptions[0]['type']
                if hasattr(table, 'active'):
                    results_or_query = (results_or_query
                                        .filter(table.active.is_(True)))
            else:
                results_or_query = [i for i in results_or_query if
                                    getattr(i, 'active', True)]

        return results_or_query


# list of search strategies to be tried on each search string
_search_strategies = {'MapperSearch': MapperSearch()}


def add_strategy(strategy):
    logger.debug('adding strategy: %s', strategy.__name__)
    obj = strategy()
    _search_strategies[obj.__class__.__name__] = obj


def get_strategy(name):
    return _search_strategies.get(name, None)
