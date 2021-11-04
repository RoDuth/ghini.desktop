# Copyright 2008, 2009, 2010 Brett Adams
# Copyright 2014-2015 Mario Frasca <mario@anche.no>.
# Copyright 2017 Jardín Botánico de Quito
# Copyright 2021 Ross Demuth <rossdemuth123@gmail.com>
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

import logging
logger = logging.getLogger(__name__)

from gi.repository import Gtk  # noqa

from sqlalchemy import or_, and_, Integer, Float
from sqlalchemy.orm import class_mapper, RelationshipProperty
from sqlalchemy.orm.properties import ColumnProperty
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm.attributes import InstrumentedAttribute
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
from bauble.error import check
from bauble import utils
from bauble.editor import GenericEditorPresenter
from .querybuilderparser import BuiltQuery


def search(text, session=None):
    results = set()
    strategies = get_strategies(text)
    for strategy in strategies:
        strategy_name = type(strategy).__name__
        logger.debug("applying search strategy %s from module %s",
                     strategy_name, type(strategy).__module__)
        result = strategy.search(text, session)
        # add results to cache
        result_cache[strategy_name] = result
        results.update(result)
    return list(results)


class NoneToken:
    def __init__(self, t=None):
        pass

    def __repr__(self):
        return '(None<NoneType>)'

    def express(self):
        return None


class EmptyToken:
    def __init__(self, t=None):
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


class ValueABC:
    # abstract base class.

    def express(self):
        return self.value


class ValueToken:

    def __init__(self, t):
        self.value = t[0]

    def __repr__(self):
        return repr(self.value)

    def express(self):
        return self.value.express()


class StringToken(ValueABC):

    def __init__(self, t):
        self.value = t[0]  # no need to parse the string

    def __repr__(self):
        return f"'{self.value}'"


class DateToken(ValueABC):
    def __init__(self, t):
        self.value = t[0]  # no need to parse treated as a string

    def __repr__(self):
        return f"{self.value}"


class NumericToken(ValueABC):
    def __init__(self, t):
        self.value = float(t[0])  # store the float value

    def __repr__(self):
        return f"{self.value}"


def smartdatetime(year_or_offset, *args):
    """return either datetime.datetime, or a day with given offset.

    When given only one argument, this is interpreted as an offset for
    timedelta, and it is added to datetime.today().  If given more
    arguments, it just behaves as datetime.datetime.
    """
    from datetime import datetime, timedelta
    if not args:
        return (datetime.today()
                .replace(hour=0, minute=0, second=0, microsecond=0) +
                timedelta(year_or_offset))
    return datetime(year_or_offset, *args)


def smartboolean(*args):
    """translate args into boolean value

    Result is True whenever first argument is not numerically zero nor
    literally 'false'.  No arguments cause error.
    """
    if len(args) == 1:
        try:
            return float(args[0]) != 0.0
        except (ValueError, TypeError):
            return args[0].lower() != 'false'
    return True


class TypedValueToken(ValueABC):
    # |<name>|<paramlist>|
    constructor = {'datetime': (smartdatetime, int),
                   'bool': (smartboolean, str)}

    def __init__(self, t):
        logger.debug('constructing typedvaluetoken %s', str(t))
        try:
            constructor, converter = self.constructor[t[1]]
        except KeyError:
            return
        params = tuple(converter(i) for i in t[3].express())
        self.value = constructor(*params)

    def __repr__(self):
        return "%s" % (self.value)


class IdentifierAction:
    def __init__(self, t):
        logger.debug('IdentifierAction::__init__(%s)', t)
        self.steps = t[0][:-2:2]
        self.leaf = t[0][-1]

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
        else:
            # identifier is an attribute of a joined table
            query = query.join(*self.steps, aliased=True)
            cls = query._joinpoint['_joinpoint_entity']
        attr = getattr(cls, self.leaf)
        logger.debug('IdentifierToken for %s, %s evaluates to %s', cls,
                     self.leaf, attr)
        return (query, attr)

    def needs_join(self, env):
        return self.steps


class FilteredIdentifierAction:
    def __init__(self, t):
        logger.debug('FilteredIdentifierAction::__init__(%s)' % t)
        self.steps = t[0][:-7:2]
        self.filter_attr = t[0][-6]
        self.filter_op = t[0][-5]
        self.filter_value = t[0][-4]
        self.leaf = t[0][-1]

        # cfr: SearchParser.binop
        # = == != <> < <= > >= not like contains has ilike icontains ihas is
        self.operation = {
            '=': lambda x, y: x == y,
            '==': lambda x, y: x == y,
            'is': lambda x, y: x == y,
            '!=': lambda x, y: x != y,
            '<>': lambda x, y: x != y,
            'not': lambda x, y: x != y,
            '<': lambda x, y: x < y,
            '<=': lambda x, y: x <= y,
            '>': lambda x, y: x > y,
            '>=': lambda x, y: x >= y,
            'like': lambda x, y: utils.ilike(x, '%s' % y),
            'contains': lambda x, y: utils.ilike(x, '%%%s%%' % y),
            'has': lambda x, y: utils.ilike(x, '%%%s%%' % y),
            'ilike': lambda x, y: utils.ilike(x, '%s' % y),
            'icontains': lambda x, y: utils.ilike(x, '%%%s%%' % y),
            'ihas': lambda x, y: utils.ilike(x, '%%%s%%' % y),
        }.get(self.filter_op)

    def __repr__(self):
        return "%s[%s%s%s].%s" % ('.'.join(self.steps), self.filter_attr,
                                  self.filter_op, self.filter_value, self.leaf)

    def evaluate(self, env):
        """return pair (query, attribute)"""
        query = env.session.query(env.domain)
        # identifier is an attribute of a joined table
        query = query.join(*self.steps, aliased=True)
        cls = query._joinpoint['_joinpoint_entity']
        attr = getattr(cls, self.filter_attr)
        clause = lambda x: self.operation(attr, x)
        logger.debug('filtering on %s(%s)' % (type(attr), attr))
        query = query.filter(clause(self.filter_value.express()))
        attr = getattr(cls, self.leaf)
        logger.debug('IdentifierToken for %s, %s evaluates to %s'
                     % (cls, self.leaf, attr))
        return (query, attr)

    def needs_join(self, env):
        return self.steps


