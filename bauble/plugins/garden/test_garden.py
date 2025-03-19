# Copyright 2008-2010 Brett Adams
# Copyright 2015,2017 Mario Frasca <mario@anche.no>.
# Copyright 2017 Jardín Botánico de Quito
# Copyright 2021-2025 Ross Demuth <rossdemuth123@gmail.com>
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

import datetime
import gc
import logging
import os
import unittest
from functools import partial

logger = logging.getLogger(__name__)

from gi.repository import Gtk
from sqlalchemy import and_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import object_session

from bauble import db
from bauble import meta
from bauble import prefs
from bauble import utils
from bauble.meta import BaubleMeta
from bauble.test import BaubleTestCase
from bauble.test import check_dupids
from bauble.test import mockfunc
from bauble.test import update_gui
from bauble.view import get_search_view

from ..plants import test_plants as plants_test
from ..plants.family import Family
from ..plants.genus import Genus
from ..plants.geography import Geography
from ..plants.species_model import Species
from ..plants.species_model import SpeciesDistribution
from ..plants.species_model import _remove_zws as remove_zws
from ..plants.species_model import update_all_full_names_task
from . import SORT_BY_PREF
from . import GardenPlugin
from . import get_plant_completions
from .accession import INTENDED_ACTIONGRP_NAME
from .accession import Accession
from .accession import AccessionEditor
from .accession import AccessionEditorPresenter
from .accession import AccessionEditorView
from .accession import IntendedLocation
from .accession import IntendedLocationPresenter
from .accession import SourcePresenter
from .accession import Verification
from .accession import VerificationBox
from .accession import VerificationPresenter
from .accession import Voucher
from .accession import VoucherPresenter
from .accession import dms_to_decimal
from .accession import latitude_to_dms
from .accession import longitude_to_dms
from .institution import Institution
from .institution import InstitutionCommand
from .institution import InstitutionDialog
from .institution import InstitutionTool
from .institution import start_institution_editor
from .location import Location
from .location import LocationEditor
from .location import LocationPicture
from .plant import DEFAULT_PLANT_CODE_FORMAT
from .plant import PLANT_CODE_FORMAT_KEY
from .plant import Plant
from .plant import PlantChange
from .plant import PlantEditor
from .plant import PlantEditorPresenter
from .plant import PlantEditorView
from .plant import PlantNote
from .plant import PlantPicture
from .plant import acc_to_string_matcher
from .plant import added_reasons
from .plant import branch_callback
from .plant import change_reasons
from .plant import deleted_reasons
from .plant import get_next_code
from .plant import is_code_unique
from .plant import set_code_format
from .plant import transfer_reasons
from .propagation import PlantPropagation
from .propagation import Propagation
from .propagation import PropagationEditor
from .propagation import PropCutting
from .propagation import PropCuttingRooted
from .propagation import PropSeed
from .source import Collection
from .source import CollectionPresenter
from .source import Source
from .source import SourceDetail
from .source import SourceDetailPresenter

accession_test_data = (
    {
        "id": 1,
        "code": "2001.1",
        "species_id": 1,
        "private": True,
        "date_accd": datetime.date(2024, 1, 1),
        "date_recvd": datetime.date(2024, 1, 1),
        "recvd_type": "BULB",
        "quantity_recvd": 1,
        "purchase_price": 10,
    },
    {"id": 2, "code": "2001.2", "species_id": 2, "source_type": "Collection"},
    {"id": 3, "code": "2020.1", "species_id": 1, "source_type": "Collection"},
    {"id": 4, "code": "2020.2", "species_id": 2, "source_type": "Individual"},
    {"id": 5, "code": "2022.1", "species_id": 3, "source_type": "Individual"},
    {
        "id": 6,
        "code": "2022.2",
        "species_id": 3,
        "id_qual": "?",
        "id_qual_rank": "sp",
    },
    {"id": 7, "code": "2022.3", "species_id": 27},
)

accession_verification_test_data = (
    {
        "accession_id": 1,
        "verifier": "Jade Green",
        "date": datetime.date(2023, 1, 1),
        "level": 2,
        "species_id": 2,
        "prev_species_id": 1,
        "notes": "some notes",
        "reference": "a book",
    },
)

accession_voucher_test_data = (
    {
        "herbarium": "BRI",
        "code": "ABC123",
        "parent_material": True,
        "accession_id": 1,
    },
    {
        "herbarium": "BRI",
        "code": "ABC321",
        "parent_material": False,
        "accession_id": 1,
    },
)

plant_test_data = (
    {"id": 1, "code": "1", "accession_id": 1, "location_id": 1, "quantity": 1},
    {"id": 2, "code": "1", "accession_id": 2, "location_id": 1, "quantity": 1},
    {"id": 3, "code": "2", "accession_id": 2, "location_id": 1, "quantity": 1},
    {"id": 4, "code": "1", "accession_id": 5, "location_id": 1, "quantity": 0},
    {"id": 5, "code": "1", "accession_id": 6, "location_id": 1, "quantity": 3},
)

plant_change_test_data = (
    {
        "id": 1,
        "plant_id": 1,
        "from_location_id": 2,
        "to_location_id": 1,
        "quantity": 1,
    },
)

plant_seedprop_test_data = (
    {
        "pretreatment": "Soaked in peroxide solution",
        "nseeds": 24,
        "date_sown": datetime.date(2023, 1, 1),
        "container": "tray",
        "location": "mist tent",
        "moved_from": "mist tent",
        "moved_to": "hardening table",
        "media": "standard mix",
        "germ_date": datetime.date(2023, 2, 1),
        "germ_pct": 99,
        "nseedlings": 23,
        "date_planted": datetime.date(2023, 2, 8),
        "propagation_id": 1,
    },
)

propagation_test_data = (
    {
        "id": 1,
        "prop_type": "Seed",
        "notes": "Some note",
        "date": datetime.date(2023, 1, 1),
    },
)

plant_propagation_test_data = ({"id": 1, "plant_id": 1, "propagation_id": 1},)

location_test_data = (
    {"id": 1, "name": "Somewhere Over The Rainbow", "code": "RBW"},
    {"id": 2, "name": "Somewhere Under The Rainbow", "code": "URBW"},
    {"id": 3, "name": "Somewhere Else", "code": "SE"},
)

geography_test_data = [
    {
        "id": 1,
        "code": "SWH",
        "name": "Somewhere",
        "level": 1,
        "approx_area": 10,
        "geojson": {
            "type": "Polygon",
            "coordinates": [
                [
                    [167.96496, -29.081111],
                    [167.91247, -29.005279],
                    [167.96496, -29.081111],
                ]
            ],
        },
    },
    {
        "id": 2,
        "code": "SWH-SA",
        "name": "SomewhereSubArea",
        "parent_id": 1,
        "level": 2,
        "approx_area": 20,
        "geojson": {
            "type": "Polygon",
            "coordinates": [
                [
                    [167.9649658203125, -29.081111907958984],
                    [167.9124755859375, -29.005279541015625],
                    [167.9649658203125, -29.081111907958984],
                ]
            ],
        },
    },
]


source_detail_data = (
    {"id": 1, "name": "Jade Green", "source_type": "Individual"},
)

source_test_data = (
    {"id": 1, "accession_id": 2},
    {"id": 2, "accession_id": 3},
    {"id": 3, "accession_id": 4, "source_detail_id": 1},
    {"id": 4, "accession_id": 5, "source_detail_id": 1},
    {
        "id": 5,
        "accession_id": 1,
        "source_detail_id": 1,
        "sources_code": "AB1",
        "notes": "SOURCE NOTE",
    },
)

collection_test_data = (
    {
        "id": 1,
        "source_id": 1,
        "locale": "Somewhere",
        "collector": "Someone",
        "collectors_code": "1111",
        "geography_id": 1,
    },
    {
        "id": 2,
        "source_id": 2,
        "locale": "Somewhere Else",
        "collector": "Someone Else",
        "collectors_code": "2222",
        "geography_id": 1,
    },
    {
        "id": 3,
        "source_id": 5,
        "locale": "Somewhere",
        "date": datetime.date(2011, 11, 25),
        "collector": "me",
        "collectors_code": "1234",
        "geography_id": 1,
        "latitude": "89.876",
        "longitude": "87.654",
        "gps_datum": "WGS 84",
        "geo_accy": 10.01,
        "elevation": 1010.10,
        "elevation_accy": 10.10,
        "habitat": "Various species",
        "notes": "Some notes",
    },
)

# needs to be here (not in test_plants) or will fail in postgresql
species_distribution_test_data = (
    {"species_id": 3, "geography_id": 1},
    {"species_id": 1, "geography_id": 1},
)

default_propagation_values = {
    "notes": "test notes",
    "date": datetime.date(2011, 11, 25),
}

default_cutting_values = {
    "cutting_type": "Nodal",
    "length": 2,
    "length_unit": "mm",
    "tip": "Intact",
    "leaves": "Intact",
    "leaves_reduced_pct": 25,
    "flower_buds": "None",
    "wound": "Single",
    "fungicide": "Physan",
    "media": "standard mix",
    "container": '4" pot',
    "hormone": "Auxin powder",
    "cover": "Poly cover",
    "location": "Mist frame",
    "bottom_heat_temp": 65,
    "bottom_heat_unit": "F",
    "rooted_pct": 90,
}

default_seed_values = {
    "pretreatment": "Soaked in peroxide solution",
    "nseeds": 24,
    "date_sown": datetime.date(2017, 1, 1),
    "container": "tray",
    "location": "mist tent",
    "moved_from": "mist tent",
    "moved_to": "hardening table",
    "media": "standard mix",
    "germ_date": datetime.date(2017, 2, 1),
    "germ_pct": 99,
    "nseedlings": 23,
    "date_planted": datetime.date(2017, 2, 8),
}

test_data_table_control = (
    (Location, location_test_data),
    (Geography, geography_test_data),
    (SpeciesDistribution, species_distribution_test_data),
    (Accession, accession_test_data),
    (Verification, accession_verification_test_data),
    (Voucher, accession_voucher_test_data),
    (SourceDetail, source_detail_data),
    (Source, source_test_data),
    (Plant, plant_test_data),
    (PlantChange, plant_change_test_data),
    (Propagation, propagation_test_data),
    (PropSeed, plant_seedprop_test_data),
    (PlantPropagation, plant_propagation_test_data),
    (Collection, collection_test_data),
)

testing_today = datetime.date(2017, 1, 1)


def setUp_data():
    """
    create_test_data()
    # if this method is called again before tearDown_test_data is called you
    # will get an error about the test data rows already existing in the
    # database
    """
    for cls, data in test_data_table_control:
        table = cls.__table__
        for row in data:
            table.insert().execute(row).close()
        for col in table.c:
            utils.reset_sequence(col)
    inst = Institution()
    inst.name = "TestInstitution"
    inst.technical_contact = "TestTechnicalContact Name"
    inst.email = "contact@test.com"
    inst.contact = "TestContact Name"
    inst.code = "TestCode"
    inst.write()


setUp_data.order = 1  # type: ignore [attr-defined]


# TODO: if we ever get a GUI tester then do the following
# test all possible combinations of entering data into the accession editor
# 1. new accession without source
# 2. new accession with source
# 3. existing accession without source
# 4. existing accession with new source
# 5. existing accession with existing source
# - create test for parsing latitude/longitude entered into the lat/lon entries


class DuplicateIdsGlade(unittest.TestCase):
    def test_duplicate_ids(self):
        """
        Test for duplicate ids for all .glade files in the gardens plugin.
        """
        import glob

        import bauble.plugins.garden as mod

        head, tail = os.path.split(mod.__file__)
        files = glob.glob(os.path.join(head, "*.glade"))
        for f in files:
            self.assertTrue(not check_dupids(f), f)


class GardenTestCase(BaubleTestCase):
    def setUp(self):
        super().setUp()
        plants_test.setUp_data()
        setUp_data()
        self.family = Family(family="Cactaceae")
        self.genus = Genus(family=self.family, genus="Echinocactus")
        self.species = Species(genus=self.genus, sp="grusonii")
        self.sp2 = Species(genus=self.genus, sp="texelensis")
        self.session.add_all([self.family, self.genus, self.species, self.sp2])
        self.session.commit()

    def create(self, class_, **kwargs):
        obj = class_(**kwargs)
        self.session.add(obj)
        return obj


