# Copyright (c) 2005,2006,2007,2008,2009 Brett Adams <brett@belizebotanic.org>
# Copyright (c) 2012-2016 Mario Frasca <mario@anche.no>
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
#
"""
Description: test the ABCD (Access to Biological Collection Data) plugin
"""
import os
import tempfile
from unittest import mock

from lxml import etree

import bauble.plugins.garden.test_garden as garden_test

# from bauble.plugins.garden import Plant, Accession
import bauble.plugins.plants.test_plants as plants_test
from bauble.plugins import abcd
from bauble.test import BaubleTestCase

# TODO: the ABCD tests need to be completely reworked


class ABCDTestCase(BaubleTestCase):
    def __init__(self, *args):
        super().__init__(*args)

    def setUp(self):
        super().setUp()
        plants_test.setUp_data()
        garden_test.setUp_data()

    @mock.patch("bauble.utils.message_dialog")
    def test_export(self, mock_dialog):
        """Test the ABCDExporter.  If message_dialog is called fail. i.e.
        validation fails
        """
        handle, filename = tempfile.mkstemp()
        abcd.ABCDExporter().start(filename)
        mock_dialog.assert_not_called()
        os.close(handle)
