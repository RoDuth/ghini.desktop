# Copyright 2008-2010 Brett Adams
# Copyright 2012-2015 Mario Frasca <mario@anche.no>.
# Copyright 2017 Jardín Botánico de Quito
# Copyright 2020-2023 Ross Demuth <rossdemuth123@gmail.com>
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
"""
Species modules
"""

import os
import traceback

import logging
logger = logging.getLogger(__name__)

from gi.repository import Gtk  # noqa
from gi.repository import Pango

from sqlalchemy.orm.session import object_session
from sqlalchemy import or_

import bauble
from bauble import paths
from bauble import db

from bauble import pluginmgr
from bauble import utils
from bauble.view import (InfoBox,
                         InfoBoxPage,
                         InfoExpander,
                         select_in_search_results)
from bauble import search
from bauble.view import PropertiesExpander, Action
from bauble import view
from bauble import prefs
from .species_editor import (SpeciesDistribution,
                             SpeciesEditorPresenter,
                             SpeciesEditorView,
                             SpeciesEditor,
                             edit_species)
from .species_model import (Species,
                            SpeciesNote,
                            VernacularName,
                            SpeciesSynonym,
                            DefaultVernacularName)
from .genus import Genus, GenusSynonym
from .family import Family, FamilySynonym

# imported by clients of this modules
__all__ = [
    'SpeciesDistribution', 'SpeciesEditorPresenter', 'SpeciesEditorView',
    'SpeciesEditor', 'edit_species', 'DefaultVernacularName',
    'SpeciesNote'
]

# TODO: we need to make sure that this will still work if the
# AccessionPlugin is not present, this means that we would have to
# change the species context menu, getting the children from the
# search view and what else


def edit_callback(values):
    sp = values[0]
    if isinstance(sp, VernacularName):
        sp = sp.species
    return edit_species(model=sp) is not None


def remove_callback(values):
    """
    The callback function to remove a species from the species context menu.
    """
    from bauble.plugins.garden.accession import Accession
    species = values[0]
    s_lst = []
    session = object_session(species)
    for species in values:
        if isinstance(species, VernacularName):
            species = species.species
        nacc = session.query(Accession).filter_by(
            species_id=species.id).count()
        safe_str = utils.xml_safe(str(species))
        s_lst.append(safe_str)
        if nacc > 0:
            msg = (_('The species <i>%(1)s</i> has %(2)s accessions.'
                     '\n\n') % {'1': safe_str, '2': nacc} +
                   _('You cannot remove a species with accessions.'))
            utils.message_dialog(msg, typ=Gtk.MessageType.WARNING)
            return False
    msg = _("Are you sure you want to remove the following species "
            "<i>%s</i>?") % ', '.join(i for i in s_lst)
    if not utils.yes_no_dialog(msg):
        return False
    for species in values:
        session.delete(species)
    try:
        utils.remove_from_results_view(values)
        session.commit()
    except Exception as e:  # pylint: disable=broad-except
        msg = _('Could not delete.\n\n%s') % utils.xml_safe(e)
        utils.message_details_dialog(msg, traceback.format_exc(),
                                     Gtk.MessageType.ERROR)
        session.rollback()
    return True


def add_accession_callback(values):
    from bauble.plugins.garden.accession import Accession, AccessionEditor
    session = db.Session()
    species = session.merge(values[0])
    if isinstance(species, VernacularName):
        species = species.species
    e = AccessionEditor(model=Accession(species=species))
    session.close()
    return e.start() is not None


edit_action = Action('species_edit', _('_Edit'),
                     callback=edit_callback,
                     accelerator='<ctrl>e')
add_accession_action = Action('species_acc_add', _('_Add accession'),
                              callback=add_accession_callback,
                              accelerator='<ctrl>k')
remove_action = Action('species_remove', _('_Delete'),
                       callback=remove_callback,
                       accelerator='<ctrl>Delete', multiselect=True)

species_context_menu = [edit_action, remove_action]

vernname_context_menu = [edit_action]


def on_taxa_clicked(_label, _event, taxon):
    """Function intended for use with :func:`utils.make_label_clickable`

    if the return_accepted_pref is set True then select both the name synonym
    clicked on and its accepted name.
    """
    if prefs.prefs.get(prefs.return_accepted_pref) and taxon.accepted:
        select_in_search_results(taxon.accepted)
    select_in_search_results(taxon)


