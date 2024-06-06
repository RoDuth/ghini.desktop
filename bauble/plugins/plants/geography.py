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
from collections.abc import Iterable
from operator import itemgetter
from pathlib import Path

logger = logging.getLogger(__name__)

from gi.repository import Gio
from gi.repository import GLib
from gi.repository import Gtk
from pyproj import Geod
from sqlalchemy import Column
from sqlalchemy import ForeignKey
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy import Unicode
from sqlalchemy import exists
from sqlalchemy import literal
from sqlalchemy import select
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import aliased
from sqlalchemy.orm import backref
from sqlalchemy.orm import deferred
from sqlalchemy.orm import object_session
from sqlalchemy.orm import relationship

from bauble import btypes as types
from bauble import db
from bauble import prefs
from bauble import utils
from bauble.i18n import _
from bauble.utils.geo import KMLMapCallbackFunctor
from bauble.view import Action
from bauble.view import InfoBox
from bauble.view import InfoExpander
from bauble.view import PropertiesExpander
from bauble.view import select_in_search_results

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
        ValueError("geography is not in a session")

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

        *tdwg_code*:

        *tdwg_level*

        *iso_code*:

        *parent_id*:

        *geojson*

    :Properties:
        *children*:

    :Constraints:
    """

    __tablename__ = "geography"

    # columns
    name = Column(Unicode(255), nullable=False)
    tdwg_code = Column(String(6))
    tdwg_level = Column(Integer, nullable=False, autoincrement=False)
    iso_code = Column(String(7))
    geojson = deferred(Column(types.JSON()))
    # don't use, can lead to InvalidRequestError (Collection unknown)
    # collection = relationship('Collection', back_populates='region')
    distribution = relationship(
        "SpeciesDistribution", back_populates="geography"
    )

    retrieve_cols = ["id", "tdwg_code"]
    parent_id = Column(Integer, ForeignKey("geography.id"))
    children = relationship(
        "Geography",
        cascade="all",
        backref=backref("parent", remote_side="Geography.id"),
        order_by=[name],
    )

    @classmethod
    def retrieve(cls, session, keys):
        parts = {k: v for k, v in keys.items() if k in cls.retrieve_cols}

        if parts:
            return session.query(cls).filter_by(**parts).one_or_none()
        return None

    def __str__(self):
        return str(self.name)

    def get_parent_ids(self) -> set[int]:
        session = object_session(self)
        cte = (
            session.query(Geography.parent_id)
            .filter(Geography.id == self.id)
            .cte(recursive=True)
        )
        child = aliased(cte)
        query = session.query(Geography.parent_id).join(
            child, Geography.id == child.c.parent_id
        )
        query = cte.union_all(query)
        query = session.query(Geography.id).join(
            query, Geography.id == query.c.parent_id
        )
        ids = {i[0] for i in query}
        return ids

    def get_children_ids(self) -> set[int]:
        session = object_session(self)
        cte = (
            session.query(Geography.id)
            .filter(Geography.id == self.id)
            .cte(recursive=True)
        )
        parent = aliased(cte)
        query = cte.union_all(
            session.query(Geography.id).join(
                parent, Geography.parent_id == parent.c.id
            )
        )
        query = session.query(Geography.id).join(
            query, Geography.parent_id == query.c.id
        )
        ids = {i[0] for i in query}
        return ids

    def has_children(self) -> bool:
        """Has this geography or any of it children or parents got a
        SpeciesDistribution
        """
        from .species_model import SpeciesDistribution

        session = object_session(self)
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

        session = object_session(self)
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

    @hybrid_property
    def approx_area(self) -> float:
        """The area in square kilometres using a WGS84 sphere"""
        if not self.geojson:
            return 0.0
        total = 0.0
        if self.geojson["type"] == "MultiPolygon":
            for poly in self.geojson["coordinates"]:
                lons = []
                lats = []
                for lon, lat in poly[0]:
                    lons.append(lon)
                    lats.append(lat)
                area, __ = geod.polygon_area_perimeter(lons, lats)
                total += area
        elif self.geojson["type"] == "Polygon":
            lons = []
            lats = []
            for lon, lat in self.geojson["coordinates"][0]:
                lons.append(lon)
                lats.append(lat)
            area, __ = geod.polygon_area_perimeter(lons, lats)
            total += area
        return abs(total) / 1e6


class GeneralGeographyExpander(InfoExpander):
    """Generic minimalist info about a geography."""

    def __init__(self, widgets):
        super().__init__(_("General"), widgets)
        general_box = self.widgets.general_box
        self.widgets.general_window.remove(general_box)
        self.vbox.pack_start(general_box, True, True, 0)
        self.table_cells = []

    def update(self, row):
        on_clicked = utils.generate_on_clicked(select_in_search_results)
        level = ["Continent", "Region", "Area", "Unit"][row.tdwg_level - 1]
        self.widget_set_value("name_label", row.name)
        self.widget_set_value("tdwg_level", level)
        self.widget_set_value("tdwg_code", row.tdwg_code)
        self.widget_set_value("iso_code", row.iso_code)
        self.widget_set_value("parent", row.parent or "")
        shape = row.geojson.get("type", "") if row.geojson else ""
        self.widget_set_value("geojson_type", shape)
        self.widget_set_value("approx_size", f"{row.approx_area:.2f} km²")
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


def consolidate_geographies(geo_list: Iterable[Geography]) -> list:
    """Given a list of geographies, if all child members of a parent exist
    recursively replace the children with the parent.
    """
    parents = set()
    for geo in geo_list:
        parents.add(geo.parent)

    result = set()
    for geo in parents:
        if geo:
            if all(i in geo_list for i in geo.children):
                result.add(geo)

    for geo in geo_list:
        parent_ids = geo.get_parent_ids()
        if all(i.id not in parent_ids for i in result):
            result.add(geo)

    if geo_list == result:
        return list(result)
    return consolidate_geographies(result)
