# Copyright 2008-2010 Brett Adams
# Copyright 2012-2015 Mario Frasca <mario@anche.no>.
# Copyright 2021-2025 Ross Demuth <rossdemuth123@gmail.com>
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
import os
from ast import literal_eval
from functools import partial
from pathlib import Path
from threading import Thread

logger = logging.getLogger(__name__)

from gi.repository import Gio
from gi.repository import GLib
from gi.repository import Gtk
from sqlalchemy import Column
from sqlalchemy.exc import OperationalError

import bauble
from bauble import db
from bauble import pluginmgr
from bauble import prefs
from bauble import search
from bauble import utils
from bauble.i18n import _
from bauble.paths import lib_dir
from bauble.search.query_builder import ExpressionRow
from bauble.search.stored_queries import StoredQueriesButtonBox
from bauble.ui import dialogs
from bauble.ui.views import HistoryView
from bauble.ui.views import HomeView
from bauble.ui.views import SearchView
from bauble.ui.views import View

from .family import Familia
from .family import Family
from .genus import Genus
from .geography import DistributionMap
from .geography import Geography
from .geography import GeographyInfoBox
from .geography import geography_context_menu
from .geography import get_species_in_geography
from .geography import update_all_approx_areas_handler
from .species import BinomialSearch
from .species import Species
from .species import SpeciesDistribution
from .species import SpeciesInfoBox
from .species import SynonymSearch
from .species import VernacularName
from .species import VernacularNameInfoBox
from .species import get_binomial_completions
from .species_model import update_all_full_names_handler
from .ui.family_editor import create_family
from .ui.family_editor import edit_callback as family_edit_callback
from .ui.family_view import FamilyInfoBox
from .ui.family_view import family_context_menu
from .ui.genus_editor import create_genus
from .ui.genus_editor import edit_callback as genus_edit_callback
from .ui.genus_view import GenusInfoBox
from .ui.genus_view import genus_context_menu
from .ui.species_editor import create_species
from .ui.species_editor import edit_callback as species_edit_callback
from .ui.species_view import species_context_menu
from .ui.species_view import vernname_context_menu

# imported by clients of the module
__all__ = ["Familia", "SpeciesDistribution"]


