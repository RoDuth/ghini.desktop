# Copyright 2008-2010 Brett Adams
# Copyright 2012-2015 Mario Frasca <mario@anche.no>.
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
plants plugin
"""

import os
from threading import Thread
from functools import partial
from pathlib import Path

import logging
logger = logging.getLogger(__name__)

from gi.repository import Gtk
from gi.repository import Gio
from gi.repository import GLib

import bauble
from bauble import prefs
from bauble import db
from bauble import search

from bauble.paths import lib_dir
from bauble import pluginmgr
from bauble import utils
from bauble.view import SearchView, HistoryView
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
                      SpeciesEditor,
                      SpeciesInfoBox,
                      SpeciesNote,
                      species_context_menu,
                      add_accession_action,
                      SynonymSearch,
                      SpeciesDistribution,
                      VernacularName,
                      VernacularNameInfoBox,
                      vernname_context_menu)
from .species_model import SpeciesPicture, update_all_full_names_handler
from .geography import (Geography,
                        get_species_in_geography,
                        GeographyInfoBox,
                        geography_context_menu)
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
        try:
            value = session.execute(self.query).first()[0]
            GLib.idle_add(self.widget.set_text, str(value))
        except SystemError:
            # tuple error should investigate further, seems specific to sqlite,
            # when using insert menu with splashscreen visible.  Possibly a
            # race condition?  Re running seems to always succeed second time
            # around.
            self.run()
        session.close()


@Gtk.Template(filename=str(Path(__file__).resolve().parent / 'splash_info.ui'))
class SplashInfoBox(pluginmgr.View, Gtk.Box):
    """info box shown in the initial splash screen."""

    __gtype_name__ = 'SplashInfoBox'

    splash_stqr_button = Gtk.Template.Child()
    splash_nlocnot = Gtk.Template.Child()
    splash_nlocuse = Gtk.Template.Child()
    splash_nloctot = Gtk.Template.Child()
    splash_npltnot = Gtk.Template.Child()
    splash_npltuse = Gtk.Template.Child()
    splash_nplttot = Gtk.Template.Child()
    splash_naccnot = Gtk.Template.Child()
    splash_naccuse = Gtk.Template.Child()
    splash_nacctot = Gtk.Template.Child()
    splash_nspcnot = Gtk.Template.Child()
    splash_nspcuse = Gtk.Template.Child()
    splash_nspctot = Gtk.Template.Child()
    splash_ngennot = Gtk.Template.Child()
    splash_ngenuse = Gtk.Template.Child()
    splash_ngentot = Gtk.Template.Child()
    splash_nfamtot = Gtk.Template.Child()
    splash_nfamuse = Gtk.Template.Child()
    splash_nfamnot = Gtk.Template.Child()

    for i in range(1, 11):
        wname = f"stqr_{i:02d}_button"
        locals()[wname] = Gtk.Template.Child()

    def __init__(self):
        logger.debug('SplashInfoBox::__init__')
        super().__init__()

        for i in range(1, 11):
            wname = f"stqr_{i:02d}_button"
            widget = getattr(self, wname)
            widget.connect('clicked', partial(self.on_sqb_clicked, i))

        self.name_tooltip_query = None

        on_clicked_search = utils.generate_on_clicked(bauble.gui.send_command)

        utils.make_label_clickable(
            self.splash_nfamtot,
            on_clicked_search,
            'family like %'
        )

        utils.make_label_clickable(
            self.splash_nfamuse,
            on_clicked_search,
            'family where genera.species.accessions.id != 0'
        )

        utils.make_label_clickable(
            self.splash_nfamnot,
            on_clicked_search,
            'family where not genera.species.accessions.id != 0'
        )

        utils.make_label_clickable(
            self.splash_ngentot,
            on_clicked_search,
            'genus like %'
        )

        utils.make_label_clickable(
            self.splash_ngenuse,
            on_clicked_search,
            'genus where species.accessions.id!=0'
        )

        utils.make_label_clickable(
            self.splash_ngennot,
            on_clicked_search,
            'genus where not species.accessions.id!=0'
        )

        utils.make_label_clickable(
            self.splash_nspctot,
            on_clicked_search,
            'species like %'
        )

        utils.make_label_clickable(
            self.splash_nspcuse,
            on_clicked_search,
            'species where not accessions = Empty'
        )

        utils.make_label_clickable(
            self.splash_nspcnot,
            on_clicked_search,
            'species where accessions = Empty'
        )

        utils.make_label_clickable(
            self.splash_nacctot,
            on_clicked_search,
            'accession like %'
        )

        utils.make_label_clickable(
            self.splash_naccuse,
            on_clicked_search,
            'accession where sum(plants.quantity)>0'
        )

        utils.make_label_clickable(
            self.splash_naccnot,
            on_clicked_search,
            'accession where plants = Empty or sum(plants.quantity)=0'
        )

        utils.make_label_clickable(
            self.splash_nplttot,
            on_clicked_search,
            'plant like %'
        )

        utils.make_label_clickable(
            self.splash_npltuse,
            on_clicked_search,
            'plant where sum(quantity)>0'
        )

        utils.make_label_clickable(
            self.splash_npltnot,
            on_clicked_search,
            'plant where sum(quantity)=0'
        )

        utils.make_label_clickable(
            self.splash_nloctot,
            on_clicked_search,
            'location like %'
        )

        utils.make_label_clickable(
            self.splash_nlocuse,
            on_clicked_search,
            'location where sum(plants.quantity)>0'
        )

        utils.make_label_clickable(
            self.splash_nlocnot,
            on_clicked_search,
            'location where plants is Empty or sum(plants.quantity)=0'
        )

        for i in range(1, 11):
            wname = f"stqr_{i:02d}_button"
            widget = getattr(self, wname)
            widget.connect('clicked', partial(self.on_sqb_clicked, i))

        self.splash_stqr_button.connect('clicked',
                                        self.on_splash_stqr_button_clicked)

    def update(self, *_args):
        # desensitise links that wont work.
        sensitive = not prefs.prefs.get(prefs.exclude_inactive_pref)
        for widget in [self.splash_nplttot,
                       self.splash_npltnot,
                       self.splash_nacctot,
                       self.splash_naccnot,
                       self.splash_nspctot,
                       self.splash_nspcnot]:
            widget.get_parent().set_sensitive(sensitive)

        logger.debug('SplashInfoBox::update')
        statusbar = bauble.gui.widgets.statusbar
        sbcontext_id = statusbar.get_context_id('searchview.nresults')
        statusbar.pop(sbcontext_id)
        bauble.gui.widgets.main_comboentry.get_child().set_text('')

        session = db.Session()
        query = (session.query(bauble.meta.BaubleMeta)
                 .filter(bauble.meta.BaubleMeta.name.startswith('stqr')))
        name_tooltip_query = dict(
            (int(i.name[5:]), (i.value.split(':', 2)))
            for i in query.all())
        session.close()

        for i in range(1, 11):
            wname = f"stqr_{i:02d}_button"
            widget = getattr(self, wname)
            name, tooltip, _query = name_tooltip_query.get(
                i, (_('<empty>'), '', '')
            )
            widget.set_label(name)
            widget.set_tooltip_text(tooltip)

        self.name_tooltip_query = name_tooltip_query

        # LabelUpdater objects **can** run in a thread.
        if 'GardenPlugin' in pluginmgr.plugins:
            self.start_thread(
                LabelUpdater(self.splash_nplttot,
                             "select count(*) from plant"))
            self.start_thread(
                LabelUpdater(self.splash_npltuse,
                             "select count(*) from plant where quantity>0"))
            self.start_thread(
                LabelUpdater(self.splash_npltnot,
                             "select count(*) from plant where quantity=0"))
            self.start_thread(
                LabelUpdater(self.splash_nacctot,
                             "select count(*) from accession"))
            self.start_thread(
                LabelUpdater(self.splash_naccuse,
                             "select count(distinct accession.id) "
                             "from accession "
                             "join plant on plant.accession_id=accession.id "
                             "where plant.quantity>0"))
            self.start_thread(
                LabelUpdater(self.splash_naccnot,
                             "select count(id) "
                             "from accession "
                             "where id not in "
                             "(select accession_id from plant "
                             " where plant.quantity>0)"))
            self.start_thread(
                LabelUpdater(self.splash_nloctot,
                             "select count(*) from location"))
            self.start_thread(
                LabelUpdater(self.splash_nlocuse,
                             "select count(distinct location.id) "
                             "from location "
                             "join plant on plant.location_id=location.id "
                             "where plant.quantity>0"))
            self.start_thread(
                LabelUpdater(self.splash_nlocnot,
                             "select count(id) "
                             "from location "
                             "where id not in "
                             "(select location_id from plant "
                             " where plant.quantity>0)"))

        self.start_thread(
            LabelUpdater(self.splash_nspcuse,
                         "select count(distinct species.id) "
                         "from species join accession "
                         "on accession.species_id=species.id"))
        self.start_thread(
            LabelUpdater(self.splash_ngenuse,
                         "select count(distinct species.genus_id) "
                         "from species join accession "
                         "on accession.species_id=species.id"))
        self.start_thread(
            LabelUpdater(self.splash_nfamuse,
                         "select count(distinct genus.family_id) from genus "
                         "join species on species.genus_id=genus.id "
                         "join accession on accession.species_id=species.id "))
        self.start_thread(
            LabelUpdater(self.splash_nspctot,
                         "select count(*) from species"))
        self.start_thread(
            LabelUpdater(self.splash_ngentot,
                         "select count(*) from genus"))
        self.start_thread(
            LabelUpdater(self.splash_nfamtot,
                         "select count(*) from family"))
        self.start_thread(
            LabelUpdater(self.splash_nspcnot,
                         "select count(id) from species "
                         "where id not in "
                         "(select distinct species.id "
                         " from species join accession "
                         " on accession.species_id=species.id)"))
        self.start_thread(
            LabelUpdater(self.splash_ngennot,
                         "select count(id) from genus "
                         "where id not in "
                         "(select distinct species.genus_id "
                         " from species join accession "
                         " on accession.species_id=species.id)"))
        self.start_thread(
            LabelUpdater(self.splash_nfamnot,
                         "select count(id) from family "
                         "where id not in "
                         "(select distinct genus.family_id from genus "
                         "join species on species.genus_id=genus.id "
                         "join accession on accession.species_id=species.id)"))

    def on_sqb_clicked(self, btn_no, _widget):
        query = self.name_tooltip_query.get(btn_no)
        if query:
            bauble.gui.widgets.main_comboentry.get_child().set_text(query[2])
            bauble.gui.widgets.go_button.emit("clicked")

    @staticmethod
    def on_splash_stqr_button_clicked(_widget):
        from .stored_queries import edit_callback
        edit_callback()


class PlantsPlugin(pluginmgr.Plugin):
    tools = [StoredQueryEditorTool]
    provides = {'Family': Family,
                'FamilyNote': FamilyNote,
                'Genus': Genus,
                'GenusNote': GenusNote,
                'Species': Species,
                'SpeciesNote': SpeciesNote,
                'SpeciesPicture': SpeciesPicture,
                'VernacularName': VernacularName,
                'Geography': Geography, }
    prefs_change_handler = None
    options_menu_set = False

    @classmethod
    def init(cls):

        if bauble.gui and not cls.options_menu_set:
            cls.options_menu_set = True
            accptd_action = Gio.SimpleAction.new_stateful(
                "accepted_toggled",
                None,
                GLib.Variant.new_boolean(prefs.prefs.get(
                    prefs.return_accepted_pref, True
                ))
            )
            accptd_action.connect("change-state",
                                  cls.on_return_syns_chkbx_toggled)
            bauble.gui.window.add_action(accptd_action)

            item = Gio.MenuItem.new(_('Return Accepted'),
                                    'win.accepted_toggled')
            bauble.gui.options_menu.append_item(item)

            bauble.gui.add_action("update_full_name",
                                  update_all_full_names_handler)

            item = Gio.MenuItem.new(_('Update All Species Full Names'),
                                    'win.update_full_name')
            bauble.gui.options_menu.append_item(item)

            def prefs_ls_changed(model, path, _itr):
                key, _repr_str, _type_str = model[path]
                if key == prefs.return_accepted_pref:
                    accptd_action.set_state(
                        GLib.Variant.new_boolean(
                            prefs.prefs.get(prefs.return_accepted_pref)
                        )
                    )

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

        SearchView.row_meta[Genus].set(children=partial(db.get_active_children,
                                                        'species'),
                                       infobox=GenusInfoBox,
                                       context_menu=genus_context_menu)

        search.add_strategy(SynonymSearch)
        mapper_search.add_meta(('species', 'sp'), Species,
                               ['sp', 'sp2', 'infrasp1', 'infrasp2',
                                'infrasp3', 'infrasp4'])
        # full_name search
        mapper_search.add_meta(('species_full_name', 'taxon'),
                               Species,
                               ['full_name'])
        SearchView.row_meta[Species].set(
            children=partial(db.get_active_children,
                             partial(db.natsort, 'accessions')),
            infobox=SpeciesInfoBox,
            context_menu=species_context_menu
        )

        mapper_search.add_meta(
            ('vernacular_name', 'vernacular', 'vern', 'common'),
            VernacularName, ['name']
        )
        SearchView.row_meta[VernacularName].set(
            children=partial(db.get_active_children,
                             partial(db.natsort, 'species.accessions')),
            infobox=VernacularNameInfoBox,
            context_menu=vernname_context_menu
        )

        mapper_search.add_meta(('geography', 'geo'), Geography, ['name'])
        SearchView.row_meta[Geography].set(
            children=partial(db.get_active_children, get_species_in_geography),
            infobox=GeographyInfoBox,
            context_menu=geography_context_menu
        )

        # now it's the turn of the DefaultView
        logger.debug('PlantsPlugin::init, registering splash info box')
        DefaultView.infoboxclass = SplashInfoBox

        if bauble.gui is not None:
            bauble.gui.add_to_insert_menu(FamilyEditor, _('Family'))
            bauble.gui.add_to_insert_menu(GenusEditor, _('Genus'))
            bauble.gui.add_to_insert_menu(SpeciesEditor, _('Species'))

        note_query = '{table} where notes.id = {obj_id}'
        HistoryView.add_translation_query('family_note', 'family', note_query)
        HistoryView.add_translation_query('genus_note', 'genus', note_query)
        HistoryView.add_translation_query('species_note', 'species',
                                          note_query)
        pic_query = '{table} where pictures.id = {obj_id}'
        HistoryView.add_translation_query('species_picture', 'species',
                                          pic_query)
        syn_query = '{table} where _synonyms.id = {obj_id}'
        HistoryView.add_translation_query('family_synonym', 'family',
                                          syn_query)
        HistoryView.add_translation_query('genus_synonym', 'genus', syn_query)
        HistoryView.add_translation_query('species_synonym', 'species',
                                          syn_query)

        HistoryView.add_translation_query(
            'default_vernacular_name',
            'species',
            '{table} where _default_vernacular_name.id = {obj_id}'
        )

        HistoryView.add_translation_query(
            'species_distribution',
            'species',
            '{table} where distribution.id = {obj_id}'
        )

    @staticmethod
    def on_return_syns_chkbx_toggled(action, value):
        action.set_state(value)

        prefs.prefs[prefs.return_accepted_pref] = value.get_boolean()
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
