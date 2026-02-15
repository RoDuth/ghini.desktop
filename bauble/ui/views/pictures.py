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
Pictures display widgets, as used in SearchView.
"""

import logging

logger = logging.getLogger(__name__)

import threading
from pathlib import Path
from typing import cast

from gi.repository import Gdk
from gi.repository import GLib
from gi.repository import GObject
from gi.repository import Gtk

from bauble import db
from bauble import prefs
from bauble import utils

from ..utils import ImageLoader


class PicturesScroller(Gtk.ScrolledWindow):
    # pylint: disable=too-many-instance-attributes
    """Displays pictures corresponding to the supplied domain objects."""

    __gsignals__ = {
        "picture-selected": (
            GObject.SignalFlags.RUN_FIRST,
            None,
            (object,),
        ),
    }

    PAGE_SIZE = 6

    def __init__(self) -> None:
        logger.debug("entering PicturesScroller.__init__")
        super().__init__()
        self.pictures_box = Gtk.FlowBox()
        self.pictures_box.set_selection_mode(Gtk.SelectionMode.NONE)
        self.add(self.pictures_box)
        self.show()
        self.single_button_press_timer: threading.Timer | None = None
        self.get_vadjustment().connect("value-changed", self.on_scrolled)
        self.max_allocated_height = 0
        self.all_pics: list[db.Picture] | None = None
        self.count = 0
        self.waiting_on_realise = 0
        self.selection: list[db.Domain] = []

    def on_scrolled(self, adjustment: Gtk.Adjustment) -> None:
        """On scrolling add more pictures as needed.

        Uses the largest size allocation (of the last batch after they are
        realised) to calculate if the end is close.
        """
        page_size = adjustment.get_page_size()
        current_val = adjustment.get_value()
        upper_val = adjustment.get_upper()
        if page_size + current_val > upper_val - self.max_allocated_height:
            self.add_rows()

    def on_image_size_allocated(self, image: Gtk.Widget, *_args) -> None:
        """After an image has had its size allocated use its `pic_box` height
        allocation to calculate the maximum height allocation of the current
        batch of pictures.

        Also triggers on_scrolled in case more images are needed on the page.
        """
        pic_box = cast(Gtk.Box, image.get_parent())

        # pic_box can be None very occassionly
        allocated_height = pic_box.get_allocated_height() if pic_box else 0
        # max is slower # pylint: disable=consider-using-max-builtin
        if allocated_height > self.max_allocated_height:
            self.max_allocated_height = allocated_height

        # avoid making negative in case of an overlap (i.e. user changes
        # selection prior to image realising)
        if self.waiting_on_realise > 0:
            self.waiting_on_realise -= 1

        # check if more should be added (e.g. first run, so we get a scrollbar)
        if self.waiting_on_realise <= 0:
            GLib.idle_add(self.on_scrolled, self.get_vadjustment())

    def update(self, selection: list[db.Domain] | None) -> None:
        logger.debug("PicturesScroller.update(%s)", selection)

        # bail early if nothing has changed
        if self.selection == selection:
            return

        self.selection = selection or []

        self.all_pics = None

        for kid in self.pictures_box.get_children():
            kid.destroy()

        self.count = 0
        self.waiting_on_realise = 0

        self.all_pics = self._get_pictures(selection or [])
        self.add_rows()

    @staticmethod
    def _get_pictures(selection: list[db.Domain]) -> list[db.Picture]:
        all_pics_set: set[db.Picture] = set()
        for obj in selection:
            if pics := getattr(obj, "pictures", None):
                all_pics_set.update(pics)

        # prefer group PlantPictures by species name
        # space before id string places others before PlantPicture
        return sorted(
            all_pics_set,
            key=lambda i: (
                (str(i.owner.accession.species), str(i.owner))
                if hasattr(i.owner, "accession")
                else (str(i.owner), " " + str(i.id))
            ),
        )

    def add_rows(self) -> None:
        """Add a page of pictures."""
        if self.all_pics is None:
            return

        if self.count == len(self.all_pics):
            # bail early if already finished adding rows
            return

        self.max_allocated_height = 0

        page_end = self.count + self.PAGE_SIZE
        for pic in self.all_pics[self.count : page_end]:
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            if pic.category:
                label = Gtk.Label(label="category: " + pic.category)
                box.add(label)
            event_box = Gtk.EventBox()
            event_box.connect(
                "button-press-event",
                self.on_button_press,
                pic,
            )
            pic_box = Gtk.Box()
            self.waiting_on_realise += 1
            ImageLoader(
                pic_box,
                pic.picture,
                on_size_allocated=self.on_image_size_allocated,
            ).start()
            pic_box.set_vexpand(True)
            event_box.add(pic_box)
            box.pack_start(event_box, False, True, 0)
            self.pictures_box.add(box)
            box.show_all()
            self.count += 1

        self.pictures_box.show_all()

    def on_button_press(
        self, _view, event: Gdk.EventButton, picture: db.Picture
    ) -> None:
        """On double click open the image in the default viewer. On single
        click select the item in the search view, if its already selected check
        if the picture comes from a child and if so select it.
        """
        # hack single click
        if self.single_button_press_timer:
            self.single_button_press_timer.cancel()
            self.single_button_press_timer = None
        link = picture.picture
        if event.button == 1:
            if event.type == Gdk.EventType.DOUBLE_BUTTON_PRESS:
                # if it is not a url append the picture_root and open, if it is
                # a URL just open it.
                full_path = None
                if not (
                    link.startswith("http://") or link.startswith("https://")
                ):
                    pic_root = prefs.prefs.get(prefs.picture_root_pref)
                    full_path = Path(pic_root, link)
                utils.desktop.open(full_path or link)
            elif event.type == Gdk.EventType.BUTTON_PRESS:
                self.single_button_press_timer = threading.Timer(
                    0.3, self._on_single_button_press, (picture,)
                )
                self.single_button_press_timer.start()

    def _on_single_button_press(self, picture: db.Picture) -> None:
        self.single_button_press_timer = None
        GLib.idle_add(self.emit, "picture-selected", picture)
