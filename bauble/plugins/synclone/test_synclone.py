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

from datetime import datetime
from unittest import mock

from sqlalchemy import select

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
        self.assertEqual(DBCloner.get_line_count(), 30)

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
