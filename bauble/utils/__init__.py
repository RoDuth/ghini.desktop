# Copyright (c) 2005,2006,2007,2008,2009 Brett Adams <brett@belizebotanic.org>
# Copyright (c) 2015-2016 Mario Frasca <mario@anche.no>
# Copyright 2017 Jardín Botánico de Quito
# Copyright (c) 2018-2026 Ross Demuth <rossdemuth123@gmail.com>
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
#
# utils module
#

"""
A common set of utility functions used throughout Ghini.
"""
import logging

logger = logging.getLogger(__name__)

import datetime
import inspect
import os
import re
import shutil
import time
from collections import OrderedDict
from collections import UserDict
from collections.abc import Callable
from collections.abc import Iterable
from functools import wraps
from pathlib import Path
from string import capwords
from typing import Any
from typing import Literal
from typing import overload
from xml.sax import saxutils

from gi.repository import Gtk
from PIL import Image
from PIL import ImageOps
from pyparsing import DelimitedList
from pyparsing import Group
from pyparsing import ParseException
from pyparsing import ParseResults
from pyparsing import Suppress
from pyparsing import Word
from pyparsing import alphanums

import bauble
from bauble.error import check
from bauble.i18n import _


def read_in_chunks(file_object, chunk_size=1024):
    """read a chunk from a stream

    Lazy function (generator) to read piece by piece from a file-like object.
    Default chunk size: 1k."""
    while True:
        data = file_object.read(chunk_size)
        if not data:
            break
        yield data


def chunks(subscriptable, size):
    """Generator to divide a subscriptable (list, tuple, string, etc.) into
    parts of :param size:.
    """
    for i in range(0, len(subscriptable), size):
        yield subscriptable[i : i + size]


class LRUCache[KT, VT](OrderedDict[KT, VT]):
    """Limited size LRU cache dict.

    When items are accessed via square brackets they are moved to the end,
    making them last to be popped from the cache.  Use the ``get`` method if
    you wish to avoid this.
    """

    def __init__(self, *args, size: int = 100, **kwargs) -> None:
        """Set the size of the cache."""
        self.size = size
        super().__init__(*args, **kwargs)

    def __setitem__(self, key: KT, value: VT) -> None:
        if len(self) >= self.size:
            self.popitem(last=False)
        super().__setitem__(key, value)

    def __getitem__(self, key: KT) -> VT:
        self.move_to_end(key)
        return super().__getitem__(key)


def copy_picture_with_thumbnail(
    path: str,
    basename: str | None = None,
    rename: str | None = None,
) -> None:
    """Copy file from path to picture_root, make a thumbnail copying it to
    picture_root/thumbs, preserving the file name unless rename is provided.
    """

    from bauble import prefs

    if basename is None:
        filename = path
        path, basename = os.path.split(filename)
    else:
        filename = os.path.join(path, basename)
    if not filename.startswith(prefs.prefs[prefs.picture_root_pref]):
        if rename:
            destination = os.path.join(
                prefs.prefs[prefs.picture_root_pref], rename
            )
            shutil.copy(filename, destination)
        else:
            shutil.copy(filename, prefs.prefs[prefs.picture_root_pref])
    # make thumbnail in thumbs subdirectory
    full_dest_path = os.path.join(
        prefs.prefs[prefs.picture_root_pref], "thumbs", rename or basename
    )
    try:
        with Image.open(filename) as img_file:
            img = ImageOps.exif_transpose(img_file)
            img.thumbnail((400, 400))
            logger.debug("copying %s to %s", filename, full_dest_path)
            img.save(full_dest_path)
    except Exception as e:  # pylint: disable=broad-except
        logger.warning(
            "unexpected exception making thumbnail: %s(%s)",
            type(e).__name__,
            e,
        )


def find_dependent_tables(table, metadata=None):
    """Return an iterator with all tables that depend on table.

    The tables are returned in the order that they depend on each other. For
    example you know that table[0] does not depend on tables[1].

    :param table: The tables who dependencies we want to find

    :param metadata: The :class:`sqlalchemy.engine.MetaData` object
      that holds the tables to search through.  If None then use
      bauble.db.metadata
    """
    # NOTE: we can't use bauble.metadata.sorted_tables here because it
    # returns all the tables in the metadata even if they aren't
    # dependent on table at all
    from sqlalchemy.sql.util import sort_tables

    if metadata is None:
        from bauble import db

        metadata = db.metadata
    tables = []

    def _impl(tbl2):
        for tbl in metadata.sorted_tables:
            for fkey in tbl.foreign_keys:
                if (
                    fkey.column.table == tbl2
                    and tbl not in tables
                    and tbl is not table
                ):
                    tables.append(tbl)
                    _impl(tbl)

    _impl(table)
    return sort_tables(tables=tables)


