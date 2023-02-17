# pylint: disable=missing-module-docstring
# Copyright (c) 2022-2023 Ross Demuth <rossdemuth123@gmail.com>
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

import os
from unittest import mock
from pathlib import Path

from gi.repository import Gtk, Gdk, Gio

from bauble.view import (AppendThousandRows,
                         HistoryView,
                         PicturesScroller,
                         SearchView,
                         Note,
                         multiproc_counter,
                         _mainstr_tmpl,
                         _substr_tmpl,
                         select_in_search_results,
                         PICTURESSCROLLER_WIDTH_PREF)
from bauble.test import (BaubleTestCase,
                         update_gui,
                         get_setUp_data_funcs,
                         wait_on_threads,
                         uri)
from bauble import db, utils, search, prefs, pluginmgr

# pylint: disable=too-few-public-methods


class TestMultiprocCounter(BaubleTestCase):
    def setUp(self):
        if ':memory:' in uri:
            # for the sake of multiprocessing, create a temp file database and
            # populate it rather than use an in memory database
            from tempfile import mkstemp
            self.db_handle, self.temp_db = mkstemp(suffix='.db', text=True)
            self.uri = f'sqlite:///{self.temp_db}'
            db.open_conn(self.uri, verify=False, show_error_dialogs=False)
            self.handle, self.temp = mkstemp(suffix='.cfg', text=True)
            # reason not to use `from bauble.prefs import prefs`
            prefs.default_prefs_file = self.temp
            prefs.prefs = prefs._prefs(filename=self.temp)
            prefs.prefs.init()
            prefs.prefs[prefs.web_proxy_prefs] = 'use_requests_without_proxies'
            pluginmgr.plugins = {}
            pluginmgr.load()
            db.create(import_defaults=False)
            pluginmgr.install('all', False, force=True)
            pluginmgr.init()
        else:
            super().setUp()
            self.uri = uri

        # add some data
        for func in get_setUp_data_funcs():
            func()
        self.session = db.Session()

    def tearDown(self):
        if ':memory:' in uri:
            self.session.close()
            os.close(self.db_handle)
            os.remove(self.temp_db)
            os.close(self.handle)
            os.remove(self.temp)
            db.engine.dispose()
        else:
            super().tearDown()

    def test_multiproc_counter_all_domains(self):
        # tests that relationships don't fail in the process
        # NOTE coverage can me a little flaky at times with this test with
        # occasion: "CoverageWarning: Data file '...' doesn't seem to be a
        # coverage data file: cannot unpack non-iterable NoneType object"
        # last .coverage file or so do not combine.
        # These seem to have no affect:
        # - pytest_cov's cleanup_on_sigterm() no matter where its placed
        # - using pool.map over pool.map_async (other than much slower)
        # leaving for now as final result does not seem to be effected
        from multiprocessing import get_context
        from functools import partial
        classes = []
        for klass in search.MapperSearch.get_domain_classes().values():
            if self.session.query(klass).get(1):
                classes.append(klass)

        results = []
        try:
            from pytest_cov.embed import cleanup_on_sigterm
        except ImportError:
            pass
        else:
            cleanup_on_sigterm()
        with get_context('spawn').Pool() as pool:
            procs = []
            for klass in classes:
                func = partial(multiproc_counter, self.uri, klass)
                procs.append(pool.map_async(func, [[1]]))

            for proc in procs:
                while not proc.ready():
                    proc.wait(0.1)

            for proc in procs:
                result = proc.get(9.0)
                results.append(result)

        for result in results:
            self.assertEqual(len(result), 1)
            self.assertTrue(isinstance(result[0], dict))
            self.assertGreaterEqual(len(result[0].keys()), 1)


