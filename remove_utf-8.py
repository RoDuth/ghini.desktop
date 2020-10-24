#!/usr/bin/env python3

import sys

FILE = sys.argv[1]

print(FILE)

with open(FILE, 'r+') as f:
    contents = f.read()
    remove = '# -*- coding: utf-8 -*-\n'
    if contents.startswith(remove):
        new = contents[contents.startswith(remove) and len(remove):]
        remove = '#\n'
        new = new[new.startswith(remove) and len(remove):]
        f.seek(0)
        f.write(new)
        f.truncate()
