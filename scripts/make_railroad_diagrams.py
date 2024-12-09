#!/usr/bin/env python

import os
from tempfile import mkstemp

from bauble import db
from bauble import pluginmgr
from bauble import prefs
from bauble.plugins.plants.species import BinomialSearch
from bauble.query_builder import BuiltQuery
from bauble.search.parser import statement
from bauble.search.strategies import DomainSearch
from bauble.search.strategies import ValueListSearch


def main():
    uri = "sqlite:///:memory:"
    db.open_conn(
        uri,
        verify=False,
    )
    handle, temp = mkstemp(suffix=".cfg", text=True)
    # reason not to use `from bauble.prefs import prefs`
    prefs.default_prefs_file = temp
    # pylint: disable=protected-access
    prefs.prefs = prefs._prefs(filename=temp)
    prefs.prefs.init()
    pluginmgr.load()
    db.create(import_defaults=False)
    pluginmgr.install("all", False, force=True)
    pluginmgr.init()
    statement.create_diagram("mapper_search_railroad.html")
    DomainSearch.update_domains()
    DomainSearch.statement.create_diagram("domain_search_railroad.html")
    ValueListSearch.statement.create_diagram("value_list_search_railroad.html")
    BinomialSearch.statement.create_diagram("binomial_search_railroad.html")
    BuiltQuery.query.create_diagram("query_builder_railroad.html")
    os.close(handle)
    os.remove(temp)
    db.engine.dispose()


if __name__ == "__main__":
    main()
