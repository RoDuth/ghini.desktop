# pylint: disable=protected-access,no-self-use,too-many-statements
# pylint: disable=too-many-lines
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
import os
from datetime import datetime
from tempfile import mkstemp
from unittest import TestCase
from unittest import mock

from gi.repository import Gdk
from gi.repository import Gtk
from sqlalchemy import func
from sqlalchemy import insert
from sqlalchemy import select
from sqlalchemy import update
from sqlalchemy.orm.exc import DetachedInstanceError

from bauble import db
from bauble import prefs
from bauble import utils
from bauble.plugins.plants.family import Family
from bauble.plugins.plants.family import FamilySynonym
from bauble.plugins.plants.genus import Genus
from bauble.plugins.plants.geography import Geography
from bauble.plugins.plants.species import Species
from bauble.plugins.plants.species import SpeciesDistribution
from bauble.plugins.plants.species import VernacularName
from bauble.plugins.plants.species import update_all_full_names_task
from bauble.test import BaubleClassTestCase
from bauble.test import BaubleTestCase
from bauble.test import get_setUp_data_funcs
from bauble.test import update_gui
from bauble.test import wait_on_threads
from bauble.ui.presenter import Response
from bauble.ui.utils import get_widget_value
from bauble.ui.utils import set_widget_value
from bauble.ui.widgets.message import MessageBox

from ..ui.species_editor import SpeciesEditorDialog
from ..ui.widgets.distribution import DistributionPresenter
from ..ui.widgets.geography import GEO_PACIFIC_CENTRIC
from ..ui.widgets.geography import DistributionMap
from ..ui.widgets.geography import DistributionMapEventBox
from ..ui.widgets.geography import GeographyMenu
from ..ui.widgets.geography import calculate_zoom_buffer
from ..ui.widgets.geography import get_viewbox
from ..ui.widgets.geography import split_lats_longs
from ..ui.widgets.geography import straddles_antimeridian
from ..ui.widgets.geography import update_all_approx_areas_handler
from ..ui.widgets.geography import update_all_approx_areas_task
from ..ui.widgets.species import InfraspecificPresenter
from ..ui.widgets.species import InfraspRow
from ..ui.widgets.species import SpeciesEntry
from ..ui.widgets.species import setup_conservation_fields
from ..ui.widgets.species import species_cell_data_func
from ..ui.widgets.species import species_completions
from ..ui.widgets.species import species_match_func
from ..ui.widgets.species import species_to_string_matcher
from ..ui.widgets.species import update_all_full_names_handler
from ..ui.widgets.synonyms import SynonymsPresenter
from ..ui.widgets.synonyms import _syn_data_func
from ..ui.widgets.synonyms import taxon_completion_cell_data_func
from ..ui.widgets.vernacular import CAPITALISE_VNAMES_ON_PASTE_PREF_KEY
from ..ui.widgets.vernacular import VernacularNamePresenter
from .test_geography import setup_geographies
from .test_plants import setUp_data as setup_plants_data


class SynonymsPresenterTests(BaubleTestCase):
    def test_init_new(self):
        family = Family()
        syns_presenter = SynonymsPresenter()
        syns_presenter.init(
            family,
            FamilySynonym,
            self.session,
            lambda text: (
                select(Family)
                .where(utils.ilike(Family.epithet, f"{text}%%"))
                .order_by(Family.epithet)
            ),
        )

        self.assertTrue(syns_presenter.get_sensitive())

        syns_presenter.destroy()

    def test_init_syn(self):
        family1 = Family(epithet="Fooaceae")
        family2 = Family(epithet="Baraceae")
        family1.accepted = family2
        syns_presenter = SynonymsPresenter()
        syns_presenter.init(
            family1,
            FamilySynonym,
            self.session,
            lambda text: (
                select(Family)
                .where(utils.ilike(Family.epithet, f"{text}%%"))
                .order_by(Family.epithet)
            ),
        )

        self.assertFalse(syns_presenter.get_sensitive())

        syns_presenter.destroy()

    def test_init_existing(self):
        family = Family(epithet="Fooaceae")
        self.session.add(family)
        self.session.commit()
        syns_presenter = SynonymsPresenter()
        syns_presenter.init(
            family,
            FamilySynonym,
            self.session,
            lambda text: (
                select(Family)
                .where(utils.ilike(Family.epithet, f"{text}%%"))
                .order_by(Family.epithet)
            ),
        )

        self.assertTrue(syns_presenter.get_sensitive())

        syns_presenter.destroy()

    def test_treeview_populates(self):
        myrtaceae = Family(epithet="Myrtaceae")
        leptospermaceae = Family(epithet="Leptospermaceae")
        myrtaceae.synonyms.append(leptospermaceae)
        syns_presenter = SynonymsPresenter()
        syns_presenter.init(
            myrtaceae,
            FamilySynonym,
            self.session,
            lambda text: (
                select(Family)
                .where(utils.ilike(Family.epithet, f"{text}%%"))
                .order_by(Family.epithet)
            ),
        )

        # nothing selected
        self.assertEqual(len(syns_presenter.treeview.get_model()), 1)
        self.assertFalse(syns_presenter.remove_button.get_sensitive())

        # first selected
        syns_presenter.treeview.set_cursor(Gtk.TreePath(0))

        self.assertTrue(syns_presenter.remove_button.get_sensitive())

        syns_presenter.destroy()

    def test_on_entry_changed(self):
        for func in get_setUp_data_funcs():
            func()

        family = Family()
        syns_presenter = SynonymsPresenter()
        syns_presenter.init(
            family,
            FamilySynonym,
            self.session,
            lambda text: (
                select(Family)
                .where(utils.ilike(Family.epithet, f"{text}%%"))
                .order_by(Family.epithet)
            ),
        )
        model = syns_presenter.completion.get_model()
        # without min_key_length set will populate
        syns_presenter.entry.set_text("M")

        self.assertGreater(len(model), 0)
        self.assertIsNone(syns_presenter._selected)
        self.assertEqual("M", syns_presenter.entry.get_text())
        self.assertFalse(syns_presenter.add_button.get_sensitive())
        self.assertEqual(syns_presenter.additional, [])

        # exact match will select
        syns_presenter.entry.set_text("Myrtaceae")

        self.assertEqual(syns_presenter._selected.epithet, "Myrtaceae")
        self.assertEqual("Myrtaceae Juss.", syns_presenter.entry.get_text())
        self.assertTrue(syns_presenter.add_button.get_sensitive())
        self.assertEqual(syns_presenter.additional, [])

        # set a minimum key length will not populate
        syns_presenter.completion.set_minimum_key_length(3)
        syns_presenter.entry.set_text("My")

        self.assertEqual(len(model), 0)
        self.assertIsNone(syns_presenter._selected)
        self.assertEqual("My", syns_presenter.entry.get_text())
        self.assertFalse(syns_presenter.add_button.get_sensitive())
        self.assertEqual(syns_presenter.additional, [])

        # populates once min key length is met
        syns_presenter.entry.set_text("Myr")

        self.assertGreater(len(model), 0)
        self.assertIn("Myrtaceae", [str(i[0]) for i in model])
        self.assertEqual("Myr", syns_presenter.entry.get_text())
        self.assertFalse(syns_presenter.add_button.get_sensitive())
        self.assertIsNone(syns_presenter._selected)

        syns_presenter.destroy()

    def test_syn_get_completions(self):
        family1 = Family(epithet="Myrtaceae")
        family2 = Family(epithet="Myrscinaceae")
        family3 = Family(epithet="Myristicaceae")
        self.session.add_all([family1, family2, family3])
        self.session.commit()
        syns_presenter = SynonymsPresenter()
        syns_presenter.init(
            family1,
            FamilySynonym,
            self.session,
            lambda text: (
                select(Family)
                .where(utils.ilike(Family.epithet, f"{text}%%"))
                .order_by(Family.epithet)
            ),
        )
        # None case
        syns_presenter.model = None

        self.assertEqual(syns_presenter.syn_get_completions("M"), [])

        # base case, no synonyms
        syns_presenter.model = family1

        self.assertCountEqual(
            syns_presenter.syn_get_completions("M"),
            [family2, family3],
        )

        # family2 is a synonym of self, exclude
        family1.synonyms.append(family2)

        self.assertCountEqual(
            syns_presenter.syn_get_completions("M"),
            [family3],
        )
        # same before and after commit
        self.session.commit()

        self.assertCountEqual(
            syns_presenter.syn_get_completions("M"),
            [family3],
        )

        # reset
        family1.synonyms.remove(family2)
        self.session.commit()
        # family2 has synonym family3, family3 should be excluded
        family2.synonyms.append(family3)
        self.session.commit()

        self.assertCountEqual(
            syns_presenter.syn_get_completions("M"),
            [family2],
        )

        syns_presenter.destroy()

    def test_on_match_selected_none(self):
        syns_presenter = SynonymsPresenter()
        syns_presenter.init(
            Family(),
            FamilySynonym,
            self.session,
            lambda text: (
                select(Family)
                .where(utils.ilike(Family.epithet, f"{text}%%"))
                .order_by(Family.epithet)
            ),
        )
        liststore = Gtk.ListStore(object)
        liststore.append([None])
        family = Family(epithet="Myrtaceae")
        liststore.append([family])
        syns_presenter.on_match_selected(None, liststore, 1)

        self.assertTrue(syns_presenter.add_button.get_sensitive())
        self.assertEqual(syns_presenter._selected, family)

        syns_presenter.on_match_selected(None, liststore, 0)
        self.assertFalse(syns_presenter.add_button.get_sensitive())
        self.assertIsNone(syns_presenter._selected)

        syns_presenter.destroy()

    def test_on_add_button_clicked(self):
        for func in get_setUp_data_funcs():
            func()

        myrtaceae = self.session.execute(
            select(Family).where(Family.epithet == "Myrtaceae")
        ).scalar()
        leptospermaceae = Family(epithet="Leptospermaceae")
        myrtaceae.synonyms.append(leptospermaceae)
        self.session.commit()

        family = Family()
        syns_presenter = SynonymsPresenter()
        syns_presenter.init(
            family,
            FamilySynonym,
            self.session,
            lambda text: (
                select(Family)
                .where(utils.ilike(Family.epithet, f"{text}%%"))
                .order_by(Family.epithet)
            ),
        )
        # no selected returns
        syns_presenter.add_button.clicked()

        self.assertEqual(len(syns_presenter.treeview.get_model()), 0)

        # exact match will select and move existing synonyms also
        syns_presenter.entry.set_text("Myrtaceae")
        syns_presenter.add_button.clicked()

        self.assertEqual(len(syns_presenter.treeview.get_model()), 2)
        self.assertEqual(syns_presenter.entry.get_text(), "")
        self.assertIsNone(syns_presenter._selected)
        self.assertFalse(syns_presenter.add_button.get_sensitive())
        self.assertFalse(syns_presenter.remove_button.get_sensitive())

        syns_presenter.destroy()

    @mock.patch(
        "bauble.plugins.plants.ui.widgets.synonyms.dialogs.yes_no_dialog"
    )
    def test_on_remove_button_clicked(self, mock_dlog):
        mock_dlog.return_value = True
        myrtaceae = Family(epithet="Myrtaceae")
        leptospermaceae = Family(epithet="Leptospermaceae")
        myrtaceae.synonyms.append(leptospermaceae)
        self.session.add(myrtaceae)
        self.session.commit()

        syns_presenter = SynonymsPresenter()
        syns_presenter.init(
            myrtaceae,
            FamilySynonym,
            self.session,
            lambda text: (
                select(Family)
                .where(utils.ilike(Family.epithet, f"{text}%%"))
                .order_by(Family.epithet)
            ),
        )
        self.assertEqual(len(myrtaceae.synonyms), 1)

        # no selected returns
        syns_presenter.remove_button.clicked()
        self.assertEqual(len(syns_presenter.treeview.get_model()), 1)

        # select first
        syns_presenter.treeview.set_cursor(Gtk.TreePath(0))
        # include get_toplevel returns Window
        with mock.patch.object(syns_presenter, "get_toplevel") as mock_tlevel:
            win = Gtk.Window()
            mock_tlevel.return_value = win
            syns_presenter.remove_button.clicked()

            self.assertEqual(mock_dlog.call_args[1]["parent"], win)

        self.assertEqual(len(myrtaceae.synonyms), 0)

        syns_presenter.destroy()

    @mock.patch(
        "bauble.plugins.plants.ui.widgets.synonyms.dialogs.yes_no_dialog"
    )
    def test_on_remove_button_clicked_w_additional(self, mock_dlog):
        mock_dlog.return_value = True
        myrtaceae = Family(epithet="Myrtaceae")
        leptospermaceae = Family(epithet="Leptospermaceae")
        myrtaceae.synonyms.append(leptospermaceae)
        family = Family(epithet="Fooaceae")
        self.session.add(myrtaceae)
        self.session.add(family)
        self.session.commit()

        syns_presenter = SynonymsPresenter()
        syns_presenter.init(
            family,
            FamilySynonym,
            self.session,
            lambda text: (
                select(Family)
                .where(utils.ilike(Family.epithet, f"{text}%%"))
                .order_by(Family.epithet)
            ),
        )
        # exact match will select and move existing synonyms also
        syns_presenter.entry.set_text("Myrtaceae")
        self.assertEqual(syns_presenter._selected, myrtaceae)
        syns_presenter.add_button.clicked()

        self.assertEqual(len(syns_presenter.treeview.get_model()), 2)
        self.assertEqual(len(syns_presenter.additional), 1)
        self.assertEqual(len(myrtaceae.synonyms), 0)
        self.assertEqual(len(family.synonyms), 2)

        # select and remove first
        syns_presenter.treeview.set_cursor(Gtk.TreePath(1))
        syns_presenter.remove_button.clicked()

        self.assertEqual(len(myrtaceae.synonyms), 1)
        self.assertEqual(len(family.synonyms), 1)

        # select and remove again but user rejects
        mock_dlog.return_value = False
        syns_presenter.treeview.set_cursor(Gtk.TreePath(0))
        syns_presenter.remove_button.clicked()

        self.assertEqual(len(myrtaceae.synonyms), 1)
        self.assertEqual(len(family.synonyms), 1)

        # select and remove again, don't reject
        mock_dlog.return_value = True
        syns_presenter.treeview.set_cursor(Gtk.TreePath(0))
        syns_presenter.remove_button.clicked()

        self.assertEqual(len(myrtaceae.synonyms), 1)
        self.assertEqual(len(family.synonyms), 0)
        self.assertEqual(len(syns_presenter.additional), 0)

        syns_presenter.destroy()

    def test_syn_data_func(self):
        family1 = Family(epithet="Myrtaceae")
        family2 = Family(epithet="Leptospermaceae")
        family1.synonyms.append(family2)
        self.session.add(family1)
        self.session.commit()
        synonym = family1._synonyms[0]
        model = Gtk.ListStore(object)
        treeiter = model.append([synonym])
        cell = Gtk.CellRendererText()
        column = Gtk.TreeViewColumn("column")
        column.set_cell_data_func(cell, _syn_data_func)

        _syn_data_func(column, cell, model, treeiter, None)

        self.assertEqual(
            cell.get_property("foreground_rgba").to_string(),
            "rgb(0,0,0)",
        )
        self.assertEqual(cell.get_property("text"), "Leptospermaceae")

        synonym.family_id = 3

        _syn_data_func(column, cell, model, treeiter, None)

        self.assertEqual(
            cell.get_property("foreground_rgba").to_string(),
            "rgb(0,0,255)",
        )
        self.assertEqual(cell.get_property("text"), "Leptospermaceae")
        # doesn't fail for detached
        with mock.patch.object(synonym, "markup") as mock_markup:
            mock_markup.side_effect = DetachedInstanceError
            _syn_data_func(column, cell, model, treeiter, None)

    def test_taxon_completion_cell_data_func(self):
        mock_obj = mock.MagicMock()
        mock_obj.string.return_value = "<Test>"
        list_store = Gtk.ListStore(object)
        list_store.append([mock_obj])
        mock_renderer = mock.MagicMock()

        taxon_completion_cell_data_func(None, mock_renderer, list_store, 0)
        mock_renderer.set_property.assert_called_once_with(
            "markup", "&lt;Test&gt;"
        )

    def test_taxon_completion_cell_data_func_detached_instance(self):
        mock_obj = mock.MagicMock()
        mock_obj.string.side_effect = DetachedInstanceError
        list_store = Gtk.ListStore(object)
        list_store.append([mock_obj])
        mock_renderer = mock.MagicMock()

        with self.assertLogs(
            "bauble.plugins.plants.ui.widgets", level="DEBUG"
        ) as logs:
            taxon_completion_cell_data_func(
                None,
                mock_renderer,
                list_store,
                0,
            )
        self.assertIn("DetachedInstanceError", logs.output[0])
        mock_renderer.set_property.assert_called_once_with("markup", "")


