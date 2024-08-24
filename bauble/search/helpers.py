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
Search helpers
"""
import typing

from pyparsing import FollowedBy
from pyparsing import Forward
from pyparsing import Group
from pyparsing import OneOrMore
from pyparsing import OpAssoc
from pyparsing import Opt
from pyparsing import ParseAction
from pyparsing import ParserElement

InfixNotationOperatorSpec = tuple[ParserElement, OpAssoc, ParseAction]


def infix_notation(
    base_expr: ParserElement,
    op_list: list[InfixNotationOperatorSpec],
) -> ParserElement:
    """Simplified version of pyparsing's infix_notation helper, trimmed down
    and adjusted to support one specific use case.

    Aside from being limited to one specific use case, the main difference to
    the original is this version does not generate is own parentisised clause
    as that is dealt with in `parenthesised_clause` (which has its own parse
    action) and just provided here has part of the op_list.
    """

    ret = Forward()

    for oper_def in op_list:
        op_expr, right_left_assoc, parse_action = oper_def
        term_name = f"{op_expr} term"

        this_expr: ParserElement = Forward().set_name(term_name)
        this_expr = typing.cast(Forward, this_expr)
        if right_left_assoc is OpAssoc.LEFT:
            # arity 2
            match_expr = FollowedBy(base_expr + op_expr + base_expr) + Group(
                base_expr + OneOrMore(op_expr + base_expr)
            )
        elif right_left_assoc is OpAssoc.RIGHT:
            # arity 1
            op_expr = Opt(op_expr)
            match_expr = FollowedBy(op_expr.expr + this_expr) + Group(
                op_expr + this_expr
            )
        match_expr.set_parse_action(parse_action)
        this_expr <<= (match_expr | base_expr).set_name(term_name)
        base_expr = this_expr

    ret <<= base_expr

    return ret
