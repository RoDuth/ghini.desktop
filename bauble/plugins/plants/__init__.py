# Copyright 2008-2010 Brett Adams
# Copyright 2012-2015 Mario Frasca <mario@anche.no>.
# Copyright 2021 Ross Demuth <rossdemuth123@gmail.com>
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
plants plugin
"""

import os
from threading import Thread
from functools import partial

import logging
logger = logging.getLogger(__name__)

from gi.repository import Gtk
from gi.repository import GLib

import bauble
from bauble import prefs
from bauble import db
from bauble import search

from bauble.paths import lib_dir
from bauble import pluginmgr
from bauble import utils
from bauble.view import SearchView
from bauble.ui import DefaultView
from .family import (Familia,
                     Family,
                     FamilyInfoBox,
                     FamilyEditor,
                     FamilyNote,
                     family_context_menu)
from .genus import (Genus,
                    GenusEditor,
                    GenusInfoBox,
                    GenusNote,
                    genus_context_menu)
from .species import (Species,
                      SpeciesEditorMenuItem,
                      SpeciesInfoBox,
                      SpeciesNote,
                      species_context_menu,
                      add_accession_action,
                      SynonymSearch,
                      SpeciesDistribution,
                      VernacularName,
                      VernacularNameInfoBox,
                      vernname_context_menu,
                      return_accepted_pref)
from .geography import (Geography,
                        get_species_in_geography,
                        GeographyInfoBox)
from .taxonomy_check import TaxonomyCheckTool
from .stored_queries import StoredQueryEditorTool

# imported by clients of the module
__all__ = ['Familia', 'SpeciesDistribution']


class LabelUpdater(Thread):
    def __init__(self, widget, query, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.query = query
        self.widget = widget

    def run(self):
        session = db.Session()
        # can on occassion raise:
        # Error in thread...
        # SystemError: Objects/tupleobject.c:159: bad argument to internal
        # function
        # possibly related to?: https://bugs.python.org/issue15108
        value, = session.execute(self.query).first()
        GLib.idle_add(self.widget.set_text, str(value))
        session.close()


class SplashInfoBox(pluginmgr.View):
    """info box shown in the initial splash screen."""

    def __init__(self):
        logger.debug('SplashInfoBox::__init__')
        super().__init__()
        filename = os.path.join(lib_dir(), 'plugins', 'plants',
                                'infoboxes.glade')
        self.widgets = utils.load_widgets(filename)
        self.widgets.remove_parent(self.widgets.splash_vbox)
        self.pack_start(self.widgets.splash_vbox, False, False, 8)
        self.name_tooltip_query = None

        on_clicked_search = utils.generate_on_clicked(bauble.gui.send_command)

        utils.make_label_clickable(
            self.widgets.splash_nfamtot,
            on_clicked_search,
            'family like %'
        )

        utils.make_label_clickable(
            self.widgets.splash_nfamuse,
            on_clicked_search,
            'family where genera.species.accessions.id != 0'
        )

        utils.make_label_clickable(
            self.widgets.splash_nfamnot,
            on_clicked_search,
            'family where not genera.species.accessions.id != 0'
        )

        utils.make_label_clickable(
            self.widgets.splash_ngentot,
            on_clicked_search,
            'genus like %'
        )

        utils.make_label_clickable(
            self.widgets.splash_ngenuse,
            on_clicked_search,
            'genus where species.accessions.id!=0'
        )

        utils.make_label_clickable(
            self.widgets.splash_ngennot,
            on_clicked_search,
            'genus where not species.accessions.id!=0'
        )

        utils.make_label_clickable(
            self.widgets.splash_nspctot,
            on_clicked_search,
            'species like %'
        )

        utils.make_label_clickable(
            self.widgets.splash_nspcuse,
            on_clicked_search,
            'species where not accessions = Empty'
        )

        utils.make_label_clickable(
            self.widgets.splash_nspcnot,
            on_clicked_search,
            'species where accessions = Empty'
        )

        utils.make_label_clickable(
            self.widgets.splash_nacctot,
            on_clicked_search,
            'accession like %'
        )

        utils.make_label_clickable(
            self.widgets.splash_naccuse,
            on_clicked_search,
            'accession where sum(plants.quantity)>0'
        )

        utils.make_label_clickable(
            self.widgets.splash_naccnot,
            on_clicked_search,
            'accession where plants = Empty or sum(plants.quantity)=0'
        )

        utils.make_label_clickable(
            self.widgets.splash_nplttot,
            on_clicked_search,
            'plant like %'
        )

        utils.make_label_clickable(
            self.widgets.splash_npltuse,
            on_clicked_search,
            'plant where sum(quantity)>0'
        )

        utils.make_label_clickable(
            self.widgets.splash_npltnot,
            on_clicked_search,
            'plant where sum(quantity)=0'
        )

        utils.make_label_clickable(
            self.widgets.splash_nloctot,
            on_clicked_search,
            'location like %'
        )

        utils.make_label_clickable(
            self.widgets.splash_nlocuse,
            on_clicked_search,
            'location where sum(plants.quantity)>0'
        )

        utils.make_label_clickable(
            self.widgets.splash_nlocnot,
            on_clicked_search,
            'location where plants is Empty or sum(plants.quantity)=0'
        )

        for i in range(1, 11):
            wname = "stqr_%02d_button" % i
            widget = getattr(self.widgets, wname)
            widget.connect('clicked', partial(self.on_sqb_clicked, i))
        wname = "splash_stqr_button"
        widget = getattr(self.widgets, wname)
        widget.connect('clicked', self.on_splash_stqr_button_clicked)

    def update(self):
        logger.debug('SplashInfoBox::update')
        statusbar = bauble.gui.widgets.statusbar
        sbcontext_id = statusbar.get_context_id('searchview.nresults')
        statusbar.pop(sbcontext_id)
        bauble.gui.widgets.main_comboentry.get_child().set_text('')

        session = db.Session()
        query = session.query(bauble.meta.BaubleMeta)
        query = query.filter(bauble.meta.BaubleMeta.name.startswith('stqr'))
        name_tooltip_query = dict(
            (int(i.name[5:]), (i.value.split(':', 2)))
            for i in query.all())
        session.close()

        for i in range(1, 11):
            wname = "stqr_%02d_button" % i
            widget = getattr(self.widgets, wname)
            name, tooltip, _query = name_tooltip_query.get(
                i, (_('<empty>'), '', ''))
            widget.set_label(name)
            widget.set_tooltip_text(tooltip)

        self.name_tooltip_query = name_tooltip_query

        # LabelUpdater objects **can** run in a thread.
        if 'GardenPlugin' in pluginmgr.plugins:
            self.start_thread(
                LabelUpdater(self.widgets.splash_nplttot,
                             "select count(*) from plant"))
            self.start_thread(
                LabelUpdater(self.widgets.splash_npltuse,
                             "select count(*) from plant where quantity>0"))
            self.start_thread(
                LabelUpdater(self.widgets.splash_npltnot,
                             "select count(*) from plant where quantity=0"))
            self.start_thread(
                LabelUpdater(self.widgets.splash_nacctot,
                             "select count(*) from accession"))
            self.start_thread(
                LabelUpdater(self.widgets.splash_naccuse,
                             "select count(distinct accession.id) "
                             "from accession "
                             "join plant on plant.accession_id=accession.id "
                             "where plant.quantity>0"))
            self.start_thread(
                LabelUpdater(self.widgets.splash_naccnot,
                             "select count(id) "
                             "from accession "
                             "where id not in "
                             "(select accession_id from plant "
                             " where plant.quantity>0)"))
            self.start_thread(
                LabelUpdater(self.widgets.splash_nloctot,
                             "select count(*) from location"))
            self.start_thread(
                LabelUpdater(self.widgets.splash_nlocuse,
                             "select count(distinct location.id) "
                             "from location "
                             "join plant on plant.location_id=location.id "
                             "where plant.quantity>0"))
            self.start_thread(
                LabelUpdater(self.widgets.splash_nlocnot,
                             "select count(id) "
                             "from location "
                             "where id not in "
                             "(select location_id from plant "
                             " where plant.quantity>0)"))

        self.start_thread(
            LabelUpdater(self.widgets.splash_nspcuse,
                         "select count(distinct species.id) "
                         "from species join accession "
                         "on accession.species_id=species.id"))
        self.start_thread(
            LabelUpdater(self.widgets.splash_ngenuse,
                         "select count(distinct species.genus_id) "
                         "from species join accession "
                         "on accession.species_id=species.id"))
        self.start_thread(
            LabelUpdater(self.widgets.splash_nfamuse,
                         "select count(distinct genus.family_id) from genus "
                         "join species on species.genus_id=genus.id "
                         "join accession on accession.species_id=species.id "))
        self.start_thread(
            LabelUpdater(self.widgets.splash_nspctot,
                         "select count(*) from species"))
        self.start_thread(
            LabelUpdater(self.widgets.splash_ngentot,
                         "select count(*) from genus"))
        self.start_thread(
            LabelUpdater(self.widgets.splash_nfamtot,
                         "select count(*) from family"))
        self.start_thread(
            LabelUpdater(self.widgets.splash_nspcnot,
                         "select count(id) from species "
                         "where id not in "
                         "(select distinct species.id "
                         " from species join accession "
                         " on accession.species_id=species.id)"))
        self.start_thread(
            LabelUpdater(self.widgets.splash_ngennot,
                         "select count(id) from genus "
                         "where id not in "
                         "(select distinct species.genus_id "
                         " from species join accession "
                         " on accession.species_id=species.id)"))
        self.start_thread(
            LabelUpdater(self.widgets.splash_nfamnot,
                         "select count(id) from family "
                         "where id not in "
                         "(select distinct genus.family_id from genus "
                         "join species on species.genus_id=genus.id "
                         "join accession on accession.species_id=species.id)"))

    def on_sqb_clicked(self, btn_no, _widget):
        query = self.name_tooltip_query[btn_no][2]
        bauble.gui.widgets.main_comboentry.get_child().set_text(query)
        bauble.gui.widgets.go_button.emit("clicked")

    @staticmethod
    def on_splash_stqr_button_clicked(_widget):
        from .stored_queries import edit_callback
        edit_callback()


class PlantsPlugin(pluginmgr.Plugin):
    tools = [TaxonomyCheckTool, StoredQueryEditorTool]
    provides = {'Family': Family,
                'FamilyNote': FamilyNote,
                'Genus': Genus,
                'GenusNote': GenusNote,
                'Species': Species,
                'SpeciesNote': SpeciesNote,
                'VernacularName': VernacularName,
                'Geography': Geography, }
    prefs_change_handler = None

    @classmethod
    def init(cls):

        if bauble.gui:
            return_accpt_chkbx = Gtk.CheckButton(label=_('Return accepted'))
            # set a name so its easy to find and remove
            return_accpt_chkbx.set_name('return_accpt_chkbx')

            # if reloading (opening a new connection etc.) remove any previous
            # return_accpt_chkbx
            for widget in bauble.gui.widgets.head_box.get_children():
                if widget.get_name() == 'return_accpt_chkbx':
                    bauble.gui.widgets.head_box.remove(widget)

            bauble.gui.widgets.head_box.pack_start(
                return_accpt_chkbx, False, True, 0)

            return_accpt_chkbx.set_active(
                prefs.prefs.get(return_accepted_pref, True))

            tooltip = _('For any taxonomic results: if a synonym also return '
                        'the accepted taxon (does not affect current results '
                        'only subsequent searches.)')
            return_accpt_chkbx.connect('toggled',
                                       cls.on_return_syns_chkbx_toggled)
            return_accpt_chkbx.set_tooltip_text(tooltip)
            return_accpt_chkbx.show()

            def prefs_ls_changed(model, path, _itr):
                key, _repr_str, _type_str = model[path]
                if key == return_accepted_pref:
                    return_accpt_chkbx.set_active(
                        prefs.prefs.get(return_accepted_pref))

            def on_view_box_added(_container, obj):
                if isinstance(obj, prefs.PrefsView):
                    if cls.prefs_change_handler:
                        obj.prefs_ls.disconnect(cls.prefs_change_handler)
                    cls.prefs_change_handler = obj.prefs_ls.connect(
                        'row-changed', prefs_ls_changed)

            bauble.gui.widgets.view_box.connect('set-focus-child',
                                                on_view_box_added)

        pluginmgr.provided.update(cls.provides)
        if 'GardenPlugin' in pluginmgr.plugins:
            if add_accession_action not in species_context_menu:
                species_context_menu.insert(1, add_accession_action)
            if add_accession_action not in vernname_context_menu:
                vernname_context_menu.insert(1, add_accession_action)

        mapper_search = search.get_strategy('MapperSearch')

        mapper_search.add_meta(('family', 'fam'), Family, ['family'])
        SearchView.row_meta[Family].set(children="genera",
                                        infobox=FamilyInfoBox,
                                        context_menu=family_context_menu)

        mapper_search.add_meta(('genus', 'gen'), Genus, ['genus'])
        SearchView.row_meta[Genus].set(children="species",
                                       infobox=GenusInfoBox,
                                       context_menu=genus_context_menu)

        search.add_strategy(SynonymSearch)
        mapper_search.add_meta(('species', 'sp'), Species,
                               ['sp', 'sp2', 'infrasp1', 'infrasp2',
                                'infrasp3', 'infrasp4'])
        SearchView.row_meta[Species].set(
            children=partial(db.natsort, 'accessions'),
            infobox=SpeciesInfoBox,
            context_menu=species_context_menu)

        mapper_search.add_meta(('vernacular', 'vern', 'common'),
                               VernacularName, ['name'])
        SearchView.row_meta[VernacularName].set(
            children=partial(db.natsort, 'species.accessions'),
            infobox=VernacularNameInfoBox,
            context_menu=vernname_context_menu)

        mapper_search.add_meta(('geography', 'geo'), Geography, ['name'])
        SearchView.row_meta[Geography].set(
            children=get_species_in_geography,
            infobox=GeographyInfoBox)

        # now it's the turn of the DefaultView
        logger.debug('PlantsPlugin::init, registering splash info box')
        DefaultView.infoboxclass = SplashInfoBox

        if bauble.gui is not None:
            bauble.gui.add_to_insert_menu(FamilyEditor, _('Family'))
            bauble.gui.add_to_insert_menu(GenusEditor, _('Genus'))
            bauble.gui.add_to_insert_menu(SpeciesEditorMenuItem, _('Species'))

    @staticmethod
    def on_return_syns_chkbx_toggled(widget):
        prefs.prefs[return_accepted_pref] = widget.get_active()
        if isinstance(view := bauble.gui.get_view(), prefs.PrefsView):
            view.update()

    @classmethod
    def install(cls, import_defaults=True):
        """
        Do any setup and configuration required by this plugin like
        creating tables, etc...
        """
        if not import_defaults:
            return
        path = os.path.join(lib_dir(), "plugins", "plants", "default")
        filenames = [os.path.join(path, f) for f in ('family.csv',
                                                     'family_synonym.csv',
                                                     'genus.csv',
                                                     'genus_synonym.csv',
                                                     'habit.csv')]

        # this should only occur first time around, not wipe out existing
        # data.  Or at least ask the user.
        with db.engine.connect() as con:
            try:
                fams = con.execute('SELECT COUNT(*) FROM family')
                fams = next(fams)[0]
            except Exception:  # pylint: disable=broad-except
                fams = 0
            try:
                gens = con.execute('SELECT COUNT(*) FROM genus')
                gens = next(gens)[0]
            except Exception:  # pylint: disable=broad-except
                gens = 0
            try:
                geos = con.execute('SELECT COUNT(*) FROM geography')
                geos = next(geos)[0]
            except Exception:  # pylint: disable=broad-except
                geos = 0
            if gens > 0 and fams > 0 and geos > 0:
                msg = _(f'You already seem to have approximately <b>{gens}</b>'
                        f' records in the genus table, <b>{fams}</b> in the '
                        f'family table and <b>{geos}</b> in geography table. '
                        '\n\n<b>Do you want to overwrite these tables and '
                        'their related synonym tables?</b>')
                if not utils.yes_no_dialog(msg, yes_delay=2):
                    return
        # pylint: disable=no-member
        geo_table = Geography.__table__
        depends = utils.find_dependent_tables(geo_table)

        try:
            logger.debug('dropping tables: %s', [i.name for i in depends])
            db.metadata.drop_all(tables=depends)
            logger.debug('dropping tables: %s', geo_table.name)
            geo_table.drop(db.engine)
        except Exception as e:  # pylint: disable=broad-except
            logger.debug("%s(%s)", type(e).__name__, e)

        logger.debug('creating tables: %s', [i.name for i in depends])
        geo_table.create(db.engine)

        db.metadata.create_all(tables=depends)
        logger.debug('creating tables: %s', geo_table.name)

        from .geography import geography_importer

        msg = _("importing WGSRPD (TDWG) geography table data")
        bauble.task.set_message(msg)
        bauble.task.queue(geography_importer())
        from bauble.plugins.imex.csv_ import CSVRestore
        csv = CSVRestore()
        csv.start(filenames, metadata=db.metadata, force=True)


plugin = PlantsPlugin