class IdentExpression:
    def __init__(self, t):
        logger.debug('IdentExpression::__init__(%s)' % t)
        self.op = t[0][1]

        # cfr: SearchParser.binop
        # = == != <> < <= > >= not like contains has ilike icontains ihas is
        self.operation = {
            '=': lambda x, y: x == y,
            '==': lambda x, y: x == y,
            'is': lambda x, y: x == y,
            '!=': lambda x, y: x != y,
            '<>': lambda x, y: x != y,
            'not': lambda x, y: x != y,
            '<': lambda x, y: x < y,
            '<=': lambda x, y: x <= y,
            '>': lambda x, y: x > y,
            '>=': lambda x, y: x >= y,
            'like': lambda x, y: utils.ilike(x, '%s' % y),
            'contains': lambda x, y: utils.ilike(x, '%%%s%%' % y),
            'has': lambda x, y: utils.ilike(x, '%%%s%%' % y),
            'ilike': lambda x, y: utils.ilike(x, '%s' % y),
            'icontains': lambda x, y: utils.ilike(x, '%%%s%%' % y),
            'ihas': lambda x, y: utils.ilike(x, '%%%s%%' % y),
        }.get(self.op)
        self.operands = t[0][0::2]  # every second object is an operand

    def __repr__(self):
        return "(%s %s %s)" % (self.operands[0], self.op, self.operands[1])

    def evaluate(self, env):
        q, a = self.operands[0].evaluate(env)
        if self.operands[1].express() == set():
            # check against the empty set
            if self.op in ('is', '=', '=='):
                return q.filter(~a.any())
            elif self.op in ('not', '<>', '!='):
                return q.filter(a.any())
        clause = lambda x: self.operation(a, x)
        logger.debug('filtering on %s(%s)' % (type(a), a))
        return q.filter(clause(self.operands[1].express()))

    def needs_join(self, env):
        return [self.operands[0].needs_join(env)]


class ElementSetExpression(IdentExpression):
    # currently only implements `in`

    def evaluate(self, env):
        q, a = self.operands[0].evaluate(env)
        return q.filter(a.in_(self.operands[1].express()))


def get_datetime(value):
    from dateutil import parser
    from datetime import timezone
    try:
        # try parsing as iso8601 first
        result = parser.isoparse(value)
    except ValueError:
        from bauble import prefs
        result = parser.parse(
            value,
            dayfirst=prefs.prefs[prefs.parse_dayfirst_pref],
            yearfirst=prefs.prefs[prefs.parse_yearfirst_pref]
        )
    return result.astimezone(tz=timezone.utc)


class DateOnExpression(IdentExpression):
    # implements `on` for date matching

    def evaluate(self, env):
        query, attr = self.operands[0].evaluate(env)
        date_val = get_datetime(self.operands[1].express())
        from sqlalchemy import extract
        return query.filter(extract('day', attr) == date_val.day,
                            extract('month', attr) == date_val.month,
                            extract('year', attr) == date_val.year)


class AggregatedExpression(IdentExpression):
    """Select on value of aggregated function.

    this one looks like ident.binop.value, but the ident is an
    aggregating function, so that the query has to be altered
    differently: not filter, but group_by and having.
    """

    def __init__(self, t):
        super().__init__(t)
        logger.debug('AggregatedExpression::__init__(%s)' % t)

    def evaluate(self, env):
        # operands[0] is the function/identifier pair
        # operands[1] is the value against which to test
        # operation implements the clause
        q, a = self.operands[0].identifier.evaluate(env)
        from sqlalchemy.sql import func
        f = getattr(func, self.operands[0].function)
        clause = lambda x: self.operation(f(a), x)
        # group by main ID
        # apply having
        main_table = q.column_descriptions[0]['type']
        mta = getattr(main_table, 'id')
        logger.debug('filtering on %s(%s)' % (type(mta), mta))
        result = q.group_by(mta).having(clause(self.operands[1].express()))
        return result


class BetweenExpressionAction:
    def __init__(self, t):
        self.operands = t[0][0::2]  # every second object is an operand

    def __repr__(self):
        return "(BETWEEN %s %s %s)" % tuple(self.operands)

    def evaluate(self, env):
        q, a = self.operands[0].evaluate(env)
        clause_low = lambda low: low <= a
        clause_high = lambda high: a <= high
        return q.filter(and_(clause_low(self.operands[1].express()),
                             clause_high(self.operands[2].express())))

    def needs_join(self, env):
        return [self.operands[0].needs_join(env)]


