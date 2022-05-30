# Copyright 2008-2010 Brett Adams
# Copyright 2012-2015 Mario Frasca <mario@anche.no>.
# Copyright 2017 Jardín Botánico de Quito
# Copyright 2018-2022 Ross Demuth <rossdemuth123@gmail.com>
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
# csv import/export
#
# Description: have to name this module csv_ in order to avoid conflict
# with the system csv module
#

import os
import csv
import traceback
import tempfile
from pathlib import Path

import logging
logger = logging.getLogger(__name__)

from gi.repository import Gtk  # noqa

from sqlalchemy import ColumnDefault, func, select

import bauble
from bauble import db
from bauble import utils
from bauble import pluginmgr
import bauble.task
from bauble import pb_set_fraction

# TODO: i've also had a problem with bad insert statements, e.g. importing a
# geography table after creating a new database and it doesn't use the
# 'name' column in the insert so there is an error, if  you then import the
# same table immediately after then everything seems to work fine

# TODO: should check that if we're dropping a table because of a
# dependency that we expect that data to be imported in this same
# task, or at least let the user know that the table is empty

# TODO: don't ask if we want to drop empty tables
# https://bugs.launchpad.net/bauble/+bug/103923

# required for geojson fields in geography (NORTHERN AMERICA)
csv.field_size_limit(1000000)

QUOTE_STYLE = csv.QUOTE_MINIMAL
QUOTE_CHAR = '"'


class UnicodeReader:

    def __init__(self, f, dialect=csv.excel, **kwargs):
        self.reader = csv.DictReader(f, dialect=dialect, **kwargs)

    def __next__(self):
        row = next(self.reader)
        line = {}
        for k, v in row.items():
            if v == '':
                line[k] = None
            else:
                line[k] = str(v)

        return line

    def __iter__(self):
        return self


class UnicodeWriter:

    def __init__(self, f, dialect=csv.excel, encoding="utf-8", **kwargs):
        self.writer = csv.writer(f, dialect=dialect, **kwargs)
        self.encoding = encoding

    def writerow(self, row):
        """
        Write a row.  If row is a dict then row.values() is written
        and therefore care should be taken to ensure that row.values()
        returns a consistent order.
        """
        if isinstance(row, dict):
            row = list(row.values())
        line = []
        for v in row:
            if v is None:
                line.append(None)
            else:
                line.append(str(v))
        self.writer.writerow(line)

    def writerows(self, rows):
        for row in rows:
            self.writerow(row)


