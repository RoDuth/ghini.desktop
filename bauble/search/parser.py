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

Query syntax described in a pyparsing script.
"""

from pyparsing import CaselessLiteral
from pyparsing import Forward
from pyparsing import Group
from pyparsing import Keyword
from pyparsing import Literal
from pyparsing import OneOrMore
from pyparsing import OpAssoc
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

date_str = Regex(r"\d{1,4}[/.-]{1}\d{1,2}[/.-]{1}\d{1,4}").set_parse_action(
    StringToken
)
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

value_list = Group(OneOrMore(value) ^ delimited_list(value)).set_parse_action(
    ValueListToken
)("value_list")

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
    | Group(identifier + binop_date + value).set_parse_action(DateOnExpression)
    | Group(aggregated + binop + value).set_parse_action(AggregatedExpression)
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


def parse_string(text: str) -> ParseResults:
    """Request pyparsing object to parse text

    pyparsing object parses the input text and returns a pyparsing.ParseResults
    object that represents the input.
    """

    return query.parse_string(text)
