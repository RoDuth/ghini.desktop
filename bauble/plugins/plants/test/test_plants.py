# pylint: disable=no-self-use,protected-access,too-many-public-methods
# Copyright 2008-2010 Brett Adams
# Copyright 2015 Mario Frasca <mario@anche.no>.
# Copyright 2017 Jardín Botánico de Quito
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
Plants plugin tests
"""

from datetime import datetime
from datetime import timedelta
from unittest import mock

from sqlalchemy import func
from sqlalchemy import select

from bauble import db
from bauble import prefs
from bauble import utils
from bauble.test import BaubleClassTestCase
from bauble.test import BaubleTestCase

from .. import PlantsPlugin
from ..family import Family
from ..family import FamilyNote
from ..family import FamilySynonym
from ..genus import Genus
from ..genus import GenusNote
from ..species import Species
from ..species import SpeciesNote
from ..species import SpeciesSynonym
from ..species import VernacularName

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
        "full_sci_name": (
            "Abrus precatorius L. (SomethingRidiculous Group) 'Hot Rio Nights'"
        ),
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
        "full_sci_name": (
            "Encyclia cochleata L. subsp. cochleata L. var. cochleata L. "
            "'Black'"
        ),
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
        "full_sci_name": (
            "Cynodon dactylon × transvaalensis 'DT-1' (PBR) TIFTUF™"
        ),
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


def setUp_data():  # pylint: disable=invalid-name
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


class PlantsPluginTests(BaubleClassTestCase):

    @mock.patch("bauble.plugins.plants.strategies")
    def test_init_no_mapper_search_bails(self, mock_strategies):
        # just tests the type narrowing
        mock_strategies.get_strategy.return_value = None
        PlantsPlugin.init()
        mock_strategies.add_strategy.assert_not_called()

    def test_install_w_existing_doesnt_overwrite(self):
        # test that if the plugin is installed on an existing database it
        # doesn't overwrite the existing data
        family = Family(family="TestFamily")
        self.session.add(family)
        self.session.commit()
        PlantsPlugin.install()
        with db.engine.connect() as conn:
            result = conn.scalar(select(func.count()).select_from(Family))

            self.assertEqual(result, 1)

    @mock.patch("bauble.plugins.plants.db")
    def test_install_raises_w_db_error(self, mock_db):
        mock_db.engine.connect.side_effect = Exception("BOOM")
        self.assertRaises(Exception, PlantsPlugin.install)


class CitesStatusTests(PlantTestCase):
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
