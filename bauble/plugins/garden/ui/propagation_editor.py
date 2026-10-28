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
Propagation GUI editor parts.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

import datetime
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Literal
from typing import Self
from typing import cast

from gi.repository import GLib
from gi.repository import GObject
from gi.repository import Gspell
from gi.repository import Gtk
from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy.engine import Result
from sqlalchemy.orm import Session

from bauble import db
from bauble import utils
from bauble.btypes import parse_str_date
from bauble.i18n import _
from bauble.ui.handlers import ComboBoxHandler
from bauble.ui.handlers import EntryHandler
from bauble.ui.handlers import EntryWCompletionHandler
from bauble.ui.presenter import DomainEditorDialog
from bauble.ui.presenter import EditCreateCallback
from bauble.ui.presenter import GenericPresenter
from bauble.ui.presenter import Problem
from bauble.ui.presenter import Response
from bauble.ui.utils import cell_indicate_modified
from bauble.ui.utils import default_cell_data_func
from bauble.ui.utils import enum_string_func
from bauble.ui.utils import populate_enum_combo
from bauble.ui.validators import Validator
from bauble.ui.validators import validate_date
from bauble.ui.widgets import DatePickerBox
from bauble.ui.widgets import NoteBox
from bauble.ui.widgets import NotesPresenter
from bauble.ui.widgets import PictureBox

from ...plants.ui.widgets.species import species_cell_data_func
from ...plants.ui.widgets.species import species_completions
from ...plants.ui.widgets.species import species_match_func
from ..plant import Plant
from ..plant import plant_match_func
from ..propagation import PlantPropSource
from ..propagation import Propagation
from ..propagation import PropEvent
from ..propagation import PropEventType
from ..propagation import PropType

if TYPE_CHECKING:
    from ...plants.species import Species

parent = Path(__file__).resolve().parent