class PlantTests(GardenTestCase):
    def setUp(self):
        super().setUp()
        self.accession = self.create(Accession, species=self.species, code="1")
        self.location = self.create(Location, name="site", code="STE")
        self.plant = self.create(
            Plant,
            accession=self.accession,
            location=self.location,
            code="1",
            quantity=1,
        )
        self.session.add_all([self.accession, self.location, self.plant])
        self.session.commit()

    def tearDown(self):
        super().tearDown()

    def test_constraints(self):
        """
        Test the contraints on the plant table.
        """
        # test that we can't have duplicate codes with the same accession
        plant2 = Plant(
            accession=self.accession,
            location=self.location,
            code=self.plant.code,
            quantity=1,
        )
        self.session.add(plant2)
        self.assertRaises(IntegrityError, self.session.commit)
        # rollback the IntegrityError so tearDown() can do its job
        self.session.rollback()

    def test_delete(self):
        """
        Test that when a plant is deleted so are its changes (and not its
        location)
        """
        plt = self.create(
            Plant,
            accession=self.accession,
            quantity=1,
            location=self.location,
            code="2",
        )

        self.session.commit()
        planted = plt.planted
        planted_id = planted.id
        self.session.delete(plt)
        self.session.commit()
        self.assertFalse(self.session.query(PlantChange).get(planted_id))
        self.assertTrue(self.session.query(Location).get(self.location.id))

    def test_duplicate(self):
        """
        Test Plant.duplicate()
        """
        p = Plant(
            accession=self.accession,
            location=self.location,
            code="2",
            quantity=52,
        )
        self.session.add(p)
        note = PlantNote(note="some note")
        note.plant = p
        note.date = datetime.date.today()
        change = PlantChange(
            from_location=self.location, to_location=self.location, quantity=1
        )
        change.plant = p
        self.session.commit()
        dup = p.duplicate(code="3")
        assert dup.notes is not []
        assert dup.changes is not []
        self.session.commit()

    def test_search_view_markup_pair(self):
        # living plant
        p = Plant(
            accession=self.accession,
            location=self.location,
            code="2",
            quantity=52,
        )
        self.session.add(p)
        self.assertEqual(
            p.search_view_markup_pair(),
            (
                '1.2 <span foreground="#555555" size="small" '
                'weight="light">- 52 alive in (STE) site</span>',
                "<i>Echinocactus</i> <i>grusonii</i>   "
                '<span weight="light">(Cactaceae)</span>',
            ),
        )
        # dead plant
        p = Plant(
            accession=self.accession,
            location=self.location,
            code="2",
            quantity=0,
        )
        self.session.add(p)
        self.assertEqual(
            p.search_view_markup_pair(),
            (
                '<span foreground="#9900ff">1.2</span>',
                "<i>Echinocactus</i> <i>grusonii</i>   "
                '<span weight="light">(Cactaceae)</span>',
            ),
        )

    def test_bulk_plant_editor(self):
        """
        Test creating multiple plants with the plant editor.
        """

        # use our own plant because PlantEditor.commit_changes() will
        # only work in bulk mode when the plant is in session.new
        p = Plant(
            accession=self.accession,
            location=self.location,
            code="2",
            quantity=52,
        )
        editor = PlantEditor(model=p)
        # editor.start()
        update_gui()
        rng = "2,3,4-6"

        for code in utils.range_builder(rng):
            q = (
                self.session.query(Plant)
                .join("accession")
                .filter(
                    and_(
                        Accession.id == self.plant.accession.id,
                        Plant.code == utils.nstr(code),
                    )
                )
            )
            self.assertTrue(not q.first(), "code already exists")

        widgets = editor.presenter.view.widgets
        # make sure the entry gets a Problem added to it if an
        # existing plant code is used in bulk mode
        widgets.plant_code_entry.set_text("1," + rng)
        widgets.plant_quantity_entry.set_text("2")
        update_gui()
        problem = (
            editor.presenter.PROBLEM_DUPLICATE_PLANT_CODE,
            editor.presenter.view.widgets.plant_code_entry,
        )
        self.assertTrue(
            problem in editor.presenter.problems,
            "no problem added for duplicate plant code",
        )

        # create multiple plant codes
        widgets.plant_code_entry.set_text(rng)
        update_gui()
        editor.handle_response(Gtk.ResponseType.OK)
        editor.presenter.cleanup()
        del editor

        for code in utils.range_builder(rng):
            q = (
                self.session.query(Plant)
                .join("accession")
                .filter(
                    and_(
                        Accession.id == self.plant.accession.id,
                        Plant.code == utils.nstr(code),
                    )
                )
            )
            self.assertTrue(
                q.first(), "plant %s.%s not created" % (self.accession, code)
            )
            self.assertIsNotNone(q.first().location_id)
            # test a planted change was created
            plt = q.first()
            self.assertIsNotNone(plt.planted)
            self.assertEqual(plt.planted.to_location, self.location)
            self.assertEqual(plt.planted.quantity, plt.quantity)

    @unittest.mock.patch("bauble.editor.GenericEditorView.start")
    def test_editor_doesnt_leak(self, mock_start):
        # garbage collect before start..
        gc.collect()
        mock_start.return_value = Gtk.ResponseType.OK
        loc = Location(name="site1", code="1")
        plt = Plant(accession=self.accession, location=loc, quantity=1)
        editor = PlantEditor(model=plt)
        editor.start()
        del editor
        gc.collect()
        self.assertEqual(
            utils.gc_objects_by_type("PlantEditor"),
            [],
            "PlantEditor not deleted",
        )
        self.assertEqual(
            utils.gc_objects_by_type("PlantEditorPresenter"),
            [],
            "PlantEditorPresenter not deleted",
        )
        self.assertEqual(
            utils.gc_objects_by_type("PlantEditorView"),
            [],
            "PlantEditorView not deleted",
        )

    @unittest.mock.patch("bauble.editor.GenericEditorView.start")
    def test_editor_doesnt_leak_branch_mode(self, mock_start):
        # garbage collect before start..
        gc.collect()
        mock_start.return_value = Gtk.ResponseType.OK
        loc = Location(name="site1", code="1")
        plt = Plant(
            accession=self.accession, location=loc, quantity=10, code="2"
        )
        self.session.add_all([plt, loc])
        self.session.commit()
        self.session.refresh(loc)  # or we get a foreign_keys constraint error
        editor = PlantEditor(model=plt, branch_mode=True)
        editor.start()
        del editor
        gc.collect()
        self.assertEqual(
            utils.gc_objects_by_type("PlantEditor"),
            [],
            "PlantEditor not deleted",
        )
        self.assertEqual(
            utils.gc_objects_by_type("PlantEditorPresenter"),
            [],
            "PlantEditorPresenter not deleted",
        )
        self.assertEqual(
            utils.gc_objects_by_type("PlantEditorView"),
            [],
            "PlantEditorView not deleted",
        )

    def test_remove_callback(self):
        # action
        self.invoked = []
        orig_yes_no_dialog = utils.yes_no_dialog
        utils.yes_no_dialog = partial(
            mockfunc, name="yes_no_dialog", caller=self, result=True
        )
        from bauble.plugins.garden.plant import remove_callback

        result = remove_callback([self.plant])
        self.assertTrue(result)
        self.session.flush()

        # effect
        self.assertTrue("yes_no_dialog" in [f for (f, m) in self.invoked])
        match = (
            self.session.query(Plant).filter_by(accession=self.accession).all()
        )
        self.assertEqual(match, [])
        utils.yes_no_dialog = orig_yes_no_dialog

    def test_branch_change(self):
        plant = Plant(
            accession=self.accession,
            code="11",
            location=self.location,
            quantity=10,
        )
        loc2a = Location(name="site2a", code="2a")
        self.session.add_all([plant, loc2a])
        self.session.commit()
        editor = PlantEditor(model=plant, branch_mode=True)
        loc2a = (
            object_session(editor.model)
            .query(Location)
            .filter(Location.code == "2a")
            .one()
        )
        editor.model.location = loc2a
        editor.model.quantity = 3
        editor.compute_plant_split_changes()

        self.assertEqual(editor.model.quantity, 3)
        change = editor.model.changes[0]
        self.assertEqual(change.parent_plant, editor.branched_plant)
        self.assertEqual(change.plant, editor.model)
        self.assertEqual(change.quantity, editor.model.quantity)
        self.assertEqual(change.to_location, editor.model.location)
        self.assertEqual(change.from_location, editor.branched_plant.location)

        self.assertEqual(editor.branched_plant.quantity, 7)
        # first change is planting second is the split
        change = editor.branched_plant.changes[1]
        self.assertEqual(change.child_plant, editor.model)
        self.assertEqual(change.plant, editor.branched_plant)
        self.assertEqual(change.quantity, editor.model.quantity)
        self.assertEqual(change.to_location, editor.model.location)
        self.assertEqual(change.from_location, editor.branched_plant.location)
        editor.presenter.cleanup()
        del editor

    def test_branch_and_then_delete_parent(self):
        plant = Plant(
            accession=self.accession,
            code="11",
            location=self.location,
            quantity=10,
        )
        loc2a = Location(name="site2a", code="2a")
        self.session.add_all([plant, loc2a])
        self.session.commit()
        editor = PlantEditor(model=plant, branch_mode=True)
        loc2a = (
            object_session(editor.model)
            .query(Location)
            .filter(Location.code == "2a")
            .one()
        )
        editor.model.location = loc2a
        editor.model.quantity = 3
        update_gui()
        editor.handle_response(Gtk.ResponseType.OK)
        editor.presenter.cleanup()
        del editor
        # test that if we delete the original plant using remove_callback it
        # doesn't error, fail or delete the planting date of the split plant
        # NOTE in the above self.session is equivalent to the searchview's
        # session. Branching the plant is done within the editors session.
        # If the searchview is unchanged and the original plant deleted an
        # error can occur if plant.duplication is called on the instance in
        # searchview's session not the editors.
        from bauble.plugins.garden.plant import remove_callback

        with unittest.mock.patch("bauble.utils.yes_no_dialog") as mock_dialog:
            mock_dialog.return_value = True
            result = remove_callback([plant])
            self.assertTrue(result)
            mock_dialog.assert_called()

        qry = self.session.query(Plant).filter_by(accession=self.accession)
        match = qry.filter_by(code="11").all()
        self.assertEqual(match, [])
        splt = qry.filter_by(quantity=3).all()
        self.assertEqual(len(splt), 1)
        # test that the parent_plant entry in the change is nullified
        # rather than deleting the whole change.  (which would lose the
        # planted entry and all data with it.)
        self.assertTrue(splt[0].planted)
        self.assertTrue(splt[0].planted.from_location)
        self.assertTrue(splt[0].planted.to_location)
        self.assertFalse(splt[0].planted.parent_plant)

    def test_bulk_branch(self):
        # create a plant with sufficient quantity
        plant = Plant(
            accession=self.accession,
            code="5",
            location=self.location,
            quantity=20,
        )
        loc2a = Location(name="site2a", code="2a")
        self.session.add_all([plant, loc2a])
        self.session.commit()
        editor = PlantEditor(model=plant, branch_mode=True)
        loc2a = (
            object_session(editor.branched_plant)
            .query(Location)
            .filter(Location.code == "2a")
            .one()
        )
        editor.model.location = loc2a
        widgets = editor.presenter.view.widgets
        rng = "6-9"
        widgets.plant_code_entry.set_text(rng)
        widgets.plant_quantity_entry.set_text("8")
        update_gui()
        problem = (
            editor.presenter.PROBLEM_INVALID_QUANTITY,
            editor.presenter.view.widgets.plant_quantity_entry,
        )
        self.assertTrue(problem in editor.presenter.problems)
        widgets.plant_quantity_entry.set_text("3")
        update_gui()
        editor.handle_response(Gtk.ResponseType.OK)

        for code in utils.range_builder(rng):
            q = (
                self.session.query(Plant)
                .join("accession")
                .filter(
                    and_(
                        Accession.id == plant.accession.id,
                        Plant.code == str(code),
                    )
                )
            )
            self.assertIsNotNone(q.first())
            plt = q.first()
            self.assertEqual(plt.quantity, 3)
            self.assertEqual(plt.location.code, loc2a.code)
            # test a planted change was created with appropriate values
            self.assertIsNotNone(plt.planted)
            self.assertEqual(plt.planted.parent_plant, plant)
            self.assertEqual(plt.planted.from_location, plant.location)
            self.assertEqual(plt.planted.to_location, plt.location)
            self.assertEqual(plt.planted.quantity, plt.quantity)
            q2 = self.session.query(PlantChange).filter(
                and_(
                    PlantChange.plant_id == plant.id,
                    PlantChange.child_plant_id == plt.id,
                )
            )
            self.assertEqual(len(q2.all()), 1)
            change = q2.one()
            self.assertEqual(change.child_plant, plt)
            self.assertEqual(change.quantity, plt.quantity)
            self.assertEqual(change.to_location, plt.location)
            self.assertEqual(change.from_location, plant.location)
        editor.presenter.cleanup()
        del editor

    def test_branch_editor(self):
        # test argument checks
        #
        # TODO: these argument checks make future tests fail because
        # the PlantEditor is never cleaned up
        #
        # self.assert_(PlantEditor())
        # self.assertRaises(CheckConditionError, PlantEditor, branch_mode=True)

        # plant = Plant(accession=self.accession, location=self.location,
        #               code=u'33', quantity=5)
        # self.assertRaises(CheckConditionError, PlantEditor, model=plant,
        #                   branch_mode=True)
        # self.accession.plants.remove(plant) # remove from session
        # TODO: test check where quantity < 2
        # get existing plants
        plants = self.session.query(Plant).all()
        ids = [i.id for i in plants]

        quantity = 5
        self.plant.quantity = quantity
        self.session.commit()
        editor = PlantEditor(model=self.plant, branch_mode=True)
        update_gui()

        widgets = editor.presenter.view.widgets
        new_quantity = "2"
        widgets.plant_quantity_entry.props.text = new_quantity
        update_gui()
        editor.handle_response(Gtk.ResponseType.OK)
        editor.presenter.cleanup()
        del editor

        # there should only be one new plant,
        new_plant = (
            self.session.query(Plant).filter(Plant.id.notin_(ids)).one()
        )
        # test the quantity was set properly on the new plant
        self.assertEqual(new_plant.quantity, int(new_quantity))

        self.session.refresh(self.plant)
        # test the quantity is updated on the original plant
        self.assertEqual(self.plant.quantity, quantity - new_plant.quantity)
        # test the quantity for the change is the same as the quantity
        # for the plant
        self.assertEqual(new_plant.changes[0].quantity, new_plant.quantity)
        # test the parent_plant for the change is the same as the
        # original plant
        self.assertEqual(new_plant.changes[0].parent_plant, self.plant)

    @unittest.mock.patch("bauble.editor.GenericEditorView.start")
    def test_branch_callback(self, mock_start):
        """
        Test bauble.plugins.garden.plant.branch_callback()
        """
        mock_start.return_value = Gtk.ResponseType.OK
        for plant in self.session.query(Plant):
            self.session.delete(plant)
        for location in self.session.query(Location):
            self.session.delete(location)
        self.session.commit()

        loc = Location(name="site1", code="1")
        loc2 = Location(name="site2", code="2")
        quantity = 5
        plant = Plant(
            accession=self.accession, code="1", location=loc, quantity=quantity
        )
        self.session.add_all([loc, loc2, plant])
        self.session.commit()

        branch_callback([plant])
        new_plant = self.session.query(Plant).filter(Plant.code != "1").first()
        self.session.refresh(plant)
        self.assertEqual(plant.quantity, quantity - new_plant.quantity)
        self.assertEqual(new_plant.changes[0].quantity, new_plant.quantity)

    def test_is_code_unique(self):
        """
        Test bauble.plugins.garden.plant.is_code_unique()
        """
        self.assertFalse(is_code_unique(self.plant, "1"))
        self.assertTrue(is_code_unique(self.plant, "01"))
        self.assertFalse(is_code_unique(self.plant, "1-2"))
        self.assertFalse(is_code_unique(self.plant, "01-2"))
        self.assertFalse(is_code_unique(self.plant, "10-2"))

    def test_living_plant_has_no_death(self):
        self.assertIsNone(self.plant.death)

    def test_living_plant_planted(self):
        # plant added in setUp should create a plant_change and history entry
        hist_query = self.session.query(db.History).filter(
            db.History.table_name == "plant_change"
        )
        start_count = hist_query.count()
        self.assertEqual(start_count, 1)
        plant = Plant(
            accession=self.accession,
            location=self.location,
            code="11",
            quantity=1,
        )
        change = PlantChange()
        # should be able to leave all these off and still get appropriate
        # values, see below
        change.plant = plant
        change.to_location = plant.location
        change.quantity = plant.quantity
        change.reason = "PLTD"
        plant.changes.append(change)
        self.session.add_all([plant, change])
        self.session.flush()
        self.session.refresh(plant)
        self.assertIsNotNone(plant.planted)
        self.assertEqual(plant.planted.reason, "PLTD")
        self.assertEqual(hist_query.count(), start_count + 1)
        for entry in hist_query:
            # check that a date entry exists for all history entries,
            # particularly for those added in plant_after_insert (setUp commits
            # self.plant without a change so one is created in
            # plant_after_insert along with a history entry)
            self.assertIsNotNone(entry.values["date"])

    def test_living_plant_planted_reason_only(self):
        hist_query = self.session.query(db.History).filter(
            db.History.table_name == "plant_change"
        )
        start_count = hist_query.count()
        self.assertEqual(start_count, 1)
        plant = Plant(
            accession=self.accession,
            location=self.location,
            code="11",
            quantity=1,
        )
        change = PlantChange()
        change.reason = "PLTD"
        plant.changes.append(change)
        self.session.add_all([plant, change])
        self.session.commit()
        self.session.refresh(plant)
        self.assertIsNotNone(plant.planted)
        self.assertEqual(plant.planted.to_location, plant.location)
        self.assertEqual(plant.planted.reason, "PLTD")
        self.assertEqual(plant.planted.quantity, plant.quantity)
        # test the correct amount of history entries are added
        self.assertEqual(hist_query.count(), start_count + 1)

    def test_living_plant_always_has_planted(self):
        # this is generated in event.listen
        self.assertIsNotNone(self.plant.planted)
        self.assertEqual(self.plant.planted.to_location, self.plant.location)
        self.assertEqual(self.plant.planted.quantity, self.plant.quantity)
        self.assertIsNone(self.plant.planted.from_location)
        self.assertIsNone(self.plant.planted.child_plant)
        self.assertIsNone(self.plant.planted.parent_plant)
        # test a reason can be added after the fact.
        # first check reason is not set.
        self.assertIsNone(self.plant.planted.reason)
        # set it and commit.
        self.plant.planted.reason = "PLTD"
        self.session.add(self.plant)
        self.session.commit()
        # refresh plant from the database
        self.session.refresh(self.plant)
        self.assertEqual(self.plant.planted.reason, "PLTD")

    def test_setting_quantity_to_zero_defines_a_death(self):
        self.change = PlantChange()
        self.session.add(self.change)
        self.change.plant = self.plant
        self.change.from_location = self.plant.location
        self.change.quantity = -self.plant.quantity
        self.change.reason = "DEAD"
        self.plant.quantity = 0
        self.session.flush()
        self.assertIsNotNone(self.plant.death)
        self.assertEqual(self.plant.death.reason, "DEAD")

    def test_setting_quantity_to_zero_defines_a_death_wo_manual_change(self):
        # resfresh plant from the database
        self.session.refresh(self.plant)
        self.plant.quantity = 0
        self.session.add(self.plant)
        self.session.flush()
        self.assertIsNotNone(self.plant.death)
        # test a reason can be added after the fact.
        # first check reason is not set.
        self.assertIsNone(self.plant.death.reason)
        # set it and commit.
        self.plant.death.reason = "DEAD"
        self.session.add(self.plant)
        self.session.commit()
        # resfresh plant from the database
        self.session.refresh(self.plant)
        self.assertEqual(self.plant.death.reason, "DEAD")

    def test_setting_quantity_location_produces_2_changes(self):
        hist_query = self.session.query(db.History).filter(
            db.History.table_name == "plant_change"
        )
        start_count = hist_query.count()
        loc2a = Location(name="site2a", code="2a")
        self.session.add(loc2a)
        self.session.commit()
        self.assertEqual(len(self.plant.changes), 1)
        self.plant.quantity = 10
        self.plant.location = loc2a
        self.session.commit()
        self.session.refresh(self.plant)
        self.assertEqual(len(self.plant.changes), 3)
        # test the correct amount of history entries are added
        self.assertEqual(hist_query.count(), start_count + 2)
        for entry in hist_query:
            # check that a date entry exists for all history entries,
            # particularly for those added in plant_after_insert/after_update.
            # if no date is supplied the created history entry needs to be
            # generated
            self.assertIsNotNone(entry.values["date"])

    def test_setting_quantity_location_w_date_reason_produces_2_changes(self):
        hist_query = self.session.query(db.History).filter(
            db.History.table_name == "plant_change"
        )
        start_count = hist_query.count()
        date = "02-12-2020"
        loc2a = Location(name="site2a", code="2a")
        self.session.add(loc2a)
        self.session.commit()
        # should just have one change at this point
        self.assertEqual(len(self.plant.changes), 1)
        change = PlantChange()
        change.date = date
        change.reason = "ERRO"
        self.plant.changes.append(change)
        self.plant.quantity = 10
        self.plant.location = loc2a
        self.session.flush()
        self.session.refresh(self.plant)
        self.assertEqual(len(self.plant.changes), 3)
        for chg in self.plant.changes[1:]:
            self.assertEqual(chg.reason, "ERRO")
            self.assertEqual(chg.date.strftime("%d-%m-%Y"), date)
        # test the correct amount of history entries are added
        self.assertEqual(hist_query.count(), start_count + 2)
        for entry in hist_query:
            # check that a date entry exists for all history entries,
            # particularly for those added in plant_after_insert (setUp commits
            # self.plant without a change so one is created in
            # plant_after_insert along with a history entry)
            self.assertIsNotNone(entry.values["date"])

    def test_get_plant_completions(self):
        text = "222"
        result = get_plant_completions(self.session, text)
        self.assertEqual(result, set())

        text = "200"
        result = get_plant_completions(self.session, text)
        query = (
            self.session.query(Plant)
            .join(Accession)
            .filter(utils.ilike(Accession.code, f"{text}%%"))
        )
        self.assertEqual(result, set(str(i) for i in query))

        text = "2001.2"
        result = get_plant_completions(self.session, text)
        query = (
            self.session.query(Plant)
            .join(Accession)
            .filter(utils.ilike(Accession.code, f"{text}%%"))
        )
        self.assertEqual(result, set(str(i) for i in query))

        text = "2001.2.1"
        result = get_plant_completions(self.session, text)
        query = (
            self.session.query(Plant)
            .join(Accession)
            .filter(Accession.code == "2001.2", Plant.code == "1")
        )
        self.assertEqual(result, set(str(i) for i in query))

    def test_active_w_qty(self):
        self.assertTrue(self.plant.active)
        # test the hybrid_property expression
        # pylint: disable=no-member
        plt_active_in_db = self.session.query(Plant).filter(
            Plant.active.is_(True)
        )
        self.assertIn(self.plant, plt_active_in_db)

    def test_active_wo_qty(self):
        self.session.refresh(self.plant)
        self.plant.quantity = 0
        self.session.commit()
        self.session.refresh(self.plant)
        # make sure we have killed the plant
        self.assertIsNotNone(self.plant.death)
        self.assertFalse(self.plant.active)
        # test the hybrid_property expression
        # pylint: disable=no-member
        plt_active_in_db = self.session.query(Plant).filter(
            Plant.active.is_(True)
        )
        self.assertNotIn(self.plant, plt_active_in_db)

    def test_top_level_count_w_plant_qty(self):
        plt = self.plant

        self.assertEqual(plt.top_level_count()[(1, "Plantings")], 1)
        self.assertEqual(len(plt.top_level_count()[(2, "Accessions")]), 1)
        self.assertEqual(len(plt.top_level_count()[(3, "Species")]), 1)
        self.assertEqual(len(plt.top_level_count()[(4, "Genera")]), 1)
        self.assertEqual(len(plt.top_level_count()[(5, "Families")]), 1)
        self.assertEqual(plt.top_level_count()[(6, "Living plants")], 1)
        self.assertEqual(len(plt.top_level_count()[(7, "Locations")]), 1)
        self.assertEqual(len(plt.top_level_count()[(8, "Sources")]), 0)

    def test_top_level_count_wo_plant_qty(self):
        self.plant.quantity = 0
        plt = self.plant

        self.session.commit()

        self.assertEqual(plt.top_level_count()[(1, "Plantings")], 1)
        self.assertEqual(len(plt.top_level_count()[(2, "Accessions")]), 1)
        self.assertEqual(len(plt.top_level_count()[(3, "Species")]), 1)
        self.assertEqual(len(plt.top_level_count()[(4, "Genera")]), 1)
        self.assertEqual(len(plt.top_level_count()[(5, "Families")]), 1)
        self.assertEqual(plt.top_level_count()[(6, "Living plants")], 0)
        self.assertEqual(len(plt.top_level_count()[(7, "Locations")]), 1)
        self.assertEqual(len(plt.top_level_count()[(8, "Sources")]), 0)

    def test_commit_changes_does_not_generate_pointless_changes(self):
        start = len(self.plant.changes)
        start_qty = self.plant.quantity
        editor = PlantEditor(model=self.plant)
        mock_entry = unittest.mock.Mock()

        # toggle quantity back and forth
        mock_entry.get_text.return_value = str(start_qty + 1)
        editor.presenter.on_quantity_changed(mock_entry)
        mock_entry.get_text.return_value = str(start_qty)
        editor.presenter.on_quantity_changed(mock_entry)

        self.assertTrue(editor.presenter.change)
        editor.commit_changes()
        self.session.expire(self.plant)
        end = len(self.plant.changes)
        self.assertEqual(start, end)
        editor.presenter.cleanup()
        del editor

    def test_on_save_clicked(self):
        mock_self = unittest.mock.Mock()
        PlantEditor.on_save_clicked(mock_self)
        mock_self.commit_changes.assert_called()
        self.assertFalse(mock_self.presenter._dirty)
        self.assertFalse(mock_self.presenter.pictures_presenter._dirty)
        self.assertFalse(mock_self.presenter.notes_presenter._dirty)
        self.assertFalse(mock_self.presenter.prop_presenter._dirty)
        mock_self.session.rollback.assert_not_called()
        mock_self.presenter.refresh_view.assert_called()
        mock_self.presenter.reset_change.assert_called()
        mock_self.presenter.refresh_view.assert_called()

        mock_self = unittest.mock.Mock()
        mock_self.commit_changes.side_effect = SQLAlchemyError
        PlantEditor.on_save_clicked(mock_self)
        mock_self.commit_changes.assert_called()
        self.assertTrue(mock_self.presenter._dirty)
        self.assertTrue(mock_self.presenter.pictures_presenter._dirty)
        self.assertTrue(mock_self.presenter.notes_presenter._dirty)
        self.assertTrue(mock_self.presenter.prop_presenter._dirty)
        mock_self.presenter.refresh_view.assert_called()
        mock_self.presenter.reset_change.not_assert_called()
        mock_self.presenter.refresh_view.assert_called()


class PlantEditorPresenterTests(GardenTestCase):
    def test_acc_get_completions(self):
        acc = self.session.query(Accession).get(7)
        plant = Plant()
        self.session.add(plant)
        presenter = PlantEditorPresenter(plant, PlantEditorView())
        result = presenter.acc_get_completions("2022.3")
        self.assertEqual(result.all(), [acc])
        result = presenter.acc_get_completions("Cynodo")
        self.assertEqual(result.all(), [acc])
        result = presenter.acc_get_completions("202 Cynodo")
        self.assertEqual(result.all(), [acc])
        result = presenter.acc_get_completions("Cynodo dac")
        self.assertEqual(result.all(), [acc])
        result = presenter.acc_get_completions("Cynodo 'DT-1")
        self.assertEqual(result.all(), [acc])
        result = presenter.acc_get_completions("Cynodo 'Tif")
        self.assertEqual(result.all(), [acc])
        del presenter

    def test_acc_to_string_matcher(self):
        # not part of the presenter class but is used by it
        acc = self.session.query(Accession).get(7)
        self.assertTrue(acc_to_string_matcher(acc, "2022"))
        self.assertTrue(acc_to_string_matcher(acc, "Cynodo"))
        self.assertTrue(acc_to_string_matcher(acc, "20 Cyn"))
        self.assertTrue(acc_to_string_matcher(acc, "Cy dac"))
        self.assertTrue(acc_to_string_matcher(acc, "Cynodo 'D"))
        self.assertTrue(acc_to_string_matcher(acc, "Cynodo 'Tif"))
        self.assertFalse(acc_to_string_matcher(acc, "1999"))
        self.assertFalse(acc_to_string_matcher(acc, "Cyn a"))
        self.assertFalse(acc_to_string_matcher(acc, "Dyn d"))
        self.assertFalse(acc_to_string_matcher(acc, "19 Cyn"))

    def test_on_select(self):
        acc = self.session.query(Accession).get(7)
        plant = Plant()
        self.session.add(plant)
        presenter = PlantEditorPresenter(plant, PlantEditorView())
        presenter.on_select("string")
        self.assertIsNone(plant.accession)
        self.assertEqual(
            presenter.view.widgets.acc_species_label.get_text(), ""
        )
        presenter.on_select(acc)
        self.assertEqual(plant.accession, acc)
        self.assertEqual(
            presenter.view.widgets.acc_species_label.get_text(),
            str(acc.species),
        )
        del presenter

    def test_presenter_discourages_editing_if_qty_zero(self):
        plant = self.session.query(Plant).get(1)
        plant.quantity = 0
        presenter = PlantEditorPresenter(plant, PlantEditorView())
        self.assertFalse(presenter.view.widgets.notebook.get_sensitive())
        del presenter

    def test_init_reason_combo(self):
        plant = self.session.query(Plant).get(1)
        presenter = PlantEditorPresenter(plant, PlantEditorView())
        self.assertEqual(presenter.reasons, change_reasons)
        self.assertFalse(presenter.view.widgets.change_frame.get_sensitive())
        loc2 = self.session.query(Location).get(2)
        presenter.model.location = loc2
        presenter._init_reason_combo()
        self.assertEqual(presenter.reasons, transfer_reasons)
        self.assertTrue(presenter.view.widgets.change_frame.get_sensitive())
        presenter.session.rollback()
        presenter.model.quantity = 111
        presenter._init_reason_combo()
        self.assertEqual(presenter.reasons, added_reasons)
        self.assertTrue(presenter.view.widgets.change_frame.get_sensitive())
        presenter.session.rollback()
        presenter.model.quantity = 0
        presenter._init_reason_combo()
        self.assertEqual(presenter.reasons, deleted_reasons)
        self.assertTrue(presenter.view.widgets.change_frame.get_sensitive())
        presenter.session.rollback()
        presenter._init_reason_combo()
        self.assertFalse(presenter.view.widgets.change_frame.get_sensitive())

        del presenter

    @unittest.mock.patch("bauble.plugins.garden.plant.LocationEditor")
    def test_on_loc_button_clicked(self, mock_editor):
        loc = self.session.query(Location).first()
        mock_editor().presenter.model = loc
        plant = Plant()
        self.session.add(plant)
        presenter = PlantEditorPresenter(plant, PlantEditorView())
        presenter.on_loc_button_clicked(None)
        mock_editor.assert_called()
        mock_editor.assert_called_with(parent=presenter.view.get_window())
        self.assertEqual(plant.location, loc)

        mock_editor.reset_mock()
        presenter.on_loc_button_clicked(None, cmd="edit")
        mock_editor.assert_called()
        mock_editor.assert_called_with(loc, parent=presenter.view.get_window())

        del presenter

    def test_reset_change(self):
        acc = self.session.query(Accession).get(7)
        plant = Plant(accession=acc, quantity=1)
        plant.accession_id = acc.id
        self.session.add(plant)
        presenter = PlantEditorPresenter(plant, PlantEditorView())
        start_change = presenter.change
        self.assertEqual(presenter._original_accession_id, acc.id)
        self.assertEqual(presenter._original_quantity, None)
        plant.quantity = 10
        presenter.reset_change()
        self.assertNotEqual(start_change, presenter.change)
        self.assertEqual(presenter._original_quantity, 10)

        del presenter


