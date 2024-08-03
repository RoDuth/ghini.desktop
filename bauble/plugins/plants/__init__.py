# Copyright 2008-2010 Brett Adams
# Copyright 2012-2015 Mario Frasca <mario@anche.no>.
# Copyright 2021-2023 Ross Demuth <rossdemuth123@gmail.com>
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
import weakref
from ast import literal_eval
from functools import partial
from pathlib import Path
from random import random
from threading import Thread

logger = logging.getLogger(__name__)

from gi.repository import Gio
from gi.repository import GLib
from gi.repository import Gtk
from sqlalchemy import Column
from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.exc import OperationalError

import bauble
from bauble import db
from bauble import editor
from bauble import pluginmgr
from bauble import prefs
from bauble import search
from bauble import utils
from bauble.i18n import _
from bauble.paths import lib_dir
from bauble.query_builder import ExpressionRow
from bauble.ui import DefaultView
from bauble.view import HistoryView
from bauble.view import SearchView

from .family import Familia
from .family import Family
from .family import FamilyEditor
from .family import FamilyInfoBox
from .family import FamilyNote
from .family import family_context_menu
from .genus import Genus
from .genus import GenusEditor
from .genus import GenusInfoBox
from .genus import GenusNote
from .genus import genus_context_menu
from .geography import DistributionMap
from .geography import Geography
from .geography import GeographyInfoBox
from .geography import geography_context_menu
from .geography import get_species_in_geography
from .geography import update_all_approx_areas_handler
from .species import BinomialSearch
from .species import Species
from .species import SpeciesDistribution
from .species import SpeciesEditor
from .species import SpeciesInfoBox
from .species import SpeciesNote
from .species import SynonymSearch
from .species import VernacularName
from .species import VernacularNameInfoBox
from .species import add_accession_action
from .species import species_context_menu
from .species import vernname_context_menu
from .species_model import SpeciesPicture
from .species_model import update_all_full_names_handler
from .stored_queries import StoredQueryEditorTool

# imported by clients of the module
__all__ = ["Familia", "SpeciesDistribution"]


