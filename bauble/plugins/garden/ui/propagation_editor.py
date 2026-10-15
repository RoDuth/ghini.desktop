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

import logging
from functools import partial

logger = logging.getLogger(__name__)

import datetime
from pathlib import Path
from typing import Self
from typing import cast

from gi.repository import GLib
from gi.repository import Gspell
from gi.repository import Gtk
from sqlalchemy import select
from sqlalchemy.engine import Row
from sqlalchemy.orm import Session

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
from bauble.ui.utils import default_cell_data_func
from bauble.ui.utils import enum_string_func
from bauble.ui.utils import populate_enum_combo
from bauble.ui.validators import Validator
from bauble.ui.validators import validate_date
from bauble.ui.widgets import DatePickerBox
from bauble.ui.widgets import NoteBox
from bauble.ui.widgets import NotesPresenter
from bauble.ui.widgets import PictureBox

from ..plant import Plant
from ..plant import plant_match_func
from ..propagation import PlantPropSource
from ..propagation import Propagation
from ..propagation import PropType

parent = Path(__file__).resolve().parent


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
    ) -> list[Row] | list[tuple[Plant]]:

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
        )
        stmt = stmt.limit(20).distinct().order_by(Accession.code, Plant.code)

        return self.session.execute(stmt).all()

    def on_problems_changed(self, _foo: Self, has_problems: bool) -> None:
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

    revealer = cast(Gtk.Revealer, Gtk.Template.Child())
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
    quantity_spinbutton = cast(Gtk.SpinButton, Gtk.Template.Child())
    media_comboentry = cast(Gtk.ComboBox, Gtk.Template.Child())
    media_liststore = cast(Gtk.ListStore, Gtk.Template.Child())
    container_comboentry = cast(Gtk.ComboBox, Gtk.Template.Child())
    container_liststore = cast(Gtk.ListStore, Gtk.Template.Child())
    location_comboentry = cast(Gtk.ComboBox, Gtk.Template.Child())
    location_liststore = cast(Gtk.ListStore, Gtk.Template.Child())
    notes_textview = cast(Gtk.TextView, Gtk.Template.Child())
    notes_textbuffer = cast(Gtk.TextBuffer, Gtk.Template.Child())

    notes_presenter = cast(NotesPresenter[NoteBox], Gtk.Template.Child())
    pictures_presenter = cast(NotesPresenter[PictureBox], Gtk.Template.Child())

    on_type_combo_changed = ComboBoxHandler(must_match=True)
    on_date_changed = EntryHandler(
        [Validator(validate_date, "invalid_date")],
        lambda value, *_args: parse_str_date(value, as_date=True),
    )
    on_spin_button_changed = EntryHandler(
        [Validator(lambda value, *_args: int(value) > 0, "zero_qty")],
        lambda value, *_args: int(value or 0),
    )

    PROBLEM_PRIMARY = Problem("no_primary_source")

    def __init__(
        self,
        model: Propagation,
        session: Session,
        transient_for: Gtk.Window | None = None,
    ) -> None:

        super().__init__(model, session, transient_for=transient_for)

        self.set_type_tooltip()

        self.type_combo.set_cell_data_func(
            self.type_cell,
            default_cell_data_func,
        )

        self.date_picker.init()
        self.date_entry = self.date_picker.entry

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

        self.source_plant_column.set_cell_data_func(
            self.source_plant_cell,
            default_cell_data_func,
            lambda val: f"{val.plant} {val.plant.accession.species.full_name}",
        )
        self.source_type_column.set_cell_data_func(
            self.source_type_cell,
            default_cell_data_func,
            partial(enum_string_func, prop="source_type"),
        )
        self.source_material_column.set_cell_data_func(
            self.source_material_cell,
            default_cell_data_func,
            partial(enum_string_func, prop="source_material"),
        )

        spellview = Gspell.TextView.get_from_gtk_text_view(self.notes_textview)
        spellview.basic_setup()

        self.widgets_to_model_map = {
            self.type_combo: "prop_type",
            self.date_entry: "date",
            self.propagator_entry: "propagator",
            self.quantity_spinbutton: "quantity",
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

        self.refresh_all_widgets_from_model()
        self.refresh_source_list()

        self.notes_presenter.init(self.model)
        self.pictures_presenter.init(self.model, "pictures", PictureBox)
        # trigger problems
        self.type_combo.emit("changed")
        self.quantity_spinbutton.emit("changed")

    def set_type_tooltip(self) -> None:

        type_tooltip = _("The type of propagation, available types:\n")

        for type_ in self.session.execute(
            select(PropType).order_by(PropType.name)
        ).scalars():
            self.type_liststore.append((type_,))
            type_tooltip += f"    {type_.name} - {type_.description}\n"

        type_tooltip += _("You can add more types using the add button")
        self.type_combo.set_tooltip_text(type_tooltip)

    @property
    def can_commit(self) -> bool:
        modified = self.session.is_modified(self.model)
        if not modified:
            modified = any(
                self.session.is_modified(i) for i in self.session.dirty
            )

        no_problems = not self.problems

        return all((modified, no_problems))

    def refresh_source_list(self) -> None:
        logger.debug("refreshing source list")
        self.source_liststore.clear()
        self.remove_problem(self.PROBLEM_PRIMARY, self.source_treeview)

        has_primary = False

        for source in self.model.plant_sources:
            logger.debug("adding source %s", source)
            if source.source_type == "1":
                logger.debug("source is primary")
                has_primary = True

            self.source_liststore.append((source,))

        if not has_primary:
            self.add_problem(self.PROBLEM_PRIMARY, self.source_treeview)

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
    def on_new_source_button_clicked(self, _button: Gtk.Button) -> None:
        new_source_plant = PlantPropSource(propagation=self.model)
        dialog = SourcePlantEditorDialog(new_source_plant, self.session, self)

        if dialog.run() == Gtk.ResponseType.OK:
            self.refresh_source_list()
        else:
            self.model.plant_sources.remove(new_source_plant)

        dialog.destroy()

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
            self.refresh_source_list()

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
            self.refresh_source_list()
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
    def on_quantity_entry_changed(self, spin_btn: Gtk.SpinButton) -> None:
        self.on_spin_button_changed(spin_btn)

    @Gtk.Template.Callback()
    def on_comboentry_changed(self, combo: Gtk.ComboBox) -> None:
        super().on_combobox_changed(combo)

    @Gtk.Template.Callback()
    def on_text_buffer_changed(self, buffer: Gtk.TextBuffer) -> None:
        super().on_text_buffer_changed(buffer)

    @Gtk.Template.Callback()
    def on_changed(self, _presenter: Gtk.Widget) -> None:
        self.update()

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
