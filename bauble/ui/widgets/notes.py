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
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

import shutil
from datetime import datetime
from pathlib import Path
from typing import Any
from typing import Self
from typing import cast
from typing import overload

from gi.repository import GdkPixbuf
from gi.repository import GLib
from gi.repository import GObject
from gi.repository import Gspell
from gi.repository import Gtk
from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy.orm import object_mapper

from bauble import db
from bauble import prefs
from bauble import utils
from bauble.btypes import parse_str_date
from bauble.error import BaubleError
from bauble.i18n import _
from bauble.ui import dialogs
from bauble.ui.handlers import EntryHandler
from bauble.ui.presenter import GenericPresenter
from bauble.ui.utils import ImageLoader
from bauble.ui.utils import get_window_from_widget
from bauble.ui.utils import set_widget_value
from bauble.ui.validators import Validator
from bauble.ui.validators import validate_date
from bauble.ui.widgets import DatePickerBox

parent = Path(__file__).resolve().parent


@Gtk.Template(filename=str(parent / "note_box.ui"))
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

        self.update_label()

        self.initialised = False

        self.date_entry: Gtk.Entry

    def init(self) -> None:

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

        GLib.idle_add(self.setup_spell_checker)

        self.initialised = True

    def setup_spell_checker(self) -> None:
        spell_view = Gspell.TextView.get_from_gtk_text_view(self.note_textview)
        spell_view.basic_setup()

    def populate_categories(self) -> None:
        category = self.model.__table__.c.category
        stmt = (
            select(category)
            .where(category.is_not(None))
            .order_by(category)
            .distinct()
        )

        with db.engine.connect() as connection:
            for category in connection.scalars(stmt):
                self.category_liststore.append([category])

    def set_expanded(self, expanded: bool) -> None:
        self.expander.set_expanded(expanded)

    @Gtk.Template.Callback()
    def on_expanded(
        self,
        _expander: Gtk.Expander,
        _expanded: bool,
    ) -> None:
        # delay set up until required
        if self.initialised:
            return

        self.init()

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
        self.expander.set_label(str(self.model))


