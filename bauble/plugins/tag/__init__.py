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
Tag plugin
"""

import logging
from functools import partial

logger = logging.getLogger(__name__)

import bauble
from bauble import db
from bauble import pluginmgr
from bauble import search
from bauble.view import HistoryView
from bauble.view import SearchView

from .model import Tag
from .ui import menu_manager
from .ui.editor import edit_callback
from .ui.editor import tag_context_menu
from .ui.view import TagInfoBox
from .ui.view import TagsBottomPage


class TagPlugin(pluginmgr.Plugin):

    tags_infobox: TagInfoBox | None = None
    tags_page: TagsBottomPage | None = None

    @classmethod
    def init(cls) -> None:

        mapper_search = search.strategies.get_strategy("MapperSearch")

        if not mapper_search:
            return

        if cls.tags_infobox is None:
            cls.tags_infobox = TagInfoBox()

        mapper_search.add_meta(("tag", "tags"), Tag, ["tag"])
        SearchView.row_meta[Tag].set(
            children=partial(
                db.get_active_children, partial(db.natsort, "objects")
            ),
            infobox=cls.tags_infobox,
            context_menu=tag_context_menu,
            activated_callback=edit_callback,
        )

        if cls.tags_page is None:
            cls.tags_page = TagsBottomPage()

        SearchView.bottom_pages.add((cls.tags_page, cls.tags_page.label))

        SearchView.context_menu_callbacks.add(
            menu_manager.context_menu_callback
        )

        SearchView.cursor_changed_callbacks.add(menu_manager.refresh)

        if bauble.gui:
            bauble.gui.set_view_callbacks.add(menu_manager.refresh)
            menu_manager.reset()

        HistoryView.add_translation_query(
            "tagged_obj", "tag", "{table} where objects_.id = {obj_id}"
        )


plugin = TagPlugin  # pylint: disable=invalid-name
