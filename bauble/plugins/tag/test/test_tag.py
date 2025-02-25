# pylint: disable=no-self-use,protected-access
# Copyright (c) 2005,2006,2007,2008,2009 Brett Adams <brett@belizebotanic.org>
# Copyright (c) 2012-2015 Mario Frasca <mario@anche.no>
# Copyright (c) 2021-2025 Ross Demuth <rossdemuth123@gmail.com>
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
Tag tests
"""
from unittest import mock

from bauble import search
from bauble import utils
from bauble.plugins.garden import Accession
from bauble.test import BaubleTestCase
from bauble.view import SearchView

from .. import TagPlugin
from ..model import Tag
from ..model import TaggedObj

tag_test_data = (
    {"id": 1, "tag": "test1", "description": "empty test tag"},
    {"id": 2, "tag": "test2", "description": "not empty test tag"},
)

tag_object_test_data = (
    {
        "id": 1,
        "obj_id": 1,
        "obj_class": f"{Tag.__module__}.{Tag.__name__}",
        "tag_id": 2,
    },
    {
        "id": 2,
        "obj_id": 5,
        "obj_class": f"{Accession.__module__}.{Accession.__name__}",
        "tag_id": 2,
    },
)

test_data_table_control = (
    (Tag, tag_test_data),
    (TaggedObj, tag_object_test_data),
)


def setUp_data():  # pylint: disable=invalid-name
    """Load test data.

    if this method is called again before tearDown_test_data is called you
    will get an error about the test data rows already existing in the database
    """

    for mapper, data in test_data_table_control:
        table = mapper.__table__
        # insert row by row instead of doing an insert many since each
        # row will have different columns
        for row in data:
            table.insert().execute(row).close()
        for col in table.c:
            utils.reset_sequence(col)


setUp_data.order = 2  # type: ignore [attr-defined]


class TestPlugin(BaubleTestCase):
    def test_plugin_adds_bottom_page(self):
        SearchView.bottom_pages.clear()
        plugin = TagPlugin()

        with mock.patch.object(SearchView, "bottom_pages") as mock_pages:
            plugin.init()

            mock_pages.add.assert_called_with(
                (plugin.tags_page, plugin.tags_page.label)
            )

    @mock.patch.dict(
        search.strategies._search_strategies,
        {
            k: v
            for k, v in search.strategies._search_strategies.items()
            if k != "MapperSearch"
        },
        clear=True,
    )
    def test_bails_if_no_mapper_search(self):
        plugin = TagPlugin()

        with mock.patch.object(SearchView, "bottom_pages") as mock_pages:
            plugin.init()

            mock_pages.add.assert_not_called()
