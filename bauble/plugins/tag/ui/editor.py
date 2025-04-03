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

import traceback
from collections.abc import Sequence
from pathlib import Path
from typing import Callable
from typing import Protocol
from typing import cast

from gi.repository import Gtk
from sqlalchemy.orm import Session
from sqlalchemy.orm.session import object_session

import bauble
from bauble import db
from bauble import editor
from bauble import error
from bauble import utils
from bauble.i18n import _
from bauble.view import Action

from ..model import Tag
from ..model import get_tag_ids
from ..model import tag_objects
from ..model import untag_objects
from . import menu_manager


@Gtk.Template(filename=str(Path(__file__).resolve().parent / "tag_editor.ui"))
class TagEditorDialog(editor.GenericPresenter, Gtk.Dialog):

    __gtype_name__ = "TagEditorDialog"

    tag_name_entry = cast(Gtk.Entry, Gtk.Template.Child())
    tag_desc_textbuffer = cast(Gtk.TextBuffer, Gtk.Template.Child())

    def __init__(self, model: Tag) -> None:
        super().__init__(model, self)
        self.widgets_to_model_map = {
            self.tag_name_entry: "tag",
            self.tag_desc_textbuffer: "description",
        }
        self.set_transient_for(bauble.gui.window)
        self.set_destroy_with_parent(True)

        self.tag_name_entry.grab_focus()
        self.refresh_all_widgets_from_model()
        self.tag_name_entry.emit("changed")

    @Gtk.Template.Callback()
    def on_text_buffer_changed(self, buffer: Gtk.TextBuffer) -> None:
        super().on_text_buffer_changed(buffer)

    @Gtk.Template.Callback()
    def on_tag_entry_changed(self, entry: Gtk.Entry) -> None:
        super().on_unique_text_entry_changed(entry)


@Gtk.Template(filename=str(Path(__file__).resolve().parent / "tag_items.ui"))
class TagItemsDialog(Gtk.Dialog):

    __gtype_name__ = "TagItemsDialog"

    tag_tree = cast(Gtk.TreeView, Gtk.Template.Child())
    items_data_label = cast(Gtk.Label, Gtk.Template.Child())
    delete_button = cast(Gtk.Button, Gtk.Template.Child())
    toggle_renderer = cast(Gtk.CellRendererToggle, Gtk.Template.Child())

    def __init__(self, selected: Sequence[db.Domain]) -> None:
        super().__init__()

        self.set_transient_for(bauble.gui.window)
        self.set_destroy_with_parent(True)
        self.selected_model_row: tuple[Gtk.ListStore, Gtk.TreeIter] | None = (
            None
        )

        self.selected = selected

        if not selected:
            logger.warning("No selection provided.")
            raise error.BaubleError("selected not provided")

        self.items_data_label.set_text(
            ",  ".join([str(s) for s in self.selected])
        )

    @Gtk.Template.Callback()
    def on_new_button_clicked(
        self,
        *_args,
        edit_func: Callable[[Sequence[Tag]], None] | None = None,
    ) -> None:
        """create a new tag"""

        editor_func = edit_func or edit_callback

        with db.Session() as session:
            tag = Tag()
            session.add(tag)
            response = editor_func([tag])

            if response:
                model = self.tag_tree.get_model()

                if isinstance(model, Gtk.ListStore):
                    itr = model.append([False, False, tag.tag])
                    path = model.get_path(itr)
                    self.tag_tree.set_cursor(path)
                    self.toggle_renderer.emit("toggled", str(path))

                menu_manager.reset()

    @Gtk.Template.Callback()
    def on_tag_toggled(
        self, renderer: Gtk.CellRendererToggle, path: str
    ) -> None:
        active = not renderer.get_active()
        model = self.tag_tree.get_model()

        if not model:
            return

        itr = model.get_iter(path)

        model[itr][0] = active
        model[itr][1] = False

        name = model[itr][2]
        if active:
            tag_objects(name, self.selected)
        else:
            untag_objects(name, self.selected)

    def start(self) -> None:

        tag_all, tag_some = get_tag_ids(self.selected)

        model = self.tag_tree.get_model()

        if not isinstance(model, Gtk.ListStore):
            return

        with db.Session() as session:
            for tag in session.query(Tag):
                model.append([tag.id in tag_all, tag.id in tag_some, tag.tag])

        self.run()

    @Gtk.Template.Callback()
    def on_selection_changed(self, tree_selection: Gtk.TreeSelection) -> None:
        model, row = tree_selection.get_selected()

        self.delete_button.set_sensitive(bool(model and row))

        if isinstance(model, Gtk.ListStore) and row:
            self.selected_model_row = (model, row)

    @Gtk.Template.Callback()
    def on_delete_button_clicked(
        self,
        _button,
        *,
        yn_dialog: Callable[[str], bool] | None = None,
    ) -> None:

        model = tree_iter = tag_name = None
        if self.selected_model_row:
            model, tree_iter = self.selected_model_row
            tag_name = model[tree_iter][2]
        else:
            return

        yn_dialog = yn_dialog or utils.yes_no_dialog

        msg = _('Are you sure you want to delete the tag: "%s"?') % tag_name

        if not yn_dialog(msg):
            return

        with db.Session() as session:
            tag = session.query(Tag).filter_by(tag=tag_name).one()
            session.delete(tag)
            session.commit()

        model.remove(tree_iter)
        menu_manager.reset()

        view = bauble.gui.get_view()
        if view:
            view.update()


def remove_callback(
    objs: Sequence[Tag],
    **kwargs,
) -> bool:
    """Remove the tags from selected items

    Notify user of any problems, update SearchView and reset tags menu.
    """
    yes_no_dialog: Callable[[str], bool] = kwargs.get(
        "yes_no_dialog", utils.yes_no_dialog
    )
    message_details_dialog: Callable[[str, str, int], bool] = kwargs.get(
        "message_details_dialog",
        utils.message_details_dialog,
    )
    menu_reset: Callable[[], None] = kwargs.get(
        "menu_reset", menu_manager.reset
    )

    tags = objs
    tag = tags[0]

    session = object_session(tag)

    if not isinstance(session, Session):
        logger.warning("no object session bailing.")
        return False

    tlst = []

    for tag in tags:
        tlst.append(f"{tag.__class__.__name__}: {utils.xml_safe(tag)}")

    msg = _("Are you sure you want to remove %s?") % ", ".join(i for i in tlst)
    if not yes_no_dialog(msg):
        return False

    for tag in tags:
        try:
            session.delete(tag)
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


class TagDialog(Protocol):
    def __init__(self, model: db.Domain) -> None: ...
    def run(self) -> Gtk.ResponseType: ...
    def destroy(self) -> None: ...


def edit_callback(
    objs: Sequence[Tag],
    **kwargs,
) -> bool:
    """Edit a tag."""
    tag = objs[0]
    dialog_cls: type[TagDialog] = kwargs.get("dialog_cls", TagEditorDialog)

    session = object_session(tag)

    if isinstance(session, Session):
        dialog = dialog_cls(tag)
        response = dialog.run()

        if response == Gtk.ResponseType.OK:
            session.commit()
        else:
            session.rollback()

        dialog.destroy()
    else:
        raise error.DatabaseError("Could not connect to database session.")

    return response == Gtk.ResponseType.OK


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
