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
Search strategies

Search strategies are used to run a search.

The `search.search` function will try each strategy for a given query string,
collate the results from calling these queries and return a list of database
objects.

Each strategy should have its own reason to be called (e.g. a syntax that it
can process) and given a query string the `use` method should let the caller
know if it is an appropriate strategy (or the 'only' appropriate strategy) for
the supplied query.  If it is appropriate then calling its `search` method
should provide a list of valid SQLA queries.

The main common searches strategies are provided here, others exist in plugins.
"""

import logging

logger = logging.getLogger(__name__)

import typing
from abc import ABC
from abc import abstractmethod
from functools import lru_cache

from pyparsing import Forward
from pyparsing import Group
from pyparsing import Literal
from pyparsing import OneOrMore
from pyparsing import ParseException
from pyparsing import delimited_list
from pyparsing import one_of
from pyparsing import string_end
from sqlalchemy.orm import Query
from sqlalchemy.orm import Session

from bauble.db import Base
from bauble.error import check

from . import parser
from .query_actions import DomainQueryAction
from .query_actions import ValueListQueryAction


class SearchStrategy(ABC):
    """interface for adding search strategies to a view."""

    domains: dict[str, tuple[Base, list[str]]] = {}
    shorthand: dict[str, str] = {}
    properties: dict[Base, list[str]] = {}
    # placed here for simple search convenience.
    completion_funcs: dict[str, typing.Callable] = {}

    excludes_value_list_search = True
    """If this search strategy is included do not include ValueListSearch, (the
    fall back strategy when no others are appropriate)"""

    def __init__(self):
        self.session = None

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
        # used in tests
        logger.debug('SearchStrategy "%s" (%s)', text, self.__class__.__name__)
        return []


class MapperSearch(SearchStrategy):
    """Supports a query of the form: `<domain> <where> <expression>`

    The main search strategy, supports full query syntax:

    e.g.: `location where code = LOC1`
    """

    @staticmethod
    def use(text: str) -> typing.Literal["include", "exclude", "only"]:
        atomised = text.split()
        if atomised[0] in MapperSearch.domains and atomised[1] == "where":
            return "include"
        return "exclude"

    def search(self, text: str, session: Session) -> list[Query]:
        """Returns list of queries for the text search string."""
        super().search(text, session)
        self.session = session
        result = parser.parse_string(text).query
        logger.debug("result : %s(%s)", type(result), result)
        queries = result.invoke(self)

        return queries


class DomainSearch(SearchStrategy):
    """Supports searches of the form: `<domain|shorthand> <operator> <value>`

    Resolves the domain and searches all specified columns as provided in
    `properties`.

    e.g.: `loc=LOC1`
    """

    value_token = parser.value_token
    value_list_token = parser.value_list_token
    domains_list: list[str] = []
    # updated on first call see update_domains
    domain = Forward()
    binop = parser.binop
    in_op = parser.binop_set

    star_value = Literal("*")
    domain_values = value_list_token.copy()
    domain_expression = (
        domain + binop + star_value + string_end
        | domain + binop + value_token + string_end
        | domain + in_op + domain_values + string_end
    ).set_parse_action(DomainQueryAction)("query")

    @staticmethod
    @lru_cache(maxsize=8)
    def use(text: str) -> typing.Literal["include", "exclude", "only"]:
        # cache the result to avoid calling multiple times...
        DomainSearch.update_domains()
        try:
            DomainSearch.domain_expression.parse_string(text)
            logger.debug("including DomainSearch in strategies")
            return "include"
        except ParseException:
            pass
        return "exclude"

    @classmethod
    def update_domains(cls) -> None:
        """Update the domain to include all domain names and shorthands
        accepted by DomainSearch
        """
        if not cls.domains_list:
            cls.domains_list = list(cls.domains.keys())
            cls.domains_list += list(cls.shorthand.keys())
            cls.domain <<= one_of(cls.domains_list)
            logger.debug("updated domains list to %s", cls.domains_list)

    def search(self, text: str, session: Session) -> list[Query]:
        """Returns list of queries for the text search string."""
        super().search(text, session)
        self.session = session
        result = self.domain_expression.parse_string(text).query
        logger.debug("result : %s(%s)", type(result), result)
        query = result.invoke(self)

        return query


class ValueListSearch(SearchStrategy):
    """Supports searches that are just a list of values.

    This is a fall back search that searches all domains against all columns
    (as provided in `properties`) that CONTAIN any strings in the list of
    provided values.

    Least desirable search as it is not specific and returns multiple queries
    which can take a while to run and may return a mixture of types.

    e.g.: `LOC1 LOC2 LOC3`
    """

    value_token = parser.value_token
    value_list = Group(
        OneOrMore(value_token) ^ delimited_list(value_token)
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
        # NOTE skip any other response
    logger.debug("filtered strategies %s", selected_strategies)
    return selected_strategies
