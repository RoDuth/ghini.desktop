# Copyright (c) 2021-2023 Ross Demuth <rossdemuth123@gmail.com>
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
Common helpers useful for spatial data.
"""
import logging
import os
from collections.abc import Sequence
from math import inf
from math import sqrt
from queue import PriorityQueue
from typing import Any
from typing import Self
from typing import cast

logger = logging.getLogger(__name__)

import tempfile

from mako.template import Template  # type: ignore [import-untyped]
from pyproj import ProjError
from pyproj import Transformer
from sqlalchemy import Column
from sqlalchemy import String
from sqlalchemy import Table
from sqlalchemy import select

import bauble
from bauble import btypes
from bauble import db
from bauble import utils
from bauble.error import check
from bauble.i18n import _
from bauble.meta import confirm_default
from bauble.paths import main_dir
from bauble.paths import main_is_frozen

if main_is_frozen():
    import pyproj

    pyproj.datadir.set_data_dir(os.path.join(main_dir(), "share", "proj"))

PointT = list[float]
PolygonT = list[PointT]
MultiPolyT = list[PolygonT]

# EPSG codes are easy to work with and ESRI AGOL data is generally in EPSG:3857
# recommended sys preference = EPSG:4326 - more common in GPS, KML, etc.
DEFAULT_IN_PROJ = "epsg:3857"
"""
The default input coordinate reference system (CRS) string - used as a starting
guess for input data.
"""

DEFAULT_SYS_PROJ = "epsg:4326"
"""
This is the default CRS used database wide internally.  This is used only once
when setting the 'system_proj_string' in the meta table on the first call.
"""

CRS_MSG = _(
    "Set a system wide Coordinate Reference System string, this "
    'can only be set once.\n\n"epsg:4326" is a safe default (WGS '
    "84 as used in GPS) but you may have a different preference."
    "\n\nIf using a novel CRS you may also need to populate the "
    "internal database with a .prj file string or "
    "importing/exporting shapefile data with that CRS may fail."
    "\n\nThis is most easily done by using the shapefile import "
    "tool and providing a shapefile in the desired CRS."
)


# pylint: disable=too-many-locals
def transform(geometry, in_crs=DEFAULT_IN_PROJ, out_crs=None, always_xy=False):
    """Transform coordinates from one projection coordinate system to another.

    A wrapper for pyproj.Transformer that when given a geojson simple geometry
    entry of type LineString, Point or Polygon (simple) can be used to
    transform the coordinates from one projection coordinate system to another.

    :param geometry: a geojson geometry (polygon, linestring, point).
    :param in_crs: string parameter as accepted by pyproj.crs.CRS() for the
        input.
    :param out_crs: string parameter as accepted by pyproj.crs.CRS() for the
        desired output.
    :always_xy: bool parameter used by pyproj.Transformer() to enforce standard
        GIS long, lat output.
    :return:
        dict copy of the original geometry data with coordinates reprojected.
        None if doesn't parse or errors.
    """

    if out_crs is None:
        # system projection - saved to BaubleMeta
        # The first time any transformation is attempted ensure we have a
        # system CRS string, let the user have the opportunity to select a
        # different preference if they desire
        sys_crs = confirm_default(
            "system_proj_string", DEFAULT_SYS_PROJ, CRS_MSG
        )
        if sys_crs:
            out_crs = sys_crs.value
        else:
            from bauble.error import MetaTableError

            raise MetaTableError(msg="Cannot proceed without a system CRS.")
    try:
        geometry_type = geometry.get("type")
        geometry_out = geometry.copy()
    except AttributeError as e:
        logger.debug("transform recieved unusable data: %s - %s", geometry, e)
        return None
    coords = []
    transformer = Transformer.from_crs(in_crs, out_crs, always_xy=always_xy)
    logger.debug("transform %s >> %s", in_crs, out_crs)
    try:
        if geometry_type == "Polygon":
            for x, y in geometry.get("coordinates")[0]:
                coords.append([*transformer.transform(x, y, errcheck=True)])
            geometry_out["coordinates"] = [coords]
        elif geometry_type == "LineString":
            for x, y in geometry.get("coordinates"):
                coords.append([*transformer.transform(x, y, errcheck=True)])
            geometry_out["coordinates"] = coords
        elif geometry_type == "Point":
            x, y = geometry.get("coordinates")
            geometry_out["coordinates"] = [
                *transformer.transform(x, y, errcheck=True)
            ]
        else:
            # avoid anything that doesn't parse
            logger.debug("transform: unsupported geometry: %s", geometry)
            return None
    except ProjError as e:
        logger.debug(
            "transform failed for geometry: %s with error: %s", geometry, e
        )
        return None
    return geometry_out


prj_crs = Table(
    "prj_crs",
    db.metadata,
    Column("prj_text", String(length=2048), nullable=False, unique=True),
    Column("proj_crs", String(length=64), nullable=False),
    Column("always_xy", btypes.Boolean, default=False),
)


def install_default_prjs():
    from bauble.paths import lib_dir
    from bauble.plugins.imex.csv_ import CSVRestore

    # prj_crs.drop(bind=db.engine, checkfirst=True)
    prj_crs.drop(bind=db.engine)
    path = os.path.join(lib_dir(), "utils", "prj_crs.csv")
    csv = CSVRestore()
    csv.start([path], metadata=db.metadata, force=True)


class ProjDB:
    """Database of settings appropriate for .prj file strings.

    Provide a very basic interface to the prj_crs table to store
    pyproj.crs.CRS() parameter strings that match a .prj file string.

    Only one CRS string per .prj file string is allowed.  But you can have
    multiple .prj strings for the one CRS string.  The CRS strings should be
    acceptable pyproj.crs.CRS string parameters.
    """

    def get_crs(self, prj):
        """
        Given a .prj file contents as a string return an appropriate
        pyproj.crs.CRS parameter string.  If the database doesn't have one to
        match return None.

        :param prj: string from a .prj file

        :return: the matching CRS() parameter string for prj
        """
        stmt = select(prj_crs.c.proj_crs).where(prj_crs.c.prj_text == prj)
        with db.engine.begin() as conn:
            return conn.execute(stmt).scalar()

    def get_always_xy(self, prj):
        """
        Given a .prj file contents as a string return the state of always_xy
        that was last used or True if no entry currently exists.

        :param prj: string from a .prj file

        :return: the matching CRS() parameter string for prj
        """
        stmt = select(prj_crs.c.always_xy).where(prj_crs.c.prj_text == prj)
        with db.engine.begin() as conn:
            result = conn.execute(stmt).scalar()
        return True if result is None else result

    def get_prj(self, crs):
        """
        Given a pyproj.crs.CRS parameter string return the first .prj file
        string from the database.
        This may not always be the best choice but in most situations will
        suffice.

        :param crs: string as used with pyproj.crs.CRS()

        :return: the first matching .prj file string for the crs.
        """
        stmt = select(prj_crs.c.prj_text).where(prj_crs.c.proj_crs == crs)
        with db.engine.begin() as conn:
            return conn.execute(stmt).scalar()

    def add(self, prj=None, crs=None, axy=True):
        """
        Create a new entry in the database.  Care should be taken not to add
        junk.

        :param prj: string from a .prj file
        :param crs: as used with pyproj.crs.CRS()
        :param axy: always_xy as used with pyproj.crs.CRS()
        """
        check(prj is not None, "prj is None")
        check(crs is not None, "crs is None")
        check(len(prj) >= 12, "prj string too short")
        check(len(crs) >= 4, "crs string too short")
        stmt = prj_crs.insert().values(
            prj_text=prj, proj_crs=crs, always_xy=axy
        )
        with db.engine.begin() as conn:
            conn.execute(stmt)

    def set_crs(self, prj=None, crs=None):
        """
        Set the crs database entry for the .prj file string.

        :param prj: string from a .prj file
        :param crs: string as used with pyproj.crs.CRS()
        """
        stmt = (
            prj_crs.update()
            .where(prj_crs.c.prj_text == prj)
            .values(proj_crs=crs)
        )
        with db.engine.begin() as conn:
            conn.execute(stmt)

    def set_always_xy(self, prj=None, axy=True):
        """
        Set the always_xy database entry for the .prj file string.

        :param prj: string from a .prj file
        :param axy: always_xy parameter value as used with pyproj.crs.CRS()
        """
        stmt = (
            prj_crs.update()
            .where(prj_crs.c.prj_text == prj)
            .values(always_xy=axy)
        )
        with db.engine.begin() as conn:
            conn.execute(stmt)


class KMLMapCallbackFunctor:  # pylint: disable=too-few-public-methods
    """Provides an action callback that can be instantiated with an appropriate
    filename for a Mako kml template to generate a kml map.
    """

    def __init__(self, filename: str) -> None:
        self.filename = filename

    def __call__(self, objs: Sequence[db.Domain], **kwargs: Any) -> bool:
        template = Template(
            filename=self.filename,
            input_encoding="utf-8",
            output_encoding="utf-8",
        )

        count = 0
        for obj in objs:
            file_handle, filename = tempfile.mkstemp(suffix=".kml")

            try:
                out = template.render(value=obj)
                os.write(file_handle, out)
            except ValueError as e:
                # at least provides some feedback from last failure
                if bauble.gui:
                    statusbar = bauble.gui.widgets.statusbar
                    sb_context_id = statusbar.get_context_id("show.map")
                    statusbar.pop(sb_context_id)
                    statusbar.push(sb_context_id, f"{obj} - {e}")
                # NOTE log used in test
                logger.debug("%s: %s", obj, e)
                continue
            finally:
                os.close(file_handle)

            count += 1
            try:
                utils.desktop.open(filename)
            except OSError:
                utils.message_dialog(
                    _("Could not open the kml file. It can be found here %s")
                    % filename
                )
                break

        if count == 0:
            utils.message_dialog(_("No map data for selected item(s)."))

        return False


def kml_string_to_geojson(string: str) -> str:
    """Accepts kml strings as copied from google earth etc. and returns
    it as a geojson geometry string.

    Assumes the system datum.
    """
    from lxml import etree

    try:
        kml = etree.fromstring(string.encode("utf-8"))
        namespaces = {k: v for k, v in kml.nsmap.items() if k}
    except etree.XMLSyntaxError:
        return string
    poly = (
        "/kml:kml//kml:Placemark/kml:Polygon/kml:outerBoundaryIs/"
        "kml:LinearRing/kml:coordinates/text()"
    )
    line = "/kml:kml//kml:Placemark/kml:LineString/kml:coordinates/text()"
    point = "/kml:kml//kml:Placemark/kml:Point/kml:coordinates/text()"

    if coords := cast(list[str], kml.xpath(poly, namespaces=namespaces)):
        result = '{"type": "Polygon", "coordinates": [['
        for val in coords[0].split():
            val = val.rsplit(",", 1)[0]
            result += f"[{val.replace(',', ', ')}], "
        result = result[:-2] + "]]}"
        return result
    if coords := cast(list[str], kml.xpath(line, namespaces=namespaces)):
        result = '{"type": "LineString", "coordinates": ['
        for val in coords[0].split():
            val = val.rsplit(",", 1)[0]
            result += f"[{val.replace(',', ', ')}], "
        result = result[:-2] + "]}"
        return result
    if coords := cast(list[str], kml.xpath(point, namespaces=namespaces)):
        result = '{"type": "Point", "coordinates": ['
        result += coords[0].rsplit(",", 1)[0].replace(",", ", ")
        result += "]}"
        return result
    return string


def web_mercator_point_coords_to_geojson(string: str) -> str:
    """Accepts point string coordinates as copied from google maps etc. and
    returns it as geojson geometry string.

    Assumes the system datum.
    """
    x, y = string.split(", ")
    return f'{{"type": "Point", "coordinates": [{y}, {x}]}}'


def is_point_within_poly(
    long: float, lat: float, poly: PolygonT | MultiPolyT
) -> bool:
    """Check if the point falls within the provided polygon coordinates.

    Known limitations:
    Does not account for limited float precision (edges).
    Does not account for complex polygons (crossing).
    Does not account for clockwise coordinates (holes).
    """
    if isinstance(poly[0][0], (int, float)):
        return is_point_within_poly(long, lat, [cast(PolygonT, poly)])

    inside = False
    for polygon in cast(MultiPolyT, poly):
        previous = polygon[0]
        for point in polygon[1:]:
            if ray_intersects(long, lat, previous, point):
                inside = not inside
            previous = point
    return inside


def ray_intersects(
    long: float,
    lat: float,
    previous: list[float],
    point: list[float],
) -> bool:
    """Simple ray casting,

    Given a point described by :param lat: and :param long: and a polygon
    segment described by :param previous: and :param point: return `True` if
    the horizontal ray from the point intersects the segment, `False`
    otherwise.
    """
    # https://wrfranklin.org/Research/Short_Notes/pnpoly.html
    return (point[1] > lat) != (previous[1] > lat) and (
        long
        < (previous[0] - point[0])
        * (lat - point[1])
        / (previous[1] - point[1])
        + point[0]
    )


# polylabel see: https://github.com/Twista/python-polylabel


def _point_to_polygon_distance(
    x: float, y: float, polygon: MultiPolyT
) -> float:
    inside = False
    min_dist_sq = inf

    for poly in polygon:
        previous = poly[-1]
        for point in poly:
            if ray_intersects(x, y, previous, point):
                inside = not inside

            min_dist_sq = min(
                min_dist_sq, _get_seg_dist_sq(x, y, previous, point)
            )
            previous = point

    result = sqrt(min_dist_sq)
    if inside:
        return result
    return -result


def _get_seg_dist_sq(
    x: float, y: float, previous: PointT, point: PointT
) -> float:
    """Given a point described by :param x: and :param y: and a polygon
    segment described by :param previous: and :param point: return the the
    distance between point the nearest point on the line squared.
    """
    # nearest values will end up being one end of the line or some point along
    # it, whichever is closest to the point described by x, y.
    nearest_x = previous[0]
    nearest_y = previous[1]
    dif_x = point[0] - previous[0]
    dif_y = point[1] - previous[1]

    if dif_x != 0 or dif_y != 0:
        # Linear interpolation:
        # `nearest` = `previous` if t < 0, `point` if t > 1 somewhere between
        # for values between 0 to 1.
        t = ((x - previous[0]) * dif_x + (y - previous[1]) * dif_y) / (
            dif_x**2 + dif_y**2
        )

        if t > 1:
            nearest_x = point[0]
            nearest_y = point[1]

        elif t > 0:
            nearest_x += dif_x * t
            nearest_y += dif_y * t

    diff_x = x - nearest_x
    diff_y = y - nearest_y

    return diff_x**2 + diff_y**2


class Cell:
    def __init__(
        self, x: float, y: float, half: float, polygon: MultiPolyT
    ) -> None:
        self.x = x
        self.y = y
        self.half = half
        self.distance = _point_to_polygon_distance(x, y, polygon)
        self.max_distance = self.distance + self.half * 1.41421356  # ~sqrt(2)

    def __lt__(self, other: Self) -> bool:
        return self.max_distance < other.max_distance


def _get_centroid_cell(polygon: MultiPolyT) -> Cell:
    signed_area: float = 0
    x: float = 0
    y: float = 0
    points = polygon[0]
    previous = points[-1]
    for point in points:
        # shoelace formula
        area = point[0] * previous[1] - previous[0] * point[1]
        x += (point[0] + previous[0]) * area
        y += (point[1] + previous[1]) * area
        signed_area += area * 3
        previous = point
    if signed_area == 0:
        return Cell(points[0][0], points[0][1], 0, polygon)
    return Cell(x / signed_area, y / signed_area, 0, polygon)


def polylabel(polygon: MultiPolyT, precision: float = 1.0) -> PointT:
    # find bounding box
    min_x, min_y = polygon[0][0]
    max_x, max_y = polygon[0][0]

    for point in polygon[0][1:]:
        if point[0] < min_x:
            min_x = point[0]
        if point[1] < min_y:
            min_y = point[1]
        if point[0] > max_x:
            max_x = point[0]
        if point[1] > max_y:
            max_y = point[1]

    width = max_x - min_x
    height = max_y - min_y
    cell_size = width if width < height else height
    half = cell_size / 2.0

    cell_queue: PriorityQueue[Cell] = PriorityQueue()

    if cell_size == 0:
        return [min_x, min_y]

    # cover polygon with initial cells
    x = min_x
    while x < max_x:
        y = min_y
        while y < max_y:
            cell_queue.put(Cell(x + half, y + half, half, polygon))
            y += cell_size
        x += cell_size

    best_cell = _get_centroid_cell(polygon)

    bbox_cell = Cell(min_x + width / 2, min_y + height / 2, 0, polygon)
    if bbox_cell.distance > best_cell.distance:
        best_cell = bbox_cell

    num_of_probes = cell_queue.qsize()
    while not cell_queue.empty():
        cell = cell_queue.get()

        if cell.distance > best_cell.distance:
            best_cell = cell

            logger.debug(
                "found best %s after %s probes",
                round(1e4 * cell.distance) / 1e4,
                num_of_probes,
            )

        if cell.max_distance - best_cell.distance <= precision:
            continue

        half = cell.half / 2
        cell_queue.put(Cell(cell.x - half, cell.y - half, half, polygon))
        cell_queue.put(Cell(cell.x + half, cell.y - half, half, polygon))
        cell_queue.put(Cell(cell.x - half, cell.y + half, half, polygon))
        cell_queue.put(Cell(cell.x + half, cell.y + half, half, polygon))
        num_of_probes += 4

    logger.debug("num probes: %s", num_of_probes)
    logger.debug("best distance: %s", best_cell.distance)
    return [best_cell.x, best_cell.y]
