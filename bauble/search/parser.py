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
Search parser

MapperSearch query syntax parser described with pyparsing.  Portions can be
imported and used by other search strategies.

BNF:
query ::= domain 'WHERE' query_expression
domain ::= 'family'
         | 'genus'
         | 'species'
         | 'accession'
         | 'plant'
         | 'location'
         | 'vernacular_name'
         | 'collection'
         | 'geography'
         | 'source_detail'
         | 'tag'
         ;
query_expression ::= and_term {or and_term}
and_term ::= not_term {and not_term}
not_term ::= not not_term | base_expression
or ::= 'OR' | '||'
and ::= 'AND' | '&&'
not ::= 'NOT' | '!'
base_expression ::= binary_expression
                  | in_set_expression
                  | on_date_expression
                  | function_expression
                  | parenthesised_expression
                  | between_expression
                  ;
binary_expression ::= identifier binop value_token
in_set_expression ::= identifier 'IN' value_list_token
on_date_expression ::= identifier 'ON' date_value_token
function_expression ::= aggregating_function
                        '(' identifier ')'
                        binop
                        value_token
                        ;
parenthesised_expression ::= '(' query_expression ')'
between_expression ::= identifier 'BETWEEN' value_token and value_token
identifier ::= filtered_identifier | unfiltered_identifier
unfiltered_identifier ::= atomic_identifier {'.' atomic_identifier}
filtered_identifier ::= unfiltered_identifier
                        '[' atomic_identifier binop value_token ']'
                        '.'
                        atomic_identifier
                        ;
atomic_identifier ::= regex:('[_\\da-z]*')
binop ::= '=='
        | '='
        | '!='
        | '<>'
        | '<='
        | '<'
        | '>='
        | '>'
        | 'NOT'
        | 'LIKE'
        | 'CONTAINS'
        | 'HAS'
        | 'ILIKE'
        | 'ICONTAINS'
        | 'IHAS'
        | 'IS'
        ;
value_token ::= date_str_token
              | numeric_token
              | 'None'
              | 'Empty'
              | string_token
              ;
