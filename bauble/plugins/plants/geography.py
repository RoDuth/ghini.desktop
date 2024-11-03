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
from collections.abc import Iterable
from collections.abc import Iterator
from collections.abc import Sequence
from dataclasses import dataclass
from dataclasses import field
from operator import itemgetter
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Any
from typing import Protocol
from typing import Self
from typing import cast

logger = logging.getLogger(__name__)

from gi.repository import Gdk
from gi.repository import GdkPixbuf
from gi.repository import Gio
from gi.repository import GLib
from gi.repository import Gtk
from pyproj import Geod
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
from bauble import error
from bauble import pb_set_fraction
from bauble import prefs
from bauble import utils
from bauble.i18n import _
from bauble.task import queue
from bauble.utils.geo import KMLMapCallbackFunctor
from bauble.view import Action
from bauble.view import InfoBox
from bauble.view import InfoExpander
from bauble.view import PropertiesExpander
from bauble.view import select_in_search_results

if TYPE_CHECKING:
    from . import SpeciesDistribution

GEO_KML_MAP_PREFS = "kml_templates.geography"
"""pref for path to a custom mako kml template."""

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

# set WGS84 as CRS
geod = Geod(ellps="WGS84")


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
    ACTION_NAME = "geography_activated"

    def __init__(self):
        super().__init__()
        geography_table = Geography.__table__
        self.geos = (
            select(
                [
                    geography_table.c.id,
                    geography_table.c.name,
                    geography_table.c.parent_id,
                ]
            )
            .execute()
            .fetchall()
        )
        self.geos_hash = {}
        self.populate()

    @classmethod
    def new_menu(cls, callback, button):
        menu = cls()
        menu.attach_action_group(callback, button)

        return Gtk.Menu.new_from_model(menu)

    def attach_action_group(self, callback, button):
        action = Gio.SimpleAction.new(self.ACTION_NAME, GLib.VariantType("s"))
        action.connect("activate", callback)
        action_group = Gio.SimpleActionGroup()
        action_group.add_action(action)
        button.insert_action_group("geo", action_group)

    def get_geos_hash(self):
        geos_hash = {}
        for geo_id, name, parent_id in self.geos:
            geos_hash.setdefault(parent_id, []).append((geo_id, name))

        for kids in geos_hash.values():
            kids.sort(key=itemgetter(1))  # sort by name

        return geos_hash

    def build_menu(self, geo_id, name):
        if next_level := self.geos_hash.get(geo_id):
            submenu = Gio.Menu()
            item = Gio.MenuItem.new(name, f"geo.{self.ACTION_NAME}::{geo_id}")
            submenu.append_item(item)
            section = Gio.Menu()
            submenu.append_section(None, section)
            for id_, name_ in next_level:
                item = self.build_menu(id_, name_)
                if isinstance(item, Gio.MenuItem):
                    section.append_item(item)
                else:
                    section.append_submenu(name_, item)
            return submenu

        item = Gio.MenuItem.new(name, f"geo.{self.ACTION_NAME}::{geo_id}")
        return item

    def populate(self):
        """add geography value to the menu, any top level items that don't
        have any kids are appended to the bottom of the menu
        """
        self.geos_hash = self.get_geos_hash()

        if not self.geos_hash:
            # we would get here if the geos_hash isn't populated, usually
            # during a unit test
            return

        for geo_id, geo_name in self.geos_hash[None]:
            self.append_submenu(geo_name, self.build_menu(geo_id, geo_name))


class Geography(db.Base):
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

    id: int
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
    geojson: dict = deferred(Column(types.JSON()))
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
        total = 0.0
        if self.geojson["type"] == "MultiPolygon":
            for poly in self.geojson["coordinates"]:
                for internal in poly:
                    lons = []
                    lats = []
                    for lon, lat in internal:
                        lons.append(lon)
                        lats.append(lat)
                    area, __ = geod.polygon_area_perimeter(lons, lats)
                    total += area
        elif self.geojson["type"] == "Polygon":
            for internal in self.geojson["coordinates"]:
                lons = []
                lats = []
                for lon, lat in internal:
                    lons.append(lon)
                    lats.append(lat)
                area, __ = geod.polygon_area_perimeter(lons, lats)
                total += area
        return abs(total) / 1e6

    def get_path_from_root(self) -> list[Self]:
        """Returns the nodes from root to this node including this node."""
        parents = [self]
        geo = self
        while geo.parent is not None:
            geo = geo.parent
            parents.insert(0, geo)
        return parents

    def as_svg_paths(self, fill: str = "green") -> str:
        """Convert geography geojson to SVG path element strings.

        Use a separate database connection to avoid loading deferred geojson.
        """
        logger.debug("as_svg_paths, self=%s, fill=%s", self, fill)
        svg_paths: list[str] = []

        coords = self.geojson["coordinates"]
        for shape in coords:
            if self.geojson["type"] == "MultiPolygon":
                for poly in shape:
                    svg_paths.append(_path_string(poly, fill))
            else:
                svg_paths.append(_path_string(shape, fill))

        return "".join(svg_paths)

    def distribution_map(self) -> "DistributionMap":
        logger.debug("distribution map %s", self)
        return DistributionMap([self.id])


@utils.timed_cache(size=1000, secs=None)
def _coord_string(lon: int, lat: int) -> str:
    """Convert WGS84 coordinates to SVG point strings."""
    return f"{round(lon, 3)} {round(lat, 3)}"


