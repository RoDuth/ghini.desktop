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
Plant editor tests
"""
from unittest import mock

from gi.repository import Gtk

from bauble import db
from bauble import utils
from bauble.plugins.plants.family import Family
from bauble.plugins.plants.genus import Genus
from bauble.plugins.plants.species import Species
from bauble.test import BaubleTestCase
from bauble.test import update_gui
from bauble.ui.presenter import Response
from bauble.ui.widgets.message import YesNoMessageBox

from ..accession import Accession
from ..location import Location
from ..plant import Plant
from ..plant import added_reasons
from ..plant import deleted_reasons
from ..plant import new_plt_reasons
from ..plant import transfer_reasons
from ..ui.plant_editor import PlantEditorDialog
from ..ui.plant_editor import edit_callback


class PlantEditorDialogTests(BaubleTestCase):
    @mock.patch("bauble.gui")
    def test_init_existing(self, mock_gui):
        mock_gui.window = Gtk.Window()
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
        editor = PlantEditorDialog(plant, self.session)

        self.assertEqual(editor.get_transient_for(), mock_gui.window)
        self.assertEqual(editor.map_menu_btn.model, plant)
        self.assertEqual(editor.notes_presenter.model, plant)
        self.assertEqual(editor.pictures_presenter.model, plant)
        self.assertEqual(editor.pictures_presenter.prop, "pictures")
        self.assertEqual(editor.code_entry.get_text(), "1")
        self.assertEqual(editor.accession_entry.get_text(), "2001.0001")
        self.assertEqual(len(editor.problems), 0)

        editor.destroy()

    def test_init_existing_dead(self):
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
            quantity=0,
        )
        self.session.add(plant)
        self.session.commit()
        editor = PlantEditorDialog(plant, self.session)
        update_gui()

        self.assertEqual(editor.map_menu_btn.model, plant)
        self.assertEqual(editor.notes_presenter.model, plant)
        self.assertEqual(editor.pictures_presenter.model, plant)
        self.assertEqual(editor.pictures_presenter.prop, "pictures")
        self.assertEqual(editor.code_entry.get_text(), "1")
        self.assertEqual(editor.accession_entry.get_text(), "2001.0001")
        self.assertEqual(len(editor.problems), 0)
        child = editor.revealer.get_child()
        self.assertEqual(editor.quantity_entry.get_text(), "0")
        self.assertIsInstance(child, YesNoMessageBox)
        self.assertFalse(editor.note_book.get_sensitive())

        # no
        child.get_children()[1].get_children()[1].emit("clicked")

        self.assertFalse(editor.note_book.get_sensitive())

        # yes
        editor.code_entry.set_text("")
        editor.code_entry.set_text("2")
        update_gui()
        child.get_children()[1].get_children()[0].emit("clicked")

        self.assertTrue(editor.note_book.get_sensitive())

        editor.destroy()

    def test_init_new(self):
        plant = Plant()
        editor = PlantEditorDialog(plant, self.session)

        self.assertTrue(editor.map_menu_btn.model)
        self.assertTrue(editor.notes_presenter.model)
        self.assertTrue(editor.pictures_presenter.model)
        self.assertEqual(editor.pictures_presenter.prop, "pictures")
        self.assertEqual(editor.code_entry.get_text(), "")
        self.assertEqual(editor.accession_entry.get_text(), "")
        self.assertEqual(len(editor.problems), 2)
        for problem, widget in editor.problems:
            self.assertIn(
                widget,
                [
                    editor.location_comboentry.get_child(),
                    editor.accession_entry,
                ],
            )
            self.assertTrue(
                problem.startswith(
                    "not_matched::on_completion_entry_matched::PlantEditorD"
                )
                or problem.startswith(
                    "not_matched::on_location_combo_changed::PlantEditorD",
                ),
                problem,
            )

        editor.destroy()

    def test_editor_doesnt_leak(self):
        editor = PlantEditorDialog(
            model=Plant(),
            session=db.Session(),
        )
        editor.show()
        editor.emit("response", Response.CANCEL)

        del editor
        update_gui()

        self.assertEqual(
            utils.gc_objects_by_type("PlantEditorDialog"),
            [],
            "PlantEditorDialog not deleted",
        )

    def test_allow_ok_only(self):
        editor = PlantEditorDialog(Plant(), self.session)
        editor.allow_ok_only()

        for response in Response:
            widget = editor.get_widget_for_response(response.value)
            if response == Response.OK:
                self.assertTrue(widget.get_visible())
            elif widget:
                self.assertFalse(widget.get_visible())

        editor.destroy()

    def test_can_commit_new(self):
        family = Family(epithet="Austrobaileyaceae")
        genus = Genus(epithet="Austrobaileya", family=family)
        species = Species(genus=genus, epithet="scandens")
        accession = Accession(code="2001.0001", species=species)
        # need al teast 2 locations or the editor will automatically select the
        # single existing
        location = Location(
            code="LOC1",
            name="Location One",
            description="First location.",
        )
        location2 = Location(
            code="LOC2",
            name="Location Two",
            description="Second location.",
        )
        self.session.add_all([location, location2, accession])
        self.session.commit()
        editor = PlantEditorDialog(Plant(), self.session)

        self.assertFalse(editor.can_commit)

        editor.accession_entry.set_text("2001.0001")
        editor.code_entry.set_text("1")
        editor.location_comboentry.get_child().set_text("LOC1")

        self.assertTrue(editor.can_commit)
        self.assertEqual(dict(editor.reason_liststore), new_plt_reasons)

        editor.destroy()

    def test_can_commit_existing(self):
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
        editor = PlantEditorDialog(plant, self.session)

        self.assertFalse(editor.can_commit)

        editor.code_entry.set_text("2")

        self.assertFalse(editor.can_commit)

        editor.code_entry.set_text("3")

        self.assertTrue(editor.can_commit)

        editor.destroy()

    def test_ok_sensitive(self):
        family = Family(epithet="Austrobaileyaceae")
        genus = Genus(epithet="Austrobaileya", family=family)
        species = Species(genus=genus, epithet="scandens")
        accession = Accession(code="2001.0001", species=species)
        location = Location(
            code="LOC1",
            name="Location One",
            description="First location.",
        )
        self.session.add(location)
        self.session.add(accession)
        self.session.commit()

        plant = Plant()
        editor = PlantEditorDialog(plant, self.session)
        ok_button = editor.get_widget_for_response(-5)

        self.assertFalse(ok_button.get_sensitive())

        editor.destroy()

        plant.accession = accession
        plant.location = location
        plant.code = "1"
        editor = PlantEditorDialog(plant, db.Session())

        ok_button = editor.get_widget_for_response(-5)

        self.assertTrue(ok_button.get_sensitive())

        editor.destroy()

    def test_update(self):
        family = Family(epithet="Austrobaileyaceae")
        genus = Genus(epithet="Austrobaileya", family=family)
        species = Species(genus=genus, epithet="scandens")
        accession = Accession(code="2001.0001", species=species)
        location = Location(
            code="LOC1",
            name="Location One",
            description="First location.",
        )
        self.session.add(location)
        self.session.add(accession)
        self.session.commit()

        editor = PlantEditorDialog(Plant(), self.session)

        for response in Response:
            widget = editor.get_widget_for_response(response.value)
            if response == Response.CANCEL:
                self.assertTrue(widget.get_sensitive())
            elif widget:
                self.assertFalse(widget.get_sensitive())

        editor.code_entry.set_text("1")
        editor.accession_entry.set_text("2001.0001")
        # also tests we can match on name
        editor.location_comboentry.get_child().set_text("Location One")

        for response in Response:
            widget = editor.get_widget_for_response(response.value)
            if widget:
                self.assertTrue(widget.get_sensitive())

        editor.destroy()

    def test_change_reasons(self):
        family = Family(epithet="Austrobaileyaceae")
        genus = Genus(epithet="Austrobaileya", family=family)
        species = Species(genus=genus, epithet="scandens")
        accession = Accession(code="2001.0001", species=species)
        # need al teast 2 locations or the editor will automatically select the
        # single existing
        location = Location(
            code="LOC1",
            name="Location One",
            description="First location.",
        )
        location2 = Location(
            code="LOC2",
            name="Location Two",
            description="Second location.",
        )
        plant = Plant(
            accession=accession,
            location=location,
            code="1",
            quantity=1,
        )
        self.session.add_all([plant, location2])
        self.session.commit()
        editor = PlantEditorDialog(plant, self.session)

        self.assertFalse(editor.change_frame.get_sensitive())

        editor.location_comboentry.get_child().set_text("LOC2")

        self.assertTrue(editor.change_frame.get_sensitive())
        self.assertEqual(dict(editor.reason_liststore), transfer_reasons)

        editor.location_comboentry.get_child().set_text("LOC1")

        self.assertFalse(editor.change_frame.get_sensitive())

        editor.quantity_entry.set_text("0")

        self.assertTrue(editor.change_frame.get_sensitive())
        self.assertEqual(dict(editor.reason_liststore), deleted_reasons)

        editor.quantity_entry.set_text("5")

        self.assertTrue(editor.change_frame.get_sensitive())
        self.assertEqual(dict(editor.reason_liststore), added_reasons)

        editor.destroy()

    def test_accession_get_completions_partial(self):
        family = Family(epithet="Austrobaileyaceae")
        genus = Genus(epithet="Austrobaileya", family=family)
        species = Species(genus=genus, epithet="scandens")
        accession = Accession(code="2001.0001", species=species)
        # need al teast 2 locations or the editor will automatically select the
        # single existing
        location = Location(
            code="LOC1",
            name="Location One",
            description="First location.",
        )
        location2 = Location(
            code="LOC2",
            name="Location Two",
            description="Second location.",
        )
        self.session.add_all([location, location2, accession])
        self.session.commit()
        editor = PlantEditorDialog(Plant(), self.session)

        self.assertFalse(editor.can_commit)

        self.assertEqual(
            editor.accession_get_completions("20 Aus sc"),
            [(accession,)],
        )

        editor.destroy()

    def test_changing_accession_w_existing_code(self):
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

        editor = PlantEditorDialog(Plant(location=location), self.session)

        # no matched for accession
        self.assertEqual(len(editor.problems), 1)
        for problem, widget in editor.problems:
            self.assertEqual(widget, editor.accession_entry)
            self.assertTrue(
                problem.startswith(
                    "not_matched::on_completion_entry_matched::PlantEditorD"
                )
            )

        editor.code_entry.set_text("1")
        editor.accession_entry.set_text("2001.0001")

        # accession matched but code not unique
        self.assertEqual(len(editor.problems), 1)
        for problem, widget in editor.problems:
            self.assertEqual(widget, editor.code_entry)
            self.assertTrue(
                problem.startswith(
                    "not_unique::on_unique_code_entry_changed::PlantEditorD"
                )
            )

        editor.destroy()

    def test_on_changed_calls_update(self):
        editor = PlantEditorDialog(Plant(), self.session)
        with mock.patch.object(editor, "update") as mock_update:
            editor.history_presenter.emit("changed")
            mock_update.assert_called_once()

    def test_on_comboentry_format(self):
        location = Location(
            code="LOC1",
            name="Location One",
            description="First location.",
        )
        liststore = Gtk.ListStore(object)
        liststore.append([None])
        liststore.append([location])
        combo = Gtk.ComboBox.new_with_model(liststore)
        editor = PlantEditorDialog(Plant(), self.session)

        self.assertEqual(editor.on_comboentry_format(combo, 0), "")
        self.assertEqual(
            editor.on_comboentry_format(combo, 1),
            "(LOC1) Location One",
        )

        editor.destroy()

    @mock.patch("bauble.ui.dialogs.message_details_dialog")
    def test_on_response_ok(self, mock_dlog):
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

        editor = PlantEditorDialog(plant, self.session)
        # change code to None to force an error,
        # NOTE that the editor should never allow this.
        editor.model.code = None
        # fails no code, use emit here to avoid warning due to:
        # `dialog.stop_emission_by_name("response")`
        editor.emit("response", Response.OK)

        update_gui()
        mock_dlog.assert_called_once()
        mock_dlog.reset_mock()

        editor.code_entry.set_text("1")
        # trigger change
        editor.quantity_entry.set_text("2")
        self.assertFalse(editor.on_response(editor, Response.OK))

        update_gui()
        mock_dlog.assert_not_called()

        editor.destroy()

    def test_on_response_cancel(self):
        editor = PlantEditorDialog(Plant(), self.session)

        self.assertFalse(editor.on_response(editor, Response.CANCEL))

        editor.destroy()

    @mock.patch("bauble.plugins.garden.ui.plant_editor.create_plant")
    def test_on_response_next(self, mock_callback):
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
        self.session.add_all([accession, location])
        self.session.commit()
        mock_callback.return_value = False
        editor = PlantEditorDialog(plant, self.session)

        self.assertFalse(editor.on_response(editor, Response.NEXT))

        update_gui()

        mock_callback.assert_called_once()

        editor.destroy()

    @mock.patch("bauble.plugins.garden.ui.plant_editor.edit_callback")
    def test_on_response_save(self, mock_callback):
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
        self.session.add_all([accession, location])
        self.session.commit()
        mock_callback.return_value = False
        editor = PlantEditorDialog(plant, self.session)

        self.assertFalse(editor.on_response(editor, Response.SAVE))

        update_gui()

        mock_callback.assert_called_once()

        editor.destroy()


class FunctionTests(BaubleTestCase):

    def test_edit_callback(self):
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

        with mock.patch.object(edit_callback, "dialog_class") as mock_editor:

            self.assertFalse(edit_callback([plant]))
            mock_editor.assert_called_once()
            self.assertEqual(mock_editor.call_args.kwargs["model"], plant)
            mock_editor().show.assert_called_once()
