# Copyright (c) 2017 Mario Frasca <mario@anche.no>
# Copyright (c) 2021-2023 Ross Demuth <rossdemuth123@gmail.com>
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

import unittest
from sqlalchemy.orm import class_mapper
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm.attributes import InstrumentedAttribute
from bauble import paths
from bauble.query_builder import (BuiltQuery,
                                  QueryBuilder,
                                  SchemaMenu,
                                  parse_typed_value)
from bauble.search import EmptyToken
from bauble.test import BaubleTestCase
from bauble.editor import GenericEditorView
from bauble.plugins.garden.plant import Plant
from bauble.plugins.plants.species import Species


class ParseTypedValue(BaubleTestCase):
    def test_parse_typed_value_floats(self):
        from sqlalchemy import Float
        result = parse_typed_value('0.0', Float())
        self.assertEqual(result, '0.0')
        result = parse_typed_value('-4.0', Float())
        self.assertEqual(result, '-4.0')

    def test_parse_typed_value_int(self):
        from sqlalchemy import Integer
        result = parse_typed_value('0', Integer())
        self.assertEqual(result, '0')
        result = parse_typed_value('-4', Integer())
        self.assertEqual(result, '-4')

    def test_parsed_typed_value_bool(self):
        from bauble.btypes import Boolean
        result = parse_typed_value('True', Boolean())
        self.assertEqual(result, 'True')
        result = parse_typed_value('False', Boolean())
        self.assertEqual(result, 'False')
        result = parse_typed_value(None, Boolean())
        self.assertIsNone(result.express())

    def test_parse_typed_value_date(self):
        from bauble.btypes import DateTime, Date
        result = parse_typed_value('1-1-20', Date())
        self.assertEqual(result, '1-1-20')
        result = parse_typed_value('1/1/20', Date())
        self.assertEqual(result, '1/1/20')
        result = parse_typed_value('2020/1/1', DateTime())
        self.assertEqual(result, '2020/1/1')
        result = parse_typed_value('2020-1-1', Date())
        self.assertEqual(result, '2020-1-1')
        result = parse_typed_value("15 Feb 1999", Date())
        self.assertEqual(result, "'15 Feb 1999'")
        result = parse_typed_value("15 Feb '99", DateTime())
        self.assertEqual(result, '"15 Feb \'99"')
        result = parse_typed_value('yesterday', Date())
        self.assertEqual(result, 'yesterday')
        result = parse_typed_value('today', DateTime())
        self.assertEqual(result, 'today')

    def test_parse_typed_value_none(self):
        result = parse_typed_value('None', None)
        self.assertEqual(str(result), '(None<NoneType>)')
        self.assertIsNone(result.express())
        result = parse_typed_value("'None'", None)
        self.assertEqual(result, "'None'")

    def test_parse_typed_value_empty_set(self):
        result = parse_typed_value('Empty', None)
        self.assertEqual(type(result), EmptyToken)

    def test_parse_typed_value_fallback(self):
        result = parse_typed_value('whatever else', None)
        self.assertEqual(result, "'whatever else'")