class UnaryLogical:
    ## abstract base class. `name` is defined in derived classes
    def __init__(self, t):
        self.op, self.operand = t[0]

    def __repr__(self):
        return "%s %s" % (self.name, str(self.operand))

    def needs_join(self, env):
        return self.operand.needs_join(env)


class BinaryLogical:
    ## abstract base class. `name` is defined in derived classes
    def __init__(self, t):
        self.op = t[0][1]
        self.operands = t[0][0::2]  # every second object is an operand

    def __repr__(self):
        return "(%s %s %s)" % (self.operands[0], self.name, self.operands[1])

    def needs_join(self, env):
        return self.operands[0].needs_join(env) + \
            self.operands[1].needs_join(env)


class SearchAndAction(BinaryLogical):
    name = 'AND'

    def evaluate(self, env):
        result = self.operands[0].evaluate(env)
        for i in self.operands[1:]:
            result = result.intersect(i.evaluate(env))
        return result


class SearchOrAction(BinaryLogical):
    name = 'OR'

    def evaluate(self, env):
        result = self.operands[0].evaluate(env)
        for i in self.operands[1:]:
            result = result.union(i.evaluate(env))
        return result


class SearchNotAction(UnaryLogical):
    name = 'NOT'

    def evaluate(self, env):
        q = env.session.query(env.domain)
        for i in env.domains:
            q.join(*i)
        return q.except_(self.operand.evaluate(env))


class ParenthesisedQuery:
    def __init__(self, t):
        self.content = t[1]

    def __repr__(self):
        return "(%s)" % self.content.__repr__()

    def evaluate(self, env):
        return self.content.evaluate(env)

    def needs_join(self, env):
        return self.content.needs_join(env)


class QueryAction:
    def __init__(self, t):
        self.domain = t[0]
        self.filter = t[1][0]

    def __repr__(self):
        return "SELECT * FROM %s WHERE %s" % (self.domain, self.filter)

    def invoke(self, search_strategy):
        """update search_strategy object with statement results

        Queries can use more database specific features.  This also
        means that the same query might not work the same on different
        database types. For example, on a PostgreSQL database you can
        use ilike but this would raise an error on SQLite.
        """

        logger.debug('QueryAction:invoke - %s(%s) %s(%s)', type(self.domain),
                     self.domain, type(self.filter), self.filter)
        domain = self.domain
        check(domain in search_strategy._domains or
              domain in search_strategy._shorthand,
              'Unknown search domain: %s' % domain)
        self.domain = search_strategy._shorthand.get(domain, domain)
        self.domain = search_strategy._domains[domain][0]
        self.search_strategy = search_strategy

        result = set()
        if search_strategy._session is not None:
            self.domains = self.filter.needs_join(self)
            self.session = search_strategy._session
            records = self.filter.evaluate(self).all()
            result.update(records)

        if None in result:
            logger.warning('removing None from result set')
            result = set(i for i in result if i is not None)
        return result


class StatementAction:
    def __init__(self, t):
        self.content = t[0]
        self.invoke = self.content.invoke

    def __repr__(self):
        return repr(self.content)


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
        result = None
        if self.species_epithet:
            logger.debug('binomial search sp: %s, gen: %s',
                         self.species_epithet, self.genus_epithet)
            result = (search_strategy._session.query(Species)
                      .filter(Species.sp.startswith(self.species_epithet))
                      .join(Genus)
                      .filter(Genus.genus.startswith(self.genus_epithet))
                      .all())
            result = set(result)
        else:
            logger.debug('cultivar search cv: %s, gen: %s',
                         self.cultivar_epithet, self.genus_epithet)
            result = (search_strategy._session.query(Species)
                      .filter(Species.cultivar_epithet
                              .startswith(self.cultivar_epithet))
                      .join(Genus)
                      .filter(Genus.genus.startswith(self.genus_epithet))
                      .all())
            result = set(result)
        if None in result:
            logger.warning('removing None from result set')
            result = set(i for i in result if i is not None)
        return result


class DomainExpressionAction:
    """created when the parser hits a domain_expression token.

    Searching using domain expressions is a little more magical than an
    explicit query. you give a domain, a binary_operator and a value,
    the domain expression will return all object with at least one
    property (as passed to add_meta) matching (according to the binop)
    the value.
    """

    def __init__(self, t):
        self.domain = t[0]
        self.cond = t[1]
        self.values = t[2]

    def __repr__(self):
        return "%s %s %s" % (self.domain, self.cond, self.values)

    def invoke(self, search_strategy):
        logger.debug('DomainExpressionAction:invoke')
        try:
            if self.domain in search_strategy._shorthand:
                self.domain = search_strategy._shorthand[self.domain]
            cls, properties = search_strategy._domains[self.domain]
        except KeyError:
            raise KeyError(_('Unknown search domain: %s') % self.domain)

        query = search_strategy._session.query(cls)

        # here is the place where to optionally filter out unrepresented
        # domain values. each domain class should define its own 'I have
        # accessions' filter. see issue #42

        result = set()

        # select all objects from the domain
        if self.values == '*':
            result.update(query.all())
            return result

        mapper = class_mapper(cls)

        if self.cond in ('like', 'ilike'):
            def condition(col):
                return lambda val: utils.ilike(mapper.c[col], '%s' % val)
        elif self.cond in ('contains', 'icontains', 'has', 'ihas'):
            def condition(col):
                return lambda val: utils.ilike(mapper.c[col], '%%%s%%' % val)
        elif self.cond == '=':
            def condition(col):
                return lambda val: mapper.c[col] == utils.nstr(val)
        else:
            def condition(col):
                return mapper.c[col].op(self.cond)

        for col in properties:
            ors = or_(*[condition(col)(i) for i in self.values.express()])
            result.update(query.filter(ors).all())

        if None in result:
            logger.warning('removing None from result set')
            result = set(i for i in result if i is not None)
        return result


