# Copyright (c) 2005,2006,2007,2008,2009 Brett Adams <brett@belizebotanic.org>
# Copyright (c) 2015-2016 Mario Frasca <mario@anche.no>
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
"""
UI utilities
"""
import logging

logger = logging.getLogger(__name__)

import os
import threading
from collections.abc import Callable
from datetime import date
from functools import singledispatch
from typing import Any
from typing import Protocol
from typing import cast

from gi.repository import Gdk
from gi.repository import GdkPixbuf
from gi.repository import GLib
from gi.repository import GObject
from gi.repository import Gtk
from sqlalchemy.orm import object_mapper
from sqlalchemy.orm.exc import DetachedInstanceError

from bauble import db
from bauble.i18n import _
from bauble.utils import LRUCache
from bauble.utils import date_string
from bauble.utils import nstr
from bauble.utils.web import get_net_sess

type TreeModelCompareFunc = Callable[[Gtk.TreeModelRow, Any], bool]


def tree_model_has(tree: Gtk.TreeModel | Gtk.TreeModelRow, value: Any) -> bool:
    """Return True or False if value is in the tree."""
    return len(search_tree_model(tree, value)) > 0


def search_tree_model(
    parent: Gtk.TreeModel | Gtk.TreeModelRow,
    data: Any,
    cmp: TreeModelCompareFunc = lambda row, data: row[0] == data,
) -> tuple[Gtk.TreeIter, ...]:
    """Return an iterable of Gtk.TreeIter instances to all occurences
    of data in model

    :param parent: a Gtk.TreeModel or a Gtk.TreeModelRow instance
    :param data: the data to look for
    :param cmp: the function to call on each row to check if it matches
     data, default is C{lambda row, data: row[0] == data}
    """
    if isinstance(parent, Gtk.TreeModel):
        if not parent.get_iter_first():  # model empty
            return tuple()
        treeitr = cast(Gtk.TreeIter, parent.get_iter_first())
        return search_tree_model(parent[treeitr], data, cmp)

    results = set()

    def func(
        model: Gtk.TreeModel,
        _path: Gtk.TreePath,
        itr: Gtk.TreeIter,
    ) -> bool:
        if cmp(model[itr], data):
            results.add(itr)
        return False

    parent.model.foreach(func)
    return tuple(results)


def combo_get_value_iter(
    combo: Gtk.ComboBox,
    value: Any,
    cmp: TreeModelCompareFunc = lambda row, value: row[0] == value,
) -> Gtk.TreeIter | None:
    """Returns a Gtk.TreeIter that points to first matching value in the
    combo's model.

    :param combo: the combo where we should search
    :param value: the value to search for
    :param cmp: the method to use to compare rows in the combo model and value,
      the default is C{lambda row, value: row[0] == value}

    .. note:: if more than one value is found in the combo then the first one
        in the list is returned
    """
    model = combo.get_model()
    matches = search_tree_model(model, value, cmp)
    if len(matches) == 0:
        return None
    return matches[0]


class WithModel(Protocol):  # pylint: disable=too-few-public-methods
    def get_model(self) -> Gtk.TreeModel | None: ...
    def set_model(self, model: Gtk.TreeModel | None) -> None: ...


def clear_model(obj_with_model: WithModel) -> None:
    """
    :param obj_with_model: a gtk Widget that has a Gtk.TreeModel that
      can be retrieved with obj_with_model.get_model

    Remove the model from the object and set the model on the object to None
    """
    model = obj_with_model.get_model()
    if model is None:
        return
    # model.clear()  # can lead to detached instance errors, instead del and
    # set None
    del model
    obj_with_model.set_model(None)


def set_combo_from_value(
    combo: Gtk.ComboBox,
    value: Any,
    cmp: TreeModelCompareFunc = lambda row, data: row[0] == data,
):
    """Find value in combo model and set it as active, else raise ValueError
    cmp(row, value) is the a function to use for comparison

    .. note:: if more than one value is found in the combo then the first one
        in the list is set
    """
    model = combo.get_model()
    matches = search_tree_model(model, value, cmp)
    if len(matches) == 0:
        raise ValueError(
            "set_combo_from_value() - could not find value in "
            f"combo: {value}"
        )
    combo.set_active_iter(matches[0])
    combo.emit("changed")


@singledispatch
def get_widget_value(widget: GObject.Object):
    """Get the value of a widget.

    :param widget: an instance of a Gtk.Widget.
    :raises TypeError: if widget type is not recognised.
    """

    raise TypeError(
        "ui.utils.get_widget_value(): Don't know how to handle the widget "
        f"{widget}"
    )


