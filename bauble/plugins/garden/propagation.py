# Copyright 2008-2010 Brett Adams
# Copyright 2015-2017 Mario Frasca <mario@anche.no>.
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
propagation module
"""

import datetime
import logging
import os
import traceback
import weakref
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

from gi.repository import Gtk  # noqa
from sqlalchemy import Column
from sqlalchemy import ForeignKey
from sqlalchemy import Integer
from sqlalchemy import UnicodeText
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.associationproxy import association_proxy
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import backref
from sqlalchemy.orm import relationship
from sqlalchemy.orm.session import object_session

from bauble import btypes as types
from bauble import db
from bauble import editor
from bauble import paths
from bauble import prefs
from bauble import utils
from bauble.i18n import _

if TYPE_CHECKING:
    from . import Plant

prop_type_values = {
    "Seed": _("Seed"),
    "UnrootedCutting": _("Unrooted cutting"),
    "Other": _("Other"),
}

prop_type_results = {
    "Seed": "SEDL",
    "UnrootedCutting": "RCUT",
    "Other": "UNKN",
}


class PlantPropagation(db.Base):
    """PlantPropagation provides an intermediate relation from
    Plant->Propagation
    """

    __tablename__ = "plant_prop"
    plant_id = Column(Integer, ForeignKey("plant.id"), nullable=False)
    propagation_id = Column(
        Integer, ForeignKey("propagation.id"), nullable=False
    )
    plant: Mapped["Plant"]
    propagation: Mapped["Propagation"]


class Propagation(db.Base):
    """Propagation"""

    __tablename__ = "propagation"
    prop_type = Column(
        types.Enum(
            values=list(prop_type_values.keys()), translations=prop_type_values
        ),
        nullable=False,
    )
    notes = Column(UnicodeText)
    date = Column(types.Date)

    plant = association_proxy(
        "_plant_prop",
        "plant",
        creator=lambda plant: PlantPropagation(plant=plant),
    )
    _plant_prop: "PlantPropagation" = relationship(
        "PlantPropagation",
        cascade="all, delete-orphan",
        uselist=False,
        backref=backref("propagation", uselist=False),
    )

    cutting: "PropCutting" = relationship(
        "PropCutting",
        primaryjoin="Propagation.id==PropCutting.propagation_id",
        cascade="all,delete-orphan",
        uselist=False,
        backref=backref("propagation", uselist=False),
    )
    seed: "PropSeed" = relationship(
        "PropSeed",
        primaryjoin="Propagation.id==PropSeed.propagation_id",
        cascade="all,delete-orphan",
        uselist=False,
        backref=backref("propagation", uselist=False),
    )

    @property
    def accessions(self):
        # pylint: disable=no-member
        if not self.used_source:
            return []
        accessions = []
        session = object_session(self.used_source[0])
        for used in self.used_source:
            if used.accession and used.accession not in session.new:
                accessions.append(used.accession)
        return sorted(accessions, key=utils.natsort_key)

    @property
    def accessible_quantity(self):
        """the resulting product minus the already accessed material

        return 1 if the propagation is not completely specified.
        """
        quantity = None
        incomplete = True
        if self.prop_type == "UnrootedCutting":
            incomplete = self.cutting is None  # cutting without fields
            if not incomplete and self.cutting.rooted:
                quantity = sum(
                    i.quantity for i in self.cutting.rooted if i.quantity
                )
        elif self.prop_type == "Seed":
            incomplete = self.seed is None  # seed without fields
            if not incomplete:
                quantity = self.seed.nseedlings
        if incomplete:
            return 1  # let user grab one at a time, in any case
        if quantity is None:
            quantity = 0
        removethis = sum((a.quantity_recvd or 0) for a in self.accessions)
        return max(quantity - removethis, 0)

    def get_summary(self, partial=False):
        """compute a textual summary for this propagation

        a full description contains all fields, in `key:value;` format, plus
        a prefix telling us whether the resulting material of the
        propagation was added as accessed in the collection.

        partial==1 means we only want to get the list of resulting
        accessions.

        partial==2 means we do not want the list of resulting accessions.
        """
        date_format = prefs.prefs[prefs.date_format_pref]

        def get_date(date):
            if isinstance(date, datetime.date):
                return date.strftime(date_format)
            return date

        values = []
        accession_codes = []

        if self.used_source and partial != 2:  # pylint: disable=no-member
            values = [
                _("used in") + f": {acc.code}" for acc in self.accessions
            ]
            accession_codes = [acc.code for acc in self.accessions]

        if partial == 1:
            return ";".join(accession_codes)

        if self.prop_type == "UnrootedCutting":
            cutting = self.cutting
            values.append(_("Cutting"))
            if cutting.cutting_type is not None:
                values.append(
                    _("Cutting type")
                    + f": {cutting_type_values[cutting.cutting_type]}"
                )
            if cutting.length:
                values.append(
                    _("Length: %(length)s%(unit)s")
                    % dict(
                        length=cutting.length,
                        unit=length_unit_values[cutting.length_unit],
                    )
                )
            if cutting.tip:
                values.append(_("Tip") + f": {tip_values[cutting.tip]}")
            if cutting.leaves:
                leaves = _("Leaves") + f": {leaves_values[cutting.leaves]}"
                if cutting.leaves == "Removed" and cutting.leaves_reduced_pct:
                    leaves += f"({cutting.leaves_reduced_pct}%)"
                values.append(leaves)
            if cutting.flower_buds:
                values.append(
                    _("Flower buds")
                    + f": {flower_buds_values[cutting.flower_buds]}"
                )
            if cutting.wound is not None:
                values.append(
                    _("Wounded") + f": {wound_values[cutting.wound]}"
                )
            if cutting.fungicide:
                values.append(_("Fungicide") + f": {cutting.fungicide}")
            if cutting.hormone:
                values.append(_("Hormone treatment") + f": {cutting.hormone}")
            if cutting.bottom_heat_temp:
                values.append(
                    _("Bottom heat: %(temp)s%(unit)s")
                    % dict(
                        temp=cutting.bottom_heat_temp,
                        unit=bottom_heat_unit_values[cutting.bottom_heat_unit],
                    )
                )
            if cutting.container:
                values.append(_("Container") + f": {cutting.container}")
            if cutting.media:
                values.append(_("Media") + f": {cutting.media}")
            if cutting.location:
                values.append(_("Location") + f": {cutting.location}")
            if cutting.cover:
                values.append(_("Cover") + f": {cutting.cover}")

            if cutting.rooted_pct:
                values.append(_("Rooted: %s%%") % cutting.rooted_pct)
        elif self.prop_type == "Seed":
            seed = self.seed
            values.append(_("Seed"))
            if seed.pretreatment:
                values.append(_("Pretreatment") + f": {seed.pretreatment}")
            if seed.nseeds:
                values.append(_("# of seeds") + f": {seed.nseeds}")
            date_sown = get_date(seed.date_sown)
            if date_sown:
                values.append(_("Date sown") + f": {date_sown}")
            if seed.container:
                values.append(_("Container") + f": {seed.container}")
            if seed.media:
                values.append(_("Media") + f": {seed.media}")
            if seed.covered:
                values.append(_("Covered") + f": {seed.covered}")
            if seed.location:
                values.append(_("Location") + f": {seed.location}")
            germ_date = get_date(seed.germ_date)
            if germ_date:
                values.append(_("Germination date") + f": {germ_date}")
            if seed.nseedlings:
                values.append(_("# of seedlings") + f": {seed.nseedlings}")
            if seed.germ_pct:
                values.append(_("Germination rate") + f": {seed.germ_pct}%")
            date_planted = get_date(seed.date_planted)
            if date_planted:
                values.append(_("Date planted") + f": {date_planted}")
        elif self.notes:
            values.append(_("Other"))
            values.append(utils.nstr(self.notes))
        else:
            values.append(str(self))

        string = "; ".join(values)

        return string

    def clean(self):
        if self.prop_type == "UnrootedCutting":
            utils.delete_or_expunge(self.seed)
            self.seed = None
            if not self.cutting.bottom_heat_temp:
                self.cutting.bottom_heat_unit = None
            if not self.cutting.length:
                self.cutting.length_unit = None
        elif self.prop_type == "Seed":
            utils.delete_or_expunge(self.cutting)
            self.cutting = None
        else:
            utils.delete_or_expunge(self.seed)
            utils.delete_or_expunge(self.cutting)
            self.seed = None
            self.cutting = None


class PropCuttingRooted(db.Base):
    """Rooting dates for cutting"""

    __tablename__ = "prop_cutting_rooted"

    date = Column(types.Date)
    quantity = Column(Integer, autoincrement=False)
    cutting_id = Column(Integer, ForeignKey("prop_cutting.id"), nullable=False)


cutting_type_values = {
    "Nodal": _("Nodal"),
    "InterNodal": _("Internodal"),
    "Other": _("Other"),
}

tip_values = {
    "Intact": _("Intact"),
    "Removed": _("Removed"),
    "None": _("None"),
    None: "",
}

leaves_values = {
    "Intact": _("Intact"),
    "Removed": _("Removed"),
    "None": _("None"),
    None: "",
}

flower_buds_values = {"Removed": _("Removed"), "None": _("None"), None: ""}

wound_values = {
    "No": _("No"),
    "Single": _("Singled"),
    "Double": _("Double"),
    "Slice": _("Slice"),
    None: "",
}

hormone_values = {"Liquid": _("Liquid"), "Powder": _("Powder"), "No": _("No")}

bottom_heat_unit_values = {"F": _("°F"), "C": _("°C"), None: ""}

length_unit_values = {"mm": _("mm"), "cm": _("cm"), "in": _("in"), None: ""}


class PropCutting(db.Base):
    """A cutting"""

    __tablename__ = "prop_cutting"
    cutting_type = Column(
        types.Enum(
            values=list(cutting_type_values.keys()),
            translations=cutting_type_values,
        ),
        default="Other",
    )
    tip = Column(
        types.Enum(values=list(tip_values.keys()), translations=tip_values)
    )
    leaves = Column(
        types.Enum(
            values=list(leaves_values.keys()), translations=leaves_values
        )
    )
    leaves_reduced_pct = Column(Integer, autoincrement=False)
    length = Column(Integer, autoincrement=False)
    length_unit = Column(
        types.Enum(
            values=list(length_unit_values.keys()),
            translations=length_unit_values,
        )
    )

    # single/double/slice
    wound = Column(
        types.Enum(values=list(wound_values.keys()), translations=wound_values)
    )

    # removed/None
    flower_buds = Column(
        types.Enum(
            values=list(flower_buds_values.keys()),
            translations=flower_buds_values,
        )
    )

    fungicide = Column(UnicodeText)  # fungal soak
    hormone = Column(UnicodeText)  # powder/liquid/None....solution

    media = Column(UnicodeText)
    container = Column(UnicodeText)
    location = Column(UnicodeText)
    cover = Column(UnicodeText)  # vispore, poly, plastic dome, poly bag

    # temperature of bottom heat
    bottom_heat_temp = Column(Integer, autoincrement=False)

    # TODO: make the bottom heat unit required if bottom_heat_temp is
    # not null

    # F/C
    bottom_heat_unit = Column(
        types.Enum(
            values=list(bottom_heat_unit_values.keys()),
            translations=bottom_heat_unit_values,
        ),
        nullable=True,
    )
    rooted_pct = Column(Integer, autoincrement=False)

    propagation_id = Column(
        Integer, ForeignKey("propagation.id"), nullable=False
    )

    rooted: "PropCuttingRooted" = relationship(
        "PropCuttingRooted",
        cascade="all, delete-orphan",
        primaryjoin="PropCutting.id == PropCuttingRooted.cutting_id",
        backref=backref("cutting", uselist=False),
    )


class PropSeed(db.Base):
    __tablename__ = "prop_seed"
    pretreatment = Column(UnicodeText)
    nseeds = Column(Integer, nullable=False, autoincrement=False)
    date_sown = Column(types.Date, nullable=False)
    container = Column(UnicodeText)  # 4" pot plug tray, other
    media = Column(UnicodeText)  # seedling media, sphagnum, other

    # covered with #2 granite grit: no, yes, lightly heavily
    covered = Column(UnicodeText)

    # not same as location table, glasshouse(bottom heat, no bottom
    # heat), polyhouse, polyshade house, fridge in polybag
    location = Column(UnicodeText)

    # TODO: do we need multiple moved to->moved from and date fields
    moved_from = Column(UnicodeText)
    moved_to = Column(UnicodeText)
    moved_date = Column(types.Date)

    germ_date = Column(types.Date)

    nseedlings = Column(Integer, autoincrement=False)  # number of seedling
    germ_pct = Column(Integer, autoincrement=False)  # % of germination
    date_planted = Column(types.Date)

    propagation_id = Column(
        Integer, ForeignKey("propagation.id"), nullable=False
    )

    def __str__(self):
        # what would the string be...???
        # cuttings of self.accession.species_str() and accession number
        return repr(self)


class PropagationTabPresenter(editor.GenericEditorPresenter):
    """PropagationTabPresenter

    :param parent: an instance of PlantEditorPresenter
    :param model: an instance of class Plant
    :param view: an instance of PlantEditorView
    :param session:
    """

    def __init__(self, parent, model, view, session):
        super().__init__(model, view)
        self.parent_ref = weakref.ref(parent)
        self.session = session
        self.view.connect(
            "prop_add_button", "clicked", self.on_add_button_clicked
        )
        tab_box = self.view.widgets.prop_tab_box
        for kid in tab_box:
            if isinstance(kid, Gtk.Box):
                tab_box.remove(kid)  # remove old prop boxes
        for prop in self.model.propagations:
            box = self.create_propagation_box(prop)
            tab_box.pack_start(box, False, True, 0)
        self._dirty = False

    def is_dirty(self):
        return self._dirty

    def add_propagation(self):
        """Open the PropagationEditor and append the resulting propagation to
        self.model.propagations
        """
        propagation = Propagation()
        # pylint: disable=attribute-defined-outside-init
        propagation.plant = self.model
        prop_editor = PropagationEditor(
            propagation, parent=self.view.get_window()
        )
        # open propagation editor with start(commit=False) so that the
        # propagation editor doesn't commit its changes since we'll be
        # doing our own commit later
        committed = prop_editor.start(commit=False)
        if committed:
            box = self.create_propagation_box(committed)
            self.view.widgets.prop_tab_box.pack_start(box, False, True, 0)
            self._dirty = True
        else:
            propagation.plant = None

    def create_propagation_box(self, propagation):
        hbox = Gtk.Box()
        expander = Gtk.Expander()
        hbox.pack_start(expander, True, True, 0)

        label = Gtk.Label(label=propagation.get_summary())
        label.props.wrap = True
        label.set_xalign(0)
        label.set_yalign(0)
        label.set_margin_start(15)
        label.set_margin_end(5)
        label.set_margin_top(2)
        label.set_margin_bottom(2)
        expander.add(label)

        def on_edit_clicked(_button, prop, label):
            prop_editor = PropagationEditor(
                model=prop, parent=self.view.get_window()
            )
            if prop_editor.start(commit=False) is not None:
                label.props.label = prop.get_summary()
                self._dirty = True
            self.parent_ref().refresh_sensitivity()

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        button_box = Gtk.Box(spacing=5)
        vbox.pack_start(button_box, False, False, 0)
        hbox.pack_start(vbox, False, False, 0)
        button = Gtk.Button(label="Edit")
        button.set_vexpand(False)
        self.view.connect(
            button, "clicked", on_edit_clicked, propagation, label
        )
        button_box.pack_start(button, False, False, 0)

        remove_button = Gtk.Button.new_from_icon_name(
            "list-remove-symbolic", Gtk.IconSize.BUTTON
        )
        self.view.connect(
            remove_button, "clicked", self.on_remove_clicked, propagation, hbox
        )
        button_box.pack_start(remove_button, False, False, 0)

        # TODO: add a * to the propagation label for uncommitted propagations
        prop_type = prop_type_values[propagation.prop_type]

        # hack to format date properly
        from bauble.btypes import Date

        date = Date().process_bind_param(propagation.date, None)
        date_str = date.strftime(prefs.prefs[prefs.date_format_pref])

        title = _("%(prop_type)s on %(prop_date)s") % dict(
            prop_type=prop_type, prop_date=date_str
        )
        expander.set_label(title)

        hbox.show_all()
        return hbox

    def on_remove_clicked(self, _button, propagation, box):
        count = len(propagation.accessions)
        potential = propagation.accessible_quantity
        if count == 0:
            if potential:
                msg = (
                    _(
                        "This propagation has produced %s plants.\n"
                        "It can already be accessioned.\n\n"
                        "Are you sure you want to remove it?"
                    )
                    % potential
                )
            else:
                msg = _(
                    "Are you sure you want to remove\n"
                    "this propagation trial?"
                )
            if not utils.yes_no_dialog(msg):
                return False
        else:
            if count == 1:
                msg = (
                    _(
                        "This propagation is referred to\n"
                        "by accession %s.\n\n"
                        "You cannot remove it."
                    )
                    % propagation.accessions[0]
                )
            elif count > 1:
                msg = (
                    _(
                        "This propagation is referred to\n"
                        "by %s accessions.\n\n"
                        "You cannot remove it."
                    )
                    % count
                )
            utils.message_dialog(msg, typ=Gtk.MessageType.WARNING)
            return False
        self.model.propagations.remove(propagation)
        self.view.widgets.prop_tab_box.remove(box)
        self._dirty = True
        self.parent_ref().refresh_sensitivity()
        return None

    def on_add_button_clicked(self, *_args):
        self.add_propagation()
        self.parent_ref().refresh_sensitivity()


class PropagationEditorView(editor.GenericEditorView):
    _tooltips = {}

    def __init__(self, parent=None):
        super().__init__(
            os.path.join(
                paths.lib_dir(), "plugins", "garden", "prop_editor.glade"
            ),
            parent=parent,
        )
        self.init_translatable_combo("prop_type_combo", prop_type_values)

    def get_window(self):
        return self.widgets.prop_dialog

    def start(self):
        return self.get_window().run()


def distinct(current, session):
    return utils.get_distinct_values(current, session)


class CuttingPresenter(editor.GenericEditorPresenter):
    widget_to_field_map = {
        "cutting_type_combo": "cutting_type",
        "cutting_length_entry": "length",
        "cutting_length_unit_combo": "length_unit",
        "cutting_tip_combo": "tip",
        "cutting_leaves_combo": "leaves",
        "cutting_lvs_reduced_entry": "leaves_reduced_pct",
        "cutting_buds_combo": "flower_buds",
        "cutting_wound_combo": "wound",
        "cutting_fungal_comboentry": "fungicide",
        "cutting_media_comboentry": "media",
        "cutting_container_comboentry": "container",
        "cutting_hormone_comboentry": "hormone",
        "cutting_location_comboentry": "location",
        "cutting_cover_comboentry": "cover",
        "cutting_heat_entry": "bottom_heat_temp",
        "cutting_heat_unit_combo": "bottom_heat_unit",
        "cutting_rooted_pct_entry": "rooted_pct",
    }

    def __init__(self, parent, model, view, session):
        """
        :param model: an instance of class Propagation
        :param view: an instance of PropagationEditorView
        """
        super().__init__(model, view, session=session, connect_signals=False)
        self.parent_ref = weakref.ref(parent)
        self._dirty = False

        # instance is initialized with a Propagation instance as model, but
        # that's just the common parts.  This instance takes care of the
        # cutting part of the propagation
        self.propagation = self.model
        if not self.propagation.cutting:
            self.propagation.cutting = PropCutting()
        self.model = self.model.cutting

        self.init_combos()

        # set default units
        if prefs.prefs.get(prefs.units_pref) == "imperial":
            self.model.length_unit = "in"
            self.model.bottom_heat_unit = "F"
        else:
            self.model.length_unit = "mm"
            self.model.bottom_heat_unit = "C"

        # the liststore for rooted cuttings contains PropCuttingRooted
        # objects, not just their fields, so we cannot define it in the
        # glade file.
        rooted_liststore = Gtk.ListStore(object)
        self.view.widgets.rooted_treeview.set_model(rooted_liststore)

        from functools import partial

        def on_rooted_cell_edited(attr_name, _cell, path, new_text):
            # update object if field was modified, refresh sensitivity
            rooted = rooted_liststore[path][0]
            if getattr(rooted, attr_name) == new_text:
                return  # didn't change
            setattr(rooted, attr_name, utils.nstr(new_text))
            self._dirty = True
            self.parent_ref().refresh_sensitivity()

        widgets = self.view.widgets
        for cell, column, attr_name in [
            (widgets.rooted_date_cell, widgets.rooted_date_column, "date"),
            (
                widgets.rooted_quantity_cell,
                widgets.rooted_quantity_column,
                "quantity",
            ),
        ]:
            cell.props.editable = True
            self.view.connect(
                cell, "edited", partial(on_rooted_cell_edited, attr_name)
            )
            column.set_cell_data_func(
                cell, self.rooted_cell_data_func, attr_name
            )

        self.refresh_view()

        self.assign_handlers()

        self.view.connect(
            "rooted_add_button", "clicked", self.on_rooted_add_clicked
        )
        self.view.connect(
            "rooted_remove_button", "clicked", self.on_rooted_remove_clicked
        )

    def init_combos(self):
        init_combo = self.view.init_translatable_combo
        init_combo("cutting_type_combo", cutting_type_values)
        init_combo("cutting_length_unit_combo", length_unit_values)
        init_combo("cutting_tip_combo", tip_values)
        init_combo("cutting_leaves_combo", leaves_values)
        init_combo("cutting_buds_combo", flower_buds_values)
        init_combo("cutting_wound_combo", wound_values)
        init_combo("cutting_heat_unit_combo", bottom_heat_unit_values)
        widgets = self.view.widgets

        utils.setup_text_combobox(
            widgets.cutting_hormone_comboentry,
            distinct(PropCutting.hormone, self.session),
        )
        utils.setup_text_combobox(
            widgets.cutting_cover_comboentry,
            distinct(PropCutting.cover, self.session),
        )
        utils.setup_text_combobox(
            widgets.cutting_fungal_comboentry,
            distinct(PropCutting.fungicide, self.session),
        )
        nursery_locations = distinct(PropCutting.location, self.session)
        nursery_locations += distinct(PropSeed.location, self.session)
        utils.setup_text_combobox(
            widgets.cutting_location_comboentry, sorted(set(nursery_locations))
        )
        containers = distinct(PropCutting.container, self.session)
        containers += distinct(PropSeed.container, self.session)
        utils.setup_text_combobox(
            widgets.cutting_container_comboentry, sorted(set(containers))
        )
        media = distinct(PropCutting.media, self.session)
        media += distinct(PropSeed.media, self.session)
        utils.setup_text_combobox(
            widgets.cutting_media_comboentry, sorted(set(media))
        )

    def assign_handlers(self):
        self.assign_simple_handler("cutting_type_combo", "cutting_type")
        self.assign_simple_handler("cutting_length_entry", "length")
        self.assign_simple_handler("cutting_length_unit_combo", "length_unit")
        self.assign_simple_handler("cutting_tip_combo", "tip")
        self.assign_simple_handler("cutting_leaves_combo", "leaves")
        self.assign_simple_handler(
            "cutting_lvs_reduced_entry", "leaves_reduced_pct"
        )

        self.assign_simple_handler(
            "cutting_media_comboentry", "media", editor.StringOrNoneValidator()
        )
        self.assign_simple_handler(
            "cutting_container_comboentry",
            "container",
            editor.StringOrNoneValidator(),
        )

        self.assign_simple_handler("cutting_buds_combo", "flower_buds")
        self.assign_simple_handler("cutting_wound_combo", "wound")
        self.assign_simple_handler(
            "cutting_fungal_comboentry",
            "fungicide",
            editor.StringOrNoneValidator(),
        )
        self.assign_simple_handler(
            "cutting_hormone_comboentry",
            "hormone",
            editor.StringOrNoneValidator(),
        )
        self.assign_simple_handler(
            "cutting_location_comboentry",
            "location",
            editor.StringOrNoneValidator(),
        )
        self.assign_simple_handler(
            "cutting_cover_comboentry", "cover", editor.StringOrNoneValidator()
        )
        self.assign_simple_handler("cutting_heat_entry", "bottom_heat_temp")
        self.assign_simple_handler(
            "cutting_heat_unit_combo", "bottom_heat_unit"
        )
        self.assign_simple_handler("cutting_rooted_pct_entry", "rooted_pct")

    @staticmethod
    def rooted_cell_data_func(
        _column, cell, rooted_liststore, treeiter, attr_name
    ):
        # extract attr from the object and show it in the cell
        val = rooted_liststore[treeiter][0]
        # datetime change format to the pref
        attr = getattr(val, attr_name)
        if isinstance(attr, datetime.date):
            frmt = prefs.prefs.get(prefs.date_format_pref)
            attr = attr.strftime(frmt)

        cell.set_property("text", str(attr) if attr else None)

    def is_dirty(self):
        return self._dirty

    def set_model_attr(self, attr, value, validator=None):
        super().set_model_attr(attr, value, validator)
        self._dirty = True
        self.parent_ref().refresh_sensitivity()

    def on_rooted_add_clicked(self, _button, *_args):
        tree = self.view.widgets.rooted_treeview
        rooted = PropCuttingRooted()
        # pylint: disable=attribute-defined-outside-init
        rooted.cutting = self.model
        rooted.date = utils.today_str()
        model = tree.get_model()
        treeiter = model.insert(0, [rooted])
        path = model.get_path(treeiter)
        column = tree.get_column(0)
        tree.set_cursor(path, column, start_editing=True)

    def on_rooted_remove_clicked(self, _button, *_args):
        tree = self.view.widgets.rooted_treeview
        model, treeiter = tree.get_selection().get_selected()
        if not treeiter:
            return
        rooted = model[treeiter][0]
        rooted.cutting = None
        model.remove(treeiter)
        self._dirty = True
        self.parent_ref().refresh_sensitivity()

    def refresh_view(self):
        # TODO: not so sure. is this a 'refresh', or a 'init' view?
        for widget, attr in self.widget_to_field_map.items():
            value = getattr(self.model, attr)
            self.view.widget_set_value(widget, value)
        rooted_liststore = self.view.widgets.rooted_treeview.get_model()
        rooted_liststore.clear()
        for rooted in self.model.rooted:
            rooted_liststore.append([rooted])


class SeedPresenter(editor.GenericEditorPresenter):
    widget_to_field_map = {
        "seed_pretreatment_textview": "pretreatment",
        "seed_nseeds_entry": "nseeds",
        "seed_sown_entry": "date_sown",
        "seed_container_comboentry": "container",
        "seed_media_comboentry": "media",
        "seed_location_comboentry": "location",
        "seed_mvdfrom_entry": "moved_from",
        "seed_mvdto_entry": "moved_to",
        "seed_germdate_entry": "germ_date",
        "seed_ngerm_entry": "nseedlings",
        "seed_pctgerm_entry": "germ_pct",
        "seed_date_planted_entry": "date_planted",
    }

    def __init__(self, parent, model, view, session):
        """
        :param model: an instance of class Propagation
        :param view: an instance of PropagationEditorView
        """
        super().__init__(model, view, session=session, connect_signals=False)
        self._dirty = False
        self.parent_ref = weakref.ref(parent)

        self.propagation = self.model
        if not self.propagation.seed:
            self.propagation.seed = PropSeed()
        self.model = self.model.seed

        # TODO: if % germinated is not entered and nseeds and #
        # germinated are then automatically calculate the % germinated

        media = distinct(PropCutting.media, self.session)
        media += distinct(PropSeed.media, self.session)
        utils.setup_text_combobox(
            self.view.widgets.seed_media_comboentry, sorted(set(media))
        )
        containers = distinct(PropCutting.container, self.session)
        containers += distinct(PropSeed.container, self.session)
        utils.setup_text_combobox(
            self.view.widgets.seed_container_comboentry,
            sorted(set(containers)),
        )
        nursery_locations = distinct(PropCutting.location, self.session)
        nursery_locations += distinct(PropSeed.location, self.session)
        utils.setup_text_combobox(
            self.view.widgets.seed_location_comboentry,
            sorted(set(nursery_locations)),
        )

        self.refresh_view()

        self.assign_simple_handler(
            "seed_pretreatment_textview",
            "pretreatment",
            editor.StringOrNoneValidator(),
        )
        # TODO: this should validate to an integer
        self.assign_simple_handler(
            "seed_nseeds_entry", "nseeds", editor.StringOrNoneValidator()
        )
        self.assign_simple_handler(
            "seed_sown_entry", "date_sown", editor.DateValidator()
        )
        utils.setup_date_button(
            self.view, "seed_sown_entry", "seed_sown_button"
        )
        self.assign_simple_handler(
            "seed_container_comboentry",
            "container",
            editor.StringOrNoneValidator(),
        )
        self.assign_simple_handler(
            "seed_media_comboentry", "media", editor.StringOrNoneValidator()
        )
        self.assign_simple_handler(
            "seed_location_comboentry",
            "location",
            editor.StringOrNoneValidator(),
        )
        self.assign_simple_handler(
            "seed_mvdfrom_entry", "moved_from", editor.StringOrNoneValidator()
        )
        self.assign_simple_handler(
            "seed_mvdto_entry", "moved_to", editor.StringOrNoneValidator()
        )
        self.assign_simple_handler(
            "seed_germdate_entry", "germ_date", editor.DateValidator()
        )
        utils.setup_date_button(
            self.view, "seed_germdate_entry", "seed_germdate_button"
        )
        self.assign_simple_handler("seed_ngerm_entry", "nseedlings")
        self.assign_simple_handler("seed_pctgerm_entry", "germ_pct")
        self.assign_simple_handler(
            "seed_date_planted_entry", "date_planted", editor.DateValidator()
        )
        utils.setup_date_button(
            self.view, "seed_date_planted_entry", "seed_date_planted_button"
        )

    def is_dirty(self):
        return self._dirty

    def set_model_attr(self, attr, value, validator=None):
        logger.debug("%s = %s", attr, value)
        super().set_model_attr(attr, value, validator)
        self._dirty = True
        self.parent_ref().refresh_sensitivity()

    def refresh_view(self):
        date_format = prefs.prefs[prefs.date_format_pref]
        for widget, attr in self.widget_to_field_map.items():
            value = getattr(self.model, attr)
            if isinstance(value, datetime.date):
                value = value.strftime(date_format)
            self.view.widget_set_value(widget, value)


class PropagationPresenter(editor.ChildPresenter):
    """PropagationPresenter is extended by SourcePropagationPresenter and
    PropagationEditorPresenter.
    """

    widget_to_field_map = {
        "prop_type_combo": "prop_type",
        "prop_date_entry": "date",
        "notes_textview": "notes",
    }

    def __init__(self, model, view, session=None):
        """
        :param model: an instance of class Propagation
        :param view: an instance of PropagationEditorView
        """
        super().__init__(model, view, session=session)

        # initialize the propagation type combo and set the initial value
        self.view.connect(
            "prop_type_combo", "changed", self.on_prop_type_changed
        )
        if self.model.prop_type:
            self.view.widget_set_value("prop_type_combo", self.model.prop_type)

        self._cutting_presenter = CuttingPresenter(
            self, self.model, self.view, self.session
        )
        self._seed_presenter = SeedPresenter(
            self, self.model, self.view, self.session
        )

        if not self.model.prop_type:
            view.widgets.prop_details_box.props.visible = False

        if self.model.date:
            self.view.widget_set_value(
                self.view.widgets.prop_date_entry, self.model.date
            )
        else:
            self.view.widget_set_value(
                self.view.widgets.prop_date_entry, utils.today_str()
            )

        self.view.widget_set_value(
            self.view.widgets.notes_textview, self.model.notes
        )

        self._dirty = False
        utils.setup_date_button(
            self.view, "prop_date_entry", "prop_date_button"
        )
        self.assign_simple_handler(
            "prop_date_entry", "date", editor.DateValidator()
        )
        self.assign_simple_handler(
            "notes_textview", "notes", editor.StringOrNoneValidator()
        )

        def on_expanded(*_args):
            if self.model.prop_type == "Other":
                # i don't really understand why setting the expanded
                # property to false here cause the notes_expander to
                # always stay expanded but it works
                self.view.widgets.notes_expander.props.expanded = False

        self.view.connect("notes_expander", "activate", on_expanded)

    def on_prop_type_changed(self, combo, *_args):
        itr = combo.get_active_iter()
        prop_type = combo.get_model()[itr][0]
        if self.model.prop_type != prop_type:
            # only call set_model_attr() if the value is changed to
            # avoid prematuraly calling dirty() and refresh_sensitivity()
            self.set_model_attr("prop_type", prop_type)
        prop_box_map = {
            "Seed": self.view.widgets.seed_box,
            "UnrootedCutting": self.view.widgets.cutting_box,
        }
        for type_, box in prop_box_map.items():
            box.props.visible = prop_type == type_

        self.view.widgets.notes_box.props.visible = True
        if prop_type == "Other" or self.model.notes:
            self.view.widgets.notes_expander.props.expanded = True

        self.view.widgets.prop_details_box.props.visible = True

        if not self.model.date:
            self.view.widgets.prop_date_entry.emit("changed")

    def is_dirty(self):
        if self.model.prop_type == "UnrootedCutting":
            return self._cutting_presenter.is_dirty() or self._dirty
        if self.model.prop_type == "Seed":
            return self._seed_presenter.is_dirty() or self._dirty
        return self._dirty

    def set_model_attr(self, attr, value, validator=None):
        """Set attributes on the model and update the GUI as expected."""
        logging.debug("%s = %s", attr, value)
        super().set_model_attr(attr, value, validator)
        self._dirty = True
        self.refresh_sensitivity()

    def cleanup(self):
        self._cutting_presenter.cleanup()
        self._seed_presenter.cleanup()

    def refresh_sensitivity(self):
        pass

    def refresh_view(self):
        pass


class SourcePropagationPresenter(PropagationPresenter):
    """Presenter for creating a new Propagation for the Source.propagation
    property.

    This type of propagation is not associated with a Plant.

    :param parent: SourcePresenter
    :param model:  Propagation instance
    :param view:  AccessionEditorView
    :param session: sqlalchemy.orm.sesssion
    """

    def __init__(self, parent, model, view, session):
        self.parent_ref = weakref.ref(parent)
        try:
            view.widgets.prop_main_box
        except Exception as e:
            logger.debug("init SourcePropagationPresenter %s", type(e))
            # TODO need to investigate this further, can't see a need for try
            # except here, should never fail as widgets are added in the view.
            # only add the propagation editor widgets to the view
            # widgets if the widgets haven't yet been added
            filename = os.path.join(
                paths.lib_dir(), "plugins", "garden", "prop_editor.glade"
            )
            view.widgets.builder.add_from_file(filename)
        prop_main_box = view.widgets.prop_main_box
        view.widgets.remove_parent(prop_main_box)
        view.widgets.acc_prop_box_parent.add(prop_main_box)

        # since the view here will be an AccessionEditorView and not a
        # PropagationEditorView then we need to do anything here that
        # PropagationEditorView would do
        view.init_translatable_combo("prop_type_combo", prop_type_values)
        # add None to the prop types which is specific to
        # SourcePropagationPresenter since we might also need to
        # remove the propagation...this will need to be called before
        # the PropagationPresenter.on_prop_type_changed or it won't work
        view.widgets.prop_type_combo.get_model().append([None, ""])

        self._dirty = False
        super().__init__(model, view, session=session)

    def on_prop_type_changed(self, combo, *args):
        """Override PropagationPresenter.on_type_changed() to handle the None
        value in the prop_type_combo which is specific the
        SourcePropagationPresenter
        """
        logger.debug("SourcePropagationPresenter.on_prop_type_changed()")
        itr = combo.get_active_iter()
        prop_type = combo.get_model()[itr][0]
        if not prop_type:
            self.set_model_attr("prop_type", None)
            self.view.widgets.prop_details_box.props.visible = False
        else:
            super().on_prop_type_changed(combo, *args)
        self._dirty = False

    def set_model_attr(self, attr, value, validator=None):
        logger.debug("set_model_attr(%s, %s)", attr, value)
        super().set_model_attr(attr, value)
        self._dirty = True
        self.refresh_sensitivity()

    def refresh_sensitivity(self):
        self.parent_ref().refresh_sensitivity()

    def is_dirty(self):
        return super().is_dirty() or self._dirty


class PropagationEditorPresenter(PropagationPresenter):
    def __init__(self, model, view):
        """
        :param model: an instance of class Propagation
        :param view: an instance of PropagationEditorView
        """
        super().__init__(model, view)
        # don't allow changing the propagation type if we are editing
        # an existing propagation
        if model not in self.session.new or self.model.prop_type:
            self.view.widgets.prop_type_box.props.visible = False
        elif not self.model.prop_type:
            self.view.widgets.prop_type_box.props.visible = True
            self.view.widgets.prop_details_box.props.visible = False
        self.view.widgets.prop_ok_button.props.sensitive = False

    def start(self):
        response = self.view.start()
        return response

    def refresh_sensitivity(self):
        super().refresh_sensitivity()
        sensitive = True

        if utils.get_invalid_columns(self.model):
            sensitive = False

        model = None
        if object_session(self.model):
            if self.model.prop_type == "UnrootedCutting":
                model = self.model.cutting
            elif self.model.prop_type == "Seed":
                model = self.model.seed

        if model:
            invalid = utils.get_invalid_columns(
                model, ["id", "propagation_id"]
            )
            # TODO: highlight the widget with are associated with the
            # columns that have bad values
            if invalid:
                sensitive = False
        elif self.model.notes:
            sensitive = True
        else:
            sensitive = False
        self.view.widgets.prop_ok_button.props.sensitive = sensitive


class PropagationEditor(editor.GenericModelViewPresenterEditor):
    # these have to correspond to the response values in the view
    RESPONSE_OK_AND_ADD = 11
    RESPONSE_NEXT = 22
    ok_responses = (RESPONSE_OK_AND_ADD, RESPONSE_NEXT)

    def __init__(self, model, parent=None):
        """
        :param prop_parent: an instance with a propagation relation
        :param model: Propagation instance
        :param parent: the parent widget
        """
        super().__init__(model, parent)
        # if mode already has a session then use it, this is unique to
        # the PropagationEditor because so far it is the only editor
        # that dependent on a parent editor and the parent editor's
        # model and session
        sess = object_session(model)
        if sess:
            self.session.close()
            self.session = sess
            self.model = model

        import bauble

        if not parent and bauble.gui:
            parent = bauble.gui.window
        self.parent = parent

        view = PropagationEditorView(parent=self.parent)
        self.presenter = PropagationEditorPresenter(self.model, view)
        self._return = None

    def handle_response(self, response, commit=True):
        """handle the response from self.presenter.start() in self.start()"""
        not_ok_msg = "Are you sure you want to lose your changes?"
        self._return = None
        self.model.clean()
        if response == Gtk.ResponseType.OK or response in self.ok_responses:
            try:
                self._return = self.model
                if self.presenter.is_dirty() and commit:
                    self.commit_changes()
            except DBAPIError as e:
                msg = _("Error committing changes.\n\n%s") % utils.xml_safe(
                    str(e.orig)
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
                logger.debug(traceback.format_exc())
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

        return True

    def __del__(self):
        # override the editor.GenericModelViewPresenterEditor since it
        # will close the session but since we are called with the
        # AccessionEditor's session we don't want that
        #
        # TODO: when should we close the session and not, what about
        # is self.commit is True
        pass

    def start(self, commit=True):
        while True:
            response = self.presenter.start()
            self.presenter.view.save_state()
            if self.handle_response(response, commit):
                break

        # don't close the session since the PropagationEditor depends
        # on an PlantEditor...?
        #
        # self.session.close()  # cleanup session
        self.presenter.cleanup()
        return self._return