class PropagationTests(GardenTestCase):
    def __init__(self, *args):
        super().__init__(*args)

    def setUp(self):
        super().setUp()
        self.accession = self.create(Accession, species=self.species, code="1")
        self.plants = []

    def add_plants(self, plant_codes=[]):
        loc = self.create(Location, name="name", code="code")
        for pc in plant_codes:
            self.plants.append(
                self.create(
                    Plant,
                    accession=self.accession,
                    location=loc,
                    code=pc,
                    quantity=1,
                )
            )
        self.session.commit()

    def add_propagations(self, propagation_types):
        for i, pt in enumerate(propagation_types):
            prop = Propagation()
            prop.prop_type = pt
            prop.plant = self.plants[i]
            if pt == "Seed":
                specifically = PropSeed(**default_seed_values)
            elif pt == "UnrootedCutting":
                specifically = PropCutting(**default_cutting_values)
            else:
                specifically = type("FooBar", (object,), {})()
            specifically.propagation = prop
        self.session.commit()

    def test_propagation_cutting_quantity_new_zero(self):
        self.add_plants(["1"])
        prop = Propagation()
        prop.prop_type = "UnrootedCutting"
        prop.plant = self.plants[0]
        spec = PropCutting(cutting_type="Nodal")
        spec.propagation = prop
        self.session.commit()
        self.assertEqual(prop.accessible_quantity, 0)
        prop = Propagation()
        prop.prop_type = "UnrootedCutting"
        prop.plant = self.plants[0]
        spec = PropCutting(cutting_type="Nodal", rooted_pct=0)
        spec.propagation = prop
        self.session.commit()
        self.assertEqual(prop.accessible_quantity, 0)

    def test_propagation_seed_quantity_new_zero(self):
        self.add_plants(["1"])
        prop = Propagation()
        prop.prop_type = "Seed"
        prop.plant = self.plants[0]
        spec = PropSeed(nseeds=30, date_sown=datetime.date(2017, 1, 1))
        spec.propagation = prop
        self.session.commit()
        self.assertEqual(prop.accessible_quantity, 0)
        prop = Propagation()
        prop.prop_type = "Seed"
        prop.plant = self.plants[0]
        spec = PropSeed(
            nseeds=30, date_sown=datetime.date(2017, 1, 1), nseedlings=0
        )
        spec.propagation = prop
        self.session.commit()
        self.assertEqual(prop.accessible_quantity, 0)

    def test_propagation_seed_unaccessed_quantity(self):
        self.add_plants(["1"])
        prop = Propagation()
        prop.prop_type = "Seed"
        prop.plant = self.plants[0]
        seed = PropSeed(**default_seed_values)
        seed.propagation = prop
        self.session.commit()
        summary = prop.get_summary()
        self.assertEqual(prop.accessible_quantity, 23)

    def test_propagation_cutting_accessed_remaining_quantity(self):
        self.add_plants(["1"])
        self.add_propagations(["Seed"])
        accession2 = self.create(
            Accession, species=self.species, code="2", quantity_recvd=10
        )
        source2 = self.create(
            Source, plant_propagation=self.plants[0].propagations[0]
        )
        accession2.source = source2
        self.session.commit()
        prop = self.plants[0].propagations[0]
        self.assertEqual(prop.accessible_quantity, 13)

    def test_propagation_other_unaccessed_remaining_quantity_1(self):
        self.add_plants(["1"])
        self.add_propagations(["Other"])
        prop = self.plants[0].propagations[0]
        self.assertEqual(prop.accessible_quantity, 1)

    def test_propagation_other_accessed_remaining_quantity_1(self):
        self.add_plants(["1"])
        self.add_propagations(["Other"])
        accession2 = self.create(
            Accession, species=self.species, code="2", quantity_recvd=10
        )
        source2 = self.create(
            Source, plant_propagation=self.plants[0].propagations[0]
        )
        accession2.source = source2
        self.session.commit()
        prop = self.plants[0].propagations[0]
        self.assertEqual(prop.accessible_quantity, 1)

    def test_accession_propagations_is_union_of_plant_propagations(self):
        self.add_plants(["1", "2"])
        self.add_propagations(["UnrootedCutting", "Seed"])
        self.assertEqual(len(self.accession.plants), 2)
        self.assertEqual(len(self.plants[0].propagations), 1)
        self.assertEqual(len(self.plants[1].propagations), 1)
        self.assertEqual(len(self.accession.propagations), 2)
        p1, p2 = self.plants[0].propagations[0], self.plants[1].propagations[0]
        self.assertTrue(p1 in self.accession.propagations)
        self.assertTrue(p2 in self.accession.propagations)

    def test_propagation_links_back_to_correct_plant(self):
        self.add_plants(["1", "2", "3"])
        self.add_propagations(["UnrootedCutting", "Seed", "Seed"])
        for plant in self.plants:
            self.assertEqual(len(plant.propagations), 1)
            prop = plant.propagations[0]
            self.assertEqual(prop.plant, plant)

    def test_get_summary_cutting_complete(self):
        self.add_plants(["1"])
        prop = Propagation()
        prop.prop_type = "UnrootedCutting"
        prop.plant = self.plants[0]
        cutting = PropCutting(**default_cutting_values)
        cutting.propagation = prop
        rooted = PropCuttingRooted()
        rooted.cutting = cutting
        self.session.commit()
        summary = prop.get_summary()
        self.assertEqual(
            summary,
            (
                "Cutting; Cutting type: Nodal; Length: 2mm; Tip: "
                "Intact; Leaves: Intact; Flower buds: None; Wounded:"
                " Singled; Fungicide: Physan; Hormone treatment: "
                'Auxin powder; Bottom heat: 65°F; Container: 4" pot;'
                " Media: standard mix; Location: Mist frame; Cover:"
                " Poly cover; Rooted: 90%"
            ),
        )

    def test_get_summary_seed_complete(self):
        self.add_plants(["1"])
        prop = Propagation()
        prop.prop_type = "Seed"
        prop.plant = self.plants[0]
        seed = PropSeed(**default_seed_values)
        seed.propagation = prop
        self.session.commit()
        summary = prop.get_summary()
        self.assertEqual(
            summary,
            (
                "Seed; Pretreatment: Soaked in peroxide solution; # "
                "of seeds: 24; Date sown: 01-01-2017; Container: "
                "tray; Media: standard mix; Location: mist tent; "
                "Germination date: 01-02-2017; # of seedlings: 23; "
                "Germination rate: 99%; Date planted: 08-02-2017"
            ),
        )

    def test_get_summary_seed_partial_1_still_unused(self):
        self.add_plants(["1"])
        self.add_propagations(["Seed"])
        prop = self.plants[0].propagations[0]
        self.assertEqual(prop.get_summary(partial=1), "")

    def test_get_summary_seed_partial_2_still_unused(self):
        self.add_plants(["1"])
        self.add_propagations(["Seed"])
        prop = self.plants[0].propagations[0]
        self.assertEqual(prop.get_summary(partial=2), prop.get_summary())

    def test_get_summary_seed_partial_1_used_once(self):
        self.add_plants(["1"])
        self.add_propagations(["Seed"])
        accession2 = self.create(Accession, species=self.species, code="2")
        source2 = self.create(
            Source, plant_propagation=self.plants[0].propagations[0]
        )
        accession2.source = source2
        self.session.commit()
        prop = self.plants[0].propagations[0]
        self.assertEqual(prop.get_summary(partial=1), accession2.code)

    def test_get_summary_seed_partial_1_used_twice(self):
        self.add_plants(["1"])
        self.add_propagations(["Seed"])
        using = ["2", "3"]
        for c in using:
            a = self.create(Accession, species=self.species, code=c)
            s = self.create(
                Source, plant_propagation=self.plants[0].propagations[0]
            )
            a.source = s
        self.session.commit()
        prop = self.plants[0].propagations[0]
        self.assertEqual(
            prop.get_summary(partial=1),
            ";".join("%s" % a for a in prop.accessions),
        )

    def test_propagation_accessions_used_once(self):
        self.add_plants(["1"])
        self.add_propagations(["Seed"])
        accession2 = self.create(Accession, species=self.species, code="2")
        source2 = self.create(
            Source, plant_propagation=self.plants[0].propagations[0]
        )
        accession2.source = source2
        self.session.commit()
        prop = self.plants[0].propagations[0]
        self.assertEqual(prop.accessions, [accession2])

    def test_propagation_accessions_used_twice(self):
        self.add_plants(["1"])
        self.add_propagations(["Seed"])
        prop = self.plants[0].propagations[0]
        using = ["2", "3"]
        accs = []
        for c in using:
            a = self.create(Accession, species=self.species, code=c)
            s = self.create(Source, plant_propagation=prop)
            a.source = s
            accs.append(a)
        self.session.commit()
        self.assertEqual(len(prop.accessions), 2)
        self.assertEqual(
            sorted(accs, key=utils.natsort_key),
            sorted(prop.accessions, key=utils.natsort_key),
        )

    def test_accession_source_plant_propagation_points_at_parent_plant(self):
        self.add_plants(["1"])
        self.add_propagations(["Seed"])
        prop = self.plants[0].propagations[0]
        using = ["2", "3"]
        for c in using:
            a = self.create(Accession, species=self.species, code=c)
            s = self.create(Source, plant_propagation=prop)
            a.source = s
        self.session.commit()
        for a in prop.accessions:
            self.assertEqual(a.source.plant_propagation.plant, self.plants[0])
            self.assertEqual(a.parent_plant, self.plants[0])

    def test_accession_without_parent_plant(self):
        self.assertEqual(self.accession.parent_plant, None)

    def test_cutting_property(self):
        self.add_plants(["1"])
        prop = Propagation()
        prop.plant = self.plants[0]
        prop.prop_type = "UnrootedCutting"
        prop.accession = self.accession
        cutting = PropCutting(**default_cutting_values)
        cutting.propagation = prop
        rooted = PropCuttingRooted()
        rooted.cutting = cutting
        self.session.add(rooted)
        self.session.commit()

        self.assertTrue(rooted in prop.cutting.rooted)

        rooted_id = rooted.id
        cutting_id = cutting.id
        self.assertTrue(rooted_id, "no prop_rooted.id")

        # setting the cutting property on Propagation should cause
        # the cutting and its rooted children to be deleted
        prop.cutting = None
        self.session.commit()
        self.assertTrue(not self.session.query(PropCutting).get(cutting_id))
        self.assertTrue(
            not self.session.query(PropCuttingRooted).get(rooted_id)
        )

    def test_accession_links_to_parent_plant(self):
        """we can reach the parent plant from an accession"""

        self.add_plants(["1"])
        pass

    def test_seed_property(self):
        loc = Location(name="name", code="code")
        plant = Plant(
            accession=self.accession, location=loc, code="1", quantity=1
        )
        prop = Propagation()
        plant.propagations.append(prop)
        prop.prop_type = "Seed"
        prop.accession = self.accession
        seed = PropSeed(**default_seed_values)
        self.session.add(seed)
        seed.propagation = prop
        self.session.commit()

        self.assertTrue(seed == prop.seed)
        seed_id = seed.id

        # this should cause the cutting and its rooted children to be deleted
        prop.seed = None
        self.session.commit()
        self.assertTrue(not self.session.query(PropSeed).get(seed_id))

    def test_cutting_editor(self):
        loc = Location(name="name", code="code")
        plant = Plant(
            accession=self.accession, location=loc, code="1", quantity=1
        )
        propagation = Propagation()
        plant.propagations.append(propagation)
        editor = PropagationEditor(model=propagation)
        widgets = editor.presenter.view.widgets
        self.assertTrue(widgets is not None)
        view = editor.presenter.view
        view.widget_set_value("prop_type_combo", "UnrootedCutting")
        view.widget_set_value("prop_date_entry", utils.today_str())
        cutting_presenter = editor.presenter._cutting_presenter
        for widget, attr in cutting_presenter.widget_to_field_map.items():
            # debug('%s=%s' % (widget, default_cutting_values[attr]))
            view.widget_set_value(widget, default_cutting_values[attr])
        update_gui()
        editor.handle_response(Gtk.ResponseType.OK)
        editor.commit_changes()
        model = editor.model
        s = object_session(model)
        s.expire(model)
        self.assertTrue(model.prop_type == "UnrootedCutting")
        for attr, value in default_cutting_values.items():
            v = getattr(model.cutting, attr)
            self.assertTrue(v == value, "%s = %s(%s)" % (attr, value, v))
        editor.session.close()

    def test_seed_editor_commit(self):
        loc = Location(name="name", code="code")
        plant = Plant(
            accession=self.accession, location=loc, code="1", quantity=1
        )
        propagation = Propagation()
        plant.propagations.append(propagation)
        editor = PropagationEditor(model=propagation)
        widgets = editor.presenter.view.widgets
        seed_presenter = editor.presenter._seed_presenter
        view = editor.presenter.view

        # set default values in editor widgets
        view.widget_set_value("prop_type_combo", "Seed")
        view.widget_set_value(
            "prop_date_entry", default_propagation_values["date"]
        )
        view.widget_set_value(
            "notes_textview", default_propagation_values["notes"]
        )
        for widget, attr in seed_presenter.widget_to_field_map.items():
            w = widgets[widget]
            if isinstance(w, Gtk.ComboBox) and not w.get_model():
                widgets[widget].get_child().props.text = default_seed_values[
                    attr
                ]
            view.widget_set_value(widget, default_seed_values[attr])

        # update the editor, send the RESPONSE_OK signal and commit the changes
        update_gui()
        editor.handle_response(Gtk.ResponseType.OK)
        editor.presenter.cleanup()
        model_id = editor.model.id
        editor.commit_changes()
        editor.session.close()

        s = db.Session()
        propagation = s.query(Propagation).get(model_id)

        self.assertTrue(propagation.prop_type == "Seed")
        # make sure the each value in default_seed_values matches the model
        for attr, expected in default_seed_values.items():
            v = getattr(propagation.seed, attr)
            if isinstance(v, datetime.date):
                format = prefs.prefs[prefs.date_format_pref]
                v = v.strftime(format)
                if isinstance(expected, datetime.date):
                    expected = expected.strftime(format)
            self.assertTrue(v == expected, "%s = %s(%s)" % (attr, expected, v))

        for attr, expected in default_propagation_values.items():
            v = getattr(propagation, attr)
            self.assertTrue(v == expected, "%s = %s(%s)" % (attr, expected, v))

        s.close()

    def test_seed_editor_load(self):
        loc = Location(name="name", code="code")
        plant = Plant(
            accession=self.accession, location=loc, code="1", quantity=1
        )
        propagation = Propagation(**default_propagation_values)
        propagation.prop_type = "Seed"
        propagation.seed = PropSeed(**default_seed_values)
        plant.propagations.append(propagation)

        editor = PropagationEditor(model=propagation)
        widgets = editor.presenter.view.widgets
        seed_presenter = editor.presenter._seed_presenter
        view = editor.presenter.view
        self.assertTrue(view is not None)

        update_gui()

        # check that the values loaded correctly from the model in the
        # editor widget
        def get_widget_text(w):
            if isinstance(w, Gtk.TextView):
                return w.get_buffer().props.text
            elif isinstance(w, Gtk.Entry):
                return w.props.text
            elif isinstance(w, Gtk.ComboBox) and w.get_has_entry():
                # ComboBox.with_entry
                return w.get_child().get_text()
            else:
                raise ValueError("%s not supported" % type(w))

        # make sure the default values match the values in the widgets
        date_format = prefs.prefs[prefs.date_format_pref]
        for widget, attr in editor.presenter.widget_to_field_map.items():
            if not attr in default_propagation_values:
                continue
            default = default_propagation_values[attr]
            if isinstance(default, datetime.date):
                default = default.strftime(date_format)
            value = get_widget_text(widgets[widget])
            self.assertTrue(
                value == default, "%s = %s (%s)" % (attr, value, default)
            )

        # check the default for the PropSeed and SeedPresenter
        for widget, attr in seed_presenter.widget_to_field_map.items():
            if not attr in default_seed_values:
                continue
            default = default_seed_values[attr]
            if isinstance(default, datetime.date):
                default = default.strftime(date_format)
            if isinstance(default, int):
                default = str(default)
            value = get_widget_text(widgets[widget])
            self.assertTrue(
                value == default, "%s = %s (%s)" % (attr, value, default)
            )

    @unittest.mock.patch("gi.repository.Gtk.Dialog.run")
    def test_editor(self, mock_start):
        # Not sure this really tests much...
        mock_start.return_value = Gtk.ResponseType.OK
        propagation = Propagation()
        acc1 = self.session.query(Accession).first()
        propagation.used_source = [acc1.source]
        editor = PropagationEditor(model=propagation)
        utils.set_combo_from_value(
            editor.presenter.view.widgets.prop_type_combo, "Other"
        )
        utils.set_widget_value(
            editor.presenter.view.widgets.notes_textview, "TEST"
        )
        propagation = editor.start()
        logger.debug(propagation)
        self.assertTrue(propagation.accessions)
        self.assertEqual(propagation.prop_type, "Other")
        self.assertEqual(propagation.notes, "TEST")
        del editor
        self.assertEqual(
            utils.gc_objects_by_type("PropagationEditor"),
            [],
            "PropagationEditor not deleted",
        )


class VoucherTests(GardenTestCase):
    def setUp(self):
        super().setUp()
        self.accession = self.create(Accession, species=self.species, code="1")
        self.session.commit()

    def test_voucher(self):
        """
        Test the Accession.voucher property
        """
        voucher = Voucher(herbarium="ABC", code="1234567")
        voucher.accession = self.accession
        self.session.commit()
        voucher_id = voucher.id
        self.accession.vouchers.remove(voucher)
        self.session.commit()
        self.assertTrue(not self.session.query(Voucher).get(voucher_id))

        # test that if we set voucher.accession to None then the
        # voucher is deleted but not the accession
        voucher = Voucher(herbarium="ABC", code="1234567")
        voucher.accession = self.accession
        self.session.commit()
        voucher_id = voucher.id
        acc_id = voucher.accession.id
        voucher.accession = None
        self.session.commit()
        self.assertTrue(not self.session.query(Voucher).get(voucher_id))
        self.assertTrue(self.session.query(Accession).get(acc_id))

    def test_on_tree_cursor_changed(self):
        acc = self.session.query(Accession).get(2)
        mock_parent = unittest.mock.Mock()
        presenter = VoucherPresenter(
            mock_parent, acc, AccessionEditorView(), self.session
        )
        self.assertEqual(acc.vouchers, [])
        mock_tree_view = unittest.mock.Mock()
        # sets insensitive
        mock_tree_view.get_model.return_value = []
        presenter.on_tree_cursor_changed(mock_tree_view)
        button = presenter.view.widgets.voucher_remove_button
        self.assertFalse(button.get_sensitive())
        # sets sensitive
        mock_tree_view.get_model.return_value = [1]
        presenter.on_tree_cursor_changed(mock_tree_view)
        self.assertTrue(button.get_sensitive())
        # parent voucher
        # sets insensitive
        mock_tree_view.get_model.return_value = []
        presenter.on_tree_cursor_changed(mock_tree_view, parent=True)
        button = presenter.view.widgets.parent_voucher_remove_button
        self.assertFalse(button.get_sensitive())
        # sets sensitive
        mock_tree_view.get_model.return_value = [1]
        presenter.on_tree_cursor_changed(mock_tree_view, parent=True)
        self.assertTrue(button.get_sensitive())

        presenter.cleanup()

    def test_on_cell_edited(self):
        acc = self.session.query(Accession).get(2)
        voucher = Voucher(herbarium="ABC", code="1234567")
        voucher.accession = acc
        self.session.commit()
        mock_parent = unittest.mock.Mock()
        presenter = VoucherPresenter(
            mock_parent, acc, AccessionEditorView(), self.session
        )
        self.assertEqual(acc.vouchers, [voucher])
        presenter.on_cell_edited(
            None, 0, "BRI", ("voucher_treeview", "herbarium")
        )
        self.assertEqual(voucher.herbarium, "BRI")
        presenter.on_cell_edited(
            None, 0, "987654", ("voucher_treeview", "code")
        )
        self.assertEqual(voucher.code, "987654")

        presenter.cleanup()

    def test_on_remove_clicked(self):
        acc = self.session.query(Accession).get(2)
        voucher = Voucher(herbarium="ABC", code="1234567", accession=acc)
        voucher_parent = Voucher(
            herbarium="ABC",
            code="1234567",
            accession=acc,
            parent_material=True,
        )
        self.session.commit()
        mock_parent = unittest.mock.Mock()
        presenter = VoucherPresenter(
            mock_parent, acc, AccessionEditorView(), self.session
        )
        self.assertEqual(acc.vouchers, [voucher, voucher_parent])
        presenter.view.widgets.parent_voucher_treeview.set_cursor(0)
        presenter.view.widgets.voucher_treeview.set_cursor(0)
        presenter.on_remove_clicked(None)
        self.assertEqual(acc.vouchers, [voucher_parent])
        presenter.on_remove_clicked(None, parent=True)
        self.assertEqual(acc.vouchers, [])

        presenter.cleanup()

    def test_on_add_clicked(self):
        acc = self.session.query(Accession).get(2)
        mock_parent = unittest.mock.Mock()
        presenter = VoucherPresenter(
            mock_parent, acc, AccessionEditorView(), self.session
        )
        self.assertEqual(acc.vouchers, [])
        presenter.view.widgets.parent_voucher_treeview.set_cursor(0)
        presenter.view.widgets.voucher_treeview.set_cursor(0)
        presenter.on_add_clicked(None)
        self.assertEqual(len(acc.vouchers), 1)
        presenter.on_add_clicked(None, parent=True)
        self.assertEqual(len(acc.vouchers), 2)

        presenter.cleanup()


class SourceTests(GardenTestCase):
    def __init__(self, *args):
        super().__init__(*args)

    def setUp(self):
        super().setUp()
        self.accession = self.create(Accession, species=self.species, code="1")

    def test_cutting_propagation_cascades(self):
        source = Source()
        self.accession.source = source
        source.propagation = Propagation(prop_type="Seed")

        cutting = PropCutting(**default_cutting_values)
        cutting.propagation = source.propagation
        self.session.commit()
        prop_id = source.propagation.id
        cutting_id = source.propagation.cutting.id
        self.assertTrue(prop_id)
        self.assertTrue(cutting_id)
        # make sure the propagation gets cleaned up when we set the
        # source.propagation attribute to None - and commit
        source.propagation = None
        self.session.commit()
        self.assertFalse(self.session.query(PropCutting).get(cutting_id))
        self.assertFalse(self.session.query(Propagation).get(prop_id))

    def test_seed_propagation_cascades(self):
        """
        Test cascading for the Source.propagation relation
        """
        source = Source()
        self.accession.source = source
        source.propagation = Propagation(prop_type="Seed")

        seed = PropSeed(**default_seed_values)
        seed.propagation = source.propagation
        self.session.commit()
        prop_id = source.propagation.id
        seed_id = source.propagation.seed.id
        self.assertTrue(prop_id)
        self.assertTrue(seed_id)
        # make sure the propagation gets cleaned up when we set the
        # source.propagation attribute to None - and commit
        source.propagation = None
        self.session.commit()
        self.assertFalse(self.session.query(PropSeed).get(seed_id))
        self.assertFalse(self.session.query(Propagation).get(prop_id))

    def test_propagation_of_source_material_cascades(self):
        # create a source object with a collection and propagation (this could
        # be a expedition or a purchase of seed etc.)
        source = Source()
        source.source_detail = SourceDetail(name="name2")
        source.sources_code = "1"
        source.collection = Collection(locale="locale")
        source.propagation = Propagation(prop_type="Seed")
        # use it as a source for the accession
        source.accession = self.accession
        self.session.commit()

        # test that cascading works properly
        source_detail_id = source.source_detail.id
        coll_id = source.collection.id
        prop_id = source.propagation.id
        # remove the accessions source
        self.accession.source = None
        self.session.commit()

        # the Collection and Propagation should be
        # deleted since they are specific to the source
        self.assertFalse(self.session.query(Collection).get(coll_id))
        self.assertFalse(self.session.query(Propagation).get(prop_id))

        # the SourceDetail shouldn't be deleted as it is independent of the source
        self.assertTrue(self.session.query(SourceDetail).get(source_detail_id))

    def test_plant_propagation_as_source_cascades(self):
        # create a source object
        source = Source()

        # create a plant and propagation from it
        location = Location(code="1", name="site1")
        plant = Plant(
            accession=self.accession, location=location, code="1", quantity=1
        )
        plant.propagations.append(Propagation(prop_type="Seed"))
        self.session.commit()

        # add plant propagation to the source and use it as the source for an
        # accession
        source.plant_propagation = plant.propagations[0]
        source.accession = self.accession
        self.session.commit()

        # remove the accessions source
        plant_prop_id = source.plant_propagation.id
        self.accession.source = None
        self.session.commit()

        # the Propagation shouldn't be deleted as it is independant of the
        # source
        self.assertTrue(self.session.query(Propagation).get(plant_prop_id))


