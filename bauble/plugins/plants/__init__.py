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

from sqlalchemy import func
from sqlalchemy import select

import bauble
from bauble import db
from bauble import pluginmgr
from bauble.paths import lib_dir
from bauble.search import strategies

from .family import Family
from .genus import Genus
from .geography import Geography
from .species import BinomialSearch
from .species import Species
from .species import SpeciesDistribution
from .species import SynonymSearch
from .species import VernacularName
from .species_model import register_custom_column

# imported by clients of the module
__all__ = ["SpeciesDistribution"]



class PlantsPlugin(pluginmgr.Plugin):

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

        # TODO should only load UI parts if gui exists
        # if bauble.gui:
        logger.debug("PlantsPlugin::init, setup UI")
        from .ui import plug

        plug.reset()

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
