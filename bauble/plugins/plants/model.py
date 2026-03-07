# Copyright 2025 Ross Demuth <rossdemuth123@gmail.com>
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
"""Generic database parts"""

from collections.abc import Sequence
from typing import Self

from sqlalchemy.orm import Mapped

from bauble import db


class Taxon(db.Domain):

    __abstract__ = True

    synonyms: list[Self]
    _synonyms: Sequence["Synonym"]
    accepted: Self

    def string(self, **kwargs) -> str:
        raise NotImplementedError

    def __str__(self) -> str:
        raise NotImplementedError

    def search_view_markup_pair(self) -> tuple[str, str]:
        raise NotImplementedError


class Synonym(db.Base):  # pylint: disable=too-few-public-methods

    __abstract__ = True

    synonym_id: int
    synonym: Mapped[Taxon]

    is_one_to_one = True

    def __str__(self) -> str:
        raise NotImplementedError

    def markup(self) -> str:
        raise NotImplementedError
