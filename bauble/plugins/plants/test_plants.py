# pylint: disable=no-self-use,protected-access,too-many-public-methods
# Copyright 2008-2010 Brett Adams
# Copyright 2015 Mario Frasca <mario@anche.no>.
# Copyright 2017 Jardín Botánico de Quito
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
#
# Description: test for the Plant plugin
#
import logging

logging.basicConfig()
# logging.getLogger('sqlalchemy.engine').setLevel(logging.INFO)

import os
from datetime import datetime
from datetime import timedelta
from functools import partial
from unittest import TestCase
from unittest import mock

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.exc import StatementError
from sqlalchemy.orm.exc import NoResultFound

from bauble import btypes
from bauble import db
from bauble import prefs
from bauble import search
from bauble import utils
from bauble.meta import BaubleMeta
from bauble.search.search import result_cache
from bauble.search.strategies import UseStrategy
from bauble.test import BaubleClassTestCase
from bauble.test import BaubleTestCase
from bauble.test import check_dupids
from bauble.test import get_setUp_data_funcs

from ..garden import Plant
from . import PlantsPlugin
from .family import Family
from .family import FamilyNote
from .family import FamilySynonym
from .genus import Genus
from .genus import GenusNote
from .genus import GenusSynonym
from .geography import Geography
from .geography import _coord_string
from .geography import _path_string
from .geography import consolidate_geographies
from .geography import consolidate_geographies_by_percent_area
from .geography import get_species_in_geography
from .species import BinomialSearch
from .species import DefaultVernacularName
from .species import Species
from .species import SpeciesDistribution
from .species import SpeciesNote
from .species import SpeciesSynonym
from .species import SynonymSearch
from .species import VernacularName
from .species import get_binomial_completions
from .species_model import SpeciesPicture
from .species_model import _remove_zws as remove_zws
from .species_model import markup_italics
from .species_model import register_custom_column
from .species_model import update_all_full_names_task

family_test_data = (
    {"id": 1, "family": "Orchidaceae", "cites": "II"},
    {"id": 2, "family": "Leguminosae", "qualifier": "s. str."},
    {
        "id": 3,
        "family": "Polypodiaceae",
        "order": "Polypodiales",
        "suborder": "Polypodiineae",
    },
    {"id": 4, "family": "Solanaceae"},
    {"id": 5, "family": "Rosaceae"},
    {"id": 6, "family": "Arecaceae"},
    {"id": 7, "family": "Poaceae"},
    {
        "id": 8,
        "family": "Zamiaceae",
        "order": "Cycadales",
        "suborder": "Zamiineae",
    },
    {"id": 9, "family": "Proteaceae"},
    {"id": 10, "family": "Myrtaceae", "author": "Juss."},
    {
        "id": 11,
        "family": "Stangeriaceae",
        "order": "Cycadales",
        "suborder": "Zamiineae",
    },
    {"id": 12, "family": "Vanillaceae"},
)

family_synonym_test_data = ({"id": 1, "family_id": 1, "synonym_id": 12},)

family_note_test_data = (
    {"id": 1, "family_id": 1, "category": "significance", "note": "high"},
)

genus_test_data = (
    {
        "id": 1,
        "genus": "Maxillaria",
        "family_id": 1,
        "author": "Ruiz & Pav.",
        "cites": "II",
        "qualifier": "s. str",
    },
    {"id": 2, "genus": "Encyclia", "family_id": 1},
    {"id": 3, "genus": "Abrus", "family_id": 2},
    {"id": 4, "genus": "Campyloneurum", "family_id": 3},
    {"id": 5, "genus": "Paphiopedilum", "family_id": 1, "_cites": "I"},
    {"id": 6, "genus": "Laelia", "family_id": 1},
    {"id": 7, "genus": "Brugmansia", "family_id": 4},
    {"id": 8, "hybrid": "+", "genus": "Crataegomespilus", "family_id": 5},
    {
        "id": 9,
        "hybrid": "×",
        "genus": "Butyagrus",
        "family_id": 6,
        "author": "Vorster",
    },
    {"id": 10, "genus": "Cynodon", "family_id": 7},
    {
        "id": 11,
        "genus": "Macrozamia",
        "family_id": 8,
        "subfamily": "Zamioideae",
        "tribe": "Encephalarteae",
        "subtribe": "Macrozamiinae",
    },
    {
        "id": 12,
        "genus": "Banksia",
        "family_id": 7,
        "subfamily": "Grevilleoideae",
    },
    {"id": 13, "genus": "Eucalyptus", "family_id": 10},
    {"id": 14, "genus": "Epidendrum", "family_id": 1},
    {
        "id": 15,
        "genus": "Lepidozamia",
        "family_id": 8,
        "subfamily": "Zamioideae",
        "tribe": "Encephalarteae",
        "subtribe": "Macrozamiinae",
    },
    {
        "id": 16,
        "hybrid": "×",
        "genus": "Rhynchosophrocattleya",
        "family_id": 1,
    },
    {"id": 17, "genus": "Bletilla", "family_id": 1},
)

genus_note_test_data = (
    {"id": 1, "genus_id": 5, "category": "value", "note": "high"},
    {
        "id": 2,
        "genus_id": 1,
        "category": "URL",
        "note": "https://en.wikipedia.org/wiki/Maxillaria",
    },
)

species_test_data = (
    {
        "id": 1,
        "sp": "variabilis",
        "genus_id": 1,
        "sp_author": "Bateman ex Lindl.",
        "full_sci_name": "Maxillaria s. str variabilis Bateman ex Lindl.",
        "_last_updated": datetime.now() + timedelta(days=1),
    },
    {
        "id": 2,
        "sp": "cochleata",
        "genus_id": 2,
        "sp_author": "(L.) Lem\xe9e",
        "full_sci_name": "Encyclia cochleata (L.) Lem\xe9e",
    },
    {
        "id": 3,
        "sp": "precatorius",
        "genus_id": 3,
        "sp_author": "L.",
        "full_sci_name": "Abrus precatorius L.",
    },
    {
        "id": 4,
        "sp": "alapense",
        "genus_id": 4,
        "hybrid": "×",
        "sp_author": "F\xe9e",
        "full_sci_name": "Campyloneurum × alapense F\xe9e",
    },
    {
        "id": 5,
        "sp": "cochleata",
        "genus_id": 2,
        "sp_author": "(L.) Lem\xe9e",
        "infrasp1_rank": "var.",
        "infrasp1": "cochleata",
        "full_sci_name": "Encyclia cochleata (L.) Lem\xe9e var. cochleata",
    },
    {
        "id": 6,
        "sp": "cochleata",
        "genus_id": 2,
        "sp_author": "(L.) Lem\xe9e",
        "cultivar_epithet": "Black Night",
        "full_sci_name": "Encyclia cochleata (L.) Lem\xe9e 'Black Night'",
    },
    {
        "id": 7,
        "sp": "precatorius",
        "genus_id": 3,
        "sp_author": "L.",
        "cv_group": "SomethingRidiculous",
        "full_sci_name": "Abrus precatorius L. SomethingRidiculous Group",
    },
    {
        "id": 8,
        "sp": "precatorius",
        "genus_id": 3,
        "sp_author": "L.",
        "cultivar_epithet": "Hot Rio Nights",
        "cv_group": "SomethingRidiculous",
        "full_sci_name": "Abrus precatorius L. (SomethingRidiculous Group) 'Hot Rio Nights'",
    },
    {
        "id": 9,
        "sp": "generalis",
        "genus_id": 1,
        "hybrid": "×",
        "cultivar_epithet": "Red",
        "full_sci_name": "Maxillaria × generalis 'Red'",
        "_last_updated": datetime.now() - timedelta(days=1),
    },
    {
        "id": 10,
        "sp": "generalis",
        "genus_id": 1,
        "hybrid": "×",
        "sp_author": "L.",
        "cultivar_epithet": "Red",
        "cv_group": "SomeGroup",
        "full_sci_name": "Maxillaria × generalis (SomeGroup Group) 'Red'",
    },
    {
        "id": 11,
        "sp": "generalis",
        "genus_id": 1,
        "sp_qual": "agg.",
        "full_sci_name": "Maxillaria generalis agg.",
    },
    {
        "id": 12,
        "genus_id": 1,
        "cv_group": "SomeGroup",
        "full_sci_name": "Maxillaria SomeGroup Group",
    },
    {
        "id": 13,
        "genus_id": 1,
        "cultivar_epithet": "Red",
        "full_sci_name": "Maxillaria 'Red'",
    },
    {
        "id": 14,
        "genus_id": 1,
        "cultivar_epithet": "Red & Blue",
        "full_sci_name": "Maxillaria 'Red & Blue'",
    },
    {
        "id": 15,
        "sp": "cochleata",
        "genus_id": 2,
        "sp_author": "L.",
        "infrasp1_rank": "subsp.",
        "infrasp1": "cochleata",
        "infrasp1_author": "L.",
        "infrasp2_rank": "var.",
        "infrasp2": "cochleata",
        "infrasp2_author": "L.",
        "cultivar_epithet": "Black",
        "full_sci_name": "Encyclia cochleata L. subsp. cochleata L. var. cochleata L. 'Black'",
    },
    {
        "id": 16,
        "genus_id": 1,
        "sp": "test",
        "infrasp1_rank": "subsp.",
        "infrasp1": "test",
        "cv_group": "SomeGroup",
        "full_sci_name": "Maxillaria test subsp. test SomeGroup Group",
    },
    {
        "id": 17,
        "genus_id": 5,
        "sp": "adductum",
        "author": "Asher",
        "full_sci_name": "Paphiopedilum adductum Asher",
    },
    {
        "id": 18,
        "genus_id": 6,
        "sp": "lobata",
        "author": "H.J. Veitch",
        "_cites": "III",
        "full_sci_name": "Laelia lobata H.J. Veitch",
    },
    {
        "id": 19,
        "genus_id": 6,
        "sp": "grandiflora",
        "author": "Lindl.",
        "full_sci_name": "Laelia grandiflora Lindl.",
    },
    {
        "id": 20,
        "genus_id": 2,
        "sp": "fragrans",
        "author": "Dressler",
        "full_sci_name": "Encyclia fragrans Dressler",
    },
    {
        "id": 21,
        "genus_id": 7,
        "sp": "arborea",
        "author": "Lagerh.",
        "full_sci_name": "Brugmansia arborea Lagerh.",
    },
    {
        "id": 22,
        "sp": "",
        "genus_id": 1,
        "sp_author": "",
        "cultivar_epithet": "Layla Saida",
        "full_sci_name": "Maxillaria 'Layla Saida'",
    },
    {
        "id": 23,
        "sp": "",
        "genus_id": 1,
        "sp_author": "",
        "cultivar_epithet": "Buonanotte",
        "full_sci_name": "Maxillaria 'Buonanotte'",
    },
    {
        "id": 24,
        "sp": "",
        "genus_id": 1,
        "sp_author": "",
        "infrasp1_rank": None,
        "infrasp1": "sp",
        "full_sci_name": "Maxillaria sp",
    },
    {
        "id": 25,
        "sp": "dardarii",
        "genus_id": 8,
        "full_sci_name": "+ Crataegomespilus dardarii",
    },
    {
        "id": 26,
        "sp": "nabonnandii",
        "genus_id": 9,
        "full_sci_name": "× Butyagrus nabonnandii",
        "author": "(Prosch.) Vorster",
    },
    {
        "id": 27,
        "sp": "dactylon × transvaalensis",
        "genus_id": 10,
        "cultivar_epithet": "DT-1",
        "pbr_protected": True,
        "trade_name": "TifTuf",
        "trademark_symbol": "™",
        "full_sci_name": "Cynodon dactylon × transvaalensis 'DT-1' (PBR) TIFTUF™",
    },
    {
        "id": 28,
        "sp": "precatorius",
        "genus_id": 3,
        "infrasp1_rank": "subsp.",
        "infrasp1": "africanus",
        "infrasp1_author": "Verdc.",
        "full_sci_name": "Abrus precatorius subsp. africanus Verdc.",
    },
    {
        "id": 29,
        "genus_id": 5,
        "cultivar_epithet": "Springwater",
        "grex": "Jim Kie",
        "full_sci_name": "Paphiopedilum Jim Kie grex 'Springwater'",
    },
    {
        "id": 30,
        "genus_id": 12,
        "sp": "bipinnatifida",
        "subgenus": "Banksia",
        "series": "Dryandra",
        "full_sci_name": "Banksia bipinnatifida",
    },
    {
        "id": 31,
        "genus_id": 13,
        "subgenus": "Symphyomyrtus",
        "section": "Bisectae",
        "subsection": "Destitutae",
        "series": "Subulatae",
        "subseries": "Decussatae",
        "sp": "aspera",
        "full_sci_name": "Eucalyptus aspera",
    },
    {
        "id": 32,
        "genus_id": 14,
        "subgenus": "Epidendrum",
        "section": "Planifolia",
        "subsection": "Umbellata",
        "sp": "nocturnum",
        "full_sci_name": "Epidendrum nocturnum",
    },
    {
        "id": 33,
        "genus_id": 13,
        "subgenus": "Symphyomyrtus",
        "section": "Bisectae",
        "subsection": "Destitutae",
        "series": "Subulatae",
        "subseries": "Decussatae",
        "sp": "gillii",
        "sp_qual": "s. lat.",
        "full_sci_name": "Eucalyptus gillii s. lat.",
    },
    {
        "id": 34,
        "genus_id": 16,
        "grex": "Marie Lemon Stick",
        "cv_group": "Francis Suzuki",
        "full_sci_name": (
            "× Rhynchosophrocattleya Marie Lemon Stick grex "
            "Francis Suzuki Group"
        ),
    },
    {
        "id": 35,
        "genus_id": 17,
        "grex": "Penway Prelude",
        "cv_group": "Penway Dancer",
        "cultivar_epithet": "Ballerina",
        "full_sci_name": (
            "Bletilla Penway Prelude grex (Penway Dancer Group) 'Ballerina'"
        ),
    },
)

species_note_test_data = (
    {"id": 1, "species_id": 18, "category": "value", "note": "high"},
    {"id": 2, "species_id": 20, "category": "IUCN", "note": "LC"},
    {"id": 3, "species_id": 18, "category": "<price>", "note": "19.50"},
    {"id": 4, "species_id": 18, "category": "[list_var]", "note": "abc"},
    {"id": 5, "species_id": 18, "category": "[list_var]", "note": "def"},
    {"id": 6, "species_id": 18, "category": "<price_tag>", "note": "$19.50"},
    {"id": 7, "species_id": 18, "category": "{dict_var:k}", "note": "abc"},
    {"id": 8, "species_id": 18, "category": "{dict_var:l}", "note": "def"},
    {"id": 9, "species_id": 18, "category": "{dict_var:m}", "note": "xyz"},
)

genus_str_map = {
    1: "Maxillaria s. str",
    2: "Encyclia",
}

genus_str_author_map = {
    1: "Maxillaria s. str Ruiz & Pav.",
    2: "Encyclia",
}

species_str_map = {
    1: "Maxillaria s. str variabilis",
    2: "Encyclia cochleata",
    3: "Abrus precatorius",
    4: "Campyloneurum × alapense",
    5: "Encyclia cochleata var. cochleata",
    6: "Encyclia cochleata 'Black Night'",
    7: "Abrus precatorius SomethingRidiculous Group",
    8: "Abrus precatorius (SomethingRidiculous Group) 'Hot Rio Nights'",
    9: "Maxillaria s. str × generalis 'Red'",
    10: "Maxillaria s. str × generalis (SomeGroup Group) 'Red'",
    11: "Maxillaria s. str generalis agg.",
    12: "Maxillaria s. str SomeGroup Group",
    13: "Maxillaria s. str 'Red'",
    14: "Maxillaria s. str 'Red & Blue'",
    15: "Encyclia cochleata subsp. cochleata var. cochleata 'Black'",
    16: "Maxillaria s. str test subsp. test SomeGroup Group",
    25: "+ Crataegomespilus dardarii",
    26: "× Butyagrus nabonnandii",
    27: "Cynodon dactylon × transvaalensis 'DT-1' (PBR) TIFTUF™",
    28: "Abrus precatorius subsp. africanus",
    29: "Paphiopedilum Jim Kie grex 'Springwater'",
    33: "Eucalyptus gillii s. lat.",
    34: "× Rhynchosophrocattleya Marie Lemon Stick grex Francis Suzuki Group",
    35: "Bletilla Penway Prelude grex (Penway Dancer Group) 'Ballerina'",
}

species_markup_map = {
    1: "<i>Maxillaria</i> s. str <i>variabilis</i>",
    2: "<i>Encyclia</i> <i>cochleata</i>",
    3: "<i>Abrus</i> <i>precatorius</i>",
    4: "<i>Campyloneurum</i> × <i>alapense</i>",
    5: "<i>Encyclia</i> <i>cochleata</i> var. <i>cochleata</i>",
    6: "<i>Encyclia</i> <i>cochleata</i> 'Black Night'",
    12: "<i>Maxillaria</i> s. str SomeGroup Group",
    14: "<i>Maxillaria</i> s. str 'Red &amp; Blue'",
    15: (
        "<i>Encyclia</i> <i>cochleata</i> subsp. <i>"
        "cochleata</i> var. <i>cochleata</i> 'Black'"
    ),
    25: "+ <i>Crataegomespilus</i> <i>dardarii</i>",
    26: "× <i>Butyagrus</i> <i>nabonnandii</i>",
    27: (
        "<i>Cynodon</i> <i>dactylon</i> × <i>transvaalensis</i> 'DT-1' "
        "<small>(PBR)</small> T<small>IF</small>T<small>UF</small>™"
    ),
    29: "<i>Paphiopedilum</i> Jim Kie grex 'Springwater'",
    34: (
        "× <i>Rhynchosophrocattleya</i> Marie Lemon Stick grex "
        "Francis Suzuki Group"
    ),
    35: "<i>Bletilla</i> Penway Prelude grex (Penway Dancer Group) 'Ballerina'",
}

species_str_authors_map = {
    1: "Maxillaria s. str variabilis Bateman ex Lindl.",
    2: "Encyclia cochleata (L.) Lem\xe9e",
    3: "Abrus precatorius L.",
    4: "Campyloneurum × alapense F\xe9e",
    5: "Encyclia cochleata (L.) Lem\xe9e var. cochleata",
    6: "Encyclia cochleata (L.) Lem\xe9e 'Black Night'",
    7: "Abrus precatorius L. SomethingRidiculous Group",
    8: "Abrus precatorius L. (SomethingRidiculous Group) 'Hot Rio Nights'",
    15: (
        "Encyclia cochleata L. subsp. "
        "cochleata L. var. cochleata L. 'Black'"
    ),
    28: "Abrus precatorius subsp. africanus Verdc.",
}

species_markup_authors_map = {
    1: "<i>Maxillaria</i> s. str <i>variabilis</i> Bateman ex Lindl.",
    2: "<i>Encyclia</i> <i>cochleata</i> (L.) Lem\xe9e",
    3: "<i>Abrus</i> <i>precatorius</i> L.",
    4: "<i>Campyloneurum</i> × <i>alapense</i> F\xe9e",
    5: "<i>Encyclia</i> <i>cochleata</i> (L.) Lem\xe9e var. <i>cochleata</i>",
    6: "<i>Encyclia</i> <i>cochleata</i> (L.) Lem\xe9e 'Black Night'",
}

species_searchview_markup_map = {
    1: (
        '<i>Maxillaria</i> s. str <i>variabilis</i> <span weight="light">Bateman ex '
        "Lindl.</span>"
    ),
    27: (
        "<i>Cynodon</i> <i>dactylon</i> × <i>transvaalensis</i> 'DT-1' "
        '<span weight="light"><small>(PBR)</small></span> '
        "T<small>IF</small>T<small>UF</small>™"
    ),
    28: (
        "<i>Abrus</i> <i>precatorius</i> subsp. <i>africanus</i> "
        '<span weight="light">Verdc.</span>'
    ),
}

sp_synonym_test_data = ({"id": 1, "synonym_id": 1, "species_id": 2},)