@Gtk.Template(filename=str(parent / "prop_event_presenter.ui"))
class PropEventPresenter(GenericPresenter[PropEvent], Gtk.Frame):
    """Presenter for editing a PropEvent."""

    __gtype_name__ = "PropEventPresenter"

    __gsignals__: dict = {"changed": (GObject.SignalFlags.RUN_FIRST, None, ())}

    type_liststore = cast(Gtk.ListStore, Gtk.Template.Child())
    type_combo = cast(Gtk.ComboBox, Gtk.Template.Child())
    type_cell = cast(Gtk.CellRendererText, Gtk.Template.Child())
    date_picker = cast(DatePickerBox, Gtk.Template.Child())
    quantity_spinbutton = cast(Gtk.SpinButton, Gtk.Template.Child())
    quantity_adj = cast(Gtk.Adjustment, Gtk.Template.Child())
    success_spinbutton = cast(Gtk.SpinButton, Gtk.Template.Child())
    success_adj = cast(Gtk.Adjustment, Gtk.Template.Child())
    available_spinbutton = cast(Gtk.SpinButton, Gtk.Template.Child())
    available_adj = cast(Gtk.Adjustment, Gtk.Template.Child())
    person_entry = cast(Gtk.Entry, Gtk.Template.Child())
    person_liststore = cast(Gtk.ListStore, Gtk.Template.Child())
    notes_textview = cast(Gtk.TextView, Gtk.Template.Child())
    notes_textbuffer = cast(Gtk.TextBuffer, Gtk.Template.Child())

    on_type_combo_changed = ComboBoxHandler(must_match=True)
    on_date_changed = EntryHandler(
        [Validator(validate_date, "invalid_date")],
        lambda value, *_args: parse_str_date(value, as_date=True),
    )
    on_spin_button_changed = EntryHandler(
        converter=lambda value, *_args: int(value or 0),
    )

    def __init__(self) -> None:
        super().__init__(None, self)

        self.session: Session
        self.date_entry: Gtk.Entry

    def init(self, session: Session) -> None:
        self.session = session

        spell_view = Gspell.TextView.get_from_gtk_text_view(
            self.notes_textview
        )
        spell_view.basic_setup()

        self.date_picker.init()
        self.date_entry = self.date_picker.entry

        self.setup_type_combo()

        self.widgets_to_model_map = {
            self.type_combo: "event_type",
            self.date_entry: "date",
            self.person_entry: "person",
            self.quantity_spinbutton: "quantity",
            self.success_spinbutton: "success",
            self.available_spinbutton: "available",
            self.notes_textbuffer: "event_notes",
        }

    def setup_type_combo(self) -> None:

        self.type_combo.set_cell_data_func(
            self.type_cell,
            default_cell_data_func,
        )

        type_tooltip = _("The type of event, available types:\n")

        for type_ in self.session.scalars(select(PropEventType)):
            self.type_liststore.append((type_,))
            type_tooltip += f"    {type_.name} - {type_.description}\n"

        type_tooltip += _("You can add more types using the add button")
        self.type_combo.set_tooltip_text(type_tooltip)
        self.type_combo.set_active(1)

    def set_model(self, model: PropEvent | None) -> None:
        if model is None:
            self.set_sensitive(False)
            return
        logger.debug("setting model to %s", model)

        super().set_model(model)

        # ensure current user is always first in the list
        self.person_liststore.append((utils.get_user_display_name(),))

        for person in self.session.execute(
            select(PropEvent.person).distinct().order_by(PropEvent.person)
        ).scalars():
            if person == utils.get_user_display_name():
                continue
            self.person_liststore.append((person,))

        self.constrain_widgets()
        self.set_sensitive(True)
        self.refresh_all_widgets_from_model()

        if self.model.event_type is None:
            self.type_combo.set_active(0)

        self.person_entry.emit("changed")
        self.emit("changed")

    @property
    def can_commit(self) -> bool:
        # only after model is set
        if getattr(self, "model", None):

            no_problems = not self.problems
            modified = self.session.is_modified(self.model)

            return all((modified, no_problems))

        return True

    @Gtk.Template.Callback()
    def on_type_changed(self, combo: Gtk.ComboBox) -> None:
        # only after model is set
        if getattr(self, "model", None):
            self.on_type_combo_changed(combo)
            self.constrain_widgets()

        self.emit("changed")

    def constrain_widgets(self) -> None:
        if self.model.propagation is None:
            return

        events = self.model.propagation.events
        index = events.index(self.model)
        len_events = len(events)

        logger.debug("constraining widgets, idex=%s", index)

        prior_quantity = sum(i.quantity for i in events[:index])
        prior_success = sum(i.success for i in events[:index])
        prior_available = sum(i.available for i in events[:index])

        prior_remaining_quantity = prior_quantity - prior_success
        prior_remaining_available = prior_success - prior_available

        self._constrain_spinbutton("quantity", "Q", lower=-prior_quantity)
        self._constrain_spinbutton(
            "success",
            "S",
            upper=prior_remaining_quantity,
            lower=-prior_success,
        )
        self._constrain_spinbutton(
            "available",
            "A",
            upper=prior_remaining_available,
            lower=-prior_available,
        )

        start_date: datetime.date | None = None
        end_date: datetime.date | None = None

        if index > 0:
            start_date = events[index - 1].date

        if index < len_events - 1:
            end_date = events[index + 1].date

        self.date_picker.constrain_range(start_date, end_date)

    def _constrain_spinbutton(
        self,
        column: str,
        key: Literal["Q", "S", "A"],
        upper: int = 10000000,
        lower: int = 0,
    ) -> None:
        if self.model.event_type is None:
            return

        options = self.model.event_type.parsed_options()
        logger.debug("options = %s", options)

        adds = options[key]["adds"]
        reduces = options[key]["reduces"]
        sensitive = any((adds, reduces))

        spinbutton = getattr(self, f"{column}_spinbutton")
        spinbutton.set_sensitive(sensitive)

        if not sensitive:
            return

        adjustment = getattr(self, f"{column}_adj")

        start = getattr(self.model, column)

        if reduces and not adds:
            upper = 0
        if adds and not reduces:
            lower = 0

        adjustment.set_upper(upper)
        adjustment.set_lower(lower)

        logger.debug(
            "constraining %s upper = %s, lower = %s",
            column,
            upper,
            lower,
        )

        spinbutton.set_value(start)

    @Gtk.Template.Callback()
    def on_date_entry_changed(self, date_picker: DatePickerBox) -> None:
        self.on_date_changed(date_picker.entry)
        self.emit("changed")

    @on_date_changed.validator(problem_name="not_in_range")
    def validate_date_range(self, date: datetime.date, *_args) -> bool:
        return self.date_picker.validate_date_in_range(date)

    @Gtk.Template.Callback()
    def on_spinbutton_changed(self, spin_btn: Gtk.SpinButton) -> None:
        self.on_spin_button_changed(spin_btn)
        self.emit("changed")

    @Gtk.Template.Callback()
    def on_text_entry_changed(self, entry: Gtk.Entry) -> None:
        # pylint: disable=not-callable
        super().on_non_empty_text_entry_changed(entry)
        self.emit("changed")

    @Gtk.Template.Callback()
    def on_text_buffer_changed(self, buffer: Gtk.TextBuffer) -> None:
        # pylint: disable=not-callable
        super().on_text_buffer_changed(buffer)
        self.emit("changed")