class SynonymSearch(search.SearchStrategy):
    """Return any synonyms for matching taxa.

    'bauble.search.return_accepted' pref toggles this.
    """

    def __init__(self):
        super().__init__()
        if prefs.return_accepted_pref not in prefs.prefs:
            prefs.prefs[prefs.return_accepted_pref] = True
            prefs.prefs.save()

    @staticmethod
    def use(_text):
        if prefs.prefs.get(prefs.return_accepted_pref):
            return 'include'
        return 'exclude'

    @staticmethod
    def get_ids(mapper_results):
        """Colate IDs and models to search for each result type."""
        ids = {}
        for result in mapper_results:
            models = None
            if isinstance(result, Species):
                models = (Species, SpeciesSynonym)
                id_ = result.id
            elif isinstance(result, Genus):
                models = (Genus, GenusSynonym)
                id_ = result.id
            elif isinstance(result, Family):
                models = (Family, FamilySynonym)
                id_ = result.id
            elif isinstance(result, VernacularName):
                models = (VernacularName, SpeciesSynonym)
                id_ = result.species.id
            if models:
                ids.setdefault(models, set()).add(id_)
        return ids

    def search(self, text, session):
        """Search for a synonym for each item in the results and add to the
        results
        """
        super().search(text, session)
        if not prefs.prefs.get(prefs.return_accepted_pref):
            # filter should prevent us getting here.
            return []
        mapper_results = search.result_cache.get('MapperSearch')
        if not mapper_results:
            return []
        ids = self.get_ids(mapper_results)
        if not ids:
            return []
        results = []
        for models, id_set in ids.items():
            # vernacular names are a special case.  Only returning if both
            # accepted and synonym have a VernacularName entry.
            if models[0] == VernacularName:
                syn_model_id = getattr(models[1], 'species_id')
                syn_id = getattr(models[1], 'synonym_id')
                query = (session.query(models[0])
                         .join(Species)
                         .join(SpeciesSynonym, syn_model_id == Species.id)
                         .filter(syn_id.in_(id_set)))
            else:
                id_ = getattr(models[0], 'id')
                syn_model_id = getattr(models[1],
                                       models[0].__tablename__ + '_id')
                syn_id = getattr(models[1], 'synonym_id')
                query = (session.query(models[0])
                         .join(models[1], syn_model_id == id_)
                         .filter(syn_id.in_(id_set)))
            if (prefs.prefs.get(prefs.exclude_inactive_pref) and
                    hasattr(models[0], 'active')):
                query = query.filter(or_(models[0].active.is_(True),
                                         models[1].synonym.has(active=True)))

            results.extend(query.all())
        return results


# TODO should these and even the InfoBoxPage be Gtk.Template?
class VernacularExpander(InfoExpander):
    """VernacularExpander

    :param widgets:
    """

    EXPANDED_PREF = 'infobox.species_vernacular_expanded'

    def __init__(self, widgets):
        super().__init__(_("Vernacular names"), widgets)
        vernacular_box = self.widgets.sp_vernacular_box
        self.widgets.remove_parent(vernacular_box)
        self.vbox.pack_start(vernacular_box, True, True, 0)
        self.display_widgets = [vernacular_box]

    def update(self, row):
        """update the expander

        :param row: the row to get the values from
        """
        self.reset()
        if row.vernacular_names:
            self.unhide_widgets()
            names = []
            for vernacular in row.vernacular_names:
                if (row.default_vernacular_name is not None and
                        vernacular == row.default_vernacular_name):
                    names.insert(
                        0,
                        f'{vernacular.name} - {vernacular.language} (default)'
                    )
                else:
                    names.append(f'{vernacular.name} - {vernacular.language}')
            self.widget_set_value('sp_vernacular_data', '\n'.join(names))
            self.set_sensitive(True)


