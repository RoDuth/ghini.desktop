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

from pyparsing import ParseResults
from pyparsing import Regex
from pyparsing import Word
from pyparsing import srange
from sqlalchemy import or_
from sqlalchemy.orm import Query
from sqlalchemy.orm import Session

from bauble import db
from bauble import prefs
from bauble.search.search import result_cache
from bauble.search.statements import StatementAction
from bauble.search.strategies import SearchStrategy
from bauble.search.strategies import UseStrategy

from .family import Family
from .family import FamilySynonym
from .genus import Genus
from .genus import GenusSynonym
from .species_model import DefaultVernacularName
from .species_model import Species
from .species_model import SpeciesDistribution
from .species_model import SpeciesNote
from .species_model import SpeciesSynonym
from .species_model import VernacularName

# imported by clients of this modules
__all__ = [
    "SpeciesDistribution",
    "DefaultVernacularName",
    "SpeciesNote",
]


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