class SpeciesEntryTests(TestCase):
    def test_blank_does_not_error(self):
        entry = SpeciesEntry()
        self.assertFalse(entry.species_space)
        entry.do_insert_text("", 0, 0)

    def test_spaces_not_allowed_on_init(self):
        entry = SpeciesEntry()
        self.assertFalse(entry.species_space)
        # like pasting
        string = "test1 test2"
        entry.set_text(string)
        self.assertEqual(entry.get_text(), string.replace(" ", ""))

        # like typing
        self.assertEqual(entry.insert_text("s", 0), 1)
        self.assertEqual(entry.insert_text(" ", 1), 1)

    def test_dont_allow_capitalised(self):
        entry = SpeciesEntry()
        # like pasting
        entry.set_text("Test")
        self.assertEqual(entry.get_text(), "test")

        # like typing at the start
        self.assertEqual(entry.insert_text("T", 0), 1)
        self.assertEqual(entry.get_text(), "ttest")

    def test_allow_spaces_for_hybrids(self):
        entry = SpeciesEntry()
        # like pasting
        hybrid = "test1 × test2"
        entry.set_text(hybrid)
        self.assertEqual(entry.get_text(), hybrid)

        # like typing
        self.assertEqual(entry.insert_text("*", len(hybrid)), len(hybrid) + 3)
        self.assertEqual(entry.get_text(), hybrid + " × ")

        # nothotaxon
        entry = SpeciesEntry()
        self.assertEqual(entry.insert_text("*", 0), 2)
        self.assertEqual(entry.get_text(), "× ")

    def test_allow_spaces_for_sp_nov(self):
        entry = SpeciesEntry()
        # like pasting
        nov = "sp. nov."
        entry.set_text(nov)
        self.assertEqual(entry.get_text(), nov)

        # like typing
        entry = SpeciesEntry()
        self.assertEqual(entry.insert_text("s", 0), 1)
        self.assertEqual(entry.insert_text("p", 1), 2)
        self.assertEqual(entry.insert_text(".", 2), 3)
        self.assertEqual(entry.insert_text(" ", 3), 4)
        self.assertEqual(entry.insert_text("n", 4), 5)
        self.assertEqual(entry.insert_text("o", 5), 6)
        self.assertEqual(entry.insert_text("v", 6), 7)
        self.assertEqual(entry.insert_text(".", 7), 8)
        self.assertEqual(entry.get_text(), nov)

    def test_allow_spaces_for_provisional(self):
        # very similar to above but tests that capitals remain
        entry = SpeciesEntry()
        # like pasting
        prov = "sp. (Ormeau L.H.Bird AQ435851)"
        entry.set_text(prov)
        self.assertEqual(entry.get_text(), prov)

    def test_allow_spaces_for_descriptive(self):
        entry = SpeciesEntry()
        # like pasting
        prov = "banksii (White Form)"
        entry.set_text(prov)
        self.assertEqual(entry.get_text(), prov)

        # like typing
        entry = SpeciesEntry()
        self.assertEqual(entry.insert_text("t", 0), 1)
        self.assertEqual(entry.insert_text("(", 1), 3)  # inserts space
        self.assertEqual(entry.insert_text("T", 3), 4)
        self.assertEqual(entry.get_text(), "t (T")


class SpeciesCompletionTests(BaubleTestCase):
    def setUp(self):
        super().setUp()
        setup_plants_data()
        self.family = Family(family="Myrtaceae")
        self.genus = Genus(family=self.family, genus="Syzygium")
        self.sp1 = Species(genus=self.genus, epithet="australe")
        self.sp2 = Species(genus=self.genus, epithet="luehmannii")
        self.sp3 = Species(genus=self.genus, epithet="aqueum")
        self.session.add_all(
            [self.family, self.genus, self.sp1, self.sp2, self.sp3]
        )
        self.session.commit()
        self.sp4 = self.session.get(Species, 9)
        self.sp5 = self.session.get(Species, 25)
        self.session.commit()

        self.completion = Gtk.EntryCompletion()
        completion_model = Gtk.ListStore(object)
        for val in [self.sp1, self.sp2, self.sp3, self.sp4, self.sp5]:
            completion_model.append([val])
        self.completion.set_model(completion_model)

    def test_species_match_func_full_name(self):
        key = "Syzygium australe"
        self.assertTrue(species_match_func(self.completion, key, 0))
        self.assertFalse(species_match_func(self.completion, key, 1))
        self.assertFalse(species_match_func(self.completion, key, 2))

    def test_species_match_func_only_full_genus(self):
        key = "syzygium"
        self.assertTrue(species_match_func(self.completion, key, 0))
        self.assertTrue(species_match_func(self.completion, key, 1))
        self.assertTrue(species_match_func(self.completion, key, 2))

    def test_species_match_func_only_partial_genus(self):
        key = "Syzyg"
        self.assertTrue(species_match_func(self.completion, key, 0))
        self.assertTrue(species_match_func(self.completion, key, 1))
        self.assertTrue(species_match_func(self.completion, key, 2))

    def test_species_match_func_only_partial_binomial(self):
        key = "Syz lu".lower()
        self.assertFalse(species_match_func(self.completion, key, 0))
        self.assertTrue(species_match_func(self.completion, key, 1))
        self.assertFalse(species_match_func(self.completion, key, 2))

    def test_species_match_func_notho_taxa(self):
        key = "Maxillaria × generalis"
        self.assertTrue(species_match_func(self.completion, key, 3))
        self.assertFalse(species_match_func(self.completion, key, 0))
        self.assertFalse(species_match_func(self.completion, key, 1))
        key = "+ Crataegomespilus dardarii"
        self.assertTrue(species_match_func(self.completion, key, 4))
        self.assertFalse(species_match_func(self.completion, key, 0))
        self.assertFalse(species_match_func(self.completion, key, 1))

    def test_species_match_func_no_tree_raises(self):
        key = "Syzygium australe"
        self.assertRaises(
            AttributeError,
            species_match_func,
            Gtk.EntryCompletion(),
            key,
            0,
        )

    @mock.patch("bauble.plugins.plants.ui.widgets.species.inspect")
    def test_species_match_func_not_persistent_returns_false(
        self,
        mock_inspect,
    ):
        mock_inspect().persistent = False
        key = "Syzyg"
        self.assertFalse(species_match_func(self.completion, key, 0))

    def test_species_completions(self):
        list(update_all_full_names_task())
        key = "Syz lu"
        self.assertCountEqual(
            self.session.execute(species_completions(key)).scalars().all(),
            [self.sp2],
        )
        key = "Syzyg"
        self.assertCountEqual(
            self.session.execute(species_completions(key)).scalars().all(),
            [self.sp1, self.sp2, self.sp3],
        )
        key = "Syzygium australe"
        self.assertCountEqual(
            self.session.execute(species_completions(key)).scalars().all(),
            [self.sp1],
        )
        key = "Unknown"
        self.assertEqual(
            self.session.execute(species_completions(key)).scalars().all(),
            [],
        )
        key = ""
        self.assertEqual(
            len(self.session.execute(species_completions(key)).all()),
            len(self.session.execute(select(Species)).all()),
        )

        key = "Maxillaria × general"
        sp5 = self.session.get(Species, 10)
        sp6 = self.session.get(Species, 11)
        # self.assertIn(self.sp4, completion(key).all())
        self.assertCountEqual(
            self.session.execute(species_completions(key)).scalars().all(),
            [self.sp4, sp5, sp6],
        )

        key = "+ Crataegomespilus dardarii"
        self.assertCountEqual(
            self.session.execute(species_completions(key)).scalars().all(),
            [self.sp5],
        )

        key = "Maxillaria s. str variabilis"
        self.assertCountEqual(
            [
                i.id
                for i in self.session.execute(
                    species_completions(key)
                ).scalars()
            ],
            [1],
        )

        key = "Maxillaria variabilis"
        self.assertCountEqual(
            [
                i.id
                for i in self.session.execute(
                    species_completions(key)
                ).scalars()
            ],
            [1],
        )

        key = "Cyn 'DT"
        self.assertCountEqual(
            [
                i.id
                for i in self.session.execute(
                    species_completions(key)
                ).scalars()
            ],
            [27],
        )

        key = "Cyn 'Tif"
        self.assertCountEqual(
            [
                i.id
                for i in self.session.execute(
                    species_completions(key)
                ).scalars()
            ],
            [27],
        )


