# Copyright (c) 2025 Ross Demuth <rossdemuth123@gmail.com>
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
SQL search provides a user interface to generate or edit an SQL string.
"""
import logging

logger = logging.getLogger(__name__)

import shlex
from pathlib import Path
from typing import cast

from gi.repository import Gtk

from bauble import db
from bauble import utils

from .strategies import MapperSearch
from .strategies import get_strategies


@Gtk.Template(
    filename=str(Path(__file__).resolve().parent / "sql_search_editor.ui")
)
class SQLSearchDialog(Gtk.Dialog):
    """Dialog to edit an SQL search."""

    __gtype_name__ = "SQLSearchDialog"

    domain_combo = cast(Gtk.ComboBoxText, Gtk.Template.Child())
    sql_textbuffer = cast(Gtk.TextBuffer, Gtk.Template.Child())
    sql_textview = cast(Gtk.TextView, Gtk.Template.Child())
    ok_button = cast(Gtk.Button, Gtk.Template.Child())

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        for key in sorted(MapperSearch.get_domain_classes().keys()):
            self.domain_combo.append_text(key)

        self.sql: str = ""
        self.domain: str = ""
        self.on_domain_combo_changed(self.domain_combo)

    @Gtk.Template.Callback()
    def on_text_buffer_changed(self, buffer: Gtk.TextBuffer) -> None:
        self.sql = buffer.get_text(*buffer.get_bounds(), False).strip()

        if self.sql:
            self.sql_textview.get_style_context().remove_class("problem")
        else:
            self.sql_textview.get_style_context().add_class("problem")

        self.refresh_ok_button()

    @Gtk.Template.Callback()
    def on_domain_combo_changed(self, combo: Gtk.ComboBoxText) -> None:
        self.sql_textbuffer.set_text("")
        self.domain = combo.get_active_text() or ""

        if self.domain:
            combo.get_style_context().remove_class("problem-bg")
        else:
            combo.get_style_context().add_class("problem-bg")

        if not self.domain:
            logger.debug("no value for domain.")
            return

        self.sql_textbuffer.set_text(f"SELECT * FROM {self.domain} WHERE \n")
        self.refresh_ok_button()

    def refresh_ok_button(self) -> None:
        """Set the OK button sensitivity when there is a domain and SQL."""
        self.ok_button.set_sensitive(bool(self.domain and self.sql))

    def get_query(self) -> str:
        return f":SQL = {self.domain} {repr(self.sql)}"

    @staticmethod
    def _get_sql_from_first_strategy(text: str) -> str:
        try:
            with db.Session() as session:
                queries = get_strategies(text)[0].search(text, session)
                if len(queries) == 1:
                    query = queries[0]
                    table = query.column_descriptions[0]["type"]
                    text = f":SQL = {table.__tablename__} " + repr(
                        str(
                            query.statement.compile(
                                compile_kwargs={"literal_binds": True}
                            )
                        )
                    )
        except Exception as e:  # pylint: disable=broad-except
            logger.debug("%s(%s)", type(e).__name__, e)
            return ""

        return text

    def set_query(self, text: str) -> None:
        """Set the dialog to a given SQL text.

        The text should be in the format: ":SQL = <domain> <SQL statement>".
        If it is not an attempt will be made to convert it from a query string
        to SQL using the first query of the first strategy available.
        """
        logger.debug("text = %s", text)

        if not text.startswith(":SQL"):
            text = self._get_sql_from_first_strategy(text)

        text = text.removeprefix(":SQL").strip().removeprefix("=").strip()
        logger.debug("text now %s", text)

        if not text:
            logger.debug("no text to set query to.")
            return

        try:
            domain, sql = shlex.split(text)
            sql = (
                sql.replace("'\\'", "'\\\\'")
                .replace("\\_", "\\\\_")
                .replace("\\%", "\\\\%")
                .encode("raw_unicode_escape")
                .decode("unicode_escape")
            )
        except ValueError as e:
            logger.debug("%s(%s)", type(e).__name__, e)
            return

        if domain not in MapperSearch.get_domain_classes():
            logger.debug("domain %s not valid", domain)
            return

        utils.set_widget_value(self.domain_combo, domain)
        self.sql_textbuffer.set_text(sql)