vn_test_data = (
    {"id": 1, "name": "SomeName", "language": "English", "species_id": 1},
    {"id": 2, "name": "SomeName 2", "language": "English", "species_id": 1},
    {"id": 3, "name": "Floripondio", "language": "es", "species_id": 21},
    {"id": 4, "name": "Toé", "language": "agr", "species_id": 21},
    {
        "id": 5,
        "name": "Clamshell orchid",
        "language": "English",
        "species_id": 15,
    },
    {
        "id": 6,
        "name": "Clamshell orchid",
        "language": "English",
        "species_id": 6,
    },
    {
        "id": 7,
        "name": "Clamshell orchid",
        "language": "English",
        "species_id": 5,
    },
    {
        "id": 8,
        "name": "Clamshell orchid",
        "language": "English",
        "species_id": 2,
    },
)

test_data_table_control = (
    (Family, family_test_data),
    (FamilySynonym, family_synonym_test_data),
    (Genus, genus_test_data),
    (Species, species_test_data),
    (VernacularName, vn_test_data),
    (SpeciesSynonym, sp_synonym_test_data),
    (FamilyNote, family_note_test_data),
    (GenusNote, genus_note_test_data),
    (SpeciesNote, species_note_test_data),
)


def setUp_data():
    """
    bauble.plugins.plants.test.setUp_test_data()

    if this method is called again before tearDown_test_data is called you
    will get an error about the test data rows already existing in the database
    """

    for mapper, data in test_data_table_control:
        table = mapper.__table__
        # insert row by row instead of doing an insert many since each
        # row will have different columns
        for row in data:
            table.insert().execute(row).close()
        for col in table.c:
            utils.reset_sequence(col)


setUp_data.order = 0  # type: ignore [attr-defined]


def setup_geographies() -> None:
    """For convenience for test that need geography data run this."""

    from bauble.paths import lib_dir
    from bauble.plugins.imex.csv_ import CSVRestore

    csv = CSVRestore()
    geo_csv = os.path.join(
        lib_dir(), "plugins", "plants", "default", "geography.csv"
    )
    csv.start(
        [geo_csv],
        metadata=db.metadata,
        force=True,
    )


class DuplicateIdsGlade(TestCase):
    def test_duplicate_ids(self):
        """
        Test for duplicate ids for all .glade files in the plants plugin.
        """
        import glob

        import bauble.plugins.garden as mod

        head, tail = os.path.split(mod.__file__)
        files = glob.glob(os.path.join(head, "*.glade"))
        for f in files:
            self.assertTrue(not check_dupids(f), f)


class PlantTestCase(BaubleTestCase):
    def setUp(self):
        super().setUp()
        setUp_data()


class PrefsUpdatedTest(BaubleTestCase):
    def test_prefs_update(self):
        # NOTE plugin.init() is called in BaubleTestCase.setUp if this plugin
        # exists the prefs in default/config.cfg should have been copied in.
        # tests pluginmgr.update_prefs
        self.assertTrue(
            prefs.prefs.get("web_button_defs.species.googlebutton")
        )
        self.assertTrue(prefs.prefs.get("web_button_defs.genus.googlebutton"))
        self.assertTrue(prefs.prefs.get("web_button_defs.family.googlebutton"))


class FamilyTests(PlantTestCase):
    """Tests for Family and FamilySynonym"""

    def test_cascades(self):
        """
        Test that cascading is set up properly
        """
        family = Family(family="family")
        genus = Genus(family=family, genus="genus")
        self.session.add_all([family, genus])
        self.session.commit()

        # test that deleting a family deletes an orphaned genus
        self.session.delete(family)
        self.session.commit()
        query = self.session.query(Genus).filter_by(family_id=family.id)
        self.assertRaises(NoResultFound, query.one)

    def test_synonyms(self):
        """
        Test that Family.synonyms works correctly
        """
        family = Family(family="family")
        family2 = Family(family="family2")
        family.synonyms.append(family2)
        self.session.add_all([family, family2])
        self.session.commit()

        # test that family2 was added as a synonym to family
        family = self.session.query(Family).filter_by(family="family").one()
        self.assertTrue(family2 in family.synonyms)

        # test that the synonyms relation and family backref works
        self.assertTrue(family._synonyms[0].family == family)
        self.assertTrue(family._synonyms[0].synonym == family2)

        # test that the synonyms are removed properly
        family.synonyms.remove(family2)
        self.session.commit()
        self.assertTrue(family2 not in family.synonyms)

        # test synonyms contraints, e.g that a family cannot have the
        # same synonym twice
        family.synonyms.append(family2)
        self.session.commit()
        family.synonyms.append(family2)
        self.assertRaises(IntegrityError, self.session.commit)
        self.session.rollback()

        # test that clearing all the synonyms works
        family.synonyms.clear()
        self.session.commit()
        self.assertEqual(len(family.synonyms), 0)

        # test that deleting a family that is a synonym of another family
        # deletes all the dangling objects
        family.synonyms.append(family2)
        self.session.commit()
        self.session.delete(family2)
        self.session.commit()
        self.assertEqual(len(family.synonyms), 0)

        # test that deleting the previous synonyms didn't delete the
        # family that it refered to
        self.assertTrue(self.session.get(Family, family.id))

        # test that deleting a family that has synonyms deletes all
        # the synonyms that refer to that family deletes all the
        family2 = Family(family="family2")
        self.session.add(family2)
        family.synonyms.append(family2)
        self.session.commit()
        self.session.delete(family)
        self.session.commit()
        # NOTE there is one synonym added as part of the test_data
        self.assertEqual(self.session.query(FamilySynonym).count(), 1)

    def test_constraints(self):
        """
        Test that the family constraints were created correctly
        """
        values = [
            dict(family="family"),
            dict(family="family", qualifier="s. lat."),
        ]
        for v in values:
            self.session.add(Family(**v))
            self.session.add(Family(**v))
            self.assertRaises(IntegrityError, self.session.commit)
            self.session.rollback()

        # test that family cannot be null
        self.session.add(Family(family=None))
        self.assertRaises(IntegrityError, self.session.commit)
        self.session.rollback()

    def test_str(self):
        """
        Test that the family str function works as expected
        """
        f = Family()
        self.assertTrue(str(f) == repr(f))
        f = Family(family="fam")
        self.assertTrue(str(f) == "fam")
        f.qualifier = "s. lat."
        self.assertTrue(str(f) == "fam s. lat.")
        f.author = "arthur"
        self.assertTrue(f.string(author=True) == "fam s. lat. arthur")

    def test_search_view_markup_pair(self):
        fam = Family(epithet="Myrtaceae", author="Juss.")
        self.assertEqual(
            fam.search_view_markup_pair(),
            ('Myrtaceae <span weight="light">Juss.</span>', "Family"),
        )

    def test_synonym_str(self):
        fam = Family(family="Fam", qualifier="s. lat.", author="Arthur")
        new = Family(family="Newname")
        syn = FamilySynonym(family=new, synonym=fam)
        self.assertEqual(str(syn), fam.string(author=True))

    def test_synonym_markup(self):
        fam = Family(family="Fam", qualifier="s. lat.", author="Arthur")
        new = Family(family="Newname")
        syn = FamilySynonym(family=new, synonym=fam)
        self.assertEqual(str(syn), fam.string(author=True))

    def test_no_synonyms_means_itself_accepted(self):
        def create_tmp_fam(id):
            fam = Family(id=id, epithet="fam%02d" % id)
            self.session.add(fam)
            return fam

        fam1 = create_tmp_fam(51)
        self.session.commit()
        self.assertEqual(fam1.accepted, None)

    def test_synonyms_and_accepted_properties(self):
        def create_tmp_fam(id):
            fam = Family(id=id, epithet="fam%02d" % id)
            self.session.add(fam)
            return fam

        # equivalence classes after changes
        fam1 = create_tmp_fam(41)
        fam2 = create_tmp_fam(42)
        fam3 = create_tmp_fam(43)
        fam4 = create_tmp_fam(44)  # (1), (2), (3), (4)
        fam3.accepted = fam1  # (1 3), (2), (4)
        self.assertEqual([i.epithet for i in fam1.synonyms], [fam3.epithet])
        fam1.synonyms.append(fam2)  # (1 3 2), (4)
        self.session.flush()
        self.assertEqual(fam2.accepted.epithet, fam1.epithet)  # just added
        self.assertEqual(fam3.accepted.epithet, fam1.epithet)  # no change
        fam2.accepted = fam4  # (1 3), (4 2)
        self.session.commit()
        self.assertEqual([i.epithet for i in fam4.synonyms], [fam2.epithet])
        self.assertEqual([i.epithet for i in fam1.synonyms], [fam3.epithet])
        self.assertEqual(fam1.accepted, None)
        self.assertEqual(fam2.accepted, fam4)
        self.assertEqual(fam3.accepted, fam1)
        self.assertEqual(fam4.accepted, None)
        fam2.accepted = fam4  # does not change anything
        self.session.commit()
        self.assertEqual(fam1.accepted, None)
        self.assertEqual(fam2.accepted, fam4)
        self.assertEqual(fam3.accepted, fam1)
        self.assertEqual(fam4.accepted, None)
        fam2.accepted = fam2  # cannot be a synonym of itself
        self.assertRaises(IntegrityError, self.session.commit)

    def test_pictures(self):
        from ..garden import Accession
        from ..garden import Location
        from ..garden.plant import PlantPicture

        fam = self.session.query(Family).first()
        gen = fam.genera[0]
        self.assertEqual(fam.pictures, [])
        sp = gen.species[0]
        acc = Accession(species=sp, code="1")
        plt = Plant(
            accession=acc,
            quantity=0,
            location=Location(name="site", code="STE"),
            code="1",
        )
        self.session.add_all([sp, acc, plt])
        self.session.commit()
        spic = SpeciesPicture(picture="test1.jpg", species=sp)
        ppic = PlantPicture(picture="test2.jpg", plant=plt)
        self.session.commit()
        self.assertEqual(fam.pictures, [spic, ppic])
        plt.quantity = 0
        self.session.commit()
        # exclude inactive
        prefs.prefs[prefs.exclude_inactive_pref] = True
        self.assertEqual(fam.pictures, [spic])
        # detached returns empty
        self.session.expunge(fam)
        self.assertEqual(fam.pictures, [])

    def test_active_no_genera(self):
        fam = self.session.get(Family, 12)
        self.assertFalse(fam.active)
        # test the hybrid_property expression
        # pylint: disable=no-member  # is_
        fam_active_in_db = self.session.query(Family).filter(
            Family.active.is_(True)
        )
        self.assertNotIn(fam, fam_active_in_db)

    def test_active_no_species(self):
        fam = self.session.get(Family, 8)
        self.assertFalse(fam.active)
        # test the hybrid_property expression
        # pylint: disable=no-member  # is_
        fam_active_in_db = self.session.query(Family).filter(
            Family.active.is_(True)
        )
        self.assertNotIn(fam, fam_active_in_db)

    def test_active_no_accession(self):
        fam = self.session.get(Family, 1)
        # check this is a family with no accession
        self.assertEqual(
            len(
                [
                    acc
                    for gen in fam.genera
                    for sp in gen.species
                    for acc in sp.accessions
                ]
            ),
            0,
        )
        self.assertTrue(fam.active)
        # test the hybrid_property expression
        # pylint: disable=no-member  # is_
        fam_active_in_db = self.session.query(Family).filter(
            Family.active.is_(True)
        )
        self.assertIn(fam, fam_active_in_db)

    def test_active_no_plants(self):
        from ..garden import Accession

        sp = self.session.get(Species, 26)
        fam = sp.genus.family
        # check this is a family with no plants
        self.assertEqual(
            len(
                [
                    plt
                    for gen in fam.genera
                    for sp in gen.species
                    for acc in sp.accessions
                    for plt in acc.plants
                ]
            ),
            0,
        )
        acc = Accession(code="foo", species=sp)
        self.session.add(acc)
        self.session.commit()

        self.assertTrue(fam.active)
        # test the hybrid_property expression
        # pylint: disable=no-member  # is_
        fam_active_in_db = self.session.query(Family).filter(
            Family.active.is_(True)
        )
        self.assertIn(fam, fam_active_in_db)

    def test_active_one_plants_w_qty(self):
        from ..garden import Accession
        from ..garden import Location

        sp = self.session.get(Species, 26)
        acc = Accession(code="foo", species=sp)
        plt = Plant(
            code="1", accession=acc, quantity=1, location=Location(code="bar")
        )
        self.session.add_all([acc, plt])
        self.session.commit()
        fam = sp.genus.family

        self.assertTrue(fam.active)
        # test the hybrid_property expression
        # pylint: disable=no-member  # is_
        fam_active_in_db = self.session.query(Family).filter(
            Family.active.is_(True)
        )
        self.assertIn(fam, fam_active_in_db)

    def test_active_one_plants_wo_qty(self):
        from ..garden import Accession
        from ..garden import Location

        sp = self.session.get(Species, 26)
        fam = sp.genus.family
        self.assertEqual(
            len(
                [
                    plt
                    for gen in fam.genera
                    for sp in gen.species
                    for acc in sp.accessions
                    for plt in acc.plants
                ]
            ),
            0,
        )
        acc = Accession(code="foo", species=sp)
        plt = Plant(
            code="1", accession=acc, quantity=0, location=Location(code="bar")
        )
        self.session.add_all([acc, plt])
        self.session.commit()

        self.assertFalse(fam.active)
        # test the hybrid_property expression
        # pylint: disable=no-member  # is_
        fam_active_in_db = self.session.query(Family).filter(
            Family.active.is_(True)
        )
        self.assertNotIn(fam, fam_active_in_db)

    def test_has_children(self):
        from ..garden import Accession
        from ..garden import Location

        fam = Family(epithet="Welwitschiaceae")
        gen = Genus(epithet="Welwitschia", family=fam)
        sp = Species(epithet="mirablis", genus=gen)
        acc = Accession(species=sp, code="1")
        loc = Location(code="LOC10")
        plant = Plant(
            accession=acc,
            quantity=0,
            location=loc,
            code="1",
        )
        self.session.add(plant)
        self.session.commit()

        prefs.prefs[prefs.exclude_inactive_pref] = True

        # plant qty 0 exclude inactive true
        self.assertEqual(fam.has_children(), False)

        prefs.prefs[prefs.exclude_inactive_pref] = False

        # plant qty 0 exclude inactive false
        self.assertEqual(fam.has_children(), True)

        plant.quantity = 1
        self.session.commit()

        # plant qty 1 exclude inactive false
        self.assertEqual(fam.has_children(), True)

        prefs.prefs[prefs.exclude_inactive_pref] = True

        # plant qty 1 exclude inactive true
        self.assertEqual(fam.has_children(), True)

        self.session.delete(plant)
        self.session.commit()

        # no plant exclude inactive true
        self.assertEqual(fam.has_children(), True)

        prefs.prefs[prefs.exclude_inactive_pref] = False

        # no plant exclude inactive false
        self.assertEqual(fam.has_children(), True)


class FamilyUpdatedTests(BaubleTestCase):

    def test_updated_self(self):
        fam = Family(epithet="Myrtaceae")
        self.session.add(fam)
        self.session.commit()

        self.assertIs(
            self.session.query(Family)
            .filter(Family.updated > "Today")
            .first(),
            fam,
        )

        # the python function
        self.assertEqual(fam.updated, fam._last_updated)

        date = datetime(2001, 1, 1, 0)
        fam._last_updated = date
        self.session.commit()

        self.assertIs(
            self.session.query(Family).filter(Family.updated == date).first(),
            fam,
        )

        # the python function
        self.assertEqual(fam.updated, fam._last_updated)

    def test_updated_notes(self):
        date = datetime(2001, 1, 1, 0)
        fam = Family(epithet="Myrtaceae", _last_updated=date)
        note = FamilyNote(category="Spam", note="Eggs", family=fam)
        self.session.add_all([fam, note])
        self.session.commit()

        self.assertIs(
            self.session.query(Family)
            .filter(Family.updated > "Today")
            .first(),
            fam,
        )

        # the python function
        self.assertEqual(fam.updated, note._last_updated)

        note._last_updated = datetime(2001, 1, 1, 0)
        self.session.commit()

        self.assertIs(
            self.session.query(Family).filter(Family.updated == date).first(),
            fam,
        )

        # the python function
        self.assertEqual(fam.updated, fam._last_updated)

    def test_updated_synonym(self):
        # make sure the date is not now
        date = datetime(2001, 1, 1, 0)
        fam = Family(epithet="Myrtaceae", _last_updated=date)
        fam2 = Family(epithet="Kaniaceae", _last_updated=date)
        fam2.accepted = fam
        self.session.add_all([fam, fam2])
        self.session.commit()

        self.assertIs(
            self.session.query(Family)
            .filter(Family.updated > "Today")
            .first(),
            fam2,
        )

        # the python function
        self.assertEqual(fam2.updated, fam2._accepted._last_updated)


class FamilyTopLevelCountTests(BaubleTestCase):
    def setUp(self):
        super().setUp()
        for func in get_setUp_data_funcs():
            func()

    def test_top_level_count_w_plant_qty(self):

        expected = (
            "Families: 2, "
            "Genera: 8, "
            "Species: 27, "
            "Accessions: 6, "
            "Plantings: 5, "
            "Living plants: 6, "
            "Locations: 1, "
            "Sources: 1"
        )

        self.assertEqual(str(Family.top_level_count([1, 2])), expected)

    def test_top_level_count_wo_genera(self):
        fam = Family(epithet="Welwitschiaceae")
        self.session.add(fam)
        self.session.commit()

        expected = (
            "Families: 2, "
            "Genera: 7, "
            "Species: 23, "
            "Accessions: 4, "
            "Plantings: 3, "
            "Living plants: 3, "
            "Locations: 1, "
            "Sources: 1"
        )

        self.assertEqual(str(Family.top_level_count([1, fam.id])), expected)

    def test_top_level_count_wo_species_in_genera(self):

        gen = self.session.get(Genus, 14)
        for sp in gen.species:
            self.session.delete(sp)
        self.session.commit()

        expected = (
            "Families: 2, "
            "Genera: 8, "
            "Species: 26, "
            "Accessions: 6, "
            "Plantings: 5, "
            "Living plants: 6, "
            "Locations: 1, "
            "Sources: 1"
        )

        self.assertEqual(str(Family.top_level_count([1, 2])), expected)

    def test_top_level_count_wo_species_in_genera_exclude_inactive_set(self):

        gen = self.session.get(Genus, 14)
        for sp in gen.species:
            self.session.delete(sp)
        self.session.commit()

        expected = (
            "Families: 2, "
            "Genera: 7, "
            "Species: 26, "
            "Accessions: 5, "
            "Plantings: 4, "
            "Living plants: 6, "
            "Locations: 1, "
            "Sources: 1"
        )

        self.assertEqual(str(Family.top_level_count([1, 2], True)), expected)

    def test_top_level_count_wo_plant_qty(self):
        plt = self.session.get(Plant, 1)
        self.session.delete(plt)
        plt = self.session.get(Plant, 2)
        plt.quantity = 0
        self.session.commit()

        expected = (
            "Families: 2, "
            "Genera: 8, "
            "Species: 27, "
            "Accessions: 6, "
            "Plantings: 4, "
            "Living plants: 4, "
            "Locations: 1, "
            "Sources: 1"
        )

        self.assertEqual(str(Family.top_level_count([1, 2])), expected)

    def test_top_level_count_wo_plant_qty_exclude_inactive_set(self):
        plt = self.session.get(Plant, 1)
        self.session.delete(plt)
        plt = self.session.get(Plant, 2)
        plt.quantity = 0
        self.session.commit()

        expected = (
            "Families: 2, "
            "Genera: 8, "
            "Species: 27, "
            "Accessions: 5, "
            "Plantings: 2, "
            "Living plants: 4, "
            "Locations: 1, "
            "Sources: 1"
        )

        self.assertEqual(str(Family.top_level_count([1, 2], True)), expected)


