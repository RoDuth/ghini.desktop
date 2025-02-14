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

import os
from unittest import mock

from gi.repository import Gtk

from bauble import db
from bauble import utils
from bauble.editor import GenericEditorView
from bauble.plugins.garden import Accession
from bauble.test import BaubleTestCase
from bauble.test import check_dupids

from .. import Tag
from ..model import TaggedObj
from ..ui.editor import TagEditorPresenter
from ..ui.editor import remove_callback

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


def setUp_data():
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


# TODO redundant?
def test_duplicate_ids():
    """
    Test for duplicate ids for all .glade files in the tag plugin.
    """
    import glob

    import bauble.plugins.tag as mod

    head, _tail = os.path.split(mod.__file__)
    files = glob.glob(os.path.join(head, "*.glade"))
    for f in files:
        assert not check_dupids(f)


# TODO all this to move to test_editor.py

from types import SimpleNamespace


class MockTagView(GenericEditorView):
    def __init__(self):
        self._dirty = False
        self.sensitive = False
        self.dict = {}
        self.widgets = SimpleNamespace(tag_name_entry=Gtk.Entry())
        self.window = Gtk.Dialog()

    def get_window(self):
        return self.window

    def is_dirty(self):
        return self._dirty

    def connect_signals(self, *args):
        pass

    def set_accept_buttons_sensitive(self, value):
        self.sensitive = value

    def widget_set_value(
        self, widget, value, markup=False, default=None, index=0
    ):
        self.dict[widget] = value

    def widget_get_value(self, widget):
        return self.dict.get(widget)


class TagPresenterTests(BaubleTestCase):
    "Presenter manages view and model, implements view callbacks."

    def test_when_user_edits_name_name_is_memorized(self):
        model = Tag()
        view = MockTagView()
        presenter = TagEditorPresenter(model, view)
        view.widget_set_value("tag_name_entry", "1234")
        presenter.on_text_entry_changed("tag_name_entry")
        self.assertEqual(presenter.model.tag, "1234")

    def test_when_user_inserts_existing_name_warning_ok_deactivated(self):
        session = db.Session()

        # prepare data in database
        obj = Tag(tag="1234")
        session.add(obj)
        session.commit()
        session.close()

        session = db.Session()
        view = MockTagView()
        obj = Tag()  # new scratch object
        session.add(obj)  # is in session
        presenter = TagEditorPresenter(obj, view)
        self.assertTrue(not view.sensitive)  # not changed
        presenter.on_unique_text_entry_changed("tag_name_entry", "1234")
        self.assertEqual(obj.tag, "1234")
        self.assertTrue(view.is_dirty())
        self.assertTrue(not view.sensitive)  # unacceptable change
        self.assertTrue(presenter.has_problems())

    def test_widget_names_and_field_names(self):
        model = Tag()
        view = MockTagView()
        presenter = TagEditorPresenter(model, view)
        for widget, field in list(presenter.widget_to_field_map.items()):
            self.assertTrue(hasattr(model, field), field)
            presenter.view.widget_get_value(widget)

    def test_when_user_edits_fields_ok_active(self):
        model = Tag()
        view = MockTagView()
        presenter = TagEditorPresenter(model, view)
        self.assertTrue(not view.sensitive)  # not changed
        view.widget_set_value("tag_name_entry", "1234")
        presenter.on_text_entry_changed("tag_name_entry")
        self.assertEqual(presenter.model.tag, "1234")
        self.assertTrue(view.sensitive)  # changed

    def test_when_user_edits_description_description_is_memorized(self):
        pass

    def test_presenter_does_not_initialize_view(self):
        session = db.Session()

        # prepare data in database
        obj = Tag(tag="1234")
        session.add(obj)
        view = MockTagView()
        presenter = TagEditorPresenter(obj, view)
        self.assertFalse(view.widget_get_value("tag_name_entry"))
        presenter.refresh_view()
        self.assertEqual(view.widget_get_value("tag_name_entry"), "1234")

    def test_if_asked_presenter_initializes_view(self):
        session = db.Session()

        # prepare data in database
        obj = Tag(tag="1234")
        session.add(obj)
        view = MockTagView()
        TagEditorPresenter(obj, view, refresh_view=True)
        self.assertEqual(view.widget_get_value("tag_name_entry"), "1234")


class GlobalFunctionsTests(BaubleTestCase):

    def test_remove_callback_no_confirm(self):
        mock_ynd = mock.Mock()
        mock_ynd.return_value = False
        mock_mdd = mock.Mock()
        mock_reset = mock.Mock()

        tag = Tag(tag="Foo")
        self.session.add(tag)
        self.session.flush()

        result = remove_callback(
            [tag],
            yes_no_dialog=mock_ynd,
            message_details_dialog=mock_mdd,
            menu_reset=mock_reset,
        )
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

    def test_remove_callback_confirm(self):
        mock_ynd = mock.Mock()
        mock_ynd.return_value = True
        mock_mdd = mock.Mock()
        mock_reset = mock.Mock()

        tag = Tag(tag="Foo")
        self.session.add(tag)
        self.session.flush()

        result = remove_callback(
            [tag],
            yes_no_dialog=mock_ynd,
            message_details_dialog=mock_mdd,
            menu_reset=mock_reset,
        )
        self.session.flush()

        mock_reset.assert_called()
        mock_mdd.assert_not_called()
        mock_ynd.assert_called_with(
            "Are you sure you want to remove Tag: Foo?"
        )
        self.assertEqual(result, True)
        matching = self.session.query(Tag).filter_by(tag="Foo").all()
        self.assertEqual(matching, [])
