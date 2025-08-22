# Copyright 2008-2010 Brett Adams
# Copyright 2012-2015 Mario Frasca <mario@anche.no>.
# Copyright 2021-2024 Ross Demuth <rossdemuth123@gmail.com>
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
The geography module,

World Geographical Scheme for Recording Plant Distributions (WGSRPD)
"""
import logging
import threading
import traceback
from collections import OrderedDict
from collections.abc import Callable
from collections.abc import Iterable
from collections.abc import Iterator
from collections.abc import Sequence
from dataclasses import dataclass
from dataclasses import field
from operator import itemgetter
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Any
from typing import Self
from typing import cast

logger = logging.getLogger(__name__)

from gi.repository import Gdk
from gi.repository import GdkPixbuf
from gi.repository import Gio
from gi.repository import GLib
from gi.repository import Gtk
from sqlalchemy import Column
from sqlalchemy import Float
from sqlalchemy import ForeignKey
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy import Unicode
from sqlalchemy import event
from sqlalchemy import exists
from sqlalchemy import literal
from sqlalchemy import select
from sqlalchemy.orm import QueryableAttribute
from sqlalchemy.orm import Session
from sqlalchemy.orm import aliased
from sqlalchemy.orm import backref
from sqlalchemy.orm import deferred
from sqlalchemy.orm import object_session
from sqlalchemy.orm import relationship

import bauble
from bauble import btypes as types
from bauble import db
from bauble import pb_set_fraction
from bauble import prefs
from bauble import utils
from bauble.i18n import _
from bauble.task import queue
from bauble.utils.geo import GEOJSONMultiPoly
from bauble.utils.geo import GEOJSONPoly
from bauble.utils.geo import KMLMapCallbackFunctor
from bauble.utils.geo import get_approx_area_from_geojson_sqm
from bauble.view import Action
from bauble.view import InfoBox
from bauble.view import InfoExpander
from bauble.view import PropertiesExpander
from bauble.view import select_in_search_results

if TYPE_CHECKING:
    from . import SpeciesDistribution

GEO_KML_MAP_PREFS = "kml_templates.geography"
"""pref for path to a custom mako kml template."""

GEO_PACIFIC_CENTRIC = "geography.dist_map_pacific_centric"
"""pref whether to use a pacific centric map as default."""

map_kml_callback = KMLMapCallbackFunctor(
    prefs.prefs.get(
        GEO_KML_MAP_PREFS, str(Path(__file__).resolve().parent / "geo.kml")
    )
)

map_action = Action(
    "geo_map",
    _("Show in _map"),
    callback=map_kml_callback,
    accelerator="<ctrl>m",
    multiselect=True,
)

geography_context_menu = [map_action]


def get_species_in_geography(geo):
    """Return all the Species that have distribution in geo"""
    session = object_session(geo)
    if not session:
        raise ValueError("geography is not in a session")

    from .species_model import Species
    from .species_model import SpeciesDistribution

    master_ids = set([geo.id])
    master_ids.update(geo.get_children_ids())
    master_ids.update(geo.get_parent_ids())

    query = (
        session.query(Species)
        .join(SpeciesDistribution)
        .filter(SpeciesDistribution.geography_id.in_(master_ids))
    )
    return query.all()


class GeographyMenu(Gio.Menu):
    """Menu that attaches to a button for geography selection.

    Usage example (using a thread to prevent hanging the presenter)::

        def __init__(self):
            self.add_button = Gtk.Button(label=_("Add Geography"))
            self.geo_menu = None
            self.geo_menu_thread = threading.Thread(target=self.init_geo_menu)
            GLib.idle_add(self.geo_menu_thread.start)

        # create menu with an 'activate' signal handler and button to attach to
        def init_geo_menu(self):
            self.geo_menu = GeographyMenu.new_menu(
                self.on_activate_add_menu_item, self.add_button
            )

        # signal handler for the menu item activation
        def on_activate_add_menu_item(self, action, geo_id): ...

        # destroy it with the presenter
        def cleanup(self):
            if self.geo_menu_thread.is_alive():
                self.geo_menu_thread.join()
            if self.geo_menu is not None:
                self.geo_menu.destroy()

    """

    ACTION_NAME = "geography_activated"
    _geos_ordered: dict[int | None, list[tuple[int, str]]] = {}

    def __init__(self) -> None:
        super().__init__()
        self._populate()

    @classmethod
    def new_menu(
        cls,
        handler: Callable[[Gio.SimpleAction, str], None],
        button: Gtk.Button,
    ) -> Gtk.Menu:
        logger.debug("new geography menu %s", button)
        menu_model = cls()
        menu_model._attach_action_group(handler, button)
        menu = Gtk.Menu.new_from_model(menu_model)
        menu.attach_to_widget(button)
        button.set_sensitive(True)

        return menu

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
        handler: Callable[[Gio.SimpleAction, str], None],
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


class Geography(db.Domain):
    """
    Represents a geography unit.

    :Table name: geography

    :Columns:
        *name*:

        *code*:

        *level*

        *iso_code*:

        *parent_id*:

        *geojson*

        *approx_area*

        *label_name*

    :Properties:
        *children*:

    :Constraints:
    """

    __tablename__ = "geography"

    # columns
    name: str = Column(Unicode(255), nullable=False)
    code: str = Column(String(6), unique=True, nullable=False)
    level: int = Column(Integer, nullable=False, autoincrement=False)
    iso_code: str = Column(String(7))
    # spatial data deferred mainly to avoid comparison issues in union search
    # (i.e. reports)  NOTE that deferring can lead to the instance becoming
    # dirty when merged into another session (i.e. an editor) and the column
    # has already been loaded (i.e. infobox).  This can be avoided using a
    # separate db connection.
    # Also, NOTE that if not loaded (read) prior to changing a single list
    # history change will be recoorded with no indication of its value to the
    # change.  Can use something like:
    # `if geo.geojson != val: geo.geojson = val`
    geojson: GEOJSONPoly | GEOJSONMultiPoly = deferred(Column(types.JSON()))
    # don't use, can lead to InvalidRequestError (Collection unknown)
    # collection = relationship('Collection', back_populates='region')
    distribution: "SpeciesDistribution" = relationship(
        "SpeciesDistribution", back_populates="geography"
    )

    retrieve_cols = ["id", "code"]
    parent_id: int = Column(Integer, ForeignKey("geography.id"))
    parent: Self | None
    children: list[Self] = relationship(
        "Geography",
        cascade="all",
        backref=backref("parent", remote_side="Geography.id"),
        order_by=[name],
    )
    approx_area: float = Column(Float, default=0)
    label_name: str = Column(Unicode(255))

    @classmethod
    def retrieve(cls, session, keys):
        parts = {k: v for k, v in keys.items() if k in cls.retrieve_cols}

        if parts:
            return session.query(cls).filter_by(**parts).one_or_none()
        return None

    def __str__(self):
        return str(self.name)

    def get_parent_ids(self) -> set[int]:
        session = cast(Session, object_session(self))
        cte = (
            session.query(Geography.parent_id)
            .filter(Geography.id == self.id)
            .cte(recursive=True)
        )
        child = aliased(cte)
        query = session.query(Geography.parent_id).join(
            child, Geography.id == child.c.parent_id
        )
        query_cte = cte.union_all(query)
        query = session.query(Geography.id).join(
            query_cte, Geography.id == query_cte.c.parent_id
        )
        ids = {i[0] for i in query}
        return ids

    def get_children_ids(self) -> set[int]:
        session = cast(Session, object_session(self))
        cte = (
            session.query(Geography.id)
            .filter(Geography.id == self.id)
            .cte(recursive=True)
        )
        parent = aliased(cte)
        query_cte = cte.union_all(
            session.query(Geography.id).join(
                parent, Geography.parent_id == parent.c.id
            )
        )
        query = session.query(Geography.id).join(
            query_cte, Geography.parent_id == query_cte.c.id
        )
        ids = {i[0] for i in query}
        return ids

    def has_children(self) -> bool:
        """Has this geography or any of it children or parents got a
        SpeciesDistribution
        """
        from .species_model import SpeciesDistribution

        session = cast(Session, object_session(self))
        # more expensive than other models
        ids = {self.id}

        ids.update(self.get_parent_ids())
        ids.update(self.get_children_ids())

        return bool(
            session.query(literal(True))
            .filter(exists().where(SpeciesDistribution.geography_id.in_(ids)))
            .scalar()
        )

    def count_children(self) -> int:
        # Much more expensive than other models
        from .species_model import SpeciesDistribution

        session = cast(Session, object_session(self))
        ids = {self.id}

        ids.update(self.get_parent_ids())
        ids.update(self.get_children_ids())

        query = (
            session.query(SpeciesDistribution.species_id)
            .filter(SpeciesDistribution.geography_id.in_(ids))
            .distinct()
        )
        if prefs.prefs.get(prefs.exclude_inactive_pref):
            cls = SpeciesDistribution.species.prop.mapper.class_
            query = query.join(cls).filter(cls.active.is_(True))
        return query.count()

    def get_approx_area(self) -> float:
        """The area in square kilometres using a WGS84 sphere"""
        if not self.geojson:
            return 0.0

        return get_approx_area_from_geojson_sqm(self.geojson) / 1e6

    def get_path_from_root(self) -> list[Self]:
        """Returns the nodes from root to this node including this node."""
        parents = [self]
        geo = self
        while geo.parent is not None:
            geo = geo.parent
            parents.insert(0, geo)
        return parents

    def as_svg_paths(
        self, fill: str = "green", pacific_centric: bool = False
    ) -> str:
        """Convert geography geojson to SVG path element strings.

        Use a separate database connection to avoid loading deferred geojson.

        NOTE: pacific centric is more expensive as it creates 2 maps allowing
        centering near the join longitude
        (actually 150, 30degs before the antimeridian is usual for a pacific
        centric map)
        """
        logger.debug("as_svg_paths, self=%s, fill=%s", self, fill)
        svg_paths: list[str] = []

        if self.geojson["type"] == "MultiPolygon":
            for shape in self.geojson["coordinates"]:
                for poly in shape:
                    svg_paths.append(_path_string(poly, fill, False))
                    if pacific_centric:
                        svg_paths.append(
                            _path_string(poly, fill, pacific_centric)
                        )
        else:
            poly = self.geojson["coordinates"][0]
            svg_paths.append(_path_string(poly, fill, False))
            if pacific_centric:
                svg_paths.append(_path_string(poly, fill, pacific_centric))

        return "".join(svg_paths)

    def distribution_map(self) -> "DistributionMap":
        logger.debug("distribution map %s", self)
        return DistributionMap([self.id])


def _coord_string(lon: float, lat: float, pacific_centric: bool) -> str:
    """Convert WGS84 coordinates to SVG point strings."""
    if pacific_centric:
        return f"{round(lon + 360, 3)} {round(lat, 3)}"
    return f"{round(lon, 3)} {round(lat, 3)}"


# NOTE tuple may not be correct, could be a list but will always be 2 values
def _path_string(
    poly: Sequence[tuple[float, float]], fill: str, pacific_centric: bool
) -> str:
    """Convert a WGS84 polygon to a SVG path string.

    :param fill: fill colour value for the polygon
    :param pacific_centric: if True longitudes are shifted east by 360degs
    """
    start = _coord_string(*poly[0], pacific_centric)
    middle = [f"L {_coord_string(*i, pacific_centric)}" for i in poly[1:-1]]
    d = f'M {start} {" ".join(middle)} Z'
    return f'<path stroke="{fill}" stroke-width="0.2" fill="{fill}" d="{d}"/>'


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
    longs: list[float], pc_longs: list[float], zoom: float
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
    zoom: float, min_long: float, max_long: float
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
        for geo in session.query(Geography).filter_by(level=1):
            svg_paths.append(
                geo.as_svg_paths(fill=fill, pacific_centric=pacific_centric)
            )
    return "".join(svg_paths)


class DistMapCache(OrderedDict[int, Gtk.Image]):
    """Limited size LRU image cache dict.

    When items are accessed via square brackets they are moved to the end,
    making them last to be popped from the cache.  Use `get` method if you wish
    to avoid this.
    """

    def __setitem__(self, key: int, value: Gtk.Image) -> None:
        if len(self) > 120:
            self.popitem(last=False)
        super().__setitem__(key, value)

    def __getitem__(self, key: int) -> Gtk.Image:
        self.move_to_end(key)
        return super().__getitem__(key)


class DistributionMap:
    """Provide map images for geographies."""

    _world: str = ""
    _world_pixbuf: GdkPixbuf.Pixbuf | None = None
    _image_cache = DistMapCache()
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

    def get_areas(self) -> Iterable[Geography]:

        with db.Session() as session:
            return (
                session.query(Geography)
                .filter(
                    cast(QueryableAttribute, Geography.id).in_(self._area_ids)
                )
                .order_by(Geography.code)  # for hash: _image_cache_key
            )

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
        and `idle_add` replace the current image's place holder pixbuf.

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

    def as_image(self) -> Gtk.Image:
        """Map as a Gtk.Image.

        Images are cached for reuse.
        """
        if not self._image:
            if self._image_cache_key in self._image_cache:
                logger.debug("using cache image key=%s", self._image_cache_key)
                self._image = self._image_cache[self._image_cache_key]
            else:
                logger.debug("creating image key=%s", self._image_cache_key)
                self._image = Gtk.Image.new_from_pixbuf(self.world_pixbuf)
                self._image_cache[self._image_cache_key] = self._image
                threading.Thread(target=self._generate_image).start()

        parent = self._image.get_parent()
        if parent and hasattr(parent, "remove"):
            parent.remove(self._image)

        return self._image

    def __str__(self) -> str:
        return self.map

    @classmethod
    def reset(cls) -> None:
        """Clear cache"""
        logger.debug("reset distribution map cache")
        cls._world = ""
        cls._world_pixbuf = None
        cls._image_cache = DistMapCache()

    def get_max_zoom(self):
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
            zoom -= 0.5
        return 1


class DistMapInfoExpanderMixin:
    """Mixin to provide a right click menu for a DistributionMap in an
    InfoExpander.

    To use: In `update` wrap the DistributionMap's image widget in an
    Gtk.EventBox and connect it's button_release_event to
    `on_map_button_release`. Also, set `distribution_map` to the current
    row's, `zoomed` to `False` and `zoom_level` to `1`.

    e.g. - in the infoEpander's `update` method:
            self.zoomed = False
            self.zoom_level = 1
            self.distribution_map = row.distribution_map()
            map_event_box = Gtk.EventBox()
            map_event_box.add(self.distribution_map.as_image())
            map_event_box.connect(
                "button_release_event", self.on_map_button_release
            )
    """

    MAP_ACTION_NAME: str = "distribution_map_activated"
    distribution_map: DistributionMap
    zoom_level: float
    zoomed: bool

    def on_map_button_release(
        self, box: Gtk.EventBox, event_btn: Gdk.EventButton
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
        filter_ = Gtk.FileFilter.new()
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
            return
        image = self.distribution_map.as_image()
        pixbuf = image.get_pixbuf()
        if bauble.gui and pixbuf:
            logger.debug("copying pixbuf")
            bauble.gui.get_display_clipboard().set_image(pixbuf)

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


class GeneralGeographyExpander(DistMapInfoExpanderMixin, InfoExpander):
    """Generic info about a geography."""

    def __init__(self, widgets):
        super().__init__(_("General"), widgets)
        general_box = self.widgets.general_box
        self.widgets.remove_parent(general_box)
        self.vbox.pack_start(general_box, True, True, 0)
        self.table_cells = []

    def update(self, row: Geography) -> None:
        self.zoomed = False
        self.zoom_level = 1

        self.widgets.map_box.foreach(self.widgets.map_box.remove)

        # grab shape before distribution_map to avoid thread issues for MSSQL
        # (better to use MARS_Connection=Yes when connecting)
        shape = row.geojson.get("type", "") if row.geojson else ""
        map_event_box = Gtk.EventBox()
        self.distribution_map = row.distribution_map()
        image = self.distribution_map.as_image()

        map_event_box.add(image)
        map_event_box.connect(
            "button_release_event", self.on_map_button_release
        )
        self.widgets.map_box.pack_start(map_event_box, False, False, 0)

        on_clicked = utils.generate_on_clicked(select_in_search_results)
        level = ["Continent", "Region", "Bot. Country", "Unit"][row.level - 1]
        self.widget_set_value("name_label", row.name)
        self.widget_set_value("level", f"{level} ({row.level})")
        self.widget_set_value("code", row.code)
        self.widget_set_value("iso_code", row.iso_code)
        self.widget_set_value("parent", row.parent or "")
        self.widget_set_value("geojson_type", shape)
        self.widget_set_value("approx_size", f"{row.approx_area:.2f} km²")
        self.widget_set_value("label_name", row.label_name)
        if row.parent:
            utils.make_label_clickable(
                self.widgets.parent, on_clicked, row.parent
            )
        self.widgets.childbox.foreach(self.widgets.childbox.remove)
        for geo in row.children:
            child_lbl = Gtk.Label()
            child_lbl.set_xalign(0)
            child_lbl.set_text(str(geo))
            eventbox = Gtk.EventBox()
            eventbox.add(child_lbl)
            self.widgets.childbox.pack_start(eventbox, True, True, 0)
            utils.make_label_clickable(child_lbl, on_clicked, geo)
        self.widgets.ib_general_grid.show_all()


class GeographyInfoBox(InfoBox):
    """General info."""

    def __init__(self):
        super().__init__()
        filename = str(Path(__file__).resolve().parent / "geo_infobox.glade")
        self.widgets = utils.load_widgets(filename)
        self.general = GeneralGeographyExpander(self.widgets)
        self.add_expander(self.general)
        self.props = PropertiesExpander()
        self.add_expander(self.props)

    def update(self, row):
        self.general.update(row)
        self.props.update(row)


def consolidate_geographies(
    geographies: Iterable[Geography],
) -> list[Geography]:
    """Given a list of geographies, if all child members of a parent exist
    recursively replace the children with the parent.
    """
    parents: set[Geography] = set()
    for geo in geographies:
        if geo.parent:
            parents.add(geo.parent)

    result = set()
    for geo in parents:
        if all(i in geographies for i in geo.children):
            result.add(geo)

    for geo in geographies:
        parent_ids = geo.get_parent_ids()
        if all(i.id not in parent_ids for i in result):
            result.add(geo)

    if geographies == result:
        return list(result)
    return consolidate_geographies(result)


@dataclass
class _TreeNode:
    """Tree structure that can be built in reverse (i.e. with a list of leaves
    that know their path to the root)
    """

    geo: Geography | None
    children: dict[Geography, Self] = field(default_factory=dict)


def _get_tree_leaves(node: _TreeNode) -> list[_TreeNode]:
    """Returns all the leaves from the supplied node."""
    leaves = []
    for child in node.children.values():
        if child.children:
            leaves.extend(_get_tree_leaves(child))
        else:
            leaves.append(child)
    return leaves


def _create_geo_tree(geographies: Iterable[Geography]) -> _TreeNode:
    """Given a list of Geographies as leaves create a tree with the root being
    the whole earth.
    """
    root = _TreeNode(geo=None)  # world/earth

    for geo in geographies:
        current = root
        for g in geo.get_path_from_root():
            current = current.children.setdefault(g, _TreeNode(geo=g))
    return root


class ConsolidateByPercentArea:  # pylint: disable=too-few-public-methods
    geographies: Iterable[Geography]

    def _get_consolidated(
        self, current: _TreeNode, percent: int, allowable_children: int
    ) -> list[Geography]:
        """Traverses the tree from root to leaf stopping as soon as the sum of
        all children areas are greater than the percentage given of the current
        nodes area, or a leaf node is reached.

        Returns all geographies from the nodes where traversal stopped.
        """
        logger.debug("called with: %s", current.geo)
        result = []
        if current.geo:
            if current.geo in self.geographies:
                return [current.geo]
            # don't consolidating insufficient children
            if len(current.children) >= allowable_children:
                child_area = sum(
                    i.geo.approx_area
                    for i in _get_tree_leaves(current)
                    if i.geo
                )
                if current.geo.approx_area * percent / 100 < child_area:
                    return [current.geo]
        for child in current.children.values():
            result.extend(
                self._get_consolidated(child, percent, allowable_children)
            )
        logger.debug("consolidated to %s", [i.name for i in result])
        return result

    def __call__(
        self,
        geographies: Iterable[Geography],
        percent: int = 70,
        allowable_children: int = 1,
    ) -> list[Geography]:
        """Consolidate a list of geographies to their parents, using the sum of
        their area being greater than the given percentage of the highest
        possible parent that still has `allowable_children`.

        :param geographies: an iterable of geographies.
        :param percent: percentage of area allowed to consolidate. NOTE: 100
            may not work as expected due to inaccuracies in `approx_area`.
        :param allowable_children: the minimum number of children allowed for
            an area to be consolidated if it was not in the original list.
        """
        logger.debug("geographies = %s", [i.name for i in geographies])
        logger.debug(
            "percent = %s, allowable_children = %s",
            percent,
            allowable_children,
        )
        self.geographies = geographies
        root = _create_geo_tree(geographies)

        return self._get_consolidated(root, percent, allowable_children)


consolidate_geographies_by_percent_area = ConsolidateByPercentArea()


# Listen for changes and update the area, these should only be called rarely
@event.listens_for(Geography, "before_update")
def geography_before_update(_mapper, _connection, target: Geography) -> None:
    target.approx_area = target.get_approx_area()


@event.listens_for(Geography, "before_insert")
def geography_before_insert(_mapper, _connection, target: Geography) -> None:
    target.approx_area = target.get_approx_area()


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

    session = db.Session()
    query = session.query(Geography)
    count = query.count()
    five_percent = int(count / 20) or 1
    for done, geo in enumerate(session.query(Geography)):
        geo.approx_area = geo.get_approx_area()
        if done % five_percent == 0:
            session.commit()
            pb_set_fraction(done / count)
            yield
    session.commit()
    session.close()


def update_all_approx_areas_handler(*_args) -> None:
    """Handler to update all the species full names."""

    logger.debug("update_all_approx_areas_handler")
    try:
        queue(update_all_approx_areas_task())
    except Exception as e:  # pylint: disable=broad-except
        utils.message_details_dialog(
            utils.xml_safe(str(e)),
            traceback.format_exc(),
            Gtk.MessageType.ERROR,
        )
        logger.debug(traceback.format_exc())
