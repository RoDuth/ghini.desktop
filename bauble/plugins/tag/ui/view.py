# Copyright (c) 2005,2006,2007,2008,2009 Brett Adams <brett@belizebotanic.org>
# Copyright (c) 2012-2017 Mario Frasca <mario@anche.no>
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
Tag SearchView parts
"""
import os
from typing import Callable

from gi.repository import Gtk

import bauble
from bauble import paths
from bauble import utils
from bauble.i18n import _
from bauble.view import InfoBox
from bauble.view import InfoExpander
from bauble.view import PropertiesExpander


class GeneralTagExpander(InfoExpander):
    """Generic information about a tag.  Displays the tag name, description and
    a table of the types and count(with link) of tagged items.
    """

    def __init__(self, widgets):
        super().__init__(_("General"), widgets)
        general_box = self.widgets.general_box
        self.widgets.general_window.remove(general_box)
        self.vbox.pack_start(general_box, True, True, 0)
        self.table_cells = []

    def update(self, row):
        self.widget_set_value("ib_name_label", row.tag)
        self.widget_set_value("ib_description_label", row.description)
        objects = row.objects
        classes = set(type(o) for o in objects)
        row_no = 1
        grid = self.widgets.tag_ib_general_grid

        for widget in self.table_cells:
            grid.remove(widget)

        self.table_cells = []
        for cls in classes:
            obj_ids = [str(o.id) for o in objects if isinstance(o, cls)]
            lab = Gtk.Label()
            lab.set_xalign(0)
            lab.set_yalign(0.5)
            lab.set_text(cls.__name__)
            grid.attach(lab, 0, row_no, 1, 1)

            eventbox = Gtk.EventBox()
            label = Gtk.Label()
            label.set_xalign(0)
            label.set_yalign(0.5)
            eventbox.add(label)
            grid.attach(eventbox, 1, row_no, 1, 1)
            label.set_text(f" {len(obj_ids)} ")
            utils.make_label_clickable(
                label,
                lambda _l, _e, x: bauble.gui.send_command(x),
                f'{cls.__name__.lower()} where id in {", ".join(obj_ids)}',
            )

            self.table_cells.append(lab)
            self.table_cells.append(eventbox)

            row_no += 1
        grid.show_all()


class TagInfoBox(InfoBox):
    """
    - general info
    - source
    """

    def __init__(self):
        super().__init__()
        filename = os.path.join(paths.lib_dir(), "plugins", "tag", "tag.glade")
        self.widgets = utils.load_widgets(filename)
        self.general = GeneralTagExpander(self.widgets)
        self.add_expander(self.general)
        self.props = PropertiesExpander()
        self.add_expander(self.props)

    def update(self, row):
        self.general.update(row)
        self.props.update(row)


def on_tag_bottom_info_activated(
    tree: Gtk.TreeView,
    path: Gtk.TreePath,
    _column,
    *,
    send_command: Callable[[str], None] | None = None,
) -> None:
    model = tree.get_model()
    send_command = send_command or bauble.gui.send_command
    if model:
        tag = repr(model[path][0])
        send_command(f"tag={tag}")
