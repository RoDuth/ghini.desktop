# pylint: disable=too-many-locals
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
#
"""
Propagation search view parts.
"""
from datetime import datetime
from unittest import mock

from gi.repository import Gtk
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from bauble import utils
from bauble.test import BaubleTestCase

from ...plants.family import Family
from ...plants.genus import Genus
from ...plants.species import Species
from ..accession import Accession
from ..location import Location
from ..plant import Plant
from ..propagation import PlantPropSource
from ..propagation import Propagation
from ..propagation import PropEvent
from ..propagation import PropEventType
from ..propagation import PropType
from ..propagation import populate_default_event_types
from ..propagation import populate_default_prop_types
from ..ui.propagation_view import GeneralPropagationExpander
from ..ui.propagation_view import remove_callback


class InfoBoxTests(BaubleTestCase):

    def test_general_propagation_expander_update_source(self):
        # pylint: disable=too-many-statements
        populate_default_prop_types()
        populate_default_event_types()
        location = Location(code="OH1")
        family = Family(epithet="Orchidaceae")
        laeliocattleya = Genus(
            family=family,
            epithet="Laeliocattleya",
            hybrid="×",
        )
        lc_caligula = Species(genus=laeliocattleya, grex="Caligula")
        cattleya = Genus(family=family, epithet="Cattleya")
        c_percivaliana = Species(genus=cattleya, epithet="percivaliana")
        accession1 = Accession(code="1999.0001", species=c_percivaliana)
        plant1 = Plant(
            code="1",
            accession=accession1,
            quantity=5,
            location=location,
        )
        laelia = Genus(family=family, epithet="Laelia")
        l_anceps = Species(genus=laelia, epithet="anceps")
        accession2 = Accession(code="1998.0001", species=l_anceps)
        plant2 = Plant(
            code="1",
            accession=accession2,
            quantity=5,
            location=location,
        )
        source1 = PlantPropSource(
            plant=plant1,
            source_type="1",
            source_material="F",
        )
        source2 = PlantPropSource(
            plant=plant2,
            source_type="1",
            source_material="M",
        )
        seed = self.session.scalars(select(PropType).filter_by(code="S")).one()
        prop = Propagation(
            species=lc_caligula,
            code="2001S/1",
            date=datetime(2001, 1, 1),
            propagator="Jade Green",
            media="agar/OMM",
            container="flask",
            location="incubator1",
            prop_notes="Fresh seed, sterilised with bleach",
            prop_type=seed,
            plant_sources=[source1, source2],
        )
        empty_prop = Propagation(
            species=l_anceps,
            code="2002S/1",
            date=datetime(2002, 1, 1),
            propagator="Jade Green",
            media="agar/OMM",
            container="flask",
            location="incubator1",
            prop_notes="Fresh seed, sterilised with bleach",
            prop_type=seed,
            plant_sources=[
                PlantPropSource(
                    plant=plant2,
                    source_type="1",
                    source_material="M",
                )
            ],
        )
        start = self.session.scalars(
            select(PropEventType).filter_by(code="STRT")
        ).one()
        success = self.session.scalars(
            select(PropEventType).filter_by(code="SUCC")
        ).one()
        available = self.session.scalars(
            select(PropEventType).filter_by(code="AVLB")
        ).one()
        event1 = PropEvent(
            date=datetime(2001, 1, 1).date(),
            person="Jade Green",
            quantity=10,
            event_notes="First batch",
            event_type=start,
        )
        prop.events.append(event1)
        event2 = PropEvent(
            date=datetime(2001, 2, 1).date(),
            person="Jade Green",
            success=8,
            event_notes="First batch success",
            event_type=success,
        )
        prop.events.append(event2)
        event3 = PropEvent(
            date=datetime(2001, 3, 10).date(),
            person="Jade Green",
            available=7,
            event_notes="First batch available",
            event_type=available,
        )
        prop.events.append(event3)
        prop_acc = Accession(
            date_recvd=datetime(2001, 3, 10).date(),
            code="2001.0002",
            species=lc_caligula,
            quantity_recvd=3,
        )
        prop.source_new_accession(prop_acc)
        prop_plant = Plant(
            code="1",
            quantity=3,
            accession=prop_acc,
            location=location,
        )
        self.session.add(prop_plant)
        self.session.commit()
        expander = GeneralPropagationExpander()

        expander.update(prop)
        expander.update(empty_prop)  # to trigger changing box>label>destroy
        expander.update(prop)

        self.assertEqual(expander.code_label.get_label(), "<big>2001S/1</big>")
        self.assertEqual(
            expander.name_label.get_label(),
            f"{prop.species.string(markup=True, authors=True)}",
        )
        self.assertEqual(expander.type_label.get_label(), "Seed")
        self.assertEqual(expander.propagator_label.get_label(), "Jade Green")
        self.assertEqual(
            expander.date_label.get_label(),
            utils.date_string(datetime(2001, 1, 1)),
        )
        self.assertEqual(expander.media_label.get_label(), "agar/OMM")
        self.assertEqual(expander.container_label.get_label(), "flask")
        self.assertEqual(expander.location_label.get_label(), "incubator1")
        self.assertEqual(
            expander.notes_label.get_label(),
            "Fresh seed, sterilised with bleach",
        )
        self.assertEqual(expander.quantity_label.get_label(), "10")
        self.assertEqual(expander.success_label.get_label(), "80.00%")
        self.assertEqual(expander.available_label.get_label(), "4")
        self.assertEqual(len(expander.source_plants_box.get_children()), 2)
        self.assertEqual(len(expander.source_for_box.get_children()), 1)

    def test_general_propagation_expander_update_extension(self):
        # with minimal details
        populate_default_prop_types()
        populate_default_event_types()
        family = Family(epithet="Austrobaileyaceae")
        genus = Genus(epithet="Austrobaileya", family=family)
        species = Species(genus=genus, epithet="scandens")
        accession = Accession(code="2001.0001", species=species)
        location = Location(
            code="LOC1",
            name="Location One",
            description="First location.",
        )
        plant = Plant(
            accession=accession,
            location=location,
            code="1",
            quantity=1,
        )
        seed = self.session.scalar(select(PropType).filter_by(code="S"))
        prop = Propagation(
            species=species,
            code="2019S/1",
            date=datetime(2019, 1, 19),
            propagator="Jade Green",
            prop_type=seed,
        )
        plant.propagations.append(prop)
        start = self.session.scalar(
            select(PropEventType).filter_by(code="STRT")
        )
        prop.events.append(
            PropEvent(
                quantity=10,
                event_type=start,
            )
        )
        success = self.session.scalar(
            select(PropEventType).filter_by(code="SUCC")
        )
        prop.events.append(
            PropEvent(
                success=5,
                event_type=success,
            )
        )
        available = self.session.scalar(
            select(PropEventType).filter_by(code="AVLB")
        )
        prop.events.append(
            PropEvent(
                available=4,
                event_type=available,
            )
        )
        self.session.add(plant)
        self.session.add(prop)
        self.session.commit()
        plant2 = Plant(
            accession=accession,
            location=location,
            code="2",
            quantity=1,
        )
        plant2.extension_propagation = prop
        self.session.commit()
        expander = GeneralPropagationExpander()

        expander.update(prop)

        self.assertEqual(expander.code_label.get_label(), "<big>2019S/1</big>")
        self.assertEqual(
            expander.name_label.get_label(),
            f"{prop.species.string(markup=True, authors=True)}",
        )
        self.assertEqual(expander.type_label.get_label(), "Seed")
        self.assertEqual(expander.propagator_label.get_label(), "Jade Green")
        self.assertEqual(
            expander.date_label.get_label(),
            utils.date_string(datetime(2019, 1, 19)),
        )
        self.assertEqual(expander.media_label.get_label(), "")
        self.assertEqual(expander.container_label.get_label(), "")
        self.assertEqual(expander.location_label.get_label(), "")
        self.assertEqual(
            expander.notes_label.get_label(),
            "",
        )
        self.assertEqual(expander.quantity_label.get_label(), "10")
        self.assertEqual(expander.success_label.get_label(), "50.00%")
        self.assertEqual(expander.available_label.get_label(), "3")
        self.assertEqual(len(expander.source_plants_box.get_children()), 1)
        self.assertEqual(len(expander.source_for_box.get_children()), 1)