def load_widgets(filename):
    buidloader = BuilderLoader.load(filename)
    return BuilderWidgets(buidloader)
    # return BuilderWidgets(filename)


class BuilderLoader:
    """This class caches the Gtk.Builder objects so that loading the same
    file with the same name returns the same Gtk.Builder.

    It might seem crazy to keep them around instead of deleting them
    and freeing the memory but in reality the memory is never returned
    to the system. By using this class you can keep the size of the
    application from growing if the same UI decription is loaded
    several times.  e.g. everytime you open an editor or infobox
    """

    # NOTE: this builder loader is really only used because of a bug
    # in PyGTK where a Gtk.Builder doesn't free some memory so we use
    # this to keep the memory from growing out of control. if the
    # gtk/pygtk people fix that bug we should be able to get rid of
    # this class
    # http://bugzilla.gnome.org/show_bug.cgi?id=589057,560822

    builders: dict[str, Gtk.Builder] = {}

    @classmethod
    def load(cls, filename):
        if filename in cls.builders:
            return cls.builders[filename]
        builder = Gtk.Builder()
        builder.add_from_file(filename)
        cls.builders[filename] = builder
        return builder


class BuilderWidgets(UserDict):
    """Provides dictionary and attribute access for a :class:`Gtk.Builder`
    object.
    """

    def __init__(self, ui):
        """
        :params filename: a Gtk.Builder XML UI file
        """
        super().__init__()
        if isinstance(ui, str):
            self.builder = Gtk.Builder()
            self.builder.add_from_file(ui)
            self.filename = ui
        else:
            self.builder = ui
            self.filename = f"from object {ui}"

    def __getitem__(self, name):
        """
        :param name:
        """
        widget = self.builder.get_object(name)
        if not widget:
            raise KeyError(
                _('no widget named "%s" in glade file: %s')
                % (name, self.filename)
            )
        return widget

    def __getattr__(self, name):
        """
        :param name:
        """
        if name == "_builder_":
            return self.builder
        widget = self.builder.get_object(name)
        if not widget:
            raise KeyError(
                _('no widget named "%s" in glade file: %s')
                % (name, self.filename)
            )
        return widget

    def remove_parent(self, widget):
        """Remove widgets from its parent."""
        # if parent is the last reference to widget then widget may be
        # automatically destroyed
        if isinstance(widget, str):
            widget = self[widget]
        parent = widget.get_parent()
        if parent is not None:
            parent.remove(widget)


# Avoids: Gtk-CRITICAL: gtk_entry_set_text: assertion 'text != NULL'
def format_combo_entry_text(combo, path):
    """Return text for a Gtk.Entry of a Gtk.ComboBox with model and entry where
    the model contains a list of objects that should be displayed as strings.

    Connect this to the "format-entry-text" signal of the combobox.

    :param combo: the Gtk.ComboBox widget with attached Gtk.ListStore(object)
        model and Gtk.Entry
    :param path: the Gtk.TreePath string
    """
    detail = combo.get_model()[path][0]
    if not detail:
        return ""
    return str(detail)


def default_cell_data_func(_column, cell, model, treeiter, str_func=None):
    """generic cell_data_func.

    :param str_func: a callable, provided to the func_data parameter of the
        columns's set_cell_data_func, that when supplied obj will return an
        appropriate string for the cell's text property
    """
    if str_func is None:
        str_func = str
    obj = model[treeiter][0]
    cell.set_property("text", str_func(obj))


