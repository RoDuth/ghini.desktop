# Copyright 2008-2010 Brett Adams
# Copyright 2012-2015 Mario Frasca <mario@anche.no>.
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
plants plugin
"""

import logging

logger = logging.getLogger(__name__)

import os
from functools import partial

from gi.repository import Gio
from sqlalchemy import func
from sqlalchemy import select

import bauble
from bauble import db
from bauble import pluginmgr
from bauble.i18n import _
from bauble.paths import lib_dir
from bauble.search import strategies
from bauble.search.query_builder import ExpressionRow
from bauble.ui.views import HistoryView
from bauble.ui.views import SearchView
from bauble.ui.views import home

from .family import Family
from .genus import Genus
from .geography import Geography
from .geography import get_species_in_geography
from .species import BinomialSearch
from .species import Species
from .species import SpeciesDistribution
from .species import SynonymSearch
from .species import VernacularName
from .species import get_binomial_completions
from .species_model import register_custom_column
from .ui.family_editor import create_family
from .ui.family_editor import edit_callback as family_edit_callback
from .ui.family_view import FamilyInfoBox
from .ui.family_view import family_context_menu
from .ui.genus_editor import create_genus
from .ui.genus_editor import edit_callback as genus_edit_callback
from .ui.genus_view import GenusInfoBox
from .ui.genus_view import genus_context_menu
from .ui.geography_view import GeographyInfoBox
from .ui.geography_view import geography_context_menu
from .ui.species_editor import create_species
from .ui.species_editor import edit_callback as species_edit_callback
from .ui.species_view import SpeciesInfoBox
from .ui.species_view import VernacularNameInfoBox
from .ui.species_view import species_context_menu
from .ui.species_view import vernname_context_menu
from .ui.widgets.geography import DistributionMap
from .ui.widgets.geography import update_all_approx_areas_handler
from .ui.widgets.species import setup_conservation_fields
from .ui.widgets.species import update_all_full_names_handler

# imported by clients of the module
__all__ = ["SpeciesDistribution"]



class PlantsPlugin(pluginmgr.Plugin):
    options_menu_set = False

    family_infobox: FamilyInfoBox | None = None
    genus_infobox: GenusInfoBox | None = None
    species_infobox: SpeciesInfoBox | None = None
    vernacular_infobox: VernacularNameInfoBox | None = None
    geography_infobox: GeographyInfoBox | None = None

    @classmethod
    def init(cls) -> None:
        mapper_search = strategies.get_strategy("MapperSearch")

        if not mapper_search:
            return

        mapper_search.add_meta(("family", "fam"), Family, ["family"])
        mapper_search.add_meta(("genus", "gen"), Genus, ["genus"])
        mapper_search.add_meta(
            ("species", "sp"),
            Species,
            [
                "sp",
                "infrasp1",
                "infrasp2",
                "infrasp3",
                "infrasp4",
                "cultivar_epithet",
                "trade_name",
                "grex",
            ],
        )
        mapper_search.add_meta(
            ("species_full_name", "taxon"), Species, ["full_name"]
        )
        mapper_search.add_meta(
            ("vernacular_name", "vernacular", "vern", "common"),
            VernacularName,
            ["name"],
        )
        mapper_search.add_meta(
            ("geography", "geo"), Geography, ["name", "code", "iso_code"]
        )

        strategies.add_strategy(BinomialSearch)
        strategies.add_strategy(SynonymSearch)

        register_custom_column("_sp_custom1")
        register_custom_column("_sp_custom2")


        if bauble.gui:
            bauble.gui.add_to_insert_menu(create_family, _("Family"))
            bauble.gui.add_to_insert_menu(create_genus, _("Genus"))
            bauble.gui.add_to_insert_menu(create_species, _("Species"))
            bauble.gui.main_entry_completion_callbacks.add(
                get_binomial_completions
            )

        if not cls.options_menu_set:
            cls.setup_options_menu()

        # set infoboxes once.
        if cls.family_infobox is None:
            cls.family_infobox = FamilyInfoBox()
        if cls.genus_infobox is None:
            cls.genus_infobox = GenusInfoBox()
        if cls.species_infobox is None:
            cls.species_infobox = SpeciesInfoBox()
        if cls.vernacular_infobox is None:
            cls.vernacular_infobox = VernacularNameInfoBox()
        if cls.geography_infobox is None:
            cls.geography_infobox = GeographyInfoBox()

        cls.set_search_view_row_meta()

        logger.debug("PlantsPlugin::init, registering home info box")

        cls.set_home_stats_rows()

        cls.add_history_view_translations()

        # make query builder treat active as a boolean (also accounts for
        # accessions and plants)
        ExpressionRow.custom_columns["active"] = ("True", "False")
        # on new connection reset
        DistributionMap.reset()

    @classmethod
    def setup_options_menu(cls) -> None:
        cls.options_menu_set = True

        full_names_item = Gio.MenuItem.new(
            _("Update All Species Full Names"), "win.update_full_name"
        )

        geo_areas_item = Gio.MenuItem.new(
            _("Update All Geographies Area"), "win.update_approx_area"
        )

        custom_consv_item = Gio.MenuItem.new(
            _("Setup Custom Conservation Fields"),
            "win.setup_conservation_fields",
        )

        if bauble.gui:
            bauble.gui.add_action(
                "update_full_name", update_all_full_names_handler
            )
            bauble.gui.options_menu.append_item(full_names_item)
            bauble.gui.add_action(
                "update_approx_area", update_all_approx_areas_handler
            )
            bauble.gui.options_menu.append_item(geo_areas_item)
            bauble.gui.add_action(
                "setup_conservation_fields", setup_conservation_fields
            )
            bauble.gui.options_menu.append_item(custom_consv_item)

    @classmethod
    def set_search_view_row_meta(cls) -> None:

        SearchView.row_meta[Family].set(
            children=partial(db.get_active_children, "genera"),
            infobox=cls.family_infobox,
            context_menu=family_context_menu,
            activated_callback=family_edit_callback,
        )

        SearchView.row_meta[Genus].set(
            children=partial(db.get_active_children, "species"),
            infobox=cls.genus_infobox,
            context_menu=genus_context_menu,
            activated_callback=genus_edit_callback,
        )

        SearchView.row_meta[Species].set(
            children=partial(
                db.get_active_children, partial(db.natsort, "accessions")
            ),
            infobox=cls.species_infobox,
            context_menu=species_context_menu,
            activated_callback=species_edit_callback,
        )

        SearchView.row_meta[VernacularName].set(
            children=partial(
                db.get_active_children,
                partial(db.natsort, "species.accessions"),
            ),
            infobox=cls.vernacular_infobox,
            context_menu=vernname_context_menu,
            activated_callback=species_edit_callback,
        )

        SearchView.row_meta[Geography].set(
            children=partial(db.get_active_children, get_species_in_geography),
            infobox=cls.geography_infobox,
            context_menu=geography_context_menu,
        )

    @classmethod
    def set_home_stats_rows(cls) -> None:
        if home.StatsGrid.initialised:
            return

        home.StatsGrid.stats_rows.append(
            home.StatsRow(
                _("Families:"),
                "SELECT COUNT(*) FROM family",
                "family like %",
                (
                    "SELECT COUNT(DISTINCT genus.family_id) FROM genus "
                    "JOIN species ON species.genus_id=genus.id "
                    "JOIN accession ON accession.species_id=species.id"
                ),
                "family where genera.species.accessions.id != 0",
                (
                    "SELECT COUNT(id) FROM family WHERE id NOT IN (SELECT "
                    "DISTINCT genus.family_id FROM genus "
                    "JOIN species ON species.genus_id=genus.id "
                    "JOIN accession ON accession.species_id=species.id)"
                ),
                "family where not genera.species.accessions.id != 0",
                1,
            )
        )
        home.StatsGrid.stats_rows.append(
            home.StatsRow(
                _("Genera:"),
                "SELECT COUNT(*) FROM genus",
                "genus like %",
                (
                    "SELECT COUNT(DISTINCT species.genus_id) FROM species "
                    "JOIN accession ON accession.species_id=species.id"
                ),
                "genus where species.accessions.id != 0",
                (
                    "SELECT COUNT(id) FROM genus WHERE id NOT IN (SELECT "
                    "DISTINCT species.genus_id FROM species "
                    "JOIN accession ON accession.species_id=species.id)"
                ),
                "genus where not species.accessions.id != 0",
                2,
            )
        )
        home.StatsGrid.stats_rows.append(
            home.StatsRow(
                _("Species:"),
                "SELECT COUNT(*) FROM species",
                "species like %",
                (
                    "SELECT COUNT(DISTINCT species.id) FROM species "
                    "JOIN accession ON accession.species_id=species.id"
                ),
                "species where not accessions = Empty",
                (
                    "SELECT COUNT(id) FROM species WHERE id NOT IN (SELECT "
                    "DISTINCT species.id FROM species "
                    "JOIN accession ON accession.species_id=species.id)"
                ),
                "species where accessions = Empty",
                3,
                True,
            )
        )
        # TODO move to garden plugin
        home.StatsGrid.stats_rows.append(
            home.StatsRow(
                _("Accessions:"),
                "SELECT COUNT(*) FROM accession",
                "accession like %",
                (
                    "SELECT COUNT(DISTINCT accession.id) FROM accession "
                    "JOIN plant ON plant.accession_id=accession.id "
                    "WHERE plant.quantity>0"
                ),
                "accession where sum(plants.quantity) > 0",
                (
                    "SELECT COUNT(id) FROM accession WHERE id NOT IN (SELECT "
                    "DISTINCT accession_id FROM plant WHERE plant.quantity>0)"
                ),
                "accession where plants = Empty or sum(plants.quantity)=0",
                4,
                True,
            )
        )
        home.StatsGrid.stats_rows.append(
            home.StatsRow(
                _("Plants:"),
                "SELECT COUNT(*) FROM plant",
                "plant like %",
                "SELECT COUNT(*) FROM plant WHERE quantity>0",
                "plant where sum(quantity) > 0",
                "SELECT COUNT(*) FROM plant WHERE quantity=0",
                "plant where sum(quantity) = 0",
                5,
                True,
            )
        )
        home.StatsGrid.stats_rows.append(
            home.StatsRow(
                _("Locations:"),
                "SELECT COUNT(*) FROM location",
                "location like %",
                (
                    "SELECT COUNT(DISTINCT location.id) FROM location "
                    "JOIN plant ON plant.location_id=location.id "
                    "WHERE plant.quantity>0"
                ),
                "location where sum(plants.quantity) > 0",
                (
                    "SELECT COUNT(id) FROM location WHERE id NOT IN (SELECT "
                    "DISTINCT location_id FROM plant WHERE plant.quantity>0)"
                ),
                "location where plants = Empty or sum(plants.quantity)=0",
                6,
            )
        )

    @classmethod
    def add_history_view_translations(cls) -> None:
        note_query = "{table} where notes.id = {obj_id}"
        HistoryView.add_translation_query("family_note", "family", note_query)
        HistoryView.add_translation_query("genus_note", "genus", note_query)
        HistoryView.add_translation_query(
            "species_note", "species", note_query
        )
        pic_query = "{table} where pictures.id = {obj_id}"
        HistoryView.add_translation_query(
            "species_picture", "species", pic_query
        )
        syn_query = "{table} where _synonyms.id = {obj_id}"
        HistoryView.add_translation_query(
            "family_synonym", "family", syn_query
        )
        HistoryView.add_translation_query("genus_synonym", "genus", syn_query)
        HistoryView.add_translation_query(
            "species_synonym", "species", syn_query
        )

        HistoryView.add_translation_query(
            "default_vernacular_name",
            "species",
            "{table} where _default_vernacular_name.id = {obj_id}",
        )

        HistoryView.add_translation_query(
            "species_distribution",
            "species",
            "{table} where distribution.id = {obj_id}",
        )

    @classmethod
    def install(cls, import_defaults=True) -> None:
        """Do any setup and configuration required by this plugin like creating
        tables, etc...
        """
        if not import_defaults:
            return

        path = os.path.join(lib_dir(), "plugins", "plants", "default")
        filenames = [
            os.path.join(path, f)
            for f in (
                "family.csv",
                "family_synonym.csv",
                "genus.csv",
                "genus_synonym.csv",
                "habit.csv",
                "geography.csv",
            )
        ]

        # confirm we are not just recovering from a failure where the plugin
        # was lost.
        try:
            with db.engine.connect() as con:
                fams = con.scalar(select(func.count()).select_from(Family))
                gens = con.scalar(select(func.count()).select_from(Genus))
                geos = con.scalar(select(func.count()).select_from(Geography))
                if gens > 0 or fams > 0 or geos > 0:
                    logger.warning(
                        "PlantsPlugin::install, not importing defaults "
                        "%s families, %s genera and %s geographies found",
                        fams,
                        gens,
                        geos,
                    )
                    return
        except Exception as e:  # pylint: disable=broad-except
            logger.info("checking existing: %s(%s)", type(e).__name__, e)
            raise

        # avoids circular import
        from bauble.plugins.imex.csv_ import CSVRestore

        csv = CSVRestore()
        csv.start(filenames, metadata=db.metadata, force=True)


plugin = PlantsPlugin  # pylint: disable=invalid-name