class SourcePresenterTests(GardenTestCase):
    # NOTE some tests also in AcccessionTests

    def test_on_sources_code_changed(self):
        view = AccessionEditorView()
        model = Source()
        presenter = SourcePresenter(
            unittest.mock.MagicMock(),
            Accession(source=model),
            view,
            self.session,
        )

        view.widgets.sources_code_entry.set_text("")
        self.assertIsNone(model.sources_code)
        view.widgets.sources_code_entry.set_text("ABC123")
        self.assertEqual(model.sources_code, "ABC123")
        presenter.cleanup()

    def test_on_source_note_changed(self):
        view = AccessionEditorView()
        model = Source()
        presenter = SourcePresenter(
            unittest.mock.MagicMock(),
            Accession(source=model),
            view,
            self.session,
        )

        view.widgets.source_notes_textbuffer.set_text("")
        self.assertIsNone(model.notes)
        view.widgets.source_notes_textbuffer.set_text("Test note text.")
        self.assertEqual(model.notes, "Test note text.")
        presenter.cleanup()

    def test_on_type_filter_changed(self):
        view = AccessionEditorView()
        model = Source()
        presenter = SourcePresenter(
            unittest.mock.MagicMock(),
            Accession(source=model),
            view,
            self.session,
        )

        self.assertFalse(view.widgets.source_garden_prop_box.get_visible())
        utils.set_widget_value(view.widgets.source_type_combo, "garden_prop")
        combo = view.widgets.acc_source_comboentry
        self.assertEqual(len(combo.get_model()), 2)
        self.assertTrue(view.widgets.source_garden_prop_box.get_visible())
        utils.set_widget_value(view.widgets.source_type_combo, "contact")
        self.assertEqual(len(combo.get_model()), len(source_detail_data) + 1)
        self.assertFalse(view.widgets.source_garden_prop_box.get_visible())
        presenter.cleanup()

    def test_on_coll_add_remove_clicked(self):
        view = AccessionEditorView()
        model = Source()
        presenter = SourcePresenter(
            unittest.mock.MagicMock(),
            Accession(source=model),
            view,
            self.session,
        )

        self.assertIsNone(model.collection)
        self.assertTrue(view.widgets.source_coll_add_button.get_sensitive())
        self.assertFalse(
            view.widgets.source_coll_remove_button.get_sensitive()
        )
        self.assertFalse(view.widgets.source_coll_expander.get_sensitive())

        # add
        view.widgets.source_coll_add_button.clicked()
        self.assertIsNotNone(model.collection)
        self.assertFalse(view.widgets.source_coll_add_button.get_sensitive())
        self.assertTrue(view.widgets.source_coll_remove_button.get_sensitive())
        self.assertTrue(view.widgets.source_coll_expander.get_sensitive())

        # remove
        view.widgets.source_coll_remove_button.clicked()
        self.assertIsNone(model.collection)
        self.assertTrue(view.widgets.source_coll_add_button.get_sensitive())
        self.assertFalse(
            view.widgets.source_coll_remove_button.get_sensitive()
        )
        self.assertFalse(view.widgets.source_coll_expander.get_sensitive())
        presenter.cleanup()

    def test_on_prop_add_remove_clicked(self):
        view = AccessionEditorView()
        model = Source()
        presenter = SourcePresenter(
            unittest.mock.MagicMock(),
            Accession(source=model),
            view,
            self.session,
        )

        self.assertIsNone(model.propagation)
        self.assertTrue(view.widgets.source_prop_add_button.get_sensitive())
        self.assertFalse(
            view.widgets.source_prop_remove_button.get_sensitive()
        )
        self.assertFalse(view.widgets.source_prop_expander.get_sensitive())

        # add
        view.widgets.source_prop_add_button.clicked()
        self.assertIsNotNone(model.propagation)
        self.assertFalse(view.widgets.source_prop_add_button.get_sensitive())
        self.assertTrue(view.widgets.source_prop_remove_button.get_sensitive())
        self.assertTrue(view.widgets.source_prop_expander.get_sensitive())

        # remove
        view.widgets.source_prop_remove_button.clicked()
        self.assertIsNone(model.propagation)
        self.assertTrue(view.widgets.source_prop_add_button.get_sensitive())
        self.assertFalse(
            view.widgets.source_prop_remove_button.get_sensitive()
        )
        self.assertFalse(view.widgets.source_prop_expander.get_sensitive())
        presenter.cleanup()

    @unittest.mock.patch(
        "bauble.plugins.garden.accession.SourceDetailPresenter"
    )
    def test_on_new_source_button_clicked(self, mock_presenter):
        # set the type, mock the SourceDetailPresenter, get the source suplied
        # to it, adjust its name then return from start
        view = AccessionEditorView()
        model = Source()
        mock_acc_editor_presenter = unittest.mock.MagicMock()
        presenter = SourcePresenter(
            mock_acc_editor_presenter,
            Accession(source=model),
            view,
            self.session,
        )
        utils.set_widget_value(view.widgets.source_type_combo, "Commercial")

        def mock_start():
            source = mock_presenter.call_args_list[1][0][0]
            source.name = "Test"
            source.source_type = "Commercial"
            return Gtk.ResponseType.OK

        mock_presenter().start = mock_start

        view.widgets.new_source_button.clicked()
        # assert that the selected value is selected in the
        # acc_source_comboentry
        combo = view.widgets.acc_source_comboentry
        treeiter = combo.get_active_iter()
        active = combo.get_model()[treeiter][0]

        self.assertEqual(active.name, "Test")
        self.assertEqual(
            mock_presenter.call_args.kwargs["source_types"], ["Commercial"]
        )
        presenter.cleanup()

    def test_source_match_func(self):
        view = AccessionEditorView()
        model = Source()
        presenter = SourcePresenter(
            unittest.mock.MagicMock(),
            Accession(source=model),
            view,
            self.session,
        )

        mock_completion = unittest.mock.Mock()
        mock_completion.get_model.return_value = [["test nursery name"]]
        self.assertTrue(
            presenter.source_match_func(mock_completion, "test", 0)
        )
        self.assertTrue(
            presenter.source_match_func(mock_completion, "nursery", 0)
        )
        self.assertTrue(
            presenter.source_match_func(mock_completion, "name", 0)
        )
        self.assertFalse(
            presenter.source_match_func(mock_completion, "xyz", 0)
        )
        presenter.cleanup()


class AccessionQualifiedTaxon(GardenTestCase):
    def __init__(self, *args):
        super().__init__(*args)

    def setUp(self):
        super().setUp()
        self.sp3 = Species(
            genus=self.genus,
            sp="grusonii",
            infrasp1_rank="var.",
            infrasp1="albispinus",
        )
        self.session.add(self.sp3)
        self.session.commit()
        self.ac1 = self.create(Accession, species=self.species, code="1")
        self.ac2 = self.create(Accession, species=self.sp3, code="2")

    def tearDown(self):
        super().tearDown()

    def test_species_str_plain(self):
        s = "Echinocactus grusonii"
        sp_str = self.ac1.species_str()
        self.assertEqual(remove_zws(sp_str), s)

        s = "<i>Echinocactus</i> <i>grusonii</i> var. <i>albispinus</i>"
        sp_str = self.ac2.species_str(markup=True)
        self.assertEqual(remove_zws(sp_str), s)

    def test_species_str_without_zws(self):
        s = "Echinocactus grusonii"
        sp_str = self.species.string(remove_zws=True)
        self.assertEqual(sp_str, s)
        s = "Echinocactus grusonii var. albispinus"
        sp_str = self.sp3.string(remove_zws=True)
        self.assertEqual(sp_str, s)
        s = "<i>Echinocactus</i> <i>grusonii</i> var. <i>albispinus</i>"
        sp_str = self.sp3.string(remove_zws=True, markup=True)
        self.assertEqual(sp_str, s)

    def test_species_str_with_qualification_too_deep(self):
        self.ac1.id_qual = "?"
        self.ac1.id_qual_rank = "infrasp1"
        s = "<i>Echinocactus</i> <i>grusonii</i>"
        sp_str = self.ac1.species_str(markup=True)
        self.assertEqual(remove_zws(sp_str), s)
        s = "Echinocactus grusonii"
        sp_str = self.ac1.species_str()
        self.assertEqual(sp_str, s)

        self.ac1.id_qual = "cf."
        self.ac1.id_qual_rank = "infrasp1"
        s = "Echinocactus grusonii"
        sp_str = self.ac1.species_str()
        self.assertEqual(remove_zws(sp_str), s)

    def test_species_str_with_qualification_correct(self):
        self.ac1.id_qual = "?"
        self.ac1.id_qual_rank = "sp"
        s = "<i>Echinocactus</i> ? <i>grusonii</i>"
        sp_str = self.ac1.species_str(markup=True)
        self.assertEqual(remove_zws(sp_str), s)

        # aff. before qualified epithet
        self.ac1.id_qual = "aff."
        self.ac1.id_qual_rank = "genus"
        s = "aff. <i>Echinocactus</i> <i>grusonii</i>"
        sp_str = self.ac1.species_str(markup=True)
        self.assertEqual(remove_zws(sp_str), s)

        self.ac1.id_qual_rank = "sp"
        s = "<i>Echinocactus</i> aff. <i>grusonii</i>"
        sp_str = self.ac1.species_str(markup=True)
        self.assertEqual(remove_zws(sp_str), s)

        self.ac2.id_qual = "aff."
        self.ac2.id_qual_rank = "infrasp1"
        s = "<i>Echinocactus</i> <i>grusonii</i> aff. var. <i>albispinus</i>"
        sp_str = self.ac2.species_str(markup=True)
        self.assertEqual(remove_zws(sp_str), s)

        self.ac1.id_qual = "cf."
        self.ac1.id_qual_rank = "sp"
        s = "<i>Echinocactus</i> cf. <i>grusonii</i>"
        sp_str = self.ac1.species_str(markup=True)
        self.assertEqual(remove_zws(sp_str), s)

        self.ac1.id_qual = "aff."
        self.ac1.id_qual_rank = "sp"
        s = "Echinocactus aff. grusonii"
        sp_str = self.ac1.species_str()
        self.assertEqual(remove_zws(sp_str), s)

        self.ac1.id_qual = "forsan"
        self.ac1.id_qual_rank = "sp"
        s = "Echinocactus forsan grusonii"
        sp_str = self.ac1.species_str()
        self.assertEqual(remove_zws(sp_str), s)

        ## add cultivar to species and refer to it as cf.
        self.ac1.species.cultivar_epithet = "Cultivar"
        self.ac1.id_qual = "cf."
        self.ac1.id_qual_rank = "cv"
        s = "Echinocactus grusonii cf. 'Cultivar'"
        sp_str = self.ac1.species_str()
        self.assertEqual(remove_zws(sp_str), s)

    def test_species_str_qualification_appended(self):
        # previously, if the id_qual is set but the id_qual_rank isn't then
        # we would get an error.
        # NOTE handy for not breaking imports etc. but the entry will be set to
        # genus level when opened in the editor (user can then select)
        self.ac1.id_qual = None
        self.ac1.id_qual = "?"
        s = "Echinocactus grusonii (?)"
        sp_str = self.ac1.species_str()
        self.assertEqual(remove_zws(sp_str), s)

        # species.infrasp is still none but these just get pasted on
        # the end so it doesn't matter
        self.ac1.id_qual = "incorrect"
        self.ac1.id_qual_rank = "infrasp"
        s = "Echinocactus grusonii (incorrect)"
        sp_str = self.ac1.species_str()
        self.assertEqual(remove_zws(sp_str), s)

        self.ac1.id_qual = "incorrect"
        self.ac1.id_qual_rank = "sp"
        s = "<i>Echinocactus</i> <i>grusonii</i> (incorrect)"
        sp_str = self.ac1.species_str(markup=True)
        self.assertEqual(remove_zws(sp_str), s)

    def test_species_str_be_specific_in_infraspecific(self):
        "be specific qualifying infraspecific identification - still unused"
        ## add cv to species with variety and refer to it as cf.
        self.sp3.cultivar_epithet = "Cultivar"
        self.ac2.id_qual = "cf."
        self.ac2.id_qual_rank = "cv"
        s = "Echinocactus grusonii var. albispinus cf. 'Cultivar'"
        sp_str = self.ac2.species_str()
        self.assertEqual(remove_zws(sp_str), s)

        self.ac2.id_qual = "cf."
        self.ac2.id_qual_rank = "infrasp1"
        s = "Echinocactus grusonii cf. var. albispinus 'Cultivar'"
        sp_str = self.ac2.species_str()
        self.assertEqual(remove_zws(sp_str), s)

    def test_species_str_unsorted_infraspecific(self):
        "be specific qualifying infraspecific identification - still unused"
        ## add  to species with variety and refer to it as cf.
        self.sp3.set_infrasp(1, "var.", "aizoon")
        self.sp3.set_infrasp(2, "subvar.", "brevifolia")
        self.sp3.set_infrasp(3, "f.", "multicaulis")
        self.ac2.id_qual = "cf."
        self.ac2.id_qual_rank = "infrasp3"
        # s = u"Echinocactus grusonii f. cf. multicaulis"
        sp_str = self.ac2.species_str()
        # self.assertEquals(remove_zws(sp_str), s)
        self.assertTrue(sp_str.endswith("cf. f. multicaulis"))

        self.sp3.set_infrasp(4, "subf.", "surculosa")
        self.ac2.id_qual = "cf."
        self.ac2.id_qual_rank = "infrasp4"
        # s = u"Echinocactus grusonii subf. cf. surculosa"
        sp_str = self.ac2.species_str()
        # self.assertEquals(remove_zws(sp_str), s)
        self.assertTrue(sp_str.endswith("cf. subf. surculosa"))

    def test_qualified_name(self):
        # make sure accessing as class attribute doesn't fail
        self.assertIsNotNone(Accession.qualified_name)

        self.assertEqual(self.ac1.species_str(), self.ac1.qualified_name)

        self.ac1.id_qual = "?"
        self.ac1.id_qual_rank = "sp"
        self.assertEqual("Echinocactus ? grusonii", self.ac1.species_str())
        self.assertEqual(self.ac1.species_str(), self.ac1.qualified_name)


class AccessionTests(GardenTestCase):
    def test_delete(self):
        """
        Test that when an accession is deleted any orphaned rows are
        cleaned up.
        """
        acc = self.create(Accession, species=self.species, code="1")
        plant = self.create(
            Plant,
            accession=acc,
            quantity=1,
            location=Location(name="site", code="STE"),
            code="1",
        )
        self.session.commit()

        # test that the plant is deleted after being orphaned
        plant_id = plant.id
        self.session.delete(acc)
        self.session.commit()
        self.assertFalse(self.session.query(Plant).get(plant_id))

    def test_constraints(self):
        """
        Test the constraints on the accession table.
        """
        acc = Accession(species=self.species, code="1")
        self.session.add(acc)
        self.session.commit()

        # test that accession.code is unique
        acc = Accession(species=self.species, code="1")
        self.session.add(acc)
        self.assertRaises(IntegrityError, self.session.commit)

    def test_search_view_markup_pair(self):
        acc = self.session.query(Accession).first()
        self.assertEqual(
            acc.search_view_markup_pair(),
            (
                '2001.1<span foreground="#555555" size="small" '
                'weight="light"> - 1 plant groups in 1 '
                "location(s)</span>",
                "<i>Maxillaria</i> s. str <i>variabilis</i>   "
                '<span weight="light">(Orchidaceae)  CITES:II</span>',
            ),
        )
        # with details
        acc.species.red_list = "VU"
        self.assertEqual(
            acc.search_view_markup_pair(),
            (
                '2001.1<span foreground="#555555" size="small" '
                'weight="light"> - 1 plant groups in 1 '
                "location(s)</span>",
                "<i>Maxillaria</i> s. str <i>variabilis</i>   "
                '<span weight="light">(Orchidaceae)  '
                "RedList:VU  CITES:II</span>",
            ),
        )
        type(acc.species)._sp_custom1._custom_column_short_hand = "T1"
        acc.species._sp_custom1 = "Vunerable"
        type(acc.species)._sp_custom2._custom_column_short_hand = "T2"
        acc.species._sp_custom2 = "Endangered"
        self.assertEqual(
            acc.search_view_markup_pair(),
            (
                '2001.1<span foreground="#555555" size="small" '
                'weight="light"> - 1 plant groups in 1 '
                "location(s)</span>",
                "<i>Maxillaria</i> s. str <i>variabilis</i>   "
                '<span weight="light">(Orchidaceae)  '
                "T1:V  T2:E  RedList:VU  CITES:II</span>",
            ),
        )
        acc.species.red_list = None
        acc.species._sp_custom1 = None
        acc.species._sp_custom2 = None

        acc.plants[0].quantity = 0
        self.assertEqual(
            acc.search_view_markup_pair(),
            (
                '<span foreground="#9900ff">2001.1</span>',
                "<i>Maxillaria</i> s. str <i>variabilis</i>   "
                '<span weight="light">(Orchidaceae)  CITES:II</span>',
            ),
        )
        acc = Accession(species=self.species, code="2023.1")
        self.session.add(acc)
        self.session.commit()
        self.assertEqual(
            acc.search_view_markup_pair(),
            (
                "2023.1",
                "<i>Echinocactus</i> <i>grusonii</i>   "
                '<span weight="light">(Cactaceae)</span>',
            ),
        )

    def test_accession_source_editor(self):
        # create an accession, a location, a plant
        parent = self.create(
            Accession, species=self.species, code="parent", quantity_recvd=1
        )
        plant = self.create(
            Plant,
            accession=parent,
            quantity=1,
            location=Location(name="site", code="STE"),
            code="1",
        )
        # create a propagation without a related seed/cutting
        prop = self.create(
            Propagation, prop_type="Seed", date=utils.utcnow_naive()
        )
        seed = PropSeed(
            nseeds=10,
            date_sown="11-01-2021",
            nseedlings=9,
            germ_date="21-02-2021",
        )
        prop.seed = seed
        plant.propagations.append(prop)
        # commit all the above to the database
        self.session.commit()
        self.assertTrue(prop.id > 0)  # we got a valid id after the commit
        plant_prop_id = prop.id

        acc = Accession(code="code", species=self.species, quantity_recvd=2)
        editor = AccessionEditor(acc)
        # normally called by editor.presenter.start() but we don't call it here
        editor.presenter.source_presenter.start()
        widgets = editor.presenter.view.widgets
        update_gui()

        # set the date so the presenter will be "dirty"
        widgets.acc_date_recvd_entry.props.text = utils.today_str()

        # set the source type as "Garden Propagation"
        widgets.acc_source_comboentry.get_child().props.text = (
            SourcePresenter.GARDEN_PROP_STR
        )
        self.assertFalse(editor.presenter.problems)

        # set the source plant
        widgets.source_prop_plant_entry.props.text = str(plant)
        widgets.source_prop_plant_entry.emit("changed")
        logger.debug("about to update the gui")
        update_gui()

        logger.debug("about to update the gui")
        update_gui()  # ensures idle callback is called

        # assert that the propagations were added to the treeview
        treeview = widgets.source_prop_treeview
        self.assertTrue(treeview.get_model())

        # select the first propagation in the treeview
        toggle_cell = widgets.prop_toggle_cell.emit("toggled", 0)
        self.assertTrue(toggle_cell is None)

        # commit the changes and cleanup
        editor.handle_response(Gtk.ResponseType.OK)
        editor.session.close()
        editor.presenter.cleanup()

        # open a separate session and make sure everything committed
        session = db.Session()
        acc = session.query(Accession).filter_by(code="code").first()
        self.assertIsNotNone(acc)
        logger.debug(acc.id)
        parent = session.query(Accession).filter_by(code="parent")[0]
        self.assertTrue(parent is not None)
        logger.debug(parent.id)
        logger.debug("acc plants : %s", [str(i) for i in acc.plants])
        logger.debug("parent plants : %s", [str(i) for i in parent.plants])
        logger.debug(acc.source.__dict__)
        self.assertEqual(acc.source.plant_propagation_id, plant_prop_id)
        del editor

    def test_accession_editor(self):
        acc = Accession(code="code", species=self.species)
        editor = AccessionEditor(acc)
        update_gui()

        widgets = editor.presenter.view.widgets
        # make sure there is a problem if the species entry text isn't
        # a species string
        widgets.acc_species_entry.set_text("asdasd")
        self.assertTrue(editor.presenter.problems)

        # make sure the problem is removed if the species entry text
        # is set to a species string

        # fill in the completions
        widgets.acc_species_entry.set_text(str(self.species)[0:3])
        update_gui()  # ensures idle callback is called to add completions
        # set the fill string which should match from completions
        widgets.acc_species_entry.set_text(str(self.species))
        self.assertFalse(editor.presenter.problems)

        # commit the changes and cleanup
        editor.model.name = "asda"

        editor.handle_response(Gtk.ResponseType.OK)
        editor.session.close()
        editor.presenter.cleanup()
        del editor

    def test_accession_editor_purchase_price_entry_change(self):
        sp = self.session.query(Species).first()
        acc = Accession(code="2023", species=sp)
        self.session.add(acc)
        # commit so the presenter can use the object_session
        self.session.commit()
        presenter = AccessionEditorPresenter(acc, AccessionEditorView())
        mock_entry = unittest.mock.Mock()
        # saves as cents
        mock_entry.get_text.return_value = "1.00"
        presenter.on_price_entry_changed(mock_entry)
        self.assertEqual(acc.purchase_price, 100)
        # set none
        mock_entry.get_text.return_value = ""
        presenter.on_price_entry_changed(mock_entry)
        self.assertIsNone(acc.purchase_price)
        presenter.cleanup()
        del presenter

    def test_accession_editor_price_unit_entry_change(self):
        sp = self.session.query(Species).first()
        acc = Accession(code="2023", species=sp)
        self.session.add(acc)
        # commit so the presenter can use the object_session
        self.session.commit()
        presenter = AccessionEditorPresenter(acc, AccessionEditorView())
        mock_entry = unittest.mock.Mock()
        # set value
        mock_entry.get_text.return_value = "AU$"
        presenter.on_price_unit_entry_changed(mock_entry)
        self.assertEqual(acc.price_unit, "AU$")
        # unset value
        mock_entry.get_text.return_value = ""
        presenter.on_price_unit_entry_changed(mock_entry)
        self.assertIsNone(acc.price_unit)
        presenter.cleanup()
        del presenter

    def test_accession_editor_price_unit_combo_change(self):
        sp = self.session.query(Species).first()
        acc = Accession(code="2023", species=sp)
        self.session.add(acc)
        # commit so the presenter can use the object_session
        self.session.commit()
        presenter = AccessionEditorPresenter(acc, AccessionEditorView())
        mock_combo = unittest.mock.Mock()
        mock_entry = unittest.mock.MagicMock()
        mock_combo.get_child.return_value = mock_entry
        # set value
        mock_combo.get_active_iter.return_value = 0
        mock_combo.get_model.return_value = [["AU$"]]
        presenter.on_price_unit_combo_changed(mock_combo)
        self.assertEqual(mock_entry.set_text.call_args.args[0], "AU$")
        presenter.cleanup()
        del presenter

    @unittest.mock.patch("bauble.editor.GenericEditorView.start")
    def test_editor_doesnt_leak(self, mock_start):
        mock_start.return_value = Gtk.ResponseType.OK
        sp2 = Species(genus=self.genus, sp="species")
        sp2.synonyms.append(self.species)
        self.session.add(sp2)
        self.session.commit()
        acc_code = "%s%s1" % (
            datetime.date.today().year,
            Plant.get_delimiter(),
        )
        acc = self.create(Accession, species=self.species, code=acc_code)
        voucher = Voucher(herbarium="abcd", code="123")
        acc.vouchers.append(voucher)

        # add verificaiton
        ver = Verification()
        ver.verifier = "me"
        ver.date = datetime.date.today()
        ver.prev_species = self.species
        ver.species = self.species
        ver.level = 1
        acc.verifications.append(ver)

        source_detail = SourceDetail(
            name="Test Source", source_type="Expedition"
        )
        source = Source(sources_code="22")
        source.source_detail = source_detail
        acc.source = source

        self.session.commit()

        editor = AccessionEditor(model=acc)
        editor.start()
        del editor

        self.assertEqual(utils.gc_objects_by_type("AccessionEditor"), [])
        self.assertEqual(
            utils.gc_objects_by_type("AccessionEditorPresenter"), []
        )
        self.assertEqual(utils.gc_objects_by_type("AccessionEditorView"), [])

    def test_remove_callback_no_plants_no_confirm(self):
        # T_0
        added = []
        added.append(Family(family="Caricaceae"))
        added.append(Genus(epithet="Carica", family=added[-1]))
        added.append(Species(epithet="papaya", genus=added[-1]))
        added.append(Accession(code="010101", species=added[-1]))
        sp, acc = added[-2:]
        self.session.add_all(added)
        self.session.flush()
        self.invoked = []

        # action
        orig_yes_no_dialog = utils.yes_no_dialog
        orig_message_details_dialog = utils.message_details_dialog
        utils.yes_no_dialog = partial(
            mockfunc, name="yes_no_dialog", caller=self, result=False
        )
        utils.message_details_dialog = partial(
            mockfunc, name="message_details_dialog", caller=self
        )
        from bauble.plugins.garden.accession import remove_callback

        result = remove_callback([acc])
        self.session.flush()

        # effect
        self.assertFalse(
            "message_details_dialog" in [f for (f, m) in self.invoked]
        )
        self.assertTrue(
            (
                "yes_no_dialog",
                "Are you sure you want to remove "
                "the following accessions <b>010101</b>?",
            )
            in self.invoked
        )
        self.assertEqual(result, False)
        q = self.session.query(Accession).filter_by(code="010101", species=sp)
        matching = q.all()
        self.assertEqual(matching, [acc])
        utils.yes_no_dialog = orig_yes_no_dialog
        utils.message_details_dialog = orig_message_details_dialog

    def test_remove_callback_no_accessions_confirm(self):
        # T_0
        added = []
        added.append(Family(family="Caricaceae"))
        added.append(Genus(epithet="Carica", family=added[-1]))
        added.append(Species(epithet="papaya", genus=added[-1]))
        added.append(Accession(code="010101", species=added[-1]))
        sp, acc = added[-2:]
        self.session.add_all(added)
        self.session.flush()
        self.invoked = []

        # action
        orig_yes_no_dialog = utils.yes_no_dialog
        orig_message_details_dialog = utils.message_details_dialog
        utils.yes_no_dialog = partial(
            mockfunc, name="yes_no_dialog", caller=self, result=True
        )
        utils.message_details_dialog = partial(
            mockfunc, name="message_details_dialog", caller=self
        )
        from bauble.plugins.garden.accession import remove_callback

        result = remove_callback([acc])
        self.session.flush()

        # effect
        self.assertFalse(
            "message_details_dialog" in [f for (f, m) in self.invoked]
        )
        self.assertTrue(
            (
                "yes_no_dialog",
                "Are you sure you want to remove "
                "the following accessions <b>010101</b>?",
            )
            in self.invoked
        )

        self.assertEqual(result, True)
        q = self.session.query(Species).filter_by(sp="Carica")
        matching = q.all()
        self.assertEqual(matching, [])
        utils.yes_no_dialog = orig_yes_no_dialog
        utils.message_details_dialog = orig_message_details_dialog

    def test_remove_callback_with_accessions_cant_cascade(self):
        # T_0
        added = []
        added.append(Location(code="INV99"))
        added.append(Family(family="Caricaceae"))
        added.append(Genus(epithet="Carica", family=added[-1]))
        added.append(Species(epithet="papaya", genus=added[-1]))
        added.append(Accession(code="010101", species=added[-1]))
        added.append(
            Plant(code="1", accession=added[-1], quantity=1, location=added[0])
        )
        sp, acc, plant = added[-3:]
        self.session.add_all(added)
        self.session.flush()
        self.invoked = []

        # action
        orig_yes_no_dialog = utils.yes_no_dialog
        orig_message_dialog = utils.message_dialog
        orig_message_details_dialog = utils.message_details_dialog
        utils.yes_no_dialog = partial(
            mockfunc, name="yes_no_dialog", caller=self, result=True
        )
        utils.message_dialog = partial(
            mockfunc, name="message_dialog", caller=self, result=True
        )
        utils.message_details_dialog = partial(
            mockfunc, name="message_details_dialog", caller=self
        )
        from bauble.plugins.garden.accession import remove_callback

        result = remove_callback([acc])
        self.session.flush()

        # effect
        self.assertFalse(
            "message_details_dialog" in [f for (f, m) in self.invoked]
        )
        self.assertTrue(
            (
                "message_dialog",
                "1 plants depend on this accession: <b>010101.1</b>\n\n"
                "You cannot remove an accession with plants.",
            )
            in self.invoked
        )
        q = self.session.query(Accession).filter_by(species=sp)
        matching = q.all()
        self.assertEqual(matching, [acc])
        q = self.session.query(Plant).filter_by(accession=acc)
        matching = q.all()
        self.assertEqual(matching, [plant])
        utils.yes_no_dialog = orig_yes_no_dialog
        utils.message_dialog = orig_message_dialog
        utils.message_details_dialog = orig_message_details_dialog

    def test_active_no_plants(self):
        acc = self.create(Accession, species=self.species, code="1")
        self.session.commit()
        self.assertTrue(acc.active)
        # test the hybrid_property expression
        # pylint: disable=no-member  # is_
        acc_active_in_db = self.session.query(Accession).filter(
            Accession.active.is_(True)
        )
        self.assertIn(acc, acc_active_in_db)

    def test_active_plants_w_qty(self):
        acc = self.create(Accession, species=self.species, code="1")
        self.create(
            Plant,
            accession=acc,
            quantity=1,
            location=Location(name="site", code="STE"),
            code="1",
        )
        self.session.commit()
        self.assertTrue(acc.active)
        # test the hybrid_property expression
        # pylint: disable=no-member
        acc_active_in_db = self.session.query(Accession).filter(
            Accession.active.is_(True)
        )
        self.assertIn(acc, acc_active_in_db)

    def test_active_plants_wo_qty(self):
        acc = self.create(Accession, species=self.species, code="1")
        self.create(
            Plant,
            accession=acc,
            quantity=0,
            location=Location(name="site", code="STE"),
            code="1",
        )
        self.session.commit()
        self.assertFalse(acc.active)
        # test the hybrid_property expression
        # pylint: disable=no-member
        acc_active_in_db = self.session.query(Accession).filter(
            Accession.active.is_(True)
        )
        self.assertNotIn(acc, acc_active_in_db)

    def test_count_children_wo_plants(self):
        acc = self.create(Accession, species=self.species, code="1")
        self.session.commit()

        self.assertEqual(acc.count_children(), 0)

    def test_count_children_w_plant_w_qty(self):
        acc = self.create(Accession, species=self.species, code="1")
        self.create(
            Plant,
            accession=acc,
            quantity=1,
            location=Location(name="site", code="STE"),
            code="1",
        )
        self.session.commit()

        self.assertEqual(acc.count_children(), 1)

    def test_count_children_w_plant_w_qty_exclude_inactive_set(self):
        # should be the same as if exclude inactive not set.
        acc = self.create(Accession, species=self.species, code="1")
        self.create(
            Plant,
            accession=acc,
            quantity=1,
            location=Location(name="site", code="STE"),
            code="1",
        )
        self.session.commit()

        prefs.prefs[prefs.exclude_inactive_pref] = True

        self.assertEqual(acc.count_children(), 1)

    def test_count_children_w_plant_wo_qty(self):
        acc = self.create(Accession, species=self.species, code="1")
        self.create(
            Plant,
            accession=acc,
            quantity=0,
            location=Location(name="site", code="STE"),
            code="1",
        )
        self.session.commit()

        self.assertEqual(acc.count_children(), 1)

    def test_count_children_w_plant_wo_qty_exclude_inactive_set(self):
        acc = self.create(Accession, species=self.species, code="1")
        self.create(
            Plant,
            accession=acc,
            quantity=0,
            location=Location(name="site", code="STE"),
            code="1",
        )
        self.session.commit()

        prefs.prefs[prefs.exclude_inactive_pref] = True

        self.assertEqual(acc.count_children(), 0)

    def test_top_level_count_w_plant_qty(self):
        acc = self.create(Accession, species=self.species, code="1")
        self.create(
            Plant,
            accession=acc,
            quantity=1,
            location=Location(name="site", code="STE"),
            code="1",
        )
        self.session.commit()

        self.assertEqual(acc.top_level_count()[(1, "Accessions")], 1)
        self.assertEqual(len(acc.top_level_count()[(2, "Species")]), 1)
        self.assertEqual(len(acc.top_level_count()[(3, "Genera")]), 1)
        self.assertEqual(len(acc.top_level_count()[(4, "Families")]), 1)
        self.assertEqual(acc.top_level_count()[(5, "Plantings")], 1)
        self.assertEqual(acc.top_level_count()[(6, "Living plants")], 1)
        self.assertEqual(len(acc.top_level_count()[(7, "Locations")]), 1)
        self.assertEqual(len(acc.top_level_count()[(8, "Sources")]), 0)

    def test_top_level_count_wo_plant_qty(self):
        acc = self.create(Accession, species=self.species, code="1")
        self.create(
            Plant,
            accession=acc,
            quantity=0,
            location=Location(name="site", code="STE"),
            code="1",
        )
        self.session.commit()

        self.assertEqual(acc.top_level_count()[(1, "Accessions")], 1)
        self.assertEqual(len(acc.top_level_count()[(2, "Species")]), 1)
        self.assertEqual(len(acc.top_level_count()[(3, "Genera")]), 1)
        self.assertEqual(len(acc.top_level_count()[(4, "Families")]), 1)
        self.assertEqual(acc.top_level_count()[(5, "Plantings")], 1)
        self.assertEqual(acc.top_level_count()[(6, "Living plants")], 0)
        self.assertEqual(len(acc.top_level_count()[(7, "Locations")]), 1)
        self.assertEqual(len(acc.top_level_count()[(8, "Sources")]), 0)

    def test_top_level_count_wo_plant_qty_exclude_inactive_set(self):
        # NOTE in the reality this accession would not show in search view with
        # exclude inactive set unless it had a second alive plant (and
        # hence top_level_count would not be called) but thats not a concern
        # here.
        acc = self.create(Accession, species=self.species, code="1")
        self.create(
            Plant,
            accession=acc,
            quantity=0,
            location=Location(name="site", code="STE"),
            code="1",
        )
        self.session.commit()

        prefs.prefs[prefs.exclude_inactive_pref] = True

        self.assertEqual(acc.top_level_count()[(1, "Accessions")], 1)
        self.assertEqual(len(acc.top_level_count()[(2, "Species")]), 1)
        self.assertEqual(len(acc.top_level_count()[(3, "Genera")]), 1)
        self.assertEqual(len(acc.top_level_count()[(4, "Families")]), 1)
        self.assertEqual(acc.top_level_count()[(5, "Plantings")], 0)
        self.assertEqual(acc.top_level_count()[(6, "Living plants")], 0)
        self.assertEqual(len(acc.top_level_count()[(7, "Locations")]), 0)
        self.assertEqual(len(acc.top_level_count()[(8, "Sources")]), 0)

    def test_pictures(self):
        acc = self.session.query(Accession).first()
        self.assertEqual(acc.pictures, [])
        plt = acc.plants[0]
        ppic = PlantPicture(picture="test1.jpg", plant=plt)
        self.session.commit()
        self.assertEqual(acc.pictures, [ppic])
        plt.quantity = 0
        self.session.commit()
        # exclude inactive
        prefs.prefs[prefs.exclude_inactive_pref] = True
        self.assertEqual(acc.pictures, [])
        # detached returns empty
        self.session.expunge(acc)
        self.assertEqual(acc.pictures, [])


