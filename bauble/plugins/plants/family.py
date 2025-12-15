# Copyright 2008-2010 Brett Adams
# Copyright 2014-2015 Mario Frasca <mario@anche.no>.
# Copyright 2017 Jardín Botánico de Quito
# Copyright 2020-2025 Ross Demuth <rossdemuth123@gmail.com>
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

import logging

logger = logging.getLogger(__name__)

import os
import traceback
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import cast as t_cast

from gi.repository import Gtk
from sqlalchemy import CheckConstraint
from sqlalchemy import Column
from sqlalchemy import ForeignKey
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy import Unicode
from sqlalchemy import UniqueConstraint
from sqlalchemy import and_
from sqlalchemy import case
from sqlalchemy import cast
from sqlalchemy import distinct
from sqlalchemy import exists
from sqlalchemy import func
from sqlalchemy import literal
from sqlalchemy import or_
from sqlalchemy import select
from sqlalchemy import union
from sqlalchemy.exc import DBAPIError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.associationproxy import association_proxy
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import Session
from sqlalchemy.orm import relationship
from sqlalchemy.orm import synonym as sa_synonym
from sqlalchemy.orm import validates
from sqlalchemy.orm.session import object_session

import bauble
from bauble import btypes as types
from bauble import db
from bauble import editor
from bauble import paths
from bauble import prefs
from bauble import utils
from bauble.i18n import _
from bauble.view import Action
from bauble.view import InfoBox
from bauble.view import InfoExpanderMixin
from bauble.view import LinksExpander
from bauble.view import PropertiesExpander
from bauble.view import on_clicked_search

from .model import Taxon
from .species_model import Species
from .widgets import SynonymsExpander


def edit_callback(objs: Sequence["Family"], **_kwargs) -> bool:
    family = objs[0]

    return FamilyEditor(model=family).start() is not None


def add_genera_callback(objs: Sequence["Family"], **_kwargs) -> bool:
    """Family context menu callback"""
    family = objs[0]
    gen_editor = GenusEditor(model=Genus(family=family))

    return gen_editor.start() is not None


def remove_callback(
    objs: Sequence["Family"],
    **_kwargs,
) -> bool:
    family = objs[0]
    fam_lst: list[str] = []
    session = object_session(family)
    if not isinstance(session, Session):
        return False

    for family in objs:
        num_gen = len(family.genera)
        safe_str = utils.xml_safe(str(family))
        fam_lst.append(safe_str)
        if num_gen > 0:
            msg = _(
                "The family <i>%(fam)s</i> has %(num_gen)s genera.\n\n"
                "You cannot remove a family with genera."
            ) % {"fam": safe_str, "num_gen": num_gen}
            utils.message_dialog(msg, typ=Gtk.MessageType.WARNING)

            return False

    msg = _(
        "Are you sure you want to remove the following families <i>%s</i>?"
    ) % ", ".join(fam_lst)
    if not utils.yes_no_dialog(msg):

        return False

    for family in objs:
        session.delete(family)
    try:
        session.commit()
    except SQLAlchemyError as e:
        msg = _("Could not delete.\n\n%s") % utils.xml_safe(e)
        utils.message_details_dialog(
            msg, traceback.format_exc(), Gtk.MessageType.ERROR
        )
        session.rollback()

        return False

    return True


edit_action = Action(
    "family_edit", _("_Edit"), callback=edit_callback, accelerator="<ctrl>e"
)

add_species_action = Action(
    "family_genus_add",
    _("_Add genus"),
    callback=add_genera_callback,
    accelerator="<ctrl>k",
)

remove_action = Action(
    "family_remove",
    _("_Delete"),
    callback=remove_callback,
    accelerator="<ctrl>Delete",
    multiselect=True,
)

family_context_menu = [edit_action, add_species_action, remove_action]


