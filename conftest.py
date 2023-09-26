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
"""
Global hooks, etc. for pytest.
"""
import shutil
import sys

from bauble import paths

# don't cache .pyc files (can cause failures on second etc. run)
sys.dont_write_bytecode = True


def pytest_sessionfinish(session, exitstatus):
    # pylint: disable=unused-argument
    """Called after all test have finished."""
    print()
    print(f"==sessionfinish== removing tempdir at {paths.TEMPDIR}")
    # Clean up tempfiles
    shutil.rmtree(paths.TEMPDIR)
