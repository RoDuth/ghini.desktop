# Copyright (c) 2022 Ross Demuth <rossdemuth123@gmail.com>
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
import shutil
from bauble import paths


def pytest_sessionstart(session):
    """Called before test."""
    # Note this doesn't print with `pytest --cov=bauble`, haven't investigated
    print(f'==sessionstart== tempdir: {paths.TEMPDIR}')


def pytest_sessionfinish(session, exitstatus):
    """Called after all test have finished."""
    # Clean up tempfiles
    print(f'===sessionfinish== removing tempdir at {paths.TEMPDIR}')
    shutil.rmtree(paths.TEMPDIR)