@Gtk.Template(filename=str(parent / "picture_box.ui"))
class PictureBox(GenericPresenter[db.Note], Gtk.Box):
    """Generic pictures presenter for individual pictures.

    Essentially a drop in replacement for a NoteBox that provides the extra
    widgets required for pictures.  Must be added to a NotesPresenter.

    On changes emits ``changed`` signal.
    """

    # pylint: disable=not-callable

    # TODO `PictureBox` is already in use, change this ASAP
    __gtype_name__ = "PictureBox2"

    __gsignals__: dict = {"changed": (GObject.SignalFlags.RUN_FIRST, None, ())}

    expander = cast(Gtk.Expander, Gtk.Template.Child())
    category_combo = cast(Gtk.ComboBox, Gtk.Template.Child())
    category_liststore = cast(Gtk.ListStore, Gtk.Template.Child())
    date_picker = cast(DatePickerBox, Gtk.Template.Child())
    user_entry = cast(Gtk.Entry, Gtk.Template.Child())
    remove_button = cast(Gtk.Button, Gtk.Template.Child())
    file_set_box = cast(Gtk.Box, Gtk.Template.Child())
    file_btnbrowse = cast(Gtk.Button, Gtk.Template.Child())
    file_entry = cast(Gtk.Entry, Gtk.Template.Child())
    picture_box = cast(Gtk.Box, Gtk.Template.Child())
    file_menu_btn = cast(Gtk.MenuButton, Gtk.Template.Child())

    on_date_changed = EntryHandler(
        [Validator(validate_date, "invalid_date")],
        lambda value, *_args: parse_str_date(value, as_date=True),
    )

    last_folder = str(Path.home())

    def __init__(self, model: db.Note) -> None:

        super().__init__(model, self)

        self.update_label()

        self.initialised = False

        self.date_entry: Gtk.Entry

    def init(self) -> None:

        self.date_picker.init()
        self.date_entry = self.date_picker.entry

        self.widgets_to_model_map = {
            self.date_entry: "date",
            self.user_entry: "user",
            self.category_combo: "category",
            self.file_entry: "picture",
        }
        self.refresh_all_widgets_from_model()
        self.populate_categories()

        if not self.file_entry.get_text():
            self.file_entry.emit("changed")

        self.initialised = True

    def get_presenter(self) -> NotesPresenter[PictureBox]:

        widget: Gtk.Widget = self
        while not isinstance(widget, NotesPresenter):
            widget = cast(Gtk.Widget, widget.get_parent())

        return widget

    def populate_categories(self) -> None:
        category = self.model.__table__.c.category
        stmt = (
            select(category)
            .where(category.is_not(None))
            .order_by(category)
            .distinct()
        )

        with db.engine.connect() as connection:
            for category in connection.scalars(stmt):
                self.category_liststore.append([category])

    def set_expanded(self, expanded: bool) -> None:
        self.expander.set_expanded(expanded)

    def set_content(self, text: str) -> None:

        for widget in list(self.picture_box.get_children()):
            widget.destroy()

        img: Gtk.Box | Gtk.Label | Gtk.Image
        if text.startswith("http://") or text.startswith("https://"):
            img = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            ImageLoader(img, text).start()
            self.file_btnbrowse.set_sensitive(False)
        elif text:
            img = Gtk.Image()
            pic_root = prefs.prefs[prefs.picture_root_pref]
            thumbname = Path(pic_root, "thumbs", text)
            filename = Path(pic_root, text)
            try:
                if thumbname.is_file():
                    pixbuf = GdkPixbuf.Pixbuf.new_from_file(str(thumbname))
                    img.set_from_pixbuf(pixbuf)
                    self.file_set_box.set_sensitive(False)
                elif filename.is_file():
                    pixbuf = GdkPixbuf.Pixbuf.new_from_file(str(filename))
                    if pixbuf:
                        pixbuf = pixbuf.apply_embedded_orientation()
                    if pixbuf:
                        scale_x = pixbuf.get_width() / 400.0
                        scale_y = pixbuf.get_height() / 400.0
                        scale = max(scale_x, scale_y, 1)
                        x = int(pixbuf.get_width() / scale)
                        y = int(pixbuf.get_height() / scale)
                        pixbuf = pixbuf.scale_simple(
                            x, y, GdkPixbuf.InterpType.BILINEAR
                        )
                    img.set_from_pixbuf(pixbuf)
                    self.file_set_box.set_sensitive(False)
                else:
                    label = _("picture file %s not found.") % text
                    img = Gtk.Label()
                    img.set_text(label)
            except GLib.GError as e:  # type: ignore
                logger.debug("picture %s caused GLib.GError %s", text, e)
                label = _("Error loading %s.") % text
                img = Gtk.Label()
                img.set_text(label)
            except Exception as e:  # pylint: disable=broad-except
                logger.warning("%s(%s)", type(e), e)
                img = Gtk.Label()
                img.set_text(f"{type(e).__name__}: {e}")
        else:
            # make button hold some text
            img = Gtk.Label()
            img.set_text(_("Choose a file or enter a URL…"))

        img.show()

        self.picture_box.add(img)
        self.picture_box.show()

    @Gtk.Template.Callback()
    def on_expanded(
        self,
        _expander: Gtk.Expander,
        _expanded: bool,
    ) -> None:
        # delay set up until required
        if self.initialised:
            return

        self.init()

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
    def on_file_entry_changed(self, entry: Gtk.Entry) -> None:
        super().on_text_entry_changed(entry)
        self.set_content(entry.get_text())

    @Gtk.Template.Callback()
    def on_remove_button_clicked(self, _button: Gtk.Button) -> None:
        # pylint: disable=protected-access
        text = self.file_entry.get_text()
        pic_root = prefs.prefs[prefs.picture_root_pref]
        thumbname = Path(pic_root, "thumbs", text)
        filename = Path(pic_root, text)
        if thumbname.is_file() or filename.is_file():
            logger.debug("is_file")

            parent_window = get_window_from_widget(self)
            # for testing
            msg = _("File %s exists, would you like to delete?") % text

            # check if file exists in other pictures first...
            tables = [
                table
                for name, table in db.metadata.tables.items()
                if name.endswith("_picture")
            ]

            for table in tables:
                stmt = select(func.count()).where(table.c.picture == text)

                if self.model.__tablename__ == table.name:
                    stmt = stmt.where(table.c.id != self.model.id)

                with db.engine.connect() as connection:
                    others = connection.execute(stmt).scalar()

                if others:
                    msg += _(
                        " %s other picture(s) of type %s exist using "
                        "the same file."
                    ) % (others, table.name)

            if dialogs.yes_no_dialog(msg, parent=parent_window, yes_delay=0.5):
                try:
                    if thumbname.is_file():
                        thumbname.unlink()
                    if filename.is_file():
                        filename.unlink()
                # pylint: disable=broad-exception-caught
                except Exception as e:
                    logger.debug("%s(%s)", type(e).__name__, e)
                    dialogs.message_details_dialog(
                        _("Error removing file...  File in use?"),
                        details=str(e),
                        parent=parent_window,
                    )
                    return
            self.model.owner._pictures.remove(self.model)
            self.destroy()
        else:
            # if the files don't exist, can remove the db entry
            self.model.owner._pictures.remove(self.model)
            self.destroy()

        self.emit("changed")

    @Gtk.Template.Callback()
    def on_file_btnbrowse_clicked(self, _button: Gtk.Button) -> None:
        file_chooser_dialog = Gtk.FileChooserNative.new(
            _("Select picture(s) to add…"),
            None,
            Gtk.FileChooserAction.OPEN,
        )
        file_chooser_dialog.set_select_multiple(True)
        file_chooser_dialog.set_current_folder(self.last_folder)
        file_chooser_dialog.run()
        filenames = file_chooser_dialog.get_filenames()

        try:
            self.add_from_files(filenames)
        except Exception as e:  # pylint: disable=broad-except
            logger.warning("unhandled exception: %s(%s)", type(e).__name__, e)
            dialogs.message_details_dialog(
                _("%s trying to add the selected files.") % type(e).__name__,
                str(e),
                Gtk.MessageType.WARNING,
                parent=get_window_from_widget(self),
            )

        file_chooser_dialog.destroy()

    def add_from_files(self, filenames: list[str]) -> None:

        presenter = self.get_presenter()

        boxes = [self]
        boxes += [presenter.add_note() for __ in range(len(filenames) - 1)]

        for box, filename in zip(boxes, filenames):
            # remember chosen location for next time
            path = Path(filename)
            self.__class__.last_folder = str(path.parent)
            logger.debug("new current folder is: %s", self.last_folder)
            # copy file to picture_root_dir (if not yet there),
            # check if the file already exists.
            destination = Path(
                prefs.prefs[prefs.picture_root_pref],
                path.name,
            )
            if destination.is_file():
                msg = _(
                    'A file with that name already exists, select "Yes" '
                    "and the name will be appended with a unique "
                    "identifier, if you wish to change the name "
                    'yourself select "No" to stop here so you can rename '
                    "it before returning."
                )
                parent_window = get_window_from_widget(self)

                if dialogs.yes_no_dialog(msg, parent=parent_window):
                    tstamp = datetime.now().strftime("%Y%m%d%M%S")
                    rename = f"{path.stem}_{tstamp}{path.suffix}"
                    self._copy_picture(box, path.name, rename)
                else:
                    pics = getattr(presenter.model, "_pictures")
                    if box.model in pics:
                        pics.remove(box.model)
                    box.destroy()
            else:
                self._copy_picture(box, path.name)

    def _copy_picture(
        self,
        box: Self,
        name: str,
        rename: str | None = None,
    ) -> None:
        utils.copy_picture_with_thumbnail(self.last_folder, name, rename)
        set_widget_value(box.category_combo, self.model.category or "")
        box.set_expanded(True)
        box.file_entry.set_text(rename or name)

    def update(self) -> None:
        self.update_label()
        self.emit("changed")

    def update_label(self) -> None:
        self.expander.set_label(str(self.model))


