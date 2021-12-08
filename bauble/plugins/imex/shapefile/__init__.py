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

from gi.repository import Gtk, Gdk  # noqa

from bauble import pluginmgr
from .import_tool import ShapefileImporter
from .export_tool import ShapefileExporter


class ShapefileImportTool(pluginmgr.Tool):

    category = _('Import')
    label = _('shapefile')

    @classmethod
    def start(cls):
        """Start the shapefile importer.

        This tool will also reinitialize the plugins after importing.
        """

        importer = ShapefileImporter()
        importer.start()
        logger.debug('ShapefileImportTool finished')
        return importer


class ShapefileExportTool(pluginmgr.Tool):

    category = _('Export')
    label = _('shapefile')

    @classmethod
    def start(cls):
        """Start the shapefile importer.

        This tool will also reinitialize the plugins after importing.
        """

        exporter = ShapefileExporter()
        exporter.start()
        logger.debug('ShapefileExportTool finished')
        return exporter
