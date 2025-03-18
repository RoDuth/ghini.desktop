# Copyright 2008-2010 Brett Adams
# Copyright 2015 Mario Frasca <mario@anche.no>.
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
Location table definition and related
"""
import logging
import os
import traceback
from pathlib import Path
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

from gi.repository import Gtk
from sqlalchemy import Column
from sqlalchemy import Unicode
from sqlalchemy import UnicodeText
from sqlalchemy import literal
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from sqlalchemy.orm import backref
from sqlalchemy.orm import deferred
from sqlalchemy.orm import relationship
from sqlalchemy.orm import validates
from sqlalchemy.orm.session import object_session

import bauble
from bauble import btypes as types
from bauble import db
from bauble import paths
from bauble import prefs
from bauble import utils
from bauble.editor import GenericEditorPresenter
from bauble.editor import GenericEditorView
from bauble.editor import GenericModelViewPresenterEditor
from bauble.editor import NotesPresenter
from bauble.editor import PicturesPresenter
from bauble.editor import PresenterMapMixin
from bauble.editor import StringOrNoneValidator
from bauble.i18n import _
from bauble.utils.geo import KMLMapCallbackFunctor
from bauble.view import Action
from bauble.view import Picture

if TYPE_CHECKING:
    from .accession import IntendedLocation
    from .plant import Plant


def edit_callback(objs, **kwargs):
    e = LocationEditor(model=objs[0])
    return e.start() is not None


def add_plants_callback(objs, **kwargs):
    # create a temporary session so that the temporary plant doesn't
    # get added to the accession
    session = db.Session()
    loc = session.merge(objs[0])
    from bauble.plugins.garden.plant import Plant
    from bauble.plugins.garden.plant import PlantEditor

    e = PlantEditor(model=Plant(location=loc))
    session.close()
    return e.start() is not None


def remove_callback(objs, **kwargs):
    locations = objs
    loc = locations[0]
    loc_lst = []
    for loc in locations:
        loc_lst.append(utils.xml_safe(loc))
        if len(loc.plants) > 0:
            msg = _(
                "Please remove the plants from <b>%s</b> "
                "before deleting it."
            ) % utils.xml_safe(loc)
            utils.message_dialog(msg, typ=Gtk.MessageType.WARNING)
            return False
    msg = _(
        "Are you sure you want to remove the following locations <b>%s</b>?"
    ) % ", ".join(i for i in loc_lst)
    if not utils.yes_no_dialog(msg):
        return False
    session = object_session(loc)
    for loc in locations:
        session.delete(loc)
    try:
        utils.remove_from_results_view(locations)
        session.commit()
    except Exception as e:  # pylint: disable=broad-except
        msg = _("Could not delete.\n\n%s") % utils.xml_safe(e)
        utils.message_details_dialog(
            msg, traceback.format_exc(), Gtk.MessageType.ERROR
        )
    finally:
        session.rollback()
    return True


LOC_KML_MAP_PREFS = "kml_templates.location"
"""pref for path to a custom mako kml template."""

map_kml_callback = KMLMapCallbackFunctor(
    prefs.prefs.get(
        LOC_KML_MAP_PREFS, str(Path(__file__).resolve().parent / "loc.kml")
    )
)


edit_action = Action(
    "loc_edit", _("_Edit"), callback=edit_callback, accelerator="<ctrl>e"
)

add_plant_action = Action(
    "loc_add_plant",
    _("_Add plants"),
    callback=add_plants_callback,
    accelerator="<ctrl>k",
)

remove_action = Action(
    "loc_remove",
    _("_Delete"),
    callback=remove_callback,
    accelerator="<ctrl>Delete",
    multiselect=True,
)

map_action = Action(
    "loc_map",
    _("Show in _map"),
    callback=map_kml_callback,
    accelerator="<ctrl>m",
    multiselect=True,
)

loc_context_menu = [edit_action, add_plant_action, remove_action, map_action]


LocationNote = db.make_note_class("Location")
LocationPicture = db.make_note_class("Location", cls_type="_picture")


class Location(db.Domain, db.WithNotes):
    """
    :Table name: location

    :Columns:
        *code*:
            unique

        *name*:

        *description*:

        *geojson*:
            spatial data

    :Relationships:
        *plants*:

    """

    __tablename__ = "location"

    # columns
    # refers to beds by unique codes
    code = Column(Unicode(12), unique=True, nullable=False)
    name = Column(Unicode(128))
    description = Column(UnicodeText)
    # spatial data deferred mainly to avoid comparison issues in union search
    # (i.e. reports)  NOTE that deferring can lead to the instance becoming
    # dirty when merged into another session (i.e. an editor) and the column
    # has already been loaded (i.e. infobox).  This can be avoided using a
    # separate db connection.
    # Also, NOTE that if not loaded (read) prior to changing a single list
    # history change will be recoorded with no indication of its value to the
    # change.  Can use something like:
    # `if loc.geojson != val: loc.geojson = val`
    geojson = deferred(Column(types.JSON()))

    # relations
    plants: list["Plant"] = relationship(
        "Plant", backref=backref("location", uselist=False)
    )
    intended_accessions: list["IntendedLocation"] = relationship(
        "IntendedLocation",
        cascade="all, delete-orphan",
        back_populates="location",
    )

    retrieve_cols = ["id", "code"]

    @property
    def pictures(self) -> list[Picture]:
        """Return pictures from any attached plants and any in _pictures."""
        session = object_session(self)
        if not isinstance(session, Session):
            return []
        # avoid circular imports
        from ..garden import Plant
        from ..garden.plant import PlantPicture

        plt_pics = (
            session.query(PlantPicture)
            .join(Plant, Location)
            .filter(Location.id == self.id)
        )
        if prefs.prefs.get(prefs.exclude_inactive_pref):
            plt_pics = plt_pics.filter(Plant.active.is_(True))  # type: ignore [attr-defined] # noqa
        return plt_pics.all() + self._pictures

    @classmethod
    def retrieve(cls, session, keys):
        parts = {k: v for k, v in keys.items() if k in cls.retrieve_cols}

        if parts:
            return session.query(cls).filter_by(**parts).one_or_none()
        return None

    def search_view_markup_pair(self) -> tuple[str, str]:
        """provide the two lines describing object for SearchView row."""
        if self.description is not None:
            return (
                utils.xml_safe(str(self)),
                utils.xml_safe(str(self.description)),
            )
        return utils.xml_safe(str(self)), type(self).__name__

    @validates("code", "name")
    def validate_stripping(self, _key, value):
        if value is None:
            return None
        return value.strip()

    def __str__(self):
        if self.name:
            return f"({self.code}) {self.name}"
        return str(self.code)

    def top_level_count(self):
        plants = db.get_active_children("plants", self)
        accessions = set(p.accession for p in plants)
        species = set(a.species for a in accessions)
        genera = set(s.genus for s in species)
        return {
            (1, "Locations"): 1,
            (2, "Plantings"): len(plants),
            (3, "Living plants"): sum(p.quantity for p in self.plants),
            (4, "Accessions"): set(a.id for a in accessions),
            (5, "Species"): set(s.id for s in species),
            (6, "Genera"): set(g.id for g in genera),
            (7, "Families"): set(g.family.id for g in genera),
            (8, "Sources"): set(
                a.source.source_detail.id
                for a in accessions
                if a.source and a.source.source_detail
            ),
        }

    def has_children(self):
        cls = self.__class__.plants.prop.mapper.class_
        from sqlalchemy import exists

        session = object_session(self)
        return bool(
            session.query(literal(True))
            .filter(exists().where(cls.location_id == self.id))
            .scalar()
        )

    def count_children(self):
        cls = self.__class__.plants.prop.mapper.class_
        session = object_session(self)
        query = session.query(cls.id).filter(cls.location_id == self.id)
        if prefs.prefs.get(prefs.exclude_inactive_pref):
            query = query.filter(cls.active.is_(True))
        return query.count()


class LocationEditorView(GenericEditorView):
    _tooltips = {
        "loc_name_entry": _(
            "The name that you will use later to refer to this location."
        ),
        "loc_desc_textview": _(
            "Any information that might be relevant to "
            "the location such as where it is or what's "
            "its purpose"
        ),
    }

    def __init__(self, parent=None):
        super().__init__(
            os.path.join(
                paths.lib_dir(), "plugins", "garden", "loc_editor.glade"
            ),
            parent=parent,
            root_widget_name="location_dialog",
        )
        self.use_ok_and_add = True
        self.set_accept_buttons_sensitive(False)
        self.widgets.notebook.set_current_page(0)
        # if the parent isn't the main bauble window then we assume
        # that the LocationEditor was opened from the PlantEditor and
        # so we shouldn't enable adding more plants...this is a bit of
        # a hack but it serves our purposes
        if bauble.gui and parent != bauble.gui.window:
            self.use_ok_and_add = False

    def get_window(self):
        return self.widgets.location_dialog

    def set_accept_buttons_sensitive(self, sensitive):
        self.widgets.loc_ok_button.set_sensitive(sensitive)
        self.widgets.loc_ok_and_add_button.set_sensitive(
            self.use_ok_and_add and sensitive
        )
        self.widgets.loc_next_button.set_sensitive(sensitive)


class LocationEditorPresenter(GenericEditorPresenter, PresenterMapMixin):
    widget_to_field_map = {
        "loc_name_entry": "name",
        "loc_code_entry": "code",
        "loc_desc_textview": "description",
    }

    def __init__(self, model, view):
        """
        model: should be an instance of class Accession
        view: should be an instance of AccessionEditorView
        """
        super().__init__(model, view)
        self.session = object_session(model)
        self._dirty = False

        notes_parent = self.view.widgets.notes_parent_box
        notes_parent.foreach(notes_parent.remove)
        self.notes_presenter = NotesPresenter(self, "notes", notes_parent)
        pictures_parent = self.view.widgets.pictures_parent_box
        pictures_parent.foreach(pictures_parent.remove)
        self.pictures_presenter = PicturesPresenter(
            self, "_pictures", pictures_parent
        )

        # initialize widgets
        self.refresh_view()  # put model values in view

        # connect signals
        self.assign_simple_handler(
            "loc_name_entry", "name", StringOrNoneValidator()
        )
        self.assign_simple_handler(
            "loc_code_entry", "code", StringOrNoneValidator()
        )
        self.assign_simple_handler(
            "loc_desc_textview", "description", StringOrNoneValidator()
        )
        self.refresh_sensitivity()
        if self.model not in self.session.new:
            self.view.widgets.loc_ok_and_add_button.set_sensitive(True)

        self.kml_template = prefs.prefs.get(
            LOC_KML_MAP_PREFS, str(Path(__file__).resolve().parent / "loc.kml")
        )

    def cleanup(self):
        super().cleanup()
        self.notes_presenter.cleanup()
        self.pictures_presenter.cleanup()
        self.remove_map_action_group()

    def refresh_sensitivity(self):
        sensitive = False
        ignore = "id"
        if self.is_dirty() and not utils.get_invalid_columns(
            self.model, ignore_columns=ignore
        ):
            sensitive = True
        self.view.set_accept_buttons_sensitive(sensitive)

    def set_model_attr(self, attr, value, validator=None):
        super().set_model_attr(attr, value, validator)
        self._dirty = True
        self.refresh_sensitivity()

    def is_dirty(self):
        return (
            self._dirty
            or self.notes_presenter.is_dirty()
            or self.pictures_presenter.is_dirty()
        )

    def refresh_view(self):
        for widget, field in self.widget_to_field_map.items():
            value = getattr(self.model, field)
            self.view.widget_set_value(widget, value)


class LocationEditor(GenericModelViewPresenterEditor):
    # these have to correspond to the response values in the view
    RESPONSE_OK_AND_ADD = 11
    RESPONSE_NEXT = 22
    ok_responses = (RESPONSE_OK_AND_ADD, RESPONSE_NEXT)

    def __init__(self, model=None, parent=None):
        """
        :param model: Location instance or None
        :param parent: the parent widget or None
        """
        # view and presenter are created in self.start()
        self.view = None
        self.presenter = None
        if model is None:
            model = Location()
        super().__init__(model, parent)
        # NOTE model is now modified for first time due to it having been
        # merged yet the geojson has already been loaded in the searchview
        if not parent and bauble.gui:
            parent = bauble.gui.window
        self.parent = parent
        self._committed = []

        view = LocationEditorView(parent=self.parent)
        self.presenter = LocationEditorPresenter(self.model, view)

    def handle_response(self, response):
        """handle the response from self.presenter.start() in self.start()"""
        not_ok_msg = "Are you sure you want to lose your changes?"
        if response == Gtk.ResponseType.OK or response in self.ok_responses:
            try:
                if self.presenter.is_dirty():
                    self.commit_changes()
                self._committed.append(self.model)
            except DBAPIError as e:
                msg = _("Error committing changes.\n\n%s") % utils.xml_safe(
                    e.orig
                )
                utils.message_details_dialog(
                    msg, str(e), Gtk.MessageType.ERROR
                )
                self.session.rollback()
                return False
            except Exception as e:
                msg = _(
                    "Unknown error when committing changes. See the "
                    "details for more information.\n\n%s"
                ) % utils.xml_safe(e)
                utils.message_details_dialog(
                    msg, traceback.format_exc(), Gtk.MessageType.ERROR
                )
                self.session.rollback()
                return False
        elif (
            self.presenter.is_dirty()
            and utils.yes_no_dialog(not_ok_msg)
            or not self.presenter.is_dirty()
        ):
            self.session.rollback()
            return True
        else:
            return False

        # respond to responses
        more_committed = None
        if response == self.RESPONSE_NEXT:
            self.presenter.cleanup()
            editor = LocationEditor(parent=self.parent)
            more_committed = editor.start()
        elif response == self.RESPONSE_OK_AND_ADD:
            from bauble.plugins.garden.plant import Plant
            from bauble.plugins.garden.plant import PlantEditor

            editor = PlantEditor(Plant(location=self.model), self.parent)
            more_committed = editor.start()
        if more_committed is not None:
            if isinstance(more_committed, list):
                self._committed.extend(more_committed)
            else:
                self._committed.append(more_committed)

        return True

    def start(self):
        """Start the LocationEditor and return the committed objects."""
        while True:
            response = self.presenter.start()
            self.presenter.view.save_state()
            if self.handle_response(response):
                break
        self.session.close()
        self.presenter.cleanup()
        return self._committed


from bauble.view import InfoBox
from bauble.view import InfoExpander
from bauble.view import LinksExpander
from bauble.view import PropertiesExpander


class GeneralLocationExpander(InfoExpander):
    """general expander for the PlantInfoBox"""

    def __init__(self, widgets):
        super().__init__(_("General"), widgets)
        general_box = self.widgets.loc_gen_box
        self.widgets.remove_parent(general_box)
        self.vbox.pack_start(general_box, True, True, 0)
        self.current_obj = None

        def on_nplants_clicked(*_args):
            cmd = f'plant where location.code="{self.current_obj.code}"'
            bauble.gui.send_command(cmd)

        utils.make_label_clickable(
            self.widgets.loc_nplants_data, on_nplants_clicked
        )

    def update(self, row):
        self.current_obj = row
        from bauble.plugins.garden.plant import Plant

        self.widget_set_value(
            "loc_name_data",
            f"<big>{utils.xml_safe(str(row))}</big>",
            markup=True,
        )
        session = object_session(row)
        nplants = session.query(Plant).filter_by(location_id=row.id).count()
        self.widget_set_value("loc_nplants_data", nplants)
        # NOTE don't load geojson from the row or history will always record
        # an unpdate and _last_updated will always chenge when a note is edited
        # (e.g. `shape = row.geojson...`) instead use a temp session
        temp = db.Session()
        geojson = temp.query(Location.geojson).filter_by(id=row.id).scalar()
        shape = geojson.get("type", "") if geojson else ""
        temp.close()
        self.widget_set_value("geojson_type", shape)


class DescriptionExpander(InfoExpander):
    """The location description"""

    def __init__(self, widgets):
        super().__init__(_("Description"), widgets)
        descr_box = self.widgets.loc_descr_box
        self.widgets.remove_parent(descr_box)
        self.vbox.pack_start(descr_box, True, True, 0)

    def update(self, row):
        if row.description is None:
            self.set_expanded(False)
            self.set_sensitive(False)
        else:
            self.set_expanded(True)
            self.set_sensitive(True)
            self.widget_set_value("loc_descr_data", str(row.description))


class LocationInfoBox(InfoBox):
    """an InfoBox for a Location table row"""

    def __init__(self):
        super().__init__()
        filename = os.path.join(
            paths.lib_dir(), "plugins", "garden", "loc_infobox.glade"
        )
        self.widgets = utils.load_widgets(filename)
        self.general = GeneralLocationExpander(self.widgets)
        self.add_expander(self.general)
        self.description = DescriptionExpander(self.widgets)
        self.add_expander(self.description)
        self.links = LinksExpander("notes")
        self.add_expander(self.links)
        self.props = PropertiesExpander()
        self.add_expander(self.props)

    def update(self, row):
        self.general.update(row)
        self.description.update(row)
        self.links.update(row)
        self.props.update(row)