class IntendedLocationsTests(GardenTestCase):
    @staticmethod
    def set_combo_from_value(combo, value):
        model = combo.props.model
        matches = utils.search_tree_model(model, value)
        if len(matches) == 0:
            raise ValueError(f"could not find value in combo: {value}")
        combo.set_active_iter(matches[0])
        combo.emit("changed")

    def test_intended_locations_cascades_delete_accession(self):
        sp = self.session.query(Species).first()
        acc = Accession(code="2023", species=sp)
        loc1 = Location(code="LOC1")
        int_loc = IntendedLocation(
            quantity=1, location=loc1, date=datetime.datetime.now().date()
        )
        acc.intended_locations.append(int_loc)
        self.session.add_all([acc, loc1])
        self.session.commit()
        self.assertEqual(self.session.query(IntendedLocation).count(), 1)
        # intended_locations are removed if accession is removed.
        self.session.delete(acc)
        self.session.commit()
        self.assertFalse(self.session.query(IntendedLocation).all())

    def test_delete_intended_locations_doesnt_cascade_to_loc_acc(self):
        sp = self.session.query(Species).first()
        acc = Accession(code="2023", species=sp)
        loc1 = Location(code="LOC1")
        int_loc = IntendedLocation(
            quantity=1, location=loc1, date=datetime.datetime.now().date()
        )
        acc.intended_locations.append(int_loc)
        self.session.add_all([acc, loc1])
        self.session.commit()
        # accession is not removed if intended_location is removed.
        self.session.delete(int_loc)
        self.session.commit()
        self.assertEqual(acc, self.session.query(Accession).get(acc.id))
        self.assertEqual(loc1, self.session.query(Location).get(loc1.id))

    def test_intended_locations_cascades_delete_location(self):
        sp = self.session.query(Species).first()
        acc = Accession(code="2023", species=sp)
        loc1 = Location(code="LOC1")
        int_loc = IntendedLocation(
            quantity=1, location=loc1, date=datetime.datetime.now().date()
        )
        acc.intended_locations.append(int_loc)
        self.session.add_all([acc, loc1])
        self.session.commit()
        self.assertEqual(self.session.query(IntendedLocation).count(), 1)
        # intended_locations are removed if location is removed.
        self.session.delete(loc1)
        self.session.commit()
        self.assertFalse(self.session.query(IntendedLocation).all())

    def test_refresh_sets_dirty_true_when_all_fields_full(self):
        presenter = IntendedLocationPresenter(
            unittest.mock.MagicMock(),
            Accession(),
            AccessionEditorView(),
            self.session,
        )
        presenter.refresh(
            unittest.mock.Mock(
                quantity=1, location=Location(), date=datetime.datetime.now()
            )
        )
        self.assertTrue(presenter.is_dirty())

    def test_refresh_sets_dirty_false_when_location_missing(self):
        presenter = IntendedLocationPresenter(
            unittest.mock.MagicMock(),
            Accession(),
            AccessionEditorView(),
            self.session,
        )
        presenter.refresh(
            unittest.mock.Mock(
                quantity=1, location=None, date=datetime.datetime.now()
            )
        )
        self.assertFalse(presenter.is_dirty())
        presenter.cleanup()

    def test_refresh_sets_dirty_false_when_date_missing(self):
        presenter = IntendedLocationPresenter(
            unittest.mock.MagicMock(),
            Accession(),
            AccessionEditorView(),
            self.session,
        )
        presenter.refresh(
            unittest.mock.Mock(quantity=1, location=Location(), date=None)
        )
        self.assertFalse(presenter.is_dirty())
        presenter.cleanup()

    def test_refresh_sets_dirty_false_when_qty_missing_or_0(self):
        presenter = IntendedLocationPresenter(
            unittest.mock.MagicMock(),
            Accession(),
            AccessionEditorView(),
            self.session,
        )
        presenter.refresh(
            unittest.mock.Mock(
                quantity=None,
                location=Location(),
                date=datetime.datetime.now(),
            )
        )
        self.assertFalse(presenter.is_dirty())
        presenter.refresh(
            unittest.mock.Mock(
                quantity=0, location=Location(), date=datetime.datetime.now()
            )
        )
        self.assertFalse(presenter.is_dirty())
        presenter.cleanup()

    def test_cell_data_func(self):
        presenter = IntendedLocationPresenter(
            unittest.mock.MagicMock(),
            Accession(),
            AccessionEditorView(),
            self.session,
        )

        cell = Gtk.CellRendererText()
        # plain text
        # pylint: disable=no-member,protected-access
        mock_obj = unittest.mock.Mock(prop="test")
        presenter._cell_data_func(None, cell, [[mock_obj]], 0, "prop")
        self.assertEqual(cell.props.text, "test")
        # date
        date = datetime.datetime.now().date()
        mock_obj = unittest.mock.Mock(date=date)
        presenter._cell_data_func(None, cell, [[mock_obj]], 0, "date")
        frmt = prefs.prefs[prefs.date_format_pref]
        self.assertEqual(cell.props.text, date.strftime(frmt))
        # empty date
        date = None
        mock_obj = unittest.mock.Mock(date=date)
        presenter._cell_data_func(None, cell, [[mock_obj]], 0, "date")
        frmt = prefs.prefs[prefs.date_format_pref]
        self.assertEqual(cell.props.text, "")
        # toggle
        cell = Gtk.CellRendererToggle()
        self.assertFalse(cell.get_active())
        mock_obj = unittest.mock.Mock(prop=True)
        presenter._cell_data_func(None, cell, [[mock_obj]], 0, "prop")
        self.assertTrue(cell.get_active())

        presenter.cleanup()

    def test_refresh_only_called_when_value_changes_loc(self):
        sp = self.session.query(Species).first()
        acc = Accession(code="2023", species=sp)
        loc1 = Location(code="LOC1")
        loc2 = Location(code="LOC2")
        acc.intended_locations.append(
            IntendedLocation(
                quantity=1, location=loc1, date=datetime.datetime.now().date()
            )
        )
        self.session.add_all([acc, loc1, loc2])
        self.session.commit()
        mock_parent = unittest.mock.MagicMock()
        presenter = IntendedLocationPresenter(
            mock_parent, acc, AccessionEditorView(), self.session
        )
        combo = Gtk.ComboBox.new_with_entry()
        presenter.on_loc_editing_started(None, combo, Gtk.TreePath.new_first())
        mockrefresh = unittest.mock.Mock()
        presenter.refresh = mockrefresh
        # no change
        self.set_combo_from_value(combo, loc1)
        mockrefresh.assert_not_called()
        # changed
        self.set_combo_from_value(combo, loc2)
        mockrefresh.assert_called()
        presenter.cleanup()

    def test_refresh_only_called_when_value_changes_qty(self):
        acc = Accession()
        loc1 = Location(code="LOC1")
        loc2 = Location(code="LOC2")
        acc.intended_locations.append(
            IntendedLocation(
                quantity=1, location=loc1, date=datetime.datetime.now()
            )
        )
        self.session.add_all([acc, loc1, loc2])
        presenter = IntendedLocationPresenter(
            unittest.mock.MagicMock(), acc, AccessionEditorView(), self.session
        )
        mockrefresh = unittest.mock.Mock()
        presenter.refresh = mockrefresh

        # not callled
        presenter.on_qty_cell_edited(None, Gtk.TreePath.new_first(), 1)
        mockrefresh.assert_not_called()
        presenter.on_qty_cell_edited(None, Gtk.TreePath.new_first(), 0)
        mockrefresh.assert_not_called()
        presenter.on_qty_cell_edited(None, Gtk.TreePath.new_first(), None)
        mockrefresh.assert_not_called()

        # called
        presenter.on_qty_cell_edited(None, Gtk.TreePath.new_first(), 10)
        mockrefresh.assert_called()
        presenter.cleanup()

    def test_refresh_only_called_when_value_changes_planted(self):
        acc = Accession()
        loc1 = Location(code="LOC1")
        loc2 = Location(code="LOC2")
        acc.intended_locations.append(
            IntendedLocation(
                quantity=1,
                location=loc1,
                date=datetime.datetime.now(),
                planted=False,
            )
        )
        self.session.add_all([acc, loc1, loc2])
        presenter = IntendedLocationPresenter(
            unittest.mock.MagicMock(), acc, AccessionEditorView(), self.session
        )
        mockrefresh = unittest.mock.Mock()
        presenter.refresh = mockrefresh

        # not callled
        mockcell = unittest.mock.Mock()
        mockcell.get_active.return_value = True
        presenter.on_planted_toggled(mockcell, Gtk.TreePath.new_first())
        mockrefresh.assert_not_called()

        # called
        mockcell.get_active.return_value = False
        presenter.on_planted_toggled(mockcell, Gtk.TreePath.new_first())
        mockrefresh.assert_called()
        presenter.cleanup()

    def test_refresh_only_called_when_value_changes_date(self):
        acc = Accession()
        loc1 = Location(code="LOC1")
        loc2 = Location(code="LOC2")
        date = datetime.datetime.now().date()
        acc.intended_locations.append(
            IntendedLocation(
                quantity=1, location=loc1, date=date, planted=False
            )
        )
        self.session.add_all([acc, loc1, loc2])
        presenter = IntendedLocationPresenter(
            unittest.mock.MagicMock(), acc, AccessionEditorView(), self.session
        )
        mockrefresh = unittest.mock.Mock()
        presenter.refresh = mockrefresh

        # not callled - iso parse should work here
        presenter.on_date_cell_edited(
            None, Gtk.TreePath.new_first(), str(date)
        )
        mockrefresh.assert_not_called()

        # called
        presenter.on_date_cell_edited(
            None, Gtk.TreePath.new_first(), "25/09/2023"
        )
        mockrefresh.assert_called()
        presenter.cleanup()

    def test_context_menu_add_plant_only_available_when_planted_false(self):
        acc = Accession()
        loc1 = Location(code="LOC1")
        loc2 = Location(code="LOC2")
        date = datetime.datetime.now().date()
        int_loc = IntendedLocation(
            quantity=1, location=loc1, date=date, planted=False
        )
        acc.intended_locations.append(int_loc)
        self.session.add_all([acc, loc1, loc2])
        presenter = IntendedLocationPresenter(
            unittest.mock.MagicMock(), acc, AccessionEditorView(), self.session
        )

        treeview = presenter.view.widgets.intended_loc_treeview
        action_group = treeview.get_action_group(INTENDED_ACTIONGRP_NAME)
        plant_action = action_group.lookup_action("plant")

        tree_selection = treeview.get_selection()
        # set the cursor
        treeview.set_cursor(Gtk.TreePath.new_first())

        presenter.on_selection_changed(tree_selection)
        self.assertTrue(plant_action.get_enabled())

        int_loc.planted = True
        presenter.on_selection_changed(tree_selection)
        self.assertFalse(plant_action.get_enabled())

        presenter.cleanup()

    def test_context_menu_show_map_only_available_when_geojson(self):
        acc = Accession()
        loc1 = Location(code="LOC1")
        loc2 = Location(code="LOC2")
        date = datetime.datetime.now().date()
        int_loc = IntendedLocation(
            quantity=1, location=loc1, date=date, planted=False
        )
        acc.intended_locations.append(int_loc)
        self.session.add_all([acc, loc1, loc2])
        presenter = IntendedLocationPresenter(
            unittest.mock.MagicMock(), acc, AccessionEditorView(), self.session
        )

        treeview = presenter.view.widgets.intended_loc_treeview
        action_group = treeview.get_action_group(INTENDED_ACTIONGRP_NAME)
        map_action = action_group.lookup_action("show")

        tree_selection = treeview.get_selection()
        # set the cursor
        treeview.set_cursor(Gtk.TreePath.new_first())

        presenter.on_selection_changed(tree_selection)
        self.assertFalse(map_action.get_enabled())

        loc1.geojson = {"test": "test"}
        presenter.on_selection_changed(tree_selection)
        self.assertTrue(map_action.get_enabled())

        presenter.cleanup()

    def test_button_release_returns_false_unless_button_3(self):
        presenter = IntendedLocationPresenter(
            unittest.mock.MagicMock(),
            Accession(),
            AccessionEditorView(),
            self.session,
        )

        mockmenu = unittest.mock.MagicMock()
        presenter.context_menu = mockmenu
        mockevent = unittest.mock.Mock(button=1)
        self.assertFalse(presenter.on_button_release(None, mockevent))
        mockmenu.popup_at_pointer.assert_not_called()

        mockevent = unittest.mock.Mock(button=3)
        self.assertTrue(presenter.on_button_release(None, mockevent))
        mockmenu.popup_at_pointer.assert_called()

        presenter.cleanup()

    @unittest.mock.patch("bauble.utils.desktop.open")
    def test_on_map_kml_show_produces_file(self, mock_open):
        acc = Accession()
        loc1 = Location(code="LOC1", geojson={"test": "test"})
        loc2 = Location(code="LOC2")
        acc.intended_locations.append(
            IntendedLocation(
                quantity=1,
                location=loc1,
                date=datetime.datetime.now(),
                planted=False,
            )
        )
        self.session.add_all([acc, loc1, loc2])
        presenter = IntendedLocationPresenter(
            unittest.mock.MagicMock(), acc, AccessionEditorView(), self.session
        )
        presenter.view.widgets.intended_loc_treeview.set_cursor(
            Gtk.TreePath.new_first()
        )
        template_str = "${value}"
        template = utils.get_temp_path()
        with template.open("w", encoding="utf-8") as f:
            f.write(template_str)
        from .location import LOC_KML_MAP_PREFS

        prefs.prefs[LOC_KML_MAP_PREFS] = str(template)

        presenter.on_map_kml_show()
        with open(mock_open.call_args.args[0], encoding="utf-8") as f:
            self.assertEqual(str(loc1), f.read())

        presenter.cleanup()

    @unittest.mock.patch("bauble.utils.yes_no_dialog")
    @unittest.mock.patch("bauble.plugins.garden.accession.PlantEditor")
    def test_on_add_plant_asks_to_commit(self, mockeditor, mock_dialog):
        sp = self.session.query(Species).first()
        acc = Accession(code="2023", species=sp)
        loc1 = Location(code="LOC1")
        loc2 = Location(code="LOC2")
        acc.intended_locations.append(
            IntendedLocation(
                quantity=1,
                location=loc1,
                date=datetime.datetime.now(),
                planted=False,
            )
        )
        self.session.add_all([acc, loc1, loc2])
        mock_parent = unittest.mock.MagicMock()
        presenter = IntendedLocationPresenter(
            mock_parent, acc, AccessionEditorView(), self.session
        )
        # nothing selected should bail
        presenter.on_add_plant()
        mockeditor.assert_not_called()

        # select something
        presenter.view.widgets.intended_loc_treeview.set_cursor(
            Gtk.TreePath.new_first()
        )
        mock_dialog.return_value = False

        # dialog should ask to commit
        presenter.on_add_plant()
        mockeditor.assert_not_called()
        mock_dialog.assert_called()

        # commit and reset mock
        self.session.commit()
        mock_dialog.reset_mock()

        # should not ask to commit just open PlantEditor
        presenter.on_add_plant()
        mockeditor.assert_called()
        mock_dialog.assert_not_called()

        presenter.cleanup()

    @unittest.mock.patch("bauble.plugins.garden.accession.PlantEditor")
    def test_on_add_plant_can_add_plants_without_effecting_current(
        self, mockeditor
    ):
        sp = self.session.query(Species).first()
        acc = Accession(code="2023", species=sp)
        loc1 = Location(code="LOC1")
        loc2 = Location(code="LOC2")
        int_loc = IntendedLocation(
            quantity=1,
            location=loc1,
            date=datetime.datetime.now(),
            planted=False,
        )
        acc.intended_locations.append(int_loc)
        self.session.add_all([acc, loc1, loc2])
        self.session.commit()

        mock_parent = unittest.mock.MagicMock()
        presenter = IntendedLocationPresenter(
            mock_parent, acc, AccessionEditorView(), self.session
        )
        # select something
        presenter.view.widgets.intended_loc_treeview.set_cursor(
            Gtk.TreePath.new_first()
        )
        mockeditor.start.return_value = True

        # add the NEW plant
        presenter.on_add_plant()

        # grab the model supplied to PlantEditor and treat it as it would be in
        # the editor when OK selected NOTE a bit dodgy! Emulating the presenter
        # ...But it does prove that the supplied object is not associated to
        # it's original session.
        model = mockeditor.call_args.kwargs["model"]
        model.code = "1"  # next available value
        session = db.Session()
        session.merge(model)
        session.commit()
        session.close()

        # at this point the only thing that should be in the original sessions
        # dirty is the IntendedLocation (as it is now planted=True)
        self.assertNotIn(sp, self.session.dirty)
        self.assertNotIn(acc, self.session.dirty)
        self.assertNotIn(loc1, self.session.dirty)
        self.assertNotIn(loc2, self.session.dirty)
        # the intended location has changed
        self.assertIn(int_loc, self.session.dirty)
        self.assertTrue(int_loc.planted)
        # nothing NEW in the original session
        self.assertFalse(self.session.new)

        presenter.cleanup()

    def test_on_tree_cursor_changed(self):
        # test the remove button is enabled appropriately
        presenter = IntendedLocationPresenter(
            unittest.mock.MagicMock(),
            Accession(),
            AccessionEditorView(),
            self.session,
        )
        button = presenter.view.widgets.int_loc_remove_button
        mock_treee_view = unittest.mock.Mock()
        # sets insensitive
        mock_treee_view.get_model.return_value = []
        presenter.on_tree_cursor_changed(mock_treee_view)
        self.assertFalse(button.get_sensitive())
        # sets sensitive
        mock_treee_view.get_model.return_value = [1]
        presenter.on_tree_cursor_changed(mock_treee_view)
        self.assertTrue(button.get_sensitive())

        presenter.cleanup()

    def test_on_add_clicked_adds(self):
        # test a new IntendedLocation is added
        acc = Accession()
        loc1 = Location(code="LOC1")
        self.session.add_all([acc, loc1])
        presenter = IntendedLocationPresenter(
            unittest.mock.MagicMock(), acc, AccessionEditorView(), self.session
        )
        # no intended_locations yet
        self.assertFalse(acc.intended_locations)

        presenter.on_add_clicked(None)
        # one added
        self.assertEqual(len(acc.intended_locations), 1)
        # with date and quantity set
        self.assertEqual(acc.intended_locations[0].quantity, 1)
        self.assertEqual(
            acc.intended_locations[0].date, datetime.datetime.now().date()
        )
        # treeview is selected and ready for input
        treeview = presenter.view.widgets.intended_loc_treeview
        self.assertTrue(all(treeview.get_cursor()))

        presenter.cleanup()

    def test_on_remove_clicked_removes(self):
        sp = self.session.query(Species).first()
        acc = Accession(code="2023", species=sp)
        loc1 = Location(code="LOC1")
        acc.intended_locations.append(
            IntendedLocation(
                quantity=1,
                location=loc1,
                date=datetime.datetime.now(),
                planted=False,
            )
        )
        presenter = IntendedLocationPresenter(
            unittest.mock.MagicMock(), acc, AccessionEditorView(), self.session
        )
        # has one intended_location
        self.assertEqual(len(acc.intended_locations), 1)
        # set the cursor
        treeview = presenter.view.widgets.intended_loc_treeview
        treeview.set_cursor(Gtk.TreePath.new_first())
        presenter.on_remove_clicked(None)

        # has no intended_locations
        self.assertFalse(acc.intended_locations)

        presenter.cleanup()

    def test_on_remove_clicked_removes_sets_dirty_old_only(self):
        sp = self.session.query(Species).first()
        acc = Accession(code="2023", species=sp)
        loc1 = Location(code="LOC1")
        loc2 = Location(code="LOC2")
        # need to commit the locations before committing the accession later
        self.session.add_all([loc1, loc2])
        self.session.commit()
        acc.intended_locations.append(
            IntendedLocation(
                quantity=1,
                location=loc1,
                date=datetime.datetime.now(),
                planted=False,
            )
        )
        mock_parent = unittest.mock.MagicMock()
        presenter = IntendedLocationPresenter(
            mock_parent, acc, AccessionEditorView(), self.session
        )
        # has one intended_location
        self.assertEqual(len(acc.intended_locations), 1)
        # set the cursor
        treeview = presenter.view.widgets.intended_loc_treeview
        treeview.set_cursor(Gtk.TreePath.new_first())
        presenter.on_remove_clicked(None)

        # has no intended_locations
        self.assertFalse(acc.intended_locations)
        # was new doesn't set dirty
        self.assertFalse(presenter.is_dirty())

        # commit an intended_location
        int_loc = IntendedLocation(
            quantity=1,
            location=loc2,
            date=datetime.datetime.now(),
            planted=False,
        )
        acc.intended_locations.append(int_loc)
        self.session.add(acc)
        self.session.commit()
        # has one intended_location
        self.assertEqual(len(acc.intended_locations), 1)
        # add it to the treeview
        model = treeview.get_model()
        model.insert(0, [int_loc])
        treeview.set_cursor(Gtk.TreePath.new_first())
        self.assertFalse(presenter.is_dirty())
        # click remove
        presenter.on_remove_clicked(None)

        # has no intended_locations
        self.assertFalse(acc.intended_locations)
        # was old does set dirty
        self.assertTrue(presenter.is_dirty())
        presenter.cleanup()


