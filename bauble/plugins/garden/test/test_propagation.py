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
Propagation models tests
"""
from sqlalchemy import select

from bauble import utils
from bauble.plugins.garden.source import Source
from bauble.test import BaubleTestCase

from ...plants.family import Family
from ...plants.genus import Genus
from ...plants.species import Species
from ..accession import Accession
from ..location import Location
from ..plant import Plant
from ..propagation import Propagation
from ..propagation import PropEvent
from ..propagation import PropEventType
from ..propagation import PropType
from ..propagation import populate_default_event_types
from ..propagation import populate_default_prop_types


class PropagationTests(BaubleTestCase):
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
        self.plant2 = Plant(
            code="2",
            accession=self.accession,
            quantity=7,
            location=location,
        )
        self.session.add(self.plant)
        self.session.commit()

    def test_can_add_propagation(self):
        prop = Propagation(
            quantity=10,
            media="potting mix",
            container="140",
            location="table 3",
            prop_notes="bulb division",
        )
        self.plant.propagations.append(prop)
        self.session.commit()

        self.assertEqual(len(self.plant.propagations), 1)

    def test_can_add_propagation_multiple_plants(self):
        prop = Propagation(
            quantity=10,
            media="potting mix",
            container="140",
            location="table 3",
            prop_notes="bulb division",
        )
        self.plant.propagations.append(prop)
        prop.plants.append(self.plant2)
        self.session.commit()

        self.assertEqual(len(self.plant.propagations), 1)
        self.assertEqual(len(self.plant2.propagations), 1)

    def test_propagation_string(self):
        prop_type = self.session.query(PropType).filter_by(code="seed").first()
        prop = Propagation(
            quantity=10,
            media="potting mix",
            container="140",
            location="table 3",
            prop_notes="bulb division",
            prop_type=prop_type,
        )
        self.plant.propagations.append(prop)
        self.session.commit()

        today = utils.today_str()
        user = utils.get_user_display_name()
        self.assertEqual(
            str(prop),
            (
                f"Seed; propagated by {user} on {today}; "
                "Quantity: 10; Media: potting mix; Container: 140; "
                "Location: table 3; Notes: bulb division"
            ),
        )

    def test_propagation_events(self):
        # test hybrid_property.expressions for established_qty, available_qty,
        # and percent_success and 'children' methods also
        prop = Propagation(
            quantity=10,
            media="potting mix",
            container="140",
            location="table 3",
            prop_notes="bulb division",
        )
        self.plant.propagations.append(prop)
        self.session.commit()

        established_qty = self.session.scalar(
            select(Propagation.established_qty).filter_by(id=prop.id)
        )
        available_qty = self.session.scalar(
            select(Propagation.available_qty).filter_by(id=prop.id)
        )
        percent_success = self.session.scalar(
            select(Propagation.percent_success).filter_by(id=prop.id)
        )

        self.assertEqual(established_qty, 0)
        self.assertEqual(available_qty, 0)
        self.assertEqual(percent_success, 0.0)

        success = self.session.scalar(
            select(PropEventType).filter_by(code="success")
        )
        prop.events.append(
            PropEvent(
                quantity=9,
                event_notes="leaves appear",
                event_type=success,
            )
        )
        self.session.commit()

        established_qty = self.session.scalar(
            select(Propagation.established_qty).filter_by(id=prop.id)
        )
        available_qty = self.session.scalar(
            select(Propagation.available_qty).filter_by(id=prop.id)
        )
        percent_success = self.session.scalar(
            select(Propagation.percent_success).filter_by(id=prop.id)
        )

        self.assertEqual(established_qty, 9)
        self.assertEqual(available_qty, 9)
        self.assertEqual(percent_success, 90.0)

        prop.events.append(
            PropEvent(
                quantity=1,
                event_notes="leaves appear",
                event_type=success,
            )
        )

        self.session.commit()
        # test the expressions also
        established_qty = self.session.scalar(
            select(Propagation.established_qty).filter_by(id=prop.id)
        )
        available_qty = self.session.scalar(
            select(Propagation.available_qty).filter_by(id=prop.id)
        )
        percent_success = self.session.scalar(
            select(Propagation.percent_success).filter_by(id=prop.id)
        )

        self.assertEqual(established_qty, 10)
        self.assertEqual(available_qty, 10)
        self.assertEqual(percent_success, 100.0)

    def test_propagation_events_discard(self):
        prop = Propagation(
            quantity=10,
            media="potting mix",
            container="140",
            location="table 3",
            prop_notes="bulb division",
        )
        self.plant.propagations.append(prop)
        self.session.commit()

        self.assertEqual(prop.established_qty, 0)
        self.assertEqual(prop.available_qty, 0)
        self.assertEqual(prop.percent_success, 0.0)

        success = self.session.scalar(
            select(PropEventType).filter_by(code="success")
        )
        prop.events.append(
            PropEvent(
                quantity=5,
                event_notes="leaves appear",
                event_type=success,
            )
        )

        self.assertEqual(prop.established_qty, 5)
        self.assertEqual(prop.available_qty, 5)
        self.assertEqual(prop.percent_success, 50.0)

        discard = self.session.scalar(
            select(PropEventType).filter_by(code="discard")
        )
        prop.events.append(
            PropEvent(
                quantity=-5,
                event_notes="reduced to make room.",
                event_type=discard,
            )
        )

        self.assertEqual(prop.established_qty, 0)
        self.assertEqual(prop.available_qty, 0)
        self.assertEqual(prop.percent_success, 0.0)

    def test_propagation_as_source(self):
        # also test hybrid_property.expressions used_qty
        prop = Propagation(
            quantity=10,
            media="potting mix",
            container="140",
            location="table 3",
            prop_notes="bulb division",
        )
        self.plant.propagations.append(prop)
        success = self.session.scalar(
            select(PropEventType).filter_by(code="success")
        )
        prop.events.append(
            PropEvent(
                quantity=8,
                event_notes="leaves appear",
                event_type=success,
            )
        )
        self.session.commit()
        used_qty = self.session.scalar(
            select(Propagation.used_qty).filter_by(id=prop.id)
        )

        self.assertEqual(prop.established_qty, 8)
        self.assertEqual(prop.available_qty, 8)
        self.assertEqual(prop.percent_success, 80.0)
        self.assertEqual(prop.used_qty, 0)
        self.assertEqual(used_qty, 0)
        self.assertFalse(prop.has_children())
        self.assertEqual(prop.count_children(), 0)

        source = Source(plant_propagation=prop)
        acc1 = Accession(
            code="2001.0002",
            species=self.species,
            quantity_recvd=3,
            source=source,
        )
        self.session.add(acc1)
        self.session.commit()
        used_qty = self.session.scalar(
            select(Propagation.used_qty).filter_by(id=prop.id)
        )

        self.assertEqual(prop.used_qty, 3)
        self.assertEqual(used_qty, 3)
        self.assertEqual(prop.available_qty, 5)
        self.assertTrue(prop.has_children())
        self.assertEqual(prop.count_children(), 1)

        source = Source(plant_propagation=prop)
        acc2 = Accession(
            code="2001.0003",
            species=self.species,
            quantity_recvd=5,
            source=source,
        )
        self.session.add(acc2)
        self.session.commit()
        used_qty = self.session.scalar(
            select(Propagation.used_qty).filter_by(id=prop.id)
        )

        self.assertEqual(prop.used_qty, 8)
        self.assertEqual(used_qty, 8)
        self.assertEqual(prop.available_qty, 0)
        self.assertTrue(prop.has_children())
        self.assertEqual(prop.count_children(), 2)
        self.assertCountEqual(prop.accessions, [acc1, acc2])


class FunctionTests(BaubleTestCase):
    def test_populate_default_prop_types(self):
        prop_types = self.session.scalars(select(PropType)).all()
        self.assertEqual(len(prop_types), 0)

        populate_default_prop_types()

        prop_types = self.session.scalars(select(PropType)).all()
        self.assertEqual(len(prop_types), 6)

        # second run doesn't change
        populate_default_prop_types()

        prop_types = self.session.scalars(select(PropType)).all()
        self.assertEqual(len(prop_types), 6)

    def test_populate_default_event_types(self):
        event_types = self.session.scalars(select(PropEventType)).all()
        self.assertEqual(len(event_types), 0)

        populate_default_event_types()

        event_types = self.session.scalars(select(PropEventType)).all()
        self.assertEqual(len(event_types), 12)

        # second run doesn't change
        populate_default_event_types()

        event_types = self.session.scalars(select(PropEventType)).all()
        self.assertEqual(len(event_types), 12)
