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
Shapefile Import Output plugins
"""
import logging
logger = logging.getLogger(__name__)

from gi.repository import Gtk, Gdk  # noqa

from bauble import pluginmgr
from bauble.plugins.imex.shapefile.import_tool import ShapefileImporter
from bauble.plugins.imex.shapefile.export_tool import ShapefileExporter

from bauble.prefs import prefs, debug_logging_prefs, testing
if not testing and __name__ in prefs.get(debug_logging_prefs, []):
    logger.setLevel(logging.DEBUG)
logger.setLevel(logging.DEBUG)

# TODO <RD> this is just a temp approach should do this more globally
_css = Gtk.CssProvider()
_css.load_from_data(
    b'.err-btn * {color: #FF9999;}'
)
Gtk.StyleContext.add_provider_for_screen(
    Gdk.Screen.get_default(), _css,
    Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)


class ShapefileImportTool(pluginmgr.Tool):

    category = _('Import')
    label = _('shapefile')

    @classmethod
    def start(cls):
        """
        Start the shapefile importer.  This tool will also reinitialize the
        plugins after importing.
        """

        importer = ShapefileImporter()
        importer.start()
        logger.debug('ShapefileImportTool finished')
        # bauble.command_handler('home', None)
        return importer


class ShapefileExportTool(pluginmgr.Tool):

    category = _('Export')
    label = _('shapefile')

    @classmethod
    def start(cls):
        """
        Start the shapefile importer.  This tool will also reinitialize the
        plugins after importing.
        """

        exporter = ShapefileExporter()
        exporter.start()
        logger.debug('ShapefileExportTool finished')
        return exporter