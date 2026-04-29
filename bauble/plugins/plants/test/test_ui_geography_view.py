# Copyright 2024-2026 Ross Demuth <rossdemuth123@gmail.com>
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
Geography search view parts.
"""
from unittest import mock

from ..geography import Geography
from ..ui.geography_view import GeneralGeographyExpander
from .test_plants import PlantTestCase
from .test_plants import setup_geographies


class InfoBoxTests(PlantTestCase):

    @mock.patch("bauble.utils.make_label_clickable")
    def test_expander_update_with_parent_makes_label_clickable(self, mock_mlc):
        setup_geographies()
        qld = self.session.get(Geography, 330)
        self.assertTrue(qld.parent)

        expander = GeneralGeographyExpander()
        expander.update(qld)
        mock_mlc.assert_called()