class AggregatingAction:

    def __init__(self, t):
        logger.debug("AggregatingAction::__init__(%s)" % t)
        self.function = t[0]
        self.identifier = t[2]

    def __repr__(self):
        return "(%s %s)" % (self.function, self.identifier)

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
        if any(len(str(i)) < 4 for i in self.values):
            logger.debug('contains single letter')
            msg = _('The search string provided contains no specific query '
                    'and will search against all fields in all tables.  It '
                    'also contains a single letter.\n\n<b>Is this what you '
                    'intended?</b>\n\n(Returning results from a query like '
                    'this could take a very long time.)')
            if not utils.yes_no_dialog(msg, yes_delay=1):
                logger.debug('user aborted')
                return []

        def like(table, col, val):
            return utils.ilike(table.c[col], ('%%%s%%' % val))

        result = set()
        for cls, columns in search_strategy._properties.items():
            column_cross_value = [(c, v) for c in columns
                                  for v in self.express()]

            table = class_mapper(cls)
            query = (search_strategy._session.query(cls)
                     .filter(or_(*[like(table, c, v) for c, v in
                                   column_cross_value])))
            result.update(query.all())

        def replace(i):
            try:
                replacement = i.replacement()
                logger.debug('replacing %s by %s in result set', i,
                             replacement)
                return replacement
            except AttributeError:
                return i
        result = set(replace(i) for i in result)
        logger.debug("result is now %s", result)
        if None in result:
            logger.warning('removing None from result set')
            result = set(i for i in result if i is not None)
        return result


wordStart, wordEnd = WordStart(), WordEnd()


class SearchParser:
    """The parser for bauble.search.MapperSearch"""

    date_value = Regex(
        r'\d{1,4}[/.-]{1}\d{1,2}[/.-]{1}\d{1,4}'
    ).setParseAction(DateToken)('date')
    numeric_value = Regex(
        r'[-]?\d+(\.\d*)?([eE]\d+)?'
    ).setParseAction(NumericToken)('number')
    unquoted_string = Word(alphanums + alphas8bit + '%.-_*;:')
    string_value = (
        quotedString.setParseAction(removeQuotes) | unquoted_string
    ).setParseAction(StringToken)('string')

    none_token = Literal('None').setParseAction(NoneToken)
    empty_token = Literal('Empty').setParseAction(EmptyToken)

    value_list = Forward()
    typed_value = (
        Literal("|") + unquoted_string + Literal("|") +
        value_list + Literal("|")
    ).setParseAction(TypedValueToken)

    value = (
        typed_value |
        date_value |
        WordStart('0123456789.-e') + numeric_value + WordEnd('0123456789.-e') |
        none_token |
        empty_token |
        string_value
    ).setParseAction(ValueToken)('value')

    value_list << Group(
        OneOrMore(value) ^ delimitedList(value)
    ).setParseAction(ValueListAction)('value_list')

    domain = Word(alphas, alphanums)
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
    ).setParseAction(DomainExpressionAction)('domain_expression')

    caps = srange("[A-Z]")
    lowers = caps.lower()
    binomial_name = (
        Word(caps, lowers) + (
            Word(lowers) | Word("'", caps + lowers + " ") + Literal("'") |
            Word("'", caps + lowers))
    ).setParseAction(BinomialNameAction)('binomial_name')

    AND_ = wordStart + (CaselessLiteral("AND") | Literal("&&")) + wordEnd
    OR_ = wordStart + (CaselessLiteral("OR") | Literal("||")) + wordEnd
    NOT_ = wordStart + (CaselessLiteral("NOT") | Literal('!')) + wordEnd
    BETWEEN_ = wordStart + CaselessLiteral("BETWEEN") + wordEnd

    aggregating_func = (Literal('sum') | Literal('min') | Literal('max') |
                        Literal('count'))

    query_expression = Forward()('filter')

    atomic_identifier = Word(alphas + '_', alphanums + '_')
    identifier = (
        Group(atomic_identifier + ZeroOrMore('.' + atomic_identifier) + '[' +
              atomic_identifier + binop + value + ']' + '.' +
              atomic_identifier).setParseAction(FilteredIdentifierAction) |
        Group(atomic_identifier + ZeroOrMore('.' + atomic_identifier)
              ).setParseAction(IdentifierAction))

    aggregated = (aggregating_func + Literal('(') + identifier + Literal(')')
                  ).setParseAction(AggregatingAction)
    ident_expression = (Group(identifier + binop + value
                              ).setParseAction(IdentExpression) |
                        Group(identifier + binop_set + value_list
                              ).setParseAction(ElementSetExpression) |
                        Group(identifier + binop_date + date_value
                              ).setParseAction(DateOnExpression) |
                        Group(aggregated + binop + value
                              ).setParseAction(AggregatedExpression) |
                        (Literal('(') + query_expression + Literal(')')
                         ).setParseAction(ParenthesisedQuery))
    between_expression = Group(
        identifier + BETWEEN_ + value + AND_ + value
    ).setParseAction(BetweenExpressionAction)
    query_expression << infixNotation(
        (ident_expression | between_expression),
        [(NOT_, 1, opAssoc.RIGHT, SearchNotAction),
         (AND_, 2, opAssoc.LEFT, SearchAndAction),
         (OR_, 2, opAssoc.LEFT, SearchOrAction)])
    query = (domain + Keyword('where', caseless=True).suppress() +
             Group(query_expression) + stringEnd).setParseAction(QueryAction)

    statement = (query('query') |
                 domain_expression('domain') |
                 binomial_name('binomial') |
                 value_list('value_list')
                 ).setParseAction(StatementAction)('statement')

    def parse_string(self, text):
        """request pyparsing object to parse text

        `text` can be either a query, or a domain expression, or a list of
        values. the `self.statement` pyparsing object parses the input text
        and return a pyparsing.ParseResults object that represents the input
        """

        return self.statement.parseString(text)


