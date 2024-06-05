# Copyright (c) 2005,2006,2007,2008,2009 Brett Adams <brett@belizebotanic.org>
# Copyright (c) 2012-2015 Mario Frasca <mario@anche.no>
# Copyright 2017 Jardín Botánico de Quito
# Copyright (c) 2022-2024 Ross Demuth <rossdemuth123@gmail.com>
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
from pathlib import Path
from unittest import TestCase
from unittest import mock

from gi.repository import Gtk

from bauble.plugins.garden import Location
from bauble.plugins.garden import Plant
from bauble.plugins.plants import Family
from bauble.plugins.plants import Geography
from bauble.plugins.plants.test_plants import setup_geographies
from bauble.test import BaubleTestCase
from bauble.test import get_setUp_data_funcs

from .. import options
from . import MakoFormatterPlugin
from . import MakoFormatterSettingsBox


class FormatterTests(BaubleTestCase):
    def setUp(self, *args):
        super().setUp(*args)
        for func in get_setUp_data_funcs():
            func()
        self.session.commit()

    @mock.patch("bauble.utils.desktop.open", new=mock.Mock())
    def test_format_all_csv_templates_locations(self):
        """MakoFormatterPlugin.format() runs without raising an error for all
        templates.
        """
        templates_dir = Path(__file__).parent / "templates"
        locations = self.session.query(Location).all()
        for template in templates_dir.glob("*.csv"):
            report = MakoFormatterPlugin.format(
                locations, template=str(template)
            )
            self.assertTrue(isinstance(report, bytes))

    @mock.patch("bauble.utils.desktop.open", new=mock.Mock())
    def test_format_all_csv_templates_families(self):
        """MakoFormatterPlugin.format() runs without raising an error for all
        templates.
        """
        templates_dir = Path(__file__).parent / "templates"
        families = self.session.query(Family).all()

        for template in templates_dir.glob("*.csv"):
            report = MakoFormatterPlugin.format(
                families, template=str(template)
            )
            self.assertTrue(isinstance(report, bytes))

    @mock.patch("bauble.utils.desktop.open", new=mock.Mock())
    def test_format_all_csv_templates_plants(self):
        """MakoFormatterPlugin.format() runs without raising an error for all
        templates.
        """
        templates_dir = Path(__file__).parent / "templates"
        plants = self.session.query(Plant).all()

        for template in templates_dir.glob("*.csv"):
            report = MakoFormatterPlugin.format(plants, template=str(template))
            self.assertTrue(isinstance(report, bytes))

    @mock.patch("bauble.utils.desktop.open", new=mock.Mock())
    def test_format_all_html_templates_locations(self):
        """MakoFormatterPlugin.format() runs without raising an error for all
        templates.
        """
        templates_dir = Path(__file__).parent / "templates"
        locations = self.session.query(Location).all()

        for template in templates_dir.glob("*.html"):
            report = MakoFormatterPlugin.format(
                locations, template=str(template)
            )
            self.assertTrue(isinstance(report, bytes))

    @mock.patch("bauble.utils.desktop.open", new=mock.Mock())
    def test_format_all_html_templates_families(self):
        """MakoFormatterPlugin.format() runs without raising an error for all
        templates.
        """
        templates_dir = Path(__file__).parent / "templates"
        families = self.session.query(Family).all()

        for template in templates_dir.glob("*.html"):
            report = MakoFormatterPlugin.format(
                families, template=str(template)
            )
            self.assertTrue(isinstance(report, bytes))

    @mock.patch("bauble.utils.desktop.open", new=mock.Mock())
    def test_format_all_html_templates_plants(self):
        """MakoFormatterPlugin.format() runs without raising an error for all
        templates.
        """
        templates_dir = Path(__file__).parent / "templates"
        plants = self.session.query(Plant).all()

        for template in templates_dir.glob("*.html"):
            report = MakoFormatterPlugin.format(plants, template=str(template))
            self.assertTrue(isinstance(report, bytes))

    @mock.patch("bauble.utils.desktop.open", new=mock.Mock())
    def test_format_all_geojson_templates_geography(self):
        """MakoFormatterPlugin.format() runs without raising an error for all
        templates.
        """
        setup_geographies()
        templates_dir = Path(__file__).parent / "templates"
        geos = self.session.query(Geography).all()

        for template in templates_dir.glob("*.geojson"):
            print(template)
            report = MakoFormatterPlugin.format(geos, template=str(template))
            self.assertTrue(isinstance(report, bytes))


