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
Genus GUI editor parts.
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
from sqlalchemy import inspect
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.sql import Select
from sqlalchemy.sql import func

import bauble
from bauble import db
from bauble import utils
from bauble.i18n import _
from bauble.ui import dialogs
from bauble.ui.handlers import EntryWCompletionHandler
from bauble.ui.handlers import default_completion_cell_data_func
from bauble.ui.handlers import default_completion_match_func
from bauble.ui.handlers import populate_enum_combo
from bauble.ui.presenter import EditCreateCallback
from bauble.ui.presenter import GenericPresenter
from bauble.ui.presenter import Problem
from bauble.ui.presenter import Response
from bauble.ui.presenter import default_dialog_update
from bauble.ui.widgets import LinksMenuButton
from bauble.ui.widgets import NoteBox
from bauble.ui.widgets import NotesPresenter
from bauble.ui.widgets import YesNoMessageBox

from ..family import Family
from ..genus import Genus
from ..genus import GenusSynonym
from ..species import edit_species
from ..species_model import Species
from .widgets import SynonymsPresenter

GENUS_WEB_BUTTON_DEFS_PREFS = "web_button_defs.genus"


parent = Path(__file__).resolve().parent


def validate_unique_genus(
    epithet: str,
    author: str,
    qualifier: str,
    family: int | None,
    model: Genus,
) -> bool:
    """Validate that the family, genus, author and qualifier combination is
    unique
    """

    with db.Session() as session:
        model = session.merge(model)

        stmt = (
            select(Genus)
            .where(Genus.family == family)
            .where(Genus.epithet == epithet)
            .where(Genus.author == author)
            .where(Genus.qualifier == qualifier)
        )

        exists = session.execute(stmt).scalars().one_or_none()

        if exists is not None and exists is not model:
            return False
    return True


def genus_completions(text: str) -> Select:
    """Given text to search for return an appropriate statement to retrieve
    matching genera.
    """
    query = select(Genus)
    hybrid = ""
    genus = text.removeprefix("×").removeprefix("+").strip()
    try:
        if text[0] in ["×", "+"]:
            hybrid = text[0]
    except (AttributeError, IndexError):
        pass
    query = query.where(utils.ilike(Genus.genus, f"{genus}%"))
    if hybrid:
        query = query.where(Genus.hybrid == hybrid)
    return query.order_by(Genus.epithet)


def genus_to_string_matcher(
    genus: Genus,
    key: str,
    gen_path: str = "",
) -> bool:
    """Helper function to match string or partial string.

    :param genus: a Genus table entry
    :param key: the string to search with
    :param gen_path: optional path for model obects to get to the genus

    :return: bool, True if the genus matches the key
    """
    if gen_path:
        from operator import attrgetter

        genus = attrgetter(gen_path)(genus)
    key = key.removeprefix("× ").removeprefix("+ ").lower()
    return genus.genus.lower().startswith(key)


def genus_match_func(
    completion: Gtk.EntryCompletion,
    key: str,
    treeiter: Gtk.TreeIter,
    path: str = "",
) -> bool:
    """match_func that allows partial matches.

    :param completion: the completion to match
    :param key: lowercase string of the entry text
    :param treeiter: the row number for the item to match
    :param gen_path: optional path for model obects to get to the genus

    :return: bool, True if the item at the treeiter matches the key
    """
    tree_model = completion.get_model()
    if not tree_model:
        raise AttributeError(f"can't get TreeModel from {completion}")
    genus = tree_model[treeiter][0]
    if not inspect(genus).persistent:
        return False
    return genus_to_string_matcher(genus, key, path)


def genus_cell_data_func(
    column: Gtk.TreeViewColumn,
    renderer: Gtk.CellRendererText,
    model: Gtk.ListStore,
    treeiter: Gtk.TreeIter,
) -> None:
    # pylint: disable=unused-argument
    value = model[treeiter][0]
    # occassionally the session gets lost and can result in
    # DetachedInstanceErrors. So check first
    if inspect(value).persistent:
        renderer.set_property(
            "markup",
            f"{value.markup(authors=True)}  (<small>{value.family}</small>)",
        )


