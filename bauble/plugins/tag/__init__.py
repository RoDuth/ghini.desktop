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
Tag plugin
"""

import logging
import os
import traceback
from collections.abc import Callable
from collections.abc import Sequence

logger = logging.getLogger(__name__)

from gi.repository import Gdk
from gi.repository import Gio
from gi.repository import GLib
from gi.repository import Gtk
from sqlalchemy import func
from sqlalchemy.orm import Query
from sqlalchemy.orm import Session
from sqlalchemy.orm.session import object_session

import bauble
from bauble import db
from bauble import editor
from bauble import paths
from bauble import pluginmgr
from bauble import search
from bauble import utils
from bauble.editor import GenericEditorPresenter
from bauble.editor import GenericEditorView
from bauble.i18n import _
from bauble.view import Action
from bauble.view import HistoryView
from bauble.view import InfoBox
from bauble.view import InfoExpander
from bauble.view import PropertiesExpander
from bauble.view import SearchView
from bauble.view import get_search_view_selected

from .model import Tag
from .model import get_tag_ids
from .model import tag_objects
from .model import untag_objects


class TagsMenuManager:
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
        """initialize or replace Tags menu in main menu."""
        tags_menu = self.build_menu()

        if self.menu_pos is None:
            self.menu_pos = bauble.gui.add_menu(_("Tags"), tags_menu)
        else:
            bauble.gui.remove_menu(self.menu_pos)
            self.menu_pos = bauble.gui.add_menu(_("Tags"), tags_menu)

        self.refresh()

    def reset_active_tag_name(self) -> None:
        """Reset the active tag to latest by ID if current is not valid."""
        if not db.Session:
            logger.warning("reset_active_tag_name: no session bailing.")
            return

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

    def refresh(self, selected_values: list[db.Base] | None = None) -> None:
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
        _action, tag_name: GLib.Variant
    ) -> None:
        view = bauble.gui.get_view()

        if not isinstance(view, SearchView):
            return

        selected = view.get_selected_values()
        # unpack to python type
        if selected:
            tag_objects(tag_name.unpack(), selected)
            view.update_bottom_notebook(selected)

    @staticmethod
    def on_context_menu_remove_activated(
        _action, tag_name: GLib.Variant
    ) -> None:
        view = bauble.gui.get_view()

        if not isinstance(view, SearchView):
            return

        selected = view.get_selected_values()
        if selected:
            # unpack to python type
            untag_objects(tag_name.unpack(), selected)
            view.update_bottom_notebook(selected)

    def context_menu_callback(
        self, selected: Sequence[db.Base]
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
        selected: Sequence[db.Base], query: Query
    ) -> tuple[set[Tag], set[Tag]]:
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

        return apply_tags, remove_tags

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

        if db.Session:
            with db.Session() as session:
                query = session.query(Tag)
                has_tags = query.first()
                if has_tags:
                    self.set_selection_tag_action()
                    self.append_sections(tags_menu, query)

        return tags_menu

    def append_sections(self, tags_menu: Gio.Menu, query: Query) -> None:
        section = Gio.Menu()

        for tag in query.order_by(Tag.tag):
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

    def toggle_tag(self, applying: Callable[[str, list], None]) -> None:
        view = bauble.gui.get_view()
        selected: list[db.Base] | None = None

        def warn():
            msg = _(
                "In order to tag or untag an item you must first search "
                "for something."
            )
            bauble.gui.show_message_box(msg)

        if isinstance(view, SearchView):
            selected = view.get_selected_values()
        else:
            warn()
            return

        if not selected:
            warn()
            return

        if self.active_tag_name is None:
            msg = _("Please make sure a tag is active.")
            print(msg)
            utils.message_dialog(msg)
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


tags_menu_manager = TagsMenuManager()


def edit_callback(tags: Sequence[Tag]) -> int:
    tag = tags[0]

    if tag is None:
        tag = Tag()

    view = GenericEditorView(
        os.path.join(paths.lib_dir(), "plugins", "tag", "tag.glade"),
        parent=None,
        root_widget_name="tag_dialog",
    )
    presenter = TagEditorPresenter(tag, view, refresh_view=True)
    error_state = presenter.start()

    if error_state:
        presenter.session.rollback()
    else:
        presenter.commit_changes()
        tags_menu_manager.reset()

    presenter.cleanup()
    return error_state


def remove_callback(tags: Sequence[Tag]) -> bool:
    tag = tags[0]

    session = object_session(tag)

    if not isinstance(session, Session):
        logger.warning("no object session aborting.")
        return False

    tlst = []

    for tag in tags:
        tlst.append(f"{tag.__class__.__name__}: {utils.xml_safe(tag)}")

    msg = _("Are you sure you want to remove %s?") % ", ".join(i for i in tlst)
    if not utils.yes_no_dialog(msg):
        return False

    for tag in tags:
        session.delete(tag)
    try:
        utils.remove_from_results_view(tags)
        session.commit()
    except Exception as e:  # pylint: disable=broad-except
        msg = _("Could not delete.\n\n%s") % utils.xml_safe(e)
        utils.message_details_dialog(
            msg, traceback.format_exc(), Gtk.MessageType.ERROR
        )
        session.rollback()

    # reinitialize the tag menu
    tags_menu_manager.reset()
    return True


edit_action = Action(
    "tag_edit", _("_Edit"), callback=edit_callback, accelerator="<ctrl>e"
)

remove_action = Action(
    "tag_remove",
    _("_Delete"),
    callback=remove_callback,
    accelerator="<ctrl>Delete",
    multiselect=True,
)

tag_context_menu = [edit_action, remove_action]


class TagEditorPresenter(GenericEditorPresenter):
    widget_to_field_map = {
        "tag_name_entry": "tag",
        "tag_desc_textbuffer": "description",
    }

    view_accept_buttons = [
        "tag_ok_button",
        "tag_cancel_button",
    ]

    def on_tag_desc_textbuffer_changed(self, widget, value=None):
        return GenericEditorPresenter.on_textbuffer_changed(
            self, widget, value, attr="description"
        )


class TagItemGUI(editor.GenericEditorView):
    """Interface for tagging individual items in the results of the SearchView"""

    def __init__(self, values):
        filename = os.path.join(paths.lib_dir(), "plugins", "tag", "tag.glade")
        super().__init__(filename)
        self.item_data_label = self.widgets.items_data
        self.values = values
        self.item_data_label.set_text(", ".join([str(s) for s in self.values]))
        self.connect(
            self.widgets.new_button, "clicked", self.on_new_button_clicked
        )
        self.tag_tree = self.widgets.tag_tree

    def get_window(self):
        return self.widgets.tag_item_dialog

    def on_new_button_clicked(self, *_args):
        """create a new tag"""
        session = db.Session()
        tag = Tag(description="")
        session.add(tag)
        error_state = edit_callback([tag])
        if not error_state:
            model = self.tag_tree.get_model()
            model.append([False, tag.tag, False])
            tags_menu_manager.reset()
        session.close()

    def on_toggled(self, renderer, path):
        """tag or untag the objs in self.values"""
        active = not renderer.get_active()
        model = self.tag_tree.get_model()
        itr = model.get_iter(path)
        model[itr][0] = active
        model[itr][2] = False
        name = model[itr][1]
        if active:
            tag_objects(name, self.values)
        else:
            untag_objects(name, self.values)

    def build_tag_tree_columns(self):
        """Build the tag tree columns."""
        renderer = Gtk.CellRendererToggle()
        self.connect(renderer, "toggled", self.on_toggled)
        renderer.set_property("activatable", True)
        toggle_column = Gtk.TreeViewColumn(None, renderer)
        toggle_column.add_attribute(renderer, "active", 0)
        toggle_column.add_attribute(renderer, "inconsistent", 2)

        renderer = Gtk.CellRendererText()
        tag_column = Gtk.TreeViewColumn(None, renderer, text=1)

        return [toggle_column, tag_column]

    def on_key_released(self, _widget, event):
        """When the user hits the delete key on a selected tag in the tag
        editor delete the tag
        """
        keyname = Gdk.keyval_name(event.keyval)

        if keyname != "Delete":
            return

        model, row_iter = self.tag_tree.get_selection().get_selected()
        tag_name = model[row_iter][1]
        msg = _('Are you sure you want to delete the tag "%s"?') % tag_name

        if not utils.yes_no_dialog(msg):
            return

        session = db.Session()
        try:
            query = session.query(Tag)
            tag = query.filter_by(tag=str(tag_name)).one()
            session.delete(tag)
            session.commit()
            model.remove(row_iter)
            tags_menu_manager.reset()
            view = bauble.gui.get_view()
            if hasattr(view, "update"):
                view.update()
        except Exception as e:
            utils.message_details_dialog(
                utils.xml_safe(str(e)),
                traceback.format_exc(),
                Gtk.MessageType.ERROR,
            )
        finally:
            session.close()

    def start(self):
        # we remove the old columns and create new ones each time the
        # tag editor is started since we have to connect and
        # disconnect the toggled signal each time
        for col in self.tag_tree.get_columns():
            self.tag_tree.remove_column(col)
        columns = self.build_tag_tree_columns()
        for col in columns:
            self.tag_tree.append_column(col)

        # create the model
        model = Gtk.ListStore(bool, str, bool)
        tag_all, tag_some = get_tag_ids(self.values)
        with db.Session() as session:
            for tag in session.query(Tag):
                model.append([tag.id in tag_all, tag.tag, tag.id in tag_some])

        self.tag_tree.set_model(model)

        self.tag_tree.add_events(Gdk.EventMask.KEY_RELEASE_MASK)
        self.connect(self.tag_tree, "key-release-event", self.on_key_released)

        response = self.get_window().run()
        while response not in (
            Gtk.ResponseType.OK,
            Gtk.ResponseType.DELETE_EVENT,
        ):
            response = self.get_window().run()

        self.get_window().hide()
        self.disconnect_all()


def _on_add_tag_activated(_action, _param) -> None:
    # get the selection from the search view
    view = bauble.gui.get_view()

    def warn():
        msg = _(
            "In order to tag or untag an item you must first search "
            "for something."
        )
        bauble.gui.show_message_box(msg)

    if isinstance(view, SearchView):
        selected = view.get_selected_values()
    else:
        warn()
        return

    if not selected:
        warn()
        return

    tagitem = TagItemGUI(selected)
    tagitem.start()
    view.update_bottom_notebook(selected)


class GeneralTagExpander(InfoExpander):
    """
    generic information about a tag.  Displays the tag name, description and a
    table of the types and count(with link) of tagged items.
    """

    def __init__(self, widgets):
        super().__init__(_("General"), widgets)
        general_box = self.widgets.general_box
        self.widgets.general_window.remove(general_box)
        self.vbox.pack_start(general_box, True, True, 0)
        self.table_cells = []

    def update(self, row):
        self.widget_set_value("ib_name_label", row.tag)
        self.widget_set_value("ib_description_label", row.description)
        objects = row.objects
        classes = set(type(o) for o in objects)
        row_no = 1
        grid = self.widgets.tag_ib_general_grid

        for widget in self.table_cells:
            grid.remove(widget)

        self.table_cells = []
        for cls in classes:
            obj_ids = [str(o.id) for o in objects if isinstance(o, cls)]
            lab = Gtk.Label()
            lab.set_xalign(0)
            lab.set_yalign(0.5)
            lab.set_text(cls.__name__)
            grid.attach(lab, 0, row_no, 1, 1)

            eventbox = Gtk.EventBox()
            label = Gtk.Label()
            label.set_xalign(0)
            label.set_yalign(0.5)
            eventbox.add(label)
            grid.attach(eventbox, 1, row_no, 1, 1)
            label.set_text(f" {len(obj_ids)} ")
            utils.make_label_clickable(
                label,
                lambda _l, _e, x: bauble.gui.send_command(x),
                f'{cls.__name__.lower()} where id in {", ".join(obj_ids)}',
            )

            self.table_cells.append(lab)
            self.table_cells.append(eventbox)

            row_no += 1
        grid.show_all()


class TagInfoBox(InfoBox):
    """
    - general info
    - source
    """

    def __init__(self):
        super().__init__()
        filename = os.path.join(paths.lib_dir(), "plugins", "tag", "tag.glade")
        self.widgets = utils.load_widgets(filename)
        self.general = GeneralTagExpander(self.widgets)
        self.add_expander(self.general)
        self.props = PropertiesExpander()
        self.add_expander(self.props)

    def update(self, row):
        self.general.update(row)
        self.props.update(row)


class TagPlugin(pluginmgr.Plugin):
    provides = {"Tag": Tag}

    @classmethod
    def init(cls):
        pluginmgr.provided.update(cls.provides)
        from functools import partial

        mapper_search = search.strategies.get_strategy("MapperSearch")
        mapper_search.add_meta(("tag", "tags"), Tag, ["tag"])
        SearchView.row_meta[Tag].set(
            children=partial(
                db.get_active_children, partial(db.natsort, "objects")
            ),
            infobox=TagInfoBox,
            context_menu=tag_context_menu,
            activated_callback=edit_callback,
        )
        tag_meta = {
            "page_widget": "taginfo_scrolledwindow",
            "fields_used": ["tag", "description"],
            "glade_name": os.path.join(
                paths.lib_dir(), "plugins/tag/tag.glade"
            ),
            "name": _("Tags"),
            "row_activated": cls.on_tag_bottom_info_activated,
        }
        # Only want to add this once (incase of opening another connection),
        # hence directly accessing underlying dict with setdefault
        # If no 'label' key in the Meta object add_page_to_bottom_notebook will
        # be called again adding another page.
        SearchView.bottom_info.data.setdefault(Tag, tag_meta)
        SearchView.context_menu_callbacks.add(
            tags_menu_manager.context_menu_callback
        )
        SearchView.cursor_changed_callbacks.add(tags_menu_manager.refresh)

        if bauble.gui:
            bauble.gui.set_view_callbacks.add(tags_menu_manager.refresh)
            tags_menu_manager.reset()

        HistoryView.add_translation_query(
            "tagged_obj", "tag", "{table} where objects_.id = {obj_id}"
        )

    @staticmethod
    def on_tag_bottom_info_activated(tree, path, _column):
        tag = repr(tree.get_model()[path][0])
        bauble.gui.send_command(f"tag={tag}")


plugin = TagPlugin