class GenusTests(PlantTestCase):
    def test_synonyms(self):
        family = Family(family="family")
        genus = Genus(family=family, genus="genus")
        genus2 = Genus(family=family, genus="genus2")
        genus.synonyms.append(genus2)
        self.session.add_all([genus, genus2])
        self.session.commit()

        # test that genus2 was added as a synonym to genus
        genus = self.session.query(Genus).filter_by(genus="genus").one()
        self.assertTrue(genus2 in genus.synonyms)

        # test that the synonyms relation and genus backref works
        self.assertTrue(genus._synonyms[0].genus == genus)
        self.assertTrue(genus._synonyms[0].synonym == genus2)

        # test that the synonyms are removed properly
        genus.synonyms.remove(genus2)
        self.session.commit()
        self.assertTrue(genus2 not in genus.synonyms)

        # test synonyms contraints, e.g that a genus cannot have the
        # same synonym twice
        genus.synonyms.append(genus2)
        self.session.commit()
        genus.synonyms.append(genus2)
        self.assertRaises(IntegrityError, self.session.commit)
        self.session.rollback()

        # test that clearing all the synonyms works
        genus.synonyms.clear()
        self.session.commit()
        self.assertTrue(len(genus.synonyms) == 0)
        self.assertTrue(self.session.query(GenusSynonym).count() == 0)

        # test that deleting a genus that is a synonym of another genus
        # deletes all the dangling objects
        genus.synonyms.append(genus2)
        self.session.commit()
        self.session.delete(genus2)
        self.session.commit()
        self.assertTrue(self.session.query(GenusSynonym).count() == 0)

        # test that deleting the previous synonyms didn't delete the
        # genus that it refered to
        self.assertTrue(self.session.get(Genus, genus.id))

        # test that deleting a genus that has synonyms deletes all
        # the synonyms that refer to that genus
        genus2 = Genus(family=family, genus="genus2")
        self.session.add(genus2)
        genus.synonyms.append(genus2)
        self.session.commit()
        self.session.delete(genus)
        self.session.commit()
        self.assertTrue(self.session.query(GenusSynonym).count() == 0)

    def test_contraints(self):
        """
        Test that the genus constraints were created correctly
        """
        family = Family(family="family")
        self.session.add(family)

        # if any of these values are inserted twice they should raise
        # an IntegrityError because the UniqueConstraint on Genus
        values = [
            dict(family=family, genus="genus"),
            dict(family=family, genus="genus", author="author"),
            dict(family=family, genus="genus", qualifier="s. lat."),
            dict(
                family=family,
                genus="genus",
                qualifier="s. lat.",
                author="author",
            ),
        ]
        for v in values:
            self.session.add(Genus(**v))
            self.session.add(Genus(**v))
            self.assertRaises(IntegrityError, self.session.commit)
            self.session.rollback()

    def test_string(self):
        for gid, expected in genus_str_map.items():
            gen = self.session.get(Genus, gid)

            self.assertEqual(str(gen), expected)

            self.assertTrue(
                all(i not in gen.str_basic for i in ("s. lat", "s. str"))
            )

        for gid, expected in genus_str_author_map.items():
            gen = self.session.get(Genus, gid)

            self.assertEqual(gen.string(author=True), expected)

        self.assertEqual(str(Genus()), "")

        self.assertEqual(Genus(genus="SPAM").markup(), "SPAM")

        self.assertEqual(
            Genus(genus="Spam", qualifier="s. lat.").markup(),
            "<i>Spam</i> s. lat.",
        )

    def test_can_use_epithet_field(self):
        family = Family(epithet="family")
        genus = Genus(family=family, genus="genus")
        self.session.add_all([family, genus])
        self.session.commit()
        g1 = self.session.query(Genus).filter(Genus.epithet == "genus").one()
        g2 = self.session.query(Genus).filter(Genus.genus == "genus").one()
        self.assertEqual(g1, g2)
        self.assertEqual(g1.genus, "genus")
        self.assertEqual(g2.epithet, "genus")

    def test_count_children_wo_plants(self):
        from ..garden import Accession

        fam = Family(family="Myrtaceae")
        gen = Genus(epithet="Syzygium", family=fam)
        sp = Species(epithet="australe", genus=gen)
        acc = Accession(species=sp, code="1")
        self.session.add_all([fam, gen, sp, acc])
        self.session.commit()

        self.assertEqual(gen.count_children(), 1)

    def test_count_children_w_plant_w_qty(self):
        from ..garden import Accession
        from ..garden import Location

        fam = Family(family="Myrtaceae")
        gen = Genus(epithet="Syzygium", family=fam)
        sp = Species(epithet="australe", genus=gen)
        acc = Accession(species=sp, code="1")
        plant = Plant(
            accession=acc,
            quantity=1,
            location=Location(name="site", code="STE"),
            code="1",
        )
        self.session.add_all([fam, gen, sp, acc, plant])
        self.session.commit()

        self.assertEqual(gen.count_children(), 1)

    def test_count_children_w_plant_w_qty_exclude_inactive_set(self):
        # should be the same as if exclude inactive not set.
        from ..garden import Accession
        from ..garden import Location

        fam = Family(family="Myrtaceae")
        gen = Genus(epithet="Syzygium", family=fam)
        sp = Species(epithet="australe", genus=gen)
        acc = Accession(species=sp, code="1")
        plant = Plant(
            accession=acc,
            quantity=1,
            location=Location(name="site", code="STE"),
            code="1",
        )
        self.session.add_all([fam, gen, sp, acc, plant])
        self.session.commit()

        prefs.prefs[prefs.exclude_inactive_pref] = True

        self.assertEqual(gen.count_children(), 1)

    def test_count_children_w_plant_wo_qty(self):
        from ..garden import Accession
        from ..garden import Location

        fam = Family(family="Myrtaceae")
        gen = Genus(epithet="Syzygium", family=fam)
        sp = Species(epithet="australe", genus=gen)
        acc = Accession(species=sp, code="1")
        plant = Plant(
            accession=acc,
            quantity=0,
            location=Location(name="site", code="STE"),
            code="1",
        )
        self.session.add_all([fam, gen, sp, acc, plant])
        self.session.commit()

        self.assertEqual(gen.count_children(), 1)

    def test_count_children_w_plant_wo_qty_exclude_inactive_set(self):
        from ..garden import Accession
        from ..garden import Location

        fam = Family(family="Myrtaceae")
        gen = Genus(epithet="Syzygium", family=fam)
        sp = Species(epithet="australe", genus=gen)
        acc = Accession(species=sp, code="1")
        plant = Plant(
            accession=acc,
            quantity=0,
            location=Location(name="site", code="STE"),
            code="1",
        )
        self.session.add_all([fam, gen, sp, acc, plant])
        self.session.commit()

        prefs.prefs[prefs.exclude_inactive_pref] = True

        self.assertEqual(gen.count_children(), 0)

    def test_pictures(self):
        from ..garden import Accession
        from ..garden import Location
        from ..garden.plant import PlantPicture

        gen = self.session.query(Genus).first()
        self.assertEqual(gen.pictures, [])
        sp = gen.species[0]
        acc = Accession(species=sp, code="1")
        plt = Plant(
            accession=acc,
            quantity=0,
            location=Location(name="site", code="STE"),
            code="1",
        )
        self.session.add_all([sp, acc, plt])
        self.session.commit()
        spic = SpeciesPicture(picture="test1.jpg", species=sp)
        ppic = PlantPicture(picture="test2.jpg", plant=plt)
        self.session.commit()
        self.assertEqual(gen.pictures, [spic, ppic])
        plt.quantity = 0
        self.session.commit()
        # exclude inactive
        prefs.prefs[prefs.exclude_inactive_pref] = True
        self.assertEqual(gen.pictures, [spic])
        # detached returns empty
        self.session.expunge(gen)
        self.assertEqual(gen.pictures, [])

    def test_has_children(self):
        from ..garden import Accession
        from ..garden import Location

        gen = self.session.get(Genus, 1)
        sp1 = self.session.get(Species, 22)
        acc = Accession(species=sp1, code="1")
        plt = Plant(
            accession=acc,
            quantity=1,
            location=Location(name="site", code="STE"),
            code="1",
        )
        self.session.add(plt)
        self.session.commit()

        self.assertTrue(gen.has_children())

        plt.quantity = 0
        self.session.commit()

        self.assertTrue(gen.has_children())

        prefs.prefs[prefs.exclude_inactive_pref] = True

        # some species active
        self.assertTrue(gen.has_children())

        # make sure only the not active species left
        for sp in gen.species:
            if sp.id != sp1.id:
                self.session.delete(sp)

        self.session.commit()

        self.assertFalse(gen.has_children())

    def test_active_no_species(self):
        gen = self.session.get(Genus, 11)
        # check genus has no species
        self.assertEqual(len(gen.species), 0)
        self.assertFalse(gen.active)
        # test the hybrid_property expression
        # pylint: disable=no-member  # is_
        fam_active_in_db = self.session.query(Genus).filter(
            Genus.active.is_(True)
        )
        self.assertNotIn(gen, fam_active_in_db)

    def test_active_no_accession(self):
        gen = self.session.get(Genus, 9)
        # check this is a family with no accession
        self.assertEqual(
            len([acc for sp in gen.species for acc in sp.accessions]),
            0,
        )
        self.assertTrue(gen.active)
        # test the hybrid_property expression
        # pylint: disable=no-member  # is_
        gen_active_in_db = self.session.query(Genus).filter(
            Genus.active.is_(True)
        )
        self.assertIn(gen, gen_active_in_db)

    def test_active_no_plants(self):
        from ..garden import Accession

        sp = self.session.get(Species, 26)
        gen = sp.genus
        # check this is a family with no plants
        self.assertEqual(
            len(
                [
                    plt
                    for sp in gen.species
                    for acc in sp.accessions
                    for plt in acc.plants
                ]
            ),
            0,
        )
        acc = Accession(code="foo", species=sp)
        self.session.add(acc)
        self.session.commit()

        self.assertTrue(gen.active)
        # test the hybrid_property expression
        # pylint: disable=no-member  # is_
        gen_active_in_db = self.session.query(Genus).filter(
            Genus.active.is_(True)
        )
        self.assertIn(gen, gen_active_in_db)

    def test_active_one_plants_w_qty(self):
        from ..garden import Accession
        from ..garden import Location

        sp = self.session.get(Species, 26)
        acc = Accession(code="foo", species=sp)
        plt = Plant(
            code="1", accession=acc, quantity=1, location=Location(code="bar")
        )
        self.session.add_all([acc, plt])
        self.session.commit()
        gen = sp.genus

        self.assertTrue(gen.active)
        # test the hybrid_property expression
        # pylint: disable=no-member  # is_
        gen_active_in_db = self.session.query(Genus).filter(
            Genus.active.is_(True)
        )
        self.assertIn(gen, gen_active_in_db)

    def test_active_one_plants_wo_qty(self):
        from ..garden import Accession
        from ..garden import Location

        sp = self.session.get(Species, 26)
        gen = sp.genus
        acc = Accession(code="foo", species=sp)
        plt = Plant(
            code="1", accession=acc, quantity=0, location=Location(code="bar")
        )
        self.session.add_all([acc, plt])
        self.session.commit()

        self.assertFalse(gen.active)
        # test the hybrid_property expression
        # pylint: disable=no-member  # is_
        gen_active_in_db = self.session.query(Genus).filter(
            Genus.active.is_(True)
        )
        self.assertNotIn(gen, gen_active_in_db)


class GenusUpdatedTests(BaubleTestCase):

    def test_updated_self(self):
        fam = Family(epithet="Myrtaceae")
        gen = Genus(epithet="Syzygium", family=fam)
        self.session.add(gen)
        self.session.commit()

        self.assertIs(
            self.session.query(Genus).filter(Genus.updated > "Today").first(),
            gen,
        )

        # the python function
        self.assertEqual(gen.updated, gen._last_updated)

        date = datetime(2001, 1, 1, 0)
        gen._last_updated = date
        self.session.commit()

        self.assertIs(
            self.session.query(Genus).filter(Genus.updated == date).first(),
            gen,
        )

        # the python function
        self.assertEqual(gen.updated, gen._last_updated)

    def test_updated_notes(self):
        date = datetime(2001, 1, 1, 0)
        fam = Family(epithet="Myrtaceae")
        gen = Genus(epithet="Syzygium", family=fam, _last_updated=date)
        note = GenusNote(category="Spam", note="Eggs", genus=gen)
        self.session.add_all([gen, note])
        self.session.commit()

        self.assertIs(
            self.session.query(Genus).filter(Genus.updated > "Today").first(),
            gen,
        )

        # the python function
        self.assertEqual(gen.updated, note._last_updated)

        note._last_updated = datetime(2000, 1, 1, 0)
        self.session.commit()

        self.assertIs(
            self.session.query(Genus).filter(Genus.updated == date).first(),
            gen,
        )

        # the python function
        self.assertEqual(gen.updated, gen._last_updated)

    def test_updated_synonym(self):
        # make sure the date is not now
        date = datetime(2001, 1, 1, 0)
        fam = Family(epithet="Myrtaceae")
        gen = Genus(epithet="Melaleuca", family=fam, _last_updated=date)
        gen2 = Genus(epithet="Callistemon", family=fam, _last_updated=date)
        gen2.accepted = gen
        self.session.add_all([gen, gen2])
        self.session.commit()

        self.assertIs(
            self.session.query(Genus).filter(Genus.updated > "Today").first(),
            gen2,
        )

        # the python function
        self.assertEqual(gen2.updated, gen2._accepted._last_updated)


class GenusTopLevelCountTests(BaubleTestCase):
    def setUp(self):
        super().setUp()
        for func in get_setUp_data_funcs():
            func()

    def test_top_level_count_w_plant_qty(self):

        expected = (
            "Families: 2, "
            "Genera: 2, "
            "Species: 15, "
            "Accessions: 4, "
            "Plantings: 3, "
            "Living plants: 4, "
            "Locations: 1, "
            "Sources: 1"
        )

        self.assertEqual(str(Genus.top_level_count([1, 3])), expected)

    def test_top_level_count_wo_species(self):
        fam = Family(epithet="Welwitschiaceae")
        gen = Genus(epithet="Welwitschia", family=fam)
        self.session.add(gen)
        self.session.commit()

        expected = (
            "Families: 2, "
            "Genera: 2, "
            "Species: 11, "
            "Accessions: 2, "
            "Plantings: 1, "
            "Living plants: 1, "
            "Locations: 1, "
            "Sources: 1"
        )

        self.assertEqual(str(Genus.top_level_count([1, gen.id])), expected)

    def test_top_level_count_wo_plant_qty(self):
        plt = self.session.get(Plant, 1)
        self.session.delete(plt)
        plt = self.session.get(Plant, 2)
        plt.quantity = 0
        self.session.commit()

        expected = (
            "Families: 2, "
            "Genera: 2, "
            "Species: 15, "
            "Accessions: 4, "
            "Plantings: 2, "
            "Living plants: 3, "
            "Locations: 1, "
            "Sources: 1"
        )

        self.assertEqual(str(Genus.top_level_count([1, 3])), expected)

    def test_top_level_count_wo_plant_qty_exclude_inactive_set(self):
        plt = self.session.get(Plant, 1)
        self.session.delete(plt)
        plt = self.session.get(Plant, 2)
        plt.quantity = 0
        self.session.commit()

        expected = (
            "Families: 2, "
            "Genera: 2, "
            "Species: 15, "
            "Accessions: 3, "
            "Plantings: 1, "
            "Living plants: 3, "
            "Locations: 1, "
            "Sources: 1"
        )

        self.assertEqual(str(Genus.top_level_count([1, 3], True)), expected)


class GenusSynonymyTests(PlantTestCase):
    def setUp(self):
        super().setUp()
        f = (
            self.session.query(Family)
            .filter(Family.family == "Orchidaceae")
            .one()
        )
        bu = Genus(family=f, genus="Bulbophyllum")  # accepted
        zy = Genus(family=f, genus="Zygoglossum")  # synonym
        bu.synonyms.append(zy)
        self.session.add_all([f, bu, zy])
        self.session.commit()

    def test_forward_synonyms(self):
        "a taxon has a list of synonyms"
        bu = (
            self.session.query(Genus)
            .filter(Genus.genus == "Bulbophyllum")
            .one()
        )
        zy = (
            self.session.query(Genus)
            .filter(Genus.genus == "Zygoglossum")
            .one()
        )
        self.assertEqual(bu.synonyms, [zy])
        self.assertEqual(zy.synonyms, [])

    def test_backward_synonyms(self):
        "synonymy is used to get the accepted taxon"
        bu = (
            self.session.query(Genus)
            .filter(Genus.genus == "Bulbophyllum")
            .one()
        )
        zy = (
            self.session.query(Genus)
            .filter(Genus.genus == "Zygoglossum")
            .one()
        )
        self.assertEqual(zy.accepted, bu)
        self.assertEqual(bu.accepted, None)

    def test_define_accepted(self):
        # notice that same test should be also in Species and Family
        bu = (
            self.session.query(Genus)
            .filter(Genus.genus == "Bulbophyllum")
            .one()
        )
        f = (
            self.session.query(Family)
            .filter(Family.family == "Orchidaceae")
            .one()
        )
        he = Genus(family=f, genus="Henosis")  # one more synonym
        self.session.add(he)
        self.session.commit()
        self.assertEqual(len(bu.synonyms), 1)
        self.assertFalse(he in bu.synonyms)
        he.accepted = bu
        self.assertEqual(len(bu.synonyms), 2)
        self.assertTrue(he in bu.synonyms)

    def test_can_redefine_accepted(self):
        # Altamiranoa Rose used to refer to Villadia Rose for its accepted
        # name, it is now updated to Sedum L.

        # T_0
        claceae = Family(family="Crassulaceae")  # J. St.-Hil.
        villa = Genus(family=claceae, genus="Villadia", author="Rose")
        alta = Genus(family=claceae, genus="Altamiranoa", author="Rose")
        alta.accepted = villa
        self.session.add_all([claceae, alta, villa])
        self.session.commit()

        sedum = Genus(family=claceae, genus="Sedum", author="L.")
        alta.accepted = sedum
        self.session.commit()

    def test_no_synonyms_means_itself_accepted(self):
        def create_tmp_gen(id):
            gen = Genus(id=id, epithet="gen%02d" % id, family_id=1)
            self.session.add(gen)
            return gen

        gen1 = create_tmp_gen(51)
        self.session.commit()
        self.assertEqual(gen1.accepted, None)

    def test_synonyms_and_accepted_properties(self):
        def create_tmp_gen(id):
            gen = Genus(id=id, epithet="gen%02d" % id, family_id=1)
            self.session.add(gen)
            return gen

        # equivalence classes after changes
        gen1 = create_tmp_gen(41)
        gen2 = create_tmp_gen(42)
        gen3 = create_tmp_gen(43)
        gen4 = create_tmp_gen(44)  # (1), (2), (3), (4)
        gen3.accepted = gen1  # (1 3), (2), (4)
        self.assertEqual([i.epithet for i in gen1.synonyms], [gen3.epithet])
        gen1.synonyms.append(gen2)  # (1 3 2), (4)
        self.session.flush()
        self.assertEqual(gen2.accepted.epithet, gen1.epithet)  # just added
        self.assertEqual(gen3.accepted.epithet, gen1.epithet)  # no change
        gen2.accepted = gen4  # (1 3), (4 2)
        self.session.flush()
        self.assertEqual([i.epithet for i in gen4.synonyms], [gen2.epithet])
        self.assertEqual([i.epithet for i in gen1.synonyms], [gen3.epithet])
        self.assertEqual(gen1.accepted, None)
        self.assertEqual(gen2.accepted, gen4)
        self.assertEqual(gen3.accepted, gen1)
        self.assertEqual(gen4.accepted, None)
        gen2.accepted = gen4  # does not change anything
        self.assertEqual(gen1.accepted, None)
        self.assertEqual(gen2.accepted, gen4)
        self.assertEqual(gen3.accepted, gen1)
        self.assertEqual(gen4.accepted, None)
        gen2.accepted = gen2  # cannot be a synonym of itself
        self.assertRaises(IntegrityError, self.session.commit)


