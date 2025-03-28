# Copyright 2008-2010 Brett Adams
# Copyright 2012-2015 Mario Frasca <mario@anche.no>.
# Copyright 2017 Jardín Botánico de Quito
# Copyright 2020-2023 Ross Demuth <rossdemuth123@gmail.com>
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
#
"""
Species modules
"""

import logging
import os
import re
import traceback
import typing
from ast import literal_eval

logger = logging.getLogger(__name__)

from gi.repository import Gtk
from gi.repository import Pango
from pyparsing import ParseResults
from pyparsing import Regex
from pyparsing import Word
from pyparsing import srange
from sqlalchemy import or_
from sqlalchemy.orm import Query
from sqlalchemy.orm import Session
from sqlalchemy.orm.session import object_session

import bauble
from bauble import db
from bauble import paths
from bauble import pluginmgr
from bauble import prefs
from bauble import utils
from bauble import view
from bauble.i18n import _
from bauble.search.search import result_cache
from bauble.search.statements import StatementAction
from bauble.search.strategies import SearchStrategy
from bauble.view import Action
from bauble.view import InfoBox
from bauble.view import InfoBoxPage
from bauble.view import InfoExpander
from bauble.view import PropertiesExpander
from bauble.view import select_in_search_results

from .family import Family
from .family import FamilySynonym
from .genus import Genus
from .genus import GenusSynonym
from .geography import DistMapInfoExpanderMixin
from .geography import map_kml_callback
from .species_editor import SPECIES_WEB_BUTTON_DEFS_PREFS
from .species_editor import SpeciesDistribution
from .species_editor import SpeciesEditor
from .species_editor import SpeciesEditorPresenter
from .species_editor import SpeciesEditorView
from .species_editor import edit_species
from .species_model import DefaultVernacularName
from .species_model import Species
from .species_model import SpeciesNote
from .species_model import SpeciesSynonym
from .species_model import VernacularName
from .species_model import red_list_values

# imported by clients of this modules
__all__ = [
    "SpeciesDistribution",
    "SpeciesEditorPresenter",
    "SpeciesEditorView",
    "SpeciesEditor",
    "edit_species",
    "DefaultVernacularName",
    "SpeciesNote",
]

# TODO: we need to make sure that this will still work if the
# AccessionPlugin is not present, this means that we would have to
# change the species context menu, getting the children from the
# search view and what else


def edit_callback(values):
    sp = values[0]
    if isinstance(sp, VernacularName):
        sp = sp.species
    return edit_species(model=sp) is not None


def remove_callback(values):
    """
    The callback function to remove a species from the species context menu.
    """
    from bauble.plugins.garden.accession import Accession

    species = values[0]
    s_lst = []
    session = object_session(species)
    for species in values:
        if isinstance(species, VernacularName):
            species = species.species
        nacc = (
            session.query(Accession).filter_by(species_id=species.id).count()
        )
        safe_str = utils.xml_safe(str(species))
        s_lst.append(safe_str)
        if nacc > 0:
            msg = _(
                "The species <i>%(1)s</i> has %(2)s accessions." "\n\n"
            ) % {"1": safe_str, "2": nacc} + _(
                "You cannot remove a species with accessions."
            )
            utils.message_dialog(msg, typ=Gtk.MessageType.WARNING)
            return False
    msg = _(
        "Are you sure you want to remove the following species <i>%s</i>?"
    ) % ", ".join(i for i in s_lst)
    if not utils.yes_no_dialog(msg):
        return False
    for species in values:
        session.delete(species)
    try:
        utils.remove_from_results_view(values)
        session.commit()
    except Exception as e:  # pylint: disable=broad-except
        msg = _("Could not delete.\n\n%s") % utils.xml_safe(e)
        utils.message_details_dialog(
            msg, traceback.format_exc(), Gtk.MessageType.ERROR
        )
        session.rollback()
    return True


