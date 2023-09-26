# pylint: disable=too-few-public-methods
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
Shapefile import export plugins
"""
import logging

logger = logging.getLogger(__name__)

from gi.repository import Gdk  # noqa
from gi.repository import Gtk

from bauble import pluginmgr

PLANT_SHAPEFILE_PREFS = "shapefile.plant"
"""Shapefile default prefs section for Plants.

Options: search_by, fields.
"""

LOCATION_SHAPEFILE_PREFS = "shapefile.location"
"""Shapefile default prefs section for Locations.

Options: search_by, fields.
"""

SHAPEFILE_IGNORE_PREF = "shapefile.ignore"
"""Pref for which field names to ignore when importing shapefiles."""


class ShapefileImportTool(pluginmgr.Tool):
    category = _("Import")
    label = _("Shapefile")

    @classmethod
    def start(cls):
        """Start the shapefile importer.

        This tool will also reinitialize the plugins after importing.
        """

        importer = ShapefileImporter()
        importer.start()
        logger.debug("ShapefileImportTool finished")
        return importer


class ShapefileExportTool(pluginmgr.Tool):
    category = _("Export")
    label = _("Shapefile")

    @classmethod
    def start(cls):
        """Start the shapefile importer.

        This tool will also reinitialize the plugins after importing.
        """

        exporter = ShapefileExporter()
        exporter.start()
        logger.debug("ShapefileExportTool finished")
        return exporter


from .export_tool import ShapefileExporter

# Avoid circular imports (LOCATION_SHAPEFILE_PREFS, PLANT_SHAPEFILE_PREFS)
from .import_tool import ShapefileImporter
