# Copyright 2008-2010 Brett Adams
# Copyright 2014-2015 Mario Frasca <mario@anche.no>.
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
"""
Family table definition
"""

import os
import traceback
import weakref

import logging
logger = logging.getLogger(__name__)

from gi.repository import Gtk

from sqlalchemy import (Column, Integer, ForeignKey, and_, UniqueConstraint,
                        String)
from sqlalchemy.orm import relationship, validates
from sqlalchemy.orm import synonym as sa_synonym
from sqlalchemy.orm.session import object_session
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.associationproxy import association_proxy

import bauble
from bauble import db
from bauble import pluginmgr
from bauble import editor
from bauble import utils
from bauble import btypes as types
from bauble import prefs
from bauble.view import (Action, InfoBox, InfoExpander, PropertiesExpander,
                         select_in_search_results, LinksExpander)
from bauble import paths
from .species_model import Species


def edit_callback(families):
    """Family context menu callback"""
    family = families[0]
    return FamilyEditor(model=family).start() is not None


def add_genera_callback(families):
    """Family context menu callback"""
    session = db.Session()
    family = session.merge(families[0])
    e = GenusEditor(model=Genus(family=family))
    session.close()
    return e.start() is not None


def remove_callback(families):
    """The callback function to remove a family from the family context menu.
    """
    family = families[0]
    session = object_session(family)
    for family in families:
        ngen = session.query(Genus).filter_by(family_id=family.id).count()
        safe_str = utils.xml_safe(str(family))
        if ngen > 0:
            msg = (_('The family <i>%(1)s</i> has %(2)s genera.'
                     '\n\n') % {'1': safe_str, '2': ngen} +
                   _('You cannot remove a family with genera.'))
            utils.message_dialog(msg, typ=Gtk.MessageType.WARNING)
            return None
    fams = ', '.join([utils.xml_safe(i) for i in families])
    msg = _("Are you sure you want to remove the following families "
            "<i>%s</i>?") % fams
    if not utils.yes_no_dialog(msg):
        return None
    for family in families:
        session.delete(family)
    try:
        utils.remove_from_results_view(families)
        session.commit()
    except Exception as e:
        msg = _('Could not delete.\n\n%s') % utils.xml_safe(e)
        utils.message_details_dialog(msg, traceback.format_exc(),
                                     typ=Gtk.MessageType.ERROR)
        session.rollback()
    return True


edit_action = Action('family_edit', _('_Edit'),
                     callback=edit_callback,
                     accelerator='<ctrl>e')
add_species_action = Action('family_genus_add', _('_Add genus'),
                            callback=add_genera_callback,
                            accelerator='<ctrl>k')
remove_action = Action('family_remove', _('_Delete'),
                       callback=remove_callback,
                       accelerator='<ctrl>Delete', multiselect=True)

family_context_menu = [edit_action, add_species_action, remove_action]