class SearchStrategy:
    """interface for adding search strategies to a view."""

    def search(self, text, session=None):
        """
        :param text: the search string
        :param session: the session to use for the search

        Return an iterator that iterates over mapped classes retrieved
        from the search.
        """
        # NOTE this logger is used in various tests
        logger.debug('SearchStrategy "%s" (%s)', text, self.__class__.__name__)


result_cache = {}
"""Cache of search strategy results, can use instead of running the search
repeatedly. MapperSearch results should be available first."""


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
    # clear the cache
    result_cache.clear()
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

    _domains = {}
    _shorthand = {}
    _properties = {}

    def __init__(self):
        super().__init__()
        self._results = set()
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
            self._domains[domain[0]] = cls, properties
            for dom in domain[1:]:
                self._shorthand[dom] = domain[0]
        else:
            self._domains[domain] = cls, properties
        self._properties[cls] = properties

    @classmethod
    def get_domain_classes(cls):
        domains = {}
        for domain, item in cls._domains.items():
            domains.setdefault(domain, item[0])
        return domains

    def search(self, text, session=None):
        """Returns a set() of database hits for the text search string.

        If session=None then the session should be closed after the results
        have been processed or it is possible that some database backends
        could cause deadlocks.
        """
        super().search(text, session)
        self._session = session

        self._results.clear()
        statement = self.parser.parse_string(text).statement
        logger.debug("statement : %s(%s)", type(statement), statement)
        self._results.update(statement.invoke(self))
        logger.debug('search returns %s(%s)', type(self._results).__name__,
                     self._results)

        # these _results get filled in when the parse actions are called
        return self._results


# list of search strategies to be tried on each search string
_search_strategies = {'MapperSearch': MapperSearch()}


def add_strategy(strategy):
    logger.debug('adding strategy: %s', strategy.__name__)
    obj = strategy()
    _search_strategies[obj.__class__.__name__] = obj


def get_strategy(name):
    return _search_strategies.get(name, None)


