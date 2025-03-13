# pylint: disable=no-self-use,protected-access,too-many-public-methods
# Copyright (c) 2022-2025 Ross Demuth <rossdemuth123@gmail.com>
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
view tests
"""

import os
from datetime import datetime
from pathlib import Path
from unittest import mock

from gi.repository import Gdk
from gi.repository import Gio
from gi.repository import Gtk
from sqlalchemy.exc import InvalidRequestError

from bauble import db
from bauble import error
from bauble import meta
from bauble import paths
from bauble import pluginmgr
from bauble import prefs
from bauble import search
from bauble import utils
from bauble.plugins.plants.genus import Genus
from bauble.search.strategies import MapperSearch
from bauble.test import BaubleTestCase
from bauble.test import get_setUp_data_funcs
from bauble.test import update_gui
from bauble.test import uri
from bauble.test import wait_on_threads
from bauble.ui import GUI
from bauble.view import _MAINSTR_TMPL
from bauble.view import _SUBSTR_TMPL
from bauble.view import EXPAND_ON_ACTIVATE_PREF
from bauble.view import INFOBOXPAGE_WIDTH_PREF
from bauble.view import PIC_PANE_PAGE_PREF
from bauble.view import PIC_PANE_WIDTH_PREF
from bauble.view import SEARCH_CACHE_SIZE_PREF
from bauble.view import SEARCH_COUNT_FAST_PREF
from bauble.view import SEARCH_POLL_SECS_PREF
from bauble.view import SEARCH_REFRESH_PREF
from bauble.view import HistoryView
from bauble.view import InfoBox
from bauble.view import InfoBoxPage
from bauble.view import LinksExpander
from bauble.view import NotesBottomPage
from bauble.view import PicturesScroller
from bauble.view import PropertiesExpander
from bauble.view import SearchView
from bauble.view import get_search_view
from bauble.view import get_search_view_selected
from bauble.view import multiproc_counter
from bauble.view import select_in_search_results

# pylint: disable=too-few-public-methods


class TestMultiprocCounter(BaubleTestCase):
    def setUp(self):
        if ":memory:" in uri or "?mode=memory" in uri:
            # for the sake of multiprocessing, create a temp file database and
            # populate it rather than use an in memory database
            from tempfile import mkstemp

            self.db_handle, self.temp_db = mkstemp(suffix=".db", text=True)
            self.uri = f"sqlite:///{self.temp_db}"
            db.open_conn(self.uri, verify=False, show_error_dialogs=False)
            self.handle, self.temp = mkstemp(suffix=".cfg", text=True)
            # reason not to use `from bauble.prefs import prefs`
            prefs.default_prefs_file = self.temp
            prefs.prefs = prefs._prefs(filename=self.temp)
            prefs.prefs.init()
            prefs.prefs[prefs.web_proxy_prefs] = "no_proxies"
            pluginmgr.plugins.clear()
            pluginmgr.load()
            db.create(import_defaults=False)
            pluginmgr.install("all", False, force=True)
            pluginmgr.init()
            self.session = db.Session()
        else:
            super().setUp()
            self.uri = uri

        # add some data
        for func in get_setUp_data_funcs():
            func()

    def tearDown(self):
        if ":memory:" in uri or "?mode=memory" in uri:
            update_gui()
            wait_on_threads()
            self.session.close()
            os.close(self.db_handle)
            os.remove(self.temp_db)
            os.close(self.handle)
            os.remove(self.temp)
            db.engine.dispose()
        else:
            super().tearDown()

    def test_multiproc_counter_all_domains(self):
        # NOTE for coverage to work need to set
        # concurency=multiprocessing,thread
        from functools import partial
        from multiprocessing import Pool

        classes = []
        for klass in MapperSearch.get_domain_classes().values():
            if self.session.query(klass).get(1):
                classes.append(klass)

        results = []

        with Pool() as pool:
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

            pool.close()
            pool.join()

        for result in results:
            self.assertEqual(len(result), 1)
            self.assertTrue(isinstance(result[0], dict))
            self.assertGreaterEqual(len(result[0].keys()), 1)


class TestSearchView(BaubleTestCase):
    def setUp(self):
        super().setUp()
        self.search_view = get_search_view()

    def tearDown(self):
        self.search_view.infobox = None
        self.search_view._reset()
        self.search_view.btn_1_timer = (0, 0, 0)
        super().tearDown()

    def test_init_no_db_raises(self):
        with mock.patch("bauble.view.db._Session", None):

            self.assertRaises(error.DatabaseError, SearchView)

    def test_has_kids_cache_sets_from_prefs_on_init(self):
        # setup
        self.search_view._remove_bottom_pages()

        prefs.prefs[SEARCH_POLL_SECS_PREF] = 20
        prefs.prefs[SEARCH_CACHE_SIZE_PREF] = 100

        with mock.patch.object(SearchView, "has_kids") as mock_kids:
            SearchView()

            mock_kids.set_secs.assert_called_with(20)
            mock_kids.set_size.assert_called_with(100)

        # teardown
        self.search_view._remove_bottom_pages()
        self.search_view._add_bottom_pages()

    def test_extra_signals_connect_on_init(self):
        # setup
        self.search_view._remove_bottom_pages()
        mock_handler = mock.Mock()
        signal = ("foo", "bar", mock_handler)
        SearchView.extra_signals = {signal}

        with mock.patch.object(SearchView, "connect_signal") as mock_connect:
            SearchView()

            mock_connect.assert_called_with(*signal)

        # teardown
        SearchView.extra_signals = set()
        self.search_view._remove_bottom_pages()
        self.search_view._add_bottom_pages()

    def test_row_meta_populates_with_all_domains(self):
        search_view = self.search_view
        self.assertEqual(
            set(search_view.row_meta.keys()),
            set(MapperSearch.get_domain_classes().values()),
        )

    def test_add_pic_pane_pages(self):
        widget = Gtk.ScrolledWindow()
        pages = {(widget, 1, "foo")}
        with (
            mock.patch.object(
                self.search_view, "pic_pane_notebook_pages", new=pages
            ),
            mock.patch.object(
                self.search_view, "add_page_to_pic_pane_notebook"
            ) as mock_add,
        ):
            self.search_view.add_pic_pane_notebook_pages()

            mock_add.assert_called_with(widget, 1, "foo")

    def test_update_infobox_detached_bails(self):
        genus = Genus(epithet="Grevillea")
        with mock.patch.object(
            self.search_view, "set_infobox_from_row"
        ) as mock_set:
            self.search_view.update_infobox([genus])

            mock_set.assert_not_called()

    def test_update_infobox_exception_reraises_removes_infobox(self):
        for func in get_setUp_data_funcs():
            func()
        genus = self.session.query(Genus).get(1)
        with mock.patch.object(
            self.search_view.info_pane, "show_all"
        ) as mock_show:
            mock_show.side_effect = Exception("Boom")

            self.assertRaises(
                Exception, self.search_view.update_infobox, [genus]
            )
        self.assertIsNone(self.search_view.info_pane.get_child2())

    def test_on_selection_changed_str_bails(self):
        with (
            mock.patch.object(
                self.search_view, "get_selected_values"
            ) as mock_selected,
            mock.patch.object(
                self.search_view, "update_infobox"
            ) as mock_update,
        ):
            mock_selected.return_value = ["Foo"]
            self.search_view.on_selection_changed(None)
            mock_update.assert_not_called()

    def test_all_domains_w_children_sorter(self):
        prefs.prefs["bauble.search.sort_by_taxon"] = True
        search_view = self.search_view
        for func in get_setUp_data_funcs():
            func()
        for cls in MapperSearch.get_domain_classes().values():
            if not self.search_view.row_meta[cls].children:
                continue
            for obj in self.session.query(cls):
                kids = search_view.row_meta[cls].get_children(obj)
                if not kids:
                    continue
                kids_count = len(kids)
                # acount for tags (as in on_test_expand_row)
                sorter = utils.natsort_key
                if len({type(i) for i in kids}) == 1:
                    sorter = search_view.row_meta[type(kids[0])].sorter

                kids_sorted = sorted(kids, key=sorter)
                kids_sorted_count = len(kids_sorted)
                self.assertEqual(
                    kids_sorted_count,
                    kids_count,
                )

    def test_all_domains_w_children_has_children_returns_correct(self):
        search_view = self.search_view
        for func in get_setUp_data_funcs():
            func()
        for cls in MapperSearch.get_domain_classes().values():
            if not self.search_view.row_meta[cls].children:
                continue
            for obj in self.session.query(cls):
                self.assertIsInstance(obj.has_children(), bool, cls)
                kids = search_view.row_meta[cls].get_children(obj)
                has_kids = bool(kids)
                self.assertEqual(
                    obj.has_children(),
                    has_kids,
                    f"{obj}: {[str(i) for i in kids]}",
                )

    def test_all_domains_w_children_count_children_returns_correct(self):
        search_view = self.search_view
        for func in get_setUp_data_funcs():
            func()
        for cls in MapperSearch.get_domain_classes().values():
            if not self.search_view.row_meta[cls].children:
                continue
            for obj in self.session.query(cls):
                self.assertIsInstance(obj.count_children(), int, cls)
                kids = search_view.row_meta[cls].get_children(obj)
                kids_count = len(kids)
                self.assertEqual(
                    obj.count_children(),
                    kids_count,
                    f"{obj}: {[str(i) for i in kids]}",
                )

    def test_all_domains_w_children_count_children_returns_active(self):
        prefs.prefs[prefs.exclude_inactive_pref] = True

        search_view = self.search_view
        for func in get_setUp_data_funcs():
            func()
        for cls in MapperSearch.get_domain_classes().values():
            if not self.search_view.row_meta[cls].children:
                continue
            for obj in self.session.query(cls):
                self.assertIsInstance(obj.count_children(), int, cls)
                kids = search_view.row_meta[cls].get_children(obj)
                kids_count = len(kids)
                self.assertEqual(
                    obj.count_children(),
                    kids_count,
                    f"{obj}: {[str(i) for i in kids]}",
                )

    def test_row_meta_get_children(self):
        from sqlalchemy import Column
        from sqlalchemy import ForeignKey
        from sqlalchemy import Integer
        from sqlalchemy import String
        from sqlalchemy.orm import relationship

        class Parent(db.Base):
            __tablename__ = "parent"
            name = Column("name", String(10))
            children = relationship("Child", back_populates="parent")

        class Child(db.Base):
            __tablename__ = "child"
            name = Column("name", String(10))
            parent_id = Column(Integer, ForeignKey(Parent.id), nullable=False)
            parent = relationship(Parent, back_populates="children")

        self.search_view.row_meta[Parent].set(children="children")

        search_view = self.search_view
        parent = Parent(name="test1")
        child = Child(name="test2", parent=parent)

        self.assertEqual(
            search_view.row_meta[Parent].get_children(parent), [child]
        )
        # remove so further tests don't fail
        del self.search_view.row_meta.data[Parent]

    def test_on_test_expand_row_w_kids_returns_false_adds_kids(self):
        for func in get_setUp_data_funcs():
            func()
        search_view = self.search_view
        search_view.search("genus where id = 1")
        model = search_view.results_view.get_model()
        val = search_view.on_test_expand_row(
            search_view.results_view,
            model.get_iter_first(),
            Gtk.TreePath.new_first(),
        )
        self.assertFalse(val)
        kid = model.get_value(model.get_iter_from_string("0:1"), 0)
        self.assertEqual(kid.genus_id, 1)

    @mock.patch("bauble.view.SearchView.append_children")
    def test_on_test_expand_row_sort_by_taxon(self, mock_append):
        for func in get_setUp_data_funcs():
            func()
        search_view = self.search_view
        text = 'source_detail = "Jade Green"'
        search_view.search(text)
        model = search_view.results_view.get_model()
        treeiter = model.get_iter_first()
        row = model.get_value(treeiter, 0)
        val = search_view.on_test_expand_row(
            search_view.results_view, treeiter, Gtk.TreePath.new_first()
        )
        self.assertFalse(val)

        # natsort
        mock_append.assert_called()
        results = sorted(
            [i.accession for i in row.sources], key=utils.natsort_key
        )
        mock_append.assert_called_with(model, treeiter, results)
        mock_append.reset_mock()

        # by taxon
        prefs.prefs["bauble.search.sort_by_taxon"] = True
        val = search_view.on_test_expand_row(
            search_view.results_view, treeiter, Gtk.TreePath.new_first()
        )
        self.assertFalse(val)
        results = sorted(
            [i.accession for i in row.sources],
            key=lambda obj: str(obj.species),
        )
        mock_append.assert_called()
        mock_append.assert_called_with(model, treeiter, results)
        mock_append.reset_mock()

        # test tag - tags are a special mixed case where sorter doesn't work
        text = "tag = test2"
        search_view.search(text)
        model = search_view.results_view.get_model()
        treeiter = model.get_iter_first()
        row = model.get_value(treeiter, 0)
        val = search_view.on_test_expand_row(
            search_view.results_view, treeiter, Gtk.TreePath.new_first()
        )
        self.assertFalse(val)

    def test_on_test_expand_row_w_no_kids_returns_true_adds_no_kids(self):
        # doesn't propagate
        for func in get_setUp_data_funcs():
            func()
        search_view = self.search_view
        search_view.search("plant where id = 1")
        model = search_view.results_view.get_model()
        val = search_view.on_test_expand_row(
            search_view.results_view,
            model.get_iter_first(),
            Gtk.TreePath.new_first(),
        )
        self.assertTrue(val)
        with self.assertRaises(ValueError):
            model.get_iter_from_string("0:1")

    def test_on_test_expand_row_exception_returns_true(self):
        # doesn't propagate
        search_view = self.search_view
        mock_treeview = mock.Mock()
        mock_treeview.get_model().iter_has_child.return_value = False
        with mock.patch.object(search_view, "row_meta") as mock_meta:
            mock_meta.__getitem__.side_effect = Exception("Boom")

            self.assertTrue(
                search_view.on_test_expand_row(
                    mock_treeview, mock.Mock(), mock.Mock()
                )
            )
        mock_treeview.get_model().remove.assert_not_called()

    @mock.patch("bauble.view.utils.search_tree_model")
    def test_on_test_expand_row_invalid_request_returns_true_and_removes(
        self, mock_search_tm
    ):
        # doesn't propagate
        for func in get_setUp_data_funcs():
            func()
        search_view = self.search_view
        search_view.search("plant where id = 1")
        model = search_view.results_view.get_model()
        treeiter = model.get_iter_first()
        mock_search_tm.return_value = [treeiter]
        mock_treeview = mock.Mock()
        mock_treeview.get_model.return_value = model

        with mock.patch.object(search_view, "row_meta") as mock_meta:
            mock_meta.__getitem__.side_effect = InvalidRequestError("Boom")

            self.assertTrue(
                search_view.on_test_expand_row(
                    mock_treeview,
                    model.get_iter_first(),
                    Gtk.TreePath.new_first(),
                )
            )
            mock_search_tm.assert_called()

    def test_remove_children(self):
        for func in get_setUp_data_funcs():
            func()
        search_view = self.search_view
        search_view.search("genus where id = 1")
        model = search_view.results_view.get_model()
        # expand a row
        search_view.on_test_expand_row(
            search_view.results_view,
            model.get_iter_first(),
            Gtk.TreePath.new_first(),
        )
        start = search_view.get_selected_values()
        # check kids exist
        self.assertTrue(model.get_iter_from_string("0:1"))
        # remove them
        search_view.remove_children(model, model.get_iter_first())
        # kids removed
        with self.assertRaises(ValueError):
            model.get_iter_from_string("0:1")
        end = search_view.get_selected_values()
        # parent still exists
        self.assertEqual(start, end)

    @mock.patch("bauble.view.task")
    def test_populate_results_large_result_uses_task(self, mock_task):
        search_view = self.search_view
        with mock.patch.object(search_view, "populate_callbacks", []):
            search_view.populate_results(range(4000))
        mock_task.queue.assert_called()

    def test_on_action_activate_supplies_selected_updates(self):
        for func in get_setUp_data_funcs():
            func()
        search_view = self.search_view
        search_view.search("genus where id = 1")
        values = search_view.get_selected_values()

        mock_callback = mock.Mock()
        mock_callback.return_value = True

        with self.assertLogs(level="DEBUG") as logs:
            search_view.on_action_activate(None, None, mock_callback)
            update_gui()
        self.assertTrue(any("SearchView::update" in i for i in logs.output))

        mock_callback.assert_called_with(values)

    @mock.patch("bauble.view.utils.message_details_dialog")
    def test_on_action_activate_with_error_notifies(self, mock_dialog):
        search_view = self.search_view
        mock_callback = mock.Mock()
        mock_callback.side_effect = ValueError("boom")
        search_view.on_action_activate(None, None, mock_callback)
        mock_dialog.assert_called_with("boom", mock.ANY, Gtk.MessageType.ERROR)

    def test_reset_calls_populate_callbacks_w_empty_list(self):
        # raises if no DB
        mock_callback = mock.Mock()
        self.search_view.populate_callbacks.add(mock_callback)
        self.search_view._reset()
        mock_callback.assert_called_with([])

    def test_search_no_result(self):
        search_view = self.search_view
        search_view.search("genus where epithet = None")
        model = search_view.results_view.get_model()

        self.assertIn("Could not find anything for search", model[0][0])
        self.assertEqual(len(model), 1)

        # with exclude inactive warns
        prefs.prefs[prefs.exclude_inactive_pref] = True
        search_view.search("genus where epithet = None")
        model = search_view.results_view.get_model()

        self.assertIn("Could not find anything for search", model[0][0])
        self.assertIn("CONSIDER: uncheck 'Exclude Inactive'", model[1][0])
        # no infobox
        self.assertIsNone(search_view.infobox)

    @mock.patch("bauble.gui")
    def test_search_w_error(self, mock_gui):
        search_view = self.search_view
        mock_show_err_box = mock.Mock()
        mock_gui.show_error_box = mock_show_err_box
        search_view.search("accession where private = 3")
        mock_show_err_box.assert_called()
        self.assertTrue(
            mock_show_err_box.call_args.args[0].startswith("** Error: ")
        )
        # parser error
        mock_show_err_box.reset_mock()
        search_view.search("accession where private ? 1")
        mock_show_err_box.assert_called()
        error_msg = "Error in search string at column"
        self.assertTrue(
            mock_show_err_box.call_args.args[0].startswith(error_msg),
            mock_show_err_box.call_args.args[0],
        )
        # no infobox
        self.assertIsNone(search_view.infobox)

    @mock.patch("bauble.gui")
    def test_search_with_one_result_all_domains(self, mock_gui):
        mock_gui.window.get_size().width = 100
        prefs.prefs["bauble.search.return_accepted"] = False
        for func in get_setUp_data_funcs():
            func()
        search_view = self.search_view
        for klass in search_view.row_meta:
            if klass.__tablename__ == "tag":
                continue
            domain = klass.__tablename__
            if domain not in MapperSearch.domains:
                domain = None
                for key, val in MapperSearch.domains.items():
                    if val[0] == klass:
                        domain = key
                        break

            string = f"{domain} where id = 1"
            # with self.assertLogs(level="DEBUG") as logs:
            search_view.search(string)
            # wait for the CountResultsTask thread to finish
            wait_on_threads()
            # check it called
            mock_gui.widgets.statusbar.push.assert_called()
            mock_gui.reset_mock()
            # test the correct object was returned
            model = search_view.results_view.get_model()
            obj = model[0][0]
            self.assertIsInstance(obj, klass)
            self.assertEqual(obj.id, 1)
            # check correct infobox (errors can cause no infobox)
            self.assertIs(
                search_view.infobox, search_view.row_meta[klass].infobox
            )
            search_view.infobox.update(obj)

    @mock.patch("bauble.gui")
    def test_search_with_one_result_all_domains_refresh_false(self, mock_gui):
        # just checking nothing breaks, slightly increases coverage
        prefs.prefs[SEARCH_REFRESH_PREF] = False

        mock_gui.window.get_size().width = 100
        prefs.prefs["bauble.search.return_accepted"] = False
        for func in get_setUp_data_funcs():
            func()
        search_view = self.search_view
        for klass in search_view.row_meta:
            if klass.__tablename__ == "tag":
                continue
            domain = klass.__tablename__
            if domain not in MapperSearch.domains:
                domain = None
                for key, val in MapperSearch.domains.items():
                    if val[0] == klass:
                        domain = key
                        break

            string = f"{domain} where id = 1"
            # with self.assertLogs(level="DEBUG") as logs:
            search_view.search(string)
            # wait for the CountResultsTask thread to finish
            wait_on_threads()
            # check it called
            mock_gui.widgets.statusbar.push.assert_called()
            mock_gui.reset_mock()
            # test the correct object was returned
            model = search_view.results_view.get_model()
            obj = model[0][0]
            self.assertIsInstance(obj, klass)
            self.assertEqual(obj.id, 1)
            # check correct infobox (errors can cause no infobox)
            self.assertIs(
                search_view.infobox, search_view.row_meta[klass].infobox
            )
            search_view.infobox.update(obj)

    @mock.patch("bauble.gui")
    def test_search_all_all_domains(self, mock_gui):
        mock_gui.window.get_size().width = 100
        prefs.prefs["bauble.search.return_accepted"] = False
        for func in get_setUp_data_funcs():
            func()
        search_view = self.search_view
        for klass in search_view.row_meta:
            if klass.__tablename__ == "tag":
                continue
            domain = klass.__tablename__
            if domain not in MapperSearch.domains:
                domain = None
                for key, val in MapperSearch.domains.items():
                    if val[0] == klass:
                        domain = key
                        break

            string = f"{domain} = *"
            # with self.assertLogs(level="DEBUG") as logs:
            search_view.search(string)
            # wait for the CountResultsTask thread to finish
            wait_on_threads()
            # check it called
            mock_gui.widgets.statusbar.push.assert_called()
            mock_gui.reset_mock()
            # test the correct object was returned
            model = search_view.results_view.get_model()
            obj = model[0][0]
            self.assertIsInstance(obj, klass)
            # check correct infobox (errors can cause no infobox)
            self.assertIs(
                search_view.infobox, search_view.row_meta[klass].infobox
            )

    @mock.patch("bauble.view.search.search")
    @mock.patch("bauble.view.utils.yes_no_dialog")
    def test_search_large_result_allows_user_to_bail(
        self, mock_dialog, mock_search
    ):
        mock_dialog.return_value = False
        mock_search.return_value = range(35000)
        search_view = get_search_view()
        search_view.search("everything")
        mock_dialog.assert_called_with(
            "This query returned 35000 results.  It may take a "
            "while to display all the data. Are you sure you "
            "want to continue?"
        )

    def test_update_statusbar_non_homogeneous_result(self):
        search_view = get_search_view()
        mock_status_bar = mock.Mock()
        search_view._update_statusbar(
            [1, "one", object()], statusbar=mock_status_bar
        )
        self.assertIn(
            "size of non homogeneous result: 3",
            mock_status_bar.push.call_args[0],
        )

    def test_update_statusbar_count_fast(self):
        prefs.prefs[SEARCH_COUNT_FAST_PREF] = "no"
        search_view = get_search_view()
        mock_status_bar = mock.Mock()
        search_view._update_statusbar([1, 2, 3], statusbar=mock_status_bar)
        self.assertIn(
            "size of result: 3",
            mock_status_bar.push.call_args[0],
        )

    @mock.patch("bauble.gui")
    def test_update_context_menus_all_domains(self, mock_gui):
        for func in get_setUp_data_funcs():
            func()

        for domain in MapperSearch.domains:
            self.search_view.search(f"{domain} where id = 1")
            self.search_view.update_context_menus(
                self.search_view.get_selected_values()
            )

            mock_gui.edit_context_menu.remove_all.assert_called()
            mock_gui.edit_context_menu.insert_section.assert_called_with(
                0, None, self.search_view.context_menu_model
            )

    @mock.patch("bauble.gui")
    def test_add_meta_actions_to_context_menu_adds_action(self, mock_gui):
        for func in get_setUp_data_funcs():
            func()

        self.search_view.search("genus where id < 3")
        selected = self.search_view.get_selected_values()
        mock_gui.lookup_action.return_value = False

        with mock.patch(
            "bauble.view.Gio.Application.get_default"
        ) as mock_default:
            self.search_view._add_meta_actions_to_context_menu(selected)
            mock_default().set_accels_for_action.assert_called()

        mock_gui.window.add_action.assert_called()
        mock_gui.remove_action.assert_not_called()

        # test non current actions are removed by changing the selected type
        mock_gui.reset_mock()
        self.search_view.search("species where id < 3")
        selected = self.search_view.get_selected_values()

        self.search_view._add_meta_actions_to_context_menu(selected)

        mock_gui.window.add_action.assert_called()
        mock_gui.remove_action.assert_called()

    @mock.patch("bauble.gui")
    def test_add_copy_selection_to_context_menu_adds_action(self, mock_gui):
        mock_gui.lookup_action.return_value = False

        self.search_view._add_copy_selection_to_context_menu()

        mock_gui.add_action.assert_called_with(
            "copy_selection_strings", self.search_view.on_copy_selection
        )

    @mock.patch("bauble.gui")
    def test_add_get_history_to_context_menu_adds_action(self, mock_gui):
        for func in get_setUp_data_funcs():
            func()

        self.search_view.search("genus where id < 3")
        selected = self.search_view.get_selected_values()
        mock_gui.lookup_action.return_value = False

        self.search_view._add_get_history_to_context_menu(selected)

        mock_gui.add_action.assert_called_with(
            "get_history", self.search_view.on_get_history
        )

    @mock.patch("bauble.view.SearchView.get_selected_values")
    def test_on_get_history(self, mock_get_selected):
        mock_get_selected.return_value = None
        self.assertIsNone(self.search_view.on_get_history(None, None))

        mock_data = mock.Mock(
            id=100, _created="18/09/2023", __tablename__="mock_table"
        )

        search_str = (
            ":history = table_name = mock_table and table_id = 100 and "
            'timestamp >= "18/09/2023"'
        )

        mock_get_selected.return_value = [mock_data]
        with mock.patch("bauble.gui") as mock_gui:
            self.search_view.on_get_history(None, None),
            mock_gui.send_command.assert_called_with(search_str)

    @mock.patch("bauble.view.SearchView.get_selected_values")
    def test_on_copy_selected(self, mock_get_selected):
        mock_data = mock.MagicMock(field="Mock Field")
        mock_data.__str__.return_value = "Mock Data"

        mock_get_selected.return_value = [mock_data]
        search_view = self.search_view

        with mock.patch("bauble.gui") as mock_gui:
            search_view.on_copy_selection(None, None)
            mock_gui.get_display_clipboard().set_text.assert_called_with(
                "Mock Data, MagicMock", -1
            )

        prefs.prefs["copy_templates.magicmock"] = "${value}, ${value.field}"

        with mock.patch("bauble.gui") as mock_gui:
            search_view.on_copy_selection(None, None)
            mock_gui.get_display_clipboard().set_text.assert_called_with(
                "Mock Data, Mock Field", -1
            )

    @mock.patch("bauble.view.SearchView.get_selected_values")
    def test_on_copy_selected_bails_no_selected(self, mock_get_selected):

        mock_get_selected.return_value = []
        search_view = self.search_view

        with mock.patch("bauble.gui") as mock_gui:
            search_view.on_copy_selection(None, None)
            mock_gui.get_display_clipboard().set_text.assert_not_called()

    @mock.patch("bauble.view.SearchView.get_selected_values")
    def test_on_copy_selected_warns_user_if_exception(self, mock_get_selected):
        mock_data = mock.MagicMock(field="Mock Field")
        mock_data.__str__.side_effect = AttributeError("Boom")

        mock_get_selected.return_value = [mock_data]
        search_view = self.search_view

        with mock.patch(
            "bauble.view.utils.message_details_dialog"
        ) as mock_dialog:
            search_view.on_copy_selection(None, None)
            mock_dialog.assert_called()

    def test_cell_data_func(self):
        for func in get_setUp_data_funcs():
            func()
        search_view = self.search_view
        search_view.search("genus where id < 3")

        selected = search_view.get_selected_values()[0]

        mock_renderer = mock.Mock()
        results_view = search_view.results_view
        model = results_view.get_model()
        tree_iter = model.get_iter(Gtk.TreePath.new_first())
        search_view.cell_data_func(
            results_view.get_column(0), mock_renderer, model, tree_iter, None
        )
        mock_renderer.set_property.assert_called()
        main, substr = selected.search_view_markup_pair()
        markup = f"{_MAINSTR_TMPL % main}\n{_SUBSTR_TMPL % substr}"
        mock_renderer.set_property.assert_called_with("markup", markup)

        # change selection and check it updates
        path = Gtk.TreePath.new_from_string("1")
        search_view.results_view.set_cursor(path)

        selected2 = search_view.get_selected_values()[0]
        self.assertNotEqual(selected, selected2)

        mock_renderer = mock.Mock()
        results_view = search_view.results_view
        model = results_view.get_model()
        tree_iter = model.get_iter(path)
        search_view.cell_data_func(
            results_view.get_column(0), mock_renderer, model, tree_iter, None
        )
        mock_renderer.set_property.assert_called()
        main, substr = selected2.search_view_markup_pair()
        markup = f"{_MAINSTR_TMPL % main}\n{_SUBSTR_TMPL % substr}"
        mock_renderer.set_property.assert_called_with("markup", markup)

    def test_cell_data_func_no_result(self):
        search_view = self.search_view
        search_view.search("genus where epithet = None")

        mock_renderer = mock.Mock()
        results_view = search_view.results_view
        model = results_view.get_model()
        tree_iter = model.get_iter(Gtk.TreePath.new_first())
        search_view.cell_data_func(
            results_view.get_column(0), mock_renderer, model, tree_iter, None
        )
        mock_renderer.set_property.assert_called()
        markup = (
            "<b>Could not find anything for search: &quot;genus where epithet "
            "= None&quot;</b>"
        )
        mock_renderer.set_property.assert_called_with("markup", markup)

    def test_cell_data_func_no_kids(self):
        for func in get_setUp_data_funcs():
            func()

        search_view = self.search_view
        search_view.search("plant where id = 1")

        mock_renderer = mock.Mock()
        results_view = search_view.results_view
        model = results_view.get_model()
        tree_iter = model.get_iter(Gtk.TreePath.new_first())
        # delete item

        with self.assertLogs(level="DEBUG") as logs:
            search_view.cell_data_func(
                results_view.get_column(0),
                mock_renderer,
                model,
                tree_iter,
                None,
            )
            update_gui()
        self.assertTrue(
            any("remove_children called" in i for i in logs.output)
        )

    def test_cell_data_func_w_deleted(self):
        # as if another user had deleted an item we were also looking at.
        for func in get_setUp_data_funcs():
            func()
        search_view = self.search_view
        search_view.search("genus where id > 3 and id < 7")

        start = search_view.get_selected_values()

        mock_renderer = mock.Mock()
        results_view = search_view.results_view
        model = results_view.get_model()
        tree_iter = model.get_iter(Gtk.TreePath.new_first())
        # delete item
        with db.engine.begin() as conn:
            conn.execute(f"DELETE FROM species WHERE genus_id = {start[0].id}")
            conn.execute(f"DELETE FROM genus WHERE id = {start[0].id}")

        with self.assertLogs(level="DEBUG") as logs:
            search_view.cell_data_func(
                results_view.get_column(0),
                mock_renderer,
                model,
                tree_iter,
                None,
            )
            update_gui()
        end = search_view.get_selected_values()
        self.assertNotEqual(start, end)
        self.assertTrue(any("remove_row called" in i for i in logs.output))

    def test_cell_data_func_w_added_adds_item(self):
        # as if another user had added an item
        for func in get_setUp_data_funcs():
            func()
        search_view = self.search_view
        search_view.search("genus where id = 1")

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
        with db.engine.begin() as conn:
            conn.execute(
                """
                INSERT INTO species (sp, genus_id, _created, _last_updated)
                VALUES ('test2', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """
            )

        mock_renderer = mock.Mock()
        search_view.cell_data_func(
            results_view.get_column(0), mock_renderer, model, tree_iter, None
        )
        update_gui()
        end = model.iter_n_children(tree_iter)
        self.assertEqual(start + 1, end)

    @mock.patch("bauble.gui")
    def test_update_expires_all_and_triggers_selection_change(self, mock_gui):
        mock_gui.window.get_size().width = 100
        for func in get_setUp_data_funcs():
            func()
        search_view = self.search_view
        search_view.search("accession where id < 3")
        with self.assertLogs(level="DEBUG") as logs:
            search_view.update()
        self.assertTrue(any("SearchView::update" in i for i in logs.output))
        self.assertTrue(
            any("SearchView::on_selection_changed" in i for i in logs.output)
        )
        self.assertTrue(
            any("SearchView::update_infobox" in i for i in logs.output)
        )
        # check all accessions are expired. (except the currently selected obj
        # as it has already been accessed)
        from sqlalchemy import inspect

        selected = search_view.get_selected_values()[0]
        for obj in search_view.session:
            # get state before accessing the obj.
            expired = bool(inspect(obj).expired_attributes)
            if obj.id == selected.id:
                continue
            if obj.__class__.__name__ == "Accession":
                self.assertTrue(expired, str(obj))

    def test_on_view_button_press_not_3_returns_false(self):
        for func in get_setUp_data_funcs():
            func()
        search_view = self.search_view
        search_view.search("genus where id = 1")

        results_view = search_view.results_view

        # test bails on non 3 buttons and returns False (allows propagating the
        # event)
        mock_button = mock.Mock(time=10, button=1, x=1, y=1)
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
        search_view.search("genus where id = 1")

        results_view = search_view.results_view

        event = Gdk.EventButton()
        event.type = Gdk.EventType.BUTTON_PRESS
        event.button = 3
        event.x = 1.0
        event.y = 1.0

        with self.assertLogs(level="DEBUG") as logs:
            self.assertFalse(
                search_view.on_view_button_press(results_view, event)
            )

        self.assertTrue(any("view button 3 press" in i for i in logs.output))

    def test_on_view_button_press_3_inside_selection_returns_true(self):
        for func in get_setUp_data_funcs():
            func()
        search_view = self.search_view
        search_view.search("genus where id = 1")

        event = Gdk.EventButton()
        event.type = Gdk.EventType.BUTTON_PRESS
        event.button = 3
        event.x = 1.0
        event.y = 1.0

        mock_view = mock.Mock()
        mock_view.get_path_at_pos.return_value = (0, 0, 0, 0)

        with self.assertLogs(level="DEBUG") as logs:
            self.assertTrue(search_view.on_view_button_press(mock_view, event))

        self.assertTrue(any("view button 3 press" in i for i in logs.output))

    def test_on_view_button_release_not_3_returns_false(self):
        for func in get_setUp_data_funcs():
            func()
        search_view = self.search_view
        search_view.search("genus where id = 1")

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

    @mock.patch("bauble.view.Gtk.Menu.popup_at_pointer")
    def test_on_view_button_release_3_returns_true(self, mock_popup):
        for func in get_setUp_data_funcs():
            func()
        search_view = self.search_view
        search_view.search("genus where id = 1")

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
        mock_popup.assert_called()

    def test_on_view_row_activated(self):
        for func in get_setUp_data_funcs():
            func()

        search_view = self.search_view
        mock_editor = mock.Mock()
        search_view.row_meta[Genus].activated_callback = mock_editor
        search_view.search("genus where id = 1")

        search_view.on_view_row_activated(None, None, None)
        mock_editor.assert_called_with(search_view.get_selected_values())

        prefs.prefs[EXPAND_ON_ACTIVATE_PREF] = True
        mock_tree_view = mock.Mock()
        search_view.on_view_row_activated(mock_tree_view, "test_path", None)
        mock_tree_view.expand_row.assert_called_with("test_path", False)

    def test_info_box_not_tabbed_add_expander(self):
        prop_exp = PropertiesExpander()
        info_box = InfoBox()
        info_box.add_expander(prop_exp)
        page = info_box.get_nth_page(0)

        self.assertIsInstance(prop_exp._sep, Gtk.Separator)
        self.assertEqual(page.expanders["Properties"], prop_exp)

    def test_info_box_not_tabbed_update(self):
        gen = Genus(epithet="Dendrobium")
        prop_exp = PropertiesExpander()
        prop_exp.update = mock.Mock()
        info_box = InfoBox()
        info_box.add_expander(prop_exp)
        info_box.update(gen)

        prop_exp.update.assert_called_with(gen)

    def test_info_box_tabbed_add_expander(self):
        prop_exp = PropertiesExpander()
        links_exp = LinksExpander()
        info_box = InfoBox(tabbed=True)
        page1 = InfoBoxPage()
        page2 = InfoBoxPage()
        info_box.insert_page(page1, tab_label=Gtk.Label(label="0"), position=0)
        info_box.add_expander(prop_exp)
        info_box.insert_page(page2, tab_label=Gtk.Label(label="1"), position=1)
        info_box.add_expander(links_exp, 1)

        self.assertIsInstance(prop_exp._sep, Gtk.Separator)
        self.assertIsInstance(links_exp._sep, Gtk.Separator)
        self.assertEqual(page1.get_expander("Properties"), prop_exp)
        self.assertEqual(page2.get_expander("Links"), links_exp)

    def test_info_box_tabbed_on_switch_page(self):
        prop_exp = PropertiesExpander()
        links_exp = LinksExpander()
        info_box = InfoBox(tabbed=True)
        page0 = InfoBoxPage()
        page1 = InfoBoxPage()
        page1.update = mock.Mock()
        info_box.insert_page(page0, tab_label=Gtk.Label(label="0"), position=0)
        info_box.add_expander(prop_exp)
        info_box.insert_page(page1, tab_label=Gtk.Label(label="1"), position=1)
        info_box.add_expander(links_exp, 1)

        info_box.on_switch_page(None, None, 1)

        # no row
        page1.update.assert_not_called()

        # with row
        gen = Genus(epithet="Dendrobium")
        info_box.row = gen
        info_box.on_switch_page(None, None, 1)

        page1.update.assert_called_with(gen)

    def test_info_box_tabbed_update(self):
        prop_exp = PropertiesExpander()
        links_exp = LinksExpander()
        info_box = InfoBox(tabbed=True)
        page0 = InfoBoxPage()
        page1 = InfoBoxPage()
        page1.update = mock.Mock()
        info_box.insert_page(page0, tab_label=Gtk.Label(label="0"), position=0)
        info_box.add_expander(prop_exp)
        info_box.insert_page(page1, tab_label=Gtk.Label(label="1"), position=1)
        info_box.add_expander(links_exp, 1)
        info_box.set_current_page(1)
        gen = Genus(epithet="Dendrobium")
        info_box.update(gen)

        page1.update.assert_called_with(gen)

    def test_info_box_page_on_resize(self):
        page = InfoBoxPage()
        self.assertIsNone(prefs.prefs.get(INFOBOXPAGE_WIDTH_PREF))
        mock_alloc = mock.Mock(width=100)
        page.on_resize(None, mock_alloc)

        self.assertEqual(prefs.prefs.get(INFOBOXPAGE_WIDTH_PREF), 100)

    def test_info_box_page_get_expander(self):
        prop_exp = PropertiesExpander()
        page = InfoBoxPage()
        page.add_expander(prop_exp)

        self.assertIsNone(page.get_expander("Foo"))
        self.assertEqual(page.get_expander("Properties"), prop_exp)

    def test_info_box_page_remove_expander(self):
        prop_exp = PropertiesExpander()
        page = InfoBoxPage()
        page.add_expander(prop_exp)

        self.assertEqual(page.remove_expander("Properties"), prop_exp)
        self.assertEqual(page.expanders, {})
        self.assertIsNone(page.remove_expander("Properties"), prop_exp)


class TestHistoryView(BaubleTestCase):
    def test_populates_listore(self):
        # also tests populating history I suppose
        for func in get_setUp_data_funcs():
            func()

        history_count = self.session.query(db.History).count()
        self.assertLess(history_count, 5)

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

        # add 5 notes
        for i in range(5):
            parent_model.notes.append(note_cls(note=f"test{i}"))

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
        mock_hist_item = mock.Mock(
            timestamp=datetime.today(),
            operation="insert",
            user="Jade Green",
            table_name="mock_table",
            values={
                "id": 1,
                "data": "some random data",
                "name": "test name",
                "geojson": {"test": "this"},
                "_created": None,
                "_last_updated": None,
            },
            id=1,
        )

        hist_view = HistoryView()
        start_len = len(hist_view.liststore)
        hist_view.add_row(mock_hist_item)
        self.assertEqual(len(hist_view.liststore), start_len + 1)
        first_row = hist_view.liststore[0]
        self.assertEqual(
            first_row[hist_view.TVC_TABLE], mock_hist_item.table_name
        )
        self.assertEqual(first_row[hist_view.TVC_USER], mock_hist_item.user)
        # test type guard, no values should return early
        mock_hist_item2 = mock.Mock(
            timestamp=datetime.today(),
            operation="insert",
            user="Jade Green",
            table_name="mock_table",
            values=None,
            id=2,
        )
        hist_view.add_row(mock_hist_item2)
        self.assertEqual(len(hist_view.liststore), start_len + 1)

    @mock.patch("bauble.view.HistoryView.TRUNCATE", 20)
    def test_add_row_truncate_single(self):
        mock_hist_item = mock.Mock(
            timestamp=datetime.today(),
            operation="insert",
            user="Jade Green",
            table_name="mock_table",
            values={
                "id": 1,
                "data": "some random data",
                "name": "test name",
                "geojson": {"test": "this", "and": "that"},
                "_created": None,
                "_last_updated": None,
            },
            id=1,
        )

        hist_view = HistoryView()
        self.assertEqual(hist_view.TRUNCATE, 20)
        start_len = len(hist_view.liststore)
        hist_view.add_row(mock_hist_item)
        self.assertEqual(len(hist_view.liststore), start_len + 1)
        first_row = hist_view.liststore[0]
        self.assertEqual(
            first_row[hist_view.TVC_TABLE], mock_hist_item.table_name
        )
        self.assertLessEqual(
            len(first_row[hist_view.TVC_USER_FRIENDLY + 1]), 20
        )
        self.assertEqual(
            first_row[hist_view.TVC_USER_FRIENDLY + 1], '{"test": "this",…'
        )

    @mock.patch("bauble.view.HistoryView.TRUNCATE", 22)
    def test_add_row_truncate_list(self):
        # test type guard, no values should return early
        mock_hist_item = mock.Mock(
            timestamp=datetime.today(),
            operation="insert",
            user="Jade Green",
            table_name="mock_table",
            values={
                "id": 1,
                "data": "some random data",
                "name": "test name",
                "geojson": [{"test": "this"}, {"and": "that"}],
                "_created": None,
                "_last_updated": None,
            },
            id=1,
        )

        hist_view = HistoryView()
        self.assertEqual(hist_view.TRUNCATE, 22)
        hist_view.add_row(mock_hist_item)
        first_row = hist_view.liststore[0]
        self.assertLessEqual(
            len(first_row[hist_view.TVC_USER_FRIENDLY + 1]), 22
        )
        self.assertEqual(
            first_row[hist_view.TVC_USER_FRIENDLY + 1],
            '[{"test":…, {"and":…]',
        )

    def test_shorten_list(self):
        short_part1 = {"1": 1}
        short_part2 = {"1": 1}
        long_part1 = {str(i): i for i in range(30)}
        long_part2 = {str(i): i for i in range(30)}

        two_short_parts = [short_part1, short_part2]
        hist_view = HistoryView()
        self.assertEqual(
            hist_view._shorten_list(two_short_parts), '[{"1": 1}, {"1": 1}]'
        )

        one_short_part1 = [short_part1, long_part1]
        shortened = hist_view._shorten_list(one_short_part1)
        self.assertLessEqual(len(shortened), hist_view.TRUNCATE)
        self.assertEqual(
            shortened,
            '[{"1": 1}, {"0": 0, "1": 1, "2": 2, "3": 3, "4": 4, "5": 5, '
            '"6": 6, "7": 7, "8": 8, "9": 9, "10":…]',
        )

        one_short_part2 = [long_part1, short_part1]
        shortened = hist_view._shorten_list(one_short_part2)
        self.assertLessEqual(len(shortened), hist_view.TRUNCATE)
        self.assertEqual(
            shortened,
            '[{"0": 0, "1": 1, "2": 2, "3": 3, "4": 4, "5": 5, '
            '"6": 6, "7": 7, "8": 8, "9": 9, "10":…, {"1": 1}]',
        )

        two_long_parts = [long_part1, long_part2]
        shortened = hist_view._shorten_list(two_long_parts)
        self.assertLessEqual(len(shortened), hist_view.TRUNCATE)
        self.assertEqual(
            shortened,
            '[{"0": 0, "1": 1, "2": 2, "3": 3, "4": 4, "5":…, {"0": 0, "1": '
            '1, "2": 2, "3": 3, "4": 4, "5":…]',
        )

    def test_cmp_items_key(self):
        values = {
            "name": "Jade Green",
            "none_value": None,
            "list_value": ["new", "old"],
            "id": 1,
        }
        out = [
            ("id", 1),
            ("list_value", ["new", "old"]),
            ("name", "Jade Green"),
            ("none_value", None),
        ]

        sortd = sorted(list(values.items()), key=HistoryView._cmp_items_key)
        self.assertEqual(sortd, out)

    def test_button_release(self):
        mock_context = mock.Mock()
        hist_view = HistoryView()
        hist_view.context_menu = mock_context
        self.assertFalse(
            hist_view.on_button_release(None, mock.Mock(button=1))
        )
        mock_context.popup_at_pointer.assert_not_called()
        self.assertTrue(hist_view.on_button_release(None, mock.Mock(button=3)))
        mock_context.popup_at_pointer.assert_called()

    @mock.patch("bauble.view.HistoryView.get_selected_value")
    def test_on_revert_to_history_type_guard(self, mock_get_selected):
        mock_get_selected.return_value = mock.Mock(id=None)
        hist_view = HistoryView()
        with self.assertNoLogs(level="DEBUG"):
            hist_view.on_revert_to_history(None, None)
        mock_get_selected.return_value = None
        with self.assertNoLogs(level="DEBUG"):
            hist_view.on_revert_to_history(None, None)

    @mock.patch("bauble.utils.yes_no_dialog")
    def test_on_revert_to_history_not_cloned(self, mock_dialog):
        mock_dialog.return_value = True
        # load history
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
        # add 5 notes
        for i in range(5):
            parent_model.notes.append(note_cls(note=f"test{i}"))

        self.session.add(parent_model)
        self.session.commit()

        start_note_count = self.session.query(note_cls).count()
        self.assertEqual(start_note_count, 6)
        start_hist_count = self.session.query(db.History).count()
        self.assertEqual(start_hist_count, 6)

        hist_view = HistoryView()
        hist_view.update(None)
        # wait for the thread to finish
        wait_on_threads()
        update_gui()
        # select something
        hist_view.history_tv.set_cursor(3)
        hist_view.on_revert_to_history(None, None)
        mock_dialog.assert_called()
        self.assertEqual(
            self.session.query(note_cls).count(), start_note_count - 4
        )
        self.assertEqual(
            self.session.query(db.History).count(), start_hist_count - 4
        )
        wait_on_threads()

    @mock.patch("bauble.utils.message_dialog")
    def test_on_revert_to_history_wont_revert_past_cloned(self, mock_dialog):
        # set clone point
        clone_point = 4
        meta.get_default("clone_history_id", clone_point)
        mock_dialog.return_value = True

        # load history
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
        # add 5 notes
        for i in range(5):
            parent_model.notes.append(note_cls(note=f"test{i}"))

        self.session.add(parent_model)
        self.session.commit()

        start_note_count = self.session.query(note_cls).count()
        self.assertEqual(start_note_count, 6)
        start_hist_count = self.session.query(db.History).count()
        self.assertEqual(start_hist_count, 7)

        hist_view = HistoryView()
        hist_view.update(None)
        # wait for the thread to finish
        wait_on_threads()
        update_gui()
        # select something
        hist_view.history_tv.set_cursor(4)
        selected = hist_view.get_selected_value()
        self.assertLessEqual(selected.id, clone_point)
        # try revert
        hist_view.on_revert_to_history(None, None)
        mock_dialog.assert_called()
        # test nothing changed
        self.assertEqual(
            self.session.query(note_cls).count(), start_note_count
        )
        self.assertEqual(
            self.session.query(db.History).count(), start_hist_count
        )
        wait_on_threads()

    @mock.patch("bauble.utils.yes_no_dialog")
    def test_on_revert_to_history_will_revert_before_cloned(self, mock_dialog):
        # set clone point
        clone_point = 4
        meta.get_default("clone_history_id", clone_point)
        mock_dialog.return_value = True

        # load history
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
        # add 5 notes
        for i in range(5):
            parent_model.notes.append(note_cls(note=f"test{i}"))

        self.session.add(parent_model)
        self.session.commit()

        start_note_count = self.session.query(note_cls).count()
        self.assertEqual(start_note_count, 6)
        start_hist_count = self.session.query(db.History).count()
        self.assertEqual(start_hist_count, 7)

        hist_view = HistoryView()
        hist_view.update(None)
        # wait for the thread to finish
        wait_on_threads()
        update_gui()
        # select something
        hist_view.history_tv.set_cursor(2)
        selected = hist_view.get_selected_value()
        self.assertTrue(selected.id > clone_point)

        hist_view.on_revert_to_history(None, None)
        mock_dialog.assert_called()
        self.assertEqual(
            self.session.query(note_cls).count(), start_note_count - 3
        )
        self.assertEqual(
            self.session.query(db.History).count(), start_hist_count - 3
        )
        wait_on_threads()

    @mock.patch("bauble.gui")
    @mock.patch("bauble.view.HistoryView.get_selected_value")
    def test_on_copy_values(self, mock_get_selected, mock_gui):
        geojson = {"type": "Point", "coordinate": [1, 2]}

        vals = {
            "id": 1,
            "genus_id": 10,
            "note": "test note",
            "_created": None,
            "_last_updated": None,
        }
        values = dict(vals)
        values["geojson"] = geojson

        mock_hist_item = mock.Mock(
            timestamp=datetime.today(),
            operation="insert",
            user="Jade Green",
            table_name="genus_note",
            table_id=1,
            values=values,
        )
        mock_get_selected.return_value = mock_hist_item

        hist_view = HistoryView()
        import json

        hist_view.on_copy_values(None, None)
        mock_gui.get_display_clipboard().set_text.assert_called_with(
            json.dumps(vals), -1
        )
        mock_gui.reset_mock()
        # type guards
        mock_get_selected.return_value = None
        hist_view.on_copy_values(None, None)
        mock_gui.get_display_clipboard().set_text.assert_not_called()
        mock_gui.reset_mock()

        mock_hist_item2 = mock.Mock(
            timestamp=datetime.today(),
            operation="insert",
            user="Jade Green",
            table_name="genus_note",
            table_id=1,
            values=None,
        )
        mock_get_selected.return_value = mock_hist_item2
        hist_view.on_copy_values(None, None)
        mock_gui.get_display_clipboard().set_text.assert_not_called()

    @mock.patch("bauble.gui")
    @mock.patch("bauble.view.HistoryView.get_selected_value")
    def test_on_copy_geojson(self, mock_get_selected, mock_gui):
        geojson = {"type": "Point", "coordinate": [1, 2]}
        values = {
            "id": 1,
            "name": "name data",
            "_created": None,
            "_last_updated": None,
            "geojson": geojson,
        }

        mock_hist_item = mock.Mock(
            timestamp=datetime.today(),
            operation="insert",
            user="Jade Green",
            table_name="mock_table",
            table_id=1,
            values=values,
            geojson=geojson,
        )
        mock_get_selected.return_value = mock_hist_item

        hist_view = HistoryView()
        import json

        hist_view.on_copy_geojson(None, None)
        mock_gui.get_display_clipboard().set_text.assert_called_with(
            json.dumps(geojson), -1
        )
        mock_gui.reset_mock()
        # type guards
        mock_get_selected.return_value = None
        hist_view.on_copy_geojson(None, None)
        mock_gui.get_display_clipboard().set_text.assert_not_called()
        mock_gui.reset_mock()

        mock_hist_item2 = mock.Mock(
            timestamp=datetime.today(),
            operation="insert",
            user="Jade Green",
            table_name="genus_note",
            table_id=1,
            values=None,
        )
        mock_get_selected.return_value = mock_hist_item2
        hist_view.on_copy_geojson(None, None)
        mock_gui.get_display_clipboard().set_text.assert_not_called()

    @mock.patch("bauble.gui")
    def test_on_row_activated_existing_table(self, mock_gui):
        mock_hist_item = mock.Mock(
            timestamp=datetime.today(),
            operation="insert",
            user="Jade Green",
            table_name="genus_note",
            table_id=1,
            values={
                "id": 1,
                "genus_id": 10,
                "note": "test note",
                "_created": None,
                "_last_updated": None,
            },
            id=1,
        )

        hist_view = HistoryView()
        hist_view.add_row(mock_hist_item)
        hist_view.on_row_activated(None, 0, None)
        mock_gui.send_command.assert_called_with("genus where notes.id = 1")

    @mock.patch("bauble.gui")
    def test_on_row_activated_none_existing_table(self, mock_gui):
        mock_hist_item = mock.Mock(
            timestamp=datetime.today(),
            operation="insert",
            user="Jade Green",
            table_name="bad_table",
            table_id=1,
            values={
                "id": 1,
                "genus_id": 10,
                "note": "test note",
                "_created": None,
                "_last_updated": None,
            },
            id=1,
        )

        hist_view = HistoryView()
        hist_view.add_row(mock_hist_item)
        hist_view.on_row_activated(None, 0, None)
        mock_gui.send_command.assert_not_called()

    def test_query_method(self):
        string = "table_name = plant"
        hist_view = HistoryView()
        hist_view.last_arg = string
        result = hist_view.query(self.session)
        self.assertTrue(
            result.whereclause.compare(db.History.table_name == "plant")
        )

    def test_basic_search_query_filters_eq(self):
        string = "table_name = plant"
        hist_view = HistoryView()
        hist_view.last_arg = string
        result = hist_view.get_query_filters()
        self.assertTrue(result[0].compare(db.History.table_name == "plant"))

    def test_basic_search_query_filters_not_eq(self):
        string = "table_name != plant"
        hist_view = HistoryView()
        hist_view.last_arg = string
        result = hist_view.get_query_filters()
        self.assertTrue(result[0].compare(db.History.table_name != "plant"))

    def test_basic_search_query_filters_w_and(self):
        string = (
            "table_name = plant and user = 'test user' and operation ="
            " insert"
        )
        hist_view = HistoryView()
        hist_view.last_arg = string
        result = hist_view.get_query_filters()
        # self.assertEqual(str(result[0]), "")
        self.assertTrue(result[0].compare(db.History.table_name == "plant"))
        self.assertTrue(result[1].compare(db.History.user == "test user"))
        self.assertTrue(result[2].compare(db.History.operation == "insert"))

    def test_basic_search_query_filters_like(self):
        # comparing strings like this isn't ideal, doesn't test value but
        # compare() does not work here (at least not in sqlalchemy v1.3.24)
        string = "values like %id"
        hist_view = HistoryView()
        hist_view.last_arg = string
        result = hist_view.get_query_filters()
        self.assertEqual(
            str(result[0]), str(utils.ilike(db.History.values, "%id"))
        )

    def test_basic_search_query_filters_contains(self):
        # comparing strings like this in't ideal, doesn't test value but
        # compare() does not work here (at least not in sqlalchemy v1.3.24)
        string = "values contains id"
        hist_view = HistoryView()
        hist_view.last_arg = string
        result = hist_view.get_query_filters()
        self.assertEqual(
            str(result[0]), str(utils.ilike(db.History.values, "%id"))
        )

    def test_basic_search_query_filters_on_timestamp(self):
        from datetime import timedelta
        from datetime import timezone

        from sqlalchemy import and_

        string = "timestamp on 10/8/23"
        date_val = search.clauses.get_datetime("10/8/23")
        today = date_val.astimezone(tz=timezone.utc)
        tomorrow = today + timedelta(1)
        hist_view = HistoryView()
        hist_view.last_arg = string
        result = hist_view.get_query_filters()
        self.assertTrue(
            result[0].compare(
                and_(
                    db.History.timestamp >= today,
                    db.History.timestamp < tomorrow,
                )
            )
        )

    def test_basic_search_query_filters_fails(self):
        string = "test = test"
        hist_view = HistoryView()
        hist_view.last_arg = string
        self.assertRaises(AttributeError, hist_view.get_query_filters)

    def test_basic_to_sync_search_is_clone(self):
        val = meta.get_default("clone_history_id", 5).value
        string = "to_sync"
        hist_view = HistoryView()
        hist_view.update(None)
        hist_view.last_arg = string
        result = hist_view.get_query_filters()
        self.assertTrue(result[0].compare(db.History.id > int(val)))

    def test_basic_to_sync_search_not_clone(self):
        string = "to_sync"
        hist_view = HistoryView()
        hist_view.last_arg = string
        result = hist_view.get_query_filters()
        self.assertTrue(result[0].compare(db.History.id.is_(None)))

    def test_basic_search_query_filters_w_to_sync(self):
        val = meta.get_default("clone_history_id", 5).value
        string = "to_sync and table_name = plant and operation = insert"
        hist_view = HistoryView()
        hist_view.update(None)
        hist_view.last_arg = string
        result = hist_view.get_query_filters()
        self.assertTrue(result[0].compare(db.History.id > int(val)))
        self.assertTrue(result[1].compare(db.History.table_name == "plant"))
        self.assertTrue(result[2].compare(db.History.operation == "insert"))

    @mock.patch("bauble.view.HistoryView.add_rows")
    def test_on_history_tv_value_changed_at_top(self, mock_add_rows):
        mock_tv = mock.MagicMock()
        mock_tv.get_visible_range.return_value = [True, True]
        mock_ls = mock.MagicMock()
        # bottom_line - id of last visible line (higher is towards top)
        mock_ls.get_value.return_value = 9950
        hist_view = HistoryView()
        hist_view.history_tv = mock_tv
        hist_view.liststore = mock_ls
        # id of last row in tree - below visible row (higher is towards top)
        hist_view.last_row_in_tree = 8000
        # line number of last row in tree (higher is towards the bottom)
        hist_view.offset = 2000
        # the total number of potential rows
        hist_view.hist_count = 10000
        hist_view.on_history_tv_value_changed()
        mock_add_rows.assert_not_called()

    @mock.patch("bauble.view.HistoryView.add_rows")
    def test_on_history_tv_value_changed_towards_top(self, mock_add_rows):
        mock_tv = mock.MagicMock()
        mock_tv.get_visible_range.return_value = [True, True]
        mock_ls = mock.MagicMock()
        # bottom_line - id of last visible line (higher is towards top)
        mock_ls.get_value.return_value = 7100
        hist_view = HistoryView()
        hist_view.history_tv = mock_tv
        hist_view.liststore = mock_ls
        # id of last row in tree - below visible row (higher is towards top)
        hist_view.last_row_in_tree = 7000
        # line number of last row in tree (higher is towards the bottom)
        hist_view.offset = 3000
        # the total number of potential rows
        hist_view.hist_count = 10000
        hist_view.on_history_tv_value_changed()
        mock_add_rows.assert_called()

    @mock.patch("bauble.view.HistoryView.add_rows")
    def test_on_history_tv_value_changed_towards_bottom(self, mock_add_rows):
        mock_tv = mock.MagicMock()
        mock_tv.get_visible_range.return_value = [True, True]
        mock_ls = mock.MagicMock()
        # bottom_line - id of last visible line (higher is towards top)
        mock_ls.get_value.return_value = 600
        hist_view = HistoryView()
        hist_view.history_tv = mock_tv
        hist_view.liststore = mock_ls
        # id of last row in tree - below visible row (higher is towards top)
        hist_view.last_row_in_tree = 500
        # line number of last row in tree (higher is towards the bottom)
        hist_view.offset = 9500
        # the total number of potential rows
        hist_view.hist_count = 10000
        hist_view.on_history_tv_value_changed()
        mock_add_rows.assert_called()

    @mock.patch("bauble.view.HistoryView.add_rows")
    def test_on_history_tv_value_changed_at_bottom(self, mock_add_rows):
        mock_tv = mock.MagicMock()
        mock_tv.get_visible_range.return_value = [True, True]
        mock_ls = mock.MagicMock()
        # bottom_line - id of last visible line (higher is towards top)
        mock_ls.get_value.return_value = 1
        hist_view = HistoryView()
        hist_view.history_tv = mock_tv
        hist_view.liststore = mock_ls
        # id of last row in tree - below visible row (higher is towards top)
        hist_view.last_row_in_tree = 1
        # line number of last row in tree (higher is towards the bottom)
        hist_view.offset = 1000
        # the total number of potential rows
        hist_view.hist_count = 1000
        hist_view.on_history_tv_value_changed()
        mock_add_rows.assert_not_called()

    @mock.patch("bauble.gui")
    @mock.patch("bauble.view.HistoryView.show_error_box")
    def test_add_rows_w_exception(self, mock_show_error, _mock_gui):
        db._Session = mock.Mock()
        db._Session.side_effect = ValueError("boom")
        hist_view = HistoryView()
        hist_view.add_rows()
        mock_show_error.assert_called()

    @mock.patch("bauble.gui")
    def test_show_error_box(self, mock_gui):
        hist_view = HistoryView()
        values = "test msg", "test_details"
        hist_view.show_error_box(*values)
        mock_gui.show_error_box.assert_called_with(*values)


class TestPicturesScroller(BaubleTestCase):
    def test_on_destroy_records_width_and_selected_page(self):
        window = Gtk.Window()
        window.resize(300, 300)
        box = Gtk.Box()
        notebook = Gtk.Notebook()
        pics_box = Gtk.Paned()
        pic_pane = Gtk.Paned()  # the parent pane, notebook is within
        notebook.append_page(pics_box, Gtk.Label(label="test"))
        box2 = Gtk.Box()
        pic_pane.pack1(box2)
        pic_pane.pack2(notebook)
        box.pack_start(pic_pane, True, True, 1)
        window.add(box)
        PicturesScroller(parent=pics_box, pic_pane=pic_pane)
        self.assertIsNone(prefs.prefs.get(PIC_PANE_WIDTH_PREF))
        pic_pane.set_position(100)
        box3 = Gtk.Box()
        notebook.append_page(box3, Gtk.Label(label="test2"))
        notebook.show_all()
        # NOTE can't set current page until after show_all
        notebook.set_current_page(1)
        window.show_all()
        window.destroy()
        self.assertEqual(prefs.prefs.get(PIC_PANE_WIDTH_PREF), 100)
        self.assertEqual(prefs.prefs.get(PIC_PANE_PAGE_PREF), 1)

    def test_set_width_and_notebook_page(self):
        prefs.prefs[PIC_PANE_PAGE_PREF] = 1
        window = Gtk.Window()
        window.resize(500, 500)
        box = Gtk.Box()
        notebook = Gtk.Notebook()
        pics_box = Gtk.Paned()
        pic_pane = Gtk.Paned()  # the parent pane, notebook is within
        notebook.append_page(pics_box, Gtk.Label(label="test"))
        box2 = Gtk.Box()
        pic_pane.pack1(box2)
        pic_pane.pack2(notebook)
        box.pack_start(pic_pane, True, True, 1)
        window.add(box)
        pic_pane.set_position(100)
        box3 = Gtk.Box()
        notebook.append_page(box3, Gtk.Label(label="test2"))
        notebook.show_all()
        # NOTE can't set current page until after show_all
        notebook.set_current_page(1)
        PicturesScroller(
            parent=pics_box, pic_pane=pic_pane
        ).set_width_and_notebook_page()
        # default position if not set
        self.assertEqual(pic_pane.get_position(), 1000 - 300 - 300 - 6)
        # as set in prefs
        self.assertEqual(notebook.get_current_page(), 1)

        # no search results
        with mock.patch("bauble.gui") as mock_gui:
            mock_gui.window.get_size().width = 1000
            search_view = get_search_view()
            search_view.infobox = None
            mock_gui.get_view.return_value = search_view
            PicturesScroller(
                parent=pics_box, pic_pane=pic_pane
            ).set_width_and_notebook_page()
            self.assertEqual(pic_pane.get_position(), 1000 - 0 - 300 - 6)

    def test_populate_from_selection_adds_children(self):
        box = Gtk.Box()
        notebook = Gtk.Notebook()
        pics_box = Gtk.Paned()
        pic_pane = Gtk.Paned()  # the parent pane, notebook is within
        notebook.append_page(pics_box, Gtk.Label(label="test"))
        box2 = Gtk.Box()
        pic_pane.pack1(box2)
        pic_pane.pack2(notebook)
        box.pack_start(pic_pane, True, True, 1)
        picture_scroller = PicturesScroller(parent=pics_box, pic_pane=pic_pane)
        self.assertFalse(picture_scroller.pictures_box.get_children())
        # single
        picture_scroller.populate_from_selection(
            [
                mock.Mock(
                    pictures=[mock.Mock(picture="test.jpg", category="test")]
                )
            ]
        )
        self.assertEqual(len(picture_scroller.pictures_box.get_children()), 1)
        # test doesn't add twice
        mock_pic = mock.Mock(picture="test.jpg", category="test")
        picture_scroller.populate_from_selection(
            [mock.Mock(pictures=[mock_pic]), mock.Mock(pictures=[mock_pic])]
        )
        self.assertEqual(len(picture_scroller.pictures_box.get_children()), 1)

    def test_add_rows(self):
        box = Gtk.Box()
        notebook = Gtk.Notebook()
        pics_box = Gtk.Paned()
        pic_pane = Gtk.Paned()  # the parent pane, notebook is within
        notebook.append_page(pics_box, Gtk.Label(label="test"))
        box2 = Gtk.Box()
        pic_pane.pack1(box2)
        pic_pane.pack2(notebook)
        box.pack_start(pic_pane, True, True, 1)

        path = os.path.join(paths.lib_dir(), "images", "bauble_logo.png")
        mock_pic = mock.Mock(category="test", picture=path)
        picture_scroller = PicturesScroller(parent=pics_box, pic_pane=pic_pane)
        picture_scroller.count = 0
        picture_scroller.all_pics = [mock_pic]
        self.assertEqual(len(picture_scroller.pictures_box.get_children()), 0)
        picture_scroller.add_rows()
        wait_on_threads()
        update_gui()
        self.assertEqual(len(picture_scroller.pictures_box.get_children()), 1)

    def test_add_rows_bails_early_if_populated_or_no_pics(self):
        box = Gtk.Box()
        notebook = Gtk.Notebook()
        pics_box = Gtk.Paned()
        pic_pane = Gtk.Paned()  # the parent pane, notebook is within
        notebook.append_page(pics_box, Gtk.Label(label="test"))
        box2 = Gtk.Box()
        pic_pane.pack1(box2)
        pic_pane.pack2(notebook)
        box.pack_start(pic_pane, True, True, 1)
        picture_scroller = PicturesScroller(parent=pics_box, pic_pane=pic_pane)
        picture_scroller.count = 2
        picture_scroller.all_pics = [1, 2]
        picture_scroller.max_allocated_height = 100
        picture_scroller.add_rows()
        # should not be set to 0.
        self.assertEqual(picture_scroller.max_allocated_height, 100)
        picture_scroller.all_pics = None
        picture_scroller.add_rows()
        # should not be set to 0.
        self.assertEqual(picture_scroller.max_allocated_height, 100)

    def test_on_scrolled_adds_if_needed(self):
        mock_self = mock.Mock()
        mock_self.max_allocated_height = 100
        mock_adj = mock.Mock()
        mock_adj.get_page_size.return_value = 10
        mock_adj.get_value.return_value = 10
        mock_adj.get_upper.return_value = 200
        PicturesScroller.on_scrolled(mock_self, mock_adj)
        mock_self.add_rows.assert_not_called()
        mock_adj.get_upper.return_value = 100
        PicturesScroller.on_scrolled(mock_self, mock_adj)
        mock_self.add_rows.assert_called()

    def test_on_image_size_allocated(self):
        mock_adj = mock.Mock()
        mock_adj.get_page_size.return_value = 10
        mock_adj.get_value.return_value = 10
        mock_adj.get_upper.return_value = 200
        mock_self = mock.Mock()
        mock_self.waiting_on_realise = 3
        mock_self.max_allocated_height = 0
        mock_self.get_vadjustment.return_value = mock_adj
        # make sure idle_add finishes
        mock_self.on_scrolled.return_value = False
        mock_image = mock.Mock()
        mock_image.get_parent().get_allocated_height.return_value = 10

        PicturesScroller.on_image_size_allocated(mock_self, mock_image)
        self.assertEqual(mock_self.max_allocated_height, 10)
        self.assertEqual(mock_self.waiting_on_realise, 2)
        mock_self.on_scrolled.assert_not_called()

        mock_image.get_parent().get_allocated_height.return_value = 20

        PicturesScroller.on_image_size_allocated(mock_self, mock_image)
        self.assertEqual(mock_self.max_allocated_height, 20)
        self.assertEqual(mock_self.waiting_on_realise, 1)
        mock_self.on_scrolled.assert_not_called()

        mock_image.get_parent().get_allocated_height.return_value = 19

        PicturesScroller.on_image_size_allocated(mock_self, mock_image)
        update_gui()
        wait_on_threads()
        self.assertEqual(mock_self.max_allocated_height, 20)
        self.assertEqual(mock_self.waiting_on_realise, 0)
        mock_self.on_scrolled.assert_called()
        mock_self.reset_mock()
        # does not set waiting_on_realise below zero
        PicturesScroller.on_image_size_allocated(mock_self, mock_image)
        update_gui()
        wait_on_threads()
        self.assertEqual(mock_self.max_allocated_height, 20)
        self.assertEqual(mock_self.waiting_on_realise, 0)
        mock_self.on_scrolled.assert_called()

    @mock.patch("bauble.utils.desktop.open")
    def test_on_button_press_double_click_opens_picture(self, mock_open):
        box = Gtk.Box()
        notebook = Gtk.Notebook()
        pics_box = Gtk.Paned()
        pic_pane = Gtk.Paned()  # the parent pane, notebook is within
        notebook.append_page(pics_box, Gtk.Label(label="test"))
        box2 = Gtk.Box()
        pic_pane.pack1(box2)
        pic_pane.pack2(notebook)
        box.pack_start(pic_pane, True, True, 1)
        picture_scroller = PicturesScroller(parent=pics_box, pic_pane=pic_pane)
        mock_event = mock.Mock(button=1, type=Gdk.EventType._2BUTTON_PRESS)
        picture_scroller.on_button_press(
            None, mock_event, mock.Mock(picture="test.jpg")
        )
        mock_open.assert_called_with(Path("pictures/test.jpg"))
        mock_open.reset_mock()
        with mock.patch("bauble.gui") as mock_gui:
            mock_event = mock.Mock(button=1, type=Gdk.EventType.BUTTON_PRESS)
            picture_scroller.on_button_press(
                None, mock_event, mock.Mock(picture="test.jpg")
            )
            mock_event = mock.Mock(button=1, type=Gdk.EventType._2BUTTON_PRESS)
            picture_scroller.on_button_press(
                None, mock_event, mock.Mock(picture="test.jpg")
            )
            wait_on_threads()
            update_gui()
            mock_open.assert_called_with(Path("pictures/test.jpg"))
            mock_gui.assert_not_called()

    @mock.patch("bauble.gui")
    def test_on_button_press_single_click_selects_obj(self, mock_gui):
        box = Gtk.Box()
        notebook = Gtk.Notebook()
        pics_box = Gtk.Paned()
        pic_pane = Gtk.Paned()  # the parent pane, notebook is within
        notebook.append_page(pics_box, Gtk.Label(label="test"))
        box2 = Gtk.Box()
        pic_pane.pack1(box2)
        pic_pane.pack2(notebook)
        box.pack_start(pic_pane, True, True, 1)
        picture_scroller = PicturesScroller(parent=pics_box, pic_pane=pic_pane)
        mock_gui.get_view.return_value = None
        mock_event = mock.Mock(button=1, type=Gdk.EventType.BUTTON_PRESS)
        picture_scroller.on_button_press(
            None, mock_event, mock.Mock(picture="test.jpg")
        )
        wait_on_threads()
        update_gui()
        mock_gui.get_view.assert_called()

    @mock.patch("bauble.gui")
    def test_select_object(self, mock_gui):
        for func in get_setUp_data_funcs():
            func()
        from bauble.plugins.garden import Plant
        from bauble.plugins.garden import PlantPicture

        plt1 = self.session.query(Plant).get(1)
        plt2 = self.session.query(Plant).get(2)
        pic1 = PlantPicture(picture="test1.jpg")
        plt2.pictures.append(pic1)
        self.session.add(pic1)
        self.session.commit()
        box = Gtk.Box()
        notebook = Gtk.Notebook()
        pics_box = Gtk.Paned()
        pic_pane = Gtk.Paned()  # the parent pane, notebook is within
        notebook.append_page(pics_box, Gtk.Label(label="test"))
        box2 = Gtk.Box()
        pic_pane.pack1(box2)
        pic_pane.pack2(notebook)
        box.pack_start(pic_pane, True, True, 1)
        picture_scroller = PicturesScroller(parent=pics_box, pic_pane=pic_pane)
        picture_scroller.set_selection = mock.Mock()
        # species selected should traverse
        search_view = get_search_view()
        search_view.pictures_scroller = picture_scroller
        search_view.history_action = mock.Mock()
        search_view.populate_results([plt2.accession.species])
        search_view.results_view.set_cursor(Gtk.TreePath.new_first())
        mock_gui.get_view.return_value = search_view
        self.assertEqual(
            search_view.get_selected_values(), [plt2.accession.species]
        )
        picture_scroller.select_object(pic1)
        self.assertEqual(search_view.get_selected_values(), [plt2])
        mock_gui.get_view.assert_called()
        # plant selected should do nothing
        search_view.populate_results([plt1, plt2])
        search_view.results_view.set_cursor(Gtk.TreePath.new_from_indices([1]))
        self.assertEqual(search_view.get_selected_values(), [plt2])
        picture_scroller.select_object(pic1)
        self.assertEqual(search_view.get_selected_values(), [plt2])
        # both selected selects owner
        search_view.results_view.get_selection().select_all()
        self.assertEqual(search_view.get_selected_values(), [plt1, plt2])
        picture_scroller.select_object(pic1)
        self.assertEqual(search_view.get_selected_values(), [plt2])
        # just for coverage...
        search_view.results_view.set_model(None)
        picture_scroller.select_object(pic1)

    @mock.patch("bauble.gui", GUI())
    def test_hide_restore_pic_pane(self):
        box = Gtk.Box()
        notebook = Gtk.Notebook()
        pics_box = Gtk.Paned()
        pic_pane = Gtk.Paned()  # the parent pane, notebook is within
        notebook.append_page(pics_box, Gtk.Label(label="test"))
        box2 = Gtk.Box()
        pic_pane.pack1(box2)
        pic_pane.pack2(notebook)
        box.pack_start(pic_pane, True, True, 1)
        picture_scroller = PicturesScroller(parent=pics_box, pic_pane=pic_pane)
        self.assertEqual(picture_scroller.restore_position, -1)
        # no result
        self.assertFalse(picture_scroller.restore_pic_pane)
        picture_scroller._hide_restore_pic_pane([])
        self.assertTrue(picture_scroller.restore_pic_pane)
        rectangle = Gdk.Rectangle()
        rectangle.height = 10
        rectangle.width = 10
        rectangle.x = 10
        rectangle.y = 10

        notebook.emit("size-allocate", rectangle)
        self.assertFalse(picture_scroller.restore_pic_pane)
        self.assertEqual(picture_scroller.restore_position, -1)
        self.assertFalse(picture_scroller.last_result_succeed)
        # error
        picture_scroller._hide_restore_pic_pane(None)
        notebook.emit("size-allocate", rectangle)
        self.assertEqual(picture_scroller.restore_position, -1)
        self.assertFalse(picture_scroller.last_result_succeed)
        # success (but last result was a fail - idle_add pic_pane set_position)
        restore_pos = picture_scroller.restore_position
        self.assertFalse(picture_scroller.restore_pic_pane)
        picture_scroller._hide_restore_pic_pane([1])
        self.assertTrue(picture_scroller.restore_pic_pane)
        notebook.emit("size-allocate", rectangle)
        self.assertFalse(picture_scroller.restore_pic_pane)
        self.assertTrue(picture_scroller.last_result_succeed)
        # no result (yet records restore position because prev was successful)
        picture_scroller._hide_restore_pic_pane([])
        notebook.emit("size-allocate", rectangle)
        self.assertFalse(picture_scroller.last_result_succeed)
        restore_pos2 = picture_scroller.restore_position
        self.assertIsNotNone(restore_pos2)
        self.assertNotEqual(restore_pos2, restore_pos)
        # succeed and change position then succeed again should store new value
        picture_scroller._hide_restore_pic_pane([1])
        notebook.emit("size-allocate", rectangle)
        picture_scroller.pic_pane.set_position(100)
        self.assertTrue(picture_scroller.last_result_succeed)
        picture_scroller._hide_restore_pic_pane([1])
        notebook.emit("size-allocate", rectangle)
        self.assertEqual(picture_scroller.restore_position, 100)
        self.assertTrue(picture_scroller.last_result_succeed)
        # change position then fail multiple time, captures and uses last
        # successful position
        picture_scroller.pic_pane.set_position(50)
        picture_scroller._hide_restore_pic_pane(None)
        notebook.emit("size-allocate", rectangle)
        self.assertFalse(picture_scroller.last_result_succeed)
        picture_scroller._hide_restore_pic_pane(None)
        notebook.emit("size-allocate", rectangle)
        self.assertFalse(picture_scroller.last_result_succeed)
        picture_scroller._hide_restore_pic_pane([])
        notebook.emit("size-allocate", rectangle)
        self.assertFalse(picture_scroller.last_result_succeed)
        self.assertEqual(picture_scroller.restore_position, 50)
        picture_scroller._hide_restore_pic_pane([1])
        notebook.emit("size-allocate", rectangle)
        self.assertTrue(picture_scroller.last_result_succeed)
        self.assertEqual(picture_scroller.restore_position, 50)
        self.assertEqual(picture_scroller.pic_pane.get_position(), 50)


class NotesBottomPageTests(BaubleTestCase):

    def test_update_populates_makes_label_bold(self):
        notes_page = NotesBottomPage()
        now = datetime.now().date()

        mock_note = mock.Mock(date=now, user="me", category="foo", note="bar")
        mock_row = mock.Mock(notes=[mock_note])

        notes_page.update(mock_row)

        self.assertEqual(len(notes_page.liststore), 1)
        self.assertTrue(notes_page.label.get_use_markup())

        mock_row = mock.Mock(notes=[])

        notes_page.update(mock_row)

        self.assertEqual(len(notes_page.liststore), 0)
        self.assertFalse(notes_page.label.get_use_markup())

    def test_on_note_row_activated(self):
        notes_page = NotesBottomPage()
        notes_page.domain = "test"
        notes_page.liststore.append([None, None, "cat", "note"])
        mock_send = mock.Mock()

        notes_page.on_row_activated(None, 0, None, send_command=mock_send)
        mock_send.assert_called_with(
            "test where notes[category='cat'].note='note'",
        )


class GlobalFunctionsTests(BaubleTestCase):
    def test_select_in_search_results_selects_existing(self):
        for func in get_setUp_data_funcs():
            func()
        search_view = get_search_view()
        search_view.history_action = mock.Mock()
        search_view.search("genus where id <= 3")
        start = search_view.get_selected_values()
        obj = self.session.query(start[0].__class__).get(3)
        with mock.patch("bauble.gui") as mock_gui:
            mock_gui.get_view.return_value = search_view
            select_in_search_results(obj)
        end = search_view.get_selected_values()
        self.assertNotEqual(start, end)
        self.assertEqual(end[0].id, obj.id)
        search_view.cancel_threads()

    @mock.patch("bauble.gui")
    def test_get_search_view_selected(self, mock_gui):
        for func in get_setUp_data_funcs():
            func()
        search_view = get_search_view()
        search_view.search("plant=*")
        self.assertTrue(search_view.get_selected_values())

        mock_gui.get_view.return_value = search_view

        self.assertEqual(
            get_search_view_selected(), search_view.get_selected_values()
        )

    def test_select_in_search_results_adds_not_existing(self):
        for func in get_setUp_data_funcs():
            func()
        search_view = get_search_view()
        search_view.history_action = mock.Mock()
        search_view.search("genus where id <= 3")
        start = search_view.get_selected_values()
        obj = self.session.query(start[0].__class__).get(5)
        with mock.patch("bauble.gui") as mock_gui:
            mock_gui.get_view.return_value = search_view
            with self.assertLogs(level="DEBUG") as logs:
                select_in_search_results(obj)
        self.assertTrue(
            any(f"{obj} added to search results" in i for i in logs.output)
        )
        end = search_view.get_selected_values()
        self.assertNotEqual(start, end)
        self.assertEqual(end[0].id, obj.id)
        update_gui()
        search_view.cancel_threads()
