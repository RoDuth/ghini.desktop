# Copyright (c) 2005,2006,2007,2008,2009 Brett Adams <brett@belizebotanic.org>
# Copyright (c) 2012-2017 Mario Frasca <mario@anche.no>
# Copyright (c) 2021-2025 Ross Demuth <rossdemuth123@gmail.com>
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
Tags menu manager
"""
import logging

logger = logging.getLogger(__name__)

from collections.abc import Callable
from collections.abc import Sequence
from typing import Protocol

from gi.repository import Gio
from gi.repository import GLib
from gi.repository import Gtk
from sqlalchemy import func
from sqlalchemy.orm import Query
from sqlalchemy.orm import Session
from sqlalchemy.orm.session import object_session

import bauble
from bauble import db
from bauble import utils
from bauble.i18n import _
from bauble.view import SearchView
from bauble.view import get_search_view_selected

from ..model import Tag
from ..model import tag_objects
from ..model import untag_objects
from . import editor


class _TagsMenuManager:
    """Tag menu manager manages the state of the tags menu and SearchView
    context menu for all objects.

    Intended to be instantiated once and used as a global object.
    """

    ACTIVATED_ACTION_NAME = "tag_activated"
    REMOVE_CONTEXT_ACTION_NAME = "context_tag_remove"
    APPLY_CONTEXT_ACTION_NAME = "context_tag_apply"
    REMOVE_ACTIVE_ACTION_NAME = "remove_active_tag"
    APPLY_ACTIVE_ACTION_NAME = "apply_active_tag"
    TAG_ACTION_NAME = "tag_selection"

    def __init__(self) -> None:
        self.menu_pos: int | None = None
        self.active_tag_name: str | None = None
        self.apply_active_tag_action: Gio.SimpleAction | None = None
        self.remove_active_tag_action: Gio.SimpleAction | None = None
        self.select_tag_action: Gio.SimpleAction | None = None
        self.tag_selection_action: Gio.SimpleAction | None = None

        if bauble.gui:
            bauble.gui.add_action(
                self.APPLY_CONTEXT_ACTION_NAME,
                self.on_context_menu_apply_activated,
                param_type=GLib.VariantType("s"),
            )

            bauble.gui.add_action(
                self.REMOVE_CONTEXT_ACTION_NAME,
                self.on_context_menu_remove_activated,
                param_type=GLib.VariantType("s"),
            )

    def reset(self) -> None:
        """Initialize or replace Tags menu in main menu."""
        tags_menu = self.build_menu()

        if self.menu_pos is None:
            self.menu_pos = bauble.gui.add_menu(_("Tags"), tags_menu)
        else:
            bauble.gui.remove_menu(self.menu_pos)
            self.menu_pos = bauble.gui.add_menu(_("Tags"), tags_menu)

        self.refresh()

    def reset_active_tag_name(self) -> None:
        """Reset the active tag to latest by ID if current is not valid."""
        with db.Session() as session:
            active = None

            if self.active_tag_name:
                active = (
                    session.query(Tag)
                    .filter_by(tag=self.active_tag_name)
                    .first()
                )

            if not active:
                sub_query = session.query(func.max(Tag.id)).scalar_subquery()
                self.active_tag_name = (
                    session.query(Tag.tag).filter(Tag.id == sub_query).scalar()
                )

    def refresh(self, selected_values: list[db.Domain] | None = None) -> None:
        """Refresh the tag menu, set the active tag and enable/disable menu
        items.
        """
        self.reset_active_tag_name()

        if self.select_tag_action and self.active_tag_name:
            self.select_tag_action.set_state(
                GLib.Variant.new_string(self.active_tag_name)
            )

        selected_values = selected_values or get_search_view_selected()

        if not (
            self.apply_active_tag_action and self.remove_active_tag_action
        ):
            return

        if selected_values:
            if self.active_tag_name:
                self.apply_active_tag_action.set_enabled(True)
                self.remove_active_tag_action.set_enabled(True)
            if self.tag_selection_action:
                self.tag_selection_action.set_enabled(True)
        elif self.tag_selection_action:
            self.apply_active_tag_action.set_enabled(False)
            self.remove_active_tag_action.set_enabled(False)
            self.tag_selection_action.set_enabled(False)

    def on_tag_change_state(
        self, action: Gio.SimpleAction, tag_name: GLib.Variant
    ) -> None:
        action.set_state(tag_name)
        self.active_tag_name = tag_name.unpack()
        bauble.gui.send_command(f"tag={tag_name}")
        view = bauble.gui.get_view()
        if isinstance(view, SearchView):
            GLib.idle_add(
                view.results_view.expand_to_path, Gtk.TreePath.new_first()
            )
        self.refresh()

    @staticmethod
    def on_context_menu_apply_activated(
        _action, tag_name: GLib.Variant | None
    ) -> None:
        view = bauble.gui.get_view()

        if not isinstance(view, SearchView):
            return

        selected = view.get_selected_values()
        # unpack to python type
        if selected and tag_name:
            tag_objects(tag_name.unpack(), selected)
            view.update_bottom_notebook(selected)

    @staticmethod
    def on_context_menu_remove_activated(
        _action, tag_name: GLib.Variant | None
    ) -> None:
        view = bauble.gui.get_view()

        if not isinstance(view, SearchView):
            return

        selected = view.get_selected_values()
        if selected and tag_name:
            # unpack to python type
            untag_objects(tag_name.unpack(), selected)
            view.update_bottom_notebook(selected)

    def context_menu_callback(
        self, selected: Sequence[db.Domain]
    ) -> Gio.Menu | None:
        """Build the SearchView context menu tag section for the selected
        items.
        """
        if not selected:
            logger.warning("nothing selected bailing.")
            return None

        session = object_session(selected[0])

        if not isinstance(session, Session):
            logger.warning("no object session bailing.")
            return None

        section = Gio.Menu()
        tag_item = Gio.MenuItem.new(
            _("Tag Selection"), f"win.{self.TAG_ACTION_NAME}"
        )
        section.append_item(tag_item)

        query = session.query(Tag)
        # bail early if no tags
        if not query.first():
            logger.debug("no tags, not creating submenus.")
            return section

        apply_tags, remove_tags = self._apply_remove_tags(selected, query)

        if apply_tags:
            apply_submenu = Gio.Menu()
            section.append_submenu(_("Apply Tag"), apply_submenu)
            for tag in apply_tags:
                menu_item = Gio.MenuItem.new(
                    tag.tag.replace("_", "__"),
                    f"win.{self.APPLY_CONTEXT_ACTION_NAME}::{tag.tag}",
                )
                apply_submenu.append_item(menu_item)

        if remove_tags:
            remove_submenu = Gio.Menu()
            section.append_submenu(_("Remove Tag"), remove_submenu)

            for tag in remove_tags:
                menu_item = Gio.MenuItem.new(
                    tag.tag.replace("_", "__"),
                    f"win.{self.REMOVE_CONTEXT_ACTION_NAME}::{tag.tag}",
                )
                remove_submenu.append_item(menu_item)

        return section

    @staticmethod
    def _apply_remove_tags(
        selected: Sequence[db.Domain], query: Query
    ) -> tuple[list[Tag], list[Tag]]:
        all_tagged = None
        remove_tags = set()
        for item in selected:
            tags = Tag.attached_to(item)
            if all_tagged is None:
                all_tagged = set(tags)
            elif all_tagged:
                all_tagged.intersection_update(tags)
            remove_tags.update(tags)

        apply_tags = set()

        if all_tagged:
            query = query.filter(Tag.id.notin_([i.id for i in all_tagged]))

        for tag in query:
            apply_tags.add(tag)

        def lower(tag: Tag) -> str:
            return tag.tag.lower()

        return sorted(apply_tags, key=lower), sorted(remove_tags, key=lower)

    def build_menu(self) -> Gio.Menu:
        """build tags menu based on current data."""
        tags_menu = Gio.Menu()

        if bauble.gui:
            # set up actions
            if not self.tag_selection_action:
                self.tag_selection_action = bauble.gui.add_action(
                    self.TAG_ACTION_NAME, _on_add_tag_activated
                )

            if not self.apply_active_tag_action:
                self.apply_active_tag_action = bauble.gui.add_action(
                    self.APPLY_ACTIVE_ACTION_NAME,
                    self.on_apply_active_tag_activated,
                )

            if not self.remove_active_tag_action:
                self.remove_active_tag_action = bauble.gui.add_action(
                    self.REMOVE_ACTIVE_ACTION_NAME,
                    self.on_remove_active_tag_activated,
                )

        # tag selection
        add_tag_menu_item = Gio.MenuItem.new(
            _("Tag Selection"), f"win.{self.TAG_ACTION_NAME}"
        )

        app = Gio.Application.get_default()
        if isinstance(app, Gtk.Application):
            # tag selection
            app.set_accels_for_action(
                f"win.{self.TAG_ACTION_NAME}", ["<Control>t"]
            )
            # apply active tag
            app.set_accels_for_action(
                f"win.{self.APPLY_ACTIVE_ACTION_NAME}", ["<Control>y"]
            )
            # remove active tag
            app.set_accels_for_action(
                f"win.{self.REMOVE_ACTIVE_ACTION_NAME}", ["<Control><Shift>y"]
            )

        tags_menu.append_item(add_tag_menu_item)

        with db.Session() as session:
            query = session.query(Tag)
            has_tags = query.first()
            if has_tags:
                self.set_selection_tag_action()
                self.append_sections(tags_menu, query)

        return tags_menu

    def append_sections(self, tags_menu: Gio.Menu, query: Query) -> None:
        section = Gio.Menu()

        for tag in query.order_by(func.lower(Tag.tag)):
            menu_item = Gio.MenuItem.new(
                tag.tag.replace("_", "__"),
                f"win.{self.ACTIVATED_ACTION_NAME}::{tag.tag}",
            )
            section.append_item(menu_item)

        tags_menu.append_section(None, section)

        section = Gio.Menu()
        apply_active_tag_menu_item = Gio.MenuItem.new(
            _("Apply Active Tag"), f"win.{self.APPLY_ACTIVE_ACTION_NAME}"
        )
        remove_active_tag_menu_item = Gio.MenuItem.new(
            _("Remove Active Tag"), f"win.{self.REMOVE_ACTIVE_ACTION_NAME}"
        )
        section.append_item(apply_active_tag_menu_item)
        section.append_item(remove_active_tag_menu_item)

        tags_menu.append_section(None, section)

        if self.apply_active_tag_action:
            self.apply_active_tag_action.set_enabled(False)

        if self.remove_active_tag_action:
            self.remove_active_tag_action.set_enabled(False)

    def set_selection_tag_action(self) -> None:
        if not self.select_tag_action:
            # setup the select_tag_action only if there are existing tags.
            # Most likely little harm in leaving the action in place even
            # if all tags are deleted, the menu is unavailable anyway.
            # set a valid value for self.active_tag_name
            self.reset_active_tag_name()
            variant = GLib.Variant.new_string(self.active_tag_name or "")
            self.select_tag_action = Gio.SimpleAction.new_stateful(
                self.ACTIVATED_ACTION_NAME, variant.get_type(), variant
            )
            self.select_tag_action.connect(
                "change-state", self.on_tag_change_state
            )

            bauble.gui.window.add_action(self.select_tag_action)

    def toggle_tag(
        self,
        applying: Callable[[str, list], None],
        *,
        message_dialog: Callable[[str], None] = utils.message_dialog,
    ) -> None:
        view = bauble.gui.get_view()

        if not isinstance(view, SearchView):
            return

        selected = view.get_selected_values()

        if not selected:
            return

        if self.active_tag_name is None:
            msg = _("Please make sure a tag is active.")
            message_dialog(msg)
            return

        applying(self.active_tag_name, selected)
        view.update_bottom_notebook(selected)

    def on_apply_active_tag_activated(self, _action, _param) -> None:
        logger.debug(
            "you're applying %s to the selection", self.active_tag_name
        )
        self.toggle_tag(tag_objects)

    def on_remove_active_tag_activated(self, _action, _param) -> None:
        logger.debug(
            "you're removing %s from the selection", self.active_tag_name
        )
        self.toggle_tag(untag_objects)


class ItemsDialog(Protocol):
    def __init__(self, values: Sequence[db.Domain]) -> None: ...
    def start(self) -> None: ...
    def destroy(self) -> None: ...


def _on_add_tag_activated(
    _action,
    _param,
    *,
    dialog_cls: type[ItemsDialog] = editor.TagItemsDialog,
) -> None:
    # get the selection from the search view
    view = bauble.gui.get_view()
    if not isinstance(view, SearchView):
        return

    selected = view.get_selected_values()

    if not selected:
        return

    dialog = dialog_cls(selected)
    dialog.start()
    view.update_bottom_notebook(selected)
    dialog.destroy()


# should not be needed outside of this plugin
_tags_menu_manager = _TagsMenuManager()

reset: Callable[[], None] = _tags_menu_manager.reset
"""Reset the Tags menu."""

refresh: Callable[[list[db.Domain] | None], None] = _tags_menu_manager.refresh
"""Reset the Tags menu."""

context_menu_callback: Callable[[Sequence[db.Domain]], Gio.Menu | None] = (
    _tags_menu_manager.context_menu_callback
)
"""Return the context menu tag section for the supplied selected items."""