class Family(db.Base, db.Serializable, db.WithNotes):
    """
    :Table name: family

    :Columns:
        *family*:
            The name of the family. Required.

        *qualifier*:
            The family qualifier.

            Possible values:
                * s. lat.: aggregrate family (senso lato)

                * s. str.: segregate family (senso stricto)

                * '': the empty string

    :Properties:
        *synonyms*:
            An association to _synonyms that will automatically
            convert a Family object and create the synonym.

    :Constraints:
        The family table has a unique constraint on family/qualifier.
    """
    __tablename__ = 'family'
    __table_args__ = (UniqueConstraint('family'), {})

    rank = 'familia'
    link_keys = ['accepted']

    # columns
    family = Column(String(45), nullable=False, index=True)
    epithet = sa_synonym('family')

    # we use the blank string here instead of None so that the
    # contraints will work properly,
    qualifier = Column(types.Enum(values=['s. lat.', 's. str.', '']),
                       default='')

    # relations
    # `genera` relation is defined outside of `Family` class definition
    synonyms = association_proxy('_synonyms', 'synonym')
    _synonyms = relationship('FamilySynonym',
                             primaryjoin='Family.id==FamilySynonym.family_id',
                             cascade='all, delete-orphan',
                             uselist=True,
                             backref='family')

    # this is a dummy relation, it is only here to make cascading work
    # correctly and to ensure that all synonyms related to this family
    # get deleted if this family gets deleted
    _accepted = relationship('FamilySynonym',
                             primaryjoin='Family.id==FamilySynonym.synonym_id',
                             cascade='all, delete-orphan',
                             uselist=True,
                             backref='synonym')

    retrieve_cols = ['id', 'epithet', 'family']
    genera = relationship('Genus',
                          order_by='Genus.genus',
                          back_populates='family',
                          cascade='all, delete-orphan')

    @classmethod
    def retrieve(cls, session, keys):
        fam_parts = {k: v for k, v in keys.items() if k in cls.retrieve_cols}

        if fam_parts:
            return session.query(cls).filter_by(**fam_parts).one_or_none()
        return None

    @validates('genus')
    def validate_stripping(self, _key, value):
        if value is None:
            return None
        return value.strip()

    @property
    def cites(self):
        """the cites status of this taxon, or None"""

        cites_notes = [i.note for i in self.notes
                       if i.category and i.category.upper() == 'CITES']
        if not cites_notes:
            return None
        return cites_notes[0]

    def __repr__(self):
        return Family.str(self)

    @staticmethod
    def str(family, _qualifier=False, _author=False):
        # TODO author is not in the model but it really should
        if family.family is None:
            return db.Base.__repr__(family)
        return ' '.join([s for s in [
            family.family, family.qualifier] if s not in (None, '')])

    @property
    def accepted(self):
        """Name that should be used if name of self should be rejected"""
        session = object_session(self)
        if not session:
            logger.warning('family:accepted - object not in session')
            return None
        syn = session.query(FamilySynonym).filter(
            FamilySynonym.synonym_id == self.id).first()
        accepted = syn and syn.family
        return accepted

    @accepted.setter
    def accepted(self, value):
        'Name that should be used if name of self should be rejected'
        assert isinstance(value, self.__class__)
        if self in value.synonyms:
            return
        # remove any previous `accepted` link
        session = object_session(self)
        if not session:
            logger.warning('family:accepted.setter - object not in session')
            return
        previous_synonymy_link = (session.query(FamilySynonym)
                                  .filter(FamilySynonym.synonym_id == self.id)
                                  .first())
        if previous_synonymy_link:
            accepted = (
                session.query(Family)
                .filter(Family.id == previous_synonymy_link.family_id)
                .one()
            )
            accepted.synonyms.remove(self)
        session.flush()
        if value != self:
            value.synonyms.append(self)

    def as_dict(self, recurse=True):
        result = db.Serializable.as_dict(self)
        del result['family']
        del result['qualifier']
        result['object'] = 'taxon'
        result['rank'] = self.rank
        result['epithet'] = self.family
        if recurse and self.accepted is not None:
            result['accepted'] = self.accepted.as_dict(recurse=False)
        return result

    @classmethod
    def correct_field_names(cls, keys):
        for internal, exchange in [('family', 'epithet')]:
            if exchange in keys:
                keys[internal] = keys[exchange]
                del keys[exchange]

    def top_level_count(self):
        genera = set(g for g in self.genera if g.species)
        species = [s for g in genera for s in
                   db.get_active_children('species', g)]
        accessions = [a for s in species for a in
                      db.get_active_children('accessions', s)]
        plants = [p for a in accessions for p in
                  db.get_active_children('plants', a)]
        return {(1, 'Families'): set([self.id]),
                (2, 'Genera'): genera,
                (3, 'Species'): set(s.id for s in species),
                (4, 'Accessions'): len(accessions),
                (5, 'Plantings'): len(plants),
                (6, 'Living plants'): sum(p.quantity for p in plants),
                (7, 'Locations'): set(p.location.id for p in plants),
                (8, 'Sources'): set(a.source.source_detail.id for a in
                                    accessions if a.source and
                                    a.source.source_detail)}

    def has_children(self):
        cls = self.__class__.genera.prop.mapper.class_
        from sqlalchemy import exists
        session = object_session(self)
        return session.query(
            exists().where(cls.family_id == self.id)
        ).scalar()

    def count_children(self):
        cls = self.__class__.genera.prop.mapper.class_
        session = object_session(self)
        return session.query(cls.id).filter(cls.family_id == self.id).count()


# defining the latin alias to the class.
Familia = Family


def compute_serializable_fields(_cls, session, keys):
    result = {'family': None}

    family_keys = {'epithet': keys['family']}
    result['family'] = Family.retrieve_or_create(
        session, family_keys, create=False)

    return result


FamilyNote = db.make_note_class('Family', compute_serializable_fields)


