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

import bauble.meta as meta
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

    def test_confirm_default(self):
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
        # test that a dialog_box is created, test it offers the default and
        # contains the message. test if we press OK it save it
        from bauble import utils
        _orig_create_message_dialog = utils.create_message_dialog
        import gi
        gi.require_version("Gtk", "3.0")
        from gi.repository import Gtk  # noqa

        class MockDialog:
            def __init__(self):
                self.msg = None
                self.box = set()
                self.size = dict()

            def get_message_area(self):
                return self.box

            def resize(self, x, y):
                return

            def show_all(self):
                return

            def run(self):
                return Gtk.ResponseType.OK

            def destroy(self):
                return

        mock_dialog = MockDialog()

        def mock_create_message_dialog(msg):
            mock_dialog.msg = msg
            return mock_dialog

        utils.create_message_dialog = mock_create_message_dialog
        name = 'test2'
        msg = 'test msg2'
        obj3 = meta.confirm_default(name, value, msg)
        self.assertEqual(mock_dialog.msg, msg)

        # test the new value was added and returned correctly
        result = self.session.query(meta.BaubleMeta).filter_by(name=name).one()
        self.assertEqual(result.value, value)
        self.assertEqual(result.value, obj3.value)
        utils.create_message_dialog = _orig_create_message_dialog

        # test that if the dialog is canceled the metadata is not saved
        class MockDialog2(MockDialog):
            def run(self):
                return Gtk.ResponseType.CANCEL

        mock_dialog = MockDialog2()

        utils.create_message_dialog = mock_create_message_dialog
        name = 'test3'
        msg = 'test msg3'
        obj3 = meta.confirm_default(name, value, msg)
        self.assertEqual(mock_dialog.msg, msg)

        # test the new value was added and returned correctly
        result = self.session.query(meta.BaubleMeta).filter_by(
            name=name).first()
        self.assertIsNone(result)
        utils.create_message_dialog = _orig_create_message_dialog