class CSVRestore:
    """imports comma separated value files into a Ghini database.

    It imports multiple files, each of them equally named as the bauble
    database tables. The bauble tables dependency graph defines the correct
    import order, each file being imported will completely replace any
    existing data in the corresponding table.

    The CSVRestore imports the rows of the CSV file in chunks rather than
    one row at a time.  The non-server side column defaults are determined
    before the INSERT statement is generated instead of getting new defaults
    for each row.  This shouldn't be a problem but it also means that your
    column default should change depending on the value of previously
    inserted rows.
    """

    def __init__(self):
        super().__init__()
        self.translator = {}
        self.__error = False   # flag to indicate error on import
        self.__cancel = False  # flag to cancel importing
        self.__pause = False   # flag to pause importing

    def start(self, filenames=None, metadata=None, force=False):
        """start the import process.

        this is a non blocking method: we queue the process as a bauble task.
        there is no callback informing whether it is successfully completed or
        not.
        """
        if metadata is None:
            metadata = db.metadata  # use the default metadata

        if filenames is None:
            filenames = self._get_filenames()
        if filenames is None:
            return

        bauble_meta = [i for i in filenames if i.endswith('bauble.txt')]
        geography = [i for i in filenames if i.endswith('geography.txt')]

        if bauble_meta and geography and not force:
            with open(bauble_meta[0], 'r', encoding='utf-8', newline='') as f:
                in_file = csv.DictReader(f)
                version = None
                for line in in_file:
                    if line.get('name') == 'version':
                        version = line.get('value')
                        logger.debug('importing version %s data', version)
                        break

                if version < '1.3.0-b':
                    msg = _('You are importing data from a version prior '
                            'to v1.3.0-b?\n\nSveral tables have changed '
                            '\n\nWould you like to transform your data to '
                            'match the new version? \n\nCopies of the '
                            'original files will be saved with an appended '
                            '"_ORIG_"')
                    response = utils.yes_no_dialog(msg)
                    if response:
                        change_lst = [i for i in filenames if
                                      i.endswith('species_distribution.txt') or
                                      i.endswith('collection.txt')]
                        filenames.remove(geography[0])
                        bauble.task.queue(
                            self.set_geo_translator(geography[0]))
                        bauble.task.queue(
                            self.geo_upgrader(change_lst))
                        bauble.task.queue(self.acc_upgrader(filenames))
                        bauble.task.queue(self.changes_upgrader(filenames))

        bauble.task.queue(self.run(filenames, metadata, force))

    def acc_upgrader(self, filenames):
        """Upgrade accession file"""
        accession_file = [i for i in filenames if i.endswith('accession.txt')]

        # bail early
        if not accession_file:
            return

        depr_wild_prov = ['Impound',
                          'Collection',
                          'Rescue',
                          'InsufficientData',
                          'Unknown']

        depr_prov_type = ['Purchase', 'Unknown']

        accession_file = accession_file[0]
        original = accession_file + '_ORIG_'

        msg = _('removing deprecated provenance entries: ')
        logger.debug('upgrading %s', accession_file)
        bauble.task.set_message(msg + accession_file)

        with open(accession_file, 'r', encoding='utf-8', newline='') as f:
            num_lines = len(f.readlines())

        if num_lines <= 1:
            logger.debug('%s contains no table data skip translation',
                         accession_file)
            return

        os.rename(accession_file, original)
        five_percent = int(num_lines / 20) or 1

        with (open(original, 'r', encoding='utf-8', newline='') as old,
              open(accession_file, 'w', encoding='utf-8', newline='') as new):
            in_file = csv.DictReader(old)
            fieldnames = in_file.fieldnames
            out_file = csv.DictWriter(new, fieldnames=fieldnames)
            out_file.writeheader()
            for count, line in enumerate(in_file):
                wp_status = line.get('wild_prov_status')
                if wp_status in depr_wild_prov:
                    line['wild_prov_status'] = None
                prov_type = line.get('prov_type')
                if prov_type in depr_prov_type:
                    line['prov_type'] = None
                out_file.writerow(line)
                if count % five_percent == 0:
                    pb_set_fraction(count / num_lines)
                    yield

    def changes_upgrader(self, filenames):
        """Upgrade plant_change file"""
        changes_file = [i for i in filenames if i.endswith('plant_change.txt')]

        # bail early
        if not changes_file:
            return

        deprecated = ['FOGS',
                      'PLOP',
                      'BA40',
                      'TOTM']

        changes_file = changes_file[0]
        original = changes_file + '_ORIG_'

        msg = _('removing deprecated reason entries: ')
        logger.debug('upgrading %s', changes_file)
        bauble.task.set_message(msg + changes_file)

        with open(changes_file, 'r', encoding='utf-8', newline='') as f:
            num_lines = len(f.readlines())

        if num_lines <= 1:
            logger.debug('%s contains no table data skip translation',
                         changes_file)
            return

        os.rename(changes_file, original)
        five_percent = int(num_lines / 20) or 1

        with (open(original, 'r', encoding='utf-8', newline='') as old,
              open(changes_file, 'w', encoding='utf-8', newline='') as new):
            in_file = csv.DictReader(old)
            fieldnames = in_file.fieldnames
            out_file = csv.DictWriter(new, fieldnames=fieldnames)
            out_file.writeheader()
            for count, line in enumerate(in_file):
                wps = line.get('reason')
                if wps in deprecated:
                    line['wild_prov_status'] = None
                out_file.writerow(line)
                if count % five_percent == 0:
                    pb_set_fraction(count / num_lines)
                    yield

    def geo_upgrader(self, change_lst: list[str]) -> None:
        """Upgrade changes from v1.0 to v1.3 prior to importing"""
        for file in change_lst:
            original = file + '_ORIG_'

            msg = _('translating data in: ')
            logger.debug('translating %s', file)
            bauble.task.set_message(msg + file)

            with open(file, 'r', encoding='utf-8', newline='') as f:
                num_lines = len(f.readlines())

            if num_lines <= 1:
                logger.debug('%s contains no table data skip translation',
                             file)
                continue

            os.rename(file, original)
            five_percent = int(num_lines / 20) or 1
            with (open(original, 'r', encoding='utf-8', newline='') as old,
                  open(file, 'w', encoding='utf-8', newline='') as new):
                in_file = csv.DictReader(old)
                fieldnames = in_file.fieldnames
                out_file = csv.DictWriter(new, fieldnames=fieldnames)
                out_file.writeheader()
                for count, line in enumerate(in_file):
                    new_geo_id = self.translator.get(line.get('geography_id'))
                    # the old system had one entry with no code or parent.
                    if not new_geo_id:
                        logger.debug('skipping %s', line)
                        continue
                    line['geography_id'] = new_geo_id
                    out_file.writerow(line)
                    if count % five_percent == 0:
                        pb_set_fraction(count / num_lines)
                        yield

    def set_geo_translator(self, geography: str) -> None:
        """return a dictionary of old IDs to new IDs for the geography table.
        """
        from bauble.plugins.plants import Geography

        msg = _('creating translation table')
        logger.debug(msg)
        bauble.task.set_message(msg)

        with open(geography, 'r', encoding='utf-8', newline='') as f:
            num_lines = len(f.readlines())

        five_percent = int(num_lines / 20) or 1
        old_geos = {}
        with open(geography, 'r', encoding='utf-8', newline='') as f:
            geo = csv.DictReader(f)
            for count, line in enumerate(geo):
                id_ = line.get('id')
                code = line.get('tdwg_code').split(',')[0]
                parent = line.get('parent_id')
                old_geos[id_] = {'code': code, 'parent': parent}
                # update the gui
                if count % five_percent == 0:
                    fraction = count / num_lines
                    pb_set_fraction(fraction)
                    yield

        session = db.Session()
        translator = {}
        # make sure to get the right count
        num_lines = len(old_geos)
        for count, (id_, codes) in enumerate(old_geos.items()):
            new = (session.query(Geography)
                   .filter_by(tdwg_code=codes.get('code'))
                   .all())
            if not new:
                parent = old_geos.get(codes.get('parent'))
                if not parent:
                    logger.debug('no parent for %s', codes)
                    continue
                new = (session.query(Geography)
                       .filter_by(tdwg_code=parent.get('code'))
                       .all())
            if not new:
                parent2 = old_geos.get(parent.get('parent'))
                if not parent2:
                    logger.debug('no parent for %s', codes)
                    continue
                new = (session.query(Geography)
                       .filter_by(tdwg_code=parent2.get('code'))
                       .all())
            if new:
                if len(new) == 1:
                    translator[id_] = new[0].id
                else:
                    logger.debug('multiples records for %s', codes)
            else:
                logger.debug('unfound area %s', codes)
            if count % five_percent == 0:
                fraction = count / num_lines
                pb_set_fraction(fraction)
                yield
        session.close()
        self.translator = translator

    @staticmethod
    def _toposort_file(filename, key_pairs):
        """Topologically sort a file that contains self referential
        relationship so that the lines come before the lines that refer to
        them.

        :param filename: the csv file to sort

        :param key_pairs: tuples of the form (parent, child) where for each
        line in the file the line[parent] needs to be sorted before
        any of the line[child].  parent is usually the name of the
        foreign_key column and child is usually the column that the
        foreign key points to, e.g ('parent_id', 'id')
        """
        with open(filename, 'r', encoding='utf-8', newline='') as f:
            reader = UnicodeReader(f, quotechar=QUOTE_CHAR,
                                   quoting=QUOTE_STYLE)

            # create a dictionary of the lines mapped to the child field
            bychild = {}
            for line in reader:
                for parent, child in key_pairs:
                    bychild[line[child]] = line
            fields = reader.reader.fieldnames

        # create pairs from the values in the lines where pair[0]
        # should come before pair[1] when the lines are sorted
        pairs = []
        for line in list(bychild.values()):
            for parent, child in key_pairs:
                if line[parent] and line[child]:
                    pairs.append((line[parent], line[child]))

        # sort the keys and flatten the lines back into a list
        sorted_keys = utils.topological_sort(list(bychild.keys()), pairs)
        sorted_lines = []
        for key in sorted_keys:
            sorted_lines.append(bychild[key])

        # write a temporary file of the sorted lines
        tmppath = tempfile.mkdtemp()
        # _head, name = os.path.split(filename)
        name = Path(filename).name
        filename = Path(tmppath, name)
        with open(filename, 'w', encoding='utf-8', newline='') as tmpfile:
            row = ','.join(fields)
            tmpfile.write(f"{row}\n")
            # writer = UnicodeWriter(tmpfile, fields, quotechar=QUOTE_CHAR,
            writer = csv.DictWriter(tmpfile, fields, quotechar=QUOTE_CHAR,
                                    quoting=QUOTE_STYLE)
            writer.writerows(sorted_lines)
        return str(filename)

    def run(self, filenames, metadata, force=False):
        """A generator method for importing filenames into the database.

        This method periodically yields control so that the GUI can
        update.

        :param filenames:
        :param metadata:
        :param force: default=False
        """
        transaction = None
        connection = None

        try:
            # use a contextual connect in case whoever called this
            # method called it inside a transaction then we can pick
            # up the parent connection and the transaction
            connection = metadata.bind.connect()
            transaction = connection.begin()
        except Exception as e:
            msg = _('Error connecting to database.\n\n{}').format(
                utils.xml_safe(e))
            utils.message_dialog(msg, Gtk.MessageType.ERROR)
            return

        # create a mapping of table names to filenames
        filename_dict = {}
        for f in filenames:
            # _path, base = os.path.split(f)
            table_name = Path(f).stem
            # table_name, ext = os.path.splitext(base)
            if table_name in filename_dict:
                safe = utils.xml_safe
                msg = _('More than one file given to import into table '
                        f'<b>{safe(table_name)}</b>: '
                        f'{safe(filename_dict.get(table_name))}, {safe(f)}')
                utils.message_dialog(msg, Gtk.MessageType.ERROR)
                return
            filename_dict[table_name] = f

        # resolve filenames to table names and return them in sorted order
        sorted_tables = []
        for table in metadata.sorted_tables:
            try:
                sorted_tables.insert(0, (table, filename_dict.pop(table.name)))
            except KeyError:
                logger.debug('%s not in list of filenames', table.name)

        if len(filename_dict) > 0:
            msg = _('Could not match all filenames to table names.\n\n'
                    f'{filename_dict}')
            utils.message_dialog(msg, Gtk.MessageType.ERROR)
            return

        total_lines = 0
        filesizes = {}
        for filename in filenames:
            # get the total number of lines for all the files
            with open(filename, 'r', encoding='utf-8', newline='') as f:
                nlines = len(f.readlines())

            filesizes[filename] = nlines
            total_lines += nlines

        five_percent = int(total_lines / 20) or 1
        created_tables = []

        def create_table(table):
            table.create(bind=connection)
            if table.name not in created_tables:
                created_tables.append(table.name)

        steps_so_far = 0
        insert = None
        depends = set()  # the type will be changed to a [] later
        try:
            logger.debug('entering try block in csv importer')
            # get all the dependencies
            for table, filename in sorted_tables:
                logger.debug('get table dependendencies for table %s',
                             table.name)
                deps = utils.find_dependent_tables(table)
                depends.update(list(deps))
                del deps

            deps_names = ', '.join(sorted([deps.name for deps in depends]))
            # drop all of the dependencies together
            # have added one table since v1.0 and a user may choose to drop
            # one or 2 tables (e.g plugin, history)
            if len(filenames) >= len(metadata.tables) - 3:
                if not force:
                    msg = _('It appears you are attempting a full restore. To '
                            'do this requires deleting all data.\n\n'
                            '<b>CAUTION! only proceed if you know what you '
                            'are doing</b>.\n\nWould you like to continue a '
                            'full restore?')
                    response = utils.yes_no_dialog(msg)
                    if response:
                        force = True

            if len(depends) > 0:
                if not force:
                    msg = _('In order to import the files the following '
                            'tables will need to be dropped:'
                            f'\n\n<b>{deps_names}</b>\n\n'
                            'Would you like to continue?')
                    response = utils.yes_no_dialog(msg)
                else:
                    response = True

                if response and len(depends) > 0:
                    logger.debug('dropping: %s', deps_names)
                    metadata.drop_all(bind=connection, tables=depends)
                else:
                    # user doesn't want to drop dependencies so we just quit
                    return

            # commit the dependency drops
            logger.debug('commit dropped tables')
            transaction.commit()
            transaction = connection.begin()

            # update_every determines how many rows we will insert at a time
            update_every = 127

            # import the tables one at a time, breaking every so often
            # so the GUI can update
            for table, filename in reversed(sorted_tables):
                if self.__cancel or self.__error:
                    break
                msg = (_('importing %(table)s table from %(filename)s') %
                       {'table': table.name, 'filename': filename})
                logger.info(msg)
                bauble.task.set_message(msg)
                yield  # allow progress bar update

                # check if the table was in the depends because they
                # could have been dropped whereas table.exists() can
                # return true for a dropped table if the transaction
                # hasn't been committed
                if table in depends or not table.exists():
                    logger.info('%s does not exist. creating.', table.name)
                    create_table(table)
                elif table.name not in created_tables and table not in depends:
                    # we get here if the table wasn't previously
                    # dropped because it was a dependency of another
                    # table
                    if not force:
                        msg = _('The <b>%s</b> table already exists in the '
                                'database and may contain some data. If a '
                                'row the import file has the same id as a '
                                'row in the database then the file will not '
                                'import correctly.\n\n<i>Would you like to '
                                'drop the table in the database first. You '
                                'will lose the data in your database if you '
                                'do this?</i>') % table.name
                        response = utils.yes_no_dialog(msg)
                    else:
                        response = True
                    if response:
                        table.drop(bind=connection)
                        create_table(table)

                if self.__cancel or self.__error:
                    break

                # commit the drop of the table we're importing
                transaction.commit()
                transaction = connection.begin()

                # do nothing more for empty tables
                if filesizes[filename] <= 1:
                    logger.debug('%s contains no table data skipping import',
                                 filename)
                    continue

                # open a temporary reader to get the column keys so we
                # can later precompile our insert statement
                with open(filename, 'r', encoding='utf-8', newline='') as f:
                    logger.debug('%s open', filename)
                    tmp = UnicodeReader(f, quotechar=QUOTE_CHAR,
                                        quoting=QUOTE_STYLE)
                    next(tmp)
                    csv_columns = set(tmp.reader.fieldnames)
                    logger.debug('%s columns = %s', filename, csv_columns)
                    del tmp
                logger.debug('%s closed', filename)

                # precompute the defaults...this assumes that the
                # default function doesn't depend on state after each
                # row...it shouldn't anyways since we do an insert
                # many instead of each row at a time
                defaults = {}
                for column in table.c:
                    if isinstance(column.default, ColumnDefault):
                        defaults[column.name] = column.default.execute()

                logger.debug('column defaults: %s', defaults)
                # check if there are any foreign keys on the table that refer
                # to itself, if so create a new file with the lines sorted in
                # order of dependency so that we don't get errors about
                # importing values into a foreign_key that don't reference an
                # existing row
                self_keys = [f for f in table.foreign_keys if
                             f.column.table == table]
                if self_keys:
                    logger.debug('%s requires toposort')
                    key_pairs = [
                        (x.parent.name, x.column.name) for x in self_keys]
                    filename = self._toposort_file(filename, key_pairs)

                # the column keys for the insert are a union of the
                # columns in the CSV file and the columns with
                # defaults
                column_keys = list(csv_columns.union(list(defaults.keys())))
                insert = table.insert(bind=connection).compile(
                    column_keys=column_keys)

                def do_insert(values):
                    logger.debug('do_insert')
                    if values:
                        logger.debug('executing inserting')
                        connection.execute(insert, *values)

                with open(filename, 'r', encoding='utf-8', newline='') as f:
                    values = []

                    reader = UnicodeReader(f, quotechar=QUOTE_CHAR,
                                           quoting=QUOTE_STYLE)
                    logger.debug('%s open', filename)
                    # NOTE: we shouldn't get this far if the file doesn't
                    # have any rows to import but if so there is a chance
                    # that this loop could cause problems
                    for line in reader:
                        while self.__pause:
                            logger.debug('__pause')
                            yield
                        if self.__cancel or self.__error:
                            logger.debug('breaking: __cancel=%s, __error=%s',
                                         self.__cancel, self.__error)
                            break

                        # fill in default values and None for "empty"
                        # columns in line
                        for column in list(table.c.keys()):
                            if (column in defaults and
                                    (column not in line or
                                     line[column] in ('', None))):
                                line[column] = defaults[column]
                            elif column in line and line[column] in ('', None):
                                line[column] = None
                            elif column not in line:
                                line[column] = None
                            elif column == 'geojson':
                                # eval json data
                                from ast import literal_eval
                                line[column] = literal_eval(
                                    line.get(column, 'None'))
                            elif ((filename.endswith('bauble.csv') or
                                   filename.endswith('bauble.txt')) and
                                  line.get(column) == 'version'):
                                logger.debug('setting version in bauble table')
                                # as this is recreating the database it's more
                                # accurate to say the current version created
                                # the data.
                                line['value'] = bauble.version
                        values.append(line)
                        steps_so_far += 1
                        if steps_so_far % update_every == 0:
                            do_insert(values)
                            values.clear()

                        if steps_so_far % five_percent == 0:
                            fraction = steps_so_far / total_lines
                            pb_set_fraction(fraction)
                            yield

                if self.__error or self.__cancel:
                    logger.debug('breaking: __cancel=%s, __error=%s',
                                 self.__cancel, self.__error)
                    break

                # insert the remainder that were less than update every
                do_insert(values)

                # we have commit after create after each table is imported
                # or Postgres will complain if two tables that are
                # being imported have a foreign key relationship
                transaction.commit()
                logger.debug('%s: %s', table.name,
                             select([func.count()]).select_from(
                                 table).execute().fetchone()[0])
                transaction = connection.begin()
            logger.debug('creating: %s', deps_names)
            # TODO: need to get those tables from depends that need to
            # be created but weren't created already
            metadata.create_all(connection, depends, checkfirst=True)
        except GeneratorExit:
            transaction.rollback()
            raise
        except Exception as e:
            logger.error("%s(%s)", type(e).__name__, e)
            logger.error(traceback.format_exc())
            transaction.rollback()
            self.__error = True
            raise
        else:
            transaction.commit()

        # unfortunately inserting an explicit value into a column that
        # has a sequence doesn't update the sequence, we shortcut this
        # by setting the sequence manually to the max(column)+1
        col = None
        try:
            for table, filename in sorted_tables:
                for col in table.c:
                    utils.reset_sequence(col)
        except Exception:
            col_name = None
            try:
                col_name = col.name
            except Exception:
                pass
            msg = _('Error: Could not set the sequence for column: '
                    f'{col_name}')
            utils.message_details_dialog(utils.xml_safe(msg),
                                         traceback.format_exc(),
                                         Gtk.MessageType.ERROR)

    @staticmethod
    def _get_filenames():
        filechooser = Gtk.FileChooserNative.new(
            _("Choose file(s) to import…"), None, Gtk.FileChooserAction.OPEN)
        filechooser.set_select_multiple(True)
        filechooser.set_current_folder(str(Path.home()))
        filenames = None
        if filechooser.run() == Gtk.ResponseType.ACCEPT:
            filenames = filechooser.get_filenames()
        filechooser.destroy()
        return filenames


