# Copyright 2008-2010 Brett Adams
# Copyright 2012-2015 Mario Frasca <mario@anche.no>.
# Copyright 2017 Jardín Botánico de Quito
# Copyright 2020-2025 Ross Demuth <rossdemuth123@gmail.com>
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

logger = logging.getLogger(__name__)

import re
from ast import literal_eval
from pathlib import Path
from typing import cast

from gi.repository import Gdk
from gi.repository import Gtk
from pyparsing import ParseResults
from pyparsing import Regex
from pyparsing import Word
from pyparsing import srange
from sqlalchemy import and_
from sqlalchemy import distinct
from sqlalchemy import func
from sqlalchemy import or_
from sqlalchemy import select
from sqlalchemy.orm import Query
from sqlalchemy.orm import Session
from sqlalchemy.orm.session import object_session

import bauble
from bauble import db
from bauble import prefs
from bauble import utils
from bauble.i18n import _
from bauble.search.search import result_cache
from bauble.search.statements import StatementAction
from bauble.search.strategies import SearchStrategy
from bauble.search.strategies import UseStrategy
from bauble.ui.views import InfoBox
from bauble.ui.views import InfoExpander
from bauble.ui.views import LinksExpander
from bauble.ui.views import PropertiesExpander
from bauble.ui.views import on_clicked_search
from bauble.ui.views import on_clicked_select
from bauble.ui.views import select_in_search_results

from .family import Family
from .family import FamilySynonym
from .genus import Genus
from .genus import GenusSynonym
from .geography import DistributionMapEventBox
from .species_model import DefaultVernacularName
from .species_model import Species
from .species_model import SpeciesDistribution
from .species_model import SpeciesNote
from .species_model import SpeciesSynonym
from .species_model import VernacularName
from .species_model import red_list_values
from .ui.species_editor import SPECIES_WEB_BUTTON_DEFS_PREFS
from .ui.widgets import SynonymsExpander

# imported by clients of this modules
__all__ = [
    "SpeciesDistribution",
    "DefaultVernacularName",
    "SpeciesNote",
]


def on_taxa_clicked(
    _label: Gtk.Label,
    _event: Gdk.Event,
    taxon: Genus | Family | Species,
) -> None:
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
        self.genus_epithet: str = tokens.genus
        self.species_epithet: None | str = tokens.species or None
        self.cultivar_epithet: None | str
        if tokens.cultivar == "'":
            self.cultivar_epithet = tokens.cultivar
        else:
            self.cultivar_epithet = tokens.cultivar.strip("'") or None

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
            if self.cultivar_epithet == "'":
                query = query.filter(
                    or_(
                        Species.cultivar_epithet.is_not(None),
                        Species.trade_name.is_not(None),
                    )
                )
            else:
                query = query.filter(
                    or_(
                        Species.cultivar_epithet.startswith(
                            self.cultivar_epithet
                        ),
                        Species.trade_name.startswith(self.cultivar_epithet),
                    )
                )
        return [query]


_BINOMIAL_RGX = re.compile(
    r"^[A-Z]+[a-z-]* +([a-z]+\.$|[a-z]+[a-z-]*$|'[A-Za-z0-9-]*$|"
    r"'[A-Za-z0-9- ]*'$|[a-z]+[a-z-]* ('[A-Za-z0-9-]*$|'[A-Za-z0-9- ]*'$))"
)


