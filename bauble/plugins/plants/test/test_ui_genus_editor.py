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
from bauble.plugins.plants.family import Family
from bauble.plugins.plants.genus import Genus
from bauble.plugins.plants.species import Species
from bauble.test import BaubleTestCase
from bauble.test import update_gui
from bauble.ui.presenter import Response

from ..ui.genus_editor import GenusEditorDialog
from ..ui.genus_editor import add_species_callback
from ..ui.genus_editor import edit_callback
from ..ui.genus_editor import validate_unique_genus


class GenusEditorDialogTests(BaubleTestCase):
    @mock.patch("bauble.gui")
    def test_init_existing(self, mock_gui):
        mock_gui.window = Gtk.Window()
        family = Family(epithet="Austrobaileyaceae")
        genus = Genus(epithet="Austrobaileya", family=family)
        self.session.add(genus)
        self.session.commit()
        editor = GenusEditorDialog(genus, self.session)

        self.assertEqual(editor.get_transient_for(), mock_gui.window)
        self.assertEqual(editor.links_menu_btn.model, genus)
        self.assertEqual(editor.synonyms_presenter.model, genus)
        self.assertEqual(editor.family_entry.get_text(), "Austrobaileyaceae")
        self.assertEqual(editor.genus_entry.get_text(), "Austrobaileya")
        self.assertEqual(len(editor.problems), 0)

        editor.destroy()

    def test_init_new(self):
        genus = Genus()
        editor = GenusEditorDialog(genus, self.session)

        # can't compare models due to merge but can check they intialised
        self.assertTrue(editor.links_menu_btn.model)
        self.assertTrue(editor.synonyms_presenter.model)
        self.assertEqual(editor.family_entry.get_text(), "")
        self.assertEqual(editor.genus_entry.get_text(), "")
        self.assertFalse(editor.supragen_expander.get_expanded())
        self.assertEqual(len(editor.problems), 2)
        for problem, widget in editor.problems:
            self.assertIn(widget, [editor.family_entry, editor.genus_entry])
            self.assertTrue(problem.startswith("empty::GenusEditorDialog"))

        editor.destroy()

    def test_init_existing_w_suprageneric_parts(self):
        family = Family(epithet="Poaceae")
        genus = Genus(
            epithet="Bambusa",
            family=family,
            subfamily="Bambusoideae",
            tribe="Bambuseae",
            subtribe="Bambusinae",
        )

        self.session.add(genus)
        self.session.commit()
        editor = GenusEditorDialog(genus, self.session)

        self.assertEqual(editor.links_menu_btn.model, genus)
        self.assertEqual(editor.synonyms_presenter.model, genus)
        self.assertEqual(editor.family_entry.get_text(), "Poaceae")
        self.assertEqual(editor.genus_entry.get_text(), "Bambusa")
        self.assertEqual(editor.subfamily_entry.get_text(), "Bambusoideae")
        self.assertEqual(editor.tribe_entry.get_text(), "Bambuseae")
        self.assertEqual(editor.subtribe_entry.get_text(), "Bambusinae")
        self.assertTrue(editor.supragen_expander.get_expanded())
        self.assertEqual(len(editor.problems), 0)

        editor.destroy()

    def test_editor_doesnt_leak(self):
        family = Family(family="Myrtaceae")
        self.session.add(family)
        self.session.commit()
        editor = GenusEditorDialog(
            model=Genus(epithet="Acmena", family=family),
            session=db.Session(),
        )
        with mock.patch.object(editor, "run") as mock_run:
            mock_run.return_value = Gtk.ResponseType.OK
            editor.run()

        editor.destroy()
        del editor
        update_gui()

        self.assertEqual(
            utils.gc_objects_by_type("GenusEditorDialog"),
            [],
            "GenusEditorDialog not deleted",
        )

    def test_allow_ok_only(self):
        editor = GenusEditorDialog(Genus(), self.session)
        editor.allow_ok_only()

        for response in Response:
            widget = editor.get_widget_for_response(response.value)
            if response == Response.OK:
                self.assertTrue(widget.get_visible())
            else:
                self.assertFalse(widget.get_visible())

        editor.destroy()

    def test_can_commit(self):
        self.session.add(Family(epithet="Myrtaceae"))
        self.session.commit()
        editor = GenusEditorDialog(Genus(), self.session)

        self.assertFalse(editor.can_commit)

        editor.genus_entry.set_text("Eucalyptus")

        self.assertFalse(editor.can_commit)

        editor.family_entry.set_text("Myrtaceae")

        self.assertTrue(editor.can_commit)

        editor.destroy()

    def test_on_changed_calls_update(self):
        editor = GenusEditorDialog(Genus(), self.session)
        with mock.patch.object(editor, "update") as mock_update:
            editor.synonyms_presenter.emit("changed")
            mock_update.assert_called_once()

        editor.destroy()

    def test_update(self):
        family = Family(epithet="Myrtaceae")
        self.session.add(family)
        self.session.commit()
        editor = GenusEditorDialog(Genus(family=family), self.session)

        for response in Response:
            widget = editor.get_widget_for_response(response.value)
            if response == Response.CANCEL:
                self.assertTrue(widget.get_sensitive())
            else:
                self.assertFalse(widget.get_sensitive())

        editor.genus_entry.set_text("Syzygium")

        for response in Response:
            widget = editor.get_widget_for_response(response.value)
            self.assertTrue(widget.get_sensitive())

        editor.destroy()

    def test_on_genus_author_entry_changes(self):
        # also picks up combobox changed
        family = Family(epithet="Myrtaceae")
        self.session.add(family)
        self.session.commit()
        editor = GenusEditorDialog(Genus(family=family), self.session)
        editor.author_entry.set_text("Juss.")

        self.assertEqual(editor.model.author, "Juss.")

        # no epithet
        self.assertEqual(len(editor.problems), 1)
        self.assertEqual(list(editor.problems)[0][1], editor.genus_entry)

        # with epithet
        editor.genus_entry.set_text("Acmena")

        self.assertEqual(editor.model.epithet, "Acmena")
        self.assertEqual(len(editor.problems), 0)

        utils.set_widget_value(editor.qualifier_combo, "s. str")
        self.assertEqual(editor.model.qualifier, "s. str")

        self.assertEqual(len(editor.problems), 0)

        # reset
        utils.set_widget_value(editor.qualifier_combo, "")
        # add a Genus
        self.session.add(
            Genus(
                family=family,
                epithet="Acmena",
                author="Lindl.",
                qualifier="s. str",
            )
        )
        self.session.commit()
        # same epithet
        editor.genus_entry.set_text("Acmena")

        self.assertEqual(len(editor.problems), 0)

        # same epithet and author
        editor.author_entry.set_text("Lindl.")

        self.assertEqual(len(editor.problems), 0)

        # same epithet, author and qualifier
        utils.set_widget_value(editor.qualifier_combo, "s. str")

        self.assertEqual(len(editor.problems), 4)

        editor.destroy()

    def test_on_subfamily_entry_changed(self):
        editor = GenusEditorDialog(Genus(), self.session)
        editor.subfamily_entry.set_text("Foo")

        self.assertEqual(editor.model.subfamily, "Foo")

        editor.destroy()

    def test_subfamily_get_completions(self):
        family = Family(epithet="Poaceae")
        self.session.add(family)
        for i in range(30):
            self.session.add(
                Genus(
                    family=family,
                    epithet=f"Genus{i}",
                    subfamily=f"abcd{i}",
                )
            )
            self.session.add(
                Genus(
                    family=family,
                    epithet=f"Other{i}",
                    subfamily=f"wxyz{i}",
                )
            )
        self.session.commit()
        editor = GenusEditorDialog(Genus(), self.session)

        completions = editor.subfamily_get_completions("abc")
        self.assertEqual(len(completions), 20)
        self.assertTrue(all(i.startswith("abcd") for i in completions))

        editor.destroy()

    def test_on_tribe_entry_changed(self):
        editor = GenusEditorDialog(Genus(), self.session)
        editor.tribe_entry.set_text("Foo")

        self.assertEqual(editor.model.tribe, "Foo")

        editor.destroy()

    def test_tribe_get_completions(self):
        family = Family(epithet="Poaceae")
        for i in range(30):
            self.session.add(
                Genus(
                    family=family,
                    epithet=f"Genus{i}",
                    subfamily="abcd",
                    tribe=f"this{i}",
                )
            )
            self.session.add(
                Genus(
                    family=family,
                    epithet=f"Other{i}",
                    subfamily=f"wxyz{i}",
                    tribe="other{i}",
                )
            )
        self.session.commit()
        editor = GenusEditorDialog(Genus(), self.session)

        completions = editor.tribe_get_completions("this")
        self.assertEqual(len(completions), 20)
        self.assertTrue(all(i.startswith("this") for i in completions))

        editor.subfamily_entry.set_text("abcd")

        completions = editor.tribe_get_completions("this")
        self.assertEqual(len(completions), 20)
        self.assertTrue(all(i.startswith("this") for i in completions))

        editor.subfamily_entry.set_text("wxyz1")

        completions = editor.tribe_get_completions("other")
        self.assertEqual(len(completions), 1)

        completions = editor.tribe_get_completions("this")
        self.assertEqual(len(completions), 0)

        editor.destroy()

    def test_cites_label(self):
        family = Family(epithet="Orchidaceae", cites="II")
        genus = Genus(epithet="Dendrobium", family=family)
        self.session.add(genus)
        self.session.commit()
        editor = GenusEditorDialog(genus, self.session)

        self.assertEqual(editor.cites_label.get_text(), "Family: II")

        family.cites = None
        self.session.commit()
        editor.refresh_cites_label()

        self.assertEqual(editor.cites_label.get_text(), "Family: N/A")

        editor.destroy()

    @mock.patch(
        "bauble.plugins.plants.ui.genus_editor.utils.message_details_dialog"
    )
    def test_on_response_ok(self, mock_dlog):
        family = Family(epithet="Myrtaceae")
        self.session.add(family)
        self.session.commit()
        editor = GenusEditorDialog(Genus(), self.session)
        # fails no epithet or family, use emit here to avoid warning due to:
        # `dialog.stop_emission_by_name("response")`
        editor.emit("response", Response.OK)

        update_gui()
        mock_dlog.assert_called_once()
        mock_dlog.reset_mock()

        editor.model.family = family
        editor.genus_entry.set_text("Eucalyptus")
        self.assertFalse(editor.on_response(editor, Response.OK))

        update_gui()
        mock_dlog.assert_not_called()

        editor.destroy()

    def test_on_response_cancel(self):
        editor = GenusEditorDialog(Genus(), self.session)

        self.assertFalse(editor.on_response(editor, Response.CANCEL))

        editor.destroy()

    @mock.patch("bauble.plugins.plants.ui.genus_editor.create_genus")
    def test_on_response_next(self, mock_callback):
        mock_callback.return_value = False
        family = Family(epithet="Myrtaceae")
        self.session.add(family)
        self.session.commit()
        editor = GenusEditorDialog(
            Genus(epithet="Eucalyptus", family=family),
            self.session,
        )

        self.assertFalse(editor.on_response(editor, Response.NEXT))

        update_gui()

        mock_callback.assert_called_once_with(family=family)

        editor.destroy()

    @mock.patch("bauble.plugins.plants.ui.genus_editor.add_species_callback")
    def test_on_response_add(self, mock_callback):
        family = Family(epithet="Myrtaceae")
        self.session.add(family)
        self.session.commit()
        mock_callback.return_value = False
        editor = GenusEditorDialog(
            Genus(epithet="Eucalyptus", family=family),
            self.session,
        )

        self.assertFalse(editor.on_response(editor, Response.ADD))

        update_gui()

        mock_callback.assert_called_once_with([editor.model])

        editor.destroy()

    @mock.patch("bauble.plugins.plants.ui.family_editor.FamilyEditorDialog")
    def test_on_family_add_button_clicked(self, mock_fam_editor):
        # test bails
        mock_fam_editor().run.return_value = Gtk.ResponseType.CANCEL
        mock_fam_editor.reset_mock()
        genus = Genus(epithet="genus")
        self.session.add(genus)

        editor = GenusEditorDialog(genus, self.session)
        editor.on_family_add_button_clicked(None)

        mock_fam_editor.assert_called_once()
        self.assertEqual(editor.family_entry.get_text(), "")

        # test success
        mock_fam_editor.reset_mock()
        genus = Genus(epithet="Genus")
        self.session.add(genus)

        editor.destroy()

        editor = GenusEditorDialog(genus, self.session)
        editor.family_entry.set_text("Eg")
        mock_fam_editor().run.return_value = Gtk.ResponseType.OK
        mock_fam_editor().model = Family(epithet="Spamaceae")
        mock_fam_editor.reset_mock()
        editor.on_family_add_button_clicked(None)

        mock_fam_editor.assert_called_once()
        self.assertEqual(editor.family_entry.get_text(), "Spamaceae")

        editor.destroy()


