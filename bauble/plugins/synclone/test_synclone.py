# Copyright 2023 Ross Demuth <rossdemuth123@gmail.com>
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
# pylint: disable=protected-access
"""SynClone tests"""

import tempfile
from datetime import datetime
from unittest import mock

from sqlalchemy import create_engine, select
from gi.repository import Gtk

import bauble
from bauble import db
from bauble.test import BaubleTestCase, uri
from bauble.plugins.plants import (Family,
                                   Genus,
                                   Species)
from bauble.plugins.garden import (Accession,
                                   Location,
                                   Plant)

from .clone import DBCloner
from .sync import (DBSyncroniser,
                   ToSync,
                   SyncRow,
                   ResolverDialog,
                   ResolutionCentreView,
                   RESPONSE_SKIP,
                   RESPONSE_SKIP_RELATED,
                   RESPONSE_QUIT,
                   RESPONSE_RESOLVE)


class DBClonerTests(BaubleTestCase):
    def add_data(self):
        # adding data using session ensures history entries
        fam = Family(epithet='Myrtaceae')
        gen = Genus(epithet='Syzygium', family=fam)
        sp = Species(epithet='luehmannii', genus=gen)
        loc = Location(code='LOC1')
        acc = Accession(code='2023.0001', species=sp)
        plt = Plant(code='1', quantity='1', location=loc, accession=acc)
        self.session.add_all([fam, gen, sp, loc, acc, plt])
        self.session.commit()

    def test_history_is_not_empty(self):
        self.add_data()
        id_ = self.session.query(db.History.id).first()
        self.assertIsNotNone(id_)

    @mock.patch('bauble.connmgr.start_connection_manager',
                return_value=(None, 'sqlite:///test.db'))
    def test_get_uri_succeeds(self, _mock_start_cm):
        self.assertEqual(DBCloner._get_uri(), 'sqlite:///test.db')

    @mock.patch('bauble.plugins.synclone.clone.utils.message_dialog')
    @mock.patch('bauble.connmgr.start_connection_manager',
                return_value=(None, uri))
    def test_get_uri_fails(self, _mock_start_cm, mock_dialog):
        self.assertIsNone(DBCloner._get_uri())
        mock_dialog.assert_called()

    def test_clone_engine(self):
        cloner = DBCloner()
        cloner.uri = 'sqlite:///test.db'
        self.assertEqual(str(cloner.clone_engine.url), 'sqlite:///test.db')

    @mock.patch('bauble.plugins.synclone.clone.create_engine')
    def test_clone_engine_mssql_sets_fast_executemany(self, mock_create_eng):
        # MS SQL Server
        cloner = DBCloner()
        ms_uri = ('mssql://ghini:TestPWord@localhost:1434/'
                  'BG?driver=ODBC+Driver+17+for+SQL+Server')
        cloner.uri = ms_uri
        self.assertIsNotNone(cloner.clone_engine)
        mock_create_eng.assert_called_with(ms_uri, fast_executemany=True)

    def test_drop_create_tables_creates_tables(self):
        from sqlalchemy import inspect
        cloner = DBCloner()
        cloner.uri = 'sqlite:///:memory:'
        self.assertEqual(len(inspect(cloner.clone_engine).get_table_names()),
                         0)
        cloner.drop_create_tables()
        self.assertTrue(
            len(inspect(cloner.clone_engine).get_table_names()) > 20
        )

    def test_get_line_count(self):
        self.add_data()
        # institution, BaubleMeta, History and added in setUp
        self.assertAlmostEqual(DBCloner.get_line_count(), 30, delta=1)

    @mock.patch('bauble.task.set_message')
    def test_run(self, mock_set_message):
        self.add_data()
        cloner = DBCloner()
        cloner.uri = 'sqlite:///:memory:'
        bauble.task.queue(cloner.run())
        mock_set_message.assert_called()
        with cloner.clone_engine.begin() as conn:
            stmt = Family.__table__.select()
            self.assertEqual(conn.execute(stmt).first().family, 'Myrtaceae')
            stmt = Genus.__table__.select()
            self.assertEqual(conn.execute(stmt).first().genus, 'Syzygium')
            stmt = Location.__table__.select()
            self.assertEqual(conn.execute(stmt).first().code, 'LOC1')
            stmt = Accession.__table__.select()
            self.assertEqual(conn.execute(stmt).first().code, '2023.0001')

    @mock.patch('bauble.task.set_message')
    def test_run_bulk_insert(self, mock_set_message):
        for i in range(200):
            self.session.add(Family(epithet=f'Family{i}'))
        self.session.commit()
        cloner = DBCloner()
        cloner.uri = 'sqlite:///:memory:'
        with self.assertLogs(level='DEBUG') as logs:
            bauble.task.queue(cloner.run())
        self.assertTrue(any('adding 127 rows to clone' in i for i in
                            logs.output))
        mock_set_message.assert_called()

    @mock.patch('bauble.task.set_message')
    def test_start(self, mock_set_message):
        self.add_data()
        cloner = DBCloner()
        cloner.start('sqlite:///:memory:')
        bauble.task.queue(cloner.run())
        mock_set_message.assert_called()
        with cloner.clone_engine.begin() as conn:
            stmt = Family.__table__.select()
            self.assertEqual(conn.execute(stmt).first().family, 'Myrtaceae')
            stmt = Genus.__table__.select()
            self.assertEqual(conn.execute(stmt).first().genus, 'Syzygium')
            stmt = Location.__table__.select()
            self.assertEqual(conn.execute(stmt).first().code, 'LOC1')
            stmt = Plant.__table__.select()
            self.assertEqual(conn.execute(stmt).first().code, '1')

    @mock.patch('bauble.task.set_message')
    def test_datetimes_transfer_correctly(self, mock_set_message):
        self.add_data()
        cloner = DBCloner()
        cloner.uri = 'sqlite:///:memory:'
        bauble.task.queue(cloner.run())
        mock_set_message.assert_called()

        with db.engine.begin() as conn:
            stmt = Accession.__table__.select()
            self.assertAlmostEqual(
                conn.execute(stmt).first()._created.timestamp(),
                datetime.now().timestamp(), delta=2
            )

        with cloner.clone_engine.begin() as conn:
            stmt = Accession.__table__.select()
            self.assertAlmostEqual(
                conn.execute(stmt).first()._created.timestamp(),
                datetime.now().timestamp(), delta=2
            )

    @mock.patch('bauble.task.set_message')
    def test_record_clone_point(self, _mock_set_message):
        self.add_data()
        cloner = DBCloner()
        cloner.uri = 'sqlite:///:memory:'
        cloner.drop_create_tables()
        # _record_clone_point is called by run.
        bauble.task.queue(cloner.run())
        meta_table = bauble.meta.BaubleMeta.__table__
        stmt = (select(meta_table.c.value)
                .where(meta_table.c.name == 'clone_history_id'))
        with cloner.clone_engine.begin() as conn:
            self.assertEqual(conn.execute(stmt).scalar(), '7')
        # add an extra history entry and run it again should update not insert
        hist = db.History.__table__
        insert = hist.insert().values({'table_name': 'family',
                                       'table_id': 100,
                                       'values': {'family': 'Orchidaceae'},
                                       'operation': 'insert',
                                       'timestamp': datetime.utcnow()})
        with cloner.clone_engine.begin() as conn:
            conn.execute(insert)

        cloner._record_clone_point()
        with cloner.clone_engine.begin() as conn:
            self.assertEqual(conn.execute(stmt).scalar(), '8')

    @mock.patch('bauble.task.set_message')
    def test_record_clone_point_not_set_w_no_history(self, _mock_set_message):
        cloner = DBCloner()
        cloner.uri = 'sqlite:///:memory:'
        cloner.drop_create_tables()
        # _record_clone_point is called by run.
        bauble.task.queue(cloner.run())
        meta_table = bauble.meta.BaubleMeta.__table__
        stmt = (select(meta_table.c.value)
                .where(meta_table.c.name == 'clone_history_id'))
        with cloner.clone_engine.begin() as conn:
            self.assertEqual(conn.execute(stmt).scalar(), None)
        # add an extra history entry and it should set
        hist = db.History.__table__
        insert = hist.insert().values({'table_name': 'family',
                                       'table_id': 100,
                                       'values': {'family': 'Orchidaceae'},
                                       'operation': 'insert',
                                       'timestamp': datetime.utcnow()})
        with cloner.clone_engine.begin() as conn:
            conn.execute(insert)

        cloner._record_clone_point()
        with cloner.clone_engine.begin() as conn:
            self.assertEqual(conn.execute(stmt).scalar(), '1')


