#!/usr/bin/env python

import os
from tempfile import mkstemp

from bauble import db
from bauble import pluginmgr
from bauble import prefs
from bauble.search.parser import query


def main():
    uri = "sqlite:///:memory:"
    db.open_conn(
        uri,
        verify=False,
    )
    handle, temp = mkstemp(suffix=".cfg", text=True)
    # reason not to use `from bauble.prefs import prefs`
    prefs.default_prefs_file = temp
    prefs.prefs = prefs._prefs(filename=temp)
    prefs.prefs.init()
    pluginmgr.load()
    db.create(import_defaults=False)
    pluginmgr.install("all", False, force=True)
    pluginmgr.init()
    query.create_diagram("mapper_search_railroad.html")
    os.close(handle)
    os.remove(temp)
    db.engine.dispose()


if __name__ == "__main__":
    main()
