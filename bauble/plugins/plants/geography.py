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

logger = logging.getLogger(__name__)

from collections.abc import Iterable
from collections.abc import Sequence
from dataclasses import dataclass
from dataclasses import field
from typing import TYPE_CHECKING
from typing import Self
from typing import cast

from sqlalchemy import Column
from sqlalchemy import Float
from sqlalchemy import ForeignKey
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy import Unicode
from sqlalchemy import case
from sqlalchemy import cast as cast_sql
from sqlalchemy import event
from sqlalchemy import exists
from sqlalchemy import literal
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm import aliased
from sqlalchemy.orm import backref
from sqlalchemy.orm import deferred
from sqlalchemy.orm import object_session
from sqlalchemy.orm import relationship

from bauble import btypes as types
from bauble import db
from bauble import prefs
from bauble.utils.geo import GEOJSONMultiPoly
from bauble.utils.geo import GEOJSONPoly
from bauble.utils.geo import get_approx_area_from_geojson_sqm

if TYPE_CHECKING:
    from . import SpeciesDistribution


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
        self,
        fill: str = "green",
        pacific_centric: bool = False,
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

    def get_geography_ids(self) -> list[int] | None:

        logger.debug("get_geography_ids %s", self)
        # avoid loading deferred geojson unnecessarily, MSSQL requires cast
        with db.engine.begin() as connection:
            geojson = connection.execute(
                select(
                    cast_sql(
                        case([(Geography.geojson.is_not(None), 1)], else_=0),
                        types.Boolean,
                    )
                ).where(Geography.id == self.id)
            ).scalar()

        if geojson:
            return [self.id]

        return None


def _coord_string(lon: float, lat: float, pacific_centric: bool) -> str:
    """Convert WGS84 coordinates to SVG point strings."""
    if pacific_centric:
        return f"{round(lon + 360, 3)} {round(lat, 3)}"
    return f"{round(lon, 3)} {round(lat, 3)}"


# NOTE tuple may not be correct, could be a list but will always be 2 values
def _path_string(
    poly: Sequence[tuple[float, float]],
    fill: str,
    pacific_centric: bool,
) -> str:
    """Convert a WGS84 polygon to a SVG path string.

    :param fill: fill colour value for the polygon
    :param pacific_centric: if True longitudes are shifted east by 360degs
    """
    start = _coord_string(*poly[0], pacific_centric)
    middle = [f"L {_coord_string(*i, pacific_centric)}" for i in poly[1:-1]]
    d = f'M {start} {" ".join(middle)} Z'
    return f'<path stroke="{fill}" stroke-width="0.2" fill="{fill}" d="{d}"/>'


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