class SpeciesTests(PlantTestCase):
    def test_str(self):
        """
        Test the Species.string() method
        """

        def get_sp_str(id, **kwargs):
            return self.session.get(Species, id).string(**kwargs)

        for sid, expect in species_str_map.items():
            sp = self.session.get(Species, sid)
            printable_name = remove_zws("%s" % sp)
            self.assertEqual(species_str_map[sid], printable_name)
            spstr = get_sp_str(sid)
            self.assertEqual(remove_zws(spstr), expect)

            self.assertTrue(
                all(
                    i not in sp.str_basic for i in ("s. lat", "s. str", "agg.")
                )
            )

        for sid, expect in species_str_authors_map.items():
            spstr = get_sp_str(sid, authors=True)
            self.assertEqual(remove_zws(spstr), expect)

        for sid, expect in species_markup_map.items():
            spstr = get_sp_str(sid, markup=True)
            self.assertEqual(remove_zws(spstr), expect)

        for sid, expect in species_markup_authors_map.items():
            spstr = get_sp_str(sid, markup=True, authors=True)
            self.assertEqual(remove_zws(spstr), expect)

        for sid, expect in species_searchview_markup_map.items():
            spstr = get_sp_str(
                sid, markup=True, authors=True, for_search_view=True
            )
            self.assertEqual(remove_zws(spstr), expect)

    def test_lexicographic_order__unspecified_precedes_specified(self):
        def get_sp_str(id, **kwargs):
            return self.session.get(Species, id).string(**kwargs)

        self.assertTrue(get_sp_str(1) > get_sp_str(22))
        self.assertTrue(get_sp_str(1) > get_sp_str(23))
        self.assertTrue(get_sp_str(1) > get_sp_str(24))
        self.assertTrue(get_sp_str(16) > get_sp_str(22))
        self.assertTrue(get_sp_str(16) > get_sp_str(23))
        self.assertTrue(get_sp_str(16) > get_sp_str(24))

    def test_vernacular_name(self):
        """
        Test the Species.vernacular_name property
        """
        family = Family(family="family")
        genus = Genus(family=family, genus="genus")
        sp = Species(genus=genus, sp="sp")
        self.session.add_all([family, genus, sp])
        self.session.commit()

        # add a name
        vn = VernacularName(name="name")
        sp.vernacular_names.append(vn)
        self.session.commit()
        self.assertTrue(vn in sp.vernacular_names)

        # test that removing a name removes deleted orphaned objects
        sp.vernacular_names.remove(vn)
        self.session.commit()
        q = self.session.query(VernacularName).filter_by(species_id=sp.id)
        self.assertRaises(NoResultFound, q.one)

    def test_default_vernacular_name(self):
        """
        Test the Species.default_vernacular_name property
        """
        family = Family(family="family")
        genus = Genus(family=family, genus="genus")
        sp = Species(genus=genus, sp="sp")
        vn = VernacularName(name="name")
        sp.vernacular_names.append(vn)
        self.session.add_all([family, genus, sp, vn])
        self.session.commit()

        # test that setting the default vernacular names
        default = VernacularName(name="default")
        sp.default_vernacular_name = default
        self.session.commit()
        self.assertTrue(vn in sp.vernacular_names)
        self.assertTrue(sp.default_vernacular_name == default)

        # test that set_attr work on default vernacular name
        default = VernacularName(name="default2")
        setattr(sp, "default_vernacular_name", default)
        self.session.commit()
        self.assertTrue(vn in sp.vernacular_names)
        self.assertTrue(default in sp.vernacular_names)
        self.assertTrue(sp.default_vernacular_name == default)

        # test that if you set the default_vernacular_name on a
        # species then it automatically adds it to vernacular_names
        default = VernacularName(name="default3")
        sp.default_vernacular_name = default
        self.session.commit()
        self.assertTrue(vn in sp.vernacular_names)
        self.assertTrue(default in sp.vernacular_names)
        self.assertTrue(sp.default_vernacular_name == default)

        # test that removing a vernacular name removes it from
        # default_vernacular_name, this test also effectively tests VNList
        dvid = int(sp._default_vernacular_name.id)
        sp.vernacular_names.remove(default)
        self.session.commit()
        self.assertEqual(sp.default_vernacular_name, None)
        q = self.session.query(DefaultVernacularName)
        self.assertRaises(NoResultFound, q.filter_by(species_id=sp.id).one)
        self.assertRaises(NoResultFound, q.filter_by(id=dvid).one)

        # test that setting default_vernacular_name to None
        # removes the name properly and deletes any orphaned objects
        sp.vernacular_names.append(vn)
        sp.default_vernacular_name = vn
        self.session.commit()
        dvid = sp._default_vernacular_name.id
        sp.default_vernacular_name = None
        self.session.commit()
        q = self.session.query(DefaultVernacularName)
        self.assertRaises(NoResultFound, q.filter_by(species_id=sp.id).one)
        self.assertRaises(NoResultFound, q.filter_by(id=dvid).one)

        # test that calling __del__ on a default vernacular name removes it
        sp.default_vernacular_name = vn
        self.session.commit()
        dvid = sp._default_vernacular_name.id
        del sp.default_vernacular_name
        self.session.commit()
        self.assertEqual(sp.default_vernacular_name, None)
        q = self.session.query(DefaultVernacularName)
        self.assertRaises(NoResultFound, q.filter_by(species_id=sp.id).one)
        self.assertRaises(NoResultFound, q.filter_by(id=dvid).one)

        # test for regression in bug Launchpad #123286
        vn1 = VernacularName(name="vn1")
        vn2 = VernacularName(name="vn2")
        sp.default_vernacular_name = vn1
        sp.default_vernacular_name = vn2
        self.session.commit()

        # test hybrid property setter and expression
        q = (
            self.session.query(Species)
            .filter(Species.default_vernacular_name == "vn2")
            .one()
        )
        self.assertEqual(q, sp)
        sp.default_vernacular_name = "hybrid set"
        self.session.commit()
        self.assertEqual(sp.default_vernacular_name.name, "hybrid set")
        self.assertIsNone(sp.default_vernacular_name.language)
        # Test the language is added
        sp.default_vernacular_name = "set hybrid:Lang"
        self.session.commit()
        self.assertEqual(sp.default_vernacular_name.name, "set hybrid")
        self.assertEqual(sp.default_vernacular_name.language, "Lang")

    def test_accepted_low_level(self):
        sp1 = self.session.get(Species, 2)
        sp2 = self.session.get(Species, 3)
        sp3 = self.session.get(Species, 4)
        sp1.accepted = sp2
        self.session.commit()
        self.assertEqual(sp1.accepted, sp2)
        self.assertIn(sp1, sp2.synonyms)
        sp1.accepted = sp3
        self.session.commit()
        self.assertEqual(sp1.accepted, sp3)
        self.assertIn(sp1, sp3.synonyms)
        self.assertNotIn(sp1, sp2.synonyms)
        sp1.accepted = sp1
        self.assertRaises(IntegrityError, self.session.commit)
        self.session.rollback()
        self.assertNotIn(sp1, sp1.synonyms)
        self.assertEqual(sp1.accepted, sp3)
        sp1.accepted = None
        self.session.commit()
        self.assertIsNone(sp1.accepted)
        self.assertNotIn(sp1, sp3.synonyms)

    def test_synonyms_low_level(self):
        """
        Test the Species.synonyms property
        """
        load_sp = lambda id: self.session.get(Species, id)

        def syn_str(id1, id2, isit="not"):
            sp1 = load_sp(id1)
            sp2 = load_sp(id2)
            return "%s(%s).synonyms: %s" % (
                sp1,
                sp1.id,
                str(["%s(%s)" % (s, s.id) for s in sp1.synonyms]),
            )

        def synonym_of(id1, id2):
            sp1 = load_sp(id1)
            sp2 = load_sp(id2)
            return sp2 in sp1.synonyms

        # test that appending a synonym works using species.synonyms
        sp1 = load_sp(1)
        sp2 = load_sp(2)
        sp1.synonyms.append(sp2)
        self.session.flush()
        self.assertTrue(synonym_of(1, 2), syn_str(1, 2))

        # test that removing a synonyms works using species.synonyms
        sp1.synonyms.remove(sp2)
        self.session.flush()
        self.assertFalse(synonym_of(1, 2), syn_str(1, 2))

        self.session.expunge_all()

        # test that appending a synonym works using species._synonyms
        sp1 = load_sp(1)
        sp2 = load_sp(2)
        syn = SpeciesSynonym(synonym=sp2)
        sp1._synonyms.append(syn)
        self.session.flush()
        self.assertTrue(synonym_of(1, 2), syn_str(1, 2))

        # test that removing a synonyms works using species._synonyms
        sp1._synonyms.remove(syn)
        self.session.flush()
        self.assertFalse(synonym_of(1, 2), syn_str(1, 2))

        # test adding a species and then immediately remove it
        self.session.expunge_all()
        sp1 = load_sp(1)
        sp2 = load_sp(2)
        sp1.synonyms.append(sp2)
        sp1.synonyms.remove(sp2)
        import warnings

        # SAWarning: Object of type <SpeciesSynonym> not in session, add
        # operation along 'Species._accepted' will not proceed
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            self.session.commit()
        assert sp2 not in sp1.synonyms

        # add a species and immediately add the same species
        sp2 = load_sp(2)
        sp1.synonyms.append(sp2)
        sp1.synonyms.remove(sp2)
        sp1.synonyms.append(sp2)
        # self.session.flush() # shouldn't raise an error
        self.session.commit()
        assert sp2 in sp1.synonyms

        # test that deleting a species removes it from the synonyms list
        assert sp2 in sp1.synonyms
        self.session.delete(sp2)
        self.session.commit()
        assert sp2 not in sp1.synonyms
        # but doesn't delete the species it referes to.
        self.assertTrue(self.session.get(Species, sp1.id))

        # test that deleting a species that has synonyms deletes all
        # the synonyms that refer to that species
        sp3 = Species(genus=self.session.get(Genus, 1), epithet="three")
        self.session.add(sp3)
        sp1.synonyms.append(sp3)
        self.session.commit()
        self.session.delete(sp1)
        self.session.commit()
        self.assertTrue(self.session.query(SpeciesSynonym).count() == 0)

    def test_adding_synonym_doesnt_add_sp_history_entry(self):
        # update all full names so listens_for doesn't make the a change
        list(update_all_full_names_task())
        sp1 = self.session.get(Species, 5)
        sp2 = self.session.get(Species, 6)
        hist_start = self.session.query(db.History).count()
        # this should not update the species
        sp1.synonyms.append(sp2)
        self.session.commit()
        hist_end = self.session.query(db.History).count()
        self.assertEqual(hist_end, hist_start + 1)

    def test_no_synonyms_means_itself_accepted(self):
        def create_tmp_sp(id):
            sp = Species(id=id, epithet="sp%02d" % id, genus_id=1)
            self.session.add(sp)
            return sp

        sp1 = create_tmp_sp(51)
        sp2 = create_tmp_sp(52)
        sp3 = create_tmp_sp(53)
        sp4 = create_tmp_sp(54)
        self.session.commit()
        self.assertEqual(sp1.accepted, None)
        self.assertEqual(sp2.accepted, None)
        self.assertEqual(sp3.accepted, None)
        self.assertEqual(sp4.accepted, None)

    def test_synonyms_and_accepted_properties(self):
        def create_tmp_sp(id):
            sp = Species(id=id, epithet="sp%02d" % id, genus_id=1)
            self.session.add(sp)
            return sp

        # equivalence classes after changes
        sp1 = create_tmp_sp(41)
        sp2 = create_tmp_sp(42)
        sp3 = create_tmp_sp(43)
        sp4 = create_tmp_sp(44)  # (1), (2), (3), (4)
        sp3.accepted = sp1  # (1 3), (2), (4)
        self.assertEqual([i.epithet for i in sp1.synonyms], [sp3.epithet])
        sp1.synonyms.append(sp2)  # (1 3 2), (4)
        self.session.flush()
        self.assertEqual(sp2.accepted.epithet, sp1.epithet)  # just added
        self.assertEqual(sp3.accepted.epithet, sp1.epithet)  # no change
        sp2.accepted = sp4  # (1 3), (4 2)
        self.session.flush()
        self.assertEqual([i.epithet for i in sp4.synonyms], [sp2.epithet])
        self.assertEqual([i.epithet for i in sp1.synonyms], [sp3.epithet])
        self.assertEqual(sp1.accepted, None)
        self.assertEqual(sp2.accepted, sp4)
        self.assertEqual(sp3.accepted, sp1)
        self.assertEqual(sp4.accepted, None)
        sp2.accepted = sp4  # does not change anything
        self.assertEqual(sp1.accepted, None)
        self.assertEqual(sp2.accepted, sp4)
        self.assertEqual(sp3.accepted, sp1)
        self.assertEqual(sp4.accepted, None)

    def test_synonym_str(self):
        syn = self.session.execute(select(SpeciesSynonym)).scalar()
        self.assertEqual(str(syn), syn.synonym.string(author=True))

    def test_synonym_markup(self):
        syn = self.session.execute(select(SpeciesSynonym)).scalar()
        self.assertEqual(syn.markup(), syn.synonym.markup(authors=True))

    def test_active_no_accessions(self):

        fam = Family(family="Myrtaceae")
        gen = Genus(epithet="Syzygium", family=fam)
        sp = Species(epithet="australe", genus=gen)
        self.session.add_all([fam, gen, sp])
        self.session.commit()
        self.assertTrue(sp.active)
        # test the hybrid_property expression
        # pylint: disable=no-member
        sp_active_in_db = self.session.query(Species).filter(
            Species.active.is_(True)
        )
        self.assertIn(sp, sp_active_in_db)

    def test_active_no_plants(self):
        from ..garden.accession import Accession

        fam = Family(family="Myrtaceae")
        gen = Genus(epithet="Syzygium", family=fam)
        sp = Species(epithet="australe", genus=gen)
        acc = Accession(species=sp, code="1")
        self.session.add_all([fam, gen, sp, acc])
        self.session.commit()
        self.assertTrue(sp.active)
        # test the hybrid_property expression
        # pylint: disable=no-member
        sp_active_in_db = self.session.query(Species).filter(
            Species.active.is_(True)
        )
        self.assertIn(sp, sp_active_in_db)

    def test_active_plants_w_qty(self):
        from ..garden import Accession
        from ..garden import Location

        fam = Family(family="Myrtaceae")
        gen = Genus(epithet="Syzygium", family=fam)
        sp = Species(epithet="australe", genus=gen)
        acc = Accession(species=sp, code="1")
        plant = Plant(
            accession=acc,
            quantity=1,
            location=Location(name="site", code="STE"),
            code="1",
        )
        self.session.add_all([fam, gen, sp, acc, plant])
        self.session.commit()
        self.assertTrue(sp.active)
        # test the hybrid_property expression
        # pylint: disable=no-member
        sp_active_in_db = self.session.query(Species).filter(
            Species.active.is_(True)
        )
        self.assertIn(sp, sp_active_in_db)

    def test_active_plants_wo_qty(self):
        from ..garden import Accession
        from ..garden import Location

        fam = Family(family="Myrtaceae")
        gen = Genus(epithet="Syzygium", family=fam)
        sp = Species(epithet="australe", genus=gen)
        acc = Accession(species=sp, code="1")
        plant = Plant(
            accession=acc,
            quantity=0,
            location=Location(name="site", code="STE"),
            code="1",
        )
        self.session.add_all([fam, gen, sp, acc, plant])
        self.session.commit()
        self.assertFalse(sp.active)
        self.assertFalse(plant.active)
        # test the hybrid_property expression
        # pylint: disable=no-member
        sp_active_in_db = self.session.query(Species).filter(
            Species.active.is_(True)
        )
        self.assertNotIn(sp, sp_active_in_db)

    def test_count_children_wo_plants(self):
        from ..garden import Accession

        fam = Family(family="Myrtaceae")
        gen = Genus(epithet="Syzygium", family=fam)
        sp = Species(epithet="australe", genus=gen)
        acc = Accession(species=sp, code="1")
        self.session.add_all([fam, gen, sp, acc])
        self.session.commit()

        self.assertEqual(sp.count_children(), 1)

    def test_count_children_w_plant_w_qty(self):
        from ..garden import Accession
        from ..garden import Location

        fam = Family(family="Myrtaceae")
        gen = Genus(epithet="Syzygium", family=fam)
        sp = Species(epithet="australe", genus=gen)
        acc = Accession(species=sp, code="1")
        plant = Plant(
            accession=acc,
            quantity=1,
            location=Location(name="site", code="STE"),
            code="1",
        )
        self.session.add_all([fam, gen, sp, acc, plant])
        self.session.commit()

        self.assertEqual(sp.count_children(), 1)

    def test_count_children_w_plant_w_qty_exclude_inactive_set(self):
        # should be the same as if exclude inactive not set.
        from ..garden import Accession
        from ..garden import Location

        fam = Family(family="Myrtaceae")
        gen = Genus(epithet="Syzygium", family=fam)
        sp = Species(epithet="australe", genus=gen)
        acc = Accession(species=sp, code="1")
        plant = Plant(
            accession=acc,
            quantity=1,
            location=Location(name="site", code="STE"),
            code="1",
        )
        self.session.add_all([fam, gen, sp, acc, plant])
        self.session.commit()

        prefs.prefs[prefs.exclude_inactive_pref] = True

        self.assertEqual(sp.count_children(), 1)

    def test_count_children_w_plant_wo_qty(self):
        from ..garden import Accession
        from ..garden import Location

        fam = Family(family="Myrtaceae")
        gen = Genus(epithet="Syzygium", family=fam)
        sp = Species(epithet="australe", genus=gen)
        acc = Accession(species=sp, code="1")
        plant = Plant(
            accession=acc,
            quantity=0,
            location=Location(name="site", code="STE"),
            code="1",
        )
        self.session.add_all([fam, gen, sp, acc, plant])
        self.session.commit()

        self.assertEqual(sp.count_children(), 1)

    def test_count_children_w_plant_wo_qty_exclude_inactive_set(self):
        from ..garden import Accession
        from ..garden import Location

        fam = Family(family="Myrtaceae")
        gen = Genus(epithet="Syzygium", family=fam)
        sp = Species(epithet="australe", genus=gen)
        acc = Accession(species=sp, code="1")
        plant = Plant(
            accession=acc,
            quantity=0,
            location=Location(name="site", code="STE"),
            code="1",
        )
        self.session.add_all([fam, gen, sp, acc, plant])
        self.session.commit()

        prefs.prefs[prefs.exclude_inactive_pref] = True

        self.assertEqual(sp.count_children(), 0)

    def test_custom_column_acts_as_unicode_before_init(self):
        sp = self.session.query(Species).first()
        sp._sp_custom1 = "test"
        self.session.commit()
        self.assertEqual(sp._sp_custom1, "test")

    def test_custom_column(self):
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

        register_custom_column("_sp_custom1")

        self.assertTrue(hasattr(Species, "nca_status"))
        self.assertEqual(
            Species._sp_custom1.prop.columns[0].type.values,
            ("extinct", "vulnerable", None),
        )
        self.assertRaises(
            btypes.EnumError,
            Species._sp_custom1.prop.columns[0].type.process_bind_param,
            "test",
            None,
        )
        sp = self.session.get(Species, 1)
        self.assertEqual(
            sp.__table__.c["_sp_custom1"].type.values,
            ("extinct", "vulnerable", None),
        )
        self.assertRaises(
            btypes.EnumError,
            sp.__table__.c["_sp_custom1"].type.process_bind_param,
            "test",
            None,
        )

        sp.nca_status = "vulnerable"
        self.session.commit()

        # restart connection
        self.session.close()
        db.open_conn(db.engine.url)
        self.session = db.Session()
        sp = self.session.get(Species, 1)

        self.assertEqual(sp.nca_status, "vulnerable")
        # can't set value when not in values
        with self.assertRaises(AttributeError):
            sp.nca_status = "test"
        self.assertEqual(sp.nca_status, "vulnerable")

        with self.assertRaises(StatementError):
            sp._sp_custom1 = "test"
            self.session.commit()
        self.session.rollback()
        self.assertEqual(sp.nca_status, "vulnerable")
        sp.nca_status = "extinct"
        self.session.commit()
        # test can filter by custom column
        session = db.Session()
        qry = session.query(Species).filter(Species.nca_status == "extinct")
        self.assertEqual(qry.first().id, sp.id)
        session.close()
        # cleanup
        self.session.delete(meta)
        self.session.commit()
        register_custom_column("_sp_custom1")

        # reset the connection (similar to opening a new connection, also
        # reruns register_custom_column etc.)
        # tearDown needed to delete temp config file or conftest.py will fail
        # to cleanup tempfiles at end of tests
        self.tearDown()
        self.setUp()
        self.assertFalse(hasattr(Species, "nca_status"))

    def test_family_name_hybrid_property(self):
        # property
        sp = self.session.get(Species, 1)
        self.assertEqual(sp.family_name, "Orchidaceae")
        # expression
        palms = self.session.query(Species.id).filter(
            Species.family_name == "Arecaceae"
        )
        palm_ids = [i[0] for i in palms]
        self.assertCountEqual(palm_ids, [26])

    def test_pictures_property_wo_pics(self):
        sp = self.session.get(Species, 1)
        self.assertEqual(sp.pictures, [])

    def test_pictures_property_w_pics(self):
        sp = self.session.get(Species, 1)
        pic1 = SpeciesPicture(picture="test1.jpg")
        sp._pictures.append(pic1)
        self.assertEqual(sp.pictures, [pic1])

    def test_pictures_property_w_plant_pics(self):
        from ..garden import Accession
        from ..garden import Location
        from ..garden.plant import PlantPicture

        fam = Family(family="Myrtaceae")
        gen = Genus(epithet="Syzygium", family=fam)
        sp = Species(epithet="australe", genus=gen)
        acc = Accession(species=sp, code="1")
        loc = Location(name="site", code="STE")
        plant = Plant(
            accession=acc,
            quantity=1,
            location=loc,
            code="1",
        )
        pic1 = PlantPicture(picture="test1.jpg")
        plant.pictures.append(pic1)
        plant2 = Plant(
            accession=acc,
            quantity=1,
            location=loc,
            code="2",
        )
        pic2 = PlantPicture(picture="test2.jpg")
        plant2.pictures.append(pic2)
        self.session.add_all([plant, plant2])
        self.session.commit()
        self.assertCountEqual(sp.pictures, [pic1, pic2])

    def test_pictures_property_w_pics_and_plant_pics(self):
        from ..garden import Accession
        from ..garden import Location
        from ..garden.plant import PlantPicture

        fam = Family(family="Myrtaceae")
        gen = Genus(epithet="Syzygium", family=fam)
        sp = Species(epithet="australe", genus=gen)
        pic1 = SpeciesPicture(picture="test1.jpg")
        sp._pictures.append(pic1)
        acc = Accession(species=sp, code="1")
        loc = Location(name="site", code="STE")
        plant = Plant(
            accession=acc,
            quantity=1,
            location=loc,
            code="1",
        )
        pic2 = PlantPicture(picture="test1.jpg")
        plant.pictures.append(pic2)
        plant2 = Plant(
            accession=acc,
            quantity=1,
            location=loc,
            code="2",
        )
        pic3 = PlantPicture(picture="test2.jpg")
        plant2.pictures.append(pic3)
        self.session.add_all([plant, plant2])
        self.session.commit()
        self.assertCountEqual(sp.pictures, [pic1, pic2, pic3])
        # exclude inactive
        plant2.quantity = 0
        self.session.commit()
        prefs.prefs[prefs.exclude_inactive_pref] = True
        self.assertCountEqual(sp.pictures, [pic1, pic2])
        # detached returns empty
        self.session.expunge(sp)
        self.assertEqual(sp.pictures, [])


