# Copyright 2008-2010 Brett Adams
# Copyright 2015 Mario Frasca <mario@anche.no>.
# Copyright 2017 Jardín Botánico de Quito
# Copyright 2020-2022 Ross Demuth <rossdemuth123@gmail.com>
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
The garden plugin
"""

import re
import logging
from random import random
logger = logging.getLogger(__name__)

from sqlalchemy.orm import object_session, eagerload

from gi.repository import Gtk

import bauble

from bauble import utils
from bauble import db
from bauble import pluginmgr
from bauble.view import SearchView, HistoryView
from bauble import search
from .accession import (AccessionEditor,
                        Accession,
                        AccessionInfoBox,
                        AccessionNote,
                        acc_context_menu,
                        BAUBLE_ACC_CODE_FORMAT)
from .location import (LocationEditor,
                       Location,
                       LocationNote,
                       LocationInfoBox,
                       loc_context_menu)
from .plant import (PlantEditor,
                    PlantNote,
                    PlantPicture,
                    Plant,
                    PlantSearch,
                    PlantInfoBox,
                    plant_context_menu,
                    plant_delimiter_key,
                    default_plant_delimiter)
from .source import (Source,
                     create_source_detail,
                     SourceDetail,
                     SourceDetailInfoBox,
                     source_detail_context_menu,
                     Collection,
                     collection_context_menu,
                     collection_context_menu_callback)
from .institution import (Institution,
                          InstitutionCommand,
                          InstitutionTool,
                          start_institution_editor)

# other ideas:
# - cultivation table
# - conservation table


def get_plant_completions(session, text):
    """Get completions for plants.  For use in simple search"""
    from sqlalchemy import and_
    acc_code = text
    plant_code = ''
    delimiter = Plant.get_delimiter()
    if delimiter in text:
        acc_code, plant_code = text.rsplit(delimiter, 1)
    vals = []
    qry = (session.query(Plant)
           .join(Accession)
           .filter(utils.ilike(Accession.code, f'{text}%%')))
    vals = [str(val) for val in qry.limit(10)]
    qry = (session.query(Plant)
           .join(Accession)
           .filter(and_(utils.ilike(Plant.code, f'{plant_code}%%'),
                        utils.ilike(Accession.code, f'{acc_code}%%'))))
    vals += [str(val) for val in qry.limit(10)]
    return set(vals)


class GardenPlugin(pluginmgr.Plugin):

    depends = ["PlantsPlugin"]
    tools = [InstitutionTool]
    commands = [InstitutionCommand]
    provides = {'Accession': Accession,
                'AccessionNote': AccessionNote,
                'Location': Location,
                'LocationNote': LocationNote,
                'Plant': Plant,
                'PlantNote': PlantNote,
                'PlantPicture': PlantPicture,
                'Source': Source,
                'SourceDetail': SourceDetail,
                'Collection': Collection}

    @classmethod
    def install(cls, *args, **kwargs):
        pass

    @classmethod
    def init(cls):
        pluginmgr.provided.update(cls.provides)
        from bauble.plugins.plants import Species
        mapper_search = search.get_strategy('MapperSearch')

        from functools import partial
        mapper_search.add_meta(('accession', 'acc'), Accession, ['code'])
        SearchView.row_meta[Accession].set(
            children=partial(db.natsort, "plants"),
            infobox=AccessionInfoBox,
            context_menu=acc_context_menu)

        mapper_search.add_meta(('location', 'loc'), Location, ['name', 'code'])
        SearchView.row_meta[Location].set(
            children=partial(db.natsort, 'plants'),
            infobox=LocationInfoBox,
            context_menu=loc_context_menu)

        mapper_search.add_meta(('plant', 'planting'), Plant, ['code'])
        # special search value strategy
        search.add_strategy(PlantSearch)

        mapper_search.completion_funcs['plant'] = get_plant_completions

        SearchView.row_meta[Plant].set(
            infobox=PlantInfoBox,
            context_menu=plant_context_menu)

        mapper_search.add_meta(('source_detail', 'source', 'contact'),
                               SourceDetail, ['name'])

        def sd_kids(detail):
            session = object_session(detail)
            results = (session.query(Accession)
                       .join(Source)
                       .join(SourceDetail)
                       .options(eagerload('species'))
                       .filter(SourceDetail.id == detail.id)
                       .all())
            return results

        SearchView.row_meta[SourceDetail].set(
            children=sd_kids,
            infobox=SourceDetailInfoBox,
            context_menu=source_detail_context_menu)

        mapper_search.add_meta(('collection', 'col', 'coll'),
                               Collection, ['locale'])

        def coll_kids(coll):
            return sorted(coll.source.accession.plants, key=utils.natsort_key)

        SearchView.row_meta[Collection].set(
            children=coll_kids,
            infobox=AccessionInfoBox,
            context_menu=collection_context_menu)

        # done here b/c the Species table is not part of this plugin
        SearchView.row_meta[Species].child = "accessions"

        if bauble.gui is not None:
            bauble.gui.add_to_insert_menu(AccessionEditor, _('Accession'))
            bauble.gui.add_to_insert_menu(PlantEditor, _('Planting'))
            bauble.gui.add_to_insert_menu(LocationEditor, _('Location'))
            bauble.gui.add_to_insert_menu(create_source_detail, _('Source'))

        # if the plant delimiter isn't in the bauble meta then add the default
        from bauble import meta
        meta.get_default(plant_delimiter_key, default_plant_delimiter)

        def get_default_acc_code_format():
            query = (db.Session().query(meta.BaubleMeta)
                     .filter(meta.BaubleMeta.name.like('acidf_%'))
                     .order_by(meta.BaubleMeta.name))
            return query.first()

        Accession.code_format = (get_default_acc_code_format() or
                                 BAUBLE_ACC_CODE_FORMAT)

        institution = Institution()
        if bauble.gui is not None and not institution.name:
            start_institution_editor()

        SearchView.context_menu_callbacks.add(collection_context_menu_callback)

        note_query = '{table} where notes.id = {obj_id}'
        HistoryView.add_translation_query('accession_note', 'accession',
                                          note_query)
        HistoryView.add_translation_query('plant_note', 'plant', note_query)
        HistoryView.add_translation_query('location_note', 'location',
                                          note_query)

        HistoryView.add_translation_query('source', 'accession',
                                          '{table} where source.id = {obj_id}')

        HistoryView.add_translation_query(
            'verification',
            'accession',
            '{table} where verifications.id = {obj_id}'
        )

        HistoryView.add_translation_query(
            'plant_change',
            'plant',
            '{table} where changes.id = {obj_id}'
        )

        # These are a little rough, only getting to accessions that have used
        # them as a source.
        HistoryView.add_translation_query(
            'propagation',
            'accession',
            ('{table} where source.plant_propagation.id = {obj_id} or '
             'source.propagation.id = {obj_id}')
        )
        HistoryView.add_translation_query(
            'prop_seed',
            'accession',
            ('{table} where source.plant_propagation._seed.id = {obj_id} or '
             'source.propagation._seed.id = {obj_id}')
        )
        HistoryView.add_translation_query(
            'prop_cutting',
            'accession',
            ('{table} where source.plant_propagation._cutting.id = {obj_id} '
             'or source.propagation._cutting.id = {obj_id}')
        )
        HistoryView.add_translation_query(
            'prop_cutting',
            'accession',
            ('{table} where source.plant_propagation._cutting.id = {obj_id} '
             'or source.propagation._cutting.id = {obj_id}')
        )
        HistoryView.add_translation_query(
            'prop_cutting_rooted',
            'accession',
            ('{table} where source.plant_propagation._cutting.rooted.id = '
             '{obj_id} or source.propagation._cutting.rooted.id = {obj_id}')
        )


def init_location_comboentry(presenter, combo, on_select, required=True):
    """A comboentry that allows the location to be entered.

    Requires more custom setup than view.attach_completion and
    self.assign_simple_handler can provides.

    This method allows us to have completions on the location entry based on
    the location code, location name and location string as well as selecting a
    location from a combo drop down.

    :param presenter: instance of GenericEditorPresenter
    :param combo: a Gtk.ComboBox widget with a Gtk.Entry
    :param on_select: a one-parameter function
    """
    # not a constant here but named so for consistency
    PROBLEM = f'unknown_location:{random()}'  # pylint: disable=invalid-name

    re_code_name_splitter = re.compile(r'\(([^)]+)\) ?(.*)')

    def cell_data_func(_col, cell, model, treeiter):
        val = model[treeiter][0]
        from sqlalchemy import inspect as sa_inspect
        if isinstance(val, str) or sa_inspect(val).persistent:
            cell.props.text = str(val)

    completion = Gtk.EntryCompletion()
    cell = Gtk.CellRendererText()  # set up the completion renderer
    completion.pack_start(cell, True)
    completion.set_cell_data_func(cell, cell_data_func)
    completion.props.popup_set_width = False

    entry = combo.get_child()
    entry.set_completion(completion)

    combo.clear()
    cell = Gtk.CellRendererText()
    combo.pack_start(cell, True)
    combo.set_cell_data_func(cell, cell_data_func)

    model = Gtk.ListStore(object)
    locations = [''] + sorted(presenter.session.query(Location).all(),
                              key=lambda loc: utils.natsort_key(loc.code))
    for loc in locations:
        model.append([loc])
    combo.set_model(model)
    completion.set_model(model)

    def match_func(completion, key, treeiter):
        loc = completion.get_model()[treeiter][0]
        # skip the first blank ('') row
        if loc == '':
            return False
        return ((loc.name and loc.name.lower().startswith(key.lower())) or
                (loc.code and loc.code.lower().startswith(key.lower())))
    completion.set_match_func(match_func)

    def on_match_select(_completion, model, treeiter):
        logger.debug('on_match_select')
        value = model[treeiter][0]
        on_select(value)
        entry.props.text = str(value)
        presenter.remove_problem(PROBLEM, entry)
        presenter.refresh_sensitivity()
        return True

    presenter.view.connect(completion, 'match-selected', on_match_select)

    def on_entry_changed(entry, presenter):
        logger.debug('on_entry_changed(%s, %s)', entry, presenter)
        text = str(entry.props.text)

        if not text and not required:
            presenter.remove_problem(PROBLEM, entry)
            on_select(None)
            return None
        # see if the text matches a completion string
        comp = entry.get_completion()
        compl_model = comp.get_model()

        def _cmp(row, data):
            return str(row[0]) == data

        found = utils.search_tree_model(compl_model, text, _cmp)
        if len(found) == 1:
            comp.emit('match-selected', compl_model, found[0])
            return True
        # if text looks like '(code) name', then split it into the two
        # parts, then see if the text matches exactly a code or name
        match = re_code_name_splitter.match(text)
        if match:
            code, name = match.groups()
        else:
            code = name = text
        codes = (presenter.session.query(Location)
                 .filter(utils.ilike(Location.code, code)))
        names = (presenter.session.query(Location)
                 .filter(utils.ilike(Location.name, name)))
        if codes.count() == 1:
            logger.debug('location matches code')
            location = codes.first()
            presenter.remove_problem(PROBLEM, entry)
            on_select(location)
        elif names.count() == 1:
            logger.debug('location matches name')
            location = names.first()
            presenter.remove_problem(PROBLEM, entry)
            on_select(location)
        else:
            logger.debug('location %s does not match anything', text)
            presenter.add_problem(PROBLEM, entry)
        return True

    presenter.view.connect(entry, 'changed', on_entry_changed, presenter)

    def on_combo_changed(combo, *_args):
        # model = combo.get_model()
        active = combo.get_active_iter()
        if not active:
            return
        location = combo.get_model()[active][0]
        combo.get_child().set_text(str(location))

    presenter.view.connect(combo, 'changed', on_combo_changed)

    presenter.view.connect(combo, 'format-entry-text',
                           utils.format_combo_entry_text)


plugin = GardenPlugin

# make names visible to db module
db.Accession = Accession
db.AccessionNote = AccessionNote
db.Plant = Plant
db.PlantNote = PlantNote
db.PlantPicture = PlantPicture
db.Location = Location
db.LocationNote = LocationNote
