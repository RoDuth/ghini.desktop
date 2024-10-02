# Copyright 2008, 2009, 2010 Brett Adams
# Copyright 2014-2015 Mario Frasca <mario@anche.no>.
# Copyright 2021-2024 Ross Demuth <rossdemuth123@gmail.com>
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
Search tokens

Search tokens are pyparsing parse actions that refers to a single value or list
of values.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

import typing
from abc import ABC
from abc import abstractmethod

from pyparsing import ParseResults

from .clauses import QueryHandler


class TokenAction(ABC):
    """A pyparsing parse action class that refers to a single token or list of
    tokens. i.e. the value(s) to query for.
    """

    @abstractmethod
    def __init__(self, tokens: ParseResults) -> None:
        """Set tokens"""

    @abstractmethod
    def __repr__(self) -> str:
        """Repr for logging etc."""

    @abstractmethod
    def express(self, handler: QueryHandler) -> typing.Any:
        """Returns the token value as used in queries"""


class NoneToken(TokenAction):
    """`Literal('None')`"""

    def __init__(self, tokens: ParseResults | None = None) -> None:
        logger.debug("%s::__init__(%s)", self.__class__.__name__, tokens)

    def __repr__(self) -> str:
        return "(None<NoneType>)"

    def express(self, _handler: QueryHandler) -> None:
        return None


class EmptyToken(TokenAction):
    """`Literal('Empty')`"""

    def __init__(self, tokens: ParseResults | None = None) -> None:
        logger.debug("%s::__init__(%s)", self.__class__.__name__, tokens)

    def __repr__(self) -> str:
        return "Empty"

    def express(self, _handler: QueryHandler) -> set:
        return set()

    def __eq__(self, other: object) -> bool:
        if isinstance(other, EmptyToken):
            return True
        if isinstance(other, set):
            return len(other) == 0
        return NotImplemented


class StringToken(TokenAction):
    """Any string, quoted or not"""

    def __init__(self, tokens: ParseResults) -> None:
        logger.debug("%s::__init__(%s)", self.__class__.__name__, tokens)
        self.value: str = tokens[0]

    def __repr__(self) -> str:
        return f"'{self.value}'"

    def express(self, _handler: QueryHandler) -> str:
        """Returns the unquoted string."""
        return self.value


class NumericToken(TokenAction):
    """Any numeric value"""

    def __init__(self, tokens: ParseResults) -> None:
        logger.debug("%s::__init__(%s)", self.__class__.__name__, tokens)
        self.value = float(str(tokens[0]))  # store the float value
        # ValueListAction and DomainQueryAction: need the raw value
        self.raw_value: str = tokens[0]

    def __repr__(self) -> str:
        return str(self.value)

    def express(self, _handler: QueryHandler) -> float:
        """Returns the value as a float."""
        return self.value


class ValueToken(TokenAction):
    """Any token (i.e. any TokenAction)"""

    def __init__(self, tokens: ParseResults) -> None:
        logger.debug("%s::__init__(%s)", self.__class__.__name__, tokens)
        Token: typing.TypeAlias = (
            NoneToken | EmptyToken | StringToken | NumericToken
        )
        self.value: Token = tokens[0]

    def __repr__(self) -> str:
        return str(self.value)

    def express(
        self, handler: QueryHandler
    ) -> None | set | list | str | float:
        """Returns the result of calling express on the recieved token."""
        return self.value.express(handler)


class ValueListToken(TokenAction):
    """A list of tokens [TokenAction, ...]"""

    def __init__(self, tokens: ParseResults) -> None:
        logger.debug("%s::__init__(%s)", self.__class__.__name__, tokens)
        self.values: ParseResults = tokens[0]

    def __repr__(self) -> str:
        return str(self.values)

    def express(
        self, handler: QueryHandler
    ) -> list[None | set | list | str | float]:
        """Returns the results of calling express on the recieved tokens as a
        list.
        """
        return [i.express(handler) for i in self.values]
