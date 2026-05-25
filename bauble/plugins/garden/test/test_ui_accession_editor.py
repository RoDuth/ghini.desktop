# Copyright (c) 2026 Ross Demuth <rossdemuth123@gmail.com>
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
Accession editor tests
"""
from unittest import mock

from bauble.plugins.plants.family import Family
from bauble.plugins.plants.genus import Genus
from bauble.plugins.plants.species import Species
from bauble.test import BaubleTestCase

from ..accession import Accession
from ..plant import Plant
from ..ui.accession_editor import add_plants_callback


class FunctionTests(BaubleTestCase):
    def test_add_plants_callback(self):
        family = Family(epithet="Austrobaileyaceae")
        genus = Genus(epithet="Austrobaileya", family=family)
        species = Species(genus=genus, epithet="scandens")
        accession = Accession(code="2001.0001", species=species)
        self.session.add(accession)
        self.session.commit()

        with mock.patch.object(
            add_plants_callback,
            "dialog_class",
        ) as mock_editor:

            self.assertFalse(add_plants_callback([accession]))
            mock_editor.assert_called_once()
            plt = mock_editor.call_args.kwargs["model"]
            plt = self.session.merge(plt)
            self.assertIsInstance(plt, Plant)
            self.assertEqual(plt.accession, accession)
