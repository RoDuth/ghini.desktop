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
Family GUI editor parts.
"""

import logging

logger = logging.getLogger(__name__)

import traceback
from collections.abc import Sequence
from pathlib import Path
from typing import Self
from typing import cast

from gi.repository import GLib
from gi.repository import Gtk
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.orm.session import object_session

import bauble
from bauble import db
from bauble import utils
from bauble.i18n import _
from bauble.ui.handlers import EntryWCompletionHandler
from bauble.ui.handlers import populate_enum_combo
from bauble.ui.presenter import AddCallback
from bauble.ui.presenter import EditCreateCallback
from bauble.ui.presenter import GenericPresenter
from bauble.ui.presenter import Problem
from bauble.ui.presenter import Response
from bauble.ui.presenter import default_dialog_update
from bauble.ui.widgets import LinksMenuButton
from bauble.ui.widgets import NotesPresenter

from ..family import Family
from ..family import FamilySynonym
from ..genus import Genus
from .genus_editor import GenusEditorDialog
from .widgets import SynonymsPresenter

FAMILY_WEB_BUTTON_DEFS_PREFS = "web_button_defs.family"


def validate_unique_family(
    epithet: str,
    author: str,
    qualifier: str,
    model: Family,
) -> bool:
    # pylint: disable=unused-argument
    """Validate that the family, author and qualifier combination is unique"""

    with db.Session() as session:

        model = session.merge(model)
        exists = (
            session.query(Family)
            .filter(Family.epithet == epithet)
            .filter(Family.author == author)
            .filter(Family.qualifier == qualifier)
            .one_or_none()
        )

        if exists is not None and exists is not model:
            return False
    return True


@Gtk.Template(
    filename=str(Path(__file__).resolve().parent / "family_editor.ui")
)
class FamilyEditorDialog(
    GenericPresenter[Family],
    Gtk.Dialog,
):  # pylint: disable=not-callable

    __gtype_name__ = "FamilyEditorDialog"

    notebook = cast(Gtk.Notebook, Gtk.Template.Child())
    suprafam_expander = cast(Gtk.Expander, Gtk.Template.Child())
    order_entry = cast(Gtk.Entry, Gtk.Template.Child())
    suborder_entry = cast(Gtk.Entry, Gtk.Template.Child())
    family_entry = cast(Gtk.Entry, Gtk.Template.Child())
    author_entry = cast(Gtk.Entry, Gtk.Template.Child())
    qualifier_combo = cast(Gtk.ComboBox, Gtk.Template.Child())
    cites_combo = cast(Gtk.ComboBox, Gtk.Template.Child())

    synonyms_presenter = cast(SynonymsPresenter, Gtk.Template.Child())
    notes_presenter = cast(NotesPresenter, Gtk.Template.Child())
    links_menu_btn = cast(LinksMenuButton, Gtk.Template.Child())

    on_entry_w_completion_changed = EntryWCompletionHandler()

    PROBLEM_EMPTY = Problem("empty")
    PROBLEM_NOT_UNIQUE = Problem("not_unique")

    def __init__(
        self,
        model: Family,
        session: Session,
        transient_for: Gtk.Window | None = None,
    ) -> None:
        self.session = session

        if model not in self.session:
            model = self.session.merge(model)

        if bauble.gui and not transient_for:
            transient_for = bauble.gui.window

        super().__init__(model, self, transient_for=transient_for)

        self.widgets_to_model_map = {
            self.family_entry: "epithet",
            self.author_entry: "author",
            self.order_entry: "order",
            self.suborder_entry: "suborder",
            self.cites_combo: "cites",
            self.qualifier_combo: "qualifier",
        }

        populate_enum_combo(self.qualifier_combo, model, "qualifier")
        populate_enum_combo(self.cites_combo, model, "cites")

        self.refresh_all_widgets_from_model()
        self.family_entry.emit("changed")

        self.synonyms_presenter.init(
            self.model,
            FamilySynonym,
            self.session,
            lambda session, text: (
                session.query(Family)
                .filter(utils.ilike(Family.family, f"{text}%%"))
                .order_by(Family.family)
            ),
        )
        self.links_menu_btn.init(model, FAMILY_WEB_BUTTON_DEFS_PREFS)
        self.notes_presenter.init(model)

        if any(getattr(self.model, i) for i in ("order", "suborder")):
            self.suprafam_expander.set_expanded(True)

    def allow_ok_only(self) -> None:
        for response in Response:
            if response.name == "OK":
                continue

            widget = self.get_widget_for_response(response.value)
            if widget:
                widget.hide()

    @property
    def can_commit(self) -> bool:
        modified = self.session.is_modified(self.model)
        if not modified:
            modified = any(
                self.session.is_modified(i) for i in self.session.dirty
            )

        no_problems = not self.problems
        notes_can_commit = self.notes_presenter.can_commit

        return all((modified, no_problems, notes_can_commit))

    @Gtk.Template.Callback()
    def on_changed(self, _presenter: Gtk.Widget) -> None:
        self.update()

    def update(self) -> None:
        default_dialog_update(self, self.can_commit)

    @Gtk.Template.Callback()
    def on_combobox_changed(self, combo: Gtk.ComboBox) -> None:
        super().on_combobox_changed(combo)

        if combo is self.qualifier_combo:
            self.family_entry.emit("changed")

    @Gtk.Template.Callback()
    def on_family_author_entry_changed(self, entry: Gtk.Entry) -> None:

        self.remove_problem(self.PROBLEM_EMPTY, self.family_entry)
        self.remove_problem(self.PROBLEM_NOT_UNIQUE, None)

        epithet = self.family_entry.get_text()
        author = self.author_entry.get_text()
        qualifier = self.model.qualifier or ""

        if not epithet.strip():
            self.add_problem(self.PROBLEM_EMPTY, self.family_entry)
            self.update()
            self.on_text_entry_changed(entry)
            return

        if not validate_unique_family(epithet, author, qualifier, self.model):
            self.add_problem(self.PROBLEM_NOT_UNIQUE, self.family_entry)

            if author:
                self.add_problem(self.PROBLEM_NOT_UNIQUE, self.author_entry)

            if qualifier:
                self.add_problem(self.PROBLEM_NOT_UNIQUE, self.qualifier_combo)

        self.on_text_entry_changed(entry)

    @Gtk.Template.Callback()
    def on_order_entry_changed(self, entry: Gtk.Entry) -> None:
        self.on_entry_w_completion_changed(
            entry,
            get_values=self.order_get_completions,
        )

    @staticmethod
    def order_get_completions(text: str) -> list[str]:
        stmt = (
            select(Family.order)
            .where(utils.ilike(Family.order, f"{text}%%"))
            .distinct()
            .limit(20)
        )

        with db.engine.connect() as connection:

            return connection.scalars(stmt).all()

    @Gtk.Template.Callback()
    def on_suborder_entry_changed(self, entry: Gtk.Entry) -> None:
        self.on_entry_w_completion_changed(
            entry,
            get_values=self.suborder_get_completions,
        )

    def suborder_get_completions(self, text: str) -> list[str]:
        stmt = (
            select(Family.suborder)
            .where(utils.ilike(Family.suborder, f"{text}%%"))
            .distinct()
            .limit(20)
        )

        if self.model.order:
            stmt = stmt.where(Family.order == self.model.order)

        with db.engine.connect() as connection:

            return connection.scalars(stmt).all()

    def do_commit(self) -> bool:
        try:
            self.session.commit()
            self.session.close()
            return True
        except SQLAlchemyError as e:
            msg = _("Error committing changes.\n\n%s") % utils.xml_safe(e)
            utils.message_details_dialog(
                msg, traceback.format_exc(), Gtk.MessageType.ERROR
            )
            self.session.rollback()
            self.model = self.session.merge(self.model)
        return False

    @Gtk.Template.Callback()
    def on_response(
        self,
        dialog: Self,
        response: Response,
    ) -> bool:
        if response in [Response.NEXT, Response.ADD, Response.OK]:
            if self.do_commit() is False:
                logger.debug("commit failed")
                dialog.stop_emission_by_name("response")
                return True

        if response == Response.NEXT:
            edit_callback()

        elif response == Response.ADD:
            add_genera_callback([self.model])

        elif response == Response.CANCEL:
            # most likely not needed
            self.session.rollback()
            self.session.close()

        if not self.get_modal():
            # allow chaining response signal
            GLib.idle_add(self.destroy)

        return False


edit_callback = EditCreateCallback(
    FamilyEditorDialog,
    Family,
)

create_family = edit_callback


def remove_callback(
    objs: Sequence["Family"],
    **_kwargs,
) -> bool:
    family = objs[0]
    fam_lst: list[str] = []
    session = object_session(family)  # prefer not object session
    if not isinstance(session, Session):
        return False

    for family in objs:
        num_gen = len(family.genera)
        safe_str = utils.xml_safe(str(family))
        fam_lst.append(safe_str)
        if num_gen > 0:
            msg = _(
                "The family <i>%(fam)s</i> has %(num_gen)s genera.\n\n"
                "You cannot remove a family with genera."
            ) % {"fam": safe_str, "num_gen": num_gen}
            utils.message_dialog(msg, typ=Gtk.MessageType.WARNING)

            return False

    msg = _(
        "Are you sure you want to remove the following families <i>%s</i>?"
    ) % ", ".join(fam_lst)
    if not utils.yes_no_dialog(msg):

        return False

    for family in objs:
        session.delete(family)
    try:
        session.commit()
    except SQLAlchemyError as e:
        msg = _("Could not delete.\n\n%s") % utils.xml_safe(e)
        utils.message_details_dialog(
            msg, traceback.format_exc(), Gtk.MessageType.ERROR
        )
        session.rollback()

        return False

    return True
add_genera_callback = AddCallback(GenusEditorDialog, Genus, "family")
