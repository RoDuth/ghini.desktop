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
Species search view tests
"""
from unittest import mock

from gi.repository import Gtk
from sqlalchemy.exc import SQLAlchemyError

from bauble.plugins.plants.family import Family
from bauble.plugins.plants.genus import Genus
from bauble.plugins.plants.species import Species
from bauble.plugins.plants.species import VernacularName
from bauble.test import BaubleTestCase

from ...garden import Accession
from ..ui.species_view import remove_callback


class FunctionTests(BaubleTestCase):
    def test_remove_callback_no_accessions_no_confirm(self):
        caricaceae = Family(family="Caricaceae")
        gen = Genus(epithet="Carica", family=caricaceae)
        sp = Species(epithet="papaya", genus=gen)
        self.session.add_all([caricaceae, gen, sp])
        self.session.flush()

        with mock.patch("bauble.ui.dialogs.yes_no_dialog") as mock_dlog:
            mock_dlog.return_value = False
            result = remove_callback([sp])
            mock_dlog.assert_called_once_with(
                "Are you sure you want to remove the following species "
                "<i>Carica papaya</i>?",
            )

        self.assertFalse(result)
        self.assertEqual(
            self.session.query(Species).filter_by(sp="papaya").all(),
            [sp],
        )

    def test_remove_callback_no_accessions_confirm(self):
        caricaceae = Family(family="Caricaceae")
        gen = Genus(epithet="Carica", family=caricaceae)
        sp = Species(epithet="papaya", genus=gen)
        self.session.add_all([caricaceae, gen, sp])
        self.session.flush()

        with mock.patch("bauble.ui.dialogs.yes_no_dialog") as mock_dlog:
            mock_dlog.return_value = True
            result = remove_callback([sp])
            mock_dlog.assert_called_once_with(
                "Are you sure you want to remove the following species "
                "<i>Carica papaya</i>?",
            )

        self.assertTrue(result)
        self.assertEqual(
            self.session.query(Species).filter_by(sp="papaya").all(),
            [],
        )

    def test_remove_callback_with_accessions_cant_cascade(self):
        caricaceae = Family(family="Caricaceae")
        gen = Genus(epithet="Carica", family=caricaceae)
        sp = Species(epithet="papaya", genus=gen)
        vern = VernacularName(name="Pawpaw")
        sp.default_vernacular_name = vern

        acc = Accession(code="0123456", species=sp)
        self.session.add_all([caricaceae, gen, sp, acc])
        self.session.flush()

        with mock.patch("bauble.ui.dialogs.message_dialog") as mock_dlog:
            mock_dlog.return_value = True
            result = remove_callback([vern])
            mock_dlog.assert_called_once_with(
                "The species <i>Carica papaya</i> has 1 accessions."
                "\n\nYou cannot remove a species with accessions.",
                typ=Gtk.MessageType.WARNING,
            )

        self.assertFalse(result)
        self.assertEqual(
            self.session.query(Species).filter_by(sp="papaya").all(),
            [sp],
        )
        self.assertEqual(
            self.session.query(Accession).filter_by(species=sp).all(),
            [acc],
        )

    def test_remove_callback_bails_not_session(self):
        caricaceae = Family(family="Caricaceae")
        gen = Genus(epithet="Carica", family=caricaceae)
        sp = Species(epithet="papaya", genus=gen)
        self.session.add(sp)
        self.session.flush()

        with mock.patch(
            "bauble.plugins.plants.ui.species_view.object_session"
        ):
            self.assertFalse(remove_callback([sp]))

    @mock.patch("bauble.ui.dialogs.yes_no_dialog")
    @mock.patch("bauble.ui.dialogs.message_details_dialog")
    def test_remove_callback_commit_exception(self, mock_d_dlog, mock_yn_dlog):
        mock_yn_dlog.return_value = True
        mock_d_dlog.return_value = True
        caricaceae = Family(family="Caricaceae")
        gen = Genus(epithet="Carica", family=caricaceae)
        sp = Species(epithet="papaya", genus=gen)
        self.session.add(sp)
        self.session.flush()

        with (
            mock.patch.object(
                self.session, "commit", side_effect=SQLAlchemyError
            ),
            mock.patch.object(self.session, "rollback") as mock_rollback,
        ):
            self.assertFalse(remove_callback([sp]))
            mock_rollback.assert_called()
            mock_d_dlog.assert_called()

    # def test_edit_callback(self):
    #     caricaceae = Family(family="Caricaceae")
    #     gen = Genus(epithet="Carica", family=caricaceae)
    #     sp = Species(epithet="papaya", genus=gen)
    #     vern = VernacularName(name="Pawpaw")
    #     sp.default_vernacular_name = vern
    #     self.session.add(sp)
    #     self.session.flush()

    #     from .ui.species_view import edit_callback

    #     with mock.patch(
    #         "bauble.plugins.plants.species.edit_species"
    #     ) as mock_edit:
    #         mock_edit.return_value = None

    #         self.assertFalse(edit_callback([sp]))

    #         mock_edit.return_value = sp
    #         self.assertTrue(edit_callback([vern]))

    # def test_add_accession_callback(self):
    #     caricaceae = Family(family="Caricaceae")
    #     gen = Genus(epithet="Carica", family=caricaceae)
    #     sp = Species(epithet="papaya", genus=gen)
    #     vern = VernacularName(name="Pawpaw")
    #     sp.default_vernacular_name = vern
    #     self.session.add(sp)
    #     self.session.flush()

    #     from ..garden import Accession
    #     from .ui.species_view import add_accession_callback

    #     with mock.patch(
    #         "bauble.plugins.garden.accession.AccessionEditor"
    #     ) as mock_edit:
    #         mock_edit().start.return_value = None

    #         self.assertFalse(add_accession_callback([sp]))
    #         acc = mock_edit.call_args.kwargs["model"]
    #         self.assertIsInstance(acc, Accession)
    #         self.assertEqual(acc.species, sp)
    #         mock_edit.reset_mock()

    #         mock_edit().start.return_value = True
    #         self.assertTrue(add_accession_callback([vern]))
    #         acc = mock_edit.call_args.kwargs["model"]
    #         self.assertIsInstance(acc, Accession)
    #         self.assertEqual(acc.species, sp)