@Gtk.Template(filename=str(parent / "source_plant_editor.ui"))
class SourcePlantEditorDialog(
    GenericPresenter[PlantPropSource],
    Gtk.Dialog,
):

    __gtype_name__ = "SourcePlantEditorDialog"

    __gsignals__ = GenericPresenter.gsignals

    plant_entry = cast(Gtk.Entry, Gtk.Template.Child())
    plant_cell = cast(Gtk.CellRendererText, Gtk.Template.Child())
    type_combo = cast(Gtk.ComboBox, Gtk.Template.Child())
    material_combo = cast(Gtk.ComboBox, Gtk.Template.Child())
    ok_button = cast(Gtk.Button, Gtk.Template.Child())

    on_completion_entry_matched = EntryWCompletionHandler(must_match=True)
    on_combo_changed = ComboBoxHandler(must_match=True)

    def __init__(
        self,
        model: PlantPropSource,
        session: Session,
        transient_for: Gtk.Window | None = None,
    ) -> None:
        super().__init__(model, self)

        self.session = session

        plant_completion = self.plant_entry.get_completion()
        plant_completion.set_cell_data_func(
            self.plant_cell,
            default_cell_data_func,
            lambda value: f"{value} {value.accession.species.full_name}",
        )
        plant_completion.set_match_func(plant_match_func)

        self.widgets_to_model_map = {
            self.plant_entry: "plant",
            self.type_combo: "source_type",
            self.material_combo: "source_material",
        }
        self.set_transient_for(transient_for)
        self.set_destroy_with_parent(True)

        populate_enum_combo(self.type_combo, self.model, "source_type")
        populate_enum_combo(self.material_combo, self.model, "source_material")

        self.plant_entry.grab_focus()
        self.refresh_all_widgets_from_model()
        self.connect("problems-changed", self.on_problems_changed)
        # triger problems
        self.plant_entry.emit("changed")
        self.type_combo.emit("changed")
        self.material_combo.emit("changed")

    @Gtk.Template.Callback()
    def on_combobox_changed(self, combo: Gtk.ComboBox) -> None:
        self.on_combo_changed(combo)

    @Gtk.Template.Callback()
    def on_plant_entry_changed(self, entry: Gtk.Entry) -> None:
        self.on_completion_entry_matched(
            entry,
            get_values=self.plant_get_completions,
        )

    def plant_get_completions(
        self,
        text: str,
    ) -> Result:

        from ...plants.species import Species
        from ..accession import Accession

        with_wildcards = "%" + "% %".join(text.split()) + "%"

        string_expr = (
            Accession.code
            + Plant.get_delimiter()
            + Plant.code
            + " "
            + Species.full_name
        )

        # exlude any plants that are already in the source list
        current_plant_ids = [
            p.id for p in self.model.propagation.plants if p is not None
        ]

        stmt = (
            select(Plant)
            .join(Accession)
            .join(Species)
            .where(string_expr.ilike(with_wildcards))
            .where(Plant.quantity > 0)
            .where(Plant.id.not_in(current_plant_ids))
            .limit(20)
            .order_by(Accession.code, Plant.code)
        )

        return self.session.execute(stmt)

    def on_problems_changed(self, _view: Self, has_problems: bool) -> None:
        # could use an `update` method instead, to prevent OK being sensitive
        # if the model is not modified, but this could lead to the situation,
        # when editing an existing propagation, of not being able to change
        # back from setting the type to secondary on a single source plant - a
        # problem for the propagation editor's source_treeview.
        self.ok_button.set_sensitive(not has_problems)