def setup_text_combobox(combo, values=None, cell_data_func=None):
    """Configure a Gtk.ComboBox as a text combobox

    NOTE: If you pass a cell_data_func that is a method of an object that
    holds a reference to combo then the object will not be properly
    garbage collected.  To avoid this problem either don't pass a
    method of object or make the method static

    :param combo: Gtk.ComboBox
    :param values: list values or Gtk.ListStore
    :param cell_data_func:
    """
    values = values or []
    if isinstance(values, Gtk.ListStore):
        model = values
    else:
        model = Gtk.ListStore(str)
        for val in values:
            model.append(row=[val])

    combo.clear()
    combo.set_model(model)
    renderer = Gtk.CellRendererText()
    combo.pack_start(renderer, True)
    combo.add_attribute(renderer, "text", 0)

    if not isinstance(combo, Gtk.ComboBox):
        logger.debug("not a Gtk.ComboBox")
        return

    if cell_data_func:
        combo.set_cell_data_func(renderer, cell_data_func)

    # enables things like scrolling through values with keyboard and
    # other goodies
    # combo.props.text_column = 0

    if combo.get_has_entry():
        # add completion using the first column of the model for the text
        logger.debug("ComboBox has entry")
        entry = combo.get_child()
        completion = Gtk.EntryCompletion()
        entry.set_completion(completion)
        completion.set_model(model)
        completion.set_text_column(0)
        completion.set_popup_completion(True)
        completion.set_inline_completion(True)
        completion.set_inline_selection(True)
        completion.set_minimum_key_length(2)

        combo.connect("format-entry-text", format_combo_entry_text)


def today_str(fmat=None):
    """Return a string for of today's date according to format.

    If fmat=None then the format uses the prefs.date_format_pref
    """
    from bauble import prefs

    fmat = fmat or prefs.prefs.get(prefs.date_format_pref)
    today = datetime.date.today()
    return today.strftime(fmat)


def utcnow_naive() -> datetime.datetime:
    """When a naive UTC now is required.

    Use as a drop in replacement for deprecated `datetime.datetime.utcnow()`
    """
    return datetime.datetime.now(datetime.UTC).replace(tzinfo=None)


def setup_date_button(view, entry, button):
    """Associate a button with entry so that when the button is clicked a date
    is inserted into the entry.

    :param view: a bauble.editor.GenericEditorView
    :param entry: the entry that the data goes into
    :param button: the button that enters the data in entry
    """
    logger.debug("setup_date_button %s %s", type(view).__name__, entry)
    if isinstance(entry, str):
        entry = view.widgets[entry]
    if isinstance(button, str):
        button = view.widgets[button]
    image = Gtk.Image.new_from_icon_name(
        "x-office-calendar-symbolic", Gtk.IconSize.BUTTON
    )
    button.set_tooltip_text(_("Today's date"))
    button.set_image(image)

    def on_clicked(_widget):
        entry.set_text(today_str())

    if view and hasattr(view, "connect"):
        view.connect(button, "clicked", on_clicked)
    else:
        button.connect("clicked", on_clicked)


def date_string(value: datetime.date | None) -> str:
    if not value:
        return ""

    from bauble import prefs

    date_format = prefs.prefs.get(prefs.date_format_pref, "%Y-%m-%d")
    return value.strftime(date_format)


def nstr(obj: Any) -> str | None:
    """If obj is None return None else return str(obj).

    :param obj: the object that a string is needed for, should have a __str__
        method.
    """
    return None if obj is None else str(obj)


def xml_safe(obj):
    """Return a string with character entities escaped safe for xml"""
    return saxutils.escape(str(obj))


def xml_safe_name(obj):
    """Return a string that conforms to W3C XML 1.0 (fifth edition)
    recommendation for XML names.

    Space is replaced with _ and <{[()]}> are stripped. If string does not
    provide any chars that conform return _
    """
    # make sure we have a unicode string with no spaces or surrounding
    # parentheses
    uni = str(obj).replace(" ", "_").strip("<{[()]}>")
    # if nothing is left return '_'
    if not uni:
        return "_"

    start_char = (
        r"[A-Z]|[_]|[a-z]|\xc0-\xd6]|[\xd8-\xf6]|[\xf8-\xff]|"
        r"[\u0100-\u02ff]|[\u0370-\u037d]|[\u037f-\u1fff]|"
        r"[\u200c-\u200d]|[\u2070-\u218f]|[\u2c00-\u2fef]|"
        r"[\u3001-\uD7FF]|[\uF900-\uFDCF]|[\uFDF0-\uFFFD]|"
    )
    # depending on a ucs-2 or ucs-4 build python
    start_char_ucs4 = start_char + r"[\U00010000-\U000EFFFF]"
    name_start_char_ucs4 = r"(" + start_char_ucs4 + r")"
    name_char = (
        r"(" + start_char_ucs4 + r"|[-.0-9\xb7\u0337-\u036f\u203f-\u2040])"
    )

    start_char_ucs2 = start_char + r"[\uD800-\uDBFF][\uDC00-\uDFFF]"
    name_start_char_ucs2 = r"(" + start_char_ucs2 + r")"
    name_char_ucs2 = (
        r"(" + start_char_ucs2 + r"|[-.0-9\xb7\u0337-\u036f\u203f-\u2040])"
    )
    try:
        first_char = re.match(name_start_char_ucs4, uni[0])
    except re.error:
        first_char = re.match(name_start_char_ucs2, uni[0])
        name_char = name_char_ucs2

    if first_char:
        start_char = first_char.group()
        uni = uni[1:]
    else:
        start_char = "_"

    name_chars = "".join([i for i in uni if re.match(name_char, i)])

    name = start_char + name_chars

    return name


