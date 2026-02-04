# Copyright (c) 2025 Ross Demuth <rossdemuth123@gmail.com>
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
Tests for the SQL search dialog.
"""
import warnings

from bauble import prefs
from bauble import search
from bauble.plugins.plants.family import Family
from bauble.plugins.plants.genus import Genus
from bauble.plugins.plants.geography import Geography
from bauble.plugins.plants.species_model import Species
from bauble.plugins.plants.species_model import SpeciesDistribution
from bauble.plugins.plants.test_plants import setup_geographies
from bauble.search.sql_search import SQLSearchDialog
from bauble.search.strategies import MapperSearch
from bauble.test import BaubleTestCase
from bauble.test import get_setUp_data_funcs


class DialogTests(BaubleTestCase):
    def test_sql_search_dialog_init(self):
        dialog = SQLSearchDialog()
        self.assertEqual(dialog.sql, "")
        self.assertEqual(dialog.domain, "")
        self.assertFalse(dialog.ok_button.get_sensitive())
        dialog.destroy()

    def test_domain_change_sets_ok_sensitive(self):
        dialog = SQLSearchDialog()
        dialog.domain_combo.set_active(0)

        self.assertEqual(
            dialog.domain,
            sorted(MapperSearch.get_domain_classes().keys())[0],
        )
        # generates starting of SQL
        self.assertEqual(dialog.sql, f"SELECT * FROM {dialog.domain} WHERE")
        self.assertTrue(dialog.ok_button.get_sensitive())
        dialog.destroy()

    def test_text_buffer_changed_sets_sql_and_ok_sensitive(self):
        dialog = SQLSearchDialog()

        dialog.sql_textbuffer.set_text("SELECT * FROM species WHERE 1=1")

        self.assertEqual(dialog.sql, "SELECT * FROM species WHERE 1=1")
        # still no domain
        self.assertFalse(dialog.ok_button.get_sensitive())

        dialog.domain = "species"
        dialog.sql_textbuffer.set_text("SELECT * FROM species WHERE sp=spam")

        self.assertTrue(dialog.ok_button.get_sensitive())
        dialog.destroy()

    def test_set_query_no_text_logs(self):
        dialog = SQLSearchDialog()

        with self.assertLogs(level="DEBUG") as logs:
            dialog.set_query("")

        string = "sql_search:ParseException("
        self.assertTrue(any(string in i for i in logs.output))

        self.assertEqual(dialog.sql, "")
        self.assertEqual(dialog.domain, "")
        dialog.destroy()

    def test_set_query_no_sql_text_logs(self):
        dialog = SQLSearchDialog()

        with self.assertLogs(level="DEBUG") as logs:
            dialog.set_query(":SQL")

        string = "no text to set query to."
        self.assertTrue(any(string in i for i in logs.output))

        self.assertEqual(dialog.sql, "")
        self.assertEqual(dialog.domain, "")
        dialog.destroy()

    def test_set_query_no_domain_text_logs(self):
        dialog = SQLSearchDialog()

        with self.assertLogs(level="DEBUG") as logs:
            dialog.set_query(':SQL = "SELECT species where id = 1"')

        string = 'sql_search:domain "SELECT not valid'
        self.assertTrue(any(string in i for i in logs.output))

        self.assertEqual(dialog.sql, "")
        self.assertEqual(dialog.domain, "")
        dialog.destroy()

    def test_set_query_bad_domain_text_logs(self):
        dialog = SQLSearchDialog()

        with self.assertLogs(level="DEBUG") as logs:
            dialog.set_query(':SQL = spam "SELECT species where id = 1"')

        string = "domain spam not valid"
        self.assertTrue(any(string in i for i in logs.output))

        self.assertEqual(dialog.sql, "")
        self.assertEqual(dialog.domain, "")
        dialog.destroy()

    def test_set_query_sql(self):
        dialog = SQLSearchDialog()

        string = ":SQL = species 'SELECT species WHERE sp=eggs'"
        dialog.set_query(string)

        self.assertEqual(dialog.domain, "species")
        self.assertEqual(dialog.sql, "SELECT species WHERE sp=eggs")
        self.assertTrue(dialog.ok_button.get_sensitive())
        dialog.destroy()

    def test_set_query_w_mapper_search(self):
        dialog = SQLSearchDialog()

        string = "species where sp=eggs"
        dialog.set_query(string)

        self.assertEqual(dialog.domain, "species")
        self.assertTrue(dialog.sql.startswith("SELECT species"))
        sql = "FROM species \nWHERE species.sp = 'eggs'"
        mssql = "FROM species \nWHERE species.sp = N'eggs'"
        self.assertTrue(
            any(
                (
                    dialog.sql.endswith(sql),
                    dialog.sql.endswith(mssql),
                )
            )
        )
        self.assertTrue(dialog.ok_button.get_sensitive())
        dialog.destroy()

    def test_get_query_domain_search(self):
        dialog = SQLSearchDialog()

        string = "loc=eggs"
        dialog.set_query(string)

        self.assertTrue(dialog.sql.startswith("SELECT location"))
        sql = (
            "FROM location \nWHERE location.name = 'eggs' OR "
            "location.code = 'eggs'"
        )
        mssql = (
            "FROM location \nWHERE location.name = N'eggs' OR "
            "location.code = N'eggs'"
        )
        self.assertTrue(
            any(
                (
                    dialog.sql.endswith(sql),
                    dialog.sql.endswith(mssql),
                )
            )
        )
        self.assertTrue(dialog.ok_button.get_sensitive())
        dialog.destroy()

    def test_queries_return_same_results(self):
        # test that converting a MapperSearch or DomainSearch query to SQL
        # returns the same results and can be reused multiple times reliably
        # (checks escaping etc.)
        for func in get_setUp_data_funcs():
            func()
        setup_geographies()
        prefs.prefs[prefs.enable_raw_sql_search_pref] = True
        poaceae = (
            self.session.query(Family).filter_by(epithet="Poaceae").first()
        )
        poa = Genus(epithet="Poa", family=poaceae)
        p_sieberiana = Species(
            epithet="sieberiana",
            genus=poa,
            distribution=[
                SpeciesDistribution(geography=i)
                for i in self.session.query(Geography)
                .filter(
                    Geography.name.in_(
                        [
                            "New South Wales",
                            "Queensland",
                            "South Australia",
                            "Tasmania",
                            "Victoria",
                        ]
                    )
                )
                .filter(Geography.level == 3)
            ],
        )
        p_labillardierei = Species(
            epithet="labillardierei",
            genus=poa,
            distribution=[
                SpeciesDistribution(geography=i)
                for i in self.session.query(Geography)
                .filter(
                    Geography.name.in_(
                        [
                            "New South Wales",
                            "Queensland",
                            "South Australia",
                            "Tasmania",
                            "Victoria",
                        ]
                    )
                )
                .filter(Geography.level == 3)
            ],
        )
        p_cheelii = Species(
            epithet="cheelii",
            genus=poa,
            distribution=[
                SpeciesDistribution(geography=i)
                for i in self.session.query(Geography)
                .filter(
                    Geography.name.in_(
                        [
                            "New South Wales",
                            "Queensland",
                        ]
                    )
                )
                .filter(Geography.level == 3)
            ],
        )
        p_cheelii.awards = "Gold_Medal"
        p_cheelii.sp_author = "%Ewart"
        self.session.add_all([p_sieberiana, p_cheelii, p_labillardierei])
        self.session.commit()

        dialog = SQLSearchDialog()
        # both complex MapperSearch and simple DomainSearch queries
        queries = [
            "species where id < 3",
            "species where awards like '%d\\_Me%'",
            "species where sp_author like '\\%Ew%'",
            "species where genus.epithet = 'Poa' "
            "and sum(distribution.geography.approx_area) = "
            "(max(sum(species.distribution.geography.approx_area)) "
            "where genus.epithet = 'Poa')",
            "fam = 'Myrtaceae'",
            'fam = "Myrtaceae"',
            "fam like 'Myrt%'",
        ]

        # DeprecatedWarning invalid escape sequence \_
        with warnings.catch_warnings(action="ignore"):
            for query in queries:
                self.assertTrue(
                    search.search(query, self.session),
                    f"no results for query: {query}",
                )
                dialog.set_query(query)
                dialog_query = "SQL:" + dialog.get_query()[6:]

                self.assertTrue(
                    len(search.search(dialog_query, self.session)) > 0
                )
                self.assertCountEqual(
                    search.search(query, self.session),
                    search.search(dialog_query, self.session),
                    query,
                )

                # reuse to check does not mutate the query (escaping etc.)
                dialog.set_query(dialog.get_query())
                dialog_query = "SQL:" + dialog.get_query()[6:]
                self.assertCountEqual(
                    search.search(query, self.session),
                    search.search(dialog_query, self.session),
                    query,
                )

        dialog.destroy()
