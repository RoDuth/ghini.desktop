# Copyright 2026 Ross Demuth <rossdemuth123@gmail.com>
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
UI views
"""
from .base import View
from .history import HistoryView
from .home import HomeCommandHandler
from .home import HomeView
from .infobox import InfoBox
from .infobox import InfoExpander
from .infobox import LinksExpander
from .infobox import PropertiesExpander
from .prefs import PrefsView
from .search import Action
from .search import SearchView
from .search import get_search_view
from .search import get_search_view_selected
from .search import on_clicked_search
from .search import on_clicked_select
from .search import select_in_search_results

__all__ = [
    "View",
    "HistoryView",
    "HomeCommandHandler",
    "HomeView",
    "InfoBox",
    "InfoExpander",
    "LinksExpander",
    "PropertiesExpander",
    "PrefsView",
    "Action",
    "SearchView",
    "get_search_view",
    "get_search_view_selected",
    "on_clicked_search",
    "on_clicked_select",
    "select_in_search_results",
]