def safe_numeric(string):
    """evaluate the string as a number, or return zero"""

    try:
        return int(string)
    except ValueError:
        pass
    try:
        return float(string)
    except ValueError:
        pass
    return 0


def safe_int(string):
    "evaluate the string as an integer, or return zero"

    try:
        return int(string)
    except ValueError:
        pass
    return 0


_NATSORT_RX = re.compile("([0-9]+)")


def natsort_key(obj: Any) -> tuple[list[str | int], str]:
    """a key getter for sort and sorted function

    the sorting is done on return value of obj.__str__() so we can sort
    generic objects as well.

    use like: sorted(some_list, key=utils.natsort_key)
    """

    item = str(obj)
    parts = [
        int(part) if part.isdigit() else part
        for part in _NATSORT_RX.split(item)
    ]
    return parts, item


def delete_or_expunge(obj):
    """If the object is in object_session(obj).new then expunge it from the
    session.  If not then session.delete it.
    """
    from sqlalchemy.orm import object_session

    session = object_session(obj)
    if session is None:
        return
    if obj not in session.new:
        logger.debug("delete obj: %s -- %s", obj, repr(obj))
        session.delete(obj)
    else:
        logger.debug("expunge obj: %s -- %s", obj, repr(obj))
        session.expunge(obj)
        del obj


def reset_sequence(column, engine=None):
    """If column.sequence is not None or the column is an Integer and
    column.autoincrement is true then reset the sequence for the next
    available value for the column...if the column doesn't have a
    sequence then do nothing and return

    The SQL statements are executed directly from db.engine

    This function only works for PostgreSQL database.  It does nothing
    for other database engines.
    """
    from sqlalchemy import schema
    from sqlalchemy.types import Integer

    if not engine:
        from bauble import db

        engine = db.engine

    if not engine.name == "postgresql":
        return

    sequence_name = None
    if hasattr(column, "default") and isinstance(
        column.default, schema.Sequence
    ):
        sequence_name = column.default.name
    elif (
        (isinstance(column.type, Integer) and column.autoincrement)
        and (
            column.default is None
            or (
                isinstance(column.default, schema.Sequence)
                and column.default.optional
            )
        )
        and len(column.foreign_keys) == 0
    ):
        sequence_name = f"{column.table.name}_{column.name}_seq"
    else:
        return
    conn = engine.connect()
    trans = conn.begin()
    try:
        # the FOR UPDATE locks the table for the transaction
        stmt = f"SELECT {column.name} from {column.table.name} FOR UPDATE;"
        result = conn.execute(stmt)
        maxid = None
        vals = list(result)
        if vals:
            maxid = max(vals, key=lambda x: x[0])[0]
        result.close()
        if maxid is None:
            # set the sequence to nextval()
            stmt = f"SELECT nextval('{sequence_name}');"
        else:
            stmt = (
                f"SELECT setval('{sequence_name}', max({column.name})+1) "
                f"from {column.table.name};"
            )
        conn.execute(stmt)
    except Exception as e:
        logger.warning(
            "bauble.utils.reset_sequence(): %s(%s)", type(e).__name__, e
        )
        trans.rollback()
    else:
        trans.commit()
    finally:
        conn.close()


def generate_on_clicked(call):
    """Closure to return a function that will call the provided callable with
    the data provided, ignoring the label and event.  Intended for use with
    make_label_clickable labels and a callable that only takes one argument.

    :param call: a callable that takes one positional argument
    """

    def on_label_clicked(_label, _event, data):
        return call(data)

    return on_label_clicked


