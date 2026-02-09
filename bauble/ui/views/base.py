# Copyright 2008-2010 Brett Adams
# Copyright 2015 Mario Frasca <mario@anche.no>.
# Copyright 2021-2026 Ross Demuth <rossdemuth123@gmail.com>
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
View base components
"""
from typing import Protocol


class ViewThread(Protocol):
    def cancel(self) -> None: ...
    def join(self) -> None: ...
    def start(self) -> None: ...


class View:
    """If a class extends this View it will most likely also inherit from
    Gtk.Box and should call this __init__.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.running_threads: list[ViewThread] = []
        self.prevent_threads = False

    def cancel_threads(self) -> None:
        for thread in self.running_threads:
            thread.cancel()

        for thread in self.running_threads:
            thread.join()

        self.running_threads = []

    def start_thread(self, thread: ViewThread) -> ViewThread:
        self.running_threads.append(thread)
        thread.start()

        if self.prevent_threads:
            self.cancel_threads()

        return thread

    def update(self, *args: str | None) -> None:
        raise NotImplementedError
