# Copyright 2008, 2009, 2010 Brett Adams
# Copyright 2014-2015 Mario Frasca <mario@anche.no>.
# Copyright 2021-2023 Ross Demuth <rossdemuth123@gmail.com>
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
Search functionailty.
"""

import logging
logger = logging.getLogger(__name__)

from gi.repository import Gtk

from sqlalchemy import Integer, Float
from sqlalchemy.orm import class_mapper, RelationshipProperty
from sqlalchemy.orm.properties import ColumnProperty
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.ext.associationproxy import AssociationProxy
from sqlalchemy.orm.attributes import InstrumentedAttribute
from sqlalchemy.exc import InvalidRequestError
from pyparsing import (Word,
                       alphas,
                       alphanums,
                       delimitedList,
                       Group,
                       alphas8bit,
                       quotedString,
                       Regex,
                       oneOf,
                       CaselessLiteral,
                       WordStart,
                       WordEnd,
                       ZeroOrMore,
                       Literal,
                       ParseException,
                       Optional)

import bauble
from bauble import utils
from bauble.editor import GenericEditorPresenter
from bauble.search import NoneToken, EmptyToken, MapperSearch


class SchemaMenu(Gtk.Menu):
    """
    SchemaMenu

    :param mapper:
    :param activate_cb:
    :param column_filter:
    :param relation_filter:
    :param private: if True include private fields (starting with underscore)
    :param selectable_relations: if True include relations as selectable items
    """

    def __init__(self,  # pylint: disable=too-many-arguments
                 mapper,
                 activate_cb=None,
                 column_filter=lambda k, p: True,
                 relation_filter=lambda k, p: True,
                 private=False,
                 selectable_relations=False):
        super().__init__()
        self.mapper = mapper
        self.activate_cb = activate_cb
        self.private = private
        self.relation_filter = relation_filter
        self.column_filter = column_filter
        self.selectable_relations = selectable_relations
        for item in self._get_prop_menuitems(mapper):
            self.append(item)
        self.show_all()

    def on_activate(self, menuitem, prop):
        """Called when menu items that hold column properties are activated."""
        path = [menuitem.get_child().props.label]
        menu = menuitem.get_parent()
        while menu is not None:
            menuitem = menu.props.attach_widget
            if not menuitem:
                break
            label = menuitem.get_child().props.label
            path.append(label)
            menu = menuitem.get_parent()
        full_path = '.'.join(reversed(path))
        if self.selectable_relations and hasattr(prop, '__table__'):
            full_path = full_path.removesuffix(f'.{prop.__table__.key}')
        self.activate_cb(menuitem, full_path, prop)

    def on_select(self, menuitem, prop):
        """Called when menu items that have submenus are selected."""
        submenu = menuitem.get_submenu()
        if len(submenu.get_children()) == 0:
            if isinstance(prop, AssociationProxy):
                mapper = getattr(
                    prop.for_class(self.mapper.class_).target_class,
                    prop.value_attr
                ).mapper
            else:
                mapper = prop.mapper
            for item in self._get_prop_menuitems(mapper):
                submenu.append(item)
        submenu.show_all()

    def _get_prop_menuitems(self, mapper):
        # Separate properties in column_properties and relation_properties

        column_properties = {}
        relation_properties = {}
        for key, prop in mapper.all_orm_descriptors.items():
            if isinstance(prop, hybrid_property):
                column_properties[key] = prop
            elif (isinstance(prop, InstrumentedAttribute) or
                  prop.key in [i.key for i in mapper.synonyms]):
                i = prop.property
                if isinstance(i, RelationshipProperty):
                    relation_properties[key] = prop
                elif isinstance(i, ColumnProperty):
                    column_properties[key] = prop
            elif isinstance(prop, AssociationProxy):
                relation_properties[key] = prop

        column_properties = dict(sorted(
            column_properties.items(),
            key=lambda p: (p[0] != 'id', p[0])
        ))
        relation_properties = dict(sorted(relation_properties.items(),
                                          key=lambda p: p[0]))

        items = []

        # add the table name to the top of the submenu and allow it to be
        # selected (intended for export selection where you wish to include the
        # string representation of the table)
        if self.selectable_relations:
            item = Gtk.MenuItem(label=mapper.entity.__table__.key,
                                use_underline=False)
            item.connect('activate', self.on_activate, mapper.entity)
            items.append(item)
            items.append(Gtk.SeparatorMenuItem())

        for key, prop in column_properties.items():
            if not self.column_filter(key, prop):
                continue
            item = Gtk.MenuItem(label=key, use_underline=False)
            if hasattr(prop, 'prop'):
                prop = prop.prop
            item.connect('activate', self.on_activate, prop)
            items.append(item)

        for key, prop in relation_properties.items():
            if not self.relation_filter(key, prop):
                continue
            item = Gtk.MenuItem(label=key, use_underline=False)
            submenu = Gtk.Menu()
            item.set_submenu(submenu)
            item.connect('select', self.on_select, prop)
            items.append(item)

        return items


def parse_typed_value(value, proptype):
    """parse the input string and return the corresponding typed value

    handles boolean, integers, floats, datetime, None, Empty, and falls back to
    string.
    """
    if value in ['None', None]:
        value = NoneToken()
    elif value in ["'None'", '"None"']:
        # in case user really does want to use "None" as a string.
        value = repr(str(value[1:-1]))
    elif value == 'Empty':
        value = EmptyToken()
    elif isinstance(proptype, (bauble.btypes.DateTime, bauble.btypes.Date)):
        # allow string dates e.g. 12th of April '22
        if ' ' in value:
            value = repr(value)
    elif isinstance(proptype, bauble.btypes.Boolean):
        # btypes.Boolean accepts strings and 0, 1
        if value not in ['True', 'False', 1, 0]:
            value = f'|bool|{value}|'
    elif isinstance(proptype, Integer):
        value = ''.join([i for i in value if i in '-0123456789.'])
        if value:
            value = str(int(value))
    elif isinstance(proptype, Float):
        value = ''.join([i for i in value if i in '-0123456789.'])
        if value:
            value = str(float(value))
    elif value not in ['%', '_']:
        value = repr(str(value).strip())
    return value


class ExpressionRow:

    CONDITIONS = [
        '=',
        '!=',
        '<',
        '<=',
        '>',
        '>=',
        'is',
        'not',
        'like',
        'contains',
    ]

    def __init__(self, query_builder, remove_callback, row_number):
        self.proptype = None
        self.grid = query_builder.view.widgets.expressions_table
        self.presenter = query_builder
        self.menu_item_activated = False

        self.and_or_combo = None
        if row_number != 1:
            self.and_or_combo = Gtk.ComboBoxText()
            self.and_or_combo.append_text("and")
            self.and_or_combo.append_text("or")
            self.and_or_combo.set_active(0)
            self.grid.attach(self.and_or_combo, 0, row_number, 1, 1)
            self.and_or_combo.connect('changed',
                                      lambda w: self.presenter.validate())

        self.not_combo = Gtk.ComboBoxText()
        self.not_combo.append_text("")
        self.not_combo.append_text("not")
        self.not_combo.set_active(0)
        self.grid.attach(self.not_combo, 1, row_number, 1, 1)
        self.not_combo.connect('changed', lambda w: self.presenter.validate())
        self.not_combo.set_tooltip_text(
            'Set to "not" to search for the inverse'
        )

        self.prop_button = Gtk.Button(label=_('Choose a property…'))

        self.schema_menu = SchemaMenu(self.presenter.mapper,
                                      self.on_schema_menu_activated,
                                      self.column_filter,
                                      self.relation_filter)
        self.prop_button.connect('button-press-event',
                                 self.on_prop_button_clicked,
                                 self.schema_menu)
        self.prop_button.set_tooltip_text('The property to query')
        self.grid.attach(self.prop_button, 2, row_number, 1, 1)

        # start with a default combobox and entry but value_widget and
        # cond_combo can change depending on the type of the property chosen in
        # the schema menu, see self.on_schema_menu_activated
        self.cond_combo = Gtk.ComboBoxText()
        for condition in self.CONDITIONS:
            self.cond_combo.append_text(condition)
        self.cond_combo.set_active(0)
        self.grid.attach(self.cond_combo, 3, row_number, 1, 1)
        self.cond_handler = self.cond_combo.connect(
            'changed', lambda w: self.presenter.validate()
        )
        self.cond_combo.set_tooltip_text('How to search')

        self.value_widget = Gtk.Entry()
        self.value_widget.connect('changed', self.on_value_changed)
        self.value_widget.set_tooltip_text('The value to search for')
        self.grid.attach(self.value_widget, 4, row_number, 1, 1)

        if row_number != 1:
            self.remove_button = Gtk.Button.new_from_icon_name(
                'list-remove-symbolic', Gtk.IconSize.BUTTON
            )

            def on_remove_btn_clicked(_button):
                remove_callback(self)
                self.presenter.validate()

            self.remove_button.connect('clicked', on_remove_btn_clicked)
            self.grid.attach(self.remove_button, 5, row_number, 1, 1)
        query_builder.view.get_window().resize(1, 1)

    @staticmethod
    def on_prop_button_clicked(_button, event, menu):
        menu.popup_at_pointer(event)

    @staticmethod
    def is_accepted_text(text):
        return text in ('None'[:len(text)], 'Empty'[:len(text)])

    def on_value_changed(self, widget):
        """Call the QueryBuilder.validate() for this row.

        Sets the sensitivity of the Gtk.ResponseType.OK button on the
        QueryBuilder.
        """
        # change to a standard entry if the user tries to enter none numbers
        if isinstance(widget, Gtk.SpinButton):
            text = widget.get_text()
            if text and self.is_accepted_text(text):
                focus = widget.has_focus()
                top = self.grid.child_get_property(self.value_widget,
                                                   'top-attach')
                left = self.grid.child_get_property(self.value_widget,
                                                    'left-attach')
                self.grid.remove(self.value_widget)
                self.value_widget = Gtk.Entry()
                self.value_widget.connect('changed',
                                          self.on_number_value_changed)
                self.value_widget.set_tooltip_text(
                    'Number or "None" for no value has been set'
                )
                self.grid.attach(self.value_widget, left, top, 1, 1)
                self.grid.show_all()
                if focus:
                    self.value_widget.grab_focus()
                self.value_widget.set_text(text)
                self.value_widget.set_position(1)
            self.value_widget.set_activates_default(True)
        elif isinstance(widget, Gtk.Entry):
            if any(i in widget.get_text() for i in ['%', '_']):
                self.cond_combo.set_active(self.CONDITIONS.index('like'))
            elif self.cond_combo.get_active_text() == 'like':
                self.cond_combo.set_active(0)
            self.value_widget.set_activates_default(True)

        self.presenter.validate()

    def on_number_value_changed(self, widget):
        """Loosely constrain text to None or numbers parts only"""
        val = widget.get_text()
        if not self.is_accepted_text(val):
            val = ''.join([i for i in val if i in '-.0123456789'])
            widget.set_text(val)
        self.on_value_changed(widget)

    def on_schema_menu_activated(self, _menuitem, path, prop):
        """Called when an item in the schema menu is activated"""
        self.prop_button.set_label(path)
        self.menu_item_activated = True
        top = self.grid.child_get_property(self.value_widget, 'top-attach')
        left = self.grid.child_get_property(self.value_widget, 'left-attach')
        self.grid.remove(self.value_widget)

        # change the widget depending on the type of the selected property
        logger.debug('prop = %s', prop)
        try:
            self.proptype = prop.columns[0].type
        except AttributeError:
            self.proptype = None
        # reset the cond_combo incase it was last a date/datetime
        if not isinstance(self.proptype, (bauble.btypes.Date,
                                          bauble.btypes.DateTime)):
            self.cond_combo.handler_block(self.cond_handler)
            self.cond_combo.remove_all()
            for condition in self.CONDITIONS:
                self.cond_combo.append_text(condition)
            self.cond_combo.set_active(0)
            self.cond_combo.handler_unblock(self.cond_handler)
            self.cond_combo.set_tooltip_text('How to search')

        val = utils.get_widget_value(self.value_widget)
        set_value_widget = self.get_set_value_widget()
        set_value_widget(prop, val)

        self.grid.attach(self.value_widget, left, top, 1, 1)
        self.grid.show_all()
        self.presenter.validate()

    def get_set_value_widget(self):
        logger.debug('proptype = %s', type(self.proptype))
        if isinstance(self.proptype, bauble.btypes.Enum):
            return self.set_enum_widget
        if isinstance(self.proptype, Integer):
            return self.set_int_widget
        if isinstance(self.proptype, Float):
            return self.set_float_widget
        if isinstance(self.proptype, bauble.btypes.Boolean):
            return self.set_bool_widget
        if isinstance(self.proptype, (bauble.btypes.Date,
                                      bauble.btypes.DateTime)):
            return self.set_date_widget
        return self.set_entry_widget

    def set_enum_widget(self, prop, val):
        self.value_widget = Gtk.ComboBox()
        cell = Gtk.CellRendererText()
        self.value_widget.pack_start(cell, True)
        self.value_widget.add_attribute(cell, 'text', 1)
        model = Gtk.ListStore(str, str)
        if prop.columns[0].type.translations:
            trans = prop.columns[0].type.translations
            sorted_keys = [
                i for i in trans.keys() if i is None
            ] + sorted(i for i in trans.keys() if i is not None)
            prop_values = [(k, trans[k] or 'None') for k in sorted_keys]
        else:
            values = prop.columns[0].type.values
            prop_values = [(v, v or 'None') for v in sorted(values)]
        for value, translation in prop_values:
            model.append([value, translation])
        self.value_widget.set_model(model)
        self.value_widget.set_tooltip_text(
            'select a value, "None" means no value has been set'
        )
        self.value_widget.connect('changed', self.on_value_changed)
        utils.set_widget_value(self.value_widget, val)

    def set_int_widget(self, _prop, val):
        adjustment = Gtk.Adjustment(upper=1000000000000,
                                    step_increment=1,
                                    page_increment=10)
        self.value_widget = Gtk.SpinButton(adjustment=adjustment,
                                           numeric=False)
        self.value_widget.set_tooltip_text(
            'Number (non decimal) or "None" for no value has been set'
        )
        try:
            val = int(val)
            self.value_widget.set_value(float(val))
        except ValueError:
            pass
        self.value_widget.connect('changed', self.on_value_changed)

    def set_float_widget(self, _prop, val):
        adjustment = Gtk.Adjustment(upper=10000000,
                                    lower=0.00000000001,
                                    step_increment=0.1,
                                    page_increment=1)
        self.value_widget = Gtk.SpinButton(adjustment=adjustment,
                                           digits=10,
                                           numeric=False)
        self.value_widget.set_tooltip_text(
            'Number, decimal number or "None" for no value has been set'
        )
        try:
            val = float(val)
            self.value_widget.set_value(val)
        except ValueError:
            pass
        self.value_widget.connect('changed', self.on_value_changed)

    def set_bool_widget(self, _prop, val):
        values = ['False', 'True']
        self.value_widget = Gtk.ComboBoxText()
        for value in values:
            self.value_widget.append_text(value)
        self.value_widget.set_tooltip_text('Select a value')
        self.value_widget.connect('changed', self.on_value_changed)
        utils.set_widget_value(self.value_widget,
                               val if val in values else 'False')

    def set_date_widget(self, prop, val):
        self.value_widget = Gtk.Entry()
        self.value_widget.set_tooltip_text(
            'Date (e.g. 1/1/2021), 0 for today, a negative number for '
            'number of days before today or "None" for no date has been '
            'set.  Also accepts text dates (e.g. "15 Feb \'22") and "today" '
            'or "yesterday"'
        )
        self.value_widget.connect('changed', self.on_value_changed)
        self.value_widget.set_text(val)
        conditions = self.CONDITIONS.copy()
        prev = self.cond_combo.get_active_text()
        conditions.append('on')
        self.cond_combo.handler_block(self.cond_handler)
        self.cond_combo.remove_all()
        for condition in conditions:
            self.cond_combo.append_text(condition)
        # set 'on' as default
        if isinstance(prop.columns[0].type, bauble.btypes.DateTime):
            logger.debug("setting condition to 'on'")
            self.cond_combo.set_active(len(conditions) - 1)
        else:
            self.cond_combo.set_active(conditions.index(prev))
        self.cond_combo.handler_unblock(self.cond_handler)
        self.cond_combo.set_tooltip_text('How to search')

    def set_entry_widget(self, _prop, val):
        self.value_widget = Gtk.Entry()
        self.value_widget.set_tooltip_text(
            'The text value to search for or "None" for no value has been '
            'set'
        )
        self.value_widget.connect('changed', self.on_value_changed)
        if val is not None:
            self.value_widget.set_text(str(val))

    # TODO what to do with synonyms?  Could leave out sp, genus, family and
    # use epithet only?
    @staticmethod
    def column_filter(key, _prop):
        # skip any id fields (e.g. genus_id) as they are available via the
        # related id property (e.g. species.genus_id == species.genus.id)
        # Except obj_id from tags
        if key.endswith('_id') and not key == 'obj_id':
            return False
        return True

    @staticmethod
    def relation_filter(key, _prop):
        if key.startswith('_'):
            return False
        return True

    def get_widgets(self):
        """Returns a tuple of the and_or_combo, prop_button, cond_combo,
        value_widget, and remove_button widgets.
        """
        return (
            i for i in (self.and_or_combo, self.not_combo, self.prop_button,
                        self.cond_combo, self.value_widget,
                        self.remove_button) if i)

    def get_expression(self):
        """Return the expression represented by this ExpressionRow.

        If the expression is not valid then return None.
        """

        if not self.menu_item_activated:
            return None

        value = ''
        if isinstance(self.value_widget, Gtk.ComboBoxText):
            value = self.value_widget.get_active_text()
        elif isinstance(self.value_widget, Gtk.ComboBox):
            model = self.value_widget.get_model()
            active_iter = self.value_widget.get_active_iter()
            if active_iter:
                value = model[active_iter][0]
        else:
            # assume it's a Gtk.Entry or other widget with a text property
            value = self.value_widget.get_text().strip()
        value = parse_typed_value(value, self.proptype)
        and_or = ''
        if self.and_or_combo:
            and_or = self.and_or_combo.get_active_text()
        not_ = self.not_combo.get_active_text()
        field_name = self.prop_button.get_label()
        if value == EmptyToken():
            field_name = field_name.rsplit('.', 1)[0]
            value = repr(value)
        if isinstance(value, NoneToken):
            value = 'None'
        result = ' '.join([i for i in (and_or, not_, field_name,
                                       self.cond_combo.get_active_text(),
                                       value) if i]).strip()
        return result


class BuiltQuery:
    """Parse a query string for its domain and clauses to preloading the
    QueryBuilder.
    """

    wordStart, wordEnd = WordStart(), WordEnd()

    NOT = wordStart + CaselessLiteral('not') + wordEnd
    AND_ = wordStart + CaselessLiteral('and') + wordEnd
    OR_ = wordStart + CaselessLiteral('or') + wordEnd
    BETWEEN_ = wordStart + CaselessLiteral('between') + wordEnd

    numeric_value = Regex(r'[-]?\d+(\.\d*)?([eE]\d+)?')
    date_str = Regex(
        r'\d{1,4}[/.-]{1}\d{1,2}[/.-]{1}\d{1,4}'
    )
    date_type = Regex(r'(\d{4}),[ ]?(\d{1,2}),[ ]?(\d{1,2})')
    true_false = (Literal('True') | Literal('False'))
    unquoted_string = Word(alphanums + alphas8bit + '%.-_*;:')
    string_value = (quotedString | unquoted_string)
    value_part = (date_type | numeric_value | true_false)
    typed_value = (Literal("|") + Word(alphas) + Literal("|") +
                   value_part + Literal("|")).setParseAction(
                       lambda s, l, t: t[3])
    none_token = Literal('None').setParseAction(lambda s, l, t: '<None>')
    fieldname = Group(delimitedList(Word(alphas + '_', alphanums + '_'), '.'))
    value = (none_token | date_str | numeric_value | string_value |
             typed_value)
    conditions = ' '.join(ExpressionRow.CONDITIONS) + ' on'
    binop = oneOf(conditions, caseless=True)
    clause = Optional(NOT) + fieldname + binop + value
    unparseable_clause = (fieldname + BETWEEN_ + value + AND_ + value) | (
        Word(alphanums) + '(' + fieldname + ')' + binop + value)
    expression = Group(clause) + ZeroOrMore(Group(
        AND_ + clause | OR_ + clause | ((OR_ | AND_) + unparseable_clause)
        .suppress()))
    query = Word(alphas, alphas + '_') + CaselessLiteral("where") + expression

    def __init__(self, search_string):
        self.parsed = None
        self.__clauses = None
        try:
            self.parsed = self.query.parseString(search_string)
            self.is_valid = True
        except ParseException as e:
            logger.debug('%s(%s)', type(e).__name__, e)
            self.is_valid = False

    @property
    def clauses(self):
        if not self.__clauses:
            from dataclasses import dataclass

            @dataclass
            class Clause:
                not_: str = None
                connector: str = None
                field: str = None
                operator: str = None
                value: str = None

            self.__clauses = []
            for part in [k for k in self.parsed if len(k) > 0][2:]:
                clause = Clause()
                if len(part) > 3:
                    for i, j in enumerate(part[:2]):
                        if (i == 0 and isinstance(j, str) and
                                j.lower() in ['and', 'or']):
                            clause.connector = j
                        elif isinstance(j, str) and j.lower() == 'not':
                            clause.not_ = j
                clause.field = '.'.join(part[-3])
                clause.operator = part[-2]
                clause.value = part[-1]
                self.__clauses.append(clause)

        return self.__clauses

    @property
    def domain(self):
        return self.parsed[0]


class QueryBuilder(GenericEditorPresenter):

    view_accept_buttons = ['cancel_button', 'confirm_button']
    default_size = []

    def __init__(self, view=None):
        super().__init__(self, view=view, refresh_view=False, session=False)

        self.expression_rows = []
        self.mapper = None
        self.domain = None
        self.table_row_count = 0
        self.domain_map = MapperSearch.get_domain_classes().copy()

        self.view.widgets.domain_combo.set_active(-1)
        self.view.widgets.domain_combo.set_tooltip_text(
            'The type of items returned'
        )

        table = self.view.widgets.expressions_table
        for child in table.get_children():
            table.remove(child)

        self.view.widgets.domain_liststore.clear()
        for key in sorted(self.domain_map.keys()):
            self.view.widgets.domain_liststore.append([key])
        self.view.widgets.add_clause_button.set_sensitive(False)
        self.view.widgets.confirm_button.set_sensitive(False)
        self.refresh_view()
        utils.make_label_clickable(self.view.widgets.help_label,
                                   self.on_help_clicked)

    def on_help_clicked(self, _label, _event):
        msg = _("<b>Search Domain</b> - the type of items you want "
                "returned.\n\n"
                "<b>Clauses</b> - consists of an <b>optional 'not'</b> "
                "(searches for the inverse), a <b>property</b>, a "
                "<b>condition</b> and a <b>value</b>.\n"
                "Can be chained together with <b>and</b> or <b>or</b>.\n\n"
                "<b>property</b> - the field or related field to query\n"
                "<b>condition</b> - how to query. Note that the choice of "
                "condition may depend on the value you provide. e.g. "
                "wildcards require the <tt>like</tt> condition.  Only string "
                "dates can use the <tt>on</tt> condition. (<tt>!=</tt> is NOT "
                "equal)\n"
                "<b>value</b> - the value to query, may contain special "
                "tokens.\n"
                "\nSpecial Tokens with some example usage:\n\n"
                "<b>%</b> - wildcard for any value, use with <b>like</b> "
                "condition\n"
                "        <tt>genus where epithet like Mel%</tt>\n"
                "Return the genera Melaleuca, Melastoma, etc..\n\n"
                "<b>_</b> - wildcard for a single character, use with "
                "<b>like</b> condition\n"
                "        <tt>plant where code like _</tt>\n"
                "Return plants where the code is a single character.  Most "
                "commonly 1-9.\n\n"
                "<b>None</b> - has no value\n"
                "        <tt>location where description != None</tt>\n"
                "Note <b>!=</b> meaning does NOT equal None. Return locations "
                "where there is a description.\n\n"
                "<b>dates (e.g. 10-1-1997)</b> - text date entries are "
                "flexible and can be either iternational format (i.e. "
                "year-month-day) or in the format as specified in your "
                "preferences <tt>default_date_format</tt> setting (e.g. "
                "day-month-year or month-day-year).  (date separaters can be "
                "any of <tt>/ - .</tt>) <b>on</b> is a special condition for "
                "dates only\n"
                "        <tt>plant where planted.date on 11/05/2021</tt>\n"
                "Return plants that where planted on the 11/05/2021.\n\n"
                "<b>days from today (e.g. -10)</b> - best used with the "
                "<b>&gt;</b> or <b>&lt;</b> condition (note: these will "
                "become typed in the search entry - e.g. |datetime|-10|)\n"
                "        <tt>plant where planted.date > -10</tt>\n"
                "Return plants that where planted in the last 10 days.\n"
                )
        dialog = utils.create_message_dialog(msg,
                                             parent=self.view.get_window(),
                                             resizable=False)
        dialog.set_title(_('Basic Intro to Queries'))
        dialog.run()
        dialog.destroy()

    def on_domain_combo_changed(self, _combo):
        """Change the search domain.

        Resets the expression table, clear the query label and deletes all the
        expression rows.
        """
        try:
            index = self.view.widgets.domain_combo.get_active()
        except AttributeError:
            return
        if index == -1:
            return

        self.domain = self.view.widgets.domain_liststore[index][0]

        self.view.widgets.query_lbl.set_text('')
        # remove all clauses, they became useless in new domain
        table = self.view.widgets.expressions_table
        for child in table.get_children():
            table.remove(child)
        del self.expression_rows[:]
        # initialize view at 1 clause, however invalid
        self.table_row_count = 0
        self.on_add_clause()
        self.view.get_window().resize(1, 1)
        self.view.widgets.expressions_table.show_all()
        # let user add more clauses
        self.view.widgets.add_clause_button.set_sensitive(True)

    def validate(self):
        """Validate the search expression is a valid expression."""
        valid = False
        query_string = f'{self.domain} where'
        for row in self.expression_rows:
            value = None
            if isinstance(row.value_widget, Gtk.Entry):  # also spinbutton
                value = row.value_widget.get_text()
            elif isinstance(row.value_widget, Gtk.ComboBox):
                value = row.value_widget.get_active() >= 0

            query_string = f'{query_string} {row.get_expression()}'
            self.view.widgets.query_lbl.set_text(query_string)

            if value and row.menu_item_activated:
                valid = True
            else:
                valid = False
                break

        self.view.widgets.confirm_button.set_sensitive(valid)
        return valid

    def remove_expression_row(self, row):
        """Remove a row from the expressions table."""
        for widget in row.get_widgets():
            widget.destroy()
        self.table_row_count -= 1
        self.expression_rows.remove(row)
        self.view.get_window().resize(1, 1)

    def on_add_clause(self, _widget=None):
        """Add a row to the expressions table."""
        domain = self.domain_map[self.domain]
        self.mapper = class_mapper(domain)
        self.table_row_count += 1
        row = ExpressionRow(self, self.remove_expression_row,
                            self.table_row_count)
        self.expression_rows.append(row)
        self.view.widgets.expressions_table.show_all()

    def cleanup(self):
        for row in self.expression_rows:
            row.schema_menu.destroy()
        super().cleanup()

    def start(self):
        if not self.default_size:
            self.__class__.default_size = (self.view.widgets.main_dialog
                                           .get_size())
        else:
            self.view.widgets.main_dialog.resize(*self.default_size)
        return self.view.start()

    @property
    def valid_clauses(self):
        return [i.get_expression() for i in self.expression_rows if
                i.get_expression()]

    def get_query(self):
        """Return query expression string."""

        query = [self.domain, 'where'] + self.valid_clauses
        return ' '.join(query)

    def set_query(self, query):
        parsed = BuiltQuery(query)
        if not parsed.is_valid:
            logger.debug('cannot restore query, invalid')
            return

        # locate domain in list of valid domains
        try:
            index = sorted(self.domain_map.keys()).index(parsed.domain)
        except ValueError as e:
            logger.debug('cannot restore query, %s(%s)', type(e).__name__, e)
            return
        # and set the domain_combo correspondently
        self.view.widgets.domain_combo.set_active(index)

        # now scan all clauses, one ExpressionRow per clause
        for clause in parsed.clauses:
            if clause.value == 'None':
                clause.value = "'None'"
            elif clause.value == '<None>':
                clause.value = 'None'
            if clause.connector:
                self.on_add_clause()
            row = self.expression_rows[-1]
            if clause.connector:
                row.and_or_combo.set_active(
                    {'and': 0, 'or': 1}[clause.connector])
            if clause.not_:
                row.not_combo.set_active(1)

            # the part about the value is a bit more complex: where the
            # clause.field leads to an enumerated property, on_add_clause
            # associates a gkt.ComboBox to it, otherwise a Gtk.Entry.
            # To set the value of a gkt.ComboBox we match one of its
            # items. To set the value of a gkt.Entry we need set_text.
            steps = clause.field.split('.')
            cls = self.domain_map[parsed.domain]
            mapper = class_mapper(cls)
            try:
                for target in steps[:-1]:
                    if hasattr(proxy := getattr(mapper.class_, target),
                               'target_collection'):
                        # AssociationProxy
                        mapper = (mapper.get_property(proxy.target_collection)
                                  .mapper)
                        mapper = mapper.get_property(proxy.value_attr).mapper
                    else:
                        mapper = mapper.get_property(target).mapper
                try:
                    prop = mapper.get_property(steps[-1])
                except InvalidRequestError:
                    prop = mapper.all_orm_descriptors[steps[-1]]
            except Exception as e:  # pylint: disable=broad-except
                logger.debug('cannot restore query details, %s(%s)',
                             type(e).__name__, e)
                return
            conditions = row.CONDITIONS.copy()
            if hasattr(prop, 'columns') and isinstance(
                prop.columns[0].type,
                    (bauble.btypes.Date, bauble.btypes.DateTime)
            ):
                row.cond_combo.append_text('on')
                conditions.append('on')
            row.on_schema_menu_activated(None, clause.field, prop)
            if isinstance(row.value_widget, Gtk.Entry):  # also spinbutton
                row.value_widget.set_text(clause.value)
            elif isinstance(row.value_widget, Gtk.ComboBox):
                for item in row.value_widget.props.model:
                    val = clause.value if clause.value != 'None' else None
                    if item[0] == val:
                        row.value_widget.set_active_iter(item.iter)
                        break
            # check for misplaced 'on'
            if clause.operator in conditions:
                row.cond_combo.set_active(conditions.index(clause.operator))
