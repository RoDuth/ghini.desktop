# Copyright 2008-2010 Brett Adams
# Copyright 2012-2015 Mario Frasca <mario@anche.no>.
# Copyright 2020-2026 Ross Demuth <rossdemuth123@gmail.com>
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
Species GUI editor parts.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

import re
import traceback
from ast import literal_eval
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Self
from typing import cast

from gi.repository import GLib
from gi.repository import Gtk
from gi.repository import Pango
from sqlalchemy import and_
from sqlalchemy import func
from sqlalchemy import or_
from sqlalchemy import select
from sqlalchemy.engine import Row
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.sql import ColumnElement

import bauble
from bauble import db
from bauble import utils
from bauble.i18n import _
from bauble.meta import BaubleMeta
from bauble.ui import dialogs
from bauble.ui.handlers import ComboBoxHandler
from bauble.ui.handlers import EntryWCompletionHandler
from bauble.ui.handlers import ToggleButtonHandler
from bauble.ui.presenter import EditCreateCallback
from bauble.ui.presenter import GenericPresenter
from bauble.ui.presenter import Problem
from bauble.ui.presenter import Response
from bauble.ui.presenter import default_dialog_update
from bauble.ui.utils import default_completion_cell_data_func
from bauble.ui.utils import default_completion_match_func
from bauble.ui.utils import format_combo_entry_text
from bauble.ui.utils import populate_enum_combo
from bauble.ui.utils import set_widget_value
from bauble.ui.widgets import LinksMenuButton
from bauble.ui.widgets import NoteBox
from bauble.ui.widgets import NotesPresenter
from bauble.ui.widgets import PictureBox
from bauble.ui.widgets import YesNoMessageBox

from ..genus import Genus
from ..species_model import Habit
from ..species_model import Species
from ..species_model import SpeciesSynonym
from ..species_model import VernacularName
from .widgets import SynonymsPresenter
from .widgets import taxon_completion_cell_data_func
from .widgets.species import InfraspecificPresenter
from .widgets.species import SpeciesEntry
from .widgets.species import species_cell_data_func
from .widgets.species import species_completions
from .widgets.species import species_match_func
from .widgets.vernacular import VernacularNamePresenter

SPECIES_WEB_BUTTON_DEFS_PREFS = "web_button_defs.species"


parent = Path(__file__).resolve().parent


def validate_unique_species(full_sci_name: str, model: Species) -> bool:
    # pylint: disable=unused-argument
    """Validate that the family, author and qualifier combination is unique"""

    with db.Session() as session:

        model = session.merge(model)
        exists = (
            session.query(Species)
            .filter(Species.full_sci_name == full_sci_name)
            .one_or_none()
        )

        if exists is not None and exists is not model:
            return False
    return True


@dataclass
class Name:
    genus: str
    species: str
    genus_hybrid: str | None = None
    species_hybrid: str | None = None
    species_author: str | None = None
    infrasp_rank: str | None = None
    infrasp_epithet: str | None = None
    infrasp_author: str | None = None

    def __post_init__(self):
        if self.infrasp_rank == "ssp.":
            self.infrasp_rank = "subsp."
        elif self.infrasp_rank == "forma":
            self.infrasp_rank = "f."


_RE_TAXON = re.compile(
    r"""
    (?P<genus_hybrid>[×+])?\s?
    (?P<genus>[A-Z][\w\-]+)\s
    (?P<species_hybrid>[×+])?\s?
    (?P<species>[\w\-]+)?
    (?:\s(?P<species_author>(
      .*(?=\s(ssp\.|subsp\.|var\.|subvar\.|forma|f\.|subf\.)\s)|
      (?!ssp\.)(?!subsp\.)(?!var\.)(?!subvar\.)(?!forma.)(?!f\.)(?!subf\.).*$)
    ))?
    (?:\s?(?P<infrasp_rank>ssp\.|subsp\.|var\.|subvar\.|forma|f\.|subf\.)?\s?
    (?P<infrasp_epithet>[\w\.\-\(\)]+))?
    (?:\s+(?P<infrasp_author>.+?))?$
    """,
    re.VERBOSE,
)