class SynonymsPresenter(editor.GenericEditorPresenter):
    """The SynonymsPresenter provides a generic presenter for adding and
    removing synonyms that can be used with a taxon editor.

    This presenter requires that the parent editors view provides the the
    following widgets: syn_entry, syn_frame, syn_add_button, syn_remove_button,
    syn_treeview, syn_column, syn_cell

    Must also call cleanup when finished to ensure it is correctly garbage
    collected.  Deleting the view here is also required to prevent circular
    references (i.e. within the parents __del__ method).

    :param parent: the parent presenter of this presenter
    :param synonym_model: the class used for synonyms
    :param comparer: comparer callable (or None to use the default) as used by
        `assign_completions_handler`
    :param completions_seed: callable that when supplied with a session and the
        search text provides the starting query for the get_completions method
        required by `assign_completions_handler`
    """

    PROBLEM_INVALID_SYNONYM = f"invalid_synonym:{random()}"

    def __init__(self, parent, synonym_model, comparer, completions_seed):
        self.synonym_model = synonym_model
        self.completions_seed = completions_seed

        super().__init__(
            parent.model,
            parent.view,
            session=parent.session,
            connect_signals=False,
        )

        self.parent_table_name = parent.model.__tablename__
        self.parent_ref = weakref.ref(parent)
        self.view.widget_set_value("syn_entry", "")
        self.init_treeview()

        # prevent adding synonyms to synonyms
        if self.model.accepted:
            self.view.widgets.syn_entry.set_placeholder_text(
                _("Already a synonym of %s") % self.model.accepted
            )
            self.view.widgets.syn_frame.set_sensitive(False)

        self.assign_completions_handler(
            "syn_entry",
            self.syn_get_completions,
            on_select=self.on_select,
            comparer=comparer,
        )
        self.on_select(None)  # set to default state

        self._selected = None
        self.view.connect(
            "syn_add_button", "clicked", self.on_add_button_clicked
        )
        self.view.connect(
            "syn_remove_button", "clicked", self.on_remove_button_clicked
        )
        self.additional = []
        self._dirty = False

    def syn_get_completions(self, text):
        # Skip current synonyms, self and already added synonyms
        result = self.completions_seed(self.session, text)
        ids = [i[0] for i in self.session.query(self.synonym_model.synonym_id)]
        for syn in self.model._synonyms:
            if syn.synonym and (id_ := syn.synonym.id) not in ids:
                ids.append(id_)
        if id_ := self.model.id:
            ids.append(id_)
        return result.filter(type(self.model).id.notin_(ids)).limit(100)

    def on_select(self, value):
        sensitive = True
        if value is None:
            sensitive = False
        self.view.widgets.syn_add_button.set_sensitive(sensitive)
        self._selected = value

    def is_dirty(self):
        return self._dirty

    def init_treeview(self):
        """initialize the Gtk.TreeView"""
        self.treeview = self.view.widgets.syn_treeview

        def _syn_data_func(_column, cell, model, treeiter, _data):
            val = model[treeiter][0]
            cell.set_property("text", str(val))
            # background color to indicate it's new
            if self.session.is_modified(val):
                cell.set_property("foreground", "blue")
            else:
                cell.set_property("foreground", None)

        col = self.view.widgets.syn_column
        col.set_cell_data_func(self.view.widgets.syn_cell, _syn_data_func)

        utils.clear_model(self.treeview)
        tree_model = Gtk.ListStore(object)
        for syn in sorted(self.model._synonyms, key=str):
            tree_model.append([syn])
        self.treeview.set_model(tree_model)
        self.view.connect(
            self.treeview, "cursor-changed", self.on_tree_cursor_changed
        )

    def on_tree_cursor_changed(self, tree):
        self.view.widgets.syn_remove_button.set_sensitive(
            len(tree.get_model()) > 0
        )

    def refresh_view(self):
        """doesn't do anything"""
        return

    def on_add_button_clicked(self, _button):
        """Adds the synonym from the synonym entry to the list of synonyms?

        If the synonym is already considered a synonym, move them all across.
        """
        synonyms = []
        syn = self.synonym_model(synonym=self._selected)
        synonyms.append(syn)
        for syn in self._selected._synonyms:
            synonyms.append(syn)
            self.additional.append(syn)
        tree_model = self.treeview.get_model()
        for syn in synonyms:
            setattr(syn, self.parent_table_name, self.model)
            tree_model.append([syn])
        self._selected = None
        entry = self.view.widgets.syn_entry
        entry.set_text("")
        entry.set_position(-1)
        self.view.widgets.syn_add_button.set_sensitive(False)
        self._dirty = True
        self.parent_ref().refresh_sensitivity()

    def on_remove_button_clicked(self, _button):
        """Removes the currently selected synonym from the list of synonyms."""
        tree = self.view.widgets.syn_treeview
        path, _col = tree.get_cursor()
        tree_model = tree.get_model()
        value = tree_model[tree_model.get_iter(path)][0]
        syn = str(value.synonym)
        msg = _(
            "Are you sure you want to remove %s as a synonym? \n\n"
            "<i>Note: This will not remove %s from the database.</i>"
        ) % (syn, syn)
        if not utils.yes_no_dialog(msg, parent=self.view.get_window()):
            return

        tree_model.remove(tree_model.get_iter(path))
        self.model.synonyms.remove(value.synonym)
        self.session.refresh(value.synonym)
        if value in self.additional:
            try:
                self.session.expunge(value)
            except InvalidRequestError as e:
                logger.debug("syn %s > %s (%s)", value, type(e).__name__, e)
            self.additional.remove(value)
        elif value in self.session:
            self.session.delete(value)
        self._dirty = True
        self.parent_ref().refresh_sensitivity()


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