def make_label_clickable(label, on_clicked, *args):
    """
    :param label: a Gtk.Label that has a Gtk.EventBox as its parent
    :param on_clicked: callback to be called when the label is clicked
      on_clicked(label, event, data)
    """
    # pylint: disable=protected-access
    eventbox = label.get_parent()

    check(eventbox is not None, "label must have a parent")
    check(
        isinstance(eventbox, Gtk.EventBox),
        "label must have an Gtk.EventBox as its parent",
    )
    label.__pressed = False

    def on_enter_notify(_widget, *_args):
        label.get_style_context().add_class("click-label")

    def on_leave_notify(_widget, *_args):
        label.get_style_context().remove_class("click-label")
        label.__pressed = False

    def on_press(*_args):
        label.__pressed = True

    def on_release(_widget, event, *args):
        if label.__pressed:
            label.__pressed = False
            label.get_style_context().remove_class("click-label")
            on_clicked(label, event, *args)

    try:
        eventbox.disconnect(label.__on_event)
        logger.debug("disconnected previous release-event handler")
        label.__on_event = eventbox.connect(
            "button_release_event", on_release, *args
        )
    except AttributeError:
        logger.debug("defining handlers - %s", on_clicked)
        label.__on_event = eventbox.connect(
            "button_release_event", on_release, *args
        )
        eventbox.connect("enter_notify_event", on_enter_notify)
        eventbox.connect("leave_notify_event", on_leave_notify)
        eventbox.connect("button_press_event", on_press)


def which(filename, path=None):
    """Return first occurence of file on the path."""
    if not path:
        path = os.environ["PATH"].split(os.pathsep)
    for dirname in path:
        candidate = os.path.join(dirname, filename)
        if os.path.isfile(candidate):
            return candidate
    return None


def ilike(col, val, engine=None):
    """Return a cross platform ilike function."""
    from sqlalchemy import func

    if not engine:
        engine = bauble.db.engine
    if engine.name == "postgresql":
        return col.op("ILIKE")(val)
    return func.lower(col).like(func.lower(val), escape="\\")


def range_builder(text: str) -> list:
    """Return a list of ints or chrs from a string range of the form
    1-3,4,5
    """
    in_type: Callable[[str], int]
    out_type: Callable[[int], str | int]

    range_ = Group(Word(alphanums) + Suppress("-") + Word(alphanums))
    range_list = DelimitedList(range_ | Word(alphanums))

    try:
        tokens = range_list.parse_string(text)
    except (AttributeError, ParseException) as e:
        logger.debug("%s(%s)", type(e).__name__, e)
        return []
    values = set()

    err_msg = (
        "Invalid value(s) for start: '{rng[0]}' and/or end: '{rng[1]}' of "
        "range in '{text}'"
    )

    for rng in tokens:
        if isinstance(rng, ParseResults):
            # get here if the token is a range
            if rng[0].isdigit() and rng[1].isdigit():
                in_type = int
                out_type = int
            elif rng[0].isalpha() and rng[1].isalpha():
                in_type = ord
                out_type = chr
            else:
                raise ValueError(err_msg.format(rng=rng, text=text))

            try:
                start = in_type(rng[0])
                end = in_type(rng[1]) + 1
            except TypeError as e:
                raise ValueError(err_msg.format(rng=rng, text=text)) from e

            check(
                start < end - 1,
                f"start: '{rng[0]}' must be less than end: '{rng[1]}' in "
                f"range from '{text}'",
            )

            values_list = []
            for i in range(start, end):
                out = out_type(i)
                if isinstance(out, int) or out.isalpha():
                    values_list.append(out)

            values.update(values_list)
        else:
            # get here if the token is an integer or char
            values.add(rng if rng.isalpha() else int(rng))
    return sorted(list(values))


def gc_objects_by_type(tipe):
    """Return a list of objects from the garbage collector by type."""
    import gc

    if isinstance(tipe, str):
        return [o for o in gc.get_objects() if type(o).__name__ == tipe]
    if inspect.isclass(tipe):
        return [o for o in gc.get_objects() if isinstance(o, tipe)]
    return [o for o in gc.get_objects() if isinstance(o, type(tipe))]


