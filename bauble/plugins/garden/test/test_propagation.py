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
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from bauble import utils
from bauble.plugins.garden.source import Source
from bauble.test import BaubleTestCase

from ...plants.family import Family
from ...plants.genus import Genus
from ...plants.species import Species
from ..accession import Accession
from ..location import Location
from ..plant import Plant
from ..propagation import START_DEFAULT_EVENT_TYPES
from ..propagation import START_DEFAULT_PROP_TYPES
from ..propagation import Propagation
from ..propagation import PropEvent
from ..propagation import PropEventType
from ..propagation import PropType
from ..propagation import populate_default_event_types
from ..propagation import populate_default_prop_types

SELECT_STMTS = {
    "quantity": select(Propagation.quantity),
    "total_quantity": select(Propagation.total_quantity),
    "culled_quantity": select(Propagation.culled_quantity),
    "success": select(Propagation.success),
    "total_success": select(Propagation.total_success),
    "culled_success": select(Propagation.culled_success),
    "remaining_success": select(Propagation.remaining_success),
    "percent_success": select(Propagation.percent_success),
    "available": select(Propagation.available),
    "made_available": select(Propagation.made_available),
    "discarded": select(Propagation.discarded),
    "used": select(Propagation.used),
    "unused": select(Propagation.unused),
}


@dataclass
class PropHybridsChecker:
    quantity: int = 0
    total_quantity: int = 0
    culled_quantity: int = 0
    success: int = 0
    total_success: int = 0
    culled_success: int = 0
    remaining_success: int = 0
    percent_success: float = 0.0
    available: int = 0
    made_available: int = 0
    discarded: int = 0
    used: int = 0
    unused: int = 0

    def __call__(
        self,
        session: Session,
        propagation: Propagation,
        **kwargs,
    ) -> tuple[bool, str]:
        for prop, stmt in SELECT_STMTS.items():
            result = session.scalar(stmt.filter_by(id=propagation.id))
            prop_is_in_kwargs = False

            if kwargs.get(prop) is not None:
                expected = kwargs.pop(prop)
                prop_is_in_kwargs = True
            else:
                expected = getattr(self, prop)

            # the sql side
            if result != expected:
                return (
                    False,
                    f"hybrid property expression {prop=} FAILED {result=} != "
                    f"{expected=} - {prop_is_in_kwargs=}",
                )

            # the python side
            if getattr(propagation, prop) != expected:
                return (
                    False,
                    f"hybrid property python {prop=} FAILED {result=} != "
                    f"{expected=} - {prop_is_in_kwargs=}",
                )

        if kwargs:
            raise ValueError(f"Unexpected key word arguments {kwargs}")

        return True, "SUCCESS"


