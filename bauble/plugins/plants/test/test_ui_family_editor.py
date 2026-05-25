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
from unittest import mock

from gi.repository import Gtk

from bauble import db
from bauble import utils
from bauble.test import BaubleTestCase
from bauble.test import update_gui
from bauble.ui.presenter import Response
from bauble.ui.utils import set_widget_value
from bauble.ui.widgets.message import YesNoMessageBox

from ..family import Family
from ..genus import Genus
from ..ui.family_editor import FamilyEditorDialog
from ..ui.family_editor import add_genera_callback
from ..ui.family_editor import edit_callback
from ..ui.family_editor import validate_unique_family


class FamilyEditorDialogTests(BaubleTestCase):
    @mock.patch("bauble.gui")
    def test_init_existing(self, mock_gui):
        mock_gui.window = Gtk.Window()
        family = Family(epithet="Austrobaileyaceae")
        self.session.add(family)
        self.session.commit()
        editor = FamilyEditorDialog(family, self.session)

        self.assertEqual(editor.get_transient_for(), mock_gui.window)
        self.assertEqual(editor.links_menu_btn.model, family)
        self.assertEqual(editor.synonyms_presenter.model, family)
        self.assertEqual(editor.family_entry.get_text(), "Austrobaileyaceae")
        self.assertEqual(len(editor.problems), 0)

        editor.destroy()

    def test_init_new(self):
        family = Family()
        editor = FamilyEditorDialog(family, self.session)

        # can't compare models due to merge but can check they intialised
        self.assertTrue(editor.links_menu_btn.model)
        self.assertTrue(editor.synonyms_presenter.model)
        self.assertEqual(editor.family_entry.get_text(), "")
        self.assertFalse(editor.suprafam_expander.get_expanded())
        self.assertEqual(len(editor.problems), 1)
        for problem, widget in editor.problems:
            self.assertEqual(widget, editor.family_entry)
            self.assertTrue(problem.startswith("empty::FamilyEditorDialog"))

        editor.destroy()

    def test_init_existing_w_suprafamilial_parts(self):
        family = Family(
            epithet="Austrobaileyaceae",
            order="Austrobaileyales",
            suborder="Austrobaileyineae",
        )
        self.session.add(family)
        self.session.commit()
        editor = FamilyEditorDialog(family, self.session)

        self.assertEqual(editor.links_menu_btn.model, family)
        self.assertEqual(editor.synonyms_presenter.model, family)
        self.assertEqual(editor.family_entry.get_text(), "Austrobaileyaceae")
        self.assertEqual(editor.order_entry.get_text(), "Austrobaileyales")
        self.assertEqual(editor.suborder_entry.get_text(), "Austrobaileyineae")
        self.assertTrue(editor.suprafam_expander.get_expanded())
        self.assertEqual(len(editor.problems), 0)

        editor.destroy()

    @mock.patch("bauble.plugins.plants.ui.family_editor.edit_callback")
    def test_init_is_synonym(self, mock_callback):
        family = Family(epithet="Leptospermaceae")
        family.accepted = Family(epithet="Myrtaceae")
        self.session.add(family)
        self.session.commit()
        editor = FamilyEditorDialog(family, self.session)
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
        self.assertEqual(str(result), "Myrtaceae")

        editor.destroy()

    def test_editor_doesnt_leak(self):
        editor = FamilyEditorDialog(
            model=Family(family="Fooaceae"),
            session=db.Session(),
        )
        editor.show()
        editor.emit("response", -6)

        del editor
        update_gui()

        self.assertEqual(
            utils.gc_objects_by_type("FamilyEditorDialog"),
            [],
            "FamilyEditorDialog not deleted",
        )

    def test_can_commit(self):
        # new
        editor = FamilyEditorDialog(Family(), self.session)

        self.assertFalse(editor.can_commit)

        editor.family_entry.set_text("Myrtaceae")

        self.assertTrue(editor.can_commit)

        editor.destroy()

        # existing
        family = Family(epithet="Austrobaileyaceae")
        self.session.add(family)
        self.session.commit()

        editor = FamilyEditorDialog(family, self.session)

        self.assertFalse(editor.can_commit)

        editor.author_entry.set_text("Juss.")

        self.assertTrue(editor.can_commit)

        editor.destroy()

    def test_ok_sensitive(self):
        fam = Family()
        self.session.add(fam)
        editor = FamilyEditorDialog(fam, db.Session())
        ok_button = editor.get_widget_for_response(-5)

        self.assertFalse(ok_button.get_sensitive())

        editor.destroy()

        fam.family = "Spamaceae"
        editor = FamilyEditorDialog(fam, db.Session())

        ok_button = editor.get_widget_for_response(-5)

        self.assertTrue(ok_button.get_sensitive())

        editor.destroy()

    def test_on_changed_calls_update(self):
        editor = FamilyEditorDialog(Family(), self.session)
        with mock.patch.object(editor, "update") as mock_update:
            editor.synonyms_presenter.emit("changed")
            mock_update.assert_called_once()

        editor.destroy()

    def test_update(self):
        editor = FamilyEditorDialog(Family(), self.session)

        for response in Response:
            widget = editor.get_widget_for_response(response.value)
            if response == Response.CANCEL:
                self.assertTrue(widget.get_sensitive())
            elif widget:
                self.assertFalse(widget.get_sensitive())

        editor.family_entry.set_text("Myrtaceae")

        for response in Response:
            widget = editor.get_widget_for_response(response.value)
            if widget:
                self.assertTrue(widget.get_sensitive())

        editor.destroy()

    @mock.patch("bauble.plugins.plants.ui.family_editor.edit_callback")
    def test_on_family_entry_changed_family_exists(self, mock_callback):
        family = Family(epithet="Myrtaceae")
        self.session.add(family)
        self.session.commit()
        editor = FamilyEditorDialog(Family(), self.session)
        editor.family_entry.set_text("Myrtaceae")

        self.assertEqual(editor.model.epithet, "Myrtaceae")
        self.assertEqual(len(editor.problems), 1)
        update_gui()

        child = editor.revealer.get_child()

        self.assertIsInstance(child, YesNoMessageBox)

        # no
        mock_callback.reset_mock()
        child.get_children()[1].get_children()[1].emit("clicked")

        mock_callback.assert_not_called()

        # yes
        editor.family_entry.set_text("")
        editor.family_entry.set_text("Myrtaceae")
        update_gui()
        child.get_children()[1].get_children()[0].emit("clicked")

        mock_callback.assert_called_once()
        mock_callback.reset_mock()

        editor.destroy()

        # yes modal
        editor = FamilyEditorDialog(Family(), self.session)
        with mock.patch.object(editor, "get_modal") as mock_get_modal:
            mock_get_modal.return_value = True
            editor.family_entry.set_text("Myrtaceae")
            update_gui()
            child = editor.revealer.get_child()
            child.get_children()[1].get_children()[0].emit("clicked")
            mock_callback.assert_not_called()

        self.assertIs(editor.model, self.session.merge(family))

        editor.destroy()

    def test_on_family_author_entry_changes(self):
        # also picks up combobox changed
        editor = FamilyEditorDialog(Family(), self.session)
        editor.author_entry.set_text("Juss.")

        self.assertEqual(editor.model.author, "Juss.")

        # no epithet
        self.assertEqual(len(editor.problems), 1)
        self.assertEqual(list(editor.problems)[0][1], editor.family_entry)

        # with epithet
        editor.family_entry.set_text("Myrtaceae")

        self.assertEqual(editor.model.epithet, "Myrtaceae")
        self.assertEqual(len(editor.problems), 0)

        set_widget_value(editor.qualifier_combo, "s. str.")
        self.assertEqual(editor.model.qualifier, "s. str.")

        self.assertEqual(len(editor.problems), 0)

        # reset
        set_widget_value(editor.qualifier_combo, "")
        # add a family
        self.session.add(
            Family(epithet="Fabaceae", author="Lindl.", qualifier="s. str.")
        )
        self.session.commit()
        # same epithet
        editor.family_entry.set_text("Fabaceae")

        self.assertEqual(len(editor.problems), 0)

        # same epithet and author
        editor.author_entry.set_text("Lindl.")

        self.assertEqual(len(editor.problems), 0)

        # same epithet, author and qualifier
        set_widget_value(editor.qualifier_combo, "s. str.")

        self.assertEqual(len(editor.problems), 3)

        editor.destroy()

    def test_on_order_entry_changed(self):
        editor = FamilyEditorDialog(Family(), self.session)
        editor.order_entry.set_text("Foo")

        self.assertEqual(editor.model.order, "Foo")

        editor.destroy()

    def test_order_get_completions(self):
        for i in range(30):
            self.session.add(Family(epithet=f"Family{i}", order=f"Order{i}"))
            self.session.add(Family(epithet=f"Other{i}", order=f"Another{i}"))
        self.session.commit()
        editor = FamilyEditorDialog(Family(), self.session)

        completions = editor.order_get_completions("Ord")
        self.assertEqual(len(completions), 20)
        self.assertTrue(all(i[0].startswith("Order") for i in completions))

        editor.destroy()

    def test_on_suborder_entry_changed(self):
        editor = FamilyEditorDialog(Family(), self.session)
        editor.suborder_entry.set_text("Foo")

        self.assertEqual(editor.model.suborder, "Foo")

        editor.destroy()

    def test_suborder_get_completions(self):
        for i in range(30):
            self.session.add(
                Family(
                    epithet=f"Family{i}",
                    order="Order1",
                    suborder=f"Suborder{i}",
                )
            )
            self.session.add(
                Family(
                    epithet=f"Other{i}",
                    order=f"Another{i}",
                    suborder="Subother{i}",
                )
            )
        self.session.commit()
        editor = FamilyEditorDialog(Family(), self.session)

        completions = editor.suborder_get_completions("Subo")
        self.assertEqual(len(completions), 20)
        self.assertTrue(all(i[0].startswith("Subo") for i in completions))

        editor.order_entry.set_text("Order1")

        completions = editor.suborder_get_completions("Subo")
        self.assertEqual(len(completions), 20)
        self.assertTrue(all(i[0].startswith("Suborder") for i in completions))

        editor.order_entry.set_text("Order3")

        completions = editor.suborder_get_completions("Subo")
        self.assertEqual(len(completions), 0)

        editor.destroy()

    @mock.patch("bauble.ui.dialogs.message_details_dialog")
    def test_on_response_ok(self, mock_dlog):
        editor = FamilyEditorDialog(Family(), self.session)
        # change epithet to None to force an error,
        # NOTE that the editor should never allow this.
        editor.model.epithet = None
        # fails no epithet, use emit here to avoid warning due to:
        # `dialog.stop_emission_by_name("response")`
        editor.emit("response", Response.OK)

        update_gui()
        mock_dlog.assert_called_once()
        mock_dlog.reset_mock()

        editor.family_entry.set_text("Myrtaceae")
        self.assertFalse(editor.on_response(editor, Response.OK))

        update_gui()
        mock_dlog.assert_not_called()

        editor.destroy()

    def test_on_response_cancel(self):
        editor = FamilyEditorDialog(Family(), self.session)

        self.assertFalse(editor.on_response(editor, Response.CANCEL))

        editor.destroy()

    @mock.patch("bauble.plugins.plants.ui.family_editor.create_family")
    def test_on_response_next(self, mock_callback):
        mock_callback.return_value = False
        editor = FamilyEditorDialog(Family(epithet="Myrtcaeae"), self.session)

        self.assertFalse(editor.on_response(editor, Response.NEXT))

        update_gui()

        mock_callback.assert_called_once()

        editor.destroy()

    @mock.patch("bauble.plugins.plants.ui.family_editor.add_genera_callback")
    def test_on_reponse_add(self, mock_callback):
        mock_callback.return_value = False
        editor = FamilyEditorDialog(Family(epithet="Myrtcaeae"), self.session)

        self.assertFalse(editor.on_response(editor, Response.ADD))

        update_gui()

        mock_callback.assert_called_once_with([editor.model])

        editor.destroy()


