# Copyright 2008-2010 Brett Adams
# Copyright 2015 Mario Frasca <mario@anche.no>.
# Copyright 2021-2024 Ross Demuth <rossdemuth123@gmail.com>
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

from unittest import mock

from dateutil import parser
from sqlalchemy import Column
from sqlalchemy import ForeignKey
from sqlalchemy import Integer
from sqlalchemy import Unicode
from sqlalchemy import create_engine
from sqlalchemy import func
from sqlalchemy.orm import relationship

from bauble import btypes
from bauble import db
from bauble import error
from bauble import meta
from bauble import prefs
from bauble import utils
from bauble.error import DatabaseError
from bauble.plugins.garden.accession import Accession
from bauble.plugins.garden.accession import AccessionNote
from bauble.plugins.garden.accession import Plant
from bauble.plugins.garden.accession import SourceDetail
from bauble.plugins.garden.location import Location
from bauble.plugins.plants.genus import Family
from bauble.plugins.plants.genus import Genus
from bauble.plugins.plants.genus import Species
from bauble.plugins.plants.species_model import VernacularName
from bauble.search.strategies import MapperSearch
from bauble.test import BaubleTestCase
from bauble.test import get_setUp_data_funcs


class HistoryTests(BaubleTestCase):
    def test_history_add_insert_populates(self):
        for setup in get_setUp_data_funcs():
            setup()

        # setUp_data functions do not use ORM and hence do not populate history
        # Only expect 1 or 2 entries at this point
        session = db.Session()
        history_count1 = self.session.query(db.History).count()
        self.assertLess(history_count1, 5)

        # INSERT
        note_cls = AccessionNote
        parent_model = Accession(species_id=1, code="567")

        date_val = "21.1.24"

        # add 5 notes
        for i in range(5):
            note_model = note_cls(note=f"test{i}", date=date_val)
            parent_model.notes.append(note_model)
        session.add(parent_model)
        session.commit()

        history_count2 = self.session.query(db.History).count()
        # 5 notes and 1 parent
        self.assertEqual(history_count2, history_count1 + 5 + 1)

        # test we can retrieve each note record (Note casting to unicode)
        for i in range(5):
            note = (
                self.session.query(db.History)
                .filter(db.History.table_name == note_cls.__tablename__)
                .filter(db.History.operation == "insert")
                .filter(db.History.values.cast(Unicode).contains(f"%test{i}%"))
                .one()
            )
            self.assertTrue(note)
            self.assertEqual(
                note.values["date"],
                str(btypes.Date().process_bind_param(date_val, None)),
            )

    def test_history_add_update_populates(self):
        for setup in get_setUp_data_funcs():
            setup()

        session = db.Session()
        history_count1 = self.session.query(db.History).count()
        self.assertLess(history_count1, 5)

        date_val = "21.1.24"

        note_model = AccessionNote(note="test note", date=date_val)
        parent_model = Accession(species_id=1, code="567")
        parent_model.notes.append(note_model)

        session.add(parent_model)
        session.commit()

        # NOTE if the model is not refreshed the update will record a single
        # item list
        session.refresh(note_model)
        first_updated = note_model._last_updated

        # sleep so _last_updated changes
        import time

        time.sleep(1)

        new_date_val = "22/1/22"
        note_model.note = "TEST AGAIN"
        note_model.date = new_date_val
        session.commit()

        session.refresh(note_model)
        last_updated = note_model._last_updated

        updated = (
            self.session.query(db.History)
            .filter(db.History.table_name == "accession_note")
            .filter(db.History.operation == "update")
        )

        self.assertEqual(updated.count(), 1)
        updated = updated.one()
        self.assertIn("['TEST AGAIN',", str(updated.values))
        self.assertIn("['2022-01-22', '2024-01-21']", str(updated.values))
        # last updated is correct
        self.assertIn(
            f"'_last_updated': ['{last_updated}', '{first_updated}']",
            str(updated.values),
        )

    def test_history_add_no_update_doesnt_populate(self):
        for setup in get_setUp_data_funcs():
            setup()

        session = db.Session()
        history_count1 = self.session.query(db.History).count()
        self.assertLess(history_count1, 5)

        date_val = "21.1.24"

        note_model = AccessionNote(note="test note", date=date_val)
        parent_model = Accession(species_id=1, code="567")
        parent_model.notes.append(note_model)

        session.add(parent_model)
        session.commit()

        # NOTE if the model is not refreshed the update will record a single
        # item list
        session.refresh(note_model)

        # UPDATE AGAIN, no actual change is made
        note_model.note = "something else"
        note_model.note = "test note"
        note_model.date = "21/1/24"
        session.commit()

        updated = (
            self.session.query(db.History)
            .filter(db.History.table_name == "accession_note")
            .filter(db.History.operation == "update")
        )

        self.assertEqual(updated.count(), 0)

    def test_history_add_delete_updates(self):
        for setup in get_setUp_data_funcs():
            setup()

        session = db.Session()
        history_count1 = self.session.query(db.History).count()
        self.assertLess(history_count1, 5)

        date_val = "21.1.24"

        note_model = AccessionNote(note="test note", date=date_val)
        parent_model = Accession(species_id=1, code="567")
        parent_model.notes.append(note_model)

        session.add(parent_model)
        session.commit()

        # NOTE if the model is not refreshed the update will record a single
        # item list
        session.refresh(note_model)

        # DELETE
        session.delete(note_model)
        session.commit()

        deleted = (
            self.session.query(db.History)
            .filter(db.History.table_name == "accession_note")
            .filter(db.History.operation == "delete")
        )

        self.assertEqual(deleted.count(), 1)
        self.assertIn("test note", str(deleted.one().values))
        self.assertIn("2024-01-21", str(deleted.one().values))

        session.close()

    def test_revert_to_insert(self):
        for setup in get_setUp_data_funcs():
            setup()

        # get a notes class and parent model...
        for klass in MapperSearch.get_domain_classes().values():
            if hasattr(klass, "notes") and hasattr(klass.notes, "mapper"):
                note_cls = klass.notes.mapper.class_
                parent_model = klass()
                break

        # populate parent model with junk data...
        for col in parent_model.__table__.columns:
            if not col.nullable:
                if col.name.endswith("_id"):
                    setattr(parent_model, col.name, 1)
                if not getattr(parent_model, col.name):
                    setattr(parent_model, col.name, "567")
        start_count = self.session.query(note_cls).count()
        # add 5 notes
        for i in range(5):
            parent_model.notes.append(note_cls(note=f"test{i}"))

        self.session.add(parent_model)
        self.session.commit()

        self.assertEqual(self.session.query(note_cls).count(), 5 + start_count)

        db.History.revert_to(
            self.session.query(func.max(db.History.id)).scalar() - 5
        )

        self.assertEqual(self.session.query(note_cls).count(), start_count)

    def test_revert_to_update(self):
        for setup in get_setUp_data_funcs():
            setup()

        # get a notes class and parent model...
        for klass in MapperSearch.get_domain_classes().values():
            if hasattr(klass, "notes") and hasattr(klass.notes, "mapper"):
                note_cls = klass.notes.mapper.class_
                parent_model = klass()
                break
        start_count = self.session.query(note_cls).count()

        # populate parent model with junk data...
        for col in parent_model.__table__.columns:
            if not col.nullable:
                if col.name.endswith("_id"):
                    setattr(parent_model, col.name, 1)
                if not getattr(parent_model, col.name):
                    setattr(parent_model, col.name, "567")
        # add 5 notes
        for i in range(5):
            parent_model.notes.append(note_cls(note=f"test{i}"))

        self.session.add(parent_model)
        self.session.commit()

        start_max_id = self.session.query(func.max(db.History.id)).scalar()
        # UPDATE
        for note in parent_model.notes:
            note.note = "TEST UPDATE"

        self.session.commit()

        updated = (
            self.session.query(db.History)
            .filter(db.History.table_name == note_cls.__tablename__)
            .filter(db.History.operation == "update")
        )

        self.assertEqual(updated.count(), 5)

        self.assertEqual(
            start_max_id + 5,
            self.session.query(func.max(db.History.id)).scalar(),
        )

        self.assertEqual(self.session.query(note_cls).count(), 5 + start_count)

        for note in parent_model.notes:
            self.assertEqual(note.note, "TEST UPDATE")

        db.History.revert_to(
            self.session.query(func.max(db.History.id)).scalar() - 4
        )

        self.assertEqual(self.session.query(note_cls).count(), 5 + start_count)

        self.assertEqual(
            start_max_id, self.session.query(func.max(db.History.id)).scalar()
        )

        for note in parent_model.notes:
            self.session.refresh(note)
            self.assertNotEqual(note.note, "TEST UPDATE")

    def test_revert_to_delete(self):
        for setup in get_setUp_data_funcs():
            setup()

        # get a notes class and parent model...
        for klass in MapperSearch.get_domain_classes().values():
            if hasattr(klass, "notes") and hasattr(klass.notes, "mapper"):
                note_cls = klass.notes.mapper.class_
                parent_model = klass()
                break
        start_count = self.session.query(note_cls).count()

        # populate parent model with junk data...
        for col in parent_model.__table__.columns:
            if not col.nullable:
                if col.name.endswith("_id"):
                    setattr(parent_model, col.name, 1)
                if not getattr(parent_model, col.name):
                    setattr(parent_model, col.name, "567")
        # add 5 notes
        for _ in range(5):
            parent_model.notes.append(note_cls(note="TEST"))

        self.session.add(parent_model)
        self.session.commit()

        start_max_id = self.session.query(func.max(db.History.id)).scalar()
        # DELETE
        for note in parent_model.notes:
            self.session.delete(note)

        self.session.commit()

        deleted = (
            self.session.query(db.History)
            .filter(db.History.table_name == note_cls.__tablename__)
            .filter(db.History.operation == "delete")
        )

        self.assertEqual(deleted.count(), 5)

        self.assertEqual(
            start_max_id + 5,
            self.session.query(func.max(db.History.id)).scalar(),
        )

        self.assertEqual(self.session.query(note_cls).count(), start_count)

        self.session.refresh(parent_model)
        self.assertFalse(parent_model.notes)

        db.History.revert_to(
            self.session.query(func.max(db.History.id)).scalar() - 4
        )

        self.assertEqual(self.session.query(note_cls).count(), 5 + start_count)

        self.assertEqual(
            start_max_id, self.session.query(func.max(db.History.id)).scalar()
        )

        self.session.refresh(parent_model)

        for note in parent_model.notes:
            self.assertEqual(note.note, "TEST")

    def test_event_add_delete(self):
        table = meta.BaubleMeta.__table__
        instance = meta.get_default("test", "test value")
        with db.engine.begin() as connection:
            db.History.event_add(
                "delete", table, connection, instance, commit_user="test user"
            )
        rows = self.session.query(db.History).all()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1].operation, "delete")
        self.assertEqual(rows[1].values["name"], "test")
        self.assertEqual(rows[1].values["value"], "test value")
        self.assertEqual(rows[1].user, "test user")

    def test_event_add_insert(self):
        table = meta.BaubleMeta.__table__
        instance = meta.get_default("test", "test value")
        with db.engine.begin() as connection:
            db.History.event_add(
                "insert", table, connection, instance, commit_user="test user"
            )
        rows = self.session.query(db.History).all()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1].operation, "insert")
        self.assertEqual(rows[1].values["name"], "test")
        self.assertEqual(rows[1].values["value"], "test value")
        self.assertEqual(rows[1].user, "test user")

    def test_event_add_update(self):
        table = meta.BaubleMeta.__table__
        instance = meta.get_default("test", "test value")
        with db.engine.begin() as connection:
            db.History.event_add(
                "update",
                table,
                connection,
                instance,
                _last_updated=utils.utcnow_naive(),
            )
        rows = self.session.query(db.History).all()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1].operation, "update")
        self.assertEqual(rows[1].values["name"], "test")
        self.assertEqual(rows[1].values["value"], "test value")
        # only one update
        self.assertEqual(
            len([v for v in rows[1].values.values() if isinstance(v, list)]), 1
        )
        # test datetimes don't fail
        self.assertAlmostEqual(
            parser.parse((rows[1].values["_last_updated"][0])).timestamp(),
            utils.utcnow_naive().timestamp(),
            delta=1,
        )

    def test_event_add_update_no_change_doesnt_add(self):
        table = meta.BaubleMeta.__table__
        instance = meta.get_default("test", "test value")
        with db.engine.begin() as connection:
            db.History.event_add("update", table, connection, instance)
        rows = self.session.query(db.History).all()
        # no kwargs, no update is added
        self.assertEqual(len(rows), 1)