class TestSearchView(BaubleTestCase):
    def setUp(self):
        super().setUp()
        self.search_view = SearchView()

    def tearDown(self):
        self.search_view.cancel_threads()
        super().tearDown()

    def test_row_meta_populates_with_all_domains(self):
        search_view = self.search_view
        self.assertEqual(
            list(search_view.row_meta.keys()),
            list(search.MapperSearch.get_domain_classes().values())
        )

    def test_all_domains_w_children_has_children_returns_correct(self):
        search_view = self.search_view
        for func in get_setUp_data_funcs():
            func()
        for cls in search.MapperSearch.get_domain_classes().values():
            if not SearchView.row_meta[cls].children:
                continue
            for obj in self.session.query(cls):
                self.assertIsInstance(obj.has_children(), bool, cls)
                kids = search_view.row_meta[cls].get_children(obj)
                has_kids = bool(kids)
                self.assertEqual(obj.has_children(), has_kids,
                                 f'{obj}: {kids}')

    def test_all_domains_w_children_count_children_returns_correct(self):
        search_view = self.search_view
        for func in get_setUp_data_funcs():
            func()
        for cls in search.MapperSearch.get_domain_classes().values():
            if not SearchView.row_meta[cls].children:
                continue
            for obj in self.session.query(cls):
                self.assertIsInstance(obj.count_children(), int, cls)
                kids = search_view.row_meta[cls].get_children(obj)
                kids_count = len(kids)
                self.assertEqual(obj.count_children(), kids_count,
                                 f'{obj}: {kids}')

    def test_all_domains_w_children_count_children_returns_active(self):
        prefs.prefs[prefs.exclude_inactive_pref] = True

        search_view = self.search_view
        for func in get_setUp_data_funcs():
            func()
        for cls in search.MapperSearch.get_domain_classes().values():
            if not SearchView.row_meta[cls].children:
                continue
            for obj in self.session.query(cls):
                self.assertIsInstance(obj.count_children(), int, cls)
                kids = search_view.row_meta[cls].get_children(obj)
                kids_count = len(kids)
                self.assertEqual(obj.count_children(), kids_count,
                                 f'{obj}: {kids}')

    def test_bottom_info_populates_with_note_and_tag(self):
        search_view = self.search_view
        self.assertEqual(
            list(search_view.bottom_info.keys()),
            [search.MapperSearch.get_domain_classes()['tag'], Note]
        )

    def test_row_meta_get_children(self):
        from sqlalchemy import Column, Integer, String, ForeignKey
        from sqlalchemy.orm import relationship

        class Parent(db.Base):
            __tablename__ = 'parent'
            name = Column('name', String(10))
            children = relationship('Child', back_populates='parent')

        class Child(db.Base):
            __tablename__ = 'child'
            name = Column('name', String(10))
            parent_id = Column(Integer, ForeignKey(Parent.id), nullable=False)
            parent = relationship(Parent, back_populates='children')

        SearchView.row_meta[Parent].set(children="children")

        search_view = self.search_view
        parent = Parent(name='test1')
        child = Child(name='test2', parent=parent)

        self.assertEqual(search_view.row_meta[Parent].get_children(parent),
                         [child])
        # remove so further tests don't fail
        del SearchView.row_meta.data[Parent]

    def test_on_test_expand_row_w_kids_returns_false_adds_kids(self):
        for func in get_setUp_data_funcs():
            func()
        search_view = self.search_view
        search_view.search('genus where id = 1')
        model = search_view.results_view.get_model()
        val = search_view.on_test_expand_row(
            search_view.results_view,
            model.get_iter_first(),
            Gtk.TreePath.new_first()
        )
        self.assertFalse(val)
        kid = model.get_value(model.get_iter_from_string('0:1'), 0)
        self.assertEqual(kid.genus_id, 1)

    def test_on_test_expand_row_w_no_kids_returns_true_adds_no_kids(self):
        # doesn't propagate
        for func in get_setUp_data_funcs():
            func()
        search_view = self.search_view
        search_view.search('plant where id = 1')
        model = search_view.results_view.get_model()
        val = search_view.on_test_expand_row(
            search_view.results_view,
            model.get_iter_first(),
            Gtk.TreePath.new_first()
        )
        self.assertTrue(val)
        with self.assertRaises(ValueError):
            model.get_iter_from_string('0:1')

    def test_remove_children(self):
        for func in get_setUp_data_funcs():
            func()
        search_view = self.search_view
        search_view.search('genus where id = 1')
        model = search_view.results_view.get_model()
        # expand a row
        search_view.on_test_expand_row(
            search_view.results_view,
            model.get_iter_first(),
            Gtk.TreePath.new_first()
        )
        start = search_view.get_selected_values()
        # check kids exist
        self.assertTrue(model.get_iter_from_string('0:1'))
        # remove them
        search_view.remove_children(model, model.get_iter_first())
        # kids removed
        with self.assertRaises(ValueError):
            model.get_iter_from_string('0:1')
        end = search_view.get_selected_values()
        # parent still exists
        self.assertEqual(start, end)

    def test_on_action_activate_supplies_selected_updates(self):
        for func in get_setUp_data_funcs():
            func()
        search_view = self.search_view
        search_view.search('genus where id = 1')
        values = search_view.get_selected_values()

        mock_callback = mock.Mock()
        mock_callback.return_value = True

        with self.assertLogs(level='DEBUG') as logs:
            search_view.on_action_activate(None, None, mock_callback)
            update_gui()
        self.assertTrue(any('SearchView::update' in i for i in logs.output))

        mock_callback.assert_called_with(values)

    @mock.patch('bauble.view.utils.message_details_dialog')
    def test_on_action_activate_with_error_notifies(self, mock_dialog):
        search_view = self.search_view
        mock_callback = mock.Mock()
        mock_callback.side_effect = ValueError('boom')
        search_view.on_action_activate(None, None, mock_callback)
        mock_dialog.assert_called_with('boom', mock.ANY, Gtk.MessageType.ERROR)

    @mock.patch('bauble.view.SearchView.get_selected_values')
    def test_on_note_row_activated(self, mock_get_selected):
        mock_tree = mock.Mock()
        mock_tree.get_model.return_value = {'note':
                                            [None, None, 'cat', 'note']}
        mock_get_selected.return_value = [type('Test', (), {})()]
        search_view = self.search_view
        self.assertEqual(
            search_view.on_note_row_activated(mock_tree, 'note', None),
            "test where notes[category='cat'].note='note'"
        )

    def test_search_no_result(self):
        search_view = self.search_view
        search_view.search('genus where epithet = None')
        model = search_view.results_view.get_model()
        self.assertIn('Could not find anything for search', model[0][0])
        # no infobox
        self.assertIsNone(search_view.infobox)

    def test_search_w_error(self):
        search_view = self.search_view
        mock_gui = mock.patch('bauble.gui')
        with mock.patch('bauble.gui') as mock_gui:
            mock_show_err_box = mock.Mock()
            mock_gui.show_error_box = mock_show_err_box
            search_view.search('accession where private = 3')
            mock_show_err_box.assert_called()
            self.assertTrue(
                mock_show_err_box.call_args.args[0].startswith('** Error: ')
            )
        # no infobox
        self.assertIsNone(search_view.infobox)

    def test_search_with_one_result_all_domains(self):
        prefs.prefs['bauble.search.return_accepted'] = False
        for func in get_setUp_data_funcs():
            func()
        search_view = self.search_view
        for klass in search_view.row_meta:
            if klass.__tablename__ == 'tag':
                continue
            domain = klass.__tablename__
            if domain not in search.MapperSearch.domains:
                domain = None
                for key, val in search.MapperSearch.domains.items():
                    if val[0] == klass:
                        domain = key
                        break

            string = f'{domain} where id = 1'
            with self.assertLogs(level='DEBUG') as logs:
                search_view.search(string)
                # wait for the CountResultsTask thread to finish
                wait_on_threads()
            # check counting occured
            self.assertTrue(any('top level count:' in i for i in logs.output))
            # test the correct object was returned
            model = search_view.results_view.get_model()
            obj = model[0][0]
            self.assertIsInstance(obj, klass)
            self.assertEqual(obj.id, 1)
            # check correct infobox (errors can cause no infobox)
            self.assertIsInstance(search_view.infobox,
                                  search_view.row_meta[klass].infobox)

    @mock.patch('bauble.view.SearchView.get_selected_values')
    def test_on_copy_selected(self, mock_get_selected):

        class MockData:
            field = 'Mock Field'

            @staticmethod
            def __str__():
                return 'Mock Data'

        mock_get_selected.return_value = [MockData()]
        search_view = self.search_view
        self.assertEqual(
            search_view.on_copy_selection(None, None),
            "Mock Data, MockData"
        )
        prefs.prefs['copy_templates.mockdata'] = '${value}, ${value.field}'

        mock_get_selected.return_value = [MockData()]
        self.assertEqual(
            search_view.on_copy_selection(None, None),
            "Mock Data, Mock Field"
        )

    def test_cell_data_func(self):
        for func in get_setUp_data_funcs():
            func()
        search_view = self.search_view
        search_view.search('genus where id < 3')

        selected = search_view.get_selected_values()[0]

        mock_renderer = mock.Mock()
        results_view = search_view.results_view
        model = results_view.get_model()
        tree_iter = model.get_iter(Gtk.TreePath.new_first())
        search_view.cell_data_func(results_view.get_column(0),
                                   mock_renderer,
                                   model,
                                   tree_iter,
                                   None)
        mock_renderer.set_property.assert_called()
        main, substr = selected.search_view_markup_pair()
        markup = (f'{_mainstr_tmpl % utils.nstr(main)}\n'
                  f'{_substr_tmpl % utils.nstr(substr)}')
        mock_renderer.set_property.assert_called_with('markup', markup)

        # change selection and check it updates
        path = Gtk.TreePath.new_from_string('1')
        search_view.results_view.set_cursor(path)

        selected2 = search_view.get_selected_values()[0]
        self.assertNotEqual(selected, selected2)

        mock_renderer = mock.Mock()
        results_view = search_view.results_view
        model = results_view.get_model()
        tree_iter = model.get_iter(path)
        search_view.cell_data_func(results_view.get_column(0),
                                   mock_renderer,
                                   model,
                                   tree_iter,
                                   None)
        mock_renderer.set_property.assert_called()
        main, substr = selected2.search_view_markup_pair()
        markup = (f'{_mainstr_tmpl % utils.nstr(main)}\n'
                  f'{_substr_tmpl % utils.nstr(substr)}')
        mock_renderer.set_property.assert_called_with('markup', markup)

    def test_cell_data_func_w_deleted(self):
        # as if another user had deleted an item we were also looking at.
        for func in get_setUp_data_funcs():
            func()
        search_view = self.search_view
        search_view.search('genus where id > 3 and id < 7')

        start = search_view.get_selected_values()

        mock_renderer = mock.Mock()
        results_view = search_view.results_view
        model = results_view.get_model()
        tree_iter = model.get_iter(Gtk.TreePath.new_first())
        # delete item
        db.engine.execute(
            f"DELETE FROM species WHERE genus_id = {start[0].id}"
        )
        db.engine.execute(f"DELETE FROM genus WHERE id = {start[0].id}")

        with self.assertLogs(level='DEBUG') as logs:
            search_view.cell_data_func(results_view.get_column(0),
                                       mock_renderer,
                                       model,
                                       tree_iter,
                                       None)
            update_gui()
        end = search_view.get_selected_values()
        self.assertNotEqual(start, end)
        self.assertTrue(any('remove_row called' in i for i in logs.output))

    def test_cell_data_func_w_added_adds_item(self):
        # as if another user had deleted an item we were also looking at.
        for func in get_setUp_data_funcs():
            func()
        search_view = self.search_view
        search_view.search('genus where id = 1')

        results_view = search_view.results_view
        model = results_view.get_model()
        path = Gtk.TreePath.new_first()
        tree_iter = model.get_iter(path)
        # expand
        search_view.on_test_expand_row(results_view, tree_iter, path)
        results_view.expand_all()
        update_gui()

        start = model.iter_n_children(tree_iter)
        self.assertGreater(start, 1)
        # add new item
        db.engine.execute(
            """
            INSERT INTO species (sp, genus_id, _created, _last_updated)
            VALUES ('test2', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """
        )

        mock_renderer = mock.Mock()
        search_view.cell_data_func(results_view.get_column(0),
                                   mock_renderer,
                                   model,
                                   tree_iter,
                                   None)
        update_gui()
        end = model.iter_n_children(tree_iter)
        self.assertEqual(start + 1, end)

    def test_update_expires_all_and_triggers_selection_change(self):
        for func in get_setUp_data_funcs():
            func()
        search_view = self.search_view
        search_view.search('accession where id < 3')
        with self.assertLogs(level='DEBUG') as logs:
            search_view.update()
        self.assertTrue(any('SearchView::update' in i for i in logs.output))
        self.assertTrue(any('SearchView::on_selection_changed' in i for i in
                            logs.output))
        self.assertTrue(any('SearchView::update_infobox' in i for i in
                            logs.output))
        # check everything is expired. (except the currently selected obj as
        # it has already been accessed)
        from sqlalchemy import inspect
        selected = search_view.get_selected_values()[0]
        for obj in search_view.session:
            # get state before accessing the obj.
            expired = bool(inspect(obj).expired_attributes)
            if obj.id == selected.id:
                continue
            self.assertTrue(expired, obj)

    def test_on_view_button_press_not_3_returns_false(self):
        for func in get_setUp_data_funcs():
            func()
        search_view = self.search_view
        search_view.search('genus where id = 1')

        results_view = search_view.results_view

        # test bails on non 3 buttons and returns False (allows propagating the
        # event)
        mock_button = mock.Mock(button=1, x=1, y=1)
        self.assertFalse(
            search_view.on_view_button_press(results_view, mock_button)
        )

        mock_button = mock.Mock(button=2, x=1, y=1)
        self.assertFalse(
            search_view.on_view_button_press(results_view, mock_button)
        )

        mock_button = mock.Mock(button=4, x=1, y=1)
        self.assertFalse(
            search_view.on_view_button_press(results_view, mock_button)
        )

    def test_on_view_button_press_3_outside_selection_returns_false(self):
        for func in get_setUp_data_funcs():
            func()
        search_view = self.search_view
        search_view.search('genus where id = 1')

        results_view = search_view.results_view

        event = Gdk.EventButton()
        event.type = Gdk.EventType.BUTTON_PRESS
        event.button = 3
        event.x = 1.0
        event.y = 1.0

        with self.assertLogs(level='DEBUG') as logs:
            self.assertFalse(
                search_view.on_view_button_press(results_view, event)
            )

        self.assertTrue(any('view button 3 press' in i for i in logs.output))

    def test_on_view_button_press_3_inside_selection_returns_true(self):
        for func in get_setUp_data_funcs():
            func()
        search_view = self.search_view
        search_view.search('genus where id = 1')

        event = Gdk.EventButton()
        event.type = Gdk.EventType.BUTTON_PRESS
        event.button = 3
        event.x = 1.0
        event.y = 1.0

        mock_view = mock.Mock()
        mock_view.get_path_at_pos.return_value = (0, 0, 0, 0)

        with self.assertLogs(level='DEBUG') as logs:
            self.assertTrue(
                search_view.on_view_button_press(mock_view, event)
            )

        self.assertTrue(any('view button 3 press' in i for i in logs.output))

    def test_on_view_button_release_not_3_returns_false(self):
        for func in get_setUp_data_funcs():
            func()
        search_view = self.search_view
        search_view.search('genus where id = 1')

        results_view = search_view.results_view
        mock_callback = mock.Mock()
        mock_callback.return_value = Gio.Menu()

        search_view.context_menu_callbacks = set([mock_callback])

        # test bails on non 3 buttons and returns False (allows propagating the
        # event)
        mock_button = mock.Mock(button=1, x=1, y=1, time=100000000)
        self.assertFalse(
            search_view.on_view_button_release(results_view, mock_button)
        )
        mock_callback.assert_not_called()

        mock_button = mock.Mock(button=2, x=1, y=1, time=100000000)
        self.assertFalse(
            search_view.on_view_button_release(results_view, mock_button)
        )
        mock_callback.assert_not_called()

        mock_button = mock.Mock(button=4, x=1, y=1, time=100000000)
        self.assertFalse(
            search_view.on_view_button_release(results_view, mock_button)
        )
        mock_callback.assert_not_called()

    def test_on_view_button_release_3_returns_true(self):
        for func in get_setUp_data_funcs():
            func()
        search_view = self.search_view
        search_view.search('genus where id = 1')

        results_view = search_view.results_view
        mock_callback = mock.Mock()
        mock_callback.return_value = Gio.Menu()

        search_view.context_menu_callbacks = set([mock_callback])

        event = Gdk.EventButton()
        event.type = Gdk.EventType.BUTTON_RELEASE
        event.button = 3

        self.assertTrue(
            search_view.on_view_button_release(results_view, event)
        )
        mock_callback.assert_called()


