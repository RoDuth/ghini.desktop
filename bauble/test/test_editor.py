# Copyright (c) 2005,2006,2007,2008,2009 Brett Adams <brett@belizebotanic.org>
# Copyright (c) 2012-2015 Mario Frasca <mario@anche.no>
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
#
# test_bauble.py
#

import os
import json
from unittest import TestCase, mock

from gi.repository import Gtk

from bauble.editor import (GenericEditorView,
                           PresenterMapMixin)
from bauble import paths
from bauble import utils
from bauble import search
from bauble import prefs

from bauble.test import BaubleTestCase


class BaubleTests(BaubleTestCase):

    def test_create_generic_view(self):
        filename = os.path.join(paths.lib_dir(), 'bauble.glade')
        view = GenericEditorView(filename)
        self.assertTrue(type(view.widgets) is utils.BuilderWidgets)

    def test_set_title_ok(self):
        filename = os.path.join(paths.lib_dir(), 'bauble.glade')
        view = GenericEditorView(filename, root_widget_name='main_window')
        title = 'testing'
        view.set_title(title)
        self.assertEqual(view.get_window().get_title(), title)

    def test_set_title_no_root(self):
        filename = os.path.join(paths.lib_dir(), 'bauble.glade')
        view = GenericEditorView(filename)
        title = 'testing'
        self.assertRaises(NotImplementedError, view.set_title, title)
        self.assertRaises(NotImplementedError, view.get_window)

    def test_set_icon_no_root(self):
        filename = os.path.join(paths.lib_dir(), 'bauble.glade')
        view = GenericEditorView(filename)
        title = 'testing'
        self.assertRaises(NotImplementedError, view.set_icon, title)

    def test_add_widget(self):
        filename = os.path.join(paths.lib_dir(), 'bauble.glade')
        view = GenericEditorView(filename)
        label = Gtk.Label(label='testing')
        view.widget_add('statusbar', label)

    def test_set_accept_buttons_sensitive_not_set(self):
        'it is a task of the presenter to indicate the accept buttons'
        filename = os.path.join(paths.lib_dir(), 'connmgr.glade')
        view = GenericEditorView(filename, root_widget_name='main_dialog')
        self.assertRaises(AttributeError,
                          view.set_accept_buttons_sensitive, True)
        view.get_window().destroy()

    def test_set_sensitive(self):
        filename = os.path.join(paths.lib_dir(), 'connmgr.glade')
        view = GenericEditorView(filename, root_widget_name='main_dialog')
        view.widget_set_sensitive('cancel_button', True)
        self.assertTrue(view.widgets.cancel_button.get_sensitive())
        view.widget_set_sensitive('cancel_button', False)
        self.assertFalse(view.widgets.cancel_button.get_sensitive())
        view.get_window().destroy()

    def test_set_visible_get_visible(self):
        filename = os.path.join(paths.lib_dir(), 'connmgr.glade')
        view = GenericEditorView(filename, root_widget_name='main_dialog')
        view.widget_set_visible('noconnectionlabel', True)
        self.assertTrue(view.widget_get_visible('noconnectionlabel'))
        self.assertTrue(view.widgets.noconnectionlabel.get_visible())
        view.widget_set_visible('noconnectionlabel', False)
        self.assertFalse(view.widget_get_visible('noconnectionlabel'))
        self.assertFalse(view.widgets.noconnectionlabel.get_visible())
        view.get_window().destroy()


