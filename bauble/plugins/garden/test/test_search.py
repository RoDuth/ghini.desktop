# Copyright 2008-2010 Brett Adams
# Copyright 2015,2017 Mario Frasca <mario@anche.no>.
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
"""
Search tests
"""
from unittest import mock

from pyparsing import ParseException

from bauble import search
from bauble.plugins.plants.family import Family
from bauble.plugins.plants.genus import Genus
from bauble.plugins.plants.species import Species
from bauble.test import BaubleTestCase

from ..accession import Accession
from ..location import Location
from ..plant import Plant
from ..search import PlantSearch
from ..search import in_query
from ..search import queries


class PlantSearchTests(BaubleTestCase):
    def setUp(self):
        super().setUp()

        fam = Family(family="Myrtaceae")
        gen = Genus(family=fam, genus="Eucalyptus")
        spc = Species(sp="curtisii", genus=gen)
        acc1 = Accession(code="XXXX", species=spc)
        acc2 = Accession(code="YYYY", species=spc)
        loc = Location(code="Bed1")
        # XXXX.1
        self.plt1 = Plant(code="1", quantity=1, accession=acc1, location=loc)
        # XXXX.2
        self.plt2 = Plant(code="2", quantity=1, accession=acc1, location=loc)
        # YYYY.1
        self.plt3 = Plant(code="1", quantity=1, accession=acc2, location=loc)
        # YYYY.3
        self.plt4 = Plant(code="3", quantity=1, accession=acc2, location=loc)
        self.session.add_all(
            [
                fam,
                gen,
                spc,
                acc1,
                acc2,
                loc,
                self.plt1,
                self.plt2,
                self.plt3,
                self.plt3,
            ]
        )
        self.session.commit()

    def test_plant_search_directly(self):
        plant_search = search.strategies.get_strategy("PlantSearch")
        self.assertTrue(isinstance(plant_search, PlantSearch))

        qry = "planting = XXXX.1"
        results = plant_search.search(qry, self.session)[0].all()
        self.assertEqual(results, [self.plt1])

    def test__eq__plant_search(self):
        qry = 'planting = "XXXX.1"'
        with self.assertLogs(level="DEBUG") as logs:
            results = search.search(qry, self.session)
        string = f'SearchStrategy "{qry}" (PlantSearch)'
        self.assertTrue(any(string in i for i in logs.output))
        string = '"equals" PlantSearch accession: XXXX plant: 1'
        self.assertTrue(any(string in i for i in logs.output))
        self.assertEqual(results, [self.plt1])

    def test__in__plant_search(self):
        qry = "planting in XXXX.1 YYYY.3"
        with self.assertLogs(level="DEBUG") as logs:
            results = search.search(qry, self.session)
        string = f'SearchStrategy "{qry}" (PlantSearch)'
        self.assertTrue(any(string in i for i in logs.output))
        string = "\"in\" PlantSearch val_list: [('XXXX', '1'), ('YYYY', '3')]"
        self.assertTrue(any(string in i for i in logs.output))
        self.assertCountEqual(results, [self.plt1, self.plt4])

        qry = "planting in 'XXXX.1' 'YYYY.3'"
        with self.assertLogs(level="DEBUG") as logs:
            results = search.search(qry, self.session)
        string = f'SearchStrategy "{qry}" (PlantSearch)'
        self.assertTrue(any(string in i for i in logs.output))
        string = "\"in\" PlantSearch val_list: [('XXXX', '1'), ('YYYY', '3')]"
        self.assertTrue(any(string in i for i in logs.output))
        self.assertCountEqual(results, [self.plt1, self.plt4])

    def test__not_eq__plant_search(self):
        qry = "planting != XXXX.1"
        with self.assertLogs(level="DEBUG") as logs:
            results = search.search(qry, self.session)
        string = f'SearchStrategy "{qry}" (PlantSearch)'
        self.assertTrue(any(string in i for i in logs.output))
        string = '"not equals" PlantSearch accession: XXXX plant: "1"'
        self.assertTrue(any(string in i for i in logs.output))
        self.assertCountEqual(results, [self.plt2, self.plt3, self.plt4])

        qry = "planting <> YYYY.1"
        results = search.search(qry, self.session)
        self.assertCountEqual(results, [self.plt2, self.plt1, self.plt4])

    def test__star__plant_search(self):
        qry = "planting = *"
        with self.assertLogs(level="DEBUG") as logs:
            results = search.search(qry, self.session)
        string = f'SearchStrategy "{qry}" (PlantSearch)'
        self.assertTrue(any(string in i for i in logs.output))
        string = '"star" PlantSearch, returning all plants'
        self.assertTrue(any(string in i for i in logs.output))
        self.assertCountEqual(
            results, [self.plt1, self.plt2, self.plt3, self.plt4]
        )

        qry = "planting != *"
        self.assertEqual(search.search(qry, self.session), [])

    def test__contains__plant_search(self):
        qry = "planting contains XX"
        with self.assertLogs(level="DEBUG") as logs:
            results = search.search(qry, self.session)
        string = f'SearchStrategy "{qry}" (PlantSearch)'
        self.assertTrue(any(string in i for i in logs.output))
        string = '"contains" PlantSearch accession: XX plant: XX'
        self.assertTrue(any(string in i for i in logs.output))
        self.assertCountEqual(results, [self.plt1, self.plt2])

        qry = "plant contains .1"
        with self.assertLogs(level="DEBUG") as logs:
            results = search.search(qry, self.session)
        string = f'SearchStrategy "{qry}" (PlantSearch)'
        self.assertTrue(any(string in i for i in logs.output))
        string = '"contains" PlantSearch accession:  plant: 1'
        self.assertTrue(any(string in i for i in logs.output), logs.output)
        self.assertCountEqual(results, [self.plt1, self.plt3])

    def test__like__plant_search(self):
        qry = "planting like XX%.1"
        with self.assertLogs(level="DEBUG") as logs:
            results = search.search(qry, self.session)
        string = f'SearchStrategy "{qry}" (PlantSearch)'
        self.assertTrue(any(string in i for i in logs.output))

        string = '"like" PlantSearch accession: XX% plant: 1'
        self.assertTrue(any(string in i for i in logs.output))
        self.assertCountEqual(results, [self.plt1])

        qry = "planting like XX%.%"
        with self.assertLogs(level="DEBUG") as logs:
            results = search.search(qry, self.session)
        string = f'SearchStrategy "{qry}" (PlantSearch)'
        self.assertTrue(any(string in i for i in logs.output))
        string = '"like" PlantSearch accession: XX% plant: %'
        self.assertTrue(any(string in i for i in logs.output))
        self.assertCountEqual(results, [self.plt1, self.plt2])

        qry = "planting like XX%"
        with self.assertLogs(level="DEBUG") as logs:
            results = search.search(qry, self.session)
        string = f'SearchStrategy "{qry}" (PlantSearch)'
        self.assertTrue(any(string in i for i in logs.output))
        string = '"like" PlantSearch accession: XX% plant: '
        self.assertTrue(any(string in i for i in logs.output))
        self.assertCountEqual(results, [self.plt1, self.plt2])

    def test_in_query_mssql(self):
        with mock.patch("bauble.db.engine") as mock_engine:
            mock_engine.name = "mssql"
            query = in_query(self.session, ["XXXX.1", "YYYY.1"])
            self.assertIn("EXISTS", str(query))

    def test_parser_error(self):
        qry = "planting like XX%.1"
        with self.assertLogs(level="DEBUG") as logs:
            with mock.patch.object(
                PlantSearch, "domain_expression"
            ) as mock_exp:
                mock_exp.parse_string.side_effect = ParseException("BOOM")
                results = search.search(qry, self.session)
        string = "PlantSearch ParseException(BOOM"
        self.assertTrue(any(string in i for i in logs.output), logs.output)

        self.assertEqual(results, [])

    def test_no_query_func_for_operator(self):
        qry = "planting like XX%.1"
        with self.assertLogs(level="DEBUG") as logs:
            with mock.patch.dict(queries, {"like": None}):
                results = search.search(qry, self.session)

        string = "PlantSearch no query for operator: like"
        self.assertTrue(any(string in i for i in logs.output), logs.output)

        self.assertEqual(results, [])
