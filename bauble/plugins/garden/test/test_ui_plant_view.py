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
Plant search view parts.
"""
from datetime import datetime
from unittest import mock

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from bauble.plugins.plants.family import Family
from bauble.plugins.plants.genus import Genus
from bauble.plugins.plants.species import Species
from bauble.test import BaubleTestCase

from ..accession import Accession
from ..location import Location
from ..plant import Plant
from ..plant import PlantChange
from ..propagation import Propagation
from ..source import Source
from ..test_garden import GardenTestCase
from ..ui.plant_view import ChangeBox
from ..ui.plant_view import GeneralPlantExpander
from ..ui.plant_view import PropagationBox
from ..ui.plant_view import remove_callback


class InfoBoxTests(GardenTestCase):
    def test_general_expander(self):
        # at least tests nothing errors
        plants = self.session.query(Plant)

        general = GeneralPlantExpander()
        for plt in plants:
            general.update(plt)
            self.assertEqual(
                general.acc_code_label.get_label(),
                f"<big>{plt.accession}</big>",
            )


class ChangeBoxTests(BaubleTestCase):
    def test_basic(self):
        fam = Family(epithet="Myrtaceae")
        gen = Genus(epithet="Syzygium", family=fam)
        sp = Species(epithet="luehmannii", genus=gen)
        acc = Accession(code="2025.0001", species=sp)
        loc = Location(code="LOC1")
        plt = Plant(code="1", quantity=1, accession=acc, location=loc)
        change = PlantChange(
            date=datetime(2026, 1, 1).date(),
            reason="ESTM",
            quantity=3,
            to_location=loc,
        )
        plt.changes.append(change)

        box = ChangeBox(change)

        self.assertEqual(len(box.get_children()), 3)
        self.assertEqual(
            box.get_children()[0].get_label(),
            "<b>01-01-2026</b>",
        )
        self.assertEqual(
            box.get_children()[1].get_label(),
            "3 Planted (estm.) in LOC1",
        )
        self.assertEqual(
            box.get_children()[2].get_label(),
            "Estimated planting date",
        )
        box.destroy()

        change.reason = "NTRL"
        box = ChangeBox(change)

        self.assertEqual(
            box.get_children()[1].get_label(),
            "3 Captured in LOC1",
        )

        box.destroy()

    def test_transferred(self):
        fam = Family(epithet="Myrtaceae")
        gen = Genus(epithet="Syzygium", family=fam)
        sp = Species(epithet="luehmannii", genus=gen)
        acc = Accession(code="2025.0001", species=sp)
        loc = Location(code="LOC1")
        loc2 = Location(code="LOC2")
        plt = Plant(code="1", quantity=1, accession=acc, location=loc)
        change = PlantChange(
            date=datetime(2026, 1, 1).date(),
            reason="TRAN",
            quantity=3,
            from_location=loc,
            to_location=loc2,
        )
        plt.changes.append(change)

        box = ChangeBox(change)

        self.assertEqual(len(box.get_children()), 3)
        self.assertEqual(
            box.get_children()[0].get_label(),
            "<b>01-01-2026</b>",
        )
        self.assertEqual(
            box.get_children()[1].get_label(),
            "3 Transferred from LOC1 to LOC2",
        )
        self.assertEqual(
            box.get_children()[2].get_label(),
            "Transplanted to another area",
        )

        box.destroy()

    def test_removed(self):
        fam = Family(epithet="Myrtaceae")
        gen = Genus(epithet="Syzygium", family=fam)
        sp = Species(epithet="luehmannii", genus=gen)
        acc = Accession(code="2025.0001", species=sp)
        loc = Location(code="LOC1")
        plt = Plant(code="1", quantity=1, accession=acc, location=loc)
        change = PlantChange(
            date=datetime(2026, 1, 1).date(),
            reason="DEAD",
            quantity=-3,
            from_location=loc,
        )
        plt.changes.append(change)

        box = ChangeBox(change)

        self.assertEqual(len(box.get_children()), 3)
        self.assertEqual(
            box.get_children()[0].get_label(),
            "<b>01-01-2026</b>",
        )
        self.assertEqual(
            box.get_children()[1].get_label(),
            "3 Removed from LOC1",
        )
        self.assertEqual(
            box.get_children()[2].get_label(),
            "Dead",
        )

        box.destroy()

    def test_split_to(self):
        fam = Family(epithet="Myrtaceae")
        gen = Genus(epithet="Syzygium", family=fam)
        sp = Species(epithet="luehmannii", genus=gen)
        acc = Accession(code="2025.0001", species=sp)
        loc = Location(code="LOC1")
        from_plt = Plant(code="1", quantity=1, accession=acc, location=loc)
        to_plt = Plant(code="2", quantity=1, accession=acc, location=loc)
        to_change = PlantChange(
            date=datetime(2026, 1, 1).date(),
            reason="PLTD",
            quantity=-1,
            from_location=loc,
            child_plant=to_plt,
        )
        from_plt.changes.append(to_change)

        box = ChangeBox(to_change)

        self.assertEqual(len(box.get_children()), 4)
        self.assertEqual(
            box.get_children()[0].get_label(),
            "<b>01-01-2026</b>",
        )
        self.assertEqual(
            box.get_children()[1].get_label(),
            "1 Removed from LOC1",
        )
        self.assertEqual(
            box.get_children()[2].get_label(),
            "New planting",
        )
        self.assertEqual(
            box.get_children()[3].get_child().get_label(),
            "<i>Split as 2025.0001.2</i>",
        )

        box.destroy()

    def test_split_from(self):
        fam = Family(epithet="Myrtaceae")
        gen = Genus(epithet="Syzygium", family=fam)
        sp = Species(epithet="luehmannii", genus=gen)
        acc = Accession(code="2025.0001", species=sp)
        loc = Location(code="LOC1")
        from_plt = Plant(code="1", quantity=1, accession=acc, location=loc)
        to_plt = Plant(code="2", quantity=1, accession=acc, location=loc)
        from_change = PlantChange(
            date=datetime(2026, 1, 1).date(),
            reason="PLTD",
            quantity=1,
            to_location=loc,
            child_plant=to_plt,
            parent_plant=from_plt,
        )
        to_plt.changes.append(from_change)

        box = ChangeBox(from_change)

        self.assertEqual(len(box.get_children()), 5)
        self.assertEqual(
            box.get_children()[0].get_label(),
            "<b>01-01-2026</b>",
        )
        self.assertEqual(
            box.get_children()[1].get_label(),
            "1 Planted in LOC1",
        )
        self.assertEqual(
            box.get_children()[2].get_label(),
            "New planting",
        )
        self.assertEqual(
            box.get_children()[3].get_child().get_label(),
            "<i>Split from 2025.0001.1</i>",
        )

        box.destroy()

    def test_fallback(self):
        # a change that shouldn't exist (an error)
        fam = Family(epithet="Myrtaceae")
        gen = Genus(epithet="Syzygium", family=fam)
        sp = Species(epithet="luehmannii", genus=gen)
        acc = Accession(code="2025.0001", species=sp)
        loc = Location(code="LOC1")
        plt = Plant(code="1", quantity=1, accession=acc, location=loc)
        change = PlantChange(
            date=datetime(2026, 1, 1).date(),
            quantity=0,
            to_location=loc,
        )
        plt.changes.append(change)

        box = ChangeBox(change)

        self.assertEqual(len(box.get_children()), 2)
        self.assertEqual(
            box.get_children()[0].get_label(),
            "<b>01-01-2026</b>",
        )
        self.assertEqual(
            box.get_children()[1].get_label(),
            "0: None -> LOC1",
        )

        box.destroy()


class PropagationBoxTests(BaubleTestCase):
    def test_basic(self):
        date = datetime(2001, 1, 1, 0)
        fam = Family(epithet="Myrtaceae")
        gen = Genus(epithet="Syzygium", family=fam)
        sp = Species(epithet="luehmannii", genus=gen)
        acc = Accession(code="2015.0001", species=sp)
        loc = Location(code="LOC1")
        plt = Plant(
            code="1",
            quantity=1,
            accession=acc,
            location=loc,
            _last_updated=date,
        )
        prop = Propagation(
            prop_type="Other",
            notes="Spam spam spam spam",
            date=date,
        )
        plt.propagations.append(prop)
        acc2 = Accession(code="2025.0001", species=sp)
        acc2.source = Source(plant_propagation=prop)
        acc2.source.propagation = prop
        self.session.add(plt)
        self.session.commit()

        box = PropagationBox(prop)

        self.assertEqual(len(box.get_children()), 3)
        self.assertEqual(
            box.get_children()[0].get_label(),
            "<b>01-01-2001</b>",
        )
        self.assertEqual(
            box.get_children()[1].get_label(),
            "Other; Spam spam spam spam",
        )
        self.assertEqual(
            box.get_children()[2].get_children()[0].get_label(),
            "Parent of:",
        )
        self.assertEqual(
            box.get_children()[2].get_children()[1].get_child().get_label(),
            "2025.0001",
        )

        box.destroy()


class FunctionTests(BaubleTestCase):
    def test_remove_callback_no_confirm(self):
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
        plant2 = Plant(
            accession=accession,
            location=location,
            code="2",
            quantity=1,
        )
        self.session.add_all([plant, plant2])
        self.session.commit()

        with mock.patch("bauble.ui.dialogs.yes_no_dialog") as mock_dlog:
            mock_dlog.return_value = False
            result = remove_callback([plant, plant2])
            mock_dlog.assert_called_once_with(
                "Are you sure you want to remove the following plants?\n\n"
                "2001.0001.1, 2001.0001.2\n\n<small>Note that deleting a "
                "plant can destroy related data.  If the plant has died set "
                "its quantity to zero rather than delete it.</small>",
            )

        self.assertFalse(result)
        self.assertCountEqual(
            self.session.scalars(
                select(Plant).where(Plant.accession == accession)
            ).all(),
            [plant, plant2],
        )

    def test_remove_callback_confirm(self):
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
        self.session.add(plant)
        self.session.flush()

        with mock.patch("bauble.ui.dialogs.yes_no_dialog") as mock_dlog:
            mock_dlog.return_value = True
            result = remove_callback([plant])
            mock_dlog.assert_called_once_with(
                "Are you sure you want to remove the following plants?\n\n"
                "2001.0001.1\n\n<small>Note that deleting a plant "
                "can destroy related data.  If the plant has died set its "
                "quantity to zero rather than delete it.</small>",
            )

        self.assertTrue(result)
        self.assertCountEqual(
            self.session.scalars(
                select(Plant).where(Plant.accession == accession)
            ).all(),
            [],
        )

    @mock.patch("bauble.ui.dialogs.yes_no_dialog")
    def test_remove_callback_with_branches_asks(self, mock_dlog):
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
            quantity=2,
        )
        self.session.add(plant)
        self.session.commit()
        plant.quantity = 1
        plant2 = Plant(
            accession=accession,
            location=location,
            code="2",
            quantity=1,
        )
        plant.changes.append(
            PlantChange(
                date=datetime(2026, 1, 1),
                reason="PLTD",
                quantity=-1,
                child_plant=plant2,
            )
        )
        plant2.changes.append(
            PlantChange(
                date=datetime(2026, 1, 1),
                reason="PLTD",
                quantity=1,
                parent_plant=plant,
            )
        )
        self.session.add(plant2)
        self.session.commit()

        mock_dlog.side_effect = [True, False]
        result = remove_callback([plant])
        mock_dlog.assert_has_calls(
            [
                mock.call(
                    "Are you sure you want to remove the following plants?\n\n"
                    "2001.0001.1\n\n<small>Note that deleting a plant can "
                    "destroy related data.  If the plant has died set its "
                    "quantity to zero rather than delete it.</small>",
                ),
                mock.call(
                    "2001.0001.1 has plant(s) split from it.  Removing this "
                    "plant will destroy their link back.  Are you sure you "
                    "want to want to delete it?"
                ),
            ]
        )

        self.assertFalse(result)
        self.assertCountEqual(
            self.session.scalars(
                select(Plant).where(Plant.accession == accession)
            ).all(),
            [plant, plant2],
        )

    @mock.patch("bauble.ui.dialogs.yes_no_dialog")
    def test_remove_callback_with_propagations_asks(self, mock_dlog):
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
            quantity=2,
        )
        plant.propagations.append(
            Propagation(
                prop_type="Other",
                notes="Spam spam spam spam",
                date=datetime(2026, 1, 1),
            )
        )
        self.session.add(plant)
        self.session.commit()

        mock_dlog.side_effect = [True, False]
        result = remove_callback([plant])
        mock_dlog.assert_has_calls(
            [
                mock.call(
                    "Are you sure you want to remove the following plants?\n\n"
                    "2001.0001.1\n\n<small>Note that deleting a plant can "
                    "destroy related data.  If the plant has died set its "
                    "quantity to zero rather than delete it.</small>",
                ),
                mock.call(
                    "2001.0001.1 has propagations.  Removing this plant will "
                    "destroy these propagations and possibly the source data "
                    "for any accessions created from them.  Are you sure you "
                    "want to want to delete it?"
                ),
            ]
        )

        self.assertFalse(result)
        self.assertCountEqual(
            self.session.scalars(
                select(Plant).where(Plant.accession == accession)
            ).all(),
            [plant],
        )

    def test_remove_callback_bails_not_session(self):
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
        self.session.add(plant)
        self.session.flush()

        with mock.patch("bauble.plugins.garden.ui.plant_view.object_session"):
            self.assertFalse(remove_callback([plant]))

    @mock.patch("bauble.ui.dialogs.yes_no_dialog")
    @mock.patch("bauble.ui.dialogs.message_details_dialog")
    def test_remove_callback_commit_exception(
        self,
        mock_d_dlog,
        _mock_yn_dlog,
    ):
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
        self.session.add(plant)
        self.session.commit()

        with (
            mock.patch.object(
                self.session, "commit", side_effect=SQLAlchemyError("BOOM")
            ),
            mock.patch.object(self.session, "rollback") as mock_rollback,
        ):
            self.assertFalse(remove_callback([plant]))
            mock_rollback.assert_called_once()
            mock_d_dlog.assert_called_once()