class CSVBackup:

    def start(self, path=None):
        if path is None:
            filechooser = Gtk.FileChooserNative.new(
                _("Select a directory"), None,
                Gtk.FileChooserAction.CREATE_FOLDER)
            filechooser.set_current_folder(str(Path.home()))
            response = filechooser.run()
            path = filechooser.get_filename()
            filechooser.destroy()
            if response != Gtk.ResponseType.ACCEPT:
                return

        if not os.path.exists(path):
            raise ValueError(_("CSVBackup: path does not exist.\n%s") % path)

        try:
            bauble.task.queue(self._export_task(path))
        except Exception as e:
            logger.debug("%s(%s)", type(e).__name__, e)

    @staticmethod
    def _export_task(path):
        filename_template = os.path.join(path, "%s.csv")
        steps_so_far = 0
        ntables = 0
        for table in db.metadata.sorted_tables:
            ntables += 1
            filename = filename_template % table.name
            if os.path.exists(filename):
                msg = _('Backup file <b>%(filename)s</b> for '
                        '<b>%(table)s</b> table already exists.\n\n<i>Would '
                        'you like to continue?</i>')\
                    % {'filename': filename, 'table': table.name}
                if not utils.yes_no_dialog(msg):  # if NO: return
                    return

        def replace(string):
            if isinstance(string, str):
                string.replace('\n', '\\n').replace('\r', '\\r')
            return string

        def write_csv(filename, rows):
            with open(filename, 'w', encoding='utf-8', newline='') as f:
                writer = UnicodeWriter(f, quotechar=QUOTE_CHAR,
                                       quoting=QUOTE_STYLE)
                writer.writerows(rows)

        five_percent = int(ntables / 20) or 1
        for table in db.metadata.sorted_tables:
            filename = filename_template % table.name
            steps_so_far += 1
            msg = _('exporting %(table)s table to %(filename)s')\
                % {'table': table.name, 'filename': filename}
            bauble.task.set_message(msg)
            logger.info("exporting %s", table.name)

            # get the data
            results = table.select().execute().fetchall()

            # if empty tables, create empty files with only the column names
            if len(results) == 0:
                write_csv(filename, [table.c.keys()])
                yield
                continue

            rows = []
            rows.append(list(table.c.keys()))  # append col names
            for row in results:
                try:
                    rows.append([replace(i) for i in row.values()])
                except Exception:  # pylint: disable=broad-except
                    logger.error(traceback.format_exc())
            write_csv(filename, rows)
            if ntables % five_percent == 0:
                pb_set_fraction(steps_so_far / ntables)
                yield


class CSVRestoreCommandHandler(pluginmgr.CommandHandler):

    command = 'restore'

    def __call__(self, cmd, arg):
        importer = CSVRestore()
        importer.start(arg)


class CSVBackupCommandHandler(pluginmgr.CommandHandler):

    command = 'backup'

    def __call__(self, cmd, arg):
        exporter = CSVBackup()
        exporter.start(arg)


# pylint: disable=too-few-public-methods
class CSVRestoreTool(pluginmgr.Tool):
    category = _('Backup')
    label = _('Restore')

    @classmethod
    def start(cls):
        """
        Start the CSV importer.  This tool will also reinitialize the
        plugins after importing.
        """
        msg = _('Restoring data into this database will destroy or corrupt '
                'any existing data.\n\n<i>Would you like to continue?</i>')
        if utils.yes_no_dialog(msg, yes_delay=2):
            csv_im = CSVRestore()
            csv_im.start()
            bauble.command_handler('home', None)


class CSVBackupTool(pluginmgr.Tool):
    category = _('Backup')
    label = _('Create')

    @classmethod
    def start(cls):
        csv_ex = CSVBackup()
        csv_ex.start()