class FunctionTests(BaubleTestCase):
    def test_validate_unique_family(self):
        family = Family(epithet="Myrtaceae")
        self.session.add(family)
        self.session.commit()

        self.assertTrue(
            validate_unique_family("Austrobaileyaceae", "", "", family)
        )
        self.assertTrue(validate_unique_family("Myrtaceae", "", "", family))
        self.assertFalse(validate_unique_family("Myrtaceae", "", "", Family()))
        self.assertTrue(
            validate_unique_family("Myrtaceae", "Me", "", Family())
        )
        self.assertTrue(
            validate_unique_family("Myrtaceae", "", "s. lat.", Family())
        )
        self.assertTrue(
            validate_unique_family("Myrtaceae", "Me", "s. lat.", Family())
        )

        family.qualifier = "s. lat."
        self.session.commit()

        self.assertFalse(
            validate_unique_family("Myrtaceae", "", "s. lat.", Family())
        )
        self.assertTrue(
            validate_unique_family("Myrtaceae", "Me", "s. lat.", Family())
        )
        self.assertTrue(
            validate_unique_family("Myrtaceae", "Me", "", Family())
        )

        family.author = "Me"
        self.session.commit()

        self.assertTrue(
            validate_unique_family("Myrtaceae", "", "s. lat.", Family())
        )
        self.assertTrue(
            validate_unique_family("Myrtaceae", "Me", "", Family())
        )
        self.assertFalse(
            validate_unique_family("Myrtaceae", "Me", "s. lat.", Family())
        )
        self.assertTrue(
            validate_unique_family("Fabaceae", "Me", "s. lat.", Family())
        )
        self.assertTrue(
            validate_unique_family("Myrtaceae", "Me", "s. lat.", family)
        )

    def test_edit_callback(self):
        family = Family(family="Welwitschiaceae")
        self.session.add(family)
        self.session.flush()

        with mock.patch.object(edit_callback, "dialog_class") as mock_editor:

            self.assertFalse(edit_callback([family]))
            mock_editor.assert_called_once()
            self.assertEqual(mock_editor.call_args.kwargs["model"], family)
            mock_editor().show.assert_called_once()

    def test_add_genera_callback(self):
        family = Family(family="Welwitschiaceae")
        self.session.add(family)
        self.session.commit()

        with mock.patch.object(
            add_genera_callback, "dialog_class"
        ) as mock_editor:

            self.assertFalse(add_genera_callback([family]))
            mock_editor.assert_called_once()
            gen = mock_editor.call_args.kwargs["model"]
            gen = self.session.merge(gen)
            self.assertIsInstance(gen, Genus)
            self.assertEqual(gen.family, family)
