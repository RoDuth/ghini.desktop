#!/usr/bin/env python
"""
Scrips to generate railroad diagrams for all version of the search dialect.
"""

import os
from tempfile import mkstemp

from sqlalchemy.engine import make_url

from bauble import db
from bauble import pluginmgr
from bauble import prefs
from bauble.plugins.plants.species import BinomialSearch
from bauble.search import parser
from bauble.search.query_builder import BuiltQuery
from bauble.search.strategies import DomainSearch
from bauble.search.strategies import ValueListSearch


def main() -> None:
    uri = make_url("sqlite:///:memory:")
    db.open_conn(
        uri,
        verify=False,
    )
    handle, temp = mkstemp(suffix=".cfg", text=True)
    prefs.default_prefs_file = temp
    # pylint: disable=protected-access
    prefs.prefs = prefs._prefs(filename=temp)
    prefs.prefs.init()
    pluginmgr.load()
    db.create(import_defaults=False)
    pluginmgr.install("all", False)
    pluginmgr.init()

    parser.statement.create_diagram("mapper_search_railroad.html")
    DomainSearch.update_domains()
    DomainSearch.statement.create_diagram("domain_search_railroad.html")
    ValueListSearch.statement.create_diagram("value_list_search_railroad.html")
    BinomialSearch.statement.create_diagram("binomial_search_railroad.html")
    BuiltQuery.query.create_diagram("query_builder_railroad.html")

    os.close(handle)
    os.remove(temp)

    if db.engine:
        db.engine.dispose()


if __name__ == "__main__":
    main()
