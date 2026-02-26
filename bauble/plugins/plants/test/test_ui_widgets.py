# pylint: disable=protected-access
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
from unittest import mock

from gi.repository import Gtk

from bauble import utils
from bauble.plugins.plants.family import Family
from bauble.plugins.plants.family import FamilySynonym
from bauble.test import BaubleTestCase
from bauble.test import get_setUp_data_funcs

from ..ui.widgets import SynonymsPresenter
from ..ui.widgets import _syn_data_func


class SynonymsPresenterTests(BaubleTestCase):
    def test_init_new(self):
        family = Family()
        syns_presenter = SynonymsPresenter()
        syns_presenter.init(
            family,
            FamilySynonym,
            self.session,
            lambda session, text: (
                session.query(Family)
                .filter(utils.ilike(Family.family, f"{text}%%"))
                .order_by(Family.family)
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
            lambda session, text: (
                session.query(Family)
                .filter(utils.ilike(Family.family, f"{text}%%"))
                .order_by(Family.family)
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
            lambda session, text: (
                session.query(Family)
                .filter(utils.ilike(Family.family, f"{text}%%"))
                .order_by(Family.family)
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
            lambda session, text: (
                session.query(Family)
                .filter(utils.ilike(Family.family, f"{text}%%"))
                .order_by(Family.family)
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
            lambda session, text: (
                session.query(Family)
                .filter(utils.ilike(Family.family, f"{text}%%"))
                .order_by(Family.family)
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

        self.assertEqual(len(model), 1)
        self.assertEqual(syns_presenter._selected.epithet, "Myrtaceae")
        self.assertEqual("Myrtaceae", syns_presenter.entry.get_text())
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
            lambda session, text: (
                session.query(Family)
                .filter(utils.ilike(Family.family, f"{text}%%"))
                .order_by(Family.family)
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
            lambda session, text: (
                session.query(Family)
                .filter(utils.ilike(Family.family, f"{text}%%"))
                .order_by(Family.family)
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

        myrtaceae = (
            self.session.query(Family).filter_by(epithet="Myrtaceae").first()
        )
        leptospermaceae = Family(epithet="Leptospermaceae")
        myrtaceae.synonyms.append(leptospermaceae)
        self.session.commit()

        family = Family()
        syns_presenter = SynonymsPresenter()
        syns_presenter.init(
            family,
            FamilySynonym,
            self.session,
            lambda session, text: (
                session.query(Family)
                .filter(utils.ilike(Family.family, f"{text}%%"))
                .order_by(Family.family)
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
        self.assertFalse(syns_presenter.add_button.get_sensitive())
        self.assertFalse(syns_presenter.remove_button.get_sensitive())

        syns_presenter.destroy()

    @mock.patch("bauble.plugins.plants.ui.widgets.dialogs.yes_no_dialog")
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
            lambda session, text: (
                session.query(Family)
                .filter(utils.ilike(Family.family, f"{text}%%"))
                .order_by(Family.family)
            ),
        )
        self.assertEqual(len(myrtaceae.synonyms), 1)

        # no selected returns
        syns_presenter.remove_button.clicked()

        self.assertEqual(len(syns_presenter.treeview.get_model()), 1)

        # select first
        syns_presenter.treeview.set_cursor(Gtk.TreePath(0))
        syns_presenter.remove_button.clicked()

        self.assertEqual(len(myrtaceae.synonyms), 0)

        syns_presenter.destroy()

    @mock.patch("bauble.plugins.plants.ui.widgets.dialogs.yes_no_dialog")
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
            lambda session, text: (
                session.query(Family)
                .filter(utils.ilike(Family.family, f"{text}%%"))
                .order_by(Family.family)
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
        self.session.expunge(synonym)

        _syn_data_func(column, cell, model, treeiter, None)
