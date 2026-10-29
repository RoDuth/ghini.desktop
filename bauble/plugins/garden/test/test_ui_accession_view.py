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
Accession search view tests
"""

from bauble.test import BaubleTestCase

from ...plants.test.test_plants import setUp_data as setup_plants_data
from ..accession import Accession
from ..accession import IntendedLocation
from ..location import Location
from ..plant import Plant
from ..source import Source
from ..test_garden import setUp_data as setup_garden_data
from ..ui.accession_view import GeneralAccessionExpander
from ..ui.accession_view import SourceExpander


class InfoBoxTests(BaubleTestCase):
    def test_general_expander(self):
        setup_plants_data()
        setup_garden_data()
        # at least tests nothing errors
        accessions = self.session.query(Accession).filter(
            Accession.id.in_((1, 2, 5, 7))
        )
        general = GeneralAccessionExpander()
        for acc in accessions:
            general.update(acc)

            self.assertEqual(
                general.code_label.get_label(), f"<big>{acc.code}</big>"
            )
            self.assertEqual(
                general.name_label.get_label(),
                f"{acc.species_str(markup=True, authors=True)}",
            )

        acc7 = self.session.get(Accession, 7)
        acc7.prov_type = "Wild"
        acc7.wild_prov_status = "WildNative"
        loc1 = self.session.get(Location, 1)
        acc7.intended_locations.append(
            IntendedLocation(quantity=5, location=loc1)
        )
        self.session.commit()
        general.update(acc7)

        self.assertEqual(
            general.living_plants_label.get_label(),
            "0",
        )
        self.assertEqual(
            general.intended_locations_label.get_label(),
            "(RBW) Somewhere Over The Rainbow : 5",
        )
        self.assertEqual(
            general.provenance_label.get_label(),
            "Accession of wild source (Wild native)",
        )

    def test_source_expander(self):
        setup_plants_data()
        setup_garden_data()
        accessions = self.session.query(Accession).filter(
            Accession.id.in_((1, 2, 5, 7))
        )
        expander = SourceExpander()
        for acc in accessions:
            expander.update(acc)

            self.assertFalse(expander.propagation_label.get_visible())
            if acc.source:
                self.assertTrue(expander.get_sensitive())
            else:
                self.assertFalse(expander.get_sensitive())
                continue

            if acc.source.source_detail:
                self.assertEqual(
                    expander.source_name_data_label.get_label(),
                    str(acc.source.source_detail),
                )
            else:
                self.assertFalse(expander.source_name_data_label.get_visible())
            self.assertEqual(len(expander.parent_plants_box), 0)

        acc7 = self.session.get(Accession, 7)
        plt1 = self.session.get(Plant, 1)
        prop = plt1.propagations[0]
        acc7.source = Source(plant_propagation=prop)

        expander.update(acc7)

        self.assertEqual(len(expander.parent_plants_box), 1)
        self.assertTrue(expander.parent_plants_box.get_visible())

        plant_boxes = expander.parent_plants_box.get_children()
        first_box = plant_boxes[0]
        event_box = first_box.get_children()[0]
        label = event_box.get_child()
        type_label = first_box.get_children()[1]

        self.assertEqual(label.get_label(), str(plt1))
        self.assertEqual(type_label.get_label(), " (Seed - Primary)")
        self.assertEqual(
            expander.propagation_code_label.get_label(),
            "2023S/1",
        )
        self.assertEqual(
            expander.propagation_data_label.get_label(),
            str(prop),
        )

        # back to no propagation source destroys and hides
        acc1 = self.session.get(Accession, 1)

        expander.update(acc1)

        self.assertEqual(len(expander.parent_plants_box), 0)
        self.assertFalse(expander.parent_plants_box.get_visible())