class VerificationTests(GardenTestCase):
    def test_verifications(self):
        acc = self.create(Accession, species=self.species, code="1")
        self.session.add(acc)
        self.session.commit()

        ver = Verification()
        ver.verifier = "me"
        ver.date = datetime.date.today()
        ver.level = 1
        ver.species = acc.species
        ver.prev_species = acc.species
        acc.verifications.append(ver)
        self.session.commit()
        self.assertTrue(ver in acc.verifications)
        self.assertTrue(ver in self.session)

    def test_verification_box(self):
        list(update_all_full_names_task())
        acc = self.session.query(Accession).get(2)
        sp = self.session.query(Species).get(5)
        ver = Verification(accession=acc)
        acc.verifications.append(ver)
        mock_parent = unittest.mock.Mock()
        presenter = VerificationPresenter(
            mock_parent, acc, AccessionEditorView(), self.session
        )
        ver_box = VerificationBox(presenter, ver)
        utils.set_widget_value(ver_box.date_entry, "2/9/23")
        utils.set_widget_value(ver_box.date_entry, "")
        self.assertTrue(presenter.has_problems(ver_box.date_entry))
        utils.set_widget_value(ver_box.date_entry, "2/9/23")
        self.assertTrue(presenter.has_problems(ver_box.verifier_entry))
        self.assertTrue(presenter.has_problems(ver_box.new_taxon_entry))
        self.assertTrue(presenter.has_problems(ver_box.prev_taxon_entry))
        self.assertTrue(presenter.has_problems(ver_box.level_combo))
        utils.set_widget_value(ver_box.verifier_entry, "some expert")
        self.assertFalse(presenter.has_problems(ver_box.verifier_entry))
        utils.set_widget_value(ver_box.new_taxon_entry, sp.string())
        ver_box.on_sp_select(sp)
        self.assertFalse(presenter.has_problems(ver_box.new_taxon_entry))
        utils.set_widget_value(ver_box.prev_taxon_entry, acc.species.string())
        ver_box.on_sp_select(acc.species, attr="prev_species")
        self.assertFalse(presenter.has_problems(ver_box.prev_taxon_entry))
        utils.set_widget_value(ver_box.level_combo, 1)
        self.assertFalse(presenter.has_problems(ver_box.level_combo))
        self.session.commit()
        from bauble.btypes import Date

        self.assertEqual(ver.date, Date().process_bind_param("2/9/23", None))
        self.assertEqual(ver.verifier, "some expert")
        self.assertEqual(ver.species, sp)
        self.assertEqual(ver.prev_species, acc.species)
        self.assertEqual(ver.level, 1)

    @unittest.mock.patch("bauble.plugins.garden.accession.utils.yes_no_dialog")
    def test_on_remove_button_clicked(self, mock_dialog):
        acc = self.session.query(Accession).get(2)
        sp = (
            self.session.query(Species)
            .filter(Species.id != acc.species.id)
            .first()
        )
        ver = Verification(
            verifier="some botanist from an herbarium",
            date=datetime.date.today(),
            level=1,
            species=acc.species,
            prev_species=sp,
        )
        acc.verifications.append(ver)
        self.session.commit()
        mock_parent = unittest.mock.Mock()
        presenter = VerificationPresenter(
            mock_parent, acc, AccessionEditorView(), self.session
        )
        ver_box = VerificationBox(presenter, ver)
        mock_dialog.return_value = True
        ver_box.on_remove_button_clicked(None)
        mock_dialog.assert_called()
        self.assertEqual(acc.verifications, [])

    @unittest.mock.patch("bauble.plugins.garden.accession.utils.yes_no_dialog")
    def test_on_remove_button_clicked_user_backout(self, mock_dialog):
        acc = self.session.query(Accession).get(2)
        sp = (
            self.session.query(Species)
            .filter(Species.id != acc.species.id)
            .first()
        )
        ver = Verification(
            verifier="some botanist from an herbarium",
            date=datetime.date.today(),
            level=1,
            species=acc.species,
            prev_species=sp,
            notes="some note",
            reference="some book",
        )
        acc.verifications.append(ver)
        self.session.commit()
        mock_parent = unittest.mock.Mock()
        presenter = VerificationPresenter(
            mock_parent, acc, AccessionEditorView(), self.session
        )
        ver_box = VerificationBox(presenter, ver)
        mock_dialog.return_value = False
        ver_box.on_remove_button_clicked(None)
        mock_dialog.assert_called()
        self.assertEqual(acc.verifications, [ver])

    def test_ref_get_completions(self):
        acc1 = self.session.query(Accession).get(1)
        ver1 = Verification(
            verifier="me",
            date=datetime.date.today(),
            level=1,
            species=acc1.species,
            prev_species=acc1.species,
            reference="Flora of Queensland",
        )
        acc1.verifications.append(ver1)
        acc2 = self.session.query(Accession).get(2)
        ver2 = Verification(
            verifier="me",
            date=datetime.date.today(),
            level=1,
            species=acc1.species,
            prev_species=acc1.species,
            reference="Flora of Queensland",
        )
        acc2.verifications.append(ver2)
        self.session.commit()
        presenter = VerificationPresenter(
            unittest.mock.Mock(), acc1, AccessionEditorView(), self.session
        )
        ver_box = VerificationBox(presenter, ver1)
        self.assertEqual(
            ver_box.ref_get_completions("flora"), [ver1.reference]
        )

    def test_verifier_get_completions(self):
        acc1 = self.session.query(Accession).get(1)
        ver1 = Verification(
            verifier="Some botanist from an herbarium",
            date=datetime.date.today(),
            level=1,
            species=acc1.species,
            prev_species=acc1.species,
        )
        acc1.verifications.append(ver1)
        acc2 = self.session.query(Accession).get(2)
        ver2 = Verification(
            verifier="Some botanist from an herbarium",
            date=datetime.date.today(),
            level=1,
            species=acc1.species,
            prev_species=acc1.species,
        )
        acc2.verifications.append(ver2)
        self.session.commit()
        presenter = VerificationPresenter(
            unittest.mock.Mock(), acc1, AccessionEditorView(), self.session
        )
        ver_box = VerificationBox(presenter, ver1)
        self.assertEqual(
            ver_box.verifier_get_completions("some"), [ver1.verifier]
        )

    @unittest.mock.patch("bauble.plugins.garden.accession.utils.yes_no_dialog")
    def test_on_copy_to_taxon_general_clicked(self, mock_dialog):
        acc = self.session.query(Accession).get(1)
        sp = (
            self.session.query(Species)
            .filter(Species.id != acc.species.id)
            .first()
        )
        ver = Verification(
            verifier="some botanist from an herbarium",
            date=datetime.date.today(),
            level=3,
            species=sp,
            prev_species=acc.species,
        )
        acc.verifications.append(ver)
        self.session.commit()
        mock_parent = unittest.mock.Mock()
        mock_parent.model = acc
        presenter = VerificationPresenter(
            mock_parent, acc, AccessionEditorView(), self.session
        )
        ver_box = VerificationBox(presenter, ver)
        mock_dialog.return_value = True
        ver_box.on_copy_to_taxon_general_clicked(None)
        mock_dialog.assert_called()
        self.assertEqual(acc.species, sp)

    @unittest.mock.patch("bauble.plugins.garden.accession.utils.yes_no_dialog")
    def test_on_copy_to_taxon_general_clicked_user_backout(self, mock_dialog):
        acc = self.session.query(Accession).get(1)
        sp = (
            self.session.query(Species)
            .filter(Species.id != acc.species.id)
            .first()
        )
        ver = Verification(
            verifier="some botanist from an herbarium",
            date=datetime.date.today(),
            level=3,
            species=sp,
            prev_species=acc.species,
        )
        acc.verifications.append(ver)
        self.session.commit()
        mock_parent = unittest.mock.Mock()
        mock_parent.model = acc
        presenter = VerificationPresenter(
            mock_parent, acc, AccessionEditorView(), self.session
        )
        ver_box = VerificationBox(presenter, ver)
        mock_dialog.return_value = False
        ver_box.on_copy_to_taxon_general_clicked(None)
        mock_dialog.assert_called()
        self.assertNotEqual(acc.species, sp)


class LocationTests(GardenTestCase):
    def test_location_editor(self):
        loc = self.create(Location, name="some site", code="STE")
        self.session.commit()
        editor = LocationEditor(model=loc)
        update_gui()
        widgets = editor.presenter.view.widgets

        # test that the accept buttons are NOT sensitive since nothing
        # has changed and that the text entries and model are the same
        self.assertEqual(widgets.loc_name_entry.get_text(), loc.name)
        self.assertEqual(widgets.loc_code_entry.get_text(), loc.code)
        self.assertFalse(widgets.loc_ok_button.props.sensitive)
        self.assertFalse(widgets.loc_next_button.props.sensitive)

        # test the accept buttons become sensitive when the name entry
        # is changed
        widgets.loc_name_entry.set_text("something")
        update_gui()
        self.assertTrue(widgets.loc_ok_button.props.sensitive)
        self.assertTrue(widgets.loc_ok_and_add_button.props.sensitive)
        self.assertTrue(widgets.loc_next_button.props.sensitive)

        # test the accept buttons become NOT sensitive when the code
        # entry is empty since this is a required field
        widgets.loc_code_entry.set_text("")
        update_gui()
        self.assertFalse(widgets.loc_ok_button.props.sensitive)
        self.assertFalse(widgets.loc_ok_and_add_button.props.sensitive)
        self.assertFalse(widgets.loc_next_button.props.sensitive)

        # test the accept buttons aren't sensitive from setting the textview
        buff = Gtk.TextBuffer()
        buff.set_text("saasodmadomad")
        widgets.loc_desc_textview.set_buffer(buff)
        self.assertFalse(widgets.loc_ok_button.props.sensitive)
        self.assertFalse(widgets.loc_ok_and_add_button.props.sensitive)
        self.assertFalse(widgets.loc_next_button.props.sensitive)

        # commit the changes and cleanup
        editor.model.name = editor.model.code = "asda"
        editor.handle_response(Gtk.ResponseType.OK)
        editor.session.close()
        editor.presenter.cleanup()
        return

    @unittest.mock.patch("bauble.editor.GenericEditorView.start")
    def test_editor_doesnt_leak(self, mock_start):
        # garbage collect before start..
        gc.collect()
        mock_start.return_value = Gtk.ResponseType.OK
        loc = self.create(Location, name="some site", code="STE")
        editor = LocationEditor(model=loc)

        editor.start()
        del editor
        self.assertEqual(
            utils.gc_objects_by_type("LocationEditor"),
            [],
            "LocationEditor not deleted",
        )
        self.assertEqual(
            utils.gc_objects_by_type("LocationEditorPresenter"),
            [],
            "LocationEditorPresenter not deleted",
        )
        self.assertEqual(
            utils.gc_objects_by_type("LocationEditorView"),
            [],
            "LocationEditorView not deleted",
        )

    def test_count_children_wo_plants(self):
        loc = self.create(Location, name="some site", code="STE")
        self.session.commit()

        self.assertEqual(loc.count_children(), 0)

    def test_count_children_w_plant_w_qty(self):
        acc = self.create(Accession, species=self.species, code="1")
        loc = self.create(Location, name="site", code="STE")
        self.create(Plant, accession=acc, quantity=1, location=loc, code="1")
        self.session.commit()

        self.assertEqual(loc.count_children(), 1)

    def test_count_children_w_plant_w_qty_exclude_inactive_set(self):
        # should be the same as if exclude inactive not set.
        acc = self.create(Accession, species=self.species, code="1")
        loc = self.create(Location, name="site", code="STE")
        self.create(Plant, accession=acc, quantity=1, location=loc, code="1")
        self.session.commit()

        prefs.prefs[prefs.exclude_inactive_pref] = True

        self.assertEqual(loc.count_children(), 1)

    def test_count_children_w_plant_wo_qty(self):
        acc = self.create(Accession, species=self.species, code="1")
        loc = self.create(Location, name="site", code="STE")
        self.create(Plant, accession=acc, quantity=0, location=loc, code="1")
        self.session.commit()

        self.assertEqual(loc.count_children(), 1)

    def test_count_children_w_plant_wo_qty_exclude_inactive_set(self):
        acc = self.create(Accession, species=self.species, code="1")
        loc = self.create(Location, name="site", code="STE")
        self.create(Plant, accession=acc, quantity=0, location=loc, code="1")
        self.session.commit()

        prefs.prefs[prefs.exclude_inactive_pref] = True

        self.assertEqual(loc.count_children(), 0)

    def test_top_level_count_w_plant_qty(self):
        acc = self.create(Accession, species=self.species, code="1")
        loc = Location(name="site", code="STE")
        self.create(Plant, accession=acc, quantity=1, location=loc, code="1")
        self.session.commit()

        self.assertEqual(loc.top_level_count()[(1, "Locations")], 1)
        self.assertEqual(loc.top_level_count()[(2, "Plantings")], 1)
        self.assertEqual(loc.top_level_count()[(3, "Living plants")], 1)
        self.assertEqual(len(loc.top_level_count()[(4, "Accessions")]), 1)
        self.assertEqual(len(loc.top_level_count()[(5, "Species")]), 1)
        self.assertEqual(len(loc.top_level_count()[(6, "Genera")]), 1)
        self.assertEqual(len(loc.top_level_count()[(7, "Families")]), 1)
        self.assertEqual(len(loc.top_level_count()[(8, "Sources")]), 0)

    def test_top_level_count_wo_plant_qty(self):
        acc = self.create(Accession, species=self.species, code="1")
        loc = Location(name="site", code="STE")
        self.create(Plant, accession=acc, quantity=0, location=loc, code="1")
        self.session.commit()

        self.assertEqual(loc.top_level_count()[(1, "Locations")], 1)
        self.assertEqual(loc.top_level_count()[(2, "Plantings")], 1)
        self.assertEqual(loc.top_level_count()[(3, "Living plants")], 0)
        self.assertEqual(len(loc.top_level_count()[(4, "Accessions")]), 1)
        self.assertEqual(len(loc.top_level_count()[(5, "Species")]), 1)
        self.assertEqual(len(loc.top_level_count()[(6, "Genera")]), 1)
        self.assertEqual(len(loc.top_level_count()[(7, "Families")]), 1)
        self.assertEqual(len(loc.top_level_count()[(8, "Sources")]), 0)

    def test_top_level_count_wo_plant_qty_exclude_inactive_set(self):
        acc = self.create(Accession, species=self.species, code="1")
        loc = Location(name="site", code="STE")
        self.create(Plant, accession=acc, quantity=0, location=loc, code="1")
        self.session.commit()

        prefs.prefs[prefs.exclude_inactive_pref] = True

        self.assertEqual(loc.top_level_count()[(1, "Locations")], 1)
        self.assertEqual(loc.top_level_count()[(2, "Plantings")], 0)
        self.assertEqual(loc.top_level_count()[(3, "Living plants")], 0)
        self.assertEqual(len(loc.top_level_count()[(4, "Accessions")]), 0)
        self.assertEqual(len(loc.top_level_count()[(5, "Species")]), 0)
        self.assertEqual(len(loc.top_level_count()[(6, "Genera")]), 0)
        self.assertEqual(len(loc.top_level_count()[(7, "Families")]), 0)
        self.assertEqual(len(loc.top_level_count()[(8, "Sources")]), 0)

    def test_pictures(self):
        loc = self.session.query(Location).first()
        self.assertEqual(loc.pictures, [])
        pic = LocationPicture(picture="test.jpg", location=loc)
        self.session.commit()
        self.assertEqual(loc.pictures, [pic])
        plt = loc.plants[0]
        ppic = PlantPicture(picture="test1.jpg", plant=plt)
        self.session.commit()
        self.assertEqual(loc.pictures, [ppic, pic])
        plt.quantity = 0
        self.session.commit()
        # exclude inactive
        prefs.prefs[prefs.exclude_inactive_pref] = True
        self.assertEqual(loc.pictures, [pic])
        # detached returns empty
        self.session.expunge(loc)
        self.assertEqual(loc.pictures, [])


