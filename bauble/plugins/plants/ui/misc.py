# Copyright 2020-2026 Ross Demuth <rossdemuth123@gmail.com>
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
Miscellaneous helpers.
"""
from gi.repository import Gdk
from gi.repository import Gtk
from sqlalchemy import or_

from bauble import db
from bauble import prefs
from bauble.ui.views import select_in_search_results

from ..genus import Genus
from ..model import Taxon
from ..species import Species


def on_taxa_clicked(
    _label: Gtk.Label,
    _event: Gdk.Event,
    taxon: Taxon,
) -> None:
    """Function intended for use with :func:`utils.make_label_clickable`

    if the return_accepted_pref is set True then select both the name synonym
    clicked on and its accepted name.
    """
    if prefs.prefs.get(prefs.return_accepted_pref) and taxon.accepted:
        select_in_search_results(taxon.accepted)

    select_in_search_results(taxon)


def get_binomial_completions(text: str) -> set[str]:
    parts = text.split()
    sp_part = ""
    cv_part = ""

    with db.Session() as session:
        epithets = (
            session.query(
                Genus.epithet,
                Species.epithet,
                Species.cultivar_epithet,
                Species.trade_name,
            )
            .join(Genus)
            .filter(Genus.epithet.ilike(f"{parts[0]}%"))
        )
        if len(parts) == 2:
            if parts[1].startswith("'"):
                cv_part = parts[1][1:]
                epithets = epithets.filter(
                    or_(
                        Species.cultivar_epithet.startswith(cv_part),
                        Species.trade_name.startswith(cv_part),
                    )
                )
            else:
                sp_part = parts[1]
                epithets = epithets.filter(Species.epithet.startswith(sp_part))
        elif len(parts) == 3:
            sp_part = parts[1]
            epithets = epithets.filter(Species.epithet.startswith(sp_part))
            if parts[2].startswith("'"):
                cv_part = parts[2][1:]
                epithets = epithets.filter(
                    or_(
                        Species.cultivar_epithet.startswith(cv_part),
                        Species.trade_name.startswith(cv_part),
                    )
                )

        binomial_completions = set()
        for gen, sp, cv, trade_name in epithets.limit(10):
            string = f"{gen}"
            if sp and (sp_part or not cv_part):
                string += f"{' ' + sp.split()[0] if sp else ''}"
                if not cv_part:
                    binomial_completions.add(string)
            if cv and cv.startswith(cv_part):
                cv_string = string + f" '{cv}'"
                binomial_completions.add(cv_string)
            if trade_name and trade_name.startswith(cv_part):
                t_string = string + f" '{trade_name}'"
                binomial_completions.add(t_string)

    return binomial_completions