def add_accession_callback(values):
    from bauble.plugins.garden.accession import Accession
    from bauble.plugins.garden.accession import AccessionEditor

    session = db.Session()
    species = session.merge(values[0])
    if isinstance(species, VernacularName):
        species = species.species
    e = AccessionEditor(model=Accession(species=species))
    session.close()
    return e.start() is not None


edit_action = Action(
    "species_edit", _("_Edit"), callback=edit_callback, accelerator="<ctrl>e"
)
add_accession_action = Action(
    "species_acc_add",
    _("_Add accession"),
    callback=add_accession_callback,
    accelerator="<ctrl>k",
)
remove_action = Action(
    "species_remove",
    _("_Delete"),
    callback=remove_callback,
    accelerator="<ctrl>Delete",
    multiselect=True,
)

distribution_map_action = Action(
    "acc_dist_map",
    _("Show distribution in _map"),
    callback=map_kml_callback,
    accelerator="<ctrl>m",
    multiselect=True,
)

species_context_menu = [edit_action, remove_action, distribution_map_action]

vernname_context_menu = [edit_action]


def on_taxa_clicked(_label, _event, taxon):
    """Function intended for use with :func:`utils.make_label_clickable`

    if the return_accepted_pref is set True then select both the name synonym
    clicked on and its accepted name.
    """
    if prefs.prefs.get(prefs.return_accepted_pref) and taxon.accepted:
        select_in_search_results(taxon.accepted)
    select_in_search_results(taxon)


class BinomialStatement(StatementAction):
    """Generates species queries searching by `Genus species` partial matches.

    Partial or complete cultivar names are also matched if started with a '
    """

    def __init__(self, tokens: ParseResults) -> None:
        logger.debug("%s::__init__(%s)", self.__class__.__name__, tokens)
        self.genus_epithet: str = tokens[0]
        self.species_epithet: None | str
        self.cultivar_epithet: None | str
        if tokens[1].startswith("'"):
            self.cultivar_epithet = tokens[1].strip("'")
            self.species_epithet = None
        else:
            self.species_epithet = tokens[1]
            self.cultivar_epithet = (
                None if len(tokens) == 2 else tokens[2].strip("'")
            )

    def __repr__(self) -> str:
        if self.species_epithet:
            return f"{self.genus_epithet} {self.species_epithet}"
        return f"{self.genus_epithet} {self.cultivar_epithet}"

    def invoke(self, search_strategy: SearchStrategy) -> list[Query]:
        logger.debug("%s::invoke", self.__class__.__name__)
        logger.debug(
            "binomial search gen: %s, sp: %s, cv: %s",
            self.genus_epithet,
            self.species_epithet,
            self.cultivar_epithet,
        )
        query = (
            search_strategy.session.query(Species)
            .join(Genus)
            .filter(Genus.genus.startswith(self.genus_epithet))
        )

        if self.species_epithet:
            query = query.filter(Species.sp.startswith(self.species_epithet))
        if self.cultivar_epithet:
            query = query.filter(
                or_(
                    Species.cultivar_epithet.startswith(self.cultivar_epithet),
                    Species.trade_name.startswith(self.cultivar_epithet),
                )
            )
        return [query]


_BINOMIAL_RGX = re.compile(
    "^[A-Z]+[a-z-]* +([a-z]+[a-z-]*$|'[A-Za-z0-9-]*$|'[A-Za-z0-9- ]*'$|"
    "[a-z]+[a-z-]* ('[A-Za-z0-9-]*$|'[A-Za-z0-9- ]*'$))"
)