class SchemaMenuTests(BaubleTestCase):
    def setUp(self):
        super().setUp()
        self.selected = []

    def menu_activated(self, widget, path, prop):
        self.selected.append((path, prop))

    @staticmethod
    def key(prop):
        key = prop.key if hasattr(prop, 'key') else prop.__name__
        return key

    def test_menu_populates_w_plants(self):
        schema_menu = SchemaMenu(class_mapper(Plant), self.menu_activated)
        for i in class_mapper(Plant).all_orm_descriptors:
            key = self.key(i)
            self.assertTrue(key in [j.get_label() for j in
                                    schema_menu.get_children()],
                            f'key:{key} not found in schema menu')

    def test_menu_populates_w_species(self):
        mapper = class_mapper(Species)
        schema_menu = SchemaMenu(mapper, self.menu_activated)
        for i in class_mapper(Species).all_orm_descriptors:
            if (isinstance(i, (hybrid_property, InstrumentedAttribute)) or
                    i.key in [i.key for i in mapper.synonyms]):
                key = self.key(i)
                self.assertTrue(key in [j.get_label() for j in
                                        schema_menu.get_children()],
                                f'key:{key} not found in schema menu')
            else:
                key = self.key(i)
                self.assertFalse(key in [j.get_label() for j in
                                         schema_menu.get_children()],
                                 f'key:{key} should not be in schema menu')

    def test_selectable_relations(self):
        schema_menu = SchemaMenu(class_mapper(Plant),
                                 self.menu_activated,
                                 selectable_relations=True)
        for i in class_mapper(Plant).all_orm_descriptors:
            key = self.key(i)
            self.assertTrue(key in [j.get_label() for j in
                                    schema_menu.get_children()],
                            f'key:{key} not found in schema menu')
            self.assertTrue(
                'plant' in [i.get_label() for i in schema_menu.get_children()])
        items = {i.get_label(): i for i in schema_menu.get_children()}
        schema_menu.on_activate(items.get('plant'), None)
        self.assertTrue(('plant', None) in self.selected)

    def test_column_filter(self):
        def test_filter(key, prop):
            if key == 'code':
                return False
            return True

        schema_menu = SchemaMenu(class_mapper(Plant),
                                 self.menu_activated,
                                 column_filter=test_filter)
        self.assertFalse('code' in [i.get_label() for i in
                                    schema_menu.get_children()],
                         'key:code should be filtered from schema menu')

    def test_relation_filter(self):
        def test_filter(key, prop):
            if key == 'accession':
                return False
            return True

        schema_menu = SchemaMenu(class_mapper(Plant),
                                 self.menu_activated,
                                 relation_filter=test_filter)
        self.assertFalse('accession' in [i.get_label() for i in
                                         schema_menu.get_children()],
                         'key:accession should be filtered from schema menu')

    def test_on_activate(self):
        schema_menu = SchemaMenu(class_mapper(Plant), self.menu_activated)
        items = {i.get_label(): i for i in schema_menu.get_children()}
        schema_menu.on_activate(items.get('code'), None)
        self.assertTrue(('code', None) in self.selected)

    def test_on_select(self):
        schema_menu = SchemaMenu(class_mapper(Plant), self.menu_activated)
        items = {i.get_label(): i for i in schema_menu.get_children()}
        schema_menu.on_select(items.get('accession'), Plant.accession)
        sub_menu = items.get('accession').get_submenu()
        self.assertEqual(sub_menu.get_children()[0].get_label(),
                         'id')

    def test_on_activate_with_submenus(self):
        schema_menu = SchemaMenu(class_mapper(Plant), self.menu_activated)
        items = {i.get_label(): i for i in schema_menu.get_children()}
        schema_menu.on_select(items.get('accession'), Plant.accession)
        sub_menu = items.get('accession').get_submenu()
        schema_menu.on_activate(sub_menu.get_children()[0], None)
        self.assertTrue(('accession.id', None) in self.selected)

    def test_on_activate_w_selecable_relations_submenus(self):
        schema_menu = SchemaMenu(class_mapper(Plant),
                                 self.menu_activated,
                                 selectable_relations=True)
        items = {i.get_label(): i for i in schema_menu.get_children()}
        schema_menu.on_select(items.get('accession'), Plant.accession)
        sub_menu = items.get('accession').get_submenu()
        from bauble.plugins.garden.accession import Accession
        schema_menu.on_activate(sub_menu.get_children()[0], Accession)
        self.assertTrue(('accession', Accession) in self.selected,
                        f'{self.selected}')


