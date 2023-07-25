# Copyright (c) 2005,2006,2007,2008,2009 Brett Adams <brett@belizebotanic.org>
# Copyright (c) 2012-2015 Mario Frasca <mario@anche.no>
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
#
# test for bauble.meta
#
from unittest import mock
from gi.repository import Gtk

from bauble import meta, db
from bauble.test import BaubleTestCase


class MetaTests(BaubleTestCase):

    def __init__(self, *args):
        super().__init__(*args)

    def test_get_default(self):
        """
        Test bauble.meta.get_default()
        """
        # test the object isn't created if it doesn't exist and we
        # don't pass a default value
        name = 'name'
        obj = meta.get_default(name)
        self.assertTrue(obj is None)

        # test that the obj is created if it doesn't exists and that
        # the default value is set
        value = 'value'
        meta.get_default(name, default=value)
        obj = self.session.query(meta.BaubleMeta).filter_by(name=name).one()
        self.assertTrue(obj.value == value)

        # test that the value isn't changed if it already exists
        value2 = 'value2'
        obj = meta.get_default(name, default=value2)
        self.assertTrue(obj.value == value)

        # test that if we pass our own session when we are creating a
        # new value that the object is added to the session but not committed
        obj = meta.get_default('name2', default=value, session=self.session)
        self.assertTrue(obj in self.session.new)

    def test_confirm_default_with_value(self):
        # when value already exists it is just returned
        name = 'test'
        value = 'test value'
        obj1 = meta.get_default(name, value)
        obj2 = meta.confirm_default(name, value, 'test msg')
        self.assertEqual(obj1.value, obj2.value)
        self.assertEqual(obj1.name, obj2.name)

        # test giving a different value doesn't change it
        value = 'value2'
        obj2 = meta.confirm_default(name, value, 'test msg')
        self.assertEqual(obj1.value, obj2.value)
        self.assertEqual(obj1.name, obj2.name)

    @mock.patch('bauble.prefs.Gtk.MessageDialog.run',
                return_value=Gtk.ResponseType.OK)
    def test_confirm_default_no_value_ok(self, mock_dialog):
        # a dialog_box is created, offers the default, contains the message and
        # press OK saves it
        name = 'test2'
        value = 'test value'
        msg = 'test msg2'
        obj3 = meta.confirm_default(name, value, msg)
        mock_dialog.assert_called()
        # self.assertEqual(mock_dialog.msg, msg)

        # test the new value was added and returned correctly
        result = self.session.query(meta.BaubleMeta).filter_by(name=name).one()
        self.assertEqual(result.value, value)
        self.assertEqual(result.value, obj3.value)

    @mock.patch('bauble.prefs.Gtk.MessageDialog.run',
                return_value=Gtk.ResponseType.CANCEL)
    def test_confirm_default_no_value_cancel(self, mock_dialog):
        # a dialog_box is created, offers the default, contains the message and
        # cancelling does not save.
        name = 'test3'
        value = 'test value'
        msg = 'test msg3'
        obj3 = meta.confirm_default(name, value, msg)
        mock_dialog.assert_called()

        # test the new value was not added and returned correctly
        result = self.session.query(meta.BaubleMeta).filter_by(
            name=name).first()
        self.assertIsNone(result)
        self.assertIsNone(obj3)

    def test_get_cached_value(self):
        name = 'test3'
        value = 'test value'
        value2 = 'new value'

        self.assertIsNone(meta.get_cached_value(name))
        obj = meta.BaubleMeta(name=name, value=value)
        self.session.add(obj)
        self.session.commit()
        self.assertEqual(meta.get_cached_value(name), value)
        # ask for the same value again and the session should not be called
        with mock.patch('bauble.db.Session') as mock_session:
            val = meta.get_cached_value(name)
            mock_session.assert_not_called()
            self.assertEqual(val, value)

        # change the value and its should ask the session
        obj.value = value2
        self.session.commit()

        session = db.Session()
        with mock.patch('bauble.db.Session') as mock_session:
            mock_session.return_value = session
            val = meta.get_cached_value(name)
            mock_session.assert_called()
            self.assertEqual(val, value2)