class BinomialSearch(SearchStrategy):
    """Supports a query of the form: `<Genus> <species|'Cultivar(')>`

    e.g.: `Loma hys`
    """

    caps = srange("[A-Z]")
    lowers = caps.lower() + "-"

    genus = Word(caps, lowers).set_name("Genus epithet or partial epithet")
    species = Word(lowers).set_name("species epithet or partial epithet")
    cultivar = Regex("'[A-Za-z0-9- ]*'?").set_name(
        "cultivar epithet or partial epithet"
    )

    statement = (
        (genus + species + cultivar | genus + species | genus + cultivar)
    ).set_parse_action(BinomialStatement)("statement")

    @staticmethod
    def use(text: str) -> typing.Literal["include", "exclude", "only"]:
        logger.debug("Use called with %s", text)
        if _BINOMIAL_RGX.match(text):
            logger.debug("including BinomialSearch in strategies")
            return "include"
        return "exclude"

    def search(self, text: str, session: Session) -> list[Query]:
        """Search for a synonym for each item in the results and add to the
        results
        """
        super().search(text, session)
        self.session = session
        statement = self.statement.parse_string(text).statement
        logger.debug("statement : %s(%s)", type(statement), statement)
        queries = statement.invoke(self)

        return queries


def get_binomial_completions(text: str) -> set[str]:
    parts = text.split()
    sp_part = ""
    cv_part = ""

    if not db.Session:
        return set()

    with db.Session() as session:
        epithets = (
            session.query(
                Genus.epithet,
                Species.epithet,
                Species.cultivar_epithet,
                Species.trade_name,
            )
            .join(Genus)
            .filter(Genus.epithet.startswith(parts[0]))
        )
        if len(parts) == 2:
            if parts[1].startswith("'"):
                cv_part = parts[1][1:]
                epithets = epithets.filter(
                    or_(
                        Species.cultivar_epithet.startswith(cv_part),
                        Species.trade_name.startswith(cv_part),
                    )
                )
            else:
                sp_part = parts[1]
                epithets = epithets.filter(Species.epithet.startswith(sp_part))
        elif len(parts) == 3:
            sp_part = parts[1]
            epithets = epithets.filter(Species.epithet.startswith(sp_part))
            if parts[2].startswith("'"):
                cv_part = parts[2][1:]
                epithets = epithets.filter(
                    or_(
                        Species.cultivar_epithet.startswith(cv_part),
                        Species.trade_name.startswith(cv_part),
                    )
                )

    binomial_completions = set()
    for gen, sp, cv, trade_name in epithets.limit(10):
        string = f"{gen}"
        if sp and (sp_part or not cv_part):
            string += f"{' ' + sp.split()[0] if sp else ''}"
            if not cv_part:
                binomial_completions.add(string)
        if cv and cv.startswith(cv_part):
            cv_string = string + f" '{cv}'"
            binomial_completions.add(cv_string)
        if trade_name and trade_name.startswith(cv_part):
            t_string = string + f" '{trade_name}'"
            binomial_completions.add(t_string)

    return binomial_completions


