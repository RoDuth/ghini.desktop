# pylint: disable=no-self-use,protected-access,too-many-public-methods
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
Tag info box tests
"""
from unittest import TestCase
from unittest import mock

from gi.repository import Gtk

from bauble.test import BaubleTestCase

from .. import Tag
from ..ui.view import TagInfoBox
from ..ui.view import on_tag_bottom_info_activated


class TagInfoBoxTest(BaubleTestCase):

    def test_update_infobox_from_empty_tag(self):
        t = Tag(tag="name", description="description")
        ib = TagInfoBox()
        ib.update(t)
        self.assertEqual(
            ib.widgets.ib_description_label.get_text(), t.description
        )
        self.assertEqual(ib.widgets.ib_name_label.get_text(), t.tag)
        self.assertEqual(ib.general.table_cells, [])
        ib.destroy()

    def test_update_infobox_from_tagging_tag(self):
        t = Tag(tag="name", description="description")
        x = Tag(tag="objectx", description="none")
        y = Tag(tag="objecty", description="none")
        z = Tag(tag="objectz", description="none")
        self.session.add_all([t, x, y, z])
        self.session.commit()
        t.tag_objects([x, y, z])
        ib = TagInfoBox()
        self.assertEqual(ib.general.table_cells, [])
        ib.update(t)
        self.assertEqual(
            ib.widgets.ib_description_label.get_text(), t.description
        )
        self.assertEqual(ib.widgets.ib_name_label.get_text(), t.tag)
        self.assertEqual(len(ib.general.table_cells), 2)
        self.assertEqual(ib.general.table_cells[0].get_text(), "Tag")
        self.assertEqual(type(ib.general.table_cells[1]), Gtk.EventBox)
        label = ib.general.table_cells[1].get_children()[0]
        self.assertEqual(label.get_text(), " 3 ")
        ib.destroy()

    def test_update_repopulates_grid(self):
        tag1 = Tag(tag="tag1")
        tag2 = Tag(tag="tag2")
        self.session.add_all([tag1, tag2])
        self.session.commit()
        tag1.tag_objects([tag2])
        ib = TagInfoBox()
        mock_grid = mock.Mock()
        ib.widgets.tag_ib_general_grid = mock_grid
        ib.update(tag1)
        # not first time
        mock_grid.remove.assert_not_called()
        self.assertEqual(len(ib.general.table_cells), 2)

        ib.update(tag1)
        # but second time
        mock_grid.remove.assert_called()
        self.assertEqual(len(ib.general.table_cells), 2)
        ib.destroy()


class GlobalFunctionsTests(TestCase):
    def test_on_tag_bottom_info_activated(self):
        mock_send = mock.Mock()
        model = Gtk.ListStore(str, str)
        model.append(["Foo", "description"])
        path = Gtk.TreePath.new_first()
        tree = Gtk.TreeView().new_with_model(model)
        on_tag_bottom_info_activated(tree, path, None, send_command=mock_send)
        mock_send.assert_called_with("tag='Foo'")
