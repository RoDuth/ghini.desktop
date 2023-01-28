# Copyright (c) 2005,2006,2007,2008,2009 Brett Adams <brett@belizebotanic.org>
# Copyright (c) 2012-2015 Mario Frasca <mario@anche.no>
# Copyright (c) 2020-2022 Ross Demuth <rossdemuth123@gmail.com>
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
# task.py
"""
The bauble.task module allows you to queue up long running tasks. The
running tasks still block but allows the GUI to update.
"""

import logging
logger = logging.getLogger(__name__)

from gi.repository import Gtk  # noqa

import bauble

# TODO: provide a way to create background tasks that don't call set_busy()

__running = False
__kill = False
__message_ids = None


def running():
    """Return True/False if a task is running."""
    return __running


def kill():
    """Kill the current task.

    This will kill the task when it goes idle and not while it's
    running.  A task is idle after it yields.
    """
    global __kill
    __kill = True


def _idle():
    """Called when a task is idle."""
    while Gtk.events_pending():
        Gtk.main_iteration_do(blocking=False)

    global __kill
    if __kill:
        __kill = False
        raise StopIteration()


def _yielding_queue(task):
    """Run a blocking task that must occasionally update the UI.

    This version will yield the results and is essentially just a copy of
    `queue` that yields instead of running to exhaustion. It is intended to be
    returned from `queue`.
    """
    if bauble.gui is not None:
        bauble.gui.set_busy(True)
        bauble.gui.progressbar.show()
        bauble.gui.progressbar.set_pulse_step(1.0)
        bauble.gui.progressbar.set_fraction(0)
    global __running
    __running = True
    try:
        while True:
            try:
                _idle()
                yield next(task)
            except StopIteration:
                break
        __running = False
    except Exception as e:
        logger.debug('%s(%s)', type(e).__name__, e)
        raise
    finally:
        __running = False
        if bauble.gui is not None:
            bauble.gui.progressbar.set_pulse_step(0)
            bauble.gui.progressbar.set_fraction(0)
            bauble.gui.progressbar.hide()
            bauble.gui.set_busy(False)
        clear_messages()


def queue(task, yielding=False):
    """Run a blocking task that must occasionally update the UI.

    Task should be a generator with UI side effects. It does not matter what it
    yields only that it does yield from time to time to allow updating the UI.
    """
    if yielding:
        return _yielding_queue(task)

    if bauble.gui is not None:
        bauble.gui.set_busy(True)
        bauble.gui.progressbar.show()
        bauble.gui.progressbar.set_pulse_step(1.0)
        bauble.gui.progressbar.set_fraction(0)
    global __running
    __running = True
    try:
        while True:
            try:
                _idle()
                next(task)
            except StopIteration:
                break
        __running = False
    except Exception as e:
        logger.debug('%s(%s)', type(e).__name__, e)
        raise
    finally:
        __running = False
        if bauble.gui is not None:
            bauble.gui.progressbar.set_pulse_step(0)
            bauble.gui.progressbar.set_fraction(0)
            bauble.gui.progressbar.hide()
            bauble.gui.set_busy(False)
        clear_messages()


__message_ids = []

_context_id = None


def set_message(msg):
    """A convenience function for setting a message on the statusbar.

    Returns the message id
    """
    if bauble.gui is None or bauble.gui.widgets is None:
        return
    global _context_id
    if not _context_id:
        _context_id = bauble.gui.widgets.statusbar.get_context_id('__task')
        logger.info("new context id: %s", _context_id)
    msg_id = bauble.gui.widgets.statusbar.push(_context_id, msg)
    __message_ids.append(msg_id)
    return msg_id


def clear_messages():
    """Clear all the messages from the statusbar that were set with
    :func:`bauble.task.set_message`
    """
    if bauble.gui is None or bauble.gui.widgets is None \
            or bauble.gui.widgets.statusbar is None:
        return
    for mid in __message_ids:
        bauble.gui.widgets.statusbar.remove(_context_id, mid)
