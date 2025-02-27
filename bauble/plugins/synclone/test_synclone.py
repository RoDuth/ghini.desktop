# Copyright 2023-2024 Ross Demuth <rossdemuth123@gmail.com>
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

from gi.repository import Gtk
from sqlalchemy import create_engine
from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError

import bauble
from bauble import db
from bauble import error
from bauble import utils
from bauble.plugins.garden import Accession
from bauble.plugins.garden import Location
from bauble.plugins.garden import Plant
from bauble.plugins.plants import Family
from bauble.plugins.plants import Genus
from bauble.plugins.plants import Species
from bauble.test import BaubleTestCase
from bauble.test import uri

from .clone import DBCloner
from .clone import DBCloneTool
from .sync import RESPONSE_QUIT
from .sync import RESPONSE_RESOLVE
from .sync import RESPONSE_SKIP
from .sync import RESPONSE_SKIP_RELATED
from .sync import DBResolveSyncTool
from .sync import DBSyncroniser
from .sync import DBSyncTool
from .sync import ResolutionCentreView
from .sync import ResolveCommandHandler
from .sync import ResolverDialog
from .sync import SyncRow
from .sync import ToSync


class DBClonerTests(BaubleTestCase):
    def add_data(self):
        # adding data using session ensures history entries
        fam = Family(epithet="Myrtaceae")
        gen = Genus(epithet="Syzygium", family=fam)
        sp = Species(epithet="luehmannii", genus=gen)
        loc = Location(code="LOC1")
        acc = Accession(code="2023.0001", species=sp)
        plt = Plant(code="1", quantity="1", location=loc, accession=acc)
        self.session.add_all([fam, gen, sp, loc, acc, plt])
        self.session.commit()

    def test_history_is_not_empty(self):
        self.add_data()
        id_ = self.session.query(db.History.id).first()
        self.assertIsNotNone(id_)

    def test_uri_setter_none(self):
        cloner = DBCloner()
        cloner.uri = None
        self.assertIsNone(cloner._uri)

    @mock.patch(
        "bauble.connmgr.start_connection_manager",
        return_value=(None, "sqlite:///test.db"),
    )
    def test_get_uri_succeeds(self, _mock_start_cm):
        self.assertEqual(str(DBCloner._get_uri()), "sqlite:///test.db")

    @mock.patch("bauble.plugins.synclone.clone.utils.message_dialog")
    @mock.patch(
        "bauble.connmgr.start_connection_manager", return_value=(None, uri)
    )
    def test_get_uri_fails(self, _mock_start_cm, mock_dialog):
        self.assertIsNone(DBCloner._get_uri())
        mock_dialog.assert_called()

    def test_fails_early_if_no_db_engine(self):
        orig_engine = db.engine
        db.engine = None
        self.assertRaises(error.DatabaseError, DBCloner._get_uri)
        self.assertRaises(error.DatabaseError, DBCloner.get_line_count)
        cloner = DBCloner()
        self.assertRaises(error.DatabaseError, next, cloner.run())
        self.assertRaises(error.DatabaseError, lambda: DBCloner().clone_engine)

        db.engine = orig_engine

    def test_clone_engine(self):
        cloner = DBCloner()
        cloner.uri = "sqlite:///test.db"
        self.assertEqual(str(cloner.clone_engine.url), "sqlite:///test.db")

    @mock.patch("bauble.plugins.synclone.clone.create_engine")
    def test_clone_engine_mssql_sets_fast_executemany(self, mock_create_eng):
        # MS SQL Server
        cloner = DBCloner()
        ms_uri = (
            "mssql://ghini:TestPWord@localhost:1434/"
            "BG?driver=ODBC+Driver+17+for+SQL+Server"
        )
        cloner.uri = ms_uri
        self.assertIsNotNone(cloner.clone_engine)
        mock_create_eng.assert_called_with(cloner.uri, fast_executemany=True)

    def test_drop_create_tables_creates_tables(self):
        from sqlalchemy import inspect

        cloner = DBCloner()
        cloner.uri = "sqlite:///:memory:"
        self.assertEqual(
            len(inspect(cloner.clone_engine).get_table_names()), 0
        )
        cloner.drop_create_tables()
        self.assertTrue(
            len(inspect(cloner.clone_engine).get_table_names()) > 20
        )

    def test_get_line_count(self):
        self.add_data()
        # institution, BaubleMeta, History and added in setUp
        self.assertAlmostEqual(DBCloner.get_line_count(), 30, delta=2)

    @mock.patch("bauble.task.set_message")
    def test_run(self, mock_set_message):
        self.add_data()
        cloner = DBCloner()
        cloner.uri = "sqlite:///:memory:"
        bauble.task.queue(cloner.run())
        mock_set_message.assert_called()
        with cloner.clone_engine.begin() as conn:
            stmt = Family.__table__.select()
            self.assertEqual(conn.execute(stmt).first().family, "Myrtaceae")
            stmt = Genus.__table__.select()
            self.assertEqual(conn.execute(stmt).first().genus, "Syzygium")
            stmt = Location.__table__.select()
            self.assertEqual(conn.execute(stmt).first().code, "LOC1")
            stmt = Accession.__table__.select()
            self.assertEqual(conn.execute(stmt).first().code, "2023.0001")
        # with error
        with (
            mock.patch(
                "sqlalchemy.engine.base.Connection.execute"
            ) as mock_execute,
            mock.patch(
                "bauble.plugins.synclone.clone.DBCloner.drop_create_tables"
            ),
            mock.patch(
                "bauble.plugins.synclone.clone.DBCloner.get_line_count"
            ),
            mock.patch(
                "bauble.plugins.synclone.clone.utils.message_details_dialog"
            ) as mock_dialog,
        ):
            mock_execute.side_effect = SQLAlchemyError
            bauble.task.queue(cloner.run())
            mock_dialog.assert_called()
            self.assertTrue(cloner._DBCloner__cancel)

    @mock.patch("bauble.task.set_message")
    def test_run_bulk_insert(self, mock_set_message):
        for i in range(200):
            self.session.add(Family(epithet=f"Family{i}"))
        self.session.commit()
        cloner = DBCloner()
        cloner.uri = "sqlite:///:memory:"
        with self.assertLogs(level="DEBUG") as logs:
            bauble.task.queue(cloner.run())
        self.assertTrue(
            any("adding 127 rows to clone" in i for i in logs.output)
        )
        mock_set_message.assert_called()

    @mock.patch("bauble.connmgr.start_connection_manager")
    @mock.patch("bauble.task.set_message")
    def test_start(self, mock_set_message, mock_start_cm):
        # without supplying uri
        temp_dir = tempfile.mkdtemp()
        clone_uri = f"sqlite:///{temp_dir}/test.db"
        mock_start_cm.return_value = (None, clone_uri)
        self.add_data()
        cloner = DBCloner()
        cloner.start()
        # cloner.start("sqlite:///:memory:")
        mock_set_message.assert_called()
        with cloner.clone_engine.begin() as conn:
            stmt = Family.__table__.select()
            self.assertEqual(conn.execute(stmt).first().family, "Myrtaceae")
            stmt = Genus.__table__.select()
            self.assertEqual(conn.execute(stmt).first().genus, "Syzygium")
            stmt = Location.__table__.select()
            self.assertEqual(conn.execute(stmt).first().code, "LOC1")
            stmt = Plant.__table__.select()
            self.assertEqual(conn.execute(stmt).first().code, "1")
        # with supplied uri
        mock_set_message.reset_mock()
        cloner.start("sqlite:///:memory:")
        mock_set_message.assert_called()
        with cloner.clone_engine.begin() as conn:
            stmt = Family.__table__.select()
            self.assertEqual(conn.execute(stmt).first().family, "Myrtaceae")
            stmt = Genus.__table__.select()
            self.assertEqual(conn.execute(stmt).first().genus, "Syzygium")
            stmt = Location.__table__.select()
            self.assertEqual(conn.execute(stmt).first().code, "LOC1")
            stmt = Plant.__table__.select()
            self.assertEqual(conn.execute(stmt).first().code, "1")

    @mock.patch("bauble.task.set_message")
    def test_datetimes_transfer_correctly(self, mock_set_message):
        self.add_data()
        cloner = DBCloner()
        cloner.uri = "sqlite:///:memory:"
        bauble.task.queue(cloner.run())
        mock_set_message.assert_called()

        with db.engine.begin() as conn:
            stmt = Accession.__table__.select()
            self.assertAlmostEqual(
                conn.execute(stmt).first()._created.timestamp(),
                datetime.now().timestamp(),
                delta=2,
            )

        with cloner.clone_engine.begin() as conn:
            stmt = Accession.__table__.select()
            self.assertAlmostEqual(
                conn.execute(stmt).first()._created.timestamp(),
                datetime.now().timestamp(),
                delta=2,
            )

    @mock.patch("bauble.task.set_message")
    def test_record_clone_point(self, _mock_set_message):
        self.add_data()
        cloner = DBCloner()
        cloner.uri = make_url("sqlite:///:memory:")
        cloner.drop_create_tables()
        # _record_clone_point is called by run.
        bauble.task.queue(cloner.run())
        meta_table = bauble.meta.BaubleMeta.__table__
        stmt = select(meta_table.c.value).where(
            meta_table.c.name == "clone_history_id"
        )
        with cloner.clone_engine.begin() as conn:
            self.assertEqual(conn.execute(stmt).scalar(), "7")
        # add an extra history entry and run it again should update not insert
        hist = db.History.__table__
        insert = hist.insert().values(
            {
                "table_name": "family",
                "table_id": 100,
                "values": {"family": "Orchidaceae"},
                "operation": "insert",
                "timestamp": utils.utcnow_naive(),
            }
        )
        with cloner.clone_engine.begin() as conn:
            conn.execute(insert)

        cloner._record_clone_point()
        with cloner.clone_engine.begin() as conn:
            self.assertEqual(conn.execute(stmt).scalar(), "8")

    @mock.patch("bauble.task.set_message")
    def test_record_clone_point_not_set_w_no_history(self, _mock_set_message):
        cloner = DBCloner()
        cloner.uri = "sqlite:///:memory:"
        cloner.drop_create_tables()
        # _record_clone_point is called by run.
        bauble.task.queue(cloner.run())
        meta_table = bauble.meta.BaubleMeta.__table__
        stmt = select(meta_table.c.value).where(
            meta_table.c.name == "clone_history_id"
        )
        with cloner.clone_engine.begin() as conn:
            self.assertEqual(conn.execute(stmt).scalar(), None)
        # add an extra history entry and it should set
        hist = db.History.__table__
        insert = hist.insert().values(
            {
                "table_name": "family",
                "table_id": 100,
                "values": {"family": "Orchidaceae"},
                "operation": "insert",
                "timestamp": utils.utcnow_naive(),
            }
        )
        with cloner.clone_engine.begin() as conn:
            conn.execute(insert)

        cloner._record_clone_point()
        with cloner.clone_engine.begin() as conn:
            self.assertEqual(conn.execute(stmt).scalar(), "1")

    @mock.patch("bauble.plugins.synclone.clone.DBCloner")
    @mock.patch("bauble.plugins.synclone.clone.utils.yes_no_dialog")
    @mock.patch("bauble.plugins.synclone.clone.bauble.command_handler")
    def test_db_clone_tool_start(self, mock_handler, mock_dialog, mock_cloner):
        mock_dialog.return_value = True
        tool = DBCloneTool()
        tool.start()
        mock_handler.assert_called_with("home", None)
        mock_cloner().start.assert_called()
        # allows backing out
        mock_dialog.return_value = False
        mock_handler.reset_mock()
        mock_cloner.reset_mock()
        tool.start()
        mock_handler.assert_not_called()
        mock_cloner().start.assert_not_called()


