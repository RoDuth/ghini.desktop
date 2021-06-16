# Copyright 2008-2010 Brett Adams
# Copyright 2014-2017 Mario Frasca <mario@anche.no>.
# Copyright 2016 Ross Demuth <rossdemuth123@gmail.com>
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


import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa

import re

import logging
logger = logging.getLogger(__name__)

from bauble.prefs import prefs, debug_logging_prefs, testing
if not testing and __name__ in prefs.get(debug_logging_prefs, []):
    logger.setLevel(logging.DEBUG)

from bauble.utils import desktop


class BaubleLinkButton(Gtk.LinkButton):

    _base_uri = "%s"
    _space = "_"
    title = _("Search")
    tooltip = None
    pt = re.compile(r'%\(([a-z_\.]*)\)s')

    def __init__(self, title=_("Search"), tooltip=None):
        super().__init__("", self.title)
        self.set_tooltip_text(self.tooltip or self.title)
        self.__class__.fields = self.pt.findall(self._base_uri)
        self.connect('activate-link', self.on_link_activated)

    def on_link_activated(self, view):
        logger.debug("opening link %s", self.get_uri())
        desktop.open(self.get_uri())
        return True

    def set_string(self, row):
        if self.fields == []:
            s = str(row)
            # remove any zws (species string)
            s = s.replace('\u200b', '')
            self.set_uri(self._base_uri % s.replace(' ', self._space))
        else:
            values = {}
            for key in self.fields:
                value = row
                for step in key.split('.'):
                    value = getattr(value, step, '-')
                values[key] = (value == str(value)) and value or ''
            self.set_uri(self._base_uri % values)
