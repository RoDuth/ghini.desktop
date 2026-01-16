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
MenuButton widget to dsiplay web links.
"""

from gi.repository import Gio
from gi.repository import Gtk

from bauble import db
from bauble import prefs
from bauble.i18n import _
from bauble.utils import desktop
from bauble.utils import hide_widgets
from bauble.utils.web import FIELD_RE
from bauble.utils.web import LinkDict
from bauble.utils.web import get_formatted_url_for_obj
from bauble.utils.web import update_deprecated_forms


class LinksMenuButton(Gtk.MenuButton):
    """MenuButton widget for use in editors to make web links available from
    within the editor.

    To use, include the widget, either in the ``.ui`` file or directly then
    call ``init`` on instantiation supplying the model and
    preference key pointing to the web link definitions. e.g.::

        FOO_WEB_LINKS_PREFS = "web_button_defs.foo"

        @Gtk.Template(filename="/path/to/file.ui"))
        class Foo(Gtk.Dialog):

            __gtype_name__ = "Foo"

            link_menu_btn = cast(LinksMenuButton, Gtk.Template.Child())

            def __init__(self, model: FooModel) -> None:
                super().__init__()

                self.link_menu_btn.init(model, FOO_WEB_LINKS_PREFS)

    """

    __gtype_name__ = "LinksMenuButton"

    def __init__(self) -> None:
        super().__init__()
        self.model: db.Domain

    def init(self, model: db.Domain, links_pref_key: str) -> None:
        """Initialise the menu button adding any links with `editor_button` set
        to True
        """
        self.model = model

        self.setup_menu(links_pref_key)
        self.set_image_tooltip()
        # ensure destroys with parent
        parent = self.get_parent()
        if parent:
            parent.connect("destroy", self.on_destroy)

    def setup_menu(self, links_pref_key: str) -> None:
        menu = Gio.Menu()
        action_name = self.model.__tablename__.lower() + "_link"
        action_group = Gio.SimpleActionGroup()

        menu_has_items = False
        for name, link in sorted(prefs.prefs.itersection(links_pref_key)):
            if not (isinstance(name, str) and isinstance(link, dict)):
                continue

            if not link.get("editor_button"):
                continue

            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", self.on_item_selected, link)
            action_group.add_action(action)
            menu_item = Gio.MenuItem.new(
                link.get("title"), f"{action_name}.{name}"
            )
            menu.append_item(menu_item)
            menu_has_items = True

        if menu_has_items:
            self.set_menu_model(menu)
            self.insert_action_group(action_name, action_group)
        else:
            hide_widgets([self])

    def set_image_tooltip(self) -> None:
        image = Gtk.Image.new_from_icon_name(
            "open-menu-symbolic",
            Gtk.IconSize.BUTTON,
        )
        tooltip = _(
            "Links Menu - the items here are a selection of the Links "
            "available in the search results view info box (right hand pane) "
            "for the same type.  You can include others by adding:\n"
            "\t'editor_button': True\n"
            "to their definitions in the preferences."
        )
        self.set_tooltip_text(tooltip)
        self.set_image(image)

    def on_item_selected(self, _action, _param, link: LinkDict) -> None:
        url = self.get_url(link)
        if url:
            desktop.open(url)

    def get_url(self, link: LinkDict) -> str | None:
        _base_uri = link.get("_base_uri")

        if not _base_uri:
            return None

        base_uri = update_deprecated_forms(_base_uri)
        fields = FIELD_RE.findall(base_uri)
        return get_formatted_url_for_obj(base_uri, fields, self.model)

    def on_destroy(self, _parent: Gtk.Widget) -> None:
        self.destroy()