class InfraspRowTests(BaubleTestCase):
    def test_init_new(self):
        grid = Gtk.Grid()
        row = InfraspRow(Species(), grid, 1)

        self.assertIsInstance(grid.get_child_at(0, 1), Gtk.ComboBoxText)
        self.assertIsInstance(grid.get_child_at(1, 1), Gtk.Entry)
        self.assertIsInstance(grid.get_child_at(2, 1), Gtk.Entry)
        self.assertIsInstance(grid.get_child_at(3, 1), Gtk.Button)
        self.assertIsNone(get_widget_value(grid.get_child_at(0, 1)))
        self.assertEqual(grid.get_child_at(1, 1).get_text(), "")
        self.assertEqual(grid.get_child_at(2, 1).get_text(), "")
        self.assertEqual(len(row.problems), 1)
        self.assertTrue(row.has_problem(row.epithet_entry))

        row.destroy()

    def test_init_row(self):
        family = Family(epithet="Testaceae")
        genus = Genus(family=family, epithet="Testia")
        species = Species(
            genus=genus,
            epithet="testii",
            infrasp1_rank="subsp.",
            infrasp1="testiana",
            infrasp1_author="1",
            infrasp2_rank="var.",
            infrasp2="testianis",
            infrasp2_author="2",
            infrasp3_rank="subvar.",
            infrasp3="testiania",
            infrasp3_author="3",
            infrasp4_rank="f.",
            infrasp4="varigata",
            infrasp4_author="L.",
        )
        self.session.add(species)
        self.session.commit()
        grid = Gtk.Grid()
        row = InfraspRow(species, grid, 1)

        self.assertIsInstance(grid.get_child_at(0, 1), Gtk.ComboBoxText)
        self.assertIsInstance(grid.get_child_at(1, 1), Gtk.Entry)
        self.assertIsInstance(grid.get_child_at(2, 1), Gtk.Entry)
        self.assertIsInstance(grid.get_child_at(3, 1), Gtk.Button)
        self.assertEqual(get_widget_value(grid.get_child_at(0, 1)), "subsp.")
        self.assertEqual(grid.get_child_at(1, 1).get_text(), "testiana")
        self.assertEqual(grid.get_child_at(2, 1).get_text(), "1")
        self.assertEqual(row.problems, set())
        self.assertEqual(row.row, 1)

        row.destroy()
        row = InfraspRow(species, grid, 2)

        self.assertIsInstance(grid.get_child_at(0, 2), Gtk.ComboBoxText)
        self.assertIsInstance(grid.get_child_at(1, 2), Gtk.Entry)
        self.assertIsInstance(grid.get_child_at(2, 2), Gtk.Entry)
        self.assertIsInstance(grid.get_child_at(3, 2), Gtk.Button)
        self.assertEqual(get_widget_value(grid.get_child_at(0, 2)), "var.")
        self.assertEqual(grid.get_child_at(1, 2).get_text(), "testianis")
        self.assertEqual(grid.get_child_at(2, 2).get_text(), "2")
        self.assertEqual(row.problems, set())
        self.assertEqual(row.row, 2)

        row.destroy()
        row = InfraspRow(species, grid, 3)

        self.assertIsInstance(grid.get_child_at(0, 3), Gtk.ComboBoxText)
        self.assertIsInstance(grid.get_child_at(1, 3), Gtk.Entry)
        self.assertIsInstance(grid.get_child_at(2, 3), Gtk.Entry)
        self.assertIsInstance(grid.get_child_at(3, 3), Gtk.Button)
        self.assertEqual(get_widget_value(grid.get_child_at(0, 3)), "subvar.")
        self.assertEqual(grid.get_child_at(1, 3).get_text(), "testiania")
        self.assertEqual(grid.get_child_at(2, 3).get_text(), "3")
        self.assertEqual(row.problems, set())
        self.assertEqual(row.row, 3)

        row.destroy()
        row = InfraspRow(species, grid, 4)

        self.assertIsInstance(grid.get_child_at(0, 4), Gtk.ComboBoxText)
        self.assertIsInstance(grid.get_child_at(1, 4), Gtk.Entry)
        self.assertIsInstance(grid.get_child_at(2, 4), Gtk.Entry)
        self.assertIsInstance(grid.get_child_at(3, 4), Gtk.Button)
        self.assertEqual(get_widget_value(grid.get_child_at(0, 4)), "f.")
        self.assertEqual(grid.get_child_at(1, 4).get_text(), "varigata")
        self.assertEqual(grid.get_child_at(2, 4).get_text(), "L.")
        self.assertEqual(row.problems, set())
        self.assertEqual(row.row, 4)

        row.destroy()

    def test_remove_clicked_signals(self):
        family = Family(epithet="Testaceae")
        genus = Genus(family=family, epithet="Testia")
        species = Species(
            genus=genus,
            epithet="testii",
            infrasp1_rank="subsp.",
            infrasp1="testiana",
            infrasp1_author="L.",
        )
        self.session.add(species)
        self.session.commit()
        grid = Gtk.Grid()
        row = InfraspRow(species, grid, 1)
        self.assertFalse(row.in_destruction())
        mock_remove_handler = mock.Mock()
        row.connect("row-removed", mock_remove_handler)
        mock_destroy_handler = mock.Mock()
        row.connect("destroy", mock_destroy_handler)

        row.remove_button.clicked()

        mock_remove_handler.assert_called_once()
        mock_destroy_handler.assert_called_once()

    def test_combo_changed_signals(self):
        family = Family(epithet="Testaceae")
        genus = Genus(family=family, epithet="Testia")
        species = Species(
            genus=genus,
            epithet="testii",
            infrasp1_rank="subsp.",
            infrasp1="testiana",
            infrasp1_author="L.",
        )
        self.session.add(species)
        self.session.commit()
        grid = Gtk.Grid()
        row = InfraspRow(species, grid, 1)
        mock_handler = mock.Mock()
        row.connect("rank_changed", mock_handler)

        set_widget_value(row.rank_combo, "var.")

        mock_handler.assert_called_once()

        row.destroy()

    def test_any_change_signals(self):
        family = Family(epithet="Testaceae")
        genus = Genus(family=family, epithet="Testia")
        species = Species(
            genus=genus,
            epithet="testii",
            infrasp1_rank="subsp.",
            infrasp1="testiana",
            infrasp1_author="L.",
        )
        self.session.add(species)
        self.session.commit()
        grid = Gtk.Grid()
        row = InfraspRow(species, grid, 1)
        mock_handler = mock.Mock()
        row.connect("changed", mock_handler)

        set_widget_value(row.rank_combo, "var.")

        mock_handler.assert_called_once()

        mock_handler.reset_mock()
        row.epithet_entry.set_text("foo")

        mock_handler.assert_called_once()

        mock_handler.reset_mock()
        row.author_entry.set_text("bar")

        mock_handler.assert_called_once()

        mock_handler.reset_mock()

        row.destroy()

    def test_refresh(self):
        family = Family(epithet="Testaceae")
        genus = Genus(family=family, epithet="Testia")
        species = Species(
            genus=genus,
            epithet="testii",
            infrasp1_rank="subsp.",
            infrasp1="testiana",
            infrasp1_author="1",
            infrasp2_rank="var.",
            infrasp2="testianis",
            infrasp2_author="2",
            infrasp3_rank="subvar.",
            infrasp3="testiania",
            infrasp3_author="3",
            infrasp4_rank="f.",
            infrasp4="varigata",
            infrasp4_author="L.",
        )
        self.session.add(species)
        self.session.commit()
        grid = Gtk.Grid()
        row = InfraspRow(species, grid, 3)
        liststore = row.rank_combo.get_model()
        self.assertEqual(len(liststore), 4)
        grid.remove_row(2)
        self.assertEqual(
            str(species),
            "Testia testii "
            "subsp. testiana "
            "var. testianis "
            "subvar. testiania "
            "f. varigata",
        )
        self.assertEqual(row.row, 2)
        mock_handler = mock.Mock()
        row.connect("changed", mock_handler)
        row.refresh()

        mock_handler.assert_called_once()
        self.assertEqual(len(liststore), 5)
        self.assertEqual(
            str(species),
            "Testia testii "
            "subsp. testiana "
            "subvar. testiania "
            "subvar. testiania "  # not legit, no presenter to reset others
            "f. varigata",
        )

        row.destroy()

    def test_refresh_rank_combo(self):
        grid = Gtk.Grid()
        row = InfraspRow(Species(), grid, 1)
        liststore = row.rank_combo.get_model()
        mock_handler = mock.Mock()
        row.connect("changed", mock_handler)
        row.refresh_rank_combo()
        # no rank doesn't emit
        mock_handler.assert_not_called()
        self.assertEqual(len(liststore), 6)
        row.destroy()

        family = Family(epithet="Testaceae")
        genus = Genus(family=family, epithet="Testia")
        species = Species(
            genus=genus,
            epithet="testii",
            infrasp1_rank="subsp.",
            infrasp1="testiana",
            infrasp1_author="1",
            infrasp2_rank="var.",
            infrasp2="testianis",
            infrasp2_author="2",
            infrasp3_rank="subvar.",
            infrasp3="testiania",
            infrasp3_author="3",
            infrasp4_rank="f.",
            infrasp4="varigata",
            infrasp4_author="L.",
        )
        self.session.add(species)
        self.session.commit()
        grid = Gtk.Grid()
        row = InfraspRow(species, grid, 1)
        liststore = row.rank_combo.get_model()

        self.assertEqual(len(liststore), 6)

        row.destroy()

        row = InfraspRow(species, grid, 4)
        liststore = row.rank_combo.get_model()
        self.assertEqual(len(liststore), 3)
        mock_handler = mock.Mock()
        row.connect("changed", mock_handler)
        row.refresh_rank_combo()

        mock_handler.assert_called_once()

        row.destroy()

    def test_set_problem(self):
        family = Family(epithet="Testaceae")
        genus = Genus(family=family, epithet="Testia")
        species = Species(
            genus=genus,
            epithet="testii",
            infrasp1_rank="subsp.",
            infrasp1="testiana",
            infrasp1_author="L.",
        )
        self.session.add(species)
        self.session.commit()
        grid = Gtk.Grid()
        row = InfraspRow(species, grid, 1)
        self.assertEqual(row.problems, set())

        row.set_problem("test")

        self.assertCountEqual(
            row.problems,
            {
                ("test", row.rank_combo),
                ("test", row.epithet_entry),
                ("test", row.author_entry),
            },
        )
        row.remove_problem("test", None)
        self.assertEqual(row.problems, set())
        species.infrasp1_author = None

        row.set_problem("test")

        self.assertCountEqual(
            row.problems,
            {
                ("test", row.rank_combo),
                ("test", row.epithet_entry),
            },
        )

        row.destroy()


class InfraspecificPresenterTests(BaubleTestCase):
    def test_init_new(self):
        presenter = InfraspecificPresenter()

        presenter.init(Species())

        self.assertEqual(presenter.rows, [])
        self.assertTrue(presenter.can_commit)
        self.assertTrue(presenter.add_button.get_sensitive())

        presenter.destroy()

    def test_init_existing(self):
        family = Family(epithet="Testaceae")
        genus = Genus(family=family, epithet="Testia")
        species = Species(
            genus=genus,
            epithet="testii",
            infrasp1_rank="subsp.",
            infrasp1="testiana",
            infrasp1_author="1",
            infrasp2_rank="var.",
            infrasp2="testianis",
            infrasp2_author="2",
            infrasp3_rank="subvar.",
            infrasp3="testiania",
            infrasp3_author="3",
            infrasp4_rank="f.",
            infrasp4="varigata",
            infrasp4_author="L.",
        )
        presenter = InfraspecificPresenter()

        presenter.init(species)

        self.assertEqual(len(presenter.rows), 4)
        self.assertTrue(presenter.can_commit)
        self.assertFalse(presenter.add_button.get_sensitive())

        presenter.destroy()

    def test_add_row(self):
        presenter = InfraspecificPresenter()
        presenter.init(Species())

        presenter.add_button.clicked()

        self.assertEqual(len(presenter.rows), 1)
        self.assertFalse(presenter.can_commit)
        self.assertTrue(presenter.add_button.get_sensitive())

        presenter.add_button.clicked()

        self.assertEqual(len(presenter.rows), 2)
        self.assertFalse(presenter.can_commit)
        self.assertTrue(presenter.add_button.get_sensitive())

        presenter.add_button.clicked()

        self.assertEqual(len(presenter.rows), 3)
        self.assertFalse(presenter.can_commit)
        self.assertTrue(presenter.add_button.get_sensitive())

        presenter.add_button.clicked()

        self.assertEqual(len(presenter.rows), 4)
        self.assertFalse(presenter.can_commit)
        self.assertFalse(presenter.add_button.get_sensitive())

        presenter.destroy()

    def test_row_removed(self):
        family = Family(epithet="Testaceae")
        genus = Genus(family=family, epithet="Testia")
        species = Species(
            genus=genus,
            epithet="testii",
            infrasp1_rank="subsp.",
            infrasp1="testiana",
            infrasp1_author="1",
            infrasp2_rank="var.",
            infrasp2="testianis",
            infrasp2_author="2",
            infrasp3_rank="subvar.",
            infrasp3="testiania",
            infrasp3_author="3",
            infrasp4_rank="f.",
            infrasp4="varigata",
            infrasp4_author="L.",
        )
        presenter = InfraspecificPresenter()
        presenter.init(species)
        self.assertEqual(len(presenter.rows), 4)
        self.assertTrue(presenter.can_commit)
        self.assertFalse(presenter.add_button.get_sensitive())
        self.assertEqual(
            str(species),
            "Testia testii "
            "subsp. testiana "
            "var. testianis "
            "subvar. testiania "
            "f. varigata",
        )
        mock_handler = mock.Mock()
        presenter.connect("changed", mock_handler)

        presenter.rows[0].remove_button.emit("clicked")

        mock_handler.assert_called_once()
        self.assertEqual(
            str(species),
            "Testia testii "
            "var. testianis "
            "subvar. testiania "
            "f. varigata",
        )
        self.assertEqual(len(presenter.rows), 3)
        self.assertEqual(presenter.rows[0].row, 1)
        self.assertEqual(presenter.rows[1].row, 2)
        self.assertEqual(presenter.rows[2].row, 3)
        self.assertEqual(len(presenter.rows[0].rank_combo.get_model()), 6)
        self.assertEqual(len(presenter.rows[1].rank_combo.get_model()), 4)
        self.assertEqual(len(presenter.rows[2].rank_combo.get_model()), 3)

        presenter.destroy()

    def test_clear(self):
        family = Family(epithet="Testaceae")
        genus = Genus(family=family, epithet="Testia")
        species = Species(
            genus=genus,
            epithet="testii",
            infrasp1_rank="subsp.",
            infrasp1="testiana",
            infrasp1_author="1",
            infrasp2_rank="var.",
            infrasp2="testianis",
            infrasp2_author="2",
            infrasp3_rank="subvar.",
            infrasp3="testiania",
            infrasp3_author="3",
            infrasp4_rank="f.",
            infrasp4="varigata",
            infrasp4_author="L.",
        )
        presenter = InfraspecificPresenter()
        presenter.init(species)

        presenter.clear()

        self.assertEqual(str(species), "Testia testii")
        self.assertEqual(len(presenter.rows), 0)

        presenter.destroy()

    def test_set_unset_problem(self):
        family = Family(epithet="Testaceae")
        genus = Genus(family=family, epithet="Testia")
        species = Species(
            genus=genus,
            epithet="testii",
            infrasp1_rank="subsp.",
            infrasp1="testiana",
            infrasp2_rank="var.",
            infrasp2="testianis",
            infrasp2_author="2",
        )
        presenter = InfraspecificPresenter()
        presenter.init(species)

        presenter.set_problem("test")

        self.assertFalse(presenter.can_commit)
        self.assertEqual(len(presenter.rows[0].problems), 2)
        self.assertEqual(len(presenter.rows[1].problems), 3)

        presenter.unset_problem("test")

        self.assertTrue(presenter.can_commit)
        self.assertEqual(len(presenter.rows[0].problems), 0)
        self.assertEqual(len(presenter.rows[1].problems), 0)

        presenter.destroy()

    def test_row_changed(self):
        family = Family(epithet="Testaceae")
        genus = Genus(family=family, epithet="Testia")
        species = Species(
            genus=genus,
            epithet="testii",
            infrasp1_rank="subsp.",
            infrasp1="testiana",
            infrasp2_rank="var.",
            infrasp2="testianis",
            infrasp2_author="2",
        )
        presenter = InfraspecificPresenter()
        presenter.init(species)
        mock_handler = mock.Mock()
        presenter.connect("changed", mock_handler)

        presenter.rows[0].emit("changed")

        mock_handler.assert_called_once()

        mock_handler.reset_mock()
        presenter.block_change = True

        presenter.rows[0].emit("changed")

        mock_handler.assert_not_called()

        presenter.destroy()

    def test_on_rank_changed_cascades(self):
        family = Family(epithet="Testaceae")
        genus = Genus(family=family, epithet="Testia")
        species = Species(
            genus=genus,
            epithet="testii",
            infrasp1_rank="subsp.",
            infrasp1="testiana",
            infrasp1_author="1",
            infrasp2_rank="subvar.",
            infrasp2="testianis",
            infrasp2_author="2",
            infrasp3_rank="f.",
            infrasp3="testiania",
            infrasp3_author="3",
            infrasp4_rank="subf.",
            infrasp4="varigata",
            infrasp4_author="L.",
        )
        presenter = InfraspecificPresenter()
        presenter.init(species)
        mock_handler = mock.Mock()
        presenter.connect("changed", mock_handler)
        self.assertEqual(len(presenter.rows[0].rank_combo.get_model()), 6)
        self.assertEqual(len(presenter.rows[1].rank_combo.get_model()), 5)
        self.assertEqual(len(presenter.rows[2].rank_combo.get_model()), 3)
        self.assertEqual(len(presenter.rows[3].rank_combo.get_model()), 2)

        set_widget_value(presenter.rows[0].rank_combo, "var.")

        mock_handler.asset_called_once()
        self.assertEqual(len(presenter.rows[0].rank_combo.get_model()), 6)
        self.assertEqual(len(presenter.rows[1].rank_combo.get_model()), 4)
        self.assertEqual(len(presenter.rows[2].rank_combo.get_model()), 3)
        self.assertEqual(len(presenter.rows[3].rank_combo.get_model()), 2)

        mock_handler.reset_mock()
        set_widget_value(presenter.rows[0].rank_combo, "subvar.")

        mock_handler.asset_called_once()
        self.assertEqual(len(presenter.rows[0].rank_combo.get_model()), 6)
        self.assertEqual(len(presenter.rows[1].rank_combo.get_model()), 3)
        self.assertEqual(get_widget_value(presenter.rows[1].rank_combo), None)
        self.assertEqual(len(presenter.rows[2].rank_combo.get_model()), 0)
        self.assertEqual(get_widget_value(presenter.rows[1].rank_combo), None)
        self.assertEqual(len(presenter.rows[3].rank_combo.get_model()), 0)
        self.assertEqual(get_widget_value(presenter.rows[1].rank_combo), None)

        presenter.destroy()

    def test_no_epithet_can_commit_is_false(self):
        family = Family(epithet="Testaceae")
        genus = Genus(family=family, epithet="Testia")
        species = Species(
            genus=genus,
            epithet="testii",
            infrasp1_rank="subsp.",
            infrasp1="testiana",
            infrasp1_author="1",
            infrasp2_rank="subvar.",
            infrasp2="testianis",
            infrasp2_author="2",
        )
        presenter = InfraspecificPresenter()
        presenter.init(species)
        mock_handler = mock.Mock()
        presenter.connect("changed", mock_handler)
        presenter.rows[0].epithet_entry.set_text("")

        self.assertEqual(len(presenter.rows[0].problems), 1)
        self.assertFalse(presenter.can_commit)

        presenter.destroy()


