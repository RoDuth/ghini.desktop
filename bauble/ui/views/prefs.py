# Copyright 2008-2010 Brett Adams
# Copyright 2015 Mario Frasca <mario@anche.no>.
# Copyright 2021-2026 Ross Demuth <rossdemuth123@gmail.com>
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
Preferences UI parts and command handler
"""

import logging

logger = logging.getLogger(__name__)

from ast import literal_eval
from configparser import ConfigParser
from pathlib import Path
from shutil import copy2
from typing import cast

from gi.repository import Gdk
from gi.repository import Gio
from gi.repository import Gtk

import bauble
from bauble import db
from bauble import pluginmgr
from bauble import prefs
from bauble.i18n import _
from bauble.ui import dialogs

from .base import View

parent = Path(__file__).resolve().parent


def _remove_empty_config_sections(config: ConfigParser) -> None:
    """Remove sections that no longer store any options.

    Mutates the supplied ConfigParser object in place."""
    to_remove = []
    for section in config.sections():
        if not config.items(section):
            to_remove.append(section)

    logger.debug("removing section %s", to_remove)

    for section in to_remove:
        config.remove_section(section)


@Gtk.Template(filename=str(parent / "prefs_reset_dialog.ui"))
class PrefsResetDialog(Gtk.Dialog):
    __gtype_name__ = "PrefsResetDialog"

    # convince pylint liststore is iterable
    liststore = Gtk.ListStore(str, bool)
    liststore = cast(Gtk.ListStore, Gtk.Template.Child())
    treeview = cast(Gtk.TreeView, Gtk.Template.Child())

    def __init__(self, config: ConfigParser) -> None:
        logger.debug("PrefsView::__init__")
        super().__init__()
        self.config = config

        self.init_context_menu()

        for section in self.config.sections():
            for option in self.config[section]:

                self.liststore.append([f"{section}.{option}", True])

        self.treeview.connect("button-press-event", self.on_button_press_event)

    def get_config(self) -> ConfigParser:
        line: str
        val: bool
        for line, val in self.liststore:  # type: ignore
            if val is False:
                section, option = line.rsplit(".", 1)
                self.config.remove_option(section, option)

        _remove_empty_config_sections(self.config)

        return self.config

    def on_button_press_event(self, _widget, event: Gdk.EventButton) -> None:
        logger.debug("event.button %s", event.button)
        if event.button == 3:
            self.context_menu.popup_at_pointer(event)

    def init_context_menu(self) -> None:
        action_group_name = "prefs_reset"
        action_group = Gio.SimpleActionGroup()
        menu_model = Gio.Menu()

        section_action = Gio.SimpleAction.new("toggle_section", None)
        section_action.connect("activate", self.on_toggle_section)
        action_group.add_action(section_action)
        section_item = Gio.MenuItem.new(
            _("Toggle section"),
            f"{action_group_name}.toggle_section",
        )
        menu_model.append_item(section_item)

        all_action = Gio.SimpleAction.new("toggle_all", None)
        all_action.connect("activate", self.on_toggle_all)
        action_group.add_action(all_action)
        all_item = Gio.MenuItem.new(
            _("Toggle all"),
            f"{action_group_name}.toggle_all",
        )
        menu_model.append_item(all_item)

        self.context_menu = Gtk.Menu.new_from_model(menu_model)
        self.context_menu.attach_to_widget(self.treeview)
        self.treeview.insert_action_group(action_group_name, action_group)

    def on_toggle_section(
        self, _action: Gio.SimpleAction, _param: None
    ) -> None:
        selection = self.treeview.get_selection()
        model, tree_path = selection.get_selected()

        if not tree_path:
            return

        full_name = model[tree_path][0]
        section, _option = full_name.rsplit(".", 1)

        line: str
        val: bool
        for path, (line, val) in enumerate(self.liststore):  # type: ignore
            if line.startswith(section):
                self.liststore[path][1] = not val

    def on_toggle_all(self, _action: Gio.SimpleAction, _param: None) -> None:
        _line: str
        val: bool
        for path, (_line, val) in enumerate(self.liststore):  # type: ignore
            self.liststore[path][1] = not val

    @Gtk.Template.Callback()
    def on_include_toggled(
        self,
        cell: Gtk.CellRendererToggle,
        path: Gtk.TreePath,
    ) -> None:
        self.liststore[path][1] = not cell.get_active()


@Gtk.Template(filename=str(parent / "prefs_view.ui"))
class PrefsView(View, Gtk.Box):
    """The PrefsView displays the values in the plugin registry and displays
    and allows limited editing of preferences, only after warning users of
    possible dangers.
    """

    __gtype_name__ = "PrefsView"

    prefs_ls = cast(Gtk.ListStore, Gtk.Template.Child())
    plugins_ls = cast(Gtk.ListStore, Gtk.Template.Child())
    prefs_tv = cast(Gtk.TreeView, Gtk.Template.Child())
    prefs_data_renderer = cast(Gtk.CellRendererText, Gtk.Template.Child())
    menu_button = cast(Gtk.MenuButton, Gtk.Template.Child())

    def __init__(self) -> None:
        logger.debug("PrefsView::__init__")
        super().__init__()
        self.init_context_menu()
        self.init_menu_button()
        self.button_press_sid: None | int = None

    def init_menu_button(self) -> None:
        action_group_name = "prefs_button"
        action_group = Gio.SimpleActionGroup()
        menu_model = Gio.Menu()

        menu_items = (
            (_("Backup"), "backup", self.on_prefs_backup_clicked),
            (_("Restore"), "restore", self.on_prefs_restore_clicked),
            (_("Reset defaults"), "defaults", self.on_prefs_reset_clicked),
            (_("Create share file"), "create", self.on_create_share_clicked),
            (_("Update from file"), "update", self.on_update_share_clicked),
        )
        for label, name, handler in menu_items:
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", handler)
            action_group.add_action(action)
            menu_item = Gio.MenuItem.new(label, f"{action_group_name}.{name}")
            menu_model.append_item(menu_item)

        self.menu_button.set_menu_model(menu_model)
        self.menu_button.insert_action_group(action_group_name, action_group)

    def init_context_menu(self) -> None:
        action_group_name = "prefs_view"
        action_group = Gio.SimpleActionGroup()
        action = Gio.SimpleAction.new("insert", None)
        action.connect("activate", self.on_prefs_insert_activate)
        action_group.add_action(action)
        item = Gio.MenuItem.new(_("_Insert"), f"{action_group_name}.insert")
        menu_model = Gio.Menu()
        menu_model.append_item(item)
        self.context_menu = Gtk.Menu.new_from_model(menu_model)
        self.context_menu.attach_to_widget(self.prefs_tv)
        self.prefs_tv.insert_action_group(action_group_name, action_group)

    def on_button_press_event(self, _widget, event: Gdk.EventButton) -> None:
        logger.debug("event.button %s", event.button)
        if event.button == 3:
            self.context_menu.popup_at_pointer(event)

    def on_prefs_insert_activate(self, _action, _param) -> None:
        selection = self.prefs_tv.get_selection()
        model, tree_paths = selection.get_selected_rows()
        logger.debug("model: %s tree_paths: %s", model, tree_paths)

        self.add_new(cast(Gtk.ListStore, model), tree_paths)

    @staticmethod
    def add_new(
        model: Gtk.ListStore,
        tree_paths: list[Gtk.TreePath],
        text: str | None = None,
    ) -> Gtk.TreeIter | None:
        msg = _("New option name")
        selected = [model[row][0] for row in tree_paths][0]
        section = selected.rsplit(".", 1)[0]
        logger.debug("start a dialog for new section %s", section)
        dialog = dialogs.create_message_dialog(msg=msg)
        message_area = cast(Gtk.Box, dialog.get_message_area())
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        option_entry = Gtk.Entry()

        if not text:
            text = f"{section}."

        option_entry.set_text(text)
        box.add(option_entry)
        message_area.add(box)
        dialog.resize(1, 1)
        dialog.show_all()
        new_iter = None

        if dialog.run() == Gtk.ResponseType.OK:
            tree_iter = model.get_iter(tree_paths[0])
            option = option_entry.get_text()
            new_iter = model.insert_after(tree_iter, row=[option, "", None])
            logger.debug("adding new pref option %s", option)

        dialog.destroy()
        return new_iter

    @Gtk.Template.Callback()
    def on_prefs_edit_toggled(self, check_button: Gtk.CheckButton) -> None:
        state = check_button.get_active()
        logger.debug("edit state %s", state)
        msg = _(
            "\n\n<b>CAUTION! Making incorrect changes to your preferences "
            "could be detrimental.\n\nDO YOU WISH TO PROCEED?</b>\n\nSome "
            "changes will not take effect until restarted."
        )
        parent = bauble.gui.window if bauble.gui else None
        if state and dialogs.yes_no_dialog(msg, parent=parent):
            logger.debug("enable editing prefs")
            self.prefs_data_renderer.set_property("editable", state)
            self.button_press_sid = self.prefs_tv.connect(
                "button-press-event", self.on_button_press_event
            )

        else:
            logger.debug("disable editing prefs")
            check_button.set_active(False)
            self.prefs_data_renderer.set_property("editable", False)
            if self.button_press_sid:
                self.prefs_tv.disconnect(self.button_press_sid)
                self.button_press_sid = None

    @Gtk.Template.Callback()
    def on_prefs_edited(
        self,
        _renderer: Gtk.CellRendererText,
        path: str,
        new_text: str,
    ) -> None:
        # pylint: disable=unsubscriptable-object
        key: str
        repr_str: str
        type_str: str
        key, repr_str, type_str = self.prefs_ls[path]  # type: ignore [misc]
        if new_text == "":
            msg = _("Delete the %s preference key?") % key
            parent = bauble.gui.window if bauble.gui else None
            if dialogs.yes_no_dialog(msg, parent=parent):
                del prefs.prefs[key]
                prefs.prefs.save()
                self.refresh_view()
                logger.debug("deleting: %s", key)
                self.prefs_ls.remove(
                    self.prefs_ls.get_iter_from_string(str(path))
                )
                return

        try:
            new_val = literal_eval(new_text)
        except (ValueError, SyntaxError):
            new_val = new_text

        if isinstance(new_val, str):
            if key.endswith("root_directory") and not Path(new_val).exists():
                new_val = ""

        new_val_type = type(new_val).__name__

        if type_str and (new_val == "" or new_val_type != type_str):
            self.prefs_ls[path][1] = repr_str
            return

        prefs.prefs[key] = new_val
        self.prefs_ls[path][1] = str(new_val)
        self.prefs_ls[path][2] = new_val_type
        prefs.prefs.save()
        self.refresh_view()

    @staticmethod
    def on_prefs_backup_clicked(
        _action: Gio.SimpleAction,
        _param: None,
    ) -> None:
        copy2(prefs.default_prefs_file, prefs.default_prefs_file + "BAK")

    def on_prefs_restore_clicked(
        self,
        _action: Gio.SimpleAction,
        _param: None,
    ) -> None:
        if Path(prefs.default_prefs_file + "BAK").exists():
            copy2(prefs.default_prefs_file + "BAK", prefs.default_prefs_file)
            prefs.prefs.reload()
            self.update()
        else:
            dialogs.message_dialog(_("No backup found"))

    @staticmethod
    def get_user_filtered(config: ConfigParser) -> ConfigParser:
        dialog = PrefsResetDialog(config)

        if dialog.run() == Gtk.ResponseType.OK:
            config = dialog.get_config()
        else:
            config = ConfigParser(interpolation=None)

        dialog.destroy()

        return config

    @staticmethod
    def remove_already_equal(config: ConfigParser) -> None:
        """Removes any parts that are already in prefs."""
        # remove _extend and already equal.
        to_remove = []
        for section in config.sections():
            for option in config[section]:
                if option == "_extend":
                    to_remove.append((section, option))

                elif config.get(section, option) == prefs.prefs.config.get(
                    section, option, fallback=None
                ):
                    to_remove.append((section, option))

        logger.debug("removing %s", to_remove)
        for section, option in to_remove:
            config.remove_option(section, option)

        _remove_empty_config_sections(config)

    def apply_changes(self, config: ConfigParser) -> None:

        for section in config.sections():
            for option in config[section]:
                logger.debug("Applying change to pref %s.%s", section, option)
                prefs.prefs[f"{section}.{option}"] = config.get(
                    section, option
                )

        self.update()

    def on_prefs_reset_clicked(
        self,
        _action: Gio.SimpleAction,
        _param: None,
    ) -> None:
        config_paths = pluginmgr.get_config_files(pluginmgr.plugins.values())

        config = ConfigParser(interpolation=None)
        config.read(config_paths)

        self.remove_already_equal(config)

        config = self.get_user_filtered(config)

        self.apply_changes(config)

    def on_create_share_clicked(
        self,
        _action: Gio.SimpleAction,
        _param: None,
    ) -> None:

        config = ConfigParser(interpolation=None)
        config.read(prefs.prefs._filename)  # pylint: disable=protected-access

        config = self.get_user_filtered(config)

        if not config.sections():
            return

        chooser = Gtk.FileChooserNative.new(
            _("Save to file"),
            None,
            Gtk.FileChooserAction.SAVE,
        )
        # pylint: disable=no-value-for-parameter
        filter_ = Gtk.FileFilter.new()
        filter_.add_pattern("*.cfg")
        chooser.add_filter(filter_)
        chooser.set_current_folder(str(Path.home()))

        filename = None
        if chooser.run() == Gtk.ResponseType.ACCEPT:
            filename = chooser.get_filename()
            logger.debug("saving to %s", filename)

        chooser.destroy()

        if not filename:
            return

        with open(filename, "w+", encoding="utf-8") as f:
            config.write(f)

    def on_update_share_clicked(
        self,
        _action: Gio.SimpleAction,
        _param: None,
    ) -> None:
        chooser = Gtk.FileChooserNative.new(
            _("Load file"),
            None,
            Gtk.FileChooserAction.OPEN,
        )
        # pylint: disable=no-value-for-parameter
        filter_ = Gtk.FileFilter.new()
        filter_.add_pattern("*.cfg")
        chooser.add_filter(filter_)
        chooser.set_current_folder(str(Path.home()))

        filename = None
        if chooser.run() == Gtk.ResponseType.ACCEPT:
            filename = chooser.get_filename()

        chooser.destroy()

        if not filename:
            return

        config = ConfigParser(interpolation=None)
        config.read(filename)

        self.remove_already_equal(config)

        config = self.get_user_filtered(config)

        self.apply_changes(config)

    def update(self, *_args) -> None:
        self.prefs_ls.clear()
        for key, value in sorted(prefs.prefs.iteritems()):
            logger.debug(
                "update prefs: %s, %s, %s",
                key,
                value,
                prefs.prefs[key].__class__.__name__,
            )
            self.prefs_ls.append(
                (key, value, prefs.prefs[key].__class__.__name__)
            )

        self.plugins_ls.clear()

        with db.Session() as session:
            plugins = session.query(
                pluginmgr.PluginRegistry.name,
                pluginmgr.PluginRegistry.version,
            )

            for item in plugins:
                self.plugins_ls.append(item)

        self.refresh_view()

    @staticmethod
    def refresh_view() -> None:
        if bauble.gui is not None:
            # may be more to do here yet...
            bauble.gui.populate_main_entry()


class PrefsCommandHandler(pluginmgr.CommandHandler):
    command = ("prefs", "config")
    view: PrefsView | None = None

    @classmethod
    def get_view(cls) -> PrefsView:
        if cls.view is None:
            cls.view = PrefsView()
        return cls.view

    def __call__(self, cmd: str, arg: str | None) -> None:
        self.get_view().update()


pluginmgr.register_command(PrefsCommandHandler)
