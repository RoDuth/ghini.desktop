# Copyright 2008, 2009, 2010 Brett Adams
# Copyright 2014-2015 Mario Frasca <mario@anche.no>.
# Copyright 2021-2024 Ross Demuth <rossdemuth123@gmail.com>
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
Query builder provides a user interface to generate or edit a query string.

It only supports a subset of the full query syntax.
"""

import logging
from collections.abc import Callable
from collections.abc import Generator
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any
from typing import Self
from typing import cast

logger = logging.getLogger(__name__)

from gi.repository import Gdk
from gi.repository import Gtk
from pyparsing import CaselessLiteral
from pyparsing import Forward
from pyparsing import Group
from pyparsing import Opt
from pyparsing import ParseException
from pyparsing import ZeroOrMore
from pyparsing import one_of
from sqlalchemy import Float
from sqlalchemy import Integer
from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.ext.associationproxy import AssociationProxy
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import InspectionAttr
from sqlalchemy.orm import Mapper
from sqlalchemy.orm import RelationshipProperty
from sqlalchemy.orm import class_mapper
from sqlalchemy.orm.attributes import InstrumentedAttribute
from sqlalchemy.orm.properties import ColumnProperty

import bauble
from bauble import prefs
from bauble import utils
from bauble.db import Base
from bauble.i18n import _

from .parser import and_
from .parser import domain
from .parser import not_
from .parser import or_
from .parser import unfiltered_identifier
from .parser import value_token
from .strategies import MapperSearch
from .tokens import EmptyToken
from .tokens import NoneToken

type Filter = Callable[[str, InspectionAttr], bool]


class SchemaMenu(Gtk.Menu):
    """SchemaMenu, allows drilling down into database columns and relations.

    :param mapper: mapper for the root model
    :param activate_callback: function to call when menu item is activted
    :param column_filter: function that returns False if a column is not to be
        included in the menus
    :param relation_filter: function that returns False if the relation is not
        to be included in the menu
    :param private: if True include private fields (starting with underscore)
    :param selectable_relations: if True include relations as selectable items
    :param recurse: if True allow recusing (i.e. species.accessions.species)
    """

    def __init__(  # pylint: disable=too-many-arguments
        self,
        mapper: Mapper,
        activate_callback: Callable[[Gtk.MenuItem, str, ColumnProperty], None],
        column_filter: Filter = lambda k, p: True,
        relation_filter: Filter = lambda k, p: True,
        private: bool = False,
        recurse: bool = False,
        selectable_relations: bool = False,
    ) -> None:
        super().__init__()
        self.mapper = mapper
        self.activate_callback = activate_callback
        self.private = private
        self.relation_filter = relation_filter
        self.column_filter = column_filter
        self.selectable_relations = selectable_relations
        self.recurse = recurse
        for item in self._get_prop_menuitems(mapper):
            self.append(item)
        self.show_all()

    def on_activate(
        self, menuitem: Gtk.MenuItem, prop: ColumnProperty
    ) -> None:
        """Called when menu items that hold column properties are activated."""
        path = [menuitem.get_label()]
        menu = cast(Gtk.Menu, menuitem.get_parent())
        while menu is not None:
            menuitem = cast(Gtk.MenuItem, menu.get_attach_widget())
            if not menuitem:
                break
            label = menuitem.get_label()
            path.append(label)
            menu = cast(Gtk.Menu, menuitem.get_parent())
        full_path = ".".join(reversed(path))
        if self.selectable_relations and hasattr(prop, "__table__"):
            full_path = full_path.removesuffix(f".{prop.__table__.key}")
        self.activate_callback(menuitem, full_path, prop)

    def on_select(self, menuitem: Gtk.MenuItem, prop: ColumnProperty) -> None:
        """Called when menu items that have submenus are selected."""
        try:
            current_cls = prop.parent.class_
        except AttributeError:
            # pylint: disable=protected-access
            current_cls = prop._class

        submenu = cast(Gtk.Menu, menuitem.get_submenu())
        if len(submenu.get_children()) == 0:
            if isinstance(prop, AssociationProxy):
                # pylint: disable=protected-access
                mapper = getattr(
                    prop.for_class(prop._class).target_class, prop.value_attr
                ).mapper
            else:
                mapper = prop.mapper
            for item in self._get_prop_menuitems(mapper, current_cls):
                submenu.append(item)
        submenu.show_all()

    @staticmethod
    def _get_column_and_relation_properties(mapper: Mapper) -> tuple[
        dict[str, InspectionAttr],
        dict[str, InspectionAttr],
    ]:
        # Separate properties into column_properties and relation_properties

        column_properties: dict[str, InspectionAttr] = {}
        relation_properties: dict[str, InspectionAttr] = {}
        key: str
        for key, prop in mapper.all_orm_descriptors.items():
            if isinstance(prop, hybrid_property):
                column_properties[key] = prop
            elif isinstance(prop, InstrumentedAttribute) or prop.key in [
                i.key for i in mapper.synonyms
            ]:
                i = prop.property
                if isinstance(i, RelationshipProperty):
                    relation_properties[key] = prop
                elif isinstance(i, ColumnProperty):
                    column_properties[key] = prop
            elif isinstance(prop, AssociationProxy):
                # patch in the class so we have it later
                # pylint: disable=protected-access
                prop._class = mapper.class_  # type: ignore[attr-defined]
                relation_properties[key] = prop

        column_properties = dict(
            sorted(
                column_properties.items(), key=lambda p: (p[0] != "id", p[0])
            )
        )
        relation_properties = dict(
            sorted(relation_properties.items(), key=lambda p: p[0])
        )

        return column_properties, relation_properties

    def _get_prop_menuitems(
        self, mapper: Mapper, current_cls: Base | None = None
    ) -> list[Gtk.MenuItem]:
        all_props = self._get_column_and_relation_properties(mapper)
        column_properties, relation_properties = all_props

        items: list[Gtk.MenuItem] = []
        # add the table name to the top of the submenu and allow it to be
        # selected (intended for export selection where you wish to include the
        # string representation of the table)
        if self.selectable_relations:
            item = Gtk.MenuItem(
                label=mapper.entity.__table__.key, use_underline=False
            )
            item.connect("activate", self.on_activate, mapper.entity)
            items.append(item)
            items.append(Gtk.SeparatorMenuItem())

        for key, prop in column_properties.items():
            if not self.column_filter(key, prop):
                continue
            item = Gtk.MenuItem(label=key, use_underline=False)
            if hasattr(prop, "prop"):
                prop = prop.prop
            item.connect("activate", self.on_activate, prop)
            items.append(item)

        for key, prop in relation_properties.items():
            if not self.relation_filter(key, prop):
                continue

            if self.recurse is False:
                if isinstance(prop, AssociationProxy):
                    # pylint: disable=protected-access,line-too-long
                    target_prop = getattr(
                        prop.for_class(prop._class).target_class,  # type: ignore[attr-defined]  # noqa
                        prop.value_attr,
                    ).prop
                else:
                    target_prop = cast(RelationshipProperty, prop).prop
                if target_prop.mapper.class_ is current_cls:
                    continue

            item = Gtk.MenuItem(label=key, use_underline=False)
            submenu = Gtk.Menu()
            item.set_submenu(submenu)
            item.connect("select", self.on_select, prop)
            items.append(item)

        return items


def parse_typed_value(value: Any, proptype: type | None) -> Any:
    """parse the input string and return the corresponding typed value

    handles boolean, integers, floats, datetime, None, Empty, and falls back to
    string.
    """
    if value in ["None", None]:
        value = NoneToken()
    elif value in ["'None'", '"None"']:
        # in case user really does want to use "None" as a string.
        value = repr(str(value[1:-1]))
    elif value == "Empty":
        value = EmptyToken()
    elif proptype in (bauble.btypes.DateTime, bauble.btypes.Date):
        # allow string dates e.g. 12th of April '22
        if " " in value:
            value = repr(value)
    elif proptype is bauble.btypes.Boolean:
        # btypes.Boolean accepts strings and 0, 1
        if value not in ["True", "False", 1, 0]:
            value = 0
    elif proptype is Integer:
        value = "".join([i for i in value if i in "-0123456789."])
        if value:
            value = str(int(value))
    elif proptype is Float:
        value = "".join([i for i in value if i in "-0123456789."])
        if value:
            value = str(float(value))
    elif value not in ["%", "_"]:
        # wrap in appropriate quotes but correct any escapes
        value = (
            repr(str(value))
            .encode("raw_unicode_escape")
            .decode("unicode_escape")
        )
    return value


class ExpressionRow:  # pylint: disable=too-many-instance-attributes
    CONDITIONS = [
        "=",
        "!=",
        "<",
        "<=",
        ">",
        ">=",
        "is",
        "not",
        "like",
        "contains",
    ]
    custom_columns: dict[str, tuple] = {}

    def __init__(
        self,
        query_builder: "QueryBuilder",
        remove_callback: Callable[[Self], None],
        row_number: int,
    ) -> None:
        self.proptype: type | None = None
        self.grid: Gtk.Grid = query_builder.expressions_table
        self.presenter = query_builder
        self.menu_item_activated = False

        self.and_or_combo: Gtk.ComboBoxText | None = None
        if row_number != 1:
            self.and_or_combo = Gtk.ComboBoxText()
            self.and_or_combo.append_text("and")
            self.and_or_combo.append_text("or")
            self.and_or_combo.set_active(0)
            self.grid.attach(self.and_or_combo, 0, row_number, 1, 1)
            self.and_or_combo.connect(
                "changed", lambda w: self.presenter.validate()
            )

        self.not_combo = Gtk.ComboBoxText()
        self.not_combo.append_text("")
        self.not_combo.append_text("not")
        self.not_combo.set_active(0)
        self.grid.attach(self.not_combo, 1, row_number, 1, 1)
        self.not_combo.connect("changed", lambda w: self.presenter.validate())
        self.not_combo.set_tooltip_text(
            'Set to "not" to search for the inverse'
        )

        self.prop_button = Gtk.Button(label=_("Choose a property…"))

        recurse = prefs.prefs.get(prefs.query_builder_recurse, False)
        self.schema_menu = SchemaMenu(
            self.presenter.mapper,
            self.on_schema_menu_activated,
            self.column_filter,
            self.relation_filter,
            recurse=recurse,
        )
        self.prop_button.connect(
            "button-press-event", self.on_prop_button_clicked, self.schema_menu
        )
        self.prop_button.set_tooltip_text("The property to query")
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
            "changed", lambda w: self.presenter.validate()
        )
        self.cond_combo.set_tooltip_text("How to search")

        self.value_widget: Gtk.Widget = Gtk.Entry()
        self.value_widget.connect("changed", self.on_value_changed)
        self.value_widget.set_tooltip_text("The value to search for")
        self.grid.attach(self.value_widget, 4, row_number, 1, 1)

        if row_number != 1:
            self.remove_button = Gtk.Button.new_from_icon_name(
                "list-remove-symbolic", Gtk.IconSize.BUTTON
            )

            def on_remove_btn_clicked(_button):
                remove_callback(self)
                self.presenter.validate()

            self.remove_button.connect("clicked", on_remove_btn_clicked)
            self.grid.attach(self.remove_button, 5, row_number, 1, 1)
        query_builder.resize(1, 1)

    @staticmethod
    def on_prop_button_clicked(
        _button, event: Gdk.Event, menu: Gtk.Menu
    ) -> None:
        menu.popup_at_pointer(event)

    @staticmethod
    def is_accepted_text(text: str) -> bool:
        return text in ("None"[: len(text)], "Empty"[: len(text)])

    def on_value_changed(self, widget: Gtk.Widget) -> None:
        """Adjust widget if required and if the query is valid enable OK."""
        # change to a standard entry if the user tries to enter none numbers
        if isinstance(widget, Gtk.SpinButton):
            text = widget.get_text()
            if text and self.is_accepted_text(text):
                focus = widget.has_focus()
                top = self.grid.child_get_property(
                    self.value_widget, "top-attach"
                )
                left = self.grid.child_get_property(
                    self.value_widget, "left-attach"
                )
                self.grid.remove(self.value_widget)
                self.value_widget = Gtk.Entry()
                self.value_widget.connect(
                    "changed", self.on_number_value_changed
                )
                self.value_widget.set_tooltip_text(
                    'Number or "None" for no value has been set'
                )
                self.grid.attach(self.value_widget, left, top, 1, 1)
                self.grid.show_all()
                if focus:
                    self.value_widget.grab_focus()
                self.value_widget.set_text(text)
                self.value_widget.set_position(1)
            widget.set_activates_default(True)
        elif isinstance(widget, Gtk.Entry):
            if any(i in widget.get_text() for i in ["%", "_"]):
                self.cond_combo.set_active(self.CONDITIONS.index("like"))
            elif self.cond_combo.get_active_text() == "like":
                self.cond_combo.set_active(0)
            widget.set_activates_default(True)

        self.presenter.validate()

    def on_number_value_changed(self, widget: Gtk.Entry) -> None:
        """Loosely constrain text to None or numbers parts only"""
        val = widget.get_text()
        if not self.is_accepted_text(val):
            val = "".join([i for i in val if i in "-.0123456789"])
            widget.set_text(val)
        self.on_value_changed(widget)

    def on_schema_menu_activated(
        self, _menuitem, path: str, prop: ColumnProperty
    ) -> None:
        """Called when an item in the schema menu is activated"""
        self.prop_button.set_label(path)
        self.menu_item_activated = True
        top = self.grid.child_get_property(self.value_widget, "top-attach")
        left = self.grid.child_get_property(self.value_widget, "left-attach")
        self.grid.remove(self.value_widget)

        # change the widget depending on the type of the selected property
        logger.debug("prop = %s", prop)
        try:
            self.proptype = type(prop.columns[0].type)
        except AttributeError:
            self.proptype = None
        # reset the cond_combo incase it was last a date/datetime
        if self.proptype not in (bauble.btypes.Date, bauble.btypes.DateTime):
            self.cond_combo.handler_block(self.cond_handler)
            self.cond_combo.remove_all()
            for condition in self.CONDITIONS:
                self.cond_combo.append_text(condition)
            self.cond_combo.set_active(0)
            self.cond_combo.handler_unblock(handler_id=self.cond_handler)
            self.cond_combo.set_tooltip_text("How to search")

        val = utils.get_widget_value(self.value_widget)
        set_value_widget = self.get_set_value_widget(path)
        set_value_widget(prop, val)

        self.grid.attach(self.value_widget, left, top, 1, 1)
        self.grid.show_all()
        self.presenter.validate()

    def get_set_value_widget(
        self, path: str
    ) -> Callable[[ColumnProperty, Any], None]:
        logger.debug("proptype = %s", self.proptype)

        column_name = path.rsplit(".", 1)[-1]
        if column_name in self.custom_columns:
            return partial(
                self.set_custom_enum_widget, self.custom_columns[column_name]
            )
        widgets: dict[type | None, Callable[[ColumnProperty, Any], None]] = {
            bauble.btypes.Enum: self.set_enum_widget,
            Integer: self.set_int_widget,
            Float: self.set_float_widget,
            bauble.btypes.Boolean: self.set_bool_widget,
            bauble.btypes.Date: self.set_date_widget,
            bauble.btypes.DateTime: self.set_date_widget,
        }
        return widgets.get(self.proptype, self.set_entry_widget)

    def set_custom_enum_widget(self, values: tuple, _prop, val: str) -> None:
        self.value_widget = Gtk.ComboBoxText()
        for value in values:
            self.value_widget.append_text(str(value))
        self.value_widget.set_tooltip_text("select a value")
        self.value_widget.connect("changed", self.on_value_changed)
        utils.set_widget_value(self.value_widget, val)

    def set_enum_widget(self, prop: ColumnProperty, val: str) -> None:
        self.value_widget = Gtk.ComboBox()
        cell = Gtk.CellRendererText()
        self.value_widget.pack_start(cell, True)
        self.value_widget.add_attribute(cell, "text", 1)
        model = Gtk.ListStore(str, str)
        if prop.columns[0].type.translations:
            trans = prop.columns[0].type.translations
            prop_values = [(k, trans[k] or "None") for k in trans.keys()]
            for value, translation in prop_values:
                model.append([value, translation])
        self.value_widget.set_model(model)
        self.value_widget.set_tooltip_text(
            'select a value, "None" means no value has been set'
        )
        self.value_widget.connect("changed", self.on_value_changed)
        utils.set_widget_value(self.value_widget, val)

    def set_int_widget(self, _prop, val: int | str) -> None:
        adjustment = Gtk.Adjustment(
            upper=1000000000000, step_increment=1, page_increment=10
        )
        self.value_widget = Gtk.SpinButton(
            adjustment=adjustment, numeric=False
        )
        self.value_widget.set_tooltip_text(
            'Number (non decimal) or "None" for no value has been set'
        )
        try:
            val = int(val or 0)
            self.value_widget.set_value(float(val))
        except ValueError:
            pass
        self.value_widget.connect("changed", self.on_number_value_changed)

    def set_float_widget(self, _prop, val: float | str) -> None:
        adjustment = Gtk.Adjustment(
            upper=10000000,
            lower=0.00000000001,
            step_increment=0.1,
            page_increment=1,
        )
        self.value_widget = Gtk.SpinButton(
            adjustment=adjustment, digits=10, numeric=False
        )
        self.value_widget.set_tooltip_text(
            'Number, decimal number or "None" for no value has been set'
        )
        try:
            val = float(val or 0)
            self.value_widget.set_value(val)
        except ValueError:
            pass
        self.value_widget.connect("changed", self.on_number_value_changed)

    def set_bool_widget(self, _prop, val: str) -> None:
        values = ["False", "True"]
        self.value_widget = Gtk.ComboBoxText()
        for value in values:
            self.value_widget.append_text(value)
        self.value_widget.set_tooltip_text("Select a value")
        self.value_widget.connect("changed", self.on_value_changed)
        utils.set_widget_value(
            self.value_widget, val if val in values else "False"
        )

    def set_date_widget(self, prop: ColumnProperty, val: str) -> None:
        self.value_widget = Gtk.Entry()
        self.value_widget.set_tooltip_text(
            "Date (e.g. 1/1/2021), 0 for today, a negative number for "
            'number of days before today or "None" for no date has been '
            'set.  Also accepts text dates (e.g. "15 Feb \'22") and "today" '
            'or "yesterday"'
        )
        self.value_widget.connect("changed", self.on_value_changed)
        self.value_widget.set_text(val)
        conditions = self.CONDITIONS.copy()
        prev = self.cond_combo.get_active_text()
        conditions.append("on")
        self.cond_combo.handler_block(self.cond_handler)
        self.cond_combo.remove_all()
        for condition in conditions:
            self.cond_combo.append_text(condition)
        # set 'on' as default
        if isinstance(prop.columns[0].type, bauble.btypes.DateTime):
            logger.debug("setting condition to 'on'")
            self.cond_combo.set_active(len(conditions) - 1)
        else:
            self.cond_combo.set_active(conditions.index(str(prev)))
        self.cond_combo.handler_unblock(handler_id=self.cond_handler)
        self.cond_combo.set_tooltip_text("How to search")

    def set_entry_widget(self, _prop, val: str) -> None:
        self.value_widget = Gtk.Entry()
        self.value_widget.set_tooltip_text(
            'The text value to search for or "None" for no value has been '
            "set"
        )
        self.value_widget.connect("changed", self.on_value_changed)
        if val is not None:
            self.value_widget.set_text(str(val))

    @staticmethod
    def column_filter(key: str, prop: InspectionAttr) -> bool:
        # skip any id fields (e.g. genus_id) as they are available via the
        # related id property (e.g. species.genus_id == species.genus.id)
        # Except obj_id from tags
        if key.endswith("_id") and not key == "obj_id":
            return False
        if key.startswith("_") and key not in ("_last_updated", "_created"):
            return False
        if isinstance(prop, hybrid_property) and not prop.expr:
            return False
        qualname = ""
        if hasattr(prop, "__qualname__"):
            qualname = getattr(prop, "__qualname__")
        else:
            qualname = str(prop)
        if prefs.prefs.get(
            prefs.query_builder_advanced, False
        ) is False and qualname in prefs.prefs.get(
            prefs.query_builder_excludes, []
        ):
            return False
        return True

    @staticmethod
    def relation_filter(key: str, _prop) -> bool:
        if prefs.prefs.get(
            prefs.query_builder_advanced, False
        ) is False and key.startswith("_"):
            return False
        return True

    def get_widgets(self) -> Generator[Gtk.Widget]:
        """Returns the and_or_combo, prop_button, cond_combo, value_widget, and
        remove_button widgets.
        """
        return (
            i
            for i in (
                self.and_or_combo,
                self.not_combo,
                self.prop_button,
                self.cond_combo,
                self.value_widget,
                self.remove_button,
            )
            if i
        )

    def get_expression(self) -> str | None:
        """Return the expression represented by this ExpressionRow.

        If the expression is not valid then return None.
        """

        if not self.menu_item_activated:
            return None

        value = ""
        if isinstance(self.value_widget, Gtk.ComboBoxText):
            value = self.value_widget.get_active_text() or ""
        elif isinstance(self.value_widget, Gtk.ComboBox):
            model = self.value_widget.get_model()
            active_iter = self.value_widget.get_active_iter()
            if active_iter:
                value = model[active_iter][0]
        elif isinstance(self.value_widget, Gtk.Entry):
            # assume it's a Gtk.Entry or other widget with a text property
            value = self.value_widget.get_text()
        value = parse_typed_value(value, self.proptype)
        and_or = ""
        if self.and_or_combo:
            and_or = self.and_or_combo.get_active_text() or ""
        _not = self.not_combo.get_active_text()
        field_name = self.prop_button.get_label()
        if value == EmptyToken():
            field_name = field_name.rsplit(".", 1)[0]
            value = repr(value)
        if isinstance(value, NoneToken):
            value = "None"
        result = " ".join(
            [
                i
                for i in (
                    and_or,
                    _not,
                    field_name,
                    self.cond_combo.get_active_text(),
                    value,
                )
                if i
            ]
        ).strip()
        return result


@dataclass
class Clause:  # pylint: disable=too-few-public-methods
    not__: bool = False
    connector: str | None = None
    field: str | None = None
    operator: str | None = None
    value: str | None = None


class BuiltQuery:
    """Parse a query string for its domain and clauses to preloading the
    QueryBuilder.
    """

    conditions = " ".join(ExpressionRow.CONDITIONS) + " on"
    binop = one_of(conditions, caseless=True).set_name("binary operator")
    # Forward to break out railroad diagram i.e. don't streamline and/or_clause
    clause = cast(Forward, Forward().set_name("clause"))
    and_clause = Group(and_ + clause).set_name("and clause")
    or_clause = Group(or_ + clause).set_name("or clause")
    clause <<= Opt(not_) + unfiltered_identifier + binop + value_token

    infix_clauses = (and_clause | or_clause).set_name("infix clauses")
    # Forward to break out railroad diagram
    expression = cast(Forward, Forward().set_name("expression"))
    query = domain + CaselessLiteral("where").suppress() + expression
    expression <<= (Group(clause) + ZeroOrMore(infix_clauses)).set_name(
        "expression"
    )

    def __init__(self, search_string: str) -> None:
        self.parsed = None
        self._clauses: list[Clause] = []
        try:
            self.parsed = self.query.parse_string(search_string)
            self.is_valid = True
        except ParseException as e:
            logger.debug("%s(%s)", type(e).__name__, e)
            self.is_valid = False

    @property
    def clauses(self) -> list[Clause]:
        if not self._clauses and self.parsed:
            self._clauses = []
            for part in [k for k in self.parsed if len(k) > 0][1:]:
                clause = Clause()
                if len(part) > 3:
                    if part.and_:
                        clause.connector = "and"
                    elif part.or_:
                        clause.connector = "or"
                    if part.not_:
                        clause.not__ = True
                # clause.field = ".".join(part[-3])
                clause.field = str(part[-3])
                clause.operator = part[-2]
                val = (
                    part[-1].value.raw_value
                    if hasattr(part[-1].value, "raw_value")
                    else str(part[-1])
                )
                if val == "(None<NoneType>)":
                    val = "None"
                elif val != "'None'":
                    val = val.strip("'")
                clause.value = val
                self._clauses.append(clause)

        return self._clauses

    @property
    def domain_str(self) -> str:
        return self.parsed[0] if self.parsed else ""


@Gtk.Template(
    filename=str(Path(__file__).resolve().parent / "query_builder.ui")
)
class QueryBuilder(Gtk.Dialog):

    __gtype_name__ = "QueryBuilder"
    domain_liststore = cast(Gtk.ListStore, Gtk.Template.Child())
    domain_combo = cast(Gtk.ComboBox, Gtk.Template.Child())
    advanced_switch = cast(Gtk.Switch, Gtk.Template.Child())
    help_label = cast(Gtk.Label, Gtk.Template.Child())
    query_lbl = cast(Gtk.Label, Gtk.Template.Child())
    expressions_table = cast(Gtk.Grid, Gtk.Template.Child())
    add_clause_button = cast(Gtk.Button, Gtk.Template.Child())
    confirm_button = cast(Gtk.Button, Gtk.Template.Child())

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)

        self.expression_rows: list[ExpressionRow] = []
        self.mapper: Mapper
        self.domain: str | None = None
        self.table_row_count = 0
        self.domain_map = MapperSearch.get_domain_classes().copy()

        self.domain_combo.set_active(-1)
        self.advanced_switch.set_active(
            prefs.prefs.get(prefs.query_builder_advanced, False)
        )

        for key in sorted(self.domain_map.keys()):
            self.domain_liststore.append([key])

        utils.make_label_clickable(self.help_label, self.on_help_clicked)

    def on_help_clicked(self, _label, _event) -> None:
        msg = _(
            "<b>Search Domain</b> - the type of items you want "
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
            "<b>&gt;</b> or <b>&lt;</b> condition\n"
            "        <tt>plant where planted.date > -10</tt>\n"
            "Return plants that where planted in the last 10 days.\n"
        )
        dialog = utils.create_message_dialog(msg, parent=self, resizable=False)
        dialog.set_title(_("Basic Intro to Queries"))
        dialog.run()
        dialog.destroy()

    @Gtk.Template.Callback()
    def on_advanced_set(self, _switch, state: bool) -> None:
        prefs.prefs[prefs.query_builder_advanced] = state
        self.reset_expression_table()

    @Gtk.Template.Callback()
    def on_domain_combo_changed(self, combo: Gtk.ComboBox) -> None:
        """Change the search domain."""
        index = combo.get_active()

        # pylint: disable=unsubscriptable-object
        self.domain = self.domain_liststore[index][0]
        self.reset_expression_table()

    def reset_expression_table(self) -> None:
        """Resets the expression table, clear the query label and deletes all
        the expression rows.
        """

        self.query_lbl.set_text("")
        # remove all clauses, they became useless in new domain
        for child in self.expressions_table.get_children():
            self.expressions_table.remove(child)
        self.expression_rows.clear()
        # initialize view at 1 clause, however invalid
        self.table_row_count = 0
        self.on_add_clause()
        self.resize(1, 1)
        self.expressions_table.show_all()
        # let user add more clauses
        self.add_clause_button.set_sensitive(True)

    def validate(self) -> bool:
        """Validate the search expression is a valid expression."""
        valid = False
        query_string = f"{self.domain} where"
        for row in self.expression_rows:
            value = False
            if isinstance(row.value_widget, Gtk.Entry):  # also spinbutton
                value = bool(row.value_widget.get_text())
            elif isinstance(row.value_widget, Gtk.ComboBox):
                value = row.value_widget.get_active() >= 0

            query_string = f"{query_string} {row.get_expression() or ''}"
            self.query_lbl.set_text(query_string)

            if value and row.menu_item_activated:
                valid = True
            else:
                valid = False
                break

        self.confirm_button.set_sensitive(valid)
        return valid

    def remove_expression_row(self, row: ExpressionRow) -> None:
        """Remove a row from the expressions table."""
        for widget in row.get_widgets():
            widget.destroy()
        self.table_row_count -= 1
        self.expression_rows.remove(row)
        self.resize(1, 1)

    @Gtk.Template.Callback()
    def on_add_clause(self, _widget=None) -> None:
        """Add a row to the expressions table."""
        if not self.domain:
            return

        domain_cls = self.domain_map.get(self.domain)

        self.mapper = class_mapper(domain_cls)
        self.table_row_count += 1
        row = ExpressionRow(
            self, self.remove_expression_row, self.table_row_count
        )
        self.expression_rows.append(row)
        self.expressions_table.show_all()

    def destroy(self) -> None:  # pylint: disable=arguments-differ
        for row in self.expression_rows:
            row.schema_menu.destroy()
        super().destroy()

    @property
    def valid_clauses(self) -> list[str]:
        return [
            value
            for i in self.expression_rows
            if (value := i.get_expression())
        ]

    def get_query(self) -> str:
        """Return query expression string."""

        if not self.domain:
            return ""

        query = [self.domain, "where"] + self.valid_clauses
        return " ".join(query)

    def set_query(self, query: str) -> None:
        parsed = BuiltQuery(query)
        if not parsed.is_valid:
            logger.debug("cannot restore query, invalid")
            return

        index = sorted(self.domain_map.keys()).index(parsed.domain_str)
        # and set the domain_combo correspondently
        self.domain_combo.set_active(index)

        # now scan all clauses, one ExpressionRow per clause
        for clause in parsed.clauses:
            if clause.connector:
                self.on_add_clause()
            row = self.expression_rows[-1]
            if clause.connector and row.and_or_combo:
                row.and_or_combo.set_active(
                    {"and": 0, "or": 1}[clause.connector]
                )
            if clause.not__:
                row.not_combo.set_active(1)

            column = self.get_column(clause, parsed.domain_str)
            if not column:
                return

            conditions = row.CONDITIONS.copy()
            if hasattr(column, "columns") and isinstance(
                column.columns[0].type,
                (bauble.btypes.Date, bauble.btypes.DateTime),
            ):
                row.cond_combo.append_text("on")
                conditions.append("on")
            row.on_schema_menu_activated(None, clause.field or "", column)
            if isinstance(row.value_widget, Gtk.Entry):  # also spinbutton
                row.value_widget.set_text(clause.value or "")
            elif isinstance(row.value_widget, Gtk.ComboBox):
                for item in row.value_widget.props.model:
                    val = None if clause.value == "None" else clause.value
                    if item[0] == val:
                        row.value_widget.set_active_iter(item.iter)
                        break
            # check for misplaced 'on'
            if clause.operator in conditions:
                row.cond_combo.set_active(conditions.index(clause.operator))

    def get_column(
        self, clause: Clause, domain_str: str
    ) -> ColumnProperty | None:
        if not clause.field:
            return None

        steps = clause.field.split(".")
        cls = self.domain_map[domain_str]
        mapper = class_mapper(cls)
        try:
            for target in steps[:-1]:
                if hasattr(
                    proxy := getattr(mapper.class_, target),
                    "target_collection",
                ):
                    # AssociationProxy
                    mapper = mapper.get_property(
                        proxy.target_collection
                    ).mapper
                    mapper = mapper.get_property(proxy.value_attr).mapper
                else:
                    mapper = mapper.get_property(target).mapper
            try:
                column = mapper.get_property(steps[-1])
            except InvalidRequestError:
                column = mapper.all_orm_descriptors[steps[-1]]
        except Exception as e:  # pylint: disable=broad-except
            logger.debug(
                "cannot restore query details, %s(%s)", type(e).__name__, e
            )
            return None
        return column
