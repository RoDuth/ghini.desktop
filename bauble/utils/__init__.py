# Copyright (c) 2005,2006,2007,2008,2009 Brett Adams <brett@belizebotanic.org>
# Copyright (c) 2015-2016 Mario Frasca <mario@anche.no>
# Copyright 2017 Jardín Botánico de Quito
# Copyright (c) 2018-2022 Ross Demuth <rossdemuth123@gmail.com>
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
from collections.abc import Iterable
from collections import UserDict
from typing import Any, Union
import datetime
import os
import re
import inspect
import threading
from xml.sax import saxutils

import logging
logger = logging.getLogger(__name__)

from gi.repository import Gtk  # noqa
from gi.repository import Gdk  # noqa
from gi.repository import GLib
from gi.repository import GdkPixbuf

import bauble
from bauble.error import check


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
        yield subscriptable[i:i + size]


class Cache:
    """a simple class for caching images

    you instantiate a size 10 cache like this:
    >>> cache = Cache(10)

    if `getter` is a function that returns a picture, you don't immediately
    invoke it, you use the cache like this:
    >>> image = cache.get(name, getter)

    internally, the cache is stored in a dictionary, the key is the name of
    the image, the value is a pair with first the timestamp of the last usage
    of that key and second the value.
    """

    def __init__(self, size):
        self.size = size
        self.storage = {}

    def get(self, key, getter, on_hit=lambda x: None):
        if key in self.storage:
            value = self.storage[key][1]
            on_hit(value)
        else:
            if len(self.storage) == self.size:
                # remove the oldest entry
                k = min(list(zip(list(self.storage.values()),
                                 list(self.storage.keys()))))[1]
                del self.storage[k]
            value = getter()
        import time
        self.storage[key] = time.time(), value
        return value


def copy_picture_with_thumbnail(path, basename=None):
    """copy file from path to picture_root, and make thumbnail, preserving name

    return base64 representation of thumbnail
    """
    from bauble import prefs
    import base64
    import shutil
    from PIL import Image
    from io import BytesIO
    if basename is None:
        filename = path
        path, basename = os.path.split(filename)
    else:
        filename = os.path.join(path, basename)
    if not filename.startswith(prefs.prefs[prefs.picture_root_pref]):
        shutil.copy(filename, prefs.prefs[prefs.picture_root_pref])
    # make thumbnail in thumbs subdirectory
    full_dest_path = os.path.join(prefs.prefs[prefs.picture_root_pref],
                                  'thumbs', basename)
    result = ""
    try:
        img = Image.open(filename)
        img.thumbnail((400, 400))
        logger.debug('copying %s to %s', filename, full_dest_path)
        img.save(full_dest_path)
        output = BytesIO()
        img.save(output, format='JPEG')
        im_data = output.getvalue()
        result = base64.b64encode(im_data)
    except IOError as e:
        logger.warning("can't make thumbnail %s", e)
    except Exception as e:  # pylint: disable=broad-except
        logger.warning("unexpected exception making thumbnail: "
                       "%s(%s)", type(e).__name__, e)
    return result