class SpeciesUpdatedTests(BaubleTestCase):

    def test_updated_self(self):
        fam = Family(epithet="Myrtaceae")
        gen = Genus(epithet="Syzygium", family=fam)
        sp = Species(epithet="luehmannii", genus=gen)
        self.session.add(sp)
        self.session.commit()

        self.assertIs(
            self.session.query(Species)
            .filter(Species.updated > "Today")
            .first(),
            sp,
        )

        # the python function
        self.assertEqual(sp.updated, sp._last_updated)

        date = datetime(2001, 1, 1, 0)
        sp._last_updated = date
        self.session.commit()

        self.assertIs(
            self.session.query(Species)
            .filter(Species.updated == date)
            .first(),
            sp,
        )

        # the python function
        self.assertEqual(sp.updated, sp._last_updated)

    def test_updated_notes(self):
        date = datetime(2001, 1, 1, 0)
        fam = Family(epithet="Myrtaceae")
        gen = Genus(epithet="Syzygium", family=fam)
        sp = Species(epithet="luehmannii", genus=gen, _last_updated=date)
        note = SpeciesNote(category="Spam", note="Eggs", species=sp)
        self.session.add_all([sp, note])
        self.session.commit()

        self.assertIs(
            self.session.query(Species)
            .filter(Species.updated > "Today")
            .first(),
            sp,
        )

        # the python function
        self.assertEqual(sp.updated, note._last_updated)

        note._last_updated = datetime(2000, 1, 1, 0)
        self.session.commit()

        self.assertIs(
            self.session.query(Species)
            .filter(Species.updated == date)
            .first(),
            sp,
        )

        # the python function
        self.assertEqual(sp.updated, sp._last_updated)

    def test_updated_pictures(self):
        date = datetime(2001, 1, 1, 0)
        fam = Family(epithet="Myrtaceae")
        gen = Genus(epithet="Syzygium", family=fam)
        sp = Species(epithet="luehmannii", genus=gen, _last_updated=date)
        pic = SpeciesPicture(category="Spam", picture="Eggs.png", species=sp)
        self.session.add_all([sp, pic])
        self.session.commit()

        self.assertIs(
            self.session.query(Species)
            .filter(Species.updated > "Today")
            .first(),
            sp,
        )

        # the python function
        self.assertEqual(sp.updated, pic._last_updated)

        pic._last_updated = datetime(2000, 1, 1, 0)
        self.session.commit()

        self.assertIs(
            self.session.query(Species)
            .filter(Species.updated == date)
            .first(),
            sp,
        )

        # the python function
        self.assertEqual(sp.updated, sp._last_updated)

    def test_updated_synonym(self):
        # make sure the date is not now
        date = datetime(2001, 1, 1, 0)
        fam = Family(epithet="Myrtaceae")
        gen = Genus(epithet="Melaleuca", family=fam)
        gen2 = Genus(epithet="Callistemon", family=fam)
        sp1 = Species(epithet="viminalis", genus=gen, _last_updated=date)
        sp2 = Species(epithet="viminalis", genus=gen2, _last_updated=date)
        sp2.accepted = sp1
        self.session.add_all([sp1, sp2])
        self.session.commit()

        self.assertIs(
            self.session.query(Species)
            .filter(Species.updated > "Today")
            .first(),
            sp2,
        )

        # the python function
        self.assertEqual(sp2.updated, sp2._accepted._last_updated)

    def test_updated_distribution(self):
        # make sure the date is not now
        date = datetime(2001, 1, 1, 0)
        fam = Family(epithet="Myrtaceae")
        gen = Genus(epithet="Melaleuca", family=fam)
        sp = Species(epithet="viminalis", genus=gen, _last_updated=date)
        geo = Geography(name="Fiji", code="FIJ", level="1")
        sp.distribution.append(SpeciesDistribution(geography=geo))
        self.session.add(sp)
        self.session.commit()

        self.assertIs(
            self.session.query(Species)
            .filter(Species.updated > "Today")
            .first(),
            sp,
        )

        # the python function
        self.assertEqual(sp.updated, sp.distribution[0]._last_updated)
        self.assertNotEqual(sp.updated, sp._last_updated)

    def test_updated_vernacular_name(self):
        # make sure the date is not now
        date = datetime(2001, 1, 1, 0)
        fam = Family(epithet="Myrtaceae")
        gen = Genus(epithet="Melaleuca", family=fam)
        sp = Species(epithet="viminalis", genus=gen, _last_updated=date)
        vern = VernacularName(name="Bottle Brush")
        sp.vernacular_names.append(vern)
        self.session.add(sp)
        self.session.commit()

        self.assertIs(
            self.session.query(Species)
            .filter(Species.updated > "Today")
            .first(),
            sp,
        )

        # the python function
        self.assertEqual(sp.updated, sp.vernacular_names[0]._last_updated)
        self.assertNotEqual(sp.updated, sp._last_updated)


class SpeciesTopLevelCountTests(BaubleTestCase):
    def setUp(self):
        super().setUp()
        for func in get_setUp_data_funcs():
            func()

    def test_top_level_count_w_plant_qty(self):

        expected = (
            "Families: 2, "
            "Genera: 2, "
            "Species: 2, "
            "Accessions: 4, "
            "Plantings: 3, "
            "Living plants: 4, "
            "Locations: 1, "
            "Sources: 1"
        )

        self.assertEqual(str(Species.top_level_count([1, 3])), expected)

    def test_top_level_count_wo_plant_qty(self):
        plt = self.session.get(Plant, 1)
        self.session.delete(plt)
        plt = self.session.get(Plant, 2)
        plt.quantity = 0
        self.session.commit()

        expected = (
            "Families: 2, "
            "Genera: 2, "
            "Species: 2, "
            "Accessions: 4, "
            "Plantings: 2, "
            "Living plants: 3, "
            "Locations: 1, "
            "Sources: 1"
        )

        self.assertEqual(str(Species.top_level_count([1, 3])), expected)

    def test_top_level_count_wo_plant_qty_exclude_inactive_set(self):
        plt = self.session.get(Plant, 1)
        self.session.delete(plt)
        plt = self.session.get(Plant, 2)
        plt.quantity = 0
        self.session.commit()

        expected = (
            "Families: 2, "
            "Genera: 2, "
            "Species: 2, "
            "Accessions: 3, "
            "Plantings: 1, "
            "Living plants: 3, "
            "Locations: 1, "
            "Sources: 1"
        )

        self.assertEqual(str(Species.top_level_count([1, 3], True)), expected)

    def test_top_level_count_sp_wo_plant_qty_exclude_inactive_set(self):
        plt = self.session.get(Plant, 1)
        for acc in plt.accession.species.accessions:

            if not acc.plants:
                self.session.delete(acc)
                continue

            for plt in acc.plants:
                plt.quantity = 0

        self.session.commit()

        expected = (
            "Families: 1, "
            "Genera: 1, "
            "Species: 1, "
            "Accessions: 1, "
            "Plantings: 1, "
            "Living plants: 3, "
            "Locations: 1, "
            "Sources: 0"
        )

        self.assertEqual(str(Species.top_level_count([1, 3], True)), expected)

    def test_top_level_count_sp_no_accessions(self):

        expected = (
            "Families: 2, "
            "Genera: 2, "
            "Species: 2, "
            "Accessions: 2, "
            "Plantings: 1, "
            "Living plants: 1, "
            "Locations: 1, "
            "Sources: 1"
        )

        # 4 has no accessions
        self.assertEqual(str(Species.top_level_count([1, 4])), expected)


class VernacularNameTests(BaubleTestCase):
    def test_has_children_same_as_species(self):
        for vern in self.session.query(VernacularName):

            self.assertEqual(vern.has_children(), vern.species.has_children())

    def test_count_children_same_as_species(self):
        for vern in self.session.query(VernacularName):

            self.assertEqual(
                vern.count_children(), vern.species.count_children()
            )

    def test_pictures_same_as_species(self):
        for vern in self.session.query(VernacularName):
            sp_pic = SpeciesPicture(picture="foo.jpg")
            vern.species.pictures.append(sp_pic)

            self.assertEqual(vern.pictures, vern.species.pictures)

    def test_active_same_as_species(self):
        for vern in self.session.query(VernacularName):

            self.assertEqual(vern.active, vern.species.active)

    def test_active_expresion_returns_same_as_species(self):
        # pylint: disable=no-member
        verns = self.session.query(VernacularName).filter(
            VernacularName.active.is_(True)
        )
        spp = self.session.query(Species).filter(Species.active.is_(True))

        self.assertCountEqual(
            [i.id for i in spp], [i.species.id for i in verns]
        )

    def test_top_level_count_same_as_species(self):
        for func in get_setUp_data_funcs():
            func()

        verns = self.session.query(VernacularName).all()
        vern_ids = [i.id for i in verns]
        sp_ids = [i.species_id for i in verns]

        self.assertEqual(
            str(VernacularName.top_level_count(vern_ids)),
            str(Species.top_level_count(sp_ids)),
        )

        self.assertEqual(
            VernacularName.top_level_count(vern_ids, True),
            Species.top_level_count(sp_ids, True),
        )


class MarkupItalicsTests(TestCase):
    def test_markup_simple(self):
        self.assertEqual(markup_italics("sp."), "sp.")
        self.assertEqual(markup_italics("spp."), "spp.")
        self.assertEqual(markup_italics("cv."), "cv.")
        self.assertEqual(markup_italics("cvs."), "cvs.")
        self.assertEqual(markup_italics("viminalis"), "<i>viminalis</i>")
        # with ZWS
        self.assertEqual(
            markup_italics("\u200bviminalis"), "\u200b<i>viminalis</i>"
        )
        self.assertEqual(markup_italics("crista-galli"), "<i>crista-galli</i>")

    def test_markup_provisory(self):
        self.assertEqual(
            markup_italics("sp. (Shute Harbour L.J.Webb+ 7916)"),
            "sp. (Shute Harbour L.J.Webb+ 7916)",
        )
        self.assertEqual(
            markup_italics("caerulea (Shute Harbour)"),
            "<i>caerulea</i> (Shute Harbour)",
        )

    def test_markup_nothospecies(self):
        self.assertEqual(
            markup_italics("\xd7 grandiflora"), "\xd7 <i>grandiflora</i>"
        )
        self.assertEqual(
            markup_italics("\xd7grandiflora"), "\xd7<i>grandiflora</i>"
        )

    def test_markup_species_hybrid(self):
        self.assertEqual(
            markup_italics("lilliputiana \xd7 compacta \xd7 ampullacea"),
            "<i>lilliputiana</i> \xd7 <i>compacta</i> \xd7 <i>ampullacea</i>",
        )

    def test_markup_infraspecific_hybrid(self):
        self.assertEqual(
            markup_italics(
                "wilsonii subsp. cryptophlebium \xd7 wilsonii subsp. wilsonii"
            ),
            "<i>wilsonii</i> subsp. <i>cryptophlebium</i> \xd7 "
            "<i>wilsonii</i> subsp. <i>wilsonii</i>",
        )
        # with ZWS
        self.assertEqual(
            markup_italics(
                "\u200bwilsonii subsp. cryptophlebium \xd7 wilsonii subsp. "
                "wilsonii"
            ),
            "\u200b<i>wilsonii</i> subsp. <i>cryptophlebium</i> \xd7 "
            "<i>wilsonii</i> subsp. <i>wilsonii</i>",
        )

    def test_markup_species_cv_hybrid(self):
        self.assertEqual(
            markup_italics("carolinae \xd7 'Hot Wizz'"),
            "<i>carolinae</i> \xd7 'Hot Wizz'",
        )

    def test_markup_complex_hybrid(self):
        self.assertEqual(
            markup_italics(
                "(carolinae \xd7 'Purple Star') \xd7 (compacta \xd7 sp.)"
            ),
            "(<i>carolinae</i> \xd7 'Purple Star') \xd7 (<i>compacta</i> "
            "\xd7 sp.)",
        )

        self.assertEqual(
            markup_italics(
                "(('Gee Whizz' \xd7 'Fireball' \xd7 compacta) \xd7 "
                "'Purple Star') \xd7 lilliputiana"
            ),
            "(('Gee Whizz' \xd7 'Fireball' \xd7 <i>compacta</i>) \xd7 "
            "'Purple Star') \xd7 <i>lilliputiana</i>",
        )
        self.assertEqual(
            markup_italics(
                "'Gee Whizz' \xd7 ('Fireball' \xd7 (compacta \xd7 "
                "'Purple Star')) \xd7 lilliputiana"
            ),
            "'Gee Whizz' \xd7 ('Fireball' \xd7 (<i>compacta</i> \xd7 "
            "'Purple Star')) \xd7 <i>lilliputiana</i>",
        )
        self.assertEqual(
            markup_italics("carolinae 'Tricolor' \xd7 compacta"),
            "<i>carolinae</i> 'Tricolor' \xd7 <i>compacta</i>",
        )
        self.assertEqual(
            markup_italics("carolinae \xd7 sp. (pink and red)"),
            "<i>carolinae</i> \xd7 sp. (pink and red)",
        )

    def test_markup_complex_hybrid_zws(self):
        self.assertEqual(
            markup_italics(
                "\u200b(carolinae \xd7 'Purple Star') \xd7 (compacta "
                "\xd7 sp.)"
            ),
            "\u200b(<i>carolinae</i> \xd7 'Purple Star') \xd7 "
            "(<i>compacta</i> \xd7 sp.)",
        )
        self.assertEqual(
            markup_italics("\u200bcarolinae \xd7 sp. (pink and red)"),
            "\u200b<i>carolinae</i> \xd7 sp. (pink and red)",
        )

    def test_markup_provisory_hybrid(self):
        self.assertEqual(
            markup_italics(
                "sp. \xd7 sp. (South Molle Island J.P.GrestyAQ208995)"
            ),
            "sp. \xd7 sp. (South Molle Island J.P.GrestyAQ208995)",
        )

    def test_markup_nothospecies_hybrid(self):
        self.assertEqual(
            markup_italics("gymnocarpa \xd7 \xd7grandiflora"),
            "<i>gymnocarpa</i> \xd7 \xd7<i>grandiflora</i>",
        )
        self.assertEqual(
            markup_italics("gymnocarpa \xd7 \xd7 grandiflora"),
            "<i>gymnocarpa</i> \xd7 \xd7 <i>grandiflora</i>",
        )
        # with ZWS
        self.assertEqual(
            markup_italics("\u200b\xd7 grandiflora"),
            "\u200b\xd7 <i>grandiflora</i>",
        )

    def test_markup_junk(self):
        # check junk doesn't crash
        self.assertEqual(
            markup_italics(
                "\ub0aaN\ua001\U00055483\u01d6\u059e/C\U00103e9aG|\U0010eb876"
            ),
            "\ub0aaN\ua001\U00055483\u01d6\u059e/C\U00103e9aG|\U0010eb876",
        )

    def test_markup_complex_hybrid_mismatched_bracket(self):
        # check that mismatch brackets can produce something close to a desired
        # outcome.
        self.assertEqual(
            markup_italics(
                "((carolinae \xd7 'Purple Star') \xd7 (compacta \xd7 sp.)"
            ),
            "((<i>carolinae</i> \xd7 'Purple Star') \xd7 (compacta \xd7 sp.)",
        )
        self.assertEqual(
            markup_italics(
                "(carolinae \xd7 'Purple Star')) \xd7 (lilliputiana \xd7 "
                "compacta \xd7 sp.)"
            ),
            "(<i>carolinae</i> \xd7 'Purple Star')) \xd7 (lilliputiana \xd7 "
            "<i>compacta</i> \xd7 sp.)",
        )