class SchemaMenu(Gtk.Menu):
    """
    SchemaMenu

    :param mapper:
    :param activate_cb:
    :param column_filter:
    :param relation_filter:
    :param private: if True include private fields (starting with underscore)
    :param selectable_relations: if True include relations as selectable items
    """

    def __init__(self,
                 mapper,
                 activate_cb=None,
                 column_filter=lambda p: True,
                 relation_filter=lambda p: True,
                 private=False,
                 selectable_relations=False):
        super().__init__()
        self.activate_cb = activate_cb
        self.private = private
        self.relation_filter = relation_filter
        self.column_filter = column_filter
        self.selectable_relations = selectable_relations
        for item in self._get_prop_menuitems(mapper):
            self.append(item)
        self.show_all()

    def on_activate(self, menuitem, prop):
        """
        Call when menu items that hold column properties are activated.
        """
        path = []
        path = [menuitem.get_child().props.label]
        menu = menuitem.get_parent()
        while menu is not None:
            menuitem = menu.props.attach_widget
            if not menuitem:
                break
            label = menuitem.get_child().props.label
            path.append(label)
            menu = menuitem.get_parent()
        full_path = '.'.join(reversed(path))
        if self.selectable_relations and hasattr(prop, '__table__'):
            # python 3.9 only  - not currently available in mingw packages
            # full_path = full_path.removesuffix(f'.{prop.__table__.key}')
            suffix = f'.{prop.__table__.key}'
            if full_path.endswith(suffix):
                full_path = full_path[:-len(suffix)]
        self.activate_cb(menuitem, full_path, prop)

    def on_select(self, menuitem, prop):
        """
        Called when menu items that have submenus are selected
        """
        submenu = menuitem.get_submenu()
        if len(submenu.get_children()) == 0:
            for item in self._get_prop_menuitems(prop.mapper):
                submenu.append(item)
        submenu.show_all()

    def _get_prop_menuitems(self, mapper):
        # Separate properties in column_properties and relation_properties

        column_properties = []
        relation_properties = []
        for prop in mapper.all_orm_descriptors:
            if isinstance(prop, hybrid_property):
                column_properties.append(prop)
            elif (isinstance(prop, InstrumentedAttribute) or
                  prop.key in [i.key for i in mapper.synonyms]):
                i = prop.property
                if isinstance(i, RelationshipProperty):
                    relation_properties.append(prop)
                elif isinstance(i, ColumnProperty):
                    column_properties.append(prop)

        def key(prop):
            key = prop.key if hasattr(prop, 'key') else prop.__name__
            return key

        column_properties = sorted(
            column_properties,
            key=lambda p: (key(p) != 'id', not key(p).endswith('_id'), key(p))
        )
        relation_properties = sorted(relation_properties, key=key)

        items = []

        # add the table name to the top of the submenu and allow it to be
        # selected (intended for export selection where you wish to include the
        # string representation of the table)
        if self.selectable_relations:
            item = Gtk.MenuItem(label=mapper.entity.__table__.key,
                                use_underline=False)
            item.connect('activate', self.on_activate, mapper.entity)
            items.append(item)
            items.append(Gtk.SeparatorMenuItem())

        for prop in column_properties:
            if not self.column_filter(prop):
                continue
            item = Gtk.MenuItem(label=key(prop), use_underline=False)
            if hasattr(prop, 'prop'):
                prop = prop.prop
            item.connect('activate', self.on_activate, prop)
            items.append(item)

        for prop in relation_properties:
            if not self.relation_filter(prop):
                continue
            item = Gtk.MenuItem(label=prop.key, use_underline=False)
            submenu = Gtk.Menu()
            item.set_submenu(submenu)
            item.connect('select', self.on_select, prop)
            items.append(item)

        return items


def parse_typed_value(value, proptype):
    """parse the input string and return the corresponding typed value

    handles boolean, integers, floats, datetime, None, Empty, and falls back to
    string.
    """
    if value in ['None', None]:
        value = NoneToken()
    elif value in ["'None'", '"None"']:
        # in case user really does want to use "None" as a string.
        value = repr(str(value[1:-1]))
    elif value == 'Empty':
        value = EmptyToken()
    elif isinstance(proptype, (bauble.btypes.DateTime, bauble.btypes.Date)):
        # btypes.DateTime/Date accepts string dates
        if not value.count('-') == 2 and not value.count('/') == 2:
            value = f'|datetime|{value}|'
    elif isinstance(proptype, bauble.btypes.Boolean):
        # btypes.Boolean accepts strings and 0, 1
        if value not in ['True', 'False', 1, 0]:
            value = f'|bool|{value}|'
    elif isinstance(proptype, Integer):
        value = ''.join([i for i in value if i in '-0123456789.'])
        value = str(int(value))
    elif isinstance(proptype, Float):
        value = ''.join([i for i in value if i in '-0123456789.'])
        value = str(float(value))
    elif value not in ['%', '_']:
        value = repr(str(value).strip())
    return value