class QueryBuilderTests(BaubleTestCase):

    def test_cancreatequerybuilder(self):
        import os
        gladefilepath = os.path.join(paths.lib_dir(), "querybuilder.glade")
        view = GenericEditorView(
            gladefilepath,
            parent=None,
            root_widget_name='main_dialog')
        QueryBuilder(view)

    def test_emptyisinvalid(self):
        import os
        gladefilepath = os.path.join(paths.lib_dir(), "querybuilder.glade")
        view = GenericEditorView(
            gladefilepath,
            parent=None,
            root_widget_name='main_dialog')
        qb = QueryBuilder(view)
        self.assertFalse(qb.validate())

    def test_cansetquery(self):
        import os
        gladefilepath = os.path.join(paths.lib_dir(), "querybuilder.glade")
        view = GenericEditorView(
            gladefilepath,
            parent=None,
            root_widget_name='main_dialog')
        qb = QueryBuilder(view)
        qb.set_query('plant where id=0 or id=1 or id>10')
        self.assertEqual(len(qb.expression_rows), 3)

    def test_cansetenumquery(self):
        import os
        gladefilepath = os.path.join(paths.lib_dir(), "querybuilder.glade")
        view = GenericEditorView(
            gladefilepath,
            parent=None,
            root_widget_name='main_dialog')
        qb = QueryBuilder(view)
        qb.set_query("accession where recvd_type = 'BBIL'")
        self.assertEqual(len(qb.expression_rows), 1)

    def test_invalid_domain(self):
        import os
        gladefilepath = os.path.join(paths.lib_dir(), "querybuilder.glade")
        view = GenericEditorView(
            gladefilepath,
            parent=None,
            root_widget_name='main_dialog')
        qb = QueryBuilder(view)
        qb.set_query("nonexistentdomain where id = 1")
        self.assertFalse(qb.validate())

    def test_invalid_target(self):
        import os
        gladefilepath = os.path.join(paths.lib_dir(), "querybuilder.glade")
        view = GenericEditorView(
            gladefilepath,
            parent=None,
            root_widget_name='main_dialog')
        qb = QueryBuilder(view)
        qb.set_query("plant where accession.invalid = 1")
        self.assertFalse(qb.validate())

    def test_invalid_query(self):
        import os
        gladefilepath = os.path.join(paths.lib_dir(), "querybuilder.glade")
        view = GenericEditorView(
            gladefilepath,
            parent=None,
            root_widget_name='main_dialog')
        qb = QueryBuilder(view)
        qb.set_query("plant where id between 1 and 10")
        self.assertFalse(qb.validate())

    def test_empty_query(self):
        import os
        gladefilepath = os.path.join(paths.lib_dir(), "querybuilder.glade")
        view = GenericEditorView(
            gladefilepath,
            parent=None,
            root_widget_name='main_dialog')
        qb = QueryBuilder(view)
        query = "plant where notes.id = Empty"
        qb.set_query(query)
        self.assertTrue(qb.validate())
        # should drop the attribute
        self.assertEqual(qb.get_query(), "plant where notes = Empty")

    def test_none_string_query(self):
        import os
        gladefilepath = os.path.join(paths.lib_dir(), "querybuilder.glade")
        view = GenericEditorView(
            gladefilepath,
            parent=None,
            root_widget_name='main_dialog')
        qb = QueryBuilder(view)
        query = "plant where notes.category = 'None'"
        qb.set_query(query)
        self.assertTrue(qb.validate())
        self.assertEqual(qb.get_query(), query)

    def test_nonetype_query(self):
        import os
        gladefilepath = os.path.join(paths.lib_dir(), "querybuilder.glade")
        view = GenericEditorView(
            gladefilepath,
            parent=None,
            root_widget_name='main_dialog')
        qb = QueryBuilder(view)
        query = "plant where notes.category = None"
        qb.set_query(query)
        self.assertTrue(qb.validate())
        self.assertEqual(qb.get_query(), query)

    def test_boolean_query(self):
        import os
        gladefilepath = os.path.join(paths.lib_dir(), "querybuilder.glade")
        view = GenericEditorView(
            gladefilepath,
            parent=None,
            root_widget_name='main_dialog')
        qb = QueryBuilder(view)
        query = "plant where memorial = True"
        qb.set_query(query)
        self.assertTrue(qb.validate())
        self.assertEqual(qb.get_query(), query)

    def test_date_query(self):
        import os
        gladefilepath = os.path.join(paths.lib_dir(), "querybuilder.glade")
        view = GenericEditorView(
            gladefilepath,
            parent=None,
            root_widget_name='main_dialog')
        qb = QueryBuilder(view)
        # isoparse
        query = "plant where _created = 2020-02-01"
        qb.set_query(query)
        self.assertTrue(qb.validate())
        self.assertEqual(qb.get_query(), query)
        # parse
        query = "plant where _created = 01-02-2020"
        qb.set_query(query)
        self.assertTrue(qb.validate())
        self.assertEqual(qb.get_query(), query)

    def test_int_query(self):
        import os
        gladefilepath = os.path.join(paths.lib_dir(), "querybuilder.glade")
        view = GenericEditorView(
            gladefilepath,
            parent=None,
            root_widget_name='main_dialog')
        qb = QueryBuilder(view)
        query = "plant where quantity > 2"
        qb.set_query(query)
        self.assertTrue(qb.validate())
        self.assertEqual(qb.get_query(), query)

    def test_float_query(self):
        import os
        gladefilepath = os.path.join(paths.lib_dir(), "querybuilder.glade")
        view = GenericEditorView(
            gladefilepath,
            parent=None,
            root_widget_name='main_dialog')
        qb = QueryBuilder(view)
        query = "collection where elevation > 0.01"
        qb.set_query(query)
        self.assertTrue(qb.validate())
        self.assertEqual(qb.get_query(), query)

    def test_not_translated_enum_query(self):
        import os
        gladefilepath = os.path.join(paths.lib_dir(), "querybuilder.glade")
        view = GenericEditorView(
            gladefilepath,
            parent=None,
            root_widget_name='main_dialog')
        qb = QueryBuilder(view)
        query = "family where qualifier = 's. lat.'"
        qb.set_query(query)
        self.assertTrue(qb.validate())
        self.assertEqual(qb.get_query(), query)

    def test_not_associationproxy_query(self):
        import os
        gladefilepath = os.path.join(paths.lib_dir(), "querybuilder.glade")
        view = GenericEditorView(
            gladefilepath,
            parent=None,
            root_widget_name='main_dialog')
        qb = QueryBuilder(view)
        query = "species where accepted.full_name = 'Melaleuca viminalis'"
        qb.set_query(query)
        self.assertTrue(qb.validate())
        self.assertEqual(qb.get_query(), query)

    def test_adding_wildcard_sets_cond_to_like(self):
        import os
        gladefilepath = os.path.join(paths.lib_dir(), "querybuilder.glade")
        view = GenericEditorView(
            gladefilepath,
            parent=None,
            root_widget_name='main_dialog')
        qb = QueryBuilder(view)
        query = "family where epithet = Myrt"
        qb.set_query(query)
        self.assertTrue(qb.validate())
        qb.expression_rows[0].value_widget.set_text('Myrt%')
        self.assertEqual(qb.expression_rows[0].cond_combo.get_active_text(),
                         'like')

    def test_date_searches_add_on_condition(self):
        import os
        gladefilepath = os.path.join(paths.lib_dir(), "querybuilder.glade")
        view = GenericEditorView(
            gladefilepath,
            parent=None,
            root_widget_name='main_dialog')
        qb = QueryBuilder(view)
        query = "family where _created on 1/1/2021"
        qb.set_query(query)
        self.assertTrue(qb.validate())
        from bauble.utils import tree_model_has
        self.assertTrue(
            tree_model_has(qb.expression_rows[0].cond_combo.get_model(), 'on')
        )
        # it is removed when changed to a none date search
        from bauble.plugins.plants.family import Family
        prop = Family.__mapper__.get_property('id')
        qb.expression_rows[0].on_schema_menu_activated(None, 'id', prop)
        self.assertFalse(
            tree_model_has(qb.expression_rows[0].cond_combo.get_model(), 'on')
        )

    def test_adding_date_field_sets_cond_to_on(self):
        import os
        gladefilepath = os.path.join(paths.lib_dir(), "querybuilder.glade")
        view = GenericEditorView(
            gladefilepath,
            parent=None,
            root_widget_name='main_dialog')
        qb = QueryBuilder(view)
        query = "family where epithet = Myrt"
        qb.set_query(query)
        self.assertTrue(qb.validate())
        from bauble.plugins.plants.family import Family
        prop = Family.__mapper__.get_property('_created')
        qb.expression_rows[0].on_schema_menu_activated(None, '_created', prop)
        self.assertEqual(
            qb.expression_rows[0].cond_combo.get_active_text(), 'on'
        )

    def test_remove_button_removes_row(self):
        import os
        gladefilepath = os.path.join(paths.lib_dir(), "querybuilder.glade")
        view = GenericEditorView(
            gladefilepath,
            parent=None,
            root_widget_name='main_dialog')
        qb = QueryBuilder(view)
        qb.set_query('plant where id=0 or id=1 or id>10')
        self.assertEqual(len(qb.expression_rows), 3)
        qb.expression_rows[2].remove_button.emit('clicked')
        self.assertEqual(len(qb.expression_rows), 2)
        self.assertEqual(qb.get_query(), "plant where id = 0 or id = 1")
        self.assertTrue(qb.validate())