class FamilySynonym(db.Base):
    """
    :Table name: family_synonyms

    :Columns:
        *family_id*:

        *synonyms_id*:

    :Properties:
        *synonyms*:

        *family*:
    """
    __tablename__ = 'family_synonym'

    # columns
    family_id = Column(Integer, ForeignKey('family.id'), nullable=False)
    synonym_id = Column(Integer, ForeignKey('family.id'), nullable=False,
                        unique=True)

    def __init__(self, synonym=None, **kwargs):
        # it is necessary that the first argument here be synonym for
        # the Family.synonyms association_proxy to work
        self.synonym = synonym
        super().__init__(**kwargs)

    def __str__(self):
        return Family.str(self.synonym)


# avoid circular imports
from .genus import Genus, GenusEditor


class FamilyEditorView(editor.GenericEditorView):

    _tooltips = {
        'fam_family_entry': _('The family name.'),
        'fam_qualifier_combo': _('The family qualifier helps to remove '
                                 'ambiguities that might be associated with '
                                 'this family name.'),
        'fam_syn_frame': _('A list of synonyms for this family.\n\nTo add a '
                           'synonym enter a family name and select one from '
                           'the list of completions.  Then click Add to add '
                           'it to the list of synonyms.'),
        'fam_cancel_button': _('Cancel your changes.'),
        'fam_ok_button': _('Save your changes.'),
        'fam_ok_and_add_button': _('Save your changes and add a '
                                   'genus to this family.'),
        'fam_next_button': _('Save your changes and add another '
                             'family.')
    }

    def __init__(self, parent=None):
        filename = os.path.join(paths.lib_dir(), 'plugins', 'plants',
                                'family_editor.glade')
        super().__init__(filename, parent=parent,
                         root_widget_name='family_dialog')
        self.attach_completion('fam_syn_entry')
        self.set_accept_buttons_sensitive(False)
        self.widgets.notebook.set_current_page(0)

    def get_window(self):
        return self.widgets.family_dialog

    # TODO can this be removed?
    def save_state(self):
        pass

    # TODO can this be removed?  (was only for syn_expanded_pref)
    def restore_state(self):
        pass

    def set_accept_buttons_sensitive(self, sensitive):
        self.widgets.fam_ok_button.set_sensitive(sensitive)
        self.widgets.fam_ok_and_add_button.set_sensitive(sensitive)
        self.widgets.fam_next_button.set_sensitive(sensitive)


class FamilyEditorPresenter(editor.GenericEditorPresenter):

    widget_to_field_map = {'fam_family_entry': 'family',
                           'fam_qualifier_combo': 'qualifier'}

    def __init__(self, model, view):
        """
        :param model: should be an instance of class Family
        :param view: should be an instance of FamilyEditorView
        """
        super().__init__(model, view)
        self.session = object_session(model)

        # initialize widgets
        self.init_enum_combo('fam_qualifier_combo', 'qualifier')
        self.synonyms_presenter = SynonymsPresenter(self)
        self.refresh_view()  # put model values in view

        # connect signals
        self.assign_simple_handler('fam_family_entry', 'family',
                                   editor.StringOrNoneValidator())
        self.assign_simple_handler('fam_qualifier_combo', 'qualifier',
                                   editor.StringOrEmptyValidator())

        notes_parent = self.view.widgets.notes_parent_box
        notes_parent.foreach(notes_parent.remove)
        self.notes_presenter = editor.NotesPresenter(self,
                                                     'notes',
                                                     notes_parent)

        if self.model not in self.session.new:
            self.view.widgets.fam_ok_and_add_button.set_sensitive(True)

        # for each widget register a signal handler to be notified when the
        # value in the widget changes, that way we can do things like sensitize
        # the ok button
        self._dirty = False

    def refresh_sensitivity(self):
        # TODO: check widgets for problems
        if self.model.family:
            self.view.set_accept_buttons_sensitive(self.is_dirty())
        else:
            self.view.set_accept_buttons_sensitive(False)

    def set_model_attr(self, attr, value, validator=None):
        # debug('set_model_attr(%s, %s)' % (attr, value))
        super().set_model_attr(attr, value, validator)
        self._dirty = True
        self.refresh_sensitivity()

    def is_dirty(self):
        return (self._dirty or self.synonyms_presenter.is_dirty() or
                self.notes_presenter.is_dirty())

    def refresh_view(self):
        for widget, field in self.widget_to_field_map.items():
            value = getattr(self.model, field)
            self.view.widget_set_value(widget, value)

    def cleanup(self):
        super().cleanup()
        self.synonyms_presenter.cleanup()
        self.notes_presenter.cleanup()