class SynonymSearch(SearchStrategy):
    """Adds queries that will return the accepted names for any synonyms that
    previous strategies may have returned.

    This strategy should run last as it reuses the results from previous
    strategies.

    'bauble.search.return_accepted' pref key is used to enable/disable this
    strategy.
    """

    excludes_value_list_search = False

    def __init__(self) -> None:
        super().__init__()
        if prefs.return_accepted_pref not in prefs.prefs:
            prefs.prefs[prefs.return_accepted_pref] = True
            prefs.prefs.save()

    @staticmethod
    def use(_text: str) -> typing.Literal["include", "exclude", "only"]:
        if prefs.prefs.get(prefs.return_accepted_pref):
            logger.debug("including SynonymSearch in strategies")
            return "include"
        return "exclude"

    @staticmethod
    def get_ids(
        results: set[Query],
    ) -> dict[tuple[type[db.Base], type[db.Base]], set[int]]:
        """Colate IDs and models to search for each result type."""
        ids: dict[tuple[type[db.Base], type[db.Base]], set[int]] = {}
        for result in results:
            models: tuple[type[db.Base], type[db.Base]] | None = None
            id_ = None
            if isinstance(result, Species):
                models = (Species, SpeciesSynonym)
                id_ = result.id
            elif isinstance(result, Genus):
                models = (Genus, GenusSynonym)
                id_ = result.id
            elif isinstance(result, Family):
                models = (Family, FamilySynonym)
                id_ = result.id
            elif isinstance(result, VernacularName):
                models = (VernacularName, SpeciesSynonym)
                id_ = result.species.id  # type: ignore[attr-defined]
            if models and id_:
                ids.setdefault(models, set()).add(id_)
        return ids

    def search(self, text: str, session: Session) -> list[Query]:
        """Returns queries that will return the accepted names for items
        currently in results.

        NOTE: the value of text is not used.
        """
        super().search(text, session)
        if not prefs.prefs.get(prefs.return_accepted_pref):
            # filter should prevent us getting here.
            return []
        results = set()
        for result in result_cache.values():
            results.update(result)
        if not results:
            return []
        ids = self.get_ids(results)
        if not ids:
            return []
        queries = []
        for models, id_set in ids.items():
            # vernacular names are a special case.  Only returning if both
            # accepted and synonym have a VernacularName entry.
            if models[0] == VernacularName:
                syn_model_id = getattr(models[1], "species_id")
                syn_id = getattr(models[1], "synonym_id")
                # pylint: disable=line-too-long
                query = (
                    session.query(models[0])
                    .join(Species)
                    .join(SpeciesSynonym, syn_model_id == Species.id)
                    .filter(syn_id.in_(id_set))
                )
            else:
                id_ = getattr(models[0], "id")
                syn_model_id = getattr(
                    models[1], models[0].__tablename__ + "_id"
                )
                syn_id = getattr(models[1], "synonym_id")
                query = (
                    session.query(models[0])
                    .join(models[1], syn_model_id == id_)
                    .filter(syn_id.in_(id_set))
                )
            if (
                prefs.prefs.get(prefs.exclude_inactive_pref)
                and hasattr(models[0], "active")
                and hasattr(models[1], "synonym")
            ):
                query = query.filter(
                    or_(
                        models[0].active.is_(True),
                        models[1].synonym.has(active=True),
                    )
                )

            queries.append(query)
        return queries


# TODO should these and even the InfoBoxPage be Gtk.Template?
class VernacularExpander(InfoExpander):
    """VernacularExpander

    :param widgets:
    """

    EXPANDED_PREF = "infobox.species_vernacular_expanded"

    def __init__(self, widgets):
        super().__init__(_("Vernacular names"), widgets)
        vernacular_box = self.widgets.sp_vernacular_box
        self.widgets.remove_parent(vernacular_box)
        self.vbox.pack_start(vernacular_box, True, True, 0)
        self.display_widgets = [vernacular_box]

    def update(self, row):
        """update the expander

        :param row: the row to get the values from
        """
        self.reset()
        if row.vernacular_names:
            self.unhide_widgets()
            names = []
            for vernacular in row.vernacular_names:
                if (
                    row.default_vernacular_name is not None
                    and vernacular == row.default_vernacular_name
                ):
                    names.insert(
                        0,
                        f"{vernacular.name} - {vernacular.language} (default)",
                    )
                else:
                    names.append(f"{vernacular.name} - {vernacular.language}")
            self.widget_set_value("sp_vernacular_data", "\n".join(names))
            self.set_sensitive(True)


