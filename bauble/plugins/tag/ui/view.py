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
import logging

logger = logging.getLogger(__name__)

from pathlib import Path
from typing import Callable
from typing import cast

from gi.repository import Gtk

import bauble
from bauble import db
from bauble import utils
from bauble.i18n import _
from bauble.view import InfoBox
from bauble.view import PropertiesExpander

from ..model import Tag


@Gtk.Template(filename=str(Path(__file__).resolve().parent / "info_box.ui"))
class GeneralTagExpander(Gtk.Expander):
    """Generic information about a tag.  Displays the tag name, description and
    a table of the types and count(with link) of tagged items.
    """

    __gtype_name__ = "GeneralTagExpander"

    general_box = cast(Gtk.Box, Gtk.Template.Child())
    name_label = cast(Gtk.Label, Gtk.Template.Child())
    description_label = cast(Gtk.Label, Gtk.Template.Child())
    grid = cast(Gtk.Grid, Gtk.Template.Child())

    def __init__(self):
        super().__init__(label=_("General"), expanded=True)
        self.table_cells = []

    def update(self, row):
        self.name_label.set_text(row.tag)
        self.description_label.set_text(row.description or "")
        objects = row.objects
        classes = set(type(o) for o in objects)
        row_no = 1

        for widget in self.table_cells:
            self.grid.remove(widget)

        self.table_cells = []
        for cls in classes:
            obj_ids = [str(o.id) for o in objects if isinstance(o, cls)]
            lab = Gtk.Label()
            lab.set_xalign(0)
            lab.set_yalign(0.5)
            lab.set_text(cls.__name__)
            self.grid.attach(lab, 0, row_no, 1, 1)

            eventbox = Gtk.EventBox()
            label = Gtk.Label()
            label.set_xalign(0)
            label.set_yalign(0.5)
            eventbox.add(label)
            self.grid.attach(eventbox, 1, row_no, 1, 1)
            label.set_text(f" {len(obj_ids)} ")
            utils.make_label_clickable(
                label,
                lambda _l, _e, x: bauble.gui.send_command(x),
                f'{cls.__name__.lower()} where id in {", ".join(obj_ids)}',
            )

            self.table_cells.append(lab)
            self.table_cells.append(eventbox)

            row_no += 1
        self.grid.show_all()


class TagInfoBox(InfoBox):

    def __init__(self):
        super().__init__()
        self.general = GeneralTagExpander()
        self.add_expander(self.general)
        self.props = PropertiesExpander()
        self.add_expander(self.props)

    def update(self, row):
        self.general.update(row)
        self.props.update(row)


@Gtk.Template(filename=str(Path(__file__).resolve().parent / "tags_page.ui"))
class TagsBottomPage(Gtk.ScrolledWindow):
    """Page to append to ``SearchView.bottom_notebook``, shows the tags
    attached to the selected object.
    """

    __gtype_name__ = "TagsBottomPage"

    treeview = cast(Gtk.TreeView, Gtk.Template.Child())
    liststore = cast(Gtk.ListStore, Gtk.Template.Child())

    LABEL_STR = _("Tags")
    label = Gtk.Label(label=LABEL_STR)

    def update(self, row: db.Domain) -> None:
        logger.debug("update tags bottom page")

        self.liststore.clear()
        tags = Tag.attached_to(row)

        for tag in reversed(tags):
            self.liststore.append((tag.tag, tag.description or ""))

        if tags:
            self.label.set_use_markup(True)
            self.label.set_label(f"<b>{self.LABEL_STR}</b>")
        else:
            self.label.set_use_markup(False)
            self.label.set_label(self.LABEL_STR)

    @Gtk.Template.Callback()
    def on_row_activated(
        self,
        _tree,
        path: Gtk.TreePath,
        _column,
        *,
        send_command: Callable[[str], None] | None = None,
    ) -> None:
        """When a row is double clicked run a search for the rows tag."""
        send_command = send_command or bauble.gui.send_command
        # pylint: disable=unsubscriptable-object
        tag = repr(self.liststore[path][0])
        logger.debug("tags bottom page row_activated: tag=%s", tag)
        send_command(f"tag={tag}")