class SynonymsPresenter(editor.GenericEditorPresenter):

    def __init__(self, parent):
        """
        :param parent: FamilyEditorPresenter
        """
        self.parent_ref = weakref.ref(parent)
        super().__init__(self.parent_ref().model, self.parent_ref().view)
        self.session = self.parent_ref().session
        self.view.widgets.fam_syn_entry.props.text = ''
        self.init_treeview()

        def fam_get_completions(text):
            query = self.session.query(Family)
            return (query.filter(and_(Family.family.like(f'{text}%%'),
                                      Family.id != self.model.id))
                    .order_by(Family.family))

        self._selected = None

        def on_select(value):
            # don't set anything in the model, just set self._selected
            sensitive = True
            if value is None:
                sensitive = False
            self.view.widgets.fam_syn_add_button.set_sensitive(sensitive)
            self._selected = value
        self.assign_completions_handler('fam_syn_entry', fam_get_completions,
                                        on_select=on_select)
        self.view.connect('fam_syn_add_button', 'clicked',
                          self.on_add_button_clicked)
        self.view.connect('fam_syn_remove_button', 'clicked',
                          self.on_remove_button_clicked)
        self._dirty = False

    def is_dirty(self):
        return self._dirty

    def init_treeview(self):
        """initialize the Gtk.TreeView"""
        self.treeview = self.view.widgets.fam_syn_treeview
        # remove any columns that were setup previous, this became a
        # problem when we starting reusing the glade files with
        # utils.BuilderLoader, the right way to do this would be to
        # create the columns in glade instead of here
        for col in self.treeview.get_columns():
            self.treeview.remove_column(col)

        def _syn_data_func(_column, cell, model, itr, _data):
            v = model[itr][0]
            cell.set_property('text', str(v))
            # just added so change the background color to indicate it's new
            if v.id is None:
                cell.set_property('foreground', 'blue')
            else:
                cell.set_property('foreground', None)

        cell = Gtk.CellRendererText()
        col = Gtk.TreeViewColumn('Synonym', cell)
        col.set_cell_data_func(cell, _syn_data_func)
        self.treeview.append_column(col)

        tree_model = Gtk.ListStore(object)
        for syn in self.model._synonyms:
            tree_model.append([syn])
        self.treeview.set_model(tree_model)
        self.view.connect(self.treeview, 'cursor-changed',
                          self.on_tree_cursor_changed)

    def on_tree_cursor_changed(self, tree):
        path, _column = tree.get_cursor()
        self.view.widgets.fam_syn_remove_button.set_sensitive(path is not None)

    def refresh_view(self):
        """Doesn't do anything"""
        return

    def on_add_button_clicked(self, _button):
        """adds the synonym from the synonym entry to the list of synonyms for
        this species
        """
        syn = FamilySynonym(family=self.model, synonym=self._selected)
        tree_model = self.treeview.get_model()
        tree_model.append([syn])
        self._selected = None
        entry = self.view.widgets.fam_syn_entry
        entry.props.text = ''
        entry.set_position(-1)
        self.view.widgets.fam_syn_add_button.set_sensitive(False)
        self.view.widgets.fam_syn_add_button.set_sensitive(False)
        self._dirty = True
        self.parent_ref().refresh_sensitivity()

    def on_remove_button_clicked(self, _button):
        """removes the currently selected synonym from the list of synonyms for
        this species
        """
        # TODO: maybe we should only ask 'are you sure' if the selected value
        # is an instance, this means it will be deleted from the database
        tree = self.view.widgets.fam_syn_treeview
        path, _col = tree.get_cursor()
        tree_model = tree.get_model()
        value = tree_model[tree_model.get_iter(path)][0]
        syn_str = Family.str(value.synonym)
        msg = _('Are you sure you want to remove %s as a synonym to the '
                'current family?\n\n<i>Note: This will not remove the family '
                '%s from the database.</i>') % (syn_str, syn_str)
        if utils.yes_no_dialog(msg, parent=self.view.get_window()):
            tree_model.remove(tree_model.get_iter(path))
            self.model.synonyms.remove(value.synonym)
            utils.delete_or_expunge(value)
            self.session.flush([value])
            self._dirty = True
            self.parent_ref().refresh_sensitivity()