class SynonymsExpander(InfoExpander):
    EXPANDED_PREF = "infobox.species_synonyms_expanded"

    def __init__(self, widgets):
        super().__init__(_("Synonyms"), widgets)
        synonyms_box = self.widgets.sp_synonyms_box
        self.widgets.remove_parent(synonyms_box)
        self.vbox.pack_start(synonyms_box, True, True, 0)

    def update(self, row):
        """Update the expander

        :param row: the row to get the values from
        """
        self.reset()
        syn_box = self.widgets.sp_synonyms_box
        # remove old labels
        syn_box.foreach(syn_box.remove)
        logger.debug(row.synonyms)
        self.set_label(_("Synonyms"))  # reset default value
        on_label_clicked = utils.generate_on_clicked(select_in_search_results)
        if row.accepted is not None:
            self.set_label(_("Accepted name"))
            # create clickable label that will select the synonym
            # in the search results
            box = Gtk.EventBox()
            label = Gtk.Label()
            label.set_xalign(0.0)
            label.set_yalign(0.5)
            label.set_markup(row.accepted.str(markup=True, authors=True))
            box.add(label)
            utils.make_label_clickable(label, on_label_clicked, row.accepted)
            syn_box.pack_start(box, False, False, 0)
            self.show_all()
            self.set_sensitive(True)
        elif row.synonyms:
            for syn in sorted(row.synonyms, key=str):
                # create clickable label that will select the synonym
                # in the search results
                box = Gtk.EventBox()
                label = Gtk.Label()
                label.set_xalign(0.0)
                label.set_yalign(0.5)
                label.set_markup(syn.str(markup=True, authors=True))
                box.add(label)
                utils.make_label_clickable(label, on_label_clicked, syn)
                syn_box.pack_start(box, False, False, 0)
            self.show_all()
            self.set_sensitive(True)


