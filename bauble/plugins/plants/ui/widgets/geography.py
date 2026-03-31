# Copyright 2008-2010 Brett Adams
# Copyright 2012-2015 Mario Frasca <mario@anche.no>.
# Copyright 2021-2026 Ross Demuth <rossdemuth123@gmail.com>
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
Generic Geography widgets.
"""
import logging

logger = logging.getLogger(__name__)

import threading
import traceback
from collections.abc import Callable
from collections.abc import Iterable
from collections.abc import Iterator
from collections.abc import Sequence
from operator import itemgetter
from pathlib import Path
from typing import Any
from typing import Protocol
from typing import cast

from gi.repository import Gdk
from gi.repository import GdkPixbuf
from gi.repository import Gio
from gi.repository import GLib
from gi.repository import Gtk
from sqlalchemy import event
from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy.orm import QueryableAttribute
from sqlalchemy.orm import undefer

from bauble import db
from bauble import pb_set_fraction
from bauble import prefs
from bauble import utils
from bauble.i18n import _
from bauble.task import queue
from bauble.ui import dialogs
from bauble.ui.utils import get_clipboard

from ...geography import Geography

GEO_PACIFIC_CENTRIC = "geography.dist_map_pacific_centric"
"""pref whether to use a pacific centric map as default."""


def split_lats_longs(
    areas: Iterable[Geography],
) -> tuple[list[float], list[float]]:
    """Given an interable of Geographies return their combined lats and longs
    as separate lists.
    """
    longs: list[float] = []
    lats: list[float] = []
    for area in areas:
        if area.geojson["type"] == "MultiPolygon":
            for shape in area.geojson["coordinates"]:
                for poly in shape:
                    for long, lat in poly:
                        longs.append(long)
                        lats.append(lat)
        else:
            for long, lat in area.geojson["coordinates"][0]:
                longs.append(long)
                lats.append(lat)
    return longs, lats


def straddles_antimeridian(
    longs: list[float],
    pc_longs: list[float],
    zoom: float,
) -> bool:
    """Do the provided longitudes values stradle or are close to stradling
    the 180th meridian considering the zoom buffer.

    :param longs: an iterable longitude values.
    :param pc_longs: an iterable longitude as could be used for a pacific
        centric map.
    :param zoom: level of zoom
    """

    max_long, min_long = max(longs), min(longs)

    # straddles antimeridian (slightly biased to not - i.e. when a distribution
    # is almost global there is little benefit in switching to pacific centric
    # map)
    if abs(max(pc_longs) - min(pc_longs)) + 4 < abs(max_long - min_long):
        logger.debug("stradles antimeridian")
        return True

    try:
        zoom_buffer = calculate_zoom_buffer(max(zoom, 2), min_long, max_long)
    except ValueError:
        zoom_buffer = calculate_zoom_buffer(zoom, min_long, max_long)

    min_long_is_lt = min_long < -180 + zoom_buffer
    max_long_is_gt = max_long > 180 - zoom_buffer

    # western pacific and too close
    if min_long_is_lt and not max_long_is_gt:
        logger.debug("west stradles antimeridian")
        return True
    # eastern pacific and too close
    if max_long_is_gt and not min_long_is_lt:
        logger.debug("east stradles antimeridian")
        return True
    return False


def calculate_zoom_buffer(
    zoom: float,
    min_long: float,
    max_long: float,
) -> float:
    """Given the min and max longitude and the zoom level return the number of
    degrees required on each side of the map.

    :raises ValueError: If the result is negative (e.g. zoom level too great)
    """
    degs = (360 / zoom - abs(max_long - min_long)) / 2
    if degs < 0:
        raise ValueError(f"Negative result: {degs}, zoom level too great?")
    return degs


def get_viewbox(
    min_long: float,
    max_long: float,
    min_lat: float,
    max_lat: float,
    zoom: float,
) -> str:
    """Given the max/min lats and longs and a zoom level return a SVG viewBox
    string

    :raised ValueError: if the calculated start x is too low, indicating the
        need to use a pacific central map.
    """
    width = 360 / zoom
    height = 180 / zoom

    start_x = min_long - ((width - abs(max_long - min_long)) / 2)
    start_y = -(max_lat + ((height - abs(max_lat - min_lat)) / 2))
    # correct for too far north or south
    if start_y < -90:
        start_y = -90.0
    else:
        start_y = min(start_y, 180.0 - height - 90.0)

    logger.debug(
        "start_x = %s start_y = %s width = %s height = %s",
        start_x,
        start_y,
        width,
        height,
    )

    if start_x < -180:
        if zoom == 1:
            start_x = -180.0
        else:
            raise ValueError(
                f"Too low a value for viewbox x axis start point: {start_x} "
                f"at zoom level {zoom}"
            )
    return (
        f"{round(start_x, 3)} {round(start_y, 3)} "
        f"{round(width, 3)} {round(height, 3)}"
    )


@utils.timed_cache(size=3, secs=None)
def get_world_paths(fill: str, pacific_centric: bool) -> str:
    """All continent level WGSRPD areas as an string of SVG paths."""
    svg_paths = []
    with db.Session() as session:
        for geo in session.scalars(
            select(Geography).where(Geography.level == 1)
        ):
            svg_paths.append(
                geo.as_svg_paths(fill=fill, pacific_centric=pacific_centric)
            )
    return "".join(svg_paths)


class DistributionMap:
    """Provide map images for geographies."""

    _world: str = ""
    _world_pixbuf: GdkPixbuf.Pixbuf | None = None
    _image_cache = utils.LRUCache[int, Gtk.Image](size=120)
    _pacific_centric: bool = False

    def __init__(self, ids: Sequence[int]) -> None:
        # Use a separate session to avoid triggering history pointlessly
        self._area_ids = ids
        self.areas = self.get_areas()
        codes_str = "|".join(i.code for i in self.areas)
        self._image_cache_key = hash(codes_str)

        if not self._world:
            # set once per session
            type(self)._pacific_centric = bool(
                prefs.prefs.get(GEO_PACIFIC_CENTRIC)
            )
        self._svg_paths = (
            i.as_svg_paths(pacific_centric=self._pacific_centric)
            for i in self.areas
        )

        self._image: Gtk.Image | None = None
        self._map: str = ""
        self._zoom_map: str = ""
        self._current_max_mins: tuple[float, float, float, float] | None = None
        self._lock = threading.Lock()

    def get_areas(self) -> Iterable[Geography]:

        with db.Session() as session:
            return (
                session.scalars(
                    select(Geography)
                    .options(undefer(Geography.geojson))
                    .where(
                        cast(QueryableAttribute, Geography.id).in_(
                            self._area_ids
                        )
                    )
                    .order_by(Geography.code)
                )
            ).all()

    @property
    def map(self) -> str:
        """Instance level SVG map for the supplied geographies."""
        if not self._map:
            logger.debug("generating map")
            self._map = self.world.format(selected="".join(self._svg_paths))
        return self._map

    @property
    def zoom_map(self) -> str:
        """Map template ready to zoom by formating with `viewbox`."""
        if not self._zoom_map:
            logger.debug("generating zoom map")
            svg_paths = []
            for area in self.areas:
                svg_paths.append(
                    area.as_svg_paths(fill="green", pacific_centric=True)
                )
            selected = "".join(svg_paths)
            world_paths = get_world_paths("lightgrey", True)
            self._zoom_map = (
                '<svg xmlns="http://www.w3.org/2000/svg" '
                'width="360" height="180" '
                'viewBox="{viewbox}">'
                '<g transform="scale(1, -1)">'
                f"{world_paths}"
                f"{selected}"
                "</g>"
                "</svg>"
            )
        return self._zoom_map

    def get_zoom_viewbox(self, zoom: float) -> str:
        """Return an appropriate viewBox value as a string for the supplied
        zoom level.

        Avoids recalculating from scratch when no need.
        """
        if self._current_max_mins:
            try:
                return get_viewbox(*self._current_max_mins, zoom=zoom)
            except ValueError:
                pass
        longs, lats = split_lats_longs(self.areas)
        pc_longs = [i + 360 if i < 0 else i for i in longs]

        pacific_centric = straddles_antimeridian(longs, pc_longs, zoom)

        if pacific_centric:
            # NOTE for purely eastern pacific pc_longs and longs are equal
            max_long, min_long = max(pc_longs), min(pc_longs)
        else:
            min_long, max_long = min(longs), max(longs)

        max_lat, min_lat = max(lats), min(lats)
        self._current_max_mins = (min_long, max_long, min_lat, max_lat)

        return get_viewbox(*self._current_max_mins, zoom=zoom)

    @property
    def world(self) -> str:
        """Class level SVG map template ready to take more paths in it's
        `selected` placeholder.
        """
        if not self._world:
            self._set_base_map(self._pacific_centric)
        return self._world

    @property
    def world_pixbuf(self) -> GdkPixbuf.Pixbuf:
        """Class level map as a pixbuf, use to create blank map images."""
        if not self._world_pixbuf:
            self._set_base_map(self._pacific_centric)
        return cast(GdkPixbuf.Pixbuf, self._world_pixbuf)

    @classmethod
    def _set_base_map(cls, pacific_centric: bool) -> None:
        """Set the class level world SVG map and pixbuf once."""
        logger.debug("setting base map")

        viewbox = "-180 -90 360 180"
        if cls._pacific_centric:
            # 30degs before the antimeridian for a pacific centric map
            viewbox = "-30 -90 360 180"

        world_paths = get_world_paths("lightgrey", pacific_centric)
        cls._world = (
            '<svg xmlns="http://www.w3.org/2000/svg" width="360" height="180" '
            f'viewBox="{viewbox}">'
            '<g transform="scale(1, -1)">'
            f"{world_paths}"
            "{selected}"
            "</g>"
            "</svg>"
        )
        loader = GdkPixbuf.PixbufLoader()
        loader.write(cls._world.format(selected="").encode())
        loader.close()
        pixbuf = loader.get_pixbuf()
        cls._world_pixbuf = pixbuf

    def _generate_image(self) -> None:
        """Generate an appropriate image pixbuf for the supplied geographies
        and ``idle_add`` replace the current image's place holder pixbuf.

        Run in a thread while the image, with a placeholder pixbuf, is used
        replacing it's pixbuf when it becomes available.
        """
        loader = GdkPixbuf.PixbufLoader()
        loader.write(str(self).encode())
        loader.close()
        pixbuf = loader.get_pixbuf()
        if self._image:  # type guard
            logger.debug("setting image pixbuf")
            GLib.idle_add(self._image.set_from_pixbuf, pixbuf)

    def replace_image(self, svg: str) -> None:
        """Temperarily replace the image (e.g. zoom)"""
        self._map = svg
        loader = GdkPixbuf.PixbufLoader()
        loader.write(str(svg).encode())
        loader.close()
        pixbuf = loader.get_pixbuf()
        if self._image:  # type guard
            logger.debug("replacing image pixbuf")
            self._image.set_from_pixbuf(pixbuf)
            # delete from cache so it refreshes next access
            if self._image_cache.get(self._image_cache_key):
                del self._image_cache[self._image_cache_key]

    def zoom_to_level(self, zoom: float) -> None:
        logger.debug("zooming to level: %s", zoom)
        svg = self.zoom_map.format(viewbox=self.get_zoom_viewbox(zoom))
        self.replace_image(svg)

    def detach_image(self) -> None:

        if not self._image:
            return

        parent = self._image.get_parent()
        if parent and hasattr(parent, "remove"):
            parent.remove(self._image)

    def as_image(self) -> Gtk.Image:
        """Map as a Gtk.Image.

        Images are cached for reuse.
        """
        if not self._image:
            if self._image_cache_key in self._image_cache:
                logger.debug("using cache image key=%s", self._image_cache_key)
                self._image = self._image_cache[self._image_cache_key]
                self.detach_image()
            else:
                logger.debug("creating image key=%s", self._image_cache_key)
                self._image = Gtk.Image.new_from_pixbuf(self.world_pixbuf)
                self._image_cache[self._image_cache_key] = self._image
                self._image.set_halign(Gtk.Align.START)
                threading.Thread(target=self._generate_image).start()

        return self._image

    def __str__(self) -> str:
        with self._lock:
            return self.map

    @classmethod
    def reset(cls) -> None:
        """Clear cache"""
        logger.debug("reset distribution map cache")
        cls._world = ""
        cls._world_pixbuf = None
        cls._image_cache = utils.LRUCache()

    def get_max_zoom(self) -> int:
        longs, lats = split_lats_longs(self.areas)
        max_lat, min_lat = max(lats), min(lats)

        pc_longs = [i + 360 if i < 0 else i for i in longs]

        pacific_centric = straddles_antimeridian(longs, pc_longs, 1)
        logger.debug("pacific_centric = %s", pacific_centric)

        if pacific_centric:
            # NOTE for purely eastern pacific pc_longs and longs are equal
            max_long, min_long = max(pc_longs), min(pc_longs)
        else:
            max_long, min_long = max(longs), min(longs)
        width = abs(max_long - min_long)
        height = abs(max_lat - min_lat)

        zoom = 18
        while zoom > 1:
            zwidth = 360 / zoom
            zheight = 180 / zoom
            if width < zwidth and height < zheight:
                return zoom
            zoom -= 1

        return 1


class ModelWDistributionMap(Protocol):
    # pylint: disable=too-few-public-methods
    """Protocol for models that provide a distribution map."""

    def get_geography_ids(self) -> list[int] | None: ...


class DistributionMapEventBox(Gtk.EventBox):
    """EventBox to display a rows DistributionMap image and provide a context
    menu.

    To use: add this widget and call ``update(row)`` on it when required.

    e.g.::

        XML = '''<?xml version="1.0" encoding="UTF-8"?>
        <interface>
          <template class="InfoBox" parent="GtkExpander">
            <property name="visible">True</property>
            <property name="can-focus">True</property>
            <child>
              <object class="DistributionMapEventBox" id="map_event_box"/>
              <packing>
                <property name="expand">False</property>
                <property name="fill">True</property>
                <property name="position">1</property>
              </packing>
            </child>
          </template>
        </interface>
        '''

        @Gtk.Template(string=XML)
        class InfoExpander(InfoExpander, Gtk.Expander):

            __gtype_name__ = "InfoExpander"

            map_event_box = cast(DistributionMapEventBox, Gtk.Template.Child())

            # - alternatively, if not using Gtk.Template
            # def __init__(self):
            #     self.map_event_box = DistributionMapEventBox()

            def update(self, row):
                self.map_event_box.update(row)

    """

    __gtype_name__ = "DistributionMapEventBox"

    MAP_ACTION_NAME = "distribution_map_activated"

    def __init__(self) -> None:
        super().__init__()
        self.distribution_map: DistributionMap | None = None
        self.zoomed = False
        self.zoom_level = 1
        self.connect("button_release_event", self.on_map_button_release)

    def update(self, row: ModelWDistributionMap) -> None:
        """Update the map image for the supplied row."""
        self.zoomed = False
        self.zoom_level = 1
        self.foreach(self.remove)
        ids = row.get_geography_ids()
        if not ids:
            return

        map_ = DistributionMap(ids)

        self.distribution_map = map_
        image = self.distribution_map.as_image()
        self.add(image)
        self.show_all()

    def on_map_button_release(
        self,
        box: Gtk.EventBox,
        event_btn: Gdk.EventButton,
    ) -> bool:
        """On right click create menu and pop it up."""
        if event_btn.button == 3:
            menu = Gio.Menu()
            action_group = Gio.SimpleActionGroup()

            if self.zoomed:
                last_item = (_("Zoom out"), "zmout", self.on_dist_map_zoom_out)
            else:
                last_item = (_("Zoom"), "zoom", self.on_dist_map_zoom)

            menu_items = (
                (_("Save"), "save", self.on_dist_map_save),
                (_("Copy"), "copy", self.on_dist_map_copy),
                last_item,
            )
            for label, name, handler in menu_items:
                action = Gio.SimpleAction.new(name, None)
                action.connect("activate", handler)
                action.set_enabled(True)
                action_group.add_action(action)
                menu_item = Gio.MenuItem.new(
                    label, f"{self.MAP_ACTION_NAME}.{name}"
                )
                menu.append_item(menu_item)
            context_menu = Gtk.Menu.new_from_model(menu)
            context_menu.attach_to_widget(box)

            box.insert_action_group(self.MAP_ACTION_NAME, action_group)
            context_menu.popup_at_pointer(event_btn)
            return True
        return False

    def on_dist_map_save(self, _action, _param) -> None:
        """Save as SVG file."""
        if not self.distribution_map:
            return

        filechooser = Gtk.FileChooserNative.new(
            _("Save to…"), None, Gtk.FileChooserAction.SAVE
        )
        filechooser.set_current_folder(str(Path.home()))
        filter_ = Gtk.FileFilter().new()
        filter_.add_pattern("*.svg")
        filechooser.add_filter(filter_)
        filename = None
        if filechooser.run() == Gtk.ResponseType.ACCEPT:
            filename = filechooser.get_filename()

        if filename:
            logger.debug("saving SVG to %s", filename)
            with Path(filename).open("w", encoding="utf-8") as f:
                f.write(str(self.distribution_map))

        filechooser.destroy()

    def on_dist_map_copy(self, _action, _param) -> None:
        """Copy the pixbuf to the clipboard."""
        if not self.distribution_map:
            logger.debug("no distribution_map to copy")
            return

        image = self.distribution_map.as_image()
        pixbuf = image.get_pixbuf()

        clipboard = get_clipboard()
        if clipboard and pixbuf:
            logger.debug("copying pixbuf")
            clipboard.set_image(pixbuf)

    def on_dist_map_zoom(self, _action, _param) -> None:
        """Zoom the map to the maximum zoom level that displays the areas."""
        if not self.distribution_map:
            return

        self.zoom_level = self.distribution_map.get_max_zoom()
        if self.zoom_level == 1:
            return

        self.distribution_map.zoom_to_level(self.zoom_level)
        self.zoomed = True

    def on_dist_map_zoom_out(self, _action, _param) -> None:
        if not self.distribution_map:
            return

        if self.zoom_level != 1:

            step = 2
            if self.zoom_level < 4:
                step = 1

            self.zoom_level = max(1, self.zoom_level - step)
            if self.zoom_level == 1:
                self.zoomed = False

        self.distribution_map.zoom_to_level(self.zoom_level)


class GeographyMenu(Gio.Menu):
    """Menu that attaches to a button for geography selection.

    NOTE: the menu is populated in a thread.  The button supplied to
    ``attach_new`` should be set insensitive and will be set sensitive when the
    menu is ready and attached.

    Usage example::

        def __init__(self):
            GeographyMenu.attach_new(self.on_activate_menu_item, geo_button)

        # signal handler for the menu item activation
        def on_activate_menu_item(self, action, geo_id): ...

    """

    ACTION_NAME = "geography_activated"

    _geos_ordered: dict[int | None, list[tuple[int, str]]] = {}

    def __init__(self) -> None:
        super().__init__()
        self._populate()

    @classmethod
    def attach_new(
        cls,
        handler: Callable[[Gio.SimpleAction, GLib.Variant], None],
        button: Gtk.Button,
    ) -> None:

        threading.Thread(
            target=cls._create,
            args=(handler, button),
            daemon=True,
        ).start()

    @classmethod
    def _create(
        cls,
        handler: Callable[[Gio.SimpleAction, GLib.Variant], None],
        button: Gtk.Button,
    ) -> None:

        logger.debug("new geography menu %s", button)
        menu_model = cls()
        GLib.idle_add(menu_model._attach, handler, button)

    def _attach(
        self,
        handler: Callable[[Gio.SimpleAction, GLib.Variant], None],
        button: Gtk.Button,
    ) -> None:
        self._attach_action_group(handler, button)
        menu = Gtk.Menu.new_from_model(self)
        menu.attach_to_widget(button)

        button.connect(
            "button-press-event",
            lambda w, e: menu.popup_at_pointer(e),
        )

        button.set_sensitive(True)

    @property
    def geos_ordered(self) -> dict[int | None, list[tuple[int, str]]]:
        if not self._geos_ordered:
            geography_table = Geography.__table__
            stmt = select(
                [
                    geography_table.c.id,
                    geography_table.c.name,
                    geography_table.c.parent_id,
                ]
            )
            with db.engine.begin() as connection:
                geos = connection.execute(stmt).all()

            geos_ordered: dict[int | None, list[tuple[int, str]]] = {}
            for id_, name, parent_id in geos:
                geos_ordered.setdefault(parent_id, []).append((id_, name))

            for kids in geos_ordered.values():
                kids.sort(key=itemgetter(1))  # sort by name

            type(self)._geos_ordered = geos_ordered
        return self._geos_ordered

    def _attach_action_group(
        self,
        handler: Callable[[Gio.SimpleAction, GLib.Variant], None],
        button: Gtk.Button,
    ) -> None:
        action = Gio.SimpleAction.new(self.ACTION_NAME, GLib.VariantType("s"))
        action.connect("activate", handler)
        action_group = Gio.SimpleActionGroup()
        action_group.add_action(action)
        button.insert_action_group("geo", action_group)

    def _build_menu(self, geo_id: int, name: str) -> Gio.MenuItem | Gio.Menu:
        next_level = self.geos_ordered.get(geo_id)

        if next_level:
            submenu = Gio.Menu()
            item = Gio.MenuItem.new(name, f"geo.{self.ACTION_NAME}::{geo_id}")
            submenu.append_item(item)
            section = Gio.Menu()
            submenu.append_section(None, section)
            for id_, name_ in next_level:
                next_item = self._build_menu(id_, name_)
                if isinstance(next_item, Gio.MenuItem):
                    section.append_item(next_item)
                else:
                    section.append_submenu(name_, next_item)
            # result
            return submenu

        # base case
        return Gio.MenuItem.new(name, f"geo.{self.ACTION_NAME}::{geo_id}")

    def _populate(self) -> None:
        """add geography value to the menu, any top level items that don't
        have any kids are appended to the bottom of the menu
        """

        if not self.geos_ordered:
            # we would get here if the geos_ordered isn't populated, usually
            # during a unit test
            return

        no_kids = []

        for geo_id, geo_name in self.geos_ordered[None]:
            menu = self._build_menu(geo_id, geo_name)

            if isinstance(menu, Gio.Menu):
                self.append_submenu(geo_name, menu)
            else:
                no_kids.append(menu)

        for item in no_kids:
            # append to the end of the menu
            self.append_item(item)

    @classmethod
    def reset(cls) -> None:
        cls._geos_ordered = {}


# update the menu in the event of any changes (should be rare)
@event.listens_for(Geography, "after_update")
def geography_after_update(_mapper, _connection, _target) -> None:
    GeographyMenu.reset()


@event.listens_for(Geography, "after_insert")
def geography_after_insert(_mapper, _connection, _target) -> None:
    GeographyMenu.reset()


@event.listens_for(Geography, "after_delete")
def geography_after_delete(_mapper, _connection, _target) -> None:
    GeographyMenu.reset()


def update_all_approx_areas_task(*_args: Any) -> Iterator[None]:
    """Task to update all the geographies approx area.

    Yields occassionally to update the progress bar
    """

    with db.Session() as session:
        count = session.scalar(select(func.count()).select_from(Geography))
        five_percent = int(count / 20) or 1
        for done, geo in enumerate(session.scalars(select(Geography))):
            geo.approx_area = geo.get_approx_area()
            if done % five_percent == 0:
                session.commit()
                pb_set_fraction(done / count)
                yield
        session.commit()


def update_all_approx_areas_handler(*_args) -> None:
    """Handler to update all the species full names."""

    logger.debug("update_all_approx_areas_handler")
    try:
        queue(update_all_approx_areas_task())
    except Exception as e:  # pylint: disable=broad-except
        dialogs.message_details_dialog(
            utils.xml_safe(str(e)),
            traceback.format_exc(),
            Gtk.MessageType.ERROR,
        )
        logger.debug(traceback.format_exc())