class ExpressionRow:

    conditions = ['=', '!=', '<', '<=', '>', '>=', 'like', 'contains']

    def __init__(self, query_builder, remove_callback, row_number):
        self.proptype = None
        self.grid = query_builder.view.widgets.expressions_table
        self.presenter = query_builder
        self.menu_item_activated = False

        self.and_or_combo = None
        if row_number != 1:
            self.and_or_combo = Gtk.ComboBoxText()
            self.and_or_combo.append_text("and")
            self.and_or_combo.append_text("or")
            self.and_or_combo.set_active(0)
            self.grid.attach(self.and_or_combo, 0, row_number, 1, 1)

        self.prop_button = Gtk.Button(label=_('Choose a property…'))

        self.schema_menu = SchemaMenu(self.presenter.mapper,
                                      self.on_schema_menu_activated,
                                      self.column_filter)
        self.prop_button.connect('button-press-event',
                                 self.on_prop_button_clicked,
                                 self.schema_menu)
        self.grid.attach(self.prop_button, 1, row_number, 1, 1)

        self.cond_combo = Gtk.ComboBoxText()
        for condition in self.conditions:
            self.cond_combo.append_text(condition)
        self.cond_combo.set_active(0)
        self.grid.attach(self.cond_combo, 2, row_number, 1, 1)

        # by default we start with an entry but value_widget can
        # change depending on the type of the property chosen in the
        # schema menu, see self.on_schema_menu_activated
        self.value_widget = Gtk.Entry()
        self.value_widget.connect('changed', self.on_value_changed)
        self.grid.attach(self.value_widget, 3, row_number, 1, 1)

        if row_number != 1:
            self.remove_button = Gtk.Button.new_from_icon_name(
                'list-remove', Gtk.IconSize.BUTTON)
            self.remove_button.connect('clicked',
                                       lambda b: remove_callback(self))
            self.grid.attach(self.remove_button, 4, row_number, 1, 1)

    @staticmethod
    def on_prop_button_clicked(_button, event, menu):
        menu.popup(None, None, None, None, event.button, event.time)

    def on_value_changed(self, widget):
        """Call the QueryBuilder.validate() for this row.

        Sets the sensitivity of the Gtk.ResponseType.OK button on the
        QueryBuilder.
        """
        self.presenter.validate()

    def on_date_value_changed(self, widget, *args):
        """Loosely constrain text to numbers and datetime parts only"""
        val = widget.get_text()
        val = ''.join([i for i in val if i in ',/-.0123456789'])
        widget.set_text(val)
        self.on_value_changed(widget)

    def on_schema_menu_activated(self, _menuitem, path, prop):
        """Called when an item in the schema menu is activated"""
        self.prop_button.set_label(path)
        self.menu_item_activated = True
        top = self.grid.child_get_property(self.value_widget, 'top-attach')
        left = self.grid.child_get_property(self.value_widget, 'left-attach')
        self.grid.remove(self.value_widget)

        # change the widget depending on the type of the selected property
        try:
            self.proptype = prop.columns[0].type
        except AttributeError:
            self.proptype = None
        if isinstance(self.proptype, bauble.btypes.Enum):
            self.value_widget = Gtk.ComboBox()
            cell = Gtk.CellRendererText()
            self.value_widget.pack_start(cell, True)
            self.value_widget.add_attribute(cell, 'text', 1)
            model = Gtk.ListStore(str, str)
            if prop.columns[0].type.translations:
                trans = prop.columns[0].type.translations
                sorted_keys = [
                    i for i in trans.keys() if i is None
                ] + sorted(i for i in trans.keys() if i is not None)
                prop_values = [(k, trans[k]) for k in sorted_keys]
            else:
                values = prop.columns[0].type.values
                prop_values = [(v, v) for v in sorted(values)]
            for value, translation in prop_values:
                model.append([value, translation])
            self.value_widget.props.model = model
            self.value_widget.connect('changed', self.on_value_changed)

        elif isinstance(self.proptype, Integer):
            val_widgt_adjustment = Gtk.Adjustment(upper=1000000000000,
                                                  step_increment=1,
                                                  page_increment=10)
            self.value_widget = Gtk.SpinButton(adjustment=val_widgt_adjustment,
                                               numeric=True)
            self.value_widget.connect('changed', self.on_value_changed)

        elif isinstance(self.proptype, Float):
            val_widgt_adjustment = Gtk.Adjustment(upper=10000000,
                                                  lower=0.00000000001,
                                                  step_increment=0.1,
                                                  page_increment=1)
            self.value_widget = Gtk.SpinButton(adjustment=val_widgt_adjustment,
                                               digits=10,
                                               numeric=True)
            self.value_widget.connect('changed', self.on_value_changed)

        elif isinstance(self.proptype, bauble.btypes.Boolean):
            self.value_widget = Gtk.ComboBoxText()
            self.value_widget.append_text('False')
            self.value_widget.append_text('True')
            self.value_widget.connect('changed', self.on_value_changed)

        elif isinstance(self.proptype, (bauble.btypes.Date,
                                        bauble.btypes.DateTime)):
            self.value_widget = Gtk.Entry()
            self.cond_combo.append_text('on')
            self.value_widget.connect('changed', self.on_date_value_changed)
        elif (not isinstance(self.value_widget, Gtk.Entry) or
              isinstance(self.value_widget, Gtk.SpinButton)):
            self.value_widget = Gtk.Entry()
            self.value_widget.connect('changed', self.on_value_changed)

        self.grid.attach(self.value_widget, left, top, 1, 1)
        self.grid.show_all()
        self.presenter.validate()

    def column_filter(self, _prop):
        return True

    def relation_filter(self, _prop):
        return True

    def get_widgets(self):
        """Returns a tuple of the and_or_combo, prop_button, cond_combo,
        value_widget, and remove_button widgets.
        """
        return (
            i for i in (self.and_or_combo, self.prop_button, self.cond_combo,
                        self.value_widget, self.remove_button) if i)

    def get_expression(self):
        """Return the expression represented by this ExpressionRow.

        If the expression is not valid then return None.
        """

        if not self.menu_item_activated:
            return None

        value = ''
        if isinstance(self.value_widget, Gtk.ComboBoxText):
            value = self.value_widget.get_active_text()
        elif isinstance(self.value_widget, Gtk.ComboBox):
            model = self.value_widget.get_model()
            active_iter = self.value_widget.get_active_iter()
            if active_iter:
                value = model[active_iter][0]
        else:
            # assume it's a Gtk.Entry or other widget with a text property
            value = self.value_widget.get_text().strip()
        value = parse_typed_value(value, self.proptype)
        and_or = ''
        if self.and_or_combo:
            and_or = self.and_or_combo.get_active_text()
        field_name = self.prop_button.get_label()
        if value == EmptyToken():
            field_name = field_name.rsplit('.', 1)[0]
            value = repr(value)
        if isinstance(value, NoneToken):
            value = 'None'
        result = ' '.join([and_or, field_name,
                           self.cond_combo.get_active_text(),
                           value]).strip()
        return result