@Gtk.Template(filename=str(parent / "propagation_editor.ui"))
class PropagationEditorDialog(
    DomainEditorDialog[Propagation],
    Gtk.Dialog,
):  # pylint: disable=not-callable,too-many-public-methods

    __gtype_name__ = "PropagationEditorDialog"

    __gsignals__ = GenericPresenter.gsignals

    revealer = cast(Gtk.Revealer, Gtk.Template.Child())
    code_entry = cast(Gtk.Entry, Gtk.Template.Child())
    species_box = cast(Gtk.Box, Gtk.Template.Child())
    species_entry = cast(Gtk.Entry, Gtk.Template.Child())
    species_liststore = cast(Gtk.ListStore, Gtk.Template.Child())
    species_cell = cast(Gtk.CellRendererText, Gtk.Template.Child())
    type_combo = cast(Gtk.ComboBox, Gtk.Template.Child())
    type_liststore = cast(Gtk.ListStore, Gtk.Template.Child())
    type_cell = cast(Gtk.CellRendererText, Gtk.Template.Child())
    date_picker = cast(DatePickerBox, Gtk.Template.Child())
    propagator_entry = cast(Gtk.Entry, Gtk.Template.Child())
    propagator_liststore = cast(Gtk.ListStore, Gtk.Template.Child())
    source_liststore = cast(Gtk.ListStore, Gtk.Template.Child())
    source_treeview = cast(Gtk.TreeView, Gtk.Template.Child())
    source_plant_column = cast(Gtk.TreeViewColumn, Gtk.Template.Child())
    source_plant_cell = cast(Gtk.CellRendererText, Gtk.Template.Child())
    source_type_column = cast(Gtk.TreeViewColumn, Gtk.Template.Child())
    source_type_cell = cast(Gtk.CellRendererText, Gtk.Template.Child())
    source_material_column = cast(Gtk.TreeViewColumn, Gtk.Template.Child())
    source_material_cell = cast(Gtk.CellRendererText, Gtk.Template.Child())
    remove_source_button = cast(Gtk.Button, Gtk.Template.Child())
    media_comboentry = cast(Gtk.ComboBox, Gtk.Template.Child())
    media_liststore = cast(Gtk.ListStore, Gtk.Template.Child())
    container_comboentry = cast(Gtk.ComboBox, Gtk.Template.Child())
    container_liststore = cast(Gtk.ListStore, Gtk.Template.Child())
    location_comboentry = cast(Gtk.ComboBox, Gtk.Template.Child())
    location_liststore = cast(Gtk.ListStore, Gtk.Template.Child())
    notes_textview = cast(Gtk.TextView, Gtk.Template.Child())
    notes_textbuffer = cast(Gtk.TextBuffer, Gtk.Template.Child())
    add_event_button = cast(Gtk.Button, Gtk.Template.Child())
    remove_event_button = cast(Gtk.Button, Gtk.Template.Child())
    events_frame = cast(Gtk.Frame, Gtk.Template.Child())
    events_liststore = cast(Gtk.ListStore, Gtk.Template.Child())
    events_treeview = cast(Gtk.TreeView, Gtk.Template.Child())
    event_date_column = cast(Gtk.TreeViewColumn, Gtk.Template.Child())
    event_date_cell = cast(Gtk.CellRendererText, Gtk.Template.Child())
    event_type_column = cast(Gtk.TreeViewColumn, Gtk.Template.Child())
    event_type_cell = cast(Gtk.CellRendererText, Gtk.Template.Child())
    event_person_column = cast(Gtk.TreeViewColumn, Gtk.Template.Child())
    event_person_cell = cast(Gtk.CellRendererText, Gtk.Template.Child())
    event_quantity_column = cast(Gtk.TreeViewColumn, Gtk.Template.Child())
    event_quantity_cell = cast(Gtk.CellRendererText, Gtk.Template.Child())
    event_success_column = cast(Gtk.TreeViewColumn, Gtk.Template.Child())
    event_success_cell = cast(Gtk.CellRendererText, Gtk.Template.Child())
    event_available_column = cast(Gtk.TreeViewColumn, Gtk.Template.Child())
    event_available_cell = cast(Gtk.CellRendererText, Gtk.Template.Child())
    event_notes_column = cast(Gtk.TreeViewColumn, Gtk.Template.Child())
    event_notes_cell = cast(Gtk.CellRendererText, Gtk.Template.Child())
    state_label = cast(Gtk.Label, Gtk.Template.Child())

    prop_event_presenter = cast(PropEventPresenter, Gtk.Template.Child())
    notes_presenter = cast(NotesPresenter[NoteBox], Gtk.Template.Child())
    pictures_presenter = cast(NotesPresenter[PictureBox], Gtk.Template.Child())

    on_type_combo_changed = ComboBoxHandler(must_match=True)
    on_date_changed = EntryHandler(
        [Validator(validate_date, "invalid_date")],
        lambda value, *_args: parse_str_date(value, as_date=True),
    )
    on_completion_entry_matched = EntryWCompletionHandler(must_match=True)

    PROBLEM_PRIMARY = Problem("no_primary_source")

    def __init__(
        self,
        model: Propagation,
        session: Session,
        transient_for: Gtk.Window | None = None,
    ) -> None:

        super().__init__(model, session, transient_for=transient_for)

        self.setup_type_combo()

        self.date_picker.init()
        self.date_entry = self.date_picker.entry

        self._populate_liststores()
        self._setup_data_funcs()

        spellview = Gspell.TextView.get_from_gtk_text_view(self.notes_textview)
        spellview.basic_setup()

        species_completion = self.species_entry.get_completion()
        species_completion.set_cell_data_func(
            self.species_cell,
            species_cell_data_func,
        )
        species_completion.set_match_func(species_match_func)

        self.widgets_to_model_map = {
            self.code_entry: "code",
            self.species_entry: "species",
            self.type_combo: "prop_type",
            self.date_entry: "date",
            self.propagator_entry: "propagator",
            self.media_comboentry: "media",
            self.container_comboentry: "container",
            self.location_comboentry: "location",
            self.notes_textbuffer: "prop_notes",
        }

        if self.model.id is None:
            if model.date is None:
                self.model.date = datetime.date.today()
            if model.propagator is None:
                self.model.propagator = utils.get_user_display_name()

        self.connect("problems-changed", self.on_problems_changed)
        self.refresh_all_widgets_from_model()
        self.populate_source_list()

        self.notes_presenter.init(self.model)
        self.pictures_presenter.init(self.model, "pictures", PictureBox)
        self.prop_event_presenter.init(self.session)
        # trigger problems
        self.type_combo.emit("changed")

        events_selection = self.events_treeview.get_selection()
        events_selection.set_select_function(self.events_selection_func)
        self.populate_events()

    def _populate_liststores(self) -> None:

        # ensure current user is always first in the list
        self.propagator_liststore.append((utils.get_user_display_name(),))

        for propagator in self.session.execute(
            select(Propagation.propagator)
            .distinct()
            .order_by(Propagation.propagator)
        ).scalars():
            if propagator == utils.get_user_display_name():
                continue
            self.propagator_liststore.append((propagator,))

        for media in self.session.execute(
            select(Propagation.media).distinct().order_by(Propagation.media)
        ).scalars():
            self.media_liststore.append((media,))

        for container in self.session.execute(
            select(Propagation.container)
            .distinct()
            .order_by(Propagation.container)
        ).scalars():
            self.container_liststore.append((container,))

        for location in self.session.execute(
            select(Propagation.location)
            .distinct()
            .order_by(Propagation.location)
        ).scalars():
            self.location_liststore.append((location,))

    def _setup_data_funcs(self) -> None:
        cell_data_func = partial(
            default_cell_data_func,
            render_func=cell_indicate_modified,
        )
        self.source_plant_column.set_cell_data_func(
            self.source_plant_cell,
            cell_data_func,
            lambda val: f"{val.plant} {val.plant.accession.species.full_name}",
        )
        self.source_type_column.set_cell_data_func(
            self.source_type_cell,
            cell_data_func,
            partial(enum_string_func, prop="source_type"),
        )
        self.source_material_column.set_cell_data_func(
            self.source_material_cell,
            cell_data_func,
            partial(enum_string_func, prop="source_material"),
        )

        self.event_date_column.set_cell_data_func(
            self.event_date_cell,
            cell_data_func,
            lambda val: utils.date_string(val.date),
        )
        self.event_type_column.set_cell_data_func(
            self.event_type_cell,
            cell_data_func,
            lambda val: str(val.event_type or ""),
        )
        self.event_person_column.set_cell_data_func(
            self.event_person_cell,
            cell_data_func,
            lambda val: val.person or "",
        )
        self.event_quantity_column.set_cell_data_func(
            self.event_quantity_cell,
            cell_data_func,
            lambda val: str(val.quantity),
        )
        self.event_success_column.set_cell_data_func(
            self.event_success_cell,
            cell_data_func,
            lambda val: str(val.success),
        )
        self.event_available_column.set_cell_data_func(
            self.event_available_cell,
            cell_data_func,
            lambda val: str(val.available),
        )
        self.event_notes_column.set_cell_data_func(
            self.event_notes_cell,
            cell_data_func,
            lambda val: val.event_notes or "",
        )

    def on_problems_changed(self, _view: Self, has_problems: bool) -> None:
        self.events_frame.set_sensitive(not has_problems)

    def update(self) -> None:
        if self.model.id is None:
            self.code_entry.set_text(self.model.get_next_code())

        super().update()

    @property
    def can_commit(self) -> bool:
        modified = self.session.is_modified(self.model)
        if not modified:
            modified = any(
                self.session.is_modified(i) for i in self.session.dirty
            )

        notes_can_commit = self.notes_presenter.can_commit
        pics_can_commit = self.pictures_presenter.can_commit
        events_can_commit = self.prop_event_presenter.can_commit

        no_problems = not self.problems

        return all(
            (
                modified,
                no_problems,
                notes_can_commit,
                pics_can_commit,
                events_can_commit,
            )
        )

    def populate_source_list(self) -> None:
        logger.debug("refreshing source list")
        self.source_liststore.clear()
        self.remove_problem(self.PROBLEM_PRIMARY, self.source_treeview)

        has_primary = False

        species = None
        all_same_species = True

        for source in self.model.plant_sources:
            logger.debug("adding source %s", source)
            if source.source_type == "1":
                logger.debug("source is primary")
                has_primary = True

            if species is None:
                species = source.plant.accession.species
            elif source.plant.accession.species_id != species.id:
                all_same_species = False

            self.source_liststore.append((source,))

        if not has_primary:
            self.add_problem(self.PROBLEM_PRIMARY, self.source_treeview)

        if all_same_species:
            self.model.species = species
            self.species_entry.set_text(str(species))
            self.species_box.set_sensitive(False)
        else:
            if not self.model.id:
                self.species_entry.set_text("")
            self.species_box.set_sensitive(True)
            self.species_entry.emit("changed")

    @Gtk.Template.Callback()
    def on_code_entry_changed(self, entry: Gtk.Entry) -> None:
        super().on_unique_text_entry_changed(entry)

    @Gtk.Template.Callback()
    def on_code_edit_button_toggled(self, button: Gtk.ToggleButton) -> None:
        self.code_entry.set_sensitive(button.get_active())

    @Gtk.Template.Callback()
    def on_species_entry_changed(self, entry: Gtk.Entry) -> None:
        # pylint: disable=not-callable
        self.on_completion_entry_matched(
            entry,
            get_values=self.species_get_completions,
        )

    def species_get_completions(
        self,
        text: str,
    ) -> Result | list[tuple[Species]]:
        if str(self.model.species) == text:
            return [(self.model.species,)]

        return self.session.execute(species_completions(text).limit(20))

    @Gtk.Template.Callback()
    def on_type_changed(self, combo: Gtk.ComboBox) -> None:
        self.on_type_combo_changed(combo)

    @Gtk.Template.Callback()
    def on_date_entry_changed(self, datepicker: DatePickerBox) -> None:
        self.on_date_changed(datepicker.entry)

    @Gtk.Template.Callback()
    def on_text_entry_changed(self, entry: Gtk.Entry) -> None:
        super().on_text_entry_changed(entry)

    @Gtk.Template.Callback()
    def on_add_source_button_clicked(self, _button: Gtk.Button) -> None:
        new_source_plant = PlantPropSource(propagation=self.model)
        dialog = SourcePlantEditorDialog(new_source_plant, self.session, self)

        if dialog.run() == Gtk.ResponseType.OK:
            self.populate_source_list()
        else:
            self.model.plant_sources.remove(new_source_plant)

        self.present()
        dialog.destroy()
        self.update()

    @Gtk.Template.Callback()
    def on_remove_source_button_clicked(self, _button: Gtk.Button) -> None:
        model = iter_ = None
        selection = self.source_treeview.get_selection()
        selected = selection.get_selected()
        if selected:
            model, iter_ = selected

        if iter_:
            source = model[iter_][0]
            self.model.plant_sources.remove(source)
            self.populate_source_list()

    @Gtk.Template.Callback()
    def on_species_add_button_clicked(self, _button: Gtk.Button) -> None:

        from ...plants.species import Species
        from ...plants.ui.species_editor import SpeciesEditorDialog

        species = Species()

        genus_ids = {
            i.plant.accession.species.genus_id
            for i in self.model.plant_sources
        }

        if len(genus_ids) == 1:
            genus = self.model.plant_sources[0].plant.accession.species.genus
            species.genus = genus

        with db.Session() as session:
            dialog = SpeciesEditorDialog(
                species,
                session,
                transient_for=self,
            )

            if dialog.run() not in [Response.OK, Response.RETURN]:
                dialog.destroy()
                return

            species = self.session.merge(dialog.model)
            dialog.destroy()

        self.present()
        self.model.species = species
        self.species_entry.set_text(str(species))

    @Gtk.Template.Callback()
    def on_source_activated(
        self,
        _tree_view: Gtk.TreeView,
        path: Gtk.TreePath,
        _column: Gtk.TreeViewColumn,
    ) -> None:
        iter_ = self.source_liststore.get_iter(path)
        source = self.source_liststore.get_value(iter_, 0)
        dialog = SourcePlantEditorDialog(source, self.session, self)

        if dialog.run() == Gtk.ResponseType.OK:
            self.populate_source_list()
        else:
            self.session.expire(source)

        self.update()

        dialog.destroy()

    @Gtk.Template.Callback()
    def on_source_selection_changed(
        self,
        selection: Gtk.TreeSelection,
    ) -> None:
        sensitive = bool(selection.count_selected_rows())
        self.remove_source_button.set_sensitive(sensitive)

    @Gtk.Template.Callback()
    def on_comboentry_changed(self, combo: Gtk.ComboBox) -> None:
        super().on_combobox_changed(combo)

    @Gtk.Template.Callback()
    def on_text_buffer_changed(self, buffer: Gtk.TextBuffer) -> None:
        super().on_text_buffer_changed(buffer)

    @Gtk.Template.Callback()
    def on_changed(self, _presenter: Gtk.Widget) -> None:
        self.update()

    def events_selection_func(
        self,
        _selection: Gtk.TreeSelection,
        _model: Gtk.TreeModel,
        _path: Gtk.TreePath,
        _is_selected: bool,
    ) -> bool:
        """Disallow changing if problems with the currently selected."""
        if self.prop_event_presenter.problems:
            return False
        return True

    def setup_type_combo(self) -> None:

        self.type_combo.set_cell_data_func(
            self.type_cell,
            default_cell_data_func,
        )

        type_tooltip = _("The type of propagation, available types:\n")

        for type_ in self.session.execute(
            select(PropType).order_by(PropType.name)
        ).scalars():
            self.type_liststore.append((type_,))
            type_tooltip += f"    {type_.name} - {type_.description}\n"

        type_tooltip += _("You can add more types using the add button")
        self.type_combo.set_tooltip_text(type_tooltip)

    @Gtk.Template.Callback()
    def on_add_event_button_clicked(self, _button: Gtk.Button) -> None:
        last = self.session.scalar(
            select(func.max(PropEvent.date)).filter_by(
                propagation_id=self.model.id
            )
        )
        date = datetime.date.today()

        if last:
            date = max(last, date)

        event = PropEvent(
            date=date,
            person=utils.get_user_display_name(),
            quantity=0,
            success=0,
            available=0,
        )

        self.model.events.append(event)
        self.populate_events()

        path = Gtk.TreePath.new_from_string(
            str(len(self.events_liststore) - 1)
        )
        self.events_treeview.set_cursor(path)

    @Gtk.Template.Callback()
    def on_remove_event_button_clicked(self, _button: Gtk.Button) -> None:

        model = iter_ = None
        selection = self.events_treeview.get_selection()
        selected = selection.get_selected()
        if selected:
            model, iter_ = selected

        if iter_:
            source = model[iter_][0]
            self.model.events.remove(source)
            self.populate_events()

    def populate_events(self) -> None:
        self.events_liststore.clear()

        # for event in self.model.events:
        for event in sorted(
            self.model.events,
            key=lambda val: val.date or datetime.date.today(),
        ):
            self.events_liststore.append((event,))

    @Gtk.Template.Callback()
    def on_event_selection_changed(self, selection: Gtk.TreeSelection) -> None:
        model = iter_ = event = None
        selected = selection.get_selected()

        if selected:
            model, iter_ = selected

        if iter_:
            event = model[iter_][0]

        # give the tree selection func time to process the unselecting first
        GLib.idle_add(self.prop_event_presenter.set_model, event)

        self.remove_event_button.set_sensitive(bool(event))

    @Gtk.Template.Callback()
    def on_events_changed(self, presenter: PropEventPresenter) -> None:

        logger.debug("events changed")

        context = self.events_treeview.get_style_context()
        context.remove_class("problem-selected")

        # refresh the list_store to get the treeview to update
        model = iter_ = None
        selection = self.events_treeview.get_selection()
        selected = selection.get_selected()

        if selected:
            model, iter_ = selected

        if iter_ is not None:
            path = model.get_path(iter_)
            # refresh
            model.row_changed(path, iter_)

        self.add_event_button.set_sensitive(bool(not presenter.problems))

        if presenter.problems:
            # this from the cell_data_func
            context.remove_class("modified-selected")
            context.add_class("problem-selected")

        self.on_changed(presenter)
        self.state_label.set_text(
            f"Quantity: {self.model.quantity}\n"
            f"Total available: {self.model.available}\n"
            f"Currently available: {self.model.unused}\n"
            f"Success: {self.model.percent_success:.1f}%"
        )

    @Gtk.Template.Callback()
    def on_response(
        self,
        dialog: Self,
        response: Response,
    ) -> bool:
        propagator = self.model.propagator
        date = self.model.date
        if response in [
            Response.NEXT,
            Response.OK,
        ]:
            if self.do_commit() is False:
                logger.debug("commit failed")
                dialog.stop_emission_by_name("response")
                return True

        if response == Response.NEXT:
            create_propagation(propagator=propagator, date=date)

        elif response == Response.CANCEL:
            # most likely not needed
            self.session.rollback()
            self.session.close()

        if not self.get_modal():
            # allow chaining response signal
            GLib.idle_add(self.destroy)

        return False


edit_callback = EditCreateCallback(
    PropagationEditorDialog,
    Propagation,
)

create_propagation = edit_callback
