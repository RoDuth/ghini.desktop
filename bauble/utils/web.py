# Copyright 2008-2010 Brett Adams
# Copyright 2014-2017 Mario Frasca <mario@anche.no>.
# Copyright 2016-2022 Ross Demuth <rossdemuth123@gmail.com>
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

import re

import logging
logger = logging.getLogger(__name__)

from gi.repository import Gtk

from bauble.utils import desktop


class BaubleLinkButton(Gtk.LinkButton):

    _base_uri = "%s"
    _space = "_"
    title = _("Search")
    tooltip = None
    fields = []
    pt = re.compile(r'%\(([a-z_\.]+)\)s')

    def __init__(self):
        super().__init__(uri="", label=self.title)
        self.set_tooltip_text(self.tooltip or self.title)
        self.__class__.fields = self.pt.findall(self._base_uri)
        self.set_halign(Gtk.Align.START)
        self.connect('activate-link', self.on_link_activated)

    def on_link_activated(self, _button):
        logger.debug("opening link %s", self.get_uri())
        desktop.open(self.get_uri())
        return True

    def set_string(self, row):
        if self.fields == []:
            # remove any zws (species string)
            string = str(row).replace('\u200b', '').replace(' ', self._space)
            self.set_uri(self._base_uri % string)
        else:
            values = {}
            for key in self.fields:
                value = row
                for step in key.split('.'):
                    value = getattr(value, step, '-')
                values[key] = value if value == str(value) else ''
            self.set_uri(self._base_uri % values)


def link_button_factory(link):
    return type(link.get('name', 'LinkButton'), (BaubleLinkButton, ), link)()
