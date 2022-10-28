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
import tempfile
from shutil import copy2

from gi.repository import Gtk

from bauble.editor import (GenericEditorView,
                           NoteBox,
                           PictureBox,
                           PresenterMapMixin)
from bauble import paths
from bauble import utils
from bauble import search
from bauble import prefs

from bauble.test import BaubleTestCase, get_setUp_data_funcs


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


class NoteBoxTests(BaubleTestCase):

    def setUp(self):
        super().setUp()
        # get the first note class
        for klass in search.MapperSearch.get_domain_classes().values():
            if hasattr(klass, 'notes') and hasattr(klass.notes, 'mapper'):
                note_cls = klass.notes.mapper.class_
                self.model = note_cls()
                self.session.add(self.model)
                break

    def test_note_box_set_contents_sets_widget(self):
        presenter = mock.Mock(model=self.model)
        box = NoteBox(presenter, self.model)
        self.assertTrue(box)
        # test set_contents set widget value.
        test_str = 'test string'
        box.set_content(test_str)
        self.assertEqual(utils.get_widget_value(box.note_textview), test_str)

    def test_note_box_set_widget_set_model(self):
        presenter = mock.Mock(model=self.model)
        box = NoteBox(presenter, self.model)
        self.assertTrue(box)
        # test set widget sets model value
        test_str = 'test string'
        utils.set_widget_value(box.note_textview, test_str)
        self.assertEqual(self.model.note, test_str)

    def test_note_box_on_notes_remove_button_removes_note(self):
        presenter = mock.Mock(model=self.model, notes=[self.model])
        box = NoteBox(presenter, self.model)
        self.assertIn(self.model, presenter.notes)
        box.on_notes_remove_button(None)
        self.assertNotIn(self.model, presenter.notes)

    def test_note_box_on_date_entry_changed_sets_attr(self):
        presenter = mock.Mock(model=self.model, notes=[self.model])
        box = NoteBox(presenter, self.model)
        self.assertIsNone(self.model.date)
        date = '25/10/2022'
        box.date_entry.set_text(date)
        self.assertEqual(self.model.date, date)

    def test_note_box_on_user_entry_changed_sets_attr(self):
        presenter = mock.Mock(model=self.model, notes=[self.model])
        box = NoteBox(presenter, self.model)
        self.assertIsNone(self.model.date)
        user = 'Test User'
        box.user_entry.set_text(user)
        self.assertEqual(self.model.user, user)

    def test_note_box_on_category_combo_changed_sets_attr(self):
        presenter = mock.Mock(model=self.model, notes=[self.model])
        box = NoteBox(presenter, self.model)
        self.assertIsNone(self.model.date)
        cat = 'Test Category'
        utils.set_widget_value(box.category_comboentry, cat)
        self.assertEqual(self.model.category, cat)