class DBSyncTests(BaubleTestCase):
    def test_fails_early_if_no_db_engine(self):
        orig_engine = db.engine
        db.engine = None
        clone_uri = "sqlite:///test.db"
        self.assertRaises(
            error.DatabaseError, ToSync.add_batch_from_uri, clone_uri
        )
        row = mock.Mock()
        self.assertRaises(
            error.DatabaseError, DBSyncroniser([row])._sync_row, row
        )
        db.engine = orig_engine

    def test_fails_early_if_no_db_session(self):
        db.Session = None
        clone_uri = "sqlite:///test.db"
        self.assertRaises(
            error.DatabaseError, ToSync.add_batch_from_uri, clone_uri
        )

    def add_clone_history(self, clone_engine, history_id, values):
        # add clone_history_id
        meta = bauble.meta.BaubleMeta.__table__
        meta_stmt = meta.insert().values(
            {"name": "clone_history_id", "value": history_id}
        )
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
        values = {
            "table_name": "family",
            "table_id": 100,
            "values": {"family": "Orchidaceae"},
            "operation": "insert",
            "timestamp": datetime.now(),
        }
        clone_engine = create_engine(clone_uri)
        self.add_clone_history(clone_engine, 0, values)

        batch_num = ToSync.add_batch_from_uri(clone_uri)
        self.assertEqual(batch_num, "1")

        result = self.session.query(ToSync).all()
        self.assertEqual(len(result), 1)
        first = result[0]
        self.assertEqual(first.batch_number, 1)
        self.assertEqual(first.table_name, "family")
        self.assertEqual(first.table_id, 100)
        self.assertEqual(first.operation, "insert")
        self.assertEqual(first.user, None)
        self.assertAlmostEqual(
            first.timestamp.timestamp(), datetime.now().timestamp(), delta=2
        )
        self.assertEqual(first.values, {"family": "Orchidaceae"})

    def test_to_sync_add_batch_fails(self):
        temp_dir = tempfile.mkdtemp()
        clone_uri = f"sqlite:///{temp_dir}/test.db"
        values = {
            "table_name": "family",
            "table_id": 100,
            "values": {"family": "Orchidaceae"},
            "operation": "insert",
            "timestamp": datetime.now(),
        }
        clone_engine = create_engine(clone_uri)
        self.add_clone_history(clone_engine, None, values)

        self.assertRaises(
            bauble.error.BaubleError, ToSync.add_batch_from_uri, clone_uri
        )

    def test_to_sync_remove_row(self):
        # use a file here so it is persistent
        # add a history entry
        temp_dir = tempfile.mkdtemp()
        clone_uri = f"sqlite:///{temp_dir}/test.db"
        values = {
            "table_name": "family",
            "table_id": 100,
            "values": {"family": "Orchidaceae"},
            "operation": "insert",
            "timestamp": datetime.now(),
        }
        clone_engine = create_engine(clone_uri)
        self.add_clone_history(clone_engine, 0, values)

        batch_num = ToSync.add_batch_from_uri(clone_uri)
        self.assertEqual(batch_num, "1")

        result = self.session.query(ToSync).all()
        self.assertEqual(len(result), 1)
        first = result[0]
        self.assertEqual(first.values, {"family": "Orchidaceae"})

        with db.engine.begin() as conn:
            ToSync.remove_row(first, conn)

        result = self.session.query(ToSync).all()
        self.assertEqual(len(result), 0)

    def test_sync_raises_if_cant_set_instance(self):
        data = {
            "batch_number": 1,
            "table_name": "family",
            "table_id": 1,
            "values": {
                "id": 1,
            },
            "operation": "insert",
            "user": "test",
            "timestamp": datetime(2024, 2, 17),
        }

        to_sync = ToSync.__table__
        in_stmt = to_sync.insert(data)
        out_stmt = select(to_sync)
        with db.engine.begin() as conn:
            conn.execute(in_stmt)
            first = conn.execute(out_stmt).first()
            row = SyncRow({}, first, conn)
            # NOTE calling instance before sync() on an insert. (i.e. before
            # the instance can exist)
            self.assertRaises(error.DatabaseError, lambda: row.instance)

    def test_sync_row_values_removes_id_last_updated_created(self):
        data = {
            "batch_number": 1,
            "table_name": "family",
            "table_id": 100,
            "values": {
                "id": 100,
                "family": ["Malvaceae", "Sterculiaceae"],
                "_last_updated": 0,
                "_created": 0,
            },
            "operation": "update",
            "user": "test",
            "timestamp": datetime(2023, 1, 1),
        }

        to_sync = ToSync.__table__
        in_stmt = to_sync.insert(data)
        out_stmt = select(to_sync)
        with db.engine.begin() as conn:
            conn.execute(in_stmt)
            first = conn.execute(out_stmt).first()
            row = SyncRow({}, first, conn)
            self.assertIsNone(row.values.get("id"))
            self.assertIsNone(row.values.get("_last_updated"))
            self.assertIsNone(row.values.get("_created"))

    def test_sync_row_values_ignores_non_foreign_key_id(self):
        # NOTE this should never occur (a ..._id field should always be a
        # forgeign_key or tag obj_id) but there is an escape in case it ever
        # does become the case.
        data = {
            "values": {
                "id": 20,
                "test_id": 1,
                "_created": 0,
                "_last_updated": 0,
            }
        }
        row = mock.MagicMock()
        row.__getitem__.side_effect = data.__getitem__
        row.table_name = "family"
        row.table_id = 1
        with db.engine.begin() as conn:
            row = SyncRow({"family": {"test_id": 5}}, row, conn)
            mock_table = mock.Mock()
            mock_table.c = {"test_id": mock.Mock(foreign_keys=set())}
            row.table = mock_table
            self.assertEqual(row.values.get("test_id"), 1)

    def test_sync_row_updates_ids_from_id_map_insert(self):
        # insert
        data = {
            "batch_number": 1,
            "table_name": "genus",
            "table_id": 10,
            "values": {
                "id": 10,
                "family_id": 10,
                "genus": "Sterculia",
                "_last_updated": 0,
                "_created": 0,
            },
            "operation": "insert",
            "user": "test",
            "timestamp": datetime(2023, 1, 1),
        }

        to_sync = ToSync.__table__
        in_stmt = to_sync.insert(data)
        out_stmt = select(to_sync)
        with db.engine.begin() as conn:
            conn.execute(in_stmt)
            first = conn.execute(out_stmt).first()
            row = SyncRow({"family": {10: 2}}, first, conn)
            self.assertEqual(row.values.get("family_id"), 2)

    def test_sync_row_updates_ids_from_id_map_insert_tag(self):
        # insert tag
        data = {
            "batch_number": 1,
            "table_name": "tagged_obj",
            "table_id": 1,
            "values": {
                "id": 1,
                "obj_id": 10,
                "obj_class": "bauble.plugins.plants.species_model.Species",
                "tag_id": 1,
                "_last_updated": 0,
                "_created": 0,
            },
            "operation": "insert",
            "user": "test",
            "timestamp": datetime(2023, 1, 1),
        }

        to_sync = ToSync.__table__
        in_stmt = to_sync.insert(data)
        out_stmt = select(to_sync)
        with db.engine.begin() as conn:
            conn.execute(in_stmt)
            first = conn.execute(out_stmt).first()
            row = SyncRow({"species": {10: 3}}, first, conn)
            self.assertEqual(row.values.get("obj_id"), 3)

    def test_sync_row_updates_ids_from_id_map_update(self):
        # update
        data = {
            "batch_number": 1,
            "table_name": "genus",
            "table_id": 10,
            "values": {
                "id": 10,
                "family_id": [10, 2],
                "genus": "Sterculia",
                "_last_updated": 0,
                "_created": 0,
            },
            "operation": "update",
            "user": "test",
            "timestamp": datetime(2023, 1, 1),
        }

        to_sync = ToSync.__table__
        in_stmt = to_sync.insert(data)
        out_stmt = select(to_sync)
        with db.engine.begin() as conn:
            conn.execute(in_stmt)
            first = conn.execute(out_stmt).first()
            row = SyncRow({"family": {10: 4}}, first, conn)
            self.assertEqual(row.values.get("family_id"), [4, 2])

    def test_sync_row_gets_correct_instance(self):
        fam = Family(id=4, family="Sterculiaceae")
        self.session.add(fam)
        self.session.commit()

        data = {
            "batch_number": 1,
            "table_name": "family",
            "table_id": 10,
            "values": {
                "id": 10,
                "family": ["Malvaceae", "Sterculiaceae"],
                "_last_updated": 0,
                "_created": 0,
            },
            "operation": "update",
            "user": "test",
            "timestamp": datetime(2023, 1, 1),
        }

        to_sync = ToSync.__table__
        in_stmt = to_sync.insert(data)
        out_stmt = select(to_sync)
        with db.engine.begin() as conn:
            conn.execute(in_stmt)
            first = conn.execute(out_stmt).first()
            row = SyncRow({"family": {10: 4}}, first, conn)
            self.assertEqual(row.table_id, 4)
            self.assertEqual(row.instance.id, fam.id)

    def test_sync_row_sync_update_no_val_to_update_doesnt_add_history(self):
        fam = Family(id=4, family="Sterculiaceae")
        self.session.add(fam)
        self.session.commit()

        data = {
            "batch_number": 1,
            "table_name": "family",
            "table_id": 4000,
            "values": {
                "id": 4000,
                "family": "Sterculiaceae",
                "_last_updated": 0,
                "_created": 0,
            },
            "operation": "update",
            "user": "test",
            "timestamp": datetime(2023, 1, 1),
        }

        to_sync = ToSync.__table__
        in_stmt = to_sync.insert(data)
        out_stmt = select(to_sync)
        with db.engine.begin() as conn:
            conn.execute(in_stmt)
            first = conn.execute(out_stmt).first()
            row = SyncRow({}, first, conn)
            row.sync()
        self.session.expire(fam)
        self.assertEqual(fam.family, "Sterculiaceae")
        # check history entered correctly
        hist = self.session.query(db.History).all()
        # just the add not the sync has added history
        self.assertEqual(len(hist), 1)

    def test_sync_row_sync_update_no_change_doesnt_add_history(self):
        fam = Family(id=4, family="Sterculiaceae")
        self.session.add(fam)
        self.session.commit()

        data = {
            "batch_number": 1,
            "table_name": "family",
            "table_id": 4,
            "values": {
                "id": 4,
                "family": "Sterculiaceae",
                "_last_updated": 0,
                "_created": 0,
            },
            "operation": "update",
            "user": "test",
            "timestamp": datetime(2023, 1, 1),
        }

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
        self.assertEqual(fam.family, "Sterculiaceae")
        # check history entered correctly
        hist = self.session.query(db.History).all()
        # just the add not the sync has added history
        self.assertEqual(len(hist), 1)

    def test_sync_row_sync_update(self):
        fam = Family(
            id=4, family="Sterculiaceae", _last_updated=datetime(2023, 1, 1)
        )
        self.session.add(fam)
        self.session.commit()
        start_date = str(fam._last_updated)

        data = {
            "batch_number": 1,
            "table_name": "family",
            "table_id": 4,
            "values": {
                "id": 4,
                "family": ["Malvaceae", "Sterculiaceae"],
                "_last_updated": 0,
                "_created": 0,
            },
            "operation": "update",
            "user": "test",
            "timestamp": datetime(2023, 1, 1),
        }

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
        self.assertEqual(fam.family, "Malvaceae")
        # check history entered correctly
        hist = self.session.query(db.History).all()
        self.assertEqual(len(hist), 2)
        self.assertEqual(hist[1].table_id, 4)
        self.assertEqual(hist[1].operation, "update")
        self.assertEqual(hist[1].table_name, "family")
        self.assertEqual(hist[1].user, "test")
        self.assertAlmostEqual(
            hist[1].timestamp.timestamp(), datetime.now().timestamp(), delta=2
        )
        self.assertEqual(
            hist[1].values["family"], ["Malvaceae", "Sterculiaceae"]
        )
        # assert that _last_updated change is recorded
        self.assertEqual(
            hist[1].values["_last_updated"],
            [str(fam._last_updated), start_date],
        )

    def test_sync_row_sync_insert(self):
        data = {
            "batch_number": 1,
            "table_name": "family",
            "table_id": 4,
            "values": {
                "id": 4,
                "family": "Malvaceae",
                "_last_updated": 0,
                "_created": 0,
            },
            "operation": "insert",
            "user": "test",
            "timestamp": datetime(2023, 1, 1),
        }

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
            self.assertEqual(id_map, {"family": {4: 1}})
        fam = self.session.query(Family).filter(Family.id == 1).first()
        self.assertEqual(fam.family, "Malvaceae")
        # check history entered correctly
        hist = self.session.query(db.History).all()
        self.assertEqual(len(hist), 1)
        self.assertEqual(hist[0].table_id, 1)
        self.assertEqual(hist[0].operation, "insert")
        self.assertEqual(hist[0].table_name, "family")
        self.assertEqual(hist[0].user, "test")
        self.assertAlmostEqual(
            hist[0].timestamp.timestamp(), datetime.now().timestamp(), delta=2
        )
        self.assertEqual(hist[0].values["family"], "Malvaceae")

    def test_sync_row_sync_delete(self):
        fam = Family(id=4, family="Sterculiaceae")
        self.session.add(fam)
        self.session.commit()

        data = {
            "batch_number": 1,
            "table_name": "family",
            "table_id": 4,
            "values": {
                "id": 4,
                "family": "Sterculiaceae",
                "_last_updated": 0,
                "_created": 0,
            },
            "operation": "delete",
            "user": "test",
            "timestamp": datetime(2023, 1, 1),
        }

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
        self.assertEqual(hist[1].operation, "delete")
        self.assertEqual(hist[1].table_name, "family")
        self.assertEqual(hist[1].user, "test")
        self.assertAlmostEqual(
            hist[1].timestamp.timestamp(), datetime.now().timestamp(), delta=2
        )
        self.assertEqual(hist[1].values["family"], "Sterculiaceae")

    def test_resolver_dialog_edit_text_cell(self):
        data = {
            "batch_number": 1,
            "table_name": "family",
            "table_id": 4,
            "values": {
                "family": "Sterculiaceae",
                "_last_updated": 0,
                "_created": 0,
            },
            "operation": "insert",
            "user": "test",
            "timestamp": datetime(2023, 1, 1),
        }

        to_sync = ToSync.__table__
        in_stmt = to_sync.insert(data)
        out_stmt = select(to_sync)
        with db.engine.begin() as conn:
            conn.execute(in_stmt)
            first = conn.execute(out_stmt).first()

        resolver = ResolverDialog(row=first)
        path = list(resolver.row["values"]).index("family")
        resolver.on_value_cell_edited(None, path, "Malvaceae")
        self.assertCountEqual(
            resolver.row["values"].items(),
            {"family": "Malvaceae", "_last_updated": 0, "_created": 0}.items(),
        )

    def test_resolver_dialog_edit_int_cell(self):
        data = {
            "batch_number": 1,
            "table_name": "accession",
            "table_id": 1,
            "values": {
                "code": "2023.0001",
                "species_id": 1,
                "quantity_recvd": 2,
                "_last_updated": 0,
                "_created": 0,
            },
            "operation": "insert",
            "user": "test",
            "timestamp": datetime(2023, 1, 1),
        }

        to_sync = ToSync.__table__
        in_stmt = to_sync.insert(data)
        out_stmt = select(to_sync)
        with db.engine.begin() as conn:
            conn.execute(in_stmt)
            first = conn.execute(out_stmt).first()

        resolver = ResolverDialog(row=first)
        path = list(resolver.row["values"]).index("quantity_recvd")
        resolver.on_value_cell_edited(None, path, "3")
        self.assertCountEqual(
            resolver.row["values"].items(),
            {
                "code": "2023.0001",
                "species_id": 1,
                "quantity_recvd": 3,
                "_last_updated": 0,
                "_created": 0,
            }.items(),
        )

    def test_resolver_dialog_edit_int_cell_wrong_type(self):
        data = {
            "batch_number": 1,
            "table_name": "accession",
            "table_id": 1,
            "values": {
                "code": "2023.0001",
                "species_id": 1,
                "quantity_recvd": 2,
                "_last_updated": 0,
                "_created": 0,
            },
            "operation": "insert",
            "user": "test",
            "timestamp": datetime(2023, 1, 1),
        }

        to_sync = ToSync.__table__
        in_stmt = to_sync.insert(data)
        out_stmt = select(to_sync)
        with db.engine.begin() as conn:
            conn.execute(in_stmt)
            first = conn.execute(out_stmt).first()

        resolver = ResolverDialog(row=first)
        path = list(resolver.row["values"]).index("quantity_recvd")
        resolver.on_value_cell_edited(None, path, "a")
        # does not change
        self.assertCountEqual(
            resolver.row["values"].items(),
            {
                "code": "2023.0001",
                "species_id": 1,
                "quantity_recvd": 2,
                "_last_updated": 0,
                "_created": 0,
            }.items(),
        )

    def test_resolver_dialog_edit_datetime_cell(self):
        data = {
            "batch_number": 1,
            "table_name": "accession",
            "table_id": 1,
            "values": {
                "code": "2023.0001",
                "species_id": 1,
                "quantity_recvd": 2,
                "_last_updated": 0,
                "_created": 0,
            },
            "operation": "insert",
            "user": "test",
            "timestamp": datetime(2023, 1, 1),
        }

        to_sync = ToSync.__table__
        in_stmt = to_sync.insert(data)
        out_stmt = select(to_sync)
        with db.engine.begin() as conn:
            conn.execute(in_stmt)
            first = conn.execute(out_stmt).first()

        resolver = ResolverDialog(row=first)
        path = list(resolver.row["values"]).index("_last_updated")
        resolver.on_value_cell_edited(None, path, "29/5/23")
        self.assertCountEqual(
            resolver.row["values"].items(),
            {
                "code": "2023.0001",
                "species_id": 1,
                "quantity_recvd": 2,
                "_last_updated": "29/5/23",
                "_created": 0,
            }.items(),
        )

    @mock.patch("bauble.plugins.synclone.sync.ResolverDialog.run")
    def test_dbsyncroniser_can_resolve_on_fly(self, mock_run):
        fam = Family(id=4, family="Sterculiaceae")
        gen = Genus(id=1, genus="Sterculia", family=fam)
        self.session.add_all([fam, gen])
        self.session.commit()
        # This data should raise an SQLAlchemyError (invalid genus foreign
        # keys)
        data = [
            {
                "batch_number": 1,
                "table_name": "species",
                "table_id": 1,
                "values": {
                    "id": 1,
                    "sp": "quadrifida",
                    "genus_id": 4,
                    "_last_updated": "29/5/23",
                    "_created": 0,
                },
                "operation": "insert",
                "user": "test",
                "timestamp": datetime(2023, 1, 1),
            }
        ]

        to_sync = ToSync.__table__
        in_stmt = to_sync.insert(data)
        out_stmt = select(to_sync).order_by(to_sync.c.id.desc())
        with db.engine.begin() as conn:
            conn.execute(in_stmt)
            rows = conn.execute(out_stmt).all()
        synchroniser = DBSyncroniser(rows)

        # mutate the row and set return_value to RESPONSE_RESOLVE...  Tests
        # that values is set back to start_values
        def _set_and_respond():
            rows[0]["values"]["genus_id"] = 1
            return RESPONSE_RESOLVE

        mock_run.side_effect = _set_and_respond

        failed = synchroniser.sync()
        self.assertEqual(len(failed), 0)
        self.assertEqual(rows[0]["values"]["genus_id"], 1)
        # species added
        self.assertEqual(
            [str(i) for i in self.session.query(Species)],
            ["Sterculia quadrifida"],
        )

    @mock.patch("bauble.plugins.synclone.sync.ResolverDialog.run")
    def test_dbsyncroniser_rolls_back_returns_failed_on_quit(self, mock_run):
        fam = Family(id=4, family="Sterculiaceae")
        gen = Genus(id=1, genus="Sterculia", family=fam)
        self.session.add_all([fam, gen])
        self.session.commit()
        # This data should raise an SQLAlchemyError (invalid foreign keys for
        # accession, if reversed this should work)
        data = [
            {
                "batch_number": 1,
                "table_name": "accession",
                "table_id": 1,
                "values": {
                    "id": 1,
                    "code": "2023.0001",
                    "species_id": 1,
                    "quantity_recvd": 2,
                    "_last_updated": "29/5/23",
                    "_created": 0,
                },
                "operation": "insert",
                "user": "test",
                "timestamp": datetime(2023, 1, 1),
            },
            {
                "batch_number": 1,
                "table_name": "species",
                "table_id": 1,
                "values": {
                    "id": 1,
                    "sp": "quadrifida",
                    "genus_id": 1,
                    "_last_updated": "29/5/23",
                    "_created": 0,
                },
                "operation": "insert",
                "user": "test",
                "timestamp": datetime(2023, 1, 1),
            },
        ]

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
            rows[1]["values"]["code"] = "2023.0003"
            return RESPONSE_QUIT

        mock_run.side_effect = _set_and_respond
        # Respond QUIT
        failed = synchroniser.sync()
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed, [1])
        self.assertEqual(rows[1]["values"]["code"], "2023.0001")
        # nothing added
        self.assertEqual(self.session.query(Species).all(), [])
        self.assertEqual(self.session.query(Accession).all(), [])

    @mock.patch("bauble.utils.yes_no_dialog")
    @mock.patch("bauble.plugins.synclone.sync.ResolverDialog.run")
    def test_dbsyncroniser_on_delete_asks_quit(self, mock_run, mock_dialog):
        # NOTE if quiting this way failed is not returned
        fam = Family(id=4, family="Sterculiaceae")
        gen = Genus(id=1, genus="Sterculia", family=fam)
        self.session.add_all([fam, gen])
        self.session.commit()
        # This data should raise an SQLAlchemyError (invalid foreign keys for
        # accession, if reversed this should work)
        data = [
            {
                "batch_number": 1,
                "table_name": "accession",
                "table_id": 1,
                "values": {
                    "id": 1,
                    "code": "2023.0001",
                    "species_id": 1,
                    "quantity_recvd": 2,
                    "_last_updated": "29/5/23",
                    "_created": 0,
                },
                "operation": "insert",
                "user": "test",
                "timestamp": datetime(2023, 1, 1),
            },
            {
                "batch_number": 1,
                "table_name": "species",
                "table_id": 1,
                "values": {
                    "id": 1,
                    "sp": "quadrifida",
                    "genus_id": 1,
                    "_last_updated": "29/5/23",
                    "_created": 0,
                },
                "operation": "insert",
                "user": "test",
                "timestamp": datetime(2023, 1, 1),
            },
        ]

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
            rows[1]["values"]["code"] = "2023.0003"
            return Gtk.ResponseType.DELETE_EVENT

        mock_run.side_effect = _set_and_respond
        mock_dialog.return_value = Gtk.ResponseType.YES
        failed = synchroniser.sync()
        self.assertEqual(len(failed), 0)
        self.assertEqual(rows[1]["values"]["code"], "2023.0001")
        # nothing added
        self.assertEqual(self.session.query(Species).all(), [])
        self.assertEqual(self.session.query(Accession).all(), [])
        mock_dialog.assert_called()

    @mock.patch("bauble.plugins.synclone.sync.ResolverDialog.run")
    def test_dbsyncroniser_fails_duplicate_cascades_on_skip_related(
        self, mock_run
    ):
        # this is one of the harder to resolve scenario that would requires
        # user input to sort out
        fam = Family(id=4, family="Sterculiaceae")
        gen = Genus(id=1, genus="Sterculia", family=fam)
        self.session.add_all([fam, gen])
        self.session.commit()
        # This data should raise an SQLAlchemyError (unique constraint family,
        # genus)
        data = [
            {
                "batch_number": 1,
                "table_name": "family",
                "table_id": 1,
                "values": {
                    "id": 1,
                    "family": "Sterculiaceae",
                    "_last_updated": 0,
                    "_created": 0,
                },
                "operation": "insert",
                "user": "test",
                "timestamp": datetime(2023, 1, 1),
            },
            {
                "batch_number": 1,
                "table_name": "genus",
                "table_id": 1,
                "values": {
                    "id": 1,
                    "genus": "Sterculia",
                    "family_id": 1,
                    "_last_updated": 0,
                    "_created": 0,
                },
                "operation": "insert",
                "user": "test",
                "timestamp": datetime(2023, 1, 1),
            },
            {
                "batch_number": 1,
                "table_name": "species",
                "table_id": 1,
                "values": {
                    "id": 1,
                    "sp": "quadrifida",
                    "genus_id": 1,
                    "_last_updated": "29/5/23",
                    "_created": 0,
                },
                "operation": "insert",
                "user": "test",
                "timestamp": datetime(2023, 1, 1),
            },
        ]

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

    @mock.patch("bauble.plugins.synclone.sync.ResolverDialog.run")
    def test_dbsyncroniser_returns_failed_on_skip(self, mock_run):
        fam = Family(id=4, family="Sterculiaceae")
        gen = Genus(id=1, genus="Sterculia", family=fam)
        self.session.add_all([fam, gen])
        self.session.commit()
        # This data should raise an SQLAlchemyError (invalid foreign keys for
        # accession, if reversed this should work)
        data = [
            {
                "batch_number": 1,
                "table_name": "accession",
                "table_id": 1,
                "values": {
                    "id": 1,
                    "code": "2023.0001",
                    "species_id": 1,
                    "quantity_recvd": 2,
                    "_last_updated": "29/5/23",
                    "_created": 0,
                },
                "operation": "insert",
                "user": "test",
                "timestamp": datetime(2023, 1, 1),
            },
            {
                "batch_number": 1,
                "table_name": "species",
                "table_id": 1,
                "values": {
                    "id": 1,
                    "sp": "quadrifida",
                    "genus_id": 1,
                    "_last_updated": "29/5/23",
                    "_created": 0,
                },
                "operation": "insert",
                "user": "test",
                "timestamp": datetime(2023, 1, 1),
            },
        ]

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
            rows[1]["values"]["code"] = "2023.0003"
            return RESPONSE_SKIP

        mock_run.side_effect = _set_and_respond
        # Respond SKIP
        failed = synchroniser.sync()
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed, [1])
        self.assertEqual(rows[1]["values"]["code"], "2023.0001")
        # species added
        self.assertEqual(
            [str(i) for i in self.session.query(Species)],
            ["Sterculia quadrifida"],
        )
        self.assertEqual(self.session.query(Accession).all(), [])

    @mock.patch("bauble.plugins.synclone.sync.ResolverDialog.run")
    def test_dbsyncroniser_failed_id_map_cascades_on_skip_related(
        self, mock_run
    ):
        fam = Family(id=4, family="Sterculiaceae")
        gen = Genus(id=1, genus="Sterculia", family=fam)
        self.session.add_all([fam, gen])
        self.session.commit()
        # This data should raise an SQLAlchemyError (invalid foreign keys for
        # species)
        data = [
            {
                "batch_number": 1,
                "table_name": "species",
                "table_id": 1,
                "values": {
                    "id": 1,
                    "sp": "quadrifida",
                    "_last_updated": "29/5/23",
                    "_created": 0,
                },
                "operation": "insert",
                "user": "test",
                "timestamp": datetime(2023, 1, 1),
            },
            {
                "batch_number": 1,
                "table_name": "accession",
                "table_id": 1,
                "values": {
                    "id": 1,
                    "code": "2023.0001",
                    "species_id": 1,
                    "quantity_recvd": 2,
                    "_last_updated": "29/5/23",
                    "_created": 0,
                },
                "operation": "insert",
                "user": "test",
                "timestamp": datetime(2023, 1, 1),
            },
        ]

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
            rows[1]["values"]["sp"] = "sp."
            return RESPONSE_SKIP_RELATED

        mock_run.side_effect = _set_and_respond
        # Respond SKIP_RELATED
        failed = synchroniser.sync()
        self.assertEqual(
            synchroniser.id_map, {"species": {1: None}, "accession": {1: None}}
        )
        self.assertEqual(len(failed), 2)
        self.assertEqual(failed, [1, 2])
        self.assertEqual(rows[1]["values"]["sp"], "quadrifida", rows[0])
        # nothing added
        self.assertEqual(self.session.query(Species).all(), [])
        self.assertEqual(self.session.query(Accession).all(), [])

    @mock.patch("bauble.gui")
    def test_dbsyncroniser_succeeds(self, _mock_gui):
        # mock bauble.gui just to cover the tags_menu_manager line
        data = [
            {
                "batch_number": 1,
                "table_name": "family",
                "table_id": 1,
                "values": {
                    "id": 1,
                    "family": "Malvaceae",
                    "_last_updated": 0,
                    "_created": 0,
                },
                "operation": "insert",
                "user": "test",
                "timestamp": datetime(2023, 1, 1),
            },
            {
                "batch_number": 1,
                "table_name": "genus",
                "table_id": 1,
                "values": {
                    "id": 1,
                    "genus": "Sterculia",
                    "family_id": 1,
                    "_last_updated": 0,
                    "_created": 0,
                },
                "operation": "insert",
                "user": "test",
                "timestamp": datetime(2023, 1, 1),
            },
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
        self.assertEqual(
            [str(i) for i in self.session.query(Genus)], ["Sterculia"]
        )
        self.assertEqual(
            [str(i) for i in self.session.query(Family)], ["Malvaceae"]
        )

    def test_dbsynchroniser_succeeds_complex(self):
        data = [
            {
                "batch_number": 1,
                "table_name": "family",
                "table_id": 1,
                "values": {
                    "id": 1,
                    "family": "Sterculiaceae",
                    "_last_updated": 0,
                    "_created": 0,
                },
                "operation": "insert",
                "user": "test",
                "timestamp": datetime(2023, 1, 1),
            },
            {
                "batch_number": 1,
                "table_name": "genus",
                "table_id": 1,
                "values": {
                    "id": 1,
                    "genus": "Sterculia",
                    "family_id": 1,
                    "_last_updated": 0,
                    "_created": 0,
                },
                "operation": "insert",
                "user": "test",
                "timestamp": datetime(2023, 1, 1),
            },
            {
                "batch_number": 1,
                "table_name": "family",
                "table_id": 1,
                "values": {
                    "id": 1,
                    "family": ["Malvaceae", "Sterculiaceae"],
                    "_last_updated": 0,
                    "_created": 0,
                },
                "operation": "update",
                "user": "test",
                "timestamp": datetime(2023, 1, 1),
            },
            {
                "batch_number": 1,
                "table_name": "genus",
                "table_id": 1,
                "values": {
                    "id": 1,
                    "genus": "Sterculia",
                    "family_id": 1,
                    "_last_updated": 0,
                    "_created": 0,
                },
                "operation": "delete",
                "user": "test",
                "timestamp": datetime(2023, 1, 1),
            },
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
        self.assertEqual(
            [str(i) for i in self.session.query(Family)], ["Malvaceae"]
        )

    def test_dbsynchroniser_adds_history_correctly(self):
        # add a family to update
        self.session.add(Family(family="Leguminosae", _created="1/1/21"))
        self.session.commit()
        # sync some data
        data = [
            {
                "batch_number": 1,
                "table_name": "family",
                "table_id": 2,
                "values": {
                    "id": 2,
                    "family": "Sterculiaceae",
                    "_last_updated": "1/1/23",
                    "_created": 0,
                },
                "operation": "insert",
                "user": "test",
                "timestamp": datetime(2023, 1, 1),
            },
            {
                "batch_number": 1,
                "table_name": "genus",
                "table_id": 1,
                "values": {
                    "id": 1,
                    "genus": "Sterculia",
                    "family_id": 2,
                    "_last_updated": "1/1/23",
                    "_created": 0,
                },
                "operation": "insert",
                "user": "test",
                "timestamp": datetime(2023, 1, 1),
            },
            {
                "batch_number": 1,
                "table_name": "family",
                "table_id": 2,
                "values": {
                    "id": 2,
                    "family": ["Malvaceae", "Sterculiaceae"],
                    "_created": "1/1/23",
                    "_last_updated": "1/1/23",
                },
                "operation": "update",
                "user": "test",
                "timestamp": datetime(2023, 1, 1),
            },
            {
                "batch_number": 1,
                "table_name": "genus",
                "table_id": 1,
                "values": {
                    "id": 1,
                    "genus": "Sterculia",
                    "family_id": 2,
                    "_created": "1/1/23",
                    "_last_updated": "1/1/23",
                },
                "operation": "delete",
                "user": "test",
                "timestamp": datetime(2023, 1, 1),
            },
            {
                "batch_number": 1,
                "table_name": "family",
                "table_id": 1,
                "values": {
                    "id": 1,
                    "family": ["Fabaceae", "Leguminosae"],
                    "_created": "1/1/23",
                    "_last_updated": "1/1/23",
                },
                "operation": "update",
                "user": "test",
                "timestamp": datetime(2023, 1, 1),
            },
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
            self.assertEqual(row.user, "test")
            # timestamp accurate
            self.assertAlmostEqual(
                row.timestamp.timestamp(), datetime.now().timestamp(), delta=2
            )
            # _last_update == now regardless of value in clones data
            if row.operation == "update" and isinstance(
                row["values"]["_last_updated"], list
            ):
                last_updated = parser.parse(
                    row["values"]["_last_updated"][0]
                ).timestamp()
            else:
                last_updated = parser.parse(
                    row["values"]["_last_updated"]
                ).timestamp()
            self.assertAlmostEqual(
                last_updated, datetime.now().timestamp(), delta=3
            )
            # _created not changed for existing but added for others
            if row.table_name == "family" and row.table_id == 1:
                self.assertEqual(
                    parser.parse(row["values"]["_created"]).timestamp(),
                    parser.parse("1/1/21").timestamp(),
                )
            else:
                self.assertAlmostEqual(
                    parser.parse(row["values"]["_created"]).timestamp(),
                    datetime.now().timestamp(),
                    delta=3,
                )
            # updates recorded as lists, insert/delete not record as lists
            if row.operation == "update":
                self.assertTrue(
                    [v for v in row["values"].values() if isinstance(v, list)]
                )
            else:
                self.assertFalse(
                    [v for v in row["values"].values() if isinstance(v, list)]
                )
        # operation is equal
        self.assertEqual(rows[1].operation, "insert")
        self.assertEqual(rows[2].operation, "insert")
        self.assertEqual(rows[3].operation, "update")
        self.assertEqual(rows[4].operation, "delete")
        self.assertEqual(rows[5].operation, "update")
        # updates recorded
        self.assertEqual(
            rows[3]["values"]["family"], ["Malvaceae", "Sterculiaceae"]
        )
        self.assertEqual(
            rows[5]["values"]["family"], ["Fabaceae", "Leguminosae"]
        )


class ResolutionCentreViewTests(BaubleTestCase):
    def test_fails_early_if_no_db_engine(self):
        orig_engine = db.engine
        db.engine = None
        view = ResolutionCentreView()
        self.assertRaises(error.DatabaseError, view.on_resolve_btn_clicked)
        self.assertRaises(
            error.DatabaseError, view.on_remove_selected_btn_clicked
        )
        self.assertRaises(error.DatabaseError, view.update)

        clone_uri = "sqlite:///test.db"
        self.assertRaises(
            error.DatabaseError, ToSync.add_batch_from_uri, clone_uri
        )
        row = mock.Mock()
        self.assertRaises(
            error.DatabaseError, DBSyncroniser([row])._sync_row, row
        )
        db.engine = orig_engine

    def test_get_selected_rows_no_model_no_rows_returns_none(self):
        # Not sure this is actually useful. (or the right return value)
        view = ResolutionCentreView()
        mock_tree_view = mock.Mock()
        mock_tree_view.get_selection().get_selected_rows.return_value = (
            None,
            [],
        )
        view.sync_tv = mock_tree_view
        self.assertIsNone(view.get_selected_rows())
        mock_tree_view.get_selection().get_selected_rows.return_value = (
            mock.Mock(),
            None,
        )
        view.sync_tv = mock_tree_view
        self.assertIsNone(view.get_selected_rows())

    def test_get_selected_rows_none_selected_returns_empty(self):
        view = ResolutionCentreView()
        self.assertEqual(view.get_selected_rows(), [])

    @mock.patch("bauble.gui")
    def test_init_creates_context_menu(self, mock_gui):
        view = ResolutionCentreView()
        self.assertIsNotNone(view.context_menu)
        add_action_calls = [c.args for c in mock_gui.add_action.call_args_list]
        self.assertIn(("select_batch", view.on_select_batch), add_action_calls)
        self.assertIn(
            ("select_related", view.on_select_related), add_action_calls
        )
        self.assertIn(("select_all", view.on_select_all), add_action_calls)

    def test_add_row_populates_liststore(self):
        # Test friendly drops geojson replaces None with "" and does show False
        data = [
            {
                "batch_number": 1,
                "table_name": "accession",
                "table_id": 1,
                "values": {
                    "code": "2023.0001",
                    "species_id": 1,
                    "quantity_recvd": 2,
                    "private": False,
                    "id_qual": None,
                    "_last_updated": 0,
                    "_created": 0,
                },
                "operation": "insert",
                "user": "test",
                "timestamp": datetime(2023, 1, 1),
            },
            {
                "batch_number": 1,
                "table_name": "location",
                "table_id": 1,
                "values": {
                    "id": 1,
                    "code": "LOC1",
                    "description": ["the first location", None],
                    "geojson": [
                        {
                            "type": "Point",
                            "coordinates": [
                                152.980,
                                -27.476,
                            ],
                        },
                        None,
                    ],
                    "_last_updated": 0,
                    "_created": 0,
                },
                "operation": "update",
                "user": "test",
                "timestamp": datetime(2023, 1, 1),
            },
        ]
        to_sync = ToSync.__table__
        in_stmt = to_sync.insert(data)
        out_stmt = select(to_sync).order_by(to_sync.c.id.desc())
        with db.engine.begin() as conn:
            conn.execute(in_stmt)
            rows = conn.execute(out_stmt).all()
        view = ResolutionCentreView()
        self.assertEqual(len(rows), 2)
        for row in rows:  # only one
            view.add_row(row)
        frmt = bauble.prefs.prefs.get(bauble.prefs.datetime_format_pref)
        row1 = view.liststore[0]
        self.assertEqual(row1[1], "1")
        self.assertEqual(row1[2], rows[0].timestamp.strftime(frmt))
        self.assertEqual(row1[3], "update")
        self.assertEqual(row1[4], "test")
        self.assertEqual(row1[5], "location")
        self.assertEqual(
            row1[6],
            "id: 1, description: ['the first location', None], code: LOC1",
        )
        self.assertEqual(
            row1[7],
            '[{"type": "Point", "coordinates": [152.98, -27.476]}, null]',
        )
        row2 = view.liststore[1]
        self.assertEqual(row2[1], "1")
        self.assertEqual(row2[2], rows[1].timestamp.strftime(frmt))
        self.assertEqual(row2[3], "insert")
        self.assertEqual(row2[4], "test")
        self.assertEqual(row2[5], "accession")
        self.assertEqual(
            row2[6],
            "code: 2023.0001, private: False, quantity_recvd: 2, "
            "species_id: 1, id_qual: ''",
        )
        self.assertIsNone(row2[7])

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
        mock_view.get_path_at_pos.return_value = None
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
        view.liststore.__iter__.return_value = [mock_row1, mock_row2]
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
            {
                "batch_number": 1,
                "table_name": "family",
                "table_id": 1,
                "values": {
                    "id": 1,
                    "family": "Sterculiaceae",
                    "_created": 0,
                    "_last_updated": 0,
                },
                "operation": "insert",
                "user": "test",
                "timestamp": datetime(2023, 1, 1),
            },
            {
                "batch_number": 1,
                "table_name": "family",
                "table_id": 2,
                "values": {
                    "id": 2,
                    "family": "Myrtaceae",
                    "_created": 0,
                    "_last_updated": 0,
                },
                "operation": "insert",
                "user": "test",
                "timestamp": datetime(2023, 1, 1),
            },
            {
                "batch_number": 1,
                "table_name": "genus",
                "table_id": 1,
                "values": {
                    "id": 1,
                    "genus": "Sterculia",
                    "family_id": 1,
                    "_created": 0,
                    "_last_updated": 0,
                },
                "operation": "insert",
                "user": "test",
                "timestamp": datetime(2023, 1, 1),
            },
            {
                "batch_number": 1,
                "table_name": "family",
                "table_id": 1,
                "values": {
                    "id": 1,
                    "family": ["Malvaceae", "Sterculiaceae"],
                    "_created": 0,
                    "_last_updated": 0,
                },
                "operation": "update",
                "user": "test",
                "timestamp": datetime(2023, 1, 1),
            },
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

    @mock.patch("bauble.plugins.synclone.sync.ResolverDialog.run")
    def test_on_resolve_btn_clicked_resolve_reponse(self, mock_run):
        data = {
            "batch_number": 1,
            "table_name": "accession",
            "table_id": 1,
            "values": {
                "code": "2023.0001",
                "species_id": 1,
                "quantity_recvd": 2,
                "id_qual": None,
                "_last_updated": 0,
                "_created": 0,
            },
            "operation": "insert",
            "user": "test",
            "timestamp": datetime(2023, 1, 1),
        }

        to_sync = ToSync.__table__
        in_stmt = to_sync.insert(data)
        out_stmt = select(to_sync).order_by(to_sync.c.id.desc())
        with db.engine.begin() as conn:
            conn.execute(in_stmt)
            rows = conn.execute(out_stmt).all()
        view = ResolutionCentreView()
        self.assertEqual(len(rows), 1)
        for row in rows:  # only one
            view.add_row(row)
        view.sync_tv.set_cursor(0)

        def _set_and_respond():
            rows[0]["values"]["code"] = "2023.0003"
            return RESPONSE_RESOLVE

        mock_run.side_effect = _set_and_respond
        view.on_resolve_btn_clicked()

        with db.engine.begin() as conn:
            rows = conn.execute(out_stmt).all()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["values"]["code"], "2023.0003")

    @mock.patch("bauble.plugins.synclone.sync.ResolverDialog.run")
    def test_on_resolve_btn_clicked_quit_reponse(self, mock_run):
        data = {
            "batch_number": 1,
            "table_name": "accession",
            "table_id": 1,
            "values": {
                "code": "2023.0001",
                "species_id": 1,
                "quantity_recvd": 2,
                "_last_updated": 0,
                "_created": 0,
            },
            "operation": "insert",
            "user": "test",
            "timestamp": datetime(2023, 1, 1),
        }

        to_sync = ToSync.__table__
        in_stmt = to_sync.insert(data)
        out_stmt = select(to_sync).order_by(to_sync.c.id.desc())
        with db.engine.begin() as conn:
            conn.execute(in_stmt)
            rows = conn.execute(out_stmt).all()
        view = ResolutionCentreView()
        self.assertEqual(len(rows), 1)
        for row in rows:  # only one
            view.add_row(row)
        view.sync_tv.set_cursor(0)

        def _set_and_respond():
            rows[0]["values"]["code"] = "2023.0003"
            return RESPONSE_QUIT

        mock_run.side_effect = _set_and_respond
        view.on_resolve_btn_clicked()

        with db.engine.begin() as conn:
            rows = conn.execute(out_stmt).all()
        self.assertEqual(len(rows), 1)
        # no change
        self.assertEqual(rows[0]["values"]["code"], "2023.0001")

    def test_on_remove_selected_btn_clicked(self):
        data = {
            "batch_number": 1,
            "table_name": "accession",
            "table_id": 1,
            "values": {
                "code": "2023.0001",
                "species_id": 1,
                "quantity_recvd": 2,
                "_last_updated": 0,
                "_created": 0,
            },
            "operation": "insert",
            "user": "test",
            "timestamp": datetime(2023, 1, 1),
        }

        to_sync = ToSync.__table__
        in_stmt = to_sync.insert(data)
        out_stmt = select(to_sync).order_by(to_sync.c.id.desc())
        with db.engine.begin() as conn:
            conn.execute(in_stmt)
            rows = conn.execute(out_stmt).all()
        view = ResolutionCentreView()
        self.assertEqual(len(rows), 1)
        for row in rows:  # only one
            view.add_row(row)
        view.sync_tv.set_cursor(0)

        view.on_remove_selected_btn_clicked()

        with db.engine.begin() as conn:
            rows = conn.execute(out_stmt).all()
        # no rows left
        self.assertEqual(len(rows), 0)

    @mock.patch("bauble.utils.yes_no_dialog")
    @mock.patch("bauble.plugins.synclone.sync.DBCloner")
    @mock.patch("bauble.plugins.synclone.sync.command_handler")
    def test_on_sync_selected_btn_clicked_succeeds_all(
        self, mock_handler, mock_cloner, mock_dlog
    ):
        loc = Location(code="LOC1")
        self.session.add(loc)
        self.session.commit()
        mock_dlog.return_value = Gtk.ResponseType.YES
        data = [
            {
                "batch_number": 1,
                "table_name": "family",
                "table_id": 1,
                "values": {
                    "id": 1,
                    "family": "Sterculiaceae",
                    "_created": 0,
                    "_last_updated": 0,
                },
                "operation": "insert",
                "user": "test",
                "timestamp": datetime(2023, 1, 1),
            },
            {
                "batch_number": 1,
                "table_name": "genus",
                "table_id": 1,
                "values": {
                    "id": 1,
                    "genus": "Sterculia",
                    "family_id": 1,
                    "_created": 0,
                    "_last_updated": 0,
                },
                "operation": "insert",
                "user": "test",
                "timestamp": datetime(2023, 1, 1),
            },
            {
                "batch_number": 1,
                "table_name": "family",
                "table_id": 1,
                "values": {
                    "id": 1,
                    "family": ["Malvaceae", "Sterculiaceae"],
                    "_created": 0,
                    "_last_updated": 0,
                },
                "operation": "update",
                "user": "test",
                "timestamp": datetime(2023, 1, 1),
            },
            {
                "batch_number": 1,
                "table_name": "location",
                "table_id": 1,
                "values": {
                    "id": 1,
                    "code": "LOC1",
                    "description": ["the first location", None],
                    "geojson": [
                        {
                            "type": "Point",
                            "coordinates": [
                                152.980,
                                -27.476,
                            ],
                        },
                        None,
                    ],
                    "_last_updated": 0,
                    "_created": 0,
                },
                "operation": "update",
                "user": "test",
                "timestamp": datetime(2023, 1, 1),
            },
        ]

        to_sync = ToSync.__table__
        in_stmt = to_sync.insert(data)
        out_stmt = select(to_sync).order_by(to_sync.c.id.desc())
        with db.engine.begin() as conn:
            conn.execute(in_stmt)
            rows = conn.execute(out_stmt).all()
        view = ResolutionCentreView()
        view.uri = "sqlite:///:memory:"
        self.assertEqual(len(rows), 4)
        for row in rows:
            view.add_row(row)

        view.on_select_all()
        view.on_sync_selected_btn_clicked()

        mock_dlog.assert_called()
        mock_cloner.assert_called()
        mock_handler.assert_called_with("home", None)

        with db.engine.begin() as conn:
            rows = conn.execute(out_stmt).all()
        # no rows left
        self.assertEqual(len(rows), 0)
        self.assertEqual(
            [str(i) for i in self.session.query(Genus)], ["Sterculia"]
        )
        self.assertEqual(
            [str(i) for i in self.session.query(Family)], ["Malvaceae"]
        )
        self.session.refresh(loc)
        self.assertEqual(
            loc.geojson,
            {"type": "Point", "coordinates": [152.980, -27.476]},
        )
        self.assertEqual(loc.description, "the first location")

    @mock.patch("bauble.utils.yes_no_dialog")
    @mock.patch("bauble.plugins.synclone.sync.DBCloner")
    @mock.patch("bauble.plugins.synclone.sync.command_handler")
    def test_on_sync_selected_btn_clicked_succeeds_one(
        self, mock_handler, mock_cloner, mock_dlog
    ):
        bauble.pluginmgr.register_command(bauble.ui.SplashCommandHandler)
        mock_dlog.return_value = Gtk.ResponseType.YES
        data = [
            {
                "batch_number": 1,
                "table_name": "family",
                "table_id": 1,
                "values": {
                    "id": 1,
                    "family": "Sterculiaceae",
                    "_created": 0,
                    "_last_updated": 0,
                },
                "operation": "insert",
                "user": "test",
                "timestamp": datetime(2023, 1, 1),
            },
            {
                "batch_number": 1,
                "table_name": "genus",
                "table_id": 1,
                "values": {
                    "id": 1,
                    "genus": "Sterculia",
                    "family_id": 1,
                    "_created": 0,
                    "_last_updated": 0,
                },
                "operation": "insert",
                "user": "test",
                "timestamp": datetime(2023, 1, 1),
            },
            {
                "batch_number": 1,
                "table_name": "family",
                "table_id": 1,
                "values": {
                    "id": 1,
                    "family": ["Malvaceae", "Sterculiaceae"],
                    "_created": 0,
                    "_last_updated": 0,
                },
                "operation": "update",
                "user": "test",
                "timestamp": datetime(2023, 1, 1),
            },
        ]

        to_sync = ToSync.__table__
        in_stmt = to_sync.insert(data)
        out_stmt = select(to_sync).order_by(to_sync.c.id.desc())
        with db.engine.begin() as conn:
            conn.execute(in_stmt)
            rows = conn.execute(out_stmt).all()
        view = ResolutionCentreView()
        view.uri = make_url("sqlite:///:memory:")
        self.assertEqual(len(rows), 3)
        for row in rows:
            view.add_row(row)

        view.sync_tv.set_cursor(2)
        view.on_sync_selected_btn_clicked()

        mock_dlog.assert_called()
        mock_cloner.assert_called()
        mock_handler.assert_called_with("home", None)

        with db.engine.begin() as conn:
            rows = conn.execute(out_stmt).all()
        # 2 rows left
        self.assertEqual(len(rows), 2)
        self.assertEqual(self.session.query(Genus).all(), [])
        self.assertEqual(
            [str(i) for i in self.session.query(Family)], ["Sterculiaceae"]
        )

    @mock.patch("bauble.plugins.synclone.sync.DBSyncroniser")
    def test_on_sync_selected_btn_clicked_fails_all(self, mock_sync):
        # similar to choosing to quit this does nothing to the database but
        # returns failed
        mock_sync().sync.return_value = [2, 3]
        data = [
            {
                "batch_number": 1,
                "table_name": "family",
                "table_id": 1,
                "values": {
                    "id": 1,
                    "family": "Sterculiaceae",
                    "_created": 0,
                    "_last_updated": 0,
                },
                "operation": "insert",
                "user": "test",
                "timestamp": datetime(2023, 1, 1),
            },
            {
                "batch_number": 1,
                "table_name": "genus",
                "table_id": 1,
                "values": {
                    "id": 1,
                    "genus": "Sterculia",
                    "_created": 0,
                    "_last_updated": 0,
                },
                "operation": "insert",
                "user": "test",
                "timestamp": datetime(2023, 1, 1),
            },
            {
                "batch_number": 1,
                "table_name": "family",
                "table_id": 1,
                "values": {
                    "id": 1,
                    "family": ["Malvaceae", "Sterculiaceae"],
                    "_created": 0,
                    "_last_updated": 0,
                },
                "operation": "update",
                "user": "test",
                "timestamp": datetime(2023, 1, 1),
            },
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
        self.assertEqual(
            selected[0]["values"]["family"], ["Malvaceae", "Sterculiaceae"]
        )
        self.assertEqual(selected[1]["values"]["genus"], "Sterculia")

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
        data = {
            "batch_number": 1,
            "table_name": "accession",
            "table_id": 1,
            "values": {
                "code": "2023.0001",
                "species_id": 1,
                "quantity_recvd": 2,
                "_last_updated": 0,
                "_created": 0,
            },
            "operation": "insert",
            "user": "test",
            "timestamp": datetime(2023, 1, 1),
        }

        to_sync = ToSync.__table__
        in_stmt = to_sync.insert(data)
        out_stmt = select(to_sync).order_by(to_sync.c.id.desc())
        with db.engine.begin() as conn:
            conn.execute(in_stmt)
            rows = conn.execute(out_stmt).all()
        view = ResolutionCentreView()
        for row in rows:  # only one
            view.add_row(row)
        view.update()
        self.assertEqual(len(view.liststore), 1)
        self.assertEqual(view.get_selected_rows(), [])
        self.assertFalse(view.remove_selected_btn.get_sensitive())
        self.assertFalse(view.sync_selected_btn.get_sensitive())
        self.assertFalse(view.resolve_btn.get_sensitive())

    def test_update_w_batch_num_uri(self):
        data = [
            {
                "batch_number": 1,
                "table_name": "accession",
                "table_id": 1,
                "values": {
                    "code": "2023.0001",
                    "species_id": 1,
                    "quantity_recvd": 2,
                    "_last_updated": 0,
                    "_created": 0,
                },
                "operation": "insert",
                "user": "test",
                "timestamp": datetime(2023, 1, 1),
            },
            {
                "batch_number": 2,
                "table_name": "family",
                "table_id": 1,
                "values": {
                    "id": 1,
                    "family": "Sterculiaceae",
                    "_created": 0,
                    "_last_updated": 0,
                },
                "operation": "insert",
                "user": "test",
                "timestamp": datetime(2023, 1, 1),
            },
            {
                "batch_number": 2,
                "table_name": "family",
                "table_id": 1,
                "values": {
                    "id": 1,
                    "family": ["Malvaceae", "Sterculiaceae"],
                    "_created": 0,
                    "_last_updated": 0,
                },
                "operation": "update",
                "user": "test",
                "timestamp": datetime(2023, 1, 1),
            },
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
        view.update(["2", "sqlite:///:memory:"])
        self.assertEqual(str(view.uri), "sqlite:///:memory:")
        self.assertEqual(len(view.liststore), 3)
        self.assertEqual(len(view.get_selected_rows()), 2)
        self.assertTrue(view.remove_selected_btn.get_sensitive())
        self.assertTrue(view.sync_selected_btn.get_sensitive())
        self.assertFalse(view.resolve_btn.get_sensitive())


class SyncToolTests(BaubleTestCase):
    @mock.patch("bauble.plugins.synclone.sync.command_handler")
    def test_db_resolve_sync_tool(self, mock_handler):
        DBResolveSyncTool.start()
        mock_handler.assert_called_with("resolve", None)

    def test_resolve_command_handler(self):
        handler = ResolveCommandHandler()
        self.assertIsInstance(handler.get_view(), ResolutionCentreView)
        mock_view = mock.Mock()
        ResolveCommandHandler.view = mock_view
        handler(None, None)
        mock_view.update.assert_called_with(None)

    @mock.patch("bauble.plugins.synclone.sync.start_connection_manager")
    @mock.patch("bauble.plugins.synclone.sync.command_handler")
    def test_db_sync_tool_start_returns_if_no_uri(
        self, mock_handler, mock_start
    ):
        mock_start.return_value = (None, None)
        tool = DBSyncTool()
        tool.start()
        mock_handler.assert_not_called()

    @mock.patch("bauble.plugins.synclone.sync.utils.message_dialog")
    @mock.patch("bauble.plugins.synclone.sync.start_connection_manager")
    @mock.patch("bauble.plugins.synclone.sync.command_handler")
    def test_db_sync_tool_start_returns_notifies_if_same_uri(
        self, mock_handler, mock_start, mock_dialog
    ):
        mock_start.return_value = (None, db.engine.url)
        tool = DBSyncTool()
        tool.start()
        mock_dialog.assert_called()
        mock_handler.assert_not_called()

    @mock.patch("bauble.plugins.synclone.sync.ToSync")
    @mock.patch("bauble.plugins.synclone.sync.start_connection_manager")
    @mock.patch("bauble.plugins.synclone.sync.command_handler")
    def test_db_sync_tool_start(self, mock_handler, mock_start, mock_tosync):
        uri = "sqlite:///test.db"
        mock_tosync.add_batch_from_uri.return_value = 1
        mock_start.return_value = (None, uri)
        tool = DBSyncTool()
        tool.start()
        mock_handler.assert_called_with("resolve", [1, make_url(uri)])
