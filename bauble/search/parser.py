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
Search parser

MapperSearch query syntax parser described with pyparsing.  Portions can be
imported and used by other search strategies.

Supports complex searches queries, in its most basic form could be written as:
    `<domain> 'WHERE' <identifier> = <value>`

BNF:
note - 'Regex' used to approximate terminals

statement ::= domain 'WHERE' query_clause
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
query_clause ::= or_term
or_term ::= and_term {or and_term}
and_term ::= not_term {and not_term}
not_term ::= not not_term | base_clause
or ::= 'OR' | '||'
and ::= 'AND' | '&&'
not ::= 'NOT' | '!'
base_clause ::= binary_clause
              | in_set_clause
              | on_date_clause
              | function_clause
              | between_clause
              | parenthesised_clause
              ;
binary_clause ::= identifier binary_operator (value_token | subquery)
in_set_clause ::= identifier binary_in_operator (value_list_token | subquery)
on_date_clause ::= identifier 'ON' (date_value_token | subquery)
function_clause ::= function_call (function_in | function_binary)
function_in ::= binary_in_operator (value_list_token | subquery)
function_binary ::= binary_operator (value_token | subquery)
parenthesised_clause ::= '(' query_clause ')'
between_clause ::= identifier 'BETWEEN' value_token and value_token
function_call ::= function '(' ['DISTINCT'] (identifier | function_call) ')'
identifier ::= filtered_identifier | unfiltered_identifier
unfiltered_identifier ::= atomic_identifier {'.' atomic_identifier}
filtered_identifier ::= {unfiltered_identifier
                         '[' filter_clause {',' filter_clause} ']'
                         '.'}
                        unfiltered_identifier
                        ;
filter_clause ::= atomic_binary_clause | atomic_in_clause
atomic_binary_clause ::= atomic_identifier binary_operator value_token
atomic_in_clause ::= atomic_identifier binary_in_operator value_list_token
atomic_identifier ::= Regex('[_\\da-z]*')
binary_operator ::= '='
                  | '=='
                  | 'IS'
                  | '!='
                  | '<>'
                  | 'NOT'
                  | '<='
                  | '<'
                  | '>='
                  | '>'
                  | 'LIKE'
                  | 'CONTAINS'
                  | 'HAS'
                  ;
binary_in_operator ::= 'IN' | 'NOT IN'
value_token ::= date_str_token
              | numeric_token
              | 'None'
              | 'Empty'
              | string_token
              ;
value_list_token ::= value_token {[','] value_token}
date_value_token ::= date_str_token | numeric_token | string_token
date_str_token ::= Regex('\\d{1,4}[/.-]{1}\\d{1,2}[/.-]{1}\\d{1,4}')
numeric_token ::= Regex('[-]?\\d+(\\.\\d*)?([eE]\\d+)?')
string_token ::= unquoted_string | quoted_string
quoted_string ::= Regex('([\'"])(.*?)\\1')
unquoted_string ::= Regex('\\S*')
function ::= 'SUM' | 'MIN' | 'MAX' | 'COUNT' | 'LENGTH' | ... (DB dependant)
subquery ::= '(' (subquery_function_call | subquery_identifier)
             [where_statement] ['CORRELATE'] ')'
             ;
subquery_identifier ::= table '.' unfiltered_identifier
subquery_function_call ::= function '(' ['DISTINCT']
                           (subquery_identifier | subquery_function_call) ')'
                           ;
where_statement ::= 'WHERE' unfiltered_identifier (where_in | where_binary)
where_in ::= binary_in_operator value_list_token
where_binary ::= binary_operator value_token
table ::= 'family'
         | 'genus'
         | 'species'
         | 'accession'
         | 'plant'
         | ... (any table)
         ;
