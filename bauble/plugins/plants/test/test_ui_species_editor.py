# pylint: disable=too-many-lines,too-many-public-methods,no-self-use
# pylint: disable=too-many-statements
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
Family editor tests
"""
import os
from unittest import mock

from gi.repository import Gtk
from sqlalchemy import func
from sqlalchemy import select

from bauble import db
from bauble import utils
from bauble.meta import BaubleMeta
from bauble.plugins.imex.csv_ import CSVRestore
from bauble.plugins.plants.family import Family
from bauble.plugins.plants.genus import Genus
from bauble.plugins.plants.species import Habit
from bauble.plugins.plants.species import Species
from bauble.plugins.plants.species import VernacularName
from bauble.plugins.plants.species import register_custom_column
from bauble.test import BaubleTestCase
from bauble.test import update_gui
from bauble.ui.presenter import Response
from bauble.ui.utils import get_widget_value
from bauble.ui.utils import set_widget_value
from bauble.ui.widgets.message import YesNoMessageBox

from ..ui.species_editor import Name
from ..ui.species_editor import SpeciesEditorDialog
from ..ui.species_editor import edit_callback
from ..ui.species_editor import split_taxon_full_name
from .test_plants import setUp_data as setup_plants_data


class SpeciesEditorDialogTests(BaubleTestCase):
    @mock.patch("bauble.gui")
    def test_init_existing(self, mock_gui):
        mock_gui.window = Gtk.Window()
        mock_gui.window = Gtk.Window()
        family = Family(epithet="Austrobaileyaceae")
        genus = Genus(epithet="Austrobaileya", family=family)
        species = Species(genus=genus, epithet="scandens")
        self.session.add(species)
        self.session.commit()
        editor = SpeciesEditorDialog(species, self.session)

        self.assertEqual(editor.get_transient_for(), mock_gui.window)
        self.assertEqual(editor.links_menu_btn.model, species)
        self.assertEqual(editor.synonyms_presenter.model, species)
        self.assertEqual(editor.genus_entry.get_text(), "Austrobaileya")
        self.assertEqual(editor.species_entry.get_text(), "scandens")
        self.assertFalse(editor.infragen_expander.get_expanded())
        self.assertFalse(editor.cv_extras_grid.get_visible())
        self.assertEqual(len(editor.problems), 0)

        editor.destroy()

    def test_init_new(self):
        species = Species()
        editor = SpeciesEditorDialog(species, self.session)

        self.assertTrue(editor.links_menu_btn.model)
        self.assertTrue(editor.synonyms_presenter.model)
        self.assertEqual(editor.genus_entry.get_text(), "")
        self.assertEqual(editor.species_entry.get_text(), "")
        self.assertEqual(editor.infrasp_presenter.rows, [])
        self.assertEqual(editor.cv_epithet_entry.get_text(), "")
        self.assertEqual(editor.cv_group_entry.get_text(), "")
        self.assertEqual(editor.tradename_entry.get_text(), "")
        self.assertEqual(editor.habit_entry.get_text(), "")
        self.assertFalse(editor.infragen_expander.get_expanded())
        self.assertFalse(editor.cv_extras_grid.get_visible())
        self.assertEqual(len(editor.problems), 1)
        for problem, widget in editor.problems:
            self.assertEqual(widget, editor.genus_entry)
            self.assertTrue(
                problem.startswith(
                    "not_matched::on_completion_entry_matched::SpeciesEditor"
                )
            )

        editor.destroy()

    def test_init_existing_w_infrageneric_parts(self):
        family = Family(epithet="Ericaceae")
        genus = Genus(epithet="Rhododendron", family=family)
        species = Species(
            genus=genus,
            section="Vireya",
            cultivar_epithet="Lady Di",
        )
        self.session.add(species)
        self.session.commit()
        editor = SpeciesEditorDialog(species, self.session)

        self.assertEqual(editor.links_menu_btn.model, species)
        self.assertEqual(editor.synonyms_presenter.model, species)
        self.assertEqual(editor.genus_entry.get_text(), "Rhododendron")
        self.assertEqual(editor.section_entry.get_text(), "Vireya")
        self.assertEqual(editor.cv_epithet_entry.get_text(), "Lady Di")
        self.assertTrue(editor.infragen_expander.get_expanded())
        self.assertFalse(editor.cv_extras_grid.get_visible())
        self.assertEqual(len(editor.problems), 0)

        editor.destroy()

    def test_init_existing_w_grex_cites(self):
        family = Family(epithet="Orchidaceae", cites="III")
        genus = Genus(epithet="Bletilla", family=family, _cites="II")
        species = Species(
            genus=genus,
            grex="Penway Prelude",
            _cites="I",
        )
        self.session.add(species)
        self.session.commit()
        editor = SpeciesEditorDialog(species, self.session)

        self.assertEqual(editor.links_menu_btn.model, species)
        self.assertEqual(editor.synonyms_presenter.model, species)
        self.assertEqual(editor.genus_entry.get_text(), "Bletilla")
        self.assertEqual(editor.grex_entry.get_text(), "Penway Prelude")
        self.assertTrue(editor.cv_extras_grid.get_visible())
        self.assertEqual(len(editor.problems), 0)
        self.assertEqual(
            editor.fullname_label.get_label(),
            "<i>Bletilla</i> Penway Prelude grex",
        )
        self.assertEqual(
            editor.cites_label.get_text(),
            "Family: III, Genus: II",
        )
        self.assertEqual(get_widget_value(editor.cites_combo), "I")

        editor.destroy()

    def test_init_existing_w_group_label_markup_habit(self):
        family = Family(epithet="Musaceae")
        genus = Genus(epithet="Musa", family=family)
        species = Species(
            genus=genus,
            epithet="acuminata",
            cv_group="AAA",
            cultivar_epithet="Cavendish",
            label_markup="<i>Musa</i> 'Cavendish'",
            habit=Habit(name="Herbaceous", code="HER"),
        )
        self.session.add(species)
        self.session.commit()
        editor = SpeciesEditorDialog(species, self.session)

        self.assertEqual(editor.links_menu_btn.model, species)
        self.assertEqual(editor.synonyms_presenter.model, species)
        self.assertEqual(editor.genus_entry.get_text(), "Musa")
        self.assertEqual(editor.species_entry.get_text(), "acuminata")
        self.assertEqual(editor.cv_group_entry.get_text(), "AAA")
        self.assertTrue(editor.cv_extras_grid.get_visible())
        self.assertTrue(editor.label_markup_expander.get_expanded())
        self.assertTrue(
            editor.label_markup_entry.get_text(),
            "<i>Musa</i> 'Cavendish'",
        )
        self.assertEqual(editor.habit_entry.get_text(), "Herbaceous (HER)")
        self.assertEqual(len(editor.problems), 0)

        editor.destroy()

    @mock.patch("bauble.plugins.plants.ui.species_editor.edit_callback")
    def test_init_is_synonym(self, mock_callback):
        family = Family(epithet="Myrtaceae")
        genus = Genus(epithet="Syzygium", family=family)
        species = Species(
            genus=genus,
            epithet="sp. (East Normanby River P.I.Forster+ PIF10750)",
        )
        species.accepted = Species(genus=genus, epithet="monimioides")
        self.session.add(species)
        self.session.commit()
        editor = SpeciesEditorDialog(species, self.session)

        update_gui()
        child = editor.revealer.get_child()

        self.assertIsInstance(child, YesNoMessageBox)

        # no
        mock_callback.reset_mock()
        child.get_children()[1].get_children()[1].emit("clicked")

        mock_callback.assert_not_called()

        # yes
        child.get_children()[1].get_children()[0].emit("clicked")

        mock_callback.assert_called_once()
        result = self.session.merge(mock_callback.call_args[0][0][0])
        self.assertEqual(str(result), "Syzygium monimioides")

        editor.destroy()

    def test_editor_doesnt_leak(self):
        setup_plants_data()
        editor = SpeciesEditorDialog(
            model=Species(),
            session=db.Session(),
        )
        editor.show()
        editor.emit("response", -6)

        del editor
        update_gui()

        self.assertEqual(
            utils.gc_objects_by_type("SpeciesEditorDialog"),
            [],
            "SpeciesEditorDialog not deleted",
        )

    @mock.patch("bauble.ui.dialogs.message_dialog")
    def test_show_warns_and_bails_if_no_genera(self, mock_dialog):
        editor = SpeciesEditorDialog(
            model=Species(),
            session=db.Session(),
        )
        editor.show()
        mock_dialog.assert_called_once_with(
            "You must first add or import at least one genus into the "
            "database before you can add species.",
            parent=editor,
        )
        del editor

    def test_allow_ok_only(self):
        editor = SpeciesEditorDialog(Species(), self.session)
        editor.allow_ok_only()

        for response in Response:
            widget = editor.get_widget_for_response(response.value)
            if response == Response.OK:
                self.assertTrue(widget.get_visible())
            else:
                self.assertFalse(widget.get_visible())

        editor.destroy()

    def test_can_commit_new(self):
        family = Family(epithet="Myrtaceae")
        genus = Genus(epithet="Syzygium", family=family)
        self.session.add(genus)
        self.session.commit()
        editor = SpeciesEditorDialog(Species(), self.session)

        self.assertFalse(editor.can_commit)

        editor.genus_entry.set_text("Syzygium")

        self.assertFalse(editor.can_commit)

        editor.species_entry.set_text("australe")

        self.assertTrue(editor.can_commit)

        editor.destroy()

        # new cultivar
        editor = SpeciesEditorDialog(Species(), self.session)

        self.assertFalse(editor.can_commit)

        editor.genus_entry.set_text("Syzygium")

        self.assertFalse(editor.can_commit)

        editor.species_entry.set_text("Tiny Trev")

        self.assertTrue(editor.can_commit)

        editor.destroy()

    def test_can_commit_existing(self):
        family = Family(epithet="Myrtaceae")
        genus = Genus(epithet="Syzygium", family=family)
        species = Species(genus=genus, epithet="luehmannii")
        self.session.add(species)
        self.session.commit()

        editor = SpeciesEditorDialog(species, self.session)

        self.assertFalse(editor.can_commit)

        editor.author_entry.set_text("(F.Muell.) L.A.S.Johnson")

        self.assertTrue(editor.can_commit)

        editor.destroy()

    def test_ok_sensitive(self):
        family = Family(epithet="Austrobaileyaceae")
        genus = Genus(epithet="Austrobaileya", family=family)
        species = Species(genus=genus, epithet="scandens")
        self.session.add(species)
        self.session.commit()
        editor = SpeciesEditorDialog(species, db.Session())
        ok_button = editor.get_widget_for_response(-5)

        self.assertFalse(ok_button.get_sensitive())

        editor.destroy()

        species.sp_author = "C.T.White"
        editor = SpeciesEditorDialog(species, db.Session())

        ok_button = editor.get_widget_for_response(-5)

        self.assertTrue(ok_button.get_sensitive())

        editor.destroy()

    def test_on_changed_calls_update(self):
        editor = SpeciesEditorDialog(Species(), self.session)
        with mock.patch.object(editor, "update") as mock_update:
            editor.synonyms_presenter.emit("changed")
            mock_update.assert_called_once()

        editor.destroy()

    def test_update(self):
        family = Family(epithet="Myrtaceae")
        genus = Genus(epithet="Syzygium", family=family)
        species = Species(epithet="australe", genus=genus)
        self.session.add(species)
        self.session.commit()
        editor = SpeciesEditorDialog(Species(genus=genus), self.session)
        # genus only should start with empty species_entry problem
        self.assertEqual(len(editor.problems), 1)
        for problem, widget in editor.problems:
            self.assertEqual(widget, editor.species_entry)
            self.assertTrue(problem.startswith("empty::SpeciesEditorDialog"))

        for response in Response:
            widget = editor.get_widget_for_response(response.value)
            if response == Response.CANCEL:
                self.assertTrue(widget.get_sensitive())
            else:
                self.assertFalse(widget.get_sensitive())

        editor.species_entry.set_text("luehmannii")

        for response in Response:
            widget = editor.get_widget_for_response(response.value)
            self.assertTrue(widget.get_sensitive())

        # set to existing (validate_unique, check_existing)
        editor.species_entry.set_text("australe")
        update_gui()

        self.assertEqual(len(editor.problems), 2)
        for problem, widget in editor.problems:
            self.assertIn(widget, (editor.species_entry, editor.genus_entry))
            self.assertTrue(
                problem.startswith("not_unique::SpeciesEditorDialog")
            )
        self.assertIsInstance(editor.revealer.get_child(), YesNoMessageBox)

        editor.destroy()

    @mock.patch("bauble.plugins.plants.ui.species_editor.edit_callback")
    def test_check_existing_offers_accepted(self, mock_callback):
        orchid = Family(epithet="Orchidaceae")
        pterid = Family(epithet="Pteridaceae")
        genus1 = Genus(family=orchid, epithet="Onychium", author="Blume")
        genus2 = Genus(family=pterid, epithet="Onychium", author="Kaulf.")
        dendrobium = Genus(family=orchid, epithet="Dendrobium", author="Sw.")
        genus1.accepted = dendrobium
        species1 = Species(
            genus=genus1,
            epithet="japonicum",
            sp_author="Blume",
        )
        species1.accepted = Species(
            genus=dendrobium,
            epithet="moniliforme",
            sp_author="(L.) Sw.",
        )
        species2 = Species(
            genus=genus2,
            epithet="japonicum",
            sp_author="(Thunb.) Kunz",
        )
        self.session.add_all([species1, species2])
        self.session.commit()

        editor = SpeciesEditorDialog(Species(genus=genus1), self.session)

        self.assertEqual(editor.genus_entry.get_text(), "Onychium")

        editor.species_entry.set_text("japonicum")
        update_gui()
        child = editor.revealer.get_child()

        self.assertIsInstance(child, YesNoMessageBox)

        # yes
        child.get_children()[1].get_children()[0].emit("clicked")
        mock_callback.assert_called_once()
        result = self.session.merge(mock_callback.call_args[0][0][0])
        accepted = self.session.merge(species2)  # detached after commit
        self.assertEqual(result, accepted)

        editor.destroy()

    @mock.patch("bauble.plugins.plants.ui.species_editor.edit_callback")
    def test_check_existing_cultivar(self, mock_callback):
        # existing has species epithet
        family = Family(epithet="Proteaceae")
        genus = Genus(family=family, epithet="Grevillea")
        species = Species(
            genus=genus,
            epithet="rosmarinifolia",
            cultivar_epithet="Nana",
        )
        self.session.add(species)
        self.session.commit()

        editor = SpeciesEditorDialog(Species(genus=genus), self.session)

        self.assertEqual(editor.genus_entry.get_text(), "Grevillea")
        self.assertEqual(editor.species_entry.get_text(), "")

        editor.cv_epithet_entry.set_text("Nana")
        update_gui()
        child = editor.revealer.get_child()

        self.assertIsInstance(child, YesNoMessageBox)

        # yes
        child.get_children()[1].get_children()[0].emit("clicked")
        mock_callback.assert_called_once()
        result = self.session.merge(mock_callback.call_args[0][0][0])
        accepted = self.session.merge(species)  # detached after commit
        self.assertEqual(result, accepted)

        editor.destroy()

        # existing has no species epithet
        mock_callback.reset_mock()
        species.epithet = None
        self.session.commit()

        editor = SpeciesEditorDialog(
            Species(genus=genus, epithet="rosmarinifolia"),
            self.session,
        )

        self.assertEqual(editor.genus_entry.get_text(), "Grevillea")
        self.assertEqual(editor.species_entry.get_text(), "rosmarinifolia")

        editor.cv_epithet_entry.set_text("Nana")
        update_gui()
        child = editor.revealer.get_child()

        self.assertIsInstance(child, YesNoMessageBox)

        # yes
        child.get_children()[1].get_children()[0].emit("clicked")
        mock_callback.assert_called_once()
        result = self.session.merge(mock_callback.call_args[0][0][0])
        accepted = self.session.merge(species)  # detached after commit
        self.assertEqual(result, accepted)

        editor.destroy()

    def test_check_existing_asks_once(self):
        orchid = Family(epithet="Orchidaceae")
        pterid = Family(epithet="Pteridaceae")
        genus1 = Genus(family=orchid, epithet="Onychium", author="Blume")
        genus2 = Genus(family=pterid, epithet="Onychium", author="Kaulf.")
        dendrobium = Genus(family=orchid, epithet="Dendrobium", author="Sw.")
        genus1.accepted = dendrobium
        species1 = Species(
            genus=genus1,
            epithet="japonicum",
            sp_author="Blume",
        )
        species1.accepted = Species(
            genus=dendrobium,
            epithet="moniliforme",
            sp_author="(L.) Sw.",
        )
        species2 = Species(
            genus=genus2,
            epithet="japonicum",
            sp_author="(Thunb.) Kunz",
        )
        self.session.add_all([species1, species2])
        self.session.commit()

        editor = SpeciesEditorDialog(Species(genus=genus2), self.session)

        self.assertEqual(editor.genus_entry.get_text(), "Onychium")

        editor.species_entry.set_text("japonicum")
        update_gui()
        child = editor.revealer.get_child()

        self.assertIsInstance(child, YesNoMessageBox)

        # no
        child.get_children()[1].get_children()[1].emit("clicked")
        self.assertEqual(editor.genus_entry.get_text(), "Onychium")
        update_gui()

        # not whole text or validate_unique resets last_existing_notified
        editor.author_entry.set_text("(Thunb")
        self.assertFalse(editor.revealer.get_reveal_child())

        editor.destroy()

    def test_validate_unique_w_qualifier(self):
        setup_plants_data()
        editor = SpeciesEditorDialog(Species(), self.session)
        # Eucalyptus gillii s. lat.
        editor.genus_entry.set_text("Eucalyptus")

        self.assertEqual(len(editor.problems), 1)  # no genus

        editor.species_entry.set_text("gillii")

        self.assertEqual(len(editor.problems), 0)

        set_widget_value(editor.qualifier_combo, "s. lat.")

        self.assertEqual(len(editor.problems), 3)

        for problem, widget in editor.problems:
            self.assertIn(
                widget,
                [
                    editor.genus_entry,
                    editor.species_entry,
                    editor.qualifier_combo,
                ],
            )
            self.assertTrue(
                problem.startswith("not_unique::SpeciesEditorDialog")
            )

        editor.destroy()

    def test_validate_unique_w_infrasp(self):
        setup_plants_data()
        editor = SpeciesEditorDialog(Species(), self.session)
        # Encyclia cochleata (L.) Lem\xe9e
        # and
        # Encyclia cochleata (L.) Lem\xe9e var. cochleata
        editor.genus_entry.set_text("Encyclia")

        self.assertEqual(len(editor.problems), 1)  # no genus

        editor.species_entry.set_text("cochleata")

        self.assertEqual(len(editor.problems), 0)

        editor.author_entry.set_text("(L.) Lem\xe9e")

        self.assertEqual(len(editor.problems), 3)

        editor.infrasp_presenter.add_row()
        infrasp1_row = editor.infrasp_presenter.rows[0]
        set_widget_value(infrasp1_row.rank_combo, "var.")

        self.assertEqual(len(editor.problems), 0)

        set_widget_value(infrasp1_row.epithet_entry, "cochleata")

        self.assertEqual(len(editor.problems), 3)
        self.assertEqual(len(infrasp1_row.problems), 2)

        for problem, widget in editor.problems:
            self.assertIn(
                widget,
                [
                    editor.genus_entry,
                    editor.species_entry,
                    editor.author_entry,
                ],
            )
            self.assertTrue(
                problem.startswith("not_unique::SpeciesEditorDialog")
            )
        for problem, widget in infrasp1_row.problems:
            self.assertIn(
                widget,
                [
                    infrasp1_row.rank_combo,
                    infrasp1_row.epithet_entry,
                ],
            )
            self.assertTrue(
                problem.startswith("not_unique::SpeciesEditorDialog")
            )

        editor.destroy()

        # to cover the infrasp author entry
        # Abrus precatorius subsp. africanus Verdc.
        editor = SpeciesEditorDialog(Species(), self.session)

        editor.genus_entry.set_text("Abrus")
        editor.species_entry.set_text("precatorius")
        editor.infrasp_presenter.add_row()
        infrasp1_row = editor.infrasp_presenter.rows[0]
        set_widget_value(infrasp1_row.rank_combo, "subsp.")
        set_widget_value(infrasp1_row.epithet_entry, "africanus")
        set_widget_value(infrasp1_row.author_entry, "Verdc.")

        self.assertEqual(len(editor.problems), 2)
        self.assertEqual(len(infrasp1_row.problems), 3)

        for problem, widget in editor.problems:
            self.assertIn(
                widget,
                [
                    editor.genus_entry,
                    editor.species_entry,
                ],
            )
            self.assertTrue(
                problem.startswith("not_unique::SpeciesEditorDialog")
            )
        for problem, widget in infrasp1_row.problems:
            self.assertIn(
                widget,
                [
                    infrasp1_row.rank_combo,
                    infrasp1_row.epithet_entry,
                    infrasp1_row.author_entry,
                ],
            )
            self.assertTrue(
                problem.startswith("not_unique::SpeciesEditorDialog")
            )

        editor.destroy()

    def test_validate_unique_cv_w_tradename(self):
        setup_plants_data()
        editor = SpeciesEditorDialog(Species(), self.session)
        # Cynodon dactylon × transvaalensis 'DT-1' (PBR) TIFTUF™
        editor.genus_entry.set_text("Cynodon")

        self.assertEqual(len(editor.problems), 1)  # no genus

        editor.species_entry.set_text("dactylon × transvaalensis")

        self.assertEqual(len(editor.problems), 0)

        editor.cv_epithet_entry.set_text("DT-1")

        self.assertEqual(len(editor.problems), 0)

        set_widget_value(editor.pbr_checkbtn, True)

        self.assertEqual(len(editor.problems), 0)

        editor.tradename_entry.set_text("TifTuf")

        self.assertEqual(len(editor.problems), 0)

        set_widget_value(editor.trademark_combo, "™")

        self.assertEqual(len(editor.problems), 5)

        for problem, widget in editor.problems:
            self.assertIn(
                widget,
                [
                    editor.genus_entry,
                    editor.species_entry,
                    editor.cv_epithet_entry,
                    editor.pbr_checkbtn,
                    editor.tradename_entry,
                ],
            )
            self.assertTrue(
                problem.startswith("not_unique::SpeciesEditorDialog")
            )

        editor.destroy()

    def test_validate_unique_cv_w_grex_group(self):
        setup_plants_data()
        editor = SpeciesEditorDialog(Species(), self.session)
        # Bletilla Penway Prelude grex (Penway Dancer Group) 'Ballerina'
        editor.genus_entry.set_text("Bletilla")

        self.assertEqual(len(editor.problems), 1)  # no genus

        editor.grex_entry.set_text("Penway Prelude")

        self.assertEqual(len(editor.problems), 0)

        editor.cv_group_entry.set_text("Penway Dancer")

        self.assertEqual(len(editor.problems), 0)

        editor.cv_epithet_entry.set_text("Ballerina")

        self.assertEqual(len(editor.problems), 4)

        for problem, widget in editor.problems:
            self.assertIn(
                widget,
                [
                    editor.genus_entry,
                    editor.grex_entry,
                    editor.cv_group_entry,
                    editor.cv_epithet_entry,
                ],
            )
            self.assertTrue(
                problem.startswith("not_unique::SpeciesEditorDialog")
            )

        editor.destroy()

    def test_on_comboentry_format(self):
        habit = Habit(name="Herbaceous", code="HER")
        liststore = Gtk.ListStore(object)
        liststore.append([None])
        liststore.append([habit])
        combo = Gtk.ComboBox.new_with_model(liststore)
        editor = SpeciesEditorDialog(Species(), self.session)

        self.assertEqual(editor.on_comboentry_format(combo, 0), "")
        self.assertEqual(
            editor.on_comboentry_format(combo, 1),
            "Herbaceous (HER)",
        )

        editor.destroy()

    def test_on_habit_entry_changed(self):
        importer = CSVRestore()
        from bauble import paths

        default_path = os.path.join(
            paths.lib_dir(), "plugins", "plants", "default"
        )
        importer.start([os.path.join(default_path, "habit.csv")], force=True)
        editor = SpeciesEditorDialog(Species(), self.session)
        editor.habit_entry.set_text("Tre")

        self.assertIsNone(editor.model.habit)

        editor.habit_entry.set_text("Tree (TRE)")

        self.assertEqual(editor.model.habit.name, "Tree")

        editor.destroy()

    def test_custom_fields(self):
        # pylint: disable=protected-access
        meta = BaubleMeta(
            name="_sp_custom1",
            value=(
                "{'field_name': 'nca_status', "
                "'display_name': 'NCA Status', "
                "'values': "
                "('extinct', 'Critically endangered', 'vulnerable', None)}"
            ),
        )
        self.session.add(meta)
        self.session.commit()

        register_custom_column("_sp_custom1")

        family = Family(epithet="Myrtaceae")
        genus = Genus(family=family, epithet="Rhodomytus")
        species = Species(
            genus=genus,
            epithet="psidioides",
            nca_status="Critically endangered",
        )
        self.session.add(species)
        self.session.commit()

        self.assertEqual(species.nca_status, "Critically endangered")
        self.assertEqual(species._sp_custom1, "Critically endangered")

        editor = SpeciesEditorDialog(species, self.session)

        self.assertEqual(editor._sp_custom1_label.get_text(), "NCA Status")
        self.assertEqual(
            get_widget_value(editor._sp_custom1_combo),
            "Critically endangered",
        )

        set_widget_value(editor._sp_custom1_combo, "")

        self.assertEqual(species.nca_status, None)

        # tear down
        self.session.delete(meta)
        self.session.commit()
        register_custom_column("_sp_custom1")
        editor.destroy()

    def test_on_subgenus_entry_changed(self):
        editor = SpeciesEditorDialog(Species(), self.session)
        editor.subgenus_entry.set_text("Foo")

        self.assertEqual(editor.model.subgenus, "Foo")

        editor.destroy()

    def test_subgenus_get_completions(self):
        family = Family(epithet="Poaceae")
        genus1 = Genus(family=family, epithet="Bambusa")
        genus2 = Genus(family=family, epithet="Poa")
        for i in range(30):
            self.session.add(
                Species(
                    genus=genus1,
                    epithet=f"sp{i}",
                    subgenus=f"abcd{i}",
                )
            )
            self.session.add(
                Species(
                    genus=genus2,
                    epithet=f"sp{i}",
                    subgenus="wxyz",
                )
            )
        self.session.commit()
        editor = SpeciesEditorDialog(Species(genus=genus1), self.session)

        completions = editor.subgenus_get_completions("a")
        self.assertEqual(len(completions), 20)
        self.assertTrue(all(i[0].startswith("abcd") for i in completions))

        completions = editor.subgenus_get_completions("abcd11")
        self.assertEqual(len(completions), 1)
        self.assertEqual(completions[0][0], "abcd11")

        completions = editor.subgenus_get_completions("w")
        self.assertEqual(len(completions), 0)

        editor.destroy()

    def test_on_section_entry_changed(self):
        editor = SpeciesEditorDialog(Species(), self.session)
        editor.section_entry.set_text("Foo")

        self.assertEqual(editor.model.section, "Foo")

        editor.destroy()

    def test_section_get_completions(self):
        family = Family(epithet="Poaceae")
        genus = Genus(family=family, epithet="Bambusa")
        for i in range(30):
            self.session.add(
                Species(
                    genus=genus,
                    epithet=f"spA{i}",
                    subgenus="subg1",
                    section=f"abcd{i}",
                )
            )
            self.session.add(
                Species(
                    genus=genus,
                    epithet=f"spB{i}",
                    subgenus="subg2",
                    section="wxyz",
                )
            )
        self.session.commit()
        editor = SpeciesEditorDialog(Species(genus=genus), self.session)

        completions = editor.section_get_completions("a")
        self.assertEqual(len(completions), 20)
        self.assertTrue(all(i[0].startswith("abcd") for i in completions))

        completions = editor.section_get_completions("abcd11")
        self.assertEqual(len(completions), 1)
        self.assertEqual(completions[0][0], "abcd11")

        completions = editor.section_get_completions("w")
        self.assertEqual(completions[0][0], "wxyz")

        editor.subgenus_entry.set_text("subg1")

        completions = editor.section_get_completions("w")
        self.assertEqual(len(completions), 0)
        completions = editor.section_get_completions("a")
        self.assertEqual(len(completions), 20)

        editor.destroy()

    def test_on_subsection_entry_changed(self):
        editor = SpeciesEditorDialog(Species(), self.session)
        editor.subsection_entry.set_text("Foo")

        self.assertEqual(editor.model.subsection, "Foo")

        editor.destroy()

    def test_subsection_get_completions(self):
        family = Family(epithet="Poaceae")
        genus = Genus(family=family, epithet="Bambusa")
        for i in range(30):
            self.session.add(
                Species(
                    genus=genus,
                    epithet=f"spA{i}",
                    subgenus="subg1",
                    section="sect1",
                    subsection=f"abcd{i}",
                )
            )
            self.session.add(
                Species(
                    genus=genus,
                    epithet=f"spB{i}",
                    subgenus="subg2",
                    section="sect2",
                    subsection="wxyz",
                )
            )
        self.session.commit()
        editor = SpeciesEditorDialog(Species(genus=genus), self.session)

        completions = editor.subsection_get_completions("a")
        self.assertEqual(len(completions), 20)
        self.assertTrue(all(i[0].startswith("abcd") for i in completions))

        completions = editor.subsection_get_completions("abcd11")
        self.assertEqual(len(completions), 1)
        self.assertEqual(completions[0][0], "abcd11")

        completions = editor.subsection_get_completions("w")
        self.assertEqual(completions[0][0], "wxyz")

        editor.section_entry.set_text("sect1")

        completions = editor.subsection_get_completions("w")
        self.assertEqual(len(completions), 0)
        completions = editor.subsection_get_completions("a")
        self.assertEqual(len(completions), 20)

        editor.section_entry.set_text("")
        editor.subgenus_entry.set_text("subg2")

        completions = editor.subsection_get_completions("w")
        self.assertEqual(completions[0][0], "wxyz")
        completions = editor.subsection_get_completions("a")
        self.assertEqual(len(completions), 0)

        editor.destroy()

    def test_on_series_entry_changed(self):
        editor = SpeciesEditorDialog(Species(), self.session)
        editor.series_entry.set_text("Foo")

        self.assertEqual(editor.model.series, "Foo")

        editor.destroy()

    def test_series_get_completions(self):
        family = Family(epithet="Poaceae")
        genus = Genus(family=family, epithet="Bambusa")
        for i in range(30):
            self.session.add(
                Species(
                    genus=genus,
                    epithet=f"spA{i}",
                    subgenus="subg1",
                    section="sect1",
                    subsection="subsect1",
                    series=f"abcd{i}",
                )
            )
            self.session.add(
                Species(
                    genus=genus,
                    epithet=f"spB{i}",
                    subgenus="subg2",
                    section="sect2",
                    subsection="subsect2",
                    series="wxyz",
                )
            )
        self.session.commit()
        editor = SpeciesEditorDialog(Species(genus=genus), self.session)

        completions = editor.series_get_completions("a")
        self.assertEqual(len(completions), 20)
        self.assertTrue(all(i[0].startswith("abcd") for i in completions))

        completions = editor.series_get_completions("abcd11")
        self.assertEqual(len(completions), 1)
        self.assertEqual(completions[0][0], "abcd11")

        completions = editor.series_get_completions("w")
        self.assertEqual(completions[0][0], "wxyz")

        editor.subsection_entry.set_text("subsect1")

        completions = editor.series_get_completions("w")
        self.assertEqual(len(completions), 0)
        completions = editor.series_get_completions("a")
        self.assertEqual(len(completions), 20)

        editor.subsection_entry.set_text("")
        editor.section_entry.set_text("sect2")

        completions = editor.series_get_completions("w")
        self.assertEqual(completions[0][0], "wxyz")
        completions = editor.series_get_completions("a")
        self.assertEqual(len(completions), 0)

        editor.section_entry.set_text("")
        editor.subgenus_entry.set_text("subg1")

        completions = editor.series_get_completions("w")
        self.assertEqual(len(completions), 0)
        completions = editor.series_get_completions("a")
        self.assertEqual(len(completions), 20)

        editor.destroy()

    def test_on_subseries_entry_changed(self):
        editor = SpeciesEditorDialog(Species(), self.session)
        editor.subseries_entry.set_text("Foo")

        self.assertEqual(editor.model.subseries, "Foo")

        editor.destroy()

    def test_subseries_get_completions(self):
        family = Family(epithet="Poaceae")
        genus = Genus(family=family, epithet="Bambusa")
        for i in range(30):
            self.session.add(
                Species(
                    genus=genus,
                    epithet=f"spA{i}",
                    subgenus="subg1",
                    section="sect1",
                    subsection="subsect1",
                    series="series1",
                    subseries=f"abcd{i}",
                )
            )
            self.session.add(
                Species(
                    genus=genus,
                    epithet=f"spB{i}",
                    subgenus="subg2",
                    section="sect2",
                    subsection="subsect2",
                    series="series2",
                    subseries="wxyz",
                )
            )
        self.session.commit()
        editor = SpeciesEditorDialog(Species(genus=genus), self.session)

        completions = editor.subseries_get_completions("a")
        self.assertEqual(len(completions), 20)
        self.assertTrue(all(i[0].startswith("abcd") for i in completions))

        completions = editor.subseries_get_completions("abcd11")
        self.assertEqual(len(completions), 1)
        self.assertEqual(completions[0][0], "abcd11")

        completions = editor.subseries_get_completions("w")
        self.assertEqual(completions[0][0], "wxyz")

        editor.series_entry.set_text("series2")

        completions = editor.subseries_get_completions("w")
        self.assertEqual(completions[0][0], "wxyz")
        completions = editor.subseries_get_completions("a")
        self.assertEqual(len(completions), 0)

        editor.series_entry.set_text("")
        editor.subsection_entry.set_text("subsect1")

        completions = editor.subseries_get_completions("w")
        self.assertEqual(len(completions), 0)
        completions = editor.subseries_get_completions("a")
        self.assertEqual(len(completions), 20)

        editor.subsection_entry.set_text("")
        editor.section_entry.set_text("sect2")

        completions = editor.subseries_get_completions("w")
        self.assertEqual(completions[0][0], "wxyz")
        completions = editor.subseries_get_completions("a")
        self.assertEqual(len(completions), 0)

        editor.section_entry.set_text("")
        editor.subgenus_entry.set_text("subg1")

        completions = editor.subseries_get_completions("w")
        self.assertEqual(len(completions), 0)
        completions = editor.subseries_get_completions("a")
        self.assertEqual(len(completions), 20)

        editor.destroy()

    def test_genus_get_completions(self):
        setup_plants_data()
        editor = SpeciesEditorDialog(Species(), self.session)
        result = editor.genus_get_completions("Cy")
        self.assertEqual([str(i[0]) for i in result], ["Cynodon"])

        editor.destroy()

    def test_on_genus_entry_changed_is_synonym(self):
        family = Family(epithet="Myrtaceae")
        genus = Genus(family=family, epithet="Callistemon")
        genus.accepted = Genus(family=family, epithet="Melaleuca")
        self.session.add(genus)
        self.session.commit()
        editor = SpeciesEditorDialog(Species(), self.session)

        editor.genus_entry.set_text("Callistemon")
        update_gui()
        child = editor.revealer.get_child()

        self.assertIsInstance(child, YesNoMessageBox)

        # no
        child.get_children()[1].get_children()[1].emit("clicked")
        self.assertEqual(editor.genus_entry.get_text(), "Callistemon")

        # yes
        editor.genus_entry.set_text("")
        editor.genus_entry.set_text("Callistemon")
        child.get_children()[1].get_children()[0].emit("clicked")
        self.assertEqual(editor.genus_entry.get_text(), "Melaleuca")

        editor.destroy()

    def test_on_genus_entry_paste(self):
        setup_plants_data()
        species = Species()
        self.session.add(species)
        editor = SpeciesEditorDialog(species, self.session)

        editor.genus_entry.set_text(" Encyclia ")
        editor.on_genus_entry_paste(editor.genus_entry)
        update_gui()

        self.assertEqual(editor.genus_entry.get_text(), "Encyclia")
        self.assertEqual(species.genus.epithet, "Encyclia")

        editor.genus_entry.set_text("Encyclia cochleata var. cochleata")
        editor.on_genus_entry_paste(editor.genus_entry)
        update_gui()

        self.assertEqual(editor.genus_entry.get_text(), "Encyclia")
        self.assertEqual(species.genus.epithet, "Encyclia")
        self.assertEqual(species.epithet, "cochleata")
        self.assertEqual(species.infrasp1_rank, "var.")
        self.assertEqual(species.infrasp1, "cochleata")

        editor.genus_entry.set_text(
            "Banksia spinulosa var. collina (R.Br.) A.S.George"
        )
        editor.on_genus_entry_paste(editor.genus_entry)
        update_gui()

        self.assertEqual(editor.genus_entry.get_text(), "Banksia")
        self.assertEqual(species.genus.epithet, "Banksia")
        self.assertEqual(species.epithet, "spinulosa")
        self.assertEqual(species.infrasp1_rank, "var.")
        self.assertEqual(species.infrasp1, "collina")
        self.assertEqual(species.infrasp1_author, "(R.Br.) A.S.George")

        editor.genus_entry.set_text(
            "Abelia × grandiflora (Rovelli ex André) Rehder"
        )
        editor.on_genus_entry_paste(editor.genus_entry)
        update_gui()

        self.assertEqual(editor.genus_entry.get_text(), "Abelia")
        self.assertEqual(species.hybrid, "×")
        self.assertEqual(species.epithet, "grandiflora")
        self.assertEqual(species.sp_author, "(Rovelli ex André) Rehder")

        editor.genus_entry.set_text("+ Crataegomespilus dardarii")
        editor.on_genus_entry_paste(editor.genus_entry)
        update_gui()

        self.assertEqual(editor.genus_entry.get_text(), "+ Crataegomespilus")
        self.assertIsNone(species.hybrid)
        self.assertEqual(species.epithet, "dardarii")
        self.assertEqual(species.sp_author, None)

        editor.genus_entry.set_text(
            "\nFicus rubiginosa Desf. ex Vent. forma rubiginosa\n"
        )
        editor.on_genus_entry_paste(editor.genus_entry)
        update_gui()

        self.assertEqual(editor.genus_entry.get_text(), "Ficus")
        self.assertEqual(species.epithet, "rubiginosa")
        self.assertEqual(species.sp_author, "Desf. ex Vent.")
        self.assertEqual(species.infrasp1_rank, "f.")
        self.assertEqual(species.infrasp1, "rubiginosa")

        editor.genus_entry.set_text("some random string with no meaning")
        editor.on_genus_entry_paste(editor.genus_entry)
        update_gui()

        self.assertEqual(
            editor.genus_entry.get_text(), "some random string with no meaning"
        )
        # doesn't change the other fields
        self.assertEqual(species.epithet, "rubiginosa")
        self.assertEqual(species.sp_author, "Desf. ex Vent.")
        self.assertEqual(species.infrasp1_rank, "f.")
        self.assertEqual(species.infrasp1, "rubiginosa")

        editor.genus_entry.set_text("Melaleuca viminalis")
        editor.on_genus_entry_paste(editor.genus_entry)
        update_gui()

        self.assertEqual(editor.genus_entry.get_text(), "Melaleuca")
        self.assertEqual(species.epithet, "viminalis")
        # resets other fields
        self.assertEqual(species.sp_author, None)
        self.assertIsNone(species.infrasp1_rank)
        self.assertIsNone(species.infrasp1)

        editor.destroy()

    @mock.patch("bauble.plugins.plants.ui.species_editor.edit_callback")
    def test_on_species_entry_changed_existing(self, mock_callback):
        family = Family(epithet="Proteaceae")
        genus = Genus(epithet="Banksia", family=family)
        species = Species(epithet="robusta", genus=genus)
        self.session.add(species)
        self.session.commit()
        editor = SpeciesEditorDialog(Species(), self.session)
        editor.genus_entry.set_text("Banksia")
        editor.species_entry.set_text("robusta")

        self.assertEqual(editor.model.epithet, "robusta")
        self.assertEqual(len(editor.problems), 2)

        update_gui()
        child = editor.revealer.get_child()

        self.assertIsInstance(child, YesNoMessageBox)

        # no
        mock_callback.reset_mock()
        child.get_children()[1].get_children()[1].emit("clicked")

        mock_callback.assert_not_called()

        # yes
        editor.species_entry.set_text("")
        editor.species_entry.set_text("robusta")
        child.get_children()[1].get_children()[0].emit("clicked")

        mock_callback.assert_called_once()

        editor.destroy()

    def test_on_infrasp_add_clicked(self):
        editor = SpeciesEditorDialog(Species(), self.session)

        self.assertTrue(editor.infrasp_presenter.add_button.get_sensitive())
        self.assertEqual(editor.infrasp_presenter.rows, [])

        editor.infrasp_presenter.add_button.emit("clicked")

        self.assertTrue(editor.infrasp_presenter.add_button.get_sensitive())
        self.assertEqual(len(editor.infrasp_presenter.rows), 1)

        editor.infrasp_presenter.add_button.emit("clicked")

        self.assertTrue(editor.infrasp_presenter.add_button.get_sensitive())
        self.assertEqual(len(editor.infrasp_presenter.rows), 2)

        editor.infrasp_presenter.add_button.emit("clicked")

        self.assertTrue(editor.infrasp_presenter.add_button.get_sensitive())
        self.assertEqual(len(editor.infrasp_presenter.rows), 3)

        editor.infrasp_presenter.add_button.emit("clicked")

        self.assertFalse(editor.infrasp_presenter.add_button.get_sensitive())
        self.assertEqual(len(editor.infrasp_presenter.rows), 4)

        for i in range(1, 5):
            self.assertIsNone(getattr(editor.model, f"infrasp{i}"))
            self.assertIsNone(getattr(editor.model, f"infrasp{i}_rank"))
            self.assertIsNone(getattr(editor.model, f"infrasp{i}_author"))

        editor.destroy()

    def test_on_infrasp_presenter_can_commit(self):
        family = Family(epithet="Testaceae")
        genus = Genus(family=family, epithet="testia")
        self.session.add(genus)
        self.session.commit()
        editor = SpeciesEditorDialog(Species(genus=genus), self.session)
        self.assertFalse(editor.can_commit)

        editor.infrasp_presenter.add_button.emit("clicked")

        editor.infrasp_presenter.rows[0].epithet_entry.set_text("test")
        self.assertTrue(editor.can_commit)
        editor.infrasp_presenter.rows[0].epithet_entry.set_text("")
        self.assertFalse(editor.can_commit)

        editor.destroy()

    def test_on_infrasp_remove_clicked_in_sequence(self):
        family = Family(epithet="Testaceae")
        genus = Genus(family=family, epithet="Testia")
        species = Species(
            genus=genus,
            epithet="testii",
            infrasp1_rank="subsp.",
            infrasp1="testiana",
            infrasp2_rank="var.",
            infrasp2="testianis",
            infrasp3_rank="subvar.",
            infrasp3="testiania",
            infrasp4_rank="f.",
            infrasp4="varigata",
        )
        self.session.add(species)
        self.session.commit()
        editor = SpeciesEditorDialog(species, self.session)

        self.assertFalse(editor.infrasp_presenter.add_button.get_sensitive())
        self.assertEqual(len(editor.infrasp_presenter.rows), 4)

        editor.infrasp_presenter.rows[-1].remove_button.emit("clicked")

        self.assertEqual(species.infrasp4, None)
        self.assertEqual(species.infrasp4_rank, None)
        self.assertEqual(species.infrasp4_author, None)
        self.assertTrue(editor.infrasp_presenter.add_button.get_sensitive())
        self.assertEqual(len(editor.infrasp_presenter.rows), 3)

        editor.infrasp_presenter.rows[-1].remove_button.emit("clicked")

        self.assertEqual(species.infrasp3, None)
        self.assertEqual(species.infrasp3_rank, None)
        self.assertEqual(species.infrasp3_author, None)
        self.assertTrue(editor.infrasp_presenter.add_button.get_sensitive())
        self.assertEqual(len(editor.infrasp_presenter.rows), 2)

        editor.infrasp_presenter.rows[-1].remove_button.emit("clicked")

        self.assertEqual(species.infrasp2, None)
        self.assertEqual(species.infrasp2_rank, None)
        self.assertEqual(species.infrasp2_author, None)
        self.assertTrue(editor.infrasp_presenter.add_button.get_sensitive())
        self.assertEqual(len(editor.infrasp_presenter.rows), 1)

        editor.infrasp_presenter.rows[-1].remove_button.emit("clicked")

        self.assertEqual(species.infrasp1, None)
        self.assertEqual(species.infrasp1_rank, None)
        self.assertEqual(species.infrasp1_author, None)
        self.assertTrue(editor.infrasp_presenter.add_button.get_sensitive())
        self.assertEqual(len(editor.infrasp_presenter.rows), 0)

        editor.destroy()

    def test_on_infrasp_remove_clicked_out_of_sequence(self):
        family = Family(epithet="Testaceae")
        genus = Genus(family=family, epithet="Testia")
        species = Species(
            genus=genus,
            epithet="testii",
            infrasp1_rank="subsp.",
            infrasp1="testiana",
            infrasp2_rank="var.",
            infrasp2="testianis",
            infrasp3_rank="subvar.",
            infrasp3="testiania",
            infrasp4_rank="f.",
            infrasp4="variagata",
        )
        self.session.add(species)
        self.session.commit()
        editor = SpeciesEditorDialog(species, self.session)

        self.assertFalse(editor.infrasp_presenter.add_button.get_sensitive())

        editor.infrasp_presenter.rows[2].remove_button.emit("clicked")

        self.assertTrue(editor.infrasp_presenter.add_button.get_sensitive())
        self.assertEqual(species.infrasp4_rank, None)
        self.assertEqual(species.infrasp4, None)
        self.assertEqual(species.infrasp3_rank, "f.")
        self.assertEqual(species.infrasp3, "variagata")
        self.assertEqual(species.infrasp2_rank, "var.")
        self.assertEqual(species.infrasp2, "testianis")
        self.assertEqual(species.infrasp1_rank, "subsp.")
        self.assertEqual(species.infrasp1, "testiana")

        editor.infrasp_presenter.rows[1].remove_button.emit("clicked")

        self.assertEqual(species.infrasp4_rank, None)
        self.assertEqual(species.infrasp4, None)
        self.assertEqual(species.infrasp3_rank, None)
        self.assertEqual(species.infrasp3, None)
        self.assertEqual(species.infrasp2_rank, "f.")
        self.assertEqual(species.infrasp2, "variagata")
        self.assertEqual(species.infrasp1_rank, "subsp.")
        self.assertEqual(species.infrasp1, "testiana")

        editor.infrasp_presenter.rows[0].remove_button.emit("clicked")
        self.assertEqual(str(species), "Testia testii f. variagata")

        editor.destroy()

    def test_on_expand_cv_button_clicked(self):
        editor = SpeciesEditorDialog(Species(), self.session)

        editor.on_expand_cv_button_clicked(None)
        icon_name = editor.expand_btn_icon.get_icon_name()[0]
        self.assertEqual("pan-start-symbolic", icon_name)
        self.assertTrue(editor.cv_extras_grid.get_visible())

        editor.on_expand_cv_button_clicked(None)
        icon_name = editor.expand_btn_icon.get_icon_name()[0]
        self.assertEqual("pan-end-symbolic", icon_name)
        self.assertFalse(editor.cv_extras_grid.get_visible())

        editor.destroy()

    def test_refresh_fullname_label(self):
        # toggles prev_sp_box visibility
        # sets sp_fullname_label to markup
        # resets label_markup if markup has changed
        family = Family(epithet="Orchidaceae")
        genus = Genus(family=family, epithet="Paphiopedilum")
        species = Species(
            genus=genus,
            grex="Jim Kie",
            cultivar_epithet="Springwater",
        )
        species.label_markup = "Test markup"
        self.session.add(species)
        self.session.commit()
        editor = SpeciesEditorDialog(species, self.session)
        # on init if a label_markup exists then the label should set and the
        # expander expand
        self.assertTrue(editor.label_markup_expander.get_expanded())
        self.assertEqual(
            editor.label_markup_label.get_label(),
            "Test markup",
        )

        editor.refresh_fullname_label()  # should not reset label_markup
        self.assertEqual(editor.model.label_markup, "Test markup")
        # should not trigger change on the label yet
        editor.model.grex = "Test Grex"
        self.assertEqual(
            editor.fullname_label.get_label(),
            "<i>Paphiopedilum</i> Jim Kie grex 'Springwater'",
        )
        self.assertFalse(editor.prev_sp_box.get_visible())

        editor.refresh_fullname_label()
        self.assertEqual(
            editor.fullname_label.get_label(),
            "<i>Paphiopedilum</i> Test Grex grex 'Springwater'",
        )
        self.assertIsNone(editor.model.label_markup)

        editor.destroy()

    def test_on_markup_entry_changed(self):
        family = Family(epithet="Poaceae")
        genus = Genus(family=family, epithet="Cynodon")
        species = Species(
            genus=genus,
            epithet="dactylon × transvaalensis",
            cultivar_epithet="DT-1",
            pbr_protected=True,
            trade_name="TifTuf",
            trademark_symbol="™",
        )
        self.session.add(species)
        self.session.commit()
        editor = SpeciesEditorDialog(species, self.session)

        self.assertEqual(editor.label_markup_entry.get_name(), "GtkEntry")

        editor.label_markup_entry.set_text(species.markup())

        self.assertIsNone(species.label_markup)
        self.assertEqual(editor.label_markup_entry.get_name(), "unsaved-entry")
        self.assertEqual(len(editor.problems), 0)

        editor.label_markup_entry.set_text("<><bad<markup")

        self.assertEqual(editor.label_markup_entry.get_name(), "GtkEntry")
        self.assertEqual(len(editor.problems), 1)
        self.assertIn(
            (editor.PROBLEM_INVALID_MARKUP, editor.label_markup_entry),
            editor.problems,
        )
        self.assertEqual(editor.label_markup_label.get_text(), "--")
        self.assertIsNone(species.label_markup)

        valid_markup = "<i>Some</i> <small>valid markup</small> entry"
        editor.label_markup_entry.set_text(valid_markup)

        self.assertEqual(editor.label_markup_entry.get_name(), "GtkEntry")
        self.assertEqual(len(editor.problems), 0)
        self.assertEqual(editor.label_markup_label.get_label(), valid_markup)
        self.assertEqual(species.label_markup, valid_markup)

        editor.destroy()

    def test_on_markup_button_clicked(self):
        family = Family(epithet="Poaceae")
        genus = Genus(family=family, epithet="Cynodon")
        species = Species(
            genus=genus,
            epithet="dactylon × transvaalensis",
            cultivar_epithet="DT-1",
            pbr_protected=True,
            trade_name="TifTuf",
            trademark_symbol="™",
        )
        self.session.add(species)
        self.session.commit()

        editor = SpeciesEditorDialog(species, self.session)

        self.assertEqual(editor.label_markup_entry.get_text(), "")

        editor.on_markup_button_clicked(None)

        self.assertEqual(
            editor.label_markup_entry.get_text(),
            species.markup(),
        )

        editor.destroy()

    @mock.patch("bauble.ui.dialogs.message_details_dialog")
    def test_on_response_ok(self, mock_dlog):
        family = Family(epithet="Myrtaceae")
        genus = Genus(family=family, epithet="Syzygium")
        self.session.add(genus)
        self.session.commit()
        editor = SpeciesEditorDialog(Species(), self.session)
        # fails no epithet or genus, use emit here to avoid warning due to:
        # `dialog.stop_emission_by_name("response")`
        editor.emit("response", Response.OK)

        update_gui()
        mock_dlog.assert_called_once()
        self.assertEqual(str(editor.model), "")
        self.assertIn(editor.model, editor.session.new)
        mock_dlog.reset_mock()

        editor.model.genus = genus
        editor.species_entry.set_text("luehmannii")
        self.assertFalse(editor.on_response(editor, Response.OK))

        update_gui()
        mock_dlog.assert_not_called()
        self.assertEqual(str(editor.model), "Syzygium luehmannii")
        self.assertNotIn(editor.model, editor.session.new)

        editor.destroy()

    @mock.patch("bauble.ui.dialogs.message_details_dialog")
    def test_on_response_ok_add_syn_chkbox(self, mock_dlog):
        family = Family(epithet="Myrtaceae")
        genus1 = Genus(family=family, epithet="Callistemon")
        genus2 = Genus(family=family, epithet="Melaleuca")
        species = Species(genus=genus1, epithet="viminalis")
        self.session.add_all([genus2, species])
        self.session.commit()
        self.assertEqual(
            self.session.execute(
                select(func.count()).select_from(Species)
            ).scalar(),
            1,
        )
        editor = SpeciesEditorDialog(species, self.session)
        editor.genus_entry.set_text("Melaleuca")

        self.assertEqual(len(species.synonyms), 0)
        self.assertEqual(species.genus, genus2)
        self.assertEqual(species.epithet, "viminalis")
        self.assertEqual(
            editor.prevname_label.get_text(),
            "Callistemon viminalis (previous name)",
        )

        editor.add_syn_chkbox.set_active(True)

        self.assertFalse(editor.on_response(editor, Response.OK))

        update_gui()
        mock_dlog.assert_not_called()
        species = self.session.merge(species)
        genus2 = self.session.merge(genus2)
        genus1 = self.session.merge(genus1)
        self.assertNotIn(editor.model, editor.session.new)
        self.assertEqual(species.genus, genus2)
        self.assertEqual(species.epithet, "viminalis")
        self.assertEqual(len(species.synonyms), 1)
        self.assertEqual(species.synonyms[0].genus, genus1)
        self.assertEqual(species.synonyms[0].epithet, "viminalis")
        self.assertEqual(
            self.session.execute(
                select(func.count()).select_from(Species)
            ).scalar(),
            2,
        )

        editor.destroy()

    def test_on_response_cancel(self):
        family = Family(epithet="Myrtaceae")
        genus = Genus(family=family, epithet="Syzygium")
        species = Species()
        self.session.add(genus)
        self.session.commit()
        editor = SpeciesEditorDialog(species, self.session)

        self.assertIn(editor.model, editor.session)
        self.assertIn(editor.model, editor.session.new)

        editor.model.genus = genus
        editor.species_entry.set_text("luehmannii")
        self.assertFalse(editor.on_response(editor, Response.CANCEL))
        self.assertNotIn(editor.model, editor.session.new)

        editor.destroy()

    @mock.patch("bauble.plugins.plants.ui.species_editor.create_species")
    def test_on_response_next(self, mock_callback):
        mock_callback.return_value = False
        family = Family(epithet="Myrtaceae")
        genus = Genus(family=family, epithet="Syzygium")
        self.session.add(genus)
        self.session.commit()
        editor = SpeciesEditorDialog(
            Species(genus=genus, epithet="luehmannii"),
            self.session,
        )
        self.assertIn(editor.model, editor.session.new)

        self.assertFalse(editor.on_response(editor, Response.NEXT))
        self.assertEqual(str(editor.model), "Syzygium luehmannii")
        self.assertNotIn(editor.model, editor.session.new)

        update_gui()

        mock_callback.assert_called_once_with(genus=genus)

        editor.destroy()

    @mock.patch(
        "bauble.plugins.plants.ui.species_editor.add_accession_callback"
    )
    def test_on_response_add(self, mock_callback):
        mock_callback.return_value = False
        family = Family(epithet="Myrtaceae")
        genus = Genus(family=family, epithet="Syzygium")
        self.session.add(genus)
        self.session.commit()
        editor = SpeciesEditorDialog(
            Species(genus=genus, epithet="luehmannii"),
            self.session,
        )
        self.assertIn(editor.model, editor.session.new)

        self.assertFalse(editor.on_response(editor, Response.ADD))
        self.assertEqual(str(editor.model), "Syzygium luehmannii")
        self.assertNotIn(editor.model, editor.session.new)

        update_gui()

        mock_callback.assert_called_once_with([editor.model])

        editor.destroy()

    @mock.patch("bauble.plugins.plants.ui.genus_editor.GenusEditorDialog")
    def test_on_genus_add_button_clicked(self, mock_editor):
        # test bails
        mock_editor().run.return_value = Gtk.ResponseType.CANCEL
        mock_editor.reset_mock()
        family = Family(epithet="Myrtaceae")
        genus = Genus(family=family, epithet="Syzygium")
        species = Species(epithet="luehmannii")
        self.session.add(species)

        editor = SpeciesEditorDialog(species, self.session)
        editor.on_genus_add_button_clicked(None)

        mock_editor.assert_called_once()
        self.assertEqual(editor.genus_entry.get_text(), "")

        editor.destroy()

        # test success
        mock_editor.reset_mock()

        editor = SpeciesEditorDialog(species, self.session)
        editor.genus_entry.set_text("Acme")
        mock_editor().run.return_value = Gtk.ResponseType.OK
        mock_editor().model = genus
        mock_editor.reset_mock()
        editor.on_genus_add_button_clicked(None)

        mock_editor.assert_called_once()
        self.assertEqual(editor.genus_entry.get_text(), "Syzygium")

        editor.destroy()


class FunctionTests(BaubleTestCase):
    def test_split_taxon_full_name(self):
        self.assertIsNone(
            split_taxon_full_name(""),
        )
        self.assertIsNone(
            split_taxon_full_name("Encyclia "),
        )
        self.assertIsNone(
            split_taxon_full_name(" cochleata"),
        )
        self.assertEqual(
            split_taxon_full_name("Encyclia cochleata"),
            Name(
                genus="Encyclia",
                species="cochleata",
            ),
        )
        self.assertEqual(
            split_taxon_full_name("Campyloneurum × alapense"),
            Name(
                genus="Campyloneurum",
                species_hybrid="×",
                species="alapense",
            ),
        )
        self.assertEqual(
            split_taxon_full_name("Campyloneurum ×alapense"),
            Name(
                species="alapense",
                species_hybrid="×",
                genus="Campyloneurum",
            ),
        )
        self.assertEqual(
            split_taxon_full_name("Encyclia cochleata var. cochleata"),
            Name(
                genus="Encyclia",
                species="cochleata",
                infrasp_rank="var.",
                infrasp_epithet="cochleata",
            ),
        )
        self.assertEqual(
            split_taxon_full_name("+ Crataegomespilus dardarii"),
            Name(
                genus="Crataegomespilus",
                genus_hybrid="+",
                species="dardarii",
            ),
        )
        self.assertEqual(
            split_taxon_full_name("+Crataegomespilus dardarii"),
            Name(
                genus="Crataegomespilus",
                genus_hybrid="+",
                species="dardarii",
            ),
        )
        self.assertEqual(
            split_taxon_full_name(
                "Acmella grandiflora var. discoidea R.K.Jansen"
            ),
            Name(
                genus="Acmella",
                species="grandiflora",
                infrasp_rank="var.",
                infrasp_epithet="discoidea",
                infrasp_author="R.K.Jansen",
            ),
        )
        self.assertEqual(
            split_taxon_full_name(
                "Camellia pingguoensis var. terminalis (J.Y.Liang & Z.M.Su) "
                "T.L.Ming & W.J.Zhang"
            ),
            Name(
                genus="Camellia",
                species="pingguoensis",
                infrasp_rank="var.",
                infrasp_epithet="terminalis",
                infrasp_author="(J.Y.Liang & Z.M.Su) T.L.Ming & W.J.Zhang",
            ),
        )
        self.assertEqual(
            split_taxon_full_name(
                "Acmena hemilampra (F.Muell. ex F.M.Bailey) Merr. & "
                "L.M.Perry subsp. hemilampra"
            ),
            Name(
                genus="Acmena",
                species="hemilampra",
                species_author="(F.Muell. ex F.M.Bailey) Merr. & L.M.Perry",
                infrasp_rank="subsp.",
                infrasp_epithet="hemilampra",
            ),
        )
        self.assertEqual(
            split_taxon_full_name(
                "× Hesperotropsis leylandii "
                "(A.B.Jacks. & Dallim.) Garland & Gerry Moore"
            ),
            Name(
                genus_hybrid="×",
                genus="Hesperotropsis",
                species="leylandii",
                species_author="(A.B.Jacks. & Dallim.) Garland & Gerry Moore",
            ),
        )
        # translates
        self.assertEqual(
            split_taxon_full_name(
                "Ficus rubiginosa Desf. ex Vent. forma rubiginosa"
            ),
            Name(
                genus="Ficus",
                species="rubiginosa",
                species_author="Desf. ex Vent.",
                infrasp_rank="f.",
                infrasp_epithet="rubiginosa",
            ),
        )
        self.assertEqual(
            split_taxon_full_name("Acmena hemilampra ssp. hemilampra"),
            Name(
                genus="Acmena",
                species="hemilampra",
                infrasp_rank="subsp.",
                infrasp_epithet="hemilampra",
            ),
        )

    def test_edit_callback(self):
        caricaceae = Family(family="Caricaceae")
        gen = Genus(epithet="Carica", family=caricaceae)
        sp = Species(epithet="papaya", genus=gen)
        self.session.add(sp)
        self.session.flush()

        with mock.patch.object(edit_callback, "dialog_class") as mock_editor:

            self.assertFalse(edit_callback([sp]))
            mock_editor.assert_called_once()
            self.assertEqual(mock_editor.call_args.kwargs["model"], sp)
            mock_editor().show.assert_called_once()

    def test_add_accession_callback(self):
        caricaceae = Family(family="Caricaceae")
        gen = Genus(epithet="Carica", family=caricaceae)
        sp = Species(epithet="papaya", genus=gen)
        vern = VernacularName(name="Pawpaw")
        sp.default_vernacular_name = vern
        self.session.add(sp)
        self.session.flush()

        from ...garden import Accession
        from ..ui.species_editor import add_accession_callback

        with mock.patch(
            "bauble.plugins.garden.accession.AccessionEditor"
        ) as mock_edit:
            mock_edit().start.return_value = None

            self.assertFalse(add_accession_callback([sp]))
            acc = mock_edit.call_args.kwargs["model"]
            self.assertIsInstance(acc, Accession)
            self.assertEqual(acc.species, sp)
            mock_edit.reset_mock()

            mock_edit().start.return_value = True
            self.assertTrue(add_accession_callback([vern]))
            acc = mock_edit.call_args.kwargs["model"]
            self.assertIsInstance(acc, Accession)
            self.assertEqual(acc.species, sp)
