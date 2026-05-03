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
Home view is the first view the user sees after connecting.
"""

import logging

logger = logging.getLogger(__name__)

import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any
from typing import Protocol
from typing import cast

from gi.repository import GLib
from gi.repository import Gtk
from gi.repository import Pango
from sqlalchemy import text

import bauble
from bauble import db
from bauble import paths
from bauble import pluginmgr
from bauble import prefs
from bauble import search
from bauble import utils
from bauble.i18n import _

from ..utils import clear_model
from .base import View
from .search import on_clicked_search


class SimpleSearchBox(Gtk.Frame):
    """Provides a simple search for the home screen."""

    def __init__(self) -> None:
        super().__init__(
            label=_("Simple Search"),
            valign=Gtk.Align.START,
            vexpand=False,
            tooltip_text=_(
                "Simple search provides a quick way to access basic "
                "expression searches with the convenience of auto-completion. "
                "For more advanced searches the query builder provides a "
                "better starting point.\n\nTo return all of a domain use = *"
            ),
        )
        cast(Gtk.Label, self.get_label_widget()).set_margin_start(8)
        self.domain: type[db.Domain] | None = None
        self.columns: list[str] = []
        self.short_domain: str = ""
        box = Gtk.Box(margin=10)
        self.add(box)
        self.domain_combo = Gtk.ComboBoxText()
        self.domain_combo.connect("changed", self.on_domain_combo_changed)
        box.add(self.domain_combo)
        self.cond_combo = Gtk.ComboBoxText()

        for cond in ["=", "contains", "like"]:
            self.cond_combo.append_text(cond)

        self.cond_combo.set_active(0)
        box.add(self.cond_combo)
        self.entry = Gtk.Entry()
        liststore = Gtk.ListStore(str)
        completion = Gtk.EntryCompletion()
        completion.set_model(liststore)
        completion.set_text_column(0)
        completion.set_minimum_key_length(2)
        completion.set_popup_completion(True)
        self.entry.set_completion(completion)
        self.entry.connect("activate", self.on_entry_activated)
        self.entry.connect("changed", self.on_entry_changed)
        box.pack_start(self.entry, True, True, 0)
        self.completion_getter: Callable | None = None

    def on_entry_activated(self, entry: Gtk.Entry) -> None:
        condition = self.cond_combo.get_active_text()
        txt = entry.get_text()
        if txt != "*":
            txt = repr(txt)
        search_str = f"{self.short_domain} {condition} {txt}"
        if bauble.gui:
            bauble.gui.send_command(search_str)

    def on_domain_combo_changed(self, combo: Gtk.ComboBoxText) -> None:

        mapper_search = search.strategies.get_strategy("MapperSearch")

        if not mapper_search:
            return

        domain = combo.get_active_text()
        # domain is None when resetting
        if domain:
            self.domain, self.columns = mapper_search.domains[domain]
            self.short_domain = min(
                (
                    min((k, v), key=len)
                    for k, v in mapper_search.shorthand.items()
                    if v == domain
                ),
                key=len,
            )
            self.completion_getter = mapper_search.completion_funcs.get(domain)

    def on_entry_changed(self, entry: Gtk.Entry) -> None:
        txt = entry.get_text()
        completion = entry.get_completion()
        key_length = completion.get_minimum_key_length()
        clear_model(completion)

        if len(txt) < key_length:
            return

        completion_model = Gtk.ListStore(str)

        with db.Session() as session:
            if self.completion_getter:
                for val in self.completion_getter(session, txt):
                    completion_model.append([val])
            else:
                for column in self.columns:
                    vals = (
                        session.query(getattr(self.domain, column))
                        .filter(
                            utils.ilike(
                                getattr(self.domain, column), f"{txt}%%"
                            )
                        )
                        .distinct()
                        .limit(10)
                    )
                    for val in vals:
                        completion_model.append([str(val[0])])

        completion.set_model(completion_model)

    def update(self) -> None:

        mapper_search = search.strategies.get_strategy("MapperSearch")

        if not mapper_search:
            return

        self.domain_combo.remove_all()

        for domain in sorted(mapper_search.domains.keys()):
            self.domain_combo.append_text(domain)

        self.domain_combo.set_active(0)
        self.cond_combo.set_active(0)
        self.entry.set_text("")


class StatsLabel(Gtk.Label):
    """Gtk.Label that is always bold with a margin of 4 for the stats grid."""

    def __init__(self, label: str, **kwargs) -> None:
        super().__init__(**kwargs)
        attr_list = Pango.AttrList()
        bold_attr = Pango.attr_weight_new(Pango.Weight.BOLD)
        attr_list.insert(bold_attr)
        self.set_attributes(attr_list)
        self.set_margin_start(4)
        self.set_margin_end(4)
        self.set_margin_top(4)
        self.set_margin_bottom(4)
        self.set_label(label)

    def set_label(self, label: Any) -> None:
        # pylint: disable=arguments-differ
        super().set_label(str(label))


class StatsRow:
    def __init__(
        self,
        label: str,
        total_query: str,
        total_link: str,
        in_use_query: str,
        in_use_link: str,
        unused_query: str,
        unused_link: str,
        position: int,
        has_active: bool = False,
    ) -> None:
        # pylint: disable=too-many-positional-arguments,too-many-arguments
        self.label = StatsLabel(label=label, xalign=1)

        self.total_label = StatsLabel(label="...")
        self.total_viewport = self._wrap(self.total_label)
        utils.make_label_clickable(
            self.total_label,
            on_clicked_search,
            total_link,
        )
        self.total_query = text(total_query)

        self.in_use_label = StatsLabel(label="...")
        self.in_use_viewport = self._wrap(self.in_use_label)
        utils.make_label_clickable(
            self.in_use_label,
            on_clicked_search,
            in_use_link,
        )
        self.in_use_query = text(in_use_query)

        self.unused_label = StatsLabel(label="...")
        self.unused_viewport = self._wrap(self.unused_label)
        utils.make_label_clickable(
            self.unused_label,
            on_clicked_search,
            unused_link,
        )
        self.unused_query = text(unused_query)

        self.position = position

        self.has_active = has_active

    @staticmethod
    def _wrap(label: Gtk.Label) -> Gtk.Widget:
        viewport = Gtk.Viewport(shadow_type=Gtk.ShadowType.ETCHED_OUT)
        event_box = Gtk.EventBox(border_width=2)
        viewport.add(event_box)
        event_box.add(label)
        return viewport

    def update(self) -> None:
        with db.engine.connect() as connection:
            total = connection.scalar(self.total_query)
            in_use = connection.scalar(self.in_use_query)
            unused = connection.scalar(self.unused_query)

        GLib.idle_add(self.set_labels, total, in_use, unused)

    def set_labels(self, total: int, in_use: int, unused: int) -> None:
        if self.has_active:
            sensitive = not prefs.prefs.get(prefs.exclude_inactive_pref)
            self.total_label.set_sensitive(sensitive)
            self.unused_label.set_sensitive(sensitive)

        self.total_label.set_label(total)
        self.in_use_label.set_label(in_use)
        self.unused_label.set_label(unused)


class StatsGrid(Gtk.Grid):
    stats_rows: list[StatsRow] = []
    initialised = False

    def __init__(self) -> None:
        super().__init__(
            row_spacing=2,
            column_spacing=2,
            column_homogeneous=True,
        )

        label = Gtk.Label(use_markup=True, label=f"<b>{_('Total')}</b>")
        self.attach(label, 1, 0, 1, 1)
        label = Gtk.Label(use_markup=True, label=f"<b>{_('In Use')}</b>")
        self.attach(label, 2, 0, 1, 1)
        label = Gtk.Label(use_markup=True, label=f"<b>{_('Unused')}</b>")
        self.attach(label, 3, 0, 1, 1)

    def update(self) -> None:
        for row in self.stats_rows:
            logger.debug("Updating stats row: %s", row.label.get_label())
            row.update()

    def init(self) -> None:
        if self.initialised:
            return

        for row in self.stats_rows:
            self.attach(row.label, 0, row.position, 1, 1)
            self.attach(row.total_viewport, 1, row.position, 1, 1)
            self.attach(row.in_use_viewport, 2, row.position, 1, 1)
            self.attach(row.unused_viewport, 3, row.position, 1, 1)

        self.show_all()

        type(self).initialised = True


class UpdateableNoArgs(Protocol):  # pylint: disable=too-few-public-methods
    def update(self) -> None: ...


# best solution I could come up with for the MetaClass conflict between
# Protocol and GObject

PMeta: type = type(Protocol)


WMeta: type = type(Gtk.Widget)


class _UWMeta(PMeta, WMeta):
    pass


class UpdateableWidget(Gtk.Widget, UpdateableNoArgs, metaclass=_UWMeta):
    pass


class HomeView(View, Gtk.Box):
    """The home screen.

    It is displayed after connecting and when home is selected.  it's the core
    of the "what do I do now" screen.
    """

    main_widget: UpdateableWidget | Gtk.Widget | None = None

    def __init__(self) -> None:
        super().__init__()
        self.left_vbox = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, margin=8
        )
        self.right_vbox = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            margin=8,
        )
        self.pack_start(self.left_vbox, True, True, 0)
        self.pack_end(self.right_vbox, False, False, 0)

        self.search_box = SimpleSearchBox()
        self.left_vbox.pack_start(self.search_box, False, True, 5)

        self.stats_grid = StatsGrid()
        self.right_vbox.pack_start(self.stats_grid, False, False, 8)

        from bauble.search.stored_queries import StoredQueriesButtonBox

        self.stored_queries_box = StoredQueriesButtonBox()
        self.right_vbox.pack_start(self.stored_queries_box, True, True, 8)

        self._main_widget: UpdateableWidget | Gtk.Widget | None = None

    def update(self, *_args) -> None:
        logger.debug("HomeView::update")

        self.search_box.update()
        self.stored_queries_box.refresh()

        self.stats_grid.init()
        threading.Thread(target=self.stats_grid.update, daemon=True).start()

        self.set_main_widget()

        if (
            self._main_widget
            and hasattr(self._main_widget, "update")
            and callable(self._main_widget.update)
        ):
            self._main_widget.update()

    def set_main_widget(self) -> None:
        # update after db change
        logger.debug("_main_widget = %s", self._main_widget)
        logger.debug("main_widget = %s", self.main_widget)
        if self._main_widget and self._main_widget is not self.main_widget:
            self.left_vbox.remove(self._main_widget)
            self._main_widget = None

        if self._main_widget:
            return

        if self.main_widget:
            self._main_widget = self.main_widget
        else:
            self._main_widget = Gtk.Image()
            self._main_widget.set_from_file(
                str(Path(paths.lib_dir(), "images", "bauble_logo.png"))
            )
            self._main_widget.set_valign(Gtk.Align.START)
            self.__class__.main_widget = self._main_widget
        self.left_vbox.pack_start(self._main_widget, True, True, 10)
        self.left_vbox.show_all()


class HomeCommandHandler(pluginmgr.CommandHandler):
    command = ["home"]
    view: HomeView | None = None

    @classmethod
    def get_view(cls) -> HomeView:
        if cls.view is None:
            cls.view = HomeView()
        return cls.view

    def __call__(self, cmd: str, arg: str | None) -> None:
        self.get_view().update()


pluginmgr.register_command(HomeCommandHandler)
