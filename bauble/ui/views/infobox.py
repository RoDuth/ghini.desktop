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
InfoBox widgets, as used in SearchView.
"""

import logging

logger = logging.getLogger(__name__)

import re
from collections.abc import Callable
from pathlib import Path
from typing import Protocol
from typing import cast

from gi.repository import Gdk
from gi.repository import Gtk

import bauble
from bauble import db
from bauble import prefs
from bauble import utils
from bauble.i18n import _
from bauble.utils.web import BaubleLinkButton
from bauble.utils.web import LinkDict
from bauble.utils.web import link_button_factory

INFOBOXPAGE_WIDTH_PREF = "infobox.page_width"
"""The preferences key for storing the InfoBoxPage width."""


class ExpandedPref:  # pylint: disable=too-few-public-methods
    """A descriptor for the prefs key for storing the expanded state of an
    info expander.
    """

    def __get__[T](self, _instance: T, class_: type[T]) -> str:
        expander_name = re.sub(
            r"(?<!^)(?=[A-Z])",
            "_",
            class_.__name__,
        ).lower()[:-1]
        return f"infobox.{expander_name}d"


class InfoExpander[T: db.Domain]:
    """InfoExpander mixin that can be used with Gtk.Template decorated class
    that inherits from Gtk.Expander and supplies an update method.

    This mixin provides a way to store the expanded state of the expander in
    the preferences.

    Example with Gtk.Template and no specific type::

        @Gtk.Template(filename="/path/to/file.ui"))
        class HamExpander(InfoExpander, Gtk.Expander):

            __gtype_name__ = "HamExpander"

            label = cast(Gtk.Label, Gtk.Template.Child())

            def __init__(self) -> None:
                super().__init__(label=_("Hams"))

            @Gtk.Template.Callback()
            def on_expanded(self, expander: Gtk.Expander, *_args) -> None:
                super().on_expanded(expander)

            def update(self, row: db.Base) -> None:
                self.label.set_text(row.id)

    Example without Gtk.Template and a specific type::

        class EggsExpander(InfoExpander[EggsModel], Gtk.Expander):

            def __init__(self) -> None:
                super().__init__(label=_("Eggs"))
                self.connect("notify::expanded", self.on_expanded)
                self.label = Gtk.Label(xalign=0.1)
                box = Gtk.Box()
                box.set_border_width(5)
                box.add(self.label)
                self.add(box)

            def update(self, row: EggsModel) -> None:
                self.label.set_text(row.yoke_count)

    """

    EXPANDED_PREF = ExpandedPref()
    set_expanded: Callable[[bool], None]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        # the separator inserted between expanders see InfoBoxPage.add_expander
        self._sep: Gtk.Separator | None = None
        self.set_expanded(prefs.prefs.get(self.EXPANDED_PREF, True))

    def on_expanded(self, expander: Gtk.Expander, *_args) -> None:
        prefs.prefs[self.EXPANDED_PREF] = expander.get_expanded()

    def update(self, row: T) -> None:
        """This method should be implimented in subclass to update from the
        selected row.
        """
        raise NotImplementedError


# beware, typing hack ahead (due to the lack of Intersection).
class Updateable(Protocol):  # pylint: disable=too-few-public-methods

    def update(self, row: db.Domain) -> None: ...


# best solution I could come up with for the MetaClass conflict between
# Protocol and GObject

PMeta: type = type(Protocol)


EMeta: type = type(Gtk.Expander)


class _UEMeta(PMeta, EMeta):
    pass


class UpdateableExpander(Gtk.Expander, Updateable, metaclass=_UEMeta):
    _sep: Gtk.Separator | None

    def update(self, row: db.Domain) -> None: ...


class InfoBoxPage[T: db.Domain](Gtk.ScrolledWindow):
    """A ``Gtk.ScrolledWindow`` that contains ``InfoExpander`` objects."""

    def __init__(self) -> None:
        super().__init__()
        self.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.vbox.set_spacing(10)
        viewport = Gtk.Viewport()
        viewport.add(self.vbox)
        self.add(viewport)
        self.expanders: dict[str, UpdateableExpander] = {}
        self.label: str | None = None
        self.connect("size-allocate", self.on_resize)

    @staticmethod
    def on_resize(_window, allocation: Gdk.Rectangle) -> None:
        prefs.prefs[INFOBOXPAGE_WIDTH_PREF] = allocation.width

    def add_expander(self, expander: UpdateableExpander) -> None:
        """Add an expander to the dictionary of exanders in this infobox using
        the label name as the key.

        :param expander: Gtk.Expander to add to this infobox
        """
        self.vbox.pack_start(expander, expand=False, fill=True, padding=5)
        self.expanders[expander.get_property("label")] = expander

        expander._sep = Gtk.Separator()
        self.vbox.pack_start(expander._sep, False, False, padding=0)

    def get_expander(self, label: str) -> UpdateableExpander | None:
        """Get an expander by the expander's label name.

        :param label: the name of the expander to return
        :return: expander or None
        """
        return self.expanders.get(label)

    def remove_expander(self, label: str) -> UpdateableExpander | None:
        """Remove expander from the infobox by the expander's label name.

        :param label: the name of the expander to remove

        Return the expander that was removed from the infobox.
        """
        if label in self.expanders:
            expander = self.expanders[label]
            self.vbox.remove(expander)
            del self.expanders[label]
            return expander
        return None

    def update(self, row: T) -> None:
        """Updates the infobox with values from row.

        :param row: the mapper instance to use to update this infobox,
            this is passed to each of the infoexpanders in turn
        """
        for expander in list(self.expanders.values()):
            expander.update(row)


class InfoBox[T: db.Domain](Gtk.Notebook):
    """Holds list of expanders with an optional tabbed layout.

    The default is to not use tabs. To create the InfoBox with tabs
    use InfoBox(tabbed=True).  When using tabs then you can either add
    expanders directly to the InfoBoxPage or using
    InfoBox.add_expander with the page_num argument.

    Also, it's not recommended to create a subclass of a subclass of
    InfoBox since if they both use bauble.utils.BuilderWidgets then
    the widgets will be parented to the infobox that is created first
    and the expanders of the second infobox will appear empty.
    """

    def __init__(self, tabbed: bool = False) -> None:
        super().__init__()
        self.row: db.Domain | None = None
        self.set_property("show-border", False)

        if not tabbed:
            page = InfoBoxPage[T]()
            self.insert_page(page, tab_label=None, position=0)
            self.set_property("show-tabs", False)
            self.set_current_page(0)

        self.connect("switch-page", self.on_switch_page)

    # notebook == self could be a static method and just use the notebook?
    def on_switch_page(self, _notebook, _page, page_num: int, *_args) -> None:
        """Called when a page is switched."""
        if not self.row:
            return

        page = self.get_nth_page(page_num)
        if page and hasattr(page, "update"):
            page.update(self.row)

    def add_expander(
        self,
        expander: InfoExpander,
        page_num: int = 0,
    ) -> None:
        """Add an expander to a page.

        :param expander: The expander to add.
        :param page_num: The page number in the InfoBox to add the expander.
        """
        page = self.get_nth_page(page_num)
        if page and hasattr(page, "add_expander"):
            page.add_expander(expander)

    def update(self, row: T) -> None:
        """Update the current page with row."""
        self.row = row
        page_num = self.get_current_page()

        page = self.get_nth_page(page_num)
        if page and hasattr(page, "update"):
            page.update(row)


@Gtk.Template(
    filename=str(Path(__file__).resolve().parent / "properties_expander.ui")
)
class PropertiesExpander(InfoExpander[db.Domain], Gtk.Expander):
    """Displays base properties all Domains have. Created, Updated, ID, Type"""

    __gtype_name__ = "PropertiesExpander"

    id_label = cast(Gtk.Label, Gtk.Template.Child())
    type_label = cast(Gtk.Label, Gtk.Template.Child())
    created_label = cast(Gtk.Label, Gtk.Template.Child())
    updated_label = cast(Gtk.Label, Gtk.Template.Child())

    def __init__(self) -> None:
        super().__init__(label=_("Properties"))

    def update(self, row: db.Domain) -> None:
        self.id_label.set_text(str(row.id))
        self.type_label.set_text(str(type(row).__name__))
        fmat = prefs.prefs.get(prefs.datetime_format_pref)
        # pylint: disable=protected-access
        self.created_label.set_text(
            row._created.strftime(fmat) if row._created else ""
        )
        self.updated_label.set_text(
            row._last_updated.strftime(fmat) if row._last_updated else ""
        )

    @Gtk.Template.Callback()
    def on_id_button_press(
        self,
        _widget: Gtk.EventBox,
        event: Gdk.EventButton,
    ) -> bool:
        """Copy the ID value to clipboard."""
        if (
            event.button == 1
            and event.type == Gdk.EventType.DOUBLE_BUTTON_PRESS
        ):
            # Copy the ID on a double click
            string = self.id_label.get_text()
            bauble.gui.get_display_clipboard().set_text(string, -1)
            return True
        return False

    @Gtk.Template.Callback()
    def on_expanded(self, expander: Gtk.Expander, *_args) -> None:
        super().on_expanded(expander)


@Gtk.Template(
    filename=str(Path(__file__).resolve().parent / "links_expander.ui")
)
class LinksExpander(InfoExpander[db.Domain], Gtk.Expander):
    """Provides the web link buttons section for this row.

    :param notes: the name of the notes property on the row, notes can
        contain embeded links.
    :param links: a list of link definitions to be used for all rows of
        this type.
    """

    __gtype_name__ = "LinksExpander"

    notes_links_box = cast(Gtk.Box, Gtk.Template.Child())
    web_links_box = cast(Gtk.Box, Gtk.Template.Child())
    separator = cast(Gtk.Separator, Gtk.Template.Child())

    @Gtk.Template.Callback()
    def on_expanded(self, expander: Gtk.Expander, *_args) -> None:
        super().on_expanded(expander)

    def __init__(
        self,
        notes: str | None = None,
        links: list[LinkDict] | None = None,
    ) -> None:
        super().__init__(label=_("Links"))
        links = links or []
        self.notes = notes
        self.web_links: list[BaubleLinkButton] = []
        for link in sorted(links, key=lambda i: i["title"]):
            try:
                btn = link_button_factory(link)
                self.web_links.append(btn)
                self.web_links_box.pack_start(btn, False, False, 0)
            except Exception as e:  # pylint: disable=broad-except
                # broad except, user data.
                logger.debug(
                    "wrong link definition %s, %s(%s)",
                    link,
                    type(e).__name__,
                    e,
                )

    def update(self, row: db.Domain) -> None:
        widgets: list[Gtk.Widget] = [
            self,
            self.notes_links_box,
            self.separator,
            self.web_links_box,
        ]
        if self._sep:
            widgets.append(self._sep)

        utils.hide_widgets(widgets)

        note_links: list[BaubleLinkButton] = []

        for btn in self.web_links:
            btn.set_string(row)

        self.notes_links_box.foreach(self.notes_links_box.remove)

        if self.notes:
            for note in getattr(row, self.notes):
                for label, url in utils.get_urls(note.note):
                    if not label:
                        label = url
                    category = note.category
                    link: LinkDict = {
                        "title": label,
                        "tooltip": f"from note of category {category}",
                    }
                    button = link_button_factory(link)
                    button.set_uri(url)
                    note_links.append(button)

            for button in sorted(note_links, key=lambda i: i.title):
                self.notes_links_box.pack_start(button, False, False, 0)

        widgets = [self]

        if self._sep:
            widgets.append(self._sep)

        if self.web_links and note_links:
            widgets.extend(
                [self.separator, self.notes_links_box, self.web_links_box]
            )
            utils.unhide_widgets(widgets)
        elif note_links:
            widgets.append(self.notes_links_box)
            utils.unhide_widgets(widgets)
        elif self.web_links:
            widgets.append(self.web_links_box)
            utils.unhide_widgets(widgets)
