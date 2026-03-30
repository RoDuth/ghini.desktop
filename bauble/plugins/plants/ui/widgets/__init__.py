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
Generic widgets.
"""
from .geography import GeographyMenu
from .synonyms import SynonymsExpander
from .synonyms import SynonymsPresenter
from .synonyms import taxon_completion_cell_data_func

__all__ = [
    "GeographyMenu",
    "SynonymsExpander",
    "SynonymsPresenter",
    "taxon_completion_cell_data_func",
]