class QueryBuilder(GenericEditorPresenter):

    view_accept_buttons = ['cancel_button', 'confirm_button']
    default_size = None

    def __init__(self, view=None):
        super().__init__(self, view=view, refresh_view=False)

        self.expression_rows = []
        self.mapper = None
        self.domain = None
        self.table_row_count = 0
        self.domain_map = MapperSearch.get_domain_classes().copy()

        self.view.widgets.domain_combo.set_active(-1)

        table = self.view.widgets.expressions_table
        for child in table.get_children():
            table.remove(child)

        self.view.widgets.domain_liststore.clear()
        for key in sorted(self.domain_map.keys()):
            self.view.widgets.domain_liststore.append([key])
        self.view.widgets.add_clause_button.set_sensitive(False)
        self.view.widgets.confirm_button.set_sensitive(False)
        self.refresh_view()

    def on_domain_combo_changed(self, *args):
        """
        Change the search domain.  Resets the expression table and
        deletes all the expression rows.
        """
        try:
            index = self.view.widgets.domain_combo.get_active()
        except AttributeError:
            return
        if index == -1:
            return

        self.domain = self.view.widgets.domain_liststore[index][0]

        # remove all clauses, they became useless in new domain
        table = self.view.widgets.expressions_table
        for child in table.get_children():
            table.remove(child)
        del self.expression_rows[:]
        # initialize view at 1 clause, however invalid
        self.table_row_count = 0
        self.on_add_clause()
        self.view.get_window().resize(1, 1)
        self.view.widgets.expressions_table.show_all()
        # let user add more clauses
        self.view.widgets.add_clause_button.props.sensitive = True

    def validate(self):
        """Validate the search expression is a valid expression."""
        valid = False
        for row in self.expression_rows:
            value = None
            if isinstance(row.value_widget, Gtk.Entry):  # also spinbutton
                value = row.value_widget.get_text()
            elif isinstance(row.value_widget, Gtk.ComboBox):
                value = row.value_widget.get_active() >= 0

            if value and row.menu_item_activated:
                valid = True
            else:
                valid = False
                break

        self.view.widgets.confirm_button.props.sensitive = valid
        return valid

    def remove_expression_row(self, row):
        """Remove a row from the expressions table."""
        [i.destroy() for i in row.get_widgets()]
        self.table_row_count -= 1
        self.expression_rows.remove(row)
        self.view.get_window().resize(1, 1)

    def on_add_clause(self, *args):
        """Add a row to the expressions table."""
        domain = self.domain_map[self.domain]
        self.mapper = class_mapper(domain)
        self.table_row_count += 1
        row = ExpressionRow(self, self.remove_expression_row,
                            self.table_row_count)
        self.expression_rows.append(row)
        self.view.widgets.expressions_table.show_all()

    def start(self):
        if self.default_size is None:
            self.__class__.default_size = (self.view.widgets.main_dialog
                                           .get_size())
        else:
            self.view.widgets.main_dialog.resize(*self.default_size)
        return self.view.start()

    @property
    def valid_clauses(self):
        return [i.get_expression() for i in self.expression_rows if
                i.get_expression()]

    def get_query(self):
        """Return query expression string."""

        query = [self.domain, 'where'] + self.valid_clauses
        return ' '.join(query)

    def set_query(self, q):
        parsed = BuiltQuery(q)
        if not parsed.is_valid:
            logger.debug('cannot restore query, invalid')
            return

        # locate domain in list of valid domains
        try:
            index = sorted(self.domain_map.keys()).index(parsed.domain)
        except ValueError as e:
            logger.debug('cannot restore query, %s(%s)' % (type(e), e))
            return
        # and set the domain_combo correspondently
        self.view.widgets.domain_combo.set_active(index)

        # now scan all clauses, one ExpressionRow per clause
        for clause in parsed.clauses:
            if clause.value == 'None':
                clause.value = "'None'"
            elif clause.value == '<None>':
                clause.value = 'None'
            if clause.connector:
                self.on_add_clause()
            row = self.expression_rows[-1]
            if clause.connector:
                row.and_or_combo.set_active(
                    {'and': 0, 'or': 1}[clause.connector])

            # the part about the value is a bit more complex: where the
            # clause.field leads to an enumerated property, on_add_clause
            # associates a gkt.ComboBox to it, otherwise a Gtk.Entry.
            # To set the value of a gkt.ComboBox we match one of its
            # items. To set the value of a gkt.Entry we need set_text.
            steps = clause.field.split('.')
            cls = self.domain_map[parsed.domain]
            mapper = class_mapper(cls)
            try:
                for target in steps[:-1]:
                    mapper = mapper.get_property(target).mapper
                prop = mapper.get_property(steps[-1])
            except Exception as e:
                logger.debug('cannot restore query details, %s(%s)',
                             type(e).__name__, e)
                return
            conditions = row.conditions.copy()
            if hasattr(prop, 'columns') and isinstance(
                prop.columns[0].type,
                    (bauble.btypes.Date, bauble.btypes.DateTime)
            ):
                row.cond_combo.append_text('on')
                conditions.append('on')
            row.on_schema_menu_activated(None, clause.field, prop)
            if isinstance(row.value_widget, Gtk.Entry):  # also spinbutton
                row.value_widget.set_text(clause.value)
            elif isinstance(row.value_widget, Gtk.ComboBox):
                for item in row.value_widget.props.model:
                    val = clause.value if clause.value != 'None' else None
                    if item[0] == val:
                        row.value_widget.set_active_iter(item.iter)
                        break
            row.cond_combo.set_active(conditions.index(clause.operator))