@get_widget_value.register
def _get_label_value(widget: Gtk.Label) -> str | None:
    return nstr(widget.get_text())


@get_widget_value.register
def _get_entry_value(widget: Gtk.Entry) -> str | None:
    return nstr(widget.get_text())


@get_widget_value.register
def _get_textview_value(widget: Gtk.TextView) -> str | None:
    textbuffer = widget.get_buffer()
    return nstr(textbuffer.get_text(*textbuffer.get_bounds(), False))


@get_widget_value.register
def _get_combo_value(widget: Gtk.ComboBox) -> str | None:
    if widget.get_has_entry():
        return nstr(cast(Gtk.Entry, widget.get_child()).get_text())
    # handle combobox without entry, assumes first item is value to return.
    model = widget.get_model()
    itr = widget.get_active_iter()
    if model is None or itr is None:
        return None
    value = model[itr][0]
    return value


@get_widget_value.register
def _get_tglbutton_value(
    widget: Gtk.ToggleButton | Gtk.CheckButton | Gtk.RadioButton,
) -> bool:
    return widget.get_active()


@get_widget_value.register
def _get_button_value(
    widget: Gtk.Button,
) -> str:
    return widget.get_label()


@singledispatch
def set_widget_value(
    widget: GObject.Object,
    value: Any,
    markup: bool = False,
    index: int = 0,
) -> None:
    """Set the value of the widget.

    :param widget: an instance of Gtk.Widget
    :param value: the value to put in the widget
    :param markup: whether or not value is markup
    :param index: the row index to use for those widgets who use a model

    :raises TypeError: if widget type is not recognised.

    .. note:: any values passed in for widgets that expect a string will call
      the values __str__ method
    """

    raise TypeError(
        "ui.utils.set_widget_value(): Don't know how to handle "
        f"widget {widget}"
    )


def _string(value: Any) -> str:
    value = "" if value is None else value

    if isinstance(value, date):
        return date_string(value)

    return str(value)


@set_widget_value.register
def _set_label_value(
    widget: Gtk.Label,
    value: Any,
    markup: bool = False,
    index: int = 0,
) -> None:
    if markup:
        widget.set_markup(_string(value))
    else:
        widget.set_text(_string(value))


@set_widget_value.register
def _set_textview_value(
    widget: Gtk.TextView,
    value: Any,
    markup: bool = False,
    index: int = 0,
) -> None:
    widget.get_buffer().set_text(_string(value))


@set_widget_value.register
def _set_textbuffer_value(
    widget: Gtk.TextBuffer,
    value: Any,
    markup: bool = False,
    index: int = 0,
) -> None:
    widget.set_text(_string(value))


@set_widget_value.register
def _set_spinbutton_value(
    widget: Gtk.SpinButton,
    value: Any,
    markup: bool = False,
    index: int = 0,
) -> None:
    widget.set_value(float(value or 0))


@set_widget_value.register
def _set_entry_value(
    widget: Gtk.Entry,
    value: Any,
    markup: bool = False,
    index: int = 0,
) -> None:
    widget.set_text(_string(value))


@set_widget_value.register
def _set_combo_value(
    widget: Gtk.ComboBox,
    value: Any,
    markup: bool = False,
    index: int = 0,
) -> None:
    # ComboBox.with_entry
    if widget.get_has_entry():
        cast(Gtk.Entry, widget.get_child()).set_text(_string(value))
        return

    if not widget.get_model():
        logger.warning(
            "ui.utils.set_widget_value(): combo doesn't have a model: %s",
            Gtk.Buildable.get_name(widget),
        )
        return

    treeiter = combo_get_value_iter(
        widget,
        value,
        cmp=lambda row, value: row[index] == value,
    )

    if treeiter:
        widget.set_active_iter(treeiter)
    else:
        widget.set_active(-1)


@set_widget_value.register
def _set_tglbutton_value(
    widget: Gtk.ToggleButton | Gtk.CheckButton | Gtk.RadioButton,
    value: Any,
    markup: bool = False,
    index: int = 0,
) -> None:

    if isinstance(widget, Gtk.CheckButton) and isinstance(value, str):
        value = value == Gtk.Buildable.get_name(widget)
    if value is True:
        widget.set_inconsistent(False)
        widget.set_active(True)
    elif value is False:  # why do we need unset `inconsistent` for False?
        widget.set_inconsistent(False)
        widget.set_active(False)
    else:  # treat None as False, we do not handle inconsistent cases.
        widget.set_inconsistent(False)
        widget.set_active(False)


