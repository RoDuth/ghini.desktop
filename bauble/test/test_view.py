# pylint: disable=missing-module-docstring
# Copyright (c) 2022 Ross Demuth <rossdemuth123@gmail.com>
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
from unittest import mock, TestCase

from gi.repository import Gtk, Gdk, Gio

from bauble.view import (AppendThousandRows,
                         HistoryView,
                         SearchView,
                         Note,
                         multiproc_counter,
                         _mainstr_tmpl,
                         _substr_tmpl,
                         select_in_search_results)
from bauble.test import BaubleTestCase, update_gui, get_setUp_data_funcs
from bauble import db, utils, search, prefs, pluginmgr

# pylint: disable=too-few-public-methods


class TestMultiprocCounter(TestCase):
    def setUp(self):
        # for the sake of multiprocessng, setUp here creates a temp file
        # database and populates it
        from tempfile import mkstemp
        self.db_handle, self.temp_db = mkstemp(suffix='.db', text=True)
        self.uri = f'sqlite:///{self.temp_db}'
        db.open(self.uri, verify=False, show_error_dialogs=False)
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
        db.create(import_defaults=False)

        # add some data
        for func in get_setUp_data_funcs():
            func()
        self.session = db.Session()

    def tearDown(self):
        self.session.close()
        os.close(self.db_handle)
        os.remove(self.temp_db)
        os.close(self.handle)
        os.remove(self.temp)
        db.engine.dispose()

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
                pool.terminate()

        for result in results:
            self.assertEqual(len(result), 1)
            self.assertTrue(isinstance(result[0], dict))
            self.assertGreaterEqual(len(result[0].keys()), 1)