class BinomialSearchTests(BaubleTestCase):
    def setUp(self):
        super().setUp()
        db.engine.execute("delete from genus")
        db.engine.execute("delete from family")

        f1 = Family(family="family1", qualifier="s. lat.")
        g1 = Genus(family=f1, genus="genus1")
        f2 = Family(family="family2")
        g2 = Genus(family=f2, genus="genus2")
        f3 = Family(family="fam3", qualifier="s. lat.")
        g3 = Genus(family=f3, genus="Ixora")
        sp = Species(sp="coccinea", genus=g3)
        sp2 = Species(sp="peruviana", genus=g3)
        sp3 = Species(sp="chinensis", genus=g3)
        self.cv1 = Species(cultivar_epithet="Magnifica", genus=g3)
        self.cv2 = Species(
            sp="chinensis", cultivar_epithet="Prince Of Orange", genus=g3
        )
        g4 = Genus(family=f3, genus="Pachystachys")
        sp4 = Species(sp="coccinea", genus=g4)
        self.sp5 = Species(sp="rosa-sinensis", genus=g3)
        sp6 = Species(sp="speciosa", genus=g3)
        self.sp7 = Species(sp="sp.", genus=g3)
        self.session.add_all(
            [
                f1,
                f2,
                g1,
                g2,
                f3,
                g3,
                sp,
                sp2,
                sp3,
                g4,
                sp4,
                self.sp5,
                sp6,
                self.sp7,
            ]
        )
        self.session.commit()
        self.ixora, self.ic, self.pc = g3, sp, sp4

    def test_binomial_complete(self):
        strategy = search.strategies.get_strategy("BinomialSearch")
        self.assertTrue(isinstance(strategy, BinomialSearch))

        s = "Ixora coccinea"  # matches Ixora coccinea
        results = []
        for i in strategy.search(s, self.session):
            results.extend(i)
        self.assertEqual(results, [self.ic])

    def test_binomial_incomplete(self):
        strategy = search.strategies.get_strategy("BinomialSearch")
        self.assertTrue(isinstance(strategy, BinomialSearch))

        s = "Ix cocc"  # matches Ixora coccinea
        results = []
        for i in strategy.search(s, self.session):
            results.extend(i)
        self.assertEqual(results, [self.ic])

    def test_binomial_no_match(self):
        strategy = search.strategies.get_strategy("BinomialSearch")
        self.assertTrue(isinstance(strategy, BinomialSearch))

        s = "Cosito inesistente"  # matches nothing
        results = []
        for i in strategy.search(s, self.session):
            results.extend(i)
        self.assertEqual(results, [])

    def test_use(self):
        strategy = search.strategies.get_strategy("BinomialSearch")
        self.assertTrue(isinstance(strategy, BinomialSearch))

        s = "ixora coccinea"
        self.assertEqual(strategy.use(s), UseStrategy.EXCLUDE)

        s = "i c"
        self.assertEqual(strategy.use(s), UseStrategy.EXCLUDE)

        s = "I "
        self.assertEqual(strategy.use(s), UseStrategy.EXCLUDE)

        s = "I "
        self.assertEqual(strategy.use(s), UseStrategy.EXCLUDE)

        s = "I c"
        self.assertEqual(strategy.use(s), UseStrategy.INCLUDE)

        s = "Ixora coccinea"
        self.assertEqual(strategy.use(s), UseStrategy.INCLUDE)

        s = "Gre 'Roby"
        self.assertEqual(strategy.use(s), UseStrategy.INCLUDE)

        s = "Grevillea 'Robyn Gordon'"
        self.assertEqual(strategy.use(s), UseStrategy.INCLUDE)

        s = "Hibiscus rosa-sinensis"
        self.assertEqual(strategy.use(s), UseStrategy.INCLUDE)

        s = "Cyn dac 'DT-1"
        self.assertEqual(strategy.use(s), UseStrategy.INCLUDE)

        s = "Eryth sp."
        self.assertEqual(strategy.use(s), UseStrategy.INCLUDE)

        s = "Eryth ."
        self.assertEqual(strategy.use(s), UseStrategy.EXCLUDE)

        s = "Grev '"
        self.assertEqual(strategy.use(s), UseStrategy.INCLUDE)

    def test_sp_cultivar_also_matches(self):
        strategy = search.strategies.get_strategy("BinomialSearch")
        self.assertTrue(isinstance(strategy, BinomialSearch))

        from bauble.plugins.plants.genus import Genus
        from bauble.plugins.plants.species import Species

        g3 = self.session.query(Genus).filter(Genus.genus == "Ixora").one()
        sp5 = Species(sp="coccinea", genus=g3, cultivar_epithet="Nora Grant")
        self.session.add_all([sp5])
        self.session.commit()
        s = "Ixora coccinea"  # matches I.coccinea and Nora Grant
        results = []
        for i in strategy.search(s, self.session):
            results.extend(i)
        self.assertCountEqual(results, [self.ic, sp5])

    def test_cultivar_no_sp_search(self):
        strategy = search.strategies.get_strategy("BinomialSearch")
        self.assertTrue(isinstance(strategy, BinomialSearch))

        s = "Ixora 'Mag"
        results = []
        for i in strategy.search(s, self.session):
            results.extend(i)
        self.assertEqual(results, [self.cv1])

    def test_cultivar_w_sp_search(self):
        strategy = search.strategies.get_strategy("BinomialSearch")
        self.assertTrue(isinstance(strategy, BinomialSearch))

        s = "Ixo 'Pri"
        results = []
        for i in strategy.search(s, self.session):
            results.extend(i)
        self.assertEqual(results, [self.cv2])

    def test_cultivar_complete(self):
        strategy = search.strategies.get_strategy("BinomialSearch")
        self.assertTrue(isinstance(strategy, BinomialSearch))

        s = "Ixora chinensis 'Prince Of Orange'"
        results = []
        for i in strategy.search(s, self.session):
            results.extend(i)
        self.assertEqual(results, [self.cv2])

    def test_full_cultivar_search(self):
        strategy = search.strategies.get_strategy("BinomialSearch")
        self.assertTrue(isinstance(strategy, BinomialSearch))

        s = "Ixora 'Prince Of Orange'"
        results = []
        for i in strategy.search(s, self.session):
            results.extend(i)
        self.assertEqual(results, [self.cv2])

    def test_cultivar_partial_complete(self):
        strategy = search.strategies.get_strategy("BinomialSearch")
        self.assertTrue(isinstance(strategy, BinomialSearch))

        s = "Ixo chi 'Pri"
        results = []
        for i in strategy.search(s, self.session):
            results.extend(i)
        self.assertEqual(results, [self.cv2])

    def test_trade_name_search(self):
        self.cv2.trade_name = "Test Trade Name"
        self.session.commit()
        strategy = search.strategies.get_strategy("BinomialSearch")
        self.assertTrue(isinstance(strategy, BinomialSearch))

        s = "Ixo 'Test"
        results = []
        for i in strategy.search(s, self.session):
            results.extend(i)
        self.assertEqual(results, [self.cv2])

    def test_hyphenated_name_search(self):
        strategy = search.strategies.get_strategy("BinomialSearch")
        self.assertTrue(isinstance(strategy, BinomialSearch))

        s = "Ixo rosa-sinensis"
        results = []
        for i in strategy.search(s, self.session):
            results.extend(i)
        self.assertEqual(results, [self.sp5])

        self.sp5.cultivar_epithet = "Test-10"
        self.session.commit()

        s = "Ixo ros 'Test-1"
        results = []
        for i in strategy.search(s, self.session):
            results.extend(i)
        self.assertEqual(results, [self.sp5])

    def test_sp_dot_search(self):
        strategy = search.strategies.get_strategy("BinomialSearch")
        self.assertTrue(isinstance(strategy, BinomialSearch))

        s = "Ixo sp."
        results = []
        for i in strategy.search(s, self.session):
            results.extend(i)
        self.assertEqual(results, [self.sp7])

        s = "Ixo sp"
        results = []
        for i in strategy.search(s, self.session):
            results.extend(i)
        self.assertEqual(len(results), 2)

    def test_all_cvs_search(self):
        strategy = search.strategies.get_strategy("BinomialSearch")
        self.assertTrue(isinstance(strategy, BinomialSearch))

        s = "Ixo '"
        results = []
        for i in strategy.search(s, self.session):
            results.extend(i)
        self.assertCountEqual(results, [self.cv1, self.cv2])

        s = "Pach '"
        results = []
        for i in strategy.search(s, self.session):
            results.extend(i)
        self.assertEqual(results, [])