class DBSyncTests(BaubleTestCase):

    def add_clone_history(self, clone_engine, history_id, values):
        # add clone_history_id
        meta = bauble.meta.BaubleMeta.__table__
        meta_stmt = meta.insert().values({'name': 'clone_history_id',
                                          'value': history_id})
        # add a history entry
        hist = db.History.__table__
        hist_stmt = hist.insert().values(values)
        with clone_engine.begin() as conn:
            for table in db.metadata.sorted_tables:
                table.create(bind=conn)
            if history_id is not None:
                conn.execute(meta_stmt)
            conn.execute(hist_stmt)

    def test_to_sync_add_batch_succeeds(self):
        # use a file here so it is persistent
        # add a history entry
        temp_dir = tempfile.mkdtemp()
        clone_uri = f"sqlite:///{temp_dir}/test.db"
        values = {'table_name': 'family',
                  'table_id': 100,
                  'values': {'family': 'Orchidaceae'},
                  'operation': 'insert',
                  'timestamp': datetime.now()}
        clone_engine = create_engine(clone_uri)
        self.add_clone_history(clone_engine, 0, values)

        batch_num = ToSync.add_batch_from_uri(clone_uri)
        self.assertEqual(batch_num, '1')

        result = self.session.query(ToSync).all()
        self.assertEqual(len(result), 1)
        first = result[0]
        self.assertEqual(first.batch_number, 1)
        self.assertEqual(first.table_name, 'family')
        self.assertEqual(first.table_id, 100)
        self.assertEqual(first.operation, 'insert')
        self.assertEqual(first.user, None)
        self.assertAlmostEqual(first.timestamp.timestamp(),
                               datetime.now().timestamp(),
                               delta=1)
        self.assertEqual(first.values, {'family': 'Orchidaceae'})

    def test_to_sync_add_batch_fails(self):
        temp_dir = tempfile.mkdtemp()
        clone_uri = f"sqlite:///{temp_dir}/test.db"
        values = {'table_name': 'family',
                  'table_id': 100,
                  'values': {'family': 'Orchidaceae'},
                  'operation': 'insert',
                  'timestamp': datetime.now()}
        clone_engine = create_engine(clone_uri)
        self.add_clone_history(clone_engine, None, values)

        self.assertRaises(bauble.error.BaubleError,
                          ToSync.add_batch_from_uri,
                          clone_uri)

    def test_to_sync_remove_row(self):
        # use a file here so it is persistent
        # add a history entry
        temp_dir = tempfile.mkdtemp()
        clone_uri = f"sqlite:///{temp_dir}/test.db"
        values = {'table_name': 'family',
                  'table_id': 100,
                  'values': {'family': 'Orchidaceae'},
                  'operation': 'insert',
                  'timestamp': datetime.now()}
        clone_engine = create_engine(clone_uri)
        self.add_clone_history(clone_engine, 0, values)

        batch_num = ToSync.add_batch_from_uri(clone_uri)
        self.assertEqual(batch_num, '1')

        result = self.session.query(ToSync).all()
        self.assertEqual(len(result), 1)
        first = result[0]
        self.assertEqual(first.values, {'family': 'Orchidaceae'})

        with db.engine.begin() as conn:
            ToSync.remove_row(first, conn)

        result = self.session.query(ToSync).all()
        self.assertEqual(len(result), 0)

    def test_sync_row_values_removes_id_updates_last_updated(self):
        data = {'batch_number': 1,
                'table_name': 'family',
                'table_id': 100,
                'values': {'id': 100,
                           'family': ['Malvaceae', 'Sterculiaceae'],
                           '_last_updated': 0},
                'operation': 'update',
                'user': 'test',
                'timestamp': datetime(2023, 1, 1)}

        to_sync = ToSync.__table__
        in_stmt = to_sync.insert(data)
        out_stmt = select(to_sync)
        with db.engine.begin() as conn:
            conn.execute(in_stmt)
            first = conn.execute(out_stmt).first()
            row = SyncRow({}, first, conn)
            self.assertIsNone(row.values.get('id'))
            self.assertAlmostEqual(row.values.get('_last_updated').timestamp(),
                                   datetime.now().timestamp(),
                                   delta=1)

    def test_sync_row_updates_ids_from_id_map(self):
        # insert
        data = {'batch_number': 1,
                'table_name': 'genus',
                'table_id': 10,
                'values': {'id': 10,
                           'family_id': 10,
                           'genus': 'Sterculia',
                           '_last_updated': 0},
                'operation': 'insert',
                'user': 'test',
                'timestamp': datetime(2023, 1, 1)}

        to_sync = ToSync.__table__
        in_stmt = to_sync.insert(data)
        out_stmt = select(to_sync)
        with db.engine.begin() as conn:
            conn.execute(in_stmt)
            first = conn.execute(out_stmt).first()
            row = SyncRow({'family': {10: 2}}, first, conn)
            self.assertEqual(row.values.get('family_id'), 2)

        # update
        data = {'batch_number': 1,
                'table_name': 'genus',
                'table_id': 10,
                'values': {'id': 10,
                           'family_id': [10, 2],
                           'genus': 'Sterculia',
                           '_last_updated': 0},
                'operation': 'update',
                'user': 'test',
                'timestamp': datetime(2023, 1, 1)}

        to_sync = ToSync.__table__
        in_stmt = to_sync.insert(data)
        out_stmt = select(to_sync)
        with db.engine.begin() as conn:
            conn.execute(in_stmt)
            first = conn.execute(out_stmt).first()
            row = SyncRow({'family': {10: 4}}, first, conn)
            self.assertEqual(row.values.get('family_id'), 4)

    def test_sync_row_gets_correct_instance(self):
        fam = Family(id=4, family='Sterculiaceae')
        self.session.add(fam)
        self.session.commit()

        data = {'batch_number': 1,
                'table_name': 'family',
                'table_id': 10,
                'values': {'id': 10,
                           'family': ['Malvaceae', 'Sterculiaceae'],
                           '_last_updated': 0},
                'operation': 'update',
                'user': 'test',
                'timestamp': datetime(2023, 1, 1)}

        to_sync = ToSync.__table__
        in_stmt = to_sync.insert(data)
        out_stmt = select(to_sync)
        with db.engine.begin() as conn:
            conn.execute(in_stmt)
            first = conn.execute(out_stmt).first()
            row = SyncRow({'family': {10: 4}}, first, conn)
            self.assertEqual(row.table_id, 4)
            self.assertEqual(row.instance.id, fam.id)

    def test_sync_row_sync_update(self):
        fam = Family(id=4, family='Sterculiaceae')
        self.session.add(fam)
        self.session.commit()

        data = {'batch_number': 1,
                'table_name': 'family',
                'table_id': 4,
                'values': {'id': 4,
                           'family': ['Malvaceae', 'Sterculiaceae'],
                           '_last_updated': 0},
                'operation': 'update',
                'user': 'test',
                'timestamp': datetime(2023, 1, 1)}

        to_sync = ToSync.__table__
        in_stmt = to_sync.insert(data)
        out_stmt = select(to_sync)
        with db.engine.begin() as conn:
            conn.execute(in_stmt)
            first = conn.execute(out_stmt).first()
            row = SyncRow({}, first, conn)
            self.assertEqual(row.table_id, 4)
            self.assertEqual(row.instance.id, fam.id)
            row.sync()
        self.session.expire(fam)
        self.assertEqual(fam.family, 'Malvaceae')
        # check history entered correctly
        hist = self.session.query(db.History).all()
        self.assertEqual(len(hist), 2)
        self.assertEqual(hist[1].table_id, 4)
        self.assertEqual(hist[1].operation, 'update')
        self.assertEqual(hist[1].table_name, 'family')
        self.assertEqual(hist[1].user, 'test')
        self.assertAlmostEqual(hist[1].timestamp.timestamp(),
                               datetime.now().timestamp(),
                               delta=1)
        self.assertEqual(hist[1].values['family'],
                         ['Malvaceae', 'Sterculiaceae'])

    def test_sync_row_sync_insert(self):
        data = {'batch_number': 1,
                'table_name': 'family',
                'table_id': 4,
                'values': {'id': 4,
                           'family': 'Malvaceae',
                           '_last_updated': 0},
                'operation': 'insert',
                'user': 'test',
                'timestamp': datetime(2023, 1, 1)}

        to_sync = ToSync.__table__
        in_stmt = to_sync.insert(data)
        out_stmt = select(to_sync)
        with db.engine.begin() as conn:
            conn.execute(in_stmt)
            first = conn.execute(out_stmt).first()
            id_map = {}
            row = SyncRow(id_map, first, conn)
            row.sync()
            self.assertEqual(row.instance.id, 1)
            # updates the id_map
            self.assertEqual(id_map, {'family': {4: 1}})
        fam = self.session.query(Family).filter(Family.id == 1).first()
        self.assertEqual(fam.family, 'Malvaceae')
        # check history entered correctly
        hist = self.session.query(db.History).all()
        self.assertEqual(len(hist), 1)
        self.assertEqual(hist[0].table_id, 1)
        self.assertEqual(hist[0].operation, 'insert')
        self.assertEqual(hist[0].table_name, 'family')
        self.assertEqual(hist[0].user, 'test')
        self.assertAlmostEqual(hist[0].timestamp.timestamp(),
                               datetime.now().timestamp(),
                               delta=1)
        self.assertEqual(hist[0].values['family'], 'Malvaceae')

    def test_sync_row_sync_delete(self):
        fam = Family(id=4, family='Sterculiaceae')
        self.session.add(fam)
        self.session.commit()

        data = {'batch_number': 1,
                'table_name': 'family',
                'table_id': 4,
                'values': {'id': 4,
                           'family': 'Sterculiaceae',
                           '_last_updated': 0},
                'operation': 'delete',
                'user': 'test',
                'timestamp': datetime(2023, 1, 1)}

        to_sync = ToSync.__table__
        in_stmt = to_sync.insert(data)
        out_stmt = select(to_sync)
        with db.engine.begin() as conn:
            conn.execute(in_stmt)
            first = conn.execute(out_stmt).first()
            row = SyncRow({}, first, conn)
            self.assertEqual(row.table_id, 4)
            self.assertEqual(row.instance.id, fam.id)
            row.sync()
        fam = self.session.query(Family).filter(Family.id == 4).first()
        self.assertEqual(fam, None)
        # check history entered correctly
        hist = self.session.query(db.History).all()
        self.assertEqual(len(hist), 2)
        self.assertEqual(hist[1].table_id, 4)
        self.assertEqual(hist[1].operation, 'delete')
        self.assertEqual(hist[1].table_name, 'family')
        self.assertEqual(hist[1].user, 'test')
        self.assertAlmostEqual(hist[1].timestamp.timestamp(),
                               datetime.now().timestamp(),
                               delta=1)
        self.assertEqual(hist[1].values['family'], 'Sterculiaceae')

    def test_resolver_dialog_edit_text_cell(self):
        data = {'batch_number': 1,
                'table_name': 'family',
                'table_id': 4,
                'values': {'family': 'Sterculiaceae',
                           '_last_updated': 0},
                'operation': 'insert',
                'user': 'test',
                'timestamp': datetime(2023, 1, 1)}

        to_sync = ToSync.__table__
        in_stmt = to_sync.insert(data)
        out_stmt = select(to_sync)
        with db.engine.begin() as conn:
            conn.execute(in_stmt)
            first = conn.execute(out_stmt).first()

        resolver = ResolverDialog(row=first)
        resolver.on_value_cell_edited(None, 0, 'Malvaceae')
        self.assertEqual(resolver.row['values'], {'family': 'Malvaceae',
                                                  '_last_updated': 0})

    def test_resolver_dialog_edit_int_cell(self):
        data = {'batch_number': 1,
                'table_name': 'accession',
                'table_id': 1,
                'values': {'code': '2023.0001',
                           'species_id': 1,
                           'quantity_recvd': 2,
                           '_last_updated': 0},
                'operation': 'insert',
                'user': 'test',
                'timestamp': datetime(2023, 1, 1)}

        to_sync = ToSync.__table__
        in_stmt = to_sync.insert(data)
        out_stmt = select(to_sync)
        with db.engine.begin() as conn:
            conn.execute(in_stmt)
            first = conn.execute(out_stmt).first()

        resolver = ResolverDialog(row=first)
        resolver.on_value_cell_edited(None, 2, '3')
        self.assertEqual(resolver.row['values'], {'code': '2023.0001',
                                                  'species_id': 1,
                                                  'quantity_recvd': 3,
                                                  '_last_updated': 0})

    def test_resolver_dialog_edit_int_cell_wrong_type(self):
        data = {'batch_number': 1,
                'table_name': 'accession',
                'table_id': 1,
                'values': {'code': '2023.0001',
                           'species_id': 1,
                           'quantity_recvd': 2,
                           '_last_updated': 0},
                'operation': 'insert',
                'user': 'test',
                'timestamp': datetime(2023, 1, 1)}

        to_sync = ToSync.__table__
        in_stmt = to_sync.insert(data)
        out_stmt = select(to_sync)
        with db.engine.begin() as conn:
            conn.execute(in_stmt)
            first = conn.execute(out_stmt).first()

        resolver = ResolverDialog(row=first)
        resolver.on_value_cell_edited(None, 2, 'a')
        # does not change
        self.assertEqual(resolver.row['values'], {'code': '2023.0001',
                                                  'species_id': 1,
                                                  'quantity_recvd': 2,
                                                  '_last_updated': 0})

    def test_resolver_dialog_edit_datetime_cell(self):
        data = {'batch_number': 1,
                'table_name': 'accession',
                'table_id': 1,
                'values': {'code': '2023.0001',
                           'species_id': 1,
                           'quantity_recvd': 2,
                           '_last_updated': 0},
                'operation': 'insert',
                'user': 'test',
                'timestamp': datetime(2023, 1, 1)}

        to_sync = ToSync.__table__
        in_stmt = to_sync.insert(data)
        out_stmt = select(to_sync)
        with db.engine.begin() as conn:
            conn.execute(in_stmt)
            first = conn.execute(out_stmt).first()

        resolver = ResolverDialog(row=first)
        resolver.on_value_cell_edited(None, 3, '29/5/23')
        self.assertEqual(resolver.row['values'], {'code': '2023.0001',
                                                  'species_id': 1,
                                                  'quantity_recvd': 2,
                                                  '_last_updated': '29/5/23'})

    @mock.patch('bauble.plugins.synclone.sync.ResolverDialog.run')
    def test_dbsyncroniser_can_resolve_on_fly(self, mock_run):
        fam = Family(id=4, family='Sterculiaceae')
        gen = Genus(id=1, genus='Sterculia', family=fam)
        self.session.add_all([fam, gen])
        self.session.commit()
        # This data should raise an SQLAlchemyError (invalid genus foreign
        # keys)
        data = [{'batch_number': 1,
                 'table_name': 'species',
                 'table_id': 1,
                 'values': {'id': 1,
                            'sp': 'quadrifida',
                            'genus_id': 4,
                            '_last_updated': '29/5/23'},
                 'operation': 'insert',
                 'user': 'test',
                 'timestamp': datetime(2023, 1, 1)}]

        to_sync = ToSync.__table__
        in_stmt = to_sync.insert(data)
        out_stmt = select(to_sync).order_by(to_sync.c.id.desc())
        with db.engine.begin() as conn:
            conn.execute(in_stmt)
            rows = conn.execute(out_stmt).all()
        synchroniser = DBSyncroniser(rows)

        # mutate the row and set return_value to RESPONSE_QUIT...  Tests that
        # values is set back to start_values
        def _set_and_respond():
            rows[0]['values']['genus_id'] = 1
            return RESPONSE_RESOLVE

        mock_run.side_effect = _set_and_respond

        failed = synchroniser.sync()
        self.assertEqual(len(failed), 0)
        self.assertEqual(rows[0]['values']['genus_id'], 1)
        # species added
        self.assertEqual([str(i) for i in self.session.query(Species)],
                         ['Sterculia quadrifida'])

    @mock.patch('bauble.plugins.synclone.sync.ResolverDialog.run')
    def test_dbsyncroniser_rolls_back_returns_failed_on_quit(self,
                                                             mock_run):
        fam = Family(id=4, family='Sterculiaceae')
        gen = Genus(id=1, genus='Sterculia', family=fam)
        self.session.add_all([fam, gen])
        self.session.commit()
        # This data should raise an SQLAlchemyError (invalid foreign keys for
        # accession, if reversed this should work)
        data = [{'batch_number': 1,
                 'table_name': 'accession',
                 'table_id': 1,
                 'values': {'id': 1,
                            'code': '2023.0001',
                            'species_id': 1,
                            'quantity_recvd': 2,
                            '_last_updated': '29/5/23'},
                 'operation': 'insert',
                 'user': 'test',
                 'timestamp': datetime(2023, 1, 1)},
                {'batch_number': 1,
                 'table_name': 'species',
                 'table_id': 1,
                 'values': {'id': 1,
                            'sp': 'quadrifida',
                            'genus_id': 1,
                            '_last_updated': '29/5/23'},
                 'operation': 'insert',
                 'user': 'test',
                 'timestamp': datetime(2023, 1, 1)}]

        to_sync = ToSync.__table__
        in_stmt = to_sync.insert(data)
        out_stmt = select(to_sync).order_by(to_sync.c.id.desc())
        with db.engine.begin() as conn:
            conn.execute(in_stmt)
            rows = conn.execute(out_stmt).all()
        synchroniser = DBSyncroniser(rows)

        # mutate the row and set return_value to RESPONSE_QUIT...  Tests that
        # values is set back to start_values
        def _set_and_respond():
            rows[1]['values']['code'] = '2023.0003'
            return RESPONSE_QUIT

        mock_run.side_effect = _set_and_respond
        # Respond QUIT
        failed = synchroniser.sync()
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed, [1])
        self.assertEqual(rows[1]['values']['code'], '2023.0001')
        # nothing added
        self.assertEqual(self.session.query(Species).all(), [])
        self.assertEqual(self.session.query(Accession).all(), [])

    @mock.patch('bauble.utils.yes_no_dialog')
    @mock.patch('bauble.plugins.synclone.sync.ResolverDialog.run')
    def test_dbsyncroniser_on_delete_asks_quit(self, mock_run, mock_dialog):
        # NOTE if quiting this way failed is not returned
        fam = Family(id=4, family='Sterculiaceae')
        gen = Genus(id=1, genus='Sterculia', family=fam)
        self.session.add_all([fam, gen])
        self.session.commit()
        # This data should raise an SQLAlchemyError (invalid foreign keys for
        # accession, if reversed this should work)
        data = [{'batch_number': 1,
                 'table_name': 'accession',
                 'table_id': 1,
                 'values': {'id': 1,
                            'code': '2023.0001',
                            'species_id': 1,
                            'quantity_recvd': 2,
                            '_last_updated': '29/5/23'},
                 'operation': 'insert',
                 'user': 'test',
                 'timestamp': datetime(2023, 1, 1)},
                {'batch_number': 1,
                 'table_name': 'species',
                 'table_id': 1,
                 'values': {'id': 1,
                            'sp': 'quadrifida',
                            'genus_id': 1,
                            '_last_updated': '29/5/23'},
                 'operation': 'insert',
                 'user': 'test',
                 'timestamp': datetime(2023, 1, 1)}]

        to_sync = ToSync.__table__
        in_stmt = to_sync.insert(data)
        out_stmt = select(to_sync).order_by(to_sync.c.id.desc())
        with db.engine.begin() as conn:
            conn.execute(in_stmt)
            rows = conn.execute(out_stmt).all()
        synchroniser = DBSyncroniser(rows)

        # mutate the row and set return_value to RESPONSE_QUIT...  Tests that
        # values is set back to start_values
        def _set_and_respond():
            rows[1]['values']['code'] = '2023.0003'
            return Gtk.ResponseType.DELETE_EVENT

        mock_run.side_effect = _set_and_respond
        mock_dialog.return_value = Gtk.ResponseType.YES
        failed = synchroniser.sync()
        self.assertEqual(len(failed), 0)
        self.assertEqual(rows[1]['values']['code'], '2023.0001')
        # nothing added
        self.assertEqual(self.session.query(Species).all(), [])
        self.assertEqual(self.session.query(Accession).all(), [])
        mock_dialog.assert_called()

    @mock.patch('bauble.plugins.synclone.sync.ResolverDialog.run')
    def test_dbsyncroniser_fails_duplicate_cascades_on_skip_related(self,
                                                                    mock_run):
        # this is one of the harder to resolve scenario that would requires
        # user input to sort out
        fam = Family(id=4, family='Sterculiaceae')
        gen = Genus(id=1, genus='Sterculia', family=fam)
        self.session.add_all([fam, gen])
        self.session.commit()
        # This data should raise an SQLAlchemyError (unique constraint family,
        # genus)
        data = [{'batch_number': 1,
                 'table_name': 'family',
                 'table_id': 1,
                 'values': {'id': 1,
                            'family': 'Sterculiaceae',
                            '_last_updated': 0},
                 'operation': 'insert',
                 'user': 'test',
                 'timestamp': datetime(2023, 1, 1)},
                {'batch_number': 1,
                 'table_name': 'genus',
                 'table_id': 1,
                 'values': {'id': 1,
                            'genus': 'Sterculia',
                            'family_id': 1,
                            '_last_updated': 0},
                 'operation': 'insert',
                 'user': 'test',
                 'timestamp': datetime(2023, 1, 1)},
                {'batch_number': 1,
                 'table_name': 'species',
                 'table_id': 1,
                 'values': {'id': 1,
                            'sp': 'quadrifida',
                            'genus_id': 1,
                            '_last_updated': '29/5/23'},
                 'operation': 'insert',
                 'user': 'test',
                 'timestamp': datetime(2023, 1, 1)}]

        to_sync = ToSync.__table__
        in_stmt = to_sync.insert(data)
        out_stmt = select(to_sync).order_by(to_sync.c.id.desc())
        with db.engine.begin() as conn:
            conn.execute(in_stmt)
            rows = conn.execute(out_stmt).all()
        synchroniser = DBSyncroniser(rows)

        mock_run.return_value = RESPONSE_SKIP_RELATED
        failed = synchroniser.sync()
        self.assertEqual(len(failed), 3)
        self.assertEqual(failed, [1, 2, 3])
        # species not added, no extra family or genus
        self.assertEqual(self.session.query(Species).all(), [])
        self.assertEqual(len(self.session.query(Genus).all()), 1)
        self.assertEqual(len(self.session.query(Family).all()), 1)

    @mock.patch('bauble.plugins.synclone.sync.ResolverDialog.run')
    def test_dbsyncroniser_returns_failed_on_skip(self, mock_run):
        fam = Family(id=4, family='Sterculiaceae')
        gen = Genus(id=1, genus='Sterculia', family=fam)
        self.session.add_all([fam, gen])
        self.session.commit()
        # This data should raise an SQLAlchemyError (invalid foreign keys for
        # accession, if reversed this should work)
        data = [{'batch_number': 1,
                 'table_name': 'accession',
                 'table_id': 1,
                 'values': {'id': 1,
                            'code': '2023.0001',
                            'species_id': 1,
                            'quantity_recvd': 2,
                            '_last_updated': '29/5/23'},
                 'operation': 'insert',
                 'user': 'test',
                 'timestamp': datetime(2023, 1, 1)},
                {'batch_number': 1,
                 'table_name': 'species',
                 'table_id': 1,
                 'values': {'id': 1,
                            'sp': 'quadrifida',
                            'genus_id': 1,
                            '_last_updated': '29/5/23'},
                 'operation': 'insert',
                 'user': 'test',
                 'timestamp': datetime(2023, 1, 1)}]

        to_sync = ToSync.__table__
        in_stmt = to_sync.insert(data)
        out_stmt = select(to_sync).order_by(to_sync.c.id.desc())
        with db.engine.begin() as conn:
            conn.execute(in_stmt)
            rows = conn.execute(out_stmt).all()
        synchroniser = DBSyncroniser(rows)

        # mutate the row and set return_value to RESPONSE_QUIT...  Tests that
        # values is set back to start_values
        def _set_and_respond():
            rows[1]['values']['code'] = '2023.0003'
            return RESPONSE_SKIP

        mock_run.side_effect = _set_and_respond
        # Respond SKIP
        failed = synchroniser.sync()
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed, [1])
        self.assertEqual(rows[1]['values']['code'], '2023.0001')
        # species added
        self.assertEqual([str(i) for i in self.session.query(Species)],
                         ['Sterculia quadrifida'])
        self.assertEqual(self.session.query(Accession).all(), [])

    @mock.patch('bauble.plugins.synclone.sync.ResolverDialog.run')
    def test_dbsyncroniser_failed_id_map_cascades_on_skip_related(
            self, mock_run
    ):
        fam = Family(id=4, family='Sterculiaceae')
        gen = Genus(id=1, genus='Sterculia', family=fam)
        self.session.add_all([fam, gen])
        self.session.commit()
        # This data should raise an SQLAlchemyError (invalid foreign keys for
        # species)
        data = [{'batch_number': 1,
                 'table_name': 'species',
                 'table_id': 1,
                 'values': {'id': 1,
                            'sp': 'quadrifida',
                            '_last_updated': '29/5/23'},
                 'operation': 'insert',
                 'user': 'test',
                 'timestamp': datetime(2023, 1, 1)},
                {'batch_number': 1,
                 'table_name': 'accession',
                 'table_id': 1,
                 'values': {'id': 1,
                            'code': '2023.0001',
                            'species_id': 1,
                            'quantity_recvd': 2,
                            '_last_updated': '29/5/23'},
                 'operation': 'insert',
                 'user': 'test',
                 'timestamp': datetime(2023, 1, 1)}]

        to_sync = ToSync.__table__
        in_stmt = to_sync.insert(data)
        out_stmt = select(to_sync).order_by(to_sync.c.id.desc())
        with db.engine.begin() as conn:
            conn.execute(in_stmt)
            rows = conn.execute(out_stmt).all()
        synchroniser = DBSyncroniser(rows)

        # mutate the row and set return_value to RESPONSE_QUIT...  Tests that
        # values is set back to start_values
        def _set_and_respond():
            rows[1]['values']['sp'] = 'sp.'
            return RESPONSE_SKIP_RELATED

        mock_run.side_effect = _set_and_respond
        # Respond SKIP_RELATED
        failed = synchroniser.sync()
        self.assertEqual(synchroniser.id_map, {'species': {1: None},
                                               'accession': {1: None}})
        self.assertEqual(len(failed), 2)
        self.assertEqual(failed, [1, 2])
        self.assertEqual(rows[1]['values']['sp'], 'quadrifida', rows[0])
        # nothing added
        self.assertEqual(self.session.query(Species).all(), [])
        self.assertEqual(self.session.query(Accession).all(), [])

    def test_dbsyncroniser_succeeds(self):
        data = [{'batch_number': 1,
                 'table_name': 'family',
                 'table_id': 1,
                 'values': {'id': 1,
                            'family': 'Malvaceae',
                            '_last_updated': 0},
                 'operation': 'insert',
                 'user': 'test',
                 'timestamp': datetime(2023, 1, 1)},
                {'batch_number': 1,
                 'table_name': 'genus',
                 'table_id': 1,
                 'values': {'id': 1,
                            'genus': 'Sterculia',
                            'family_id': 1,
                            '_last_updated': 0},
                 'operation': 'insert',
                 'user': 'test',
                 'timestamp': datetime(2023, 1, 1)}]

        to_sync = ToSync.__table__
        in_stmt = to_sync.insert(data)
        out_stmt = select(to_sync).order_by(to_sync.c.id.desc())
        with db.engine.begin() as conn:
            conn.execute(in_stmt)
            rows = conn.execute(out_stmt).all()
        synchroniser = DBSyncroniser(rows)

        failed = synchroniser.sync()
        self.assertEqual(failed, [])
        # added
        self.assertEqual([str(i) for i in self.session.query(Genus)],
                         ['Sterculia'])
        self.assertEqual([str(i) for i in self.session.query(Family)],
                         ['Malvaceae'])

    def test_dbsynchroniser_succeeds_complex(self):
        data = [
            {'batch_number': 1,
             'table_name': 'family',
             'table_id': 1,
             'values': {'id': 1,
                        'family': 'Sterculiaceae',
                        '_last_updated': 0},
             'operation': 'insert',
             'user': 'test',
             'timestamp': datetime(2023, 1, 1)},
            {'batch_number': 1,
             'table_name': 'genus',
             'table_id': 1,
             'values': {'id': 1,
                        'genus': 'Sterculia',
                        'family_id': 1,
                        '_last_updated': 0},
             'operation': 'insert',
             'user': 'test',
             'timestamp': datetime(2023, 1, 1)},
            {'batch_number': 1,
             'table_name': 'family',
             'table_id': 1,
             'values': {'id': 1,
                        'family': ['Malvaceae', 'Sterculiaceae'],
                        '_last_updated': 0},
             'operation': 'update',
             'user': 'test',
             'timestamp': datetime(2023, 1, 1)},
            {'batch_number': 1,
             'table_name': 'genus',
             'table_id': 1,
             'values': {'id': 1,
                        'genus': 'Sterculia',
                        'family_id': 1,
                        '_last_updated': 0},
             'operation': 'delete',
             'user': 'test',
             'timestamp': datetime(2023, 1, 1)},
        ]

        to_sync = ToSync.__table__
        in_stmt = to_sync.insert(data)
        out_stmt = select(to_sync).order_by(to_sync.c.id.desc())
        with db.engine.begin() as conn:
            conn.execute(in_stmt)
            rows = conn.execute(out_stmt).all()
        synchroniser = DBSyncroniser(rows)

        failed = synchroniser.sync()
        self.assertEqual(failed, [])
        # added
        self.assertEqual(self.session.query(Genus).all(), [])
        self.assertEqual([str(i) for i in self.session.query(Family)],
                         ['Malvaceae'])

    def test_dbsynchroniser_adds_history_correctly(self):
        # add a family to update
        self.session.add(Family(id=1, family='Leguminosae', _created='1/1/21'))
        self.session.commit()
        # sync some data
        data = [
            {'batch_number': 1,
             'table_name': 'family',
             'table_id': 2,
             'values': {'id': 2,
                        'family': 'Sterculiaceae',
                        '_last_updated': '1/1/23'},
             'operation': 'insert',
             'user': 'test',
             'timestamp': datetime(2023, 1, 1)},
            {'batch_number': 1,
             'table_name': 'genus',
             'table_id': 1,
             'values': {'id': 1,
                        'genus': 'Sterculia',
                        'family_id': 2,
                        '_last_updated': '1/1/23'},
             'operation': 'insert',
             'user': 'test',
             'timestamp': datetime(2023, 1, 1)},
            {'batch_number': 1,
             'table_name': 'family',
             'table_id': 2,
             'values': {'id': 2,
                        'family': ['Malvaceae', 'Sterculiaceae'],
                        '_created': '1/1/23',
                        '_last_updated': '1/1/23'},
             'operation': 'update',
             'user': 'test',
             'timestamp': datetime(2023, 1, 1)},
            {'batch_number': 1,
             'table_name': 'genus',
             'table_id': 1,
             'values': {'id': 1,
                        'genus': 'Sterculia',
                        'family_id': 2,
                        '_created': '1/1/23',
                        '_last_updated': '1/1/23'},
             'operation': 'delete',
             'user': 'test',
             'timestamp': datetime(2023, 1, 1)},
            {'batch_number': 1,
             'table_name': 'family',
             'table_id': 1,
             'values': {'id': 1,
                        'family': ['Fabaceae', 'Leguminosae'],
                        '_created': '1/1/23',
                        '_last_updated': '1/1/23'},
             'operation': 'update',
             'user': 'test',
             'timestamp': datetime(2023, 1, 1)},
        ]

        to_sync = ToSync.__table__
        in_stmt = to_sync.insert(data)
        out_stmt = select(to_sync).order_by(to_sync.c.id.desc())
        with db.engine.begin() as conn:
            conn.execute(in_stmt)
            rows = conn.execute(out_stmt).all()
        synchroniser = DBSyncroniser(rows)

        failed = synchroniser.sync()
        self.assertEqual(failed, [])
        # check history was added
        hist = db.History.__table__
        stmt = select(hist)
        with db.engine.begin() as conn:
            rows = conn.execute(stmt).all()
        # one for each sync entry one for Leguminosae
        self.assertEqual(len(rows), 6)
        from dateutil import parser
        for row in rows[1:]:  # skip first entry for Leguminosae added at start
            # user is preserved
            self.assertEqual(row.user, 'test')
            # timetamp accurate
            self.assertAlmostEqual(row.timestamp.timestamp(),
                                   datetime.now().timestamp(), delta=2)
            # _last_update == now regardless of value in clones data
            if row.operation == 'update':
                last_updated = parser.parse(
                    row['values']['_last_updated'][0]
                ).timestamp()
            else:
                last_updated = parser.parse(
                    row['values']['_last_updated']
                ).timestamp()
            self.assertAlmostEqual(last_updated,
                                   datetime.now().timestamp(),
                                   delta=2)
            # _created not changed for existing but added for others
            if row.table_name == 'family' and row.table_id == 1:
                self.assertEqual(
                    parser.parse(row['values']['_created']).timestamp(),
                    parser.parse('1/1/21').timestamp(),
                )
            else:
                self.assertAlmostEqual(
                    parser.parse(row['values']['_created']).timestamp(),
                    datetime.now().timestamp(), delta=2
                )
            # updates recorded as lists, insert/delete not record as lists
            if row.operation == 'update':
                self.assertTrue([v for v in row['values'].values() if
                                 isinstance(v, list)])
            else:
                self.assertFalse([v for v in row['values'].values() if
                                 isinstance(v, list)])
        # operation is equal
        self.assertEqual(rows[1].operation, 'insert')
        self.assertEqual(rows[2].operation, 'insert')
        self.assertEqual(rows[3].operation, 'update')
        self.assertEqual(rows[4].operation, 'delete')
        self.assertEqual(rows[5].operation, 'update')
        # updates recorded
        self.assertEqual(rows[3]['values']['family'],
                         ['Malvaceae', 'Sterculiaceae'])
        self.assertEqual(rows[5]['values']['family'],
                         ['Fabaceae', 'Leguminosae'])


