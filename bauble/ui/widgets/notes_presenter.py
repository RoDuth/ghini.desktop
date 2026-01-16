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
Notes box for editor dialogs
"""
from pathlib import Path
from typing import cast

from gi.repository import GObject
from gi.repository import Gspell
from gi.repository import Gtk
from sqlalchemy import select
from sqlalchemy.orm import object_mapper

from bauble import db
from bauble import utils
from bauble.btypes import parse_str_date
from bauble.error import BaubleError
from bauble.i18n import _
from bauble.ui.handlers import EntryHandler
from bauble.ui.presenter import GenericPresenter
from bauble.ui.validators import Validator
from bauble.ui.validators import validate_date
from bauble.ui.widgets import DatePickerBox


@Gtk.Template(filename=str(Path(__file__).resolve().parent / "note_box.ui"))
class NoteBox(GenericPresenter[db.Note], Gtk.Box):
    """Generic notes presenter for individual notes.

    On changes emits ``changed`` signal.
    """

    # pylint: disable=not-callable

    # TODO `NoteBox` is already in use, change this ASAP
    __gtype_name__ = "NoteBox2"

    __gsignals__: dict = {"changed": (GObject.SignalFlags.RUN_FIRST, None, ())}

    expander = cast(Gtk.Expander, Gtk.Template.Child())
    category_combo = cast(Gtk.ComboBox, Gtk.Template.Child())
    category_liststore = cast(Gtk.ListStore, Gtk.Template.Child())
    date_picker = cast(DatePickerBox, Gtk.Template.Child())
    user_entry = cast(Gtk.Entry, Gtk.Template.Child())
    remove_button = cast(Gtk.Button, Gtk.Template.Child())
    note_textview = cast(Gtk.TextView, Gtk.Template.Child())
    note_textbuffer = cast(Gtk.TextBuffer, Gtk.Template.Child())

    on_date_changed = EntryHandler(
        [Validator(validate_date, "invalid_date")],
        lambda value, *_args: parse_str_date(value, as_date=True),
    )

    def __init__(self, model: db.Note) -> None:

        super().__init__(model, self)

        self.date_picker.init()
        self.date_entry = self.date_picker.entry

        self.widgets_to_model_map = {
            self.date_entry: "date",
            self.user_entry: "user",
            self.category_combo: "category",
            self.note_textbuffer: "note",
        }
        self.refresh_all_widgets_from_model()
        self.populate_categories()
        spell_view = Gspell.TextView.get_from_gtk_text_view(self.note_textview)
        spell_view.basic_setup()

    def populate_categories(self) -> None:
        stmt = select(self.model.__table__.c.category).distinct()

        with db.engine.connect() as connection:
            for category in connection.scalars(stmt):
                self.category_liststore.append([category])

    def set_expanded(self, expanded: bool) -> None:
        self.expander.set_expanded(expanded)

    @Gtk.Template.Callback()
    def on_date_entry_changed(self, date_picker: DatePickerBox) -> None:
        self.on_date_changed(date_picker.entry)

    @Gtk.Template.Callback()
    def on_category_combo_changed(self, combo: Gtk.ComboBox) -> None:
        super().on_combobox_changed(combo)

    @Gtk.Template.Callback()
    def on_text_entry_changed(self, entry: Gtk.Entry) -> None:
        super().on_text_entry_changed(entry)

    @Gtk.Template.Callback()
    def on_text_buffer_changed(self, buffer: Gtk.TextBuffer) -> None:
        super().on_text_buffer_changed(buffer)

    @Gtk.Template.Callback()
    def on_remove_button_clicked(self, _button: Gtk.Button) -> None:

        self.model.owner.notes.remove(self.model)

        self.emit("changed")
        self.destroy()

    def update(self) -> None:
        self.update_label()
        self.emit("changed")

    def update_label(self) -> None:
        label = []
        date_str = self.date_entry.get_text()
        user_str = self.user_entry.get_text()
        if date_str and user_str:
            label.append(
                _("%(user)s on %(date)s")
                % {"user": utils.xml_safe(self.model.user), "date": date_str}
            )
        elif date_str:
            label.append(date_str)
        elif user_str:
            label.append(user_str)

        category = cast(Gtk.Entry, self.category_combo.get_child()).get_text()
        if category:
            label.append(f"({category})")

        note = self.note_textbuffer.get_text(
            *self.note_textbuffer.get_bounds(),
            False,
        )

        if note:
            note_str = " : "
            note_str += utils.xml_safe(note).replace("\n", "  ")
            max_length = 25
            if len(note) > max_length:
                label.append(f"{note_str[0:max_length - 1]} …")
            else:
                label.append(note_str)

        self.expander.set_label(" ".join(label))


@Gtk.Template(
    filename=str(Path(__file__).resolve().parent / "notes_presenter.ui")
)
class NotesPresenter(Gtk.Box):
    """Provides a generic widget for handling notes on an item in the database.

    To use, include in your ``.ui`` file definition or instantiate otherwise
    then call ``init`` on it.  To react to changes connect to the ``changed``
    signal.  Check the ``can_commit`` attribute for problems before committing
    changes.
    """

    __gtype_name__ = "NotesPresenter"

    __gsignals__: dict = {"changed": (GObject.SignalFlags.RUN_FIRST, None, ())}

    expander_box = cast(Gtk.Box, Gtk.Template.Child())

    def __init__(self) -> None:
        super().__init__()
        self.note_cls: type[db.Note]
        self.model: db.Base

    def init(self, model: db.Base) -> None:
        """Setup the widget.

        :param model: a database model that has a ``notes`` attribute that
            contains db.Note objects.
        """
        if not hasattr(model, "notes"):
            raise BaubleError("model must have notes attribute")

        self.model = model
        self.note_cls = (
            object_mapper(model).get_property("notes").mapper.class_
        )
        for note in model.notes:
            self.add_note(note)

    @Gtk.Template.Callback()
    def on_add_button_clicked(self, _button: Gtk.Button) -> None:
        box = self.add_note()
        box.set_expanded(True)

    def add_note(self, note: db.Note | None = None) -> NoteBox:
        """Add a new note to the model."""
        if not note:
            note = self.note_cls()
            note.user = utils.get_user_display_name()
            note.date = utils.today_str()

            if hasattr(self.model, "notes"):
                self.model.notes.append(note)

        box = NoteBox(note)

        box.connect("changed", self.on_changed)
        self.expander_box.add(box)
        self.expander_box.reorder_child(box, 0)
        box.show_all()
        return box

    @property
    def can_commit(self) -> bool:
        for child in self.expander_box.get_children():
            if cast(NoteBox, child).problems:
                return False
        return True

    def on_changed(self, _box: NoteBox) -> None:
        self.emit("changed")