class FormatterSettingsBoxTests(TestCase):
    def setUp(self):
        options.clear()

    def test_on_file_set_no_private_no_options(self):
        set_box = MakoFormatterSettingsBox()
        templates_dir = Path(__file__).parent / "templates"
        set_box.widgets.file_entry.set_text(
            str(templates_dir / "example_plant.csv")
        )
        self.assertFalse(set_box.widgets.private_check.get_visible())
        options_box = set_box.widgets.mako_options_box
        self.assertEqual(options_box.get_children(), [])

    def test_on_file_set_sets_use_private_visible(self):
        set_box = MakoFormatterSettingsBox()
        templates_dir = Path(__file__).parent / "templates"
        set_box.widgets.file_entry.set_text(str(templates_dir / "example.csv"))
        self.assertTrue(set_box.widgets.private_check.get_visible())

    def test_on_file_set_builds_options_widgets(self):
        set_box = MakoFormatterSettingsBox()
        templates_dir = Path(__file__).parent / "templates"
        set_box.widgets.file_entry.set_text(
            str(templates_dir / "example_species.csv")
        )
        self.assertFalse(set_box.widgets.private_check.get_visible())
        options_box = set_box.widgets.mako_options_box
        # label1
        self.assertEqual(
            options_box.get_child_at(0, 0).get_label(), "authors:"
        )
        # CheckButton
        self.assertTrue(options_box.get_child_at(1, 0).get_active())
        # label2
        self.assertEqual(
            options_box.get_child_at(0, 1).get_label(), "sort by:"
        )
        # CheckButton
        self.assertEqual(options_box.get_child_at(1, 1).get_text(), "None")

        self.assertEqual(options.get("authors"), True)
        self.assertEqual(options.get("sort_by"), "None")

    def test_set_option_then_reset_options(self):
        set_box = MakoFormatterSettingsBox()
        templates_dir = Path(__file__).parent / "templates"
        set_box.widgets.file_entry.set_text(
            str(templates_dir / "example_species.csv")
        )
        self.assertFalse(set_box.widgets.private_check.get_visible())
        options_box = set_box.widgets.mako_options_box
        # CheckButton
        options_box.get_child_at(1, 0).set_active(False)
        # entry
        options_box.get_child_at(1, 1).set_text("habit")

        self.assertEqual(options.get("authors"), False)
        self.assertEqual(options.get("sort_by"), "habit")
        set_box.reset_options(None)
        self.assertEqual(options.get("authors"), True)
        self.assertEqual(options.get("sort_by"), "None")

    def test_entry_set_option(self):
        set_box = MakoFormatterSettingsBox()
        widget = Gtk.Entry()
        widget.set_text("TEST")
        set_box.entry_set_option(widget, "test")

        self.assertEqual(options.get("test"), "TEST")

    def test_toggle_set_option(self):
        set_box = MakoFormatterSettingsBox()
        widget = Gtk.CheckButton()
        widget.set_active(True)
        set_box.toggle_set_option(widget, "test")

        self.assertEqual(options.get("test"), True)
        widget.set_active(False)
        set_box.toggle_set_option(widget, "test")
        self.assertEqual(options.get("test"), False)

    def test_combo_set_option(self):
        set_box = MakoFormatterSettingsBox()
        widget = Gtk.ComboBoxText()
        for i in range(4):
            widget.append_text(str(i))
        widget.set_active(1)
        set_box.combo_set_option(widget, "test_combo")

        self.assertEqual(options.get("test_combo"), "1")
        widget.set_active(3)
        set_box.combo_set_option(widget, "test_combo")
        self.assertEqual(options.get("test_combo"), "3")

    def test_get_option_widget_enum(self):
        set_box = MakoFormatterSettingsBox()
        widget = set_box.get_option_widget(
            "enum['test1','test2']", "test2", "test_enum"
        )
        self.assertIsInstance(widget, Gtk.ComboBoxText)
        self.assertEqual(widget.get_active_text(), "test2")

        self.assertEqual(options.get("test_enum"), "test2")
        widget.set_active(0)
        self.assertEqual(options.get("test_enum"), "test1")

    def test_get_option_widget_file(self):
        set_box = MakoFormatterSettingsBox()
        widget = set_box.get_option_widget("file", "test2", "test_filename")
        self.assertIsInstance(widget, Gtk.Box)
        entry, btn = widget.get_children()
        self.assertIsInstance(entry, Gtk.Entry)
        self.assertIsInstance(btn, Gtk.Button)
        self.assertEqual(entry.get_text(), "test2")

        self.assertEqual(options.get("test_filename"), "test2")

    @mock.patch("bauble.utils.Gtk.FileChooserNative")
    def test_on_option_btnbrowse_click(self, mock_fcn):
        # TODO see test_xsl test_on_btnbrowse_clicked_no_previous_entry etc.
        set_box = MakoFormatterSettingsBox()
        mock_fcn.new.return_value = mock_fcn
        mock_fcn.run.return_value = Gtk.ResponseType.ACCEPT
        filename = "/mock/filename.ext"
        mock_fcn.get_filename.return_value = filename
        entry = Gtk.Entry()
        set_box.on_option_btnbrowse_clicked(None, entry)
        mock_fcn.set_current_folder.assert_called_with(str(Path.home()))

        mock_fcn.new.assert_called_with(
            "Select a file", None, Gtk.FileChooserAction.OPEN
        )
        self.assertEqual(entry.get_text(), filename)
        set_box.on_option_btnbrowse_clicked(None, entry)
        mock_fcn.set_current_folder.assert_called_with(
            str(Path(filename).parent)
        )

    @mock.patch("bauble.utils.Gtk.FileChooserNative")
    def test_on_btnbrowse_click(self, mock_fcn):
        # TODO see test_xsl test_on_btnbrowse_clicked_no_previous_entry etc.
        set_box = MakoFormatterSettingsBox()
        mock_fcn.new.return_value = mock_fcn
        mock_fcn.run.return_value = Gtk.ResponseType.ACCEPT
        filename = "/mock/filename.ext"
        mock_fcn.get_filename.return_value = filename
        entry = set_box.widgets.file_entry
        set_box.on_btnbrowse_clicked(None)
        # reports plugin not initialised templates_dir is None and wond call
        mock_fcn.set_current_folder.assert_not_called()

        mock_fcn.new.assert_called_with(
            "Select a stylesheet", None, Gtk.FileChooserAction.OPEN
        )
        self.assertEqual(entry.get_text(), filename)
        set_box.on_btnbrowse_clicked(None)
        mock_fcn.set_current_folder.assert_called_with(
            str(Path(filename).parent)
        )

    def test_update_w_private(self):
        set_box = MakoFormatterSettingsBox()
        self.assertIsNone(options.get("private"))
        self.assertFalse(set_box.widgets.private_check.get_active())
        set_box.update({"private": True})
        self.assertTrue(set_box.widgets.private_check.get_active())
        self.assertTrue(options.get("private"))
        # reset - avoid pollution
        set_box.update({})

    @mock.patch("bauble.plugins.report.mako.Path.is_file")
    def test_update_w_template(self, mock_is_file):
        mock_is_file.return_value = True
        set_box = MakoFormatterSettingsBox()
        self.assertIsNone(options.get("template"))
        self.assertEqual(set_box.widgets.file_entry.get_text(), "")
        fname = "/test/file/name.html"
        set_box.update({"template": fname})
        self.assertEqual(options.get("template"), fname)
        self.assertEqual(set_box.widgets.file_entry.get_text(), fname)
        mock_is_file.assert_called()
        # reset - avoid pollution
        set_box.update({})

    @mock.patch("bauble.plugins.report.mako.Path.is_file")
    def test_update_w_template_not_file(self, mock_is_file):
        mock_is_file.return_value = False
        set_box = MakoFormatterSettingsBox()
        self.assertIsNone(options.get("template"))
        self.assertEqual(set_box.widgets.file_entry.get_text(), "")
        fname = "/test/file/name.html"
        set_box.update({"template": fname})
        self.assertIsNone(options.get("template"))
        self.assertEqual(set_box.widgets.file_entry.get_text(), fname)
        mock_is_file.assert_called()
        # reset - avoid pollution
        set_box.update({})

    def test_update_w_widget_val(self):
        set_box = MakoFormatterSettingsBox()
        widg = Gtk.Entry()
        set_box.defaults["twidg"] = (widg, "blah")
        settings = {"twidg": "test value"}
        set_box.update(settings)
        self.assertEqual(widg.get_text(), "test value")
        # reset - avoid pollution
        set_box.update({})

    def test_update_w_bad_widget_just_logs(self):
        set_box = MakoFormatterSettingsBox()
        widg = Gtk.Expander()
        set_box.defaults["twidg"] = (widg, "blah")
        settings = {"twidg": "test value"}
        with self.assertLogs(level="DEBUG") as logs:
            set_box.update(settings)
        self.assertTrue(
            any(
                "TypeError(utils.set_widget_value(): Don't know how to handle"
                in i
                for i in logs.output
            )
        )
        # reset - avoid pollution
        set_box.update({})

    def test_get_report_settings_returns_options(self):
        set_box = MakoFormatterSettingsBox()
        options["test"] = "this"
        self.assertEqual(set_box.get_report_settings(), options)

    def test_clear_options_box(self):
        set_box = MakoFormatterSettingsBox()
        label = Gtk.Label(label="test")
        set_box.widgets.mako_options_box.attach(label, 0, 0, 1, 1)
        options["test"] = "this"
        mock_dialog = mock.Mock(spec=Gtk.Dialog)
        set_box.get_toplevel = lambda: mock_dialog
        set_box.clear_options_box()
        self.assertEqual(options, {})
        self.assertEqual(
            len(set_box.widgets.mako_options_box.get_children()), 0
        )
        mock_dialog.resize.assert_called_with(1, 1)
