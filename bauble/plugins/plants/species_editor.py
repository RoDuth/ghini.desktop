# Copyright 2008-2010 Brett Adams
# Copyright 2012-2015 Mario Frasca <mario@anche.no>.
# Copyright 2016-2023 Ross Demuth <rossdemuth123@gmail.com>
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
Species table definition
"""

import logging
import os
import re
import textwrap
import traceback
import weakref
from ast import literal_eval

logger = logging.getLogger(__name__)

from gi.repository import Gio
from gi.repository import GLib
from gi.repository import Gtk
from gi.repository import Pango
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import object_mapper
from sqlalchemy.orm.query import Query
from sqlalchemy.orm.session import Session
from sqlalchemy.orm.session import object_session

import bauble
from bauble import editor
from bauble import paths
from bauble import utils
from bauble.i18n import _

from .family import Family
from .genus import Genus
from .genus import GenusSynonym
from .genus import generic_gen_get_completions
from .genus import genus_cell_data_func
from .genus import genus_match_func
from .geography import Geography
from .geography import GeographyMenu
from .geography import consolidate_geographies
from .species_model import Habit
from .species_model import Species
from .species_model import SpeciesDistribution
from .species_model import SpeciesSynonym
from .species_model import VernacularName
from .species_model import compare_rank
from .species_model import infrasp_rank_values
from .species_model import red_list_values


def generic_sp_get_completions(session: Session, text: str) -> Query:
    """A generic species get_completion.

    intended used is by supplying the local session via `functools.partial`

    e.g.:
    `sp_completions = partial(generic_sp_get_completions, self.session)`

    :param session: a local session to use for the query.
    :param text: a string to search for
    """
    query = session.query(Species).join(Genus)
    hybrid = ""
    epithet = ""
    genus = text.removeprefix("×").removeprefix("+").strip()

    try:
        if text[0] in ["×", "+"]:
            hybrid = text[0]
    except (AttributeError, IndexError):
        pass

    try:
        genus, epithet = genus.split(" ", 1)
        epithet = epithet.strip(" +×")
    except (AttributeError, ValueError):
        pass

    query = query.filter(utils.ilike(Genus.genus, f"{genus}%%"))
    if hybrid:
        query = query.filter(Genus.hybrid == hybrid)
    if epithet:
        query = query.filter(
            utils.ilike(Species.full_name, f"%{genus}%{epithet}%")
        )
    return query.order_by(Genus.genus)


def species_to_string_matcher(
    species: Species, key: str, sp_path: str = ""
) -> bool:
    """Helper function to match string or partial string of the pattern
    'Genus species' with a Species

    Allows partial matches (e.g. 'Den d' and 'Dendr' will match
    'Dendrobium discolor').  Searches are case insensitive.

    :param species: a Species table entry
    :param key: the string to search with
    :param sp_path: optional path for model obects to get to the species

    :return: bool, True if the Species matches the key
    """
    if sp_path:
        from operator import attrgetter

        species = attrgetter(sp_path)(species)

    if species.full_name and species.full_name.lower().startswith(key.lower()):
        return True

    key = key.lower().removeprefix("×").removeprefix("+").strip()
    key = key.replace(" s. str ", " ", 1).replace(" s. lat. ", " ", 1)
    key_gen, key_sp = (key + " ").split(" ", 1)
    key_sp = key_sp.removeprefix("×").removeprefix("+").strip()

    comp_gen = str(species.genus.epithet).lower()
    comp_sp = species.string(genus=False).lower().strip(" ×+")
    comp_cv = "'" + (species.cultivar_epithet or "").lower()
    comp_trade = "'" + (species.trade_name or "").lower()

    if comp_gen.startswith(key_gen):
        if comp_sp.startswith(key_sp.strip()):
            return True
        if comp_cv.startswith(key_sp.strip()):
            return True
        if comp_trade.startswith(key_sp.strip()):
            return True
    return False


def species_match_func(
    completion: Gtk.EntryCompletion, key: str, treeiter: int, sp_path: str = ""
) -> bool:
    """match_func that allows partial matches on both Genus and species.

    :param completion: the completion to match
    :param key: lowercase string of the entry text
    :param treeiter: the row number for the item to match
    :param sp_path: optional path for model obects to get to the species

    :return: bool, True if the item at the treeiter matches the key
    """
    tree_model = completion.get_model()
    if not tree_model:
        raise AttributeError(f"can't get TreeModel from {completion}")
    species = tree_model[treeiter][0]
    if not sa_inspect(species).persistent:
        return False
    return species_to_string_matcher(species, key, sp_path)


def species_cell_data_func(_column, renderer, model, treeiter):
    sp = model[treeiter][0]
    # occassionally the session gets lost and can result in
    # DetachedInstanceErrors. So check first
    if sa_inspect(sp).persistent:
        renderer.set_property(
            "text", f"{sp.string(authors=True)} ({sp.genus.family})"
        )


# This, rather than insert-text signal handler, due to a bug in PyGObject, see:
# https://gitlab.gnome.org/GNOME/pygobject/-/issues/12
# https://stackoverflow.com/a/38831655/14739447
class SpeciesEntry(Gtk.Entry, Gtk.Editable):
    __gtype_name__ = "SpeciesEntry"

    def __init__(self):
        super().__init__()
        self.species_space = False  # do not accept spaces in epithet

    def do_insert_text(self, text, _length, position):
        # logic here used to resided in signal handler for insert-text
        # SpeciesEditorPresenter.on_sp_species_entry_insert_text

        # immediately allow spaces when opening a species for editing or
        # pasting text.
        if any(
            i for i in (text.count("×"), text.count(" ("), text[:4] == "sp. ")
        ):
            self.species_space = True

        # discourage capitalising species names
        if position == 0 and text and "×" not in text:
            text = "".join([text[0].lower(), *text[1:]])

        if "*" in text:
            self.species_space = True
            text = text.replace("*", " × ")
        # provisional names (e.g. 'sp. nov.', 'sp. (OrmeauL.H.Bird AQ435851)')
        full_text = self.get_chars(0, -1)
        if full_text[:3] == "sp.":
            self.species_space = True

        # informal descriptive names (e.g. 'caerulea (Finch Hatton)')
        if text == ("(") and self.species_space is False:
            self.species_space = True
            text = text.replace("(", " (")

        if self.species_space is False:
            text = text.replace(" ", "")

        if text != "":
            # best way to get correct length (accounts for ×)
            length = self.get_buffer().insert_text(position, text, -1)
            new_pos = position + length
            return new_pos
        return position


SPECIES_WEB_BUTTON_DEFS_PREFS = "web_button_defs.species"


class SpeciesEditorPresenter(
    editor.PresenterLinksMixin, editor.GenericEditorPresenter
):
    widget_to_field_map = {
        "sp_genus_entry": "genus",
        "sp_species_entry": "sp",
        "sp_author_entry": "sp_author",
        "sp_hybrid_combo": "hybrid",
        "sp_grex_entry": "grex",
        "sp_cvgroup_entry": "cv_group",
        "sp_cvepithet_entry": "cultivar_epithet",
        "sp_tradename_entry": "trade_name",
        "sp_trademark_combo": "trademark_symbol",
        "sp_pbr_checkbtn": "pbr_protected",
        "sp_spqual_combo": "sp_qual",
        "sp_awards_entry": "awards",
        "sp_label_dist_entry": "label_distribution",
        "sp_label_markup_entry": "label_markup",
        "sp_habit_comboentry": "habit",
        "cites_combo": "_cites",
        "red_list_combo": "red_list",
        "subgenus_entry": "subgenus",
        "section_entry": "section",
        "subsection_entry": "subsection",
        "series_entry": "series",
        "subseries_entry": "subseries",
    }

    PROBLEM_UNKOWN_HABIT = editor.Problem("unknown_source")
    PROBLEM_INVALID_MARKUP = editor.Problem("invalid_markup")
    LINK_BUTTONS_PREF_KEY = SPECIES_WEB_BUTTON_DEFS_PREFS

    def __init__(self, model, view):
        super().__init__(model, view)
        self.session = object_session(model)
        # get the starting position
        self.capture_start_sp(model)

        self._dirty = False
        self.omonym_box = None
        self.species_check_messages = []
        self.genus_check_messages = []
        self.init_fullname_widgets()
        self.vern_presenter = VernacularNamePresenter(self)
        from . import SynonymsPresenter

        self.synonyms_presenter = SynonymsPresenter(
            self,
            SpeciesSynonym,
            lambda row, s: species_to_string_matcher(row[0], s),
            generic_sp_get_completions,
        )
        self.dist_presenter = DistributionPresenter(self)
        self.infrasp_presenter = InfraspPresenter(self)

        notes_parent = self.view.widgets.notes_parent_box
        notes_parent.foreach(notes_parent.remove)
        self.notes_presenter = editor.NotesPresenter(
            self, "notes", notes_parent
        )

        pictures_parent = self.view.widgets.pictures_parent_box
        pictures_parent.foreach(pictures_parent.remove)
        self.pictures_presenter = editor.PicturesPresenter(
            self, "_pictures", pictures_parent
        )

        self.init_enum_combo("sp_spqual_combo", "sp_qual")
        self.init_enum_combo("sp_hybrid_combo", "hybrid")
        self.init_enum_combo("cites_combo", "_cites")

        order = {k: v for v, k in enumerate(red_list_values.keys())}
        self.view.init_translatable_combo(
            "red_list_combo", red_list_values, None, key=lambda v: order[v[0]]
        )

        combo = self.view.widgets.sp_habit_comboentry
        model = Gtk.ListStore(str, object)
        model.append(("", None))
        for habit in self.session.query(Habit):
            model.append((str(habit), habit))
        utils.setup_text_combobox(combo, model)

        combo.get_child().connect(
            "changed", self.on_habit_entry_changed, combo
        )

        mapper = object_mapper(self.model)
        values = utils.get_distinct_values(
            mapper.c["trademark_symbol"], self.session
        )
        # make sure the obvious defaults exist
        values = set(values + ["", "™", "®"])
        combo = self.view.widgets.sp_trademark_combo
        utils.setup_text_combobox(combo, values)
        utils.set_widget_value(combo, self.model.trademark_symbol or "")

        # set the model values in the widgets
        self.refresh_view()

        # connect habit comboentry widget and child entry
        self.view.connect(
            "sp_habit_comboentry", "changed", self.on_habit_comboentry_changed
        )

        # select the current genus but don't dirty the presenter
        self.gen_on_select(self.model.genus)
        self._dirty = False

        # connect signals
        self.view.connect(
            "sp_species_button", "clicked", self.on_sp_species_button_clicked
        )

        self.view.connect(
            "expand_cv_btn", "clicked", self.on_expand_cv_button_clicked
        )

        self.view.connect(
            "label_markup_btn", "clicked", self.on_markup_button_clicked
        )

        self.view.connect(
            "sp_label_markup_entry", "changed", self.on_markup_entry_changed
        )

        self.assign_completions_handler(
            "sp_genus_entry",
            self.gen_get_completions,
            on_select=self.gen_on_select,
        )
        self.assign_completions_handler(
            "subgenus_entry", self.subgenus_get_completions, set_problems=False
        )
        self.assign_completions_handler(
            "section_entry", self.section_get_completions, set_problems=False
        )
        self.assign_completions_handler(
            "subsection_entry",
            self.subsection_get_completions,
            set_problems=False,
        )
        self.assign_completions_handler(
            "series_entry", self.series_get_completions, set_problems=False
        )
        self.assign_completions_handler(
            "subseries_entry",
            self.subseries_get_completions,
            set_problems=False,
        )
        self.assign_simple_handler(
            "sp_grex_entry", "grex", editor.StringOrNoneValidator()
        )
        self.assign_simple_handler(
            "sp_cvgroup_entry", "cv_group", editor.StringOrNoneValidator()
        )
        self.assign_simple_handler(
            "sp_cvepithet_entry",
            "cultivar_epithet",
            editor.StringOrNoneValidator(),
        )
        self.assign_simple_handler(
            "sp_tradename_entry", "trade_name", editor.StringOrNoneValidator()
        )
        self.assign_simple_handler(
            "sp_trademark_combo",
            "trademark_symbol",
            editor.StringOrNoneValidator(),
        )
        self.assign_simple_handler(
            "sp_spqual_combo", "sp_qual", editor.StringOrNoneValidator()
        )
        self.assign_simple_handler(
            "sp_hybrid_combo", "hybrid", editor.StringOrNoneValidator()
        )
        self.assign_simple_handler(
            "sp_label_dist_entry",
            "label_distribution",
            editor.StringOrNoneValidator(),
        )
        self.assign_simple_handler(
            "sp_awards_entry", "awards", editor.StringOrNoneValidator()
        )
        self.assign_simple_handler(
            "cites_combo", "cites", editor.StringOrNoneValidator()
        )
        self.assign_simple_handler(
            "red_list_combo", "red_list", editor.StringOrNoneValidator()
        )
        self.assign_simple_handler(
            "subgenus_entry", "subgenus", editor.StringOrNoneValidator()
        )
        self.assign_simple_handler(
            "section_entry", "section", editor.StringOrNoneValidator()
        )
        self.assign_simple_handler(
            "subsection_entry", "subsection", editor.StringOrNoneValidator()
        )
        self.assign_simple_handler(
            "series_entry", "series", editor.StringOrNoneValidator()
        )
        self.assign_simple_handler(
            "subseries_entry", "subseries", editor.StringOrNoneValidator()
        )

        self.refresh_sensitivity()
        if self.model not in self.session.new:
            self.view.widgets.sp_ok_and_add_button.set_sensitive(True)

        if any(
            getattr(self.model, i)
            for i in ("cv_group", "trade_name", "trademark_symbol", "grex")
        ):
            self.view.widgets.expand_cv_btn.emit("clicked")

        if any(
            getattr(self.model, i)
            for i in (
                "subgenus",
                "section",
                "subsection",
                "series",
                "subseries",
            )
        ):
            self.view.widget_set_expanded("infragen_expander", True)

        if self.model.label_markup:
            self.view.widget_set_expanded("label_markup_expander", True)
            self.view.widgets.sp_label_markup_entry.emit("changed")
            # Don't dirty the presenter
            self._dirty = False

        self._setup_custom_field("_sp_custom1")
        self._setup_custom_field("_sp_custom2")

        self.init_links_menu()

    def subgenus_get_completions(self, text):
        query = self.session.query(Species.subgenus)
        if self.model.genus and self.model.genus.id:
            query = query.filter(Species.genus == self.model.genus)
        query = query.filter(
            utils.ilike(Species.subgenus, f"{text}%%")
        ).distinct()
        return [i[0] for i in query]

    def section_get_completions(self, text):
        query = self.session.query(Species.section)
        if self.model.genus and self.model.genus.id:
            query = query.filter(Species.genus == self.model.genus)
        if self.model.subgenus:
            query = query.filter(Species.subgenus == self.model.subgenus)
        query = query.filter(
            utils.ilike(Species.section, f"{text}%%")
        ).distinct()
        return [i[0] for i in query]

    def subsection_get_completions(self, text):
        query = self.session.query(Species.subsection)
        if self.model.genus and self.model.genus.id:
            query = query.filter(Species.genus == self.model.genus)
        if self.model.subgenus:
            query = query.filter(Species.subgenus == self.model.subgenus)
        if self.model.section:
            query = query.filter(Species.section == self.model.section)
        query = query.filter(
            utils.ilike(Species.subsection, f"{text}%%")
        ).distinct()
        return [i[0] for i in query]

    def series_get_completions(self, text):
        query = self.session.query(Species.series)
        if self.model.genus and self.model.genus.id:
            query = query.filter(Species.genus == self.model.genus)
        if self.model.subgenus:
            query = query.filter(Species.subgenus == self.model.subgenus)
        if self.model.section:
            query = query.filter(Species.section == self.model.section)
        if self.model.subsection:
            query = query.filter(Species.subsection == self.model.subsection)
        query = query.filter(
            utils.ilike(Species.series, f"{text}%%")
        ).distinct()
        return [i[0] for i in query]

    def subseries_get_completions(self, text):
        query = self.session.query(Species.subseries)
        if self.model.genus and self.model.genus.id:
            query = query.filter(Species.genus == self.model.genus)
        if self.model.subgenus:
            query = query.filter(Species.subgenus == self.model.subgenus)
        if self.model.section:
            query = query.filter(Species.section == self.model.section)
        if self.model.subsection:
            query = query.filter(Species.subsection == self.model.subsection)
        if self.model.series:
            query = query.filter(Species.series == self.model.series)
        query = query.filter(
            utils.ilike(Species.subseries, f"{text}%%")
        ).distinct()
        return [i[0] for i in query]

    def _setup_custom_field(self, column_name):
        session = bauble.db.Session()
        custom_meta = (
            session.query(bauble.meta.BaubleMeta)
            .filter(bauble.meta.BaubleMeta.name == column_name)
            .first()
        )
        session.close()
        # pylint: disable=protected-access
        if custom_meta:
            custom_meta = literal_eval(custom_meta.value)
            display_name = custom_meta.get("display_name")
            if display_name:
                label = column_name + "_label"
                self.view.widget_set_text(label, display_name)
                self.view.widget_set_visible(label)
            values = custom_meta.get("values")
            if values:
                combo = getattr(self.view.widgets, column_name + "_combo")
                utils.setup_text_combobox(combo, values)
                utils.set_widget_value(
                    combo, getattr(self.model, column_name, "")
                )
                combo.set_visible(True)
                self.assign_simple_handler(
                    column_name + "_combo",
                    column_name,
                    editor.StringOrNoneValidator(),
                )

    def on_markup_entry_changed(self, widget):
        self.remove_problem(self.PROBLEM_INVALID_MARKUP, widget)
        value = widget.get_text()

        if value == self.model.markup():
            widget.set_name("unsaved-entry")
        else:
            widget.set_name("GtkEntry")

        if value in (self.model.markup(), ""):
            value = None

        if value:
            try:
                Pango.parse_markup(value, -1, "0")
                self.view.set_label("label_markup_label", value)
            except (GLib.Error, TypeError, RuntimeError, UnicodeDecodeError):
                self.view.set_label("label_markup_label", "--")
                value = None
                self.add_problem(self.PROBLEM_INVALID_MARKUP, widget)
        else:
            self.view.set_label("label_markup_label", "--")

        self.set_model_attr("label_markup", value)

    def on_markup_button_clicked(self, _widget):
        self.view.widget_set_value(
            "sp_label_markup_entry", self.model.markup()
        )

    def on_expand_cv_button_clicked(self, *_args):
        extras_grid = self.view.widgets.cv_extras_grid
        visible = not extras_grid.get_visible()
        icon = self.view.widgets.expand_btn_icon
        icon.set_from_icon_name(
            {False: "pan-end-symbolic", True: "pan-start-symbolic"}[visible],
            Gtk.IconSize.BUTTON,
        )
        extras_grid.set_visible(visible)

    def capture_start_sp(self, model):
        self.start_sp_dict = None
        self.start_sp_markup = None
        if model not in self.session.new:
            self.start_sp_dict = {
                "genus": model.genus,
                "sp": model.sp,
                "hybrid": model.hybrid,
                "sp_author": model.sp_author,
                "sp_qual": model.sp_qual,
                "cv_group": model.cv_group,
                "grex": model.grex,
                "cultivar_epithet": model.cultivar_epithet,
                "trade_name": model.trade_name,
                "trademark_symbol": model.trademark_symbol,
                "pbr_protected": model.pbr_protected,
                "infrasp1": model.infrasp1,
                "infrasp1_rank": model.infrasp1_rank,
                "infrasp1_author": model.infrasp1_author,
                "infrasp2": model.infrasp2,
                "infrasp2_rank": model.infrasp2_rank,
                "infrasp2_author": model.infrasp2_author,
                "infrasp3": model.infrasp3,
                "infrasp3_rank": model.infrasp3_rank,
                "infrasp3_author": model.infrasp3_author,
                "infrasp4": model.infrasp4,
                "infrasp4_rank": model.infrasp4_rank,
                "infrasp4_author": model.infrasp4_author,
            }
            self.start_sp_markup = model.string(markup=True, authors=True)

    def _get_taxon(self, parts, species=None):
        msg = None
        gen_hybrid = parts["Genus hybrid marker"] or None
        from sqlalchemy.orm.exc import MultipleResultsFound

        try:
            genus = (
                self.session.query(Genus)
                .join(Family)
                .filter(Family.epithet == parts["Family"])
                .filter(Genus.epithet == parts["Genus"])
                .filter(Genus.hybrid == gen_hybrid)
                .one_or_none()
            )
        except MultipleResultsFound:
            return None, _(
                "Could not resolve the genus, you have multiple matches."
            )

        if not genus:
            try:
                family = (
                    self.session.query(Family)
                    .filter(Family.epithet == parts["Family"])
                    .one_or_none()
                )
            except MultipleResultsFound:
                return None, _(
                    "Could not resolve the family, you have "
                    "multiple matches."
                )

            try:
                genus = (
                    self.session.query(Genus)
                    .filter(Genus.epithet == parts["Genus"])
                    .filter(Genus.hybrid == gen_hybrid)
                    .one_or_none()
                )
                if not genus:
                    # missing hybrid marker
                    genus = (
                        self.session.query(Genus)
                        .filter(Genus.epithet == parts["Genus"])
                        .one_or_none()
                    )
            except MultipleResultsFound:
                return None, _(
                    "Could not resolve the genus, you have "
                    "multiple matches."
                )

            if not family:
                family = Family(epithet=parts["Family"])

            if genus and genus.family != family:
                genus.family = family
                msg = _(
                    "The family of the genus has been changed "
                    "affecting all species of this genera,\nsaving "
                    "now will make this permanent.\n"
                )

            if not genus:
                genus = Genus(epithet=parts["Genus"])
                msg = _(
                    "An entirely new genus has been generated.  If you "
                    "would rather rename the existing genus\nor create it "
                    "yourself cancel now."
                )

            genus.hybrid = gen_hybrid
            genus.family = family

        if not species:
            query = (
                self.session.query(Species)
                .filter(Species.sp == parts["Species"])
                .filter(
                    Species.infraspecific_rank
                    == (parts["Infraspecific rank"] or None)
                )
                .filter(
                    Species.infraspecific_epithet
                    == (parts["Infraspecific epithet"] or None)
                )
            )

            if genus and genus.id:
                query = query.filter(Species.genus == genus)

            species = query.first()

        if not species:
            species = Species()
            msg = _("An entirely new species has been generated.")

        species.genus = genus
        species.hybrid = parts["Species hybrid marker"] or None
        species.sp = parts["Species"]
        species.infrasp1_rank = parts["Infraspecific rank"] or None
        species.infrasp1 = parts["Infraspecific epithet"] or None

        if parts["Infraspecific rank"]:
            species.infrasp1_author = parts["Authorship"]
        else:
            species.sp_author = parts["Authorship"]

        return species, msg

    def sp_species_tpl_callback(self, found, accepted):
        # both found and accepted are dictionaries

        self.view.close_boxes()

        if found:
            found = dict((k, utils.nstr(v)) for k, v in found.items())
            found_s = dict(
                (k, utils.xml_safe(utils.nstr(v))) for k, v in found.items()
            )
        if accepted:
            accepted = dict((k, utils.nstr(v)) for k, v in accepted.items())
            accepted_s = dict(
                (k, utils.xml_safe(utils.nstr(v))) for k, v in accepted.items()
            )
        msg_box_msg = _("No match found on ThePlantList.org")

        if not (found is None and accepted is None):

            def _is_match(model, vals):
                if not model or not vals:
                    return False

                author_level = "sp_author"
                if vals["Infraspecific epithet"]:
                    author_level = "infraspecific_author"

                return (
                    model.genus.family.epithet == vals["Family"]
                    and model.genus.epithet == vals["Genus"]
                    and model.sp == vals["Species"]
                    and model.infraspecific_rank == vals["Infraspecific rank"]
                    and model.infraspecific_epithet
                    == vals["Infraspecific epithet"]
                    and getattr(model, author_level) == vals["Authorship"]
                    and model.hybrid == (vals["Species hybrid marker"] or None)
                    and model.genus.hybrid
                    == (vals["Genus hybrid marker"] or None)
                )

            if _is_match(self.model, found) and (
                accepted is None or _is_match(self.model.accepted, accepted)
            ):
                msg_box_msg = _("your data finely matches ThePlantList.org")
            else:
                if not _is_match(self.model, found):
                    msg_box_msg = None
                    infrasp = ""
                    if found_s["Infraspecific epithet"]:
                        infrasp = (
                            f' {found_s["Infraspecific rank"]} '
                            f'<i>{found_s["Infraspecific epithet"]}</i> '
                        )
                    cit = (
                        f'{found_s["Genus hybrid marker"]}'
                        f'<i>{found_s["Genus"]}</i> '
                        f'{found_s["Species hybrid marker"]}'
                        f'<i>{found_s["Species"]}</i> '
                        f"{infrasp}"
                        f'{found_s["Authorship"]} '
                        f'({found_s["Family"]})'
                    )
                    msg = (
                        _(
                            "%s is the closest match for your data.\n"
                            "Do you want to accept it?"
                        )
                        % cit
                    )
                    box = self.view.add_message_box(utils.MESSAGE_BOX_YESNO)
                    box1 = box
                    box.message = msg

                    def on_response_found(_button, response):
                        self.view.remove_box(box1)
                        if response:
                            model, msg = self._get_taxon(found, self.model)
                            if model:
                                self._dirty = True
                            self.infrasp_presenter.refresh_rows()
                            self.refresh_view()
                            self.refresh_fullname_label()
                            self.refresh_sensitivity()

                            if msg:
                                box0 = self.view.add_message_box(
                                    utils.MESSAGE_BOX_INFO
                                )
                                box0.message = msg
                                box0.on_response = (
                                    lambda b, r: self.view.remove_box(box0)
                                )
                                box0.show()
                                self.view.add_box(box0)
                                self.species_check_messages.append(box0)

                    box.on_response = on_response_found
                    box.show()
                    self.view.add_box(box)
                    self.species_check_messages.append(box)

                if accepted and not _is_match(self.model.accepted, accepted):
                    msg_box_msg = None
                    # synonym is at rank species, this is fine
                    infrasp = ""
                    if accepted_s["Infraspecific epithet"]:
                        infrasp = (
                            f' {accepted_s["Infraspecific rank"]} '
                            f'<i>{accepted_s["Infraspecific epithet"]}</i> '
                        )
                    cit = (
                        f'{accepted_s["Genus hybrid marker"]}'
                        f'<i>{accepted_s["Genus"]}</i> '
                        f'{accepted_s["Species hybrid marker"]}'
                        f'<i>{accepted_s["Species"]}</i> '
                        f"{infrasp}"
                        f'{accepted_s["Authorship"]} '
                        f'({accepted_s["Family"]})'
                    )
                    msg = (
                        _(
                            "%s is the accepted taxon for your data.\n"
                            "Do you want to add it and transfer any "
                            "acessions to it?"
                        )
                        % cit
                    )
                    box = self.view.add_message_box(utils.MESSAGE_BOX_YESNO)
                    box2 = box
                    box.message = msg

                    def on_response_accepted(_button, response):
                        self.view.remove_box(box2)
                        if response:
                            model, msg = self._get_taxon(accepted)
                            if model and model is not self.model:
                                self.model.accepted = model
                                for acc in self.model.accessions.copy():
                                    acc.species = model
                            self._dirty = True
                            self.refresh_sensitivity()
                            self.refresh_view()
                            self.refresh_fullname_label()

                            if msg:
                                box0 = self.view.add_message_box(
                                    utils.MESSAGE_BOX_INFO
                                )
                                box0.message = msg
                                box0.on_response = (
                                    lambda b, r: self.view.remove_box(box0)
                                )
                                box0.show()
                                self.view.add_box(box0)
                                self.species_check_messages.append(box0)

                    box.on_response = on_response_accepted
                    box.show()
                    self.view.add_box(box)
                    self.species_check_messages.append(box)

        if msg_box_msg is not None:
            box0 = self.view.add_message_box(utils.MESSAGE_BOX_INFO)
            box0.message = msg_box_msg
            box0.on_response = lambda b, r: self.view.remove_box(box0)
            box0.show()
            self.view.add_box(box0)
            self.species_check_messages.append(box0)

    def on_sp_species_button_clicked(self, _widget, event=None):
        # the real activity runs in a separate thread.
        logger.debug("sp_species button clicked, importing AskTpl")
        from .ask_tpl import AskTPL

        while self.species_check_messages:
            kid = self.species_check_messages.pop()
            self.view.widgets.remove_parent(kid)

        binomial = str(self.model)
        # we need a longer timeout for the first time at least when using a
        # pac file to get the proxy configuration
        logger.debug("calling AskTpl with binomial=%s", binomial)
        AskTPL(
            binomial, self.sp_species_tpl_callback, timeout=7, gui=True
        ).start()
        box0 = self.view.add_message_box(utils.MESSAGE_BOX_INFO)
        box0.message = _("querying the plant list")
        box0.on_response = lambda b, r: self.view.remove_box(box0)
        box0.show()
        self.view.add_box(box0)
        if event is not None:
            return False

    def gen_get_completions(self, text):
        query = generic_gen_get_completions(self.session, text)
        if self.model.genus in self.session.new:
            # e.g. after on_sp_species_button_clicked has caused a new genus to
            # be added.
            return query.all() + [self.model.genus]
        return query

    # called when a genus is selected from the genus completions
    def gen_on_select(self, value):
        logger.debug("on select: %s", value)
        if isinstance(value, str):
            value = (
                self.session.query(Genus).filter(Genus.genus == value).first()
            )
        while self.genus_check_messages:
            kid = self.genus_check_messages.pop()
            self.view.widgets.remove_parent(kid)
        self.set_model_attr("genus", value)
        self.refresh_fullname_label()
        if not value:  # no choice is a fine choice
            return
        # is value considered a synonym?
        syn = (
            self.session.query(GenusSynonym)
            .filter(GenusSynonym.synonym_id == value.id)
            .first()
        )
        if not syn:
            # chosen value is not a synonym, also fine
            return

        # value is a synonym: user alert needed
        msg = _(
            "The genus <b>%(synonym)s</b> is a synonym of "
            "<b>%(genus)s</b>.\n\nWould you like to choose "
            "<b>%(genus)s</b> instead?"
        ) % {"synonym": syn.synonym, "genus": syn.genus}
        box = None

        def on_response(_button, response):
            self.view.remove_box(box)
            if response:
                self.set_model_attr("genus", syn.genus)
                self.refresh_view()
                self.refresh_fullname_label()

        box = self.view.add_message_box(utils.MESSAGE_BOX_YESNO)
        box.message = msg
        box.on_response = on_response
        box.show()
        self.view.add_box(box)
        self.genus_check_messages.append(box)

    def set_visible_buttons(self, visible):
        self.view.widgets.sp_ok_and_add_button.set_visible(visible)
        self.view.widgets.sp_next_button.set_visible(visible)

    def on_sp_species_entry_changed(self, widget, *args):
        self.on_text_entry_changed(widget, *args)
        self.on_entry_changed_clear_boxes(widget, *args)
        self.refresh_sensitivity()

    def on_entry_changed_clear_boxes(self, _widget):
        while self.species_check_messages:
            kid = self.species_check_messages.pop()
            self.view.widgets.remove_parent(kid)

    # static method ensures garbage collection
    @staticmethod
    def on_habit_entry_changed(entry, combo):
        # check if the combo has a problem then check if the value
        # in the entry matches one of the habit codes and if so
        # then change the value to the habit
        code = entry.get_text()
        try:
            utils.set_combo_from_value(
                combo, code.lower(), cmp=lambda r, v: r[0].lower() == v.lower()
            )
        except ValueError as e:
            logger.debug("%s (%s)", type(e).__name__, e)

    def on_habit_comboentry_changed(self, combo):
        """Changed handler for sp_habit_comboentry.

        We don't need specific handlers for either comboentry because
        the validation is done in the specific Gtk.Entry handlers for
        the child of the combo entries.
        """
        treeiter = combo.get_active_iter()
        self.remove_problem(self.PROBLEM_UNKOWN_HABIT, combo.get_child())
        if not treeiter:
            self.add_problem(self.PROBLEM_UNKOWN_HABIT, combo.get_child())
            self.refresh_sensitivity()
            return
        value = combo.get_model()[treeiter][1]
        self.set_model_attr("habit", value)
        # the entry change handler does the validation of the model
        combo.get_child().set_text(str(value or ""))
        combo.get_child().set_position(-1)

    def __del__(self):
        # we have to delete the views in the child presenters manually
        # to avoid the circular reference
        # NOTE pictures_presenter and notes_presenter have no view
        del self.vern_presenter.view
        del self.synonyms_presenter.view
        del self.dist_presenter.view
        del self.infrasp_presenter.view

    def is_dirty(self):
        return (
            self._dirty
            or self.pictures_presenter.is_dirty()
            or self.vern_presenter.is_dirty()
            or self.synonyms_presenter.is_dirty()
            or self.dist_presenter.is_dirty()
            or self.infrasp_presenter.is_dirty()
            or self.notes_presenter.is_dirty()
        )

    def set_model_attr(self, attr, value, validator=None):
        """Resets the sensitivity on the ok buttons and the name widgets when
        values change in the model
        """
        super().set_model_attr(attr, value, validator)
        self._dirty = True
        self.refresh_sensitivity()

    def refresh_sensitivity(self):
        has_parts = any(
            [
                self.model.sp,
                self.model.cultivar_epithet,
                self.model.grex,
                self.model.cv_group,
                self.model.infrasp1,
                self.model.infrasp2,
                self.model.infrasp3,
                self.model.infrasp4,
            ]
        )
        has_problems = any(
            [
                self.problems,
                self.vern_presenter.problems,
                self.synonyms_presenter.problems,
                self.dist_presenter.problems,
            ]
        )
        if self.model.genus and has_parts and not has_problems:
            self.view.set_accept_buttons_sensitive(self.is_dirty())
        else:
            self.view.set_accept_buttons_sensitive(False)

    def init_fullname_widgets(self):
        """initialized the signal handlers on the widgets that are relative to
        building the fullname string in the sp_fullname_label widget
        """
        self.refresh_fullname_label()

        widgets = [
            "sp_species_entry",
            "sp_author_entry",
            "sp_grex_entry",
            "sp_cvgroup_entry",
            "sp_cvepithet_entry",
            "sp_tradename_entry",
            "sp_trademark_combo",
            "sp_spqual_combo",
            "sp_hybrid_combo",
        ]

        for widget_name in widgets:
            self.view.connect_after(
                widget_name, "changed", self.refresh_fullname_label
            )

        self.view.connect_after(
            "sp_pbr_checkbtn", "toggled", self.refresh_fullname_label
        )

    def refresh_fullname_label(self, widget=None):
        """set the value of sp_fullname_label to either '--' if there
        is a problem or to the name of the string returned by Species.str
        """
        logger.debug(
            "SpeciesEditorPresenter:refresh_fullname_label %s", widget
        )

        self.refresh_cites_label()

        if len(self.problems) > 0 or self.model.genus is None:
            self.view.set_label("sp_fullname_label", "--")
            return
        sp_str = self.model.string(markup=True, authors=True)
        self.view.set_label("sp_fullname_label", sp_str)

        # add previous species as synonym
        if self.start_sp_markup and sp_str != self.start_sp_markup:
            self.view.widgets.prev_sp_box.set_visible(True)
            self.view.set_label(
                "sp_prev_name_label", self.start_sp_markup + " (previous name)"
            )
            self.view.widget_set_value("sp_label_markup_entry", "")
        else:
            self.view.widgets.prev_sp_box.set_visible(False)
            self.view.widgets.add_syn_chkbox.set_active(False)

        if self.model.genus is not None:
            GLib.idle_add(self._warn_double_ups)

    def refresh_cites_label(self):
        gen_cites = fam_cites = "N/A"
        if self.model.genus:
            # pylint: disable=protected-access
            if val := self.model.genus._cites:
                gen_cites = val

            if self.model.genus.family:
                if val := self.model.genus.family.cites:
                    fam_cites = val

        string = f"Family: {fam_cites}, Genus: {gen_cites}"
        self.view.set_label("cites_label", string)

    def _warn_double_ups(self):
        genus = self.model.genus.genus
        epithet = self.view.widget_get_value("sp_species_entry") or None
        infrasp = self.model.infraspecific_epithet or None
        cultivar = self.model.cultivar_epithet or None
        omonym = (
            self.session.query(Species)
            .join(Genus)
            .filter(
                Genus.genus == genus,
                Species.sp == epithet,
                Species.infraspecific_epithet == infrasp,
                Species.cultivar_epithet == cultivar,
                Species.grex == self.model.grex,
                Species.cv_group == self.model.cv_group,
            )
            .first()
        )
        logger.debug("looking for %s, found %s", self.model, omonym)

        if omonym in [None, self.model]:
            # should not warn, so check warning and remove
            if self.omonym_box is not None:
                self.view.remove_box(self.omonym_box)
                self.omonym_box = None
        elif self.omonym_box is None:  # should warn, but not twice
            msg = _(
                "This taxon name is already in your collection"
                ", as %s.\n\n"
                "Are you sure you want to insert it again?"
            ) % omonym.string(authors=True, markup=True)

            def on_response(_button, response):
                self.view.remove_box(self.omonym_box)
                self.omonym_box = None
                if response:
                    logger.warning("yes")
                else:
                    # set all infrasp_parts to None
                    self.infrasp_presenter.clear_rows()
                    self.view.widget_set_value("sp_species_entry", "")

            box = self.omonym_box = self.view.add_message_box(
                utils.MESSAGE_BOX_YESNO
            )
            box.message = msg
            box.on_response = on_response
            box.show()
            self.view.add_box(box)

    def cleanup(self):
        super().cleanup()
        self.remove_link_action_group()
        self.vern_presenter.cleanup()
        self.synonyms_presenter.cleanup()
        self.dist_presenter.cleanup()
        self.infrasp_presenter.cleanup()
        self.notes_presenter.cleanup()
        self.pictures_presenter.cleanup()

    def start(self):
        response = self.view.start()
        return response

    def refresh_view(self):
        for widget, field in self.widget_to_field_map.items():
            value = getattr(self.model, field)
            logger.debug("%s, %s, %s(%s)", widget, field, type(value), value)
            self.view.widget_set_value(widget, value)

        utils.set_widget_value(
            self.view.widgets.sp_habit_comboentry, self.model.habit or ""
        )
        self.vern_presenter.refresh_view()
        self.synonyms_presenter.refresh_view()
        self.dist_presenter.refresh_view()


class InfraspRow:
    def __init__(self, presenter, level):
        self.presenter = presenter
        self.species = presenter.model
        grid = self.presenter.view.widgets.infrasp_grid
        self.level = level

        rank, epithet, author = self.species.get_infrasp(self.level)
        self.new = all(i is None for i in [rank, epithet, author])

        self.rank_combo = Gtk.ComboBox()
        self.refresh_rank_combo()

        self._rank_sid = self.rank_combo.connect(
            "changed", self.on_rank_combo_changed
        )
        grid.attach(self.rank_combo, 0, level, 1, 1)

        # epithet entry
        self.epithet_entry = Gtk.Entry(hexpand=True)
        utils.set_widget_value(self.epithet_entry, epithet)
        presenter.view.connect(
            self.epithet_entry, "changed", self.on_epithet_entry_changed
        )
        grid.attach(self.epithet_entry, 1, level, 1, 1)

        # author entry
        self.author_entry = Gtk.Entry(hexpand=True)
        utils.set_widget_value(self.author_entry, author)
        presenter.view.connect(
            self.author_entry, "changed", self.on_author_entry_changed
        )
        grid.attach(self.author_entry, 2, level, 1, 1)

        # remove button
        self.remove_button = Gtk.Button.new_from_icon_name(
            "list-remove-symbolic", Gtk.IconSize.BUTTON
        )
        presenter.view.connect(
            self.remove_button, "clicked", self.on_remove_button_clicked
        )
        grid.attach(self.remove_button, 3, level, 1, 1)
        grid.show_all()

    def refresh_rank_combo(self, block=False):
        rank = self.species.get_infrasp(self.level)[0]
        try:
            prior_rank = self.species.get_infrasp(self.level - 1)[0]
        except KeyError:
            prior_rank = False

        if prior_rank is not False:
            if not prior_rank:
                rank_values = {None: ""}
            else:
                current_rank = compare_rank.get(prior_rank, 150)
                rank_values = {
                    k: v
                    for k, v in infrasp_rank_values.items()
                    if compare_rank.get(k, 150) > current_rank
                }
            if rank not in rank_values:
                rank = None
        else:
            rank_values = infrasp_rank_values

        logger.debug("rank values = %s", rank_values)
        self.presenter.view.init_translatable_combo(
            self.rank_combo,
            rank_values,
            key=lambda x: compare_rank.get(str(x[0])),
        )
        if block:
            self.rank_combo.handler_block(self._rank_sid)
        utils.set_widget_value(self.rank_combo, rank)
        if block:
            self.rank_combo.handler_unblock(self._rank_sid)

    def on_remove_button_clicked(self, _widget):
        # remove the widgets
        grid = self.presenter.view.widgets.infrasp_grid
        # Not perfect but allows saving a deleted row on old entries
        dirty = self.presenter._dirty
        # remove the infrasp from the species and reset the levels
        # on the remaining infrasp that have a higher level than
        # the one being deleted
        grid.remove_row(self.level)

        self.set_model_attr("rank", None)
        self.set_model_attr("epithet", None)
        self.set_model_attr("author", None)

        table_len = len(self.presenter.table_rows)

        # move all the infrasp values up a level and set the last None
        for i in range(self.level + 1, 6):
            try:
                rank, epithet, author = self.species.get_infrasp(i)
            except KeyError:
                rank = epithet = author = None
            self.species.set_infrasp(i - 1, rank, epithet, author)
            if i <= table_len:
                self.presenter.table_rows[i - 1].level = i - 1
                self.presenter.table_rows[i - 1].refresh_rank_combo(block=True)

        self.presenter.table_rows.remove(self)

        if self.new:
            self.presenter._dirty = dirty
        self.presenter.parent_ref().refresh_fullname_label()
        self.presenter.parent_ref().refresh_sensitivity()
        (self.presenter.view.widgets.add_infrasp_button.props.sensitive) = True

    def set_model_attr(self, attr, value):
        infrasp_attr = Species.infrasp_attr[self.level][attr]
        setattr(self.species, infrasp_attr, value)
        self.presenter._dirty = True
        self.presenter.parent_ref().refresh_fullname_label()
        self.presenter.parent_ref().refresh_sensitivity()

    def on_rank_combo_changed(self, combo):
        logger.info("on_rank_combo_changed")
        model = combo.get_model()
        itr = combo.get_active_iter()
        value = model[itr][0]
        if value is not None:
            self.set_model_attr("rank", utils.nstr(model[itr][0]))
        else:
            self.set_model_attr("rank", None)
        table_len = len(self.presenter.table_rows)
        if self.level < table_len:
            self.presenter.table_rows[self.level].refresh_rank_combo()

    def on_epithet_entry_changed(self, entry):
        logger.info("on_epithet_entry_changed")
        value = utils.nstr(entry.get_text())
        if not value:  # if None or ''
            value = None
        self.set_model_attr("epithet", value)

    def on_author_entry_changed(self, entry):
        logger.info("on_author_entry_changed")
        value = utils.nstr(entry.get_text())
        if not value:  # if None or ''
            value = None
        self.set_model_attr("author", value)


class InfraspPresenter(editor.GenericEditorPresenter):
    def __init__(self, parent):
        """
        :param parent: the parent SpeciesEditorPresenter
        """
        super().__init__(
            parent.model, parent.view, session=False, connect_signals=False
        )
        self.parent_ref = weakref.ref(parent)
        self._dirty = False
        self.view.connect("add_infrasp_button", "clicked", self.append_infrasp)

        for item in self.view.widgets.infrasp_grid.get_children():
            if not isinstance(item, Gtk.Label):
                self.view.widgets.remove_parent(item)
        self.table_rows = []
        self.refresh_rows()

    def refresh_rows(self):
        self.clear_rows()
        for index in range(1, 5):
            infrasp = self.model.get_infrasp(index)
            if infrasp != (None, None, None):
                self.append_infrasp(None)

    def is_dirty(self):
        return self._dirty

    def append_infrasp(self, _widget=None):
        level = len(self.table_rows) + 1
        if level == 1 or self.model.get_infrasp(level - 1)[0]:
            logger.debug("appending infrasp row %s", level)
            row = InfraspRow(self, level)
            self.table_rows.append(row)
            if level >= 4:
                self.view.widgets.add_infrasp_button.set_sensitive(False)
            return row
        return None

    def clear_rows(self):
        """Clear all the infraspecific rows if any exist"""
        for row in self.table_rows.copy():
            row.on_remove_button_clicked(None)


class DistributionPresenter(editor.GenericEditorPresenter):
    MENU_ACTIONGRP_NAME = "distribution_menu_btn"

    def __init__(self, parent):
        """
        :param parent: the parent SpeciesEditorPresenter
        """
        super().__init__(
            parent.model,
            parent.view,
            session=parent.session,
            connect_signals=False,
        )
        self.parent_ref = weakref.ref(parent)
        self._dirty = False

        self.init_menu_btn()

        self.remove_menu_model = Gio.Menu()
        action = Gio.SimpleAction.new(
            "geography_remove", GLib.VariantType("s")
        )
        action.connect("activate", self.on_activate_remove_menu_item)

        action_group = Gio.SimpleActionGroup()
        action_group.add_action(action)

        remove_button = self.view.widgets.sp_dist_remove_button
        remove_button.insert_action_group("geo", action_group)

        self.remove_menu = Gtk.Menu.new_from_model(self.remove_menu_model)
        self.remove_menu.attach_to_widget(remove_button, None)

        self.view.connect(
            "sp_dist_add_button",
            "button-press-event",
            self.on_add_button_pressed,
        )
        self.view.connect(
            "sp_dist_remove_button",
            "button-press-event",
            self.on_remove_button_pressed,
        )

        self.view.widgets.sp_dist_add_button.set_sensitive(False)
        self.geo_menu = None

        add_button = self.view.widgets.sp_dist_add_button
        self.geo_menu = GeographyMenu.new_menu(
            self.on_activate_add_menu_item, add_button
        )
        self.geo_menu.attach_to_widget(add_button)
        add_button.set_sensitive(True)

    def init_menu_btn(self) -> None:
        """Initialise the distribution menu button.

        Create the ActionGroup and Menu, set the MenuButton menu model to the
        Menu and insert the ActionGroup.
        """
        menu = Gio.Menu()
        action_group = Gio.SimpleActionGroup()
        menu_items = (
            (_("Clear all"), "clear", self.on_clear_all),
            (_("Consolidate"), "consolidate", self.on_consolidate),
            (_("Paste - append"), "append", self.on_paste_append),
            (_("Paste - replace all"), "replace", self.on_paste_replace),
            (_("Copy codes"), "copy_codes", self.on_copy_codes),
            (_("Copy names"), "copy_names", self.on_copy_names),
        )
        for label, name, handler in menu_items:
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", handler)
            action_group.add_action(action)
            menu_item = Gio.MenuItem.new(
                label, f"{self.MENU_ACTIONGRP_NAME}.{name}"
            )
            menu.append_item(menu_item)

        menu_btn = self.view.widgets.sp_dist_menu_btn

        menu_btn.set_menu_model(menu)

        menu_btn.insert_action_group(self.MENU_ACTIONGRP_NAME, action_group)

    def on_clear_all(self, *_args) -> None:
        """Clear all distributions."""
        self.model.distribution = []

        self._dirty = True
        self.refresh_view()
        self.parent_ref().refresh_sensitivity()

    def append_dists_from_text(self, text: str) -> None:
        """Given a string of comma seperated names or codes, attempt to match
        them to WGSRPD units and append them to the current distributions.

        If any errors resolving names let the user know and return.
        """
        geo_names = [i.strip() for i in text.strip().split(",")]

        levels_counter: dict[int, int] = {}
        name_map: dict[str, list[Geography]] = {}
        unresolved = set()

        code_re = re.compile(r"^[0-9A-Z-]{1,6}$")
        # if text contains only codes
        if all(code_re.match(i) for i in geo_names):
            geos = self.session.query(Geography).filter(
                Geography.code.in_(geo_names)
            )

            for geo in geos:
                name_map.setdefault(geo.code, []).append(geo)
                val = levels_counter.get(geo.level, 0) + 1
                levels_counter[geo.level] = val

            for code in geo_names:
                if code not in name_map:
                    unresolved.add(code)
        else:
            # get the full names first - low hanging fruit
            geos = self.session.query(Geography).filter(
                Geography.name.in_(geo_names)
            )

            for geo in geos:
                name_map.setdefault(geo.name, []).append(geo)
                val = levels_counter.get(geo.level, 0) + 1
                levels_counter[geo.level] = val

            # then the abbreviated
            for name in geo_names:
                if not name:
                    unresolved.add(name)
                elif name not in name_map:
                    geos = self.session.query(Geography).filter(
                        utils.ilike(Geography.name, f"{name}%")
                    )
                    if not geos.all():
                        unresolved.add(name)
                    for geo in geos:
                        name_map.setdefault(geo.name, []).append(geo)
                        val = levels_counter.get(geo.level, 0) + 1
                        levels_counter[geo.level] = val

        if unresolved:
            msg = _('Could not resolve "%s"') % ", ".join(unresolved)
            utils.message_dialog(
                msg,
                Gtk.MessageType.ERROR,
                parent=self.parent_ref().view.get_window(),
            )
            logger.debug(msg)
            return

        geos = set()
        for geo_list in name_map.values():
            # heuristic choice: highest level or most common level
            if len(geo_list) > 1:
                if len(set(levels_counter.values())) == 1:
                    geo_list = [
                        sorted(geo_list, key=lambda i: i.level, reverse=True)[
                            0
                        ]
                    ]
                else:
                    geo_list = [
                        sorted(
                            geo_list,
                            key=lambda i: levels_counter[i.level],
                            reverse=True,
                        )[0]
                    ]
            geos.add(geo_list[0])

        existing_geos = [dist.geography for dist in self.model.distribution]

        for geo in sorted(geos, key=lambda i: i.name):
            if geo not in existing_geos:
                dist = SpeciesDistribution(geography=geo)
                self.model.distribution.append(dist)

        self._dirty = True
        self.refresh_view()
        self.parent_ref().refresh_sensitivity()

    def on_consolidate(self, *_args) -> None:
        geos = [i.geography for i in self.model.distribution]
        dists = []

        for geo in sorted(consolidate_geographies(geos), key=lambda i: i.name):
            dist = SpeciesDistribution(geography=geo)
            dists.append(dist)

        self.model.distribution = dists
        self._dirty = True
        self.refresh_view()
        self.parent_ref().refresh_sensitivity()

    def on_paste_append(self, *_args) -> None:
        if bauble.gui:
            text = bauble.gui.get_display_clipboard().wait_for_text()
            self.append_dists_from_text(text or "")

    def on_paste_replace(self, *_args) -> None:
        self.model.distribution = []
        if bauble.gui:
            text = bauble.gui.get_display_clipboard().wait_for_text()
            self.append_dists_from_text(text or "")

    def on_copy_codes(self, *_args) -> None:
        if bauble.gui:
            clipboard = bauble.gui.get_display_clipboard()
            txt = ", ".join(
                [d.geography.code for d in self.model.distribution]
            )
            clipboard.set_text(txt, -1)

    def on_copy_names(self, *_args) -> None:
        if bauble.gui:
            clipboard = bauble.gui.get_display_clipboard()
            txt = ", ".join(
                [d.geography.name for d in self.model.distribution]
            )
            clipboard.set_text(txt, -1)

    def cleanup(self):
        super().cleanup()
        self.geo_menu.destroy()

    def refresh_view(self) -> None:
        label = self.view.widgets.sp_dist_label
        txt = ", ".join(str(d) for d in self.model.distribution)
        label.set_text(textwrap.shorten(txt, width=500, placeholder=" ..."))

    def on_add_button_pressed(self, _button, event):
        self.geo_menu.popup_at_pointer(event)

    def on_remove_button_pressed(self, _button, event):
        # clear the menu first
        self.remove_menu_model.remove_all()
        # populate the menu
        for dist in self.model.distribution:
            # NOTE can't use dist.id as dist may not have been committed yet.
            item = Gio.MenuItem.new(
                str(dist), f"geo.geography_remove::{dist.geography.id}"
            )
            self.remove_menu_model.append_item(item)

        self.remove_menu.popup_at_pointer(event)

    def on_activate_add_menu_item(self, _action, geo_id):
        geo_id = int(geo_id.unpack())

        geo = self.session.query(Geography).get(geo_id)
        # check that this geography isn't already in the distributions
        if geo in [d.geography for d in self.model.distribution]:
            logger.debug("%s already in %s", geo, self.model)
            return
        dist = SpeciesDistribution(geography=geo)
        self.model.distribution.append(dist)
        logger.debug([str(d) for d in self.model.distribution])
        self._dirty = True
        self.refresh_view()
        self.parent_ref().refresh_sensitivity()

    def on_activate_remove_menu_item(self, _action, geo_id):
        geo_id = int(geo_id.unpack())
        dist = [
            i for i in self.model.distribution if i.geography.id == geo_id
        ][0]
        self.model.distribution.remove(dist)
        utils.delete_or_expunge(dist)
        self.refresh_view()
        self._dirty = True
        self.parent_ref().refresh_sensitivity()

    def is_dirty(self):
        return self._dirty


class VernacularNamePresenter(editor.GenericEditorPresenter):
    """In the VernacularNamePresenter we don't really use self.model, we
    more rely on the model in the TreeView which are VernacularName
    objects.
    """

    def __init__(self, parent):
        """
        :param parent: the parent SpeciesEditorPresenter
        """
        super().__init__(
            parent.model,
            parent.view,
            session=parent.session,
            connect_signals=False,
        )
        self.parent_ref = weakref.ref(parent)
        self._dirty = False
        self.init_treeview(self.model.vernacular_names)
        self.view.connect(
            "sp_vern_add_button", "clicked", self.on_add_button_clicked
        )
        self.view.connect(
            "sp_vern_remove_button", "clicked", self.on_remove_button_clicked
        )

    def is_dirty(self):
        return self._dirty

    def on_add_button_clicked(self, _button):
        """Add the values in the entries to the model."""
        treemodel = self.treeview.get_model()
        column = self.treeview.get_column(0)
        vernacular = VernacularName()
        self.model.vernacular_names.append(vernacular)
        treeiter = treemodel.append([vernacular])
        path = treemodel.get_path(treeiter)
        self.treeview.set_cursor(path, column, start_editing=True)
        if len(treemodel) == 1:
            self.model.default_vernacular_name = vernacular

    def on_remove_button_clicked(self, _button):
        """Removes the currently selected vernacular name from the view."""
        tree = self.view.widgets.vern_treeview
        path, _col = tree.get_cursor()
        treemodel = tree.get_model()
        vernacular = treemodel[path][0]

        msg = _(
            "Are you sure you want to remove the vernacular name <b>%s</b>?"
        ) % utils.xml_safe(vernacular.name)
        if (
            vernacular.name
            and vernacular not in self.session.new
            and not utils.yes_no_dialog(msg, parent=self.view.get_window())
        ):
            return

        treemodel.remove(treemodel.get_iter(path))
        self.model.vernacular_names.remove(vernacular)
        if self.model.default_vernacular_name == vernacular:
            del self.model.default_vernacular_name
        utils.delete_or_expunge(vernacular)
        if not self.model.default_vernacular_name:
            # if there is only one value in the tree then set it as the
            # default vernacular name
            first = treemodel.get_iter_first()
            if first:
                # seems we can't always use self.set_model_attr for
                # default_vernacular_name, see commit 099f97090
                self.model.default_vernacular_name = treemodel[first][0]
        self._dirty = True
        self.parent_ref().refresh_sensitivity()

    def on_default_toggled(self, cell, path):
        """Default column callback."""
        active = cell.get_active()
        if not active:  # then it's becoming active
            vernacular = self.treeview.get_model()[path][0]
            self.set_model_attr("default_vernacular_name", vernacular)
        self._dirty = True
        self.parent_ref().refresh_sensitivity()

    def on_cell_edited(self, _cell, path, new_text, prop):
        treemodel = self.treeview.get_model()
        vernacular = treemodel[path][0]
        if getattr(vernacular, prop) == new_text:
            return  # didn't change
        setattr(vernacular, prop, utils.nstr(new_text))
        self._dirty = True
        self.parent_ref().refresh_sensitivity()

    @staticmethod
    def generic_data_func(_column, cell, model, treeiter, attr):
        val = model[treeiter][0]
        cell.set_property("text", getattr(val, attr))
        # change the foreground color to indicate it's new and hasn't been
        # committed
        if val.id is None:  # hasn't been committed
            cell.set_property("foreground", "blue")
        else:
            cell.set_property("foreground", None)

    def default_data_func(self, _column, cell, model, itr, _data):
        val = model[itr][0]
        try:
            cell.set_property(
                "active", val == self.model.default_vernacular_name
            )
            return
        except AttributeError as e:
            logger.debug("AttributeError %s", e)
        cell.set_property("active", False)

    def init_treeview(self, model):
        """Initialized the list of vernacular names.

        The columns and cell renderers are loaded from the .glade file
        so we just need to customize them a bit.
        """
        self.treeview = self.view.widgets.vern_treeview
        if not isinstance(self.treeview, Gtk.TreeView):
            return

        cell = self.view.widgets.vn_name_cell
        self.view.widgets.vn_name_column.set_cell_data_func(
            cell, self.generic_data_func, "name"
        )
        self.view.connect(cell, "edited", self.on_cell_edited, "name")

        cell = self.view.widgets.vn_lang_cell
        self.view.widgets.vn_lang_column.set_cell_data_func(
            cell, self.generic_data_func, "language"
        )

        lang_store = Gtk.ListStore(str)
        for (lang,) in self.session.query(VernacularName.language).distinct():
            if lang:
                lang_store.append([lang])

        lang_completion = Gtk.EntryCompletion(model=lang_store)
        lang_completion.set_text_column(0)

        def _lang_edit_start(_cell_renderer, editable, _path):
            editable.set_completion(lang_completion)

        cell.connect("editing-started", _lang_edit_start)
        self.view.connect(cell, "edited", self.on_cell_edited, "language")

        cell = self.view.widgets.vn_default_cell
        self.view.widgets.vn_default_column.set_cell_data_func(
            cell, self.default_data_func
        )
        self.view.connect(cell, "toggled", self.on_default_toggled)

        utils.clear_model(self.treeview)

        # add the vernacular names to the tree
        tree_model = Gtk.ListStore(object)
        for vernacular in model:
            tree_model.append([vernacular])
        self.treeview.set_model(tree_model)

        self.view.connect(
            self.treeview, "cursor-changed", self.on_tree_cursor_changed
        )

    def on_tree_cursor_changed(self, tree):
        self.view.widgets.sp_vern_remove_button.set_sensitive(
            len(tree.get_model()) > 0
        )

    def refresh_view(self):
        tree_model = self.treeview.get_model()
        vernacular_names = self.model.vernacular_names
        default_vernacular_name = self.model.default_vernacular_name
        if len(vernacular_names) > 0 and default_vernacular_name is None:
            msg = _(
                "This species has vernacular names but none of them are "
                "selected as the default. The first vernacular name in "
                "the list has been automatically selected."
            )
            utils.message_dialog(msg)
            first = tree_model.get_iter_first()
            value = tree_model[first][0]
            self.model.default_vernacular_name = value
            self._dirty = True
            self.parent_ref().refresh_sensitivity()


class SpeciesEditorView(editor.GenericEditorView):
    _tooltips = {
        "sp_genus_entry": _("Genus"),
        "sp_species_entry": _(
            "Species epithet should not be capitilised (to "
            'include a hybrid formula typing a "*" '
            "(asterisk) will insert a cross symbol and "
            "allow spaces in the entry.  Similarly typing "
            '"sp." or "(" will allow for adding provisional '
            "or descriptors names etc..)"
        ),
        "sp_author_entry": _("Species author"),
        "sp_hybrid_combo": _(
            'Species hybrid flag, a named hybrid ("x") or a '
            'graft chimaera ("+")'
        ),
        "sp_grex_entry": _("Intended for Orchidaceae cultivars only."),
        "sp_cvgroup_entry": _("Cultivar group"),
        "sp_cvepithet_entry": _(
            'Cultivar name without quotes. Use "cv." to '
            "to specify an unknown cultivar"
        ),
        "sp_tradename_entry": _(
            "The trade name - if different from the cultivar name"
        ),
        "expand_cv_btn": _("Show/hide extra parts."),
        "sp_spqual_combo": _("Species qualifier"),
        "sp_dist_add_button": _("Add a WGSRPD distribution unit"),
        "sp_dist_remove_button": _("Remove a WGSRPD distribution unit"),
        "sp_dist_menu_btn": _(
            "Extra distribution actions menu.  (Consolidate "
            "attempts to replace children levels with a "
            "parent level if all its children exist.)"
        ),
        "sp_vern_frame": _("Vernacular names"),
        "syn_frame": _(
            "Species synonyms, only species that are not "
            "already synonyms can be selected (can removed them "
            "first).  If a species is selected that already has "
            "synonyms then all its synonyms will be moved here. "
            "\n(NOTE: blue entries have not been committed to "
            "the database yet and will be only when OK is "
            "clicked.)"
        ),
        "sp_label_dist_entry": _(
            "The distribution as plain text.  Intended "
            "for use on labels and other reports."
        ),
        "label_markup_expander": _(
            "Alternative species name markup. Intended "
            "for use on labels and other reports where "
            "the default markup may need to be "
            "abbreviated or otherwise altered. NOTE: "
            "setting this equivalent to the default "
            "will not save (displaying as blue text). "
            "Also, changing any part of the species "
            "name will reset it."
        ),
        "sp_habit_comboentry": _("The habit of this species"),
        "sp_awards_entry": _("The awards this species have been given"),
        "sp_cancel_button": _("Cancel your changes"),
        "sp_ok_button": _("Save your changes"),
        "sp_ok_and_add_button": _(
            "Save your changes and add an accession to this species"
        ),
        "sp_next_button": _("Save your changes and add another species "),
        "add_syn_chkbox": _(
            "Create a copy of the previous taxonomic name and "
            "attach it as a synonym of this species."
        ),
        "infrasp_grid": _(
            "Infraspecific parts should be added in order of "
            "rank. i.e. as they apear in the drop down."
        ),
    }

    def __init__(self, parent=None):
        """
        :param parent: the parent window
        """
        filename = os.path.join(
            paths.lib_dir(), "plugins", "plants", "species_editor.glade"
        )
        super().__init__(
            filename, parent=parent, root_widget_name="species_dialog"
        )
        self.attach_completion(
            "sp_genus_entry",
            cell_data_func=genus_cell_data_func,
            match_func=genus_match_func,
        )
        self.attach_completion(
            "syn_entry",
            cell_data_func=species_cell_data_func,
            match_func=species_match_func,
        )
        self.attach_completion("subgenus_entry")
        self.attach_completion("section_entry")
        self.attach_completion("subsection_entry")
        self.attach_completion("series_entry")
        self.attach_completion("subseries_entry")
        self.set_accept_buttons_sensitive(False)
        self.widgets.notebook.set_current_page(0)
        self.boxes = set()

    def get_window(self):
        """
        Returns the top level window or dialog.
        """
        return self.widgets.species_dialog

    def set_accept_buttons_sensitive(self, sensitive):
        """set the sensitivity of all the accept/ok buttons for the editor
        dialog
        """
        self.widgets.sp_ok_button.set_sensitive(sensitive)
        self.widgets.sp_ok_and_add_button.set_sensitive(sensitive)
        self.widgets.sp_next_button.set_sensitive(sensitive)


class SpeciesEditor(editor.GenericModelViewPresenterEditor):
    # these have to correspond to the response values in the view
    RESPONSE_OK_AND_ADD = 11
    RESPONSE_NEXT = 22
    ok_responses = (RESPONSE_OK_AND_ADD, RESPONSE_NEXT)

    def __init__(self, model=None, parent=None, is_dependent_window=False):
        """
        :param model: a species instance or None
        :param parent: the parent window or None
        """
        if model is None:
            model = Species()
        super().__init__(model, parent)
        if not parent and bauble.gui:
            parent = bauble.gui.window
        self.parent = parent
        self._committed = []

        view = SpeciesEditorView(parent=self.parent)
        self.presenter = SpeciesEditorPresenter(self.model, view)
        self.presenter.set_visible_buttons(not is_dependent_window)

        # set default focus
        if self.model.genus is None:
            view.widgets.sp_genus_entry.grab_focus()
        else:
            view.widgets.sp_species_entry.grab_focus()

    def handle_response(self, response):
        """
        :return: return True if the editor is ready to be closed, False if
        we want to keep editing, if any changes are committed they are stored
        in self._committed
        """
        # TODO: need to do a __cleanup_model before the commit to do things
        # like remove the insfraspecific information that's attached to the
        # model if the infraspecific rank is None
        not_ok_msg = "Are you sure you want to lose your changes?"
        if response == Gtk.ResponseType.OK or response in self.ok_responses:
            try:
                if self.presenter.is_dirty():
                    self.commit_changes()
                    self._committed.append(self.model)
            except DBAPIError as e:
                msg = _("Error committing changes.\n\n%s") % utils.xml_safe(
                    e.orig
                )
                logger.debug(traceback.format_exc())
                utils.message_details_dialog(
                    msg, str(e), Gtk.MessageType.ERROR
                )
                return False
            except Exception as e:
                msg = _(
                    "Unknown error when committing changes. See the "
                    "details for more information.\n\n%s"
                ) % utils.xml_safe(e)
                logger.debug(traceback.format_exc())
                utils.message_details_dialog(
                    msg, traceback.format_exc(), Gtk.MessageType.ERROR
                )
                return False
        elif (
            self.presenter.is_dirty()
            and utils.yes_no_dialog(not_ok_msg)
            or not self.presenter.is_dirty()
        ):
            self.session.rollback()
            self.presenter.view.close_boxes()
            return True
        else:
            return False

        more_committed = None
        if response == self.RESPONSE_NEXT:
            self.presenter.cleanup()
            sp_editor = SpeciesEditor(
                Species(genus=self.model.genus), self.parent
            )
            more_committed = sp_editor.start()
        elif response == self.RESPONSE_OK_AND_ADD:
            from ..garden.accession import Accession
            from ..garden.accession import AccessionEditor

            acc_editor = AccessionEditor(
                Accession(species=self.model), parent=self.parent
            )
            more_committed = acc_editor.start()

        if more_committed is not None:
            if isinstance(more_committed, list):
                self._committed.extend(more_committed)
            else:
                self._committed.append(more_committed)

        self.presenter.view.close_boxes()
        return True

    def commit_changes(self):
        # remove incomplete vernacular names
        for vernacular in self.model.vernacular_names:
            if vernacular.name in (None, ""):
                self.model.vernacular_names.remove(vernacular)
                utils.delete_or_expunge(vernacular)
                del vernacular
        super().commit_changes()
        if self.presenter.view.widgets.add_syn_chkbox.get_active():
            # second commit so history is placed last - sync could fail unique
            # constraint on full_sci_name otherwise
            syn = Species(**self.presenter.start_sp_dict)
            self.model.synonyms.append(syn)
            super().commit_changes()

    def start(self):
        if self.session.query(Genus).count() == 0:
            msg = _(
                "You must first add or import at least one genus into the "
                "database before you can add species."
            )
            utils.message_dialog(msg)
            return None

        while True:
            response = self.presenter.start()
            if self.handle_response(response):
                break

        self.presenter.cleanup()
        self.session.close()  # cleanup session
        return self._committed


def edit_species(model=None, parent_view=None, is_dependent_window=False):
    sp_editor = SpeciesEditor(model, parent_view, is_dependent_window)
    sp_editor.start()
    result = sp_editor._committed
    del sp_editor
    return result
