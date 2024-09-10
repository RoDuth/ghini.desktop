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
Search operations

Provides translations between our query syntax and SQLA's query syntax.
"""

import typing
from collections.abc import Callable

from sqlalchemy.orm import QueryableAttribute
from sqlalchemy.sql.elements import ColumnElement

from bauble import utils

Val: typing.TypeAlias = str | float | None | list


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


def in_(attr: QueryableAttribute, val: Val) -> ColumnElement:
    return attr.in_(val)


OPERATIONS: dict[str, Callable[[QueryableAttribute, Val], ColumnElement]] = {
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
    "in": in_,
}
"""
Dictionary of operations (as the lower case string) to the function that
generates the clause.

Useage: OPERATIONS.get(operation.lower()).
"""
