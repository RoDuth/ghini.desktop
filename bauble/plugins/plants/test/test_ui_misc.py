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
UI functions test for plants plugin.
"""
from unittest import mock

from bauble import prefs
from bauble.test import BaubleTestCase

from ..family import Family
from ..ui.misc import get_binomial_completions
from ..ui.misc import on_taxa_clicked
from .test_plants import setUp_data as setup_plants_data


class FunctionTests(BaubleTestCase):
    @mock.patch("bauble.plugins.plants.ui.misc.select_in_search_results")
    def test_on_taxa_clicked(self, mock_select):
        prefs.prefs[prefs.return_accepted_pref] = False
        fam = Family(epithet="Spam")
        fam2 = Family(epithet="Eggs")
        fam.synonyms.append(fam2)

        on_taxa_clicked(None, None, fam2)

        mock_select.assert_called_once_with(fam2)

        mock_select.reset_mock()
        prefs.prefs[prefs.return_accepted_pref] = True

        on_taxa_clicked(None, None, fam2)

        args = mock_select.call_args_list

        self.assertEqual(len(args), 2)
        self.assertEqual(args[0].args, (fam,))
        self.assertEqual(args[1].args, (fam2,))

    def test_get_binomial_completions(self):
        setup_plants_data()
        self.assertEqual(
            get_binomial_completions("cyn"),
            {
                "Cynodon dactylon 'TifTuf'",
                "Cynodon dactylon 'DT-1'",
                "Cynodon dactylon",
            },
        )
        self.assertEqual(
            get_binomial_completions("cynodon dact"),
            {
                "Cynodon dactylon 'TifTuf'",
                "Cynodon dactylon 'DT-1'",
                "Cynodon dactylon",
            },
        )
        self.assertEqual(
            get_binomial_completions("cynod dact"),
            {
                "Cynodon dactylon 'TifTuf'",
                "Cynodon dactylon 'DT-1'",
                "Cynodon dactylon",
            },
        )
        self.assertEqual(
            get_binomial_completions("Cynod 'T"),
            {
                "Cynodon 'TifTuf'",
            },
        )
        self.assertEqual(
            get_binomial_completions("Cynodon 'T"),
            {
                "Cynodon 'TifTuf'",
            },
        )
        self.assertEqual(
            get_binomial_completions("Cynodon dactylon 'DT"),
            {
                "Cynodon dactylon 'DT-1'",
            },
        )
        self.assertEqual(
            get_binomial_completions("Buty"),
            {
                "Butyagrus nabonnandii",
            },
        )
