# Copyright 2008-2010 Brett Adams
# Copyright 2012-2016 Mario Frasca <mario@anche.no>.
# Copyright 2017 Jardín Botánico de Quito
# Copyright 2020-2024 Ross Demuth <rossdemuth123@gmail.com>
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
The Mako report generator module.
"""

import logging
import os
import tempfile
from ast import literal_eval
from pathlib import Path

logger = logging.getLogger(__name__)

from gi.repository import Gtk  # noqa
from mako.template import Template

from bauble import paths
from bauble import utils
from bauble.i18n import _

from .. import FormatterPlugin
from .. import SettingsBox
from .. import options


class MakoFormatterSettingsBox(SettingsBox):
    import re

    pattern = re.compile(
        r"^## OPTION ([a-z_]*): \("
        r"type: ([a-zN_',\[\]]*), "
        r"default: '(.*)', "
        r"tooltip: '(.*)'\)$"
    )

    def __init__(self, *args):
        super().__init__(*args)
        self.widgets = utils.load_widgets(
            os.path.join(
                paths.lib_dir(), "plugins", "report", "mako", "gui.glade"
            )
        )
        # keep a refefence to settings box so it doesn't get destroyed in
        # remove_parent()
        self.settings_box = self.widgets.settings_box
        self.widgets.remove_parent(self.widgets.settings_box)
        self.pack_start(self.settings_box, True, True, 0)
        self.widgets.file_btnbrowse.connect(
            "clicked", self.on_btnbrowse_clicked
        )
        self.widgets.file_entry.connect("changed", self.on_file_entry_changed)
        self.widgets.private_check.connect(
            "toggled", self.toggle_set_option, "private"
        )
        self.defaults = {}

    def on_btnbrowse_clicked(self, _widget):
        previously = self.widgets.file_entry.get_text()
        if previously:
            last_folder = str(Path(previously).parent)
        else:
            last_folder = paths.templates_dir()
        utils.run_file_chooser_dialog(
            _("Select a stylesheet"),
            None,
            Gtk.FileChooserAction.OPEN,
            last_folder,
            self.widgets.file_entry,
        )

    def on_file_entry_changed(self, widget):
        text = widget.get_text()
        self.clear_options_box()
        utils.hide_widgets([self.widgets.private_check])
        if Path(text).is_file():
            self.on_file_set(widget)
            widget.get_style_context().remove_class("problem")
            options["template"] = text
        else:
            widget.get_style_context().add_class("problem")

    def get_report_settings(self):
        return options

    def update(self, settings):
        if template := settings.get("template"):
            self.widgets.file_entry.set_text(template)
            self.widgets.file_entry.set_position(len(template))
            logger.debug("template = %s", template)
        else:
            self.widgets.file_entry.set_text("")
            self.clear_options_box()
        if "private" in settings:
            self.widgets.private_check.set_active(settings["private"])
            self.widgets.private_check.emit("toggled")

        for key, val in settings.items():
            if key in ("template", "private"):
                continue
            if widget_and_default_val := self.defaults.get(key):
                logger.debug(
                    "%s widget_and_default_val = %s",
                    key,
                    widget_and_default_val,
                )
                widget, __ = widget_and_default_val
                try:
                    utils.set_widget_value(widget, val)
                except TypeError as e:
                    logger.debug("%s(%s)", type(e).__name__, e)

    def on_file_set(self, widget):
        self.defaults.clear()
        # which options does the template accept? (can be None)
        options_box = self.widgets.mako_options_box
        try:
            with open(widget.get_text(), encoding="utf-8") as f:
                # scan the header filtering lines starting with # OPTION
                option_lines = [
                    _f
                    for _f in [
                        self.pattern.match(i.strip()) for i in f.readlines()
                    ]
                    if _f
                ]
        except IOError:
            option_lines = []

        option_fields = [i.groups() for i in option_lines]

        current_row = 0
        # populate the options box
        for fname, ftype, fdefault, ftooltip in option_fields:
            # use_private must be in the options to enable it but the other
            # values are ignored, it is accessed in the template as a regular
            # option
            if fname == "use_private":
                utils.unhide_widgets([self.widgets.private_check])
                continue
            label = Gtk.Label(label=fname.replace("_", " ") + _(":"))
            label.set_halign(Gtk.Align.END)
            label.set_margin_end(5)
            entry = self.get_option_widget(ftype, fdefault, fname)
            entry.set_tooltip_text(ftooltip)

            # account for file widget (box with entry and button)
            widget = entry.get_children()[0] if ftype == "file" else entry

            # entry updates the corresponding item in report.options
            self.defaults[fname] = (widget, fdefault)
            options_box.attach(label, 0, current_row, 1, 1)
            options_box.attach(entry, 1, current_row, 1, 1)
            current_row += 1
        if self.defaults:
            button = Gtk.Button(label=_("Reset to defaults"))
            button.connect("clicked", self.reset_options)
            options_box.attach(button, 1, current_row, 1, 1)
        options_box.show_all()

    def clear_options_box(self):
        options.clear()
        options_box = self.widgets.mako_options_box
        # empty the options box
        for widget in options_box.get_children():
            options_box.remove(widget)

        dialog = self.get_toplevel()
        if isinstance(dialog, Gtk.Dialog):
            dialog.resize(1, 1)

    def reset_options(self, _widget):
        for entry, text in self.defaults.values():
            if isinstance(entry, Gtk.CheckButton):
                entry.set_active(text.lower() in ["1", "true"])
            else:
                utils.set_widget_value(entry, text)

    @staticmethod
    def entry_set_option(widget, fname):
        options[fname] = widget.get_text()

    @staticmethod
    def toggle_set_option(widget, fname):
        options[fname] = widget.get_active()

    @staticmethod
    def combo_set_option(widget, fname):
        options[fname] = widget.get_active_text()

    @staticmethod
    def on_option_btnbrowse_clicked(_widget, entry):
        previously = entry.get_text()
        if previously:
            last_folder = str(Path(previously).parent)
        else:
            last_folder = str(Path.home())
        utils.run_file_chooser_dialog(
            _("Select a file"),
            None,
            Gtk.FileChooserAction.OPEN,
            last_folder,
            entry,
        )

    def get_option_widget(self, ftype, fdefault, fname):
        if ftype == "boolean":
            active = fdefault.lower() in ["1", "true"]
            options.setdefault(fname, active)
            entry = Gtk.CheckButton()
            entry.set_active(active)
            entry.connect("toggled", self.toggle_set_option, fname)
            return entry

        if ftype.startswith("enum"):
            combo = Gtk.ComboBoxText()
            vals = literal_eval(ftype.removeprefix("enum"))
            for val in vals:
                combo.append_text(val)
            combo.connect("changed", self.combo_set_option, fname)
            if fdefault:
                combo.set_active(vals.index(fdefault))
            options.setdefault(fname, fdefault)
            return combo

        if ftype == "file":
            box = Gtk.Box()
            image = Gtk.Image.new_from_icon_name(
                "document-open-symbolic", Gtk.IconSize.BUTTON
            )
            btn = Gtk.Button()
            btn.set_image(image)
            entry = Gtk.Entry()
            options.setdefault(fname, fdefault)
            entry.set_text(options[fname])
            entry.connect("changed", self.entry_set_option, fname)
            box.pack_start(entry, True, True, 0)
            box.pack_start(btn, True, True, 0)
            btn.connect("clicked", self.on_option_btnbrowse_clicked, entry)
            return box

        entry = Gtk.Entry()
        options.setdefault(fname, fdefault)
        entry.set_text(options[fname])
        entry.connect("changed", self.entry_set_option, fname)
        return entry


_settings_box = MakoFormatterSettingsBox()


class MakoFormatterPlugin(FormatterPlugin):
    """The MakoFormatterPlugin passes the values in the search results
    directly to a Mako template.

    It is up to the template author to validate the type of the values and act
    accordingly if not.
    """

    title = "Mako"

    @classmethod
    def install(cls, import_defaults=True):
        logger.debug("installing mako plugin")

    @classmethod
    def init(cls):
        """copy default template files to appdata_dir

        we do this in the initialization instead of installation
        because new version of plugin might provide new templates.
        """
        cls.install()  # plugins still not versioned...

        src_dir = os.path.join(
            paths.lib_dir(), "plugins", "report", "mako", "templates"
        )

        # If user has selected a directory to store templates add the examples
        # to it otherwise use appdata
        templates_root = Path(paths.templates_dir(), "ghini_examples", "mako")

        utils.copy_tree(
            src_dir, templates_root, (".csv", ".html", ".svg", ".ps")
        )

    @staticmethod
    def get_settings_box():
        return _settings_box

    @staticmethod
    def format(objs, **kwargs):
        template_filename = kwargs.get("template")
        if not template_filename:
            msg = _("Please select a template.")
            utils.message_dialog(msg, Gtk.MessageType.WARNING)
            return False
        template = Template(
            filename=template_filename,
            input_encoding="utf-8",
            output_encoding="utf-8",
        )

        report = template.render(values=objs)
        # assume the template is the same file type as the output file
        _head, ext = os.path.splitext(template_filename)
        file_handle, filename = tempfile.mkstemp(suffix=ext)
        os.write(file_handle, report)
        os.close(file_handle)
        try:
            utils.desktop.open(filename)
        except OSError:
            utils.message_dialog(
                _(
                    "Could not open the report with the "
                    "default program. You can open the "
                    "file manually at %s"
                )
                % filename
            )
        return report


formatter_plugin = MakoFormatterPlugin
