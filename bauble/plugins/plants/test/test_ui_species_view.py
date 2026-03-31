# pylint: disable=no-self-use,protected-access,too-many-statements
# Copyright 2008-2010 Brett Adams
# Copyright 2015 Mario Frasca <mario@anche.no>.
# Copyright 2021-2026 Ross Demuth <rossdemuth123@gmail.com>
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
Species search view tests
"""
from datetime import datetime
from unittest import mock

from gi.repository import Gdk
from gi.repository import Gtk
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from bauble import prefs
from bauble.meta import BaubleMeta
from bauble.plugins.plants.family import Family
from bauble.plugins.plants.genus import Genus
from bauble.plugins.plants.species import Species
from bauble.plugins.plants.species import VernacularName
from bauble.test import BaubleTestCase
from bauble.test import get_setUp_data_funcs
from bauble.ui.views import SearchView

from ...garden import Accession
from ...garden import Plant
from ...garden.accession import Verification
from .. import PlantsPlugin
from ..test_plants import setUp_data as setup_plants_data
from ..ui.misc import on_taxa_clicked
from ..ui.species_editor import SPECIES_WEB_BUTTON_DEFS_PREFS
from ..ui.species_view import GeneralSpeciesExpander
from ..ui.species_view import SpeciesInfoBox
from ..ui.species_view import SynonymsExpander
from ..ui.species_view import VernacularExpander
from ..ui.species_view import remove_callback


class SpeciesInfoBoxTests(BaubleTestCase):
    @mock.patch("bauble.plugins.plants.ui.species_view.on_clicked_search")
    def test_vernacular_expander(self, mock_search):
        expander = VernacularExpander()
        fam = Family(epithet="Myrtaceae")
        gen = Genus(family=fam, epithet="Syzygium")
        sp = Species(genus=gen, epithet="australe")
        vern = VernacularName(name="Creek Satinash", language="EN")
        sp.vernacular_names.append(vern)
        vern2 = VernacularName(name="Brush Cherry")
        sp.vernacular_names.append(vern2)
        default = VernacularName(name="Scrub Cherry", language="EN")
        sp.default_vernacular_name = default

        expander.update(sp)
        eboxes = expander.box.get_children()

        self.assertEqual(len(eboxes), 3)
        self.assertEqual(
            eboxes[0].get_child().get_text(),
            "Scrub Cherry - EN (default)",
        )
        self.assertEqual(
            eboxes[1].get_child().get_text(),
            "Brush Cherry",
        )
        self.assertEqual(
            eboxes[2].get_child().get_text(),
            "Creek Satinash - EN",
        )

        event = Gdk.Event()
        eboxes[0].emit("button_press_event", event)
        eboxes[0].emit("button_release_event", event)

        mock_search.assert_called_once()
        self.assertEqual(
            mock_search.call_args.args[0],
            eboxes[0].get_child(),
        )
        self.assertEqual(
            mock_search.call_args.args[2],
            "vernacular_name where name = 'Scrub Cherry'",
        )

    @mock.patch("bauble.plugins.plants.ui.widgets.synonyms.on_clicked_select")
    def test_synonyms_expander_w_accepted(self, mock_select):
        expander = SynonymsExpander()
        fam = Family(epithet="Myrtaceae")
        gen = Genus(family=fam, epithet="Syzygium")
        sp = Species(genus=gen, epithet="australe")
        gen = Genus(family=fam, epithet="Myrtus")
        syn1 = Species(genus=gen, epithet="australis")
        sp.synonyms.append(syn1)

        expander.update(syn1)
        eboxes = expander.box.get_children()

        self.assertEqual(len(eboxes), 1)
        self.assertEqual(expander.get_label(), "Accepted name")
        self.assertEqual(
            eboxes[0].get_child().get_text(),
            "Syzygium australe",
        )

        event = Gdk.Event()
        eboxes[0].emit("button_press_event", event)
        eboxes[0].emit("button_release_event", event)

        mock_select.assert_called_once()
        self.assertEqual(
            mock_select.call_args.args[0],
            eboxes[0].get_child(),
        )
        self.assertEqual(
            mock_select.call_args.args[2],
            sp,
        )

    @mock.patch("bauble.plugins.plants.ui.widgets.synonyms.on_clicked_select")
    def test_synonyms_expander_w_syns(self, mock_select):
        expander = SynonymsExpander()
        fam = Family(epithet="Myrtaceae")
        gen = Genus(family=fam, epithet="Syzygium")
        sp = Species(genus=gen, epithet="australe")
        gen = Genus(family=fam, epithet="Myrtus")
        syn1 = Species(genus=gen, epithet="australis")
        sp.synonyms.append(syn1)
        gen = Genus(family=fam, epithet="Eugenia")
        syn2 = Species(genus=gen, epithet="australis")
        sp.synonyms.append(syn2)

        expander.update(sp)
        eboxes = expander.box.get_children()

        self.assertEqual(len(eboxes), 2)
        self.assertEqual(expander.get_label(), "Synonyms")
        self.assertEqual(
            eboxes[0].get_child().get_text(),
            "Eugenia australis",
        )
        self.assertEqual(
            eboxes[1].get_child().get_text(),
            "Myrtus australis",
        )

        event = Gdk.Event()
        eboxes[0].emit("button_press_event", event)
        eboxes[0].emit("button_release_event", event)

        mock_select.assert_called_once()
        self.assertEqual(
            mock_select.call_args.args[0],
            eboxes[0].get_child(),
        )
        self.assertEqual(
            mock_select.call_args.args[2],
            syn2,
        )

    def test_general_expander(self):
        setup_plants_data()
        # at least tests nothing errors
        spp = self.session.scalars(
            select(Species).where(Species.id.in_((15, 27, 31)))
        )

        expander = GeneralSpeciesExpander()
        for sp in spp:
            expander.update(sp)
            self.assertEqual(
                expander.name_label.get_label(),
                f" <big>{sp.markup(authors=True, genus=False)}</big>",
            )

    def test_general_setup_custom_column(self):
        meta = BaubleMeta(
            name="_sp_custom1",
            value=(
                "{'field_name': 'nca_status', "
                "'display_name': 'NCA Status', "
                "'values': ('extinct', 'vulnerable', None)}"
            ),
        )
        self.session.add(meta)
        self.session.commit()
        sp = self.session.get(Species, 1)
        # effectively also tests PlantsPlugin.register_custom_column
        PlantsPlugin.register_custom_column("_sp_custom1")
        infobox = SearchView.row_meta[Species].infobox

        general = infobox.get_nth_page(0).expanders["General"]
        general._setup_custom_column("_sp_custom1")

        self.assertEqual(general._sp_custom1_label.get_text(), "NCA Status:")
        self.assertTrue(general._sp_custom1_label.get_visible())

        # change the db connection
        self.tearDown()
        self.setUp()
        family = Family(family="family")
        genus = Genus(family=family, genus="genus")
        sp = Species(genus=genus, sp="sp")
        self.session.add(sp)
        self.session.commit()
        PlantsPlugin.register_custom_column("_sp_custom1")
        infobox = SearchView.row_meta[Species].infobox

        general._setup_custom_column("_sp_custom1")

        self.assertEqual(general._sp_custom1_label.get_text(), "_custom_")
        self.assertFalse(general._sp_custom1_label.get_visible())

    @mock.patch("bauble.gui")
    def test_general_label_markup(self, _mock_gui):
        fam = Family(family="Asparagaceae")
        gen = Genus(genus="Liriope", family=fam)
        sp = Species(genus=gen, sp="muscari")
        self.session.add(sp)
        self.session.commit()
        expander = GeneralSpeciesExpander()

        expander.update(sp)

        self.assertFalse(expander.label_markup_data_label.get_visible())

        sp.cultivar_epithet = "LIRF"
        sp.trade_name = "Isabella"
        sp.trademark_symbol = "®"
        sp.label_markup = "<i>Liriope</i> I<small>SABELLA</small>®"

        expander.update(sp)

        self.assertTrue(expander.label_markup_data_label.get_visible())
        self.assertEqual(
            expander.name_label.get_label(),
            " <big><i>muscari</i> 'LIRF' I<small>SABELLA</small>®</big>",
        )
        self.assertEqual(
            expander.label_markup_data_label.get_label(),
            "<i>Liriope</i> I<small>SABELLA</small>®",
        )

    @mock.patch(
        "bauble.plugins.plants.ui.species_view.select_in_search_results"
    )
    def test_general_plant_selector_selects_plant(self, mock_select):
        for func in get_setUp_data_funcs():
            func()

        sp = self.session.scalars(
            select(Species).join(Accession).join(Plant)
        ).first()

        with mock.patch("bauble.gui"):
            expander = GeneralSpeciesExpander()
            expander.update(sp)
            first_ebox = expander.plant_locations_box.get_children()[0]
            first_ebox.emit("button_press_event", None)
            first_ebox.emit("button_release_event", None)
            calls = mock_select.call_args_list

            self.assertEqual(len(calls), 2)
            self.assertEqual(calls[0].args, (sp.accessions[0],))
            self.assertEqual(calls[0].kwargs, {"expand_current_first": True})
            self.assertEqual(calls[1].args, (sp.accessions[0].plants[0],))
            self.assertEqual(calls[1].kwargs, {"expand_current_first": True})

    def test_general_expander_on_areas_expanded(self):
        self.assertFalse(
            prefs.prefs.get(GeneralSpeciesExpander.GEO_AREAS_EXPANDED_PREF)
        )
        mock_expander = mock.Mock()
        mock_expander.get_expanded.return_value = False
        GeneralSpeciesExpander.on_areas_expanded(mock_expander)
        self.assertTrue(
            prefs.prefs.get(GeneralSpeciesExpander.GEO_AREAS_EXPANDED_PREF)
        )

    @mock.patch(
        "bauble.plugins.plants.ui.species_view.select_in_search_results"
    )
    def test_general_expander_select_all_areas(self, mock_select):
        mock_sp = mock.Mock()
        mock_geo = mock.Mock(geography="TEST")
        mock_sp.distribution = [mock_geo]
        GeneralSpeciesExpander.select_all_areas(None, None, mock_sp)

        mock_select.assert_called_with("TEST")

    def test_general_expander_details(self):
        setup_plants_data()
        # no details hides
        sp = self.session.get(Species, 1)
        expander = GeneralSpeciesExpander()
        expander.update(sp)

        self.assertFalse(expander.has_details)
        self.assertFalse(expander.details_box.get_visible())

        # all details unhides all
        sp = self.session.get(Species, 33)
        expander.update(sp)

        self.assertTrue(expander.has_details)
        self.assertTrue(expander.details_box.get_visible())
        for widget in expander.details_box.get_children():
            self.assertTrue(widget.get_child().get_visible())

        # some details hides some
        sp = self.session.get(Species, 30)
        expander.update(sp)

        self.assertTrue(expander.has_details)
        self.assertTrue(expander.details_box.get_visible())
        self.assertTrue(expander.subgen_label.get_visible())
        self.assertTrue(expander.series_label.get_visible())
        self.assertFalse(expander.section_label.get_visible())
        self.assertFalse(expander.subsection_label.get_visible())
        self.assertFalse(expander.subseries_label.get_visible())

    def test_general_expander_verifications(self):
        for func in get_setUp_data_funcs():
            func()

        sp = self.session.get(Species, 3)
        acc = sp.accessions[0]
        with mock.patch("bauble.gui") as mock_gui:
            expander = GeneralSpeciesExpander()
            ver_box = expander.verifications_box

            # base case
            self.assertEqual(len(ver_box.get_children()), 0)

            # no verifications
            expander.update(sp)

            self.assertEqual(len(ver_box.get_children()), 0)

            # prev and new match should only count as new.
            acc.verifications.append(
                Verification(
                    verifier="Jade Green",
                    date=datetime.today(),
                    level=2,
                    species=sp,
                    prev_species=sp,
                )
            )
            self.session.commit()
            expander.update(sp)
            labels = []
            for i in ver_box.get_children():
                if isinstance(i, Gtk.EventBox):
                    labels.append(i.get_children()[0].get_text())

            self.assertEqual(len(labels), 1)
            self.assertNotIn("0 prev.", labels)
            self.assertIn("1 new", labels)

            # both a previous and new
            sp4 = self.session.get(Species, 4)
            acc.verifications.append(
                Verification(
                    verifier="Jade Green",
                    date=datetime.today(),
                    level=2,
                    species=sp4,
                    prev_species=sp,
                )
            )
            self.session.commit()
            expander.update(sp)
            labels = []
            for i in ver_box.get_children():
                if isinstance(i, Gtk.EventBox):
                    label = i.get_children()[0].get_text()
                    labels.append(label)
                    # test sends command
                    event = Gdk.Event()
                    i.emit("button_press_event", event)
                    i.emit("button_release_event", event)

                    if label.endswith("prev."):
                        mock_gui.send_command.assert_called_once_with(
                            "accession where verifications.prev_species.id = 3"
                        )
                    else:
                        mock_gui.send_command.assert_called_once_with(
                            "accession where verifications.species.id = 3"
                        )
                    mock_gui.reset_mock()

                else:
                    self.assertEqual(i.get_text(), ", ")

            self.assertEqual(len(labels), 2)
            self.assertIn("1 prev.", labels)
            self.assertIn("1 new", labels)

            # prev and new don't match
            sp = self.session.get(Species, 1)
            expander.update(sp)
            labels = []
            for i in ver_box.get_children():
                if isinstance(i, Gtk.EventBox):
                    labels.append(i.get_children()[0].get_text())

            self.assertEqual(len(labels), 1)
            self.assertIn("1 prev.", labels)
            self.assertNotIn("0 new", labels)

            sp = self.session.get(Species, 2)
            expander.update(sp)
            labels = []
            for i in ver_box.get_children():
                if isinstance(i, Gtk.EventBox):
                    labels.append(i.get_children()[0].get_text())

            self.assertEqual(len(labels), 1)
            self.assertNotIn("0 prev.", labels)
            self.assertIn("1 new", labels)

    @mock.patch("bauble.plugins.plants.ui.misc.select_in_search_results")
    def test_on_taxa_clicked(self, mock_select):
        prefs.prefs[prefs.return_accepted_pref] = False
        fam = Family(epithet="Spam")
        fam2 = Family(epithet="Eggs")
        fam.synonyms.append(fam2)

        on_taxa_clicked(None, None, fam2)

        mock_select.assert_called_once_with(fam2)

        mock_select.reset_mock()
        prefs.prefs[prefs.return_accepted_pref] = True

        on_taxa_clicked(None, None, fam2)

        args = mock_select.call_args_list

        self.assertEqual(len(args), 2)
        self.assertEqual(args[0].args, (fam,))
        self.assertEqual(args[1].args, (fam2,))

    def test_species_info_box_links(self):
        infobox = SpeciesInfoBox()
        links = infobox.get_nth_page(0).expanders["Links"]
        self.assertTrue(len(links.web_links) > 0)

        self.assertEqual(
            len(links.web_links),
            len(list(prefs.prefs.itersection(SPECIES_WEB_BUTTON_DEFS_PREFS))),
        )


class FunctionTests(BaubleTestCase):
    def test_remove_callback_no_accessions_no_confirm(self):
        caricaceae = Family(family="Caricaceae")
        gen = Genus(epithet="Carica", family=caricaceae)
        sp = Species(epithet="papaya", genus=gen)
        self.session.add_all([caricaceae, gen, sp])
        self.session.flush()

        with mock.patch("bauble.ui.dialogs.yes_no_dialog") as mock_dlog:
            mock_dlog.return_value = False
            result = remove_callback([sp])
            mock_dlog.assert_called_once_with(
                "Are you sure you want to remove the following species "
                "<i>Carica papaya</i>?",
            )

        self.assertFalse(result)
        self.assertEqual(
            self.session.scalars(
                select(Species).where(Species.epithet == "papaya")
            ).all(),
            [sp],
        )

    def test_remove_callback_no_accessions_confirm(self):
        caricaceae = Family(family="Caricaceae")
        gen = Genus(epithet="Carica", family=caricaceae)
        sp = Species(epithet="papaya", genus=gen)
        self.session.add_all([caricaceae, gen, sp])
        self.session.flush()

        with mock.patch("bauble.ui.dialogs.yes_no_dialog") as mock_dlog:
            mock_dlog.return_value = True
            result = remove_callback([sp])
            mock_dlog.assert_called_once_with(
                "Are you sure you want to remove the following species "
                "<i>Carica papaya</i>?",
            )

        self.assertTrue(result)
        self.assertEqual(
            self.session.scalars(
                select(Species).where(Species.epithet == "papaya")
            ).all(),
            [],
        )

    def test_remove_callback_with_accessions_cant_cascade(self):
        caricaceae = Family(family="Caricaceae")
        gen = Genus(epithet="Carica", family=caricaceae)
        sp = Species(epithet="papaya", genus=gen)
        vern = VernacularName(name="Pawpaw")
        sp.default_vernacular_name = vern

        acc = Accession(code="0123456", species=sp)
        self.session.add_all([caricaceae, gen, sp, acc])
        self.session.flush()

        with mock.patch("bauble.ui.dialogs.message_dialog") as mock_dlog:
            mock_dlog.return_value = True
            result = remove_callback([vern])
            mock_dlog.assert_called_once_with(
                "The species <i>Carica papaya</i> has 1 accessions."
                "\n\nYou cannot remove a species with accessions.",
                typ=Gtk.MessageType.WARNING,
            )

        self.assertFalse(result)
        self.assertEqual(
            self.session.scalars(
                select(Species).where(Species.epithet == "papaya")
            ).all(),
            [sp],
        )
        self.assertEqual(
            self.session.scalars(
                select(Accession).where(Accession.species == sp)
            ).all(),
            [acc],
        )

    def test_remove_callback_bails_not_session(self):
        caricaceae = Family(family="Caricaceae")
        gen = Genus(epithet="Carica", family=caricaceae)
        sp = Species(epithet="papaya", genus=gen)
        self.session.add(sp)
        self.session.flush()

        with mock.patch(
            "bauble.plugins.plants.ui.species_view.object_session"
        ):
            self.assertFalse(remove_callback([sp]))

    @mock.patch("bauble.ui.dialogs.yes_no_dialog")
    @mock.patch("bauble.ui.dialogs.message_details_dialog")
    def test_remove_callback_commit_exception(self, mock_d_dlog, mock_yn_dlog):
        mock_yn_dlog.return_value = True
        mock_d_dlog.return_value = True
        caricaceae = Family(family="Caricaceae")
        gen = Genus(epithet="Carica", family=caricaceae)
        sp = Species(epithet="papaya", genus=gen)
        self.session.add(sp)
        self.session.flush()

        with (
            mock.patch.object(
                self.session, "commit", side_effect=SQLAlchemyError
            ),
            mock.patch.object(self.session, "rollback") as mock_rollback,
        ):
            self.assertFalse(remove_callback([sp]))
            mock_rollback.assert_called()
            mock_d_dlog.assert_called()

    # def test_edit_callback(self):
    #     caricaceae = Family(family="Caricaceae")
    #     gen = Genus(epithet="Carica", family=caricaceae)
    #     sp = Species(epithet="papaya", genus=gen)
    #     vern = VernacularName(name="Pawpaw")
    #     sp.default_vernacular_name = vern
    #     self.session.add(sp)
    #     self.session.flush()

    #     from .ui.species_view import edit_callback

    #     with mock.patch(
    #         "bauble.plugins.plants.species.edit_species"
    #     ) as mock_edit:
    #         mock_edit.return_value = None

    #         self.assertFalse(edit_callback([sp]))

    #         mock_edit.return_value = sp
    #         self.assertTrue(edit_callback([vern]))

    # def test_add_accession_callback(self):
    #     caricaceae = Family(family="Caricaceae")
    #     gen = Genus(epithet="Carica", family=caricaceae)
    #     sp = Species(epithet="papaya", genus=gen)
    #     vern = VernacularName(name="Pawpaw")
    #     sp.default_vernacular_name = vern
    #     self.session.add(sp)
    #     self.session.flush()

    #     from ..garden import Accession
    #     from .ui.species_view import add_accession_callback

    #     with mock.patch(
    #         "bauble.plugins.garden.accession.AccessionEditor"
    #     ) as mock_edit:
    #         mock_edit().start.return_value = None

    #         self.assertFalse(add_accession_callback([sp]))
    #         acc = mock_edit.call_args.kwargs["model"]
    #         self.assertIsInstance(acc, Accession)
    #         self.assertEqual(acc.species, sp)
    #         mock_edit.reset_mock()

    #         mock_edit().start.return_value = True
    #         self.assertTrue(add_accession_callback([vern]))
    #         acc = mock_edit.call_args.kwargs["model"]
    #         self.assertIsInstance(acc, Accession)
    #         self.assertEqual(acc.species, sp)