class ImageLoader(threading.Thread):
    cache = Cache(12)  # class-global cached results

    def __init__(self, box, url, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.box = box  # will hold image or label
        self.loader = GdkPixbuf.PixbufLoader()
        self.inline_picture_marker = "|data:image/jpeg;base64,"
        if url.find(self.inline_picture_marker) != -1:
            self.reader_function = self.read_base64
            self.url = url
        elif (url.startswith('http://') or url.startswith('https://')):
            self.reader_function = self.read_global_url
            self.url = url
        else:
            self.reader_function = self.read_local_url
            from bauble import prefs
            pfolder = prefs.prefs.get(prefs.picture_root_pref)
            self.url = os.path.join(pfolder, url)

    def callback(self):
        pixbuf = self.loader.get_pixbuf()
        if not pixbuf:
            return
        pixbuf = pixbuf.apply_embedded_orientation()
        scale_x = pixbuf.get_width() / 400
        scale_y = pixbuf.get_height() / 400
        scale = max(scale_x, scale_y, 1)
        x = int(pixbuf.get_width() / scale)
        y = int(pixbuf.get_height() / scale)
        scaled_buf = pixbuf.scale_simple(x, y,
                                         GdkPixbuf.InterpType.BILINEAR)
        if self.box.get_children():
            image = self.box.get_children()[0]
        else:
            image = Gtk.Image()
            self.box.add(image)
        image.set_from_pixbuf(scaled_buf)
        self.box.show_all()

    def loader_notified(self, _pixbufloader):
        GLib.idle_add(self.callback)

    def run(self):
        try:
            self.cache.get(self.url,
                           self.reader_function,
                           on_hit=self.loader.write)
            self.loader.connect("closed", self.loader_notified)
        except Exception as e:  # pylint: disable=broad-except
            logger.debug("%s(%s) while loading image", type(e).__name__, e)
        try:
            self.loader.close()
        except GLib.Error as e:
            logger.debug("picture %s caused GLib.GError %s", self.url, e)
            text = _('picture file %s not found.') % self.url
            label = Gtk.Label(wrap=True)
            label.set_text(text)
            self.box.add(label)
        except Exception as e:  # pylint: disable=broad-except
            logger.warning("picture %s caused Exception %s:%s", self.url,
                           type(e).__name__, e)
            label = Gtk.Label(wrap=True)
            label.set_text(f'picture {self.url} error "{e}"')
            self.box.add(label)
        self.box.show_all()

    def read_base64(self):
        self.loader.connect("area-prepared", self.loader_notified)
        thumb64pos = self.url.find(self.inline_picture_marker)
        offset = thumb64pos + len(self.inline_picture_marker)
        import base64
        return base64.b64decode(self.url[offset:])

    def read_global_url(self):
        self.loader.connect("area-prepared", self.loader_notified)
        # display something to show an image is loading
        label = Gtk.Label()
        text = '   loading image....'
        label.set_text(text)
        spinner = Gtk.Spinner()
        spinner.start()
        self.box.add(label)
        self.box.add(spinner)
        self.box.show_all()
        net_sess = get_net_sess()
        try:
            response = net_sess.get(self.url, timeout=5)
        except Exception as e:  # pylint: disable=broad-except
            # timeout, failed to get url, malformed url, etc.
            logger.debug('%s(%s)', type(e).__name__, e)
            response = None
        self.box.remove(label)
        self.box.remove(spinner)
        if response and response.ok:
            self.loader.write(response.content)
            return response.content
        return None

    def read_local_url(self):
        self.loader.connect("area-prepared", self.loader_notified)
        pieces = []
        with open(self.url, "rb") as f:
            for piece in read_in_chunks(f, 4096):
                self.loader.write(piece)
                pieces.append(piece)
        return ''.join(pieces)


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
                if (fkey.column.table == tbl2 and tbl not in tables and
                        tbl is not table):
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

    builders = {}

    @classmethod
    def load(cls, filename):
        if filename in list(cls.builders.keys()):
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
            self.filename = f'from object {ui}'

    def __getitem__(self, name):
        """
        :param name:
        """
        widget = self.builder.get_object(name)
        if not widget:
            raise KeyError(_('no widget named "%s" in glade file: %s') %
                           (name, self.filename))
        return widget

    def __getattr__(self, name):
        """
        :param name:
        """
        if name == '_builder_':
            return self.builder
        widget = self.builder.get_object(name)
        if not widget:
            raise KeyError(_('no widget named "%s" in glade file: %s') %
                           (name, self.filename))
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


def tree_model_has(tree, value):
    """Return True or False if value is in the tree."""
    return len(search_tree_model(tree, value)) > 0


def search_tree_model(parent, data, cmp=lambda row, data: row[0] == data):
    """Return an iterable of Gtk.TreeIter instances to all occurences
    of data in model

    :param parent: a Gtk.TreeModel or a Gtk.TreeModelRow instance
    :param data: the data to look for
    :param cmp: the function to call on each row to check if it matches
     data, default is C{lambda row, data: row[0] == data}
    """
    if isinstance(parent, Gtk.TreeModel):
        if not parent.get_iter_first():  # model empty
            return []
        return search_tree_model(parent[parent.get_iter_first()], data, cmp)
    results = set()

    def func(model, _path, itr):
        if cmp(model[itr], data):
            results.add(itr)
        return False

    parent.model.foreach(func)
    return tuple(results)


def remove_from_results_view(objs):
    """Remove the supplied objects from the SearchView results. This will only
    succeed when the current view is a SearchView.  Intended for use in remove
    callbacks.

    :param obj: the item to remove"""
    # Avoid errors in tests
    if not bauble.gui:
        return
    search_view = bauble.gui.get_view()
    results_model = search_view.results_view.get_model()
    for obj in objs:
        for itr in search_tree_model(results_model, obj):
            results_model.remove(itr)


def clear_model(obj_with_model):
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


def combo_set_active_text(combo, value):
    """does the same thing as set_combo_from_value but this looks more like a
    GTK+ method
    """
    set_combo_from_value(combo, value)


def set_combo_from_value(combo, value, cmp=lambda row, value: row[0] == value):
    """Find value in combo model and set it as active, else raise ValueError
    cmp(row, value) is the a function to use for comparison

    .. note:: if more than one value is found in the combo then the
      first one in the list is set
    """
    model = combo.get_model()
    matches = search_tree_model(model, value, cmp)
    if len(matches) == 0:
        raise ValueError('set_combo_from_value() - could not find value in '
                         'combo: %s' % value)
    combo.set_active_iter(matches[0])
    combo.emit('changed')


def combo_get_value_iter(combo, value, cmp=lambda row, value: row[0] == value):
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


def get_widget_value(widget):
    """
    :param widget: an instance of Gtk.Widget
    :param index: the row index to use for those widgets who use a model

    .. note:: any values passed in for widgets that expect a string will call
      the values __str__ method
    """

    if isinstance(widget, Gtk.Label):
        return nstr(widget.get_text())
    if isinstance(widget, Gtk.TextView):
        textbuffer = widget.get_buffer()
        return nstr(textbuffer.get_text(textbuffer.get_start_iter(),
                                        textbuffer.get_end_iter(), False))
    if isinstance(widget, Gtk.Entry):
        return nstr(widget.get_text())
    if isinstance(widget, Gtk.ComboBox):
        if widget.get_has_entry():
            return nstr(widget.get_child().props.text)
        # handle combobox without entry, assumes first item is value to return.
        model = widget.get_model()
        itr = widget.get_active_iter()
        if model is None or itr is None:
            return None
        value = model[itr][0]
        return value
    if isinstance(widget,
                  (Gtk.ToggleButton, Gtk.CheckButton, Gtk.RadioButton)):
        return widget.get_active()
    if isinstance(widget, Gtk.Button):
        return nstr(widget.props.label)

    raise TypeError('utils.set_widget_value(): Don\'t know how to handle '
                    'the widget type %s with name %s' %
                    (type(widget), widget.name))


def set_widget_value(widget, value, markup=False, default=None, index=0):
    """Set the value of the widget.

    :param widget: an instance of Gtk.Widget
    :param value: the value to put in the widget
    :param markup: whether or not value is markup
    :param default: the default value to put in the widget if the value is None
    :param index: the row index to use for those widgets who use a model

    .. note:: any values passed in for widgets that expect a string will call
      the values __str__ method
    """

    if value is None:  # set the value from the default
        if isinstance(widget, (Gtk.Label, Gtk.TextView, Gtk.Entry)) \
                and default is None:
            value = ''
        else:
            value = default

    # assume that if value is a date then we want to display it with
    # the default date format
    from bauble import prefs
    if isinstance(value, datetime.date):
        date_format = prefs.prefs[prefs.date_format_pref]
        value = value.strftime(date_format)

    if isinstance(widget, Gtk.Label):
        if markup:
            widget.set_markup(str(value))
        else:
            widget.set_text(str(value))
    elif isinstance(widget, Gtk.TextView):
        widget.get_buffer().set_text(str(value))
    elif isinstance(widget, Gtk.TextBuffer):
        widget.set_text(str(value))
    elif isinstance(widget, Gtk.SpinButton):
        if value:
            widget.set_value(float(value or 0))
    elif isinstance(widget, Gtk.Entry):
        # This can create a "Warning: g_value_get_int: assertion
        # 'G_VALUE_HOLDS_INT (value)' failed
        #   widget.set_text(nstr(value))", seems safe to ignore it.
        #   see: https://stackoverflow.com/a/40163816
        widget.set_text(str(value))
    elif isinstance(widget, Gtk.ComboBox):
        # ComboBox.with_entry
        if widget.get_has_entry():
            widget.get_child().set_text(str(value or ''))
            return
        # Gtk.ComboBoxText
        if isinstance(widget, Gtk.ComboBoxText):
            widget.get_child().append_text = value or ''
        # Gtk.ComboBox
        treeiter = None
        if not widget.get_model():
            logger.warning(
                "utils.set_widget_value(): combo doesn't have a model: %s",
                Gtk.Buildable.get_name(widget))
        else:
            treeiter = combo_get_value_iter(
                widget, value, cmp=lambda row, value: row[index] == value)
            if treeiter:
                widget.set_active_iter(treeiter)
            else:
                widget.set_active(-1)
    elif isinstance(widget,
                    (Gtk.ToggleButton, Gtk.CheckButton, Gtk.RadioButton)):
        if (isinstance(widget, Gtk.CheckButton) and
                isinstance(value, str)):
            value = (value == Gtk.Buildable.get_name(widget))
        if value is True:
            widget.set_inconsistent(False)
            widget.set_active(True)
        elif value is False:  # why do we need unset `inconsistent` for False?
            widget.set_inconsistent(False)
            widget.set_active(False)
        else:  # treat None as False, we do not handle inconsistent cases.
            widget.set_inconsistent(False)
            widget.set_active(False)
    elif isinstance(widget, Gtk.Button):
        if value is None:
            widget.props.label = ''
        else:
            widget.props.label = nstr(value)

    else:
        raise TypeError('utils.set_widget_value(): Don\'t know how to handle '
                        'the widget type %s with name %s' %
                        (type(widget), widget.name))


def create_message_dialog(msg, typ=Gtk.MessageType.INFO,
                          buttons=Gtk.ButtonsType.OK,
                          parent=None,
                          resizable=True):
    """Create a message dialog.

    :param msg: The markup to use for the message. The value should be escaped
        in case it contains any HTML entities.
    :param typ: A GTK message type constant.  The default is
        Gtk.MessageType.INFO.
    :param buttons: A GTK buttons type constant.  The default is
        Gtk.ButtonsType.OK.
    :param parent: The parent window for the dialog
    :param resizable: should the dialog be resizale (can cause the window to be
        excessively large when msg is large)

    Returns a :class:`Gtk.MessageDialog`
    """
    if parent is None:
        try:  # this might get called before bauble has started
            parent = bauble.gui.window
        except Exception:
            parent = None
    dialog = Gtk.MessageDialog(modal=True, destroy_with_parent=True,
                               transient_for=parent, message_type=typ,
                               buttons=buttons)
    dialog.set_position(Gtk.WindowPosition.CENTER)
    dialog.set_title('Ghini')
    dialog.set_markup(msg)
    if resizable:
        dialog.set_property('resizable', True)

    # get the width of a character
    context = dialog.get_pango_context()
    font_metrics = context.get_metrics(context.get_font_description(),
                                       context.get_language())
    width = font_metrics.get_approximate_char_width()
    from gi.repository import Pango
    # if the character width is less than 300 pixels then set the
    # message dialog's label to be 300 to avoid tiny dialogs
    if width / Pango.SCALE * len(msg) < 300:
        dialog.set_property('default-width', 300)

    if dialog.get_icon() is None:
        try:
            pixbuf = GdkPixbuf.Pixbuf.new_from_file(bauble.default_icon)
            dialog.set_icon(pixbuf)
        except Exception:
            pass
    dialog.set_property('skip-taskbar-hint', False)
    dialog.show_all()
    return dialog


def message_dialog(msg, typ=Gtk.MessageType.INFO, buttons=Gtk.ButtonsType.OK,
                   parent=None):
    """Create a message dialog with :func:`bauble.utils.create_message_dialog`
    and run and destroy it.

    Returns the dialog's response.
    """
    dialog = create_message_dialog(msg, typ, buttons, parent)
    response = dialog.run()
    dialog.destroy()
    return response


def create_yes_no_dialog(msg, parent=None):
    """Create a dialog with yes/no buttons."""
    if parent is None:
        try:  # this might get called before bauble has started
            parent = bauble.gui.window
        except Exception:
            parent = None
    dialog = Gtk.MessageDialog(modal=True, destroy_with_parent=True,
                               transient_for=parent,
                               message_type=Gtk.MessageType.QUESTION,
                               buttons=Gtk.ButtonsType.YES_NO)
    dialog.set_title('Ghini')
    dialog.set_position(Gtk.WindowPosition.CENTER)
    dialog.set_markup(msg)
    if dialog.get_icon() is None:
        try:
            pixbuf = GdkPixbuf.Pixbuf.new_from_file(bauble.default_icon)
            dialog.set_icon(pixbuf)
        except Exception:
            pass
        dialog.set_property('skip-taskbar-hint', False)
    dialog.show_all()
    return dialog


def yes_no_dialog(msg, parent=None, yes_delay=-1):
    """Create and run a yes/no dialog.

    Return True if the dialog response equals Gtk.ResponseType.YES

    :param msg: the message to display in the dialog
    :param parent: the dialog's parent
    :param yes_delay: the number of seconds before the yes button should
      become sensitive
    """
    dialog = create_yes_no_dialog(msg, parent)
    if yes_delay > 0:
        dialog.set_response_sensitive(Gtk.ResponseType.YES, False)

        def on_timeout():
            if dialog.get_property('visible'):\
                    # conditional avoids GTK+ warning
                dialog.set_response_sensitive(Gtk.ResponseType.YES, True)
            return False
        GLib.timeout_add(yes_delay * 1000, on_timeout)
    response = dialog.run()
    dialog.destroy()
    return response == Gtk.ResponseType.YES


def create_message_details_dialog(msg, details='', typ=Gtk.MessageType.INFO,
                                  buttons=Gtk.ButtonsType.OK, parent=None):
    """Create a message dialog with a details expander."""
    if parent is None:
        try:  # this might get called before bauble has started
            parent = bauble.gui.window
        except AttributeError:
            parent = None

    dialog = Gtk.MessageDialog(modal=True,
                               destroy_with_parent=True,
                               transient_for=parent,
                               message_type=typ,
                               buttons=buttons)
    dialog.set_title('Ghini')
    dialog.set_markup(msg)
    # allow resize and copying error messages etc.
    dialog.set_property('resizable', True)
    message_label = dialog.get_message_area().get_children()[0]
    message_label.set_selectable(True)

    # get the width of a character
    context = dialog.get_pango_context()
    font_metrics = context.get_metrics(context.get_font_description(),
                                       context.get_language())
    width = font_metrics.get_approximate_char_width()
    from gi.repository import Pango
    # if the character width is less than 300 pixels then set the
    # message dialog's label to be 300 to avoid tiny dialogs
    if width / Pango.SCALE * len(msg) < 300:
        dialog.set_size_request(300, -1)

    expand = Gtk.Expander()
    text_view = Gtk.TextView()
    text_view.set_editable(False)
    text_view.set_wrap_mode(Gtk.WrapMode.WORD)
    buffer = Gtk.TextBuffer()
    buffer.set_text(details)
    text_view.set_buffer(buffer)
    scroll_win = Gtk.ScrolledWindow(propagate_natural_height=True)
    scroll_win.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    # text_view.set_size_request(-1, 400)
    scroll_win.add(text_view)
    expand.add(scroll_win)
    content_box = dialog.get_content_area()
    content_box.pack_start(expand, True, True, 0)
    # make "OK" the default response
    dialog.set_default_response(Gtk.ResponseType.OK)
    if dialog.get_icon() is None:
        try:
            pixbuf = GdkPixbuf.Pixbuf.new_from_file(bauble.default_icon)
            dialog.set_icon(pixbuf)
        except Exception:
            pass
        dialog.set_property('skip-taskbar-hint', False)

    dialog.show_all()
    return dialog


def message_details_dialog(msg, details, typ=Gtk.MessageType.INFO,
                           buttons=Gtk.ButtonsType.OK, parent=None):
    """Create and run a message dialog with a details expander."""
    dialog = create_message_details_dialog(msg, details, typ, buttons, parent)
    response = dialog.run()
    dialog.destroy()
    return response


# Avoids: Gtk-CRITICAL: gtk_entry_set_text: assertion 'text != NULL'
def format_combo_entry_text(combo, path):
    """Return text for a Gtk.Entry of a Gtk.ComboBox with model and entry where
    the model contains a list of objects that should be displayed as strings.

    Connect this to the "format-entry-text" signal of the combobox.

    :param combo: the Gtk.ComboBox widget with attached Gtk.Liststore(object)
        model and Gtk.Entry
    :param path: the Gtk.TreePath string
    """
    detail = combo.get_model()[path][0]
    if not detail:
        return ''
    return str(detail)


def default_cell_data_func(_column, cell, model, treeiter, data=None):
    """generic cell_data_func.

    :param data: a callable, provided to the func_data parameter of the
        columns's set_cell_data_func, that when supplied obj will return an
        appropriate string for the cell's text property
    """
    obj = model[treeiter][0]
    cell.props.text = data(obj)


def setup_text_combobox(combo, values=None, cell_data_func=None):
    """Configure a Gtk.ComboBox as a text combobox

    NOTE: If you pass a cell_data_func that is a method of an object that
    holds a reference to combo then the object will not be properly
    garbage collected.  To avoid this problem either don't pass a
    method of object or make the method static

    :param combo: Gtk.ComboBox
    :param values: list vales or Gtk.ListStore
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
    combo.add_attribute(renderer, 'text', 0)

    if not isinstance(combo, Gtk.ComboBox):
        logger.debug('not a Gtk.ComboBox')
        return

    if cell_data_func:
        combo.set_cell_data_func(renderer, cell_data_func)

    # enables things like scrolling through values with keyboard and
    # other goodies
    # combo.props.text_column = 0

    if combo.get_has_entry():
        # add completion using the first column of the model for the text
        logger.debug('ComboBox has entry')
        entry = combo.get_child()
        completion = Gtk.EntryCompletion()
        entry.set_completion(completion)
        completion.set_model(model)
        completion.set_text_column(0)
        completion.set_popup_completion(True)
        completion.set_inline_completion(True)
        completion.set_inline_selection(True)
        completion.set_minimum_key_length(2)

        combo.connect('format-entry-text', format_combo_entry_text)


def today_str(fmat=None):
    """Return a string for of today's date according to format.

    If fmat=None then the format uses the prefs.date_format_pref
    """
    from bauble import prefs
    fmat = fmat or prefs.prefs.get(prefs.date_format_pref)
    today = datetime.date.today()
    return today.strftime(fmat)


def setup_date_button(view, entry, button):
    """Associate a button with entry so that when the button is clicked a date
    is inserted into the entry.

    :param view: a bauble.editor.GenericEditorView
    :param entry: the entry that the data goes into
    :param button: the button that enters the data in entry
    """
    if isinstance(entry, str):
        entry = view.widgets[entry]
    if isinstance(button, str):
        button = view.widgets[button]
    image = Gtk.Image.new_from_icon_name('x-office-calendar-symbolic',
                                         Gtk.IconSize.BUTTON)
    button.set_tooltip_text(_("Today's date"))
    button.set_image(image)

    def on_clicked(_widget):
        entry.set_text(today_str())

    if view and hasattr(view, 'connect'):
        view.connect(button, 'clicked', on_clicked)
    else:
        button.connect('clicked', on_clicked)




def nstr(obj: Any) -> Union[str, None]:
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
    uni = str(obj).replace(' ', '_').strip('<{[()]}>')
    # if nothing is left return '_'
    if not uni:
        return '_'

    start_char = (r'[A-Z]|[_]|[a-z]|\xc0-\xd6]|[\xd8-\xf6]|[\xf8-\xff]|'
                  r'[\u0100-\u02ff]|[\u0370-\u037d]|[\u037f-\u1fff]|'
                  r'[\u200c-\u200d]|[\u2070-\u218f]|[\u2c00-\u2fef]|'
                  r'[\u3001-\uD7FF]|[\uF900-\uFDCF]|[\uFDF0-\uFFFD]|')
    # depending on a ucs-2 or ucs-4 build python
    start_char_ucs4 = start_char + r'[\U00010000-\U000EFFFF]'
    name_start_char_ucs4 = r'(' + start_char_ucs4 + r')'
    name_char = (r'(' + start_char_ucs4 +
                 r'|[-.0-9\xb7\u0337-\u036f\u203f-\u2040])')

    start_char_ucs2 = start_char + r'[\uD800-\uDBFF][\uDC00-\uDFFF]'
    name_start_char_ucs2 = r'(' + start_char_ucs2 + r')'
    name_char_ucs2 = (r'(' + start_char_ucs2 +
                      r'|[-.0-9\xb7\u0337-\u036f\u203f-\u2040])')
    try:
        first_char = re.match(name_start_char_ucs4, uni[0])
    except re.error:
        first_char = re.match(name_start_char_ucs2, uni[0])
        name_char = name_char_ucs2

    if first_char:
        start_char = first_char.group()
        uni = uni[1:]
    else:
        start_char = '_'

    name_chars = ''.join([i for i in uni if re.match(name_char, i)])

    name = start_char + name_chars

    return name


def complex_hyb(tax):
    """a helper function that splits a complex hybrid formula into its parts.

    :param tax: string containing brackets surounding 2 phrases seperated by
        a cross/multipy symbol
    """
    # break apart the name parts
    prts = tax.split("×")
    len_prts = len(prts)
    left = right = find = found = 0
    result = []
    # put the bracketed parts back together
    for i, prt in enumerate(prts):
        prt = prt.strip()
        if prt.startswith('('):
            # find is the amount of closing brackets we need to find to capture
            # the whole group
            find += (len(prt) - len(prt.lstrip('(')))
            left = i + 1 if not left else left
        if prt.endswith(')'):
            found += (len(prt) - len(prt.rstrip(')')))
            if found == find:
                right = i + 1
        if right:
            result.append(''.join(
                j for j in prts[left - 1:right]).strip().replace('  ', ' × '))
            left = right = find = found = 0
        elif left == right == find == found == 0:
            result.append(prt)
        # what if we hit the end and still haven't found the matching bracket?
        # Just return what we can.
        elif i == len_prts - 1:
            result.append(''.join(
                j for j in prts[left - 1:]).strip().replace('  ', ' × '))

    # if have a bracketed part remove the outer brackets and parse that else
    # return the part italicised
    italicize_part = lambda prt: (  # noqa: E731
        '({})'.format(markup_italics(prt[1:-1]))
        if prt.startswith('(') and prt.endswith(')') else
        markup_italics(prt)
    )
    # recompile adding the cross symbols back
    return ''.join([italicize_part(i) + ' × ' for i in result])[:-3]


def markup_italics(tax):
    """Add italics markup to the appropriate parts of a species string.

    :param tax: the taxon name as a unicode string
    """
    # store the zws to reapply later (if used)
    if tax.startswith('\u200b'):
        start = '\u200b'
        tax = tax.strip('\u200b')
    else:
        start = ''

    tax = tax.strip()
    result = ''
    # simple sp.
    if tax == 'sp.':
        result = '{}'.format(tax)
    # simple species
    elif re.match(r'^[a-z-]+$', tax):
        result = '<i>{}</i>'.format(tax)
    # simple species hybrids (lowercase words separated by a multiplication
    # symbol)
    elif re.match('^[a-z-]+( × [a-z-]+)*$', tax):
        result = '<i>{}</i>'.format(tax).replace(' × ', '</i> × <i>')
    # simple cultivar (starts and ends with a ' and can be almost have anything
    # between (except further quote symbols or multiplication symbols
    elif re.match("^'[^×\'\"]+'$", tax):
        result = '{}'.format(tax)
    # simple infraspecific hybrid with nothospecies name
    elif re.match('^×[a-z-]+$', tax):
        result = '{}<i>{}</i>'.format(tax[0], tax[1:])
    # simple provisory or descriptor sp.
    elif re.match(r'^sp. \([^×]+\)$', tax):
        result = '{}'.format(tax)
    # simple descriptor (brackets surrounding anything without a multiplication
    # symbol)
    elif re.match(r'^\([^×]*\)$', tax):
        result = '{}'.format(tax)

    # recursive parts
    # species with descriptor (part with only lower letters + space + bracketed
    # section)
    elif re.match(r'^[a-z-]+ \([^×]+\)$', tax):
        result = ''.join(
            [markup_italics(i) + ' ' for i in tax.split(' ', 1)]
        )[:-1]
    # complex hybrids (contains brackets surounding 2 phrases seperated by a
    # multipy symbol) These need to be reduce to less and less complex hybrids.
    elif re.search(r'\(.+×.+\)', tax):
        result = '{}'.format(complex_hyb(tax))
    # any other type of hybrid (i.e. cv to species, provisory to cv, etc..) try
    # breaking it apart and italicizing the parts
    elif re.match('.+ × .+', tax):
        parts = [i.strip() for i in tax.split(' × ')]
        result = ''.join([markup_italics(i) + ' × ' for i in parts])[:-3]
    # anything else with spaces in it. Break them off one by one and try
    # identify the parts.
    elif ' ' in tax:
        result = ''.join(
            [markup_italics(i) + ' ' for i in tax.split(' ', 1)]
        )[:-1]
    # lastly, what to do if we just don't know... (infraspecific ranks etc.)
    else:
        result = '{}'.format(tax)

    result = result.strip()
    return start + result


def safe_numeric(s):
    'evaluate the string as a number, or return zero'

    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    return 0


def safe_int(s):
    'evaluate the string as an integer, or return zero'

    try:
        return int(s)
    except ValueError:
        pass
    return 0


__natsort_rx = re.compile(r'(\d+(?:\.\d+)?)')


def natsort_key(obj):
    """a key getter for sort and sorted function

    the sorting is done on return value of obj.__str__() so we can sort
    generic objects as well.

    use like: sorted(some_list, key=utils.natsort_key)
    """

    item = str(obj)
    chunks = __natsort_rx.split(item)
    for i in range(len(chunks)):
        if chunks[i] and chunks[i][0] in '0123456789':
            if '.' in chunks[i]:
                numtype = float
            else:
                numtype = int
            # wrap in tuple with '0' to explicitly specify numbers come first
            chunks[i] = (0, numtype(chunks[i]))
        else:
            chunks[i] = (1, chunks[i])
    return (chunks, item)


def delete_or_expunge(obj):
    """If the object is in object_session(obj).new then expunge it from the
    session.  If not then session.delete it.
    """
    from sqlalchemy.orm import object_session
    session = object_session(obj)
    if session is None:
        return
    if obj not in session.new:
        logger.debug('delete obj: %s -- %s', obj, repr(obj))
        session.delete(obj)
    else:
        logger.debug('expunge obj: %s -- %s', obj, repr(obj))
        session.expunge(obj)
        del obj


def reset_sequence(column):
    """If column.sequence is not None or the column is an Integer and
    column.autoincrement is true then reset the sequence for the next
    available value for the column...if the column doesn't have a
    sequence then do nothing and return

    The SQL statements are executed directly from db.engine

    This function only works for PostgreSQL database.  It does nothing
    for other database engines.
    """
    from bauble import db
    from sqlalchemy.types import Integer
    from sqlalchemy import schema
    if not db.engine.name == 'postgresql':
        return

    sequence_name = None
    if (hasattr(column, 'default') and
            isinstance(column.default, schema.Sequence)):
        sequence_name = column.default.name
    elif ((isinstance(column.type, Integer) and column.autoincrement) and
          (column.default is None or
           (isinstance(column.default, schema.Sequence) and
            column.default.optional)) and len(column.foreign_keys) == 0):
        sequence_name = '%s_%s_seq' % (column.table.name, column.name)
    else:
        return
    conn = db.engine.connect()
    trans = conn.begin()
    try:
        # the FOR UPDATE locks the table for the transaction
        stmt = "SELECT %s from %s FOR UPDATE;" % (
            column.name, column.table.name)
        result = conn.execute(stmt)
        maxid = None
        vals = list(result)
        if vals:
            maxid = max(vals, key=lambda x: x[0])[0]
        result.close()
        if maxid is None:
            # set the sequence to nextval()
            stmt = "SELECT nextval('%s');" % (sequence_name)
        else:
            stmt = "SELECT setval('%s', max(%s)+1) from %s;" \
                % (sequence_name, column.name, column.table.name)
        conn.execute(stmt)
    except Exception as e:
        logger.warning('bauble.utils.reset_sequence(): %s', nstr(e))
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
    eventbox = label.get_parent()

    check(eventbox is not None, 'label must have a parent')
    check(isinstance(eventbox, Gtk.EventBox),
          'label must have an Gtk.EventBox as its parent')
    label.__pressed = False

    def on_enter_notify(_widget, *_args):
        label.get_style_context().add_class('click-label')

    def on_leave_notify(_widget, *_args):
        label.get_style_context().remove_class('click-label')
        label.__pressed = False

    def on_press(*_args):
        label.__pressed = True

    def on_release(_widget, event, *args):
        if label.__pressed:
            label.__pressed = False
            label.get_style_context().remove_class('click-label')
            on_clicked(label, event, *args)

    try:
        eventbox.disconnect(label.__on_event)
        logger.debug('disconnected previous release-event handler')
        label.__on_event = eventbox.connect(
            'button_release_event', on_release, *args)
    except AttributeError:
        logger.debug('defining handlers')
        label.__on_event = eventbox.connect(
            'button_release_event', on_release, *args)
        eventbox.connect('enter_notify_event', on_enter_notify)
        eventbox.connect('leave_notify_event', on_leave_notify)
        eventbox.connect('button_press_event', on_press)


def enum_values_str(col):
    """
    :param col: a string if table.col where col is an enum type

    return a string with of the values on an enum type join by a comma
    """
    from bauble import db
    table_name, col_name = col.split('.')
    # debug('%s.%s' % (table_name, col_name))
    values = db.metadata.tables[table_name].c[col_name].type.values[:]
    if None in values:
        values[values.index(None)] = '&lt;None&gt;'
    return ', '.join(values)


def which(filename, path=None):
    """Return first occurence of file on the path."""
    if not path:
        path = os.environ['PATH'].split(os.pathsep)
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
    if engine.name == 'postgresql':
        return col.op('ILIKE')(val)
    else:
        return func.lower(col).like(func.lower(val))


def range_builder(text):
    """Return a list of numbers from a string range of the form 1-3,4,5"""
    from pyparsing import Word, Group, Suppress, delimitedList, nums, \
        ParseException, ParseResults
    rng = Group(Word(nums) + Suppress('-') + Word(nums))
    range_list = delimitedList(rng | Word(nums))

    try:
        tokens = range_list.parseString(text)
    except (AttributeError, ParseException) as e:
        logger.debug("%s(%s)", type(e).__name__, e)
        return []
    values = set()
    for rng in tokens:
        if isinstance(rng, ParseResults):
            # get here if the token is a range
            start = int(rng[0])
            end = int(rng[1]) + 1
            check(start < end, 'start must be less than end')
            values.update(list(range(start, end)))
        else:
            # get here if the token is an integer
            values.add(int(rng))
    return list(values)


def gc_objects_by_type(tipe):
    """Return a list of objects from the garbage collector by type."""
    import gc
    if isinstance(tipe, str):
        return [o for o in gc.get_objects() if type(o).__name__ == tipe]
    if inspect.isclass(tipe):
        return [o for o in gc.get_objects() if isinstance(o, tipe)]
    return [o for o in gc.get_objects() if isinstance(o, type(tipe))]


def mem(size="rss"):
    """Generalization; memory sizes: rss, rsz, vsz."""
    return int(os.popen('ps -p %d -o %s | tail -1' %
                        (os.getpid(), size)).read())


# Original topological sort code written by Ofer Faigon (www.bitformation.com)
# and used with permission
# originally found at http://www.bitformation.com/art/python_toposort.html
# can now be found in various places e.g.:
# https://github.com/Yelp/ezio/blob/master/ezio/tsort.py
def topological_sort(items, partial_order):
    """Perform topological sort.  Return list of nodes sorted by dependencies.

    :param items: a list of items to be sorted.

    :param partial_order: a list of pairs. If pair ('a', 'b') is in it, it
        means that 'a' should not appear after 'b'.

    Returns a list of the items in one of the possible orders, or None if
    partial_order contains a loop.

    We want a minimum list satisfying the requirements, and the partial
    ordering states dependencies, but they may list more nodes than
    necessary in the solution. for example, whatever dependencies are given,
    if you start from the emtpy items list, the empty list is the solution.
    """

    def add_node(graph, node):
        """Add a node to the graph if not already exists."""
        if node not in graph:
            graph[node] = [0]  # 0 = number of arcs coming into this node.

    def add_arc(graph, fromnode, tonode):
        """Add an arc to a graph. Can create multiple arcs. The end nodes must
        already exist.
        """
        graph.setdefault(fromnode, [0]).append(tonode)
        graph.setdefault(tonode, [0])
        # Update the count of incoming arcs in tonode.
        graph[tonode][0] += 1

    # step 1 - create a directed graph with an arc a->b for each input
    # pair (a,b).
    # The graph is represented by a dictionary. The dictionary contains
    # a pair item:list for each node in the graph. /item/ is the value
    # of the node. /list/'s 1st item is the count of incoming arcs, and
    # the rest are the destinations of the outgoing arcs. For example:
    # {'a':[0,'b','c'], 'b':[1], 'c':[1]}
    # represents the graph:   c <-- a --> b
    # The graph may contain loops and multiple arcs.
    # Note that our representation does not contain reference loops to
    # cause GC problems even when the represented graph contains loops,
    # because we keep the node names rather than references to the nodes.

    # (ABCDE, (AB, BC, BD)) becomes:
    # {a: [0, b], b: [1, c, d], c: [1], d: [1], e: [0]}
    # requesting B and E from the above should result in including all except
    # A, and prepending C and D to B.

    graph = {}
    for v in items:
        add_node(graph, v)
    for a, b in partial_order:  # pylint: disable=invalid-name
        add_arc(graph, a, b)

    # Step 2 - find all roots (nodes with zero incoming arcs).
    roots = [node for (node, nodeinfo) in graph.items() if nodeinfo[0] == 0]

    # step 3 - repeatedly emit a root and remove it from the graph. Removing
    # a node may convert some of the node's direct children into roots.
    # Whenever that happens, we append the new roots to the list of
    # current roots.
    sortd = []
    while len(roots) != 0:
        # If len(roots) is always 1 when we get here, it means that
        # the input describes a complete ordering and there is only
        # one possible output.
        # When len(roots) > 1, we can choose any root to send to the
        # output; this freedom represents the multiple complete orderings
        # that satisfy the input restrictions. We arbitrarily take one of
        # the roots using pop(). Note that for the algorithm to be efficient,
        # this operation must be done in O(1) time.
        root = roots.pop()
        sortd.append(root)

        # remove 'root' from the graph to be explored: first remove its
        # outgoing arcs, then remove the node. if any of the nodes which was
        # connected to 'root' remains without incoming arcs, it goes into
        # the 'roots' list.

        # if the input describes a complete ordering, len(roots) stays equal
        # to 1 at each iteration.
        for child in graph[root][1:]:
            graph[child][0] = graph[child][0] - 1
            if graph[child][0] == 0:
                roots.append(child)
        del graph[root]

    if len(list(graph.items())) != 0:
        # There is a loop in the input.
        return None

    return sortd


class GenericMessageBox(Gtk.EventBox):
    """Abstract class for showing a message box at the top of an editor."""
    def __init__(self):
        super().__init__()
        self.box = Gtk.Box()
        self.box.set_spacing(10)
        self.add(self.box)

    def show_all(self):
        self.get_parent().show_all()
        size_req = self.get_preferred_size()[1]
        self.set_size_request(size_req.width, size_req.height + 10)

    def show(self):
        self.show_all()


class MessageBox(GenericMessageBox):
    """A MessageBox that can display a message label at the top of an editor.
    """

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
        button = Gtk.Button.new_from_icon_name('window-close-symbolic',
                                               Gtk.IconSize.BUTTON)
        button.set_relief(Gtk.ReliefStyle.NONE)
        button_box.pack_start(button, False, False, 0)

        self.details_expander = Gtk.Expander(label=_('Show details'),
                                             expanded=False)
        self.vbox.pack_start(self.details_expander, True, True, 0)

        scroll_win = Gtk.ScrolledWindow()
        scroll_win.set_size_request(-1, 200)
        scroll_win.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        details_label = Gtk.TextView()
        details_label.set_wrap_mode(Gtk.WrapMode.WORD)
        details_label.set_can_focus(False)
        self.details_buffer = Gtk.TextBuffer()
        details_label.set_buffer(self.details_buffer)
        scroll_win.add(details_label)

        self.details = details
        self.details_expander.add(scroll_win)

        def on_expanded(_widget, expanded):
            requisition = self.size_request()
            self.set_size_request(requisition.width, -1)
            self.queue_resize()

        self.details_expander.connect('notify::expanded', on_expanded)

        def on_close(_widget):
            parent = self.get_parent()
            if parent is not None:
                parent.remove(self)

        button.connect('clicked', on_close)

    @property
    def message(self):
        return self.buffer.get_property('text')

    @message.setter
    def message(self, msg):
        # TODO: we could probably do something smarter here that
        # involved check the font size and window width and adjust the
        # wrap widget accordingly
        if msg:
            self.buffer.set_text(msg)
        else:
            self.buffer.set_text('')

    @property
    def details(self):
        return self.details_buffer.get_property('text')

    @details.setter
    def details(self, msg):
        if msg:
            self.details_buffer.set_text(msg)
        else:
            self.details_buffer.set_text('')


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
        self.yes_button = Gtk.Button(label='Yes')
        if on_response:
            self.yes_button.connect('clicked', on_response, True)
        button_box.pack_start(self.yes_button, False, False, 0)

        button_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.box.pack_start(button_box, False, False, 0)
        self.no_button = Gtk.Button(label='No')
        if on_response:
            self.no_button.connect('clicked', on_response, False)
        button_box.pack_start(self.no_button, False, False, 0)

    def _set_on_response(self, func):
        self.yes_button.connect('clicked', func, True)
        self.no_button.connect('clicked', func, False)

    on_response = property(fset=_set_on_response)

    @property
    def message(self):
        return self.label.get_text()

    @message.setter
    def message(self, msg):
        if msg:
            self.label.set_markup(msg)
        else:
            self.label.set_markup('')


MESSAGE_BOX_INFO = 1
MESSAGE_BOX_ERROR = 2
MESSAGE_BOX_YESNO = 3


def add_message_box(parent, type=MESSAGE_BOX_INFO):
    """
    :param parent: the parent :class:`Gtk.Box` width to add the
      message box to
    :param type: one of MESSAGE_BOX_INFO, MESSAGE_BOX_ERROR or
      MESSAGE_BOX_YESNO
    """
    msg_box = None
    if type == MESSAGE_BOX_INFO:
        msg_box = MessageBox()
    elif type == MESSAGE_BOX_ERROR:
        msg_box = MessageBox()  # check this
    elif type == MESSAGE_BOX_YESNO:
        msg_box = YesNoMessageBox()
    else:
        raise ValueError('unknown message box type: %s' % type)
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
        ignore_columns = ['id']

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


def get_urls(text):
    """Return tuples of http/https links and labels for the links.  To label a
    link prefix it with [label text],

    e.g. [BBG]http://belizebotanic.org
    """
    rgx = re.compile(r'(?:\[(.+?)\])?((?:(?:http)|(?:https))://\S+)', re.I)
    matches = []
    for match in rgx.finditer(text):
        matches.append(match.groups())
    return matches


class NetSessionFunctor:
    """Functor to return a global network Session.

    Defers creating the Session until first use.  Beware of race conditions if
    first use is within multiple threads.  Calling early in a single short
    lived thread (i.e. `connmgr.notify_new_release()`) avoids this problem.

    If proxy settings are set returns requests.Session with proxies set.  If no
    settings are set tries pypac.PACSession, if no pac file is found sets pref
    to not try PACSession ever again and always return requests.Session.  The
    same Session is returned for all future calls in the current instance.
    """

    def __init__(self):
        self.net_sess = None

    def __call__(self):
        if not self.net_sess:
            self.net_sess = self.get_net_sess()
        return self.net_sess

    @staticmethod
    def get_net_sess():
        """return a requests or pypac session for making api calls, depending
        on prefrences.
        """
        logger.debug('getting a network session')

        from bauble import prefs

        prefs_proxies = prefs.prefs.get(prefs.web_proxy_prefs)

        if prefs_proxies:
            from requests import Session
            net_sess = Session()
            logger.debug('using requests directly')
            if isinstance(prefs_proxies, dict):
                net_sess.proxies = prefs_proxies
                logger.debug('net_sess proxies manually set to %s',
                             net_sess.proxies)
        else:
            from pypac import PACSession
            net_sess = PACSession()
            pac = net_sess.get_pac()
            logger.debug('pac file = %s', pac)
            if pac is None:
                # avoid every trying again...
                val = 'no_pac_file'
                logger.debug('pref: %s set to %s', prefs.web_proxy_prefs, val)
                prefs.prefs[prefs.web_proxy_prefs] = val

        return net_sess


get_net_sess = NetSessionFunctor()


def get_user_display_name():
    import sys
    from bauble import db
    if sys.platform == 'win32':
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

    return fname or db.current_user()


def run_file_chooser_dialog(text, parent, action, last_folder, target):
    """Create and run a FileChooserNative, then write result in target entry
    widget.

    this is just a bit more than a wrapper. it adds 'last_folder', a
    string indicationg the location where to put the FileChooserNative,
    and 'target', an Entry widget.

    :param text: window label text.
    :param parent: the parent window or None.
    :param action: a Gtk.FileChooserAction value.
    :param last_folder: the folder to open the window at.
    :param target: widget that has it value set to the selected filename.
    """
    chooser = Gtk.FileChooserNative.new(text, parent, action)

    try:
        if last_folder:
            chooser.set_current_folder(last_folder)
        if chooser.run() == Gtk.ResponseType.ACCEPT:
            filename = chooser.get_filename()
            if filename:
                target.set_text(filename)
                target.set_position(len(filename))
    except Exception as e:  # pylint: disable=broad-except
        logger.warning("unhandled %s exception: %s",
                       type(e).__name__, e)
    chooser.destroy()


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
    from pathlib import Path
    from shutil import copy
    if isinstance(src_dir, str):
        src_dir = Path(src_dir)
    if isinstance(dest_dir, str):
        dest_dir = Path(dest_dir)
    for path in src_dir.glob('**/*.*'):
        if not suffixes or path.suffix in suffixes:
            destination = dest_dir / path.relative_to(src_dir)
            if not destination.parent.exists():
                logger.debug('creating dir: %s', destination.parent)
                destination.parent.mkdir(parents=True)
            if not destination.exists() or over_write:
                copy(path, destination)


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
