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
Plant GUI editor parts.
"""

import logging

logger = logging.getLogger(__name__)

from pathlib import Path
from typing import Any
from typing import Self
from typing import cast

from gi.repository import GLib
from gi.repository import Gtk
from sqlalchemy import and_
from sqlalchemy import or_
from sqlalchemy import select
from sqlalchemy.engine import Row
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import get_history

from bauble import db
from bauble import prefs
from bauble import utils
from bauble.i18n import _
from bauble.plugins.plants.genus import Genus
from bauble.plugins.plants.species import Species
from bauble.ui.handlers import ComboBoxHandler
from bauble.ui.handlers import EntryHandler
from bauble.ui.handlers import EntryWCompletionHandler
from bauble.ui.presenter import DomainEditorDialog
from bauble.ui.presenter import EditCreateCallback
from bauble.ui.presenter import Response
from bauble.ui.utils import default_completion_cell_data_func
from bauble.ui.utils import format_combo_entry_text
from bauble.ui.utils import get_widget_value
from bauble.ui.utils import populate_enum_combo
from bauble.ui.utils import search_tree_model
from bauble.ui.utils import set_widget_value
from bauble.ui.validators import Validator
from bauble.ui.validators import validate_non_empty
from bauble.ui.widgets import DatePickerBox
from bauble.ui.widgets import MapMenuButton
from bauble.ui.widgets import NoteBox
from bauble.ui.widgets import NotesPresenter
from bauble.ui.widgets import PictureBox
from bauble.ui.widgets.message import YesNoMessageBox
from bauble.utils.geo import KMLMapCallbackFunctor

from ..accession import Accession
from ..location import Location
from ..plant import Plant
from ..plant import PlantChange
from ..plant import added_reasons
from ..plant import change_reasons
from ..plant import deleted_reasons
from ..plant import get_next_code
from ..plant import new_plt_reasons
from ..plant import transfer_reasons
from .widgets.accession import accession_completion_cell_data_func
from .widgets.accession import accession_match_func
from .widgets.location import location_match_func
from .widgets.plant import PlantHistoryPresenter

PLANT_KML_MAP_PREFS = "kml_templates.plant"
"""pref for path to a custom mako kml template."""

parent = Path(__file__).resolve().parent


def validate_unique_code(value: str, *args: Any) -> bool:
    """Check uniqueness of the code in the DB."""
    model = args[1]

    if not model.accession:
        return True

    with db.Session() as session:

        model = session.merge(model)

        stmt = (
            select(Plant)
            .where(Plant.accession == model.accession)
            .where(Plant.code == value)
        )
        exists = session.scalars(stmt).one_or_none()

        if exists is not None and exists is not model:
            return False
    return True


def validate_new_not_zero(value: str, *args: Any) -> bool:
    model = args[1]

    with db.Session() as session:

        model = session.merge(model)
        if model in session.new and int(value) <= 0:
            return False
    return True


@Gtk.Template(filename=str(parent / "plant_editor.ui"))
class PlantEditorDialog(
    DomainEditorDialog[Plant],
    Gtk.Dialog,
):  # pylint: disable=not-callable,too-many-public-methods

    __gtype_name__ = "PlantEditorDialog"

    revealer = cast(Gtk.Revealer, Gtk.Template.Child())
    note_book = cast(Gtk.Notebook, Gtk.Template.Child())
    species_label = cast(Gtk.Label, Gtk.Template.Child())
    id_label = cast(Gtk.Label, Gtk.Template.Child())
    accession_entry = cast(Gtk.Entry, Gtk.Template.Child())
    accession_cell = cast(Gtk.CellRendererText, Gtk.Template.Child())
    code_entry = cast(Gtk.Entry, Gtk.Template.Child())
    type_combo = cast(Gtk.ComboBox, Gtk.Template.Child())
    quantity_entry = cast(Gtk.SpinButton, Gtk.Template.Child())
    location_comboentry = cast(Gtk.ComboBox, Gtk.Template.Child())
    location_entry = cast(Gtk.Entry, Gtk.Template.Child())
    location_liststore = cast(Gtk.ListStore, Gtk.Template.Child())
    location_cell = cast(Gtk.CellRendererText, Gtk.Template.Child())
    change_frame = cast(Gtk.Frame, Gtk.Template.Child())
    reason_combo = cast(Gtk.ComboBox, Gtk.Template.Child())
    reason_liststore = cast(Gtk.ListStore, Gtk.Template.Child())

    date_picker = cast(DatePickerBox, Gtk.Template.Child())
    map_menu_btn = cast(MapMenuButton, Gtk.Template.Child())
    notes_presenter = cast(NotesPresenter[NoteBox], Gtk.Template.Child())
    pictures_presenter = cast(NotesPresenter[PictureBox], Gtk.Template.Child())
    history_presenter = cast(PlantHistoryPresenter, Gtk.Template.Child())

    on_completion_entry_matched = EntryWCompletionHandler(must_match=True)
    on_location_combo_changed = ComboBoxHandler(must_match=True)
    on_unique_code_entry_changed = EntryHandler(
        [
            Validator(validate_non_empty, "empty"),
            Validator(validate_unique_code, "not_unique"),
        ],
        lambda value, *_args: value.strip() or None,
    )
    on_spin_button_changed = EntryHandler(
        [
            Validator(validate_non_empty, "empty"),
            Validator(validate_new_not_zero, "new_zero_qty"),
        ],
        lambda value, *_args: int(value or 0),
    )

    def __init__(
        self,
        model: Plant,
        session: Session,
        transient_for: Gtk.Window | None = None,
    ) -> None:

        super().__init__(model, session, transient_for=transient_for)

        accession_completion = self.accession_entry.get_completion()
        accession_completion.set_cell_data_func(
            self.accession_cell,
            accession_completion_cell_data_func,
        )
        accession_completion.set_match_func(accession_match_func)

        location_completion = self.location_entry.get_completion()
        location_completion.set_cell_data_func(
            self.location_cell,
            default_completion_cell_data_func,
        )
        location_completion.set_match_func(location_match_func)
        self.location_comboentry.set_cell_data_func(
            self.location_comboentry.get_cells()[0],
            default_completion_cell_data_func,
        )
        self.entry_sid = self.location_entry.connect(
            "changed",
            self.on_location_entry_changed,
        )

        for loc in self.session.execute(
            select(Location).order_by(Location.code)
        ).scalars():
            self.location_liststore.append((loc,))

        for k, v in change_reasons.items():
            self.reason_liststore.append((k, v))

        self.date_picker.init()
        self.change_date_entry = self.date_picker.entry
        self.change_date_entry.set_text(utils.today_str())

        self.widgets_to_model_map = {
            self.accession_entry: "accession",
            self.code_entry: "code",
            self.type_combo: "acc_type",
            self.quantity_entry: "quantity",
            self.location_comboentry: "location",
        }
        populate_enum_combo(self.type_combo, self.model, "acc_type")

        if self.model.id is None and self.model.acc_type is None:
            self.model.acc_type = "Plant"

        if self.model.quantity == 0:
            self.note_book.set_sensitive(False)
            GLib.idle_add(self.notify_is_dead)

        self.refresh_all_widgets_from_model()

        self.map_menu_btn.init(self.model, map_kml_callback)
        self.notes_presenter.init(self.model)
        self.pictures_presenter.init(self.model, "pictures", PictureBox)
        self.history_presenter.init(self.model)

        self.location_comboentry.emit("changed")
        self.accession_entry.emit("changed")
        self.quantity_entry.emit("changed")

        if self.model.code:
            current = self.get_title()
            self.set_title(f"{current} - {self.model}")

    @property
    def can_commit(self) -> bool:
        modified = self.session.is_modified(self.model)
        if not modified:
            modified = any(
                self.session.is_modified(i) for i in self.session.dirty
            )

        notes_can_commit = self.notes_presenter.can_commit
        pics_can_commit = self.pictures_presenter.can_commit

        no_problems = not self.problems

        return all(
            (
                modified,
                no_problems,
                notes_can_commit,
                pics_can_commit,
            )
        )

    @Gtk.Template.Callback()
    def on_changed(self, _presenter: Gtk.Widget) -> None:
        self.update()

    def update(self) -> None:
        super().update()

        loc_history = get_history(self.model, "location")
        qty_history = get_history(self.model, "quantity")

        self.change_frame.set_sensitive(
            any(
                (
                    self.model in self.session.new,
                    qty_history.has_changes(),
                    loc_history.has_changes(),
                )
            )
        )
        self.refresh_reasons()

    def refresh_reasons(self) -> None:
        current = get_widget_value(self.reason_combo)

        loc_history = get_history(self.model, "location")
        qty_history = get_history(self.model, "quantity")

        reasons: dict[str | None, str] = change_reasons
        default = None

        if self.model in self.session.new:
            reasons = new_plt_reasons
            default = "PLTD"
        elif loc_history.has_changes():
            reasons = transfer_reasons
        elif qty_history.has_changes():
            reasons = deleted_reasons

            added = int(qty_history.added[0])
            deleted = int(qty_history.deleted[0])
            quantity_change = added - deleted
            if quantity_change > 0:
                reasons = added_reasons

        if default is None and current in reasons:
            default = current

        self.reason_liststore.clear()
        for k, v in reasons.items():
            self.reason_liststore.append((k, v))

        set_widget_value(self.reason_combo, default)

    def refresh_labels(self) -> None:
        """Refresh the parents, fullname, prevname labels."""

        if self.model.id:
            self.id_label.set_text(str(self.model.id))
        else:
            self.id_label.set_text("")

        if self.model.accession is None:
            self.species_label.set_text("--")
            return

        sp_str = self.model.accession.species.string(markup=True, author=True)
        self.species_label.set_markup(f"{self.model}  {sp_str}")

    def notify_is_dead(self) -> None:

        def on_yes_clicked(_button: Gtk.Button) -> None:
            self.revealer.set_reveal_child(False)
            self.note_book.set_sensitive(True)

        def on_no_clicked(_button: Gtk.Button) -> None:
            self.revealer.set_reveal_child(False)

        msg = _(
            "Dead plant\n\n"
            "This plant has a quantity of zero (dead, discarded, etc.).\n"
            "In practice, it is not longer a part of the collection.\n\n"
            "Are you sure you want to edit it anyway?"
        )

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
    def on_accession_entry_changed(self, entry: Gtk.Entry) -> None:
        self.on_completion_entry_matched(
            entry,
            get_values=self.accession_get_completions,
        )

        if self.model.accession and not self.model.code:
            code = get_next_code(self.model.accession)
            self.code_entry.set_text(code)
        elif self.model.accession:
            self.code_entry.emit("changed")

        self.refresh_labels()

    def accession_get_completions(
        self,
        text: str,
    ) -> list[Row] | list[tuple[Accession]]:
        # if already populated match.
        if self.model.accession and self.model.accession.code == text:
            return [(self.model.accession,)]

        conditions = [
            utils.ilike(Accession.code, f"{text}%"),
            utils.ilike(Species.full_name, f"{text}%"),
        ]

        parts = text.split()

        if len(parts) > 1:
            conditions.append(
                and_(
                    utils.ilike(Accession.code, f"{parts[0]}%"),
                    utils.ilike(
                        Species.full_name, f"{'% '.join(parts[1].split())}%"
                    ),
                ),
            )
            conditions.append(
                utils.ilike(Species.full_name, f"{'% '.join(text.split())}%"),
            )

        stmt = (
            select(Accession)
            .join(Species)
            .join(Genus)
            .where(or_(*conditions))
            .distinct()
            .order_by(Accession.code)
            .limit(20)
        )
        return self.session.execute(stmt).all()

    @Gtk.Template.Callback()
    def on_code_entry_changed(self, entry: Gtk.Entry) -> None:
        self.on_unique_code_entry_changed(entry)

    @Gtk.Template.Callback()
    def on_combobox_changed(self, combo: Gtk.ComboBox) -> None:
        super().on_combobox_changed(combo)

    @Gtk.Template.Callback()
    def on_quantity_entry_changed(self, spin_btn: Gtk.SpinButton) -> None:
        self.on_spin_button_changed(spin_btn)

    @Gtk.Template.Callback()
    @staticmethod
    def on_comboentry_format(
        combo: Gtk.ComboBox,
        path: Gtk.TreePath,
    ) -> str:
        return format_combo_entry_text(combo, path)

    @Gtk.Template.Callback()
    def on_location_comboentry_changed(self, combo: Gtk.ComboBox) -> None:
        self.on_location_combo_changed(combo)

    def on_location_entry_changed(self, entry: Gtk.Entry) -> None:
        text = entry.get_text()

        def _cmp(row, data):
            loc = row[0]
            if str(loc).lower().startswith(data.lower()):
                return True

            if loc.code.lower().startswith(data.lower()):
                return True

            if loc.name and loc.name.lower().startswith(data.lower()):
                return True

            return False

        matches = search_tree_model(self.location_liststore, text, _cmp)

        if len(matches) == 1:
            completion = entry.get_completion()
            self.location_entry.handler_block(self.entry_sid)
            completion.emit(
                "match-selected",
                self.location_liststore,
                matches[0],
            )
            self.location_entry.handler_unblock(self.entry_sid)

    @Gtk.Template.Callback()
    def on_location_add_button_clicked(self, _button: Gtk.Button) -> None:

        from .location_editor import LocationEditorDialog

        with db.Session() as session:
            dialog = LocationEditorDialog(
                Location(),
                session,
                transient_for=self,
            )

            if dialog.run() not in [Response.OK, Response.RETURN]:
                dialog.destroy()
                return

            location = self.session.merge(dialog.model)
            dialog.destroy()

        self.model.location = location
        self.location_liststore.append((location,))
        set_widget_value(self.location_comboentry, location)

    def do_commit(self) -> bool:
        if self.change_frame.get_sensitive():
            self.model.changes.append(
                PlantChange(
                    reason=get_widget_value(self.reason_combo),
                    date=self.change_date_entry.get_text(),
                )
            )
        return super().do_commit()

    @Gtk.Template.Callback()
    def on_response(
        self,
        dialog: Self,
        response: Response,
    ) -> bool:
        accession = self.model.accession
        location = self.model.location
        if response in [
            Response.NEXT,
            Response.OK,
            Response.SAVE,
        ]:
            if self.do_commit() is False:
                logger.debug("commit failed")
                dialog.stop_emission_by_name("response")
                return True

        if response == Response.NEXT:
            create_plant(accession=accession, location=location)

        if response == Response.SAVE:
            edit_callback([self.model])

        elif response == Response.CANCEL:
            # most likely not needed
            self.session.rollback()
            self.session.close()

        if not self.get_modal():
            # allow chaining response signal
            GLib.idle_add(self.destroy)

        return False


map_kml_callback = KMLMapCallbackFunctor(
    prefs.prefs.get(PLANT_KML_MAP_PREFS, str(parent / "plant.kml"))
)

edit_callback = EditCreateCallback(
    PlantEditorDialog,
    Plant,
)

create_plant = edit_callback
