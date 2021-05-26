# Copyright (c) 2021 Ross Demuth <rossdemuth123@gmail.com>
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
from pathlib import Path
import sqlite3
import logging
logger = logging.getLogger(__name__)
from pyproj import Transformer, ProjError

from bauble.paths import main_is_frozen, main_dir

if main_is_frozen():
    import os
    import pyproj
    pyproj.datadir.set_data_dir(os.path.join(main_dir(), 'share', 'proj'))

# EPSG codes are easy to work with and ESRI AGOL data is generally in EPSG:3857
# recommended sys preference = EPSG:4326 - more common in GPS, KML, etc.
DEFAULT_IN_PROJ = 'epsg:3857'
"""
The default input coordinate reference system (CRS) string - used as a starting
guess for input data.
"""

DEFAULT_SYS_PROJ = 'epsg:4326'
"""
This is the default CRS used database wide internally.  This is used only once
when setting the 'system_proj_string' in the meta table on the first call.
"""


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
        from bauble.meta import confirm_default
        # system projection - saved to BaubleMeta
        # The first time any transformation is attempted ensure we have a
        # system CRS string, let the user have the opportunity to select a
        # different preference if they desire
        msg = _('Set a system wide Coordinate Reference System string, this '
                'can only be set once.\n\n"epsg:4326" is a safe default but '
                'you may have a different preference.\n\nIf using a novel '
                'CRS you may also need to to populate the internal database '
                'with a .prj file string or importing/exporting shapefile '
                'data with that CRS may fail.\n\nThis is most easily done by '
                'using the shapefile import tool and providing a shapefile in '
                'the desired CRS.')
        sys_crs = confirm_default('system_proj_string', DEFAULT_SYS_PROJ, msg)
        if sys_crs:
            out_crs = sys_crs.value
        else:
            from bauble.error import MetaTableError
            raise MetaTableError(msg='Cannot proceed without a system CRS.')
    try:
        geometry_type = geometry.get("type")
        geometry_out = geometry.copy()
    except AttributeError as e:
        logger.debug('transform recieved unusable data: %s - %s', geometry, e)
        return None
    coords = []
    transformer = Transformer.from_crs(in_crs, out_crs, always_xy=always_xy)
    try:
        if geometry_type == 'Polygon':
            for x, y in geometry.get('coordinates')[0]:
                x_out, y_out = transformer.transform(x, y, errcheck=True)
                coords.append([x_out, y_out])
            geometry_out['coordinates'] = [coords]
        elif geometry_type == 'LineString':
            for x, y in geometry.get('coordinates'):
                x_out, y_out = transformer.transform(x, y, errcheck=True)
                coords.append([x_out, y_out])
            geometry_out['coordinates'] = coords
        elif geometry_type == 'Point':
            x, y = geometry.get('coordinates')
            x_out, y_out = transformer.transform(x, y, errcheck=True)
            geometry_out['coordinates'] = [x_out, y_out]
        else:
            # avoid anything that doesn't parse
            logger.debug('transform: unsupported geometry: %s', geometry)
            return None
    except ProjError as e:
        logger.debug('transform failed for geometry: %s with error: %s',
                     geometry, e)
        return None
    return geometry_out


class ProjDB:
    """Database of settings appropriate for .prj file strings.

    Provide a very basic interface to the sqlite3 file database used to store
    pyproj.crs.CRS() parameter strings that match a .prj file string.

    Only one CRS string per .prj file string is allowed.  But you can have
    multiple .prj strings for the one CRS string.  The CRS strings should be
    acceptable pyproj.crs.CRS string parameters.
    """

    PATH = Path(__file__).resolve().parent / 'prj_crs.db'
    """
    The default directory for the database file.
    """

    def __init__(self, db_path=PATH):
        """
        :param db_path: path to the sqlite database.
        """
        # NOTE pylint won't load C extensions like connect
        self.con = sqlite3.connect(db_path)   # pylint: disable=no-member
        cur = self.con.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS proj (
                prj_text TEXT NOT NULL UNIQUE CHECK(length(prj_text) >= 12),
                proj_crs TEXT NOT NULL CHECK(length(proj_crs) >= 4),
                always_xy INTEGER
            )
            """
        )
        self.con.commit()

    def get_crs(self, prj):
        """
        Given a .prj file contents as a string return an appropriate
        pyproj.crs.CRS parameter string.  If the database doesn't have one to
        match return None.

        :param prj: string from a .prj file

        :return: the matching CRS() parameter string for prj
        """
        cur = self.con.cursor()
        crs = cur.execute('SELECT proj_crs FROM proj WHERE prj_text=?',
                          (prj,)).fetchone()
        return crs[0] if crs else None

    def get_always_xy(self, prj):
        """
        Given a .prj file contents as a string return the state of always_xy
        that was last used or True if no entry currently exists.

        :param prj: string from a .prj file

        :return: the matching CRS() parameter string for prj
        """
        cur = self.con.cursor()
        axy = cur.execute('SELECT always_xy FROM proj WHERE prj_text=?',
                          (prj,)).fetchone()
        return bool(axy[0]) if axy else True

    def get_prj(self, crs):
        """
        Given a pyproj.crs.CRS paramater string return the first .prj file
        string from the database.
        This may not always be the best choice but in most situations will
        suffice.

        :param crs: string as used with pyproj.crs.CRS()

        :return: the first matching .prj file string for the crs.
        """
        cur = self.con.cursor()
        prj = cur.execute('SELECT prj_text FROM proj WHERE proj_crs=?',
                          (crs,)).fetchone()
        return prj[0] if prj else None

    def add(self, prj=None, crs=None, axy=True):
        """
        Create a new entry in the database.  Care should be taken not to add
        junk.

        :param prj: string from a .prj file
        :param crs: as used with pyproj.crs.CRS()
        :param axy: always_xy as used with pyproj.crs.CRS()
        """
        cur = self.con.cursor()
        cur.execute(('INSERT INTO proj (prj_text, proj_crs, always_xy) VALUES '
                     '(?, ?, ?)'), (prj, crs, int(axy)))
        self.con.commit()

    def set_crs(self, prj=None, crs=None):
        """
        Set the crs database entry for the .prj file string.

        :param prj: string from a .prj file
        :param crs: string as used with pyproj.crs.CRS()
        """
        cur = self.con.cursor()
        cur.execute('UPDATE proj SET proj_crs=? WHERE prj_text=?',
                    (crs, prj))
        self.con.commit()

    def set_always_xy(self, prj=None, axy=True):
        """
        Set the always_xy database entry for the .prj file string.

        :param prj: string from a .prj file
        :param axy: always_xy parameter value as used with pyproj.crs.CRS()
        """
        cur = self.con.cursor()
        cur.execute('UPDATE proj SET always_xy=? WHERE prj_text=?',
                    (int(axy), prj))
        self.con.commit()
