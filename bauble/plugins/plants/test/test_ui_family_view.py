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
Family search view parts.
"""
from unittest import mock

from gi.repository import Gtk
from sqlalchemy.exc import SQLAlchemyError

from bauble import prefs
from bauble import utils
from bauble.test import BaubleTestCase

from ..family import Family
from ..genus import Genus
from ..test_plants import PlantTestCase
from ..ui.family_editor import FAMILY_WEB_BUTTON_DEFS_PREFS
from ..ui.family_view import FamilyInfoBox
from ..ui.family_view import GeneralFamilyExpander
from ..ui.family_view import remove_callback


class InfoBoxTests(PlantTestCase):
    def test_general_expander(self):
        # at least tests nothing errors
        fams = self.session.query(Family).filter(Family.id.in_((3, 8, 10, 11)))

        general = GeneralFamilyExpander()
        for fam in fams:
            general.update(fam)
            self.assertEqual(
                general.name_label.get_label(),
                f"<big>{fam}</big> {utils.xml_safe(str(fam.author))}",
            )

    def test_family_info_box_links(self):
        infobox = FamilyInfoBox()
        links = infobox.get_nth_page(0).expanders["Links"]
        self.assertTrue(len(links.web_links) > 0)

        self.assertEqual(
            len(links.web_links),
            len(list(prefs.prefs.itersection(FAMILY_WEB_BUTTON_DEFS_PREFS))),
        )


class FunctionTests(BaubleTestCase):

    @mock.patch("bauble.ui.dialogs.yes_no_dialog")
    def test_remove_callback_user_backs_out(self, mock_dlog):
        family = Family(family="Araucariaceae")
        self.session.add(family)
        self.session.commit()
        mock_dlog.return_value = False

        remove_callback([family])

        mock_dlog.assert_called_once_with(
            "Are you sure you want to remove the following families "
            "<i>Araucariaceae</i>?"
        )
        self.assertEqual(
            self.session.query(Family).filter_by(family="Araucariaceae").all(),
            [family],
        )

    @mock.patch("bauble.ui.dialogs.yes_no_dialog")
    def test_remove_callback_user_confirms(self, mock_dlog):
        family = Family(family="Araucariaceae")
        self.session.add(family)
        self.session.commit()
        mock_dlog.return_value = True

        remove_callback([family])

        mock_dlog.assert_called_once_with(
            "Are you sure you want to remove the following families "
            "<i>Araucariaceae</i>?",
        )

        self.assertEqual(
            self.session.query(Family).filter_by(family="Araucariaceae").all(),
            [],
        )

    @mock.patch("bauble.ui.dialogs.message_dialog")
    def test_remove_callback_with_genera(self, mock_dlog):
        family = Family(family="Araucariaceae")
        gen = Genus(family=family, genus="Araucaria")
        self.session.add_all([family, gen])
        self.session.commit()
        mock_dlog.return_value = True

        remove_callback([family])

        mock_dlog.assert_called_once_with(
            "The family <i>Araucariaceae</i> has 1 genera.\n\nYou "
            "cannot remove a family with genera.",
            typ=Gtk.MessageType.WARNING,
        )
        self.assertEqual(
            self.session.query(Family).filter_by(family="Araucariaceae").all(),
            [family],
        )
        self.assertEqual(
            self.session.query(Genus).filter_by(genus="Araucaria").all(),
            [gen],
        )

    @mock.patch("bauble.ui.dialogs.yes_no_dialog")
    @mock.patch("bauble.ui.dialogs.message_details_dialog")
    def test_remove_callback_commit_exception(self, mock_d_dlog, mock_yn_dlog):
        mock_yn_dlog.return_value = True
        mock_d_dlog.return_value = True
        family = Family(family="Araucariaceae")
        self.session.add(family)
        self.session.commit()

        with (
            mock.patch.object(
                self.session, "commit", side_effect=SQLAlchemyError
            ),
            mock.patch.object(self.session, "rollback") as mock_rollback,
        ):
            self.assertFalse(remove_callback([family]))
            mock_rollback.assert_called_once()
            mock_d_dlog.assert_called_once()

    def test_remove_callback_no_session(self):
        family = Family(family="Araucariaceae")

        with self.assertLogs(
            "bauble.plugins.plants.ui.family_view",
            level="WARNING",
        ) as logs:
            remove_callback([family])
            self.assertIn(
                "Could not get session for family Araucariaceae. "
                "Cannot delete.",
                logs.output[0],
            )
