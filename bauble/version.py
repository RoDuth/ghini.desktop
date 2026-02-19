# Copyright 2008-2010 Brett Adams
# Copyright 2014-2017 Mario Frasca <mario@anche.no>.
# Copyright 2021-2026 Ross Demuth <rossdemuth123@gmail.com>
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
Current version number and version comparison utilities.
"""

from dataclasses import dataclass

version = "1.3.16"  # :bump
"""
The current version as a semantic version number MAJOR.MINOR.PATCH(-PRERELEASE)
"""


@dataclass(order=True)
class ComparableVersion:
    major: int
    minor: int
    patch: int
    build: str = "z"


def comparable_version(version_str: str) -> ComparableVersion:
    as_list: list = version_str.replace("-", ".").split(".")

    for i in range(3):
        as_list[i] = int(as_list[i])

    return ComparableVersion(*as_list)