class GeographyTests(BaubleClassTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        setUp_data()
        cls.family = Family(family="family")
        cls.genus = Genus(genus="genus", family=cls.family)
        cls.session.add_all([cls.family, cls.genus])
        cls.session.flush()
        setup_geographies()
        cls.session.commit()

    def test_get_species(self):
        mexico_id = 53
        mexico_central_id = 267
        puebla_id = 642
        oaxaca_id = 665
        northern_america_id = 7
        western_canada_id = 45
        british_columbia_id = 102

        # create a some species
        sp1 = Species(genus=self.genus, sp="sp1")
        dist = SpeciesDistribution(geography_id=mexico_central_id)
        sp1.distribution.append(dist)
        self.session.add_all([sp1, dist])
        # commit each time seems to avoid: KeyError: "Deferred loader for
        # attribute '_created' failed to populate correctly"
        self.session.commit()

        sp2 = Species(genus=self.genus, sp="sp2")
        dist = SpeciesDistribution(geography_id=oaxaca_id)
        sp2.distribution.append(dist)
        self.session.add_all([sp2, dist])
        self.session.commit()

        sp3 = Species(genus=self.genus, sp="sp3")
        dist = SpeciesDistribution(geography_id=western_canada_id)
        sp3.distribution.append(dist)
        self.session.add_all([sp3, dist])
        self.session.commit()

        oaxaca = self.session.get(Geography, oaxaca_id)
        species = get_species_in_geography(oaxaca)
        self.assertTrue([s.id for s in species] == [sp2.id])

        mexico = self.session.get(Geography, mexico_id)
        species = get_species_in_geography(mexico)
        self.assertTrue([s.id for s in species] == [sp1.id, sp2.id])

        north_america = self.session.get(Geography, northern_america_id)
        species = get_species_in_geography(north_america)
        self.assertTrue([s.id for s in species] == [sp1.id, sp2.id, sp3.id])

        # recorded in parent should show in children
        british_columbia = self.session.get(Geography, british_columbia_id)
        species = get_species_in_geography(british_columbia)
        self.assertTrue([s.id for s in species] == [sp3.id])

        puebla = self.session.get(Geography, puebla_id)
        species = get_species_in_geography(puebla)
        self.assertTrue([s.id for s in species] == [sp1.id])

        # un mapped raises
        geo = Geography()
        self.assertRaises(ValueError, get_species_in_geography, geo)

    def test_species_distribution_str(self):
        # create a some species
        sp1 = Species(genus=self.genus, sp="sp1000")
        dist = SpeciesDistribution(geography_id=267)
        sp1.distribution.append(dist)
        self.session.flush()
        self.assertEqual(sp1.distribution_str(), "Mexico Central")
        dist = SpeciesDistribution(geography_id=45)
        sp1.distribution.append(dist)
        self.session.flush()
        self.assertEqual(
            sp1.distribution_str(), "Mexico Central, Western Canada"
        )

    def test_get_children_id_get_parent_id(self):
        australia = self.session.get(Geography, 38)
        self.assertCountEqual(
            australia.get_children_ids(),
            [
                414,
                359,
                296,
                297,
                330,
                682,
                683,
                695,
                727,
                688,
                689,
                694,
                407,
                726,
                378,
                286,
            ],
        )
        lord_howe = self.session.get(Geography, 682)
        self.assertCountEqual(lord_howe.get_parent_ids(), [286, 38, 5])

    def test_consolidate_geographies(self):
        # all level 2 geographies
        lv2 = self.session.query(Geography).filter(Geography.level == 2)
        result = (
            self.session.query(Geography).filter(Geography.level == 1).all()
        )
        self.assertCountEqual(result, consolidate_geographies(lv2))
        # all level 3 geographies from EUROPE and AUSTRALASIA
        lv2s = (
            self.session.query(Geography.id)
            .filter(Geography.level == 2)
            .filter(Geography.parent_id.in_([1, 5]))
        )
        lv3 = (
            self.session.query(Geography)
            .filter(Geography.level == 3)
            .filter(Geography.parent_id.in_(lv2s))
        )
        result = (
            self.session.query(Geography)
            .filter(Geography.id.in_([1, 5]))
            .all()
        )
        self.assertCountEqual(result, consolidate_geographies(lv3))
        # all level 4 geographies from Brazil
        lv3s = (
            self.session.query(Geography.id)
            .filter(Geography.level == 3)
            .filter(Geography.parent_id == 58)
        )
        lv4 = (
            self.session.query(Geography)
            .filter(Geography.parent_id.in_(lv3s))
            .filter(Geography.level == 4)
        )
        result = [self.session.get(Geography, 58)]
        self.assertCountEqual(result, consolidate_geographies(lv4))
        # a combination that ends up in AUSTALIASIA + Paupua New Guinea
        ids = (39, 688, 689, 286, 297, 330, 359, 378, 407, 414, 691)
        geos = self.session.query(Geography).filter(Geography.id.in_(ids))
        result = (
            self.session.query(Geography)
            .filter(Geography.id.in_((691, 5)))
            .all()
        )
        self.assertCountEqual(result, consolidate_geographies(geos))
        # AUSTRALASIA and Lord Howe I. should remove Lord Howe
        ids = (5, 682)
        geos = self.session.query(Geography).filter(Geography.id.in_(ids))
        result = [self.session.get(Geography, 5)]
        self.assertCountEqual(result, consolidate_geographies(geos))

    def test_approx_area(self):
        geos = self.session.query(Geography).filter(Geography.level < 3).all()
        for geo in geos:
            self.assertGreater(geo.approx_area, 0.0)
            if geo.children:
                children_area = sum(i.approx_area for i in geo.children)
                difference = abs(children_area - geo.approx_area)
                # NOTE have to accept 8% error due to current inaccuracy of
                # WGSRPD data
                error_margin = geo.approx_area * 8 / 100
                # error_margin = 5000
                self.assertLess(difference, error_margin, str(geo))

    def test_consolidate_geographies_by_percent_area(self):
        # all level 2 geographies
        lv2 = self.session.query(Geography).filter(Geography.level == 2)
        result = (
            self.session.query(Geography).filter(Geography.level == 1).all()
        )
        self.assertCountEqual(
            result, consolidate_geographies_by_percent_area(lv2, 34)
        )
        # all level 3 geographies from EUROPE and AUSTRALASIA
        lv2s = (
            self.session.query(Geography.id)
            .filter(Geography.level == 2)
            .filter(Geography.parent_id.in_([1, 5]))
        )
        lv3 = (
            self.session.query(Geography)
            .filter(Geography.level == 3)
            .filter(Geography.parent_id.in_(lv2s))
        )
        result = (
            self.session.query(Geography)
            .filter(Geography.id.in_([1, 5]))
            .all()
        )
        self.assertCountEqual(
            result, consolidate_geographies_by_percent_area(lv3, 33)
        )
        # all level 4 geographies from Brazil
        lv3s = (
            self.session.query(Geography.id)
            .filter(Geography.level == 3)
            .filter(Geography.parent_id == 58)
        )
        lv4 = (
            self.session.query(Geography)
            .filter(Geography.parent_id.in_(lv3s))
            .filter(Geography.level == 4)
        )
        # with allowable_children = 2 gets brazil
        result = [self.session.get(Geography, 58)]
        self.assertCountEqual(
            result, consolidate_geographies_by_percent_area(lv4, 33, 2)
        )
        # with allowable_children not set (i.e. 1) gets Southern America
        result = [result[0].parent]
        self.assertCountEqual(
            result, consolidate_geographies_by_percent_area(lv4, 33)
        )
        # a combination that ends up in AUSTALIASIA + Paupua New Guinea
        ids = (39, 688, 689, 286, 297, 330, 359, 378, 407, 414, 691)
        geos = self.session.query(Geography).filter(Geography.id.in_(ids))
        result = (
            self.session.query(Geography)
            .filter(Geography.id.in_((691, 5)))
            .all()
        )
        self.assertCountEqual(
            result, consolidate_geographies_by_percent_area(geos, 33, 2)
        )
        # AUSTRALASIA and Lord Howe I. should remove Lord Howe
        ids = (5, 682)
        geos = self.session.query(Geography).filter(Geography.id.in_(ids))
        result = [self.session.get(Geography, 5)]
        self.assertCountEqual(
            result, consolidate_geographies_by_percent_area(geos, 33)
        )
        # Australia and Lord Howe I. should remove Lord Howe
        ids = (38, 682)
        geos = self.session.query(Geography).filter(Geography.id.in_(ids))
        result = [self.session.get(Geography, 38)]
        self.assertCountEqual(
            result, consolidate_geographies_by_percent_area(geos, 33)
        )
        # shouldn't make a difference if allowable_children is set higher
        self.assertCountEqual(
            result, consolidate_geographies_by_percent_area(geos, 33, 4)
        )
        # all Australian islands should not return Australia but consolidate
        # Norfolk Is.
        ids = (726, 694, 682, 683, 378)
        geos = self.session.query(Geography).filter(Geography.id.in_(ids))
        res_ids = (726, 694, 286, 378)
        result = self.session.query(Geography).filter(
            Geography.id.in_(res_ids)
        )
        self.assertCountEqual(
            result, consolidate_geographies_by_percent_area(geos, 33)
        )

    def test_distribution_map(self):
        geo = (
            self.session.query(Geography)
            .filter(Geography.code == "NFK-LH")
            .one()
        )
        self.assertEqual(geo.get_geography_ids(), [geo.id])

    def test_top_level_count(self):
        # check we get the plural name
        self.assertEqual(Geography.top_level_count([1, 2]), "Geographies: 2")


class GeographyTests2(TestCase):
    """Tests not requiring setup_geographies()"""

    def test_as_svg_paths_polygon(self):
        geojson = {
            "type": "Polygon",
            "coordinates": [
                [
                    [159.07080078125, -31.599998474121094],
                    [159.08578491210938, -31.561111450195312],
                    [159.04913330078125, -31.52166748046875],
                    [159.10189819335938, -31.57111358642578],
                    [159.07080078125, -31.599998474121094],
                ]
            ],
        }
        geo = Geography(
            name="Lord Howe I.",
            code="NFK-LH",
            level=4,
            geojson=geojson,
        )
        self.assertEqual(
            geo.as_svg_paths(),
            '<path stroke="green" stroke-width="0.2" fill="green" d='
            '"M 159.071 -31.6 L 159.086 -31.561 L 159.049 -31.522 L '
            '159.102 -31.571 Z"'
            "/>",
        )

    def test_as_svg_paths_pacific_centric(self):
        geojson = {
            "type": "Polygon",
            "coordinates": [
                [
                    [-115.7504425, 24.9516697],
                    [-115.7500534, 24.9512501],
                    [-115.7487793, 24.9524994],
                    [-115.7500305, 24.9537201],
                    [-115.7504196, 24.9533291],
                    [-115.7504501, 24.9516697],
                    [-115.7504425, 24.9516697],
                ]
            ],
        }
        geo = Geography(
            name="Rocas Alijos",
            code="MXI-RA",
            level=4,
            geojson=geojson,
        )

        # not pacific centric
        self.assertEqual(
            geo.as_svg_paths(),
            '<path stroke="green" stroke-width="0.2" fill="green" d='
            '"M -115.75 24.952 L -115.75 24.951 L -115.749 24.952 L '
            '-115.75 24.954 L -115.75 24.953 L -115.75 24.952 Z"/>',
        )
        # pacific centric (returns both)
        self.assertEqual(
            geo.as_svg_paths(pacific_centric=True),
            '<path stroke="green" stroke-width="0.2" fill="green" d='
            '"M -115.75 24.952 L -115.75 24.951 L -115.749 24.952 L '
            '-115.75 24.954 L -115.75 24.953 L -115.75 24.952 Z"/>'
            '<path stroke="green" stroke-width="0.2" fill="green" d='
            '"M 244.25 24.952 L 244.25 24.951 L 244.251 24.952 L '
            '244.25 24.954 L 244.25 24.953 L 244.25 24.952 Z"/>',
        )

    def test_as_svg_paths_multi_polygon(self):
        geojson = {
            "type": "MultiPolygon",
            "coordinates": [
                [
                    [
                        [159.07080078125, -31.599998474121094],
                        [159.08578491210938, -31.561111450195312],
                        [159.04913330078125, -31.52166748046875],
                        [159.10189819335938, -31.57111358642578],
                        [159.07080078125, -31.599998474121094],
                    ],
                    [
                        [139.07080078125, -21.599998474121094],
                        [139.08578491210938, -21.561111450195312],
                        [139.04913330078125, -21.52166748046875],
                        [139.10189819335938, -21.57111358642578],
                        [139.07080078125, -21.599998474121094],
                    ],
                ]
            ],
        }
        geo = Geography(
            name="Lord Howe I.",
            code="NFK-LH",
            level=4,
            geojson=geojson,
        )
        self.assertEqual(
            geo.as_svg_paths(),
            '<path stroke="green" stroke-width="0.2" fill="green" d="M '
            "159.071 -31.6 L 159.086 -31.561 L 159.049 -31.522 L 159.102 "
            '-31.571 Z"/><path stroke="green" stroke-width="0.2" fill="green" '
            'd="M 139.071 -21.6 L 139.086 -21.561 L 139.049 -21.522 L 139.102 '
            '-21.571 Z"/>',
        )

    def test_coord_string(self):
        self.assertEqual(
            _coord_string(10.0011, 20.0011111, False), "10.001 20.001"
        )
        self.assertEqual(
            _coord_string(-10.0011, 20.0011111, True), "349.999 20.001"
        )

    def test_path_string(self):
        path = [[10.01, 20.01], [12.01, 21.01], [13.10, 22.10], [10.01, 20.01]]
        res = (
            '<path stroke="blue" stroke-width="0.2" fill="blue" '
            'd="M 10.01 20.01 L 12.01 21.01 L 13.1 22.1 Z"/>'
        )
        self.assertEqual(
            _path_string(path, fill="blue", pacific_centric=False), res
        )


class GeographyApproxAreaTests(BaubleTestCase):
    def test_approx_area_is_set_at_insert(self):
        # test listens_for insert
        geojson = {
            "type": "Polygon",
            "coordinates": [
                [
                    [159.07080078125, -31.599998474121094],
                    [159.08578491210938, -31.561111450195312],
                    [159.04913330078125, -31.52166748046875],
                    [159.10189819335938, -31.57111358642578],
                    [159.07080078125, -31.599998474121094],
                ]
            ],
        }
        geo = Geography(
            name="Lord Howe I.",
            code="NFK-LH",
            level=4,
            geojson=geojson,
        )
        self.session.add(geo)
        self.session.commit()
        self.assertGreater(geo.approx_area, 5)
        self.assertEqual(geo.approx_area, geo.get_approx_area())
        hist_query = (
            self.session.query(db.History.values)
            .filter(db.History.table_name == "geography")
            .filter(db.History.table_id == geo.id)
            .all()
        )
        self.assertEqual(len(hist_query), 1)

    def test_approx_area_is_set_at_update(self):
        # test listens_for update
        geojson = {
            "type": "Polygon",
            "coordinates": [
                [
                    [159.07080078125, -31.599998474121094],
                    [159.08578491210938, -31.561111450195312],
                    [159.04913330078125, -31.52166748046875],
                    [159.10189819335938, -31.57111358642578],
                    [159.07080078125, -31.599998474121094],
                ]
            ],
        }
        geo = Geography(
            name="Lord Howe I.",
            code="NFK-LH",
            level=4,
            geojson=None,
        )
        self.session.add(geo)
        self.session.commit()
        self.assertEqual(geo.approx_area, 0.0)
        geo.geojson = geojson
        self.session.commit()
        self.assertGreater(geo.approx_area, 5)
        self.assertEqual(geo.approx_area, geo.get_approx_area())
        hist_query = (
            self.session.query(db.History.values)
            .filter(db.History.table_name == "geography")
            .filter(db.History.table_id == geo.id)
        )
        self.assertEqual(len(hist_query.all()), 2)
        geo.geojson = None
        self.session.commit()
        self.assertEqual(geo.approx_area, 0.0)
        self.assertEqual(len(hist_query.all()), 3)

    def test_get_approx_area_handles_holes(self):
        geojson = {
            "type": "Polygon",
            "coordinates": [
                [
                    [10.0, 10.0],
                    [0.0, 10.0],
                    [0.0, 0.0],
                    [10.0, 0.0],
                    [10.0, 10.0],
                ],
            ],
        }
        geo = Geography(
            name="Lord Howe I.",
            code="NFK-LH",
            level=4,
            geojson=geojson,
        )
        self.assertAlmostEqual(geo.get_approx_area(), 1227877.0, delta=1)
        # single hole
        geojson = {
            "type": "Polygon",
            "coordinates": [
                [
                    [10.0, 10.0],
                    [0.0, 10.0],
                    [0.0, 0.0],
                    [10.0, 0.0],
                    [10.0, 10.0],
                ],
                [  # hole 1
                    [5.0, 5.0],
                    [5.0, 1.0],
                    [1.0, 1.0],
                    [1.0, 5.0],
                    [5.0, 5.0],
                ],
            ],
        }
        geo = Geography(
            name="Lord Howe I.",
            code="NFK-LH",
            level=4,
            geojson=geojson,
        )
        self.assertAlmostEqual(geo.get_approx_area(), 1031153.0, delta=1)
        # multiple holes
        geojson = {
            "type": "Polygon",
            "coordinates": [
                [
                    [10.0, 10.0],
                    [0.0, 10.0],
                    [0.0, 0.0],
                    [10.0, 0.0],
                    [10.0, 10.0],
                ],
                [  # hole 1
                    [5.0, 5.0],
                    [5.0, 1.0],
                    [1.0, 1.0],
                    [1.0, 5.0],
                    [5.0, 5.0],
                ],
                [  # hole 2
                    [9.0, 9.0],
                    [9.0, 6.0],
                    [6.0, 6.0],
                    [6.0, 9.0],
                    [9.0, 9.0],
                ],
            ],
        }
        geo = Geography(
            name="Lord Howe I.",
            code="NFK-LH",
            level=4,
            geojson=geojson,
        )
        self.assertAlmostEqual(geo.get_approx_area(), 921283.0, delta=1)


class CitesStatus_test(PlantTestCase):
    """we can retrieve the cites status as defined in family-genus-species"""

    def test_property(self):
        # genus CITES set on the genus
        obj = self.session.get(Genus, 1)
        self.assertEqual(obj.cites, "II")
        # genus CITES set on the family
        obj = self.session.get(Genus, 6)
        self.assertEqual(obj.cites, "II")
        # genus CITES set differently on the genus to the family
        obj = self.session.get(Genus, 5)
        self.assertEqual(obj.cites, "I")
        # species CITES set differently on the genus to the family
        obj = self.session.get(Species, 17)
        self.assertEqual(obj.cites, "I")
        # species CITES set differently on the species to the family
        obj = self.session.get(Species, 18)
        self.assertEqual(obj.cites, "III")
        # species CITES set on the family
        obj = self.session.get(Species, 19)
        self.assertEqual(obj.cites, "II")

    def test_property_expression(self):
        qry = self.session.query(Genus).filter(Genus.cites == "II")
        self.assertEqual([i.id for i in qry.all()], [1, 2, 6, 14, 16, 17])

        qry = self.session.query(Species).filter(Species.cites == "III")
        self.assertEqual([i.id for i in qry.all()], [18])

        qry = self.session.query(Species).filter(Species.cites == "II")
        cites_ii = (
            self.session.query(Species)
            .join(Genus)
            .filter(Genus.family_id == 1)
            .filter(Genus.id != 5)
            .filter(Species.id != 18)
        )
        self.assertCountEqual(
            [i.id for i in qry.all()], [i.id for i in cites_ii]
        )

        qry = self.session.query(Species).filter(Species.cites == "I")
        cites_i = self.session.query(Species).join(Genus).filter(Genus.id == 5)
        self.assertCountEqual(
            [i.id for i in qry.all()], [i.id for i in cites_i]
        )

    def test_property_setter(self):
        obj = self.session.get(Genus, 2)
        obj.cites = "II"
        self.session.commit()
        self.assertEqual(obj._cites, "II")

        obj.cites = None
        self.session.commit()
        self.assertIsNone(obj._cites)

        obj = self.session.get(Family, 3)
        obj.cites = "III"
        self.session.commit()
        self.assertEqual(obj.cites, "III")

        obj.cites = None
        self.session.commit()
        self.assertIsNone(obj.cites)

        obj = self.session.get(Species, 3)
        obj.cites = "I"
        self.session.commit()
        self.assertEqual(obj.cites, "I")

        obj.cites = None
        self.session.commit()
        self.assertIsNone(obj._cites)


class SpeciesInfraspecificProp(PlantTestCase):
    def include_cinnamomum_camphora(self):
        """\
Lauraceae,,Cinnamomum,,"camphora",,"","(L.) J.Presl"
Lauraceae,,Cinnamomum,,"camphora",f.,"linaloolifera","(Y.Fujita) Sugim."
Lauraceae,,Cinnamomum,,"camphora",var.,"nominale","Hats. & Hayata"
"""
        self.cinnamomum = Genus(
            family=Family(epithet="Lauraceae"), epithet="Cinnamomum"
        )
        self.cinnamomum_camphora = Species(
            genus=self.cinnamomum, epithet="camphora"
        )
        self.session.add(self.cinnamomum_camphora)
        self.session.commit()

    def test_infraspecific_1(self):
        self.include_cinnamomum_camphora()
        obj = Species(
            genus=self.cinnamomum,
            sp="camphora",
            infrasp1_rank="f.",
            infrasp1="linaloolifera",
            infrasp1_author="(Y.Fujita) Sugim.",
        )
        self.assertEqual(obj.infraspecific_rank, "f.")
        self.assertEqual(obj.infraspecific_epithet, "linaloolifera")
        self.assertEqual(obj.infraspecific_author, "(Y.Fujita) Sugim.")

    def test_infraspecific_2(self):
        self.include_cinnamomum_camphora()
        obj = Species(
            genus=self.cinnamomum,
            sp="camphora",
            infrasp2_rank="f.",
            infrasp2="linaloolifera",
            infrasp2_author="(Y.Fujita) Sugim.",
        )
        self.assertEqual(obj.infraspecific_rank, "f.")
        self.assertEqual(obj.infraspecific_epithet, "linaloolifera")
        self.assertEqual(obj.infraspecific_author, "(Y.Fujita) Sugim.")

    def include_gleditsia_triacanthos(self):
        "Gleditsia triacanthos var. inermis 'Sunburst'."
        self.gleditsia = Genus(
            family=Family(epithet="Fabaceae"), epithet="Gleditsia"
        )
        self.gleditsia_triacanthos = Species(
            genus=self.gleditsia, epithet="triacanthos"
        )
        self.session.add(self.gleditsia_triacanthos)
        self.session.commit()

    def test_variety_and_cultivar_1(self):
        self.include_gleditsia_triacanthos()
        obj = Species(
            genus=self.gleditsia,
            sp="triacanthos",
            infrasp1_rank="var.",
            infrasp1="inermis",
            cultivar_epithet="Sunburst",
        )
        self.assertEqual(obj.infraspecific_rank, "var.")
        self.assertEqual(obj.infraspecific_epithet, "inermis")
        self.assertEqual(obj.infraspecific_author, "")
        self.assertEqual(obj.cultivar_epithet, "Sunburst")

    def test_variety_and_cultivar_2(self):
        self.include_gleditsia_triacanthos()
        obj = Species(
            genus=self.gleditsia,
            sp="triacanthos",
            infrasp2_rank="var.",
            infrasp2="inermis",
            cultivar_epithet="Sunburst",
        )
        self.assertEqual(obj.infraspecific_rank, "var.")
        self.assertEqual(obj.infraspecific_epithet, "inermis")
        self.assertEqual(obj.infraspecific_author, "")
        self.assertEqual(obj.cultivar_epithet, "Sunburst")

    def test_infraspecific_props_is_lowest_ranked(self):
        """Saxifraga aizoon var. aizoon subvar. brevifolia f. multicaulis
        subf. surculosa"""
        genus = Genus(
            family=Family(epithet="Saxifragaceae"), epithet="Saxifraga"
        )
        subvar = Species(
            genus=genus,
            sp="aizoon",
            infrasp1_rank="var.",
            infrasp1="aizoon",
            infrasp2_rank="subvar.",
            infrasp2="brevifolia",
        )
        subf = Species(
            genus=genus,
            sp="aizoon",
            infrasp2_rank="var.",
            infrasp2="aizoon",
            infrasp1_rank="subvar.",
            infrasp1="brevifolia",
            infrasp3_rank="f.",
            infrasp3="multicaulis",
            infrasp4_rank="subf.",
            infrasp4="surculosa",
        )
        self.assertEqual(subvar.infraspecific_rank, "subvar.")
        self.assertEqual(subvar.infraspecific_epithet, "brevifolia")
        self.assertEqual(subvar.infraspecific_author, "")
        self.assertIsNone(subf.cultivar_epithet)
        self.assertEqual(subf.infraspecific_rank, "subf.")
        self.assertEqual(subf.infraspecific_epithet, "surculosa")
        self.assertEqual(subf.infraspecific_author, "")
        self.assertIsNone(subf.cultivar_epithet)
        # Saxifraga aizoon var. aizoon subvar. brevifolia f. multicaulis
        # cv. 'Bellissima'
        cv = Species(
            genus=genus,
            sp="aizoon",
            infrasp4_rank="var.",
            infrasp4="aizoon",
            infrasp1_rank="subvar.",
            infrasp1="brevifolia",
            infrasp3_rank="f.",
            infrasp3="multicaulis",
            cultivar_epithet="Bellissima",
        )
        self.assertEqual(cv.infraspecific_rank, "f.")
        self.assertEqual(cv.infraspecific_epithet, "multicaulis")
        self.assertEqual(cv.infraspecific_author, "")
        self.assertEqual(cv.cultivar_epithet, "Bellissima")

    def test_infraspecific_hybrid_properties(self):
        # NOTE some of this and similar test are no longer relevant
        family = Family(family="family")
        genus = Genus(family=family, genus="genus")
        sp = Species(genus=genus, sp="sp")
        # Check all parts end up where they should
        parts = "var. variety f. form"
        sp.infraspecific_parts = parts
        cul = "Cultivar In Parts"
        sp.cultivar_epithet = cul
        self.session.add_all([family, genus, sp])
        self.session.commit()
        # Make sure we cover the expression for each
        q = (
            self.session.query(Species)
            .filter_by(infraspecific_rank=parts.split()[-2])
            .one()
        )
        self.assertEqual(sp, q)
        q = (
            self.session.query(Species)
            .filter_by(infraspecific_epithet=parts.split()[-1])
            .one()
        )
        self.assertEqual(sp, q)
        q = self.session.query(Species).filter_by(cultivar_epithet=cul).one()
        self.assertEqual(sp, q)
        self.assertEqual(sp.infraspecific_parts, parts)
        self.assertEqual(sp.infrasp1_rank, parts.split()[0])
        self.assertEqual(sp.infrasp1, parts.split()[1])
        self.assertEqual(sp.infrasp2_rank, parts.split()[2])
        self.assertEqual(sp.infrasp2, parts.split()[3])
        self.assertEqual(sp.cultivar_epithet, cul)
        # test if we remove the infraspecific parts removes all parts
        sp.infraspecific_parts = None
        self.session.commit()
        self.assertIsNone(sp.infrasp1_rank)
        self.assertIsNone(sp.infrasp1)
        self.assertIsNone(sp.infrasp2_rank)
        self.assertIsNone(sp.infrasp2)
        self.assertIsNone(sp.infrasp3_rank)
        self.assertIsNone(sp.infrasp3)
        self.assertIsNone(sp.infrasp4_rank)
        self.assertIsNone(sp.infrasp4)

    def test_infraspecific_hybrid_properties_w_cv_rank_only(self):
        family = Family(family="family")
        genus = Genus(family=family, genus="genus")
        sp = Species(genus=genus, sp="sp")
        parts = "var. variety f. form"
        sp.infraspecific_parts = parts
        self.session.add_all([family, genus, sp])
        self.session.commit()
        # test 'cv.'
        cul = "cv."
        sp.cultivar_epithet = cul
        self.session.commit()
        self.assertEqual(sp.infraspecific_parts, parts)
        self.assertEqual(sp.infrasp1_rank, parts.split()[0])
        self.assertEqual(sp.infrasp1, parts.split()[1])
        self.assertEqual(sp.infrasp2_rank, parts.split()[2])
        self.assertEqual(sp.infrasp2, parts.split()[3])
        self.assertEqual(sp.cultivar_epithet, cul)
        self.assertIsNone(sp.infrasp3)
        # test removing parts leaves cv in correct place
        sp.infraspecific_parts = None
        self.session.commit()
        self.assertEqual(sp.cultivar_epithet, cul)

    def test_infraspecific_hybrid_properties_wo_cv(self):
        family = Family(family="family")
        genus = Genus(family=family, genus="genus")
        sp = Species(genus=genus, sp="sp")
        parts = "var. variety f. form"
        sp.infraspecific_parts = parts
        self.session.add_all([family, genus, sp])
        self.session.commit()
        self.assertEqual(sp.infraspecific_parts, parts)
        self.assertEqual(sp.infrasp1_rank, parts.split()[0])
        self.assertEqual(sp.infrasp1, parts.split()[1])
        self.assertEqual(sp.infrasp2_rank, parts.split()[2])
        self.assertEqual(sp.infrasp2, parts.split()[3])
        self.assertIsNone(sp.infrasp3_rank)
        # test if we remove the infraspecific parts everything is removed
        sp.infraspecific_parts = None
        self.session.commit()
        self.assertIsNone(sp.infrasp1_rank)
        self.assertIsNone(sp.infrasp1)
        self.assertIsNone(sp.infrasp2_rank)
        self.assertIsNone(sp.infrasp2)
        self.assertIsNone(sp.infrasp3_rank)
        self.assertIsNone(sp.infrasp3)
        self.assertIsNone(sp.infrasp4_rank)
        self.assertIsNone(sp.infrasp4)


class AttributesStoredInNotesTests(PlantTestCase):
    def setUp(self):
        super().setUp()
        self.obj = (
            self.session.query(Species)
            .join(Genus)
            .filter(Genus.epithet == "Laelia")
            .filter(Species.epithet == "lobata")
            .one()
        )

    def test_proper_yaml_dictionary(self):
        note = SpeciesNote(category="<coords>", note="{1: 1, 2: 2}")
        note.species = self.obj
        self.session.commit()
        self.assertEqual(self.obj.coords, {"1": 1, "2": 2})

    def test_very_sloppy_json_dictionary(self):
        note = SpeciesNote(category="<coords>", note="lat:8.3,lon:-80.1")
        note.species = self.obj
        self.session.commit()
        self.assertEqual(self.obj.coords, {"lat": 8.3, "lon": -80.1})

    def test_very_very_sloppy_json_dictionary(self):
        note = SpeciesNote(
            category="<coords>", note="lat:8.3;lon:-80.1;alt:1400.0"
        )
        note.species = self.obj
        self.session.commit()
        self.assertEqual(
            self.obj.coords, {"lat": 8.3, "lon": -80.1, "alt": 1400.0}
        )

    def test_atomic_value_interpreted(self):
        self.assertEqual(self.obj.price, 19.50)

    def test_atomic_value_verbatim(self):
        self.assertEqual(self.obj.price_tag, "$19.50")

    def test_list_value(self):
        self.assertEqual(self.obj.list_var, ["abc", "def"])

    def test_dict_value(self):
        self.assertEqual(
            self.obj.dict_var, {"k": "abc", "l": "def", "m": "xyz"}
        )


class GlobalFunctionsTest(PlantTestCase):
    def test_species_markup_func(self):
        sp1 = (
            self.session.query(Species)
            .join(Genus)
            .filter(Genus.epithet == "Maxillaria")
            .filter(Species.epithet == "variabilis")
            .one()
        )
        sp2 = (
            self.session.query(Species)
            .join(Genus)
            .filter(Genus.epithet == "Laelia")
            .filter(Species.epithet == "lobata")
            .one()
        )
        # set the default
        sp1.default_vernacular_name = sp1.vernacular_names[0]
        first, second = sp1.search_view_markup_pair()
        self.assertTrue(
            remove_zws(first).startswith(
                "<i>Maxillaria</i> s. str <i>variabilis</i>"
            )
        )
        expect = (
            '<i>Maxillaria</i> s. str <i>variabilis</i> <span weight="light">'
            'Bateman ex Lindl.</span><span foreground="#555555" size="small" '
            'weight="light"> - synonym of <i>Encyclia</i> <i>cochleata</i> '
            "(L.) Lemée</span>"
        )
        self.assertEqual(remove_zws(first), expect)
        self.assertEqual(
            second,
            "Orchidaceae -- "
            "SomeName, "
            '<span foreground="#555555" weight="light">SomeName 2</span>',
        )
        first, second = sp2.search_view_markup_pair()
        self.assertEqual(remove_zws(first), "<i>Laelia</i> <i>lobata</i>")
        self.assertEqual(second, "Orchidaceae")

    def test_vername_markup_func(self):
        vName = self.session.query(VernacularName).filter_by(id=1).one()
        first, second = vName.search_view_markup_pair()
        self.assertEqual(
            remove_zws(second), "<i>Maxillaria</i> s. str <i>variabilis</i>"
        )
        self.assertEqual(first, "SomeName")

    def test_species_get_kids(self):
        mVa = self.session.query(Species).filter_by(id=1).one()
        self.assertEqual(partial(db.natsort, "accessions")(mVa), [])

    def test_vernname_get_kids(self):
        vName = self.session.query(VernacularName).filter_by(id=1).one()
        self.assertEqual(partial(db.natsort, "species.accessions")(vName), [])

    def test_get_binomial_completions(self):
        self.assertEqual(
            get_binomial_completions("cyn"),
            {
                "Cynodon dactylon 'TifTuf'",
                "Cynodon dactylon 'DT-1'",
                "Cynodon dactylon",
            },
        )
        self.assertEqual(
            get_binomial_completions("cynodon dact"),
            {
                "Cynodon dactylon 'TifTuf'",
                "Cynodon dactylon 'DT-1'",
                "Cynodon dactylon",
            },
        )
        self.assertEqual(
            get_binomial_completions("cynod dact"),
            {
                "Cynodon dactylon 'TifTuf'",
                "Cynodon dactylon 'DT-1'",
                "Cynodon dactylon",
            },
        )
        self.assertEqual(
            get_binomial_completions("Cynod 'T"),
            {
                "Cynodon 'TifTuf'",
            },
        )
        self.assertEqual(
            get_binomial_completions("Cynodon 'T"),
            {
                "Cynodon 'TifTuf'",
            },
        )
        self.assertEqual(
            get_binomial_completions("Cynodon dactylon 'DT"),
            {
                "Cynodon dactylon 'DT-1'",
            },
        )
        self.assertEqual(
            get_binomial_completions("Buty"),
            {
                "Butyagrus nabonnandii",
            },
        )


class SynonymSearchTest(BaubleTestCase):
    def test_search_search_uses_synonym_search(self):
        prefs.prefs["bauble.search.return_accepted"] = True
        with self.assertLogs(level="DEBUG") as logs:
            search.search("genus like %", self.session)
        string = 'SearchStrategy "genus like %" (SynonymSearch)'
        self.assertTrue(any(string in i for i in logs.output))

        with self.assertLogs(level="DEBUG") as logs:
            search.search("12.11.13", self.session)
        string = 'SearchStrategy "12.11.13" (SynonymSearch)'
        self.assertTrue(any(string in i for i in logs.output))

        with self.assertLogs(level="DEBUG") as logs:
            search.search("So ha", self.session)
        string = 'SearchStrategy "So ha" (SynonymSearch)'
        self.assertTrue(any(string in i for i in logs.output))

    def test_search_search_doesnt_use_synonym_search(self):
        prefs.prefs["bauble.search.return_accepted"] = False
        with self.assertLogs(level="DEBUG") as logs:
            search.search("genus like %", self.session)
        string = 'SearchStrategy "genus like %" (SynonymSearch)'
        self.assertFalse(any(string in i for i in logs.output))

        with self.assertLogs(level="DEBUG") as logs:
            search.search("12.11.13", self.session)
        string = 'SearchStrategy "12.11.13" (SynonymSearch)'
        self.assertFalse(any(string in i for i in logs.output))

        with self.assertLogs(level="DEBUG") as logs:
            search.search("So ha", self.session)
        string = 'SearchStrategy "So ha" (SynonymSearch)'
        self.assertFalse(any(string in i for i in logs.output))

    def test_bails_wo_return_accepted(self):
        # possibly redundant functionality?
        prefs.prefs["bauble.search.return_accepted"] = True
        fam = Family(epithet="Spam")
        fam2 = Family(epithet="Eggs")
        fam.synonyms.append(fam2)
        self.session.add(fam2)
        self.session.add(fam)
        self.session.commit()
        query = self.session.query(Family).filter_by(id=fam2.id)
        result_cache["MapperSearch"] = query.all()
        strategy = search.strategies.get_strategy("SynonymSearch")

        self.assertTrue(isinstance(strategy, SynonymSearch))

        results = []
        for i in strategy.search("", self.session):
            results.extend(i)

        self.assertEqual(results, [fam])

        # bails
        prefs.prefs["bauble.search.return_accepted"] = False

        results = []
        for i in strategy.search("", self.session):
            results.extend(i)

        self.assertEqual(results, [])


class RetrieveTests(PlantTestCase):
    def test_vernacular_name_retreives_full_sp_data(self):
        keys = {
            "species.sp": "cochleata",
            "species.genus.genus": "Encyclia",
            "species.infrasp1_rank": "subsp.",
            "species.infrasp1": "cochleata",
            "species.infrasp2_rank": "var.",
            "species.infrasp2": "cochleata",
            "species.cultivar_epithet": "Black",
        }
        vname = VernacularName.retrieve(self.session, keys)
        self.assertEqual(vname.id, 5)
        # using hybrid properties
        keys = {
            "species.epithet": "cochleata",
            "species.genus.epithet": "Encyclia",
            "species.infrasp_parts": "subsp. cochleata var. cochleata",
            "species.cultivar_epithet": "Black",
        }
        vname = VernacularName.retrieve(self.session, keys)
        self.assertEqual(vname.id, 5)

    def test_vernacular_name_retreives_incomplete_sp_data_one_sp(self):
        keys = {
            "species.epithet": "cochleata",
            "species.genus.epithet": "Encyclia",
            "species.cultivar_epithet": "Black",
        }
        vname = VernacularName.retrieve(self.session, keys)
        self.assertEqual(vname.id, 5)

    def test_vernacular_name_doesnt_retreive_incomplete_sp_data_multiple(self):
        keys = {
            "species.genus.epithet": "Encyclia",
            "species.epithet": "cochleata",
        }
        vname = VernacularName.retrieve(self.session, keys)
        self.assertIsNone(vname)

    def test_vernacular_name_doesnt_retreive_sp_data_multiple_vnames(self):
        keys = {
            "species.genus.epithet": "Maxillaria",
            "species.epithet": "variabilis",
        }
        vname = VernacularName.retrieve(self.session, keys)
        self.assertIsNone(vname)

    def test_vernacular_name_retreives_vn_parts_only_one_sp(self):
        keys = {
            "name": "SomeName",
            "language": "English",
        }
        vname = VernacularName.retrieve(self.session, keys)
        self.assertEqual(vname.id, 1)

    def test_vernacular_name_doesnt_retreive_vn_parts_only_multiple_sp(self):
        keys = {
            "name": "Clamshell Orchid",
            "language": "English",
        }
        vname = VernacularName.retrieve(self.session, keys)
        self.assertIsNone(vname)

    def test_vernacular_name_retreives_full_data(self):
        keys = {
            "name": "SomeName",
            "language": "English",
            "species.epithet": "variabilis",
            "species.genus.epithet": "Maxillaria",
        }
        vname = VernacularName.retrieve(self.session, keys)
        self.assertEqual(vname.id, 1)

    def test_vernacular_name_retreives_id_only(self):
        keys = {"id": 5}
        vname = VernacularName.retrieve(self.session, keys)
        self.assertEqual(vname.species.id, 15)

    def test_vernacular_name_retreives_sp_id_only(self):
        keys = {"species.id": 15}
        vname = VernacularName.retrieve(self.session, keys)
        self.assertEqual(vname.id, 5)

    def test_vernacular_name_retreives_name_only_exists_once(self):
        keys = {"name": "Toé"}
        vname = VernacularName.retrieve(self.session, keys)
        self.assertEqual(vname.id, 4)

    def test_vernacular_name_doesnt_retreive_non_existent_name(self):
        keys = {"name": "NonExistent"}
        vname = VernacularName.retrieve(self.session, keys)
        self.assertIsNone(vname)
        # mismatch
        keys = {
            "name": "Clamshell orchid",
            "language": "English",
            "species.epithet": "variabilis",
            "species.genus.epithet": "Maxillaria",
        }
        vname = VernacularName.retrieve(self.session, keys)
        self.assertIsNone(vname)

    def test_vernacular_name_doesnt_retreive_wrong_keys(self):
        keys = {"name": "Somewhere Else", "code": "SE"}
        vname = VernacularName.retrieve(self.session, keys)
        self.assertIsNone(vname)

    def test_vernacular_name_doesnt_retreive_for_sp_non_existent_vname(self):
        keys = {
            "species.genus": "Campyloneurum",
            "species.sp": "alapense",
            "species.hybrid": "×",
        }
        with self.assertLogs(level="DEBUG") as logs:
            vname = VernacularName.retrieve(self.session, keys)
        string = f"retrieved species {species_str_map[4]}"
        self.assertTrue(any(string in i for i in logs.output))
        self.assertIsNone(vname)

    def test_species_retreives_full_sp_data(self):
        keys = {
            "sp": "cochleata",
            "genus.genus": "Encyclia",
            "infrasp1_rank": "subsp.",
            "infrasp1": "cochleata",
            "infrasp2_rank": "var.",
            "infrasp2": "cochleata",
            "cultivar_epithet": "Black",
        }
        sp = Species.retrieve(self.session, keys)
        self.assertEqual(sp.id, 15)
        # using hybrid property infrasp_parts
        keys = {
            "epithet": "cochleata",
            "genus.epithet": "Encyclia",
            "infrasp_parts": "subsp. cochleata var. cochleata",
            "cultivar_epithet": "Black",
        }
        sp = Species.retrieve(self.session, keys)
        self.assertEqual(sp.id, 15)

    def test_species_retreives_id_only(self):
        keys = {"id": 15}
        sp = Species.retrieve(self.session, keys)
        self.assertEqual(str(sp), species_str_map[15])

    def test_species_doesnt_retreive_incomplete_sp_data_multiple(self):
        keys = {
            "genus.epithet": "Encyclia",
            "epithet": "cochleata",
        }
        sp = Species.retrieve(self.session, keys)
        self.assertIsNone(sp)

    def test_species_doesnt_retreive_non_existent(self):
        keys = {
            "genus.epithet": "Encyclia",
            "epithet": "nonexistennt",
        }
        sp = Species.retrieve(self.session, keys)
        self.assertIsNone(sp)

    def test_species_doesnt_retreive_wrong_keys(self):
        keys = {"name": "Somewhere Else", "code": "SE"}
        sp = Species.retrieve(self.session, keys)
        self.assertIsNone(sp)

    def test_genus_retreives_full_data(self):
        keys = {
            "epithet": "Encyclia",
            "family.epithet": "Orchidaceae",
        }
        gen = Genus.retrieve(self.session, keys)
        self.assertEqual(gen.id, 2)

        keys = {
            "genus": "Encyclia",
            "family.family": "Orchidaceae",
        }
        gen = Genus.retrieve(self.session, keys)
        self.assertEqual(gen.id, 2)

    def test_genus_retreives_genus_only_unique_genus(self):
        keys = {
            "epithet": "Encyclia",
        }
        gen = Genus.retrieve(self.session, keys)
        self.assertEqual(gen.id, 2)

        keys = {
            "genus": "Encyclia",
        }
        gen = Genus.retrieve(self.session, keys)
        self.assertEqual(gen.id, 2)

    def test_genus_retreives_id_only(self):
        keys = {"id": 5}
        genus = Genus.retrieve(self.session, keys)
        self.assertEqual(genus.genus, "Paphiopedilum")

    def test_genus_doesnt_retreive_family_only(self):
        keys = {
            "family.family": "Orchidaceae",
        }
        genus = Genus.retrieve(self.session, keys)
        self.assertIsNone(genus)
        # single genus family
        keys = {
            "family.family": "Solanaceae",
        }
        genus = Genus.retrieve(self.session, keys)
        self.assertIsNone(genus)

    def test_genus_doesnt_retreive_non_existent(self):
        keys = {"family.family": "Orchidaceae", "genus": "Nonexistent"}
        genus = Genus.retrieve(self.session, keys)
        self.assertIsNone(genus)

    def test_genus_doesnt_retreive_wrong_keys(self):
        keys = {
            "name": "Somewhere Else",
            "code": "SE",
        }
        genus = Genus.retrieve(self.session, keys)
        self.assertIsNone(genus)

    def test_genus_retreive_2_entries_diff_authors(self):
        eric = Family(family="Ericaceae")
        g1 = Genus(genus="Azalea", author="L.", family=eric)
        g2 = Genus(genus="Azalea", author="Gaertn.", family=eric)
        self.session.add_all([g1, g2])
        self.session.commit()
        # fails, not unique
        keys = {
            "family": "Ericaceae",
            "genus": "Azalea",
        }
        genus = Genus.retrieve(self.session, keys)
        self.assertIsNone(genus)
        # with author suceeds
        keys = {"family": "Ericaceae", "genus": "Azalea", "author": "L."}
        genus = Genus.retrieve(self.session, keys)
        self.assertEqual(genus, g1)

        keys = {"family": "Ericaceae", "genus": "Azalea", "author": "Gaertn."}
        genus = Genus.retrieve(self.session, keys)
        self.assertEqual(genus, g2)

    def test_family_retreives(self):
        keys = {
            "epithet": "Orchidaceae",
        }
        fam = Family.retrieve(self.session, keys)
        self.assertEqual(fam.id, 1)
        keys = {
            "family": "Orchidaceae",
        }
        fam = Family.retrieve(self.session, keys)
        self.assertEqual(fam.id, 1)

    def test_family_retreives_id_only(self):
        keys = {"id": 4}
        fam = Family.retrieve(self.session, keys)
        self.assertEqual(fam.family, "Solanaceae")

    def test_family_doesnt_retreive_non_existent(self):
        keys = {"epithet": "Nonexistent"}
        fam = Family.retrieve(self.session, keys)
        self.assertIsNone(fam)

    def test_family_doesnt_retreive_wrong_keys(self):
        keys = {"name": "Somewhere Else", "accession": "2001.1"}
        fam = Family.retrieve(self.session, keys)
        self.assertIsNone(fam)

    def test_geography_retreives(self):
        setup_geographies()
        keys = {
            "code": "50",
        }
        geo = Geography.retrieve(self.session, keys)
        self.assertEqual(geo.name, "Australia")

        # test id only
        keys = {"id": 4}
        geo = Geography.retrieve(self.session, keys)
        self.assertEqual(geo.id, 4)

        # test non-existent
        keys = {"epithet": "Nonexistent"}
        geo = Geography.retrieve(self.session, keys)
        self.assertIsNone(geo)

        # test wrong keys
        keys = {
            "accession.code": "2001.1",
        }
        geo = Geography.retrieve(self.session, keys)
        self.assertIsNone(geo)


class SpeciesFullNameTests(PlantTestCase):
    def test_full_name_is_created_on_species_insert(self):
        gen = self.session.query(Genus).first()
        sp = Species(genus=gen, sp="sp. nov.")
        self.assertFalse(sp.full_name)
        self.session.add(sp)
        self.session.commit()
        self.assertEqual(sp.full_name, str(sp))
        hist_query = (
            self.session.query(db.History.values)
            .filter(db.History.table_name == "species")
            .filter(db.History.table_id == sp.id)
        )
        hist_entry = [
            entry for entry in hist_query if entry[0]["full_name"] == str(sp)
        ]
        self.assertEqual(len(hist_entry), 1)

    def test_full_name_is_created_on_all_insert(self):
        fam = Family(epithet="Fabaceae")
        gen = Genus(epithet="Acacia", family=fam)
        sp = Species(
            genus=gen,
            sp="dealbata",
            infrasp1_rank="subsp.",
            infrasp1="dealbata",
        )
        self.assertFalse(sp.full_name)
        self.session.add(sp)
        self.session.commit()
        self.assertEqual(sp.full_name, "Acacia dealbata subsp. dealbata")
        hist_query = (
            self.session.query(db.History.values)
            .filter(db.History.table_name == "species")
            .filter(db.History.table_id == sp.id)
        )
        hist_entry = [
            entry for entry in hist_query if entry[0]["full_name"] == str(sp)
        ]
        self.assertEqual(len(hist_entry), 1)

    def test_full_name_updated_on_species_update(self):
        # check update any epithet, infrasp or ranks, group, cv, etc.
        # Epithet
        sp = self.session.get(Species, 1)
        sp.epithet = "sophronitis"
        self.session.add(sp)
        self.session.commit()
        self.assertEqual(sp.full_name, str(sp))
        # infrasp
        sp.infrasp1_rank = "var."
        sp.infrasp1 = "sophronitis"
        self.session.add(sp)
        self.session.commit()
        self.assertEqual(sp.full_name, str(sp))
        # group
        sp.group = "Test"
        self.session.add(sp)
        self.session.commit()
        self.assertEqual(sp.full_name, str(sp))
        # cv
        start = sp.full_name
        sp.cultivar_epithet = "Red"
        self.session.add(sp)
        self.session.commit()
        self.assertEqual(sp.full_name, str(sp))
        hist_query = (
            self.session.query(db.History.values)
            .filter(db.History.table_name == "species")
            .filter(db.History.table_id == 1)
        )
        hist_entry = [
            entry
            for entry in hist_query
            if entry[0]["full_name"] == [str(sp), start]
        ]
        self.assertEqual(len(hist_entry), 1)

    def test_full_name_updated_on_genus_update(self):
        # check epithet, hybrid, etc.
        # new genus
        fam = self.session.get(Family, 1)
        gen = Genus(epithet="Ornithidium", family=fam)
        sp = self.session.get(Species, 1)
        sp.genus = gen
        self.session.add(gen)
        self.session.commit()
        self.assertEqual(sp.full_name, str(sp))
        # update genus name
        sp.genus.epithet = "Anguloa"
        self.session.add(sp)
        self.session.commit()
        self.assertEqual(gen.epithet, "Anguloa")
        self.assertEqual(sp.full_name, str(sp))
        hist_query = (
            self.session.query(db.History.values)
            .filter(db.History.table_name == "species")
            .filter(db.History.table_id == 1)
        )
        hist_entry = [
            entry
            for entry in hist_query
            if entry[0]["full_name"]
            == ["Anguloa variabilis", "Ornithidium variabilis"]
        ]
        self.assertEqual(len(hist_entry), 1)
        # update genus hybrid
        sp.genus.hybrid = "×"
        self.session.add(sp)
        self.session.commit()
        self.assertEqual(sp.full_name, str(sp))
        hist_query = (
            self.session.query(db.History.values)
            .filter(db.History.table_name == "species")
            .filter(db.History.table_id == 1)
        )
        hist_entry = [
            entry
            for entry in hist_query
            if entry[0]["full_name"]
            == ["× Anguloa variabilis", "Anguloa variabilis"]
        ]
        self.assertEqual(len(hist_entry), 1)

    def test_full_name_updated_on_genus_and_sp_update(self):
        # change to another existing genus
        sp = self.session.get(Species, 1)
        start = sp.full_name
        gen = self.session.get(Genus, sp.genus_id + 1)
        sp.genus = gen
        sp.epither = "test_new"
        self.session.add(sp)
        self.session.commit()
        self.assertEqual(sp.full_name, str(sp))
        self.assertNotEqual(sp.full_name, start)
        hist_query = (
            self.session.query(db.History.values)
            .filter(db.History.table_name == "species")
            .filter(db.History.table_id == 1)
        )
        hist_entry = [
            entry
            for entry in hist_query
            if entry[0]["full_name"] == [str(sp), start]
        ]
        self.assertEqual(len(hist_entry), 1)

    def test_full_name_no_change_no_update_no_history(self):
        # set full_names (test data is added not triggering event.listens_for)
        list(update_all_full_names_task())
        hist_query = (
            self.session.query(db.History.values)
            .filter(db.History.table_name == "species")
            .filter(db.History.table_id == 1)
        )
        start_count = hist_query.count()
        sp = self.session.get(Species, 1)
        start = sp.full_name
        sp.epithet = "variabilis"
        self.session.add(sp)
        self.session.commit()
        self.assertEqual(sp.full_name, str(sp))
        self.assertEqual(sp.full_name, start)
        end_count = hist_query.count()
        self.assertEqual(start_count, end_count)

    def test_update_all_full_names_task(self):
        hist_query = self.session.query(db.History.values).filter(
            db.History.table_name == "species"
        )
        start_count = hist_query.count()
        list(update_all_full_names_task())
        sp_query = self.session.query(Species)
        for sp in sp_query:
            if sp.id in species_str_map:
                self.assertEqual(sp.full_name, species_str_map.get(sp.id))
        end_count = hist_query.count()
        # one history entry per species
        self.assertEqual(end_count, start_count + sp_query.count())