class FamilyEditor(editor.GenericModelViewPresenterEditor):

    # these have to correspond to the response values in the view
    RESPONSE_OK_AND_ADD = 11
    RESPONSE_NEXT = 22
    ok_responses = (RESPONSE_OK_AND_ADD, RESPONSE_NEXT)

    def __init__(self, model=None, parent=None):
        """
        :param model: Family instance or None
        :param parent: the parent window or None
        """
        if model is None:
            model = Family()
        super().__init__(model, parent)
        if not parent and bauble.gui:
            parent = bauble.gui.window
        self.parent = parent
        self._committed = []

        view = FamilyEditorView(parent=self.parent)
        self.presenter = FamilyEditorPresenter(self.model, view)

    def handle_response(self, response):
        """
        :return: list if we want to tell start() to close the editor, the list
            should either be empty or the list of committed values, return None
            if we want to keep editing
        """
        not_ok_msg = 'Are you sure you want to lose your changes?'
        if response == Gtk.ResponseType.OK or response in self.ok_responses:
            try:
                if self.presenter.is_dirty():
                    self.commit_changes()
                    self._committed.append(self.model)
            except DBAPIError as e:
                msg = _('Error committing changes.\n\n%s') % \
                    utils.xml_safe(e.orig)
                utils.message_details_dialog(msg, str(e),
                                             Gtk.MessageType.ERROR)
                return False
            except Exception as e:
                msg = _('Unknown error when committing changes. See the '
                        'details for more information.\n\n%s') % \
                    utils.xml_safe(e)
                utils.message_details_dialog(msg, traceback.format_exc(),
                                             Gtk.MessageType.ERROR)
                return False
        elif ((self.presenter.is_dirty() and
               utils.yes_no_dialog(not_ok_msg)) or not
              self.presenter.is_dirty()):
            self.session.rollback()
            return True
        else:
            return False

        # respond to responses
        more_committed = None
        if response == self.RESPONSE_NEXT:
            self.presenter.cleanup()
            e = FamilyEditor(parent=self.parent)
            more_committed = e.start()
        elif response == self.RESPONSE_OK_AND_ADD:
            e = GenusEditor(Genus(family=self.model), self.parent)
            more_committed = e.start()

        if more_committed is not None:
            if isinstance(more_committed, list):
                self._committed.extend(more_committed)
            else:
                self._committed.append(more_committed)

        return True

    def start(self):
        while True:
            response = self.presenter.start()
            self.presenter.view.save_state()
            if self.handle_response(response):
                break
        self.presenter.cleanup()
        self.session.close()  # cleanup session
        return self._committed


class GeneralFamilyExpander(InfoExpander):
    """Generic information about an family like number of genus, species,
    accessions and plants
    """

    def __init__(self, widgets):
        super().__init__(_("General"), widgets)
        general_box = self.widgets.fam_general_box
        self.widgets.remove_parent(general_box)
        self.vbox.pack_start(general_box, True, True, 0)

    def update(self, row):
        """
        update the expander

        :param row: the row to get the values from
        """
        self.widget_set_value('fam_name_data', f'<big>{row}</big>',
                              markup=True)
        session = object_session(row)
        # get the number of genera
        ngen = session.query(Genus).filter_by(family_id=row.id).count()
        self.widget_set_value('fam_ngen_data', ngen)

        # get the number of species
        nsp = (session.query(Species).join('genus').
               filter_by(family_id=row.id).count())
        if nsp == 0:
            self.widget_set_value('fam_nsp_data', 0)
        else:
            ngen_in_sp = (session.query(Species.genus_id).
                          join('genus', 'family').
                          filter_by(id=row.id).distinct().count())
            self.widget_set_value('fam_nsp_data',
                                  f'{nsp} in  {ngen_in_sp} genera')

        # stop here if no GardenPlugin
        if 'GardenPlugin' not in pluginmgr.plugins:
            return

        # get the number of accessions in the family
        from bauble.plugins.garden.accession import Accession
        from bauble.plugins.garden.plant import Plant

        nacc = (session.query(Accession).
                join('species', 'genus', 'family').
                filter_by(id=row.id).count())
        if nacc == 0:
            self.widget_set_value('fam_nacc_data', nacc)
        else:
            nsp_in_acc = (session.query(Accession.species_id).
                          join('species', 'genus', 'family').
                          filter_by(id=row.id).distinct().count())
            self.widget_set_value('fam_nacc_data',
                                  f'{nacc} in {nsp_in_acc} species')

        # get the number of plants in the family
        nplants = (session.query(Plant).
                   join('accession', 'species', 'genus', 'family').
                   filter_by(id=row.id).count())
        if nplants == 0:
            self.widget_set_value('fam_nplants_data', nplants)
        else:
            nacc_in_plants = (session.query(Plant.accession_id)
                              .join('accession', 'species', 'genus', 'family')
                              .filter_by(id=row.id).distinct().count())
            self.widget_set_value('fam_nplants_data',
                                  f'{nplants} in {nacc_in_plants} accessions')

        on_clicked = utils.generate_on_clicked(bauble.gui.send_command)

        utils.make_label_clickable(
            self.widgets.fam_ngen_data, on_clicked,
            f'genus where family.family="{row.family}" and '
            f'family.qualifier="{row.qualifier}"'
        )

        utils.make_label_clickable(
            self.widgets.fam_nsp_data, on_clicked,
            f'species where genus.family.family="{row.family}" and '
            f'genus.family.qualifier="{row.qualifier}"'
        )

        utils.make_label_clickable(
            self.widgets.fam_nacc_data, on_clicked,
            f'accession where species.genus.family.family="{row.family}" and '
            f'species.genus.family.qualifier="{row.qualifier}"'
        )

        utils.make_label_clickable(
            self.widgets.fam_nplants_data, on_clicked,
            f'plant where accession.species.genus.family.family="{row.family}"'
            f' and accession.species.genus.family.qualifier="{row.qualifier}"'
        )


