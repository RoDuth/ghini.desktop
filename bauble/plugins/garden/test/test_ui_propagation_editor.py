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
Propagation editor tests
"""
import datetime
from unittest import mock

from gi.repository import Gtk
from sqlalchemy import select

from bauble import db
from bauble import utils
from bauble.test import BaubleTestCase
from bauble.test import update_gui
from bauble.ui.presenter import Response
from bauble.ui.utils import get_widget_value
from bauble.ui.utils import set_widget_value

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
from ..ui.propagation_editor import PropagationEditorDialog
from ..ui.propagation_editor import PropEventPresenter
from ..ui.propagation_editor import SourcePlantEditorDialog
from ..ui.propagation_editor import edit_callback


class PropagationEditorDialogTests(BaubleTestCase):
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
        self.session.add(self.plant2)
        self.session.commit()
        self.seed = self.session.scalars(
            select(PropType).filter_by(code="seed")
        ).one()

    @mock.patch("bauble.gui")
    def test_init_existing(self, mock_gui):
        mock_gui.window = Gtk.Window()
        # This prop just to get the coverage on propagator_liststore population
        prop = Propagation(
            date=datetime.date(2001, 1, 1),
            propagator=utils.get_user_display_name(),
            media="potting mix",
            prop_type=self.seed,
        )
        self.plant.propagations.append(prop)
        # this for the test
        prop = Propagation(
            date=datetime.date(2001, 1, 1),
            propagator="Jade Green",
            media="potting mix",
            container="140mm",
            location="table 3",
            prop_notes="15% moisture content",
            prop_type=self.seed,
        )
        self.plant.propagations.append(prop)
        self.session.commit()
        editor = PropagationEditorDialog(prop, self.session)

        self.assertEqual(editor.get_transient_for(), mock_gui.window)
        self.assertEqual(editor.notes_presenter.model, prop)
        self.assertEqual(editor.pictures_presenter.model, prop)
        self.assertEqual(editor.pictures_presenter.prop, "pictures")
        self.assertEqual(editor.date_entry.get_text(), "01-01-2001")
        self.assertEqual(editor.propagator_entry.get_text(), "Jade Green")
        self.assertEqual(
            get_widget_value(editor.media_comboentry),
            "potting mix",
        )
        self.assertEqual(
            get_widget_value(editor.container_comboentry),
            "140mm",
        )
        self.assertEqual(
            get_widget_value(editor.location_comboentry),
            "table 3",
        )
        self.assertEqual(get_widget_value(editor.type_combo), self.seed)
        buffer = editor.notes_textbuffer
        self.assertEqual(
            buffer.get_text(*buffer.get_bounds(), False),
            "15% moisture content",
        )
        self.assertEqual(len(editor.source_liststore), 1)
        self.assertEqual(len(editor.problems), 0)

        editor.destroy()

    def test_init_new(self):
        prop = Propagation()
        editor = PropagationEditorDialog(prop, self.session)

        self.assertTrue(editor.notes_presenter.model)
        self.assertTrue(editor.pictures_presenter.model)
        self.assertEqual(editor.date_entry.get_text(), utils.today_str())
        self.assertEqual(
            editor.propagator_entry.get_text(),
            utils.get_user_display_name(),
        )
        self.assertEqual(
            get_widget_value(editor.media_comboentry),
            "",
        )
        self.assertEqual(
            get_widget_value(editor.container_comboentry),
            "",
        )
        self.assertEqual(
            get_widget_value(editor.location_comboentry),
            "",
        )
        self.assertEqual(get_widget_value(editor.type_combo), None)
        buffer = editor.notes_textbuffer
        self.assertEqual(
            buffer.get_text(*buffer.get_bounds(), False),
            "",
        )
        self.assertEqual(len(editor.source_liststore), 0)
        self.assertEqual(len(editor.problems), 2)
        for problem, widget in editor.problems:
            self.assertIn(
                widget,
                [
                    editor.source_treeview,
                    editor.type_combo,
                ],
            )
            self.assertTrue(
                problem.startswith(
                    "no_primary_source::PropagationEditorDialog",
                )
                or problem.startswith(
                    "not_matched::on_type_combo_changed::PropagationEditorDia",
                ),
                problem,
            )

        editor.destroy()

    def test_editor_doesnt_leak(self):
        editor = PropagationEditorDialog(
            model=Propagation(),
            session=db.Session(),
        )
        editor.show()
        editor.emit("response", Response.CANCEL)

        del editor
        update_gui()

        self.assertEqual(
            utils.gc_objects_by_type("PropagationEditorDialog"),
            [],
            "PropagationEditorDialog not deleted",
        )

    def test_can_commit_new(self):
        source1 = PlantPropSource(
            plant=self.plant,
            source_type="2",
            source_material="M",
        )
        source2 = PlantPropSource(
            plant=self.plant2,
            source_type="1",
            source_material="F",
        )
        prop = Propagation()
        self.session.add(prop)
        editor = PropagationEditorDialog(prop, self.session)

        self.assertFalse(editor.can_commit)

        source1.propagation = prop  # not primary
        editor.populate_source_list()
        editor.type_combo.set_active(0)

        self.assertFalse(editor.can_commit)

        source2.propagation = prop  # is primary
        editor.populate_source_list()

        self.assertTrue(editor.can_commit)

        editor.destroy()

    def test_can_commit_existing(self):
        prop = Propagation(
            date=datetime.date(2001, 1, 1),
            propagator="Jade Green",
            media="potting mix",
            container="140mm",
            location="table 3",
            prop_notes="15% moisture content",
            prop_type=self.seed,
        )
        self.plant.propagations.append(prop)
        self.session.commit()
        editor = PropagationEditorDialog(prop, self.session)

        self.assertFalse(editor.can_commit)

        editor.media_comboentry.get_child().set_text("perlite/coco peat")

        self.assertTrue(editor.can_commit)

        editor.destroy()

    def test_ok_sensitive(self):
        prop = Propagation(
            propagator="Jade Green",
            prop_type=self.seed,
        )
        self.plant.propagations.append(prop)
        self.session.commit()
        editor = PropagationEditorDialog(prop, db.Session())
        ok_button = editor.get_widget_for_response(-5)

        self.assertFalse(ok_button.get_sensitive())

        editor.destroy()

        editor = PropagationEditorDialog(prop, db.Session())
        editor.date_entry.set_text("1/1/2021")
        ok_button = editor.get_widget_for_response(-5)

        self.assertTrue(ok_button.get_sensitive())

        editor.destroy()

    def test_on_changed_calls_update(self):
        editor = PropagationEditorDialog(
            model=Propagation(),
            session=db.Session(),
        )
        with mock.patch.object(editor, "update") as mock_update:
            editor.notes_presenter.emit("changed")
            mock_update.assert_called_once()

        editor.destroy()

    @mock.patch(
        "bauble.plugins.garden.ui.propagation_editor.SourcePlantEditorDialog"
    )
    def test_on_new_source_button_clicked(self, mock_source_editor):
        editor = PropagationEditorDialog(Propagation(), db.Session())
        mock_source_editor().run.return_value = Gtk.ResponseType.CANCEL

        editor.on_add_source_button_clicked(None)

        self.assertEqual(len(editor.model.plant_sources), 0)

        mock_source_editor.reset_mock()
        mock_source_editor().run.return_value = Gtk.ResponseType.OK
        with mock.patch.object(editor, "populate_source_list") as mock_pop:

            editor.on_add_source_button_clicked(None)

            mock_pop.assert_called_once()
            self.assertEqual(len(editor.model.plant_sources), 1)

        editor.destroy()

    def test_on_remove_source_button_clicked(self):
        prop = Propagation(
            date=datetime.date(2001, 1, 1),
            propagator="Jade Green",
            media="potting mix",
            container="140mm",
            location="table 3",
            prop_notes="15% moisture content",
            prop_type=self.seed,
        )
        self.plant.propagations.append(prop)
        self.session.commit()
        editor = PropagationEditorDialog(prop, self.session)

        editor.on_remove_source_button_clicked(None)

        # fails, nothing selected
        self.assertFalse(editor.remove_source_button.get_sensitive())
        self.assertEqual(len(editor.model.plant_sources), 1)

        editor.source_treeview.set_cursor("0")

        self.assertTrue(editor.remove_source_button.get_sensitive())

        editor.on_remove_source_button_clicked(None)

        self.assertFalse(editor.remove_source_button.get_sensitive())
        self.assertEqual(len(editor.model.plant_sources), 0)

        editor.destroy()

    @mock.patch(
        "bauble.plugins.garden.ui.propagation_editor.SourcePlantEditorDialog"
    )
    def test_on_source_activated(self, mock_source_editor):
        prop = Propagation(
            date=datetime.date(2001, 1, 1),
            propagator="Jade Green",
            media="potting mix",
            container="140mm",
            location="table 3",
            prop_notes="15% moisture content",
            prop_type=self.seed,
        )
        self.plant.propagations.append(prop)
        prop.plant_sources[0].source_material = "F"
        self.session.commit()
        editor = PropagationEditorDialog(prop, self.session)
        mock_source_editor().run.return_value = Gtk.ResponseType.OK
        mock_source_editor.reset_mock()
        with mock.patch.object(editor, "populate_source_list") as mock_pop:

            editor.on_source_activated(None, "0", None)

            mock_source_editor.assert_called_once_with(
                prop.plant_sources[0],
                editor.session,
                editor,
            )
            mock_pop.assert_called_once()

        mock_source_editor().run.return_value = Gtk.ResponseType.CANCEL
        mock_source_editor.reset_mock()
        with mock.patch.object(editor, "session") as mock_session:

            editor.on_source_activated(None, "0", None)

            mock_session.expire.assert_called_once_with(prop.plant_sources[0])

        editor.destroy()

    def test_update(self):
        source = PlantPropSource(
            plant=self.plant2,
            source_type="1",
            source_material="F",
        )
        prop = Propagation()
        editor = PropagationEditorDialog(prop, self.session)

        for response in Response:
            widget = editor.get_widget_for_response(response.value)
            if response == Response.CANCEL:
                self.assertTrue(widget.get_sensitive())
            elif widget:
                self.assertFalse(widget.get_sensitive())

        source.propagation = editor.model
        editor.populate_source_list()
        editor.type_combo.set_active(0)

        for response in Response:
            widget = editor.get_widget_for_response(response.value)
            if widget:
                self.assertTrue(widget.get_sensitive())

        editor.destroy()

    @mock.patch("bauble.ui.dialogs.message_details_dialog")
    def test_on_response_ok(self, mock_dlog):
        editor = PropagationEditorDialog(Propagation(), self.session)
        # fails on prop_type_id, use emit here to avoid warning due to:
        # `dialog.stop_emission_by_name("response")`
        editor.emit("response", Response.OK)

        update_gui()
        mock_dlog.assert_called_once()
        mock_dlog.reset_mock()

        self.plant.propagations.append(editor.model)
        editor.model.plant_sources[0].source_type = "1"
        editor.type_combo.set_active(0)
        self.assertFalse(editor.on_response(editor, Response.OK))

        update_gui()
        mock_dlog.assert_not_called()

        editor.destroy()

    def test_on_response_cancel(self):
        editor = PropagationEditorDialog(Propagation(), self.session)

        self.assertFalse(editor.on_response(editor, Response.CANCEL))

        editor.destroy()

    @mock.patch(
        "bauble.plugins.garden.ui.propagation_editor.create_propagation"
    )
    def test_on_response_next(self, mock_callback):
        mock_callback.return_value = False
        editor = PropagationEditorDialog(Propagation(), self.session)
        self.plant.propagations.append(editor.model)
        editor.model.plant_sources[0].source_type = "1"
        editor.type_combo.set_active(0)
        editor.propagator_entry.set_text("Jade Green")
        editor.date_entry.set_text("1/1/2001")

        self.assertFalse(editor.on_response(editor, Response.NEXT))

        update_gui()

        mock_callback.assert_called_once_with(
            propagator="Jade Green",
            date=datetime.date(2001, 1, 1),
        )

        editor.destroy()


class SourcePlantEditorDialogTests(BaubleTestCase):
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
        self.session.add(self.plant2)
        self.session.commit()
        self.seed = self.session.scalar(
            select(PropType).filter_by(code="seed")
        )

    def test_init_existing(self):
        prop = Propagation(
            date=datetime.date(2001, 1, 1),
            propagator="Jade Green",
            media="potting mix",
            container="140mm",
            location="table 3",
            prop_notes="15% moisture content",
            prop_type=self.seed,
        )
        self.plant.propagations.append(prop)
        prop.plant_sources[0].source_material = "F"
        self.session.add(prop)
        self.session.commit()
        window = Gtk.Window()
        editor = SourcePlantEditorDialog(
            prop.plant_sources[0],
            self.session,
            window,
        )

        self.assertEqual(editor.get_transient_for(), window)
        self.assertEqual(editor.plant_entry.get_text(), str(self.plant))
        self.assertEqual(get_widget_value(editor.type_combo), "1")
        self.assertEqual(get_widget_value(editor.material_combo), "F")
        self.assertTrue(editor.ok_button.get_sensitive())
        self.assertEqual(len(editor.problems), 0)

        editor.destroy()

    def test_init_new(self):
        prop = Propagation()
        source_plant = PlantPropSource(propagation=prop)
        editor = SourcePlantEditorDialog(source_plant, self.session)

        self.assertEqual(editor.plant_entry.get_text(), "")
        self.assertIsNone(get_widget_value(editor.type_combo))
        self.assertIsNone(get_widget_value(editor.material_combo))
        self.assertFalse(editor.ok_button.get_sensitive())
        self.assertEqual(len(editor.problems), 2)

        editor.plant_entry.set_text(str(self.plant))
        set_widget_value(editor.type_combo, "Primary", index=1)
        self.assertEqual(get_widget_value(editor.type_combo), "1")

        self.assertEqual(len(editor.problems), 0)
        self.assertTrue(editor.ok_button.get_sensitive())

        editor.destroy()


class PropEventPresenterTests(BaubleTestCase):
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
        self.seed = self.session.scalar(
            select(PropType).filter_by(code="seed")
        )
        self.prop = Propagation(
            date=datetime.date(2001, 1, 1),
            propagator="Jade Green",
            media="potting mix",
            container="140mm",
            location="table 3",
            prop_notes="15% moisture content",
            prop_type=self.seed,
        )
        self.plant.propagations.append(self.prop)
        self.start = self.session.scalar(
            select(PropEventType).filter_by(code="STRT")
        )
        self.event = PropEvent(
            date=datetime.date(2001, 1, 1),
            person="Jade Green",
            quantity=10,
            event_notes="First batch",
            event_type=self.start,
            propagation=self.prop,
        )
        self.session.add(self.plant)
        self.session.add(self.prop)
        self.session.add(self.event)
        self.session.commit()

    def test_init_existing(self):
        presenter = PropEventPresenter()
        presenter.init(self.session)
        presenter.set_model(self.event)

        self.assertTrue(presenter.get_sensitive())
        self.assertEqual(presenter.person_entry.get_text(), "Jade Green")
        self.assertEqual(
            presenter.date_entry.get_text(),
            utils.date_string(datetime.datetime(2001, 1, 1)),
        )
        self.assertEqual(get_widget_value(presenter.type_combo), self.start)
        self.assertEqual(presenter.quantity_spinbutton.get_text(), "10")
        self.assertEqual(presenter.success_spinbutton.get_text(), "0")
        self.assertEqual(presenter.available_spinbutton.get_text(), "0")
        self.assertEqual(presenter.available_spinbutton.get_text(), "0")
        self.assertEqual(
            get_widget_value(presenter.notes_textview),
            "First batch",
        )
        self.assertEqual(len(presenter.problems), 0)

        presenter.destroy()

    def test_init_new(self):
        presenter = PropEventPresenter()
        presenter.init(self.session)
        presenter.set_model(
            PropEvent(
                date=datetime.date.today(),
                person=utils.get_user_display_name(),
            )
        )

        self.assertTrue(presenter.get_sensitive())
        self.assertEqual(
            presenter.person_entry.get_text(), utils.get_user_display_name()
        )
        self.assertEqual(
            presenter.date_entry.get_text(),
            utils.date_string(datetime.datetime.today()),
        )
        self.assertEqual(get_widget_value(presenter.type_combo), self.start)
        self.assertEqual(presenter.quantity_spinbutton.get_text(), "0")
        self.assertEqual(presenter.success_spinbutton.get_text(), "0")
        self.assertEqual(presenter.available_spinbutton.get_text(), "0")
        self.assertEqual(presenter.available_spinbutton.get_text(), "0")
        self.assertEqual(
            get_widget_value(presenter.notes_textview),
            "",
        )
        self.assertEqual(len(presenter.problems), 0)

        presenter.destroy()

    def test_can_commit_new(self):
        presenter = PropEventPresenter()
        presenter.init(self.session)
        presenter.set_model(
            PropEvent(
                event_type=self.start,
                date=datetime.date.today(),
                propagation=self.prop,
                quantity=0,
                success=0,
                available=0,
            )
        )

        self.assertFalse(presenter.can_commit)

        presenter.person_entry.set_text("Forrest Park")

        self.assertTrue(presenter.can_commit)

        presenter.destroy()

    def test_can_commit_existing(self):
        presenter = PropEventPresenter()
        presenter.init(self.session)
        presenter.set_model(self.event)

        self.assertFalse(presenter.can_commit)

        presenter.person_entry.set_text("Forrest Park")

        self.assertTrue(presenter.can_commit)

        presenter.destroy()

    def test_constrian_widgets(self):
        success = self.session.scalar(
            select(PropEventType).filter_by(code="SUCC")
        )
        available = self.session.scalar(
            select(PropEventType).filter_by(code="AVLB")
        )
        event2 = PropEvent(
            date=datetime.date(2001, 2, 1),
            person="Jade Green",
            success=10,
            event_notes="First batch",
            event_type=success,
            propagation=self.prop,
        )
        event3 = PropEvent(
            date=datetime.date(2001, 2, 10),
            person="Jade Green",
            available=10,
            event_notes="First batch",
            event_type=available,
            propagation=self.prop,
        )
        self.session.add(event2)
        self.session.add(event3)
        self.session.commit()
        presenter = PropEventPresenter()
        presenter.init(self.session)
        presenter.set_model(self.event)

        self.assertEqual(presenter.date_picker.start_date, None)
        self.assertEqual(presenter.date_picker.end_date, event2.date)
        self.assertTrue(presenter.quantity_spinbutton.get_sensitive())
        self.assertEqual(presenter.quantity_adj.get_lower(), 0)
        self.assertEqual(presenter.quantity_adj.get_upper(), 10000000)
        self.assertFalse(presenter.success_spinbutton.get_sensitive())
        self.assertFalse(presenter.available_spinbutton.get_sensitive())

        presenter.set_model(event2)

        self.assertEqual(presenter.date_picker.start_date, self.event.date)
        self.assertEqual(presenter.date_picker.end_date, event3.date)
        self.assertFalse(presenter.quantity_spinbutton.get_sensitive())
        self.assertTrue(presenter.success_spinbutton.get_sensitive())
        self.assertEqual(presenter.success_adj.get_lower(), 0)
        self.assertEqual(
            presenter.success_adj.get_upper(), self.event.quantity
        )
        self.assertFalse(presenter.available_spinbutton.get_sensitive())

        presenter.set_model(event3)

        self.assertEqual(presenter.date_picker.start_date, event2.date)
        self.assertEqual(presenter.date_picker.end_date, None)
        self.assertFalse(presenter.quantity_spinbutton.get_sensitive())
        self.assertFalse(presenter.success_spinbutton.get_sensitive())
        self.assertTrue(presenter.available_spinbutton.get_sensitive())
        self.assertEqual(presenter.available_adj.get_lower(), 0)
        self.assertEqual(presenter.available_adj.get_upper(), event2.success)

        presenter.destroy()

    def test_constrian_widgets_cull_discard(self):

        qty_cull = self.session.scalar(
            select(PropEventType).filter_by(code="CULQ")
        )
        success = self.session.scalar(
            select(PropEventType).filter_by(code="SUCC")
        )
        suc_cull = self.session.scalar(
            select(PropEventType).filter_by(code="CULS")
        )
        available = self.session.scalar(
            select(PropEventType).filter_by(code="AVLB")
        )
        discard = self.session.scalar(
            select(PropEventType).filter_by(code="DISC")
        )
        presenter = PropEventPresenter()
        presenter.init(self.session)
        presenter.set_model(self.event)

        # base case
        self.assertEqual(presenter.date_picker.start_date, None)
        self.assertEqual(presenter.date_picker.end_date, None)
        self.assertTrue(presenter.quantity_spinbutton.get_sensitive())
        self.assertEqual(presenter.quantity_adj.get_lower(), 0)
        self.assertEqual(presenter.quantity_adj.get_upper(), 10000000)
        self.assertFalse(presenter.success_spinbutton.get_sensitive())
        self.assertFalse(presenter.available_spinbutton.get_sensitive())

        presenter.set_model(
            PropEvent(
                event_type=qty_cull,
                date=datetime.date.today(),
                person="Jade Green",
                propagation=self.prop,
                quantity=0,
                success=0,
                available=0,
            )
        )

        self.assertTrue(presenter.quantity_spinbutton.get_sensitive())
        self.assertEqual(
            presenter.quantity_adj.get_lower(), -self.event.quantity
        )
        self.assertEqual(presenter.quantity_adj.get_upper(), 0)
        self.assertFalse(presenter.success_spinbutton.get_sensitive())
        self.assertFalse(presenter.available_spinbutton.get_sensitive())

        event2 = PropEvent(
            date=datetime.date(2001, 2, 1),
            person="Jade Green",
            success=10,
            event_notes="First batch",
            event_type=success,
            propagation=self.prop,
        )
        self.session.add(event2)
        self.session.commit()

        presenter.set_model(
            PropEvent(
                event_type=suc_cull,
                date=datetime.date.today(),
                person="Jade Green",
                propagation=self.prop,
                quantity=0,
                success=0,
                available=0,
            )
        )

        self.assertFalse(presenter.quantity_spinbutton.get_sensitive())
        self.assertTrue(presenter.success_spinbutton.get_sensitive())
        self.assertEqual(presenter.success_adj.get_lower(), -event2.success)
        self.assertEqual(presenter.success_adj.get_upper(), 0)
        self.assertFalse(presenter.available_spinbutton.get_sensitive())

        event3 = PropEvent(
            date=datetime.date(2001, 2, 10),
            person="Jade Green",
            available=10,
            event_notes="First batch",
            event_type=available,
            propagation=self.prop,
        )
        self.session.add(event3)
        self.session.commit()

        presenter.set_model(
            PropEvent(
                event_type=discard,
                date=datetime.date.today(),
                person="Jade Green",
                propagation=self.prop,
                quantity=0,
                success=0,
                available=0,
            )
        )

        self.assertFalse(presenter.quantity_spinbutton.get_sensitive())
        self.assertFalse(presenter.success_spinbutton.get_sensitive())
        self.assertTrue(presenter.available_spinbutton.get_sensitive())
        self.assertEqual(presenter.success_adj.get_lower(), -event3.available)
        self.assertEqual(presenter.success_adj.get_upper(), 0)

        presenter.destroy()


class FunctionTests(BaubleTestCase):
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
        self.session.add(self.plant)
        self.session.commit()

    def test_edit_callback(self):
        seed = self.session.scalar(select(PropType).filter_by(code="seed"))
        prop = Propagation(
            date=datetime.date(2001, 1, 1),
            propagator="Jade Green",
            media="potting mix",
            container="140mm",
            location="table 3",
            prop_notes="15% moisture content",
            prop_type=seed,
        )
        self.plant.propagations.append(prop)
        self.session.commit()

        with mock.patch.object(edit_callback, "dialog_class") as mock_editor:

            self.assertFalse(edit_callback([prop]))
            mock_editor.assert_called_once()
            self.assertEqual(mock_editor.call_args.kwargs["model"], prop)
            mock_editor().show.assert_called_once()