def debug_gc_decorator(func):
    """Handy decorator for sorting out garbage collection issues.

    To use decorate a function e.g.:
        bauble.view.SearchView.on_action_activate,
        bauble.ui.GUI.on_insert_menu_item_activate
        bauble.ui.GUI.on_tools_menu_item_activate
        bauble.ui.GUI.on_query_button_clicked
    run the app from the commandline and look at the output on standard output.

    NOTE: the first use may not be the concern so much as repeated uses
    accumulating uncollected items.  Keep an eye on totals increasing.
    """
    # NOTE another approach to manually testing that specific objects are
    # garbage collected as expected is to place something like this as the
    # bottom of main.py:
    #
    # ```
    # from gi.repository import GLib
    #
    # def print_gc_list():
    #     print(utils.gc_objects_by_type("ClassName"))
    #     return True
    #
    # GLib.timeout_add(1000, print_gc_list)
    # ```
    #
    # then check the stdout for expected behaviour

    def wrapper(*args, **kwargs):
        import gc

        before = {}
        for i in gc.get_objects():
            tipe = type(i)
            before[tipe] = before.setdefault(tipe, 0) + 1

        new_val = func(*args, **kwargs)

        gc.collect()
        after = {}
        for i in gc.get_objects():
            tipe = type(i)
            after[tipe] = after.setdefault(tipe, 0) + 1

        for k, v in after.items():
            if k in before and v - before.get(k, 0) > 0:
                print(f"{k}, {v - before.get(k)} total: {v}")
            elif k not in before:
                print(f"NEW: {k}, total: {v}")

        return new_val

    return wrapper


class GenericMessageBox(Gtk.EventBox):
    """Abstract class for showing a message box at the top of an editor."""

    message: str

    def __init__(self):
        super().__init__()
        self.box = Gtk.Box()
        self.box.set_spacing(10)
        self.add(self.box)

    def show_all(self, *_args, **_kwargs):
        self.get_parent().show_all()
        size_req = self.get_preferred_size()[1]
        self.set_size_request(size_req.width, size_req.height + 10)

    def show(self, *_args, **_kwargs):
        self.show_all()


class MessageBox(GenericMessageBox):
    """A MessageBox that can display a message label at the top of an editor"""

    def __init__(self, msg=None, details=None):
        super().__init__()
        self.vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.box.pack_start(self.vbox, True, True, 0)

        self.label = Gtk.TextView()
        self.label.set_wrap_mode(Gtk.WrapMode.WORD)
        self.label.set_can_focus(False)
        self.buffer = Gtk.TextBuffer()
        self.label.set_buffer(self.buffer)
        if msg:
            self.buffer.set_text(msg)
        self.vbox.pack_start(self.label, True, True, 0)

        button_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.box.pack_start(button_box, False, False, 0)
        button = Gtk.Button.new_from_icon_name(
            "window-close-symbolic", Gtk.IconSize.BUTTON
        )
        button.set_relief(Gtk.ReliefStyle.NONE)
        button_box.pack_start(button, False, False, 0)

        self.details_expander = Gtk.Expander(
            label=_("Show details"), expanded=False
        )
        self.vbox.pack_start(self.details_expander, True, True, 0)

        scroll_win = Gtk.ScrolledWindow()
        scroll_win.set_size_request(-1, 200)
        scroll_win.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        details_label = Gtk.TextView(monospace=True)
        details_label.set_wrap_mode(Gtk.WrapMode.WORD)
        details_label.set_can_focus(False)
        self.details_buffer = Gtk.TextBuffer()
        details_label.set_buffer(self.details_buffer)
        scroll_win.add(details_label)

        self.details = details
        self.details_expander.add(scroll_win)

        button.connect("clicked", lambda w: self.destroy())

    @property
    def message(self):
        return self.buffer.get_property("text")

    @message.setter
    def message(self, msg):
        # TODO: we could probably do something smarter here that
        # involved check the font size and window width and adjust the
        # wrap widget accordingly
        if msg:
            self.buffer.set_text(msg)
        else:
            self.buffer.set_text("")

    @property
    def details(self):
        return self.details_buffer.get_property("text")

    @details.setter
    def details(self, msg):
        if msg:
            self.details_buffer.set_text(msg)
            self.details_expander.show()
            self.details_expander.set_no_show_all(False)
        else:
            self.details_buffer.set_text("")
            self.details_expander.hide()
            self.details_expander.set_no_show_all(True)


