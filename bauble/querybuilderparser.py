#!/usr/bin/env python
#
# Copyright 2017 Mario Frasca <mario@anche.no>.
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

# help parsing the language produced by the Query Builder, so that we can
# offer the current active query back to the Query Builder, and the
# QueryBuilder will be able to start from there
#
# if the query does not follow the grammar, start from scratch.
"""
Parse a query string for its domain and clauses to preloading the QueryBuilder.
"""

from pyparsing import (Word, alphas, alphanums, delimitedList, Group,
                       alphas8bit, quotedString, Regex, oneOf,
                       CaselessLiteral, WordStart, WordEnd,
                       ZeroOrMore, Literal, ParseException)


class BuiltQuery:

    wordStart, wordEnd = WordStart(), WordEnd()

    AND_ = wordStart + CaselessLiteral('and') + wordEnd
    OR_ = wordStart + CaselessLiteral('or') + wordEnd
    BETWEEN_ = wordStart + CaselessLiteral('between') + wordEnd

    numeric_value = Regex(r'[-]?\d+(\.\d*)?([eE]\d+)?')
    datetime_str = Regex(
        r'\d{1,4}[/.-]{1}\d{1,2}[/.-]{1}\d{1,4}[ ]?[0-9: .apmAPM]*'
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
    value = (none_token | datetime_str | numeric_value | string_value |
             typed_value)
    binop = oneOf('= == != <> < <= > >= has like contains', caseless=True)
    clause = fieldname + binop + value
    unparseable_clause = (fieldname + BETWEEN_ + value + AND_ + value) | (
        Word(alphanums) + '(' + fieldname + ')' + binop + value)
    expression = Group(clause) + ZeroOrMore(Group(
        AND_ + clause | OR_ + clause | ((OR_ | AND_) + unparseable_clause)
        .suppress()))
    query = Word(alphas) + CaselessLiteral("where") + expression

    def __init__(self, search_string):
        self.parsed = None
        self.__clauses = None
        try:
            self.parsed = self.query.parseString(search_string)
            self.is_valid = True
        except ParseException:
            self.is_valid = False

    @property
    def clauses(self):
        if not self.__clauses:
            self.__clauses = [
                type('FooBar', (object,),
                     dict(connector=len(i) == 4 and i[0] or None,
                          field='.'.join(i[-3]),
                          operator=i[-2],
                          value=i[-1]))()
                for i in [k for k in self.parsed if len(k) > 0][2:]]
        return self.__clauses

    @property
    def domain(self):
        return self.parsed[0]