def _path_string(poly: Sequence[Iterable[int]], fill: str) -> str:
    """Convert a WGS84 polygon to a SVG path string.

    :param fill: fill colour value for the polygon
    """
    start = _coord_string(*poly[0])
    middle = [f"L {_coord_string(*i)}" for i in poly[1:-1]]
    d = f'M {start} {" ".join(middle)} Z'
    return f'<path stroke="black" stroke-width="0.1" fill="{fill}" d="{d}"/>'


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

    def __init__(self, ids: Sequence[int]) -> None:
        # Use a separate session to avoid triggering history pointlessly
        if db.Session is None:
            raise error.DatabaseError("db.Session is None")
        with db.Session() as session:
            areas = (
                session.query(Geography)
                .filter(cast(QueryableAttribute, Geography.id).in_(ids))
                .order_by(Geography.code)
            )
        codes_str = "|".join(i.code for i in areas)
        self._image_cache_key = hash(codes_str)
        self._svg_paths = (i.as_svg_paths() for i in areas)
        self._image: Gtk.Image | None = None
        self._map: str = ""

    @property
    def map(self) -> str:
        """Instance level SVG map for the supplied geographies."""
        if not self._map:
            logger.debug("generating map")
            self._map = self.world.format(selected="".join(self._svg_paths))
        return self._map

    @property
    def world(self) -> str:
        """Class level SVG map template ready to take more paths in it's
        `selected` placeholder.
        """
        if not self._world:
            self._set_base_map()
        return self._world

    @property
    def world_pixbuf(self) -> GdkPixbuf.Pixbuf:
        """Class level map as a pixbuf, use to create blank map images."""
        if not self._world_pixbuf:
            self._set_base_map()
        return cast(GdkPixbuf.Pixbuf, self._world_pixbuf)

    @classmethod
    def _set_base_map(cls) -> None:
        """Set the class level world SVG map and pixbuf once."""
        if not db.Session:
            return
        logger.debug("setting base map")
        session = db.Session()
        svg_paths = []
        for geo in session.query(Geography).filter_by(level=1):
            svg_paths.append(geo.as_svg_paths(fill="lightgrey"))
        cls._world = (
            '<svg xmlns="http://www.w3.org/2000/svg" width="360" height="180" '
            'viewBox="-180 90 360 180" transform="scale(1, -1)">'
            f'{"".join(svg_paths)}'
            "{selected}"
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


class DistMappable(Protocol):  # pylint: disable=too-few-public-methods
    def distribution_map(self) -> DistributionMap:
        """Return a DistributionMap instance"""


class DistMapInfoExpanderMixin:
    """Mixin to provide a right click menu for a DistributionMap in an
    InfoExpander.

    To use: Wrap the DistributionMap's image widget in an Gtk.EventBox and
    connect it's button_release_event to `on_map_button_release` supplying the
    current database row as user data.

    e.g. - in the infoEpander's `update` method:
            map_event_box = Gtk.EventBox()
            map_event_box.add(row.distribution_map().as_image())
            map_event_box.connect(
                "button_release_event", self.on_map_button_release, row
            )
    """

    MAP_ACTION_NAME: str = "distribution_map_activated"

    def on_map_button_release(
        self, box: Gtk.EventBox, event_btn: Gdk.EventButton, row: DistMappable
    ) -> bool:
        """On right click create menu and pop it up."""
        if event_btn.button == 3:
            logger.debug("infoexpander distribution map menu row=%s", row)
            menu = Gio.Menu()
            action_group = Gio.SimpleActionGroup()
            menu_items = (
                (_("Save"), "save", self.on_dist_map_save),
                (_("Copy"), "copy", self.on_dist_map_copy),
            )
            for label, name, handler in menu_items:
                action = Gio.SimpleAction.new(name, None)
                action.connect("activate", handler, row)
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

    @staticmethod
    def on_dist_map_save(_action, _param, row: DistMappable) -> None:
        """Save as SVG file."""
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
                f.write(str(row.distribution_map()))
        filechooser.destroy()

    @staticmethod
    def on_dist_map_copy(_action, _param, row: DistMappable) -> None:
        """Copy the pixbuf to the clipboard."""
        image = row.distribution_map().as_image()
        if bauble.gui:
            logger.debug("copying pixbuf")
            bauble.gui.get_display_clipboard().set_image(image.get_pixbuf())


class GeneralGeographyExpander(DistMapInfoExpanderMixin, InfoExpander):
    """Generic info about a geography."""

    def __init__(self, widgets):
        super().__init__(_("General"), widgets)
        general_box = self.widgets.general_box
        self.widgets.general_window.remove(general_box)
        self.vbox.pack_start(general_box, True, True, 0)
        self.table_cells = []

    def update(self, row: Geography) -> None:
        for child in self.widgets.map_box.get_children():
            self.widgets.map_box.remove(child)

        # grab shape before distribution_map to avoid thread issues for MSSQL
        # (better to use MARS_Connection=Yes when connecting)
        shape = row.geojson.get("type", "") if row.geojson else ""
        map_event_box = Gtk.EventBox()
        image = row.distribution_map().as_image()

        if parent := cast(Gtk.Container, image.get_parent()):
            parent.remove(image)

        map_event_box.add(image)
        map_event_box.connect(
            "button_release_event", self.on_map_button_release, row
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
    """
    general info
    """

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


def update_all_approx_areas_task(*_args: Any) -> Iterator[None]:
    """Task to update all the geographies approx area.

    Yields occassionally to update the progress bar
    """

    if not db.Session:
        return
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
