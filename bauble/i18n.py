# Copyright (c) 2005,2006,2007,2008,2009 Brett Adams <brett@belizebotanic.org>
# Copyright (c) 2006 Mark Mruss http://www.learningpython.com
# Copyright (c) 2007 Kopfgeldjaeger
# Copyright (c) 2012-2017 Mario Frasca <mario@anche.no>
# Copyright 2017 Jardín Botánico de Quito
# Copyright (c) 2022 Ross Demuth <rossdemuth123@gmail.com>
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
# i18n.py
#
# internationalization support
#

"""
The i18n module defines the _() function for creating translatable strings.

_() is added to the Python builtins so there is no reason to import
this module more than once in an application.  It is usually imported
in :mod:`bauble`
"""

import os
import sys
import locale
import gettext
from bauble import paths
from bauble import version_tuple

if sys.platform == "win32":
    import ctypes
    windll = ctypes.windll.kernel32
    language = locale.windows_locale.get(windll.GetUserDefaultUILanguage())
    os.environ['LANGUAGE'] = language

__all__ = ["_"]

TEXT_DOMAIN = 'ghini-%s' % '.'.join(version_tuple[0:2])

# most of the following code was adapted from:
# http://www.learningpython.com/2006/12/03/\
# translating-your-pythonpygtk-application/

langs = []
# Check the default locale
try:
    # Python >= 3.11
    lang_code, encoding = locale.getlocale()
except AttributeError:
    lang_code, encoding = locale.getdefaultlocale()

if lang_code:
    # If we have a default, it's the first in the list
    langs = [lang_code]
# Now lets get all of the supported languages on the system
language = os.environ.get('LANGUAGE')
if language:
    # language comes back something like en_CA:en_US:en_GB:en on linuxy
    # systems, on Win32 it's nothing, so we need to split it up into a list
    langs.extend(language.split(":"))
# add on to the back of the list the translations that we know that we
# have, our defaults"""
langs.append("en")

# langs is a list of all of the languages that we are going to try to
# use.  First we check the default, then what the system told us, and
# finally the 'known' list

if sys.platform in ['win32', 'darwin']:
    locale = gettext

try:
    import Gtk.glade as gtkglade
except ImportError:
    gtkglade = locale

for module in locale, gtkglade:
    module.bindtextdomain(TEXT_DOMAIN, paths.locale_dir())
    module.textdomain(TEXT_DOMAIN)

# Get the language to use
lang = gettext.translation(TEXT_DOMAIN, paths.locale_dir(), languages=langs,
                           fallback=True)
# associate this module's as well as the global `_` functions (we marked our
# translatable strings with it) to lang.gettext(), which translates them.
_ = lang.gettext
import builtins
builtins._ = lang.gettext
