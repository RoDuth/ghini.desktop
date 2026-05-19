# Copyright 2008-2010 Brett Adams
# Copyright 2015-2017 Mario Frasca <mario@anche.no>.
# Copyright 2020-2026 Ross Demuth <rossdemuth123@gmail.com>
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
#
"""
Garden search strategies and associated
"""

import logging

logger = logging.getLogger(__name__)

from collections.abc import Callable
from functools import lru_cache

from pyparsing import CaselessKeyword
from pyparsing import DelimitedList
from pyparsing import Keyword
from pyparsing import Literal
from pyparsing import OneOrMore
from pyparsing import ParseException
from pyparsing import Word
from pyparsing import one_of
from pyparsing import printables
from pyparsing import quoted_string
from pyparsing import remove_quotes
from pyparsing import string_end
from sqlalchemy import String
from sqlalchemy import and_
from sqlalchemy import not_
from sqlalchemy import or_
from sqlalchemy import tuple_
from sqlalchemy.orm import Query
from sqlalchemy.orm import Session
from sqlalchemy.sql import column
from sqlalchemy.sql import exists
from sqlalchemy.sql import values

from bauble import db
from bauble import utils
from bauble.search.strategies import SearchStrategy
from bauble.search.strategies import UseStrategy

from .accession import Accession
from .plant import Plant


def star_query(session: Session, _vals: list[str]) -> Query:
    logger.debug('"star" PlantSearch, returning all plants')
    return session.query(Plant)


def split_code(val: str) -> list[str]:

    delimiter = Plant.get_delimiter()

    if delimiter not in val:
        logger.debug("delimiter not found, can't split the code")
        raise ValueError(
            f"'{delimiter}' delimeter not found in text.  You must provide "
            f"the full 'ACCESSION{delimiter}PLANT' code",
        )

    return val.rsplit(delimiter, 1)


def equal_query(session: Session, vals: list[str]) -> Query:
    val = vals[0]
    acc_code, plant_code = split_code(val)

    logger.debug(
        '"equals" PlantSearch accession: %s plant: %s',
        acc_code,
        plant_code,
    )
    return (
        session.query(Plant)
        .filter(Plant.code == plant_code)
        .join(Accession)
        .filter(Accession.code == acc_code)
    )


def not_equal_query(session: Session, vals: list[str]) -> Query:
    val = vals[0]
    acc_code, plant_code = split_code(val)

    logger.debug(
        '"not equals" PlantSearch accession: %s plant: "%s"',
        acc_code,
        plant_code,
    )
    return (
        session.query(Plant)
        .join(Accession)
        .filter(
            not_(
                and_(
                    Plant.code == plant_code,
                    Accession.code == acc_code,
                )
            )
        )
    )


def like_query(session: Session, vals: list[str]) -> Query:
    val = vals[0]
    try:
        acc_code, plant_code = split_code(val)
    except ValueError as e:
        logger.debug("%s(%s)", type(e).__name__, e)
        acc_code = val
        plant_code = "%"

    logger.debug(
        '"like" PlantSearch accession: %s plant: %s',
        acc_code,
        plant_code,
    )
    return (
        session.query(Plant)
        .join(Accession)
        .filter(
            and_(
                utils.ilike(Plant.code, plant_code),
                utils.ilike(Accession.code, acc_code),
            )
        )
    )


def contains_query(session: Session, vals: list[str]) -> Query:
    val = vals[0]
    oper = and_
    try:
        acc_code, plant_code = split_code(val)
    except ValueError as e:
        logger.debug("%s(%s)", type(e).__name__, e)
        acc_code = plant_code = val
        oper = or_

    logger.debug(
        '"contains" PlantSearch accession: %s plant: %s',
        acc_code,
        plant_code,
    )
    conditions = []

    if acc_code:
        conditions.append(utils.ilike(Accession.code, f"%%{acc_code}%%"))

    if plant_code:
        conditions.append(utils.ilike(Plant.code, f"%%{plant_code}%%"))

    return session.query(Plant).join(Accession).filter(oper(*conditions))


def in_query(session: Session, vals: list[str]) -> Query:
    val_list: list[tuple[str, str]] = []
    for val in vals:
        acc_code, plant_code = split_code(val)
        val_list.append((acc_code, plant_code))

    logger.debug('"in" PlantSearch val_list: %s', val_list)
    if db.engine and db.engine.name == "mssql":
        sql_vals = (
            values(column("acc_code", String), column("plt_code", String))
            .data(val_list)
            .alias("val")
        )
        return (
            session.query(Plant)
            .join(Accession)
            .filter(
                exists().where(
                    and_(
                        Accession.code == sql_vals.c.acc_code,
                        Plant.code == sql_vals.c.plt_code,
                    )
                )
            )
        )
    # sqlite, postgresql
    return (
        session.query(Plant)
        .join(Accession)
        .filter(tuple_(Accession.code, Plant.code).in_(val_list))
    )


queries: dict[str, Callable[[Session, list[str]], Query]] = {
    "*": star_query,
    "=": equal_query,
    "==": equal_query,
    "!=": not_equal_query,
    "<>": not_equal_query,
    "like": like_query,
    "contains": contains_query,
    "has": contains_query,
    "in": in_query,
}


class PlantSearch(SearchStrategy):
    """Supports searches of the form: `plant operator value`

    This strategy overrides DomainSearch as plants are slightly more complex to
    query.
    """

    domain = Keyword("planting") | Keyword("plant")
    operator = one_of("= == != <> like contains has")
    printable = printables.replace(",", "")
    value = quoted_string.set_parse_action(remove_quotes) | Word(printable)
    value_list = DelimitedList(value) ^ OneOrMore(value)
    equals = Literal("=")
    star_value = Literal("*")
    in_op = CaselessKeyword("in")
    domain_expression = (
        domain + equals + star_value + string_end
        | domain + operator + value + string_end
        | domain + in_op + value_list + string_end
    )

    @staticmethod
    @lru_cache(maxsize=8)
    def use(text: str) -> UseStrategy:
        # cache the result to avoid calling multiple times...
        try:
            PlantSearch.domain_expression.parse_string(text)
            logger.debug("reducing strategies to PlantSearch")
            return UseStrategy.ONLY
        except ParseException:
            pass
        return UseStrategy.EXCLUDE

    def search(self, text: str, session: Session) -> list[Query]:
        # pylint: disable=too-many-branches,too-many-locals,too-many-statements
        """domain search for plants, only returns a result if appropriate
        string is supplied.  Searches a combination of Accession.code,
        delimiter and Plant.code.
        """
        super().search(text, session)

        try:
            parsed = self.domain_expression.parse_string(text)
            operator = parsed[1]
            vals = parsed[2:]
        except ParseException as e:
            logger.debug("PlantSearch %s(%s)", type(e).__name__, e)
            return []

        if vals[0] == "*":
            if operator in ("!=", "<>"):
                return []
            return [queries["*"](session, vals)]

        query_func = queries.get(operator)

        if not query_func:
            logger.debug("PlantSearch no query for operator: %s", operator)
            return []

        return [query_func(session, vals)]
