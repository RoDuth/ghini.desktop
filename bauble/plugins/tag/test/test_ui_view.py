# pylint: disable=no-self-use,protected-access,too-many-public-methods
# Copyright (c) 2005,2006,2007,2008,2009 Brett Adams <brett@belizebotanic.org>
# Copyright (c) 2012-2015 Mario Frasca <mario@anche.no>
# Copyright (c) 2021-2026 Ross Demuth <rossdemuth123@gmail.com>
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
from unittest import mock

from gi.repository import Gtk

from bauble.test import BaubleTestCase

from .. import Tag
from ..ui.view import TagInfoBox
from ..ui.view import TagsScroller
from ..ui.view import remove_callback


class TagInfoBoxTest(BaubleTestCase):

    def test_update_infobox_from_empty_tag(self):
        t = Tag(tag="name", description="description")
        ib = TagInfoBox()
        ib.update(t)
        general = ib.get_nth_page(0).expanders["General"]
        self.assertEqual(general.description_label.get_text(), t.description)
        self.assertEqual(general.name_label.get_text(), t.tag)
        self.assertEqual(general.table_cells, [])
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
        general = ib.get_nth_page(0).expanders["General"]
        self.assertEqual(general.table_cells, [])
        ib.update(t)
        self.assertEqual(general.description_label.get_text(), t.description)
        self.assertEqual(general.name_label.get_text(), t.tag)
        self.assertEqual(len(general.table_cells), 2)
        self.assertEqual(general.table_cells[0].get_text(), "Tag")
        self.assertEqual(type(general.table_cells[1]), Gtk.EventBox)
        label = general.table_cells[1].get_children()[0]
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
        general = ib.get_nth_page(0).expanders["General"]
        general.grid = mock_grid
        ib.update(tag1)
        # not first time
        mock_grid.remove.assert_not_called()
        self.assertEqual(len(general.table_cells), 2)

        ib.update(tag1)
        # but second time
        mock_grid.remove.assert_called()
        self.assertEqual(len(general.table_cells), 2)
        ib.destroy()


class TagsScrollerTests(BaubleTestCase):

    def test_update_populates_makes_label_bold(self):
        tag1 = Tag(tag="tag1")
        tag2 = Tag(tag="tag2")
        self.session.add_all([tag1, tag2])
        self.session.commit()
        tag1.tag_objects([tag2])
        self.session.commit()
        tags_page = TagsScroller()

        tags_page.update(tag2)

        self.assertEqual(len(tags_page.liststore), 1)
        self.assertTrue(tags_page.label.get_use_markup())

        tags_page.update(tag1)

        self.assertEqual(len(tags_page.liststore), 0)
        self.assertFalse(tags_page.label.get_use_markup())

    def test_on_note_row_activated(self):
        tags_page = TagsScroller()
        tags_page.liststore.append(("foo", "bar"))
        mock_send = mock.Mock()

        tags_page.on_row_activated(None, 0, None, send_command=mock_send)
        mock_send.assert_called_with("tag='foo'")


class GlobalFunctionsTests(BaubleTestCase):

    @mock.patch("bauble.plugins.tag.menu_manager.reset")
    @mock.patch("bauble.ui.dialogs.message_details_dialog")
    @mock.patch("bauble.ui.dialogs.yes_no_dialog")
    def test_remove_callback_no_confirm(self, mock_ynd, mock_mdd, mock_reset):
        mock_ynd.return_value = False

        tag = Tag(tag="Foo")
        self.session.add(tag)
        self.session.commit()

        result = remove_callback([tag])
        self.session.flush()

        mock_mdd.assert_not_called()
        # effect
        mock_ynd.assert_called_with(
            "Are you sure you want to remove Tag: Foo?"
        )
        mock_reset.assert_not_called()

        self.assertFalse(result)
        matching = self.session.query(Tag).filter_by(tag="Foo").all()
        self.assertEqual(matching, [tag])

    @mock.patch("bauble.plugins.tag.menu_manager.reset")
    @mock.patch("bauble.ui.dialogs.message_details_dialog")
    @mock.patch("bauble.ui.dialogs.yes_no_dialog")
    def test_remove_callback_confirm(self, mock_ynd, mock_mdd, mock_reset):
        mock_ynd.return_value = True

        tag = Tag(tag="Foo")
        self.session.add(tag)
        self.session.flush()

        result = remove_callback([tag])
        self.session.flush()

        mock_reset.assert_called()
        mock_mdd.assert_not_called()
        mock_ynd.assert_called_with(
            "Are you sure you want to remove Tag: Foo?"
        )
        self.assertEqual(result, True)
        matching = self.session.query(Tag).filter_by(tag="Foo").all()
        self.assertEqual(matching, [])

    @mock.patch("bauble.plugins.tag.menu_manager.reset")
    @mock.patch("bauble.ui.dialogs.message_details_dialog")
    @mock.patch("bauble.ui.dialogs.yes_no_dialog")
    def test_remove_callback_no_object_session_bails(
        self,
        mock_ynd,
        mock_mdd,
        mock_reset,
    ):
        tag = Tag(tag="Foo")

        with self.assertLogs(level="WARNING") as logs:
            result = remove_callback([tag])

        string = "no object session bailing."
        self.assertTrue(any(string in i for i in logs.output))
        mock_reset.assert_not_called()
        mock_mdd.assert_not_called()
        mock_ynd.assert_not_called()
        self.assertEqual(result, False)

    @mock.patch("bauble.plugins.tag.menu_manager.reset")
    @mock.patch("bauble.ui.dialogs.message_details_dialog")
    @mock.patch("bauble.ui.dialogs.yes_no_dialog")
    def test_remove_callback_warns_if_exception(
        self,
        mock_ynd,
        mock_mdd,
        mock_reset,
    ):
        mock_ynd.return_value = True
        tag = Tag()
        self.session.add(tag)

        result = remove_callback([tag])

        mock_reset.assert_called()
        mock_ynd.assert_called()
        mock_mdd.assert_called()
        self.assertEqual(result, True)