class Family(Taxon, db.WithNotes):
    """
    :Table name: family

    :Columns:
        *family*:
            The name of the family. Required.

        *author*

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

    __tablename__ = "family"
    __table_args__: tuple = (UniqueConstraint("family", "author"), {})

    rank = "familia"
    link_keys = ["accepted"]

    # columns
    order = Column(Unicode(64))
    suborder = Column(Unicode(64))

    family = Column(String(45), nullable=False, index=True)
    epithet: "str" = sa_synonym("family")

    # use '' instead of None so that the constraints will work propertly
    author = Column(Unicode(128), default="")

    # we use the blank string here instead of None so that the
    # contraints will work properly,
    qualifier = Column(
        types.Enum(values=["s. lat.", "s. str.", ""]), default=""
    )

    # relations
    synonyms = association_proxy(
        "_synonyms", "synonym", creator=lambda fam: FamilySynonym(synonym=fam)
    )
    _synonyms: list["FamilySynonym"] = relationship(
        "FamilySynonym",
        primaryjoin="Family.id==FamilySynonym.family_id",
        cascade="all, delete-orphan",
        uselist=True,
        backref="family",
    )

    _accepted: "FamilySynonym" = relationship(
        "FamilySynonym",
        primaryjoin="Family.id==FamilySynonym.synonym_id",
        cascade="all, delete-orphan",
        uselist=False,
        backref="synonym",
    )
    accepted = association_proxy(
        "_accepted", "family", creator=lambda fam: FamilySynonym(family=fam)
    )

    genera: list["Genus"] = relationship(
        "Genus",
        order_by="Genus.genus",
        back_populates="family",
        cascade="all, delete-orphan",
    )

    cites = Column(types.Enum(values=["I", "II", "III", None]), default=None)

    retrieve_cols = ["id", "epithet", "family"]

    @property
    def pictures(self) -> list[db.Picture]:
        session = object_session(self)
        if not isinstance(session, Session):
            return []
        from ..garden import Accession
        from ..garden import Plant
        from ..garden.plant import PlantPicture
        from .species_model import SpeciesPicture

        sp_pics = (
            session.query(SpeciesPicture)
            .join(Species, Genus, Family)
            .filter(Family.id == self.id)
        )
        plt_pics = (
            session.query(PlantPicture)
            .join(Plant, Accession, Species, Genus, Family)
            .filter(Family.id == self.id)
        )
        if prefs.prefs.get(prefs.exclude_inactive_pref):
            plt_pics = plt_pics.filter(Plant.active.is_(True))  # type: ignore [attr-defined] # noqa
        return sp_pics.all() + plt_pics.all()

    @classmethod
    def retrieve(cls, session, keys):
        fam_parts = {k: v for k, v in keys.items() if k in cls.retrieve_cols}

        if fam_parts:
            return session.query(cls).filter_by(**fam_parts).one_or_none()
        return None

    @validates("family")
    def validate_stripping(self, _key, value):
        if value is None:
            return None
        return value.strip()

    def __str__(self):
        return self.string()

    def string(self, **kwargs) -> str:
        """Returns a string representation of the family.

        :param author: if True, include the author in the string.
        """
        author = kwargs.get("author", False)
        if self.family is None:
            return db.Base.__repr__(self)

        parts = [self.family, self.qualifier]
        if author and self.author:
            parts.append(utils.xml_safe(self.author))

        return " ".join([str(s) for s in parts if s not in (None, "")])

    @hybrid_property
    def active(self) -> bool:
        """False when all accessions have been deaccessioned or no genera or
        species attached.
        """
        if not self.genera:
            return False
        for genus in self.genera:
            if genus.active:
                return True
        return False

    @active.expression  # type: ignore [no-redef]
    def active(cls) -> types.Boolean:
        # pylint: disable=no-self-argument,no-self-use,arguments-renamed
        from ..garden import Accession
        from ..garden import Plant

        active = (
            select([cls.id])
            .join(Genus)
            .join(Species)
            .outerjoin(Accession)
            .outerjoin(Plant)
            .where(or_(Plant.id.is_(None), Plant.quantity > 0))
            .scalar_subquery()
        )
        return cast(case([(cls.id.in_(active), 1)], else_=0), types.Boolean)

    @hybrid_property
    def updated(self) -> datetime:
        updates = [self._last_updated]

        if self._accepted:
            updates.append(self._accepted._last_updated)

        if self.notes:
            updates.append(max(i._last_updated for i in self.notes))

        return max(updates)

    @updated.expression  # type: ignore [no-redef]
    def updated(cls) -> types.DateTime:
        # pylint: disable=no-self-argument,no-self-use,arguments-renamed
        self_select = select([cls._last_updated, cls.id])

        note_select = select([FamilyNote._last_updated, cls.id]).join(cls)

        accepted_select = select([FamilySynonym._last_updated, cls.id]).join(
            cls, cls.id == FamilySynonym.synonym_id
        )

        dates = union(self_select, note_select, accepted_select).alias("dates")

        return (
            select([func.max(dates.c._last_updated)])
            .where(dates.c.id == cls.id)
            .label("updated")
        )

    @classmethod
    def top_level_count(
        cls,
        ids: list[int],
        exclude_inactive: bool = False,
    ) -> db.TopLevelCount:

        # avoid circular imports
        from ..garden import Accession
        from ..garden import Location
        from ..garden import Plant
        from ..garden import Source
        from ..garden import SourceDetail

        base_ids_stmt = (
            select(
                cls.id,
                Genus.id,
                Species.id,
                Accession.id,
                Plant.top_level_count_id(exclude_inactive),
                Location.id,
                SourceDetail.id,
            )
            .select_from(cls)
            .outerjoin(Genus)
            .outerjoin(Species)
            .outerjoin(Accession)
            .outerjoin(Plant)
            .outerjoin(Location)
            .outerjoin(Source)
            .outerjoin(SourceDetail)
        )

        base_count_stmt = (
            select(
                func.sum(Plant.quantity),
            )
            .select_from(cls)
            .join(Genus)
            .join(Species)
            .join(Accession)
            .join(Plant)
        )

        if exclude_inactive:
            # pylint: disable=no-member
            base_ids_stmt = base_ids_stmt.where(
                Accession.active.is_(True),  # type: ignore [attr-defined]
            )
            base_ids_stmt = base_ids_stmt.where(Species.id.is_not(None))

        result = cls._top_level_counter_helper(
            base_ids_stmt, base_count_stmt, ids
        )
        return db.TopLevelCount(*result)

    def has_children(self):
        cls = self.__class__.genera.prop.mapper.class_

        session = object_session(self)

        if prefs.prefs.get(prefs.exclude_inactive_pref):
            # probably not much point for searchview as would be exluded anyway
            return bool(
                session.query(literal(True))
                .filter(
                    exists().where(
                        and_(
                            cls.family_id == self.id,
                            cls.active.is_(True),
                        )
                    )
                )
                .scalar()
            )
        return bool(
            session.query(literal(True))
            .filter(exists().where(cls.family_id == self.id))
            .scalar()
        )

    def count_children(self):
        cls = self.__class__.genera.prop.mapper.class_
        session = object_session(self)
        query = session.query(cls.id).filter(cls.family_id == self.id)
        if prefs.prefs.get(prefs.exclude_inactive_pref):
            query = query.filter(cls.active.is_(True))
        return query.count()


# defining the latin alias to the class.
Familia = Family


FamilyNote = db.make_note_class("Family")


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

    __tablename__ = "family_synonym"
    __table_args__ = (CheckConstraint("family_id != synonym_id"),)

    # columns
    family_id = Column(Integer, ForeignKey("family.id"), nullable=False)
    synonym_id = Column(
        Integer, ForeignKey("family.id"), nullable=False, unique=True
    )
    is_one_to_one = True
    synonym: Mapped["Family"]
    family: Mapped["Family"]

    def __str__(self):
        return Family.string(self.synonym)


# avoid circular imports
from .genus import Genus
from .genus import GenusEditor


class FamilyEditorView(editor.GenericEditorView):
    _tooltips = {
        "fam_family_entry": _("The family name."),
        "fam_qualifier_combo": _(
            "The family qualifier helps to remove "
            "ambiguities that might be associated with "
            "this family name."
        ),
        "syn_frame": _(
            "A list of synonyms for this family.\n\nTo add a "
            "synonym enter a family name and select one from "
            "the list of completions.  Then click Add to add "
            "it to the list of synonyms."
        ),
        "fam_cancel_button": _("Cancel your changes."),
        "fam_ok_button": _("Save your changes."),
        "fam_ok_and_add_button": _(
            "Save your changes and add a genus to this family."
        ),
        "fam_next_button": _("Save your changes and add another family."),
    }

    def __init__(self, parent=None):
        filename = os.path.join(
            paths.lib_dir(), "plugins", "plants", "family_editor.glade"
        )
        super().__init__(
            filename, parent=parent, root_widget_name="family_dialog"
        )
        self.attach_completion("syn_entry")
        self.attach_completion("order_entry")
        self.attach_completion("suborder_entry")
        self.set_accept_buttons_sensitive(False)
        self.widgets.notebook.set_current_page(0)

    def get_window(self):
        return self.widgets.family_dialog

    def set_accept_buttons_sensitive(self, sensitive):
        self.widgets.fam_ok_button.set_sensitive(sensitive)
        self.widgets.fam_ok_and_add_button.set_sensitive(sensitive)
        self.widgets.fam_next_button.set_sensitive(sensitive)


FAMILY_WEB_BUTTON_DEFS_PREFS = "web_button_defs.family"


class FamilyEditorPresenter(
    editor.PresenterLinksMixin, editor.GenericEditorPresenter
):
    widget_to_field_map = {
        "order_entry": "order",
        "suborder_entry": "suborder",
        "fam_family_entry": "family",
        "author_entry": "author",
        "fam_qualifier_combo": "qualifier",
        "cites_combo": "cites",
    }
    LINK_BUTTONS_PREF_KEY = FAMILY_WEB_BUTTON_DEFS_PREFS

    def __init__(self, model, view):
        """
        :param model: should be an instance of class Family
        :param view: should be an instance of FamilyEditorView
        """
        super().__init__(model, view)
        self.session = object_session(model)

        # initialize widgets
        self.init_enum_combo("fam_qualifier_combo", "qualifier")
        self.init_enum_combo("cites_combo", "cites")

        from . import SynonymsPresenter

        self.synonyms_presenter = SynonymsPresenter(
            self,
            FamilySynonym,
            None,
            lambda session, text: (
                session.query(Family)
                .filter(utils.ilike(Family.family, f"{text}%%"))
                .order_by(Family.family)
            ),
        )
        self.refresh_view()  # put model values in view

        self.assign_completions_handler(
            "order_entry", self.order_get_completions, set_problems=False
        )
        self.assign_completions_handler(
            "suborder_entry", self.suborder_get_completions, set_problems=False
        )
        # connect signals
        self.assign_simple_handler(
            "order_entry", "order", editor.StringOrNoneValidator()
        )
        self.assign_simple_handler(
            "suborder_entry", "suborder", editor.StringOrNoneValidator()
        )
        self.assign_simple_handler(
            "fam_family_entry", "family", editor.StringOrNoneValidator()
        )
        self.assign_simple_handler(
            "author_entry", "author", editor.StringOrNoneValidator()
        )
        self.assign_simple_handler(
            "fam_qualifier_combo", "qualifier", editor.StringOrEmptyValidator()
        )
        self.assign_simple_handler(
            "cites_combo", "cites", editor.StringOrNoneValidator()
        )

        notes_parent = self.view.widgets.notes_parent_box
        notes_parent.foreach(notes_parent.remove)
        self.notes_presenter = editor.NotesPresenter(
            self, "notes", notes_parent
        )

        if self.model not in self.session.new:
            self.view.widgets.fam_ok_and_add_button.set_sensitive(True)

        if any(getattr(self.model, i) for i in ("order", "suborder")):
            self.view.widget_set_expanded("suprafam_expander", True)

        if self.model in self.session.new and self.model.family:
            # new model with family already set (e.g. GenusEditor add family)
            self._dirty = True
            self.refresh_sensitivity()
        else:
            self._dirty = False

        self.init_links_menu()

    def order_get_completions(self, text):
        query = (
            self.session.query(Family.order)
            .filter(utils.ilike(Family.order, f"{text}%%"))
            .distinct()
        )
        return [i[0] for i in query]

    def suborder_get_completions(self, text):
        query = self.session.query(Family.suborder)
        if self.model.order:
            query = query.filter(Family.order == self.model.order)
        query = query.filter(
            utils.ilike(Family.suborder, f"{text}%%")
        ).distinct()
        return [i[0] for i in query]

    def refresh_sensitivity(self):
        # TODO: check widgets for problems
        if self.model.family:
            self.view.set_accept_buttons_sensitive(self.is_dirty())
        else:
            self.view.set_accept_buttons_sensitive(False)

    def set_model_attr(self, attr, value, validator=None):
        super().set_model_attr(attr, value, validator)
        self._dirty = True
        self.refresh_sensitivity()

    def is_dirty(self):
        return (
            self._dirty
            or self.synonyms_presenter.is_dirty()
            or self.notes_presenter.is_dirty()
        )

    def __del__(self):
        # we have to delete the views in the child presenters manually
        # to avoid the circular reference
        del self.synonyms_presenter.view

    def cleanup(self):
        super().cleanup()
        self.synonyms_presenter.cleanup()
        self.notes_presenter.cleanup()
        self.remove_link_action_group()


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
                return False
            except Exception as e:
                msg = _(
                    "Unknown error when committing changes. See the "
                    "details for more information.\n\n%s"
                ) % utils.xml_safe(e)
                utils.message_details_dialog(
                    msg, traceback.format_exc(), Gtk.MessageType.ERROR
                )
                return False
        elif (
            self.presenter.is_dirty() and utils.yes_no_dialog(not_ok_msg)
        ) or not self.presenter.is_dirty():
            self.session.rollback()
            return True
        else:
            return False

        # respond to responses
        more_committed = None
        if response == self.RESPONSE_NEXT:
            self.presenter.cleanup()
            editor = FamilyEditor(parent=self.parent)
            more_committed = editor.start()
        elif response == self.RESPONSE_OK_AND_ADD:
            editor = GenusEditor(Genus(family=self.model), self.parent)
            more_committed = editor.start()

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


def infobox_counts(id_: int) -> dict[str, int]:
    from ..garden import Accession
    from ..garden import Plant

    stmt = (
        select(
            func.count(distinct(Genus.id)),
            func.count(distinct(Species.genus_id)),
            func.count(distinct(Species.id)),
            func.count(distinct(Accession.species_id)),
            func.count(distinct(Accession.id)),
            func.count(distinct(Plant.accession_id)),
            func.count(Plant.id),
            func.sum(Plant.quantity),
        )
        .select_from(Family)
        .outerjoin(Genus)
        .outerjoin(Species)
        .outerjoin(Accession)
        .outerjoin(Plant)
        .where(Family.id == id_)
    )
    with db.engine.begin() as connection:
        counts = connection.execute(stmt).one()

    keys = (
        "genera",
        "gen_w_sp",
        "species",
        "sp_w_acc",
        "accessions",
        "acc_w_plants",
        "plants",
        "living_plants",
    )

    return dict(zip(keys, counts, strict=True))


@Gtk.Template(
    filename=str(Path(__file__).resolve().parent / "family_expander.ui")
)
class GeneralFamilyExpander(InfoExpanderMixin[Family], Gtk.Expander):

    __gtype_name__ = "GeneralFamilyExpander"

    general_box = t_cast(Gtk.Box, Gtk.Template.Child())
    details_box = t_cast(Gtk.Box, Gtk.Template.Child())
    order_label = t_cast(Gtk.Label, Gtk.Template.Child())
    suborder_label = t_cast(Gtk.Label, Gtk.Template.Child())
    name_label = t_cast(Gtk.Label, Gtk.Template.Child())
    num_genera_label = t_cast(Gtk.Label, Gtk.Template.Child())
    num_taxa_label = t_cast(Gtk.Label, Gtk.Template.Child())
    num_acc_label = t_cast(Gtk.Label, Gtk.Template.Child())
    num_plants_label = t_cast(Gtk.Label, Gtk.Template.Child())
    living_plants_label = t_cast(Gtk.Label, Gtk.Template.Child())
    cites_label = t_cast(Gtk.Label, Gtk.Template.Child())

    def __init__(self) -> None:
        super().__init__(label=_("General"))
        self.connect("notify::expanded", self.on_expanded)
        self.has_details = False

    def update(self, row: Family) -> None:
        self.has_details = any((row.order, row.suborder))
        self.update_details(row)
        self.name_label.set_markup(
            f"<big>{row}</big> {utils.xml_safe(str(row.author))}",
        )
        self.update_counts(row)
        self.update_clickable_labels(row)

    def update_counts(self, row: Family) -> None:
        counts = infobox_counts(row.id)

        self.num_genera_label.set_label(str(counts["genera"]))
        self.num_taxa_label.set_label("0")
        self.num_acc_label.set_label("0")
        self.num_plants_label.set_label("0")

        if counts["species"]:
            self.num_taxa_label.set_label(
                f"{counts['species']} in {counts['gen_w_sp']} genera"
            )

        if counts["accessions"]:
            self.num_acc_label.set_label(
                f"{counts['accessions']} in {counts['sp_w_acc']} species"
            )

        if counts["plants"]:
            self.num_plants_label.set_label(
                f"{counts['plants']} in {counts['acc_w_plants']} accessions"
            )

        self.living_plants_label.set_label(str(counts["living_plants"] or 0))
        self.cites_label.set_label(row.cites or "")

    def update_clickable_labels(self, row: Family) -> None:
        labels_to_searches = (
            (
                self.num_genera_label,
                f"genus where family.id = {row.id}",
            ),
            (
                self.num_taxa_label,
                f"species where genus.family.id = {row.id}",
            ),
            (
                self.num_acc_label,
                f"accession where species.genus.family.id = {row.id}",
            ),
            (
                self.num_plants_label,
                f"plant where accession.species.genus.family.id = {row.id}",
            ),
            (
                self.cites_label,
                f"family where cites = {row.cites}",
            ),
            (
                self.living_plants_label,
                f"plant where accession.species.genus.family.id = {row.id} "
                "and quantity > 0",
            ),
        )

        for label, search in labels_to_searches:
            utils.make_label_clickable(
                label,
                on_clicked_search,
                search,
            )

    def update_details(self, row: Family) -> None:
        """Provides higher parts, if they exist, above the family name."""

        if not self.has_details:
            utils.hide_widgets([self.details_box])
            return

        utils.unhide_widgets([self.details_box])
        utils.hide_widgets([self.order_label, self.suborder_label])

        if row.order:
            self.order_label.set_markup(f"{utils.xml_safe(row.order)} >")
            utils.make_label_clickable(
                self.order_label,
                on_clicked_search,
                f"family where order = {row.order}",
            )
            utils.unhide_widgets([self.order_label])

        if row.suborder:
            self.suborder_label.set_markup(f"{utils.xml_safe(row.suborder)} >")
            utils.make_label_clickable(
                self.suborder_label,
                on_clicked_search,
                f"family where suborder = {row.suborder}",
            )
            utils.unhide_widgets([self.suborder_label])


class FamilyInfoBox(InfoBox[Family]):

    def __init__(self) -> None:
        super().__init__()
        self.general = GeneralFamilyExpander()
        self.add_expander(self.general)
        self.add_expander(SynonymsExpander[Family]())

        button_defs = []
        buttons = prefs.prefs.itersection(FAMILY_WEB_BUTTON_DEFS_PREFS)
        for name, button in buttons:
            button["name"] = name
            button_defs.append(button)

        self.add_expander(LinksExpander("notes", links=button_defs))
        self.add_expander(PropertiesExpander())
