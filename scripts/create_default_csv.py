#!/usr/bin/env python3
# Copyright (c) 2024 Ross Demuth <rossdemuth123@gmail.com>
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
A basic script to convert the output of a csv backup file to a file usable as
default data for initiating a database.

Intended for recreating corrected csv after changes. e.g. Corrections are made
to the Geography table via exporting a csv, making correcting then reimporting.
To ensure subsequent users get these corrections a backup can me made and the
`geography.csv` file run through this script before committing to the code
base.

Usage e.g.:
$ ./scripts/create_default_csv.py geography.csv geography_corrected.csv
$ mv geography_corrected.csv bauble/plugins/plants/default/geography.csv
"""


import csv
import os
import sys

csv.field_size_limit(1000000)


def sort_key(field) -> tuple[int, str]:
    """Place `id` first, `name` and `code` next and `geojson` last"""
    if field == "id":
        return (0, field)
    if field in ["name", "code"]:
        return (1, field)
    if field == "geojson":
        return (3, field)
    return (2, field)


def main() -> str | None:
    usage = f"Usage: {sys.argv[0]} [ in_path ] [ out_path ]"

    if len(sys.argv) != 3:
        return usage

    if not os.path.exists(sys.argv[1]):
        return f"file: {sys.argv[1]} does not exist\n" + usage

    in_file = sys.argv[1]
    out_file = sys.argv[2]
    with open(in_file, "r", encoding="utf-8", newline="") as f_in:
        dict_reader = csv.DictReader(f_in)

        if not dict_reader.fieldnames:
            return f"file: {sys.argv[1]} is not a valid CSV file\n" + usage

        fieldnames = sorted(dict_reader.fieldnames, key=sort_key)
        fieldnames.remove("_created")
        fieldnames.remove("_last_updated")

        with open(out_file, "w", encoding="utf-8", newline="") as f_out:
            dict_writer = csv.DictWriter(f_out, fieldnames=fieldnames)
            dict_writer.writeheader()
            for line in dict_reader:
                del line["_created"]
                del line["_last_updated"]
                dict_writer.writerow(line)
    return None


if __name__ == "__main__":
    sys.exit(main())