class GeneralSpeciesExpander(DistMapInfoExpanderMixin, InfoExpander):
    """expander to present general information about a species"""

    AREAS_EXPANDED_PREF = "infobox.species_geo_areas_expanded"

    custom_columns: set[str] = set()
    current_db: int | None = None

    def __init__(self, widgets):
        super().__init__(_("General"), widgets)
        general_box = self.widgets.sp_general_box
        self.widgets.remove_parent(general_box)
        self.vbox.pack_start(general_box, True, True, 0)
        # wrapping the species but not the genus looks odd, better to ellipsize
        self.widgets.sp_epithet_data.set_ellipsize(Pango.EllipsizeMode.END)

        self.current_obj = None

        def on_nacc_clicked(*_args):
            cmd = f"accession where species.id={self.current_obj.id}"
            bauble.gui.send_command(cmd)

        utils.make_label_clickable(self.widgets.sp_nacc_data, on_nacc_clicked)

        def on_nplants_clicked(*_args):
            cmd = f"plant where accession.species.id={self.current_obj.id}"
            bauble.gui.send_command(cmd)

        utils.make_label_clickable(
            self.widgets.sp_nplants_data, on_nplants_clicked
        )

        self._setup_custom_column("_sp_custom1")
        self._setup_custom_column("_sp_custom2")

    @staticmethod
    def on_areas_expanded(expander: Gtk.Expander) -> None:
        prefs.prefs[GeneralSpeciesExpander.AREAS_EXPANDED_PREF] = (
            not expander.get_expanded()
        )

    @staticmethod
    def select_all_areas(_label, _event, row: Species) -> None:
        for dist in row.distribution:
            select_in_search_results(dist.geography)

    def _setup_custom_column(self, column_name):
        self.__class__.current_db = id(db.engine.url)
        session = bauble.db.Session()
        custom_meta = (
            session.query(bauble.meta.BaubleMeta)
            .filter(bauble.meta.BaubleMeta.name == column_name)
            .first()
        )
        session.close()
        # pylint: disable=protected-access
        if custom_meta:
            self.__class__.custom_columns.add(column_name)
            custom_meta = literal_eval(custom_meta.value)
            display_name = custom_meta.get("display_name")
            if display_name:
                label = self.widgets[column_name + "_label"]
                label.set_text(display_name + ":")
                data_label = self.widgets[column_name + "_data"]
                utils.unhide_widgets((label, data_label))
        else:
            for col in self.custom_columns:
                label = self.widgets[col + "_label"]
                data_label = self.widgets[col + "_data"]
                utils.hide_widgets((label, data_label))
            self.__class__.custom_columns = set()

    def update(self, row):
        """update the expander

        :param row: the row to get the values from
        """
        self.zoomed = False
        self.zoom_level = 1
        # In case of connection change
        if self.current_db != id(db.engine.url):
            self._setup_custom_column("_sp_custom1")
            self._setup_custom_column("_sp_custom2")

        if (
            row.subgenus
            or row.section
            or row.subsection
            or row.series
            or row.subseries
        ):
            utils.unhide_widgets([self.widgets.sp_details_box])
            self.widget_set_value(
                "sp_gen_detail",
                f"<i>{utils.xml_safe(row.genus)}</i>",
                markup=True,
            )
        else:
            utils.hide_widgets([self.widgets.sp_details_box])
        details = (
            ("subg.", "sp_subgen_detail", "subgenus"),
            ("sect.", "sp_section_detail", "section"),
            ("subsect.", "sp_subsection_detail", "subsection"),
            ("ser.", "sp_series_detail", "series"),
            ("subser.", "sp_subseries_detail", "subseries"),
        )
        on_clicked_search = utils.generate_on_clicked(bauble.gui.send_command)
        step = 0
        for abv, widget_name, attr in details:
            widget = self.widgets[widget_name]
            value = getattr(row, attr)
            if value:
                step += 12
                utils.unhide_widgets([widget])
                widget.set_margin_start(step)
                self.widget_set_value(
                    widget_name,
                    f"<small>{abv} <i>{utils.xml_safe(value)}</i></small>",
                    markup=True,
                )
                utils.make_label_clickable(
                    widget,
                    on_clicked_search,
                    f"species where {attr} = {value}",
                )
            else:
                utils.hide_widgets([widget])

        self.current_obj = row
        session = object_session(row)
        # Link to family
        self.widget_set_value(
            "sp_fam_data",
            f"<small>({row.genus.family.family})</small>",
            markup=True,
        )
        utils.make_label_clickable(
            self.widgets.sp_fam_data, on_taxa_clicked, row.genus.family
        )
        genus = row.genus.markup()
        self.widget_set_value(
            "sp_gen_data", f"<big>{genus}</big>", markup=True
        )
        utils.make_label_clickable(
            self.widgets.sp_gen_data, on_taxa_clicked, row.genus
        )
        # epithet (full binomial but missing genus)
        self.widget_set_value(
            "sp_epithet_data",
            f" <big>{row.markup(authors=True, genus=False)}</big>",
            markup=True,
        )

        awards = ""
        if row.awards:
            awards = utils.nstr(row.awards)
        self.widget_set_value("sp_awards_data", awards)

        self.widget_set_value("sp_cites_data", row.cites or "")

        self.widget_set_value(
            "sp_red_list_data", red_list_values[row.red_list]
        )

        # zone = ''
        # if row.hardiness_zone:
        #     awards = utils.nstr(row.hardiness_zone)
        # self.widget_set_value('sp_hardiness_data', zone)

        habit = ""
        if row.habit:
            habit = utils.nstr(row.habit)
        self.widget_set_value("sp_habit_data", habit)

        for child in self.widgets.dist_map_box.get_children():
            self.widgets.dist_map_box.remove(child)
        on_clicked = utils.generate_on_clicked(select_in_search_results)
        self.distribution_map = None
        if row.distribution:
            map_event_box = Gtk.EventBox()
            self.distribution_map = row.distribution_map()
            image = self.distribution_map.as_image()
            map_event_box.add(image)
            map_event_box.connect(
                "button_release_event", self.on_map_button_release
            )
            self.widgets.dist_map_box.pack_start(
                map_event_box, False, False, 0
            )
            expander = Gtk.Expander(label=_("Areas"), expanded=False)

            expander.connect("activate", self.on_areas_expanded)
            expander.set_expanded(
                prefs.prefs.get(self.AREAS_EXPANDED_PREF, False)
            )
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            for place in row.distribution:
                event_box = Gtk.EventBox()
                label = Gtk.Label(label=utils.nstr(place))
                label.set_halign(Gtk.Align.START)
                event_box.add(label)

                utils.make_label_clickable(label, on_clicked, place.geography)
                box.pack_start(event_box, False, False, 0)
            event_box = Gtk.EventBox()
            label = Gtk.Label(label="...select all")
            label.set_halign(Gtk.Align.START)
            event_box.add(label)

            utils.make_label_clickable(label, self.select_all_areas, row)
            box.pack_start(event_box, False, False, 0)
            expander.add(box)
            self.widgets.dist_map_box.pack_start(expander, False, False, 0)
            self.widgets.dist_map_box.show_all()

        dist = ""
        if row.label_distribution:
            dist = row.label_distribution
        self.widget_set_value("sp_labeldist_data", dist)

        # stop here if not GardenPluin
        if "GardenPlugin" not in pluginmgr.plugins:
            return

        from bauble.plugins.garden.accession import Accession
        from bauble.plugins.garden.plant import Plant

        nacc = (
            session.query(Accession)
            .join("species")
            .filter_by(id=row.id)
            .count()
        )
        self.widget_set_value("sp_nacc_data", nacc)

        nplants = (
            session.query(Plant)
            .join("accession", "species")
            .filter_by(id=row.id)
            .count()
        )
        if nplants == 0:
            self.widget_set_value("sp_nplants_data", nplants)
        else:
            nacc_in_plants = (
                session.query(Plant.accession_id)
                .join("accession", "species")
                .filter_by(id=row.id)
                .distinct()
                .count()
            )
            self.widget_set_value(
                "sp_nplants_data", f"{nplants} in {nacc_in_plants} accessions"
            )

        living_plants = sum(
            i.quantity
            for i in session.query(Plant)
            .join("accession", "species")
            .filter_by(id=row.id)
            .all()
        )
        self.widget_set_value("living_plants_count", living_plants)

        for column in self.custom_columns:
            self.widget_set_value(column + "_data", getattr(row, column))