hybrid_checker = PropHybridsChecker()


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
        self.seed = self.session.query(PropType).filter_by(code="seed").first()
        self.start = self.session.scalars(
            select(PropEventType).filter_by(code="STRT")
        ).one()
        self.cull_qty = self.session.scalars(
            select(PropEventType).filter_by(code="CULQ")
        ).one()
        self.success = self.session.scalars(
            select(PropEventType).filter_by(code="SUCC")
        ).one()
        self.cull_success = self.session.scalars(
            select(PropEventType).filter_by(code="CULS")
        ).one()
        self.available = self.session.scalars(
            select(PropEventType).filter_by(code="AVLB")
        ).one()
        self.discard = self.session.scalars(
            select(PropEventType).filter_by(code="DISC")
        ).one()

    def test_can_add_propagation(self):
        prop = Propagation(
            date=datetime.today(),
            propagator="Jade Green",
            media="potting mix",
            container="140mm",
            location="table 3",
            prop_notes="Fresh, washed, seed.",
            prop_type=self.seed,
        )
        self.plant.propagations.append(prop)
        self.session.commit()

        self.assertEqual(len(self.plant.propagations), 1)

    def test_can_add_propagation_multiple_plants(self):
        prop = Propagation(
            date=datetime.today(),
            propagator="Jade Green",
            media="potting mix",
            container="140mm",
            location="table 3",
            prop_notes="Fresh, washed, seed.",
            prop_type=self.seed,
        )
        self.plant.propagations.append(prop)
        prop.plants.append(self.plant2)
        self.session.commit()

        self.assertEqual(len(self.plant.propagations), 1)
        self.assertEqual(len(self.plant2.propagations), 1)

    def test_propagation_string(self):
        prop = Propagation(
            date=datetime.today(),
            propagator="Jade Green",
            media="potting mix",
            container="140mm",
            location="table 3",
            prop_notes="Fresh, washed, seed.",
            prop_type=self.seed,
        )
        self.plant.propagations.append(prop)
        success = self.session.scalar(
            select(PropEventType).filter_by(code="SUCC")
        )
        available = self.session.scalar(
            select(PropEventType).filter_by(code="AVLB")
        )
        event1 = PropEvent(
            date=datetime(2001, 1, 1).date(),
            person="Jade Green",
            quantity=10,
            event_notes="First batch",
            event_type=self.start,
        )
        prop.events.append(event1)
        event2 = PropEvent(
            date=datetime(2001, 2, 1).date(),
            person="Jade Green",
            success=10,
            event_notes="First batch success",
            event_type=success,
        )
        prop.events.append(event2)
        event3 = PropEvent(
            date=datetime(2001, 2, 10).date(),
            person="Jade Green",
            available=10,
            event_notes="First batch available",
            event_type=available,
        )
        prop.events.append(event3)
        self.session.commit()

        today = utils.today_str()
        self.assertEqual(
            str(prop),
            f"Seed; propagated by Jade Green on {today}; Quantity: 10; Media: "
            "potting mix; Container: 140mm; Location: table 3; Notes: Fresh, "
            "washed, seed.; Success: 100.0%; Available: 10",
        )

    def test_propagation_events_no_events(self):
        # test hybrid_property.expressions for established_qty, available_qty,
        # and percent_success and 'children' methods also
        prop = Propagation(
            date=datetime.today(),
            propagator="Jade Green",
            media="potting mix",
            container="140mm",
            location="table 3",
            prop_notes="Fresh, washed, seed.",
            prop_type=self.seed,
        )
        self.plant.propagations.append(prop)
        self.session.commit()

        result, message = hybrid_checker(self.session, prop)
        self.assertTrue(result, message)

    def test_propagation_events_success(self):
        # test hybrid_property.expressions for established_qty, available_qty,
        # and percent_success and 'children' methods also
        prop = Propagation(
            date=datetime.today(),
            propagator="Jade Green",
            media="potting mix",
            container="140mm",
            location="table 3",
            prop_notes="Fresh, washed, seed.",
            prop_type=self.seed,
        )
        self.plant.propagations.append(prop)

        prop.events.append(
            PropEvent(
                quantity=10,
                event_type=self.start,
            )
        )
        self.session.commit()

        result, message = hybrid_checker(
            self.session,
            prop,
            quantity=10,
            total_quantity=10,
        )
        self.assertTrue(result, message)

        prop.events.append(
            PropEvent(
                success=9,
                event_notes="leaves appear",
                event_type=self.success,
            )
        )
        self.session.commit()

        result, message = hybrid_checker(
            self.session,
            prop,
            quantity=10,
            total_quantity=10,
            success=9,
            total_success=9,
            remaining_success=9,
            percent_success=90.0,
        )
        self.assertTrue(result, message)

        prop.events.append(
            PropEvent(
                success=1,
                event_notes="leaves appear",
                event_type=self.success,
            )
        )
        self.session.commit()

        result, message = hybrid_checker(
            self.session,
            prop,
            quantity=10,
            total_quantity=10,
            success=10,
            total_success=10,
            remaining_success=10,
            percent_success=100.0,
        )
        self.assertTrue(result, message)

    def test_propagation_events_culled_qty(self):
        # test hybrid_property.expressions for established_qty, available_qty,
        # and percent_success and 'children' methods also
        prop = Propagation(
            date=datetime.today(),
            propagator="Jade Green",
            media="potting mix",
            container="140mm",
            location="table 3",
            prop_notes="Fresh, washed, seed.",
            prop_type=self.seed,
        )
        self.plant.propagations.append(prop)

        prop.events.append(
            PropEvent(
                quantity=10,
                event_type=self.start,
            )
        )
        prop.events.append(
            PropEvent(
                success=5,
                event_notes="leaves appear",
                event_type=self.success,
            )
        )
        prop.events.append(
            PropEvent(
                quantity=-4,
                event_notes="Unneeded",
                event_type=self.cull_qty,
            )
        )
        self.session.commit()

        result, message = hybrid_checker(
            self.session,
            prop,
            quantity=6,
            total_quantity=10,
            culled_quantity=4,
            success=5,
            total_success=5,
            remaining_success=5,
            percent_success=83.33333333333334,
        )
        self.assertTrue(result, message)

    def test_propagation_events_discard(self):
        prop = Propagation(
            date=datetime.today(),
            propagator="Jade Green",
            media="potting mix",
            container="140mm",
            location="table 3",
            prop_notes="Fresh, washed, seed.",
            prop_type=self.seed,
        )
        self.plant.propagations.append(prop)

        prop.events.append(
            PropEvent(
                quantity=10,
                event_type=self.start,
            )
        )
        prop.events.append(
            PropEvent(
                success=5,
                event_notes="leaves appear",
                event_type=self.success,
            )
        )
        prop.events.append(
            PropEvent(
                available=5,
                event_type=self.available,
            )
        )
        self.session.commit()

        result, message = hybrid_checker(
            self.session,
            prop,
            quantity=10,
            total_quantity=10,
            success=5,
            total_success=5,
            percent_success=50.0,
            available=5,
            made_available=5,
            unused=5,
        )
        self.assertTrue(result, message)

        prop.events.append(
            PropEvent(
                quantity=-5,
                event_notes="reduced to make room.",
                event_type=self.discard,
            )
        )

        result, message = hybrid_checker(
            self.session,
            prop,
            quantity=10,
            total_quantity=10,
            success=5,
            total_success=5,
            percent_success=50.0,
            available=5,
            made_available=5,
            discaded=5,
        )

    def test_propagation_as_source(self):
        prop = Propagation(
            date=datetime.today(),
            propagator="Jade Green",
            media="potting mix",
            container="140mm",
            location="table 3",
            prop_notes="Fresh, washed, seed.",
            prop_type=self.seed,
        )
        self.plant.propagations.append(prop)

        prop.events.append(
            PropEvent(
                quantity=10,
                event_type=self.start,
            )
        )
        prop.events.append(
            PropEvent(
                success=8,
                event_notes="leaves appear",
                event_type=self.success,
            )
        )
        prop.events.append(
            PropEvent(
                available=8,
                event_type=self.available,
            )
        )
        self.session.commit()

        result, message = hybrid_checker(
            self.session,
            prop,
            quantity=10,
            total_quantity=10,
            success=8,
            total_success=8,
            percent_success=80.0,
            available=8,
            made_available=8,
            unused=8,
        )
        self.assertTrue(result, message)

        source = Source(plant_propagation=prop)
        acc1 = Accession(
            code="2001.0002",
            species=self.species,
            quantity_recvd=3,
            source=source,
        )
        self.session.add(acc1)
        self.session.commit()

        result, message = hybrid_checker(
            self.session,
            prop,
            quantity=10,
            total_quantity=10,
            success=8,
            total_success=8,
            percent_success=80.0,
            available=8,
            made_available=8,
            used=3,
            unused=5,
        )
        self.assertTrue(result, message)

        source = Source(plant_propagation=prop)
        acc2 = Accession(
            code="2001.0003",
            species=self.species,
            quantity_recvd=5,
            source=source,
        )
        self.session.add(acc2)
        self.session.commit()

        result, message = hybrid_checker(
            self.session,
            prop,
            quantity=10,
            total_quantity=10,
            success=8,
            total_success=8,
            percent_success=80.0,
            available=8,
            made_available=8,
            used=8,
        )
        self.assertTrue(result, message)


class FunctionTests(BaubleTestCase):
    def test_populate_default_prop_types(self):
        len_prop_types = len(START_DEFAULT_PROP_TYPES)
        prop_types = self.session.scalars(select(PropType)).all()
        self.assertEqual(len(prop_types), 0)

        populate_default_prop_types()

        prop_types = self.session.scalars(select(PropType)).all()
        self.assertEqual(len(prop_types), len_prop_types)

        # second run doesn't change
        populate_default_prop_types()

        prop_types = self.session.scalars(select(PropType)).all()
        self.assertEqual(len(prop_types), len_prop_types)

    def test_populate_default_event_types(self):
        len_event_type = len(START_DEFAULT_EVENT_TYPES)
        event_types = self.session.scalars(select(PropEventType)).all()
        self.assertEqual(len(event_types), 0)

        populate_default_event_types()

        event_types = self.session.scalars(select(PropEventType)).all()
        self.assertEqual(len(event_types), len_event_type)

        # second run doesn't change
        populate_default_event_types()

        event_types = self.session.scalars(select(PropEventType)).all()
        self.assertEqual(len(event_types), len_event_type)
