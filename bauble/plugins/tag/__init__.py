# Copyright (c) 2005,2006,2007,2008,2009 Brett Adams <brett@belizebotanic.org>
# Copyright (c) 2012-2017 Mario Frasca <mario@anche.no>
# Copyright (c) 2021-2023 Ross Demuth <rossdemuth123@gmail.com>
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
tag plugin
"""

import os
import traceback
from importlib import import_module

import logging
logger = logging.getLogger(__name__)

from gi.repository import Gtk
from gi.repository import Gio
from gi.repository import GLib
from gi.repository import Gdk

from sqlalchemy import (Column,
                        Unicode,
                        UnicodeText,
                        Integer,
                        String,
                        ForeignKey)
from sqlalchemy.orm import relationship
from sqlalchemy.orm.exc import DetachedInstanceError
from sqlalchemy import and_
from sqlalchemy.exc import DBAPIError, InvalidRequestError
from sqlalchemy.orm.session import object_session

import bauble
from bauble import db, editor, pluginmgr, paths, search, utils, prefs
from bauble.view import (InfoBox,
                         InfoExpander,
                         SearchView,
                         HistoryView,
                         Action,
                         PropertiesExpander)

from bauble.editor import GenericEditorView, GenericEditorPresenter


class TagsMenuManager:

    ACTIVATED_ACTION_NAME = 'tag_activated'
    REMOVE_CONTEXT_ACTION_NAME = 'context_tag_remove'
    APPLY_CONTEXT_ACTION_NAME = 'context_tag_apply'
    REMOVE_ACTIVE_ACTION_NAME = 'remove_active_tag'
    APPLY_ACTIVE_ACTION_NAME = 'apply_active_tag'
    TAG_ACTION_NAME = 'tag_selection'

    def __init__(self):
        self.menu_pos = None
        self.active_tag_name = None
        self.apply_active_tag_action = None
        self.remove_active_tag_action = None
        self.select_tag_action = None
        self.tag_selection_action = None

    def reset(self, make_active_tag=None):
        """initialize or replace Tags menu in main menu."""
        # setting active_tag_name here likely doesn't do much as its only
        # called when adding a new tag in TagItemGUI. (which should make it the
        # last ID and hence select it when rebuilding anyway.)
        self.active_tag_name = make_active_tag and make_active_tag.tag
        tags_menu = self.build_menu()
        if self.menu_pos is None:
            self.menu_pos = bauble.gui.add_menu(_("Tags"), tags_menu)
        else:
            bauble.gui.remove_menu(self.menu_pos)
            self.menu_pos = bauble.gui.add_menu(_("Tags"), tags_menu)
        self.refresh()

    def reset_active_tag_name(self):
        """Reset the active tag to latest by ID if current is not valid."""
        session = db.Session()
        if (not self.active_tag_name or (
            self.active_tag_name and not
                session.query(Tag)
                .filter_by(tag=self.active_tag_name)
                .first())):
            last_tag = session.query(Tag).order_by(Tag.id.desc()).first()
            self.active_tag_name = last_tag and last_tag.tag
        session.close()

    def refresh(self, selected_values=None):
        """Refresh the tag menu, set the active tag, enable/disable menu items.
        """
        self.reset_active_tag_name()

        if self.select_tag_action and self.active_tag_name:
            self.select_tag_action.set_state(
                GLib.Variant.new_string(self.active_tag_name)
            )

        if not selected_values and bauble.gui:
            view = bauble.gui.get_view()
            if isinstance(view, SearchView):
                selected_values = view.get_selected_values()

        if selected_values:
            if self.active_tag_name and self.apply_active_tag_action:
                self.apply_active_tag_action.set_enabled(True)
                self.remove_active_tag_action.set_enabled(True)
            if self.tag_selection_action:
                self.tag_selection_action.set_enabled(True)
        elif self.tag_selection_action:
            self.apply_active_tag_action.set_enabled(False)
            self.remove_active_tag_action.set_enabled(False)
            self.tag_selection_action.set_enabled(False)

    def on_tag_change_state(self, action, tag_name):
        action.set_state(tag_name)
        self.active_tag_name = tag_name.unpack()
        bauble.gui.send_command(f'tag={tag_name}')
        view = bauble.gui.get_view()
        if isinstance(view, SearchView):
            GLib.idle_add(
                view.results_view.expand_to_path, Gtk.TreePath.new_first()
            )
        self.refresh()

    @staticmethod
    def on_context_menu_apply_activated(_action, tag_name):
        view = bauble.gui.get_view()
        values = view.get_selected_values()
        # unpack to python type
        tag_objects(tag_name.unpack(), values)
        view.update_bottom_notebook(values)

    @staticmethod
    def on_context_menu_remove_activated(_action, tag_name):
        view = bauble.gui.get_view()
        values = view.get_selected_values()
        # unpack to python type
        untag_objects(tag_name.unpack(), values)
        view.update_bottom_notebook(values)

    def context_menu_callback(self, selected):
        """Build the SearchView context menu tag section for the selected
        items.
        """
        # Only add actions if they have not already been added...  Adding here
        # to wait for bauble.gui.
        if not bauble.gui.lookup_action(self.APPLY_CONTEXT_ACTION_NAME):

            bauble.gui.add_action(self.APPLY_CONTEXT_ACTION_NAME,
                                  self.on_context_menu_apply_activated,
                                  param_type=GLib.VariantType('s'))

            bauble.gui.add_action(self.REMOVE_CONTEXT_ACTION_NAME,
                                  self.on_context_menu_remove_activated,
                                  param_type=GLib.VariantType('s'))

        section = Gio.Menu()
        tag_item = Gio.MenuItem.new(_('Tag Selection'),
                                    f'win.{self.TAG_ACTION_NAME}')
        section.append_item(tag_item)

        session = object_session(selected[0])
        query = session.query(Tag)
        # bail early if no tags
        if not query.first():
            return section

        all_tagged = None
        attached_tags = set()
        for item in selected:
            tags = Tag.attached_to(item)
            if all_tagged is None:
                all_tagged = set(tags)
            elif all_tagged:
                all_tagged.intersection_update(tags)
            attached_tags.update(tags)

        apply_tags = set()

        if all_tagged:
            query = query.filter(Tag.id.notin_([i.id for i in all_tagged]))

        for tag in query:
            apply_tags.add(tag)

        if apply_tags:
            apply_submenu = Gio.Menu()
            section.append_submenu('Apply Tag', apply_submenu)
            for tag in apply_tags:
                menu_item = Gio.MenuItem.new(
                    tag.tag.replace('_', '__'),
                    f'win.{self.APPLY_CONTEXT_ACTION_NAME}::{tag.tag}'
                )
                apply_submenu.append_item(menu_item)

        if attached_tags:
            remove_submenu = Gio.Menu()
            section.append_submenu('Remove Tag', remove_submenu)

            for tag in attached_tags:
                menu_item = Gio.MenuItem.new(
                    tag.tag.replace('_', '__'),
                    f'win.{self.REMOVE_CONTEXT_ACTION_NAME}::{tag.tag}'
                )
                remove_submenu.append_item(menu_item)

        return section

    def build_menu(self):
        """build tags menu based on current data."""
        tags_menu = Gio.Menu()

        if bauble.gui:
            # set up actions
            if not self.tag_selection_action:
                self.tag_selection_action = bauble.gui.add_action(
                    self.TAG_ACTION_NAME, _on_add_tag_activated
                )

            if not self.apply_active_tag_action:
                self.apply_active_tag_action = bauble.gui.add_action(
                    self.APPLY_ACTIVE_ACTION_NAME,
                    self.on_apply_active_tag_activated
                )

            if not self.remove_active_tag_action:
                self.remove_active_tag_action = bauble.gui.add_action(
                    self.REMOVE_ACTIVE_ACTION_NAME,
                    self.on_remove_active_tag_activated
                )

        # tag selection
        add_tag_menu_item = Gio.MenuItem.new(_('Tag Selection'),
                                             f'win.{self.TAG_ACTION_NAME}')

        # apply active tag
        apply_active_tag_menu_item = Gio.MenuItem.new(
            _('Apply Active Tag'), f'win.{self.APPLY_ACTIVE_ACTION_NAME}'
        )

        # remove active tag
        remove_active_tag_menu_item = Gio.MenuItem.new(
            _('Remove Active Tag'), f'win.{self.REMOVE_ACTIVE_ACTION_NAME}'
        )

        app = Gio.Application.get_default()
        if app:
            # tag selection
            app.set_accels_for_action(f'win.{self.TAG_ACTION_NAME}',
                                      ['<Control>t'])
            # apply active tag
            app.set_accels_for_action(f'win.{self.APPLY_ACTIVE_ACTION_NAME}',
                                      ['<Control>y'])
            # remove active tag
            app.set_accels_for_action(f'win.{self.REMOVE_ACTIVE_ACTION_NAME}',
                                      ['<Control><Shift>y'])

        tags_menu.append_item(add_tag_menu_item)

        session = db.Session()
        query = session.query(Tag)
        has_tags = query.first()

        if has_tags:
            if (bauble.gui and not self.select_tag_action):
                # setup the select_tag_action only if there are existing tags.
                # Most likely little harm in leaving the action in place even
                # if all tags are deleted, the menu is unavailable anyway.
                # set a valid value for self.active_tag_name
                self.reset_active_tag_name()
                variant = GLib.Variant.new_string(self.active_tag_name)
                self.select_tag_action = Gio.SimpleAction.new_stateful(
                    self.ACTIVATED_ACTION_NAME, variant.get_type(), variant
                )
                self.select_tag_action.connect('change-state',
                                               self.on_tag_change_state)

                bauble.gui.window.add_action(self.select_tag_action)

            section = Gio.Menu()

            for tag in query.order_by(Tag.tag):
                menu_item = Gio.MenuItem.new(
                    tag.tag.replace('_', '__'),
                    f'win.{self.ACTIVATED_ACTION_NAME}::{tag.tag}'
                )
                section.append_item(menu_item)

            tags_menu.append_section(None, section)

            section = Gio.Menu()
            section.append_item(apply_active_tag_menu_item)
            section.append_item(remove_active_tag_menu_item)
            tags_menu.append_section(None, section)
            if bauble.gui:
                self.apply_active_tag_action.set_enabled(False)
                self.remove_active_tag_action.set_enabled(False)
        session.close()
        return tags_menu

    def toggle_tag(self, applying):
        view = bauble.gui.get_view()
        values = None
        try:
            values = view.get_selected_values()
        except AttributeError:
            msg = _('In order to tag or untag an item you must first search '
                    'for something and select one of the results.')
            bauble.gui.show_message_box(msg)
            return
        if len(values) == 0:
            msg = _('Please select something in the search results.')
            utils.message_dialog(msg)
            return
        if self.active_tag_name is None:
            msg = _('Please make sure a tag is active.')
            utils.message_dialog(msg)
            return
        applying(self.active_tag_name, values)
        view.update_bottom_notebook(values)

    def on_apply_active_tag_activated(self, _action, _param):
        logger.debug("you're applying %s to the selection",
                     self.active_tag_name)
        self.toggle_tag(applying=tag_objects)

    def on_remove_active_tag_activated(self, _action, _param):
        logger.debug("you're removing %s from the selection",
                     self.active_tag_name)
        self.toggle_tag(applying=untag_objects)


tags_menu_manager = TagsMenuManager()


def edit_callback(tags):
    tag = tags[0]
    if tag is None:
        tag = Tag()
    view = GenericEditorView(
        os.path.join(paths.lib_dir(), 'plugins', 'tag', 'tag.glade'),
        parent=None,
        root_widget_name='tag_dialog')
    presenter = TagEditorPresenter(tag, view, refresh_view=True)
    error_state = presenter.start()
    if error_state:
        presenter.session.rollback()
    else:
        presenter.commit_changes()
        tags_menu_manager.reset()
    presenter.cleanup()
    return error_state


def remove_callback(tags):
    """
    :param tags: a list of :class:`Tag` objects.
    """
    tag = tags[0]
    tlst = []
    for tag in tags:
        tlst.append(f'{tag.__class__.__name__}: {utils.xml_safe(tag)}')
    msg = _("Are you sure you want to remove %s?") % ', '.join(i for i in tlst)
    if not utils.yes_no_dialog(msg):
        return False
    session = object_session(tag)
    for tag in tags:
        session.delete(tag)
    try:
        utils.remove_from_results_view(tags)
        session.commit()
    except Exception as e:   # pylint: disable=broad-except
        msg = _('Could not delete.\n\n%s') % utils.xml_safe(e)
        utils.message_details_dialog(msg, traceback.format_exc(),
                                     Gtk.MessageType.ERROR)
        session.rollback()

    # reinitialize the tag menu
    tags_menu_manager.reset()
    return True


edit_action = Action('tag_edit', _('_Edit'),
                     callback=edit_callback,
                     accelerator='<ctrl>e')

remove_action = Action('tag_remove', _('_Delete'),
                       callback=remove_callback,
                       accelerator='<ctrl>Delete', multiselect=True)

tag_context_menu = [edit_action, remove_action]


class TagEditorPresenter(GenericEditorPresenter):

    widget_to_field_map = {
        'tag_name_entry': 'tag',
        'tag_desc_textbuffer': 'description'}

    view_accept_buttons = ['tag_ok_button', 'tag_cancel_button', ]

    def on_tag_desc_textbuffer_changed(self, widget, value=None):
        return GenericEditorPresenter.on_textbuffer_changed(
            self, widget, value, attr='description')


class TagItemGUI(editor.GenericEditorView):
    """Interface for tagging individual items in the results of the SearchView
    """
    def __init__(self, values):
        filename = os.path.join(paths.lib_dir(), 'plugins', 'tag',
                                'tag.glade')
        super().__init__(filename)
        self.item_data_label = self.widgets.items_data
        self.values = values
        self.item_data_label.set_text(', '.join([str(s) for s in self.values]))
        self.connect(self.widgets.new_button,
                     'clicked', self.on_new_button_clicked)
        self.tag_tree = self.widgets.tag_tree

    def get_window(self):
        return self.widgets.tag_item_dialog

    def on_new_button_clicked(self, *_args):
        """create a new tag"""
        session = db.Session()
        tag = Tag(description='')
        session.add(tag)
        error_state = edit_callback([tag])
        if not error_state:
            model = self.tag_tree.get_model()
            model.append([False, tag.tag, False])
            tags_menu_manager.reset(tag)
        session.close()

    def on_toggled(self, renderer, path):
        """tag or untag the objs in self.values """
        active = not renderer.get_active()
        model = self.tag_tree.get_model()
        itr = model.get_iter(path)
        model[itr][0] = active
        model[itr][2] = False
        name = model[itr][1]
        if active:
            tag_objects(name, self.values)
        else:
            untag_objects(name, self.values)

    def build_tag_tree_columns(self):
        """Build the tag tree columns."""
        renderer = Gtk.CellRendererToggle()
        self.connect(renderer, 'toggled', self.on_toggled)
        renderer.set_property('activatable', True)
        toggle_column = Gtk.TreeViewColumn(None, renderer)
        toggle_column.add_attribute(renderer, "active", 0)
        toggle_column.add_attribute(renderer, "inconsistent", 2)

        renderer = Gtk.CellRendererText()
        tag_column = Gtk.TreeViewColumn(None, renderer, text=1)

        return [toggle_column, tag_column]

    def on_key_released(self, _widget, event):
        """When the user hits the delete key on a selected tag in the tag
        editor delete the tag
        """
        keyname = Gdk.keyval_name(event.keyval)
        if keyname != "Delete":
            return
        model, row_iter = self.tag_tree.get_selection().get_selected()
        tag_name = model[row_iter][1]
        msg = _('Are you sure you want to delete the tag "%s"?') % tag_name
        if not utils.yes_no_dialog(msg):
            return
        session = db.Session()
        try:
            query = session.query(Tag)
            tag = query.filter_by(tag=str(tag_name)).one()
            session.delete(tag)
            session.commit()
            model.remove(row_iter)
            tags_menu_manager.reset()
            view = bauble.gui.get_view()
            if hasattr(view, 'update'):
                view.update()
        except Exception as e:
            utils.message_details_dialog(utils.xml_safe(str(e)),
                                         traceback.format_exc(),
                                         Gtk.MessageType.ERROR)
        finally:
            session.close()

    def start(self):
        # we remove the old columns and create new ones each time the
        # tag editor is started since we have to connect and
        # disconnect the toggled signal each time
        for col in self.tag_tree.get_columns():
            self.tag_tree.remove_column(col)
        columns = self.build_tag_tree_columns()
        for col in columns:
            self.tag_tree.append_column(col)

        # create the model
        model = Gtk.ListStore(bool, str, bool)
        tag_all, tag_some, _tag_none = get_tag_ids(self.values)
        session = db.Session()  # we need close it
        tag_query = session.query(Tag)
        for tag in tag_query:
            model.append([tag.id in tag_all, tag.tag, tag.id in tag_some])
        self.tag_tree.set_model(model)

        self.tag_tree.add_events(Gdk.EventMask.KEY_RELEASE_MASK)
        self.connect(self.tag_tree, "key-release-event", self.on_key_released)

        response = self.get_window().run()
        while response not in (Gtk.ResponseType.OK,
                               Gtk.ResponseType.DELETE_EVENT):
            response = self.get_window().run()

        self.get_window().hide()
        self.disconnect_all()
        session.close()


class Tag(db.Base):
    """
    :Table name: tag
    :Columns:
      tag: :class:`sqlalchemy.types.Unicode`
        The tag name.
      description: :class:`sqlalchemy.types.Unicode`
        A description of this tag.
    """
    __tablename__ = 'tag'

    # columns
    tag = Column(Unicode(64), unique=True, nullable=False)
    description = Column(UnicodeText)

    # relations
    _objects = relationship('TaggedObj', cascade='all, delete-orphan',
                            backref='tag')

    __my_own_timestamp = None
    __last_objects = None

    retrieve_cols = ['id', 'tag']

    @classmethod
    def retrieve(cls, session, keys):
        parts = {k: v for k, v in keys.items() if k in cls.retrieve_cols}
        if parts:
            return session.query(cls).filter_by(**parts).one_or_none()
        return None

    def __str__(self):
        try:
            return str(self.tag)
        except DetachedInstanceError:
            return db.Base.__str__(self)

    def markup(self):
        return f'{self.tag} Tag'

    def tag_objects(self, objects):
        session = object_session(self)
        for obj in objects:
            cls = and_(TaggedObj.obj_class == _classname(obj),
                       TaggedObj.obj_id == obj.id,
                       TaggedObj.tag_id == self.id)
            ntagged = session.query(TaggedObj).filter(cls).count()
            if ntagged == 0:
                tagged_obj = TaggedObj(obj_class=_classname(obj),
                                       obj_id=obj.id,
                                       tag=self)
                session.add(tagged_obj)

    @property
    def objects(self):
        """return all tagged objects

        reuse last result if nothing was changed in the database since
        list was retrieved.
        """
        if self.__my_own_timestamp is not None:
            # should I update my list?
            session = object_session(self)
            # tag must have been removed or session lost
            if session is None:
                return []

            last_history = (session.query(db.History.timestamp)
                            .order_by(db.History.timestamp.desc())
                            .limit(1)
                            .scalar())
            # last_history can be None when no history (i.e. a recent restore
            # of older data where history table has been dropped) note:
            # __last_objects will be None first run.
            if last_history and last_history > self.__my_own_timestamp:
                self.__last_objects = None

        if self.__last_objects is None:
            # here I update my list
            from datetime import datetime
            self.__my_own_timestamp = datetime.now().astimezone(tz=None)
            self.__last_objects = self.get_tagged_objects()
        # here I return my list
        return self.__last_objects

    def is_tagging(self, obj):
        """tell whether self tags obj."""
        return obj in self.objects

    def get_tagged_objects(self):
        """Get all object tagged with tag and clean up any that are left
        hanging.
        """
        session = object_session(self)

        if session is None:
            return []

        items = []
        for obj in self._objects:
            if result := _get_tagged_object_pair(obj):
                mapper, obj_id = result
                rec = session.query(mapper).filter_by(id=obj_id).first()
                if rec:
                    items.append(rec)
                else:
                    logger.debug('deleting tagged_obj: %s', obj)
                    # delete any tagged objects no longer in the database
                    session.delete(obj)
                    session.commit()
        return items

    @classmethod
    def attached_to(cls, obj):
        """return the list of tags attached to obj

        this is a class method, so more classes can invoke it.
        """
        session = object_session(obj)
        if not session:
            return []
        modname = type(obj).__module__
        clsname = type(obj).__name__
        full_cls_name = f'{modname}.{clsname}'
        qto = session.query(TaggedObj).filter(
            TaggedObj.obj_class == full_cls_name,
            TaggedObj.obj_id == obj.id)
        return [i.tag for i in qto.all()]

    def search_view_markup_pair(self):
        """provide the two lines describing object for SearchView row."""
        logging.debug('entering search_view_markup_pair %s', self)
        objects = self.objects
        classes = set(type(o) for o in objects)
        if len(classes) == 1:
            fine_prints = _("tagging %(1)s objects of type %(2)s") % {
                '1': len(objects),
                '2': classes.pop().__name__}
        elif len(classes) == 0:
            fine_prints = _("tagging nothing")
        else:
            fine_prints = (_("tagging %(objs)s objects of %(clss)s different "
                             "types") % {'objs': len(objects),
                                         'clss': len(classes)})
            if len(classes) < 4:
                fine_prints += ': '
                fine_prints += ', '.join(sorted(t.__name__ for t in classes))
        first = (f'{utils.xml_safe(self)} - '
                 f'<span weight="light">{fine_prints}</span>')
        fine_print = (self.description or '').replace('\n', ' ')[:256]
        second = (f'({type(self).__name__}) - '
                  f'<span weight="light">{fine_print}</span>')
        return first, second

    def has_children(self):
        from sqlalchemy import exists
        session = object_session(self)
        return session.query(
            exists().where(TaggedObj.tag_id == self.id)
        ).scalar()

    def count_children(self):
        session = object_session(self)
        if prefs.prefs.get(prefs.exclude_inactive_pref):
            return len([i for i in self.objects if getattr(i, 'active', True)])
        return (session.query(TaggedObj.id)
                .filter(TaggedObj.tag_id == self.id)
                .count())


class TaggedObj(db.Base):
    """
    :Table name: tagged_obj

    :Columns:
        *obj_id*
            interger, The id of the tagged object.
        *obj_class*
            The class name of the tagged object.
        *tag_id*
            A ForeignKey to :class:`Tag`.
    """
    __tablename__ = 'tagged_obj'

    # columns
    obj_id = Column(Integer, autoincrement=False)
    obj_class = Column(String(128))
    tag_id = Column(Integer, ForeignKey('tag.id'))

    def __str__(self):
        return f'{self.obj_class}: {self.obj_id}'


def _get_tagged_object_pair(obj):
    """
    :param obj: a TaggedObj instance
    """
    try:
        module_name, _part, cls_name = str(obj.obj_class).rpartition('.')
        module = import_module(module_name)
        cls = getattr(module, cls_name)
        return cls, obj.obj_id
    except (KeyError, DBAPIError, AttributeError) as e:
        logger.warning('_get_tagged_object_pair (%s) error: %s:%s', obj,
                       type(e).__name__, e)
    return None


def create_named_empty_tag(name):
    """make sure the named tag exists"""
    session = db.Session()
    try:
        tag = session.query(Tag).filter_by(tag=name).one()
    except InvalidRequestError as e:
        logger.debug("create_named_empty_tag: %s - %s", type(e).__name__, e)
        tag = Tag(tag=name)
        session.add(tag)
        session.commit()
    session.close()


def untag_objects(name, objs):
    """
    Remove the tag name from objs.

    :param name: The name of the tag
    :type name: str
    :param objs: The list of objects to untag.
    :type objs: list
    """
    name = utils.nstr(name)
    if not objs:
        create_named_empty_tag(name)
        return
    session = object_session(objs[0])
    try:
        tag = session.query(Tag).filter_by(tag=name).one()
    except Exception as e:
        logger.info("Can't remove non existing tag from non-empty list of "
                    "objects %s - %s", type(e).__name__, e)
        return
    objs = set((_classname(y), y.id) for y in objs)
    for item in tag._objects:
        if (item.obj_class, item.obj_id) not in objs:
            continue
        obj = session.query(TaggedObj).filter_by(id=item.id).one()
        session.delete(obj)
    session.commit()


# create the classname stored in the tagged_obj table
def _classname(obj):
    return f'{type(obj).__module__}.{type(obj).__name__}'


def tag_objects(name, objects):
    """create or retrieve a tag, use it to tag list of objects

    :param name: The tag name, if it's a str object then it will be
      converted to unicode() using the default encoding. If a tag with
      this name doesn't exist it will be created
    :type name: str
    :param objects: A list of mapped objects to tag.
    :type objects: list
    """
    name = utils.nstr(name)
    if not objects:
        create_named_empty_tag(name)
        return
    session = object_session(objects[0])
    tag = session.query(Tag).filter_by(tag=name).one_or_none()
    if not tag:
        tag = Tag(tag=name)
        session.add(tag)
    tag.tag_objects(objects)
    session.commit()


def get_tag_ids(objs):
    """Return a 3-tuple describing which tags apply to objs.

    the result tuple is composed of lists.  First list contains the id of
    the tags that apply to all objs.  Second list contains the id of the
    tags that apply to one or more objs, but not all.  Third list contains
    the id of the tags that do not apply to any objs.

    :param objs: a list or tuple of objects

    """
    session = object_session(objs[0])
    tag_id_query = session.query(Tag.id).join('_objects')
    starting_now = True
    s_all = set()
    s_some = set()
    s_none = set(i[0] for i in tag_id_query)  # per default none apply
    for obj in objs:
        clause = and_(TaggedObj.obj_class == _classname(obj),
                      TaggedObj.obj_id == obj.id)
        applied_tag_ids = [r[0] for r in tag_id_query.filter(clause)]
        if starting_now:
            s_all = set(applied_tag_ids)
            starting_now = False
        else:
            s_all.intersection_update(applied_tag_ids)
        s_some.update(applied_tag_ids)
        s_none.difference_update(applied_tag_ids)

    s_some.difference_update(s_all)
    return (s_all, s_some, s_none)


def _on_add_tag_activated(_action, _param):
    # get the selection from the search view
    view = bauble.gui.get_view()
    values = None
    try:
        values = view.get_selected_values()
    except AttributeError:
        msg = _('In order to tag an item you must first search for '
                'something and select one of the results.')
        bauble.gui.show_message_box(msg)
        return
    if len(values) == 0:
        msg = _('Nothing selected')
        utils.message_dialog(msg)
        return
    tagitem = TagItemGUI(values)
    tagitem.start()
    view.update_bottom_notebook(values)


class GeneralTagExpander(InfoExpander):
    """
    generic information about a tag.  Displays the tag name, description and a
    table of the types and count(with link) of tagged items.
    """

    def __init__(self, widgets):
        super().__init__(_("General"), widgets)
        general_box = self.widgets.general_box
        self.widgets.general_window.remove(general_box)
        self.vbox.pack_start(general_box, True, True, 0)
        self.table_cells = []

    def update(self, row):
        self.widget_set_value('ib_name_label', row.tag)
        self.widget_set_value('ib_description_label', row.description)
        objects = row.objects
        classes = set(type(o) for o in objects)
        row_no = 1
        grid = self.widgets.tag_ib_general_grid

        for widget in self.table_cells:
            grid.remove(widget)

        self.table_cells = []
        for cls in classes:
            obj_ids = [str(o.id) for o in objects if isinstance(o, cls)]
            lab = Gtk.Label()
            lab.set_xalign(0)
            lab.set_yalign(0.5)
            lab.set_text(cls.__name__)
            grid.attach(lab, 0, row_no, 1, 1)

            eventbox = Gtk.EventBox()
            label = Gtk.Label()
            label.set_xalign(0)
            label.set_yalign(0.5)
            eventbox.add(label)
            grid.attach(eventbox, 1, row_no, 1, 1)
            label.set_text(f' {len(obj_ids)} ')
            utils.make_label_clickable(
                label,
                lambda l, e, x: bauble.gui.send_command(x),
                f'{cls.__name__.lower()} where id in {", ".join(obj_ids)}'
            )

            self.table_cells.append(lab)
            self.table_cells.append(eventbox)

            row_no += 1
        grid.show_all()


class TagInfoBox(InfoBox):
    """
    - general info
    - source
    """
    def __init__(self):
        super().__init__()
        filename = os.path.join(paths.lib_dir(), "plugins", "tag",
                                "tag.glade")
        self.widgets = utils.load_widgets(filename)
        self.general = GeneralTagExpander(self.widgets)
        self.add_expander(self.general)
        self.props = PropertiesExpander()
        self.add_expander(self.props)

    def update(self, row):
        self.general.update(row)
        self.props.update(row)


class TagPlugin(pluginmgr.Plugin):
    provides = {'Tag': Tag}

    @classmethod
    def init(cls):
        pluginmgr.provided.update(cls.provides)
        from functools import partial
        mapper_search = search.get_strategy('MapperSearch')
        mapper_search.add_meta(('tag', 'tags'), Tag, ['tag'])
        SearchView.row_meta[Tag].set(
            children=partial(db.get_active_children,
                             partial(db.natsort, 'objects')),
            infobox=TagInfoBox,
            context_menu=tag_context_menu)
        tag_meta = {
            'page_widget': 'taginfo_scrolledwindow',
            'fields_used': ['tag', 'description'],
            'glade_name': os.path.join(paths.lib_dir(),
                                       'plugins/tag/tag.glade'),
            'name': _('Tags'),
            'row_activated': cls.on_tag_bottom_info_activated,
        }
        # Only want to add this once (incase of opening another connection),
        # hence directly accessing underlying dict with setdefault
        # If no 'label' key in the Meta object add_page_to_bottom_notebook will
        # be called again adding another page.
        SearchView.bottom_info.data.setdefault(Tag, tag_meta)
        SearchView.context_menu_callbacks.add(
            tags_menu_manager.context_menu_callback
        )
        SearchView.cursor_changed_callbacks.add(
            tags_menu_manager.refresh
        )
        if bauble.gui:
            bauble.gui.set_view_callbacks.add(tags_menu_manager.refresh)
            tags_menu_manager.reset()

        HistoryView.add_translation_query(
            'tagged_obj', 'tag', '{table} where _objects.id = {obj_id}'
        )

    @staticmethod
    def on_tag_bottom_info_activated(tree, path, _column):
        tag = repr(tree.get_model()[path][0])
        bauble.gui.send_command(f"tag={tag}")


plugin = TagPlugin