class BaseTests(BaubleTestCase):
    def test_domain(self):
        class TestTableCustom(db.Domain):
            __tablename__ = "test_table"

            def __str__(self):
                return "Test"

        TestTableCustom.__table__.create(bind=db.engine)
        t = TestTableCustom()
        self.assertEqual(
            t.search_view_markup_pair(), ("Test", "TestTableCustom")
        )


class GlobalFunctionsTests(BaubleTestCase):
    def test_class_of_object(self):
        self.assertEqual(db.class_of_object("genus"), Genus)
        self.assertEqual(db.class_of_object("accession_note"), AccessionNote)
        self.assertEqual(db.class_of_object("not_existing"), None)

    def test_get_related_class(self):
        self.assertEqual(db.get_related_class(Plant, "accession"), Accession)
        self.assertEqual(
            db.get_related_class(Plant, "accession.species.genus.family"),
            Family,
        )
        self.assertEqual(
            db.get_related_class(Plant, "accession.source.source_detail"),
            SourceDetail,
        )
        self.assertEqual(db.get_related_class(Plant, "location"), Location)
        self.assertEqual(db.get_related_class(Location, "plants"), Plant)
        self.assertEqual(
            db.get_related_class(
                Location, "plants.accession.source.source_detail"
            ),
            SourceDetail,
        )
        self.assertEqual(
            db.get_related_class(Species, "vernacular_names"), VernacularName
        )

    def test_get_create_or_update(self):
        loc1 = {
            "code": "XYZ001",
            "name": "A garden bed",
            "description": "lots of plants",
        }
        loc1_new = db.get_create_or_update(self.session, Location, **loc1)
        self.assertEqual(len(self.session.new), 1)
        self.assertTrue(loc1_new in self.session.new)
        fam1 = {"epithet": "Myrtaceae"}
        fam1_new = db.get_create_or_update(self.session, Family, **fam1)
        self.assertEqual(len(self.session.new), 2)
        self.assertTrue(fam1_new in self.session.new)
        gen1 = {"genus": "Syzygium", "family": fam1_new}
        gen1_new = db.get_create_or_update(self.session, Genus, **gen1)
        self.assertEqual(len(self.session.new), 3)
        self.assertTrue(gen1_new in self.session.new)
        sp1 = {"epithet": "francisii", "genus": gen1_new}
        sp1_new = db.get_create_or_update(self.session, Species, **sp1)
        self.assertEqual(len(self.session.new), 4)
        self.assertTrue(sp1_new in self.session.new)
        acc1 = {"code": "AAA001", "species": sp1_new}
        acc1_new = db.get_create_or_update(self.session, Accession, **acc1)
        self.assertEqual(len(self.session.new), 5)
        self.assertTrue(acc1_new in self.session.new)
        plt1 = {
            "code": "1",
            "quantity": 1,
            "accession": acc1_new,
            "location": loc1_new,
        }
        plt1_new = db.get_create_or_update(self.session, Plant, **plt1)
        self.assertEqual(len(self.session.new), 6)
        self.assertEqual(len(self.session.dirty), 0)
        self.assertTrue(plt1_new in self.session.new)
        self.session.commit()
        self.assertEqual(len(self.session.new), 0)
        self.assertEqual(len(self.session.dirty), 0)
        loc2 = {
            "code": "ABC001",
            "name": "A small garden bed",
            "description": "a few of plants",
        }
        loc2_new = db.get_create_or_update(self.session, Location, **loc2)
        self.assertEqual(len(self.session.new), 1)
        self.assertTrue(loc2_new in self.session.new)
        plt2 = {
            "code": "2",
            "quantity": 10,
            "accession": acc1_new,
            "location": loc2_new,
        }
        plt2_new = db.get_create_or_update(self.session, Plant, **plt2)
        self.assertEqual(len(self.session.new), 2)
        self.assertEqual(len(self.session.dirty), 1)
        self.assertTrue(plt2_new in self.session.new)
        self.assertTrue(acc1_new in self.session.dirty)
        self.session.commit()
        self.assertEqual(len(self.session.new), 0)
        self.assertEqual(len(self.session.dirty), 0)
        plt1_get = db.get_create_or_update(self.session, Plant, **plt1)
        self.assertEqual(plt1_new, plt1_get)
        loc2_get = db.get_create_or_update(self.session, Location, **loc2)
        self.assertEqual(loc2_new, loc2_get)
        loc2["name"] = ""
        loc2_update = db.get_create_or_update(self.session, Location, **loc2)
        self.assertEqual(loc2_new, loc2_update)
        self.assertEqual(loc2_get, loc2_update)
        self.assertEqual(len(self.session.new), 0)
        self.assertEqual(len(self.session.dirty), 1)
        self.session.commit()
        # 2 plants should fail, returning None and not adding anything to the
        # session
        plt_any = db.get_create_or_update(
            self.session, Plant, accession=acc1_new
        )
        self.assertIsNone(plt_any)
        self.assertEqual(len(self.session.new), 0)
        self.assertEqual(len(self.session.dirty), 0)
        self.assertEqual(len(self.session.deleted), 0)
        sp1_update = {
            "sp": "luehmanii",
            "sp_author": "F.Muell.",
            "id": sp1_new.id,
        }
        db.get_create_or_update(self.session, Species, **sp1_update)
        self.assertEqual(len(self.session.dirty), 1)
        self.assertEqual(sp1_new.sp, "luehmanii")
        self.assertEqual(sp1_new.sp_author, "F.Muell.")
        self.session.commit()

    def test_get_create_or_update_default_vernacular(self):
        # test does not cause unique constraint error on commit second time
        # around (i.e. try to create the default_vernacular twice)
        fam1 = {"epithet": "Myrtaceae"}
        fam1_new = db.get_create_or_update(self.session, Family, **fam1)
        self.assertEqual(len(self.session.new), 1)
        self.assertTrue(fam1_new in self.session.new)
        gen1 = {"genus": "Syzygium", "family": fam1_new}
        gen1_new = db.get_create_or_update(self.session, Genus, **gen1)
        self.assertTrue(gen1_new in self.session.new)
        self.assertEqual(len(self.session.new), 2)
        sp1 = {
            "epithet": "francisii",
            "genus": gen1_new,
            "default_vernacular_name": "Rose Satinash",
        }
        sp1_new = db.get_create_or_update(self.session, Species, **sp1)
        # Species + DefaultVernacularName + VernacularName
        self.assertEqual(len(self.session.new), 5)
        self.assertTrue(sp1_new in self.session.new)
        self.session.commit()
        sp1 = {
            "epithet": "francisii",
            "genus": gen1_new,
            "default_vernacular_name": "Rose Satinash",
        }
        sp1_get = db.get_create_or_update(self.session, Species, **sp1)
        self.assertEqual(sp1_new, sp1_get)
        self.session.commit()

    def test_get_active_children_excludes_inactive_if_pref_set(self):
        mock_child1 = mock.Mock(active=True)
        mock_child2 = mock.Mock(active=False)
        # obj without an active attr
        mock_child3 = mock.Mock()
        del mock_child3.active

        mock_parent = mock.Mock(kids=[mock_child1, mock_child2, mock_child3])
        # don't use object_session
        mock_parent._sa_instance_state.session = None

        prefs.prefs[prefs.exclude_inactive_pref] = True

        self.assertEqual(
            db.get_active_children("kids", mock_parent),
            [mock_child1, mock_child3],
        )

        def kids_func(obj):
            return obj.kids

        self.assertEqual(
            db.get_active_children(kids_func, mock_parent),
            [mock_child1, mock_child3],
        )

    def test_get_active_children_excludes_inactive_if_pref_set_from_db(self):
        class TestKid(db.Domain):
            __tablename__ = "test_kid"

            parent_id = Column(
                Integer, ForeignKey("test_parent.id"), nullable=False
            )
            parent = relationship("TestParent", back_populates="kids")
            active = Column(btypes.Boolean, default=False)

        class TestParent(db.Domain):
            __tablename__ = "test_parent"

            kids = relationship(TestKid, back_populates="parent")

        TestParent.__table__.create(bind=db.engine)
        TestKid.__table__.create(bind=db.engine)
        kid1 = TestKid(id=1, active=False)
        kid2 = TestKid(id=2, active=True)
        kid3 = TestKid(id=3, active=True)
        parent = TestParent(kids=[kid1, kid2, kid3])
        self.session.add(parent)
        self.session.commit()

        prefs.prefs[prefs.exclude_inactive_pref] = True

        self.assertCountEqual(
            db.get_active_children("kids", parent),
            [kid2, kid3],
        )

    def test_get_active_children_includes_inactive_if_pref_not_set(self):
        mock_child1 = mock.Mock(active=True)
        mock_child2 = mock.Mock(active=False)
        # obj without an active attr
        mock_child3 = mock.Mock()
        del mock_child3.active

        mock_parent = mock.Mock(kids=[mock_child1, mock_child2, mock_child3])

        prefs.prefs[prefs.exclude_inactive_pref] = False

        self.assertEqual(
            db.get_active_children("kids", mock_parent),
            [mock_child1, mock_child2, mock_child3],
        )

        def kids_func(obj):
            return obj.kids

        self.assertEqual(
            db.get_active_children(kids_func, mock_parent),
            [mock_child1, mock_child2, mock_child3],
        )

    @mock.patch("bauble.db.utils.message_dialog")
    def test_verify_connection_empty_raises(self, mock_dialog):
        engine = create_engine("sqlite:///:memory:")
        self.assertRaises(
            error.EmptyDatabaseError, db.verify_connection, engine
        )
        mock_dialog.assert_not_called()
        # with show dialogs
        self.assertRaises(
            error.EmptyDatabaseError,
            db.verify_connection,
            engine,
            show_error_dialogs=True,
        )
        mock_dialog.assert_called()

    @mock.patch("bauble.db.utils.message_dialog")
    def test_verify_connection_no_meta_raises(self, mock_dialog):
        engine = create_engine("sqlite:///:memory:")
        with engine.connect() as connection:
            tables = [
                table
                for name, table in db.metadata.tables.items()
                if not name.endswith("bauble")
            ]
            db.metadata.create_all(bind=connection, tables=tables)
        self.assertRaises(error.MetaTableError, db.verify_connection, engine)
        mock_dialog.assert_not_called()
        # with show dialogs
        self.assertRaises(
            error.MetaTableError,
            db.verify_connection,
            engine,
            show_error_dialogs=True,
        )
        mock_dialog.assert_called()

    @mock.patch("bauble.db.utils.message_dialog")
    def test_verify_connection_no_timestamp_raises(self, mock_dialog):
        engine = create_engine("sqlite:///:memory:")
        with engine.connect() as connection:
            db.metadata.create_all(bind=connection)
        self.assertRaises(error.TimestampError, db.verify_connection, engine)
        mock_dialog.assert_not_called()
        # with show dialogs
        self.assertRaises(
            error.TimestampError,
            db.verify_connection,
            engine,
            show_error_dialogs=True,
        )
        mock_dialog.assert_called()

    @mock.patch("bauble.db.utils.message_dialog")
    def test_verify_connection_no_version_raises(self, mock_dialog):
        engine = create_engine("sqlite:///:memory:")
        meta_table = meta.BaubleMeta.__table__
        with engine.connect() as connection:
            db.metadata.create_all(bind=connection)
            stmt = meta_table.insert().values(
                {"name": meta.CREATED_KEY, "value": "4/9/23"}
            )
            connection.execute(stmt)
        self.assertRaises(error.VersionError, db.verify_connection, engine)
        mock_dialog.assert_not_called()
        # with show dialogs
        self.assertRaises(
            error.VersionError,
            db.verify_connection,
            engine,
            show_error_dialogs=True,
        )
        mock_dialog.assert_called()

    @mock.patch("bauble.db.utils.message_dialog")
    def test_verify_connection_bad_version_raises(self, mock_dialog):
        engine = create_engine("sqlite:///:memory:")
        meta_table = meta.BaubleMeta.__table__
        with engine.connect() as connection:
            db.metadata.create_all(bind=connection)
            stmt = meta_table.insert().values(
                {"name": meta.CREATED_KEY, "value": "4/9/23"}
            )
            connection.execute(stmt)
            stmt = meta_table.insert().values(
                {"name": meta.VERSION_KEY, "value": "3"}
            )
            connection.execute(stmt)
        self.assertRaises(error.VersionError, db.verify_connection, engine)
        mock_dialog.assert_not_called()
        # with show dialogs
        self.assertRaises(
            error.VersionError,
            db.verify_connection,
            engine,
            show_error_dialogs=True,
        )
        mock_dialog.assert_called()

    @mock.patch("bauble.db.utils.message_dialog")
    def test_verify_connection_prior_version_raises(self, mock_dialog):
        engine = create_engine("sqlite:///:memory:")
        meta_table = meta.BaubleMeta.__table__
        with engine.connect() as connection:
            db.metadata.create_all(bind=connection)
            stmt = meta_table.insert().values(
                {"name": meta.CREATED_KEY, "value": "4/9/23"}
            )
            connection.execute(stmt)
            stmt = meta_table.insert().values(
                {"name": meta.VERSION_KEY, "value": "0.9.1"}
            )
            connection.execute(stmt)
        self.assertRaises(error.VersionError, db.verify_connection, engine)
        mock_dialog.assert_not_called()
        # with show dialogs
        self.assertRaises(
            error.VersionError,
            db.verify_connection,
            engine,
            show_error_dialogs=True,
        )
        mock_dialog.assert_called()

    def test_sqlite_fk_pragma_only_sqlite(self):
        from sqlite3 import Connection

        mock_connection = mock.Mock(spec=Connection)
        db._sqlite_fk_pragma(mock_connection, None)
        mock_connection.cursor.assert_called()
        mock_connection.cursor().execute.assert_called_with(
            "PRAGMA foreign_keys=ON;"
        )
        mock_connection.cursor().close.assert_called()

        # any other type
        mock_connection = mock.Mock()
        db._sqlite_fk_pragma(mock_connection, None)
        mock_connection.cursor.assert_not_called()

    def test_session_raises(self):
        db._Session = None

        self.assertRaises(DatabaseError, db.Session)
        with self.assertRaises(DatabaseError):
            with db.Session():
                pass