class TestQBP(BaubleTestCase):
    def test_and_clauses(self):
        query = BuiltQuery(
            'plant WHERE accession.species.genus.family.epithet=Fabaceae AND '
            'location.description="Block 10" and quantity > 0 and quantity = 0'
        )
        self.assertEqual(len(query.parsed), 6, f'query parsed: {query.parsed}')
        self.assertEqual(query.parsed[0], 'plant')
        self.assertEqual(query.parsed[1], 'where')
        self.assertEqual(len(query.parsed[2]), 3)
        for i in (3, 4, 5):
            self.assertEqual(query.parsed[i][0], 'and')
            self.assertEqual(len(query.parsed[i]), 4)

    def test_or_clauses(self):
        query = BuiltQuery(
            'plant WHERE accession.species.genus.family.epithet=Fabaceae OR '
            'location.description="Block 10" or quantity > 0 or quantity = 0'
        )
        self.assertEqual(len(query.parsed), 6)
        self.assertEqual(query.parsed[0], 'plant')
        self.assertEqual(query.parsed[1], 'where')
        self.assertEqual(len(query.parsed[2]), 3)
        for i in (3, 4, 5):
            self.assertEqual(query.parsed[i][0], 'or')
            self.assertEqual(len(query.parsed[i]), 4)

    def test_has_clauses(self):
        query = BuiltQuery('genus WHERE epithet=Inga')
        self.assertEqual(len(query.clauses), 1)
        query = BuiltQuery('genus WHERE epithet=Inga or epithet=Iris')
        self.assertEqual(len(query.clauses), 2)

    def test_has_domain(self):
        query = BuiltQuery('plant WHERE accession.species.genus.epithet=Inga')
        self.assertEqual(query.domain, 'plant')

    def test_clauses_have_fields(self):
        query = BuiltQuery(
            'genus WHERE epithet=Inga or family.epithet=Poaceae')
        self.assertEqual(len(query.clauses), 2)
        self.assertEqual(query.clauses[0].connector, None)
        self.assertEqual(query.clauses[1].connector, 'or')
        self.assertIsNone(query.clauses[0].not_)
        self.assertIsNone(query.clauses[1].not_)
        self.assertEqual(query.clauses[0].field, 'epithet')
        self.assertEqual(query.clauses[1].field, 'family.epithet')
        self.assertEqual(query.clauses[0].operator, '=')
        self.assertEqual(query.clauses[1].operator, '=')
        self.assertEqual(query.clauses[0].value, 'Inga')
        self.assertEqual(query.clauses[1].value, 'Poaceae')
        query = BuiltQuery("species WHERE genus.epithet=Inga and "
                           "accessions.code like '2010%'")
        self.assertEqual(len(query.clauses), 2)
        self.assertEqual(query.clauses[0].connector, None)
        self.assertEqual(query.clauses[1].connector, 'and')
        self.assertIsNone(query.clauses[0].not_)
        self.assertIsNone(query.clauses[1].not_)
        self.assertEqual(query.clauses[0].field, 'genus.epithet')
        self.assertEqual(query.clauses[1].field, 'accessions.code')
        self.assertEqual(query.clauses[0].operator, '=')
        self.assertEqual(query.clauses[1].operator, 'like')
        self.assertEqual(query.clauses[0].value, 'Inga')
        self.assertEqual(query.clauses[1].value, '2010%')

    def test_is_none_if_wrong(self):
        query = BuiltQuery("'species WHERE genus.epithet=Inga")
        self.assertEqual(query.is_valid, False)
        query = BuiltQuery("species like %")
        self.assertEqual(query.is_valid, False)
        query = BuiltQuery("Inga")
        self.assertEqual(query.is_valid, False)

    def test_is_case_insensitive(self):
        for s in [("species Where genus.epithet=Inga and accessions.code like"
                   " '2010%'"),
                  ("species WHERE genus.epithet=Inga and accessions.code Like"
                   " '2010%'"),
                  ("species Where genus.epithet=Inga and accessions.code LIKE"
                   " '2010%'"),
                  ("species Where genus.epithet=Inga AND accessions.code like"
                   " '2010%'"),
                  ("species WHERE genus.epithet=Inga AND accessions.code LIKE"
                   " '2010%'"), ]:
            query = BuiltQuery(s)
            self.assertEqual(len(query.clauses), 2)
            self.assertEqual(query.clauses[0].connector, None)
            self.assertEqual(query.clauses[1].connector, 'and')
            self.assertEqual(query.clauses[0].field, 'genus.epithet')
            self.assertEqual(query.clauses[1].field, 'accessions.code')
            self.assertEqual(query.clauses[0].operator, '=')
            self.assertEqual(query.clauses[1].operator, 'like')
            self.assertEqual(query.clauses[0].value, 'Inga')
            self.assertEqual(query.clauses[1].value, '2010%')

    def test_is_only_usable_clauses(self):
        # valid query, but not for the query builder
        query = BuiltQuery("species WHERE genus.epithet=Inga or "
                           "count(accessions.id)>4")
        self.assertEqual(query.is_valid, True)
        self.assertEqual(len(query.clauses), 1)
        query = BuiltQuery("species WHERE a=1 or count(accessions.id)>4 or "
                           "genus.epithet=Inga")
        self.assertEqual(query.is_valid, True)
        self.assertEqual(len(query.clauses), 2)

    @unittest.skip('not implimented')
    def test_be_able_to_skip_first_query_if_invalid(self):
        # valid query, but not for the query builder
        # "we can't do that without rewriting the grammar"
        query = BuiltQuery("species WHERE count(accessions.id)>4 or "
                           "genus.epithet=Inga")
        self.assertEqual(query.is_valid, True)
        self.assertEqual(len(query.clauses), 1)

    def test_none_or_none_str(self):
        query = BuiltQuery("accession where notes.category = None")
        self.assertEqual(query.is_valid, True)
        self.assertEqual(len(query.clauses), 1)
        self.assertEqual(query.clauses[0].value, '<None>')
        query = BuiltQuery("accession where notes.category = 'None'")
        self.assertEqual(query.is_valid, True)
        self.assertEqual(len(query.clauses), 1)
        self.assertEqual(query.clauses[0].value, 'None')

    def test_optional_not(self):
        # with not
        query = BuiltQuery("accession where not code contains 'XXX'")
        self.assertEqual(query.is_valid, True)
        self.assertEqual(len(query.clauses), 1)
        self.assertEqual(query.clauses[0].value, 'XXX')
        self.assertEqual(query.clauses[0].not_, 'not')
        self.assertEqual(query.clauses[0].operator, 'contains')
        # with not and connector
        query = BuiltQuery("accession where not code contains 'XXX' and "
                           "recv_qty > 0")
        self.assertEqual(query.is_valid, True)
        self.assertEqual(len(query.clauses), 2)
        self.assertEqual(query.clauses[0].value, 'XXX')
        self.assertEqual(query.clauses[0].not_, 'not')
        self.assertEqual(query.clauses[0].operator, 'contains')
        self.assertEqual(query.clauses[1].value, '0')
        self.assertIsNone(query.clauses[1].not_)
        self.assertEqual(query.clauses[1].operator, '>')
