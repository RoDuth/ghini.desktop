#!/usr/bin/env python
# pylint: disable=consider-using-f-string
# -*- coding: utf-8 -*-
#
# Copyright 2004-2010 Brett Adams <brett@bauble.io>
# Copyright 2015 Mario Frasca <mario@anche.no>.
# Copyright 2017-2021 Ross Demuth <rossdemuth123@gmail.com>
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
Replace the version string in the relevant files.
"""

import os
import re
import sys

usage = """Usage: %s [<version> | + | ++]
""" % os.path.basename(
    sys.argv[0]
)


# TODO use paths.root?
def root_of_clone():
    this_script = os.path.realpath(__file__)
    parts = this_script.split(os.path.sep)
    return os.path.sep + os.path.join(*parts[:-2])


def usage_and_exit(msg=None):
    print(usage, file=sys.stderr)
    if msg:
        print(msg, file=sys.stderr)
    sys.exit(1)


if len(sys.argv) != 2:
    usage_and_exit()
version = sys.argv[1]

# make sure that there is only one instance of version=some_version in a file.
# Place ":bump" somewhere in the comment on the same line
bump_tag = ":bump"

# should I just increment version as of bauble.version?
if version in ["+", "++", "+++"]:
    inc_patch = version == "+"
    inc_minor = version == "++"
    inc_major = version == "+++"
    rgx = re.compile(
        r"^version\s*=\s*(?:\'|\")(.*)\.(.*)\.(.*)(?:\'|\").*%s.*$" % bump_tag
    )

    matches = [
        rgx.match(line).groups()
        for line in open(
            os.path.join(root_of_clone(), "bauble/version.py"), "r"
        )
        if rgx.match(line)
    ]
    if matches:
        major, minor, patch = [int(i) for i in matches[0]]
        if inc_major:
            major += 1
            minor = 0
            patch = 0
        elif inc_minor:
            minor += 1
            patch = 0
        elif inc_patch:
            patch += 1
        version = "%s.%s.%s" % (major, minor, patch)

if not re.match(r".*?\..*?\..*?", version):
    usage_and_exit("bad version string")


def bump_file(filename, reg):
    """
    reg is either a compiled regular expression or a string that can be
    compiled into one.  reg should have two groups, everything before the
    version and everything after the version.
    """

    if isinstance(reg, str):
        reg = re.compile(reg)

    from io import StringIO

    buf = StringIO()
    for line in open(filename, "r"):
        match = reg.match(line)
        if match:
            string = reg.sub(r"\1%s\2", line)
            line = string % version
            print(("%s: %s" % (filename, line)).strip())
        buf.write(line)

    f = open(filename, "w")
    f.write(buf.getvalue())
    buf.close()


def bump_py_file(filename, varname="version"):
    """
    bump python files
    """

    reg = r"^(\s*%s\s*=\s*(?:\'|\")).*((?:\'|\").*%s.*)$" % (varname, bump_tag)
    bump_file(filename, reg)


def bump_desktop_file(filename):
    """
    bump xdf .desktop files
    """
    reg = r"(^Version=).*?\..*?\..*?(\s+?.*?%s.*?$)" % bump_tag
    bump_file(filename, reg)


# bump and grind
bump_py_file(os.path.join(root_of_clone(), "setup.py"))
bump_py_file(os.path.join(root_of_clone(), "bauble/version.py"))
bump_py_file(os.path.join(root_of_clone(), "doc/conf.py"), "release")
bump_desktop_file(os.path.join(root_of_clone(), "data/ghini.desktop"))

rgx = r"(^VERSION=\").*?\..*?\..*?(\".*?%s.*?$)" % bump_tag
bump_file(os.path.join(root_of_clone(), "packages/builddeb.sh"), rgx)

rgx = r"(^  release: \'v).*?\..*?\..*?(\'.*?%s.*?$)" % bump_tag
bump_file(os.path.join(root_of_clone(), ".appveyor.yml"), rgx)

rgx = r'(^!define VERSION ").*?\..*?\..*?(\".*?%s.*?$)' % bump_tag
bump_file(os.path.join(root_of_clone(), "scripts/build.nsi"), rgx)

print()
print(
    (
        f'git commit -m "bumping_to_{version}" '
        "bauble/version.py "
        "doc/conf.py "
        "data/ghini.desktop "
        "packages/builddeb.sh "
        "scripts/build.nsi "
        ".appveyor.yml "
        "setup.py"
    )
)
print("git checkout main")
print("git merge develop")
print("git push")
print()
print("after appveyor creates the release, you can get the version tag with:")
print("git fetch")
