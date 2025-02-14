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
Tags editor and associaated
"""
import logging

logger = logging.getLogger(__name__)

import os
import traceback
from collections.abc import Sequence
from typing import Callable

from gi.repository import Gdk
from gi.repository import Gtk
from sqlalchemy.orm import Session
from sqlalchemy.orm.session import object_session

import bauble
from bauble import db
from bauble import editor
from bauble import paths
from bauble import utils
from bauble.i18n import _
from bauble.view import Action

from ..model import Tag
from ..model import get_tag_ids
from ..model import tag_objects
from ..model import untag_objects
from . import menu_manager

# TODO switch to Gtk.Template?


class TagEditorPresenter(editor.GenericEditorPresenter):
    widget_to_field_map = {
        "tag_name_entry": "tag",
        "tag_desc_textbuffer": "description",
    }

    view_accept_buttons = [
        "tag_ok_button",
        "tag_cancel_button",
    ]

    def on_tag_desc_textbuffer_changed(self, widget, value=None):
        return editor.GenericEditorPresenter.on_textbuffer_changed(
            self, widget, value, attr="description"
        )


class TagItemGUI(editor.GenericEditorView):
    """Interface for tagging individual items in SearchView"""

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
            menu_manager.reset()
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
            menu_manager.reset()
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


def remove_callback(
    tags: Sequence[Tag],
    *,
    yes_no_dialog: Callable[[str], bool] | None = None,
    message_details_dialog: Callable[[str, str, int], bool] | None = None,
    menu_reset: Callable[[], None] | None = None,
) -> bool:
    """Remove the tags from selected items

    Notify user of any problems, update SearchView and reset tags menu.
    """
    yes_no_dialog = yes_no_dialog or utils.yes_no_dialog
    message_details_dialog = (
        message_details_dialog or utils.message_details_dialog
    )
    menu_reset = menu_reset or menu_manager.reset

    tag = tags[0]

    session = object_session(tag)

    if not isinstance(session, Session):
        logger.warning("no object session aborting.")
        return False

    tlst = []

    for tag in tags:
        tlst.append(f"{tag.__class__.__name__}: {utils.xml_safe(tag)}")

    msg = _("Are you sure you want to remove %s?") % ", ".join(i for i in tlst)
    if not yes_no_dialog(msg):
        return False

    for tag in tags:
        session.delete(tag)
    try:
        utils.remove_from_results_view(tags)
        session.commit()
    except Exception as e:  # pylint: disable=broad-except
        msg = _("Could not delete.\n\n%s") % utils.xml_safe(e)
        message_details_dialog(
            msg, traceback.format_exc(), Gtk.MessageType.ERROR
        )
        session.rollback()

    # reinitialize the tag menu
    menu_reset()
    return True


def edit_callback(tags: Sequence[Tag]) -> int:
    """Edit a tag."""
    tag = tags[0]

    if tag is None:
        tag = Tag()

    view = editor.GenericEditorView(
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
        menu_manager.reset()

    presenter.cleanup()
    return error_state


_edit_action = Action(
    "tag_edit", _("_Edit"), callback=edit_callback, accelerator="<ctrl>e"
)

_remove_action = Action(
    "tag_remove",
    _("_Delete"),
    callback=remove_callback,
    accelerator="<ctrl>Delete",
    multiselect=True,
)

tag_context_menu = [_edit_action, _remove_action]
