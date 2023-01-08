# Copyright 2008-2010 Brett Adams
# Copyright 2012-2017 Mario Frasca <mario@anche.no>.
# Copyright 2017 Jardín Botánico de Quito
# Copyright 2017-2023 Ross Demuth
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
report plugin.
"""

import os
import traceback

import logging
logger = logging.getLogger(__name__)

from gi.repository import Gtk
from gi.repository import GLib

import bauble
from bauble.error import BaubleError
from bauble import prefs
from bauble import utils
from bauble import paths
from bauble import pluginmgr
from bauble.plugins.plants import (Family,
                                   Genus,
                                   Species,
                                   VernacularName,
                                   Geography)
from bauble.plugins.garden import (Accession,
                                   Plant,
                                   Location,
                                   SourceDetail,
                                   Collection)
from bauble.plugins.tag import Tag
from .template_downloader import TemplateDownloadTool


# name: formatter_class, formatter_kwargs
CONFIG_LIST_PREF = 'report.configs'
"""
the preferences key for report configurations.

Value: a dict of names to settings.
"""

# the default report generator to select on start
DEFAULT_CONFIG_PREF = 'report.current'
"""
the preferences key the currently selected report.
"""


# to be populated by the dialog box, with fields mentioned in the template
options = {}


def _pertinent_objects_generator(query, order_by):
    """Generator to return results and update progressbar in tasks."""
    from bauble import pb_set_fraction
    num_objs = query.distinct().count()
    if order_by:
        query = query.order_by(*order_by)
    five_percent = int(num_objs / 20) or 1
    for records_done, item in enumerate(query):
        if records_done % five_percent == 0:
            pb_set_fraction(records_done / num_objs)
        yield item


def _get_pertinent_objects(cls,
                           get_query_func,
                           objs,
                           session,
                           as_task=False,
                           order_by=None):
    """
    :param cls: class of the objects to return
    :param get_query_func:
    :param objs:
    :param session:
    :param as_task: if True return a generator appropriate for use in tasks.
    :param order_by: columns to order_by
    """
    close_session = False
    if session is None:
        from bauble import db
        session = db.Session()
        close_session = True

    if not isinstance(objs, (tuple, list)):
        objs = [objs]

    # query once for each type
    grouped = {}
    for obj in objs:
        grouped.setdefault(type(obj), []).append(obj)

    queries = [
        get_query_func(cls, objs, session) for cls, objs in grouped.items()
    ]

    query = queries[0]
    has_union = len(queries) > 1
    if has_union:
        query = query.union(*queries[1:])

    join = None
    for col in order_by:
        if (klass := col.class_) is not cls:
            join = klass
    # this ugly hack because query._join_entities is deprecated and the
    # SQL output is predictable
    if join and (f'JOIN {join.__tablename__}' not in str(query) or has_union):
        query = query.join(join)

    try:
        if as_task:
            from bauble import task
            return task.queue(_pertinent_objects_generator(query, order_by),
                              yielding=True)

        if order_by:
            query = query.order_by(*order_by)

        return query
    finally:
        if close_session:
            session.close()


# pylint: disable=too-many-return-statements
def get_plant_query(cls, objs, session):
    query = session.query(Plant)

    if prefs.prefs.get(prefs.exclude_inactive_pref):
        # filter out inactive
        query = query.filter(Plant.active.is_(True))

    ids = {obj.id for obj in objs}
    if cls is Family:
        return (query.join('accession', 'species', 'genus', 'family')
                .filter(Family.id.in_(ids)))
    if cls is Genus:
        return (query.join('accession', 'species', 'genus')
                .filter(Genus.id.in_(ids)))
    if cls is Species:
        return query.join('accession', 'species').filter(Species.id.in_(ids))
    if cls is VernacularName:
        return (query.join('accession', 'species', 'vernacular_names')
                .filter(VernacularName.id.in_(ids)))
    if cls is Geography:
        return (query.join('accession', 'species', 'distribution', 'geography')
                .filter(Geography.id.in_(ids)))
    if cls is Plant:
        return query.filter(Plant.id.in_(ids))
    if cls is Accession:
        return query.join('accession').filter(Accession.id.in_(ids))
    if cls is Collection:
        return (query.join('accession', 'source', 'collection')
                .filter(Collection.id.in_(ids)))
    if cls is Location:
        return query.filter(Plant.location_id.in_(ids))
    if cls is SourceDetail:
        return (query.join('accession', 'source', 'source_detail')
                .filter(SourceDetail.id.in_(ids)))
    if cls is Tag:
        plants = get_plants_pertinent_to(
            [i for obj in objs for i in obj.objects], session
        )
        return query.filter(Plant.id.in_([plt.id for plt in plants]))
    raise BaubleError(_("Can't get plants from a %s") % cls.__name__)


def get_plants_pertinent_to(objs, session=None, as_task=False):
    """
    :param objs: an instance of a mapped object
    :param session: the session to use for the queries
    :param as_task: if True will yield results and update progressbar as
        appropriate for use in a yielding task

    Return all the plants found in objs.
    """
    order_by = [Accession.code, Plant.code]
    return _get_pertinent_objects(Plant, get_plant_query, objs, session,
                                  as_task, order_by=order_by)


def get_accession_query(cls, objs, session):
    query = session.query(Accession)

    if prefs.prefs.get(prefs.exclude_inactive_pref):
        # filter out inactive
        query = query.filter(Accession.active.is_(True))

    ids = {obj.id for obj in objs}
    if cls is Family:
        return (query.join('species', 'genus', 'family')
                .filter(Family.id.in_(ids)))
    if cls is Genus:
        return query.join('species', 'genus').filter(Genus.id.in_(ids))
    if cls is Species:
        return query.join('species').filter(Species.id.in_(ids))
    if cls is VernacularName:
        return (query.join('species', 'vernacular_names')
                .filter(VernacularName.id.in_(ids)))
    if cls is Geography:
        return (query.join('species', 'distribution', 'geography')
                .filter(Geography.id.in_(ids)))
    if cls is Plant:
        return query.join('plants').filter(Plant.id.in_(ids))
    if cls is Accession:
        return query.filter(Accession.id.in_(ids))
    if cls is Collection:
        return (query.join('source', 'collection')
                .filter(Collection.id.in_(ids)))
    if cls is Location:
        return query.join('plants').filter(Plant.location_id.in_(ids))
    if cls is SourceDetail:
        return (query.join('source', 'source_detail')
                .filter(SourceDetail.id.in_(ids)))
    if cls is Tag:
        accessions = get_accessions_pertinent_to(
            [i for obj in objs for i in obj.objects], session
        )
        return query.filter(Accession.id.in_([acc.id for acc in accessions]))
    raise BaubleError(_("Can't get accessions from a %s") % cls.__name__)


def get_accessions_pertinent_to(objs, session=None, as_task=False):
    """
    :param objs: an instance of a mapped object
    :param session: the session to use for the queries
    :param as_task: if True will yield results and update progressbar as
        appropriate for use in a yielding task

    Return all the accessions found in objs.
    """
    return _get_pertinent_objects(Accession, get_accession_query, objs,
                                  session, as_task, order_by=[Accession.code])


def get_species_query(cls, objs, session):
    query = session.query(Species)

    if prefs.prefs.get(prefs.exclude_inactive_pref):
        # filter out inactive
        query = query.filter(Species.active.is_(True))

    ids = {obj.id for obj in objs}
    if cls is Family:
        return (query.join('genus', 'family')
                .filter(cls.id.in_(ids)))
    if cls is Genus:
        return query.join('genus').filter(cls.id.in_(ids))
    if cls is Species:
        return query.filter(cls.id.in_(ids))
    if cls is VernacularName:
        return query.join('vernacular_names').filter(cls.id.in_(ids))
    if cls is Geography:
        return query.join('distribution', 'geography').filter(cls.id.in_(ids))
    if cls is Plant:
        return query.join('accessions', 'plants').filter(cls.id.in_(ids))
    if cls is Accession:
        return query.join('accessions').filter(cls.id.in_(ids))
    if cls is Collection:
        return (query.join('accessions', 'source', 'collection')
                .filter(cls.id.in_(ids)))
    if cls is Location:
        return (query.join('accessions', 'plants', 'location')
                .filter(cls.id.in_(ids)))
    if cls is SourceDetail:
        return (query.join('accessions', 'source', 'source_detail')
                .filter(cls.id.in_(ids)))
    if cls is Tag:
        species = get_species_pertinent_to(
            [i for obj in objs for i in obj.objects], session
        )
        return query.filter(Species.id.in_([sp.id for sp in species]))
    raise BaubleError(_("Can't get species from a %s") % cls.__name__)


def get_species_pertinent_to(objs, session=None, as_task=False):
    """
    :param objs: an instance of a mapped object
    :param session: the session to use for the queries
    :param as_task: if True will yield results and update progressbar as
        appropriate for use in a yielding task

    Return all the species found in objs.
    """
    return _get_pertinent_objects(Species, get_species_query, objs, session,
                                  as_task, order_by=[Genus.genus, Species.sp])


def get_location_query(cls, objs, session):
    query = session.query(Location)
    ids = {obj.id for obj in objs}
    if cls is Location:
        return query.filter(cls.id.in_(ids))
    if cls is Plant:
        return query.join('plants').filter(cls.id.in_(ids))
    if cls is Accession:
        return query.join('plants', 'accession').filter(cls.id.in_(ids))
    if cls is Collection:
        return (query.join('plants', 'accession', 'source', 'collection')
                .filter(cls.id.in_(ids)))
    if cls is Family:
        return (query.join('plants', 'accession', 'species', 'genus', 'family')
                .filter(cls.id.in_(ids)))
    if cls is Genus:
        return (query.join('plants', 'accession', 'species', 'genus')
                .filter(cls.id.in_(ids)))
    if cls is Species:
        return (query.join('plants', 'accession', 'species')
                .filter(cls.id.in_(ids)))
    if cls is VernacularName:
        return (query.join('plants', 'accession', 'species',
                           'vernacular_names')
                .filter(cls.id.in_(ids)))
    if cls is Geography:
        return (query.join('plants', 'accession', 'species', 'distribution',
                           'geography')
                .filter(cls.id.in_(ids)))
    if cls is SourceDetail:
        return (query.join('plants', 'accession', 'source', 'source_detail')
                .filter(cls.id.in_(ids)))
    if cls is Tag:
        locs = get_locations_pertinent_to(
            [i for obj in objs for i in obj.objects], session
        )
        return query.filter(Location.id.in_([loc.id for loc in locs]))
    raise BaubleError(_("Can't get Location from a %s") % cls.__name__)


def get_locations_pertinent_to(objs, session=None, as_task=False):
    """
    :param objs: an instance of a mapped object
    :param session: the session to use for the queries
    :param as_task: if True will yield results and update progressbar as
        appropriate for use in a yielding task

    Return all the locations found in objs.
    """
    return _get_pertinent_objects(Location, get_location_query, objs,
                                  session, as_task, order_by=[Location.code])


def get_geography_query(cls, objs, session):
    query = session.query(Geography)
    ids = {obj.id for obj in objs}
    if cls is Geography:
        return query.filter(cls.id.in_(ids))
    if cls is Plant:
        return (query.join('distribution', 'species', 'accessions', 'plants')
                .filter(cls.id.in_(ids)))
    # This is the exception, it uses the collection geography entry.
    if cls is Accession:
        return (query.join('collection', 'source', 'accession')
                .filter(cls.id.in_(ids)))
    if cls is Collection:
        return (query.join('collection')
                .filter(cls.id.in_(ids)))
    if cls is Family:
        return (query.join('distribution', 'species', 'genus', 'family')
                .filter(cls.id.in_(ids)))
    if cls is Genus:
        return (query.join('distribution', 'species', 'genus')
                .filter(cls.id.in_(ids)))
    if cls is Species:
        return query.join('distribution', 'species').filter(cls.id.in_(ids))
    if cls is Location:
        return (query.join('distribution', 'species', 'accessions', 'plants',
                           'location')
                .filter(cls.id.in_(ids)))
    if cls is VernacularName:
        return (query.join('distribution', 'species', 'vernacular_names')
                .filter(cls.id.in_(ids)))
    if cls is SourceDetail:
        return (query.join('distribution', 'species', 'accessions', 'source',
                           'source_detail')
                .filter(cls.id.in_(ids)))
    if cls is Tag:
        geographies = get_geographies_pertinent_to(
            [i for obj in objs for i in obj.objects], session
        )
        return query.filter(Geography.id.in_([geo.id for geo in geographies]))
    raise BaubleError(_("Can't get Geography from a %s") % cls.__name__)
# pylint: enable=too-many-return-statements


def get_geographies_pertinent_to(objs, session=None, as_task=False):
    """
    :param objs: an instance of a mapped object
    :param session: the session to use for the queries
    :param as_task: if True will yield results and update progressbar as
        appropriate for use in a yielding task

    Return all the locations found in objs.
    """
    return _get_pertinent_objects(Geography, get_geography_query, objs,
                                  session, as_task, order_by=[Geography.name])


class SettingsBox(Gtk.Box):
    """The interface to use for the settings box.

    Formatters should implement this interface and return it from the
    formatters's get_report_settings method
    """
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)

    def get_report_settings(self):
        """return a dict of settings from the settings box gui."""
        raise NotImplementedError

    def update(self, settings):
        """Update the settings box widgets to the values in settings"""
        raise NotImplementedError


class FormatterPlugin(pluginmgr.Plugin):
    """An interface class that a plugin should implement if it wants to
    generate reports with the ReportToolPlugin

    NOTE: the title class attribute must be a unique string
    """

    title = ''

    @staticmethod
    def get_settings_box():
        """return a class the implement Gtk.Box that should hold the gui for
        the formatter
        """
        raise NotImplementedError

    @staticmethod
    def format(selfobjs, **kwargs):
        """Called when the use clicks on OK, this is the worker"""
        raise NotImplementedError


class ReportToolDialogView:

    def __init__(self):
        self.widgets = utils.load_widgets(
            os.path.join(paths.lib_dir(), "plugins", "report", 'report.glade'))
        self.dialog = self.widgets.report_dialog
        self.dialog.set_transient_for(bauble.gui.window)
        self.builder = self.widgets.builder
        utils.setup_text_combobox(self.widgets.names_combo)
        utils.setup_text_combobox(self.widgets.formatter_combo)

        self._delete_sid = self.dialog.connect(
            'delete-event', self.on_dialog_close_or_delete)
        self._close_sid = self.dialog.connect(
            'close', self.on_dialog_close_or_delete)
        self._response_sid = self.dialog.connect(
            'response', self.on_dialog_response)

    @staticmethod
    def on_dialog_response(dialog, response):
        """Called if self.get_window() is a Gtk.Dialog and it receives the
        response signal.
        """
        dialog.hide()
        return response

    @staticmethod
    def on_dialog_close_or_delete(dialog, _event):
        """Called if self.get_window() is a Gtk.Dialog and it receives the
        close signal.
        """
        dialog.hide()
        return False

    def disconnect_all(self):
        self.dialog.disconnect(self._delete_sid)
        self.dialog.disconnect(self._close_sid)
        self.dialog.disconnect(self._response_sid)

    def start(self):
        return self.dialog.run()

    def set_sensitive(self, name, sensitivity):
        widget = self.builder.get_object(name)
        if widget:
            widget.set_sensitive(sensitivity)
        else:
            logger.debug("can't set sensitivity of %s", name)

    def resize(self):
        self.dialog.resize(1, 1)


class ReportToolDialogPresenter:

    formatter_class_map = {}  # title->class map

    def __init__(self, view):
        self.view = view
        self.init_names_combo()
        self.init_formatter_combo()

        self.view.builder.connect_signals(self)

        self.view.set_sensitive('ok_button', False)

        # set the names combo to the default, on_names_combo_changes should
        # do the rest of the work
        default = prefs.prefs.get(DEFAULT_CONFIG_PREF)
        try:
            self.set_names_combo(default)
        except ValueError as e:
            logger.debug("%s(%s)", type(e).__name__, e)
            self.set_names_combo(0)

    def set_names_combo(self, val):
        """Set the names combo to val and emit the 'changed' signal.

        :param val: either an integer index or a string value in the combo

        If the model on the combo is None then this method will return
        and not emit the changed signal
        """
        combo = self.view.widgets.names_combo
        if combo.get_model() is None:
            self.view.set_sensitive('details_box', False)
            return
        if val is None:
            combo.set_active(-1)
        elif isinstance(val, int):
            combo.set_active(val)
        else:
            utils.combo_set_active_text(combo, val)

    def set_formatter_combo(self, val):
        """Set the formatter combo to val and emit the 'changed' signal.

        :param val: either an integer index or a string value in the combo
        """
        combo = self.view.widgets.formatter_combo
        if val is None:
            combo.set_active(-1)
            combo.emit('changed')
        elif isinstance(val, int):
            combo.set_active(val)
            combo.emit('changed')
        else:
            utils.combo_set_active_text(combo, val)

    @staticmethod
    def set_prefs_for(name, formatter_title, settings):
        """This will overwrite any other report settings with name"""
        formatters = prefs.prefs.get(CONFIG_LIST_PREF)
        if formatters is None:
            formatters = {}
        formatters[name] = formatter_title, settings
        prefs.prefs[CONFIG_LIST_PREF] = formatters

    def on_new_button_clicked(self, _button):
        text = '<b>' + _('Enter a name for the new formatter') + '</b>'
        dialog = utils.create_message_dialog(
            text,
            buttons=Gtk.ButtonsType.OK_CANCEL,
            parent=self.view.dialog,
            resizable=False
        )
        content_area_box = dialog.get_content_area()
        content_area_box.set_spacing(10)
        entry_box = Gtk.Box()
        entry = Gtk.Entry()
        dialog.set_response_sensitive(Gtk.ResponseType.OK, False)
        entry.get_style_context().add_class('problem')
        names_model = self.view.widgets.names_combo.get_model()

        def on_entry_changed(_entry):
            _name = entry.get_text()
            if _name == '' or (names_model is not None and
                               utils.tree_model_has(names_model, _name)):
                entry.get_style_context().add_class('problem')
                dialog.set_response_sensitive(Gtk.ResponseType.OK, False)
            else:
                entry.get_style_context().remove_class('problem')
                dialog.set_response_sensitive(Gtk.ResponseType.OK, True)

        entry.connect('changed', on_entry_changed)
        dialog.set_default_response(Gtk.ResponseType.OK)
        entry.set_activates_default(True)
        entry_box.pack_start(entry, True, True, 15)
        content_area_box.pack_start(entry_box, True, True, 5)
        dialog.show_all()
        entry.grab_focus()
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            name = entry.get_text()
            self.set_prefs_for(name, None, {})
            self.populate_names_combo()
            utils.combo_set_active_text(self.view.widgets.names_combo, name)
        dialog.destroy()

    def on_remove_button_clicked(self, _button):
        formatters = prefs.prefs.get(CONFIG_LIST_PREF, {})
        names_combo = self.view.widgets.names_combo
        name = names_combo.get_active_text()
        formatters.pop(name)
        prefs.prefs[CONFIG_LIST_PREF] = formatters
        self.populate_names_combo()
        names_combo.set_active(0)

    def on_names_combo_changed(self, combo):
        if combo.get_model() is None or combo.get_active() == -1:
            self.view.set_sensitive('details_box', False)
            return

        name = combo.get_active_text()
        formatters = prefs.prefs.get(CONFIG_LIST_PREF, {})
        self.view.set_sensitive('details_box', name is not None)
        # set the default to the new name
        prefs.prefs[DEFAULT_CONFIG_PREF] = name
        try:
            formatter_title, _settings = formatters.get(name)
        except (KeyError, TypeError) as e:
            logger.debug("%s(%s)", type(e).__name__, e)
            utils.message_dialog(
                _('%s does not exists in your preferences') % name
            )
            return

        try:
            self.set_formatter_combo(formatter_title)
        except ValueError as e:
            utils.message_dialog(
                _('%s does not exist, have you edited your preferences?') %
                name
            )
            logger.debug("%s(%s)", type(e).__name__, e)
            self.set_formatter_combo(-1)
        self.view.set_sensitive('details_box', True)

    def on_formatter_combo_changed(self, combo):
        """formatter_combo changed signal handler."""
        self.view.set_sensitive('ok_button', False)
        GLib.idle_add(self._formatter_combo_changed_idle, combo)

    def _formatter_combo_changed_idle(self, combo):
        formatter = combo.get_active_text()
        name = self.view.widgets.names_combo.get_active_text()
        _formatter_title, settings = (prefs.prefs
                                      .get(CONFIG_LIST_PREF, {})
                                      .get(name, (None, None)))
        if settings is None:
            return

        expander = self.view.widgets.settings_expander

        for child in expander.get_children():
            expander.remove(child)

        self.view.set_sensitive('ok_button', formatter is not None)
        if not formatter:
            self.view.resize()
            return

        cls = self.formatter_class_map.get(formatter)
        box = cls.get_settings_box() if cls else None
        if box:
            box.update(settings)
            expander.add(box)
            box.show_all()
        expander.set_sensitive(box is not None)
        # TODO: should probably remember expanded state,
        # see formatter_settings_expander_pref
        expander.set_expanded(box is not None)
        self.set_prefs_for(name, formatter, settings)
        self.view.set_sensitive('ok_button', True)
        self.view.resize()

    def init_formatter_combo(self):
        plugins = []
        for plug in pluginmgr.plugins.values():
            if isinstance(plug, FormatterPlugin):
                logger.debug('recognized %s as a FormatterPlugin', plug)
                plugins.append(plug)
            else:
                logger.debug('discarded %s: not a FormatterPlugin', plug)

        # should always have at least the default formatter
        if len(plugins) == 0:
            utils.message_dialog(_('No formatter plugins defined'),
                                 Gtk.MessageType.WARNING)
            return

        for item in plugins:
            title = item.title
            self.formatter_class_map[title] = item
            self.view.widgets.formatter_combo.append_text(title)

    def populate_names_combo(self):
        """Populate combo with the list of configuration names from prefs."""
        formatter = prefs.prefs.get(CONFIG_LIST_PREF)
        combo = self.view.widgets.names_combo
        if formatter is None:
            self.view.set_sensitive('details_box', False)
            combo.remove_all()
            return
        try:
            combo.remove_all()
            for cfg in formatter.keys():
                combo.append_text(cfg)
        except AttributeError as e:
            # no formatters
            logger.debug("%s(%s)", type(e).__name__, e)

    def init_names_combo(self):
        formatters = prefs.prefs.get(CONFIG_LIST_PREF)
        if not formatters:
            msg = _('No formatters found. To create a new formatter click '
                    'the "New" button.')
            utils.message_dialog(msg, parent=self.view.dialog)
            self.view.widgets.names_combo.remove_all()
        self.populate_names_combo()

    def save_formatter_settings(self):
        name = self.view.widgets.names_combo.get_active_text()
        formatters = prefs.prefs.get(CONFIG_LIST_PREF, {})
        formatter_title, _dummy_settings = formatters.get(name)
        box = self.view.widgets.settings_expander.get_child()
        formatters[name] = formatter_title, box.get_report_settings()
        prefs.prefs[CONFIG_LIST_PREF] = formatters

    def start(self):
        formatter = None
        settings = None
        response = self.view.start()
        if response == Gtk.ResponseType.OK:
            current = self.view.widgets.names_combo.get_active_text()
            prefs.prefs[DEFAULT_CONFIG_PREF] = current
            self.save_formatter_settings()
            name = self.view.widgets.names_combo.get_active_text()
            formatter_title, settings = prefs.prefs.get(CONFIG_LIST_PREF,
                                                        {}).get(name)
            formatter = self.formatter_class_map.get(formatter_title)
        self.view.disconnect_all()
        return formatter, settings


class ReportToolDialog:  # pylint: disable=too-few-public-methods

    def __init__(self):
        self.view = ReportToolDialogView()
        self.presenter = ReportToolDialogPresenter(self.view)

    def start(self):
        return self.presenter.start()


class ReportTool(pluginmgr.Tool):  # pylint: disable=too-few-public-methods

    category = _("Report")
    label = _("Generate Report")

    @classmethod
    def start(cls):
        # get the select results from the search view
        from bauble.view import SearchView
        view = bauble.gui.get_view()
        if not isinstance(view, SearchView):
            utils.message_dialog(_('Search for something first.'))
            return

        model = view.results_view.get_model()
        if model is None:
            utils.message_dialog(_('Search for something first.'))
            return

        bauble.gui.set_busy(True, 'not-allowed')
        okay = False
        try:
            while True:
                dialog = ReportToolDialog()
                formatter, settings = dialog.start()
                if formatter is None:
                    break
                okay = formatter.format([row[0] for row in model], **settings)
                if okay:
                    break
        except AssertionError as e:
            logger.debug("%s(%s)", type(e).__name__, e)
            logger.debug(traceback.format_exc())

            utils.message_details_dialog(utils.xml_safe(e),
                                         traceback.format_exc(),
                                         Gtk.MessageType.ERROR)
        except Exception as e:   # pylint: disable=broad-except
            logger.debug(traceback.format_exc())
            utils.message_details_dialog(_('Formatting Error\n\n%s') %
                                         utils.xml_safe(e),
                                         traceback.format_exc(),
                                         Gtk.MessageType.ERROR)
        bauble.gui.set_busy(False)
        return


class ReportToolPlugin(pluginmgr.Plugin):
    depends = ['PlantsPlugin', 'GardenPlugin', 'TagPlugin']
    tools = [ReportTool, TemplateDownloadTool]


# TODO: should be able to drop in a new formatter plugin and have it
# automatically detected, right now they are just returned in the plugin()
# function

def plugin():
    from .xsl import XSLFormatterPlugin, _fop
    from .mako import MakoFormatterPlugin
    plugins = [ReportToolPlugin, MakoFormatterPlugin]
    if _fop.set_fop_command():
        plugins.append(XSLFormatterPlugin)
    return plugins