@Gtk.Template(filename=str(parent / "genus_editor.ui"))
class GenusEditorDialog(
    GenericPresenter[Genus],
    Gtk.Dialog,
):  # pylint: disable=not-callable,too-many-public-methods

    __gtype_name__ = "GenusEditorDialog"

    revealer = cast(Gtk.Revealer, Gtk.Template.Child())
    family_entry = cast(Gtk.Entry, Gtk.Template.Child())
    family_completion = cast(Gtk.EntryCompletion, Gtk.Template.Child())
    family_cell = cast(Gtk.CellRendererText, Gtk.Template.Child())
    supragen_expander = cast(Gtk.Expander, Gtk.Template.Child())
    subfamily_entry = cast(Gtk.Entry, Gtk.Template.Child())
    tribe_entry = cast(Gtk.Entry, Gtk.Template.Child())
    subtribe_entry = cast(Gtk.Entry, Gtk.Template.Child())
    hybrid_combo = cast(Gtk.ComboBox, Gtk.Template.Child())
    genus_entry = cast(Gtk.Entry, Gtk.Template.Child())
    author_entry = cast(Gtk.Entry, Gtk.Template.Child())
    qualifier_combo = cast(Gtk.ComboBox, Gtk.Template.Child())
    cites_combo = cast(Gtk.ComboBox, Gtk.Template.Child())
    cites_label = cast(Gtk.Label, Gtk.Template.Child())

    synonyms_presenter = cast(SynonymsPresenter, Gtk.Template.Child())
    notes_presenter = cast(NotesPresenter[NoteBox], Gtk.Template.Child())
    links_menu_btn = cast(LinksMenuButton, Gtk.Template.Child())

    on_entry_w_completion_changed = EntryWCompletionHandler()
    on_entry_w_completion_changed_match = EntryWCompletionHandler(
        must_match=True
    )

    PROBLEM_EMPTY = Problem("empty")
    PROBLEM_NOT_UNIQUE = Problem("not_unique")

    def __init__(
        self,
        model: Genus,
        session: Session,
        transient_for: Gtk.Window | None = None,
    ) -> None:
        self.session = session

        if model not in self.session:
            model = self.session.merge(model)

        if bauble.gui and not transient_for:
            transient_for = bauble.gui.window

        super().__init__(model, self, transient_for=transient_for)

        self.family_completion.set_cell_data_func(
            self.family_cell,
            default_completion_cell_data_func,
        )
        self.family_completion.set_match_func(default_completion_match_func)

        self.widgets_to_model_map = {
            self.family_entry: "family",
            self.genus_entry: "epithet",
            self.author_entry: "author",
            self.subfamily_entry: "subfamily",
            self.tribe_entry: "tribe",
            self.subtribe_entry: "subtribe",
            self.hybrid_combo: "hybrid",
            self.qualifier_combo: "qualifier",
            self.cites_combo: "_cites",
        }

        populate_enum_combo(self.hybrid_combo, model, "hybrid")
        populate_enum_combo(self.qualifier_combo, model, "qualifier")
        populate_enum_combo(self.cites_combo, model, "_cites")

        self.refresh_all_widgets_from_model()
        self.genus_entry.emit("changed")
        self.family_entry.emit("changed")
        if not self.model.family:
            self.family_entry.grab_focus()

        self.refresh_cites_label()

        self.synonyms_presenter.init(
            self.model,
            GenusSynonym,
            self.session,
            genus_completions,
            genus_match_func,
            genus_cell_data_func,
        )
        self.links_menu_btn.init(self.model, GENUS_WEB_BUTTON_DEFS_PREFS)
        self.notes_presenter.init(self.model)

        if any(
            getattr(self.model, i) for i in ("subfamily", "tribe", "subtribe")
        ):
            self.supragen_expander.set_expanded(True)

        self.check_synonym()

        if self.model.epithet:
            current = self.get_title()
            self.set_title(f"{current} - {self.model.string(author=True)}")

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
    def on_family_entry_changed(self, entry: Gtk.Entry) -> None:
        self.on_entry_w_completion_changed_match(
            entry,
            get_values=self.family_get_completions,
        )

    def family_get_completions(self, text: str) -> list[Family]:
        stmt = (
            select(Family)
            .where(utils.ilike(Family.epithet, f"{text}%%"))
            .distinct()
            .order_by(Family.epithet)
            .limit(20)
        )
        return self.session.execute(stmt).scalars().all()

    @Gtk.Template.Callback()
    def on_family_match_selected(
        self,
        _completion: Gtk.EntryCompletion,
        liststore: Gtk.ListStore,
        tree_iter: Gtk.TreeIter,
    ) -> None:
        value = liststore[tree_iter][0]

        if value.accepted:
            self.notify_fam_is_synonym(value)
            logger.debug("%s is a synonym of %s", value, value.accepted)

    def notify_fam_is_synonym(self, family: Family) -> None:
        def on_yes_clicked(_button: Gtk.Button) -> None:
            self.revealer.set_reveal_child(False)
            completion_model = cast(
                Gtk.ListStore,
                self.family_completion.get_model(),
            )
            completion_model.clear()
            completion_model.append([family.accepted])
            self.family_completion.emit(
                "match-selected",
                completion_model,
                completion_model.get_iter_first(),
            )

            self.family_entry.set_text(str(family.accepted))
            self.model.family = family.accepted
            self.refresh_cites_label()

        def on_no_clicked(_button: Gtk.Button) -> None:
            self.revealer.set_reveal_child(False)

        msg = _(
            "The family <b>%(synonym)s</b> is a synonym of "
            "<b>%(family)s</b>.\n\nWould you like to choose "
            "<b>%(family)s</b> instead?"
        ) % {
            "synonym": utils.xml_safe(family),
            "family": utils.xml_safe(family.accepted),
        }

        message_box = YesNoMessageBox(
            msg,
            on_yes_clicked,
            on_no_clicked,
        )
        self.revealer.foreach(self.revealer.remove)
        message_box.show_all()
        self.revealer.add(message_box)
        self.revealer.set_reveal_child(True)

    @Gtk.Template.Callback()
    def on_family_add_button_clicked(self, _button: Gtk.Button) -> None:
        from .family_editor import FamilyEditorDialog

        epithet = self.family_entry.get_text() or ""
        family = Family(epithet=epithet)

        with db.Session() as session:
            dialog = FamilyEditorDialog(
                family,
                session,
                transient_for=self,
            )
            dialog.allow_ok_only()

            if dialog.run() != Response.OK:
                dialog.destroy()
                return

            family = self.session.merge(dialog.model)
            dialog.destroy()

        completion = self.family_entry.get_completion()
        completion_model = cast(Gtk.ListStore, completion.get_model())
        completion_model.clear()
        completion_model.append([family])
        completion.emit(
            "match-selected",
            completion_model,
            completion_model.get_iter_first(),
        )

        self.refresh_cites_label()

    @Gtk.Template.Callback()
    def on_subfamily_entry_changed(self, entry: Gtk.Entry) -> None:
        self.on_entry_w_completion_changed(
            entry,
            get_values=self.subfamily_get_completions,
        )

    def subfamily_get_completions(self, text: str) -> list[str]:
        stmt = (
            select(Genus.subfamily)
            .where(utils.ilike(Genus.subfamily, f"{text}%%"))
            .distinct()
            .order_by(Genus.subfamily)
            .limit(20)
        )

        if self.model.family:
            stmt = stmt.where(Genus.family == self.model.family)

        with db.engine.connect() as connection:

            return connection.scalars(stmt).all()

    @Gtk.Template.Callback()
    def on_tribe_entry_changed(self, entry: Gtk.Entry) -> None:
        self.on_entry_w_completion_changed(
            entry,
            get_values=self.tribe_get_completions,
        )

    def tribe_get_completions(self, text: str) -> list[str]:
        stmt = (
            select(Genus.tribe)
            .where(utils.ilike(Genus.tribe, f"{text}%%"))
            .distinct()
            .order_by(Genus.tribe)
            .limit(20)
        )

        if self.model.family:
            stmt = stmt.where(Genus.family == self.model.family)

        if self.model.subfamily:
            stmt = stmt.where(Genus.subfamily == self.model.subfamily)

        with db.engine.connect() as connection:

            return connection.scalars(stmt).all()

    @Gtk.Template.Callback()
    def on_subtribe_entry_changed(self, entry: Gtk.Entry) -> None:
        self.on_entry_w_completion_changed(
            entry,
            get_values=self.subtribe_get_completions,
        )

    def subtribe_get_completions(self, text: str) -> list[str]:
        stmt = (
            select(Genus.subtribe)
            .where(utils.ilike(Genus.subtribe, f"{text}%%"))
            .distinct()
            .order_by(Genus.subtribe)
            .limit(20)
        )

        if self.model.family:
            stmt = stmt.where(Genus.family == self.model.family)

        if self.model.subfamily:
            stmt = stmt.where(Genus.subfamily == self.model.subfamily)

        if self.model.tribe:
            stmt = stmt.where(Genus.tribe == self.model.tribe)

        with db.engine.connect() as connection:

            return connection.scalars(stmt).all()

    @Gtk.Template.Callback()
    def on_changed(self, _presenter: Gtk.Widget) -> None:
        self.update()

    def update(self) -> None:
        self.refresh_cites_label()
        default_dialog_update(self, self.can_commit)

    def refresh_cites_label(self) -> None:
        fam_cites = "N/A"
        if self.model.family:
            if val := self.model.family.cites:
                fam_cites = val

        self.cites_label.set_text(f"Family: {fam_cites}")

    @Gtk.Template.Callback()
    def on_combobox_changed(self, combo: Gtk.ComboBox) -> None:
        super().on_combobox_changed(combo)

        if combo is self.qualifier_combo:
            self.genus_entry.emit("changed")

    @Gtk.Template.Callback()
    def on_genus_entry_changed(self, entry: Gtk.Entry) -> None:

        self.on_genus_author_entry_changed(entry)

        epithet = entry.get_text()
        stmt = (
            select(Genus)
            .outerjoin(Species)
            .where(Genus.epithet == epithet)
            .group_by(Genus)
            .order_by(func.count(Species.genus_id))
        )
        all_existing = self.session.execute(stmt).scalars().all()

        if not all_existing:
            return

        existing = all_existing[-1]

        if len(all_existing) > 1:
            accepted_existing = [i for i in all_existing if i.accepted is None]
            if accepted_existing:
                existing = accepted_existing[-1]

        if existing and existing is not self.model:
            logger.debug("found existing genus with epithet %s", epithet)
            self.notify_existing_genus(existing)

    def notify_existing_genus(self, existing: Genus) -> None:
        def on_yes_clicked(_button: Gtk.Button) -> None:
            self.revealer.set_reveal_child(False)
            self.emit("response", Response.CANCEL)
            edit_callback([existing])

        def on_no_clicked(_button: Gtk.Button) -> None:
            self.revealer.set_reveal_child(False)

        msg = _(
            "<b>%(genus)s (%(family)s)</b> already exists.\n\n"
            "Would you like to edit the existing genus instead?"
        ) % {
            "genus": utils.xml_safe(
                existing.string(
                    author=True,
                    qualifier=True,
                )
            ),
            "family": utils.xml_safe(existing.family),
        }

        message_box = YesNoMessageBox(msg, on_yes_clicked, on_no_clicked)

        self.revealer.foreach(self.revealer.remove)
        message_box.show_all()
        self.revealer.add(message_box)
        self.revealer.set_reveal_child(True)

    @Gtk.Template.Callback()
    def on_genus_author_entry_changed(self, entry: Gtk.Entry) -> None:

        self.remove_problem(self.PROBLEM_EMPTY, self.genus_entry)
        self.remove_problem(self.PROBLEM_NOT_UNIQUE, None)

        epithet = self.genus_entry.get_text()
        author = self.author_entry.get_text()
        qualifier = self.model.qualifier or ""
        family = self.model.family

        if not epithet.strip():
            self.add_problem(self.PROBLEM_EMPTY, self.genus_entry)
            self.update()
            self.on_text_entry_changed(entry)
            return

        if not validate_unique_genus(
            epithet,
            author,
            qualifier,
            family,
            self.model,
        ):
            self.add_problem(self.PROBLEM_NOT_UNIQUE, self.genus_entry)

            if author:
                self.add_problem(self.PROBLEM_NOT_UNIQUE, self.author_entry)

            if qualifier:
                self.add_problem(self.PROBLEM_NOT_UNIQUE, self.qualifier_combo)

            if family:
                self.add_problem(self.PROBLEM_NOT_UNIQUE, self.family_entry)

        self.on_text_entry_changed(entry)

    def check_synonym(self) -> None:
        if self.model.accepted:
            self.notify_is_synonym(self.model.accepted)

    def notify_is_synonym(self, accepted: Genus) -> None:
        def on_yes_clicked(_button: Gtk.Button) -> None:
            self.revealer.set_reveal_child(False)
            self.emit("response", Response.CANCEL)

            edit_callback([accepted])

        def on_no_clicked(_button: Gtk.Button) -> None:
            self.revealer.set_reveal_child(False)

        msg = _(
            "<b>%(genus)s</b> is a synonym of \n\n\t<b>%(accepted)s</b>.\n\n"
            "Would you like to edit the accepted genus instead?"
        ) % {
            "genus": self.model.markup(authors=True, sensu=True),
            "accepted": accepted.markup(authors=True, sensu=True),
        }

        message_box = YesNoMessageBox(msg, on_yes_clicked, on_no_clicked)

        self.revealer.foreach(self.revealer.remove)
        message_box.show_all()
        self.revealer.add(message_box)
        self.revealer.set_reveal_child(True)

    def do_commit(self) -> bool:
        try:
            self.session.commit()
            self.session.close()
            return True
        except SQLAlchemyError as e:
            msg = _("Error committing changes.\n\n%s") % utils.xml_safe(e)
            dialogs.message_details_dialog(
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
        family = self.model.family
        if response in [Response.NEXT, Response.ADD, Response.OK]:
            if self.do_commit() is False:
                logger.debug("commit failed")
                dialog.stop_emission_by_name("response")
                return True

        if response == Response.NEXT:
            create_genus(family=family)

        elif response == Response.ADD:
            add_species_callback([self.model])

        elif response == Response.CANCEL:
            # most likely not needed
            self.session.rollback()
            self.session.close()

        if not self.get_modal():
            # allow chaining response signal
            GLib.idle_add(self.destroy)

        return False


edit_callback = EditCreateCallback(
    GenusEditorDialog,
    Genus,
)

create_genus = edit_callback


def add_species_callback(objs: Sequence["Genus"], **_kwargs) -> bool:
    genus = objs[0]

    return edit_species(model=Species(genus=genus)) is not None
