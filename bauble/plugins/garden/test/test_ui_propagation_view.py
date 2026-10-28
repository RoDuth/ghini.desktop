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

from sqlalchemy import select

from bauble import utils
from bauble.test import BaubleTestCase

from ...garden.source import Source
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


class InfoBoxTests(BaubleTestCase):

    def test_general_propagation_expander_update(self):
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
        source = Source(plant_propagation=prop)
        prop_acc = Accession(
            date_recvd=datetime(2001, 3, 10).date(),
            code="2001.0002",
            species=lc_caligula,
            quantity_recvd=3,
            source=source,
        )
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