class PictureBoxTests(BaubleTestCase):

    def setUp(self):
        super().setUp()
        # get the first picture class
        for klass in search.MapperSearch.get_domain_classes().values():
            if hasattr(klass, 'pictures') and hasattr(klass.pictures, 'mapper'):
                self.parent_model = klass()
                note_cls = klass.pictures.mapper.class_
                self.model = note_cls()
                self.parent_model.pictures.append(self.model)
                self.session.add(self.model)
                break

    @mock.patch('bauble.utils.ImageLoader')
    def test_picture_box_set_contents_calls_imageloader_for_url(self,
                                                                mockloader):
        presenter = mock.Mock(model=self.model)
        box = PictureBox(presenter, self.model)
        self.assertTrue(box)
        # sets widgets
        test_str = 'http://test.org'
        box.set_content(test_str)
        self.assertEqual(utils.get_widget_value(box.file_entry),
                         test_str)
        self.assertIsInstance(box.picture_box.get_children()[0],
                              Gtk.Box)
        mockloader.assert_called()

    def test_picture_box_set_contents_adds_label_for_none_existing(self):
        presenter = mock.Mock(model=self.model)
        box = PictureBox(presenter, self.model)
        self.assertTrue(box)
        # sets widgets none existing image
        test_str = 'test.jpg'
        box.set_content(test_str)
        self.assertEqual(utils.get_widget_value(box.file_entry),
                         test_str)
        self.assertIsInstance(box.picture_box.get_children()[0],
                              Gtk.Label)
        self.assertIn(test_str,
                      box.picture_box.get_children()[0].get_text())

    def test_picture_box_set_contents_adds_pixbuff_for_existing(self):
        prefs.prefs[prefs.picture_root_pref] = os.path.join(paths.lib_dir(),
                                                            'images')
        presenter = mock.Mock(model=self.model)
        box = PictureBox(presenter, self.model)
        self.assertTrue(box)
        # sets widgets none existing image
        test_str = 'dmg_background.png'
        box.set_content(test_str)
        self.assertEqual(utils.get_widget_value(box.file_entry),
                         test_str)
        self.assertIsInstance(box.picture_box.get_children()[0],
                              Gtk.Image)

    def test_picture_box_set_contents_adds_label_for_none(self):
        presenter = mock.Mock(model=self.model)
        box = PictureBox(presenter, self.model)
        self.assertTrue(box)
        # sets widgets none existing image
        box.set_content(None)
        self.assertEqual(utils.get_widget_value(box.file_entry), '')
        self.assertIsInstance(box.picture_box.get_children()[0],
                              Gtk.Label)
        self.assertIn('Choose a file',
                      box.picture_box.get_children()[0].get_text())

    @mock.patch('bauble.utils.yes_no_dialog',
                return_value=Gtk.ResponseType.YES)
    def test_picture_box_on_notes_remove_button_removes_image(self, mock_dlog):
        temp = tempfile.mkdtemp()
        prefs.prefs[prefs.picture_root_pref] = temp
        img_name = 'dmg_background.png'
        img_full_path = os.path.join(paths.lib_dir(), 'images', img_name)
        copy2(img_full_path, temp)

        self.model.picture = img_name

        mock_parent = mock.Mock(view=None)
        presenter = mock.Mock(model=self.model, notes=[self.model],
                              **{'parent_ref.return_value': mock_parent})
        box = PictureBox(presenter, self.model)
        self.assertTrue(os.path.isfile(os.path.join(temp, img_name)))
        box.on_notes_remove_button(None)
        self.assertFalse(os.path.isfile(os.path.join(temp, img_name)))
        msg = mock_dlog.call_args.args[0]
        self.assertNotIn('the same file', msg)

    @mock.patch('bauble.utils.yes_no_dialog',
                return_value=Gtk.ResponseType.YES)
    def test_picture_box_remove_others_same_type_warns(self, mock_dlog):
        for func in get_setUp_data_funcs():
            func()
        temp = tempfile.mkdtemp()
        prefs.prefs[prefs.picture_root_pref] = temp
        img_name = 'dmg_background.png'
        img_full_path = os.path.join(paths.lib_dir(), 'images', img_name)
        copy2(img_full_path, temp)

        # create fake data and add a second model of different type with same
        # img.  Commit the lot.
        self.model.picture = img_name
        for col in self.parent_model.__table__.columns:
            if not col.nullable:
                if col.name.endswith('_id'):
                    setattr(self.parent_model, col.name, 1)
                if not getattr(self.parent_model, col.name):
                    setattr(self.parent_model, col.name, '123')

        note_cls = type(self.model)
        parent_model = type(self.parent_model)()
        model2 = note_cls(picture=img_name)
        parent_model.pictures.append(model2)
        self.session.add(model2)

        for col in parent_model.__table__.columns:
            if not col.nullable:
                if col.name.endswith('_id'):
                    setattr(parent_model, col.name, 1)
                if not getattr(parent_model, col.name):
                    setattr(parent_model, col.name, '345')

        self.session.commit()

        self.assertIs(type(self.model), type(model2))

        mock_parent = mock.Mock(view=None)
        presenter = mock.Mock(model=self.model, notes=[self.model, model2],
                              **{'parent_ref.return_value': mock_parent})
        box = PictureBox(presenter, self.model)
        self.assertTrue(os.path.isfile(os.path.join(temp, img_name)))
        box.on_notes_remove_button(None)
        self.assertFalse(os.path.isfile(os.path.join(temp, img_name)))
        msg = mock_dlog.call_args.args[0]
        self.assertIn('1 other', msg)
        self.assertIn(f'of type {note_cls.__tablename__}', msg)

    @mock.patch('bauble.utils.yes_no_dialog',
                return_value=Gtk.ResponseType.YES)
    def test_picture_box_remove_others_dif_types_warns(self, mock_dlog):
        for func in get_setUp_data_funcs():
            func()
        temp = tempfile.mkdtemp()
        prefs.prefs[prefs.picture_root_pref] = temp
        img_name = 'dmg_background.png'
        img_full_path = os.path.join(paths.lib_dir(), 'images', img_name)
        copy2(img_full_path, temp)

        # create fake data and add a second model of different type with same
        # img.  Commit the lot.
        self.model.picture = img_name
        for col in self.parent_model.__table__.columns:
            if not col.nullable:
                if col.name.endswith('_id'):
                    setattr(self.parent_model, col.name, 1)
                if not getattr(self.parent_model, col.name):
                    setattr(self.parent_model, col.name, '456')

        count = 0
        for klass in search.MapperSearch.get_domain_classes().values():
            if (hasattr(klass, 'pictures') and
                    hasattr(klass.pictures, 'mapper')):
                count += 1
                if count == 2:
                    note_cls = klass.pictures.mapper.class_
                    parent_model = klass()
                    model2 = note_cls(picture=img_name)
                    parent_model.pictures.append(model2)
                    self.session.add(model2)
                    break

        for col in parent_model.__table__.columns:
            if not col.nullable:
                if col.name.endswith('_id'):
                    setattr(parent_model, col.name, 1)
                if not getattr(parent_model, col.name):
                    setattr(parent_model, col.name, '567')

        self.session.commit()

        self.assertIsNot(type(self.model), type(model2))

        mock_parent = mock.Mock(view=None)
        presenter = mock.Mock(model=self.model, notes=[self.model, model2],
                              **{'parent_ref.return_value': mock_parent})
        box = PictureBox(presenter, self.model)
        self.assertTrue(os.path.isfile(os.path.join(temp, img_name)))
        box.on_notes_remove_button(None)
        self.assertFalse(os.path.isfile(os.path.join(temp, img_name)))
        msg = mock_dlog.call_args.args[0]
        self.assertIn('1 other', msg)
        self.assertIn(f'of type {note_cls.__tablename__}', msg)

    @mock.patch('bauble.utils.Gtk.FileChooserNative')
    def test_picture_box_on_file_btnbrowse_clicked_copies_file(
        self, mock_filechooser
    ):
        temp = tempfile.mkdtemp()
        prefs.prefs[prefs.picture_root_pref] = temp
        os.mkdir(os.path.join(temp, 'thumbs'))
        img_name = 'dmg_background.png'
        img_full_path = os.path.join(paths.lib_dir(), 'images', img_name)
        mock_filechooser.return_value.get_filename.return_value = img_full_path
        presenter = mock.Mock(model=self.model, notes=[self.model])
        box = PictureBox(presenter, self.model)
        box.on_file_btnbrowse_clicked(None)
        self.assertTrue(os.path.isfile(os.path.join(temp, img_name)))
        self.assertTrue(os.path.isfile(os.path.join(temp, 'thumbs', img_name)))


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
