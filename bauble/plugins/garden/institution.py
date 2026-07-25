# Copyright 2008-2010 Brett Adams
# Copyright 2015,2018 Mario Frasca <mario@anche.no>.
# Copyright 2017 Jardín Botánico de Quito
# Copyright 2024-2025 Ross Demuth <rossdemuth123@gmail.com>
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
Edit and store information about the institution in the bauble meta table
"""

import logging

logger = logging.getLogger(__name__)

from dataclasses import dataclass

from sqlalchemy import Table
from sqlalchemy import bindparam
from sqlalchemy import select

from bauble import db
from bauble import meta


@dataclass
class Institution:  # pylint: disable=too-many-instance-attributes
    """Institution is a "live" object, you only need to set a value on it and
    then call `write` to persist them to the database.

    Institution values are stored in the Ghini meta database and not in its own
    table
    """

    name: str | None = None
    abbreviation: str | None = None
    code: str | None = None
    contact: str | None = None
    technical_contact: str | None = None
    email: str | None = None
    tel: str | None = None
    fax: str | None = None
    address: str | None = None
    geo_latitude: str | None = None
    geo_longitude: str | None = None
    geo_zoom: str | None = None
    uuid: str | None = None

    def __post_init__(self) -> None:
        table: Table = meta.BaubleMeta.__table__

        if not db.engine:
            return

        with db.engine.begin() as conn:
            for key in self.__dict__:
                db_prop = str("inst_" + key)
                stmt = select(table.c.value).where(table.c.name == db_prop)
                value = conn.execute(stmt).scalar()
                setattr(self, key, value)

    def write(self) -> None:
        table: Table = meta.BaubleMeta.__table__

        if not db.engine:
            return

        inserts: list[dict[str, str]] = []
        updates: list[dict[str, str]] = []
        with db.engine.begin() as conn:
            for key, value in self.__dict__.items():
                db_prop = str("inst_" + key)
                stmt = select(table.c.id).where(table.c.name == db_prop)
                row = conn.execute(stmt).scalar()
                if row:
                    updates.append({"_name": db_prop, "value": value})
                else:
                    inserts.append({"name": db_prop, "value": value})

            if inserts:
                insert = table.insert()
                conn.execute(insert, inserts)

            if updates:
                update = (
                    table.update()
                    .where(table.c.name == bindparam("_name"))
                    .values(value=bindparam("value"))
                )
                conn.execute(update, updates)