value_list_token ::= value_token {[','] value_token}
date_value_token ::= date_str_token | numeric_token | string_token
date_str_token ::= regex:('\\d{1,4}[/.-]{1}\\d{1,2}[/.-]{1}\\d{1,4}')
numeric_token ::= regex:('[-]?\\d+(\\.\\d*)?([eE]\\d+)?')
string_token ::= unquoted_string | quoted_string
quoted_string ::= regex:('([\'"])(.*?)\\1')
unquoted_string ::= regex:('\\S*')
aggregating_function ::= 'SUM' | 'MIN' | 'MAX' | 'COUNT'
"""

from typing import cast

from pyparsing import CaselessKeyword
from pyparsing import Forward
from pyparsing import Group
from pyparsing import Keyword
from pyparsing import Literal
from pyparsing import OneOrMore
from pyparsing import OpAssoc
from pyparsing import ParserElement
from pyparsing import ParseResults
from pyparsing import Regex
from pyparsing import Word
from pyparsing import ZeroOrMore
from pyparsing import alphanums
from pyparsing import alphas
from pyparsing import alphas8bit
from pyparsing import delimited_list
from pyparsing import infix_notation
from pyparsing import one_of
from pyparsing import quoted_string
from pyparsing import remove_quotes
from pyparsing import string_end

from .expressions import AggregatedExpression
from .expressions import BetweenExpression
from .expressions import DateOnExpression
from .expressions import ElementSetExpression
from .expressions import IdentExpression
from .expressions import ParenthesisedExpression
from .expressions import SearchAndExpression
from .expressions import SearchNotExpression
from .expressions import SearchOrExpression
from .identifiers import AggregatingAction
from .identifiers import FilteredIdentifierAction
from .identifiers import IdentifierAction
from .query_actions import ExpressionQueryAction
from .tokens import EmptyToken
from .tokens import NoneToken
from .tokens import NumericToken
from .tokens import StringToken
from .tokens import ValueListToken
from .tokens import ValueToken

ParserElement.enable_packrat()

date_str_token = (
    Regex(r"\d{1,4}[/.-]{1}\d{1,2}[/.-]{1}\d{1,4}")
    .set_parse_action(StringToken)
    .set_name("date string")
)

numeric_token = (
    Regex(r"[-]?\d+(\.\d*)?([eE]\d+)?")
    .set_parse_action(NumericToken)
    .set_name("numeric value")
)

unquoted_string = Word(alphanums + alphas8bit + "%.-_*;:").set_name(
    "unquoted string"
)

quoted_string.set_parse_action(remove_quotes).set_name("quoted string")

string_token = (
    (quoted_string | unquoted_string)
    .set_parse_action(StringToken)
    .set_name("string value")
)

none_token = Literal("None").set_parse_action(NoneToken)

empty_token = Literal("Empty").set_parse_action(EmptyToken)

value_token = (
    (date_str_token | numeric_token | none_token | empty_token | string_token)
    .set_parse_action(ValueToken)
    .set_name("value")("value")
)

date_value_token = (
    (date_str_token | numeric_token | string_token)
    .set_parse_action(ValueToken)
    .set_name("date value")("value")
)

value_list_token = (
    Group(
        OneOrMore(value_token)
        ^ delimited_list(value_token).set_name("delimited list")
    )
    .set_parse_action(ValueListToken)
    .set_name("value list")("value_list")
)

# defined after plugins have all initialised
domain = cast(Forward, Forward().set_name("domain"))

binop = one_of(
    "= == != <> < <= > >= NOT LIKE CONTAINS HAS ILIKE ICONTAINS IHAS IS",
    caseless=True,
).set_name("binary operator")

binop_set = CaselessKeyword("IN")

binop_date = CaselessKeyword("ON")

and_ = (CaselessKeyword("AND") | Keyword("&&")).set_name("and")

or_ = (CaselessKeyword("OR") | Keyword("||")).set_name("or")

not_ = (CaselessKeyword("NOT") | Keyword("!")).set_name("not")

aggregating_function = (
    CaselessKeyword("sum")
    | CaselessKeyword("min")
    | CaselessKeyword("max")
    | CaselessKeyword("count")
).set_name("aggregating function")

atomic_identifier = Word(alphas + "_", alphanums + "_").set_name(
    "atomic identifier"
)

unfiltered_identifier = (
    Group(atomic_identifier + ZeroOrMore("." + atomic_identifier))
    .set_parse_action(IdentifierAction)
    .set_name("unfiltered identifier")
)

filtered_identifier = (
    Group(
        unfiltered_identifier
        + "["
        + atomic_identifier
        + binop
        + value_token
        + "]"
        + "."
        + atomic_identifier
    )
    .set_parse_action(FilteredIdentifierAction)
    .set_name("filtered identifier")
)

identifier = (filtered_identifier | unfiltered_identifier).set_name(
    "identifier"
)

function_call = (
    (aggregating_function + Literal("(") + identifier + Literal(")"))
    .set_parse_action(AggregatingAction)
    .set_name("function call")
)

query_expression = cast(Forward, Forward().set_name("query expression"))

binary_expression = (
    Group(identifier + binop + value_token)
    .set_parse_action(IdentExpression)
    .set_name("binary expression")
)

in_set_expression = (
    Group(identifier + binop_set + value_list_token)
    .set_parse_action(ElementSetExpression)
    .set_name("in set expression")
)

on_date_expression = (
    Group(identifier + binop_date + date_value_token)
    .set_parse_action(DateOnExpression)
    .set_name("on date expression")
)

function_expression = (
    Group(function_call + binop + value_token)
    .set_parse_action(AggregatedExpression)
    .set_name("function expression")
)

parenthesised_expression = (
    (Literal("(") + query_expression + Literal(")"))
    .set_parse_action(ParenthesisedExpression)
    .set_name("parenthesised expression")
)

between_expression = (
    Group(
        identifier
        + CaselessKeyword("BETWEEN")
        + value_token
        + and_
        + value_token
    )
    .set_parse_action(BetweenExpression)
    .set_name("between expression")
)

base_expression = (
    Group(
        binary_expression
        | in_set_expression
        | on_date_expression
        | function_expression
        | parenthesised_expression
        | between_expression
    )
    .set_parse_action(lambda tokens: tokens[0])
    .set_name("base expression")
)

query_expression <<= infix_notation(
    base_expression,
    [
        (not_, 1, OpAssoc.RIGHT, SearchNotExpression),
        (and_, 2, OpAssoc.LEFT, SearchAndExpression),
        (or_, 2, OpAssoc.LEFT, SearchOrExpression),
    ],
).set_name("query expression")

query = (
    (
        domain
        + CaselessKeyword("WHERE").suppress()
        + Group(query_expression).set_parse_action(lambda tokens: tokens[0])
        + string_end
    )
    .set_parse_action(ExpressionQueryAction)
    .set_name("query")("query")
)


def parse_string(text: str) -> ParseResults:
    """Request pyparsing object to parse text

    pyparsing object parses the input text and returns a pyparsing.ParseResults
    object that represents the input.
    """
    return query.parse_string(text)


def update_domains() -> None:
    """After all plugins are initialised update the domain names.

    Called from `bauble.pluginmgr.init`
    """
    from .strategies import MapperSearch

    domain_values = " ".join(MapperSearch.get_domain_classes().keys())
    global domain  # pylint: disable=global-statement
    domain <<= one_of(domain_values.strip()).set_name("domain")
