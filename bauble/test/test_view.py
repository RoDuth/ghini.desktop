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

from bauble.view import AppendThousandRows
from bauble.test import BaubleTestCase
from bauble import db, utils


class TestHistoryView(BaubleTestCase):
    def test_basic_search_query_filters_eq(self):
        search = 'table_name = plant'
        result = AppendThousandRows(None, search).get_query_filters()
        self.assertTrue(result[0].compare(db.History.table_name == 'plant'))

    def test_basic_search_query_filters_not_eq(self):
        search = 'table_name != plant'
        result = AppendThousandRows(None, search).get_query_filters()
        self.assertTrue(result[0].compare(db.History.table_name != 'plant'))

    def test_basic_search_query_filters_w_and(self):
        search = ("table_name = plant and user = 'test user' and operation ="
                  " insert")
        result = AppendThousandRows(None, search).get_query_filters()
        # self.assertEqual(str(result[0]), "")
        self.assertTrue(result[0].compare(db.History.table_name == 'plant'))
        self.assertTrue(result[1].compare(db.History.user == 'test user'))
        self.assertTrue(result[2].compare(db.History.operation == 'insert'))

    def test_basic_search_query_filters_like(self):
        # comparing strings like this is a flaky, doesn't test value but
        # compare() does not work here (at least not in sqlalchemy v1.3.24)
        search = "values like %id"
        result = AppendThousandRows(None, search).get_query_filters()
        self.assertEqual(str(result[0]),
                         str(utils.ilike(db.History.values, '%id')))

    def test_basic_search_query_filters_contains(self):
        # comparing strings like this is a flaky, doesn't test value but
        # compare() does not work here (at least not in sqlalchemy v1.3.24)
        search = "values contains id"
        result = AppendThousandRows(None, search).get_query_filters()
        self.assertEqual(str(result[0]),
                         str(utils.ilike(db.History.values, '%id')))

    def test_basic_search_query_filters_fails(self):
        search = "test = test"
        self.assertRaises(AttributeError,
                          AppendThousandRows(None, search).get_query_filters)