class FunctionTests(BaubleTestCase):
    def test_validate_unique_genus(self):
        family = Family(epithet="Myrtaceae")
        genus = Genus(epithet="Eucalyptus", family=family)
        self.session.add(genus)
        self.session.commit()

        self.assertTrue(
            validate_unique_genus(
                "Syzygium",
                "",
                "",
                family,
                genus,
            )
        )
        self.assertTrue(
            validate_unique_genus(
                "Eucalyptus",
                "",
                "",
                family,
                genus,
            )
        )
        self.assertFalse(
            validate_unique_genus(
                "Eucalyptus",
                "",
                "",
                family,
                Genus(),
            )
        )
        self.assertTrue(
            validate_unique_genus(
                "Eucalyptus",
                "Me",
                "",
                family,
                Genus(),
            )
        )
        self.assertTrue(
            validate_unique_genus(
                "Eucalyptus",
                "",
                "s. lat.",
                family,
                Genus(),
            )
        )
        self.assertTrue(
            validate_unique_genus(
                "Eucalyptus",
                "Me",
                "s. lat.",
                family,
                Genus(),
            )
        )

        genus.qualifier = "s. lat."
        self.session.commit()

        self.assertFalse(
            validate_unique_genus(
                "Eucalyptus",
                "",
                "s. lat.",
                family,
                Genus(),
            )
        )
        self.assertTrue(
            validate_unique_genus(
                "Eucalyptus",
                "Me",
                "s. lat.",
                family,
                Genus(),
            )
        )
        self.assertTrue(
            validate_unique_genus(
                "Eucalyptus",
                "Me",
                "",
                family,
                Genus(),
            )
        )

        genus.author = "Me"
        self.session.commit()

        self.assertTrue(
            validate_unique_genus(
                "Eucalyptus",
                "",
                "s. lat.",
                family,
                Genus(),
            )
        )
        self.assertTrue(
            validate_unique_genus(
                "Eucalyptus",
                "Me",
                "",
                family,
                Genus(),
            )
        )
        self.assertFalse(
            validate_unique_genus(
                "Eucalyptus",
                "Me",
                "s. lat.",
                family,
                Genus(),
            )
        )
        self.assertTrue(
            validate_unique_genus(
                "Acmena",
                "Me",
                "s. lat.",
                family,
                Genus(),
            )
        )
        self.assertTrue(
            validate_unique_genus(
                "Eucalyptus",
                "Me",
                "s. lat.",
                family,
                genus,
            )
        )

    def test_edit_callback(self):
        caricaceae = Family(family="Caricaceae")
        gen = Genus(epithet="Carica", family=caricaceae)
        self.session.add(gen)
        self.session.flush()

        with mock.patch.object(edit_callback, "dialog_class") as mock_editor:

            self.assertFalse(edit_callback([gen]))
            mock_editor.assert_called_once()
            self.assertEqual(mock_editor.call_args.kwargs["model"], gen)
            mock_editor().show_all.assert_called_once()

    def test_add_species_callback(self):
        caricaceae = Family(family="Caricaceae")
        gen = Genus(epithet="Carica", family=caricaceae)
        self.session.add(gen)
        self.session.flush()

        with mock.patch(
            "bauble.plugins.plants.ui.genus_editor.edit_species"
        ) as mock_editor:
            mock_editor.return_value = None

            self.assertFalse(add_species_callback([gen]))
            mock_editor.assert_called_once()
            sp = mock_editor.call_args.kwargs["model"]
            self.assertIsInstance(sp, Species)
            self.assertEqual(sp.genus, gen)