class SynonymsExpander(InfoExpander):

    EXPANDED_PREF = 'infobox.family_synonyms_expanded'

    def __init__(self, widgets):
        super().__init__(_("Synonyms"), widgets)
        synonyms_box = self.widgets.fam_synonyms_box
        self.widgets.remove_parent(synonyms_box)
        self.vbox.pack_start(synonyms_box, True, True, 0)

    def update(self, row):
        """update the expander

        :param row: the row to get thevalues from
        """
        self.reset()
        syn_box = self.widgets.fam_synonyms_box
        # remove old labels
        syn_box.foreach(syn_box.remove)
        logger.debug("family %s is synonym of %s and has synonyms %s", row,
                     row.accepted, row.synonyms)
        self.set_label(_("Synonyms"))  # reset default value
        on_clicked = utils.generate_on_clicked(select_in_search_results)
        if row.accepted is not None:
            self.set_label(_("Accepted name"))
            # create clickable label that will select the synonym
            # in the search results
            box = Gtk.EventBox()
            label = Gtk.Label()
            label.set_xalign(0.0)
            label.set_yalign(0.5)
            label.set_markup(Family.str(row.accepted))
            box.add(label)
            utils.make_label_clickable(label, on_clicked, row.accepted)
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
                label.set_markup(Family.str(syn))
                box.add(label)
                utils.make_label_clickable(label, on_clicked, syn)
                syn_box.pack_start(box, False, False, 0)
            self.show_all()
            self.set_sensitive(True)


class FamilyInfoBox(InfoBox):
    FAMILY_WEB_BUTTON_DEFS_PREFS = 'web_button_defs.family'

    def __init__(self):
        button_defs = []
        buttons = prefs.prefs.itersection(self.FAMILY_WEB_BUTTON_DEFS_PREFS)
        for name, button in buttons:
            button['name'] = name
            button_defs.append(button)

        super().__init__()
        filename = os.path.join(paths.lib_dir(), 'plugins', 'plants',
                                'infoboxes.glade')
        self.widgets = utils.load_widgets(filename)
        self.general = GeneralFamilyExpander(self.widgets)
        self.add_expander(self.general)
        self.synonyms = SynonymsExpander(self.widgets)
        self.add_expander(self.synonyms)
        self.links = LinksExpander('notes', links=button_defs)
        self.add_expander(self.links)
        self.props = PropertiesExpander()
        self.add_expander(self.props)

        if 'GardenPlugin' not in pluginmgr.plugins:
            self.widgets.remove_parent('fam_nacc_label')
            self.widgets.remove_parent('fam_nacc_data')
            self.widgets.remove_parent('fam_nplants_label')
            self.widgets.remove_parent('fam_nplants_data')

    def update(self, row):
        self.general.update(row)
        self.synonyms.update(row)
        self.links.update(row)
        self.props.update(row)


db.Family = Family
