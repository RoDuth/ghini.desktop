# Copyright 2008-2010 Brett Adams
# Copyright 2015-2016 Mario Frasca <mario@anche.no>.
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
Source and associated tables, etc.
"""
import os
import traceback
import weakref
from random import random

import logging
logger = logging.getLogger(__name__)

from gi.repository import Gtk

from sqlalchemy import (Column,
                        Unicode,
                        Integer,
                        ForeignKey,
                        Float,
                        UnicodeText)
from sqlalchemy.orm import relationship, backref
from sqlalchemy.orm.session import object_session

from bauble import db
from bauble import editor
from bauble import utils
from bauble import btypes as types
from bauble import paths
from bauble import prefs
from bauble.view import Action, InfoExpander, InfoBox, PropertiesExpander
from ..plants.geography import Geography, GeographyMenu


def collection_edit_callback(coll):
    from bauble.plugins.garden.accession import edit_callback
    # TODO: set the tab to the source tab on the accession editor
    return edit_callback([coll[0].source.accession])


def collection_add_plants_callback(coll):
    from bauble.plugins.garden.accession import add_plants_callback
    return add_plants_callback([coll[0].source.accession])


def collection_remove_callback(coll):
    from bauble.plugins.garden.accession import remove_callback
    return remove_callback([coll[0].source.accession])


collection_edit_action = Action('collection_edit', _('_Edit'),
                                callback=collection_edit_callback,
                                accelerator='<ctrl>e')

collection_add_plant_action = Action('collection_add', _('_Add plants'),
                                     callback=collection_add_plants_callback,
                                     accelerator='<ctrl>k')

collection_remove_action = Action('collection_remove', _('_Delete'),
                                  callback=collection_remove_callback,
                                  accelerator='<ctrl>Delete')

collection_context_menu = [collection_edit_action, collection_add_plant_action,
                           collection_remove_action]


class Source(db.Base):
    """connected 1-1 to Accession.

    Source objects have the function to add fields to one Accession.  From
    an Accession, to access the fields added here you obviously still need
    to go through its `.source` member.

    Create an Accession a, then create a Source s, then assign a.source = s
    """
    __tablename__ = 'source'
    # ITF2 - E7 - Donor's Accession Identifier - donacc
    sources_code = Column(Unicode(32))

    accession_id = Column(Integer, ForeignKey('accession.id'), nullable=False,
                          unique=True)
    accession = relationship('Accession', uselist=False,
                             back_populates='source')

    source_detail_id = Column(Integer, ForeignKey('source_detail.id'))
    source_detail = relationship('SourceDetail', uselist=False,
                                 backref=backref('sources',
                                                 cascade='all, delete-orphan'))

    collection = relationship('Collection',
                              uselist=False,
                              cascade='all, delete-orphan',
                              back_populates='source')

    # relation to a propagation that is specific to this Source and
    # not attached to a Plant
    # i.e. a Propagation of source material (i.e. purchased seeds etc.)
    propagation_id = Column(Integer, ForeignKey('propagation.id'))
    propagation = relationship(
        'Propagation', uselist=False, single_parent=True,
        primaryjoin='Source.propagation_id==Propagation.id',
        cascade='all, delete-orphan',
        backref=backref('source', uselist=False))

    # relation to a Propagation that already exists and is attached
    # to a Plant
    # i.e. a plant is propagation from to create a new accession
    plant_propagation_id = Column(Integer, ForeignKey('propagation.id'))
    plant_propagation = relationship(
        'Propagation', uselist=False,
        primaryjoin='Source.plant_propagation_id==Propagation.id',
        backref=backref('used_source', uselist=True))


source_type_values = [('Expedition', _('Expedition')),
                      ('GeneBank', _('Gene Bank')),
                      ('BG', _('Botanic Garden or Arboretum')),
                      ('Research/FieldStation', _('Research/Field Station')),
                      ('Staff', _('Staff member')),
                      ('UniversityDepartment', _('University Department')),
                      ('Club', _('Horticultural Association/Garden Club')),
                      ('MunicipalDepartment', _('Municipal department')),
                      ('Commercial', _('Nursery/Commercial')),
                      ('Individual', _('Individual')),
                      ('Other', _('Other')),
                      ('Unknown', _('Unknown')),
                      (None, '')]


# TODO: should have a label next to lat/lon entry to show what value will be
# stored in the database, might be good to include both DMS and the float
# so the user can see both no matter what is in the entry. it could change in
# time as the user enters data in the entry
# TODO: shouldn't allow entering altitude accuracy without entering altitude,
# same for geographic accuracy
# TODO: should show an error if something other than a number is entered in
# the altitude entry

# TODO: should provide a collection type: alcohol, bark, boxed,
# cytological, fruit, illustration, image, other, packet, pollen,
# print, reference, seed, sheet, slide, transparency, vertical,
# wood.....see HISPID standard, in general need to be more herbarium
# aware

# TODO: create a DMS column type to hold latitude and longitude,
# should probably store the DMS data as a string in decimal degrees

class Collection(db.Base):
    """
    :Table name: collection

    :Columns:
            *collector*: :class:`sqlalchemy.types.Unicode`

            *collectors_code*: :class:`sqlalchemy.types.Unicode`

            *date*: :class:`sqlalchemy.types.Date`

            *locale*: :class:`sqlalchemy.types.UnicodeText`

            *latitude*: :class:`sqlalchemy.types.Float`

            *longitude*: :class:`sqlalchemy.types.Float`

            *gps_datum*: :class:`sqlalchemy.types.Unicode`

            *geo_accy*: :class:`sqlalchemy.types.Float`

            *elevation*: :class:`sqlalchemy.types.Float`

            *elevation_accy*: :class:`sqlalchemy.types.Float`

            *habitat*: :class:`sqlalchemy.types.UnicodeText`

            *geography_id*: :class:`sqlalchemy.types.Integer`

            *notes*: :class:`sqlalchemy.types.UnicodeText`


    :Properties:


    :Constraints:
    """
    __tablename__ = 'collection'

    # columns
    # ITF2 - F24 - Primary Collector's Name
    collector = Column(Unicode(64))
    # ITF2 - F.25 - Collector's Identifier
    collectors_code = Column(Unicode(50))
    # ITF2 - F.27 - Collection Date
    date = Column(types.Date)
    locale = Column(UnicodeText, nullable=False)
    # ITF2 - F1, F2, F3, F4 - Latitude, Degrees, Minutes, Seconds, Direction
    latitude = Column(Unicode(15))
    # ITF2 - F5, F6, F7, F8 - Longitude, Degrees, Minutes, Seconds, Direction
    longitude = Column(Unicode(15))
    gps_datum = Column(Unicode(32))
    # ITF2 - F9 - Accuracy of Geographical Referencing Data
    geo_accy = Column(Float)
    # ITF2 - F17 - Altitude
    elevation = Column(Float)
    # ITF2 - F18 - Accuracy of Altitude
    elevation_accy = Column(Float)
    # ITF2 - F22 - Habitat
    habitat = Column(UnicodeText)
    # ITF2 - F18 - Collection Notes
    notes = Column(UnicodeText)

    geography_id = Column(Integer, ForeignKey('geography.id'))
    # use backref here or can lead to InvalidRequestError (Collection unknown
    # in Geography) particularly in view.multiproc_counter
    # region = relationship('Geography', uselist=False,
    #                       back_populates='collection')
    region = relationship(Geography, uselist=False,
                          backref=backref('collection', uselist=True))

    source_id = Column(Integer, ForeignKey('source.id'), unique=True)
    source = relationship('Source',
                          back_populates='collection')

    retrieve_cols = ['id', 'source', 'collectors_code', 'collector', 'date',
                     'source.accession.code', 'source.accession']

    @classmethod
    def retrieve(cls, session, keys):
        parts = ['id', 'source', 'collectors_code', 'collector', 'date']
        col_parts = {k: v for k, v in keys.items() if k in parts}
        acc = keys.get('source.accession.code') or keys.get('source.accession')
        acc_key = {}
        if acc:
            acc_key['code'] = acc
        retrieved_acc = None
        query = session.query(cls)
        if col_parts:
            query = query.filter_by(**col_parts)
        if acc_key:
            from .accession import Accession
            retrieved_acc = Accession.retrieve(session, acc_key)
            if not retrieved_acc:
                return None
            query = (query.join(Source, Accession)
                     .filter(Accession.id == retrieved_acc.id))
        if col_parts or acc_key:
            from sqlalchemy.orm.exc import MultipleResultsFound
            try:
                return query.one_or_none()
            except MultipleResultsFound:
                return None
        return None

    def search_view_markup_pair(self):
        """provide the two lines describing object for SearchView row."""
        acc = self.source.accession  # pylint: disable=no-member
        safe = utils.xml_safe
        return (f'{safe(acc)} - <small>{safe(acc.species_str())}</small>',
                safe(self))

    def __str__(self):
        return _('Collection at %s') % (self.locale or repr(self))

    def has_children(self):
        # more expensive than other models (loads full accession query)
        return self.source.accession.has_children()


class CollectionPresenter(editor.ChildPresenter):

    """CollectionPresenter

    :param parent: an AccessionEditorPresenter
    :param model: a Collection instance
    :param view: an AccessionEditorView
    :param session: a sqlalchemy.orm.session
    """
    widget_to_field_map = {'collector_entry': 'collector',
                           'coll_date_entry': 'date',
                           'collid_entry': 'collectors_code',
                           'locale_entry': 'locale',
                           'lat_entry': 'latitude',
                           'lon_entry': 'longitude',
                           'geoacc_entry': 'geo_accy',
                           'alt_entry': 'elevation',
                           'altacc_entry': 'elevation_accy',
                           'habitat_textview': 'habitat',
                           'coll_notes_textview': 'notes',
                           'datum_entry': 'gps_datum',
                           'add_region_button': 'region',
                           }

    PROBLEM_BAD_LATITUDE = f'bad_latitude:{random()}'
    PROBLEM_BAD_LONGITUDE = f'bad_longitude:{random()}'
    PROBLEM_INVALID_LOCALE = f'invalid_locale:{random()}'

    def __init__(self, parent, model, view, session):
        super().__init__(model, view, session=session)
        self.parent_ref = weakref.ref(parent)
        self.session = session
        self.refresh_view()
        self.geo_menu = None

        self.assign_simple_handler('collector_entry', 'collector',
                                   editor.StringOrNoneValidator())
        self.assign_simple_handler('locale_entry', 'locale',
                                   editor.StringOrNoneValidator())
        self.assign_simple_handler('collid_entry', 'collectors_code',
                                   editor.StringOrNoneValidator())
        self.assign_simple_handler('geoacc_entry', 'geo_accy',
                                   editor.IntOrNoneStringValidator())
        self.assign_simple_handler('alt_entry', 'elevation',
                                   editor.FloatOrNoneStringValidator())
        self.assign_simple_handler('altacc_entry', 'elevation_accy',
                                   editor.FloatOrNoneStringValidator())
        self.assign_simple_handler('habitat_textview', 'habitat',
                                   editor.StringOrNoneValidator())
        self.assign_simple_handler('coll_notes_textview', 'notes',
                                   editor.StringOrNoneValidator())
        # the list of completions are added in AccessionEditorView.__init__

        def on_match(completion, model, itr):
            value = model[itr][0]
            validator = editor.StringOrNoneValidator()
            self.set_model_attr('gps_data', value, validator)
            completion.get_entry().set_text(value)

        completion = self.view.widgets.datum_entry.get_completion()
        self.view.connect(completion, 'match-selected', on_match)
        self.assign_simple_handler('datum_entry', 'gps_datum',
                                   editor.StringOrNoneValidator())

        self.view.connect('lat_entry', 'changed', self.on_lat_entry_changed)
        self.view.connect('lon_entry', 'changed', self.on_lon_entry_changed)

        self.view.connect('coll_date_entry', 'changed',
                          self.on_date_entry_changed, (self.model, 'date'))

        utils.setup_date_button(view, 'coll_date_entry',
                                'coll_date_button')

        # don't need to connection to south/west since they are in the same
        # groups as north/east
        self.north_toggle_signal_id = self.view.connect(
            'north_radio', 'toggled', self.on_north_south_radio_toggled)
        self.east_toggle_signal_id = self.view.connect(
            'east_radio', 'toggled', self.on_east_west_radio_toggled)

        self.view.widgets.add_region_button.set_sensitive(False)

        def on_add_button_pressed(_widget, event):
            self.geo_menu.popup_at_pointer(event)

        self.view.connect('add_region_button', 'button-press-event',
                          on_add_button_pressed)

        add_button = self.view.widgets.add_region_button
        self.geo_menu = GeographyMenu.new_menu(self.set_region, add_button)
        self.geo_menu.attach_to_widget(add_button, None)
        add_button.set_sensitive(True)

        self._dirty = False

    def set_region(self, _action, geo_id):
        geo_id = int(geo_id.unpack())
        geography = self.session.query(Geography).get(geo_id)
        self.set_model_attr('region', geography)
        self.view.widgets.add_region_button.props.label = str(geography)

    def set_model_attr(self, attr, value, validator=None):
        """Validates the fields when a attr changes."""
        super().set_model_attr(attr, value, validator)
        self._dirty = True
        if self.model.locale is None or self.model.locale in ('', ''):
            self.add_problem(self.PROBLEM_INVALID_LOCALE, 'locale_entry')
        else:
            self.remove_problem(self.PROBLEM_INVALID_LOCALE, 'locale_entry')

        if attr in ('longitude', 'latitude'):
            sensitive = (self.model.latitude is not None and
                         self.model.longitude is not None)
            self.view.widgets.geoacc_entry.set_sensitive(sensitive)
            self.view.widgets.datum_entry.set_sensitive(sensitive)

        if attr == 'elevation':
            sensitive = self.model.elevation is not None
            self.view.widgets.altacc_entry.set_sensitive(sensitive)

        self.parent_ref().refresh_sensitivity()

    def start(self):
        raise Exception('CollectionPresenter cannot be started')

    def is_dirty(self):
        return self._dirty

    def refresh_view(self):
        from .accession import latitude_to_dms, longitude_to_dms
        for widget, field in self.widget_to_field_map.items():
            value = getattr(self.model, field)
            logger.debug('%s, %s, %s', widget, field, value)
            self.view.widget_set_value(widget, value)

        latitude = self.model.latitude
        if latitude is not None:
            direct, degs, mins, secs = latitude_to_dms(latitude)
            dms_string = f'{direct} {degs}°{mins}\'{secs}"'
            self.view.widgets.lat_dms_label.set_text(dms_string)
            if float(latitude) < 0:
                self.view.widgets.south_radio.set_active(True)
            else:
                self.view.widgets.north_radio.set_active(True)
        else:
            self.view.widgets.lat_dms_label.set_text('')
            self.view.widgets.north_radio.set_active(True)

        longitude = self.model.longitude
        if longitude is not None:
            direct, degs, mins, secs = longitude_to_dms(longitude)
            dms_string = f'{direct} {degs}°{mins}\'{secs}"'
            self.view.widgets.lon_dms_label.set_text(dms_string)
            if float(longitude) < 0:
                self.view.widgets.west_radio.set_active(True)
            else:
                self.view.widgets.east_radio.set_active(True)
        else:
            self.view.widgets.lon_dms_label.set_text('')
            self.view.widgets.east_radio.set_active(True)

        if self.model.elevation is None:
            self.view.widgets.altacc_entry.set_sensitive(False)

        if self.model.latitude is None or self.model.longitude is None:
            self.view.widgets.geoacc_entry.set_sensitive(False)
            self.view.widgets.datum_entry.set_sensitive(False)

    def on_east_west_radio_toggled(self, _widget):
        direction = self._get_lon_direction()
        entry = self.view.widgets.lon_entry
        lon_text = entry.get_text()
        if lon_text == '':
            return

        try:
            # make sure that the first part of the string is a number before
            # toggling
            float(lon_text.split(' ')[0])
        except TypeError as e:
            logger.debug("%s(%s)", type(e), e)
            return

        if direction == 'W' and lon_text[0] != '-':
            entry.set_text(f'-{lon_text}')
        elif direction == 'E' and lon_text[0] == '-':
            entry.set_text(lon_text[1:])

    def on_north_south_radio_toggled(self, _widget):
        direction = self._get_lat_direction()
        entry = self.view.widgets.lat_entry
        lat_text = entry.get_text()
        if lat_text == '':
            return

        try:
            # make sure that the first part of the string is a number before
            # toggling
            float(lat_text.split(' ')[0])
        except TypeError as e:
            logger.debug("%s(%s)", type(e).__name__, e)
            return

        if direction == 'S' and lat_text[0] != '-':
            entry.set_text(f'-{lat_text}')
        elif direction == 'N' and lat_text[0] == '-':
            entry.set_text(lat_text[1:])

    @staticmethod
    def _parse_lat_lon(direction, text):
        """Parse a latitude or longitude in a variety of formats and return a
        degress decimal
        """

        import re
        from decimal import Decimal
        from bauble.plugins.garden.accession import dms_to_decimal
        parts = re.split(':| ', text.strip())
        if len(parts) == 1:
            dec = Decimal(text).copy_abs()
            if dec > 0 and direction in ('W', 'S'):
                dec = -dec
        elif len(parts) == 2:
            degs = Decimal(parts[0])
            mins = Decimal(parts[1])
            dec = dms_to_decimal(direction, degs, mins, 0)
        elif len(parts) == 3:
            dec = dms_to_decimal(direction, *[Decimal(i) for i in parts])
        else:
            raise ValueError(_('_parse_lat_lon() -- incorrect format: %s') %
                             text)
        return dec

    def _get_lat_direction(self):
        """return N or S from the radio"""
        if self.view.widgets.north_radio.get_active():
            return 'N'
        if self.view.widgets.south_radio.get_active():
            return 'S'
        raise ValueError(_('North/South radio buttons in a confused state'))

    def _get_lon_direction(self):
        """return E or W from the radio"""
        if self.view.widgets.east_radio.get_active():
            return 'E'
        if self.view.widgets.west_radio.get_active():
            return 'W'
        raise ValueError(_('East/West radio buttons in a confused state'))

    def on_lat_entry_changed(self, entry):
        """set the latitude value from text"""
        from .accession import latitude_to_dms
        text = entry.get_text()
        latitude = None
        dms_string = ''
        try:
            if text != '' and text is not None:
                north_radio = self.view.widgets.north_radio
                north_radio.handler_block(self.north_toggle_signal_id)
                if text[0] == '-':
                    self.view.widgets.south_radio.set_active(True)
                else:
                    north_radio.set_active(True)
                north_radio.handler_unblock(self.north_toggle_signal_id)
                direction = self._get_lat_direction()
                latitude = CollectionPresenter._parse_lat_lon(direction, text)
                direct, degs, mins, secs = latitude_to_dms(latitude)
                dms_string = f'{direct} {degs}°{mins}\'{secs}"'
        except Exception:
            logger.debug(traceback.format_exc())
            self.add_problem(self.PROBLEM_BAD_LATITUDE,
                             self.view.widgets.lat_entry)
        else:
            self.remove_problem(self.PROBLEM_BAD_LATITUDE,
                                self.view.widgets.lat_entry)

        self.view.widgets.lat_dms_label.set_text(dms_string)
        if text is None or text.strip() == '':
            self.set_model_attr('latitude', None)
        else:
            self.set_model_attr('latitude', utils.nstr(latitude))

    def on_lon_entry_changed(self, entry):
        from .accession import longitude_to_dms
        text = entry.get_text()
        longitude = None
        dms_string = ''
        try:
            if text != '' and text is not None:
                east_radio = self.view.widgets.east_radio
                east_radio.handler_block(self.east_toggle_signal_id)
                if text[0] == '-':
                    self.view.widgets.west_radio.set_active(True)
                else:
                    self.view.widgets.east_radio.set_active(True)
                east_radio.handler_unblock(self.east_toggle_signal_id)
                direction = self._get_lon_direction()
                longitude = CollectionPresenter._parse_lat_lon(direction, text)
                direct, degs, mins, secs = longitude_to_dms(longitude)
                dms_string = f'{direct} {degs}°{mins}\'{secs}"'
        except Exception:
            logger.debug(traceback.format_exc())
            self.add_problem(self.PROBLEM_BAD_LONGITUDE,
                             self.view.widgets.lon_entry)
        else:
            self.remove_problem(self.PROBLEM_BAD_LONGITUDE,
                                self.view.widgets.lon_entry)

        self.view.widgets.lon_dms_label.set_text(dms_string)
        if text is None or text.strip() == '':
            self.set_model_attr('longitude', None)
        else:
            self.set_model_attr('longitude', utils.nstr(longitude))


class PropagationChooserPresenter(editor.ChildPresenter):
    """Chooser for selecting an existing garden propagation for the source.

    :param parent: the parent AccessionEditorPresenter
    :param model: a Source instance
    :param view: an AccessionEditorView
    :param session: an sqlalchemy.orm.session
    """
    widget_to_field_map = {}

    def __init__(self, parent, model, view, session=None):
        super().__init__(model, view, session=session)
        self.parent_ref = weakref.ref(parent)
        self.session = session
        self._dirty = False

        # first item in the list store is the object that is used when toggled
        # The rest are strings for their respective fields, this allows
        # sorting by row without the need to tree_model.set_sort_func() etc.
        self.tree_model = Gtk.ListStore(object, str, str, str, str, str)
        self.view.widgets.source_prop_treeview.set_model(self.tree_model)
        self.refresh_view()

        prop_toggle_cell = self.view.widgets.prop_toggle_cell
        self.view.widgets.prop_toggle_column.set_cell_data_func(
            prop_toggle_cell, self.toggle_cell_data_func)

        self.view.connect_after(prop_toggle_cell, 'toggled',
                                self.on_prop_toggle_cell_toggled)

        # assign_completions_handler
        def plant_cell_data_func(_column, renderer, tree_model, itr):
            val = tree_model[itr][0]
            renderer.set_property('text', f'{val} ({val.accession.species})')

        from .plant import plant_match_func
        self.view.attach_completion('source_prop_plant_entry',
                                    cell_data_func=plant_cell_data_func,
                                    match_func=plant_match_func,
                                    minimum_key_length=1)

        from .plant import plant_to_string_matcher
        self.assign_completions_handler(
            'source_prop_plant_entry',
            self.plant_get_completions,
            on_select=self.on_propagation_search_select,
            comparer=lambda row, txt: plant_to_string_matcher(row[0], txt)
        )

    def plant_get_completions(self, _text):
        logger.debug('PropagationChooserPresenter::plant_get_completions')
        from .accession import Accession
        from .plant import Plant
        query = (self.session.query(Plant)
                 .filter(Plant.propagations.any())
                 .join('accession')
                 .order_by(Accession.code, Plant.code))
        if self.model.accession and self.model.accession.id:
            query = query.filter(Accession.id != self.model.accession.id)
        result = []
        for plant in query:
            has_accessible = False
            for propagation in plant.propagations:
                if propagation.accessible_quantity > 0:
                    has_accessible = True
            if has_accessible:
                result.append(plant)
        return result

    def on_propagation_search_select(self, value):
        logger.debug('on select: %s', value)
        if isinstance(value, str):
            return
        if not value:
            # if there is nothing in the entry show all again
            if not self.view.widgets.source_prop_plant_entry.get_text():
                self.view.widgets.source_prop_treeview.set_sensitive(True)
                self.populate_with_all()
                return
            self.view.widgets.source_prop_treeview.set_sensitive(False)
            return
        self.tree_model.clear()
        frmt = prefs.prefs.get(prefs.date_format_pref)
        for prop in value.propagations:
            if prop.accessible_quantity == 0:
                continue
            self.tree_model.append(
                [prop,
                 str(prop.plant),
                 prop.plant.accession.species_str(markup=True),
                 prop.plant.location.code,
                 prop.date.strftime(frmt),
                 prop.get_summary()]
            )
        self.view.widgets.source_prop_treeview.set_sensitive(True)

    def on_prop_toggle_cell_toggled(self, cell, path):
        if cell.get_sensitive() is False:
            return
        prop = None
        if not cell.get_active():  # it's not active make it active
            prop = self.view.widgets.source_prop_treeview.get_model()[path][0]
            acc_view = self.parent_ref().view
            acc_view.widget_set_value(
                'acc_species_entry',
                utils.nstr(prop.plant.accession.species))
            acc_view.widget_set_value(
                'acc_id_qual_combo',
                utils.nstr(prop.plant.accession.id_qual))
            # need to set the model value for id_qual_rank
            self.parent_ref().model.id_qual_rank = utils.nstr(
                prop.plant.accession.id_qual_rank)
            self.parent_ref().parent_ref().refresh_id_qual_rank_combo()
            acc_view.widget_set_value(
                'acc_quantity_recvd_entry',
                utils.nstr(prop.accessible_quantity))
            from .accession import recvd_type_values
            from .propagation import prop_type_results
            acc_view.widget_set_value(
                'acc_recvd_type_comboentry',
                recvd_type_values[prop_type_results[prop.prop_type]],
                index=1)
            self.parent_ref().model.source = self.model
        else:
            self.parent_ref().model.source = None

        self.model.plant_propagation = prop
        self._dirty = True
        self.parent_ref().refresh_sensitivity()

    def populate_with_all(self):
        from .accession import Accession
        from .plant import Plant
        query = (self.session.query(Plant)
                 .filter(Plant.propagations.any())
                 .join('accession')
                 .order_by(Accession.code, Plant.code))
        if self.model.accession and self.model.accession.id:
            query = query.filter(Accession.id != self.model.accession.id)
        results = []
        for plant in query:
            has_accessible = False
            for propagation in plant.propagations:
                if propagation.accessible_quantity > 0:
                    has_accessible = True
            if has_accessible:
                results.append(plant)
        if not results:
            self.view.widgets.source_prop_treeview.set_sensitive(False)
            return
        self.tree_model.clear()
        frmt = prefs.prefs.get(prefs.date_format_pref)
        for plant in results:
            for prop in plant.propagations:
                if prop.accessible_quantity == 0:
                    continue
                self.tree_model.append(
                    [prop,
                     str(prop.plant),
                     prop.plant.accession.species_str(markup=True),
                     prop.plant.location.code,
                     prop.date.strftime(frmt),
                     prop.get_summary()]
                )
        self.view.widgets.source_prop_treeview.set_sensitive(True)

    def refresh_view(self):
        if not self.model.plant_propagation:
            self.view.widgets.source_prop_plant_entry.set_text('')
            self.tree_model.clear()
            self.populate_with_all()
            return

        parent_plant = self.model.plant_propagation.plant
        # set the parent accession
        self.view.widgets.source_prop_plant_entry.set_text(str(parent_plant))

        if not parent_plant.propagations:
            self.view.widgets.source_prop_treeview.set_sensitive(False)
            return
        self.tree_model.clear()
        frmt = prefs.prefs.get(prefs.date_format_pref)
        for prop in parent_plant.propagations:
            self.tree_model.append(
                [prop,
                 str(prop.plant),
                 prop.plant.accession.species_str(markup=True),
                 prop.plant.location.code,
                 prop.date.strftime(frmt),
                 prop.get_summary()]
            )
        self.view.widgets.source_prop_treeview.set_sensitive(True)

    def toggle_cell_data_func(self, _column, cell, model, treeiter, _data):
        propagation = model[treeiter][0]
        active = self.model.plant_propagation == propagation
        cell.set_active(active)
        cell.set_sensitive(True)

    def is_dirty(self):
        return self._dirty


# SourceDetail (ITF2 donor)


def create_source_detail(parent=None):
    model = SourceDetail()
    source_detail_edit_callback([model], parent)
    return [model]


def source_detail_edit_callback(details, parent=None):
    glade_path = os.path.join(paths.lib_dir(), "plugins", "garden",
                              "source_detail_editor.glade")
    view = editor.GenericEditorView(
        glade_path,
        parent=parent,
        root_widget_name='source_details_dialog')
    model = details[0]
    presenter = SourceDetailPresenter(model, view)
    result = presenter.start()
    return result is not None


def source_detail_remove_callback(details):
    detail = details[0]
    s_lst = []
    for detail in details:
        s_lst.append(utils.xml_safe(detail))
    msg = _("Are you sure you want to remove the following sources: \n"
            "%s?") % ', '.join(i for i in s_lst)
    if not utils.yes_no_dialog(msg):
        return False
    session = object_session(detail)
    for detail in details:
        session.delete(detail)
    try:
        utils.remove_from_results_view(details)
        session.commit()
    except Exception as e:   # pylint: disable=broad-except
        msg = _('Could not delete.\n\n%s') % utils.xml_safe(e)
        utils.message_details_dialog(msg, traceback.format_exc(),
                                     typ=Gtk.MessageType.ERROR)
        session.rollback()
    return True


def source_detail_add_acc_callback(values):
    from bauble.plugins.garden.accession import Accession, AccessionEditor
    session = db.Session()
    source_detail = session.merge(values[0])
    source = Source(source_detail=source_detail)
    edtr = AccessionEditor(model=Accession(source=source))
    session.close()
    return edtr.start() is not None


source_detail_edit_action = Action('source_detail_edit', _('_Edit'),
                                   callback=source_detail_edit_callback,
                                   accelerator='<ctrl>e')

source_detail_remove_action = Action('source_detail_remove', _('_Delete'),
                                     callback=source_detail_remove_callback,
                                     accelerator='<ctrl>Delete',
                                     multiselect=True)

source_detail_add_acc_action = Action('source_detail_add_acc',
                                      _('_Add accession'),
                                      callback=source_detail_add_acc_callback,
                                      accelerator='<ctrl>k')

source_detail_context_menu = [source_detail_edit_action,
                              source_detail_add_acc_action,
                              source_detail_remove_action]


class SourceDetail(db.Base, db.Serializable):
    __tablename__ = 'source_detail'

    # ITF2 - E6 - Donor
    name = Column(Unicode(75), unique=True)
    # extra description, not included in E6
    description = Column(UnicodeText)
    # ITF2 - E5 - Donor Type Flag
    _source_types = dict(source_type_values)
    source_type = Column(types.Enum(values=list(_source_types.keys()),
                                    translations=_source_types),
                         default=None)

    retrieve_cols = ['id', 'name']

    @classmethod
    def retrieve(cls, session, keys):
        parts = {k: v for k, v in keys.items() if k in cls.retrieve_cols}

        if parts:
            return session.query(cls).filter_by(**parts).one_or_none()
        return None

    def __str__(self):
        if self.source_type:
            return f'{self.name} ({self._source_types.get(self.source_type)})'
        return f'{self.name}'

    def search_view_markup_pair(self):
        """provide the two lines describing object for SearchView row."""
        safe = utils.xml_safe
        return (safe(self.name),
                safe(self._source_types.get(self.source_type)))

    def has_children(self):
        from sqlalchemy import exists
        session = object_session(self)
        return session.query(
            exists().where(Source.source_detail_id == self.id)
        ).scalar()


class SourceDetailPresenter(editor.GenericEditorPresenter):

    widget_to_field_map = {'source_name_entry': 'name',
                           'source_type_combo': 'source_type',
                           'source_desc_textview': 'description'}
    view_accept_buttons = ['sd_ok_button']

    def __init__(self, model, view, do_commit=True, source_types=None,
                 **kwargs):

        _source_type_vals = source_type_values
        default_source_type = None
        if source_types:
            _source_type_vals = [
                (k, v) for k, v in source_type_values if k in source_types
            ]
            if len(source_types) == 1:
                default_source_type = source_types[0]

        source_type_combo = view.widgets.source_type_combo
        # init combo before super().__init__
        view.init_translatable_combo(source_type_combo,
                                     _source_type_vals)

        super().__init__(model,
                         view,
                         refresh_view=True,
                         do_commit=do_commit,
                         **kwargs)

        # set combo default after super().__init__
        if default_source_type:
            treeiter = utils.combo_get_value_iter(source_type_combo,
                                                  default_source_type)
            source_type_combo.set_active_iter(treeiter)

        view.set_accept_buttons_sensitive(False)

    def on_textbuffer_changed_description(self, widget, value=None):
        return self.on_textbuffer_changed(widget, value, attr='description')


class GeneralSourceDetailExpander(InfoExpander):
    """Displays name, number of accessions, address, email, fax, tel, type of
    source.
    """
    def __init__(self, widgets):
        super().__init__(_('General'), widgets)
        gen_box = self.widgets.sd_gen_box
        self.widgets.remove_parent(gen_box)
        self.vbox.pack_start(gen_box, True, True, 0)

    def update(self, row):
        self.widget_set_value('sd_name_data',
                              f'<big>{utils.xml_safe(row.name)}</big>',
                              markup=True)
        source_type = ''
        if row.source_type:
            source_type = utils.xml_safe(row.source_type)
        self.widget_set_value('sd_type_data', source_type)

        description = ''
        if row.description:
            description = utils.xml_safe(row.description)
        self.widget_set_value('sd_desc_data', description, markup=True)

        session = object_session(row)
        nacc = (session.query(Source)
                .filter(Source.source_detail_id == row.id)
                .count())
        self.widget_set_value('sd_nacc_data', nacc)


class SourceDetailInfoBox(InfoBox):

    def __init__(self):
        super().__init__()
        filename = os.path.join(paths.lib_dir(), "plugins", "garden",
                                "source_detail_infobox.glade")
        self.widgets = utils.load_widgets(filename)
        self.general = GeneralSourceDetailExpander(self.widgets)
        self.add_expander(self.general)
        self.props = PropertiesExpander()
        self.add_expander(self.props)

    def update(self, row):
        self.general.update(row)
        self.props.update(row)
