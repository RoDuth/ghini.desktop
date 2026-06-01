# pylint: disable=no-self-use
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
Generic widgets tests
"""
from datetime import datetime
from itertools import chain
from unittest import mock

from gi.repository import Gtk
from sqlalchemy import select
from sqlalchemy.orm.exc import DetachedInstanceError

from bauble.plugins.plants.family import Family
from bauble.plugins.plants.genus import Genus
from bauble.plugins.plants.species import Species
from bauble.plugins.plants.species import update_all_full_names_task
from bauble.test import BaubleClassTestCase
from bauble.test import BaubleTestCase
from bauble.test import get_setUp_data_funcs

from ..accession import Accession
from ..location import Location
from ..plant import Plant
from ..plant import PlantChange
from ..plant import added_reasons
from ..plant import change_reasons
from ..plant import deleted_reasons
from ..plant import new_plt_reasons
from ..plant import split_reasons
from ..plant import transfer_reasons
from ..ui.widgets.accession import accession_completion_cell_data_func
from ..ui.widgets.accession import accession_match_func
from ..ui.widgets.location import location_match_func
from ..ui.widgets.plant import PlantHistoryPresenter
from ..ui.widgets.plant import _set_cell_from_func


class PlantHistoryPresenterTests(BaubleTestCase):
    def test_init_new(self):

        presenter = PlantHistoryPresenter()
        presenter.init(Plant())

        self.assertEqual(len(presenter.reason_liststore), len(change_reasons))
        self.assertEqual(len(presenter.liststore), 0)

        presenter.destroy()

    def test_init_existing(self):
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

        presenter = PlantHistoryPresenter()
        presenter.init(plant)
        presenter.selection.select_path(0)

        self.assertEqual(len(presenter.reason_liststore), len(new_plt_reasons))
        self.assertEqual(len(presenter.liststore), 2)

        presenter.destroy()

    def test_date_cell_data_func(self):
        change = PlantChange(
            date=datetime(2026, 1, 1),
            reason="PLTD",
            quantity=1,
        )
        model = Gtk.ListStore(object)
        model.append([change])
        tree_iter = model.get_iter(0)

        mock_cell = mock.MagicMock()
        PlantHistoryPresenter.date_cell_data_func(
            None,
            mock_cell,
            model,
            tree_iter,
        )

        mock_cell.set_property.assert_called_once_with("text", "01-01-2026")

        mock_cell.reset_mock()
        change.date = None
        PlantHistoryPresenter.date_cell_data_func(
            None,
            mock_cell,
            model,
            tree_iter,
        )

        mock_cell.set_property.assert_called_once_with("text", "")

    def test_quantity_cell_data_func(self):
        change = PlantChange(
            date=datetime(2026, 1, 1),
            reason="PLTD",
            quantity=10,
        )
        model = Gtk.ListStore(object)
        model.append([change])
        tree_iter = model.get_iter(0)

        mock_cell = mock.MagicMock()
        PlantHistoryPresenter.quantity_cell_data_func(
            None,
            mock_cell,
            model,
            tree_iter,
        )

        mock_cell.set_property.assert_called_once_with("text", "10")

    def test_from_cell_data_func(self):
        change = PlantChange(
            date=datetime(2026, 1, 1),
            reason="PLTD",
            quantity=10,
        )
        model = Gtk.ListStore(object)
        model.append([change])
        tree_iter = model.get_iter(0)

        mock_cell = mock.MagicMock()
        PlantHistoryPresenter.from_cell_data_func(
            None,
            mock_cell,
            model,
            tree_iter,
        )

        mock_cell.set_property.assert_called_once_with("text", "")

        mock_cell.reset_mock()
        location = Location(
            code="LOC1",
            name="Location One",
            description="First location.",
        )
        change.from_location = location
        tree_iter = model.get_iter(0)

        mock_cell = mock.MagicMock()
        PlantHistoryPresenter.from_cell_data_func(
            None,
            mock_cell,
            model,
            tree_iter,
        )

        mock_cell.set_property.assert_called_once_with("text", "LOC1")

    def test_to_cell_data_func(self):
        change = PlantChange(
            date=datetime(2026, 1, 1),
            reason="PLTD",
            quantity=10,
        )
        model = Gtk.ListStore(object)
        model.append([change])
        tree_iter = model.get_iter(0)

        mock_cell = mock.MagicMock()
        PlantHistoryPresenter.to_cell_data_func(
            None,
            mock_cell,
            model,
            tree_iter,
        )

        mock_cell.set_property.assert_called_once_with("text", "")

        mock_cell.reset_mock()
        location = Location(
            code="LOC1",
            name="Location One",
            description="First location.",
        )
        change.to_location = location
        tree_iter = model.get_iter(0)

        mock_cell = mock.MagicMock()
        PlantHistoryPresenter.to_cell_data_func(
            None,
            mock_cell,
            model,
            tree_iter,
        )

        mock_cell.set_property.assert_called_once_with("text", "LOC1")

    def test_parent_cell_data_func(self):
        change = PlantChange(
            date=datetime(2026, 1, 1),
            reason="PLTD",
            quantity=10,
        )
        model = Gtk.ListStore(object)
        model.append([change])
        tree_iter = model.get_iter(0)

        mock_cell = mock.MagicMock()
        PlantHistoryPresenter.parent_cell_data_func(
            None,
            mock_cell,
            model,
            tree_iter,
        )

        mock_cell.set_property.assert_called_once_with("text", "")

        mock_cell.reset_mock()
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
        change.parent_plant = plant
        tree_iter = model.get_iter(0)

        mock_cell = mock.MagicMock()
        PlantHistoryPresenter.parent_cell_data_func(
            None,
            mock_cell,
            model,
            tree_iter,
        )

        mock_cell.set_property.assert_called_once_with("text", "2001.0001.1")

    def test_child_cell_data_func(self):
        change = PlantChange(
            date=datetime(2026, 1, 1),
            reason="PLTD",
            quantity=10,
        )
        model = Gtk.ListStore(object)
        model.append([change])
        tree_iter = model.get_iter(0)

        mock_cell = mock.MagicMock()
        PlantHistoryPresenter.child_cell_data_func(
            None,
            mock_cell,
            model,
            tree_iter,
        )

        mock_cell.set_property.assert_called_once_with("text", "")

        mock_cell.reset_mock()
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
        change.child_plant = plant
        tree_iter = model.get_iter(0)

        mock_cell = mock.MagicMock()
        PlantHistoryPresenter.child_cell_data_func(
            None,
            mock_cell,
            model,
            tree_iter,
        )

        mock_cell.set_property.assert_called_once_with("text", "2001.0001.1")

    def test_reason_cell_data_func(self):
        change = PlantChange(
            date=datetime(2026, 1, 1),
            reason="PLTD",
            quantity=10,
        )
        model = Gtk.ListStore(object)
        model.append([change])
        tree_iter = model.get_iter(0)

        mock_cell = mock.MagicMock()
        PlantHistoryPresenter.reason_cell_data_func(
            None,
            mock_cell,
            model,
            tree_iter,
        )

        mock_cell.set_property.assert_called_once_with("text", "New planting")

        mock_cell.reset_mock()
        change.reason = None
        PlantHistoryPresenter.reason_cell_data_func(
            None,
            mock_cell,
            model,
            tree_iter,
        )

        mock_cell.set_property.assert_called_once_with("text", "")

    def test_user_cell_data_func(self):
        change = PlantChange(
            date=datetime(2026, 1, 1),
            reason="PLTD",
            quantity=10,
        )
        model = Gtk.ListStore(object)
        model.append([change])
        tree_iter = model.get_iter(0)

        mock_cell = mock.MagicMock()
        PlantHistoryPresenter.user_cell_data_func(
            None,
            mock_cell,
            model,
            tree_iter,
        )

        mock_cell.set_property.assert_called_once_with("text", "")
        change.person = "Jade Greeen"
        mock_cell.reset_mock()
        PlantHistoryPresenter.user_cell_data_func(
            None,
            mock_cell,
            model,
            tree_iter,
        )

        mock_cell.set_property.assert_called_once_with("text", "Jade Greeen")

    def test_set_cell_from_func_detached_instance(self):
        change = PlantChange(
            date=datetime(2026, 1, 1),
            reason="PLTD",
            quantity=10,
        )

        mock_cell = mock.MagicMock()
        mock_func = mock.MagicMock()
        mock_func.side_effect = DetachedInstanceError("BOOM")

        change.from_location = None
        with self.assertLogs(
            "bauble.plugins.garden.ui.widgets", level="DEBUG"
        ) as logs:
            _set_cell_from_func(
                mock_cell,
                change,
                mock_func,
            )

        self.assertIn("DetachedInstanceError(BOOM", logs.output[0])
        mock_cell.set_property.assert_not_called()

    def test__user_edit_start(self):
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
        plant.changes.append(
            PlantChange(
                date=datetime(2026, 1, 1),
                reason="PLTD",
                quantity=1,
                person="Jade Green",
            )
        )
        self.session.add(plant)
        self.session.commit()

        presenter = PlantHistoryPresenter()
        presenter.init(Plant())
        entry = Gtk.Entry()
        self.assertIsNone(entry.get_completion())
        presenter.user_cell.emit(
            "editing-started",
            entry,
            "0",
        )

        self.assertIsNotNone(entry.get_completion())
        self.assertEqual(len(entry.get_completion().get_model()), 1)
        self.assertEqual(
            entry.get_completion().get_model()[0][0],
            "Jade Green",
        )

        presenter.destroy()

    def test_selection_change_sets_reasons(self):
        family = Family(epithet="Austrobaileyaceae")
        genus = Genus(epithet="Austrobaileya", family=family)
        species = Species(genus=genus, epithet="scandens")
        accession = Accession(code="2001.0001", species=species)
        location = Location(
            code="LOC1",
            name="Location One",
            description="First location.",
        )
        location2 = Location(
            code="LOC2",
            name="Location Two",
            description="second location.",
        )
        plant = Plant(
            accession=accession,
            location=location,
            code="1",
            quantity=2,
        )
        plant.changes.append(
            PlantChange(
                date=datetime(2026, 1, 1),
                reason="PLTD",
                quantity=1,
            )
        )
        plant.changes.append(
            PlantChange(
                date=datetime(2026, 2, 1),
                reason="TRAN",
                quantity=1,
                from_location=location,
                to_location=location2,
            )
        )
        plant.changes.append(
            PlantChange(
                date=datetime(2026, 3, 1),
                reason="DEAD",
                quantity=-1,
                from_location=location2,
            )
        )
        plant.changes.append(
            PlantChange(
                date=datetime(2026, 2, 1),
                reason="VPIP",
                quantity=1,
                to_location=location2,
            )
        )

        presenter = PlantHistoryPresenter()
        presenter.init(plant)
        presenter.selection.select_path(0)

        self.assertEqual(len(presenter.liststore), 4)
        self.assertEqual(dict(presenter.reason_liststore), new_plt_reasons)

        presenter.selection.select_path(1)

        self.assertEqual(dict(presenter.reason_liststore), transfer_reasons)

        presenter.selection.select_path(2)

        self.assertEqual(dict(presenter.reason_liststore), deleted_reasons)

        presenter.selection.select_path(3)

        self.assertEqual(dict(presenter.reason_liststore), added_reasons)

        presenter.destroy()

    def test_selection_change_split_reasons(self):
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

        presenter = PlantHistoryPresenter()
        presenter.init(plant2)
        presenter.selection.select_path(0)

        self.assertEqual(len(presenter.liststore), 1)
        self.assertEqual(dict(presenter.reason_liststore), split_reasons)

        presenter.destroy()

    def test_on_selection_changed_no_iter_bails(self):
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
        presenter = PlantHistoryPresenter()
        presenter.init(plant)
        mock_selection = mock.Mock()
        mock_model = mock.Mock()
        mock_selection.get_selected.return_value = mock_model, None

        presenter.on_selection_changed(mock_selection)

        mock_model.get_path.assert_not_called()
        self.assertEqual(dict(presenter.reason_liststore), change_reasons)

        presenter.destroy()

    def test_on_date_edited(self):
        change = PlantChange()
        liststore = Gtk.ListStore(object)
        liststore.append((change,))
        mock_self = mock.Mock()
        mock_self.liststore = liststore

        PlantHistoryPresenter.on_date_edited(
            mock_self,
            None,
            "0",
            "2026-01-11",
        )

        self.assertEqual(change.date, datetime(2026, 1, 11))
        mock_self.emit.assert_called_once_with("changed")
        mock_self.reset_mock()

        PlantHistoryPresenter.on_date_edited(
            mock_self,
            None,
            "0",
            "spam spam spam",
        )

        # can't parst, don't change
        self.assertEqual(change.date, datetime(2026, 1, 11))
        mock_self.emit.assert_not_called()

    def test_on_reason_changed(self):
        change = PlantChange()
        liststore = Gtk.ListStore(object)
        liststore.append((change,))
        reason_ls = Gtk.ListStore(str, str)
        reason_ls.append(("PLTD", "New planting"))
        mock_self = mock.Mock()
        mock_self.liststore = liststore
        mock_self.reason_liststore = reason_ls

        PlantHistoryPresenter.on_reason_changed(
            mock_self,
            None,
            "0",
            "0",
        )

        self.assertEqual(change.reason, "PLTD")
        mock_self.emit.assert_called_once_with("changed")

    def test_on_user_edited(self):
        change = PlantChange()
        liststore = Gtk.ListStore(object)
        liststore.append((change,))
        mock_self = mock.Mock()
        mock_self.liststore = liststore

        PlantHistoryPresenter.on_user_edited(
            mock_self,
            None,
            "0",
            "Forrest Gardener",
        )

        self.assertEqual(change.person, "Forrest Gardener")
        mock_self.emit.assert_called_once_with("changed")


class AccessionCompletionTests(BaubleClassTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        for setup_func in get_setUp_data_funcs():
            setup_func()

        list(update_all_full_names_task())

        cls.completion = Gtk.EntryCompletion()
        completion_model = Gtk.ListStore(object)
        for val in cls.session.execute(
            select(Accession).order_by(Accession.id)
        ):
            completion_model.append(val)
        cls.completion.set_model(completion_model)

    @classmethod
    def tearDownClass(cls):
        del cls.completion
        return super().tearDownClass()

    def test_match_func_full_accession_code(self):
        key = "2001.1"
        self.assertTrue(accession_match_func(self.completion, key, 0))
        for i in range(1, 7):
            self.assertFalse(accession_match_func(self.completion, key, i))

    def test_match_func_full_accession_code_and_species(self):
        key = "2001.1 Maxillaria s. str variabilis"
        self.assertTrue(accession_match_func(self.completion, key, 0))
        for i in range(1, 7):
            self.assertFalse(accession_match_func(self.completion, key, i))

    def test_match_func_partial_accession_code(self):
        key = "202"
        self.assertFalse(accession_match_func(self.completion, key, 0))
        self.assertFalse(accession_match_func(self.completion, key, 1))
        for i in range(2, 7):
            self.assertTrue(accession_match_func(self.completion, key, i))

    def test_match_func_full_species(self):
        key = "Maxillaria s. str variabilis"
        self.assertTrue(accession_match_func(self.completion, key, 0))
        self.assertTrue(accession_match_func(self.completion, key, 2))
        for i in chain([1], range(3, 7)):
            self.assertFalse(accession_match_func(self.completion, key, i))

    def test_match_func_partial_species(self):
        key = "Max var"
        self.assertTrue(accession_match_func(self.completion, key, 0))
        self.assertTrue(accession_match_func(self.completion, key, 2))
        for i in chain([1], range(3, 7)):
            self.assertFalse(accession_match_func(self.completion, key, i))

    def test_match_func_partial_accession_and_species(self):
        key = "20 Enc coc"
        self.assertTrue(accession_match_func(self.completion, key, 1))
        self.assertTrue(accession_match_func(self.completion, key, 3))
        for i in chain([0, 2], range(4, 7)):
            self.assertFalse(accession_match_func(self.completion, key, i))

    def test_match_func_no_tree_raises(self):
        key = "20 Enc coc"
        self.assertRaises(
            AttributeError,
            accession_match_func,
            Gtk.EntryCompletion(),
            key,
            0,
        )

    def test_accession_cell_data_func(self):
        mock_renderer = mock.Mock()
        mock_model = [[self.session.get(Accession, 1)]]

        accession_completion_cell_data_func(None, mock_renderer, mock_model, 0)

        mock_renderer.set_property.assert_called_with(
            "text",
            "2001.1 (Maxillaria s. str variabilis)",
        )

        mock_renderer.reset_mock()
        mock_value = mock.MagicMock()
        mock_value.__str__.side_effect = DetachedInstanceError("BOOM")
        mock_model = [[mock_value]]

        with self.assertLogs(
            "bauble.plugins.garden.ui.widgets", level="DEBUG"
        ) as logs:
            accession_completion_cell_data_func(
                None, mock_renderer, mock_model, 0
            )

        self.assertIn("DetachedInstanceError(BOOM", logs.output[0])
        mock_renderer.set_property.assert_called_with("text", "")


class LocationCompletionTests(BaubleClassTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.loc1 = Location(
            code="LOC1",
            name="Location One",
            description="First location.",
        )
        cls.loc2 = Location(
            code="LOC2",
            name="Location Two",
            description="second location.",
        )
        cls.other1 = Location(
            code="OTH1",
            name="Other One",
            description="First other location.",
        )
        cls.other2 = Location(
            code="OTH2",
            name="Other Two",
            description="Second other location.",
        )

        cls.completion = Gtk.EntryCompletion()
        completion_model = Gtk.ListStore(object)
        for val in (cls.loc1, cls.loc2, cls.other1, cls.other2):
            completion_model.append((val,))
        cls.completion.set_model(completion_model)

    @classmethod
    def tearDownClass(cls):
        del cls.completion
        return super().tearDownClass()

    def test_match_func_full_code(self):
        key = "LOC1"
        self.assertTrue(location_match_func(self.completion, key, 0))
        for i in range(1, 4):
            self.assertFalse(location_match_func(self.completion, key, i))

    def test_match_func_full_code_and_name(self):
        key = "(OTH2) Other Two"
        self.assertTrue(location_match_func(self.completion, key, 3))
        for i in range(3):
            self.assertFalse(location_match_func(self.completion, key, i))

    def test_match_func_full_name(self):
        key = "Other Two"
        self.assertTrue(location_match_func(self.completion, key, 3))
        for i in range(3):
            self.assertFalse(location_match_func(self.completion, key, i))

    def test_match_func_partial_name(self):
        key = "Other"
        self.assertTrue(location_match_func(self.completion, key, 2))
        self.assertTrue(location_match_func(self.completion, key, 3))
        for i in range(2):
            self.assertFalse(location_match_func(self.completion, key, i))

    def test_match_func_partial_code(self):
        key = "LOC"
        self.assertTrue(location_match_func(self.completion, key, 0))
        self.assertTrue(location_match_func(self.completion, key, 1))
        for i in range(2, 4):
            self.assertFalse(location_match_func(self.completion, key, i))

    def test_match_func_no_tree_raises(self):
        key = "LOC"
        self.assertRaises(
            AttributeError,
            location_match_func,
            Gtk.EntryCompletion(),
            key,
            0,
        )