class SynonymsExpander(InfoExpander):

    EXPANDED_PREF = 'infobox.species_synonyms_expanded'

    def __init__(self, widgets):
        super().__init__(_("Synonyms"), widgets)
        synonyms_box = self.widgets.sp_synonyms_box
        self.widgets.remove_parent(synonyms_box)
        self.vbox.pack_start(synonyms_box, True, True, 0)

    def update(self, row):
        """Update the expander

        :param row: the row to get the values from
        """
        self.reset()
        syn_box = self.widgets.sp_synonyms_box
        # remove old labels
        syn_box.foreach(syn_box.remove)
        logger.debug(row.synonyms)
        self.set_label(_("Synonyms"))  # reset default value
        on_label_clicked = utils.generate_on_clicked(select_in_search_results)
        if row.accepted is not None:
            self.set_label(_("Accepted name"))
            # create clickable label that will select the synonym
            # in the search results
            box = Gtk.EventBox()
            label = Gtk.Label()
            label.set_xalign(0.0)
            label.set_yalign(0.5)
            label.set_markup(row.accepted.str(markup=True, authors=True))
            box.add(label)
            utils.make_label_clickable(label, on_label_clicked, row.accepted)
            syn_box.pack_start(box, False, False, 0)
            self.show_all()
            self.set_sensitive(True)
        elif row.synonyms:
            for syn in row.synonyms:
                # create clickable label that will select the synonym
                # in the search results
                box = Gtk.EventBox()
                label = Gtk.Label()
                label.set_xalign(0.0)
                label.set_yalign(0.5)
                label.set_markup(syn.str(markup=True, authors=True))
                box.add(label)
                utils.make_label_clickable(label, on_label_clicked, syn)
                syn_box.pack_start(box, False, False, 0)
            self.show_all()
            self.set_sensitive(True)


class GeneralSpeciesExpander(InfoExpander):
    """expander to present general information about a species"""

    def __init__(self, widgets):
        super().__init__(_("General"), widgets)
        general_box = self.widgets.sp_general_box
        self.widgets.remove_parent(general_box)
        self.vbox.pack_start(general_box, True, True, 0)
        # wrapping the species but not the genus looks odd, better to ellipsize
        self.widgets.sp_epithet_data.set_ellipsize(Pango.EllipsizeMode.END)

        self.current_obj = None

        def on_nacc_clicked(*_args):
            cmd = f'accession where species.id={self.current_obj.id}'
            bauble.gui.send_command(cmd)

        utils.make_label_clickable(self.widgets.sp_nacc_data,
                                   on_nacc_clicked)

        def on_nplants_clicked(*_args):
            cmd = f'plant where accession.species.id={self.current_obj.id}'
            bauble.gui.send_command(cmd)

        utils.make_label_clickable(self.widgets.sp_nplants_data,
                                   on_nplants_clicked)

    def update(self, row):
        """update the expander

        :param row: the row to get the values from
        """
        self.current_obj = row
        session = object_session(row)

        # Link to family
        self.widget_set_value('sp_fam_data',
                              f'<small>({row.genus.family.family})</small>',
                              markup=True)
        utils.make_label_clickable(self.widgets.sp_fam_data,
                                   on_taxa_clicked,
                                   row.genus.family)
        genus = row.genus.markup()
        self.widget_set_value('sp_gen_data',
                              f'<big>{genus}</big>',
                              markup=True)
        utils.make_label_clickable(
            self.widgets.sp_gen_data, on_taxa_clicked, row.genus)
        # epithet (full binomial but missing genus)
        self.widget_set_value(
            'sp_epithet_data',
            f' <big>{row.markup(authors=True, genus=False)}</big>',
            markup=True
        )

        awards = ''
        if row.awards:
            awards = utils.nstr(row.awards)
        self.widget_set_value('sp_awards_data', awards)

        self.widget_set_value('sp_cites_data', row.cites or '')

        # zone = ''
        # if row.hardiness_zone:
        #     awards = utils.nstr(row.hardiness_zone)
        # self.widget_set_value('sp_hardiness_data', zone)

        habit = ''
        if row.habit:
            habit = utils.nstr(row.habit)
        self.widget_set_value('sp_habit_data', habit)

        if self.widgets.sp_dist_box.get_children():
            for child in self.widgets.sp_dist_box.get_children():
                self.widgets.sp_dist_box.remove(child)
        on_clicked = utils.generate_on_clicked(select_in_search_results)
        if row.distribution:
            for place in row.distribution:
                event_box = Gtk.EventBox()
                label = Gtk.Label(label=utils.nstr(place))
                label.set_halign(Gtk.Align.START)
                event_box.add(label)
                self.widgets.sp_dist_box.pack_start(event_box, False, False, 0)

                utils.make_label_clickable(label, on_clicked,
                                           place.geography)
            self.widgets.sp_dist_box.show_all()

        dist = ''
        if row.label_distribution:
            dist = row.label_distribution
        self.widget_set_value('sp_labeldist_data', dist)

        # stop here if not GardenPluin
        if 'GardenPlugin' not in pluginmgr.plugins:
            return

        from bauble.plugins.garden.accession import Accession
        from bauble.plugins.garden.plant import Plant

        nacc = (session.query(Accession)
                .join('species')
                .filter_by(id=row.id)
                .count())
        self.widget_set_value('sp_nacc_data', nacc)

        nplants = (session.query(Plant)
                   .join('accession', 'species')
                   .filter_by(id=row.id)
                   .count())
        if nplants == 0:
            self.widget_set_value('sp_nplants_data', nplants)
        else:
            nacc_in_plants = (session.query(Plant.accession_id)
                              .join('accession', 'species')
                              .filter_by(id=row.id)
                              .distinct()
                              .count())
            self.widget_set_value('sp_nplants_data',
                                  f'{nplants} in {nacc_in_plants} accessions')

        living_plants = sum(i.quantity for i in
                            session.query(Plant)
                            .join('accession', 'species')
                            .filter_by(id=row.id).all())
        self.widget_set_value('living_plants_count', living_plants)