class TestHistoryView(BaubleTestCase):

    def test_populates_listore(self):
        # also tests populating history I suppose
        for func in get_setUp_data_funcs():
            func()

        history_count = self.session.query(db.History).count()
        self.assertLess(history_count, 5)

        # get a notes class and parent model...
        for klass in search.MapperSearch.get_domain_classes().values():
            if (hasattr(klass, 'notes') and
                    hasattr(klass.notes, 'mapper')):
                note_cls = klass.notes.mapper.class_
                parent_model = klass()
                break

        # populate parent model with junk data...
        for col in parent_model.__table__.columns:
            if not col.nullable:
                if col.name.endswith('_id'):
                    setattr(parent_model, col.name, 1)
                if not getattr(parent_model, col.name):
                    setattr(parent_model, col.name, '567')

        # add 5 notes
        for i in range(5):
            parent_model.notes.append(note_cls(note=f'test{i}'))

        session = db.Session()
        session.add(parent_model)
        session.commit()

        history_count = self.session.query(db.History).count()
        self.assertGreater(history_count, 5)

        hist_view = HistoryView()
        hist_view.update(None)
        # wait for the thread to finish
        wait_on_threads()
        update_gui()
        self.assertEqual(len(hist_view.liststore), history_count)
        # nothing selected
        self.assertIsNone(hist_view.get_selected_value())
        # select something
        hist_view.history_tv.set_cursor(0)
        self.assertIsNotNone(hist_view.get_selected_value())
        session.close()

    def test_add_row(self):
        from datetime import datetime

        mock_hist_item = mock.Mock(
            timestamp=datetime.today(),
            operation='insert',
            user='Jade Green',
            table_name='mock_table',
            values={'id': 1, 'data': 'some random data', 'name': 'test name',
                    '_created': None, '_last_updated': None}
        )

        hist_view = HistoryView()
        hist_view.add_row(mock_hist_item)
        first_row = hist_view.liststore[0]
        self.assertEqual(first_row[hist_view.TVC_TABLE],
                         mock_hist_item.table_name)
        self.assertEqual(first_row[hist_view.TVC_USER],
                         mock_hist_item.user)

    def test_button_release(self):
        mock_context = mock.Mock()
        hist_view = HistoryView()
        hist_view.context_menu = mock_context
        self.assertFalse(hist_view.on_button_release(None,
                                                     mock.Mock(button=1)))
        mock_context.popup_at_pointer.assert_not_called()
        self.assertTrue(hist_view.on_button_release(None, mock.Mock(button=3)))
        mock_context.popup_at_pointer.assert_called()

    @mock.patch('bauble.utils.yes_no_dialog')
    def test_on_revert_to_history(self, mock_dialog):
        mock_dialog.return_value = True
        # load history
        for setup in get_setUp_data_funcs():
            setup()

        # get a notes class and parent model...
        for klass in search.MapperSearch.get_domain_classes().values():
            if (hasattr(klass, 'notes') and
                    hasattr(klass.notes, 'mapper')):
                note_cls = klass.notes.mapper.class_
                parent_model = klass()
                break

        # populate parent model with junk data...
        for col in parent_model.__table__.columns:
            if not col.nullable:
                if col.name.endswith('_id'):
                    setattr(parent_model, col.name, 1)
                if not getattr(parent_model, col.name):
                    setattr(parent_model, col.name, '567')
        # add 5 notes
        for i in range(5):
            parent_model.notes.append(note_cls(note=f'test{i}'))

        self.session.add(parent_model)
        self.session.commit()

        start_count = self.session.query(note_cls).count()
        self.assertEqual(start_count, 6)

        hist_view = HistoryView()
        hist_view.update(None)
        # wait for the thread to finish
        wait_on_threads()
        update_gui()
        # select something
        hist_view.history_tv.set_cursor(3)
        selected = hist_view.get_selected_value()
        remainder = (self.session.query(note_cls)
                     .filter(note_cls.id < selected.table_id)
                     .count())
        hist_view.on_revert_to_history(None, None)
        mock_dialog.assert_called()
        self.assertEqual(self.session.query(note_cls).count(), remainder)
        wait_on_threads()

    @mock.patch('bauble.view.HistoryView.get_selected_value')
    def test_on_copy_values(self, mock_get_selected):
        geojson = {'type': 'Point', 'coordinate': [1, 2]}
        from datetime import datetime
        vals = {'id': 1, 'genus_id': 10, 'note': 'test note',
                '_created': None, '_last_updated': None}
        values = dict(vals)
        values['geojson'] = geojson

        mock_hist_item = mock.Mock(
            timestamp=datetime.today(),
            operation='insert',
            user='Jade Green',
            table_name='genus_note',
            table_id=1,
            values=values
        )
        mock_get_selected.return_value = mock_hist_item

        hist_view = HistoryView()
        import json
        self.assertEqual(hist_view.on_copy_values(None, None),
                         json.dumps(vals))

    @mock.patch('bauble.view.HistoryView.get_selected_value')
    def test_on_copy_geojson(self, mock_get_selected):
        from datetime import datetime
        geojson = {'type': 'Point', 'coordinate': [1, 2]}
        values = {'id': 1, 'name': 'name data', '_created': None,
                  '_last_updated': None, 'geojson': geojson}

        mock_hist_item = mock.Mock(
            timestamp=datetime.today(),
            operation='insert',
            user='Jade Green',
            table_name='mock_table',
            table_id=1,
            values=values,
            geojson=geojson
        )
        mock_get_selected.return_value = mock_hist_item

        hist_view = HistoryView()
        import json
        self.assertEqual(hist_view.on_copy_geojson(None, None),
                         json.dumps(geojson))

    def test_on_row_activated(self):
        from datetime import datetime

        mock_hist_item = mock.Mock(
            timestamp=datetime.today(),
            operation='insert',
            user='Jade Green',
            table_name='genus_note',
            table_id=1,
            values={'id': 1, 'genus_id': 10, 'note': 'test note',
                    '_created': None, '_last_updated': None}
        )

        hist_view = HistoryView()
        hist_view.add_row(mock_hist_item)
        self.assertEqual(hist_view.on_row_activated(None, 0, None),
                         'genus where notes.id = 1')

    def test_basic_search_query_filters_eq(self):
        string = 'table_name = plant'
        result = AppendThousandRows(None, string).get_query_filters()
        self.assertTrue(result[0].compare(db.History.table_name == 'plant'))

    def test_basic_search_query_filters_not_eq(self):
        string = 'table_name != plant'
        result = AppendThousandRows(None, string).get_query_filters()
        self.assertTrue(result[0].compare(db.History.table_name != 'plant'))

    def test_basic_search_query_filters_w_and(self):
        string = ("table_name = plant and user = 'test user' and operation ="
                  " insert")
        result = AppendThousandRows(None, string).get_query_filters()
        # self.assertEqual(str(result[0]), "")
        self.assertTrue(result[0].compare(db.History.table_name == 'plant'))
        self.assertTrue(result[1].compare(db.History.user == 'test user'))
        self.assertTrue(result[2].compare(db.History.operation == 'insert'))

    def test_basic_search_query_filters_like(self):
        # comparing strings like this isn't ideal, doesn't test value but
        # compare() does not work here (at least not in sqlalchemy v1.3.24)
        string = "values like %id"
        result = AppendThousandRows(None, string).get_query_filters()
        self.assertEqual(str(result[0]),
                         str(utils.ilike(db.History.values, '%id')))

    def test_basic_search_query_filters_contains(self):
        # comparing strings like this in't ideal, doesn't test value but
        # compare() does not work here (at least not in sqlalchemy v1.3.24)
        string = "values contains id"
        result = AppendThousandRows(None, string).get_query_filters()
        self.assertEqual(str(result[0]),
                         str(utils.ilike(db.History.values, '%id')))

    def test_basic_search_query_filters_fails(self):
        string = "test = test"
        self.assertRaises(AttributeError,
                          AppendThousandRows(None, string).get_query_filters)


