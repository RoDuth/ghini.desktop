# Copyright 2008-2010 Brett Adams
# Copyright 2015 Mario Frasca <mario@anche.no>.
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
Genera table module
"""

import os
import traceback

import logging
logger = logging.getLogger(__name__)

from gi.repository import Gtk  # noqa

from sqlalchemy import (Column,
                        Unicode,
                        Integer,
                        ForeignKey,
                        String,
                        UniqueConstraint,
                        literal,
                        event,
                        update,
                        CheckConstraint)
from sqlalchemy.orm import relationship, backref, object_mapper
from sqlalchemy.orm import synonym as sa_synonym
from sqlalchemy.orm.session import object_session
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.associationproxy import association_proxy
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.sql.expression import select, case

import bauble
from bauble import db
from bauble import error
from bauble import pluginmgr
from bauble import editor
from bauble import utils
from bauble import btypes as types
from bauble import paths
from bauble import prefs
from bauble.view import (InfoBox,
                         InfoExpander,
                         LinksExpander,
                         PropertiesExpander,
                         select_in_search_results,
                         Action)

# TODO: warn the user that a duplicate genus name is being entered
# even if only the author or qualifier is different

# TODO: since there can be more than one genus with the same name but
# different authors we need to show the Genus author in the result
# search, we should also check if when entering a plantname with a
# chosen genus if that genus has an author ask the user if they want
# to use the accepted name and show the author of the genus then so
# they aren't using the wrong version of the Genus, e.g. Cananga


def edit_callback(genera):
    genus = genera[0]
    return GenusEditor(model=genus).start() is not None


def add_species_callback(genera):
    session = db.Session()
    genus = session.merge(genera[0])
    result = edit_species(model=Species(genus=genus)) is not None
    session.close()
    return result


def remove_callback(genera):
    """The callback function to remove a genus from the genus context menu."""
    genus = genera[0]
    g_lst = []
    session = object_session(genus)
    for genus in genera:
        g_lst.append(utils.xml_safe(genus))
        nsp = session.query(Species).filter_by(genus_id=genus.id).count()
        safe_str = utils.xml_safe(str(genus))
        if nsp > 0:
            msg = (_('The genus <i>%(1)s</i> has %(2)s species.'
                     '\n\n') % {'1': safe_str, '2': nsp} +
                   _('You cannot remove a genus with species.'))
            utils.message_dialog(msg, typ=Gtk.MessageType.WARNING)
            return False
        msg = _("Are you sure you want to remove the following genera "
                "<i>%s</i>?") % ', '.join(i for i in g_lst)
    if not utils.yes_no_dialog(msg):
        return False
    for genus in genera:
        session.delete(genus)
    try:
        utils.remove_from_results_view(genera)
        session.commit()
    except Exception as e:  # pylint: disable=broad-except
        msg = _('Could not delete.\n\n%s') % utils.xml_safe(e)
        utils.message_details_dialog(msg, traceback.format_exc(),
                                     typ=Gtk.MessageType.ERROR)
        session.rollback()
    return True


edit_action = Action('genus_edit', _('_Edit'),
                     callback=edit_callback,
                     accelerator='<ctrl>e')
add_species_action = Action('genus_sp_add', _('_Add species'),
                            callback=add_species_callback,
                            accelerator='<ctrl>k')
remove_action = Action('genus_remove', _('_Delete'),
                       callback=remove_callback,
                       accelerator='<ctrl>Delete', multiselect=True)

genus_context_menu = [edit_action, add_species_action, remove_action]


class Genus(db.Base, db.WithNotes):
    """
    :Table name: genus

    :Columns:
        *genus*:
            The name of the genus.  In addition to standard generic
            names any additional hybrid flags or genera should included here.

        *qualifier*:
            Designates the botanical status of the genus.

            Possible values:
                * s. lat.: aggregrate genus (sensu lato)

                * s. str.: segregate genus (sensu stricto)

        *author*:
            The name or abbreviation of the author who published this genus.

    :Properties:
        *family*:
            The family of the genus.

        *synonyms*:
            The list of genera who are synonymous with this genus.  If
            a genus is listed as a synonym of this genus then this
            genus should be considered the current and valid name for
            the synonym.

    :Contraints:
        The combination of genus, author, qualifier
        and family_id must be unique.
    """
    __tablename__ = 'genus'
    __table_args__ = (UniqueConstraint('genus', 'author',
                                       'qualifier', 'family_id'),
                      {})

    rank = 'genus'
    link_keys = ['accepted']

    # columns
    hybrid = Column(types.Enum(values=['×', '+', None]), default=None)

    subfamily = Column(Unicode(64))
    tribe = Column(Unicode(64))
    subtribe = Column(Unicode(64))

    genus = Column(String(64), nullable=False, index=True)
    epithet = sa_synonym('genus')

    # use '' instead of None so that the constraints will work propertly
    author = Column(Unicode(128), default='')

    qualifier = Column(types.Enum(values=['s. lat.', 's. str', '']),
                       default='')

    family_id = Column(Integer, ForeignKey('family.id'), nullable=False)

    # relations
    # `species` relation is defined outside of `Genus` class definition
    synonyms = association_proxy(
        '_synonyms', 'synonym', creator=lambda gen: GenusSynonym(synonym=gen)
    )
    _synonyms = relationship('GenusSynonym',
                             primaryjoin='Genus.id==GenusSynonym.genus_id',
                             cascade='all, delete-orphan',
                             uselist=True,
                             backref='genus')

    # this is a dummy relation, it is only here to make cascading work
    # correctly and to ensure that all synonyms related to this genus
    # get deleted if this genus gets deleted
    _accepted = relationship('GenusSynonym',
                             primaryjoin='Genus.id==GenusSynonym.synonym_id',
                             cascade='all, delete-orphan',
                             uselist=False,
                             backref='synonym')
    accepted = association_proxy(
        '_accepted', 'genus', creator=lambda gen: GenusSynonym(genus=gen)
    )

    species = relationship('Species', cascade='all, delete-orphan',
                           order_by='Species.sp',
                           backref=backref('genus',
                                           lazy='subquery',
                                           uselist=False))
    family = relationship('Family', back_populates='genera')

    _cites = Column(types.Enum(values=['I', 'II', 'III', None]), default=None)

    retrieve_cols = ['id',
                     'epithet',
                     'genus',
                     'hybrid',
                     'author',
                     'family',
                     'family.epithet',
                     'family.family']

    @classmethod
    def retrieve(cls, session, keys):
        parts = ['id', 'epithet', 'genus', 'hybrid', 'author']

        gen_parts = {k: v for k, v in keys.items() if k in parts}

        if not gen_parts:
            return None

        query = session.query(cls).filter_by(**gen_parts)
        fam = (keys.get('family.epithet') or
               keys.get('family.family') or
               keys.get('family'))

        if fam:
            query.join(Family).filter(Family.family == fam)

        from sqlalchemy.orm.exc import MultipleResultsFound
        try:
            return query.one_or_none()
        except MultipleResultsFound:
            return None
        return None

    def search_view_markup_pair(self):
        """provide the two lines describing object for SearchView row."""
        citation = self.markup(authors=True, for_search_view=True)
        return citation, utils.xml_safe(self.family)

    @hybrid_property
    def cites(self):
        """the cites status of this taxon, or None

        cites appendix number, one of I, II, or III.
        """
        return self._cites or self.family.cites

    @cites.expression
    def cites(cls):
        # pylint: disable=no-self-argument,protected-access
        # subquery required to get the joins in
        fam_cites = (
            select([Family.cites])
            .where(cls.family_id == Family.id)
            .scalar_subquery()
        )
        return case((cls._cites.is_not(None), cls._cites),
                    else_=fam_cites)

    @cites.setter
    def cites(self, value):
        self._cites = value

    def __str__(self):
        return Genus.str(self)

    @staticmethod
    def str(genus, author=False):
        if genus.genus is None:
            return ''
        parts = [genus.hybrid,
                 genus.genus,
                 genus.qualifier]
        if author and genus.author:
            parts.append(utils.xml_safe(genus.author))
        return ' '.join([s for s in parts if s not in ('', None)]).strip()

    def markup(self, authors=False, for_search_view=False):
        escape = utils.xml_safe
        string = ''
        if self.hybrid:
            string += self.hybrid + ' '
        if self.genus.isupper():
            string += escape(self.genus)
        else:
            string += f'<i>{escape(self.genus)}</i>'
        if self.qualifier:
            string += ' ' + self.qualifier
        if authors and self.author:
            author = escape(self.author)
            if for_search_view:
                author = '<span weight="light">' + author + '</span>'
            string += ' ' + author
        return string

    def top_level_count(self):
        species = db.get_active_children('species', self)
        accessions = [a for s in species for a in
                      db.get_active_children('accessions', s)]
        plants = [p for a in accessions for p in
                  db.get_active_children('plants', a)]
        return {(1, 'Genera'): set([self.id]),
                (2, 'Families'): set([self.family.id]),
                (3, 'Species'): len(species),
                (4, 'Accessions'): len(accessions),
                (5, 'Plantings'): len(plants),
                (6, 'Living plants'): sum(p.quantity for p in plants),
                (7, 'Locations'): set(p.location.id for p in plants),
                (8, 'Sources'): {a.source.source_detail.id for a in
                                 accessions if a.source and
                                 a.source.source_detail}}

    def has_children(self):
        cls = self.__class__.species.prop.mapper.class_
        from sqlalchemy import exists
        session = object_session(self)
        return bool(session.query(literal(True))
                    .filter(exists().where(cls.genus_id == self.id))
                    .scalar())

    def count_children(self):
        cls = self.__class__.species.prop.mapper.class_
        session = object_session(self)
        query = session.query(cls.id).filter(cls.genus_id == self.id)
        if prefs.prefs.get(prefs.exclude_inactive_pref):
            query = query.filter(cls.active.is_(True))
        return query.count()


# Listen for changes and update the full_name string
@event.listens_for(Genus, 'before_update')
def genus_before_update(_mapper, connection, target):
    for sp in target.species:
        session = object_session(sp)
        if sp in session.new or sp in session.dirty:
            # skip species that will trigger their own full name update
            return
        if sp.full_name != str(sp):
            vals = {'full_name': str(sp)}
            sp_table = Species.__table__
            connection.execute(update(sp_table)
                               .where(sp_table.c.id == sp.id)
                               .values(vals))
            # update history because above does not trigger history
            db.History.event_add('update',
                                 object_mapper(sp),
                                 connection,
                                 sp,
                                 **vals)


GenusNote = db.make_note_class('Genus')


class GenusSynonym(db.Base):
    """
    :Table name: genus_synonym
    """
    __tablename__ = 'genus_synonym'
    __table_args__ = (CheckConstraint("genus_id != synonym_id"),)

    # columns
    genus_id = Column(Integer, ForeignKey('genus.id'), nullable=False)

    # a genus can only be a synonum of one other genus
    synonym_id = Column(Integer, ForeignKey('genus.id'), nullable=False,
                        unique=True)

    def __str__(self):
        return f'{str(self.synonym)} ({self.synonym.family})'


# late bindings
from .family import Family, FamilySynonym
from .species_model import Species
from .species_editor import edit_species


class GenusEditorView(editor.GenericEditorView):

    _tooltips = {
        'gen_family_entry': _('The family name'),
        'gen_genus_entry': _('The genus name'),
        'gen_author_entry': _('The name or abbreviation of the author that '
                              'published this genus'),
        'syn_frame': _('A list of synonyms for this genus.\n\nTo add a '
                       'synonym enter a genus name and select one from '
                       'the list of completions.  Then click Add to add '
                       'it to the list of synonyms.'),
        'gen_cancel_button': _('Cancel your changes.'),
        'gen_ok_button': _('Save your changes.'),
        'gen_ok_and_add_button': _('Save your changes and add a '
                                   'species to this genus.'),
        'gen_next_button': _('Save your changes and add another '
                             'genus.'),
        'gen_hybrid_combo': _('Genus hybrid flag, a named hybrid ("x") or a '
                              'graft chimaera ("+")'),
    }

    def __init__(self, parent=None):

        filename = os.path.join(paths.lib_dir(), 'plugins', 'plants',
                                'genus_editor.glade')
        super().__init__(filename, parent=parent,
                         root_widget_name='genus_dialog')
        self.attach_completion('syn_entry', self.syn_cell_data_func)
        self.attach_completion('gen_family_entry')
        self.set_accept_buttons_sensitive(False)
        self.widgets.notebook.set_current_page(0)
        self.restore_state()

    def get_window(self):
        return self.widgets.genus_dialog

    @staticmethod
    def syn_cell_data_func(_column, renderer, model, itr):
        value = model[itr][0]
        author = None
        if value.author is None:
            author = ''
        else:
            author = utils.xml_safe(str(value.author))
        renderer.set_property('markup',
                              f'<i>{Genus.str(value)}</i> {author} '
                              f'(<small>{Family.str(value.family)}</small>)')

    def save_state(self):
        """save the current state of the gui to the preferences"""
        # for expander, pref in self.expanders_pref_map.iteritems():
        #     prefs[pref] = self.widgets[expander].get_expanded()
        pass

    def restore_state(self):
        """restore the state of the gui from the preferences"""
        # for expander, pref in self.expanders_pref_map.iteritems():
        #     expanded = prefs.get(pref, True)
        #     self.widgets[expander].set_expanded(expanded)
        pass

    def set_accept_buttons_sensitive(self, sensitive):
        self.widgets.gen_ok_button.set_sensitive(sensitive)
        self.widgets.gen_ok_and_add_button.set_sensitive(sensitive)
        self.widgets.gen_next_button.set_sensitive(sensitive)


class GenusEditorPresenter(editor.GenericEditorPresenter):

    widget_to_field_map = {'gen_family_entry': 'family',
                           'gen_hybrid_combo': 'hybrid',
                           'gen_genus_entry': 'genus',
                           'gen_author_entry': 'author',
                           'cites_combo': '_cites',
                           'subfamily_entry': 'subfamily',
                           'tribe_entry': 'tribe',
                           'subtribe_entry': 'subtribe'}

    def __init__(self, model, view):
        """
        :param model: should be an instance of class Genus
        :param view: should be an instance of GenusEditorView
        """
        super().__init__(model, view)
        self.session = object_session(model)

        from . import SynonymsPresenter
        self.synonyms_presenter = SynonymsPresenter(
            self, GenusSynonym, None, lambda session, text: (
                session.query(Genus).filter(Genus.genus.like(f'{text}%%'))
            )
        )
        self.init_enum_combo('gen_hybrid_combo', 'hybrid')
        self.init_enum_combo('cites_combo', '_cites')
        self.refresh_view()  # put model values in view

        # connect signals
        def fam_get_completions(text):
            query = self.session.query(Family)
            return (query.filter(Family.family.like(f'{text}%%'))
                    .order_by(Family.family))

        def on_select(value):
            for kid in self.view.widgets.message_box_parent.get_children():
                self.view.widgets.remove_parent(kid)
            # We need value to be an Family object before we can do anything
            # with it. (Avoids the first 2 letters prior to the completions
            # handler kicking in - i.e. when called programatically.)
            if not value or not isinstance(value, Family):
                return
            self.set_model_attr('family', value)
            syn = self.session.query(FamilySynonym).filter(
                FamilySynonym.synonym_id == value.id).first()
            if not syn:
                self.set_model_attr('family', value)
                self.refresh_cites_label()
                return
            msg = _('The family <b>%(synonym)s</b> is a synonym of '
                    '<b>%(family)s</b>.\n\nWould you like to choose '
                    '<b>%(family)s</b> instead?') % \
                {'synonym': syn.synonym, 'family': syn.family}
            box = None

            def on_response(_button, response):
                self.view.widgets.remove_parent(box)
                box.destroy()
                if response:
                    # populate the completions model on the entry so
                    # when we set the text it will match the
                    # completion and set the value
                    completion = self.view.widgets.gen_family_entry.\
                        get_completion()
                    utils.clear_model(completion)
                    model = Gtk.ListStore(object)
                    model.append([syn.family])
                    completion.set_model(model)
                    self.view.widgets.gen_family_entry.\
                        set_text(utils.nstr(syn.family))
                    # the family value should be set properly when the
                    # text is set on the entry but it doesn't hurt to
                    # duplicate it here
                    self.set_model_attr('family', syn.family)
                    self.refresh_cites_label()

            box = self.view.add_message_box(utils.MESSAGE_BOX_YESNO)
            box.message = msg
            box.on_response = on_response
            box.show()

        self.assign_completions_handler('gen_family_entry',
                                        fam_get_completions,
                                        on_select=on_select)
        self.assign_simple_handler('gen_hybrid_combo', 'hybrid',
                                   editor.StringOrNoneValidator())
        self.assign_simple_handler('gen_genus_entry', 'genus',
                                   editor.StringOrNoneValidator())
        self.assign_simple_handler('gen_author_entry', 'author',
                                   editor.StringOrNoneValidator())
        self.assign_simple_handler('cites_combo', 'cites',
                                   editor.StringOrNoneValidator())
        self.refresh_cites_label()
        self.assign_simple_handler('subfamily_entry', 'subfamily',
                                   editor.StringOrNoneValidator())
        self.assign_simple_handler('tribe_entry', 'tribe',
                                   editor.StringOrNoneValidator())
        self.assign_simple_handler('subtribe_entry', 'subtribe',
                                   editor.StringOrNoneValidator())

        notes_parent = self.view.widgets.notes_parent_box
        notes_parent.foreach(notes_parent.remove)
        self.notes_presenter = editor.NotesPresenter(self, 'notes',
                                                     notes_parent)

        if any(getattr(self.model, i) for i in ('subfamily',
                                                'tribe',
                                                'subtribe')):
            self.view.widget_set_expanded('supragen_expander', True)

        if self.model not in self.session.new:
            self.view.widgets.gen_ok_and_add_button.set_sensitive(True)

        self._dirty = False

    def refresh_cites_label(self, _widget=None):
        fam_cites = 'N/A'
        if self.model.family:
            if val := self.model.family.cites:
                fam_cites = val

        string = f'Family: {fam_cites}'
        self.view.set_label('cites_label', string)

    def __del__(self):
        # we have to delete the views in the child presenters manually
        # to avoid the circular reference
        del self.synonyms_presenter.view

    def cleanup(self):
        super().cleanup()
        self.synonyms_presenter.cleanup()
        self.notes_presenter.cleanup()

    def refresh_sensitivity(self):
        # TODO: check widgets for problems
        if self.model.family and self.model.genus:
            self.view.set_accept_buttons_sensitive(self.is_dirty())
        else:
            self.view.set_accept_buttons_sensitive(False)

    def set_model_attr(self, attr, value, validator=None):
        super().set_model_attr(attr, value, validator)
        self._dirty = True
        self.refresh_sensitivity()

    def is_dirty(self):
        return (self._dirty or self.synonyms_presenter.is_dirty() or
                self.notes_presenter.is_dirty())

    def refresh_view(self):
        for widget, field in self.widget_to_field_map.items():
            if field == 'family_id':
                value = getattr(self.model, 'family')
            else:
                value = getattr(self.model, field)
            self.view.widget_set_value(widget, value)


class GenusEditor(editor.GenericModelViewPresenterEditor):

    # these response values have to correspond to the response values in
    # the view
    RESPONSE_OK_AND_ADD = 11
    RESPONSE_NEXT = 22
    ok_responses = (RESPONSE_OK_AND_ADD, RESPONSE_NEXT)

    def __init__(self, model=None, parent=None):
        """
        :param model: Genus instance or None
        :param parent: None
        """
        if model is None:
            model = Genus()
        super().__init__(model, parent)
        if not parent and bauble.gui:
            parent = bauble.gui.window
        self.parent = parent
        self._committed = []

        view = GenusEditorView(parent=self.parent)
        self.presenter = GenusEditorPresenter(self.model, view)

        # set default focus
        if self.model.family is None:
            view.widgets.gen_family_entry.grab_focus()
        else:
            view.widgets.gen_genus_entry.grab_focus()

    def handle_response(self, response):
        """
        handle the response from self.presenter.start() in self.start()
        """
        not_ok_msg = _('Are you sure you want to lose your changes?')
        if response == Gtk.ResponseType.OK or response in self.ok_responses:
            try:
                if self.presenter.is_dirty():
                    self.commit_changes()
                    self._committed.append(self.model)
            except DBAPIError as e:
                msg = (_('Error committing changes.\n\n%s') %
                       utils.xml_safe(e.orig))
                utils.message_details_dialog(msg, str(e),
                                             Gtk.MessageType.ERROR)
                return False
            except Exception as e:  # pylint: disable=broad-except
                msg = (_('Unknown error when committing changes. See the '
                         'details for more information.\n\n%s') %
                       utils.xml_safe(e))
                utils.message_details_dialog(msg, traceback.format_exc(),
                                             Gtk.MessageType.ERROR)
                return False
        elif ((self.presenter.is_dirty() and
               utils.yes_no_dialog(not_ok_msg)) or not
              self.presenter.is_dirty()):
            self.session.rollback()
            return True
        else:
            # we should never really even get here since we would have
            # to hit something besides "OK" and the above elif should
            # handle all the possible cases
            return False

        # respond to responses
        more_committed = None
        if response == self.RESPONSE_NEXT:
            self.presenter.cleanup()
            model = Genus(family=self.model.family)
            gen_editor = GenusEditor(model=model, parent=self.parent)
            more_committed = gen_editor.start()
        elif response == self.RESPONSE_OK_AND_ADD:
            sp = Species(genus=self.model)
            more_committed = edit_species(model=sp, parent_view=self.parent)

        if more_committed is not None:
            if isinstance(more_committed, list):
                self._committed.extend(more_committed)
            else:
                self._committed.append(more_committed)

        return True

    def start(self):
        if self.session.query(Family).count() == 0:
            msg = _('You must first add or import at least one Family into '
                    'the database before you can add plants.')
            utils.message_dialog(msg)
            return None

        while True:
            response = self.presenter.start()
            self.presenter.view.save_state()
            if self.handle_response(response):
                break

        self.presenter.cleanup()
        self.session.close()  # cleanup session
        return self._committed


class GeneralGenusExpander(InfoExpander):
    """expander to present general information about a genus"""

    def __init__(self, widgets):
        super().__init__(_("General"), widgets)
        general_box = self.widgets.gen_general_box
        self.widgets.remove_parent(general_box)
        self.vbox.pack_start(general_box, True, True, 0)

        self.current_obj = None

    def update(self, row):
        """update the expander

        :param row: the row to get the values from
        """
        session = object_session(row)
        self.widget_set_value('gen_name_data',
                              f'<big>{row.markup()}</big> '
                              f'{utils.xml_safe(str(row.author))}',
                              markup=True)
        self.widget_set_value('gen_cites_data', row.cites or '')
        self.widget_set_value('gen_fam_data',
                              (utils.xml_safe(str(row.family))))

        # get the number of species
        nsp = (session.query(Species).
               join('genus').
               filter_by(id=row.id).count())
        self.widget_set_value('gen_nsp_data', nsp)

        # stop here if no GardenPlugin
        if 'GardenPlugin' not in pluginmgr.plugins:
            return

        from bauble.plugins.garden.accession import Accession
        from bauble.plugins.garden.plant import Plant

        # get number of accessions
        nacc = (session.query(Accession).
                join('species', 'genus').
                filter_by(id=row.id).count())
        if nacc == 0:
            self.widget_set_value('gen_nacc_data', nacc)
        else:
            nsp_in_acc = (session.query(Accession.species_id).
                          join('species', 'genus').
                          filter_by(id=row.id).distinct().count())
            self.widget_set_value('gen_nacc_data',
                                  f'{nacc} in {nsp_in_acc} species')

        # get the number of plants in the genus
        nplants = (session.query(Plant).
                   join('accession', 'species', 'genus').
                   filter_by(id=row.id).count())
        if nplants == 0:
            self.widget_set_value('gen_nplants_data', nplants)
        else:
            nacc_in_plants = (session.query(Plant.accession_id).
                              join('accession', 'species', 'genus').
                              filter_by(id=row.id).distinct().count())
            self.widget_set_value('gen_nplants_data',
                                  f'{nplants} in {nacc_in_plants} accessions')

        if bauble.gui:
            on_clicked_search = utils.generate_on_clicked(
                bauble.gui.send_command
            )
        else:
            # for testing...
            on_clicked_search = utils.generate_on_clicked(lambda *args: None)

        from .species import on_taxa_clicked

        utils.make_label_clickable(self.widgets.gen_fam_data,
                                   on_taxa_clicked,
                                   row.family)

        utils.make_label_clickable(
            self.widgets.gen_nsp_data,
            on_clicked_search,
            f'species where genus.genus="{row.genus}" and '
            f'genus.qualifier="{row.qualifier}"'
        )

        utils.make_label_clickable(
            self.widgets.gen_nacc_data,
            on_clicked_search,
            f'accession where species.genus.genus="{row.genus}" and '
            f'species.genus.qualifier="{row.qualifier}"'
        )

        utils.make_label_clickable(
            self.widgets.gen_nplants_data,
            on_clicked_search,
            f'plant where accession.species.genus.genus="{row.genus}" and '
            f'accession.species.genus.qualifier="{row.qualifier}"'
        )


class SynonymsExpander(InfoExpander):

    EXPANDED_PREF = 'infobox.genus_synonyms_expanded'

    def __init__(self, widgets):
        super().__init__(_("Synonyms"), widgets)
        synonyms_box = self.widgets.gen_synonyms_box
        self.widgets.remove_parent(synonyms_box)
        self.vbox.pack_start(synonyms_box, True, True, 0)

    def update(self, row):
        """update the expander

        :param row: the row to get the values from
        """
        self.reset()
        syn_box = self.widgets.gen_synonyms_box
        # remove old labels
        syn_box.foreach(syn_box.remove)
        logger.debug("genus %s is synonym of %s and has synonyms %s", row,
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
            label.set_markup(Genus.str(row.accepted, author=True))
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
                label.set_markup(Genus.str(syn, author=True))
                box.add(label)
                utils.make_label_clickable(label, on_clicked, syn)
                syn_box.pack_start(box, False, False, 0)
            self.show_all()
            self.set_sensitive(True)


class GenusInfoBox(InfoBox):
    GENUS_WEB_BUTTON_DEFS_PREFS = 'web_button_defs.genus'

    def __init__(self):
        button_defs = []
        buttons = prefs.prefs.itersection(self.GENUS_WEB_BUTTON_DEFS_PREFS)
        for name, button in buttons:
            button['name'] = name
            button_defs.append(button)

        super().__init__()
        filename = os.path.join(paths.lib_dir(), 'plugins', 'plants',
                                'infoboxes.glade')
        self.widgets = utils.load_widgets(filename)
        self.general = GeneralGenusExpander(self.widgets)
        self.add_expander(self.general)
        self.synonyms = SynonymsExpander(self.widgets)
        self.add_expander(self.synonyms)
        self.links = LinksExpander('notes', button_defs)
        self.add_expander(self.links)
        self.props = PropertiesExpander()
        self.add_expander(self.props)

        if 'GardenPlugin' not in pluginmgr.plugins:
            self.widgets.remove_parent('gen_nacc_label')
            self.widgets.remove_parent('gen_nacc_data')
            self.widgets.remove_parent('gen_nplants_label')
            self.widgets.remove_parent('gen_nplants_data')

    def update(self, row):
        self.general.update(row)
        self.synonyms.update(row)
        self.links.update(row)
        self.props.update(row)


db.Genus = Genus