class VernacularNamePresenterTests(BaubleTestCase):
    def test_init_new(self):
        overlay = Gtk.Overlay()
        box = Gtk.Box()
        overlay.add(box)
        revealer = Gtk.Revealer()
        overlay.add_overlay(revealer)
        presenter = VernacularNamePresenter()
        mock_handler = mock.Mock()
        presenter.connect("changed", mock_handler)
        presenter.init(Species(), self.session, revealer)
        update_gui()

        self.assertEqual(len(presenter.list_store), 0)
        self.assertIsNone(revealer.get_child())
        self.assertFalse(presenter.remove_button.get_sensitive())
        self.assertTrue(presenter.can_commit)
        self.assertEqual(len(presenter.handlers), 5)
        mock_handler.assert_not_called()

        presenter.destroy()

    def test_init_existing(self):
        family = Family(family="Myrtaceae")
        genus = Genus(family=family, genus="Syzygium")
        species = Species(genus=genus, epithet="australe")
        species.vernacular_names.append(VernacularName(name="Brush Cherry"))
        species.vernacular_names.append(VernacularName(name="Creek Satinash"))
        species.default_vernacular_name = VernacularName(name="Lilly Pilly")
        self.session.add(species)
        self.session.commit()
        overlay = Gtk.Overlay()
        box = Gtk.Box()
        overlay.add(box)
        revealer = Gtk.Revealer()
        overlay.add_overlay(revealer)
        presenter = VernacularNamePresenter()
        mock_handler = mock.Mock()
        presenter.connect("changed", mock_handler)
        presenter.init(species, self.session, revealer)
        update_gui()

        self.assertEqual(len(presenter.list_store), 3)
        self.assertIsNone(revealer.get_child())
        self.assertFalse(presenter.remove_button.get_sensitive())
        self.assertTrue(presenter.can_commit)
        self.assertEqual(len(presenter.handlers), 5)
        mock_handler.assert_not_called()

        presenter.destroy()

    def test_init_existing_no_default(self):
        family = Family(family="Myrtaceae")
        genus = Genus(family=family, genus="Syzygium")
        species = Species(genus=genus, epithet="australe")
        species.vernacular_names.append(VernacularName(name="Brush Cherry"))
        species.vernacular_names.append(VernacularName(name="Creek Satinash"))
        species.vernacular_names.append(VernacularName(name="Lilly Pilly"))
        self.session.add(species)
        self.session.commit()
        overlay = Gtk.Overlay()
        box = Gtk.Box()
        overlay.add(box)
        revealer = Gtk.Revealer()
        overlay.add_overlay(revealer)
        presenter = VernacularNamePresenter()
        mock_handler = mock.Mock()
        presenter.connect("changed", mock_handler)
        presenter.init(species, self.session, revealer)
        update_gui()
        child = revealer.get_child()

        self.assertEqual(len(presenter.list_store), 3)
        self.assertIsInstance(child, MessageBox)
        self.assertTrue(revealer.get_reveal_child())
        self.assertFalse(presenter.remove_button.get_sensitive())
        self.assertTrue(presenter.can_commit)
        self.assertEqual(species.default_vernacular_name.name, "Brush Cherry")
        self.assertEqual(len(presenter.handlers), 5)
        mock_handler.assert_not_called()

        child.get_children()[0].get_children()[0].emit("clicked")
        self.assertFalse(revealer.get_reveal_child())
        presenter.destroy()

    def test__name_edit_start(self):
        overlay = Gtk.Overlay()
        box = Gtk.Box()
        overlay.add(box)
        revealer = Gtk.Revealer()
        overlay.add_overlay(revealer)
        presenter = VernacularNamePresenter()
        presenter.init(Species(), self.session, revealer)
        self.assertEqual(len(presenter.handlers), 5)
        update_gui()
        entry = Gtk.Entry()
        presenter.name_cell.emit(
            "editing-started",
            entry,
            Gtk.TreePath(0),
        )

        self.assertEqual(len(presenter.handlers), 6)

        presenter.destroy()

    def test__lang_edit_start(self):
        overlay = Gtk.Overlay()
        box = Gtk.Box()
        overlay.add(box)
        revealer = Gtk.Revealer()
        overlay.add_overlay(revealer)
        presenter = VernacularNamePresenter()
        presenter.init(Species(), self.session, revealer)
        update_gui()
        entry = Gtk.Entry()
        presenter.lang_cell.emit(
            "editing-started",
            entry,
            Gtk.TreePath(1),
        )

        self.assertIsNotNone(entry.get_completion())

        presenter.destroy()

    def test_on_cursor_changed(self):
        family = Family(family="Myrtaceae")
        genus = Genus(family=family, genus="Syzygium")
        species = Species(genus=genus, epithet="australe")
        species.vernacular_names.append(VernacularName(name="Brush Cherry"))
        species.vernacular_names.append(VernacularName(name="Creek Satinash"))
        species.default_vernacular_name = VernacularName(name="Lilly Pilly")
        self.session.add(species)
        self.session.commit()
        overlay = Gtk.Overlay()
        box = Gtk.Box()
        overlay.add(box)
        revealer = Gtk.Revealer()
        overlay.add_overlay(revealer)
        presenter = VernacularNamePresenter()
        mock_handler = mock.Mock()
        presenter.connect("changed", mock_handler)
        presenter.init(species, self.session, revealer)
        presenter.treeview.set_cursor(Gtk.TreePath(0))

        self.assertTrue(presenter.remove_button.get_sensitive())
        self.assertEqual(len(presenter.handlers), 5)

        presenter.destroy()

    def test_on_remove_clicked_default_new(self):
        family = Family(family="Myrtaceae")
        genus = Genus(family=family, genus="Syzygium")
        species = Species(genus=genus, epithet="australe")
        species.default_vernacular_name = VernacularName(name="Lilly Pilly")
        species.vernacular_names.append(VernacularName(name="Brush Cherry"))
        species.vernacular_names.append(VernacularName(name="Creek Satinash"))
        self.session.add(species)
        overlay = Gtk.Overlay()
        box = Gtk.Box()
        overlay.add(box)
        revealer = Gtk.Revealer()
        overlay.add_overlay(revealer)
        presenter = VernacularNamePresenter()
        mock_handler = mock.Mock()
        presenter.connect("changed", mock_handler)
        presenter.init(species, self.session, revealer)
        presenter.treeview.set_cursor(Gtk.TreePath(0))
        self.assertEqual(len(species.vernacular_names), 3)
        presenter.remove_button.clicked()

        self.assertEqual(len(species.vernacular_names), 2)
        self.assertEqual(species.default_vernacular_name.name, "Brush Cherry")

        presenter.destroy()

    @mock.patch("bauble.ui.dialogs.yes_no_dialog")
    def test_on_remove_clicked_existing(self, mock_dialog):
        family = Family(family="Myrtaceae")
        genus = Genus(family=family, genus="Syzygium")
        species = Species(genus=genus, epithet="australe")
        species.vernacular_names.append(VernacularName(name="Brush Cherry"))
        species.vernacular_names.append(VernacularName(name="Creek Satinash"))
        species.default_vernacular_name = VernacularName(name="Lilly Pilly")
        self.session.add(species)
        self.session.commit()
        overlay = Gtk.Overlay()
        box = Gtk.Box()
        overlay.add(box)
        revealer = Gtk.Revealer()
        overlay.add_overlay(revealer)
        presenter = VernacularNamePresenter()
        window = Gtk.Window()
        window.add(presenter)
        mock_handler = mock.Mock()
        presenter.connect("changed", mock_handler)
        presenter.init(species, self.session, revealer)
        presenter.treeview.set_cursor(Gtk.TreePath(0))
        self.assertEqual(len(species.vernacular_names), 3)
        # reject
        mock_dialog.return_value = False
        presenter.remove_button.clicked()

        mock_dialog.assert_called_once()
        self.assertIs(mock_dialog.call_args.kwargs["parent"], window)
        self.assertEqual(len(species.vernacular_names), 3)
        self.assertEqual(species.default_vernacular_name.name, "Lilly Pilly")

        mock_dialog.reset_mock()
        # accept
        mock_dialog.return_value = True
        presenter.remove_button.clicked()

        mock_dialog.assert_called_once()
        self.assertEqual(len(species.vernacular_names), 2)
        self.assertEqual(species.default_vernacular_name.name, "Lilly Pilly")

        presenter.destroy()

    def test_on_add_clicked_new(self):
        species = Species()
        overlay = Gtk.Overlay()
        box = Gtk.Box()
        overlay.add(box)
        revealer = Gtk.Revealer()
        overlay.add_overlay(revealer)
        presenter = VernacularNamePresenter()
        mock_handler = mock.Mock()
        presenter.connect("changed", mock_handler)
        presenter.init(species, self.session, revealer)
        presenter.treeview.set_cursor(Gtk.TreePath(0))
        self.assertEqual(len(species.vernacular_names), 0)
        presenter.add_button.clicked()

        self.assertEqual(len(species.vernacular_names), 1)
        self.assertIsNotNone(species.default_vernacular_name)

        presenter.destroy()

    def test_on_vernacular_name_paste(self):
        # title_case default
        entry = Gtk.Entry()
        entry.set_text("spam-eggs ham")
        VernacularNamePresenter.on_vernacular_name_paste(entry)
        update_gui()

        self.assertEqual(entry.get_text(), "Spam-eggs Ham")

        entry.set_text("spam, eggs and ham on toast")
        VernacularNamePresenter.on_vernacular_name_paste(entry)
        update_gui()

        self.assertEqual(entry.get_text(), "Spam, Eggs and Ham on Toast")

        # disabled
        entry.set_text(" spam-eggs\n ham ")
        prefs.prefs[CAPITALISE_VNAMES_ON_PASTE_PREF_KEY] = "off"
        VernacularNamePresenter.on_vernacular_name_paste(entry)
        update_gui()

        self.assertEqual(entry.get_text(), " spam-eggs\n ham ")

        # capwords
        entry.set_text(" spam, eggs and   ham\n on toast ")
        prefs.prefs[CAPITALISE_VNAMES_ON_PASTE_PREF_KEY] = "capwords"
        VernacularNamePresenter.on_vernacular_name_paste(entry)
        update_gui()

        self.assertEqual(entry.get_text(), "Spam, Eggs And Ham On Toast")

        # title_case set
        prefs.prefs[CAPITALISE_VNAMES_ON_PASTE_PREF_KEY] = "title"
        entry.set_text(" spam, eggs and \n ham on ")
        VernacularNamePresenter.on_vernacular_name_paste(entry)
        update_gui()

        self.assertEqual(entry.get_text(), "Spam, Eggs and Ham On")

        entry.set_text(" spam ")
        VernacularNamePresenter.on_vernacular_name_paste(entry)
        update_gui()

        self.assertEqual(entry.get_text(), "Spam")

        entry.set_text("spam and")
        VernacularNamePresenter.on_vernacular_name_paste(entry)
        update_gui()

        self.assertEqual(entry.get_text(), "Spam And")

        entry.set_text("and spam")
        VernacularNamePresenter.on_vernacular_name_paste(entry)
        update_gui()

        self.assertEqual(entry.get_text(), "And Spam")

        entry.set_text("if")
        VernacularNamePresenter.on_vernacular_name_paste(entry)
        update_gui()

        self.assertEqual(entry.get_text(), "If")

    def test_on_default_toggled(self):
        family = Family(family="family")
        genus = Genus(genus="genus", family=family)
        species = Species(genus=genus, epithet="sp")
        name = VernacularName(name="Test Name", language="EN")
        species.vernacular_names.append(name)
        species.default_vernacular_name = name
        name2 = VernacularName(name="Another Name", language="XY")
        species.vernacular_names.append(name2)
        self.session.add(species)
        self.session.commit()

        overlay = Gtk.Overlay()
        box = Gtk.Box()
        overlay.add(box)
        revealer = Gtk.Revealer()
        overlay.add_overlay(revealer)
        presenter = VernacularNamePresenter()
        presenter.init(species, self.session, revealer)
        presenter.treeview.set_cursor(0)

        self.assertEqual(len(species.vernacular_names), 2)
        self.assertEqual(species.default_vernacular_name, name)

        mock_cell = mock.Mock()
        mock_cell.get_active.return_value = False
        mock_path = 1
        presenter.on_default_toggled(mock_cell, mock_path)

        self.assertEqual(species.default_vernacular_name, name2)

        # switch back
        mock_path = 0
        presenter.on_default_toggled(mock_cell, mock_path)

        self.assertEqual(species.default_vernacular_name, name)

        self.assertEqual(len(species.vernacular_names), 2)
        self.assertTrue(presenter.can_commit)

        presenter.destroy()

    def test_on_cell_edited(self):
        family = Family(family="family")
        genus = Genus(genus="genus", family=family)
        species = Species(genus=genus, epithet="sp")
        name = VernacularName(name="Test Name", language="EN")
        species.vernacular_names.append(name)
        species.default_vernacular_name = name
        self.session.add(species)
        self.session.commit()

        overlay = Gtk.Overlay()
        box = Gtk.Box()
        overlay.add(box)
        revealer = Gtk.Revealer()
        overlay.add_overlay(revealer)
        presenter = VernacularNamePresenter()
        mock_handler = mock.Mock()
        presenter.connect("changed", mock_handler)
        presenter.init(species, self.session, revealer)

        self.assertEqual(len(species.vernacular_names), 1)
        self.assertEqual(species.default_vernacular_name, name)

        # check is stripped
        presenter.on_cell_edited(None, 0, "New name  \n", "name")
        presenter.on_cell_edited(None, 0, "XYZ", "language")

        mock_handler.assert_called()
        self.assertEqual(species.default_vernacular_name.name, "New name")
        self.assertEqual(species.default_vernacular_name.language, "XYZ")
        self.assertTrue(presenter.can_commit)

        # no change returns
        mock_handler.reset_mock()
        with mock.patch.object(presenter, "check_problems") as mock_check:
            presenter.on_cell_edited(None, 0, "XYZ", "language")

            mock_check.assert_not_called()
            mock_handler.assert_not_called()

        # setting name empty adds problem and unselects
        # (also tests check_problems)
        self.assertEqual(presenter.problems, set())
        presenter.on_cell_edited(None, 0, "", "name")

        self.assertEqual(
            presenter.problems,
            {(presenter.PROBLEM_EMPTY, presenter)},
        )
        self.assertIsNone(presenter.treeview.get_selection().get_selected()[1])

        presenter.destroy()

    def test_add_remove_problem(self):
        overlay = Gtk.Overlay()
        box = Gtk.Box()
        overlay.add(box)
        revealer = Gtk.Revealer()
        overlay.add_overlay(revealer)
        presenter = VernacularNamePresenter()
        presenter.add_problem("test", presenter)

        self.assertEqual(presenter.problems, {("test", presenter)})
        self.assertTrue(presenter.get_style_context().has_class("problem"))

        # no 'foo' problem doesn't fail
        presenter.remove_problem("foo", presenter)

        self.assertEqual(presenter.problems, {("test", presenter)})
        self.assertTrue(presenter.get_style_context().has_class("problem"))

        presenter.remove_problem("test", presenter)

        self.assertEqual(presenter.problems, set())
        self.assertFalse(presenter.get_style_context().has_class("problem"))

    def test_generic_data_func(self):
        family = Family(family="family")
        genus = Genus(genus="genus", family=family)
        species = Species(genus=genus, epithet="sp")
        name = VernacularName(name="Test Name", language="EN")
        species.vernacular_names.append(name)
        species.default_vernacular_name = name
        self.session.add(species)
        self.session.commit()
        name2 = VernacularName(name="Another Name", language="XY")
        species.vernacular_names.append(name2)

        overlay = Gtk.Overlay()
        box = Gtk.Box()
        overlay.add(box)
        revealer = Gtk.Revealer()
        overlay.add_overlay(revealer)
        presenter = VernacularNamePresenter()
        presenter.init(species, self.session, revealer)

        mock_cell = mock.Mock()
        mock_model = [[name]]

        # with existing vernacular
        presenter.generic_data_func(None, mock_cell, mock_model, 0, "name")
        self.assertIn(
            ("text", name.name),
            [i.args for i in mock_cell.set_property.call_args_list],
        )
        self.assertIn(
            ("background", None),
            [i.args for i in mock_cell.set_property.call_args_list],
        )
        self.assertIn(
            ("foreground", None),
            [i.args for i in mock_cell.set_property.call_args_list],
        )

        mock_cell.reset_mock()
        presenter.generic_data_func(None, mock_cell, mock_model, 0, "language")
        self.assertIn(
            ("text", name.language),
            [i.args for i in mock_cell.set_property.call_args_list],
        )
        self.assertIn(
            ("background", None),
            [i.args for i in mock_cell.set_property.call_args_list],
        )
        self.assertIn(
            ("foreground", None),
            [i.args for i in mock_cell.set_property.call_args_list],
        )

        # with new vernacular
        mock_cell.reset_mock()
        mock_model = [[name2]]
        presenter.generic_data_func(None, mock_cell, mock_model, 0, "name")
        self.assertIn(
            ("text", name2.name),
            [i.args for i in mock_cell.set_property.call_args_list],
        )
        self.assertIn(
            ("background", None),
            [i.args for i in mock_cell.set_property.call_args_list],
        )
        self.assertIn(
            ("foreground", "blue"),
            [i.args for i in mock_cell.set_property.call_args_list],
        )
        # with problems
        name.name = None
        mock_cell.reset_mock()
        mock_model = [[name]]
        presenter.generic_data_func(None, mock_cell, mock_model, 0, "name")
        self.assertIn(
            ("text", name.name),
            [i.args for i in mock_cell.set_property.call_args_list],
        )
        self.assertIn(
            ("foreground", None),
            [i.args for i in mock_cell.set_property.call_args_list],
        )
        self.assertIn(
            ("background", "pink"),
            [i.args for i in mock_cell.set_property.call_args_list],
        )
        # DetachedInstanceError just logs
        name.name = None
        mock_cell.reset_mock()
        mock_cell.set_property.side_effect = DetachedInstanceError
        mock_model = [[name]]
        with self.assertLogs(
            "bauble.plugins.plants.ui.widgets.vernacular", level="DEBUG"
        ) as logs:
            presenter.generic_data_func(None, mock_cell, mock_model, 0, "name")
        self.assertIn("DetachedInstanceError", logs.output[0])
        self.assertNotIn(
            "foreground",
            [i.args[0] for i in mock_cell.set_property.call_args_list],
        )
        self.assertNotIn(
            "background",
            [i.args[0] for i in mock_cell.set_property.call_args_list],
        )

        presenter.destroy()

    def test_default_data_func(self):
        family = Family(family="family")
        genus = Genus(genus="genus", family=family)
        species = Species(genus=genus, epithet="sp")
        name = VernacularName(name="Test Name", language="EN")
        species.vernacular_names.append(name)
        species.default_vernacular_name = name
        self.session.add(species)
        self.session.commit()
        name2 = VernacularName(name="Another Name", language="XY")
        species.vernacular_names.append(name2)

        overlay = Gtk.Overlay()
        box = Gtk.Box()
        overlay.add(box)
        revealer = Gtk.Revealer()
        overlay.add_overlay(revealer)
        presenter = VernacularNamePresenter()
        presenter.init(species, self.session, revealer)

        mock_cell = mock.Mock()
        mock_model = [[name]]

        presenter.default_data_func(None, mock_cell, mock_model, 0, None)

        self.assertIn(
            ("active", True),
            [i.args for i in mock_cell.set_property.call_args_list],
        )

        mock_model = [[name2]]

        presenter.default_data_func(None, mock_cell, mock_model, 0, None)

        self.assertIn(
            ("active", False),
            [i.args for i in mock_cell.set_property.call_args_list],
        )
        # DetachedInstanceError just logs
        name.name = None
        mock_cell.reset_mock()
        mock_cell.set_property.side_effect = DetachedInstanceError
        mock_model = [[name]]
        with self.assertLogs(
            "bauble.plugins.plants.ui.widgets.vernacular", level="DEBUG"
        ) as logs:
            presenter.default_data_func(None, mock_cell, mock_model, 0, None)
        self.assertIn("DetachedInstanceError", logs.output[0])

        presenter.destroy()