class TestPicturesScroller(BaubleTestCase):
    def test_on_destroy_records_width(self):
        window = Gtk.Window()
        window.resize(300, 300)
        box = Gtk.Box()
        paned = Gtk.Paned()
        box2 = Gtk.Box()
        paned.pack1(box2)
        box.pack_start(paned, True, True, 1)
        window.add(box)
        PicturesScroller(parent=paned)
        self.assertIsNone(prefs.prefs.get(PICTURESSCROLLER_WIDTH_PREF))
        paned.set_position(100)
        window.show_all()
        window.destroy()
        self.assertGreater(prefs.prefs.get(PICTURESSCROLLER_WIDTH_PREF), 100)

    def test_set_width_sets_parent_pane_position(self):
        window = Gtk.Window()
        window.resize(500, 500)
        box = Gtk.Box()
        paned = Gtk.Paned()
        box2 = Gtk.Box()
        paned.pack1(box2)
        box.pack_start(paned, True, True, 1)
        window.add(box)
        PicturesScroller(parent=paned).set_width()
        # default position if not set
        self.assertEqual(paned.get_position(), 1000 - 300 - 300 - 6)

    def test_set_selection_adds_children(self):
        box = Gtk.Box()
        paned = Gtk.Paned()
        box2 = Gtk.Box()
        paned.pack1(box2)
        box.pack_start(paned, True, True, 1)
        picture_scroller = PicturesScroller(parent=paned)
        self.assertFalse(picture_scroller.pictures_box.get_children())
        picture_scroller.set_selection([
            mock.Mock(
                pictures=[mock.Mock(picture='test.jpg', category='test')]
            )
        ])
        self.assertEqual(len(picture_scroller.pictures_box.get_children()), 1)

    @mock.patch('bauble.utils.desktop.open')
    def test_on_button_press_opens_picture(self, mock_open):
        box = Gtk.Box()
        paned = Gtk.Paned()
        box2 = Gtk.Box()
        paned.pack1(box2)
        box.pack_start(paned, True, True, 1)
        picture_scroller = PicturesScroller(parent=paned)
        mock_event = mock.Mock(button=1, type=Gdk.EventType._2BUTTON_PRESS)
        picture_scroller.on_button_press(None, mock_event, 'test.jpg')
        mock_open.assert_called_with(Path('test.jpg'))


