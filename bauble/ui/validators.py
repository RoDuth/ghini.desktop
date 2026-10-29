# Copyright 2026 Ross Demuth <rossdemuth123@gmail.com>
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
Validators for widget signal handlers.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

from typing import TYPE_CHECKING
from typing import Any
from typing import Protocol

from bauble import db
from bauble.utils import parse_str_date

if TYPE_CHECKING:
    from .presenter import GenericPresenter


class ValidatorError(Exception):
    """Custom validation exception, raised when validation fails"""


class Checker(Protocol):
    # pylint: disable=too-few-public-methods
    def __call__(self, value: Any, *args: Any) -> bool: ...


class Validator:  # pylint: disable=too-few-public-methods
    """Functor to supply a checker and problem_name.

    Inteneded for use case with ``HandlerMethodDescriptor`` instances.

    :param checker: a callable that returns True if value is valid else False.
        Checkers can also raise exceptions to indicate invalid values.
        Checkers must accept three parameters: value, field_name and model.
    :param problem_name: the string to use for the presenter Problem.
    """

    def __init__(
        self,
        checker: Checker,
        problem_name: str = "",
        is_method: bool = False,
    ) -> None:
        self.checker = checker
        self.problem_name = problem_name
        self.is_method = is_method

    def __call__(
        self,
        value: Any,
        field_name: str | None = None,
        model: Any = None,
        instance: GenericPresenter | None = None,
    ) -> Any:
        try:
            if self.is_method:
                assert self.checker(instance, value, field_name, model)
            else:
                assert self.checker(value, field_name, model)
        except Exception as e:
            raise ValidatorError from e


def validate_non_empty(value: str, *_args: Any) -> bool:
    """Validator function to check value is non-empty."""
    if not value or (isinstance(value, str) and not value.strip()):
        return False
    return True


def validate_unique(value: str, *args: Any) -> bool:
    """Validator function to check uniqueness of a field value in the DB."""
    field = args[0]
    model = args[1]
    class_ = model.__class__
    column = getattr(class_, field)

    with db.Session() as session:

        model = session.merge(model)
        exists = (
            session.query(class_).filter(column == value.strip()).one_or_none()
        )

        if exists is not None and exists is not model:
            return False
    return True


def validate_date(value: str, *_args: Any) -> bool:
    """Validator functiion to check value is a valid string date."""
    return parse_str_date(value) is not None