class CollectionTests(GardenTestCase):
    def test_collection_search_view_markup_pair(self):
        """Test Collection.accession property"""
        acc = Accession(code="2001.0002", species=self.species)
        acc.source = Source()
        collection = Collection(locale="some location")
        acc.source.collection = collection
        self.assertEqual(
            collection.search_view_markup_pair(),
            (
                "2001.0002 - <small>Echinocactus grusonii</small>",
                "Collection at some location",
            ),
        )

    def test_split_lat_long(self):
        view = AccessionEditorView()
        mock_parent = unittest.mock.MagicMock()
        presenter = CollectionPresenter(
            mock_parent, Collection(), view, self.session
        )
        # dms
        value = "27°28'55\"S 152°58'24.2\"E"
        view.widgets.lon_entry.set_text(value)
        update_gui()
        self.assertEqual(view.widgets.lat_entry.get_text(), value.split()[0])
        self.assertEqual(view.widgets.lon_entry.get_text(), value.split()[1])
        # dec
        value = "27.481950, -152.973379"
        view.widgets.lat_entry.set_text(value)
        update_gui()
        self.assertEqual(
            view.widgets.lat_entry.get_text(), value.split(", ")[0]
        )
        self.assertEqual(
            view.widgets.lon_entry.get_text(), value.split(", ")[1]
        )
        # dms should not split
        value = "27°28' 152°58'"
        view.widgets.lon_entry.set_text(value)
        update_gui()
        self.assertEqual(view.widgets.lon_entry.get_text(), value)

        # dec should not split
        value = "27., 152."
        view.widgets.lat_entry.set_text(value)
        update_gui()
        self.assertEqual(view.widgets.lat_entry.get_text(), value)
        presenter.cleanup()

    def test_on_east_west_radio_toggled(self):
        view = AccessionEditorView()
        mock_parent = unittest.mock.MagicMock()
        presenter = CollectionPresenter(
            mock_parent, Collection(), view, self.session
        )

        # blank
        view.widgets.lon_entry.set_text("")
        view.widgets.east_radio.set_active(True)
        self.assertEqual(view.widgets.lon_entry.get_text(), "")
        # NOTE set the west radio button active, setting east False won't work
        view.widgets.west_radio.set_active(True)
        self.assertEqual(view.widgets.lon_entry.get_text(), "")

        # dec
        view.widgets.lon_entry.set_text("12.345")
        view.widgets.west_radio.set_active(True)
        self.assertEqual(view.widgets.lon_entry.get_text(), "-12.345")
        view.widgets.east_radio.set_active(True)
        self.assertEqual(view.widgets.lon_entry.get_text(), "12.345")

        # dms
        view.widgets.lon_entry.set_text("152°58'24.2\"")
        view.widgets.west_radio.set_active(True)
        self.assertEqual(view.widgets.lon_entry.get_text(), "152°58'24.2\"W")
        view.widgets.east_radio.set_active(True)
        self.assertEqual(view.widgets.lon_entry.get_text(), "152°58'24.2\"E")
        view.widgets.west_radio.set_active(True)
        self.assertEqual(view.widgets.lon_entry.get_text(), "152°58'24.2\"W")

        # dms 2
        view.widgets.lon_entry.set_text("E 152°58'24.2\"")
        view.widgets.west_radio.set_active(True)
        self.assertEqual(view.widgets.lon_entry.get_text(), "W 152°58'24.2\"")
        view.widgets.east_radio.set_active(True)
        self.assertEqual(view.widgets.lon_entry.get_text(), "E 152°58'24.2\"")

        # junk
        view.widgets.lon_entry.set_text("abcd")
        view.widgets.east_radio.set_active(True)
        self.assertEqual(view.widgets.lon_entry.get_text(), "abcd")
        view.widgets.west_radio.set_active(True)
        self.assertEqual(view.widgets.lon_entry.get_text(), "abcd")
        presenter.cleanup()

    def test_on_north_south_radio_toggled(self):
        view = AccessionEditorView()
        mock_parent = unittest.mock.MagicMock()
        presenter = CollectionPresenter(
            mock_parent, Collection(), view, self.session
        )

        # blank
        view.widgets.lat_entry.set_text("")
        view.widgets.north_radio.set_active(True)
        self.assertEqual(view.widgets.lat_entry.get_text(), "")
        # NOTE set the west radio button active, setting east False won't work
        view.widgets.south_radio.set_active(True)
        self.assertEqual(view.widgets.lat_entry.get_text(), "")

        # dec
        view.widgets.lat_entry.set_text("12.345")
        view.widgets.south_radio.set_active(True)
        self.assertEqual(view.widgets.lat_entry.get_text(), "-12.345")
        view.widgets.north_radio.set_active(True)
        self.assertEqual(view.widgets.lat_entry.get_text(), "12.345")

        # dms
        view.widgets.lat_entry.set_text("152°58'24.2\"")
        view.widgets.south_radio.set_active(True)
        self.assertEqual(view.widgets.lat_entry.get_text(), "152°58'24.2\"S")
        view.widgets.north_radio.set_active(True)
        self.assertEqual(view.widgets.lat_entry.get_text(), "152°58'24.2\"N")
        view.widgets.south_radio.set_active(True)
        self.assertEqual(view.widgets.lat_entry.get_text(), "152°58'24.2\"S")

        # dms 2
        view.widgets.lat_entry.set_text("S 152°58'24.2\"")
        view.widgets.north_radio.set_active(True)
        self.assertEqual(view.widgets.lat_entry.get_text(), "N 152°58'24.2\"")
        view.widgets.south_radio.set_active(True)
        self.assertEqual(view.widgets.lat_entry.get_text(), "S 152°58'24.2\"")

        # junk
        view.widgets.lat_entry.set_text("abcd")
        view.widgets.north_radio.set_active(True)
        self.assertEqual(view.widgets.lat_entry.get_text(), "abcd")
        view.widgets.south_radio.set_active(True)
        self.assertEqual(view.widgets.lat_entry.get_text(), "abcd")
        presenter.cleanup()

    def test_set_region(self):
        view = AccessionEditorView()
        model = Collection()
        mock_parent = unittest.mock.MagicMock()
        presenter = CollectionPresenter(mock_parent, model, view, self.session)
        geo = self.session.query(Geography).get(5)
        mock_var = unittest.mock.Mock()
        mock_var.unpack.return_value = 5
        presenter.set_region(None, mock_var)
        self.assertEqual(model.region, geo)
        presenter.cleanup()

    def test_refresh_view_w_lat_long(self):
        view = AccessionEditorView()
        model = Collection(latitude=12.345, longitude=12.345)
        presenter = CollectionPresenter(
            unittest.mock.MagicMock(), model, view, self.session
        )
        presenter.refresh_view()
        self.assertTrue(view.widgets.north_radio.get_active())
        self.assertTrue(view.widgets.east_radio.get_active())
        model.latitude = -12.345
        model.longitude = -12.345
        presenter.refresh_view()
        self.assertFalse(view.widgets.north_radio.get_active())
        self.assertFalse(view.widgets.east_radio.get_active())
        presenter.cleanup()

    def test_collector_get_completions(self):
        view = AccessionEditorView()
        model = self.session.query(Collection).get(1)
        presenter = CollectionPresenter(
            unittest.mock.MagicMock(), model, view, self.session
        )
        self.assertCountEqual(
            presenter.collector_get_completions("some"),
            ["Someone", "Someone Else"],
        )
        self.assertCountEqual(
            presenter.collector_get_completions("me"),
            ["Someone", "Someone Else", "me"],
        )


class InstitutionTests(GardenTestCase):
    def test_init_13_props(self):
        o = Institution()
        o.name = "Ghini"
        o.write()
        fields = (
            self.session.query(BaubleMeta)
            .filter(utils.ilike(BaubleMeta.name, "inst_%"))
            .all()
        )
        self.assertEqual(len(fields), 13)

    def test_init__one_institution(self):
        o = Institution()
        o.name = "Fictive"
        o.write()
        o.name = "Ghini"
        o.write()
        fieldObjects = (
            self.session.query(BaubleMeta)
            .filter(utils.ilike(BaubleMeta.name, "inst_%"))
            .all()
        )
        self.assertEqual(len(fieldObjects), 13)

    def test_init__always_initialized(self):
        o = Institution()
        o.name = "Fictive"
        o.write()
        u = Institution()
        self.assertEqual(u.name, "Fictive")
        o.name = "Ghini"
        o.write()
        u = Institution()
        self.assertEqual(u.name, "Ghini")

    def test_init__has_all_attributes(self):
        o = Institution()
        for a in (
            "name",
            "abbreviation",
            "code",
            "contact",
            "technical_contact",
            "email",
            "tel",
            "fax",
            "address",
        ):
            self.assertTrue(hasattr(o, a))

    def test_write__None_stays_None(self):
        # clear the entries first as they are filled in setUp_data
        (
            self.session.query(BaubleMeta)
            .filter(utils.ilike(BaubleMeta.name, "inst_%"))
            .delete(synchronize_session=False)
        )
        self.session.commit()
        o = Institution()
        o.name = "Ghini"
        o.email = "bauble@anche.no"
        o.write()
        fieldObjects = (
            self.session.query(BaubleMeta)
            .filter(utils.ilike(BaubleMeta.name, "inst_%"))
            .all()
        )
        fields = dict(
            (i.name[5:], i.value) for i in fieldObjects if i.value is not None
        )
        self.assertEqual(fields["name"], "Ghini")
        self.assertEqual(fields["email"], "bauble@anche.no")
        logger.debug(fields)
        self.assertEqual(len(fields), 2)

    def test_bails_early_if_no_engine(self):
        # clear the entries first as they are filled in setUp_data
        (
            self.session.query(BaubleMeta)
            .filter(utils.ilike(BaubleMeta.name, "inst_%"))
            .delete(synchronize_session=False)
        )
        self.session.commit()
        inst = Institution()
        inst.name = "Test"
        # write bails
        with unittest.mock.patch(
            "bauble.plugins.garden.institution.db.engine", None
        ):
            inst.write()
        fields = (
            self.session.query(BaubleMeta)
            .filter(utils.ilike(BaubleMeta.name, "inst_%"))
            .all()
        )
        self.assertEqual(len(fields), 0)
        # write succeeds
        inst.write()
        fields = (
            self.session.query(BaubleMeta)
            .filter(utils.ilike(BaubleMeta.name, "inst_%"))
            .all()
        )
        self.assertEqual(len(fields), 13)
        # init bails
        with unittest.mock.patch(
            "bauble.plugins.garden.institution.db.engine", None
        ):
            inst = Institution()
        for value in inst.__dict__.values():
            self.assertIsNone(value)


class InstitutionDialogTests(BaubleTestCase):
    def test_can_create_dialog(self):
        model = Institution()
        dialog = InstitutionDialog(model)
        self.assertEqual(dialog.model, model)

    @unittest.mock.patch.object(InstitutionDialog, "set_destroy_with_parent")
    @unittest.mock.patch("bauble.gui")
    def test_sets_destroy_with_parent(self, mock_gui, mock_destroy_w_parent):
        # mock_gui purelly for the coverage
        mock_gui.window = Gtk.Window()
        model = Institution()
        dialog = InstitutionDialog(model)
        self.assertEqual(dialog.model, model)
        mock_destroy_w_parent.assert_called_with(True)

    def test_empty_name_is_a_problem(self):
        model = Institution()
        model.name = ""
        dialog = InstitutionDialog(model)
        self.assertIsNotNone(dialog.message_box)
        self.assertEqual(len(dialog.message_box_parent.get_children()), 1)

    def test_initially_empty_name_then_specified_is_ok(self):
        model = Institution()
        model.name = ""
        dialog = InstitutionDialog(model)
        dialog.inst_name.set_text("testBG")
        self.assertEqual(model.name, "testBG")
        self.assertIsNone(dialog.message_box)
        self.assertEqual(len(dialog.message_box_parent.get_children()), 0)

    def test_on_text_buffer_changed(self):
        model = Institution()
        text_buffer = Gtk.TextBuffer()

        dialog = InstitutionDialog(model)

        dialog.widgets_to_model_map = {text_buffer: "address"}

        text_buffer.set_text("test")
        dialog.on_text_buffer_changed(text_buffer)
        self.assertEqual(model.address, "test")

    def test_on_text_entry_changed(self):
        model = Institution()
        entry = Gtk.Entry()

        dialog = InstitutionDialog(model)

        dialog.widgets_to_model_map = {entry: "name"}

        entry.set_text("BG")
        dialog.on_text_entry_changed(entry)
        self.assertEqual(model.name, "BG")

    def test_on_combobox_changed(self):
        model = Institution()

        dialog = InstitutionDialog(model)
        combo = Gtk.ComboBoxText()
        combo.append_text("1")
        combo.append_text("2")
        combo.append_text("3")

        dialog.widgets_to_model_map = {combo: "geo_zoom"}

        combo.set_active(1)
        dialog.on_combobox_changed(combo)
        self.assertEqual(model.geo_zoom, "2")

    @staticmethod
    @unittest.mock.patch(
        "bauble.plugins.garden.institution.InstitutionDialog.run"
    )
    @unittest.mock.patch("bauble.plugins.garden.institution.Institution.write")
    def test_start_institution_editor(mock_write, mock_run):
        mock_run.return_value = Gtk.ResponseType.OK
        start_institution_editor()
        mock_write.assert_called()

        mock_write.reset_mock()

        mock_run.return_value = Gtk.ResponseType.CANCEL
        start_institution_editor()
        mock_write.assert_not_called()

    @staticmethod
    @unittest.mock.patch(
        "bauble.plugins.garden.institution.start_institution_editor"
    )
    def test_institution_command(mock_start):
        InstitutionCommand()(None, None)
        mock_start.assert_called()

    @staticmethod
    @unittest.mock.patch(
        "bauble.plugins.garden.institution.start_institution_editor"
    )
    def test_institution_tool(mock_start):
        InstitutionTool.start()
        mock_start.assert_called()


# latitude: deg[0-90], min[0-59], sec[0-59]
# longitude: deg[0-180], min[0-59], sec[0-59]

ALLOWED_DECIMAL_ERROR = 5
THRESHOLD = 0.01

# indexs into conversion_test_date
DMS = 0  # DMS
DEG_MIN_DEC = 1  # Deg with minutes decimal
DEG_DEC = 2  # Degrees decimal
UTM = 3  # Datum(wgs84/nad83 or nad27), UTM Zone, Easting, Northing

# decimal points to accuracy in decimal degrees
# 1 +/- 8000m
# 2 +/- 800m
# 3 +/- 80m
# 4 +/- 8m
# 5 +/- 0.8m
# 6 +/- 0.08m

from decimal import Decimal

dec = Decimal
conversion_test_data = (
    (
        (("N", 17, 21, dec(59)), ("W", 89, 1, 41)),  # dms
        (
            (dec(17), dec("21.98333333")),
            (dec(-89), dec("1.68333333")),
        ),  # deg min_dec
        (dec("17.366389"), dec("-89.028056")),  # dec deg
        (("wgs84", 16, 284513, 1921226)),
    ),  # utm
    (
        (("S", 50, 19, dec("32.59")), ("W", 74, 2, dec("11.6"))),  # dms
        (
            (dec(-50), dec("19.543166")),
            (dec(-74), dec("2.193333")),
        ),  # deg min_dec
        (dec("-50.325719"), dec("-74.036556")),  # dec deg
        (("wgs84", 18, 568579, 568579)),
        (("nad27", 18, 568581, 4424928)),
    ),
    (
        (("N", 9, 0, dec("4.593384")), ("W", 78, 3, dec("28.527984"))),
        ((9, dec("0.0765564")), (-78, dec("3.4754664"))),
        (dec("9.00127594"), dec("-78.05792444")),
    ),
    (
        (("N", 49, 10, 28), ("W", 121, 40, 39)),
        ((49, dec("10.470")), (-121, dec("40.650"))),
        (dec("49.174444"), dec("-121.6775")),
    ),
)


parse_lat_lon_data = (
    (("N", "17 21 59"), dec("17.366389")),
    (("N", "17 21.983333"), dec("17.366389")),
    (("N", "17.03656"), dec("17.03656")),
    (("W", "89 1 41"), dec("-89.028056")),
    (("W", "89 1.68333333"), dec("-89.028056")),
    (("W", "-89 1.68333333"), dec("-89.028056")),
    (("E", "121 40 39"), dec("121.6775")),
)


class DMSConversionTests(unittest.TestCase):
    # test coordinate conversions
    def test_dms_to_decimal(self):
        # test converting DMS to degrees decimal
        ALLOWED_ERROR = 6
        for data_set in conversion_test_data:
            dms_data = data_set[DMS]
            dec_data = data_set[DEG_DEC]
            lat_dec = dms_to_decimal(*dms_data[0])
            lon_dec = dms_to_decimal(*dms_data[1])
            self.assertAlmostEqual(lat_dec, dec_data[0], ALLOWED_ERROR)
            self.assertAlmostEqual(lon_dec, dec_data[1], ALLOWED_ERROR)

    def test_decimal_to_dms(self):
        # test converting degrees decimal to dms, allow a certain
        # amount of error in the seconds
        ALLOWABLE_ERROR = 2
        for data_set in conversion_test_data:
            dms_data = data_set[DMS]
            dec_data = data_set[DEG_DEC]

            # convert to DMS
            lat_dms = latitude_to_dms(dec_data[0])
            self.assertEqual(lat_dms[0:2], dms_data[0][0:2])
            # test seconds with allowable error
            self.assertAlmostEqual(lat_dms[3], dms_data[0][3], ALLOWABLE_ERROR)

            lon_dms = longitude_to_dms(dec_data[1])
            self.assertEqual(lon_dms[0:2], dms_data[1][0:2])
            # test seconds with allowable error
            self.assertAlmostEqual(lon_dms[3], dms_data[1][3], ALLOWABLE_ERROR)

    def test_parse_lat_lon(self):
        parse = CollectionPresenter._parse_lat_lon
        for data, dec_val in parse_lat_lon_data:
            result = parse(*data)
            self.assertEqual(result, dec_val)


from bauble import search
from bauble.plugins.garden import PlantSearch


class PlantSearchTests(BaubleTestCase):
    def setUp(self):
        super().setUp()

        fam = Family(family="Myrtaceae")
        gen = Genus(family=fam, genus="Eucalyptus")
        spc = Species(sp="curtisii", genus=gen)
        acc1 = Accession(code="XXXX", species=spc)
        acc2 = Accession(code="YYYY", species=spc)
        loc = Location(code="Bed1")
        # XXXX.1
        self.plt1 = Plant(code="1", quantity=1, accession=acc1, location=loc)
        # XXXX.2
        self.plt2 = Plant(code="2", quantity=1, accession=acc1, location=loc)
        # YYYY.1
        self.plt3 = Plant(code="1", quantity=1, accession=acc2, location=loc)
        # YYYY.3
        self.plt4 = Plant(code="3", quantity=1, accession=acc2, location=loc)
        self.session.add_all(
            [
                fam,
                gen,
                spc,
                acc1,
                acc2,
                loc,
                self.plt1,
                self.plt2,
                self.plt3,
                self.plt3,
            ]
        )
        self.session.commit()

    def tearDown(self):
        super().tearDown()

    def test_plant_search_directly(self):
        plant_search = search.strategies.get_strategy("PlantSearch")
        self.assertTrue(isinstance(plant_search, PlantSearch))

        qry = "planting = XXXX.1"
        results = plant_search.search(qry, self.session)[0].all()
        self.assertEqual(results, [self.plt1])

    def test__eq__plant_search(self):
        qry = 'planting = "XXXX.1"'
        with self.assertLogs(level="DEBUG") as logs:
            results = search.search(qry, self.session)
        string = f'SearchStrategy "{qry}" (PlantSearch)'
        self.assertTrue(any(string in i for i in logs.output))
        string = '"equals" PlantSearch accession: XXXX plant: 1'
        self.assertTrue(any(string in i for i in logs.output))
        self.assertEqual(results, [self.plt1])

    def test__in__plant_search(self):
        qry = "planting in XXXX.1 YYYY.3"
        with self.assertLogs(level="DEBUG") as logs:
            results = search.search(qry, self.session)
        string = f'SearchStrategy "{qry}" (PlantSearch)'
        self.assertTrue(any(string in i for i in logs.output))
        string = "\"in\" PlantSearch val_list: [('XXXX', '1'), ('YYYY', '3')]"
        self.assertTrue(any(string in i for i in logs.output))
        self.assertCountEqual(results, [self.plt1, self.plt4])

        qry = "planting in 'XXXX.1' 'YYYY.3'"
        with self.assertLogs(level="DEBUG") as logs:
            results = search.search(qry, self.session)
        string = f'SearchStrategy "{qry}" (PlantSearch)'
        self.assertTrue(any(string in i for i in logs.output))
        string = "\"in\" PlantSearch val_list: [('XXXX', '1'), ('YYYY', '3')]"
        self.assertTrue(any(string in i for i in logs.output))
        self.assertCountEqual(results, [self.plt1, self.plt4])

    def test__not_eq__plant_search(self):
        qry = "planting != XXXX.1"
        with self.assertLogs(level="DEBUG") as logs:
            results = search.search(qry, self.session)
        string = f'SearchStrategy "{qry}" (PlantSearch)'
        self.assertTrue(any(string in i for i in logs.output))
        string = '"not equals" PlantSearch accession: XXXX plant: "1"'
        self.assertTrue(any(string in i for i in logs.output))
        self.assertCountEqual(results, [self.plt2, self.plt3, self.plt4])

        qry = "planting <> YYYY.1"
        results = search.search(qry, self.session)
        self.assertCountEqual(results, [self.plt2, self.plt1, self.plt4])

    def test__star__plant_search(self):
        qry = "planting = *"
        with self.assertLogs(level="DEBUG") as logs:
            results = search.search(qry, self.session)
        string = f'SearchStrategy "{qry}" (PlantSearch)'
        self.assertTrue(any(string in i for i in logs.output))

        string = '"star" PlantSearch, returning all plants'
        self.assertTrue(any(string in i for i in logs.output))
        self.assertCountEqual(
            results, [self.plt1, self.plt2, self.plt3, self.plt4]
        )

    def test__contains__plant_search(self):
        qry = "planting contains XX"
        with self.assertLogs(level="DEBUG") as logs:
            results = search.search(qry, self.session)
        string = f'SearchStrategy "{qry}" (PlantSearch)'
        self.assertTrue(any(string in i for i in logs.output))
        string = '"contains" PlantSearch accession: XX plant: XX'
        self.assertTrue(any(string in i for i in logs.output))
        self.assertCountEqual(results, [self.plt1, self.plt2])

    def test__like__plant_search(self):
        qry = "planting like XX%.1"
        with self.assertLogs(level="DEBUG") as logs:
            results = search.search(qry, self.session)
        string = f'SearchStrategy "{qry}" (PlantSearch)'
        self.assertTrue(any(string in i for i in logs.output))

        string = '"like" PlantSearch accession: XX% plant: 1'
        self.assertTrue(any(string in i for i in logs.output))
        self.assertCountEqual(results, [self.plt1])

        qry = "planting like XX%.%"
        with self.assertLogs(level="DEBUG") as logs:
            results = search.search(qry, self.session)
        string = f'SearchStrategy "{qry}" (PlantSearch)'
        self.assertTrue(any(string in i for i in logs.output))
        string = '"like" PlantSearch accession: XX% plant: %'
        self.assertTrue(any(string in i for i in logs.output))
        self.assertCountEqual(results, [self.plt1, self.plt2])


