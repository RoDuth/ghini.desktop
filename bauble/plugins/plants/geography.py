# Copyright 2008-2010 Brett Adams
# Copyright 2012-2015 Mario Frasca <mario@anche.no>.
# Copyright 2021-2022 Ross Demuth <rossdemuth123@gmail.com>
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
The geography module,

World Geographical Scheme for Recording Plant Distributions (WGSRPD)
"""
from operator import itemgetter
from pathlib import Path

import logging
logger = logging.getLogger(__name__)

from gi.repository import Gtk  # noqa

from sqlalchemy import select, Column, Unicode, String, Integer, ForeignKey
from sqlalchemy.orm import object_session, relationship, backref, deferred

from bauble import db, utils
from bauble import btypes as types

from bauble.view import (InfoBox, InfoExpander, select_in_search_results,
                         PropertiesExpander)


def get_species_in_geography(geo):
    """Return all the Species that have distribution in geo"""
    session = object_session(geo)
    if not session:
        ValueError('geography is not in a session')

    # get all the geography children under geo
    from .species_model import SpeciesDistribution, Species
    # get the children of geo
    geo_table = geo.__table__
    master_ids = set([geo.id])
    # populate master_ids with all the geography ids that represent
    # the children of particular geography id

    def get_geography_children(parent_id):
        stmt = select([geo_table.c.id], geo_table.c.parent_id == parent_id)
        kids = [r[0] for r in db.engine.execute(stmt).fetchall()]
        for kid in kids:
            grand_kids = get_geography_children(kid)
            master_ids.update(grand_kids)
        return kids

    geokids = get_geography_children(geo.id)
    master_ids.update(geokids)
    query = (session.query(Species).join(SpeciesDistribution)
             .filter(SpeciesDistribution.geography_id.in_(master_ids)))
    return query.all()


class GeographyMenu(Gtk.Menu):

    def __init__(self, callback):
        super().__init__()
        self.callback = callback
        geography_table = Geography.__table__
        self.geos = select([geography_table.c.id,
                            geography_table.c.name,
                            geography_table.c.parent_id]).execute().fetchall()
        self.geos_hash = {}

        from gi.repository import GLib
        GLib.idle_add(self.populate)

    def get_geos_hash(self):
        geos_hash = {}
        for geo_id, name, parent_id in self.geos:
            geos_hash.setdefault(parent_id, []).append((geo_id, name))

        for kids in geos_hash.values():
            kids.sort(key=itemgetter(1))  # sort by name

        return geos_hash

    def get_kids(self, pid):
        return self.geos_hash.get(pid, [])

    def has_kids(self, pid):
        return len(self.get_kids(pid)) > 0

    def build_menu(self, geo_id, name):
        item = Gtk.MenuItem(label=name)
        if not self.has_kids(geo_id):
            if item.get_submenu() is None:
                item.connect('activate', self.callback, geo_id)
            return item

        kids_added = False
        submenu = Gtk.Menu()
        # removes two levels of kids with the same name, there must be a
        # better way to do this but i got tired of thinking about it
        kids = self.get_kids(geo_id)
        if len(kids) > 0:
            kids_added = True
        for kid_id, kid_name in kids:  # get_kids(geo_id):
            submenu.append(self.build_menu(kid_id, kid_name))

        if kids_added:
            sel_item = Gtk.MenuItem(label=name)
            submenu.insert(sel_item, 0)
            submenu.insert(Gtk.SeparatorMenuItem(), 1)
            item.set_submenu(submenu)
            sel_item.connect('activate', self.callback, geo_id)
        else:
            item.connect('activate', self.callback, geo_id)
        return item

    def populate(self):
        """add geography value to the menu, any top level items that don't
        have any kids are appended to the bottom of the menu
        """
        self.geos_hash = self.get_geos_hash()
        if not self.geos_hash:
            # we would get here if the Geography menu is populate, usually
            # during a unit test
            return
        no_kids = []
        for geo_id, geo_name in self.geos_hash[None]:
            if geo_id not in list(self.geos_hash.keys()):
                no_kids.append((geo_id, geo_name))
            else:
                self.append(self.build_menu(geo_id, geo_name))

        for geo_id, geo_name in sorted(no_kids):
            self.append(self.build_menu(geo_id, geo_name))

        self.show_all()


class Geography(db.Base):
    """
    Represents a geography unit.

    :Table name: geography

    :Columns:
        *name*:

        *tdwg_code*:

        *tdwg_level*

        *iso_code*:

        *parent_id*:

        *geojson*

    :Properties:
        *children*:

    :Constraints:
    """
    __tablename__ = 'geography'

    # columns
    name = Column(Unicode(255), nullable=False)
    tdwg_code = Column(String(6))
    tdwg_level = Column(Integer)
    iso_code = Column(String(7))
    parent_id = Column(Integer, ForeignKey('geography.id'))
    geojson = deferred(Column(types.JSON()))
    collection = relationship('Collection', back_populates='region')
    distribution = relationship('SpeciesDistribution',
                                back_populates='geography')

    retrieve_cols = ['id', 'tdwg_code']
    children = relationship('Geography',
                            cascade='all',
                            backref=backref('parent',
                                            remote_side='Geography.id'),
                            order_by=[name])

    @classmethod
    def retrieve(cls, session, keys):
        parts = {k: v for k, v in keys.items() if k in cls.retrieve_cols}

        if parts:
            return session.query(cls).filter_by(**parts).one_or_none()
        return None

    def __str__(self):
        return str(self.name)


class GeneralGeographyExpander(InfoExpander):
    """Generic minimalist info about a geography."""

    def __init__(self, widgets):
        super().__init__(_("General"), widgets)
        general_box = self.widgets.general_box
        self.widgets.general_window.remove(general_box)
        self.vbox.pack_start(general_box, True, True, 0)
        self.table_cells = []

    def update(self, row):
        on_clicked = utils.generate_on_clicked(select_in_search_results)
        level = ['Continent', 'Region', 'Area', 'Unit'][row.tdwg_level - 1]
        self.widget_set_value('name_label', row.name)
        self.widget_set_value('tdwg_level', level)
        self.widget_set_value('tdwg_code', row.tdwg_code)
        self.widget_set_value('iso_code', row.iso_code)
        self.widget_set_value('parent', row.parent or '')
        shape = row.geojson.get('type', '') if row.geojson else ''
        self.widget_set_value('geojson_type', shape)
        if row.parent:
            utils.make_label_clickable(self.widgets.parent, on_clicked,
                                       row.parent)
        self.widgets.childbox.foreach(self.widgets.childbox.remove)
        for geo in row.children:
            child_lbl = Gtk.Label()
            child_lbl.set_xalign(0)
            child_lbl.set_text(str(geo))
            eventbox = Gtk.EventBox()
            eventbox.add(child_lbl)
            self.widgets.childbox.pack_start(eventbox, True, True, 0)
            utils.make_label_clickable(child_lbl, on_clicked,
                                       geo)
        self.widgets.ib_general_grid.show_all()


class GeographyInfoBox(InfoBox):
    """
    general info
    """
    def __init__(self):
        super().__init__()
        filename = str(Path(__file__).resolve().parent / 'geo_infobox.glade')
        self.widgets = utils.load_widgets(filename)
        self.general = GeneralGeographyExpander(self.widgets)
        self.add_expander(self.general)
        self.props = PropertiesExpander()
        self.add_expander(self.props)

    def update(self, row):
        self.general.update(row)
        self.props.update(row)


def geography_importer():

    import json
    from bauble import pb_set_fraction

    root = Path(__file__).resolve().parent

    lvl1_file = root / "default/wgsrpd/level1.geojson"
    lvl2_file = root / "default/wgsrpd/level2.geojson"
    lvl3_file = root / "default/wgsrpd/level3.geojson"
    lvl4_file = root / "default/wgsrpd/level4.geojson"

    session = db.Session()

    with lvl1_file.open('r', encoding='utf-8', newline='') as f:
        geojson_lvl1 = json.load(f)

    with lvl2_file.open('r', encoding='utf-8', newline='') as f:
        geojson_lvl2 = json.load(f)

    with lvl3_file.open('r', encoding='utf-8', newline='') as f:
        geojson_lvl3 = json.load(f)

    with lvl4_file.open('r', encoding='utf-8', newline='') as f:
        geojson_lvl4 = json.load(f)

    total_items = (len(geojson_lvl1.get('features')) +
                   len(geojson_lvl2.get('features')) +
                   len(geojson_lvl3.get('features')) +
                   len(geojson_lvl4.get('features')))

    steps_so_far = 0
    five_percent = int(total_items / 20) or 1

    def update_progressbar(steps_so_far):
        percent = float(steps_so_far) / float(total_items)
        if 0 < percent < 1.0:
            pb_set_fraction(percent)

    for feature in geojson_lvl1.get('features'):
        row = Geography()
        props = feature.get('properties')
        row.tdwg_code = str(props.get('LEVEL1_COD'))
        row.tdwg_level = 1
        row.name = props.get('LEVEL1_NAM')
        row.geojson = feature.get('geometry')
        session.add(row)
        session.commit()
        steps_so_far += 1
        if steps_so_far % five_percent == 0:
            update_progressbar(steps_so_far)
            yield

    # pylint: disable=attribute-defined-outside-init  # Geography.parent
    for feature in geojson_lvl2.get('features'):
        row = Geography()
        props = feature.get('properties')
        row.tdwg_code = str(props.get('LEVEL2_COD'))
        row.tdwg_level = 2
        row.name = props.get('LEVEL2_NAM')
        row.geojson = feature.get('geometry')
        row.parent = (session.query(Geography)
                      .filter(Geography.tdwg_code ==
                              str(props.get('LEVEL1_COD')))
                      .one())
        session.add(row)
        session.commit()
        steps_so_far += 1
        if steps_so_far % five_percent == 0:
            update_progressbar(steps_so_far)
            yield

    for feature in geojson_lvl3.get('features'):
        row = Geography()
        props = feature.get('properties')
        row.tdwg_code = str(props.get('LEVEL3_COD'))
        row.tdwg_level = 3
        row.name = props.get('LEVEL3_NAM')
        row.geojson = feature.get('geometry')
        row.parent = (session.query(Geography)
                      .filter(Geography.tdwg_code ==
                              str(props.get('LEVEL2_COD')))
                      .one())
        session.add(row)
        session.commit()
        steps_so_far += 1
        if steps_so_far % five_percent == 0:
            update_progressbar(steps_so_far)
            yield

    for feature in geojson_lvl4.get('features'):
        props = feature.get('properties')
        if props.get('Level4_2') == 'OO':
            # these are really only place holders and are the same as the 3rd
            # level elements, which should be used instead.
            steps_so_far += 1
            if steps_so_far % five_percent == 0:
                update_progressbar(steps_so_far)
                yield
            continue
        parent = (session.query(Geography)
                  .filter(Geography.tdwg_code == str(props.get('Level3_cod')))
                  .one())
        # check for duplicates (e.g. CZE-SL has 2 entries) use the version with
        # the most detail
        existing = (session.query(Geography)
                    .filter_by(tdwg_level=4,
                               parent_id=parent.id,
                               tdwg_code=str(props.get('Level4_cod')),
                               iso_code=props.get('ISO_Code'),
                               name=props.get('Level_4_Na'))
                    .first())
        if existing:
            logger.debug('found duplicate for: %s', props)
            # Hacky... but works
            if (len(str(feature.get('geometry')).split(',')) >
                    len(str(existing.geojson).split(','))):
                row = existing
                logger.debug('using duplicate, overwriting original')
            else:
                logger.debug('dropping duplicate')
                continue
        else:
            row = Geography()
        row.tdwg_code = str(props.get('Level4_cod'))
        row.tdwg_level = 4
        row.iso_code = props.get('ISO_Code')
        row.name = props.get('Level_4_Na')
        row.geojson = feature.get('geometry')
        row.parent = parent
        session.add(row)
        session.commit()
        steps_so_far += 1
        if steps_so_far % five_percent == 0:
            update_progressbar(steps_so_far)
            yield
    session.close()
