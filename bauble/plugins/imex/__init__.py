# Copyright 2007 Brett Adams
# Copyright 2015 Mario Frasca <mario@anche.no>.
# Copyright 2021 Ross Demuth <rossdemuth123@gmail.com>
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
#
# imex plugin
#
# Description: plugin to provide importing and exporting
#

# TODO: would be best to provide some intermediate format so that we could
# transform from any format to another

import logging
logger = logging.getLogger(__name__)

from bauble import db, pluginmgr

# TODO: it might be best to do something like the reporter plugin so
# that this plugin provides a generic interface for importing and exporting
# and let the different tools provide the settings which are then passed to
# their start() methods

# see http://www.postgresql.org/docs/current/static/sql-copy.html

# NOTE: always beware when writing an imex plugin not to use the
# table.insert().execute(*list) statement or it will fill in values for
# missing columns so that all columns will have some value


def add_rec_to_db(session, item, rec):
    """Add or update the item record in the database including any related
    records.

    A convenience function for imex plugins.

    :param session: instance of db.Session()
    :param item: an instance of a sqlalchemy table
    :param rec: dict of the records to add, ordered so that related records
        are first so that they are found, created, or updated first.  Keys are
        paths from the item class to either fields of that class or to related
        tables.  Values are item columns values or the related table columns
        and values as a nested dict.
        e.g.:
        {'accession.species.genus.family': {'epithet': 'Alliaceae'},
         'accession.species.genus': {'epithet': 'Agapanthus'}, ...}
    """
    # peel of the first record to work on
    first, *remainder = rec.items()
    remainder = dict(remainder)
    key, value = first
    logger.debug('adding key: %s with value: %s', key, value)
    # related records
    if isinstance(value, dict):
        # after this "value" will be in the session
        # Try convert values to the correct type
        model = db.get_related_class(type(item), key)
        for k, v in value.items():
            if v is not None and not hasattr(v, '__table__'):
                try:
                    path_type = getattr(model, k).type
                    v = path_type.python_type(v)
                except Exception as e:   # pylint: disable=broad-except
                    logger.debug('convert type %s (%s)', type(e).__name__, e)
                    # for anything that doesn't have an obvious python_type a
                    # string SHOULD generally work
                    v = str(v)
                value[k] = v

        value = db.get_create_or_update(session, model, **value)
        root, atr = key.rsplit('.', 1) if '.' in key else (None, key)
        # _default_vernacular_name is blocked in relation_filter
        # NOTE default vernacular names need to be added directly as they use
        # their own methods,
        # Below accepts
        # 'accession.species._default_vernacular_name.vernacular_name.name'
        # which at this point would be:
        # root = 'accession.species._default_vernacular_name'
        # atr = 'vernacular_name'
        #  - depending on what we get back from
        #  get_create_or_update(session, VernacularName, name=... )
        # value = VernacularName(...)
        # and changes it to
        # root = 'accession.species'
        # atr = 'default_vernacular_name'
        # value = VernacularName(...)
        # This will generally work but is not fool proof.  It is preferable to
        # use the hybrid_property default_vernacular_name
        if (root and root.endswith('._default_vernacular_name') and
                atr == 'vernacular_name'):
            root = root.removesuffix('._default_vernacular_name')
            atr = 'default_vernacular_name'
        if remainder.get(root):
            remainder[root][atr] = value
        # source, contact etc. with a linking 1-1 table
        elif root and '.' in root and remainder.get(root.rsplit('.', 1)[0]):
            link, atr2 = root.rsplit('.', 1)
            from operator import attrgetter
            try:
                link_item = attrgetter(root)(item)    # existing entries
            except AttributeError:
                link_item = db.get_related_class(type(item), root)()
                session.add(link_item)
            if link_item:
                setattr(link_item, atr, value)
                logger.debug('adding: %s to %s', atr2, link)
                remainder[link][atr2] = link_item
    elif value is not None and not hasattr(value, '__table__'):
        try:
            model = type(item)
            path_type = getattr(model, key).type
            value = path_type.python_type(value)
        except Exception as e:
            logger.debug('convert type for value %s (%s)', type(e).__name__, e)
            # for anything that doesn't have an obvious python_type a
            # string SHOULD generally work
            value = str(value)

    # if there are more records continue to add them
    if len(remainder) > 0:
        add_rec_to_db(session, item, remainder)

    # once all records are accounted for add them to item in reverse
    logger.debug('setattr on object: %s with name: %s and value: %s',
                 item, key, value)
    setattr(item, key, value)
    return item


class ImexPlugin(pluginmgr.Plugin):
    # avoid cicular imports
    from .csv_ import (CSVRestoreTool,
                       CSVBackupTool,
                       CSVBackupCommandHandler,
                       CSVRestoreCommandHandler)
    from .csv_io import CSVExportTool
    from .iojson import JSONImportTool, JSONExportTool
    from .xml import XMLExportTool, XMLExportCommandHandler
    from .shapefile import (ShapefileImportTool,
                            ShapefileExportTool)
    tools = [CSVRestoreTool,
             CSVBackupTool,
             CSVExportTool,
             JSONImportTool,
             JSONExportTool,
             XMLExportTool,
             ShapefileImportTool,
             ShapefileExportTool]
    commands = [CSVBackupCommandHandler,
                CSVRestoreCommandHandler,
                XMLExportCommandHandler]


plugin = ImexPlugin