class PlantGetNextCodeTests(GardenTestCase):
    def test_digits_no_plants(self):
        accession = Accession(species=self.species, code="TEST")
        self.assertEqual(get_next_code(accession), "1")

    def test_digits_w_plants(self):
        accession = Accession(species=self.species, code="TEST")
        accession.plants.append(
            Plant(
                code="1",
                quantity=1,
                location=Location(name="site", code="STE"),
            )
        )
        self.session.add(accession)
        self.session.commit()
        self.assertEqual(get_next_code(accession), "2")

    def test_digits_w_10_plants(self):
        accession = Accession(species=self.species, code="TEST")
        accession.plants.append(
            Plant(
                code="9",
                quantity=1,
                location=Location(name="site", code="STE"),
            )
        )
        self.session.add(accession)
        self.session.commit()
        self.assertEqual(get_next_code(accession), "10")

    def test_alpha_lower_no_plants(self):
        meta.get_default(PLANT_CODE_FORMAT_KEY, "alpha_lower")
        accession = Accession(species=self.species, code="TEST")
        self.assertEqual(get_next_code(accession), "a")

    def test_alpha_lower_w_plants(self):
        meta.get_default(PLANT_CODE_FORMAT_KEY, "alpha_lower")
        accession = Accession(species=self.species, code="TEST")
        accession.plants.append(
            Plant(
                code="a",
                quantity=1,
                location=Location(name="site", code="STE"),
            )
        )
        self.session.add(accession)
        self.session.commit()
        self.assertEqual(get_next_code(accession), "b")

    def test_alpha_lower_w_z_plants(self):
        meta.get_default(PLANT_CODE_FORMAT_KEY, "alpha_lower")
        accession = Accession(species=self.species, code="TEST")
        accession.plants.append(
            Plant(
                code="z",
                quantity=1,
                location=Location(name="site", code="STE"),
            )
        )
        self.session.add(accession)
        self.session.commit()
        self.assertEqual(get_next_code(accession), "aa")

    def test_alpha_upper_no_plants(self):
        meta.get_default(PLANT_CODE_FORMAT_KEY, "alpha_upper")
        accession = Accession(species=self.species, code="TEST")
        self.assertEqual(get_next_code(accession), "A")

    def test_alpha_upper_w_plants(self):
        meta.get_default(PLANT_CODE_FORMAT_KEY, "alpha_upper")
        accession = Accession(species=self.species, code="TEST")
        accession.plants.append(
            Plant(
                code="A",
                quantity=1,
                location=Location(name="site", code="STE"),
            )
        )
        self.session.add(accession)
        self.session.commit()
        self.assertEqual(get_next_code(accession), "B")

    def test_alpha_upper_w_z_plants(self):
        meta.get_default(PLANT_CODE_FORMAT_KEY, "alpha_upper")
        accession = Accession(species=self.species, code="TEST")
        accession.plants.append(
            Plant(
                code="Z",
                quantity=1,
                location=Location(name="site", code="STE"),
            )
        )
        self.session.add(accession)
        self.session.commit()
        self.assertEqual(get_next_code(accession), "AA")


class AccessionGetNextCodeTests(GardenTestCase):
    def test_get_next_code_first_this_year_multiple_strftime(self):
        year = datetime.date.today().strftime("%Y")
        month = datetime.date.today().strftime("%m")
        day = datetime.date.today().strftime("%d")
        self.assertEqual(Accession.get_next_code(), year + ".0001")
        self.assertEqual(
            Accession.get_next_code("%Y%m%d%PD###"),
            year + month + day + Plant.get_delimiter() + "001",
        )
        self.assertEqual(
            Accession.get_next_code("%Y%m%PD###"),
            year + month + Plant.get_delimiter() + "001",
        )

    def test_get_next_code_second_this_year(self):
        this_year = str(datetime.date.today().year)
        this_code = Accession.get_next_code()
        acc = Accession(species=self.species, code=str(this_code))
        self.session.add(acc)
        self.session.commit()
        self.assertEqual(Accession.get_next_code(), this_year + ".0002")

    def test_get_next_code_absolute_beginning(self):
        this_year = str(datetime.date.today().year)
        for i in self.session.query(Accession).all():
            self.session.delete(i)
        self.session.commit()
        self.assertEqual(Accession.get_next_code(), this_year + ".0001")

    def test_get_next_code_next_with_hole(self):
        this_year = str(datetime.date.today().year)
        this_code = this_year + ".0050"
        acc = Accession(species=self.species, code=this_code)
        self.session.add(acc)
        self.session.commit()
        self.assertEqual(Accession.get_next_code(), this_year + ".0051")

    def test_get_next_code_alter_format_first(self):
        this_year = str(datetime.date.today().year)
        this_code = this_year + ".0050"
        orig = Accession.code_format
        acc = Accession(species=self.species, code=this_code)
        self.session.add(acc)
        self.session.commit()
        Accession.code_format = "H.###"
        self.assertEqual(Accession.get_next_code(), "H.001")
        Accession.code_format = "SD.###"
        self.assertEqual(Accession.get_next_code(), "SD.001")
        Accession.code_format = orig

    def test_get_next_code_alter_format_next(self):
        orig = Accession.code_format
        acc = Accession(species=self.species, code="H.012")
        self.session.add(acc)
        acc = Accession(species=self.species, code="SD.002")
        self.session.add(acc)
        self.session.commit()
        Accession.code_format = "H.###"
        self.assertEqual(Accession.get_next_code(), "H.013")
        Accession.code_format = "SD.###"
        self.assertEqual(Accession.get_next_code(), "SD.003")
        Accession.code_format = orig

    def test_get_next_code_alter_format_first_specified(self):
        this_year = str(datetime.date.today().year)
        this_code = this_year + ".0050"
        acc = Accession(species=self.species, code=this_code)
        self.session.add(acc)
        self.session.commit()
        self.assertEqual(Accession.get_next_code("H.###"), "H.001")
        self.assertEqual(Accession.get_next_code("SD.###"), "SD.001")

    def test_get_next_code_alter_format_next_specified(self):
        acc = Accession(species=self.species, code="H.012")
        self.session.add(acc)
        acc = Accession(species=self.species, code="SD.002")
        self.session.add(acc)
        self.session.commit()
        self.assertEqual(Accession.get_next_code("H.###"), "H.013")
        self.assertEqual(Accession.get_next_code("SD.###"), "SD.003")

    def test_get_next_code_plain_numeric_zero(self):
        self.assertEqual(Accession.get_next_code("#####"), "00001")

    def test_get_next_code_plain_numeric_next(self):
        acc = Accession(species=self.species, code="00012")
        self.session.add(acc)
        self.session.commit()
        self.assertEqual(Accession.get_next_code("#####"), "00013")

    def test_get_next_code_plain_numeric_next_multiple(self):
        acc = Accession(species=self.species, code="00012")
        ac2 = Accession(species=self.species, code="H.0987")
        ac3 = Accession(species=self.species, code="2112.0019")
        self.session.add_all([acc, ac2, ac3])
        self.session.commit()
        self.assertEqual(Accession.get_next_code("#####"), "00013")
        self.assertEqual(Accession.get_next_code("###"), "001")

    def test_get_next_code_fixed(self):
        acc = Accession(species=self.species, code="00012")
        ac2 = Accession(species=self.species, code="H.0987")
        ac3 = Accession(species=self.species, code="2112.0019")
        self.session.add_all([acc, ac2, ac3])
        self.session.commit()
        self.assertEqual(Accession.get_next_code("2112.003"), "2112.003")
        self.assertEqual(Accession.get_next_code("2112.0003"), "2112.0003")
        self.assertEqual(Accession.get_next_code("00003"), "00003")
        self.assertEqual(Accession.get_next_code("H.0003"), "H.0003")

    def test_get_next_code_previous_year_subst(self):
        this_year = datetime.date.today().year
        last_year = this_year - 1
        acc = Accession(species=self.species, code="%s.0012" % last_year)
        ac2 = Accession(species=self.species, code="%s.0987" % this_year)
        self.session.add_all([acc, ac2])
        self.session.commit()
        self.assertEqual(Accession.get_next_code("%{Y-1}.####")[5:], "0013")
        self.assertEqual(
            Accession.get_next_code("%{Y-1}.####"), f"{last_year}.0013"
        )
        self.assertEqual(
            Accession.get_next_code("%{Y-10}.####"), f"{this_year-10}.0001"
        )
        self.assertEqual(
            Accession.get_next_code("%Y.####"), f"{this_year}.0988"
        )

    def test_get_next_code_bad_formats_return_none(self):
        self.assertIsNone(Accession.get_next_code("%{Y-}###"))
        self.assertIsNone(Accession.get_next_code("%{Y}###"))
        self.assertIsNone(Accession.get_next_code("%{x}###"))
        self.assertIsNone(Accession.get_next_code("%i%PD###"))
        self.assertIsNone(Accession.get_next_code("%v%PD###"))
        self.assertIsNone(Accession.get_next_code("%👻%PD###"))
        # test all ascii chars (+ a few extras)that are not valid strftime
        # format codes
        bad_vals = ["e", "g", "h", "i", "k", "l", "n", "o", "q", "r", "s"]
        bad_vals += ["t", "u", "v", "C", "D", "E", "F", "G", "J", "K", "L"]
        bad_vals += ["N", "O", "P", "Q", "R", "T", "V", "$", "*", ")", "-"]
        for i in bad_vals:
            self.assertIsNone(Accession.get_next_code("%" + i + ".#"))


class SourceDetailTests(GardenTestCase):
    def __init__(self, *args):
        super().__init__(*args)

    def test_delete(self):
        # In theory, we'd rather not be allowed to delete contact if it
        # being referred to as the source for an accession.  However, this
        # just works.  As long as the trouble is theoretic we accept it.

        acc = self.create(Accession, species=self.species, code="2001.0001")
        contact = SourceDetail(name="name")
        source = Source()
        source.source_detail = contact
        acc.source = source
        self.session.commit()
        self.session.close()

        # we can delete a contact even if used as source
        session = db.Session()
        contact = session.query(SourceDetail).filter_by(name="name").one()
        session.delete(contact)
        session.commit()
        session.close()

        # the source field in the accession got removed
        session = db.Session()
        acc = session.query(Accession).filter_by(code="2001.0001").one()
        self.assertEqual(acc.source, None)
        session.close()

    def test_representation_of_contact(self):
        contact = SourceDetail(name="name")
        self.assertEqual("%s" % contact, "name")
        self.assertEqual(contact.search_view_markup_pair(), ("name", ""))
        contact = SourceDetail(name="ANBG", source_type="BG")
        self.assertEqual("%s" % contact, "ANBG (Botanic Garden or Arboretum)")
        self.assertEqual(
            contact.search_view_markup_pair(),
            ("ANBG", "Botanic Garden or Arboretum"),
        )

    def test_count_children_wo_plants(self):
        source = self.create(SourceDetail, name="name")
        self.session.commit()

        self.assertEqual(source.count_children(), 0)

    def test_count_children_w_plant_w_qty(self):
        acc = self.create(Accession, species=self.species, code="2001.0001")
        contact = SourceDetail(name="name")
        source = Source()
        source.source_detail = contact
        acc.source = source
        loc = self.create(Location, name="site", code="STE")
        self.create(Plant, accession=acc, quantity=1, location=loc, code="1")
        self.session.commit()

        self.assertEqual(contact.count_children(), 1)

    def test_count_children_w_plant_w_qty_exclude_inactive_set(self):
        # should be the same as if exclude inactive not set.
        acc = self.create(Accession, species=self.species, code="2001.0001")
        contact = SourceDetail(name="name")
        source = Source()
        source.source_detail = contact
        acc.source = source
        loc = self.create(Location, name="site", code="STE")
        self.create(Plant, accession=acc, quantity=1, location=loc, code="1")
        self.session.commit()

        prefs.prefs[prefs.exclude_inactive_pref] = True

        self.assertEqual(contact.count_children(), 1)

    def test_count_children_w_plant_wo_qty(self):
        acc = self.create(Accession, species=self.species, code="2001.0001")
        contact = SourceDetail(name="name")
        source = Source()
        source.source_detail = contact
        acc.source = source
        loc = self.create(Location, name="site", code="STE")
        self.create(Plant, accession=acc, quantity=0, location=loc, code="1")
        self.session.commit()

        self.assertEqual(contact.count_children(), 1)

    def test_count_children_w_plant_wo_qty_exclude_inactive_set(self):
        acc = self.create(Accession, species=self.species, code="2001.0001")
        contact = SourceDetail(name="name")
        source = Source()
        source.source_detail = contact
        acc.source = source
        loc = self.create(Location, name="site", code="STE")
        self.create(Plant, accession=acc, quantity=0, location=loc, code="1")
        self.session.commit()

        prefs.prefs[prefs.exclude_inactive_pref] = True

        self.assertEqual(contact.count_children(), 0)

    def test_pictures(self):
        source = self.session.query(SourceDetail).first()
        self.assertEqual(source.pictures, [])
        plt = self.session.query(Plant).get(4)
        pic = PlantPicture(picture="test1.jpg", plant=plt)
        self.session.commit()
        self.assertEqual(source.pictures, [pic])
        plt.quantity = 0
        self.session.commit()
        # exclude inactive
        prefs.prefs[prefs.exclude_inactive_pref] = True
        self.assertEqual(source.pictures, [])
        # detached returns empty
        self.session.expunge(source)
        self.assertEqual(source.pictures, [])


class SourceDetailPresenterTests(BaubleTestCase):
    def test_create_presenter_automatic_session(self):
        from bauble.editor import MockView

        view = MockView()
        m = SourceDetail()
        presenter = SourceDetailPresenter(m, view)
        self.assertEqual(presenter.view, view)
        self.assertTrue(presenter.session is not None)
        # model might have been re-instantiated to fit presenter.session

    def test_create_presenter(self):
        from bauble.editor import MockView

        view = MockView()
        m = SourceDetail()
        s = db.Session()
        s.add(m)
        presenter = SourceDetailPresenter(m, view)
        self.assertEqual(presenter.view, view)
        self.assertTrue(presenter.session is not None)
        # m belongs to s; presenter.model is the same object
        self.assertEqual(id(presenter.model), id(m))

    def test_liststore_is_initialized(self):
        from bauble.editor import MockView

        view = MockView(combos={"source_type_combo": []})
        m = SourceDetail(
            name="name", source_type="Expedition", description="desc"
        )
        presenter = SourceDetailPresenter(m, view)
        self.assertEqual(
            presenter.view.widget_get_text("source_name_entry"), "name"
        )
        self.assertEqual(
            presenter.view.widget_get_text("source_type_combo"), "Expedition"
        )
        self.assertEqual(
            presenter.view.widget_get_text("source_desc_textview"), "desc"
        )


import bauble.search


class BaubleSearchSearchTest(BaubleTestCase):
    def test_search_search_dosnt_uses_plant_search(self):
        with self.assertLogs(level="DEBUG") as logs:
            bauble.search.search("genus like %", self.session)
        string = 'SearchStrategy "genus like %" (PlantSearch)'
        self.assertFalse(any(string in i for i in logs.output))
        with self.assertLogs(level="DEBUG") as logs:
            bauble.search.search("12.11.13", self.session)
        string = 'SearchStrategy "12.11.13" (PlantSearch)'
        self.assertFalse(any(string in i for i in logs.output))
        with self.assertLogs(level="DEBUG") as logs:
            bauble.search.search("So ha", self.session)
        string = 'SearchStrategy "So ha" (PlantSearch)'
        self.assertFalse(any(string in i for i in logs.output))
        with self.assertLogs(level="DEBUG") as logs:
            bauble.search.search("plant where id > 1", self.session)
        string = 'SearchStrategy "So ha" (PlantSearch)'
        self.assertFalse(any(string in i for i in logs.output))

    def test_search_search_does_use_plant_search(self):
        with self.assertLogs(level="DEBUG") as logs:
            bauble.search.search("plant like 2021.000%.%", self.session)
        string = 'SearchStrategy "genus like %" (PlantSearch)'
        self.assertFalse(any(string in i for i in logs.output))

        with self.assertLogs(level="DEBUG") as logs:
            bauble.search.search("plant = 2000001.1", self.session)
        string = 'SearchStrategy "12.11.13" (PlantSearch)'
        self.assertFalse(any(string in i for i in logs.output))

        with self.assertLogs(level="DEBUG") as logs:
            bauble.search.search("plant != 20000001.1", self.session)
        string = 'SearchStrategy "So ha" (PlantSearch)'
        self.assertFalse(any(string in i for i in logs.output))


class RetrieveTests(GardenTestCase):
    def test_accession_retreives(self):
        keys = {
            "code": "2001.1",
        }
        acc = Accession.retrieve(self.session, keys)
        self.assertEqual(acc.species_id, 1)

    def test_accession_retreives_id_only(self):
        keys = {"id": 2}
        acc = Accession.retrieve(self.session, keys)
        self.assertEqual(acc.code, "2001.2")

    def test_accession_doesnt_retreive_non_existent(self):
        keys = {"code": "2020.0001"}
        acc = Accession.retrieve(self.session, keys)
        self.assertIsNone(acc)

    def test_accession_doesnt_retreive_wrong_keys(self):
        keys = {"epithet": "Maxillaria"}
        acc = Accession.retrieve(self.session, keys)
        self.assertIsNone(acc)

    def test_location_retreives(self):
        keys = {
            "code": "RBW",
        }
        loc = Location.retrieve(self.session, keys)
        self.assertEqual(loc.id, 1)

    def test_location_retreives_id_only(self):
        keys = {"id": 3}
        loc = Location.retrieve(self.session, keys)
        self.assertEqual(loc.code, "SE")

    def test_location_doesnt_retreive_non_existent(self):
        keys = {"code": "UKNWN"}
        loc = Location.retrieve(self.session, keys)
        self.assertIsNone(loc)

    def test_location_doesnt_retreive_wrong_keys(self):
        keys = {"epithet": "Maxillaria"}
        loc = Location.retrieve(self.session, keys)
        self.assertIsNone(loc)

    def test_plant_retreives(self):
        keys = {
            "accession.code": "2001.2",
            "code": "1",
        }
        plt = Plant.retrieve(self.session, keys)
        self.assertEqual(plt.id, 2)

    def test_plant_retreives_id_only(self):
        keys = {"id": 1}
        plt = Plant.retrieve(self.session, keys)
        self.assertEqual(str(plt), "2001.1.1")

    def test_plant_doesnt_retreive_non_existent(self):
        keys = {"accession.code": "2020.2", "code": "4"}
        plt = Plant.retrieve(self.session, keys)
        self.assertIsNone(plt)

    def test_plant_doesnt_retreive_wrong_keys(self):
        keys = {"name": "Somewhere Else", "epithet": "Maxillaria"}
        plt = Plant.retrieve(self.session, keys)
        self.assertIsNone(plt)

    def test_plant_doesnt_retreive_accession_only(self):
        keys = {
            "accession.code": "2001.2",
        }
        plt = Plant.retrieve(self.session, keys)
        self.assertIsNone(plt)
        # even with only one plant
        keys = {
            "accession.code": "2001.1",
        }
        plt = Plant.retrieve(self.session, keys)
        self.assertIsNone(plt)

    def test_contact_retreives(self):
        contact1 = SourceDetail(name="name1", id=2)
        contact2 = SourceDetail(name="name2", id=3)
        self.session.add_all([contact1, contact2])
        self.session.commit()
        keys = {
            "name": "name1",
        }
        contact = SourceDetail.retrieve(self.session, keys)
        self.assertEqual(contact.id, 2)

    def test_contact_retreives_id_only(self):
        contact1 = SourceDetail(name="name1", id=2)
        contact2 = SourceDetail(name="name2", id=3)
        self.session.add_all([contact1, contact2])
        self.session.commit()
        keys = {"id": 3}
        contact = SourceDetail.retrieve(self.session, keys)
        self.assertEqual(contact.name, "name2")

    def test_contact_doesnt_retreive_non_existent(self):
        contact1 = SourceDetail(name="name1", id=2)
        contact2 = SourceDetail(name="name2", id=3)
        self.session.add_all([contact1, contact2])
        self.session.commit()
        keys = {"name": "Nonexistent"}
        contact = SourceDetail.retrieve(self.session, keys)
        self.assertIsNone(contact)

    def test_contact_doesnt_retreive_wrong_keys(self):
        contact1 = SourceDetail(name="name1", id=2)
        contact2 = SourceDetail(name="name2", id=3)
        self.session.add_all([contact1, contact2])
        self.session.commit()
        keys = {
            "accession.code": "2001.1",
        }
        contact = SourceDetail.retrieve(self.session, keys)
        self.assertIsNone(contact)

    def test_collection_retreives_collection_data(self):
        keys = {
            "collector": "Someone",
            "collectors_code": "1111",
        }
        col = Collection.retrieve(self.session, keys)
        self.assertEqual(col.id, 1)

    def test_collection_retreives_accession_data(self):
        keys = {
            "source.accession.code": "2020.1",
        }
        col = Collection.retrieve(self.session, keys)
        self.assertEqual(col.id, 2)

    def test_collection_retreives_parts(self):
        keys = {
            "source.accession.code": "2001.2",
            "collector": "Someone",
            "collectors_code": "1111",
        }
        col = Collection.retrieve(self.session, keys)
        self.assertEqual(col.id, 1)

    def test_collection_retreives_id_only(self):
        keys = {"id": 2}
        col = Collection.retrieve(self.session, keys)
        self.assertEqual(col.id, 2)

    def test_collection_doesnt_retreive_non_existent(self):
        keys = {
            "source.accession.code": "2020.3",
            "collector": "Me",
            "collectors_code": "3333",
        }
        col = Collection.retrieve(self.session, keys)
        self.assertIsNone(col)

        # mismatch
        keys = {
            "source.accession.code": "2001.2",
            "collector": "Someone Else",
            "collectors_code": "2222",
        }
        col = Collection.retrieve(self.session, keys)
        self.assertIsNone(col)

    def test_collection_doesnt_retreive_wrong_keys(self):
        keys = {"epithet": "Maxillaria"}
        col = Collection.retrieve(self.session, keys)
        self.assertIsNone(col)


class GlobalActionTests(BaubleTestCase):
    @unittest.mock.patch("bauble.plugins.garden.garden_map.map_presenter")
    @unittest.mock.patch("bauble.gui")
    def test_on_inactive_toggled(self, mock_gui, mock_map):
        prefs_view = prefs.PrefsView()
        prefs_view.update = unittest.mock.Mock()
        mock_gui.get_view.return_value = prefs_view
        mock_action = unittest.mock.Mock()
        mock_variant = unittest.mock.Mock()

        mock_variant.get_boolean.return_value = True
        GardenPlugin.on_inactive_toggled(mock_action, mock_variant)
        # prefs_view.update.assert_called()
        self.assertTrue(prefs.prefs.get(prefs.exclude_inactive_pref))

        mock_gui.get_view.reset_mock()
        mock_variant.get_boolean.return_value = False
        GardenPlugin.on_inactive_toggled(mock_action, mock_variant)
        prefs_view.update.assert_called()
        self.assertFalse(prefs.prefs.get(prefs.exclude_inactive_pref))
        mock_map.populate_map_from_search_view.assert_called()

    @unittest.mock.patch("bauble.gui")
    def test_on_sort_toggled(self, mock_gui):
        search_view = get_search_view()
        mock_gui.get_view.return_value = search_view
        mock_action = unittest.mock.Mock()
        mock_variant = unittest.mock.Mock()
        mock_variant.get_boolean.return_value = True

        with unittest.mock.patch.object(search_view, "update") as mock_update:
            GardenPlugin.on_sort_toggled(mock_action, mock_variant)
            mock_update.assert_called()

        self.assertTrue(prefs.prefs.get(SORT_BY_PREF))

        mock_gui.get_view.reset_mock()
        mock_variant.get_boolean.return_value = False
        GardenPlugin.on_sort_toggled(mock_action, mock_variant)
        self.assertFalse(prefs.prefs.get(SORT_BY_PREF))

    def test_set_code_format_default(self):
        with unittest.mock.patch(
            "bauble.plugins.garden.plant.meta.set_value"
        ) as mock_set_val:
            set_code_format()
            mock_set_val.assert_called()
            self.assertEqual(
                mock_set_val.call_args.args[0], PLANT_CODE_FORMAT_KEY
            )
            self.assertEqual(
                mock_set_val.call_args.args[1], DEFAULT_PLANT_CODE_FORMAT
            )
            self.assertIsInstance(mock_set_val.call_args.args[2], str)

    def test_set_code_format_set(self):
        meta.get_default(PLANT_CODE_FORMAT_KEY, "alpha_lower")
        with unittest.mock.patch(
            "bauble.plugins.garden.plant.meta.set_value"
        ) as mock_set_val:
            set_code_format()
            mock_set_val.assert_called()
            self.assertEqual(
                mock_set_val.call_args.args[0], PLANT_CODE_FORMAT_KEY
            )
            self.assertEqual(mock_set_val.call_args.args[1], "alpha_lower")
            self.assertIsInstance(mock_set_val.call_args.args[2], str)