class SpeciesInfoBox(InfoBox):

    def __init__(self):
        super().__init__()
        page = SpeciesInfoPage()
        label = page.label
        if isinstance(label, str):
            label = Gtk.Label(label=label)
        self.insert_page(page, label, 0)


class SpeciesInfoPage(InfoBoxPage):
    """general info, fullname, common name, num of accessions and clones,
    distribution
    """
    SPECIES_WEB_BUTTON_DEFS_PREFS = 'web_button_defs.species'

    # others to consider: reference, images, redlist status

    def __init__(self):
        button_defs = []
        buttons = prefs.prefs.itersection(self.SPECIES_WEB_BUTTON_DEFS_PREFS)
        for name, button in buttons:
            button['name'] = name
            button_defs.append(button)

        super().__init__()
        filename = os.path.join(paths.lib_dir(), 'plugins', 'plants',
                                'infoboxes.glade')
        # load the widgets directly instead of using load_widgets()
        # because the caching that load_widgets() does can mess up
        # displaying the SpeciesInfoBox sometimes if you try to show
        # the infobox while having a vernacular names selected in
        # the search results and then a species name
        self.widgets = utils.BuilderWidgets(filename)
        self.general = GeneralSpeciesExpander(self.widgets)
        self.add_expander(self.general)
        self.vernacular = VernacularExpander(self.widgets)
        self.add_expander(self.vernacular)
        self.synonyms = SynonymsExpander(self.widgets)
        self.add_expander(self.synonyms)
        self.links = view.LinksExpander('notes', links=button_defs)
        self.add_expander(self.links)
        self.props = PropertiesExpander()
        self.add_expander(self.props)
        self.label = _('General')

        if 'GardenPlugin' not in pluginmgr.plugins:
            self.widgets.remove_parent('sp_nacc_label')
            self.widgets.remove_parent('sp_nacc_data')
            self.widgets.remove_parent('sp_nplants_label')
            self.widgets.remove_parent('sp_nplants_data')

    def update(self, row):
        """
        update the expanders in this infobox

        :param row: the row to get the values from
        """
        self.general.update(row)
        self.vernacular.update(row)
        self.synonyms.update(row)
        self.links.update(row)
        self.props.update(row)


# it's easier just to put this here instead of playing around with imports
class VernacularNameInfoBox(SpeciesInfoBox):

    def update(self, row):
        logger.debug("VernacularNameInfoBox.update %s(%s)",
                     row.__class__.__name__, row)
        if isinstance(row, VernacularName):
            super().update(row.species)
