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
import os
import logging
logger = logging.getLogger(__name__)

import tempfile
from mako.template import Template
from pyproj import Transformer, ProjError
from sqlalchemy import Table, Column, Text, CheckConstraint, select

import bauble
from bauble import utils
from bauble.paths import main_is_frozen, main_dir, appdata_dir
from bauble.meta import confirm_default
from bauble import db
from bauble import btypes

if main_is_frozen():
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

PRJ_CRS_PATH = os.path.join(appdata_dir(), 'prj_crs.db')
"""
The default directory for the database file.
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
        # system projection - saved to BaubleMeta
        # The first time any transformation is attempted ensure we have a
        # system CRS string, let the user have the opportunity to select a
        # different preference if they desire
        msg = _('Set a system wide Coordinate Reference System string, this '
                'can only be set once.\n\n"epsg:4326" is a safe default (WGS '
                '84 as used in GPS) but you may have a different preference.'
                '\n\nIf using a novel CRS you may also need to populate the '
                'internal database with a .prj file string or '
                'importing/exporting shapefile data with that CRS may fail.'
                '\n\nThis is most easily done by using the shapefile import '
                'tool and providing a shapefile in the desired CRS.')
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
    logger.debug('transform %s >> %s', in_crs, out_crs)
    try:
        if geometry_type == 'Polygon':
            for x, y in geometry.get('coordinates')[0]:
                coords.append([*transformer.transform(x, y, errcheck=True)])
            geometry_out['coordinates'] = [coords]
        elif geometry_type == 'LineString':
            for x, y in geometry.get('coordinates'):
                coords.append([*transformer.transform(x, y, errcheck=True)])
            geometry_out['coordinates'] = coords
        elif geometry_type == 'Point':
            x, y = geometry.get('coordinates')
            geometry_out['coordinates'] = [
                *transformer.transform(x, y, errcheck=True)
            ]
        else:
            # avoid anything that doesn't parse
            logger.debug('transform: unsupported geometry: %s', geometry)
            return None
    except ProjError as e:
        logger.debug('transform failed for geometry: %s with error: %s',
                     geometry, e)
        return None
    return geometry_out


prj_crs = Table('prj_crs',
                db.metadata,
                Column('prj_text',
                       Text,
                       CheckConstraint("length(prj_text) >= 12"),
                       nullable=False,
                       unique=True),
                Column('proj_crs',
                       Text,
                       CheckConstraint("length(proj_crs) >= 4"),
                       nullable=False),
                Column('always_xy', btypes.Boolean, default=False))


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
        # TODO check string length is > minimum (4, 12)
        stmt = prj_crs.insert().values(prj_text=prj,
                                       proj_crs=crs,
                                       always_xy=axy)
        with db.engine.begin() as conn:
            conn.execute(stmt)

    def set_crs(self, prj=None, crs=None):
        """
        Set the crs database entry for the .prj file string.

        :param prj: string from a .prj file
        :param crs: string as used with pyproj.crs.CRS()
        """
        stmt = (prj_crs.update()
                .where(prj_crs.c.prj_text == prj)
                .values(proj_crs=crs))
        with db.engine.begin() as conn:
            conn.execute(stmt)

    def set_always_xy(self, prj=None, axy=True):
        """
        Set the always_xy database entry for the .prj file string.

        :param prj: string from a .prj file
        :param axy: always_xy parameter value as used with pyproj.crs.CRS()
        """
        stmt = (prj_crs.update()
                .where(prj_crs.c.prj_text == prj)
                .values(always_xy=axy))
        with db.engine.begin() as conn:
            conn.execute(stmt)


class KMLMapCallbackFunctor:
    """Provides an action callback that can be instantiated with an appropriate
    filename for a Mako kml template to generate a kml map.
    """

    def __init__(self, filename):
        self.filename = filename

    def __call__(self, values):
        template = Template(filename=self.filename,
                            input_encoding='utf-8',
                            output_encoding='utf-8')

        count = 0
        for value in values:
            file_handle, filename = tempfile.mkstemp(suffix='.kml')

            try:
                out = template.render(value=value)
                os.write(file_handle, out)
            except ValueError as e:
                # at least provides some feedback from last failure
                if bauble.gui:
                    statusbar = bauble.gui.widgets.statusbar
                    sb_context_id = statusbar.get_context_id('show.map')
                    statusbar.pop(sb_context_id)
                    statusbar.push(sb_context_id, f"{value} - {e}")
                # NOTE log used in test
                logger.debug("%s: %s", value, e)
                continue
            finally:
                os.close(file_handle)

            count += 1
            try:
                utils.desktop.open(filename)
            except OSError:
                utils.message_dialog(
                    _('Could not open the kml file. It can be found here %s') %
                    filename
                )
                break

        if count == 0:
            utils.message_dialog(_('No map data for selected item(s).'))