class SpeciesInfoBox(InfoBox):
    def __init__(self):
        super().__init__()
        page = SpeciesInfoPage()
        label = page.label
        if isinstance(label, str):
            label = Gtk.Label(label=label)
        self.insert_page(page, label, 0)


class SpeciesInfoPage(InfoBoxPage):
    """general info, fullname, common name, num of accessions and clones,
    distribution
    """

    # others to consider: reference, images, redlist status

    def __init__(self):
        button_defs = []
        buttons = prefs.prefs.itersection(SPECIES_WEB_BUTTON_DEFS_PREFS)
        for name, button in buttons:
            button["name"] = name
            button_defs.append(button)

        super().__init__()
        filename = os.path.join(
            paths.lib_dir(), "plugins", "plants", "infoboxes.glade"
        )
        # load the widgets directly instead of using load_widgets()
        # because the caching that load_widgets() does can mess up
        # displaying the SpeciesInfoBox sometimes if you try to show
        # the infobox while having a vernacular names selected in
        # the search results and then a species name
        self.widgets = utils.BuilderWidgets(filename)
        self.general = GeneralSpeciesExpander(self.widgets)
        self.add_expander(self.general)
        self.vernacular = VernacularExpander(self.widgets)
        self.add_expander(self.vernacular)
        self.synonyms = SynonymsExpander(self.widgets)
        self.add_expander(self.synonyms)
        self.links = view.LinksExpander("notes", links=button_defs)
        self.add_expander(self.links)
        self.props = PropertiesExpander()
        self.add_expander(self.props)
        self.label = _("General")

        if "GardenPlugin" not in pluginmgr.plugins:
            self.widgets.remove_parent("sp_nacc_label")
            self.widgets.remove_parent("sp_nacc_data")
            self.widgets.remove_parent("sp_nplants_label")
            self.widgets.remove_parent("sp_nplants_data")

    def update(self, row):
        """
        update the expanders in this infobox

        :param row: the row to get the values from
        """
        self.general.update(row)
        self.vernacular.update(row)
        self.synonyms.update(row)
        self.links.update(row)
        self.props.update(row)


# it's easier just to put this here instead of playing around with imports
class VernacularNameInfoBox(SpeciesInfoBox):
    def update(self, row):
        logger.debug(
            "VernacularNameInfoBox.update %s(%s)", row.__class__.__name__, row
        )
        if isinstance(row, VernacularName):
            super().update(row.species)
