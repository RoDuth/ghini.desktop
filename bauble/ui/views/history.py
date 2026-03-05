# Copyright 2008-2010 Brett Adams
# Copyright 2015 Mario Frasca <mario@anche.no>.
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
History UI parts and command handler
"""

import logging

logger = logging.getLogger(__name__)

import json
import traceback
from datetime import timedelta
from datetime import timezone
from pathlib import Path
from textwrap import shorten
from textwrap import wrap
from typing import cast

from gi.repository import Gdk
from gi.repository import Gio
from gi.repository import Gtk
from pyparsing import CaselessLiteral
from pyparsing import Group
from pyparsing import Literal
from pyparsing import ParserElement
from pyparsing import ParseResults
from pyparsing import Regex
from pyparsing import Word
from pyparsing import ZeroOrMore
from pyparsing import alphas
from pyparsing import one_of
from pyparsing import printables
from pyparsing import quoted_string
from pyparsing import remove_quotes
from sqlalchemy import and_
from sqlalchemy.orm import Query
from sqlalchemy.orm import Session
from sqlalchemy.sql import ColumnElement

import bauble
from bauble import db
from bauble import pluginmgr
from bauble import prefs
from bauble import search
from bauble import utils
from bauble.i18n import _
from bauble.meta import BaubleMeta
from bauble.ui import dialogs

from .base import View

parent = Path(__file__).resolve().parent


@Gtk.Template(filename=str(parent / "history_view.ui"))
class HistoryView(View, Gtk.Box):
    """Show the tables row in the order they were last updated."""

    __gtype_name__ = "HistoryView"

    liststore = cast(Gtk.ListStore, Gtk.Template.Child())
    history_tv = cast(Gtk.TreeView, Gtk.Template.Child())

    TVC_OBJ = 0
    TVC_ID = 1
    TVC_TIMESTAMP = 2
    TVC_OPERATION = 3
    TVC_USER = 4
    TVC_TABLE = 5
    TVC_USER_FRIENDLY = 6
    STEP = 1000
    TRUNCATE = 100

    queries: dict[str, tuple[str, str]] = {}

    def __init__(self) -> None:
        logger.debug("HistoryView::__init__")
        super().__init__()

        # setup context_menu
        menu_model = Gio.Menu()
        revert_action_name = "revert_hist_to_selection"
        copy_values_action_name = "copy_hist_selection_values"
        copy_geojson_action_name = "copy_hist_selection_geojson"

        if bauble.gui:
            bauble.gui.add_action(
                revert_action_name, self.on_revert_to_history
            )
            bauble.gui.add_action(copy_values_action_name, self.on_copy_values)
            bauble.gui.add_action(
                copy_geojson_action_name, self.on_copy_geojson
            )

        revert = Gio.MenuItem.new(_("Revert to"), f"win.{revert_action_name}")
        copy_values = Gio.MenuItem.new(
            _("Copy values"), f"win.{copy_values_action_name}"
        )
        copy_geojson = Gio.MenuItem.new(
            _("Copy geojson"), f"win.{copy_geojson_action_name}"
        )
        menu_model.append_item(revert)
        menu_model.append_item(copy_values)
        menu_model.append_item(copy_geojson)

        self.context_menu = Gtk.Menu.new_from_model(menu_model)
        self.context_menu.attach_to_widget(self.history_tv)

        self.clone_hist_id = 0
        self.offset = 0
        self.hist_count = 0
        self.last_row_in_tree = 0

        self.last_arg = ""

        Gtk.Scrollable.get_vadjustment(self.history_tv).connect(
            "value-changed", self.on_history_tv_value_changed
        )

    def on_history_tv_value_changed(self, *_args) -> None:
        """When scrolling lazy load another batch of rows as needed.

        i.e. more than half way throught the the last batch and more rows
        remain
        """
        visible = self.history_tv.get_visible_range()
        if visible:
            tree_iter = self.liststore.get_iter(visible[1])
            bottom_line_id = int(self.liststore.get_value(tree_iter, 1))

            if (
                bottom_line_id - self.last_row_in_tree <= self.STEP / 2
                and self.hist_count > self.offset
            ):
                self.add_rows()

    @staticmethod
    def _cmp_items_key(val: tuple[str, object]) -> tuple[int, str]:
        """Sort by the key after putting id first, changes second and None
        values last.
        """
        k, v = val
        if k == "id":
            return (0, k)
        if isinstance(v, list):
            return (1, k)
        if v is None:
            return (3, k)
        return (2, k)

    def _shorten_list(self, lst: list) -> str:
        part1 = json.dumps(lst[0])
        part2 = json.dumps(lst[1])
        len1 = len(part1)
        len2 = len(part2)
        if len1 + len2 < self.TRUNCATE - 4:
            return f"[{part1}, {part2}]"
        if len1 < 10 and len2 > self.TRUNCATE - len1 - 4:
            short2 = shorten(
                part2,
                self.TRUNCATE - len1 - 4,
                placeholder="…",
            )
            return f"[{part1}, {short2}]"
        if len2 < 10 and len1 > self.TRUNCATE - len2 - 4:
            short1 = shorten(
                part1,
                self.TRUNCATE - len2 - 4,
                placeholder="…",
            )
            return f"[{short1}, {part2}]"
        perc = len1 / (len1 + len2)
        short1 = shorten(
            part1,
            round(self.TRUNCATE * perc) - 2,
            placeholder="…",
        )
        short2 = shorten(
            part2,
            round(self.TRUNCATE * (1 - perc)) - 2,
            placeholder="…",
        )
        return f"[{short1}, {short2}]"

    def add_row(self, item: db.History) -> None:
        if not (item.id and item.timestamp and item.values):
            return

        dct = dict(item.values)
        del dct["_created"]
        del dct["_last_updated"]

        item_geojson = dct.get("geojson")
        geojson: str | None = None
        if item_geojson:
            if isinstance(item_geojson, list) and len(item_geojson) == 2:
                geojson = self._shorten_list(item_geojson)
            else:
                geojson = shorten(
                    json.dumps(item_geojson), self.TRUNCATE, placeholder="…"
                )
            del dct["geojson"]

        friendly = ", ".join(
            f"{k}: {repr('') if v is None else v}"
            for k, v in sorted(list(dct.items()), key=self._cmp_items_key)
        )
        friendly = "\n".join(wrap(friendly, 200))
        frmt = prefs.prefs.get(prefs.datetime_format_pref)
        is_cloned = item.id <= self.clone_hist_id
        self.liststore.append(
            [
                item,
                str(item.id),
                item.timestamp.strftime(frmt),
                item.operation,
                item.user,
                item.table_name,
                friendly,
                geojson,
                is_cloned,
            ]
        )

    def get_selected_value(self) -> db.History | None:
        """Get the selected rows object from column 0."""
        model, itr = self.history_tv.get_selection().get_selected()
        if model is None or itr is None:
            return None
        return model[itr][0]

    @Gtk.Template.Callback()
    def on_button_release(self, _view, event: Gdk.EventButton) -> bool:
        if event.button != 3:
            return False

        self.context_menu.popup_at_pointer(event)
        return True

    def on_revert_to_history(self, _action, _param) -> None:
        selected = self.get_selected_value()
        if not (selected and selected.id):
            return

        if selected.id <= self.clone_hist_id:
            msg = (
                _(
                    "<b>WARNING: Can not revert past clone point</b>\n\nThis "
                    "database was cloned at line %s"
                )
                % self.clone_hist_id
            )
            dialogs.message_dialog(msg)
            return

        logger.debug(
            "reverting to selected %s id: %s",
            selected.table_name,
            selected.table_id,
        )

        rows = 0
        with db.Session() as session:
            rows = (
                session.query(db.History)
                .filter(db.History.id >= selected.id)
                .count()
            )

        msg = (
            _(
                "<b>CAUTUION: reverting database is permanent.</b>\n\nYou "
                "have selected to revert %s changes.\n\nDo you wish to "
                "proceed?"
            )
            % rows
        )
        if dialogs.yes_no_dialog(msg):
            if selected:
                db.History.revert_to(selected.id)
            self.update(self.last_arg)

    def on_copy_values(self, _action, _param) -> None:
        if selected := self.get_selected_value():
            if not selected.values:
                return
            values = dict(selected.values)
            if values.get("geojson"):
                del values["geojson"]
            string = json.dumps(values)
            if bauble.gui:
                bauble.gui.get_display_clipboard().set_text(string, -1)

    def on_copy_geojson(self, _action, _param) -> None:
        if selected := self.get_selected_value():
            if not selected.values:
                return
            string = json.dumps(selected.values.get("geojson"))
            if bauble.gui:
                bauble.gui.get_display_clipboard().set_text(string, -1)

    @classmethod
    def add_translation_query(
        cls, table_name: str, domain: str, query: str
    ) -> None:
        """Allows plugins to add search strings for the best domain for a
        selected history line's table name.
        """
        cls.queries[table_name] = (domain, query)

    @Gtk.Template.Callback()
    def on_row_activated(self, _tree, path, _column) -> None:
        """Search for the correct domain for the selected row's item.

        This generally will only work if the item is not deleted.
        """
        row = self.liststore[path]  # pylint: disable=unsubscriptable-object
        hist_obj = row[self.TVC_OBJ]
        table = row[self.TVC_TABLE]
        obj_id = hist_obj.table_id

        table, query = self.queries.get(
            table, (table, "{table} where id={obj_id}")
        )

        if table in search.strategies.MapperSearch.domains:
            query = query.format(table=table, obj_id=obj_id)
            if bauble.gui:
                bauble.gui.send_command(query)

    @staticmethod
    def get_expression() -> ParserElement:
        """Pyparsing parser for history searches."""
        operator = one_of("= != < <= > >= like contains has")
        on_operator = Literal("on")
        time_stamp_ident = Literal("timestamp")
        numeric_value = Regex(r"[-]?\d+(\.\d*)?([eE]\d+)?").set_parse_action(
            lambda _s, _l, t: [float(t[0])]
        )
        date_str = Regex(
            r"\d{1,4}[/.-]{1}\d{1,2}[/.-]{1}\d{1,4}"
        ).set_parse_action(lambda _s, _l, t: [str(t[0])])
        value = (
            quoted_string.set_parse_action(remove_quotes)
            | date_str
            | numeric_value
            | Word(printables)
        )
        _and = CaselessLiteral("and").suppress()
        identifier = Word(alphas + "_")
        ident_expression = Group(identifier + operator + value) | Group(
            time_stamp_ident + on_operator + value
        )
        to_sync = Literal("to_sync")
        expression = (
            to_sync + ZeroOrMore(_and + ident_expression)
        ) | ZeroOrMore(ident_expression + ZeroOrMore(_and + ident_expression))
        return expression

    def get_query_filters(self) -> list[ColumnElement]:
        """Parse the string provided in arg and return the equivalent as
        consumed by sqlalchemy query `filter()` method.
        """

        filters = []
        expression = self.get_expression()
        for part in expression.parse_string(self.last_arg, parse_all=True):
            if part == "to_sync":
                if self.clone_hist_id:
                    filters.append(db.History.id > self.clone_hist_id)
                else:
                    # show nothing if database doesn't appear to be a clone
                    filters.append(db.History.id.is_(None))
                continue
            if part[0] == "timestamp" and part[1] == "on":
                filters.append(self.get_on_timestamp_filter(part))
            else:
                attr = getattr(db.History, part[0])
                val = part[2]
                operation = search.operations.OPERATIONS[part[1]]
                filters.append(operation(attr, val))

        return filters

    @staticmethod
    def get_on_timestamp_filter(part: ParseResults) -> ColumnElement:
        """sqlalchemy query `filter()` statement specific to timestamp `on`
        searches
        """
        attr = getattr(db.History, part[0])
        try:
            val = float(part[2])
        except ValueError:
            val = part[2]
        date_val = search.clauses.get_datetime(val)
        today = date_val.astimezone(tz=timezone.utc)
        tomorrow = today + timedelta(1)
        return and_(attr >= today, attr < tomorrow)

    def update(self, *args: str | None) -> None:
        """Start to add the history items to the view."""

        self.liststore.clear()
        self.offset = 0
        self.hist_count = 0
        self.last_row_in_tree = 0
        self.last_arg = args[0] or ""

        with db.Session() as session:
            clone_hist_id = (
                session.query(BaubleMeta.value)
                .filter(BaubleMeta.name == "clone_history_id")
                .scalar()
            )
            self.clone_hist_id = int(clone_hist_id or 0)
            self.hist_count = self.query(session).count()

        logger.debug("hist_count = %s", self.hist_count)
        self.add_rows()

    def query(self, session: Session) -> Query:
        """Given a session attach the appropriate query and filters."""
        query = session.query(db.History)
        if self.last_arg:
            query = query.filter(*self.get_query_filters())
        query = query.order_by(db.History.id.desc())
        return query

    def add_rows(self) -> None:
        """Add a batch of rows to the view."""
        try:
            with db.Session() as session:
                query = self.query(session)
                # add rows in small batches
                rows = query.offset(self.offset).limit(self.STEP).all()
                id_ = 0
                for row in rows:
                    self.add_row(row)
                    id_ = row.id
                self.last_row_in_tree = id_
                self.offset += self.STEP
                logger.debug("offset = %s", self.offset)
        except Exception as e:  # pylint: disable=broad-except
            logger.debug("%s(%s)", type(e).__name__, e)
            msg = utils.xml_safe(e)
            details = utils.xml_safe(traceback.format_exc())
            if bauble.gui:
                self.show_error_box(msg, details)

    @staticmethod
    def show_error_box(msg: str, details: str) -> None:
        if bauble.gui:
            bauble.gui.show_error_box(msg, details)


class HistoryCommandHandler(pluginmgr.CommandHandler):
    command = ["history"]
    view: HistoryView | None = None

    @classmethod
    def get_view(cls) -> HistoryView:
        if not cls.view:
            cls.view = HistoryView()
        return cls.view

    def __call__(self, cmd: str, arg: str | None) -> None:
        self.get_view().update(arg)


pluginmgr.register_command(HistoryCommandHandler)