@Gtk.Template(filename=str(parent / "document_box.ui"))
class DocumentBox(GenericPresenter[db.Note], Gtk.Box):
    """Generic documents presenter for individual documents.

    Essentially a drop in replacement for a NoteBox that provides the extra
    widgets required for documents.  Must be added to a NotesPresenter.

    On changes emits ``changed`` signal.
    """

    # pylint: disable=not-callable

    __gtype_name__ = "DocumentBox2"

    __gsignals__: dict = {"changed": (GObject.SignalFlags.RUN_FIRST, None, ())}

    expander = cast(Gtk.Expander, Gtk.Template.Child())
    category_combo = cast(Gtk.ComboBox, Gtk.Template.Child())
    category_liststore = cast(Gtk.ListStore, Gtk.Template.Child())
    date_picker = cast(DatePickerBox, Gtk.Template.Child())
    note_textview = cast(Gtk.TextView, Gtk.Template.Child())
    note_textbuffer = cast(Gtk.TextBuffer, Gtk.Template.Child())
    user_entry = cast(Gtk.Entry, Gtk.Template.Child())
    remove_button = cast(Gtk.Button, Gtk.Template.Child())
    file_set_box = cast(Gtk.Box, Gtk.Template.Child())
    file_btnbrowse = cast(Gtk.Button, Gtk.Template.Child())
    file_entry = cast(Gtk.Entry, Gtk.Template.Child())
    file_menu_btn = cast(Gtk.MenuButton, Gtk.Template.Child())

    on_date_changed = EntryHandler(
        [Validator(validate_date, "invalid_date")],
        lambda value, *_args: parse_str_date(value, as_date=True),
    )

    last_folder = str(Path.home())

    def __init__(self, model: db.Note) -> None:

        super().__init__(model, self)

        self.update_label()

        self.initialised = False

        self.date_entry: Gtk.Entry

    def init(self) -> None:

        self.date_picker.init()
        self.date_entry = self.date_picker.entry

        self.widgets_to_model_map = {
            self.date_entry: "date",
            self.user_entry: "user",
            self.category_combo: "category",
            self.file_entry: "document",
            self.note_textbuffer: "note",
        }
        self.refresh_all_widgets_from_model()
        self.populate_categories()

        GLib.idle_add(self.setup_spell_checker)

        self.initialised = True

    def setup_spell_checker(self) -> None:
        spell_view = Gspell.TextView.get_from_gtk_text_view(self.note_textview)
        spell_view.basic_setup()

    def get_presenter(self) -> NotesPresenter[DocumentBox]:

        widget: Gtk.Widget = self
        while not isinstance(widget, NotesPresenter):
            widget = cast(Gtk.Widget, widget.get_parent())

        return widget

    def populate_categories(self) -> None:
        category = self.model.__table__.c.category
        stmt = (
            select(category)
            .where(category.is_not(None))
            .order_by(category)
            .distinct()
        )

        with db.engine.connect() as connection:
            for category in connection.scalars(stmt):
                self.category_liststore.append([category])

    def set_expanded(self, expanded: bool) -> None:
        self.expander.set_expanded(expanded)

    @Gtk.Template.Callback()
    def on_expanded(
        self,
        _expander: Gtk.Expander,
        _expanded: bool,
    ) -> None:
        # delay set up until required
        if self.initialised:
            return

        self.init()

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
    def on_file_entry_changed(self, entry: Gtk.Entry) -> None:
        super().on_text_entry_changed(entry)
        doc_root = prefs.prefs[prefs.document_root_pref]
        filename = Path(doc_root, entry.get_text())
        if filename.is_file():
            self.file_set_box.set_sensitive(False)
            self.file_menu_btn.set_sensitive(True)
        else:
            self.file_set_box.set_sensitive(True)
            self.file_menu_btn.set_sensitive(False)

    @Gtk.Template.Callback()
    def on_file_btnbrowse_clicked(self, _button: Gtk.Button) -> None:
        file_chooser_dialog = Gtk.FileChooserNative.new(
            _("Select document(s) to add…"),
            None,
            Gtk.FileChooserAction.OPEN,
        )
        file_chooser_dialog.set_select_multiple(True)
        file_chooser_dialog.set_current_folder(self.last_folder)
        file_chooser_dialog.run()
        filenames = file_chooser_dialog.get_filenames()
        logger.debug("selected files: %s", filenames)

        try:
            self.add_from_files(filenames)
        except Exception as e:  # pylint: disable=broad-except
            logger.warning("unhandled exception: %s(%s)", type(e).__name__, e)
            dialogs.message_details_dialog(
                _("%s trying to add the selected files.") % type(e).__name__,
                str(e),
                Gtk.MessageType.WARNING,
                parent=get_window_from_widget(self),
            )

        file_chooser_dialog.destroy()

    @Gtk.Template.Callback()
    def on_remove_button_clicked(self, _button: Gtk.Button) -> None:
        # pylint: disable=protected-access
        text = self.file_entry.get_text()
        doc_root = prefs.prefs[prefs.document_root_pref]
        filename = Path(doc_root, text)
        if filename.is_file():
            logger.debug("is_file")

            parent_window = get_window_from_widget(self)
            # for testing
            msg = _("File %s exists, would you like to delete?") % text

            # check if file exists in other documents first...
            tables = [
                table
                for name, table in db.metadata.tables.items()
                if name.endswith("_document")
            ]

            for table in tables:
                stmt = select(func.count()).where(table.c.document == text)

                if self.model.__tablename__ == table.name:
                    stmt = stmt.where(table.c.id != self.model.id)

                with db.engine.connect() as connection:
                    others = connection.execute(stmt).scalar()

                if others:
                    msg += _(
                        " %s other document(s) of type %s exist using "
                        "the same file."
                    ) % (others, table.name)

            if dialogs.yes_no_dialog(msg, parent=parent_window, yes_delay=0.5):
                try:
                    if filename.is_file():
                        filename.unlink()
                # pylint: disable=broad-exception-caught
                except Exception as e:
                    logger.debug("%s(%s)", type(e).__name__, e)
                    dialogs.message_details_dialog(
                        _("Error removing file...  File in use?"),
                        details=str(e),
                        parent=parent_window,
                    )
                    return
            self.model.owner.documents.remove(self.model)
            self.destroy()
        else:
            # if the files don't exist, can remove the db entry
            self.model.owner.documents.remove(self.model)
            self.destroy()

        self.emit("changed")

    def add_from_files(self, filenames: list[str]) -> None:

        presenter = self.get_presenter()

        boxes = [self]
        boxes += [presenter.add_note() for __ in range(len(filenames) - 1)]

        for box, filename in zip(boxes, filenames):
            # remember chosen location for next time
            path = Path(filename)
            self.__class__.last_folder = str(path.parent)
            logger.debug("new current folder is: %s", self.last_folder)
            # copy file to document_root_dir (if not yet there),
            # check if the file already exists.
            destination = Path(
                prefs.prefs[prefs.document_root_pref],
                path.name,
            )
            if destination.is_file():
                msg = _(
                    'A file with that name already exists, select "Yes" '
                    "and the name will be appended with a unique "
                    "identifier, if you wish to change the name "
                    'yourself select "No" to stop here so you can rename '
                    "it before returning."
                )

                if dialogs.yes_no_dialog(
                    msg,
                    parent=get_window_from_widget(self),
                ):
                    tstamp = datetime.now().strftime("%Y%m%d%M%S")
                    rename = f"{path.stem}_{tstamp}{path.suffix}"
                    self._copy_file(box, path, destination.with_name(rename))
                else:
                    docs = getattr(presenter.model, "documents")
                    if box.model in docs:
                        docs.remove(box.model)
                    box.destroy()
            else:
                self._copy_file(box, path, destination)

    def _copy_file(
        self,
        box: Self,
        source: Path,
        destination: Path,
    ) -> None:
        shutil.copy(source, destination)
        set_widget_value(box.category_combo, self.model.category or "")
        box.set_expanded(True)
        box.file_entry.set_text(destination.name)

    def update(self) -> None:
        self.update_label()
        self.emit("changed")

    def update_label(self) -> None:
        self.expander.set_label(str(self.model))