def split_taxon_full_name(full_name: str) -> Name | None:
    """Splits a full species name into its parts and returns it as a Name obj.

    NOTE: Not expected to handle all edge cases, just bi/trinomials with
    authors and hybrid flags.

    :param full_name: the full name to split
    """
    match = _RE_TAXON.match(full_name.strip())

    if not match:
        return None

    matchdict = match.groupdict()

    return Name(**matchdict)


@Gtk.Template(filename=str(parent / "species_editor.ui"))
class SpeciesEditorDialog(
    GenericPresenter[Species],
    Gtk.Dialog,
):  # pylint: disable=not-callable,too-many-public-methods

    __gtype_name__ = "SpeciesEditorDialog"

    parents_label = cast(Gtk.Label, Gtk.Template.Child())
    fullname_label = cast(Gtk.Label, Gtk.Template.Child())
    prev_sp_box = cast(Gtk.Box, Gtk.Template.Child())
    prevname_label = cast(Gtk.Label, Gtk.Template.Child())
    add_syn_chkbox = cast(Gtk.CheckButton, Gtk.Template.Child())
    revealer = cast(Gtk.Revealer, Gtk.Template.Child())
    genus_entry = cast(Gtk.Entry, Gtk.Template.Child())
    genus_completion = cast(Gtk.EntryCompletion, Gtk.Template.Child())
    genus_cell = cast(Gtk.CellRendererText, Gtk.Template.Child())
    infragen_expander = cast(Gtk.Expander, Gtk.Template.Child())
    subgenus_entry = cast(Gtk.Entry, Gtk.Template.Child())
    section_entry = cast(Gtk.Entry, Gtk.Template.Child())
    subsection_entry = cast(Gtk.Entry, Gtk.Template.Child())
    series_entry = cast(Gtk.Entry, Gtk.Template.Child())
    subseries_entry = cast(Gtk.Entry, Gtk.Template.Child())
    species_entry = cast(SpeciesEntry, Gtk.Template.Child())
    hybrid_combo = cast(Gtk.ComboBox, Gtk.Template.Child())
    author_entry = cast(Gtk.Entry, Gtk.Template.Child())
    qualifier_combo = cast(Gtk.ComboBox, Gtk.Template.Child())
    cites_combo = cast(Gtk.ComboBox, Gtk.Template.Child())
    cites_label = cast(Gtk.Label, Gtk.Template.Child())
    cv_epithet_entry = cast(Gtk.Entry, Gtk.Template.Child())
    expand_cv_btn = cast(Gtk.Button, Gtk.Template.Child())
    expand_btn_icon = cast(Gtk.Image, Gtk.Template.Child())
    cv_extras_grid = cast(Gtk.Grid, Gtk.Template.Child())
    cv_group_entry = cast(Gtk.Entry, Gtk.Template.Child())
    tradename_entry = cast(Gtk.Entry, Gtk.Template.Child())
    trademark_combo = cast(Gtk.ComboBoxText, Gtk.Template.Child())
    grex_entry = cast(Gtk.Entry, Gtk.Template.Child())
    pbr_checkbtn = cast(Gtk.CheckButton, Gtk.Template.Child())
    label_markup_expander = cast(Gtk.Expander, Gtk.Template.Child())
    label_markup_entry = cast(Gtk.Entry, Gtk.Template.Child())
    label_markup_label = cast(Gtk.Label, Gtk.Template.Child())
    label_dist_entry = cast(Gtk.Entry, Gtk.Template.Child())
    habit_comboentry = cast(Gtk.ComboBox, Gtk.Template.Child())
    habit_liststore = cast(Gtk.ListStore, Gtk.Template.Child())
    habit_cell = cast(Gtk.CellRendererText, Gtk.Template.Child())
    habit_completion = cast(Gtk.EntryCompletion, Gtk.Template.Child())
    habit_entry = cast(Gtk.Entry, Gtk.Template.Child())
    _sp_custom1_label = cast(Gtk.Label, Gtk.Template.Child())
    _sp_custom1_combo = cast(Gtk.ComboBoxText, Gtk.Template.Child())
    _sp_custom2_label = cast(Gtk.Label, Gtk.Template.Child())
    _sp_custom2_combo = cast(Gtk.ComboBoxText, Gtk.Template.Child())

    infrasp_presenter = cast(InfraspecificPresenter, Gtk.Template.Child())
    vernacular_presenter = cast(VernacularNamePresenter, Gtk.Template.Child())
    synonyms_presenter = cast(SynonymsPresenter, Gtk.Template.Child())
    notes_presenter = cast(NotesPresenter[NoteBox], Gtk.Template.Child())
    pictures_presenter = cast(NotesPresenter[PictureBox], Gtk.Template.Child())
    links_menu_btn = cast(LinksMenuButton, Gtk.Template.Child())

    on_completion_entry_matched = EntryWCompletionHandler(must_match=True)
    on_completion_entry_changed = EntryWCompletionHandler()
    on_habit_combo_changed = ComboBoxHandler(column=1, must_match=True)
    on_toggled = ToggleButtonHandler()

    PROBLEM_EMPTY = Problem("empty")
    PROBLEM_NOT_UNIQUE = Problem("not_unique")
    PROBLEM_INVALID_MARKUP = Problem("invalid_markup")

    def __init__(
        self,
        model: Species,
        session: Session,
        transient_for: Gtk.Window | None = None,
    ) -> None:
        self.session = session

        if model not in self.session:
            model = self.session.merge(model)
        # get the starting position
        self.capture_start_sp(model)

        if bauble.gui and not transient_for:
            transient_for = bauble.gui.window

        super().__init__(model, self, transient_for=transient_for)

        self.genus_completion.set_cell_data_func(
            self.genus_cell,
            taxon_completion_cell_data_func,
        )
        self.genus_completion.set_match_func(default_completion_match_func)

        self.habit_completion.set_match_func(default_completion_match_func)
        self.habit_completion.set_cell_data_func(
            self.habit_cell,
            default_completion_cell_data_func,
        )

        self.widgets_to_model_map = {
            self.genus_entry: "genus",
            self.subgenus_entry: "subgenus",
            self.section_entry: "section",
            self.subsection_entry: "subsection",
            self.series_entry: "series",
            self.subseries_entry: "subseries",
            self.species_entry: "epithet",
            self.hybrid_combo: "hybrid",
            self.author_entry: "sp_author",
            self.qualifier_combo: "sp_qual",
            self.cites_combo: "_cites",
            self.cv_epithet_entry: "cultivar_epithet",
            self.pbr_checkbtn: "pbr_protected",
            self.cv_group_entry: "cv_group",
            self.tradename_entry: "trade_name",
            self.trademark_combo: "trademark_symbol",
            self.label_markup_entry: "label_markup",
            self.grex_entry: "grex",
            self.habit_comboentry: "habit",
        }

        self._setup_custom_field("_sp_custom1", self._sp_custom1_combo)
        self._setup_custom_field("_sp_custom2", self._sp_custom2_combo)

        populate_enum_combo(self.hybrid_combo, model, "hybrid")
        populate_enum_combo(self.qualifier_combo, model, "sp_qual")
        populate_enum_combo(self.cites_combo, model, "_cites")

        symbols = (
            self.session.execute(select(Species.trademark_symbol).distinct())
            .scalars()
            .all()
        )
        # make sure the obvious defaults exist
        values = set(symbols + ["™", "®"])
        for v in values:
            self.trademark_combo.append_text(v or "")

        for habit in self.session.execute(select(Habit)).scalars():
            self.habit_liststore.append((str(habit), habit))

        self.habit_liststore.append(("", None))

        self.last_existing_notified = 0

        self.refresh_all_widgets_from_model()
        self.genus_entry.emit("changed")

        if not self.model.genus:
            self.genus_entry.grab_focus()

        self.synonyms_presenter.init(
            self.model,
            SpeciesSynonym,
            self.session,
            species_completions,
            species_match_func,
            species_cell_data_func,
        )
        self.links_menu_btn.init(model, SPECIES_WEB_BUTTON_DEFS_PREFS)
        self.infrasp_presenter.init(model)
        self.vernacular_presenter.init(model, self.session, self.revealer)
        self.notes_presenter.init(model)
        self.pictures_presenter.init(model, "_pictures", PictureBox)

        if any(
            getattr(self.model, i)
            for i in (
                "subgenus",
                "section",
                "subsection",
                "series",
                "subseries",
            )
        ):
            self.infragen_expander.set_expanded(True)

        if any(
            getattr(self.model, i)
            for i in ("cv_group", "trade_name", "trademark_symbol", "grex")
        ):
            self.expand_cv_btn.emit("clicked")

        self.check_synonym()

        if self.model.epithet:
            current = self.get_title()
            self.set_title(f"{current} - {self.model.string(author=True)}")

        if self.model.label_markup:
            self.label_markup_expander.set_expanded(True)
            self.label_markup_entry.emit("changed")

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
        pics_can_commit = self.pictures_presenter.can_commit
        infrasp_can_commit = self.infrasp_presenter.can_commit
        vernacular_can_commit = self.vernacular_presenter.can_commit

        return all(
            (
                modified,
                no_problems,
                infrasp_can_commit,
                notes_can_commit,
                pics_can_commit,
                vernacular_can_commit,
            )
        )

    @Gtk.Template.Callback()
    def on_changed(self, _presenter: Gtk.Widget) -> None:
        self.update()

    def update(self) -> None:
        self.remove_problem(self.PROBLEM_EMPTY, None)

        if str(self.model) == str(self.model.genus):
            self.add_problem(self.PROBLEM_EMPTY, self.species_entry)

        if self.problems:
            self.label_markup_expander.set_sensitive(False)
            self.label_markup_expander.set_expanded(False)
        else:
            self.label_markup_expander.set_sensitive(True)

        self.validate_unique()
        self.check_existing()
        default_dialog_update(self, self.can_commit)
        self.refresh_cites_label()
        self.refresh_fullname_label()

    def _setup_custom_field(
        self,
        column_name: str,
        widget: Gtk.ComboBox,
    ) -> None:
        with db.Session() as session:
            custom_meta = session.execute(
                select(BaubleMeta).where(BaubleMeta.name == column_name)
            ).scalar()
        # pylint: disable=protected-access
        if custom_meta:
            custom_meta = literal_eval(custom_meta.value)
            display_name = custom_meta.get("display_name")
            if display_name:
                label = getattr(self, column_name + "_label")
                label.set_label(display_name)
                label.set_visible(label)
            values = custom_meta.get("values")
            if values:
                combo = getattr(self, column_name + "_combo")
                combo.set_visible(True)
                for v in values:
                    combo.append_text(v or "")
            field_name = custom_meta.get("field_name")
            self.widgets_to_model_map[widget] = field_name

    def refresh_cites_label(self) -> None:
        gen_cites = fam_cites = "N/A"
        if self.model.genus:
            # pylint: disable=protected-access
            if gval := self.model.genus._cites:
                gen_cites = gval

            if self.model.genus.family:
                if fval := self.model.genus.family.cites:
                    fam_cites = fval

        string = f"Family: {fam_cites}, Genus: {gen_cites}"
        self.cites_label.set_text(string)

    def capture_start_sp(self, model):
        self.start_sp_dict = None
        self.start_sp_markup = None
        if model not in self.session.new:
            self.start_sp_dict = {
                "genus": model.genus,
                "sp": model.sp,
                "hybrid": model.hybrid,
                "sp_author": model.sp_author,
                "sp_qual": model.sp_qual,
                "cv_group": model.cv_group,
                "grex": model.grex,
                "cultivar_epithet": model.cultivar_epithet,
                "trade_name": model.trade_name,
                "trademark_symbol": model.trademark_symbol,
                "pbr_protected": model.pbr_protected,
                "infrasp1": model.infrasp1,
                "infrasp1_rank": model.infrasp1_rank,
                "infrasp1_author": model.infrasp1_author,
                "infrasp2": model.infrasp2,
                "infrasp2_rank": model.infrasp2_rank,
                "infrasp2_author": model.infrasp2_author,
                "infrasp3": model.infrasp3,
                "infrasp3_rank": model.infrasp3_rank,
                "infrasp3_author": model.infrasp3_author,
                "infrasp4": model.infrasp4,
                "infrasp4_rank": model.infrasp4_rank,
                "infrasp4_author": model.infrasp4_author,
            }
            self.start_sp_markup = model.string(markup=True, authors=True)

    def refresh_fullname_label(self) -> None:
        """Refresh the parents, fullname, prevname labels."""
        self.prev_sp_box.hide()

        if self.model.genus is None:
            self.parents_label.set_text("-- > --")
            self.fullname_label.set_text("--")
            return

        family_str = self.model.genus.family.string(author=True)
        genus_str = self.model.genus.string(author=True)
        self.parents_label.set_markup(f"<b>{family_str} > {genus_str}</b>")
        sp_str = self.model.string(markup=True, author=True)
        self.fullname_label.set_markup(sp_str)

        # add previous species as synonym
        if self.start_sp_markup and sp_str != self.start_sp_markup:
            self.prev_sp_box.show()
            self.prevname_label.set_markup(
                f"{self.start_sp_markup} ({_("previous name")})"
            )

            self.label_markup_entry.set_text("")
        else:
            self.add_syn_chkbox.set_active(False)

    @Gtk.Template.Callback()
    def on_genus_entry_paste(self, entry: Gtk.Entry) -> None:

        def _split() -> None:
            text = entry.get_text().strip()
            # entry.set_text(text)
            split = split_taxon_full_name(text)

            if not split:
                entry.set_text(text)
                return

            entry.set_text(
                f"{split.genus_hybrid} {split.genus}"
                if split.genus_hybrid
                else split.genus
            )
            set_widget_value(self.hybrid_combo, split.species_hybrid)
            self.species_entry.set_text(split.species)
            self.author_entry.set_text(split.species_author or "")

            self.infrasp_presenter.clear()
            if split.infrasp_rank:
                infrasp_row = self.infrasp_presenter.add_row()
                set_widget_value(infrasp_row.rank_combo, split.infrasp_rank)
                set_widget_value(
                    infrasp_row.epithet_entry,
                    split.infrasp_epithet,
                )
                set_widget_value(
                    infrasp_row.author_entry,
                    split.infrasp_author,
                )

        GLib.idle_add(_split)

    @Gtk.Template.Callback()
    def on_genus_add_button_clicked(self, _button: Gtk.Button) -> None:
        from .genus_editor import GenusEditorDialog

        epithet = self.genus_entry.get_text() or ""
        genus = Genus(epithet=epithet)

        with db.Session() as session:
            dialog = GenusEditorDialog(
                genus,
                session,
                transient_for=self,
            )
            dialog.allow_ok_only()

            if dialog.run() != Response.OK:
                dialog.destroy()
                return

            genus = self.session.merge(dialog.model)
            dialog.destroy()

        self.model.genus = genus
        self.genus_entry.set_text(str(genus))

    @Gtk.Template.Callback()
    def on_genus_entry_changed(self, entry: Gtk.Entry) -> None:
        self.on_completion_entry_matched(
            entry,
            get_values=self.genus_get_completions,
        )

    def genus_get_completions(
        self, text: str
    ) -> list[Row] | list[tuple[Genus]]:
        # if already populated match.
        if self.model.genus and self.model.genus.epithet == text:
            return [(self.model.genus,)]

        stmt = (
            select(Genus)
            .where(utils.ilike(Genus.epithet, f"{text}%"))
            .distinct()
            .order_by(Genus.epithet)
            .limit(20)
        )
        return self.session.execute(stmt).all()

    @Gtk.Template.Callback()
    def on_genus_match_selected(
        self,
        _completion: Gtk.EntryCompletion,
        liststore: Gtk.ListStore,
        tree_iter: Gtk.TreeIter,
    ) -> None:
        value = liststore[tree_iter][0]

        if value.accepted:
            GLib.idle_add(self.notify_genus_is_synonym, value)
            logger.debug("%s is a synonym of %s", value, value.accepted)

    def notify_genus_is_synonym(self, genus: Genus) -> None:
        def on_yes_clicked(_button: Gtk.Button) -> None:
            self.revealer.set_reveal_child(False)
            completion_model = cast(
                Gtk.ListStore,
                self.genus_completion.get_model(),
            )
            completion_model.clear()
            completion_model.append([genus.accepted])
            self.genus_completion.emit(
                "match-selected",
                completion_model,
                completion_model.get_iter_first(),
            )

            self.genus_entry.set_text(str(genus.accepted))
            self.model.genus = genus.accepted
            self.refresh_cites_label()

        def on_no_clicked(_button: Gtk.Button) -> None:
            self.revealer.set_reveal_child(False)

        msg = _(
            "The genus <b>%(synonym)s</b> is a synonym of "
            "<b>%(genus)s</b>.\n\nWould you like to choose "
            "<b>%(genus)s</b> instead?"
        ) % {
            "synonym": genus.markup(authors=True),
            "genus": genus.accepted.markup(authors=True),
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
    def on_subgenus_entry_changed(self, entry: Gtk.Entry) -> None:
        self.on_completion_entry_changed(
            entry,
            get_values=self.subgenus_get_completions,
        )

    def subgenus_get_completions(self, text: str) -> list[Row]:

        stmt = (
            select(Species.subgenus)
            .where(Species.genus == self.model.genus)
            .where(utils.ilike(Species.subgenus, f"{text}%"))
            .distinct()
            .order_by(Species.subgenus)
            .limit(20)
        )

        return self.session.execute(stmt).all()

    @Gtk.Template.Callback()
    def on_section_entry_changed(self, entry: Gtk.Entry) -> None:
        self.on_completion_entry_changed(
            entry,
            get_values=self.section_get_completions,
        )

    def section_get_completions(self, text: str) -> list[Row]:

        stmt = (
            select(Species.section)
            .where(Species.genus == self.model.genus)
            .where(utils.ilike(Species.section, f"{text}%"))
        )
        if self.model.subgenus:
            stmt = stmt.where(Species.subgenus == self.model.subgenus)

        stmt = stmt.distinct().order_by(Species.section).limit(20)

        return self.session.execute(stmt).all()

    @Gtk.Template.Callback()
    def on_subsection_entry_changed(self, entry: Gtk.Entry) -> None:
        self.on_completion_entry_changed(
            entry,
            get_values=self.subsection_get_completions,
        )

    def subsection_get_completions(self, text: str) -> list[Row]:

        stmt = (
            select(Species.subsection)
            .where(Species.genus == self.model.genus)
            .where(utils.ilike(Species.subsection, f"{text}%"))
        )
        if self.model.subgenus:
            stmt = stmt.where(Species.subgenus == self.model.subgenus)

        if self.model.section:
            stmt = stmt.where(Species.section == self.model.section)

        stmt = stmt.distinct().order_by(Species.subsection).limit(20)

        return self.session.execute(stmt).all()

    @Gtk.Template.Callback()
    def on_series_entry_changed(self, entry: Gtk.Entry) -> None:
        self.on_completion_entry_changed(
            entry,
            get_values=self.series_get_completions,
        )

    def series_get_completions(self, text: str) -> list[Row]:

        stmt = (
            select(Species.series)
            .where(Species.genus == self.model.genus)
            .where(utils.ilike(Species.series, f"{text}%"))
        )
        if self.model.subgenus:
            stmt = stmt.where(Species.subgenus == self.model.subgenus)

        if self.model.section:
            stmt = stmt.where(Species.section == self.model.section)

        if self.model.subsection:
            stmt = stmt.where(Species.subsection == self.model.subsection)

        stmt = stmt.distinct().order_by(Species.series).limit(20)

        return self.session.execute(stmt).all()

    @Gtk.Template.Callback()
    def on_subseries_entry_changed(self, entry: Gtk.Entry) -> None:
        self.on_completion_entry_changed(
            entry,
            get_values=self.subseries_get_completions,
        )

    def subseries_get_completions(self, text: str) -> list[Row]:

        stmt = (
            select(Species.subseries)
            .where(Species.genus == self.model.genus)
            .where(utils.ilike(Species.subseries, f"{text}%"))
        )
        if self.model.subgenus:
            stmt = stmt.where(Species.subgenus == self.model.subgenus)

        if self.model.section:
            stmt = stmt.where(Species.section == self.model.section)

        if self.model.subsection:
            stmt = stmt.where(Species.subsection == self.model.subsection)

        if self.model.series:
            stmt = stmt.where(Species.series == self.model.series)

        stmt = stmt.distinct().order_by(Species.subseries).limit(20)

        return self.session.execute(stmt).all()

    @Gtk.Template.Callback()
    @staticmethod
    def on_comboentry_format(
        combo: Gtk.ComboBox,
        path: Gtk.TreePath,
    ) -> str:
        return format_combo_entry_text(combo, path)

    @Gtk.Template.Callback()
    def on_habit_comboentry_changed(self, combo: Gtk.ComboBox) -> None:
        self.on_habit_combo_changed(combo)

    @Gtk.Template.Callback()
    def on_combobox_changed(self, combo: Gtk.ComboBox) -> None:
        super().on_combobox_changed(combo)

    @Gtk.Template.Callback()
    def on_taxon_entry_changed(self, entry: Gtk.Entry) -> None:
        # author, species, cultivar, group, grex, trade_name
        self.on_text_entry_changed(entry)

    @Gtk.Template.Callback()
    def on_expand_cv_button_clicked(self, _button: Gtk.Button) -> None:
        visible = not self.cv_extras_grid.get_visible()
        self.expand_btn_icon.set_from_icon_name(
            {False: "pan-end-symbolic", True: "pan-start-symbolic"}[visible],
            Gtk.IconSize.BUTTON,
        )
        self.cv_extras_grid.set_visible(visible)

    @Gtk.Template.Callback()
    def on_check_toggled(self, button: Gtk.ToggleButton) -> None:
        self.on_toggled(button)

    @Gtk.Template.Callback()
    def on_markup_entry_changed(self, entry: Gtk.Entry) -> None:
        self.remove_problem(self.PROBLEM_INVALID_MARKUP, entry)
        value = entry.get_text()

        if value == self.model.markup():
            entry.set_name("unsaved-entry")
        else:
            entry.set_name("GtkEntry")

        if value in (self.model.markup(), ""):
            value = ""

        if value:
            try:
                Pango.parse_markup(value, -1, "0")
                self.label_markup_label.set_markup(value)
            except (GLib.Error, TypeError, RuntimeError, UnicodeDecodeError):
                self.label_markup_label.set_markup("--")
                self.add_problem(self.PROBLEM_INVALID_MARKUP, entry)
                return
        else:
            self.label_markup_label.set_markup("--")
            return

        super().on_text_entry_changed(entry)

    @Gtk.Template.Callback()
    def on_markup_button_clicked(self, _button: Gtk.Button) -> None:
        self.label_markup_entry.set_text(self.model.markup())

    def check_synonym(self) -> None:
        if self.model.accepted:
            GLib.idle_add(self.notify_is_synonym, self.model.accepted)

    def notify_is_synonym(self, accepted: Species) -> None:
        def on_yes_clicked(_button: Gtk.Button) -> None:
            self.revealer.set_reveal_child(False)
            self.emit("response", Response.CANCEL)

            edit_callback([accepted])

        def on_no_clicked(_button: Gtk.Button) -> None:
            self.revealer.set_reveal_child(False)

        msg = _(
            "<b>%(species)s</b> is a synonym of \n\n\t<b>%(accepted)s</b>.\n\n"
            "Would you like to edit the accepted species instead?"
        ) % {
            "species": self.model.string(
                authors=True, sensu=True, markup=True
            ),
            "accepted": accepted.string(authors=True, sensu=True, markup=True),
        }

        message_box = YesNoMessageBox(msg, on_yes_clicked, on_no_clicked)

        self.revealer.foreach(self.revealer.remove)
        message_box.show_all()
        self.revealer.add(message_box)
        self.revealer.set_reveal_child(True)

    def check_existing(self) -> None:
        """Check if a species with the same name exists and offer editing it
        instead.

        Preference names that have been used before and are accepted names.
        """
        genus = self.genus_entry.get_text()
        epithet = self.model.epithet
        infrasp = self.model.infraspecific_epithet or None
        cultivar = self.model.cultivar_epithet or None
        group = self.model.cv_group or None
        grex = self.model.grex or None

        conditions = (
            Species.epithet == epithet,
            cast(ColumnElement, Species.infraspecific_epithet == infrasp),
            Species.cultivar_epithet == cultivar,
            Species.cv_group == group,
            Species.grex == grex,
        )
        if cultivar:
            condition = or_(
                and_(*conditions),
                Species.cultivar_epithet == cultivar,
            )
        else:
            condition = and_(*conditions)

        from ...garden.accession import Accession

        stmt = (
            select(Species)
            .join(Genus)
            .outerjoin(Accession)
            .where(Genus.epithet == genus)
            .where(condition)
            .group_by(Species)
            .order_by(func.count(Accession.species_id))
        )
        all_existing = self.session.execute(stmt).scalars().all()

        if not all_existing:
            return

        existing = all_existing[-1]

        if len(all_existing) > 1:
            accepted_existing = [i for i in all_existing if i.accepted is None]
            if accepted_existing:
                existing = accepted_existing[-1]

        if (
            existing
            and existing.id != self.last_existing_notified
            and existing is not self.model
        ):
            logger.debug("found existing species %s", existing)
            GLib.idle_add(self.notify_existing_species, existing)

    def notify_existing_species(self, existing: Species) -> None:
        def on_yes_clicked(_button: Gtk.Button) -> None:
            self.revealer.set_reveal_child(False)
            self.emit("response", Response.CANCEL)

            edit_callback([existing])

        def on_no_clicked(_button: Gtk.Button) -> None:
            self.last_existing_notified = existing.id
            self.revealer.set_reveal_child(False)

        msg = _(
            "<b>%(species)s</b> already exists.\n\n"
            "Would you like to edit the existing species instead?"
        ) % {"species": existing.string(authors=True, sensu=True, markup=True)}
        logger.debug(msg)

        message_box = YesNoMessageBox(msg, on_yes_clicked, on_no_clicked)

        self.revealer.foreach(self.revealer.remove)
        message_box.show_all()
        self.revealer.add(message_box)
        self.revealer.set_reveal_child(True)

    def validate_unique(self) -> None:
        self.remove_problem(self.PROBLEM_NOT_UNIQUE, None)
        self.infrasp_presenter.unset_problem(self.PROBLEM_NOT_UNIQUE)

        if not validate_unique_species(
            self.model.string(author=True), self.model
        ):
            self.last_existing_notified = 0
            self.check_existing()
            self.add_problem(self.PROBLEM_NOT_UNIQUE, self.genus_entry)

            if self.model.epithet:
                self.add_problem(self.PROBLEM_NOT_UNIQUE, self.species_entry)

            if self.model.sp_author:
                self.add_problem(self.PROBLEM_NOT_UNIQUE, self.author_entry)

            if self.model.sp_qual:
                self.add_problem(self.PROBLEM_NOT_UNIQUE, self.qualifier_combo)

            self.infrasp_presenter.set_problem(self.PROBLEM_NOT_UNIQUE)

            if self.model.cultivar_epithet:
                self.add_problem(
                    self.PROBLEM_NOT_UNIQUE,
                    self.cv_epithet_entry,
                )

            if self.model.grex:
                self.add_problem(self.PROBLEM_NOT_UNIQUE, self.grex_entry)

            if self.model.cv_group:
                self.add_problem(self.PROBLEM_NOT_UNIQUE, self.cv_group_entry)

            if self.model.pbr_protected:
                self.add_problem(self.PROBLEM_NOT_UNIQUE, self.pbr_checkbtn)

            if self.model.trade_name:
                self.add_problem(self.PROBLEM_NOT_UNIQUE, self.tradename_entry)

    def do_commit(self) -> bool:
        try:
            self.session.commit()
            if self.add_syn_chkbox.get_active():
                # second commit so history is placed last - sync could fail
                # unique constraint on full_sci_name otherwise
                syn = Species(**self.start_sp_dict)
                self.model.synonyms.append(syn)
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

    def do_show(self, *args, **kwargs) -> None:
        if self.session.scalar(select(func.count()).select_from(Genus)) == 0:
            msg = _(
                "You must first add or import at least one genus into the "
                "database before you can add species."
            )
            dialogs.message_dialog(msg)
            self.destroy()
        else:
            Gtk.Dialog.do_show(self, *args, **kwargs)

    @Gtk.Template.Callback()
    def on_response(
        self,
        dialog: Self,
        response: Response,
    ) -> bool:
        genus = self.model.genus
        if response in [Response.NEXT, Response.ADD, Response.OK]:
            if self.do_commit() is False:
                logger.debug("commit failed")
                dialog.stop_emission_by_name("response")
                return True

        if response == Response.NEXT:
            create_species(genus=genus)

        elif response == Response.ADD:
            add_accession_callback([self.model])

        elif response == Response.CANCEL:
            # most likely not needed
            self.session.rollback()
            self.session.close()

        if not self.get_modal():
            # allow chaining response signal
            GLib.idle_add(self.destroy)

        return False


edit_callback = EditCreateCallback(
    SpeciesEditorDialog,
    Species,
)

create_species = edit_callback


def add_accession_callback(
    objs: Sequence[Species | VernacularName],
    **_kwargs,
) -> bool:
    from ...garden.accession import Accession
    from ...garden.accession import AccessionEditor

    species = objs[0]
    if isinstance(species, VernacularName):
        species = species.species

    editor = AccessionEditor(model=Accession(species=species))

    return editor.start() is not None