class BinomialSearch(SearchStrategy):
    """Supports a query of the form: `<Genus> <species|'Cultivar(')>`

    e.g.: `Loma hys`
    """

    caps = srange("[A-Z]")
    lowers = caps.lower() + "-"

    genus = Word(caps, lowers)("genus")
    genus.set_name("Genus epithet or partial epithet")

    species = Regex(r"[a-z-]+\.?")("species")
    species.set_name("species epithet or partial epithet")

    cultivar = Regex("'[A-Za-z0-9- ]*'?")("cultivar")
    cultivar.set_name("cultivar epithet or partial epithet")

    statement = (
        (genus + species + cultivar | genus + species | genus + cultivar)
    ).set_parse_action(BinomialStatement)("statement")

    @staticmethod
    def use(text: str) -> UseStrategy:
        logger.debug("Use called with %s", text)
        if _BINOMIAL_RGX.match(text):
            logger.debug("including BinomialSearch in strategies")
            return UseStrategy.INCLUDE
        return UseStrategy.EXCLUDE

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

    with db.Session() as session:
        epithets = (
            session.query(
                Genus.epithet,
                Species.epithet,
                Species.cultivar_epithet,
                Species.trade_name,
            )
            .join(Genus)
            .filter(Genus.epithet.ilike(f"{parts[0]}%"))
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
    def use(_text: str) -> UseStrategy:
        if prefs.prefs.get(prefs.return_accepted_pref):
            logger.debug("including SynonymSearch in strategies")
            return UseStrategy.INCLUDE
        return UseStrategy.EXCLUDE

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
                id_ = result.species.id
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


class VernacularExpander(InfoExpander[Species], Gtk.Expander):
    DEFAULT_LBL = _("(default)")

    def __init__(self) -> None:
        super().__init__(label=_("Vernacular names"))
        self.connect("notify::expanded", self.on_expanded)
        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.box.set_border_width(5)
        self.add(self.box)

    def update(self, row: Species) -> None:
        self.set_sensitive(False)
        self.box.foreach(self.box.remove)

        names: list[tuple[str, str]] = []

        if row.vernacular_names:

            for vernacular in sorted(row.vernacular_names, key=str):
                language = ""

                if vernacular.language:
                    language = f" - {vernacular.language}"

                if (
                    row.default_vernacular_name is not None
                    and vernacular == row.default_vernacular_name
                ):
                    names.insert(
                        0,
                        (
                            vernacular.name or "",
                            f"{vernacular.name}{language} {self.DEFAULT_LBL}",
                        ),
                    )
                else:
                    names.append(
                        (vernacular.name or "", f"{vernacular.name}{language}")
                    )

            self.set_sensitive(True)

        for name, label_txt in names:
            ebox = Gtk.EventBox()
            label = Gtk.Label(
                label=label_txt,
                xalign=0.0,
                yalign=0.5,
            )
            ebox.add(label)
            utils.make_label_clickable(
                label,
                on_clicked_search,
                f"vernacular_name where name = '{name}'",
            )
            self.box.pack_start(ebox, False, False, 0)

        self.show_all()


def infobox_counts(id_: int) -> dict[str, int]:
    from ..garden import Accession
    from ..garden import Plant

    stmt = (
        select(
            func.count(distinct(Accession.id)),
            func.count(distinct(Plant.accession_id)),
            func.count(Plant.id),
            func.sum(Plant.quantity),
        )
        .select_from(Species)
        .outerjoin(Accession)
        .outerjoin(Plant)
        .where(Species.id == id_)
    )
    with db.engine.begin() as connection:
        counts = connection.execute(stmt).one()

    keys = (
        "accessions",
        "acc_w_plants",
        "plants",
        "living_plants",
    )

    return dict(zip(keys, counts, strict=True))


@Gtk.Template(
    filename=str(Path(__file__).resolve().parent / "species_expander.ui")
)
class GeneralSpeciesExpander(
    InfoExpander[Species],
    Gtk.Expander,
):
    """expander to present general information about a species"""

    __gtype_name__ = "GeneralSpeciesExpander"

    GEO_AREAS_EXPANDED_PREF = "infobox.species_geo_areas_expanded"

    general_box = cast(Gtk.Box, Gtk.Template.Child())
    details_box = cast(Gtk.Box, Gtk.Template.Child())
    details_gen_label = cast(Gtk.Label, Gtk.Template.Child())
    subgen_label = cast(Gtk.Label, Gtk.Template.Child())
    section_label = cast(Gtk.Label, Gtk.Template.Child())
    subsection_label = cast(Gtk.Label, Gtk.Template.Child())
    series_label = cast(Gtk.Label, Gtk.Template.Child())
    subseries_label = cast(Gtk.Label, Gtk.Template.Child())
    gen_label = cast(Gtk.Label, Gtk.Template.Child())
    name_label = cast(Gtk.Label, Gtk.Template.Child())
    fam_label = cast(Gtk.Label, Gtk.Template.Child())
    num_acc_label = cast(Gtk.Label, Gtk.Template.Child())
    num_plants_label = cast(Gtk.Label, Gtk.Template.Child())
    living_plants_label = cast(Gtk.Label, Gtk.Template.Child())
    plant_locations_box = cast(Gtk.Box, Gtk.Template.Child())
    cites_label = cast(Gtk.Label, Gtk.Template.Child())
    red_list_label = cast(Gtk.Label, Gtk.Template.Child())
    _sp_custom1_label = cast(Gtk.Label, Gtk.Template.Child())
    _sp_custom1_data_label = cast(Gtk.Label, Gtk.Template.Child())
    _sp_custom2_label = cast(Gtk.Label, Gtk.Template.Child())
    _sp_custom2_data_label = cast(Gtk.Label, Gtk.Template.Child())
    awards_label = cast(Gtk.Label, Gtk.Template.Child())
    habit_label = cast(Gtk.Label, Gtk.Template.Child())
    verifications_box = cast(Gtk.Box, Gtk.Template.Child())
    label_markup_label = cast(Gtk.Label, Gtk.Template.Child())
    label_markup_data_label = cast(Gtk.Label, Gtk.Template.Child())
    labeldist_label = cast(Gtk.Label, Gtk.Template.Child())
    dist_map_box = cast(Gtk.Box, Gtk.Template.Child())
    dist_details_box = cast(Gtk.Box, Gtk.Template.Child())

    def __init__(self) -> None:
        super().__init__(label=_("General"))
        self.connect("notify::expanded", self.on_expanded)
        self.has_details = False
        self.map_event_box = DistributionMapEventBox()
        self.dist_map_box.pack_start(self.map_event_box, False, False, 0)
        self._current_db_id: int | None = None
        self._custom_columns: set[str] = set()

    def _setup_custom_column(self, column_name: str) -> None:
        self._current_db_id = id(db.engine.url)
        with db.Session() as session:
            custom_meta = (
                session.query(bauble.meta.BaubleMeta)
                .filter(bauble.meta.BaubleMeta.name == column_name)
                .first()
            )
        if custom_meta:
            self._custom_columns.add(column_name)
            custom_meta = literal_eval(custom_meta.value)
            display_name = custom_meta.get("display_name")

            if display_name:
                label = getattr(self, column_name + "_label")
                label.set_text(display_name + ":")
                data_label = getattr(self, column_name + "_data_label")
                utils.unhide_widgets((label, data_label))

        else:
            label = getattr(self, column_name + "_label")
            label.set_text("_custom_")
            data_label = getattr(self, column_name + "_data_label")
            utils.hide_widgets((label, data_label))

    @staticmethod
    def on_areas_expanded(expander: Gtk.Expander) -> None:
        prefs.prefs[GeneralSpeciesExpander.GEO_AREAS_EXPANDED_PREF] = (
            not expander.get_expanded()
        )

    @staticmethod
    def select_all_areas(_label, _event, row: Species) -> None:
        for dist in row.distribution:
            select_in_search_results(dist.geography)

    def update(self, row: Species) -> None:
        self.has_details = any(
            (
                row.subgenus,
                row.section,
                row.subsection,
                row.series,
                row.subseries,
            )
        )
        # on first run and in case of connection change
        if self._current_db_id != id(db.engine.url):
            self._setup_custom_column("_sp_custom1")
            self._setup_custom_column("_sp_custom2")

        self.update_family(row)
        self.update_genus(row)
        self.update_details(row)

        self.name_label.set_markup(
            f" <big>{row.markup(authors=True, genus=False)}</big>",
        )

        self.update_counts(row)

        self.cites_label.set_label(row.cites or "")
        self.red_list_label.set_label(red_list_values[row.red_list])

        self.update_custom_columns(row)

        self.awards_label.set_label(row.awards or "")
        self.habit_label.set_label(str(row.habit or ""))

        self.update_label_markup(row)
        self.update_distribution(row)
        self.update_plant_locations(row)
        self.update_verifications(row)
        self.update_clickable_labels(row)

        self.show_all()

    def update_family(self, row: Species) -> None:
        self.fam_label.set_markup(
            f"<small>({row.genus.family.family})</small>",
        )
        utils.make_label_clickable(
            self.fam_label, on_taxa_clicked, row.genus.family
        )

    def update_genus(self, row: Species) -> None:
        genus = row.genus.markup()
        self.gen_label.set_markup(f"<big>{genus}</big>")
        utils.make_label_clickable(self.gen_label, on_taxa_clicked, row.genus)

    def update_details(self, row: Species) -> None:
        """Provides infragenic parts, if they exist, above the full name."""
        if not self.has_details:
            utils.hide_widgets([self.details_box])
            return

        utils.unhide_widgets([self.details_box])
        self.details_gen_label.set_markup(
            f"<i>{utils.xml_safe(row.genus)}</i>",
        )
        details = (
            ("subg.", "subgen_label", "subgenus"),
            ("sect.", "section_label", "section"),
            ("subsect.", "subsection_label", "subsection"),
            ("ser.", "series_label", "series"),
            ("subser.", "subseries_label", "subseries"),
        )
        step = 0
        for abv, widget_name, attr in details:
            widget = getattr(self, widget_name)
            value = getattr(row, attr)
            if value:
                step += 12
                utils.unhide_widgets([widget])
                widget.set_margin_start(step)
                widget.set_markup(
                    f"<small>{abv} <i>{utils.xml_safe(value)}</i></small>"
                )
                utils.make_label_clickable(
                    widget,
                    on_clicked_search,
                    f"species where {attr} = {value}",
                )
            else:
                utils.hide_widgets([widget])

    def update_counts(self, row: Species) -> None:
        counts = infobox_counts(row.id)
        self.num_plants_label.set_label("0")

        self.num_acc_label.set_label(str(counts["accessions"] or 0))

        if counts["plants"]:
            self.num_plants_label.set_label(
                f"{counts['plants']} in {counts['acc_w_plants']} accessions"
            )

        self.living_plants_label.set_label(str(counts["living_plants"] or 0))

    def update_custom_columns(self, row: Species) -> None:
        for column_name in self._custom_columns:
            data_label = getattr(self, column_name + "_data_label")
            value = getattr(row, column_name)
            data_label.set_label(value or "")

            utils.make_label_clickable(
                data_label,
                on_clicked_search,
                f"species where {column_name} = '{value}'",
            )

    def update_label_markup(self, row: Species) -> None:
        if row.label_markup:
            utils.unhide_widgets(
                [
                    self.label_markup_label,
                    self.label_markup_data_label,
                ]
            )
            self.label_markup_data_label.set_markup(row.label_markup)
        else:
            utils.hide_widgets(
                [
                    self.label_markup_label,
                    self.label_markup_data_label,
                ]
            )
            self.label_markup_data_label.set_label("--")

    def update_distribution(self, row: Species) -> None:
        self.labeldist_label.set_label(str(row.label_distribution or ""))

        self.map_event_box.update(row)

        self.dist_details_box.foreach(self.dist_details_box.remove)

        if not row.distribution:
            return

        expander = Gtk.Expander(label=_("Areas"), expanded=False)
        expander.connect("activate", self.on_areas_expanded)
        expander.set_expanded(
            prefs.prefs.get(self.GEO_AREAS_EXPANDED_PREF, False)
        )

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        for geo in row.distribution:
            event_box = Gtk.EventBox()
            label = Gtk.Label(label=str(geo))
            label.set_halign(Gtk.Align.START)
            event_box.add(label)

            utils.make_label_clickable(label, on_clicked_select, geo.geography)
            box.pack_start(event_box, False, False, 0)

        event_box = Gtk.EventBox()
        label = Gtk.Label(label="...select all")
        label.set_halign(Gtk.Align.START)
        event_box.add(label)
        utils.make_label_clickable(label, self.select_all_areas, row)
        box.pack_start(event_box, False, False, 0)
        expander.add(box)
        self.dist_details_box.pack_start(expander, False, False, 0)

    def update_plant_locations(self, row: Species) -> None:
        self.plant_locations_box.foreach(self.plant_locations_box.remove)

        def plant_selector(data):
            acc, plt = data
            select_in_search_results(acc, expand_current_first=True)
            select_in_search_results(plt, expand_current_first=True)

        on_clicked = utils.generate_on_clicked(plant_selector)

        sep = ""

        from ..garden import Accession
        from ..garden import Plant

        session = cast(Session, object_session(row))
        plants = (
            session.query(Plant)
            .join(Accession)
            .filter(Accession.species_id == row.id)
            .filter(Plant.quantity > 0)
        )

        for plant in sorted(plants, key=lambda p: p.location.code):
            if sep:
                label = Gtk.Label(label=sep)
                self.plant_locations_box.pack_start(label, False, False, 0)
            loc = plant.location
            event_box = Gtk.EventBox()
            label = Gtk.Label(label=f"{loc.code}")
            label.set_halign(Gtk.Align.START)
            event_box.add(label)

            utils.make_label_clickable(
                label, on_clicked, (plant.accession, plant)
            )
            self.plant_locations_box.pack_start(event_box, False, False, 0)
            sep = ", "

    def update_verifications(self, row: Species) -> None:
        from ..garden.accession import Verification

        self.verifications_box.foreach(self.verifications_box.remove)

        new = 0
        prev = 0
        with db.engine.begin() as connection:
            stmt = (
                select(func.count())
                .select_from(Verification.__table__)
                .where(
                    and_(
                        Verification.prev_species_id == row.id,
                        Verification.species_id != row.id,
                    )
                )
            )
            prev = cast(int, connection.execute(stmt).scalar())
            stmt = (
                select(func.count())
                .select_from(Verification.__table__)
                .where(Verification.species_id == row.id)
            )
            new = cast(int, connection.execute(stmt).scalar())

        if prev:
            event_box = Gtk.EventBox()
            label = Gtk.Label(label=_("%s prev.") % prev)
            event_box.add(label)
            self.verifications_box.add(event_box)
            utils.make_label_clickable(
                label,
                on_clicked_search,
                f"accession where verifications.prev_species.id = {row.id}",
            )
            if new:
                # comma
                label = Gtk.Label(label=", ")
                self.verifications_box.add(label)

        if new:
            event_box = Gtk.EventBox()
            label = Gtk.Label(label=_("%s new") % new)
            event_box.add(label)
            self.verifications_box.add(event_box)
            utils.make_label_clickable(
                label,
                on_clicked_search,
                f"accession where verifications.species.id = {row.id}",
            )

    def update_clickable_labels(self, row: Species) -> None:
        labels_to_searches = (
            (
                self.num_acc_label,
                f"accession where species.id = {row.id}",
            ),
            (
                self.num_plants_label,
                f"plant where accession.species.id = {row.id}",
            ),
            (
                self.cites_label,
                f"species where cites = '{row.cites}'",
            ),
            (
                self.red_list_label,
                f"species where red_list = '{row.red_list}'",
            ),
            (
                self.living_plants_label,
                f"plant where accession.species.id = {row.id} "
                "and quantity > 0",
            ),
        )

        for label, search in labels_to_searches:
            utils.make_label_clickable(
                label,
                on_clicked_search,
                search,
            )


class SpeciesInfoBox(InfoBox[Species]):

    def __init__(self) -> None:
        super().__init__()
        self.add_expander(GeneralSpeciesExpander())
        self.add_expander(VernacularExpander())
        self.add_expander(SynonymsExpander[Species]())

        button_defs = []
        buttons = prefs.prefs.itersection(SPECIES_WEB_BUTTON_DEFS_PREFS)
        for name, button in buttons:
            button["name"] = name
            button_defs.append(button)

        self.add_expander(LinksExpander("notes", links=button_defs))
        self.add_expander(PropertiesExpander())


# it's easier just to put this here instead of playing around with imports
class VernacularNameInfoBox(SpeciesInfoBox):

    def update(self, row: db.Domain) -> None:
        logger.debug(
            "VernacularNameInfoBox.update %s(%s)", row.__class__.__name__, row
        )
        if isinstance(row, VernacularName):
            super().update(row.species)