@Gtk.Template(filename=str(Path(__file__).resolve().parent / "splash_info.ui"))
class SplashInfoBox(pluginmgr.View, Gtk.Box):
    """info box shown in the initial splash screen."""

    __gtype_name__ = "SplashInfoBox"

    splash_stqr_button = Gtk.Template.Child()
    splash_nlocnot = Gtk.Template.Child()
    splash_nlocuse = Gtk.Template.Child()
    splash_nloctot = Gtk.Template.Child()
    splash_npltnot = Gtk.Template.Child()
    splash_npltuse = Gtk.Template.Child()
    splash_nplttot = Gtk.Template.Child()
    splash_naccnot = Gtk.Template.Child()
    splash_naccuse = Gtk.Template.Child()
    splash_nacctot = Gtk.Template.Child()
    splash_nspcnot = Gtk.Template.Child()
    splash_nspcuse = Gtk.Template.Child()
    splash_nspctot = Gtk.Template.Child()
    splash_ngennot = Gtk.Template.Child()
    splash_ngenuse = Gtk.Template.Child()
    splash_ngentot = Gtk.Template.Child()
    splash_nfamtot = Gtk.Template.Child()
    splash_nfamuse = Gtk.Template.Child()
    splash_nfamnot = Gtk.Template.Child()

    for i in range(1, 11):
        wname = f"stqr_{i:02d}_button"
        locals()[wname] = Gtk.Template.Child()

    def __init__(self):
        logger.debug("SplashInfoBox::__init__")
        super().__init__()

        for i in range(1, 11):
            wname = f"stqr_{i:02d}_button"
            widget = getattr(self, wname)
            widget.connect("clicked", partial(self.on_sqb_clicked, i))

        self.name_tooltip_query = None

        on_clicked_search = utils.generate_on_clicked(bauble.gui.send_command)

        utils.make_label_clickable(
            self.splash_nfamtot, on_clicked_search, "family like %"
        )

        utils.make_label_clickable(
            self.splash_nfamuse,
            on_clicked_search,
            "family where genera.species.accessions.id != 0",
        )

        utils.make_label_clickable(
            self.splash_nfamnot,
            on_clicked_search,
            "family where not genera.species.accessions.id != 0",
        )

        utils.make_label_clickable(
            self.splash_ngentot, on_clicked_search, "genus like %"
        )

        utils.make_label_clickable(
            self.splash_ngenuse,
            on_clicked_search,
            "genus where species.accessions.id!=0",
        )

        utils.make_label_clickable(
            self.splash_ngennot,
            on_clicked_search,
            "genus where not species.accessions.id!=0",
        )

        utils.make_label_clickable(
            self.splash_nspctot, on_clicked_search, "species like %"
        )

        utils.make_label_clickable(
            self.splash_nspcuse,
            on_clicked_search,
            "species where not accessions = Empty",
        )

        utils.make_label_clickable(
            self.splash_nspcnot,
            on_clicked_search,
            "species where accessions = Empty",
        )

        utils.make_label_clickable(
            self.splash_nacctot, on_clicked_search, "accession like %"
        )

        utils.make_label_clickable(
            self.splash_naccuse,
            on_clicked_search,
            "accession where sum(plants.quantity)>0",
        )

        utils.make_label_clickable(
            self.splash_naccnot,
            on_clicked_search,
            "accession where plants = Empty or sum(plants.quantity)=0",
        )

        utils.make_label_clickable(
            self.splash_nplttot, on_clicked_search, "plant like %"
        )

        utils.make_label_clickable(
            self.splash_npltuse,
            on_clicked_search,
            "plant where sum(quantity)>0",
        )

        utils.make_label_clickable(
            self.splash_npltnot,
            on_clicked_search,
            "plant where sum(quantity)=0",
        )

        utils.make_label_clickable(
            self.splash_nloctot, on_clicked_search, "location like %"
        )

        utils.make_label_clickable(
            self.splash_nlocuse,
            on_clicked_search,
            "location where sum(plants.quantity)>0",
        )

        utils.make_label_clickable(
            self.splash_nlocnot,
            on_clicked_search,
            "location where plants is Empty or sum(plants.quantity)=0",
        )

        for i in range(1, 11):
            wname = f"stqr_{i:02d}_button"
            widget = getattr(self, wname)
            widget.connect("clicked", partial(self.on_sqb_clicked, i))

        self.splash_stqr_button.connect(
            "clicked", self.on_splash_stqr_button_clicked
        )

    def update(self, *_args):
        # desensitise links that wont work.
        sensitive = not prefs.prefs.get(prefs.exclude_inactive_pref)
        for widget in [
            self.splash_nplttot,
            self.splash_npltnot,
            self.splash_nacctot,
            self.splash_naccnot,
            self.splash_nspctot,
            self.splash_nspcnot,
        ]:
            widget.get_parent().set_sensitive(sensitive)

        logger.debug("SplashInfoBox::update")
        statusbar = bauble.gui.widgets.statusbar
        sbcontext_id = statusbar.get_context_id("searchview.nresults")
        statusbar.pop(sbcontext_id)
        bauble.gui.widgets.main_comboentry.get_child().set_text("")

        session = db.Session()
        query = session.query(bauble.meta.BaubleMeta).filter(
            bauble.meta.BaubleMeta.name.startswith("stqr")
        )
        name_tooltip_query = dict(
            (int(i.name[5:]), (i.value.split(":", 2))) for i in query.all()
        )
        session.close()

        for i in range(1, 11):
            wname = f"stqr_{i:02d}_button"
            widget = getattr(self, wname)
            name, tooltip, _query = name_tooltip_query.get(
                i, (_("<empty>"), "", "")
            )
            widget.set_label(name)
            widget.set_tooltip_text(tooltip)

        self.name_tooltip_query = name_tooltip_query

        self.start_thread(
            LabelUpdater(
                (
                    (self.splash_nplttot, "select count(*) from plant"),
                    (
                        self.splash_npltuse,
                        "select count(*) from plant where quantity>0",
                    ),
                    (
                        self.splash_npltnot,
                        "select count(*) from plant where quantity=0",
                    ),
                    (self.splash_nacctot, "select count(*) from accession"),
                    (
                        self.splash_naccuse,
                        "select count(distinct accession.id) "
                        "from accession "
                        "join plant on plant.accession_id=accession.id "
                        "where plant.quantity>0",
                    ),
                    (
                        self.splash_naccnot,
                        "select count(id) "
                        "from accession "
                        "where id not in "
                        "(select accession_id from plant "
                        " where plant.quantity>0)",
                    ),
                    (self.splash_nloctot, "select count(*) from location"),
                    (
                        self.splash_nlocuse,
                        "select count(distinct location.id) "
                        "from location "
                        "join plant on plant.location_id=location.id "
                        "where plant.quantity>0",
                    ),
                    (
                        self.splash_nlocnot,
                        "select count(id) "
                        "from location "
                        "where id not in "
                        "(select location_id from plant "
                        " where plant.quantity>0)",
                    ),
                    (
                        self.splash_nspcuse,
                        "select count(distinct species.id) "
                        "from species join accession "
                        "on accession.species_id=species.id",
                    ),
                    (
                        self.splash_ngenuse,
                        "select count(distinct species.genus_id) "
                        "from species join accession "
                        "on accession.species_id=species.id",
                    ),
                    (
                        self.splash_nfamuse,
                        "select count(distinct genus.family_id) from genus "
                        "join species on species.genus_id=genus.id "
                        "join accession on accession.species_id=species.id ",
                    ),
                    (self.splash_nspctot, "select count(*) from species"),
                    (self.splash_ngentot, "select count(*) from genus"),
                    (self.splash_nfamtot, "select count(*) from family"),
                    (
                        self.splash_nspcnot,
                        "select count(id) from species "
                        "where id not in "
                        "(select distinct species.id "
                        " from species join accession "
                        " on accession.species_id=species.id)",
                    ),
                    (
                        self.splash_ngennot,
                        "select count(id) from genus "
                        "where id not in "
                        "(select distinct species.genus_id "
                        " from species join accession "
                        " on accession.species_id=species.id)",
                    ),
                    (
                        self.splash_nfamnot,
                        "select count(id) from family "
                        "where id not in "
                        "(select distinct genus.family_id from genus "
                        "join species on species.genus_id=genus.id "
                        "join accession on accession.species_id=species.id)",
                    ),
                )
            )
        )

    def on_sqb_clicked(self, btn_no, _widget):
        query = self.name_tooltip_query.get(btn_no)
        if query:
            bauble.gui.widgets.main_comboentry.get_child().set_text(query[2])
            bauble.gui.widgets.go_button.emit("clicked")

    @staticmethod
    def on_splash_stqr_button_clicked(_widget):
        from .stored_queries import edit_callback

        edit_callback()