class FunctionTests(BaubleTestCase):
    def setUp(self):
        super().setUp()
        populate_default_prop_types()
        populate_default_event_types()
        location = Location(code="LOC1")
        family = Family(family="Myrtaceae")
        genus = Genus(family=family, genus="Syzygium")
        self.species = Species(genus=genus, sp="australe")
        self.accession = Accession(code="2001.0001", species=self.species)
        self.plant = Plant(
            code="1",
            accession=self.accession,
            quantity=5,
            location=location,
        )
        self.session.add(self.plant)
        self.session.commit()

    @mock.patch("bauble.ui.dialogs.yes_no_dialog")
    def test_remove_callback_user_backs_out(self, mock_dlog):
        prop = Propagation(
            species=self.species,
            code="2026S/1",
            date=datetime(2026, 1, 10),
            propagator="Jade Green",
            media="potting mix",
            container="140mm",
            location="table 3",
            prop_notes="Fresh, washed, seed.",
            prop_type_id=1,
        )
        self.plant.propagations.append(prop)
        self.session.commit()
        mock_dlog.return_value = False

        remove_callback([prop])

        mock_dlog.assert_called_once_with(
            "Are you sure you want to remove the following propagations "
            "<b>2026S/1</b>?"
        )
        self.assertEqual(
            self.session.execute(
                select(Propagation).where(Propagation.code == "2026S/1")
            )
            .scalars()
            .all(),
            [prop],
        )

    @mock.patch("bauble.ui.dialogs.yes_no_dialog")
    def test_remove_callback_user_confirms(self, mock_dlog):
        prop = Propagation(
            species=self.species,
            code="2026S/1",
            date=datetime(2026, 1, 10),
            propagator="Jade Green",
            media="potting mix",
            container="140mm",
            location="table 3",
            prop_notes="Fresh, washed, seed.",
            prop_type_id=1,
        )
        self.plant.propagations.append(prop)
        self.session.commit()
        mock_dlog.return_value = True

        remove_callback([prop])

        mock_dlog.assert_called_once_with(
            "Are you sure you want to remove the following propagations "
            "<b>2026S/1</b>?"
        )
        self.assertEqual(
            self.session.execute(
                select(Propagation).where(Propagation.code == "2026S/1")
            )
            .scalars()
            .all(),
            [],
        )

    @mock.patch("bauble.ui.dialogs.message_dialog")
    def test_remove_callback_with_accessions(self, mock_dlog):
        prop = Propagation(
            species=self.species,
            code="2026S/1",
            date=datetime(2026, 1, 10),
            propagator="Jade Green",
            media="potting mix",
            container="140mm",
            location="table 3",
            prop_notes="Fresh, washed, seed.",
            prop_type_id=1,
        )
        start = self.session.scalars(
            select(PropEventType).filter_by(code="STRT")
        ).one()
        success = self.session.scalars(
            select(PropEventType).filter_by(code="SUCC")
        ).one()
        available = self.session.scalars(
            select(PropEventType).filter_by(code="AVLB")
        ).one()
        event1 = PropEvent(
            date=datetime(2026, 2, 1).date(),
            person="Jade Green",
            quantity=10,
            event_notes="First batch",
            event_type=start,
        )
        prop.events.append(event1)
        event2 = PropEvent(
            date=datetime(2026, 3, 1).date(),
            person="Jade Green",
            success=8,
            event_notes="First batch success",
            event_type=success,
        )
        prop.events.append(event2)
        event3 = PropEvent(
            date=datetime(2026, 4, 10).date(),
            person="Jade Green",
            available=7,
            event_notes="First batch available",
            event_type=available,
        )
        prop.events.append(event3)
        self.plant.propagations.append(prop)
        accession = Accession(
            code="2026.0003",
            species=self.species,
            quantity_recvd=7,
        )
        prop.source_new_accession(accession)
        self.session.commit()
        mock_dlog.return_value = True

        self.assertFalse(remove_callback([prop]))

        mock_dlog.assert_called_once_with(
            "Please remove the accessions from <b>2026S/1</b> before deleting "
            "it.",
            typ=Gtk.MessageType.WARNING,
        )
        self.assertEqual(
            self.session.execute(
                select(Propagation).where(Propagation.code == "2026S/1")
            )
            .scalars()
            .all(),
            [prop],
        )

    @mock.patch("bauble.ui.dialogs.yes_no_dialog")
    @mock.patch("bauble.ui.dialogs.message_details_dialog")
    def test_remove_callback_commit_exception(self, mock_d_dlog, mock_yn_dlog):
        mock_yn_dlog.return_value = True
        mock_d_dlog.return_value = True
        prop = Propagation(
            species=self.species,
            code="2026S/1",
            date=datetime(2026, 1, 10),
            propagator="Jade Green",
            media="potting mix",
            container="140mm",
            location="table 3",
            prop_notes="Fresh, washed, seed.",
            prop_type_id=1,
        )
        self.plant.propagations.append(prop)
        self.session.commit()

        with (
            mock.patch.object(
                self.session, "commit", side_effect=SQLAlchemyError
            ),
            mock.patch.object(self.session, "rollback") as mock_rollback,
        ):

            self.assertFalse(remove_callback([prop]))
            mock_rollback.assert_called_once()
            mock_d_dlog.assert_called_once()

    def test_remove_callback_no_session(self):
        prop = Propagation(
            species=self.species,
            code="2026S/1",
            date=datetime(2026, 1, 10),
            propagator="Jade Green",
            media="potting mix",
            container="140mm",
            location="table 3",
            prop_notes="Fresh, washed, seed.",
            prop_type_id=1,
        )

        with self.assertLogs(
            "bauble.plugins.garden.ui.propagation_view",
            level="WARNING",
        ) as logs:
            remove_callback([prop])

            self.assertIn(
                "Could not get session for propagation 2026S/1. Cannot "
                "delete.",
                logs.output[0],
            )