class GlobalFunctionsTests(BaubleTestCase):
    def test_select_in_search_results_selects_existing(self):
        for func in get_setUp_data_funcs():
            func()
        search_view = SearchView()
        search_view.search('genus where id <= 3')
        start = search_view.get_selected_values()
        obj = self.session.query(start[0].__class__).get(3)
        with mock.patch('bauble.gui') as mock_gui:
            mock_gui.get_view.return_value = search_view
            select_in_search_results(obj)
        end = search_view.get_selected_values()
        self.assertNotEqual(start, end)
        self.assertEqual(end[0].id, obj.id)
        search_view.cancel_threads()

    def test_select_in_search_results_adds_not_existing(self):
        for func in get_setUp_data_funcs():
            func()
        search_view = SearchView()
        search_view.search('genus where id <= 3')
        start = search_view.get_selected_values()
        obj = self.session.query(start[0].__class__).get(5)
        with mock.patch('bauble.gui') as mock_gui:
            mock_gui.get_view.return_value = search_view
            with self.assertLogs(level='DEBUG') as logs:
                select_in_search_results(obj)
        self.assertTrue(any(f'{obj} added to search results' in i for i in
                            logs.output))
        end = search_view.get_selected_values()
        self.assertNotEqual(start, end)
        self.assertEqual(end[0].id, obj.id)
        update_gui()
        search_view.cancel_threads()
