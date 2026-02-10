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

from collections.abc import Callable
from pathlib import Path
from typing import Protocol
from typing import cast

from gi.repository import Gtk

import bauble
from bauble import db
from bauble import paths
from bauble import pluginmgr
from bauble import search
from bauble import utils
from bauble.i18n import _

from .base import View


class SimpleSearchBox(Gtk.Frame):
    """Provides a simple search for the home screen."""

    def __init__(self) -> None:
        super().__init__(label=_("Simple Search"))
        tooltip = _(
            "Simple search provides a quick way to access basic expression "
            "searches with the convenience of auto-completion. For more "
            "advanced searches the query builder provides a better starting "
            "point.\n\nTo return all of a domain use = *"
        )
        cast(Gtk.Label, self.get_label_widget()).set_margin_start(8)
        self.set_tooltip_text(tooltip)
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
        text = entry.get_text()
        if text != "*":
            text = repr(text)
        search_str = f"{self.short_domain} {condition} {text}"
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
        text = entry.get_text()
        completion = entry.get_completion()
        key_length = completion.get_minimum_key_length()
        utils.clear_model(completion)

        if len(text) < key_length:
            return

        completion_model = Gtk.ListStore(str)

        with db.Session() as session:
            if self.completion_getter:
                for val in self.completion_getter(session, text):
                    completion_model.append([val])
            else:
                for column in self.columns:
                    vals = (
                        session.query(getattr(self.domain, column))
                        .filter(
                            utils.ilike(
                                getattr(self.domain, column), f"{text}%%"
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

    infoboxclass: type[UpdateableWidget] | None = None
    main_widget: UpdateableWidget | Gtk.Widget | None = None

    def __init__(self) -> None:
        super().__init__()

        # home window contains a hbox: left half is for the proper home,
        # right half for infobox, only one infobox is allowed.

        self.hbox = Gtk.Box()
        self.pack_start(self.hbox, True, True, 0)

        self.vbox = Gtk.Box(spacing=0, orientation=Gtk.Orientation.VERTICAL)
        self.search_box = SimpleSearchBox()
        self.search_box.set_valign(Gtk.Align.START)
        self.search_box.set_vexpand(False)
        self.vbox.pack_start(self.search_box, False, True, 5)

        self.hbox.pack_start(self.vbox, True, True, 0)

        self.infobox: UpdateableWidget | None = None
        self._main_widget: UpdateableWidget | Gtk.Widget | None = None

    def update(self, *_args) -> None:
        logger.debug("HomeView::update")

        self.search_box.update()

        if self.infoboxclass and not self.infobox:
            logger.debug("HomeView::update - creating infobox")
            self.infobox = self.infoboxclass()  # pylint: disable=not-callable
            self.hbox.pack_end(self.infobox, False, False, 8)
            self.infobox.set_vexpand(False)
            self.infobox.set_hexpand(False)
            self.infobox.show()
        if self.infobox:
            logger.debug("HomeView::update - updating infobox")
            self.infobox.update()
        self.set_main_widget()
        # pylint: disable=no-member
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
            self.vbox.remove(self._main_widget)
            self._main_widget = None

        if not self._main_widget:
            if self.main_widget:
                self._main_widget = self.main_widget
            else:
                self._main_widget = Gtk.Image()
                self._main_widget.set_from_file(
                    str(Path(paths.lib_dir(), "images", "bauble_logo.png"))
                )
                self._main_widget.set_valign(Gtk.Align.START)
                self.__class__.main_widget = self._main_widget
            self.vbox.pack_start(self._main_widget, True, True, 10)
            self.vbox.show_all()


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
