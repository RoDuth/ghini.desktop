# Copyright (c) 2025 Ross Demuth <rossdemuth123@gmail.com>
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

from gi.repository import Gtk
from sqlalchemy import inspect
from sqlalchemy.exc import SQLAlchemyError

from bauble import db
from bauble.meta import BaubleMeta
from bauble.search.stored_queries import StoredQueriesButtonBox
from bauble.search.stored_queries import StoredQueriesDialog
from bauble.search.stored_queries import StoredQuery
from bauble.search.stored_queries import StoredQueryEditorDialog
from bauble.search.stored_queries import _upgrade_stored_queries
from bauble.test import BaubleTestCase


class StoredQueryTests(BaubleTestCase):
    def test_stored_query_editor_dialog(self):
        sq = StoredQuery(
            name="Test",
            description="Test description",
            query="plant where id=0",
        )
        self.session.add(sq)
        self.session.commit()
        editor = StoredQueryEditorDialog(sq)
        editor.query_textbuffer.set_text("plant where id=1")
        editor.name_entry.set_text("New Name")
        editor.description_textbuffer.set_text("New Description")

        self.assertEqual(sq.name, "New Name")
        self.assertEqual(sq.description, "New Description")
        self.assertEqual(sq.query, "plant where id=1")
        editor.destroy()

    def test_stored_queries_dialog(self):
        # pylint: disable=not-an-iterable
        sq1 = StoredQuery(
            name="Test1",
            description="Test description 1",
            query="plant where id=0",
        )
        sq2 = StoredQuery(
            name="Test2",
            description="Test description 2",
            query="plant where id=1",
        )
        self.session.add(sq1)
        self.session.add(sq2)
        self.session.commit()
        dialog = StoredQueriesDialog()

        self.assertEqual(len(dialog.list_store), 2)
        self.assertCountEqual(
            [i[0].name for i in dialog.list_store], [sq1.name, sq2.name]
        )

    @mock.patch("bauble.search.stored_queries.StoredQueryEditorDialog")
    def test_on_new_button_clicked(self, mock_editor):
        dialog = StoredQueriesDialog()
        self.assertEqual(len(dialog.list_store), 0)
        mock_editor().run.return_value = Gtk.ResponseType.CANCEL

        dialog.on_new_button_clicked(None)

        self.assertTrue(mock_editor.called)
        self.assertEqual(len(dialog.list_store), 0)

        mock_editor().run.return_value = Gtk.ResponseType.OK

        dialog.on_new_button_clicked(None)

        self.assertTrue(mock_editor.called)
        self.assertEqual(len(dialog.list_store), 1)
        self.assertTrue(dialog.ok_button.get_sensitive())

        dialog.destroy()

    @mock.patch("bauble.search.stored_queries.StoredQueryEditorDialog")
    def test_on_edit_button_clicked(self, mock_editor):
        # pylint: disable=unsubscriptable-object,no-value-for-parameter
        sq1 = StoredQuery(
            name="Test1",
            description="Test description 1",
            query="plant where id=0",
        )
        self.session.add(sq1)
        self.session.commit()
        dialog = StoredQueriesDialog()
        dialog.refresh()

        self.assertEqual(len(dialog.list_store), 1)
        self.assertEqual(dialog.list_store[0][0].name, "Test1")

        # nothing selected
        dialog.on_edit_button_clicked(None)
        self.assertFalse(mock_editor.called)

        # edit but cancel
        dialog.selection.select_path(Gtk.TreePath.new_first())
        mock_editor().run.return_value = Gtk.ResponseType.CANCEL
        # make a change
        dialog.list_store[0][0].name = "Changed Name"
        self.assertTrue(dialog.session.is_modified(dialog.list_store[0][0]))
        dialog.on_edit_button_clicked(None)

        self.assertTrue(mock_editor.called)
        self.assertEqual(len(dialog.list_store), 1)
        self.assertEqual(dialog.list_store[0][0].name, "Test1")
        self.assertFalse(dialog.ok_button.get_sensitive())
        # change is undone
        self.assertFalse(dialog.session.is_modified(dialog.list_store[0][0]))

        # edit and ok
        dialog.selection.select_path(Gtk.TreePath.new_first())
        mock_editor().run.return_value = Gtk.ResponseType.OK

        # make a change
        dialog.list_store[0][0].name = "Changed Name"
        self.assertTrue(dialog.session.is_modified(dialog.list_store[0][0]))
        dialog.on_edit_button_clicked(None)

        self.assertTrue(mock_editor.called)
        self.assertEqual(len(dialog.list_store), 1)
        self.assertEqual(dialog.list_store[0][0].name, "Changed Name")
        self.assertTrue(dialog.ok_button.get_sensitive())
        # change not undone
        self.assertTrue(dialog.session.is_modified(dialog.list_store[0][0]))

        dialog.destroy()

    def test_on_delete_button_clicked(self):
        # pylint: disable=unsubscriptable-object,no-value-for-parameter
        sq1 = StoredQuery(
            name="Test1",
            description="Test description 1",
            query="plant where id=0",
        )
        self.session.add(sq1)
        self.session.commit()
        dialog = StoredQueriesDialog()
        dialog.refresh()

        self.assertEqual(len(dialog.list_store), 1)
        self.assertEqual(dialog.list_store[0][0].name, "Test1")

        # nothing selected
        dialog.on_delete_button_clicked(None)
        self.assertEqual(len(dialog.list_store), 1)
        self.assertFalse(dialog.ok_button.get_sensitive())

        # delete selected
        dialog.selection.select_path(Gtk.TreePath.new_first())
        dialog.on_delete_button_clicked(None)

        self.assertIn(dialog.list_store[0][0], dialog.session.deleted)
        self.assertTrue(dialog.ok_button.get_sensitive())

        dialog.destroy()

    def test_cell_data_func(self):
        sq1 = StoredQuery(
            name="Test1",
            description="Test description 1",
            query="plant where id=0",
        )
        self.session.add(sq1)
        self.session.commit()
        dialog = StoredQueriesDialog()
        sq1 = dialog.session.merge(sq1)
        mock_cell = mock.Mock()
        model = Gtk.ListStore(object)
        model.append([sq1])
        dialog.cell_data_func(
            None,
            mock_cell,
            model,
            model.get_iter_first(),
            "name",
        )

        # nothing changed
        self.assertEqual(
            mock_cell.set_property.call_args_list,
            [
                mock.call("text", "Test1"),
                mock.call("foreground", None),
            ],
        )

        sq1.name = "Changed Name"
        mock_cell.reset_mock()
        dialog.cell_data_func(
            None,
            mock_cell,
            model,
            model.get_iter_first(),
            "name",
        )

        # after change
        self.assertEqual(
            mock_cell.set_property.call_args_list,
            [
                mock.call("text", "Changed Name"),
                mock.call("foreground", None),
                mock.call("foreground", "blue"),
            ],
        )

        dialog.session.delete(sq1)
        mock_cell.reset_mock()
        dialog.cell_data_func(
            None,
            mock_cell,
            model,
            model.get_iter_first(),
            "name",
        )

        # after change and delete
        self.assertEqual(
            mock_cell.set_property.call_args_list,
            [
                mock.call("text", "Changed Name"),
                mock.call("foreground", None),
                mock.call("foreground", "blue"),
                mock.call("foreground", "red"),
            ],
        )

        dialog.destroy()


