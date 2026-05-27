# Copyright (c) 2005,2006,2007,2008,2009 Brett Adams <brett@belizebotanic.org>
# Copyright (c) 2012-2017 Mario Frasca <mario@anche.no>
# Copyright (c) 2021-2026 Ross Demuth <rossdemuth123@gmail.com>
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
Tags editor and associated
"""
import logging

logger = logging.getLogger(__name__)

from collections.abc import Sequence
from pathlib import Path
from typing import Self
from typing import cast

from gi.repository import GLib
from gi.repository import Gspell
from gi.repository import Gtk
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

import bauble
from bauble import db
from bauble import error
from bauble.i18n import _
from bauble.ui import dialogs
from bauble.ui import idle_garbage_collect
from bauble.ui.presenter import DomainEditorDialog
from bauble.ui.presenter import EditCreateCallback
from bauble.ui.presenter import Response
from bauble.ui.views import get_search_view
from bauble.utils import xml_safe

from ..model import Tag
from ..model import get_tag_ids
from ..model import tag_objects
from ..model import untag_objects
from . import menu_manager


@Gtk.Template(filename=str(Path(__file__).resolve().parent / "tag_editor.ui"))
class TagEditorDialog(
    DomainEditorDialog[Tag],
    Gtk.Dialog,
):  # pylint: disable=not-callable

    __gtype_name__ = "TagEditorDialog"

    name_entry = cast(Gtk.Entry, Gtk.Template.Child())
    description_textview = cast(Gtk.TextView, Gtk.Template.Child())
    description_textbuffer = cast(Gtk.TextBuffer, Gtk.Template.Child())

    def __init__(
        self,
        model: Tag,
        session: Session,
        transient_for: Gtk.Window | None = None,
    ) -> None:

        super().__init__(model, session, transient_for=transient_for)

        self.widgets_to_model_map = {
            self.name_entry: "tag",
            self.description_textbuffer: "description",
        }

        self.refresh_all_widgets_from_model()

        spell_view = Gspell.TextView.get_from_gtk_text_view(
            self.description_textview
        )
        spell_view.basic_setup()

        self.name_entry.emit("changed")

    @property
    def can_commit(self) -> bool:
        modified = self.session.is_modified(self.model)

        no_problems = not self.problems

        return all((modified, no_problems))

    @Gtk.Template.Callback()
    def on_text_buffer_changed(self, buffer: Gtk.TextBuffer) -> None:
        super().on_text_buffer_changed(buffer)

    @Gtk.Template.Callback()
    def on_tag_entry_changed(self, entry: Gtk.Entry) -> None:
        super().on_unique_text_entry_changed(entry)

    @Gtk.Template.Callback()
    def on_response(
        self,
        dialog: Self,
        response: Response,
    ) -> bool:
        name = str(response)
        if response in Response:
            name = Response(response).name

        logger.debug("Response: %s", name)

        if response == Response.OK:
            logger.debug("committing")
            if self.do_commit() is False:
                logger.debug("commit failed")
                dialog.stop_emission_by_name("response")
                return True

        elif response == Response.CANCEL:
            # most likely not needed
            self.session.rollback()
            self.session.close()

        if not self.get_modal():
            # allow chaining response signal
            GLib.idle_add(self.destroy)

        return False


@Gtk.Template(filename=str(Path(__file__).resolve().parent / "tag_items.ui"))
class TagItemsDialog(Gtk.Dialog):

    __gtype_name__ = "TagItemsDialog"

    tag_tree = cast(Gtk.TreeView, Gtk.Template.Child())
    items_data_label = cast(Gtk.Label, Gtk.Template.Child())
    delete_button = cast(Gtk.Button, Gtk.Template.Child())
    ok_button = cast(Gtk.Button, Gtk.Template.Child())
    toggle_renderer = cast(Gtk.CellRendererToggle, Gtk.Template.Child())

    def __init__(
        self,
        selected: Sequence[db.Domain],
        session: Session,
    ) -> None:
        super().__init__()

        self.set_transient_for(bauble.gui.window)
        self.set_destroy_with_parent(True)
        self.selected_model_row: tuple[Gtk.ListStore, Gtk.TreeIter] | None
        self.selected_model_row = None

        self.session = session
        self.selected = [self.session.merge(i) for i in selected]

        if not selected:
            logger.warning("No selection provided.")
            raise error.BaubleError("selected not provided")

        self.items_data_label.set_text(
            ",  ".join([str(s) for s in self.selected])
        )

        self.update()

    @property
    def can_commit(self) -> bool:
        if self.session.new or self.session.deleted:
            return True

        return any(self.session.is_modified(i) for i in self.session.dirty)

    def update(self) -> None:
        self.ok_button.set_sensitive(self.can_commit)

    @Gtk.Template.Callback()
    def on_new_button_clicked(self, _button: Gtk.Button) -> None:
        """create a new tag"""

        dialog = TagEditorDialog(Tag(), db.Session(), transient_for=self)
        response = dialog.run()

        if response == Response.OK:
            tag = self.session.merge(dialog.model)
            model = self.tag_tree.get_model()

            if isinstance(model, Gtk.ListStore):
                itr = model.append([False, False, tag.tag, tag.description])
                path = model.get_path(itr)
                self.tag_tree.set_cursor(path)
                self.toggle_renderer.emit("toggled", str(path))

            menu_manager.reset()

        dialog.destroy()

        self.update()

    @Gtk.Template.Callback()
    def on_tag_toggled(
        self,
        renderer: Gtk.CellRendererToggle,
        path: str,
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
            tag_objects(name, self.selected, commit=False)
        else:
            untag_objects(name, self.selected, commit=False)

        self.update()

    def start(self) -> None:

        tag_all, tag_some = get_tag_ids(self.selected)

        model = cast(Gtk.ListStore, self.tag_tree.get_model())

        for tag in self.session.scalars(select(Tag)):
            model.append(
                [
                    tag.id in tag_all,
                    tag.id in tag_some,
                    tag.tag,
                    tag.description,
                ]
            )

        self.show()

    @Gtk.Template.Callback()
    def on_response(
        self,
        dialog: Self,
        response: Response,
    ) -> None:

        if response == Response.OK:
            logger.debug("committing")
            try:
                self.session.commit()
            except SQLAlchemyError as e:
                msg = _("Error committing changes.\n\n%s") % xml_safe(e)
                dialogs.message_dialog(
                    msg,
                    Gtk.MessageType.ERROR,
                    parent=self,
                )
                self.session.rollback()

        if not self.get_modal():
            GLib.idle_add(dialog.destroy)

        self.session.close()

        get_search_view().update()

        idle_garbage_collect()

    @Gtk.Template.Callback()
    def on_selection_changed(self, tree_selection: Gtk.TreeSelection) -> None:
        model, row = tree_selection.get_selected()

        self.delete_button.set_sensitive(bool(model and row))

        if isinstance(model, Gtk.ListStore) and row:
            self.selected_model_row = (model, row)

    @Gtk.Template.Callback()
    def on_delete_button_clicked(self, _button: Gtk.Button) -> None:

        model = tree_iter = tag_name = None
        if self.selected_model_row:
            model, tree_iter = self.selected_model_row
            tag_name = model[tree_iter][2]
        else:
            return

        msg = _('Are you sure you want to delete the tag: "%s"?') % tag_name

        if not dialogs.yes_no_dialog(msg):
            return

        tag = self.session.query(Tag).filter_by(tag=tag_name).one()
        self.session.delete(tag)

        self.update()

        model.remove(tree_iter)
        menu_manager.reset()


edit_callback = EditCreateCallback(
    TagEditorDialog,
    Tag,
)