@set_widget_value.register
def _set_button_value(
    widget: Gtk.Button,
    value: Any,
    markup: bool = False,
    index: int = 0,
) -> None:

    widget.set_label(_string(value))


class ImageCache:  # pylint: disable=too-few-public-methods
    """LRU cache for images"""

    def __init__(self, size: int) -> None:
        self.size = size
        self.storage: LRUCache[str, bytes] = LRUCache(size=size)

    def get(
        self,
        key: str,
        getter: Callable[[], bytes | None],
    ) -> bytes | None:
        """Get the value for key from the cache, if not present use getter to
        get the value and store it in the cache.

        Delays calling getter until we know the value is not in the cache.

        :param key: the key to get from the cache
        :param getter: a function that returns the value to store in the cache
          if key is not present in the cache
        """
        value: bytes | None
        if key in self.storage:
            value = self.storage[key]
        else:
            value = getter()
            if value:
                # Don't store if failed
                self.storage[key] = value
        return value


class ImageLoader(threading.Thread):
    cache = ImageCache(24)  # class-global cached results

    def __init__(
        self,
        box: Gtk.Box,
        url: str,
        *args: Any,
        on_size_allocated: Callable[[Gtk.Widget, None], None] | None = None,
        loader: GdkPixbuf.PixbufLoader | None = None,
        **kwargs: Any,
    ) -> None:
        self.box = box  # will hold image or label

        self.loader = loader or GdkPixbuf.PixbufLoader()

        super().__init__(*args, **kwargs)

        self.inline_picture_marker = "|data:image/jpeg;base64,"
        if url.find(self.inline_picture_marker) != -1:
            self.reader_function = self.read_base64
            self.url = url
        elif url.startswith("http://") or url.startswith("https://"):
            self.reader_function = self.read_global_url
            self.url = url
        else:
            self.reader_function = self.read_local_url
            from bauble import prefs

            pfolder = prefs.prefs.get(prefs.picture_root_pref)
            self.url = os.path.join(pfolder, url)
        self.on_size_allocated = on_size_allocated

    def callback(self) -> None:
        pixbuf = self.loader.get_pixbuf()
        if not pixbuf:
            # type guard
            return
        oriented = pixbuf.apply_embedded_orientation()
        if oriented:
            pixbuf = oriented
        scale_x = pixbuf.get_width() / 400
        scale_y = pixbuf.get_height() / 400
        scale = max(scale_x, scale_y, 1)
        x = int(pixbuf.get_width() / scale)
        y = int(pixbuf.get_height() / scale)
        scaled_buf = pixbuf.scale_simple(x, y, GdkPixbuf.InterpType.BILINEAR)
        if self.box.get_children():
            image = cast(Gtk.Image, self.box.get_children()[0])
        else:
            image = Gtk.Image()
            self.box.pack_start(image, True, True, 0)
        image.set_from_pixbuf(scaled_buf)
        if self.on_size_allocated:
            image.connect("size-allocate", self.on_allocate_size)
        self.box.show_all()

    def _add_widgets_to_box(self, *widgets: Gtk.Widget) -> None:
        for widget in widgets:
            self.box.add(widget)
        self.box.show_all()

    def _remove_widgets_from_box(self, *widgets: Gtk.Widget) -> None:
        for widget in widgets:
            self.box.remove(widget)

    def on_allocate_size(self, *args) -> None:
        if self.on_size_allocated:
            GLib.idle_add(self.on_size_allocated, *args)

    def loader_notified(self, _pixbufloader) -> None:
        GLib.idle_add(self.callback)

    def run(self) -> None:
        try:
            as_bytes = self.cache.get(self.url, self.reader_function)
            if as_bytes:
                self.loader.write(as_bytes)

            self.loader.connect("closed", self.loader_notified)
        except Exception as e:  # pylint: disable=broad-except
            logger.debug("%s(%s) while loading image", type(e).__name__, e)

        try:
            self.loader.close()
        except GLib.Error as e:
            logger.debug("picture %s caused GLib.GError %s", self.url, e)
            text = _("picture file %s not found.") % self.url
            label = Gtk.Label(wrap=True)
            label.connect("size-allocate", self.on_allocate_size)
            label.set_text(text)
            GLib.idle_add(self._add_widgets_to_box, label)
        except Exception as e:  # pylint: disable=broad-except
            logger.warning(
                "picture %s caused Exception %s:%s",
                self.url,
                type(e).__name__,
                e,
            )
            label = Gtk.Label(wrap=True)
            label.connect("size-allocate", self.on_allocate_size)
            label.set_text(
                _('picture %(url)s error "%(error)s"')
                % {"url": self.url, "error": e}
            )
            GLib.idle_add(self._add_widgets_to_box, label)

    def read_base64(self) -> bytes | None:
        thumb64pos = self.url.find(self.inline_picture_marker)
        offset = thumb64pos + len(self.inline_picture_marker)
        import base64

        return base64.b64decode(self.url[offset:])

    def read_global_url(self) -> bytes | None:
        # display something to show an image is loading
        label = Gtk.Label()
        text = "   loading image...."
        label.set_text(text)
        spinner = Gtk.Spinner()
        spinner.start()
        GLib.idle_add(self._add_widgets_to_box, label, spinner)

        net_sess = get_net_sess()
        content = b""
        try:
            response = net_sess.get(self.url, timeout=5)
            content = response.content
        except Exception as e:  # pylint: disable=broad-except
            # timeout, failed to get url, malformed url, etc.
            logger.debug("%s(%s)", type(e).__name__, e)
            response = None
        finally:
            net_sess.close()

        GLib.idle_add(self._remove_widgets_from_box, label, spinner)

        if response and response.ok:
            return content
        return None

    def read_local_url(self) -> bytes | None:
        with open(self.url, "rb") as f:
            img = f.read()
        return img


