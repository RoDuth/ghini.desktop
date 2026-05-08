# Copyright 2025-2025 Ross Demuth <rossdemuth123@gmail.com>
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
Location search view tests
"""
from unittest import mock

from gi.repository import Gtk
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from bauble.test import BaubleTestCase

from ..location import Location
from ..test_garden import GardenTestCase
from ..ui.location_view import DescriptionExpander
from ..ui.location_view import GeneralLocationExpander
from ..ui.location_view import remove_callback


class InfoBoxTests(GardenTestCase):

    def test_general_location_expander_update_w_geojson(self):
        expander = GeneralLocationExpander()
        loc = self.session.query(Location).first()
        loc.geojson = {
            "type": "Polygon",
            "coordinates": [
                [
                    [0.001, 0.001],
                    [0.0, 0.001],
                    [0.0, 0.0],
                    [0.001, 0.0],
                    [0.001, 0.001],
                ],
            ],
        }
        self.session.commit()

        expander.update(loc)

        self.assertEqual(expander.geojson_type_label.get_text(), "Polygon")
        self.assertEqual(expander.approx_area_label.get_text(), "12309.07 m²")

    def test_desription_expander_expands(self):
        expander = DescriptionExpander()
        # with description
        loc = self.session.query(Location).first()
        expander.update(loc)

        self.assertTrue(expander.get_expanded())

        # without description
        loc = self.session.get(Location, 2)
        expander.update(loc)

        self.assertFalse(expander.get_expanded())


class FunctionTests(BaubleTestCase):

    @mock.patch("bauble.ui.dialogs.yes_no_dialog")
    def test_remove_callback_user_backs_out(self, mock_dlog):
        location = Location(code="LOC1")
        self.session.add(location)
        self.session.commit()
        mock_dlog.return_value = False

        remove_callback([location])

        mock_dlog.assert_called_once_with(
            "Are you sure you want to remove the following locations "
            "<b>LOC1</b>?"
        )
        self.assertEqual(
            self.session.execute(
                select(Location).where(Location.code == "LOC1")
            )
            .scalars()
            .all(),
            [location],
        )

    @mock.patch("bauble.ui.dialogs.yes_no_dialog")
    def test_remove_callback_user_confirms(self, mock_dlog):
        location = Location(code="LOC1")
        self.session.add(location)
        self.session.commit()
        mock_dlog.return_value = True

        remove_callback([location])

        mock_dlog.assert_called_once_with(
            "Are you sure you want to remove the following locations "
            "<b>LOC1</b>?"
        )
        self.assertEqual(
            self.session.execute(
                select(Location).where(Location.code == "LOC1")
            )
            .scalars()
            .all(),
            [],
        )

    @mock.patch("bauble.ui.dialogs.message_dialog")
    def test_remove_callback_with_plants(self, mock_dlog):
        from bauble.plugins.plants import Family
        from bauble.plugins.plants import Genus
        from bauble.plugins.plants import Species

        from ..accession import Accession
        from ..plant import Plant

        fam = Family(family="Asparagaceae")
        gen = Genus(genus="Liriope", family=fam)
        sp = Species(genus=gen, sp="muscari")
        acc = Accession(code="XXXX", species=sp)
        loc = Location(code="LOC1")
        plt = Plant(code="1", accession=acc, location=loc, quantity=1)
        self.session.add(plt)
        self.session.commit()
        mock_dlog.return_value = True

        remove_callback([loc])

        mock_dlog.assert_called_once_with(
            "Please remove the plants from <b>LOC1</b> before deleting it.",
            typ=Gtk.MessageType.WARNING,
        )
        self.assertEqual(
            self.session.execute(
                select(Location).where(Location.code == "LOC1")
            )
            .scalars()
            .all(),
            [loc],
        )

    @mock.patch("bauble.ui.dialogs.yes_no_dialog")
    @mock.patch("bauble.ui.dialogs.message_details_dialog")
    def test_remove_callback_commit_exception(self, mock_d_dlog, mock_yn_dlog):
        mock_yn_dlog.return_value = True
        mock_d_dlog.return_value = True
        location = Location(code="LOC1")
        self.session.add(location)
        self.session.commit()

        with (
            mock.patch.object(
                self.session, "commit", side_effect=SQLAlchemyError
            ),
            mock.patch.object(self.session, "rollback") as mock_rollback,
        ):

            self.assertFalse(remove_callback([location]))
            mock_rollback.assert_called_once()
            mock_d_dlog.assert_called_once()

    def test_remove_callback_no_session(self):
        location = Location(code="LOC1")

        with self.assertLogs(
            "bauble.plugins.garden.ui.location_view",
            level="WARNING",
        ) as logs:
            remove_callback([location])

            self.assertIn(
                "Could not get session for location LOC1. Cannot delete.",
                logs.output[0],
            )