from dateutil.parser import parse as parse_date
import datetime
class TimeStampParserTests(TestCase):

    def test_date_parser_generic(self):
        import dateutil
        target = parse_date('2019-01-18 18:20 +0500')
        result = parse_date('18 January 2019 18:20 +0500')
        self.assertEqual(result, target)
        result = parse_date('18:20, 18 January 2019 +0500')
        self.assertEqual(result, target)
        result = parse_date('18:20+0500, 18 January 2019')
        self.assertEqual(result, target)
        result = parse_date('18:20+0500, 18 Jan 2019')
        self.assertEqual(result, target)
        result = parse_date('18:20+0500, 2019-01-18')
        self.assertEqual(result, target)
        result = parse_date('18:20+0500, 1/18 2019')
        self.assertEqual(result, target)
        result = parse_date('18:20+0500, 18/1 2019')
        self.assertEqual(result, target)

    def test_date_parser_ambiguous(self):
        ## defaults to European: day, month, year - FAILS
        #result = parse_date('5 1 4')
        #self.assertEquals(result, datetime.datetime(2004, 1, 5, 0, 0))
        # explicit, American: month, day, year
        result = parse_date('5 1 4', dayfirst=False, yearfirst=False)
        self.assertEqual(result, datetime.datetime(2004, 5, 1, 0, 0))
        # explicit, European: day, month, year
        result = parse_date('5 1 4', dayfirst=True, yearfirst=False)
        self.assertEqual(result, datetime.datetime(2004, 1, 5, 0, 0))
        # explicit, Japanese: year, month, day (month, day, year)
        result = parse_date('5 1 4', dayfirst=False, yearfirst=True)
        self.assertEqual(result, datetime.datetime(2005, 1, 4, 0, 0))
        ## explicit, illogical: year, day, month - FAILS
        #result = parse_date('5 1 4', dayfirst=True, yearfirst=True)
        #self.assertEquals(result, datetime.datetime(2005, 4, 1, 0, 0))

    def test_date_parser_365(self):
        target = datetime.datetime(2014, 1, 1, 20)
        result = parse_date('2014-01-01 20')
        self.assertEqual(result, target)
        target = parse_date('2014-01-01 20:00 +0000')
        result = parse_date('2014-01-01 20+0')
        self.assertEqual(result, target)


class MapMixinTests(BaubleTestCase):

    def setUp(self):
        super().setUp()
        with mock.patch('bauble.editor.PresenterMapMixin.init_map_menu'):
            self.mixin = PresenterMapMixin()
            self.mixin.refresh_sensitivity = mock.Mock()
            self.geojson = {'test': 'value'}
            self.mixin.model = mock.Mock(__tablename__='test',
                                         geojson=self.geojson)
            self.mixin.view = mock.Mock()

    def test_on_map_delete(self):
        self.assertEqual(self.mixin.model.geojson, self.geojson)
        self.mixin.on_map_delete()
        self.assertIsNone(self.mixin.model.geojson)
        self.mixin.refresh_sensitivity.assert_called()

    @mock.patch('bauble.gui')
    def test_on_map_copy(self, mock_gui):
        mock_clipboard = mock.Mock()
        mock_gui.get_display_clipboard.return_value = mock_clipboard
        self.mixin.on_map_copy()
        self.assertEqual(self.mixin.model.geojson, self.geojson)
        mock_clipboard.set_text.assert_called_with(json.dumps(self.geojson),
                                                   -1)

    @mock.patch('bauble.gui')
    def test_on_map_paste(self, mock_gui):
        mock_clipboard = mock.Mock()
        geojson = {'type': 'TEST', 'coordinates': "test"}
        mock_clipboard.wait_for_text.return_value = json.dumps(geojson)
        mock_gui.get_display_clipboard.return_value = mock_clipboard
        self.mixin.on_map_paste()
        self.assertEqual(self.mixin.model.geojson, geojson)

    @mock.patch('bauble.gui')
    def test_on_map_paste_invalid(self, mock_gui):
        mock_clipboard = mock.Mock()
        mock_clipboard.wait_for_text.return_value = "INVALID VALUE"
        mock_gui.get_display_clipboard.return_value = mock_clipboard
        self.mixin.on_map_paste()
        self.assertEqual(self.mixin.model.geojson, self.geojson)
        self.mixin.view.run_message_dialog.assert_called()

    @mock.patch('bauble.utils.desktop.open')
    def test_on_map_kml_show_produces_file(self, mock_open):
        template_str = "${value}"
        template = utils.get_temp_path()
        with template.open('w', encoding='utf-8') as f:
            f.write(template_str)
        self.mixin.kml_template = str(template)
        self.mixin.on_map_kml_show()
        with open(mock_open.call_args.args[0], encoding='utf-8') as f:
            self.assertEqual(str(self.mixin.model), f.read())
