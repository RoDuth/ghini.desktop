#!/usr/bin/env python3

import sys

FILE = sys.argv[1]

print(FILE)

INSERT = """
import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa
"""

COMPLETE = """
import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk
"""

COMPLETE4 = """
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk
"""

COMPLETE8 = """
        import gi
        gi.require_version("Gtk", "3.0")
        from gi.repository import Gtk
"""

INCOMPLETE = "from gi.repository import Gtk"
INCOMPLETE4 = "\n    from gi.repository import Gtk"
INCOMPLETE8 = "\n        from gi.repository import Gtk"

with open(FILE, 'r+') as f:
    contents = f.read()
    if INCOMPLETE in contents and not any(i in contents for i in [COMPLETE,
                                                                  COMPLETE4,
                                                                  COMPLETE8]):
        if INCOMPLETE8 in contents:
            new = contents.replace(INCOMPLETE8, COMPLETE8)
        elif INCOMPLETE4 in contents:
            new = contents.replace(INCOMPLETE4, COMPLETE4)
        elif INCOMPLETE in contents:
            new = contents.replace(INCOMPLETE, INSERT)
        f.seek(0)
        f.write(new)
        f.truncate()