class StoredQueriesButtonBoxTests(BaubleTestCase):

    @mock.patch("bauble.search.stored_queries.StoredQueriesDialog")
    def test_on_edit_button_clicked_calls_dialog(self, mock_dialog):
        # pylint: disable=no-self-use
        button_box = StoredQueriesButtonBox()
        mock_dialog().run.return_value = Gtk.ResponseType.CANCEL
        button_box.on_edit_button_clicked(None)

        mock_dialog.assert_called()
        mock_dialog().session.commit.assert_not_called()

        mock_dialog().run.return_value = Gtk.ResponseType.OK
        button_box.on_edit_button_clicked(None)

        mock_dialog.assert_called()
        mock_dialog().session.commit.assert_called()

    def test_refresh(self):
        button_box = StoredQueriesButtonBox()
        button_box.refresh()

        self.assertEqual(len(button_box.query_button_box.get_children()), 0)

        sq1 = StoredQuery(
            name="Test1",
            description="Test description 1",
            query="plant where id=0",
        )
        self.session.add(sq1)
        self.session.commit()
        button_box.refresh()

        self.assertEqual(len(button_box.query_button_box.get_children()), 1)

        # test signal handler
        with mock.patch("bauble.gui") as mock_gui:
            button_box.query_button_box.get_children()[0].emit("clicked")
            mock_gui.send_command.assert_called_with(sq1.query)

    def test_refresh_upgrades(self):
        # prior to v1.3.16 there was no stored_queries table, queries where in
        # the bauble meta table
        stored_queries = self.session.query(StoredQuery).all()

        self.assertEqual(len(stored_queries), 0)

        meta_stqr = BaubleMeta(name="stqr_01", value="test:spam:Mel vim")
        self.session.add(meta_stqr)
        self.session.commit()
        StoredQuery.__table__.drop()
        button_box = StoredQueriesButtonBox()
        button_box.refresh()
        stored_queries = self.session.query(StoredQuery).all()

        self.assertEqual(len(stored_queries), 1)
        self.assertEqual(stored_queries[0].name, "test")
        self.assertEqual(stored_queries[0].description, "spam")
        self.assertEqual(stored_queries[0].query, "Mel vim")

    @mock.patch("bauble.search.stored_queries._get_meta_stored_queries")
    def test_upgrade_stored_queries_errors(self, mock_get):
        # prior to v1.3.16 there was no stored_queries table, queries where in
        # the bauble meta table
        stored_queries = self.session.query(StoredQuery).all()

        self.assertEqual(len(stored_queries), 0)

        meta_stqr = BaubleMeta(name="stqr_01", value="test:spam:Mel vim")
        self.session.add(meta_stqr)
        self.session.commit()
        mock_get.return_value = [(meta_stqr.id, meta_stqr.value)]

        # FAILS TO CREATE TABLE:
        StoredQuery.__table__.drop()
        with mock.patch(
            "bauble.search.stored_queries.StoredQuery.__table__"
        ) as mock_table:
            mock_table.create.side_effect = SQLAlchemyError
            _upgrade_stored_queries()
        # still
        self.assertFalse(
            inspect(db.engine).has_table(StoredQuery.__tablename__)
        )
        # left meta_stqr in place
        meta_queries = (
            self.session.query(BaubleMeta)
            .filter(BaubleMeta.name.like("stqr_%"))
            .all()
        )

        self.assertEqual(len(meta_queries), 1)
        self.assertEqual(meta_queries[0].id, meta_stqr.id)

        # FAILS TO MIGRATE (ValueError):
        mock_get.return_value = [(meta_stqr.value,)]
        # add table back
        StoredQuery.__table__.create()
        self.assertTrue(
            inspect(db.engine).has_table(StoredQuery.__tablename__)
        )
        _upgrade_stored_queries()
        # left meta_stqr in place and didn't add anything to StoredQuery table
        meta_queries = (
            self.session.query(BaubleMeta)
            .filter(BaubleMeta.name.like("stqr_%"))
            .all()
        )
        stored_queries = self.session.query(StoredQuery).all()

        self.assertEqual(len(meta_queries), 1)
        self.assertEqual(meta_queries[0].id, meta_stqr.id)
        self.assertEqual(len(stored_queries), 0)

        # FAILS TO COMMIT:
        mock_get.return_value = [(meta_stqr.id, meta_stqr.value)]
        with mock.patch(
            "bauble.search.stored_queries.db.Session"
        ) as mock_sess:
            mock_sess().__enter__().commit.side_effect = SQLAlchemyError
            with self.assertLogs(level="DEBUG") as logs:
                _upgrade_stored_queries()
            self.assertTrue(any("SQLAlchemyError" in i for i in logs.output))
        meta_queries = (
            self.session.query(BaubleMeta)
            .filter(BaubleMeta.name.like("stqr_%"))
            .all()
        )
        stored_queries = self.session.query(StoredQuery).all()

        self.assertEqual(len(meta_queries), 1)
        self.assertEqual(meta_queries[0].id, meta_stqr.id)
        self.assertEqual(len(stored_queries), 0)

        # NO ERROR
        _upgrade_stored_queries()
        meta_queries = (
            self.session.query(BaubleMeta)
            .filter(BaubleMeta.name.like("stqr_%"))
            .all()
        )
        stored_queries = self.session.query(StoredQuery).all()

        self.assertEqual(len(meta_queries), 0)
        self.assertEqual(len(stored_queries), 1)
        self.assertEqual(stored_queries[0].name, "test")
        self.assertEqual(stored_queries[0].description, "spam")
        self.assertEqual(stored_queries[0].query, "Mel vim")