class YesNoMessageBox(GenericMessageBox):
    """A message box that can present a Yes or No question to the user"""

    def __init__(self, msg=None, on_response=None):
        """on_response: callback method when the yes or no buttons are
        clicked.

        The signature of the function should be func(button, response) where
        response is True/False depending on whether the user selected Yes or
        No, respectively.
        """
        super().__init__()
        self.label = Gtk.Label()
        if msg:
            self.label.set_markup(msg)
        self.label.set_xalign(0.1)
        self.label.set_yalign(0.1)
        self.box.pack_start(self.label, True, True, 0)

        button_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.box.pack_start(button_box, False, False, 0)
        self.yes_button = Gtk.Button(label="Yes")
        if on_response:
            self.yes_button.connect("clicked", on_response, True)
        button_box.pack_start(self.yes_button, False, False, 0)

        button_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.box.pack_start(button_box, False, False, 0)
        self.no_button = Gtk.Button(label="No")
        if on_response:
            self.no_button.connect("clicked", on_response, False)
        button_box.pack_start(self.no_button, False, False, 0)

    def _set_on_response(self, func):
        self.yes_button.connect("clicked", func, True)
        self.no_button.connect("clicked", func, False)

    on_response = property(fset=_set_on_response)

    @property
    def message(self):
        return self.label.get_text()

    @message.setter
    def message(self, msg):
        if msg:
            self.label.set_markup(msg)
        else:
            self.label.set_markup("")


MESSAGE_BOX_INFO: Literal[1] = 1
MESSAGE_BOX_ERROR: Literal[2] = 2
MESSAGE_BOX_YESNO: Literal[3] = 3


@overload
def add_message_box(parent: Gtk.Box, type_: Literal[1]) -> MessageBox: ...


@overload
def add_message_box(parent: Gtk.Box, type_: Literal[2]) -> MessageBox: ...


@overload
def add_message_box(parent: Gtk.Box, type_: Literal[3]) -> YesNoMessageBox: ...


def add_message_box(
    parent: Gtk.Box,
    type_: Literal[1, 2, 3] = MESSAGE_BOX_INFO,
) -> GenericMessageBox:
    """
    :param parent: the parent :class:`Gtk.Box` width to add the
      message box to
    :param type_: one of MESSAGE_BOX_INFO, MESSAGE_BOX_ERROR or
      MESSAGE_BOX_YESNO
    """
    msg_box: Gtk.EventBox
    if type_ == MESSAGE_BOX_INFO:
        msg_box = MessageBox()
    elif type_ == MESSAGE_BOX_ERROR:
        msg_box = MessageBox()  # check this
    elif type_ == MESSAGE_BOX_YESNO:
        msg_box = YesNoMessageBox()
    else:
        raise ValueError(f"unknown message box type: {type_}")
    parent.pack_start(msg_box, True, True, 0)
    return msg_box


def get_distinct_values(column, session):
    """Return a list of all the distinct values in a table column"""
    qry = session.query(column).distinct()
    return [v[0] for v in qry if v != (None,)]


def get_invalid_columns(obj, ignore_columns=None):
    """Return column names on a mapped object that have values which aren't
    valid for the model.

    Invalid columns meet the following criteria:
    - nullable columns with null values
    - ...what else?
    """
    if ignore_columns is None:
        ignore_columns = ["id"]

    # TODO: check for invalid enum types
    if not obj:
        return []

    table = obj.__table__
    invalid_columns = []
    for column in [c for c in table.c if c.name not in ignore_columns]:
        v = getattr(obj, column.name)
        if v is None and not column.nullable:
            invalid_columns.append(column.name)
    return invalid_columns


URL_RGX = re.compile(r"(?:\[(.+?)\])?((?:(?:http)|(?:https))://\S+)", re.I)


def get_urls(text: str) -> list[tuple[str, ...]]:
    """Return tuples of http/https links and labels for the links.  To label a
    link prefix it with [label text],

    e.g. [BBG]http://belizebotanic.org
    """
    matches = []
    for match in URL_RGX.finditer(text):
        matches.append(match.groups())
    return matches