class LabelUpdater(Thread):
    def __init__(self, label_queries, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.label_queries = label_queries

    def run(self):
        with db.Session() as session:
            for label, query in self.label_queries:
                try:
                    value = session.execute(query).first()[0]
                    GLib.idle_add(label.set_text, str(value))
                except OperationalError as e:
                    # capture except for test_main empty db
                    logger.debug("Empty database? %s(%s)", type(e).__name__, e)
                    return


@Gtk.Template(filename=str(Path(__file__).resolve().parent / "home_info.ui"))
class HomeInfoBox(View, Gtk.Box):
    """info box shown in the initial home screen."""

    __gtype_name__ = "HomeInfoBox"

    home_nlocnot = Gtk.Template.Child()
    home_nlocuse = Gtk.Template.Child()
    home_nloctot = Gtk.Template.Child()
    home_npltnot = Gtk.Template.Child()
    home_npltuse = Gtk.Template.Child()
    home_nplttot = Gtk.Template.Child()
    home_naccnot = Gtk.Template.Child()
    home_naccuse = Gtk.Template.Child()
    home_nacctot = Gtk.Template.Child()
    home_nspcnot = Gtk.Template.Child()
    home_nspcuse = Gtk.Template.Child()
    home_nspctot = Gtk.Template.Child()
    home_ngennot = Gtk.Template.Child()
    home_ngenuse = Gtk.Template.Child()
    home_ngentot = Gtk.Template.Child()
    home_nfamtot = Gtk.Template.Child()
    home_nfamuse = Gtk.Template.Child()
    home_nfamnot = Gtk.Template.Child()

    def __init__(self):
        logger.debug("HomeInfoBox::__init__")
        super().__init__()

        self.name_tooltip_query = None

        on_clicked_search = utils.generate_on_clicked(bauble.gui.send_command)

        utils.make_label_clickable(
            self.home_nfamtot, on_clicked_search, "family like %"
        )

        utils.make_label_clickable(
            self.home_nfamuse,
            on_clicked_search,
            "family where genera.species.accessions.id != 0",
        )

        utils.make_label_clickable(
            self.home_nfamnot,
            on_clicked_search,
            "family where not genera.species.accessions.id != 0",
        )

        utils.make_label_clickable(
            self.home_ngentot, on_clicked_search, "genus like %"
        )

        utils.make_label_clickable(
            self.home_ngenuse,
            on_clicked_search,
            "genus where species.accessions.id!=0",
        )

        utils.make_label_clickable(
            self.home_ngennot,
            on_clicked_search,
            "genus where not species.accessions.id!=0",
        )

        utils.make_label_clickable(
            self.home_nspctot, on_clicked_search, "species like %"
        )

        utils.make_label_clickable(
            self.home_nspcuse,
            on_clicked_search,
            "species where not accessions = Empty",
        )

        utils.make_label_clickable(
            self.home_nspcnot,
            on_clicked_search,
            "species where accessions = Empty",
        )

        utils.make_label_clickable(
            self.home_nacctot, on_clicked_search, "accession like %"
        )

        utils.make_label_clickable(
            self.home_naccuse,
            on_clicked_search,
            "accession where sum(plants.quantity)>0",
        )

        utils.make_label_clickable(
            self.home_naccnot,
            on_clicked_search,
            "accession where plants = Empty or sum(plants.quantity)=0",
        )

        utils.make_label_clickable(
            self.home_nplttot, on_clicked_search, "plant like %"
        )

        utils.make_label_clickable(
            self.home_npltuse,
            on_clicked_search,
            "plant where sum(quantity)>0",
        )

        utils.make_label_clickable(
            self.home_npltnot,
            on_clicked_search,
            "plant where sum(quantity)=0",
        )

        utils.make_label_clickable(
            self.home_nloctot, on_clicked_search, "location like %"
        )

        utils.make_label_clickable(
            self.home_nlocuse,
            on_clicked_search,
            "location where sum(plants.quantity)>0",
        )

        utils.make_label_clickable(
            self.home_nlocnot,
            on_clicked_search,
            "location where plants is Empty or sum(plants.quantity)=0",
        )
        self.stored_queries_button_box = StoredQueriesButtonBox()
        self.pack_start(self.stored_queries_button_box, True, True, 0)

    def update(self, *_args):
        self.stored_queries_button_box.refresh()
        # desensitise links that wont work.
        sensitive = not prefs.prefs.get(prefs.exclude_inactive_pref)
        for widget in [
            self.home_nplttot,
            self.home_npltnot,
            self.home_nacctot,
            self.home_naccnot,
            self.home_nspctot,
            self.home_nspcnot,
        ]:
            widget.get_parent().set_sensitive(sensitive)

        logger.debug("HomeInfoBox::update")
        statusbar = bauble.gui.widgets.statusbar
        sbcontext_id = statusbar.get_context_id("searchview.nresults")
        statusbar.pop(sbcontext_id)
        bauble.gui.widgets.main_comboentry.get_child().set_text("")

        self.start_thread(
            LabelUpdater(
                (
                    (self.home_nplttot, "select count(*) from plant"),
                    (
                        self.home_npltuse,
                        "select count(*) from plant where quantity>0",
                    ),
                    (
                        self.home_npltnot,
                        "select count(*) from plant where quantity=0",
                    ),
                    (self.home_nacctot, "select count(*) from accession"),
                    (
                        self.home_naccuse,
                        "select count(distinct accession.id) "
                        "from accession "
                        "join plant on plant.accession_id=accession.id "
                        "where plant.quantity>0",
                    ),
                    (
                        self.home_naccnot,
                        "select count(id) "
                        "from accession "
                        "where id not in "
                        "(select accession_id from plant "
                        " where plant.quantity>0)",
                    ),
                    (self.home_nloctot, "select count(*) from location"),
                    (
                        self.home_nlocuse,
                        "select count(distinct location.id) "
                        "from location "
                        "join plant on plant.location_id=location.id "
                        "where plant.quantity>0",
                    ),
                    (
                        self.home_nlocnot,
                        "select count(id) "
                        "from location "
                        "where id not in "
                        "(select location_id from plant "
                        " where plant.quantity>0)",
                    ),
                    (
                        self.home_nspcuse,
                        "select count(distinct species.id) "
                        "from species join accession "
                        "on accession.species_id=species.id",
                    ),
                    (
                        self.home_ngenuse,
                        "select count(distinct species.genus_id) "
                        "from species join accession "
                        "on accession.species_id=species.id",
                    ),
                    (
                        self.home_nfamuse,
                        "select count(distinct genus.family_id) from genus "
                        "join species on species.genus_id=genus.id "
                        "join accession on accession.species_id=species.id ",
                    ),
                    (self.home_nspctot, "select count(*) from species"),
                    (self.home_ngentot, "select count(*) from genus"),
                    (self.home_nfamtot, "select count(*) from family"),
                    (
                        self.home_nspcnot,
                        "select count(id) from species "
                        "where id not in "
                        "(select distinct species.id "
                        " from species join accession "
                        " on accession.species_id=species.id)",
                    ),
                    (
                        self.home_ngennot,
                        "select count(id) from genus "
                        "where id not in "
                        "(select distinct species.genus_id "
                        " from species join accession "
                        " on accession.species_id=species.id)",
                    ),
                    (
                        self.home_nfamnot,
                        "select count(id) from family "
                        "where id not in "
                        "(select distinct genus.family_id from genus "
                        "join species on species.genus_id=genus.id "
                        "join accession on accession.species_id=species.id)",
                    ),
                )
            )
        )


class PlantsPlugin(pluginmgr.Plugin):
    prefs_change_handler = None
    options_menu_set = False

    family_infobox: FamilyInfoBox | None = None
    genus_infobox: GenusInfoBox | None = None
    species_infobox: SpeciesInfoBox | None = None
    vernacular_infobox: VernacularNameInfoBox | None = None
    geography_infobox: GeographyInfoBox | None = None

    @classmethod
    def init(cls):
        if not cls.options_menu_set:
            cls.options_menu_set = True

            full_names_item = Gio.MenuItem.new(
                _("Update All Species Full Names"), "win.update_full_name"
            )

            geo_areas_item = Gio.MenuItem.new(
                _("Update All Geographies Area"), "win.update_approx_area"
            )

            msg = _(
                "Setup custom conservation fields.\n\nYou have 2 fields "
                "available.  To set them up you need to provide a "
                "dictionary that defines the `field_name` as used in "
                "searches, reports, etc., the `display_name` as used in "
                "the editor and the `values` as a tuple or list of the "
                "values it can accept.\n\n Examples are provided, replace "
                "these as needed set them empty to disable."
            )
            custom1_default = (
                "{'field_name': 'nca_status', "
                "'display_name': 'NCA Status', "
                "'short_hand': 'NCA', "
                "'values': ("
                "'Extinct in the wild', "
                "'Critically endangered', "
                "'Endangered', "
                "'Vulnerable', "
                "'Near threatened', "
                "'Special least concern', "
                "'Least concern', "
                "None"
                ")}"
            )
            custom2_default = (
                "{'field_name': 'epbc_status', "
                "'display_name': 'EPBC Status',  "
                "'short_hand': 'EPBC', "
                "'values': ("
                "'Extinct', "
                "'Critically endangered', "
                "'Endangered', "
                "'Vulnerable', "
                "'Conservation dependent', "
                "'Not listed', "
                "None"
                ")}"
            )

            custom_consv_item = Gio.MenuItem.new(
                _("Setup Custom Conservation Fields"),
                "win.setup_conservation_fields",
            )

            def setup_conservation_fields(*_args):
                bauble.meta.set_value(
                    ("_sp_custom1", "_sp_custom2"),
                    (custom1_default, custom2_default),
                    msg,
                )
                cls.register_custom_column("_sp_custom1")
                cls.register_custom_column("_sp_custom2")
                db.open_conn(db.engine.url)

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

        mapper_search = search.strategies.get_strategy("MapperSearch")

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

        mapper_search.add_meta(("family", "fam"), Family, ["family"])
        SearchView.row_meta[Family].set(
            children=partial(db.get_active_children, "genera"),
            infobox=cls.family_infobox,
            context_menu=family_context_menu,
            activated_callback=family_edit_callback,
        )

        mapper_search.add_meta(("genus", "gen"), Genus, ["genus"])

        SearchView.row_meta[Genus].set(
            children=partial(db.get_active_children, "species"),
            infobox=cls.genus_infobox,
            context_menu=genus_context_menu,
            activated_callback=genus_edit_callback,
        )

        search.strategies.add_strategy(BinomialSearch)
        search.strategies.add_strategy(SynonymSearch)
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
        # full_name search
        mapper_search.add_meta(
            ("species_full_name", "taxon"), Species, ["full_name"]
        )
        SearchView.row_meta[Species].set(
            children=partial(
                db.get_active_children, partial(db.natsort, "accessions")
            ),
            infobox=cls.species_infobox,
            context_menu=species_context_menu,
            activated_callback=species_edit_callback,
        )

        mapper_search.add_meta(
            ("vernacular_name", "vernacular", "vern", "common"),
            VernacularName,
            ["name"],
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

        mapper_search.add_meta(
            ("geography", "geo"), Geography, ["name", "code", "iso_code"]
        )
        SearchView.row_meta[Geography].set(
            children=partial(db.get_active_children, get_species_in_geography),
            infobox=cls.geography_infobox,
            context_menu=geography_context_menu,
        )

        # now it's the turn of the HomeView
        logger.debug("PlantsPlugin::init, registering home info box")
        HomeView.infoboxclass = HomeInfoBox

        if bauble.gui is not None:
            bauble.gui.add_to_insert_menu(create_family, _("Family"))
            bauble.gui.add_to_insert_menu(create_genus, _("Genus"))
            bauble.gui.add_to_insert_menu(create_species, _("Species"))
            bauble.gui.main_entry_completion_callbacks.add(
                get_binomial_completions
            )

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
        cls.register_custom_column("_sp_custom1")
        cls.register_custom_column("_sp_custom2")
        # make query builder treat active as a boolean (also accounts for
        # accessions and plants)
        ExpressionRow.custom_columns["active"] = ("True", "False")
        # on new connection reset
        DistributionMap.reset()

    @staticmethod
    def register_custom_column(column_name: str) -> None:
        logger.debug("register custom column: %s", column_name)
        session = db.Session()
        custom_meta = (
            session.query(bauble.meta.BaubleMeta)
            .filter(bauble.meta.BaubleMeta.name == column_name)
            .first()
        )
        session.close()
        column: Column = getattr(Species, column_name)
        enum: bauble.btypes.CustomEnum = column.prop.columns[0].type

        # pylint: disable=protected-access
        if custom_meta:
            custom_meta = literal_eval(custom_meta.value)
            field_name = custom_meta["field_name"]
            field_values = custom_meta["values"]
            short_hand = custom_meta.get("short_hand")
            empty_to_none = None in field_values
            enum.init(field_values, empty_to_none=empty_to_none)
            # register with ExpressionRow
            ExpressionRow.custom_columns[field_name] = field_values

            def _get(self):
                return getattr(self, column_name)

            def _set(self, value):
                if empty_to_none:
                    value = value or None

                if value in field_values:
                    setattr(self, column_name, value)
                else:
                    raise AttributeError(f"{value} is not in {field_values}")

            def _exp(cls):
                return getattr(cls, column_name)

            from sqlalchemy.ext.hybrid import hybrid_property

            setattr(
                Species,
                field_name,
                hybrid_property(_get, fset=_set, expr=_exp),
            )
            setattr(column, "_custom_column_name", field_name)
            setattr(column, "_custom_column_short_hand", short_hand)

        elif hasattr(column, "_custom_column_name"):
            enum.unset_values()
            delattr(Species, getattr(column, "_custom_column_name"))
            delattr(column, "_custom_column_name")
            delattr(column, "_custom_column_short_hand")

    @classmethod
    def install(cls, import_defaults=True):
        """
        Do any setup and configuration required by this plugin like
        creating tables, etc...
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

        # this should only occur first time around, not wipe out existing
        # data.  Or at least ask the user.
        with db.engine.connect() as con:
            try:
                fams = con.execute("SELECT COUNT(*) FROM family")
                fams = next(fams)[0]
            except Exception:  # pylint: disable=broad-except
                fams = 0
            try:
                gens = con.execute("SELECT COUNT(*) FROM genus")
                gens = next(gens)[0]
            except Exception:  # pylint: disable=broad-except
                gens = 0
            try:
                geos = con.execute("SELECT COUNT(*) FROM geography")
                geos = next(geos)[0]
            except Exception:  # pylint: disable=broad-except
                geos = 0
            if gens > 0 and fams > 0 and geos > 0:
                msg = _(
                    f"You already seem to have approximately <b>{gens}</b>"
                    f" records in the genus table, <b>{fams}</b> in the "
                    f"family table and <b>{geos}</b> in geography table. "
                    "\n\n<b>Do you want to overwrite these tables and "
                    "their related synonym tables?</b>"
                )
                if not dialogs.yes_no_dialog(msg, yes_delay=2):
                    return
        # pylint: disable=no-member
        geo_table = Geography.__table__
        depends = utils.find_dependent_tables(geo_table)

        try:
            logger.debug("dropping tables: %s", [i.name for i in depends])
            db.metadata.drop_all(tables=depends)
            logger.debug("dropping tables: %s", geo_table.name)
            geo_table.drop(db.engine)
        except Exception as e:  # pylint: disable=broad-except
            logger.debug("%s(%s)", type(e).__name__, e)

        logger.debug("creating tables: %s", [i.name for i in depends])
        geo_table.create(db.engine)

        db.metadata.create_all(tables=depends)
        logger.debug("creating tables: %s", geo_table.name)

        from bauble.plugins.imex.csv_ import CSVRestore

        csv = CSVRestore()
        csv.start(filenames, metadata=db.metadata, force=True)


plugin = PlantsPlugin
