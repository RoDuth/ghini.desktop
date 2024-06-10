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
Provides the `search` function.

This function is the main entry point to running a search.

The `search.search` function will try each registered strategy in turn for a
given query string, collate the results from calling these queries and return a
list of database objects.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

from sqlalchemy.orm import Query
from sqlalchemy.orm import Session

from bauble import prefs

from .strategies import get_strategies

result_cache: dict[str, list[Query]] = {}
"""Cache of search strategy results, can use instead of running the search
repeatedly. Results should be available in the same order that the search
strategies where added to `strategies._search_strategies`."""


def search(text: str, session: Session) -> list:
    """Given a query string run the appropriate SearchStrategy(s) and return
    the collated results as a list.
    """
    text = text.strip()  # belt and braces
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