def get_user_display_name():
    import sys

    if sys.platform == "win32":
        import ctypes

        get_user_name_ex = ctypes.windll.secur32.GetUserNameExW
        name_display = 3

        size = ctypes.pointer(ctypes.c_ulong(0))
        get_user_name_ex(name_display, None, size)

        name_buffer = ctypes.create_unicode_buffer(size.contents.value)
        get_user_name_ex(name_display, name_buffer, size)
        fname = str(name_buffer.value)
    else:
        import pwd

        fname = str(pwd.getpwuid(os.getuid())[4])

    if not fname:
        # fall back to value of $USER
        fname = (
            os.getenv("USER")
            or os.getenv("USERNAME")
            or os.getenv("LOGNAME")
            or os.getenv("LNAME")
        )

    return fname


def copy_tree(src_dir, dest_dir, suffixes=None, over_write=False):
    """Copy a directory tree from source to destination.

    :param src_dir: Path or fully qualiified path as a string to the source
        directory
    :param dest_dir: Path or fully qualiified path as a string to the
        destination directory
    :param suffixes: list of suffixes (including '.') of file names to copy or
        None if all files should be copied
    :param over_write: wether to overwrite existing files or not.
    """

    if isinstance(src_dir, str):
        src_dir = Path(src_dir)
    if isinstance(dest_dir, str):
        dest_dir = Path(dest_dir)
    for path in src_dir.glob("**/*.*"):
        if not suffixes or path.suffix in suffixes:
            destination = dest_dir / path.relative_to(src_dir)
            if not destination.parent.exists():
                logger.debug("creating dir: %s", destination.parent)
                destination.parent.mkdir(parents=True)
            if not destination.exists() or over_write:
                shutil.copy(path, destination)


def hide_widgets(widgets: Iterable[Gtk.Widget]) -> None:
    """hides and disables the widgets from showing with show_all() calls."""
    for widget in widgets:
        widget.set_visible(False)
        widget.set_no_show_all(True)


def unhide_widgets(widgets: Iterable[Gtk.Widget]) -> None:
    """unhides and enable the widgets to show with show_all() calls."""
    for widget in widgets:
        widget.set_visible(True)
        widget.set_no_show_all(False)


def timed_cache(size=200, secs=2.0):
    """Timed cache function decorator.

    Very basic cache that will memoise the last value calculated for a set
    amount of seconds (default = 2.0).  Cache size can be set (default = 200).

    Cached funtion's arguments must be hashable.

    To clear the cache at anytime call clear_cache e.g. `func.clear_cache()`

    To set the size of the cache either supply the `size` paramater or at
    anytime use set_size e.g. `func.set_size(500)`. For an unlimited cache size
    set size to 0.

    To set a value for the delay in seconds before updating from the decorated
    function either supply the `secs` parameter or at anytime use set_secs e.g.
    `func.set_secs(1.0)`

    :param size: size of the cache.
    :param secs: delay in seconds before updating.  Set to None to behave as a
        regular LRU cache.
    """
    cache = {}

    def decoratorating(func):
        @wraps(func)
        def wrapper(*args):
            now = time.time()
            if size and len(cache) > size:
                cache.pop(next(iter(cache)))
            previous = cache.get(args)
            # no timer
            if previous is not None and secs is None:
                return previous[1]
            if previous is not None and now - previous[0] < secs:
                return previous[1]
            new_val = func(*args)
            cache[args] = [now, new_val]
            return new_val

        def clear_cache():
            cache.clear()

        def set_secs(val):
            nonlocal secs
            secs = val

        def set_size(val):
            nonlocal size
            size = val

        wrapper.clear_cache = clear_cache
        wrapper.set_secs = set_secs
        wrapper.set_size = set_size
        return wrapper

    return decoratorating


def get_temp_path():
    """Returns a pathlib.Path instance pointed at a temporary file."""
    import tempfile

    handle, name = tempfile.mkstemp()
    os.close(handle)
    return Path(name)


SMALLS_WORDS = [
    "A",
    "An",
    "And",
    "As",
    "At",
    "By",
    "Del",
    "For",
    "If",
    "In",
    "Of",
    "On",
    "Or",
    "The",
    "To",
]


SMALL_WORDS_MAP = {w: w.lower() for w in SMALLS_WORDS}


def title_case(string: str) -> str:
    """Return a string in title case."""
    cap_string = capwords(string)
    words = cap_string.split(" ")

    final = []

    final.append(words[0])

    if len(words) > 1:
        final.extend([SMALL_WORDS_MAP.get(word, word) for word in words[1:-1]])
        final.append(words[-1])

    return " ".join(final)