class ResolutionCentreViewTests(BaubleTestCase):

    def test_init_creates_context_menu(self):
        view = ResolutionCentreView()
        self.assertIsNotNone(view.context_menu)

    def test_on_button_press(self):
        view = ResolutionCentreView()
        mock_view = mock.Mock()
        mock_view.get_path_at_pos.return_value = (0, 0, 0, 0)
        self.assertFalse(
            view.on_button_press(mock_view, mock.Mock(x=0, y=0, button=1))
        )
        self.assertTrue(
            view.on_button_press(mock_view, mock.Mock(x=0, y=0, button=3))
        )
        mock_view.get_selection().path_is_selected.return_value = False
        self.assertFalse(
            view.on_button_press(mock_view, mock.Mock(x=0, y=0, button=3))
        )

    def test_on_button_release(self):
        view = ResolutionCentreView()
        view.context_menu = mock.Mock()
        mock_view = mock.Mock()
        mock_view.get_path_at_pos.return_value = (0, 0, 0, 0)
        self.assertFalse(
            view.on_button_release(mock_view, mock.Mock(x=0, y=0, button=1))
        )
        view.context_menu.popup_at_pointer.assert_not_called()
        self.assertTrue(
            view.on_button_release(mock_view, mock.Mock(x=0, y=0, button=3))
        )
        view.context_menu.popup_at_pointer.assert_called()

    def test_on_select_batch(self):
        # fairly redundant?
        view = ResolutionCentreView()
        view.last_pos = [0]
        view.liststore = mock.MagicMock()
        view.sync_tv = mock.Mock()
        mock_selection = mock.Mock()
        view.sync_tv.get_selection.return_value = mock_selection
        mock_row1 = mock.MagicMock(iter=0)
        mock_row1.__getitem__.return_value = 0
        mock_row2 = mock.MagicMock(iter=1)
        mock_row2.__getitem__.return_value = 0
        view.liststore.__iter__.return_value = [mock_row1,
                                                mock_row2]
        view.liststore.get_value.return_value = 0
        view.on_select_batch()
        mock_selection.select_iter.assert_called_with(1)
        # wrong batch num
        view.liststore.get_value.return_value = 1
        mock_selection.reset_mock()
        view.liststore.reset_mock()
        view.on_select_batch()
        view.liststore.__iter__.assert_called()
        # no last_pos
        view.liststore.reset_mock()
        view.last_pos = []
        view.on_select_batch()
        view.liststore.assert_not_called()

    def test_on_select_related(self):
        data = [
            {'batch_number': 1,
             'table_name': 'family',
             'table_id': 1,
             'values': {'id': 1,
                        'family': 'Sterculiaceae',
                        '_created': 0,
                        '_last_updated': 0},
             'operation': 'insert',
             'user': 'test',
             'timestamp': datetime(2023, 1, 1)},
            {'batch_number': 1,
             'table_name': 'family',
             'table_id': 2,
             'values': {'id': 2,
                        'family': 'Myrtaceae',
                        '_created': 0,
                        '_last_updated': 0},
             'operation': 'insert',
             'user': 'test',
             'timestamp': datetime(2023, 1, 1)},
            {'batch_number': 1,
             'table_name': 'genus',
             'table_id': 1,
             'values': {'id': 1,
                        'genus': 'Sterculia',
                        'family_id': 1,
                        '_created': 0,
                        '_last_updated': 0},
             'operation': 'insert',
             'user': 'test',
             'timestamp': datetime(2023, 1, 1)},
            {'batch_number': 1,
             'table_name': 'family',
             'table_id': 1,
             'values': {'id': 1,
                        'family': ['Malvaceae', 'Sterculiaceae'],
                        '_created': 0,
                        '_last_updated': 0},
             'operation': 'update',
             'user': 'test',
             'timestamp': datetime(2023, 1, 1)},
        ]

        to_sync = ToSync.__table__
        in_stmt = to_sync.insert(data)
        out_stmt = select(to_sync).order_by(to_sync.c.id.desc())
        with db.engine.begin() as conn:
            conn.execute(in_stmt)
            rows = conn.execute(out_stmt).all()
        view = ResolutionCentreView()
        self.assertEqual(len(rows), 4)
        for row in rows:
            view.add_row(row)
        view.sync_tv.set_cursor(0)
        view.last_pos = [0]
        view.on_select_related(None)
        self.assertEqual(len(view.get_selected_rows()), 3)
        # row 2 is the only record not related
        self.assertEqual([i.id for i in view.get_selected_rows()], [4, 3, 1])

    @mock.patch('bauble.plugins.synclone.sync.ResolverDialog.run')
    def test_on_resolve_btn_clicked_resolve_reponse(self, mock_run):
        data = {'batch_number': 1,
                'table_name': 'accession',
                'table_id': 1,
                'values': {'code': '2023.0001',
                           'species_id': 1,
                           'quantity_recvd': 2,
                           '_last_updated': 0,
                           '_created': 0},
                'operation': 'insert',
                'user': 'test',
                'timestamp': datetime(2023, 1, 1)}

        to_sync = ToSync.__table__
        in_stmt = to_sync.insert(data)
        out_stmt = select(to_sync).order_by(to_sync.c.id.desc())
        with db.engine.begin() as conn:
            conn.execute(in_stmt)
            rows = conn.execute(out_stmt).all()
        view = ResolutionCentreView()
        self.assertEqual(len(rows), 1)
        for row in rows:    # only one
            view.add_row(row)
        view.sync_tv.set_cursor(0)

        def _set_and_respond():
            rows[0]['values']['code'] = '2023.0003'
            return RESPONSE_RESOLVE

        mock_run.side_effect = _set_and_respond
        view.on_resolve_btn_clicked()

        with db.engine.begin() as conn:
            rows = conn.execute(out_stmt).all()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['values']['code'], '2023.0003')

    @mock.patch('bauble.plugins.synclone.sync.ResolverDialog.run')
    def test_on_resolve_btn_clicked_quit_reponse(self, mock_run):
        data = {'batch_number': 1,
                'table_name': 'accession',
                'table_id': 1,
                'values': {'code': '2023.0001',
                           'species_id': 1,
                           'quantity_recvd': 2,
                           '_last_updated': 0,
                           '_created': 0},
                'operation': 'insert',
                'user': 'test',
                'timestamp': datetime(2023, 1, 1)}

        to_sync = ToSync.__table__
        in_stmt = to_sync.insert(data)
        out_stmt = select(to_sync).order_by(to_sync.c.id.desc())
        with db.engine.begin() as conn:
            conn.execute(in_stmt)
            rows = conn.execute(out_stmt).all()
        view = ResolutionCentreView()
        self.assertEqual(len(rows), 1)
        for row in rows:    # only one
            view.add_row(row)
        view.sync_tv.set_cursor(0)

        def _set_and_respond():
            rows[0]['values']['code'] = '2023.0003'
            return RESPONSE_QUIT

        mock_run.side_effect = _set_and_respond
        view.on_resolve_btn_clicked()

        with db.engine.begin() as conn:
            rows = conn.execute(out_stmt).all()
        self.assertEqual(len(rows), 1)
        # no change
        self.assertEqual(rows[0]['values']['code'], '2023.0001')

    def test_on_remove_selected_btn_clicked(self):
        data = {'batch_number': 1,
                'table_name': 'accession',
                'table_id': 1,
                'values': {'code': '2023.0001',
                           'species_id': 1,
                           'quantity_recvd': 2,
                           '_last_updated': 0,
                           '_created': 0},
                'operation': 'insert',
                'user': 'test',
                'timestamp': datetime(2023, 1, 1)}

        to_sync = ToSync.__table__
        in_stmt = to_sync.insert(data)
        out_stmt = select(to_sync).order_by(to_sync.c.id.desc())
        with db.engine.begin() as conn:
            conn.execute(in_stmt)
            rows = conn.execute(out_stmt).all()
        view = ResolutionCentreView()
        self.assertEqual(len(rows), 1)
        for row in rows:    # only one
            view.add_row(row)
        view.sync_tv.set_cursor(0)

        view.on_remove_selected_btn_clicked()

        with db.engine.begin() as conn:
            rows = conn.execute(out_stmt).all()
        # no rows left
        self.assertEqual(len(rows), 0)

    @mock.patch('bauble.utils.yes_no_dialog')
    @mock.patch('bauble.plugins.synclone.sync.DBCloner')
    def test_on_sync_selected_btn_clicked_succeeds_all(self,
                                                       mock_cloner,
                                                       mock_dlog):
        mock_dlog.return_value = Gtk.ResponseType.YES
        data = [
            {'batch_number': 1,
             'table_name': 'family',
             'table_id': 1,
             'values': {'id': 1,
                        'family': 'Sterculiaceae',
                        '_created': 0,
                        '_last_updated': 0},
             'operation': 'insert',
             'user': 'test',
             'timestamp': datetime(2023, 1, 1)},
            {'batch_number': 1,
             'table_name': 'genus',
             'table_id': 1,
             'values': {'id': 1,
                        'genus': 'Sterculia',
                        'family_id': 1,
                        '_created': 0,
                        '_last_updated': 0},
             'operation': 'insert',
             'user': 'test',
             'timestamp': datetime(2023, 1, 1)},
            {'batch_number': 1,
             'table_name': 'family',
             'table_id': 1,
             'values': {'id': 1,
                        'family': ['Malvaceae', 'Sterculiaceae'],
                        '_created': 0,
                        '_last_updated': 0},
             'operation': 'update',
             'user': 'test',
             'timestamp': datetime(2023, 1, 1)},
        ]

        to_sync = ToSync.__table__
        in_stmt = to_sync.insert(data)
        out_stmt = select(to_sync).order_by(to_sync.c.id.desc())
        with db.engine.begin() as conn:
            conn.execute(in_stmt)
            rows = conn.execute(out_stmt).all()
        view = ResolutionCentreView()
        view.uri = 'sqlite:///:memory:'
        self.assertEqual(len(rows), 3)
        for row in rows:
            view.add_row(row)

        view.on_select_all()
        view.on_sync_selected_btn_clicked()

        mock_dlog.assert_called()
        mock_cloner.assert_called()

        with db.engine.begin() as conn:
            rows = conn.execute(out_stmt).all()
        # no rows left
        self.assertEqual(len(rows), 0)
        self.assertEqual([str(i) for i in self.session.query(Genus)],
                         ['Sterculia'])
        self.assertEqual([str(i) for i in self.session.query(Family)],
                         ['Malvaceae'])

    @mock.patch('bauble.utils.yes_no_dialog')
    @mock.patch('bauble.plugins.synclone.sync.DBCloner')
    def test_on_sync_selected_btn_clicked_succeeds_one(self,
                                                       mock_cloner,
                                                       mock_dlog):
        mock_dlog.return_value = Gtk.ResponseType.YES
        data = [
            {'batch_number': 1,
             'table_name': 'family',
             'table_id': 1,
             'values': {'id': 1,
                        'family': 'Sterculiaceae',
                        '_created': 0,
                        '_last_updated': 0},
             'operation': 'insert',
             'user': 'test',
             'timestamp': datetime(2023, 1, 1)},
            {'batch_number': 1,
             'table_name': 'genus',
             'table_id': 1,
             'values': {'id': 1,
                        'genus': 'Sterculia',
                        'family_id': 1,
                        '_created': 0,
                        '_last_updated': 0},
             'operation': 'insert',
             'user': 'test',
             'timestamp': datetime(2023, 1, 1)},
            {'batch_number': 1,
             'table_name': 'family',
             'table_id': 1,
             'values': {'id': 1,
                        'family': ['Malvaceae', 'Sterculiaceae'],
                        '_created': 0,
                        '_last_updated': 0},
             'operation': 'update',
             'user': 'test',
             'timestamp': datetime(2023, 1, 1)},
        ]

        to_sync = ToSync.__table__
        in_stmt = to_sync.insert(data)
        out_stmt = select(to_sync).order_by(to_sync.c.id.desc())
        with db.engine.begin() as conn:
            conn.execute(in_stmt)
            rows = conn.execute(out_stmt).all()
        view = ResolutionCentreView()
        view.uri = 'sqlite:///:memory:'
        self.assertEqual(len(rows), 3)
        for row in rows:
            view.add_row(row)

        view.sync_tv.set_cursor(2)
        view.on_sync_selected_btn_clicked()

        mock_dlog.assert_called()
        mock_cloner.assert_called()

        with db.engine.begin() as conn:
            rows = conn.execute(out_stmt).all()
        # 2 rows left
        self.assertEqual(len(rows), 2)
        self.assertEqual(self.session.query(Genus).all(), [])
        self.assertEqual([str(i) for i in self.session.query(Family)],
                         ['Sterculiaceae'])

    @mock.patch('bauble.plugins.synclone.sync.DBSyncroniser')
    def test_on_sync_selected_btn_clicked_fails_all(self, mock_sync):
        # similar to choosing to quit this does nothing to the database but
        # returns failed
        mock_sync().sync.return_value = [2, 3]
        data = [
            {'batch_number': 1,
             'table_name': 'family',
             'table_id': 1,
             'values': {'id': 1,
                        'family': 'Sterculiaceae',
                        '_created': 0,
                        '_last_updated': 0},
             'operation': 'insert',
             'user': 'test',
             'timestamp': datetime(2023, 1, 1)},
            {'batch_number': 1,
             'table_name': 'genus',
             'table_id': 1,
             'values': {'id': 1,
                        'genus': 'Sterculia',
                        '_created': 0,
                        '_last_updated': 0},
             'operation': 'insert',
             'user': 'test',
             'timestamp': datetime(2023, 1, 1)},
            {'batch_number': 1,
             'table_name': 'family',
             'table_id': 1,
             'values': {'id': 1,
                        'family': ['Malvaceae', 'Sterculiaceae'],
                        '_created': 0,
                        '_last_updated': 0},
             'operation': 'update',
             'user': 'test',
             'timestamp': datetime(2023, 1, 1)},
        ]

        to_sync = ToSync.__table__
        in_stmt = to_sync.insert(data)
        out_stmt = select(to_sync).order_by(to_sync.c.id.desc())
        with db.engine.begin() as conn:
            conn.execute(in_stmt)
            rows = conn.execute(out_stmt).all()
        view = ResolutionCentreView()
        self.assertEqual(len(rows), 3)
        for row in rows:
            view.add_row(row)

        view.on_select_all()
        view.on_sync_selected_btn_clicked()

        selected = view.get_selected_rows()
        self.assertEqual(len(selected), 2)
        self.assertEqual(selected[0]['values']['family'],
                         ['Malvaceae', 'Sterculiaceae'])
        self.assertEqual(selected[1]['values']['genus'], 'Sterculia')

    def test_on_sync_selection_changed_single(self):
        mock_selection = mock.Mock()
        mock_selection.count_selected_rows.return_value = 1
        view = ResolutionCentreView()
        view.on_sync_selection_changed(mock_selection)
        self.assertTrue(view.remove_selected_btn.get_sensitive())
        self.assertTrue(view.sync_selected_btn.get_sensitive())
        self.assertTrue(view.resolve_btn.get_sensitive())

    def test_on_sync_selection_changed_multi(self):
        mock_selection = mock.Mock()
        mock_selection.count_selected_rows.return_value = 2
        view = ResolutionCentreView()
        view.on_sync_selection_changed(mock_selection)
        self.assertTrue(view.remove_selected_btn.get_sensitive())
        self.assertTrue(view.sync_selected_btn.get_sensitive())
        self.assertFalse(view.resolve_btn.get_sensitive())

    def test_on_sync_selection_changed_none(self):
        mock_selection = mock.Mock()
        mock_selection.count_selected_rows.return_value = 0
        view = ResolutionCentreView()
        view.on_sync_selection_changed(mock_selection)
        self.assertFalse(view.remove_selected_btn.get_sensitive())
        self.assertFalse(view.sync_selected_btn.get_sensitive())
        self.assertFalse(view.resolve_btn.get_sensitive())

    def test_update_no_batch_num_uri(self):
        data = {'batch_number': 1,
                'table_name': 'accession',
                'table_id': 1,
                'values': {'code': '2023.0001',
                           'species_id': 1,
                           'quantity_recvd': 2,
                           '_last_updated': 0,
                           '_created': 0},
                'operation': 'insert',
                'user': 'test',
                'timestamp': datetime(2023, 1, 1)}

        to_sync = ToSync.__table__
        in_stmt = to_sync.insert(data)
        out_stmt = select(to_sync).order_by(to_sync.c.id.desc())
        with db.engine.begin() as conn:
            conn.execute(in_stmt)
            rows = conn.execute(out_stmt).all()
        view = ResolutionCentreView()
        for row in rows:    # only one
            view.add_row(row)
        view.update()
        self.assertEqual(len(view.liststore), 1)
        self.assertEqual(view.get_selected_rows(), [])
        self.assertFalse(view.remove_selected_btn.get_sensitive())
        self.assertFalse(view.sync_selected_btn.get_sensitive())
        self.assertFalse(view.resolve_btn.get_sensitive())

    def test_update_w_batch_num_uri(self):
        data = [
            {'batch_number': 1,
             'table_name': 'accession',
             'table_id': 1,
             'values': {'code': '2023.0001',
                        'species_id': 1,
                        'quantity_recvd': 2,
                        '_last_updated': 0,
                        '_created': 0},
             'operation': 'insert',
             'user': 'test',
             'timestamp': datetime(2023, 1, 1)},
            {'batch_number': 2,
             'table_name': 'family',
             'table_id': 1,
             'values': {'id': 1,
                        'family': 'Sterculiaceae',
                        '_created': 0,
                        '_last_updated': 0},
             'operation': 'insert',
             'user': 'test',
             'timestamp': datetime(2023, 1, 1)},
            {'batch_number': 2,
             'table_name': 'family',
             'table_id': 1,
             'values': {'id': 1,
                        'family': ['Malvaceae', 'Sterculiaceae'],
                        '_created': 0,
                        '_last_updated': 0},
             'operation': 'update',
             'user': 'test',
             'timestamp': datetime(2023, 1, 1)},
        ]

        to_sync = ToSync.__table__
        in_stmt = to_sync.insert(data)
        out_stmt = select(to_sync).order_by(to_sync.c.id.desc())
        with db.engine.begin() as conn:
            conn.execute(in_stmt)
            rows = conn.execute(out_stmt).all()
        view = ResolutionCentreView()
        for row in rows:
            view.add_row(row)
        view.update(['2', 'sqlite:///:memory:'])
        self.assertEqual(view.uri, 'sqlite:///:memory:')
        self.assertEqual(len(view.liststore), 3)
        self.assertEqual(len(view.get_selected_rows()), 2)
        self.assertTrue(view.remove_selected_btn.get_sensitive())
        self.assertTrue(view.sync_selected_btn.get_sensitive())
        self.assertFalse(view.resolve_btn.get_sensitive())