class DistributionPresenterTests(BaubleClassTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # setup_plants_data()
        setup_geographies()
        family = Family(family="Myrtaceae")
        genus = Genus(genus="Melaleuca", family=family)
        cls.species = Species(genus=genus, epithet="viminalis")

        cls.session.add(cls.species)
        cls.session.commit()

        cls.qld = cls.session.execute(
            select(Geography).where(Geography.code == "QLD")
        ).scalar()
        cls.nsw = cls.session.execute(
            select(Geography).where(Geography.code == "NSW")
        ).scalar()

    def tearDown(self):
        super().tearDown()
        self.species.distribution = []
        self.session.commit()

    def test_init_new(self):
        presenter = DistributionPresenter()
        presenter.init(Species(), self.session)

        self.assertFalse(presenter.add_button.get_sensitive())
        self.assertEqual(presenter.label.get_text(), "")

        wait_on_threads()
        update_gui()

        self.assertTrue(presenter.add_button.get_sensitive())
        self.assertEqual(presenter.label.get_text(), "")

        presenter.destroy()

    def test_init_existing(self):
        self.species.distribution.append(SpeciesDistribution(geography_id=695))
        self.session.commit()

        presenter = DistributionPresenter()
        presenter.init(self.species, self.session)

        self.assertFalse(presenter.add_button.get_sensitive())
        self.assertEqual(presenter.label.get_text(), "Queensland")

        wait_on_threads()
        update_gui()

        self.assertTrue(presenter.add_button.get_sensitive())
        self.assertEqual(presenter.label.get_text(), "Queensland")

        presenter.destroy()

    def test_refresh_view_long_label_shortens(self):

        for dist in self.session.execute(
            select(Geography).where(Geography.id < 100)
        ).scalars():
            spdist = SpeciesDistribution(geography=dist)
            self.species.distribution.append(spdist)

        self.session.commit()

        presenter = DistributionPresenter()
        presenter.init(self.species, self.session)
        wait_on_threads()
        update_gui()
        text = presenter.label.get_text()
        self.assertEqual(text[-4:], " ...")
        self.assertTrue(490 < len(text) < 510)

        presenter.destroy()

    def test_on_remove_button_pressed(self):
        qld_dist = SpeciesDistribution(geography=self.qld)
        nsw_dist = SpeciesDistribution(geography=self.nsw)
        self.species.distribution.append(qld_dist)
        self.species.distribution.append(nsw_dist)
        self.session.commit()

        presenter = DistributionPresenter()
        presenter.init(self.species, self.session)
        wait_on_threads()
        update_gui()
        presenter.remove_menu_model = mock.Mock()
        presenter.remove_menu = mock.Mock()

        mock_event = mock.Mock(button=1, time=datetime.now().timestamp())
        presenter.on_remove_button_pressed(None, mock_event)

        self.assertEqual(presenter.remove_menu_model.append_item.call_count, 2)
        self.assertEqual(presenter.remove_menu.popup_at_pointer.call_count, 1)

        presenter.destroy()

    def test_on_activate_add_menu_item(self):
        presenter = DistributionPresenter()
        presenter.init(self.species, self.session)
        wait_on_threads()
        update_gui()
        mock_geo = mock.Mock()
        mock_geo.unpack.return_value = self.qld.id
        presenter.on_activate_add_menu_item(None, mock_geo)
        # add twice only adds once
        presenter.on_activate_add_menu_item(None, mock_geo)

        self.assertEqual(
            [dist.geography for dist in self.species.distribution],
            [self.qld],
        )

        mock_geo.unpack.return_value = "99999"
        with self.assertLogs(
            "bauble.plugins.plants.ui.widgets.distribution", level="DEBUG"
        ) as logs:
            presenter.on_activate_add_menu_item(None, mock_geo)

        self.assertIn("Can't find Geography with ID: 99999", logs.output[0])

        presenter.destroy()

    def test_on_activate_remove_menu_item(self):
        qld_dist = SpeciesDistribution(geography=self.qld)
        nsw_dist = SpeciesDistribution(geography=self.nsw)
        self.species.distribution.append(qld_dist)
        self.species.distribution.append(nsw_dist)
        self.session.add(self.species)
        self.session.commit()

        presenter = DistributionPresenter()
        presenter.init(self.species, self.session)
        wait_on_threads()
        update_gui()
        mock_geo = mock.Mock()
        mock_geo.unpack.return_value = self.qld.id
        presenter.on_activate_remove_menu_item(None, mock_geo)
        self.assertEqual(
            [dist.geography for dist in self.species.distribution],
            [self.nsw],
        )

        presenter.destroy()

    def test_on_clear_all(self):
        qld_dist = SpeciesDistribution(geography=self.qld)
        nsw_dist = SpeciesDistribution(geography=self.nsw)
        self.species.distribution.append(qld_dist)
        self.species.distribution.append(nsw_dist)
        self.session.add(self.species)
        self.session.commit()

        presenter = DistributionPresenter()
        presenter.init(self.species, self.session)
        wait_on_threads()
        update_gui()
        presenter.on_clear_all()
        self.assertEqual(self.species.distribution, [])

        presenter.destroy()

    @mock.patch("bauble.ui.dialogs.message_dialog")
    def test_append_dists_from_clipboard_text(self, mock_dialog):
        # haven't split these up as setUp is slow
        presenter = DistributionPresenter()
        presenter.init(self.species, self.session)
        wait_on_threads()
        update_gui()
        # empty str
        txt = ""
        presenter.append_dists_from_text(txt)

        self.assertCountEqual(self.species.distribution, [])

        # junk data (i.e. a mistake)
        txt = "XYZ"
        presenter.append_dists_from_text(txt)

        self.assertCountEqual(self.species.distribution, [])
        mock_dialog.assert_called()
        mock_dialog.reset_mock()

        txt = "<asdf,KJ\nFDkjdsaiwj, <>,{[,127|8.9h\\dafn"
        presenter.append_dists_from_text(txt)

        self.assertCountEqual(self.species.distribution, [])
        mock_dialog.assert_called()
        mock_dialog.reset_mock()

        # test data that almost matches but is a little wrong
        txt = "New Zealand, Lord Howe i., XYZ"
        presenter.append_dists_from_text(txt)

        self.assertCountEqual(self.species.distribution, [])
        mock_dialog.assert_called()
        mock_dialog.reset_mock()

        # test an empty list
        txt = ","
        window = Gtk.Window()  # cover toplevel
        window.add(presenter)
        presenter.append_dists_from_text(txt)

        self.assertCountEqual(self.species.distribution, [])
        mock_dialog.assert_called()
        mock_dialog.reset_mock()
        # none of the above should have added any distribution
        self.assertEqual(self.species.distribution, [])

        # test a single list
        txt = "Australia"
        presenter.append_dists_from_text(txt)
        self.assertCountEqual(
            [i.geography.id for i in self.species.distribution],
            [38],
        )
        mock_dialog.assert_not_called()
        mock_dialog.reset_mock()

        self.species.distribution = []
        # test ambiguous (more than one level, should select highest)
        txt = "Queensland"
        presenter.append_dists_from_text(txt)

        self.assertCountEqual(
            [i.geography.id for i in self.species.distribution],
            [695],
        )
        mock_dialog.assert_not_called()
        mock_dialog.reset_mock()

        self.species.distribution = []
        # test ambiguous item in list with all others lower level
        txt = (
            "Queensland, New South Wales, Victoria, South Australia, "
            "Tasmania, Norfolk Is."
        )
        presenter.append_dists_from_text(txt)

        self.assertCountEqual(
            [i.geography.id for i in self.species.distribution],
            (330, 296, 407, 359, 378, 286),
        )
        mock_dialog.assert_not_called()
        mock_dialog.reset_mock()

        self.species.distribution = []
        # test abreviated to 12 chars
        txt = "New South Wa, Victoria, South Austra, Tasmania, Norfolk Is."
        presenter.append_dists_from_text(txt)

        self.assertCountEqual(
            [i.geography.id for i in self.species.distribution],
            (296, 407, 359, 378, 286),
            [i.geography.name for i in self.species.distribution],
        )
        mock_dialog.assert_not_called()
        mock_dialog.reset_mock()

        self.species.distribution = []
        # test abreviated to 12 chars lowercase
        txt = "new south wa, victoria, south austra, tasmania, norfolk is."
        presenter.append_dists_from_text(txt)

        self.assertCountEqual(
            [i.geography.id for i in self.species.distribution],
            (296, 407, 359, 378, 286),
            [i.geography.name for i in self.species.distribution],
        )
        mock_dialog.assert_not_called()
        mock_dialog.reset_mock()

        self.species.distribution = []
        # test codes
        txt = "NFK, QLD, NWG-PN, NSW-NS"
        presenter.append_dists_from_text(txt)

        self.assertCountEqual(
            [i.geography.id for i in self.species.distribution],
            (286, 330, 691, 689),
            [i.geography.code for i in self.species.distribution],
        )
        mock_dialog.assert_not_called()

        presenter.destroy()

    def test_on_consolidate(self):
        lv2s = self.session.execute(
            select(Geography.id)
            .where(Geography.level == 2)
            .where(Geography.parent_id.in_([1, 5]))
        ).scalars()
        lv3 = self.session.execute(
            select(Geography)
            .where(Geography.level == 3)
            .where(Geography.parent_id.in_(lv2s))
        ).scalars()
        for i in lv3:
            self.species.distribution.append(SpeciesDistribution(geography=i))
        self.session.add(self.species)
        self.session.commit()

        presenter = DistributionPresenter()
        presenter.init(self.species, self.session)
        wait_on_threads()
        update_gui()
        presenter.on_consolidate()
        self.assertCountEqual(
            [i.geography.id for i in self.species.distribution],
            (1, 5),
        )

        presenter.destroy()

    @mock.patch("bauble.plugins.plants.ui.widgets.distribution.get_clipboard")
    def test_on_paste_append(self, mock_clipboard):
        mock_clipboard().wait_for_text.return_value = "Tasmania, Queensland"
        nsw_dist = SpeciesDistribution(geography=self.nsw)
        self.species.distribution.append(nsw_dist)
        self.session.commit()

        presenter = DistributionPresenter()
        presenter.init(self.species, self.session)
        wait_on_threads()
        update_gui()
        presenter.on_paste_append()

        self.assertCountEqual(
            [i.geography.id for i in self.species.distribution],
            [296, 330, 378],
        )

        # test no clipboard doesn't fail
        mock_clipboard.reset_mock()
        mock_clipboard.return_value = None
        presenter.on_paste_append()

        presenter.destroy()

    @mock.patch("bauble.plugins.plants.ui.widgets.distribution.get_clipboard")
    def test_on_paste_replace(self, mock_clipboard):
        mock_clipboard().wait_for_text.return_value = "Tasmania, Queensland"
        nsw_dist = SpeciesDistribution(geography=self.nsw)
        self.species.distribution.append(nsw_dist)
        self.session.add(self.species)
        self.session.commit()

        presenter = DistributionPresenter()
        presenter.init(self.species, self.session)
        wait_on_threads()
        update_gui()
        presenter.on_paste_replace()

        self.assertCountEqual(
            [i.geography.id for i in self.species.distribution],
            [330, 378],
        )

        # test no clipboard doesn't fail
        mock_clipboard.reset_mock()
        mock_clipboard.return_value = None
        presenter.on_paste_replace()

        presenter.destroy()

    @mock.patch("bauble.plugins.plants.ui.widgets.distribution.get_clipboard")
    def test_on_copy(self, mock_clipboard):
        qld_dist = SpeciesDistribution(geography=self.qld)
        nsw_dist = SpeciesDistribution(geography=self.nsw)
        self.species.distribution.append(qld_dist)
        self.species.distribution.append(nsw_dist)
        self.session.add(self.species)
        self.session.commit()

        presenter = DistributionPresenter()
        presenter.init(self.species, self.session)
        wait_on_threads()
        update_gui()
        presenter.on_copy_codes()

        mock_clipboard().set_text.assert_called_with("QLD, NSW", -1)

        mock_clipboard.reset_mock()
        presenter.on_copy_names()

        mock_clipboard().set_text.assert_called_with(
            "Queensland, New South Wales", -1
        )

        # test no clipboard doesn't fail
        mock_clipboard.reset_mock()
        mock_clipboard.return_value = None
        presenter.on_copy_names()
        presenter.on_copy_codes()

        presenter.destroy()


class GeographyMenuTests(BaubleTestCase):
    def test_resets_after_changes(self):
        # start empty
        GeographyMenu.reset()  # incase other tests have already loaded
        menu = GeographyMenu()

        self.assertEqual(menu.geos_ordered, {})
        self.assertEqual(menu._geos_ordered, {})

        # insert
        geo1 = Geography(
            name="EUROPE",
            code="1",
            level=1,
        )
        self.session.add(geo1)
        self.session.commit()
        geo2 = Geography(
            name="Eastern Europe",
            code="14",
            level=2,
            parent_id=geo1.id,
        )
        self.session.add(geo2)
        self.session.commit()

        self.assertEqual(menu._geos_ordered, {})
        self.assertEqual(
            menu.geos_ordered,
            {
                None: [(geo1.id, "EUROPE")],
                geo1.id: [(geo2.id, "Eastern Europe")],
            },
        )
        self.assertEqual(
            menu._geos_ordered,
            {
                None: [(geo1.id, "EUROPE")],
                geo1.id: [(geo2.id, "Eastern Europe")],
            },
        )

        # update
        geo1.name = "Europe"
        self.session.commit()

        self.assertEqual(
            menu.geos_ordered,
            {
                None: [(geo1.id, "Europe")],
                geo1.id: [(geo2.id, "Eastern Europe")],
            },
        )
        self.assertEqual(
            menu._geos_ordered,
            {
                None: [(geo1.id, "Europe")],
                geo1.id: [(geo2.id, "Eastern Europe")],
            },
        )

        # delete
        self.session.delete(geo2)
        self.session.commit()

        self.assertEqual(
            menu.geos_ordered,
            {None: [(geo1.id, "Europe")]},
        )
        self.assertEqual(
            menu._geos_ordered,
            {None: [(geo1.id, "Europe")]},
        )

        menu.reset()

    def test_single_geography_appends_as_menu_item(self):
        """Test that a single geography is added as a menu item."""
        geo = Geography(
            name="EUROPE",
            code="1",
            level=1,
        )
        self.session.add(geo)
        self.session.commit()

        menu = GeographyMenu()

        with mock.patch.object(menu, "append_submenu") as mock_append:
            self.assertEqual(len(menu.geos_ordered), 1)
            self.assertEqual(menu.get_n_items(), 1)
            # confirm its not a submenu
            mock_append.assert_not_called()

        menu.reset()


class DistributionMapTests(BaubleClassTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        setup_geographies()
        cls.geo = cls.session.get(Geography, 682)
        fam = Family(epithet="Cyatheaceae")
        gen = Genus(epithet="Sphaeropteris", family=fam)
        cls.sp = Species(epithet="robusta", genus=gen)
        cls.sp.distribution.append(SpeciesDistribution(geography=cls.geo))
        cls.session.add(cls.sp)
        cls.session.commit()

    def setUp(self):
        DistributionMap._world = ""
        DistributionMap._world_pixbuf = None
        DistributionMap._image_cache = utils.LRUCache()

    def test_world_template(self):
        # calling world generates the template
        dist = DistributionMap([682])
        self.assertEqual(dist._world, "")
        world = dist.world
        self.assertIn("{selected}", world)
        self.assertEqual(dist._world, world)
        # template doesn't change when geography does
        dist = DistributionMap([50])
        self.assertEqual(world, dist.world)
        # str shows populated template
        dist = DistributionMap([682])
        self.assertNotIn("{selected}", str(dist))

    def test_pacific_centric_world_template(self):
        dist = DistributionMap([50])
        norm = str(dist)
        self.assertIn('viewBox="-180', norm)
        # reset and set pref
        DistributionMap._world = ""
        prefs.prefs[GEO_PACIFIC_CENTRIC] = True
        dist = DistributionMap([50])
        pc = str(dist)
        self.assertIn('viewBox="-30', pc)
        self.assertTrue(len(pc) > len(norm))

    def test_world_pixbuf(self):
        # calling world_pixbuf generates the pixbuf
        dist = DistributionMap([682])
        self.assertIsNone(dist._world_pixbuf)
        world = dist.world_pixbuf
        self.assertIsNotNone(world)
        # template doesn't change when geography does
        dist = DistributionMap([50])
        self.assertEqual(world, dist.world_pixbuf)

    def test_map(self):
        # calling map (via __str__) populates
        dist = DistributionMap([682])
        self.assertFalse(dist._map)
        map_ = str(dist)
        self.assertEqual(map_, dist.map)
        # map does change when geography does
        dist = DistributionMap([50])
        self.assertNotEqual(map_, dist.map)

    def test_as_image_starts_blank_then_populates(self):
        # returns image immediately (even if not populated yet)
        dist = DistributionMap([682])
        # initially None
        self.assertIsNone(dist._world_pixbuf)
        self.assertIsNone(dist._image)
        # trigger creation
        dist.world
        # initially the same (Blank)
        self.assertEqual(dist._world_pixbuf, dist.as_image().get_pixbuf())
        self.assertIsNotNone(dist._image)
        # populates with correct image after threads and idle_add complete
        wait_on_threads()
        update_gui()
        self.assertNotEqual(dist._world_pixbuf, dist.as_image().get_pixbuf())

    def test_dist_map_cache(self):
        cache = utils.LRUCache(size=121)
        # load the cache
        for i in range(121):
            cache[i] = Gtk.Image()
        self.assertEqual(len(cache), 121)
        self.assertIsNotNone(cache.get(0))
        # removes first entry
        cache[121] = Gtk.Image()
        self.assertEqual(len(cache), 121)
        self.assertIsNone(cache.get(0))
        # if get first does not remove it first
        self.assertIsNotNone(cache[1])
        self.assertEqual(len(cache), 121)
        cache[122] = Gtk.Image()
        self.assertIsNotNone(cache.get(1))
        # removes second
        self.assertIsNone(cache.get(2))

    def test_dist_map_does_not_cause_history_entries(self):
        # incase of history triggered by update to approx area
        # (depends on system, pyproj/proj version)
        geo_id = self.geo.id
        start = self.session.scalar(
            select(func.count())
            .select_from(db.History)
            .where(db.History.table_name == "geography")
            .where(db.History.table_id == geo_id)
        )
        dist_map = self.sp.get_geography_ids()
        self.assertTrue(dist_map)
        editor = SpeciesEditorDialog(self.sp, self.session)
        editor.emit("response", Response.OK)
        update_gui()
        editor.destroy()

        hist = self.session.scalars(
            select(db.History.values)
            .where(db.History.table_name == "geography")
            .where(db.History.table_id == geo_id)
        ).all()
        self.assertEqual(len(hist), start, hist)

    def test_get_areas(self):
        dist = DistributionMap([657, 683])
        self.assertEqual(
            [i.code for i in dist.get_areas()], ["MXI-RA", "NFK-NI"]
        )

    def test_zoom_map(self):
        dist = DistributionMap([657, 683])
        paths = (
            '<path stroke="green" stroke-width="0.2" fill="green" d="M '
            "-115.75 24.952 L -115.75 24.953 L -115.75 24.954 L -115.749 "
            '24.952 Z"/><path stroke="green" stroke-width="0.2" '
            'fill="green" d="M 244.25 24.952 L 244.25 24.953 L 244.25 '
            '24.954 L 244.251 24.952 Z"/>'
        )
        self.assertFalse(dist._zoom_map)
        self.assertIn(paths, dist.zoom_map)
        self.assertTrue(dist._zoom_map)
        self.assertIn('viewBox="{viewbox}">', dist.zoom_map)
        with mock.patch(
            "bauble.plugins.plants.ui.widgets.geography.get_world_paths"
        ) as gwp:
            self.assertIn('viewBox="{viewbox}">', dist.zoom_map)
            gwp.assert_not_called()
            dist._zoom_map = ""
            self.assertIn('viewBox="{viewbox}">', dist.zoom_map)
            gwp.assert_called()

    def test_get_zoom_viewbox(self):
        dist = DistributionMap([683])
        self.assertIsNone(dist._current_max_mins)
        self.assertEqual(dist.get_zoom_viewbox(10), "149.955 20.043 36.0 18.0")
        self.assertIsNotNone(dist._current_max_mins)
        with mock.patch(
            "bauble.plugins.plants.ui.widgets.geography.straddles_antimeridian"
        ) as sam:
            self.assertEqual(
                dist.get_zoom_viewbox(9), "147.955 19.043 40.0 20.0"
            )
            sam.assert_not_called()

        # stradling
        fiji = 167
        dist = DistributionMap([fiji])
        self.assertIsNone(dist._current_max_mins)
        self.assertEqual(dist.get_zoom_viewbox(18), "169.415 11.581 20.0 10.0")
        self.assertIsNotNone(dist._current_max_mins)
        self.assertEqual(dist.get_zoom_viewbox(2), "89.415 -28.419 180.0 90.0")
        # too far west to zoom out too far
        cook_is = 138
        dist = DistributionMap([cook_is])
        self.assertIsNone(dist._current_max_mins)
        self.assertEqual(dist.get_zoom_viewbox(18), "-170.24 14.999 20.0 10.0")
        # now pacific centric
        self.assertEqual(dist.get_zoom_viewbox(8), "177.26 8.749 45.0 22.5")

    def test_get_max_zoom(self):
        rocas_alijos = 657
        dist = DistributionMap([rocas_alijos])
        self.assertEqual(dist.get_max_zoom(), 18)

        new_zealand = 39
        dist = DistributionMap([new_zealand])
        self.assertEqual(dist.get_max_zoom(), 7)

        # EUROPE, ASIA_TEMPERATE, NORTHERN AMERICA (Global)
        dist = DistributionMap([1, 3, 7])
        self.assertEqual(dist.get_max_zoom(), 1)

        # africa
        africa = 2
        dist = DistributionMap([africa])
        self.assertEqual(dist.get_max_zoom(), 2)

    def test_replace_image(self):
        rocas_alijos = 657
        dist = DistributionMap([rocas_alijos])
        start_map = dist.map
        start_pb = dist.as_image().get_pixbuf()
        self.assertIn(dist._image, dist._image_cache.values())
        replace = (
            '<svg width="100" height="100" xmlns="http://www.w3.org/2000/svg">'
            '<path stroke="green" stroke-width="0.2" fill="green" d="M 0 0 L '
            '0 100 L 100 100 L 100 0 Z"/></svg>'
        )
        dist.replace_image(replace)
        self.assertEqual(replace, dist.map)
        self.assertNotEqual(start_map, dist.map)
        self.assertNotEqual(start_pb, dist.as_image().get_pixbuf())
        self.assertNotIn(dist._image, dist._image_cache.values())

    def test_zoom_to_level(self):
        rocas_alijos = 657
        dist = DistributionMap([rocas_alijos])
        dist._zoom_map = "TEST {viewbox}"
        dist.replace_image = mock.Mock()
        dist.zoom_to_level(8.0)
        dist.replace_image.assert_called_with("TEST -138.25 -36.203 45.0 22.5")

    def test_detach_image(self):
        rocas_alijos = 657
        dist = DistributionMap([rocas_alijos])
        # covers no image
        dist.detach_image()
        box = Gtk.Box()
        box.add(dist.as_image())

        self.assertEqual(dist._image.get_parent(), box)

        dist.detach_image()

        self.assertIsNone(dist._image.get_parent())


class DistributionMapEventBoxTests(BaubleTestCase):
    def test_update(self):
        geo = Geography(
            name="Lord Howe I.",
            code="NFK-LH",
            level=4,
        )
        self.session.add(geo)
        self.session.commit()
        map_ebox = DistributionMapEventBox()

        self.assertIsNone(map_ebox.distribution_map)
        self.assertEqual(len(map_ebox.get_children()), 0)

        # No geojson
        map_ebox.update(geo)

        self.assertIsNone(map_ebox.distribution_map)
        self.assertEqual(len(map_ebox.get_children()), 0)

        geojson = {
            "type": "Polygon",
            "coordinates": [
                [
                    [159.07080078125, -31.599998474121094],
                    [159.08578491210938, -31.561111450195312],
                    [159.04913330078125, -31.52166748046875],
                    [159.10189819335938, -31.57111358642578],
                    [159.07080078125, -31.599998474121094],
                ]
            ],
        }
        geo.geojson = geojson
        self.session.commit()
        map_ebox.update(geo)

        self.assertIsNotNone(map_ebox.distribution_map)
        self.assertEqual(len(map_ebox.get_children()), 1)

    def test_on_map_button_release(self):
        btn = Gdk.EventButton()
        btn.button = 1
        map_ebox = DistributionMapEventBox()
        map_ebox.zoomed = False
        self.assertFalse(map_ebox.on_map_button_release(None, btn))

        btn = Gdk.EventButton()
        btn.button = 3
        map_ebox = DistributionMapEventBox()
        map_ebox.zoomed = False
        path = (
            "bauble.plugins.plants.ui.widgets.geography.Gtk.Menu."
            "popup_at_pointer"
        )
        with mock.patch(path) as mock_popup:

            self.assertTrue(map_ebox.on_map_button_release(map_ebox, btn))
            mock_popup.assert_called()

        map_action_name = DistributionMapEventBox.MAP_ACTION_NAME
        grp = map_ebox.get_action_group(map_action_name)

        self.assertTrue(grp.lookup_action("zoom"))
        self.assertIsNone(grp.lookup_action("zmout"))

        map_ebox.zoomed = True
        with mock.patch(path) as mock_popup:

            self.assertTrue(map_ebox.on_map_button_release(map_ebox, btn))
            mock_popup.assert_called()

        grp = map_ebox.get_action_group(map_action_name)

        self.assertIsNone(grp.lookup_action("zoom"))
        self.assertTrue(grp.lookup_action("zmout"))

    @mock.patch(
        "bauble.plugins.plants.ui.widgets.geography.Gtk.FileChooserNative"
    )
    def test_on_dist_map_save(self, mock_chooser):
        geojson = {
            "type": "Polygon",
            "coordinates": [
                [
                    [159.07080078125, -31.599998474121094],
                    [159.08578491210938, -31.561111450195312],
                    [159.04913330078125, -31.52166748046875],
                    [159.10189819335938, -31.57111358642578],
                    [159.07080078125, -31.599998474121094],
                ]
            ],
        }
        geo = Geography(
            name="Lord Howe I.",
            code="NFK-LH",
            level=4,
            geojson=geojson,
        )
        self.session.add(geo)
        self.session.commit()
        map_ebox = DistributionMapEventBox()
        map_ebox.update(geo)
        # mock filechooser to CANCEL and check that get_filename is not
        # called
        mock_chooser.new().run.return_value = Gtk.ResponseType.CANCEL
        map_ebox.on_dist_map_save(None, None)
        mock_chooser.new().get_filename.assert_not_called()

        handle, filename = mkstemp(suffix=".svg")
        mock_chooser.new().run.return_value = Gtk.ResponseType.ACCEPT
        mock_chooser.new().get_filename.return_value = filename
        map_ebox.on_dist_map_save(None, None)
        mock_chooser.new().get_filename.assert_called()
        os.close(handle)
        with open(filename, "r", encoding="utf-8") as f:
            out = f.read()

        svg_paths = (
            '<path stroke="green" stroke-width="0.2" fill="green" d='
            '"M 159.071 -31.6 L 159.086 -31.561 L 159.049 -31.522 L 159.102 '
            '-31.571 Z"/>'
        )
        svg = DistributionMap._world.format(selected=svg_paths)
        self.assertIn(svg_paths, svg)
        self.assertEqual(out, svg)
        # type guard
        mock_chooser.reset_mock()
        map_ebox.distribution_map = None
        map_ebox.on_dist_map_save(None, None)
        mock_chooser.new().get_filename.assert_not_called()

    @mock.patch("bauble.plugins.plants.ui.widgets.geography.get_clipboard")
    def test_on_dist_map_copy(self, mock_clipboard):
        geojson = {
            "type": "Polygon",
            "coordinates": [
                [
                    [159.07080078125, -31.599998474121094],
                    [159.08578491210938, -31.561111450195312],
                    [159.04913330078125, -31.52166748046875],
                    [159.10189819335938, -31.57111358642578],
                    [159.07080078125, -31.599998474121094],
                ]
            ],
        }
        geo = Geography(
            name="Lord Howe I.",
            code="NFK-LH",
            level=4,
            geojson=geojson,
        )
        self.session.add(geo)
        self.session.commit()
        map_ebox = DistributionMapEventBox()
        map_ebox.update(geo)

        map_ebox.on_dist_map_copy(None, None)
        mock_clipboard().set_image.assert_called_with(
            DistributionMap(geo.get_geography_ids()).as_image().get_pixbuf()
        )
        mock_clipboard.reset_mock()
        map_ebox.distribution_map = None
        map_ebox.on_dist_map_copy(None, None)
        mock_clipboard().set_image.assert_not_called()

    def test_on_dist_map_zoom(self):
        # type guard, doesn't fail because it bails early
        map_ebox = DistributionMapEventBox()
        map_ebox.distribution_map = None
        self.assertIsNone(map_ebox.on_dist_map_zoom(None, None))
        # zoom == 1
        map_ebox.zoomed = False
        map_ebox.distribution_map = mock.Mock()
        map_ebox.distribution_map.get_max_zoom.return_value = 1
        map_ebox.on_dist_map_zoom(None, None)
        map_ebox.distribution_map.zoom_to_level.assert_not_called()
        self.assertFalse(map_ebox.zoomed)
        # zoom == 10
        map_ebox.distribution_map.get_max_zoom.return_value = 10
        map_ebox.on_dist_map_zoom(None, None)
        map_ebox.distribution_map.zoom_to_level.assert_called_with(10)
        self.assertTrue(map_ebox.zoomed)

    def test_on_dist_map_zoom_out(self):
        # type guard, doesn't fail because it bails early
        map_ebox = DistributionMapEventBox()
        map_ebox.distribution_map = None
        self.assertIsNone(map_ebox.on_dist_map_zoom_out(None, None))
        # zoom == 2
        map_ebox.distribution_map = mock.Mock()
        map_ebox.zoomed = True
        map_ebox.zoom_level = 2
        map_ebox.on_dist_map_zoom_out(None, None)
        self.assertEqual(map_ebox.zoom_level, 1)
        self.assertFalse(map_ebox.zoomed)
        map_ebox.distribution_map.zoom_to_level.assert_called_with(1)
        # zoom = 10
        map_ebox.distribution_map = mock.Mock()
        map_ebox.zoomed = True
        map_ebox.zoom_level = 10
        map_ebox.on_dist_map_zoom_out(None, None)
        self.assertEqual(map_ebox.zoom_level, 8)
        self.assertTrue(map_ebox.zoomed)
        map_ebox.distribution_map.zoom_to_level.assert_called_with(8)


class GeographyFuncTests(TestCase):
    """Tests not requiring setup_geographies()"""

    def test_split_lats_longs(self):
        geojson1 = {
            "type": "Polygon",
            "coordinates": [
                [
                    [-115.7504425, 24.9516697],
                    [-115.7500534, 24.9512501],
                    [-115.7487793, 24.9524994],
                    [-115.7500305, 24.9537201],
                    [-115.7504196, 24.9533291],
                    [-115.7504501, 24.9516697],
                    [-115.7504425, 24.9516697],
                ]
            ],
        }
        geo1 = Geography(
            name="Rocas Alijos",
            code="MXI-RA",
            level=4,
            geojson=geojson1,
        )
        geojson2 = {
            "type": "MultiPolygon",
            "coordinates": [
                [
                    [
                        [159.07080078125, -31.599998474121094],
                        [159.08578491210938, -31.561111450195312],
                        [159.04913330078125, -31.52166748046875],
                        [159.10189819335938, -31.57111358642578],
                        [159.07080078125, -31.599998474121094],
                    ],
                    [
                        [139.07080078125, -21.599998474121094],
                        [139.08578491210938, -21.561111450195312],
                        [139.04913330078125, -21.52166748046875],
                        [139.10189819335938, -21.57111358642578],
                        [139.07080078125, -21.599998474121094],
                    ],
                ]
            ],
        }
        geo2 = Geography(
            name="Lord Howe I.",
            code="NFK-LH",
            level=4,
            geojson=geojson2,
        )

        areas = [geo1, geo2]
        longs, lats = split_lats_longs(areas)

        longs_result = []
        lats_result = []
        for coord in geojson1["coordinates"][0]:
            longs_result.append(coord[0])
            lats_result.append(coord[1])
        for poly in geojson2["coordinates"][0]:
            for coord in poly:
                longs_result.append(coord[0])
                lats_result.append(coord[1])

        self.assertCountEqual(longs, longs_result)
        self.assertCountEqual(lats, lats_result)

    def test_get_zoom_buffer(self):
        self.assertEqual(calculate_zoom_buffer(1, -180, 180), 0)
        self.assertEqual(calculate_zoom_buffer(1, -1, 1), 179)
        self.assertEqual(calculate_zoom_buffer(1, -100, 100), 80)
        self.assertEqual(calculate_zoom_buffer(1, -10, 10), 170)
        self.assertEqual(calculate_zoom_buffer(2, -10, 10), 80)
        self.assertEqual(calculate_zoom_buffer(5, -10, 10), 26)
        self.assertEqual(calculate_zoom_buffer(5, 0, 72), 0)
        # zoomed too far
        self.assertRaises(ValueError, calculate_zoom_buffer, 6, 0, 72)

    def test_straddles_antimeridian(self):
        # doesn't stradle
        self.assertFalse(
            straddles_antimeridian([120, 0, -120], [120, 0, -120 + 360], 1)
        )
        self.assertFalse(
            straddles_antimeridian([20, 0, -20], [20, 0, -20 + 360], 8)
        )
        self.assertFalse(straddles_antimeridian([91, -91], [91, -91 + 360], 1))
        # africa
        self.assertFalse(
            straddles_antimeridian([60, 1, -17], [60, 0, -17 + 360], 1)
        )
        # zoomed it doesn't stradle, zoomed less it would be too far east
        self.assertFalse(straddles_antimeridian([91, 150], [91, 150], 4))
        # straddles
        self.assertTrue(
            straddles_antimeridian([120, -120], [120, -120 + 360], 1)
        )
        self.assertTrue(
            straddles_antimeridian([120, 179, -120], [120, 179, -120 + 360], 1)
        )
        self.assertTrue(
            straddles_antimeridian([178, -178], [178, -178 + 360], 1)
        )
        # too far West
        self.assertTrue(
            straddles_antimeridian([10, -179], [10, -179 + 360], 1)
        )
        self.assertTrue(
            straddles_antimeridian([10, 12, -179], [10, 12, -179 + 360], 1)
        )
        self.assertTrue(
            straddles_antimeridian(
                [10, -10, -179], [10, -10 + 360, -179 + 360], 1
            )
        )
        self.assertTrue(straddles_antimeridian([1, -180], [1, -180 + 360], 1))
        self.assertTrue(
            straddles_antimeridian([-91, -150], [-91 + 360, -150 + 360], 2)
        )
        # too far East
        self.assertTrue(straddles_antimeridian([180, -1], [180, -1 + 360], 1))
        self.assertTrue(
            straddles_antimeridian([178, -10], [178, -10 + 360], 1)
        )
        self.assertTrue(straddles_antimeridian([91, 150], [91, 150], 2))
        # raises - zoomed to far
        self.assertRaises(
            ValueError, straddles_antimeridian, [91, 150], [91, 150], 7
        )

    def test_get_viewbox(self):
        self.assertEqual(
            get_viewbox(-180, 180, -90, 90, 1), "-180.0 -90.0 360.0 180.0"
        )
        self.assertEqual(
            get_viewbox(-100, 100, -50, 50, 2), "-90.0 -45.0 180.0 90.0"
        )
        # far north corrects y
        self.assertEqual(
            get_viewbox(-40, 40, 50, 80, 2), "-90.0 -90.0 180.0 90.0"
        )
        # far south corrects y
        self.assertEqual(
            get_viewbox(-40, 40, -50, -80, 2), "-90.0 0.0 180.0 90.0"
        )
        self.assertEqual(
            get_viewbox(153.5433446, 138.0000446, -10.0513948, -29.1705948, 8),
            "138.815 27.48 45.0 22.5",
        )
        self.assertEqual(
            get_viewbox(-180, -10, 50, 90, 1), "-180.0 -90.0 360.0 180.0"
        )
        self.assertRaises(ValueError, get_viewbox, -180, -10, 50, 90, 2)


class UpdateAllApproxAreaTests(BaubleTestCase):
    def test_update_all_approx_areas_handler(self):
        setup_geographies()
        vals = {}
        geos = self.session.scalars(select(Geography))

        for geo in geos:
            self.assertTrue(geo.approx_area)
            vals[geo.id] = geo.approx_area
            geo.geojson = None

        # use core so listen_for is not trggered
        with db.engine.begin() as connection:
            table = Geography.__table__
            stmt = update(table).values(approx_area=0.0)
            connection.execute(stmt)

        for geo in geos:
            self.session.refresh(geo)
            self.assertFalse(geo.approx_area)

        update_all_approx_areas_handler()
        # A fail here may indicated our default is incorrect
        for geo in geos:
            self.session.refresh(geo)
            self.assertAlmostEqual(
                geo.approx_area, vals[geo.id], delta=2, msg=geo
            )

        # use core so listen_for is not trggered
        with db.engine.begin() as connection:
            table = Geography.__table__
            stmt = update(table).values(geojson=None)
            connection.execute(stmt)

        for geo in geos:
            self.session.refresh(geo)
            self.assertFalse(geo.geojson)
            self.assertTrue(geo.approx_area)

        update_all_approx_areas_handler()
        for geo in geos:
            self.session.refresh(geo)
            self.assertEqual(geo.approx_area, 0.0)

    @mock.patch("bauble.ui.dialogs.message_details_dialog")
    def test_update_all_approx_areas_handler_exception(self, mock_dialog):
        with mock.patch(
            "bauble.plugins.plants.ui.widgets.geography.queue"
        ) as que:
            que.side_effect = Exception
            update_all_approx_areas_handler()
        mock_dialog.assert_called()

    def test_update_all_approx_areas_task(self):
        geo = Geography(
            name="Lord Howe I.",
            code="NFK-LH",
            level=4,
        )
        self.session.add(geo)
        self.session.commit()
        self.assertTrue(list(update_all_approx_areas_task()))


class FunctionTests(BaubleTestCase):
    def test_species_to_string_matcher(self):
        setup_plants_data()
        list(update_all_full_names_task())
        family = Family(family="Myrtaceae")
        gen1 = Genus(family=family, genus="Syzygium")
        gen2 = Genus(family=family, genus="Melaleuca")
        sp1 = Species(genus=gen1, sp="australe")
        sp2 = Species(genus=gen2, sp="viminalis")
        sp3 = Species(
            genus=gen2,
            sp="viminalis",
            cultivar_epithet="Captain Cook",
            trade_name="Tradename",
        )
        sp4 = Species(genus=gen2, sp="viminalis", cultivar_epithet="cv.")
        sp5 = Species(genus=gen2, sp="sp. Carnarvon NP (M.B.Thomas 115)")
        sp6 = Species(
            genus=gen1,
            sp="wilsonii",
            infraspecific_parts="subsp. cryptophlebium",
        )
        sp7 = self.session.get(Species, 26)
        sp9 = self.session.get(Species, 9)
        self.assertTrue(species_to_string_matcher(sp1, "S a"))
        self.assertTrue(species_to_string_matcher(sp1, "Syzyg"))
        self.assertTrue(species_to_string_matcher(sp1, "Syzygium australe"))
        self.assertFalse(species_to_string_matcher(sp1, "unknown"))
        self.assertFalse(species_to_string_matcher(sp1, "Mel vim"))
        self.assertTrue(species_to_string_matcher(sp2, "Mel vim"))
        self.assertTrue(species_to_string_matcher(sp2, "M"))
        self.assertTrue(species_to_string_matcher(sp2, ""))
        self.assertFalse(species_to_string_matcher(sp2, "unknown"))
        self.assertFalse(
            species_to_string_matcher(sp2, "a long string with little meaning")
        )
        self.assertTrue(species_to_string_matcher(sp3, "M"))
        self.assertTrue(species_to_string_matcher(sp3, "M v"))
        self.assertTrue(
            species_to_string_matcher(sp3, "M viminalis 'Captain Cook'")
        )
        self.assertTrue(species_to_string_matcher(sp3, "M 'Cap"))
        self.assertTrue(species_to_string_matcher(sp3, "M 'Tradename"))
        self.assertFalse(species_to_string_matcher(sp3, "M 'Rob"))
        self.assertTrue(species_to_string_matcher(sp4, "Mel viminalis cv."))
        self.assertTrue(species_to_string_matcher(sp4, "Mel"))
        self.assertFalse(species_to_string_matcher(sp4, "Cal vim"))
        self.assertTrue(species_to_string_matcher(sp5, "Mel sp."))
        self.assertTrue(species_to_string_matcher(sp5, "Mel sp. Carn"))
        self.assertTrue(species_to_string_matcher(sp5, "Mel"))
        self.assertTrue(species_to_string_matcher(sp6, "Syz wil"))
        self.assertTrue(
            species_to_string_matcher(sp6, "Syz wilsonii subsp. cry")
        )
        self.assertFalse(
            species_to_string_matcher(sp6, "Syz wilsonii subsp. wil")
        )
        self.assertTrue(
            species_to_string_matcher(sp7, "× Butyagrus nabonnandii")
        )
        self.assertTrue(
            species_to_string_matcher(sp7, "Butyagrus nabonnandii")
        )
        self.assertTrue(species_to_string_matcher(sp7, "× Buty"))
        self.assertTrue(species_to_string_matcher(sp7, "× Buty nab"))
        self.assertFalse(species_to_string_matcher(sp7, "× Buty o"))
        self.assertTrue(
            species_to_string_matcher(sp9, "Maxillaria × generalis")
        )
        self.assertTrue(species_to_string_matcher(sp9, "Maxillaria ×"))
        self.assertTrue(species_to_string_matcher(sp9, "Maxil × gen"))
        self.assertFalse(species_to_string_matcher(sp9, "Maxil × sen"))
        key = "Maxillaria s. str var"
        sp = self.session.get(Species, 1)
        self.assertTrue(species_to_string_matcher(sp, key))
        key = "Maxi var"
        self.assertTrue(species_to_string_matcher(sp, key))

    def test_species_cell_data_func(self):
        family = Family(family="Myrtaceae")
        genus = Genus(family=family, genus="Syzygium")
        species = Species(genus=genus, epithet="australe")
        self.session.add(species)
        self.session.commit()
        mock_renderer = mock.Mock()
        mock_model = [[species]]

        species_cell_data_func(None, mock_renderer, mock_model, 0)

        mock_renderer.set_property.assert_called_with(
            "markup",
            "<i>Syzygium</i> <i>australe</i>  (<small>Myrtaceae</small>)",
        )

    @mock.patch("bauble.ui.dialogs.message_details_dialog")
    def test_update_all_full_names_handler(self, mock_dialog):
        family = Family(family="Myrtaceae")
        genus = Genus(family=family, genus="Syzygium")
        self.session.add(genus)
        self.session.commit()
        # avoid listen_for
        with db.engine.begin() as connection:
            stmt = insert(Species.__table__).values(
                genus_id=genus.id, sp="australe"
            )
            connection.execute(stmt)

        species = self.session.scalar(
            select(Species)
            .where(Species.genus == genus)
            .where(Species.epithet == "australe")
        )
        self.assertIsNone(species.full_name)
        update_all_full_names_handler()

        self.session.refresh(species)
        self.assertEqual(species.full_name, "Syzygium australe")

        with mock.patch(
            "bauble.plugins.plants.ui.widgets.species.queue"
        ) as mock_queue:
            mock_queue.side_effect = Exception("BOOM")
            update_all_full_names_handler()
            mock_dialog.assert_called_once()

    @mock.patch("bauble.meta.create_message_dialog")
    def test_setup_conservation_fields(self, mock_dialog):
        mock_dialog().run.return_value = -5  # OK

        with mock.patch("bauble.db.open_conn") as mock_open_conn:
            setup_conservation_fields()

            mock_open_conn.assert_called_once()
        self.assertTrue(hasattr(Species, "nca_status"))
        self.assertTrue(hasattr(Species, "epbc_status"))