"""
from typing import cast

# from pyparsing import quoted_string
from pyparsing import CaselessKeyword
from pyparsing import Combine
from pyparsing import DelimitedList
from pyparsing import Forward
from pyparsing import Group
from pyparsing import Keyword
from pyparsing import Literal
from pyparsing import OneOrMore
from pyparsing import OpAssoc
from pyparsing import Opt
from pyparsing import ParserElement
from pyparsing import ParseResults
from pyparsing import Regex
from pyparsing import Word
from pyparsing import ZeroOrMore
from pyparsing import alphanums
from pyparsing import alphas
from pyparsing import alphas8bit
from pyparsing import one_of
from pyparsing import remove_quotes
from pyparsing import string_end

from .clauses import AndTerm
from .clauses import BetweenClause
from .clauses import BinaryClause
from .clauses import FunctionClause
from .clauses import NotTerm
from .clauses import OnDateClause
from .clauses import OrTerm
from .clauses import ParenthesisedClause
from .helpers import infix_notation
from .identifiers import FilteredIdentifier
from .identifiers import FunctionIdentifier
from .identifiers import UnfilteredIdentifier
from .statements import MapperStatement
from .subquery import CorrelateAction
from .subquery import SubQueryFuncIdentifier
from .subquery import SubQueryIdentifier
from .subquery import SubQueryValue
from .subquery import WhereAction
from .subquery import get_table_model
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
    .set_name("date string token")
)

numeric_token = (
    Regex(r"[-]?\d+(\.\d*)?([eE]\d+)?")
    .set_parse_action(NumericToken)
    .set_name("numeric token")
)

unquoted_string_token = Word(alphanums + alphas8bit + "%.-_*;:").set_name(
    "unquoted string token"
)

quoted_string = (
    (
        Combine(
            Regex(r'"(?:[^"\n\r\\]|(?:"")|(?:\\(?:[^x]|x[0-9a-fA-F]+)))*')
            + '"'
        ).set_name("double quoted string")
        | Combine(
            Regex(r"'(?:[^'\n\r\\]|(?:'')|(?:\\(?:[^x]|x[0-9a-fA-F]+)))*")
            + "'"
        ).set_name("single quoted string")
    )
    .set_parse_action(remove_quotes)
    .set_name("quoted string token")
)

string_token = (
    (quoted_string | unquoted_string_token)
    .set_parse_action(StringToken)
    .set_name("string token")
)

none_token = Keyword("None").set_parse_action(NoneToken)

empty_token = Keyword("Empty").set_parse_action(EmptyToken)

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
        ^ DelimitedList(value_token).set_name("delimited list")
    )
    .set_parse_action(ValueListToken)
    .set_name("value list")("value_list")
)

# defined after plugins have all initialised
domain = Forward()

binop = one_of(
    "= == IS != <> NOT < <= > >= LIKE CONTAINS HAS", caseless=True
).set_name("binary operator")

binop_set = (CaselessKeyword("IN") | CaselessKeyword("NOT IN")).set_name(
    "set operator"
)

binop_date = CaselessKeyword("ON")

and_ = (CaselessKeyword("AND") | Keyword("&&")).set_name("and")("and_")

or_ = (CaselessKeyword("OR") | Keyword("||")).set_name("or")("or_")

not_ = (CaselessKeyword("NOT") | Keyword("!")).set_name("not")("not_")

function = (Word(alphas + "_")).set_name("function")

atomic_identifier = Word(alphas + "_", alphanums + "_").set_name(
    "atomic identifier"
)

unfiltered_identifier = (
    (
        atomic_identifier
        + ZeroOrMore(
            Literal(".").suppress() + atomic_identifier
        ).leave_whitespace()
    )
    .set_parse_action(UnfilteredIdentifier)
    .set_name("unfiltered identifier")
)

atomic_binary_clause = Group(atomic_identifier + binop + value_token).set_name(
    "atomic binary clause"
)

atomic_in_clause = Group(
    atomic_identifier + binop_set + value_list_token
).set_name("atomic in clause")

filter_clause = (atomic_in_clause | atomic_binary_clause).set_name(
    "filter clause"
)

filtered_identifier = (
    (
        OneOrMore(
            Group(
                (
                    unfiltered_identifier
                    + Literal("[").suppress().leave_whitespace()
                )
                + Group(DelimitedList(filter_clause))
                + (
                    Literal("]").suppress() + Literal(".").suppress()
                ).leave_whitespace()
            )
        )
        + unfiltered_identifier.copy().leave_whitespace()
    )
    .set_parse_action(FilteredIdentifier)
    .set_name("filtered identifier")
)

identifier = (filtered_identifier | unfiltered_identifier).set_name(
    "identifier"
)

function_call = cast(Forward, Forward().set_name("function call"))

# An IdentifierAction is used as the parse action here as it only stores the
# function name and handles the identifier at this point.
function_call <<= (
    (
        (function + Literal("(").suppress().leave_whitespace())
        + Opt(CaselessKeyword("DISTINCT"))
        + (function_call | identifier)
        + Literal(")").suppress().leave_whitespace()
    )
    .set_parse_action(FunctionIdentifier)
    .set_name("function call")
)

table = (
    atomic_identifier.copy()
    .set_name("table")
    .set_parse_action(get_table_model)
)

subquery_identifier = (
    (table + Literal(".").suppress() + unfiltered_identifier)
    .set_parse_action(SubQueryIdentifier)
    .set_name("subquery identifier")
)

subquery_function_call = cast(
    Forward, Forward().set_name("subquery function call")
)

subquery_function_call <<= (
    (
        (function + Literal("(").suppress().leave_whitespace())
        + Opt(CaselessKeyword("DISTINCT"))
        + (subquery_function_call | subquery_identifier)
        + Literal(")").suppress().leave_whitespace()
    )
    .set_parse_action(SubQueryFuncIdentifier)
    .set_name("subquery function call")
)

where_clause = (
    (
        CaselessKeyword("WHERE").suppress()
        + unfiltered_identifier
        + ((binop_set + value_list_token) | (binop + value_token))
    )
    .set_parse_action(WhereAction)
    .set_name("where clause")
)

correlate = CaselessKeyword("CORRELATE").set_parse_action(CorrelateAction)

subquery_value = (
    (
        Literal("(").suppress()
        + (subquery_function_call | subquery_identifier)
        + Opt(where_clause)
        + Opt(correlate)
        + Literal(")").suppress()
    )
    .set_parse_action(SubQueryValue)
    .set_name("subquery")
)

binary_clause = (
    Group(identifier + binop + (subquery_value | value_token))
    .set_parse_action(BinaryClause)
    .set_name("binary clause")
)

in_set_clause = (
    Group(identifier + binop_set + (subquery_value | value_list_token))
    .set_parse_action(BinaryClause)
    .set_name("in set clause")
)

on_date_clause = (
    Group(identifier + binop_date + (subquery_value | date_value_token))
    .set_parse_action(OnDateClause)
    .set_name("on date clause")
)

function_clause = (
    Group(
        function_call
        + (
            binop_set + (subquery_value | value_list_token)
            | binop + (subquery_value | value_token)
        )
    )
    .set_parse_action(FunctionClause)
    .set_name("function clause")
)

between_clause = (
    Group(
        identifier
        + CaselessKeyword("BETWEEN")
        + value_token
        + and_
        + value_token
    )
    .set_parse_action(BetweenClause)
    .set_name("between clause")
)

base_clause = Forward()

query_clause = infix_notation(
    base_clause,
    [
        (not_, OpAssoc.RIGHT, NotTerm),
        (and_, OpAssoc.LEFT, AndTerm),
        (or_, OpAssoc.LEFT, OrTerm),
    ],
).set_name("query clause")

parenthesised_clause = (
    (Literal("(").suppress() + query_clause + Literal(")").suppress())
    .set_parse_action(ParenthesisedClause)
    .set_name("parenthesised clause")
)

# delaying defining base_clause ensures railroad diagrams separates it.
base_clause <<= (
    in_set_clause
    | on_date_clause
    | function_clause
    | between_clause
    | binary_clause
    | parenthesised_clause
).set_name("base clause")

statement = (
    (domain + CaselessKeyword("WHERE").suppress() + query_clause + string_end)
    .set_parse_action(MapperStatement)
    .set_name("statement")("query")
)


def parse_string(text: str) -> ParseResults:
    """Request pyparsing object to parse text

    pyparsing object parses the input text and returns a pyparsing.ParseResults
    object that represents the input.
    """
    return statement.parse_string(text)


def update_domains() -> None:
    """After all plugins are initialised update the domain names.

    Called from `bauble.pluginmgr.init`
    """
    from .strategies import MapperSearch

    domain_values = " ".join(MapperSearch.get_domain_classes().keys())
    global domain  # pylint: disable=global-statement
    domain <<= one_of(domain_values.strip()).set_name("domain")