class PlantsPlugin(pluginmgr.Plugin):
    tools = [StoredQueryEditorTool]
    provides = {
        "Family": Family,
        "FamilyNote": FamilyNote,
        "Genus": Genus,
        "GenusNote": GenusNote,
        "Species": Species,
        "SpeciesNote": SpeciesNote,
        "SpeciesPicture": SpeciesPicture,
        "VernacularName": VernacularName,
        "Geography": Geography,
    }
    prefs_change_handler = None
    options_menu_set = False

    @classmethod
    def init(cls):
        if not cls.options_menu_set:
            cls.options_menu_set = True
            accptd_action = Gio.SimpleAction.new_stateful(
                "accepted_toggled",
                None,
                GLib.Variant.new_boolean(
                    prefs.prefs.get(prefs.return_accepted_pref, True)
                ),
            )
            accptd_action.connect(
                "change-state", cls.on_return_syns_chkbx_toggled
            )

            ret_accptd_item = Gio.MenuItem.new(
                _("Return Accepted"), "win.accepted_toggled"
            )

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
                "'display_name': 'NCA Status', 'values': ("
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
                "'display_name': 'EPBC Status', 'values': ("
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
                db.open_conn(str(db.engine.url))

            def prefs_ls_changed(model, path, _itr):
                key, _repr_str, _type_str = model[path]
                if key == prefs.return_accepted_pref:
                    accptd_action.set_state(
                        GLib.Variant.new_boolean(
                            prefs.prefs.get(prefs.return_accepted_pref)
                        )
                    )

            def on_view_box_added(_container, obj):
                if isinstance(obj, prefs.PrefsView):
                    if cls.prefs_change_handler:
                        obj.prefs_ls.disconnect(cls.prefs_change_handler)
                    cls.prefs_change_handler = obj.prefs_ls.connect(
                        "row-changed", prefs_ls_changed
                    )

            if bauble.gui:
                bauble.gui.window.add_action(accptd_action)
                bauble.gui.options_menu.append_item(ret_accptd_item)
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
                bauble.gui.widgets.view_box.connect(
                    "set-focus-child", on_view_box_added
                )

        pluginmgr.provided.update(cls.provides)
        if "GardenPlugin" in pluginmgr.plugins:
            if add_accession_action not in species_context_menu:
                species_context_menu.insert(1, add_accession_action)
            if add_accession_action not in vernname_context_menu:
                vernname_context_menu.insert(1, add_accession_action)

        mapper_search = search.strategies.get_strategy("MapperSearch")

        mapper_search.add_meta(("family", "fam"), Family, ["family"])
        SearchView.row_meta[Family].set(
            children="genera",
            infobox=FamilyInfoBox,
            context_menu=family_context_menu,
        )

        mapper_search.add_meta(("genus", "gen"), Genus, ["genus"])

        SearchView.row_meta[Genus].set(
            children=partial(db.get_active_children, "species"),
            infobox=GenusInfoBox,
            context_menu=genus_context_menu,
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
            infobox=SpeciesInfoBox,
            context_menu=species_context_menu,
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
            infobox=VernacularNameInfoBox,
            context_menu=vernname_context_menu,
        )

        mapper_search.add_meta(
            ("geography", "geo"), Geography, ["name", "code", "iso_code"]
        )
        SearchView.row_meta[Geography].set(
            children=partial(db.get_active_children, get_species_in_geography),
            infobox=GeographyInfoBox,
            context_menu=geography_context_menu,
        )

        # now it's the turn of the DefaultView
        logger.debug("PlantsPlugin::init, registering splash info box")
        DefaultView.infoboxclass = SplashInfoBox

        if bauble.gui is not None:
            bauble.gui.add_to_insert_menu(FamilyEditor, _("Family"))
            bauble.gui.add_to_insert_menu(GenusEditor, _("Genus"))
            bauble.gui.add_to_insert_menu(SpeciesEditor, _("Species"))

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
        if not db.Session:
            return
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
            enum.init(field_values, empty_to_none=None in field_values)
            # register with ExpressionRow
            ExpressionRow.custom_columns[field_name] = field_values

            def _get(self):
                return getattr(self, column_name)

            def _set(self, value):
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

        elif hasattr(column, "_custom_column_name"):
            enum.unset_values()
            delattr(Species, getattr(column, "_custom_column_name"))
            delattr(column, "_custom_column_name")

    @staticmethod
    def on_return_syns_chkbx_toggled(action, value):
        action.set_state(value)

        prefs.prefs[prefs.return_accepted_pref] = value.get_boolean()
        if isinstance(view := bauble.gui.get_view(), prefs.PrefsView):
            view.update()

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
                if not utils.yes_no_dialog(msg, yes_delay=2):
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