def populate_enum_combo(
    combo: Gtk.ComboBox,
    model: db.Base,
    field: str,
) -> None:
    """Populate a ComboBox from a Enum Column's values.

    :param combo: a ``Gtk.ComboBox``
    :param model: an instance of ``db.Base``.
    :param field: the column name of the enum to use to populate the ComboBox.
    """
    mapper = object_mapper(model)
    values = sorted(mapper.c[field].type.values, key=lambda v: str(v or ""))
    combo_model = cast(Gtk.ListStore, combo.get_model())
    for value in values:
        combo_model.append([value])


def default_completion_cell_data_func(
    column: Gtk.TreeViewColumn,
    renderer: Gtk.CellRenderer,
    model: Gtk.ListStore,
    treeiter: Gtk.TreeIter,
) -> None:
    # pylint: disable=unused-argument
    """The default completion cell data function for Gtk.EntryCompletion."""
    value = model[treeiter][0]

    try:
        string = str(value)
    except DetachedInstanceError as e:
        # object may be detached from the session when editor is destroyed
        logger.debug("%s(%s)", type(e).__name__, str(e))
        string = ""

    renderer.set_property("text", string)


def default_completion_match_func(
    completion: Gtk.EntryCompletion,
    key_string: str,
    treeiter: Gtk.TreeIter,
):
    """The default completion match function for Gtk.EntryCompletion.

    A case-insensitive string comparison of the the completions object in
    column 0.
    """
    value = cast(Gtk.ListStore, completion.get_model())[treeiter][0]
    return str(value).lower().startswith(key_string.lower())


def format_combo_entry_text(combo: Gtk.ComboBox, path: Gtk.TreePath) -> str:
    """Return text for a Gtk.Entry of a Gtk.ComboBox with model and entry where
    the model contains a list of objects that should be displayed as strings.

    Connect this to the "format-entry-text" signal of the combobox.

    Avoids: Gtk-CRITICAL: gtk_entry_set_text: assertion 'text != NULL'
    """
    detail = combo.get_model()[path][0]
    if not detail:
        return ""
    return str(detail)


def get_clipboard() -> Gtk.Clipboard | None:
    """Get the default clipboard if its available, else return None"""
    display = Gdk.Display().get_default()
    if display:
        return Gtk.Clipboard.get_default(display)
    return None


def get_window_from_widget(widget: Gtk.Widget) -> Gtk.Window | None:
    # for testing
    toplevel = widget.get_toplevel()

    logger.debug("toplevel=%s", toplevel)

    if not isinstance(toplevel, Gtk.Window):
        logger.debug("get_dialog_window: not a Gtk.Window returning None")
        return None

    return toplevel


def center_transient_window(
    parent_window: Gtk.Window,
    transient_window: Gtk.Window,
) -> None:
    parent_x, parent_y = parent_window.get_position()
    parent_w, parent_h = parent_window.get_size()

    child_w, child_h = transient_window.get_size()

    center_x = parent_x + (parent_w - child_w) // 2
    center_y = parent_y + (parent_h - child_h) // 2

    transient_window.move(center_x, center_y)
