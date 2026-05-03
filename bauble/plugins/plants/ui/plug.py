# Copyright 2026 Ross Demuth <rossdemuth123@gmail.com>
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
plants plugin UI parts
"""
from functools import partial

from gi.repository import Gio

import bauble
from bauble import db
from bauble.i18n import _
from bauble.search.query_builder import ExpressionRow
from bauble.ui.views import HistoryView
from bauble.ui.views import SearchView
from bauble.ui.views import home

from ..family import Family
from ..genus import Genus
from ..geography import Geography
from ..geography import get_species_in_geography
from ..species import Species
from ..species import VernacularName
from .family_editor import create_family
from .family_editor import edit_callback as family_edit_callback
from .family_view import FamilyInfoBox
from .family_view import family_context_menu
from .genus_editor import create_genus
from .genus_editor import edit_callback as genus_edit_callback
from .genus_view import GenusInfoBox
from .genus_view import genus_context_menu
from .geography_view import GeographyInfoBox
from .geography_view import geography_context_menu
from .misc import get_binomial_completions
from .species_editor import create_species
from .species_editor import edit_callback as species_edit_callback
from .species_view import SpeciesInfoBox
from .species_view import VernacularNameInfoBox
from .species_view import species_context_menu
from .species_view import vernname_context_menu
from .widgets.geography import DistributionMap
from .widgets.geography import update_all_approx_areas_handler
from .widgets.species import setup_conservation_fields
from .widgets.species import update_all_full_names_handler

SearchView.row_meta[Family].set(
    children=partial(db.get_active_children, "genera"),
    infobox=FamilyInfoBox(),
    context_menu=family_context_menu,
    activated_callback=family_edit_callback,
)

SearchView.row_meta[Genus].set(
    children=partial(db.get_active_children, "species"),
    infobox=GenusInfoBox(),
    context_menu=genus_context_menu,
    activated_callback=genus_edit_callback,
)

SearchView.row_meta[Species].set(
    children=partial(
        db.get_active_children,
        partial(db.natsort, "accessions"),
    ),
    infobox=SpeciesInfoBox(),
    context_menu=species_context_menu,
    activated_callback=species_edit_callback,
)

SearchView.row_meta[VernacularName].set(
    children=partial(
        db.get_active_children,
        partial(db.natsort, "species.accessions"),
    ),
    infobox=VernacularNameInfoBox(),
    context_menu=vernname_context_menu,
    activated_callback=species_edit_callback,
)

SearchView.row_meta[Geography].set(
    children=partial(db.get_active_children, get_species_in_geography),
    infobox=GeographyInfoBox(),
    context_menu=geography_context_menu,
)

if bauble.gui:
    bauble.gui.add_to_insert_menu(create_family, _("Family"))
    bauble.gui.add_to_insert_menu(create_genus, _("Genus"))
    bauble.gui.add_to_insert_menu(create_species, _("Species"))
    bauble.gui.main_entry_completion_callbacks.add(get_binomial_completions)

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
    bauble.gui.add_action("update_full_name", update_all_full_names_handler)
    bauble.gui.options_menu.append_item(full_names_item)
    bauble.gui.add_action(
        "update_approx_area", update_all_approx_areas_handler
    )
    bauble.gui.options_menu.append_item(geo_areas_item)
    bauble.gui.add_action(
        "setup_conservation_fields", setup_conservation_fields
    )
    bauble.gui.options_menu.append_item(custom_consv_item)

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

# history view translations
note_query = "{table} where notes.id = {obj_id}"
HistoryView.add_translation_query("family_note", "family", note_query)
HistoryView.add_translation_query("genus_note", "genus", note_query)
HistoryView.add_translation_query("species_note", "species", note_query)
pic_query = "{table} where pictures.id = {obj_id}"
HistoryView.add_translation_query("species_picture", "species", pic_query)
syn_query = "{table} where _synonyms.id = {obj_id}"
HistoryView.add_translation_query("family_synonym", "family", syn_query)
HistoryView.add_translation_query("genus_synonym", "genus", syn_query)
HistoryView.add_translation_query("species_synonym", "species", syn_query)
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

# make query builder treat active as a boolean (also accounts for
# accessions and plants)
ExpressionRow.custom_columns["active"] = ("True", "False")


def reset() -> None:
    """on new connection reset"""
    DistributionMap.reset()