@Gtk.Template(filename=str(parent / "notes_presenter.ui"))
class NotesPresenter[T: (NoteBox, PictureBox, DocumentBox)](Gtk.Box):
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
        self.prop: str
        self.box_cls: type[T]

    @overload
    def init(
        self: NotesPresenter[NoteBox],
        model: db.Domain,
        prop: str = "notes",
        box_cls: type[NoteBox] = NoteBox,
    ) -> None: ...

    @overload
    def init(
        self: NotesPresenter[PictureBox],
        model: db.Domain,
        prop: str,
        box_cls: type[PictureBox],
    ) -> None: ...

    @overload
    def init(
        self: NotesPresenter[DocumentBox],
        model: db.Domain,
        prop: str,
        box_cls: type[DocumentBox],
    ) -> None: ...

    def init(
        self,
        model: db.Domain,
        prop: str = "notes",
        box_cls: Any = NoteBox,
    ) -> None:
        """Setup the widget.

        :param model: a database model that has a ``notes`` attribute that
            contains db.Note objects.
        :param prop: the name of the model property containing notes.
        :param box_cls: the box class to use (PictureBox, NoteBox).
        """
        if not hasattr(model, prop):
            raise BaubleError(f"model must have {prop} attribute")

        self.model = model
        self.prop = prop
        self.box_cls = box_cls
        self.note_cls = object_mapper(model).get_property(prop).mapper.class_
        self.populate()

    def populate(self) -> None:
        for note in getattr(self.model, self.prop):
            self.add_note(note)

    @Gtk.Template.Callback()
    def on_add_button_clicked(self, _button: Gtk.Button) -> None:
        box = self.add_note()
        box.set_expanded(True)

    def add_note(self, note: db.Note | None = None) -> T:
        """Add a new note to the model."""
        if not note:
            note = self.note_cls()
            note.user = utils.get_user_display_name()
            note.date = utils.today_str()

            getattr(self.model, self.prop).append(note)

        box = self.box_cls(note)

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
