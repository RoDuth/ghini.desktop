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
Family search view tests
"""
from unittest import mock

from gi.repository import Gtk
from sqlalchemy.exc import SQLAlchemyError

from bauble import prefs
from bauble import utils
from bauble.plugins.plants.family import Family
from bauble.plugins.plants.genus import Genus
from bauble.plugins.plants.species import Species
from bauble.test import BaubleTestCase

# rename to avoid get_setUp_data_funcs finding it twice
from ..test_plants import setUp_data as setup_plants_data
from ..ui.genus_view import GENUS_WEB_BUTTON_DEFS_PREFS
from ..ui.genus_view import GeneralGenusExpander
from ..ui.genus_view import GenusInfoBox
from ..ui.genus_view import remove_callback


class InfoBoxTests(BaubleTestCase):
    def test_general_expander(self):
        setup_plants_data()
        # at least tests nothing errors
        genera = self.session.query(Genus).filter(
            Genus.id.in_((9, 11, 12, 15))
        )
        general = GeneralGenusExpander()
        for gen in genera:
            general.update(gen)
            self.assertEqual(
                general.name_label.get_label(),
                f"<big>{gen.markup()}</big> "
                f"{utils.xml_safe(str(gen.author))}",
            )

    def test_genus_info_box_links(self):
        infobox = GenusInfoBox()
        links = infobox.get_nth_page(0).expanders["Links"]
        self.assertTrue(len(links.web_links) > 0)

        self.assertEqual(
            len(links.web_links),
            len(list(prefs.prefs.itersection(GENUS_WEB_BUTTON_DEFS_PREFS))),
        )


class FunctionTests(BaubleTestCase):
    def test_remove_callback_no_species_no_confirm(self):
        caricaceae = Family(family="Caricaceae")
        gen = Genus(epithet="Carica", family=caricaceae)
        self.session.add(gen)
        self.session.flush()

        with mock.patch("bauble.ui.dialogs.yes_no_dialog") as mock_dlog:
            mock_dlog.return_value = False
            result = remove_callback([gen])
            mock_dlog.assert_called_once_with(
                "Are you sure you want to remove the following genera "
                "<i>Carica</i>?",
            )

        self.assertFalse(result)
        self.assertEqual(
            self.session.query(Genus).filter_by(genus="Carica").all(),
            [gen],
        )

    def test_remove_callback_no_species_confirm(self):
        caricaceae = Family(family="Caricaceae")
        gen = Genus(epithet="Carica", family=caricaceae)
        self.session.add(gen)
        self.session.flush()

        with mock.patch("bauble.ui.dialogs.yes_no_dialog") as mock_dlog:
            mock_dlog.return_value = True
            result = remove_callback([gen])
            mock_dlog.assert_called_once_with(
                "Are you sure you want to remove the following genera "
                "<i>Carica</i>?",
            )

        self.assertTrue(result)
        self.assertEqual(
            self.session.query(Genus).filter_by(genus="Carica").all(),
            [],
        )

    def test_remove_callback_with_species_cant_cascade(self):
        caricaceae = Family(family="Caricaceae")
        gen = Genus(epithet="Carica", family=caricaceae)
        sp = Species(genus=gen, sp="papaya")
        self.session.add(sp)
        self.session.flush()

        with mock.patch("bauble.ui.dialogs.message_dialog") as mock_dlog:
            mock_dlog.return_value = True
            result = remove_callback([gen])
            mock_dlog.assert_called_once_with(
                "The genus <i>Carica</i> has 1 species.\n\nYou "
                "cannot remove a genus with species.",
                typ=Gtk.MessageType.WARNING,
            )

        self.assertFalse(result)
        self.assertEqual(
            self.session.query(Genus).filter_by(genus="Carica").all(),
            [gen],
        )
        self.assertEqual(
            self.session.query(Species).filter_by(sp="papaya").all(),
            [sp],
        )

    def test_remove_callback_bails_not_session(self):
        caricaceae = Family(family="Caricaceae")
        gen = Genus(epithet="Carica", family=caricaceae)
        self.session.add(gen)
        self.session.flush()

        with mock.patch(
            "bauble.plugins.plants.ui.genus_view.object_session"
        ) as mock_obj_sess:
            self.assertFalse(remove_callback([gen]))
            mock_obj_sess.assert_called_once_with(gen)

    @mock.patch("bauble.ui.dialogs.yes_no_dialog")
    @mock.patch("bauble.ui.dialogs.message_details_dialog")
    def test_remove_callback_commit_exception(self, mock_d_dlog, mock_yn_dlog):
        mock_yn_dlog.return_value = True
        mock_d_dlog.return_value = True
        caricaceae = Family(family="Caricaceae")
        gen = Genus(epithet="Carica", family=caricaceae)
        self.session.add(gen)
        self.session.flush()

        with (
            mock.patch.object(
                self.session, "commit", side_effect=SQLAlchemyError
            ),
            mock.patch.object(self.session, "rollback") as mock_rollback,
        ):
            self.assertFalse(remove_callback([gen]))
            mock_rollback.assert_called()
            mock_d_dlog.assert_called()