class TestSearchView(BaubleTestCase):
    def test_row_meta_populates_with_all_domains(self):
        search_view = SearchView()
        self.assertEqual(
            list(search_view.row_meta.keys()),
            list(search.MapperSearch.get_domain_classes().values())
        )

    def test_all_domains_w_children_has_children_returns_correct(self):
        search_view = SearchView()
        for func in get_setUp_data_funcs():
            func()
        for cls in search.MapperSearch.get_domain_classes().values():
            print(cls)
            if not SearchView.row_meta[cls].children:
                continue
            for obj in self.session.query(cls):
                self.assertIsInstance(obj.has_children(), bool, cls)
                kids = search_view.row_meta[cls].get_children(obj)
                has_kids = bool(kids)
                self.assertEqual(obj.has_children(), has_kids,
                                 f'{obj}: {kids}')

    def test_bottom_info_populates_with_note_and_tag(self):
        search_view = SearchView()
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

        search_view = SearchView()
        parent = Parent(name='test1')
        child = Child(name='test2', parent=parent)

        self.assertEqual(search_view.row_meta[Parent].get_children(parent),
                         [child])
        # remove so further tests don't fail
        del SearchView.row_meta.data[Parent]

    def test_on_test_expand_row_w_kids_returns_false_adds_kids(self):
        for func in get_setUp_data_funcs():
            func()
        search_view = SearchView()
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
        search_view = SearchView()
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
        search_view = SearchView()
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
        search_view = SearchView()
        search_view.search('genus where id = 1')
        values = search_view.get_selected_values()

        mock_callback = mock.Mock()
        mock_callback.return_value = True

        with self.assertLogs(level='DEBUG') as logs:
            search_view.on_action_activate(None, None, mock_callback)
        self.assertTrue(any('SearchView::update' in i for i in logs.output))

        mock_callback.assert_called_with(values)

    @mock.patch('bauble.view.utils.message_details_dialog')
    def test_on_action_activate_with_error_notifies(self, mock_dialog):
        search_view = SearchView()
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
        search_view = SearchView()
        self.assertEqual(
            search_view.on_note_row_activated(mock_tree, 'note', None),
            "test where notes[category='cat'].note='note'"
        )

    def test_search_no_result(self):
        search_view = SearchView()
        search_view.search('genus where epithet = None')
        model = search_view.results_view.get_model()
        self.assertIn('Could not find anything for search', model[0][0])
        # no infobox
        self.assertIsNone(search_view.infobox)

    def test_search_w_error(self):
        search_view = SearchView()
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
        search_view = SearchView()
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
        search_view = SearchView()
        self.assertEqual(
            search_view.on_copy_selection(None, None),
            "Mock Data, MockData"
        )
        prefs.prefs['copy_templates.mockdata'] = '${value}, ${value.field}'

        mock_get_selected.return_value = [MockData()]
        search_view = SearchView()
        self.assertEqual(
            search_view.on_copy_selection(None, None),
            "Mock Data, Mock Field"
        )

    def test_cell_data_func(self):
        for func in get_setUp_data_funcs():
            func()
        search_view = SearchView()
        search_view.search('genus where id < 3')

        selected = search_view.get_selected_values()[0]

        mock_renderer = mock.Mock()
        results_view = search_view.results_view
        search_view.cell_data_func(results_view.get_column(0),
                                   mock_renderer,
                                   results_view.get_model(),
                                   0,
                                   None)
        mock_renderer.set_property.assert_called()
        main, substr = selected.search_view_markup_pair()
        markup = (f'{_mainstr_tmpl % utils.nstr(main)}\n'
                  f'{_substr_tmpl % utils.nstr(substr)}')
        mock_renderer.set_property.assert_called_with('markup', markup)

        # change selection and check it updates
        search_view.results_view.set_cursor(
            Gtk.TreePath.new_from_string('1')
        )

        selected2 = search_view.get_selected_values()[0]
        self.assertNotEqual(selected, selected2)

        mock_renderer = mock.Mock()
        results_view = search_view.results_view
        search_view.cell_data_func(results_view.get_column(0),
                                   mock_renderer,
                                   results_view.get_model(),
                                   1,
                                   None)
        mock_renderer.set_property.assert_called()
        main, substr = selected2.search_view_markup_pair()
        markup = (f'{_mainstr_tmpl % utils.nstr(main)}\n'
                  f'{_substr_tmpl % utils.nstr(substr)}')
        mock_renderer.set_property.assert_called_with('markup', markup)

    def test_update_expires_all_and_triggers_selection_change(self):
        for func in get_setUp_data_funcs():
            func()
        search_view = SearchView()
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

    def test_on_view_button_release_not_3_returns_false(self):
        for func in get_setUp_data_funcs():
            func()
        search_view = SearchView()
        search_view.search('genus where id = 1')

        results_view = search_view.results_view
        mock_callback = mock.Mock()
        mock_callback.return_value = Gio.Menu()

        search_view.context_menu_callbacks = set([mock_callback])

        # test bails on non 3 buttons and returns False (allows propagating the
        # event)
        self.assertFalse(
            search_view.on_view_button_release(results_view,
                                               mock.Mock(button=1))
        )
        mock_callback.assert_not_called()

        self.assertFalse(
            search_view.on_view_button_release(results_view,
                                               mock.Mock(button=2))
        )
        mock_callback.assert_not_called()

        self.assertFalse(
            search_view.on_view_button_release(results_view,
                                               mock.Mock(button=4))
        )
        mock_callback.assert_not_called()

    def test_on_view_button_release_3_returns_true(self):
        for func in get_setUp_data_funcs():
            func()
        search_view = SearchView()
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
        session = db.Session()
        history_count = session.query(db.History).count()
        # make sure there IS something minimal in history (should be in bauble)
        self.assertGreater(history_count, 5)
        hist_view = HistoryView()
        hist_view.update(None)
        # wait for the thread to finish
        import threading
        from time import sleep
        while threading.active_count() > 1:
            sleep(0.1)
        update_gui()
        self.assertEqual(len(hist_view.liststore), history_count)
        session.close()

    def test_add_row(self):
        from datetime import datetime

        mock_hist_item = mock.Mock(
            timestamp=datetime.today(),
            operation='insert',
            user='Jade Green',
            table_name='mock_table',
            values=("{'id': 1, 'data': 'some random data', 'name': "
                      " 'test name', '_created': None, '_last_updated': None}")
        )

        hist_view = HistoryView()
        hist_view.add_row(mock_hist_item)
        first_row = hist_view.liststore[0]
        self.assertEqual(first_row[hist_view.TVC_TABLE],
                         mock_hist_item.table_name)
        self.assertEqual(first_row[hist_view.TVC_USER],
                         mock_hist_item.user)

    def test_on_row_activated(self):
        from datetime import datetime

        mock_hist_item = mock.Mock(
            timestamp=datetime.today(),
            operation='insert',
            user='Jade Green',
            table_name='genus_note',
            values=("{'id': 1, 'genus_id': 10, 'note': 'test note', "
                      "'_created': None, '_last_updated': None}")
        )

        hist_view = HistoryView()
        hist_view.add_row(mock_hist_item)
        self.assertEqual(hist_view.on_row_activated(None, 0, None),
                         'genus where id=10')

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