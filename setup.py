#!/usr/bin/env python3
#
# Copyright (c) 2005-2009 Brett Adams <brett@belizebotanic.org>
# Copyright (c) 2015 Mario Frasca <mario@anche.no>
# Copyright (c) 2016-2023 Ross Demuth <rossdemuth123@gmail.com>
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
Install script.
"""

from setuptools import find_packages
from setuptools import setup

package_data = {
    "": ["README.rst", "CHANGES", "LICENSE"],
    "bauble": [
        "*.ui",
        "*.glade",
        "images/*.png",
        "images/*.svg",
        "images/*.gif",
        "images/*.ico",
        "images/*.icns",
        "images/*.bmp",
    ],
    "bauble.utils": ["prj_crs.csv"],
    "bauble.plugins.plants": [
        "default/*.csv",
        "default/wgsrpd/*.geojson",
        "*.kml",
    ],
    "bauble.plugins.garden": ["*.kml"],
    "bauble.plugins.abcd": ["*.xsd"],
    "bauble.plugins.report.mako.templates": ["*.csv", "*.html"],
    "bauble.plugins.report.xsl.stylesheets": ["*.xsl"],
    "bauble.plugins.report.xsl.stylesheets.label_memorial_example": [
        "*.png",
        "*.svg",
    ],
    "bauble.plugins.report.xsl.stylesheets.label_example": ["*.png"],
}

for plugin in find_packages(where="bauble/plugins"):
    package_data.setdefault(f"bauble.plugins.{plugin}", []).extend(
        ["*.glade", "*.ui"]
    )

with open("README.rst", "r", encoding="utf-8", newline="") as f:
    long_description = f.read()

setup(
    name="ghini.desktop",
    version="1.3.7",  # :bump
    # scripts=scripts,
    packages=find_packages(),
    # package_dir=all_package_dirs,
    package_data=package_data,
    install_requires=[
        "SQLAlchemy==1.4.43",
        "Pillow",
        "lxml",
        "tld",
        "mako",
        "pyparsing",
        "pyshp",
        "pyproj",
        "filelock>=3",
        "python-dateutil",
        "dukpy",
    ],
    extras_require={"docs": ["sphinx==1.7.9"]},
    author="Ross Demuth",
    author_email="rossdemuth123@gmail.com",
    python_requires=">=3.9.0",
    description="Ghini: a biodiversity collection manager",
    long_description=long_description,
    license="GPLv2+",
    keywords=(
        "database biodiversity botanic collection botany "
        "herbarium arboretum"
    ),
    url="http://github.com/RoDuth/ghini.desktop/",
)
